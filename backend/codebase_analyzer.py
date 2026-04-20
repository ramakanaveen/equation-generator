"""
Codebase analyzer for codegen.py.

Architecture: 3 parallel Explorer subagents + 1 Synthesizer (Claude Code Ultra pattern).

  Phase 1 (Python):  type index + bootstrap context built in parallel (~1s)
  Phase 2 (Claude):  3 explorers run simultaneously via asyncio.gather()
                       Explorer 1 — base interfaces / abstract classes
                       Explorer 2 — concrete implementations (the pattern to follow)
                       Explorer 3 — build constraints + package conventions
  Phase 3 (Claude):  synthesizer merges reports → CodebaseProfile
                     (has ask_followup_question if info is missing)

KV cache means 3 parallel explorers cost almost the same as 1 sequential pass.
Each explorer gets a focused slice of the type index — not the full dump.
"""
import asyncio
import fnmatch
import json
import os
import re
import sys

from generator import _call_with_continuation

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILES_PER_EXPLORER = 8   # per subagent
MAX_TURNS_EXPLORER = 7       # per subagent
MAX_TURNS_SYNTH = 5
BOOTSTRAP_CAP = 6000

# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def _safe_path(requested: str, root: str) -> str:
    root_real = os.path.realpath(root)
    resolved = os.path.realpath(
        requested if os.path.isabs(requested) else os.path.join(root, requested)
    )
    if resolved != root_real and not resolved.startswith(root_real + os.sep):
        raise ValueError(f"Path outside codebase root: {requested!r}")
    return resolved

# ---------------------------------------------------------------------------
# Type index  (fast Python regex scan — no Claude calls)
# ---------------------------------------------------------------------------

_PACKAGE_RE = re.compile(r'^\s*package\s+([\w.]+)\s*;', re.MULTILINE)
_TYPE_RE = re.compile(
    r'(?:public\s+)?(?:(abstract)\s+)?(class|interface|enum)\s+(\w+)'
    r'(?:\s+extends\s+([\w.<>, ]+?))?'
    r'(?:\s+implements\s+([\w.<>, ]+?))?'
    r'\s*[{<]',
    re.MULTILINE,
)
_METHOD_RE = re.compile(r'(?:public|protected)\s+[\w<>\[\].,? ]+\s+(\w+)\s*\(', re.MULTILINE)


def _build_type_index(root_path: str) -> dict:
    index: dict = {}
    root_real = os.path.realpath(root_path)
    for dirpath, _, filenames in os.walk(root_path):
        for fname in filenames:
            if not fname.endswith('.java'):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, encoding='utf-8', errors='replace') as f:
                    src = f.read()
            except (IOError, OSError):
                continue
            pkg_m = _PACKAGE_RE.search(src)
            package = pkg_m.group(1) if pkg_m else ''
            for m in _TYPE_RE.finditer(src):
                abstract_flag, kind, name, extends_raw, implements_raw = m.groups()
                if abstract_flag:
                    kind = 'abstract class'
                fqn = f'{package}.{name}' if package else name
                index[fqn] = {
                    'file': os.path.relpath(fpath, root_real),
                    'kind': kind,
                    'extends': [e.strip() for e in extends_raw.split(',')] if extends_raw else [],
                    'implements': [i.strip() for i in implements_raw.split(',')] if implements_raw else [],
                    'methods': list(dict.fromkeys(_METHOD_RE.findall(src)))[:20],
                    'package': package,
                }
    return index


def _bootstrap_context(root_path: str) -> str:
    parts = []
    for fname in ['CLAUDE.md', 'README.md', 'README.rst', 'pom.xml', 'build.gradle', 'build.gradle.kts']:
        fpath = os.path.join(root_path, fname)
        if os.path.isfile(fpath):
            try:
                with open(fpath, encoding='utf-8', errors='replace') as f:
                    content = f.read(BOOTSTRAP_CAP)
                parts.append(f'=== {fname} ===\n{content}')
            except (IOError, OSError):
                pass
    return '\n\n'.join(parts) or '(No CLAUDE.md, README, or build manifest found at root)'

# ---------------------------------------------------------------------------
# Tool implementations  (shared across all subagents)
# ---------------------------------------------------------------------------

def _tool_glob(pattern: str, root: str) -> str:
    root_real = os.path.realpath(root)
    matches = []
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            rel = os.path.relpath(fpath, root_real).replace(os.sep, '/')
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(fname, pattern.split('/')[-1]):
                matches.append(rel)
            if len(matches) >= 100:
                return json.dumps(sorted(matches)) + '\n[truncated at 100]'
    return json.dumps(sorted(matches)) if matches else '[]'


def _tool_read_file(inputs: dict, root: str, counter: list) -> str:
    limit = MAX_FILES_PER_EXPLORER
    if counter[0] >= limit:
        return f'[File read limit ({limit}) reached — output your findings now]'
    try:
        path = _safe_path(inputs['path'], root)
    except ValueError as e:
        return f'[Error: {e}]'
    if not os.path.isfile(path):
        return f'[Not a file: {inputs["path"]!r}]'
    start = inputs.get('start_line')
    end = inputs.get('end_line')
    max_lines = int(inputs.get('max_lines', 200))
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        if start is not None:
            s = max(0, int(start) - 1)
            e = int(end) if end is not None else s + max_lines
            result = ''.join(lines[s:e])
        else:
            result = ''.join(lines[:max_lines])
        counter[0] += 1
        return result
    except (IOError, OSError) as ex:
        return f'[Error: {ex}]'


def _tool_search_code(inputs: dict, root: str) -> str:
    try:
        directory = _safe_path(inputs.get('directory', root), root)
    except ValueError as e:
        return f'[Error: {e}]'
    pattern = inputs.get('pattern', '')
    ext = inputs.get('file_ext', '.java')
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f'[Invalid regex: {e}]'
    root_real = os.path.realpath(root)
    results = []
    for dirpath, _, filenames in os.walk(directory):
        for fname in filenames:
            if not fname.endswith(ext):
                continue
            fpath = os.path.join(dirpath, fname)
            rel = os.path.relpath(fpath, root_real)
            try:
                with open(fpath, encoding='utf-8', errors='replace') as f:
                    for lineno, line in enumerate(f, 1):
                        if regex.search(line):
                            results.append(f'{rel}:{lineno}: {line.rstrip()}')
                            if len(results) >= 40:
                                return '\n'.join(results) + '\n[truncated at 40]'
            except (IOError, OSError):
                pass
    return '\n'.join(results) if results else f'[No matches for {pattern!r}]'


def _tool_ask_followup_question(inputs: dict) -> str:
    question = inputs.get('question', '')
    options = inputs.get('options', [])
    print('\n', file=sys.stderr)
    print('┌─ Codebase analysis needs your input ──────────────────────', file=sys.stderr)
    print(f'│  {question}', file=sys.stderr)
    for i, opt in enumerate(options, 1):
        print(f'│  {i}. {opt}', file=sys.stderr)
    print('│', file=sys.stderr)
    print('│  Enter number or answer (Enter = let Claude decide): ',
          end='', file=sys.stderr, flush=True)
    try:
        raw = (open('/dev/tty').readline() if not sys.stdin.isatty() else sys.stdin.readline()).strip()
    except (OSError, EOFError):
        print('\n[Non-interactive — Claude will use best judgment]', file=sys.stderr)
        return 'Non-interactive. Use your best judgment from what you found.'
    print('└────────────────────────────────────────────────────────────', file=sys.stderr)
    if not raw:
        return 'Use your best judgment based on what you found.'
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx]
    return raw


def _execute_tool(name: str, inputs: dict, root: str | None, counter: list | None) -> str:
    if name == 'glob' and root:
        return _tool_glob(inputs.get('pattern', '**/*'), root)
    elif name == 'read_file' and root and counter is not None:
        return _tool_read_file(inputs, root, counter)
    elif name == 'search_code' and root:
        return _tool_search_code(inputs, root)
    elif name == 'ask_followup_question':
        return _tool_ask_followup_question(inputs)
    return f'[Unknown tool: {name!r}]'

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_EXPLORER_TOOLS = [
    {
        'name': 'glob',
        'description': 'Find files matching a glob pattern (e.g. "**/*.java", "pom.xml"). Returns sorted paths.',
        'input_schema': {
            'type': 'object',
            'properties': {'pattern': {'type': 'string'}},
            'required': ['pattern'],
        },
    },
    {
        'name': 'read_file',
        'description': 'Read a file. Use start_line/end_line for large files.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'path': {'type': 'string'},
                'start_line': {'type': 'integer'},
                'end_line': {'type': 'integer'},
                'max_lines': {'type': 'integer', 'default': 200},
            },
            'required': ['path'],
        },
    },
    {
        'name': 'search_code',
        'description': 'Regex search across files. Returns up to 40 matching lines with file:line context.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'directory': {'type': 'string'},
                'pattern': {'type': 'string'},
                'file_ext': {'type': 'string', 'default': '.java'},
            },
            'required': ['directory', 'pattern'],
        },
    },
]

_SYNTHESIZER_TOOLS = [
    {
        'name': 'ask_followup_question',
        'description': (
            'Ask the user when critical information is missing after reading all explorer reports. '
            'Use when: no base interface found, multiple equally plausible candidates, package unclear. '
            'Always include specific options derived from the reports.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'question': {'type': 'string'},
                'options': {'type': 'array', 'items': {'type': 'string'}},
            },
            'required': ['question', 'options'],
        },
    },
]

# ---------------------------------------------------------------------------
# Generic explorer loop
# ---------------------------------------------------------------------------

async def _run_explorer(
    name: str,
    system: str,
    initial_msg: str,
    root_path: str,
    client,
    model: str,
    cfg,
    progress_cb=None,
) -> str:
    """Single explorer subagent. Returns its report as a string."""
    messages = [{'role': 'user', 'content': initial_msg}]
    files_read = [0]

    for _ in range(MAX_TURNS_EXPLORER):
        try:
            response = await asyncio.to_thread(
                client.messages.create,
                model=model,
                max_tokens=8192,
                thinking={'type': 'enabled', 'budget_tokens': 5000},
                tools=_EXPLORER_TOOLS,
                system=system,
                messages=messages,
            )
        except Exception:
            response = await asyncio.to_thread(
                client.messages.create,
                model=model,
                max_tokens=cfg.max_tokens,
                tools=_EXPLORER_TOOLS,
                system=system,
                messages=messages,
            )

        tool_uses = [b for b in response.content if b.type == 'tool_use']
        text_blocks = [b for b in response.content if b.type == 'text']

        if response.stop_reason == 'end_turn' or not tool_uses:
            report = '\n'.join(b.text for b in text_blocks).strip()
            if progress_cb:
                progress_cb(f'[{name}: done]\n')
            return report or f'[{name}: no findings]'

        messages.append({'role': 'assistant', 'content': response.content})
        results = []
        for tu in tool_uses:
            if progress_cb:
                progress_cb(f'  [{name}] {tu.name}({json.dumps(tu.input, separators=(",", ":"))}) \n')
            output = _execute_tool(tu.name, tu.input, root_path, files_read)
            results.append({'type': 'tool_result', 'tool_use_id': tu.id, 'content': output})
        messages.append({'role': 'user', 'content': results})

    return f'[{name}: max turns reached]'

# ---------------------------------------------------------------------------
# The 3 Explorer subagents
# ---------------------------------------------------------------------------

_SYSTEM_EXPLORER_1 = """\
You are Explorer 1. Your only job: find the base interface or abstract class \
that new signal/computation classes should implement or extend in this codebase.

Equation being implemented: {equation_text}

You have a filtered type index showing only interfaces and abstract classes.
Use it to identify the 1-2 strongest candidates (look for types that many concrete \
classes implement/extend). Then read_file to confirm their full method signatures.

Report format:
## Base Type Found
Name: ...
File: ...
Full source:
(paste full class/interface source)

## Why This Is The Right Base Type
(brief reasoning)

Stop as soon as you have confirmed the best candidate. Max {max_files} file reads."""

_SYSTEM_EXPLORER_2 = """\
You are Explorer 2. Your only job: find one concrete class that shows the exact \
implementation pattern for signal/computation classes in this codebase.

Equation being implemented: {equation_text}

You have a filtered type index showing concrete classes that implement or extend something.
Find one that looks like a signal or computation class. Read it — focus on:
- the class declaration line (what it extends/implements)
- the key computation method (~30-50 lines)
- any annotations

Report format:
## Example Implementation Found
File: ...
Package: ...
Pattern (key parts only):
(paste relevant code)

## Observations
(naming conventions, any annotations, constructor pattern)

Stop after reading 1-2 files. Max {max_files} file reads."""

_SYSTEM_EXPLORER_3 = """\
You are Explorer 3. Your only job: determine build constraints and the correct \
package for new signal classes in this codebase.

You have the project's bootstrap context (CLAUDE.md, README, build manifest).
You may also read_file additional config files if needed.

Report format:
## Build Constraints
Java version: ...
Build system: ...
Key dependencies: ...

## Package for New Classes
(exact package name, e.g. com.example.signals)

## Project Rules
(from CLAUDE.md or README — any instructions about where to place new files, \
naming conventions, required annotations)

Stop as soon as you have the package and build info. Max {max_files} file reads."""

_SYSTEM_SYNTHESIZER = """\
You are the Synthesizer. Three parallel explorer subagents have reported back. \
Your job: merge their findings into a single coherent CodebaseProfile.

Equation to implement: {equation_text}

If critical information is missing (especially Base Interface or Package), \
use ask_followup_question with specific options from the reports before outputting the profile.

Output this exact format:

## Build Constraints
(Java version, build system, key deps)

## Package
(exact package for the new class)

## Base Interface / Abstract Class
(full source of the type to implement/extend)

## Required Imports
(all import statements the generated class needs)

## Lifecycle Contract
(annotations, constructor args, init/shutdown; "none" if simple)

## Implementation Pattern
(~60 lines from Explorer 2's example — the exact pattern)

## Codebase Rules
(from Explorer 3 + any other rules discovered)"""

# ---------------------------------------------------------------------------
# Synthesizer
# ---------------------------------------------------------------------------

async def _synthesize(
    reports: list[str],
    equation_text: str,
    client,
    model: str,
    cfg,
    progress_cb=None,
) -> str:
    r1, r2, r3 = reports
    user_content = (
        f'Explorer 1 report (Base Types):\n{r1}\n\n'
        f'Explorer 2 report (Implementations):\n{r2}\n\n'
        f'Explorer 3 report (Build + Conventions):\n{r3}'
    )
    messages = [{'role': 'user', 'content': user_content}]
    system = _SYSTEM_SYNTHESIZER.format(equation_text=equation_text)

    if progress_cb:
        progress_cb('[Synthesizer: merging reports]\n')

    for _ in range(MAX_TURNS_SYNTH):
        response = await asyncio.to_thread(
            client.messages.create,
            model=model,
            max_tokens=cfg.max_tokens,
            tools=_SYNTHESIZER_TOOLS,
            system=system,
            messages=messages,
        )

        tool_uses = [b for b in response.content if b.type == 'tool_use']
        text_blocks = [b for b in response.content if b.type == 'text']

        for block in text_blocks:
            if progress_cb and block.text:
                progress_cb(block.text)

        if response.stop_reason == 'end_turn' or not tool_uses:
            return '\n'.join(b.text for b in text_blocks).strip() or '[No profile produced]'

        messages.append({'role': 'assistant', 'content': response.content})
        results = []
        for tu in tool_uses:
            output = _execute_tool(tu.name, tu.input, None, None)
            results.append({'type': 'tool_result', 'tool_use_id': tu.id, 'content': output})
        messages.append({'role': 'user', 'content': results})

    return '[Synthesis incomplete — max turns reached]'

# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

async def analyze_codebase(
    root_path: str,
    equation_text: str,
    client,
    model: str,
    cfg,
    progress_cb=None,
) -> str:
    """
    Analyze a Java codebase using 3 parallel explorer subagents + 1 synthesizer.
    Returns CodebaseProfile markdown string.
    """
    root_path = os.path.realpath(root_path)
    if not os.path.isdir(root_path):
        raise ValueError(f'Not a directory: {root_path}')

    # Phase 1: Python pre-processing (parallel, fast)
    index, bootstrap = await asyncio.gather(
        asyncio.to_thread(_build_type_index, root_path),
        asyncio.to_thread(_bootstrap_context, root_path),
    )
    if progress_cb:
        progress_cb(f'[Type index: {len(index)} classes | Launching 3 parallel explorers]\n')

    # Split type index for focused context per explorer
    base_types = {k: v for k, v in index.items() if v['kind'] in ('interface', 'abstract class')}
    concrete = {k: v for k, v in index.items()
                if v['kind'] not in ('interface', 'abstract class')
                and (v['implements'] or v['extends'])}

    # Phase 2: 3 explorers in parallel
    r1, r2, r3 = await asyncio.gather(
        _run_explorer(
            name='Explorer-1 (Base Types)',
            system=_SYSTEM_EXPLORER_1.format(equation_text=equation_text, max_files=MAX_FILES_PER_EXPLORER),
            initial_msg=f'Base type index ({len(base_types)} entries):\n{json.dumps(base_types, indent=2)}',
            root_path=root_path,
            client=client, model=model, cfg=cfg,
            progress_cb=progress_cb,
        ),
        _run_explorer(
            name='Explorer-2 (Implementations)',
            system=_SYSTEM_EXPLORER_2.format(equation_text=equation_text, max_files=MAX_FILES_PER_EXPLORER),
            initial_msg=f'Concrete class index ({len(concrete)} entries):\n{json.dumps(concrete, indent=2)}',
            root_path=root_path,
            client=client, model=model, cfg=cfg,
            progress_cb=progress_cb,
        ),
        _run_explorer(
            name='Explorer-3 (Build + Conventions)',
            system=_SYSTEM_EXPLORER_3.format(max_files=MAX_FILES_PER_EXPLORER),
            initial_msg=f'Bootstrap context:\n{bootstrap}',
            root_path=root_path,
            client=client, model=model, cfg=cfg,
            progress_cb=progress_cb,
        ),
    )

    # Phase 3: Synthesize
    return await _synthesize([r1, r2, r3], equation_text, client, model, cfg, progress_cb)

# ---------------------------------------------------------------------------
# Verification  (unchanged)
# ---------------------------------------------------------------------------

_VERIFY_SYSTEM = """\
You are a Java code reviewer. Check the generated code against the codebase profile.

Verify:
1. Implements/extends the correct base type from the profile
2. All abstract methods are implemented
3. All Required Imports are present
4. Lifecycle Contract is honoured (annotations, constructor, lifecycle methods)
5. Package declaration matches the profile
6. No NaN returned anywhere (0.0 must be the fallback)

If correct, output exactly: VERIFIED
If there are issues, output the COMPLETE corrected code with === FILE: Name.java === delimiters.
Fix ALL issues. Output code only."""


async def verify_generated_code(
    code: str,
    profile: str,
    client,
    model: str,
    cfg,
) -> str | None:
    messages = [{
        'role': 'user',
        'content': f'## Codebase Profile\n\n{profile}\n\n## Generated Code\n\n{code}',
    }]
    result = ''
    async for chunk in _call_with_continuation(_VERIFY_SYSTEM, messages, cfg, client, model):
        result += chunk
    stripped = result.strip()
    return None if stripped == 'VERIFIED' else (stripped or None)
