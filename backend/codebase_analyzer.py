"""
Codebase analyzer for codegen.py.

Three-phase approach (Claude Code + OpenCode + DeepCode research):
  1. Type index  — regex scan all .java files -> structural map (fast, ~1s for 10K files)
  2. Bootstrap   — CLAUDE.md + README + build manifest read first
  3. Agentic loop — Claude explores with glob/read_file/search_code + extended thinking
                    -> CodebaseProfile markdown

No hardcoded naming patterns. Claude navigates based on the equation being implemented.
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

MAX_FILES = 15        # read_file calls permitted per analysis run
MAX_TURNS = 12        # agentic loop turn cap
BOOTSTRAP_CAP = 6000  # chars per bootstrap file

# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def _safe_path(requested: str, root: str) -> str:
    """Resolve requested path and verify it stays within root. Raises ValueError if not."""
    root_real = os.path.realpath(root)
    if os.path.isabs(requested):
        resolved = os.path.realpath(requested)
    else:
        resolved = os.path.realpath(os.path.join(root, requested))
    if resolved != root_real and not resolved.startswith(root_real + os.sep):
        raise ValueError(f"Path outside codebase root: {requested!r}")
    return resolved

# ---------------------------------------------------------------------------
# Type index
# ---------------------------------------------------------------------------

_PACKAGE_RE = re.compile(r'^\s*package\s+([\w.]+)\s*;', re.MULTILINE)
_TYPE_RE = re.compile(
    r'(?:public\s+)?(?:(abstract)\s+)?(?:(class|interface|enum))\s+(\w+)'
    r'(?:\s+extends\s+([\w.<>, ]+?))?'
    r'(?:\s+implements\s+([\w.<>, ]+?))?'
    r'\s*[{<]',
    re.MULTILINE,
)
_METHOD_RE = re.compile(r'(?:public|protected)\s+[\w<>\[\].,? ]+\s+(\w+)\s*\(', re.MULTILINE)


def _build_type_index(root_path: str) -> dict:
    """
    Regex-scan all .java files under root_path.
    Returns {FQN: {file, kind, extends, implements, methods, package}}.
    Runs in a thread. Fast even at 10,000 files — no Claude calls, no file buffering.
    """
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
                extends = [e.strip() for e in extends_raw.split(',')] if extends_raw else []
                implements = [i.strip() for i in implements_raw.split(',')] if implements_raw else []
                methods = list(dict.fromkeys(_METHOD_RE.findall(src)))[:20]
                index[fqn] = {
                    'file': os.path.relpath(fpath, root_real),
                    'kind': kind,
                    'extends': extends,
                    'implements': implements,
                    'methods': methods,
                    'package': package,
                }
    return index

# ---------------------------------------------------------------------------
# Context bootstrap
# ---------------------------------------------------------------------------

def _bootstrap_context(root_path: str) -> str:
    """Read CLAUDE.md, README.md, and build manifests from root (capped at BOOTSTRAP_CAP each)."""
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
# Tool implementations
# ---------------------------------------------------------------------------

def _tool_glob(pattern: str, root: str) -> str:
    root_real = os.path.realpath(root)
    matches = []
    base_pattern = pattern.split('/')[-1] if '/' in pattern else pattern
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            rel = os.path.relpath(fpath, root_real)
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel.replace(os.sep, '/'), pattern):
                matches.append(rel)
            elif '**' not in pattern and fnmatch.fnmatch(fname, base_pattern):
                matches.append(rel)
            if len(matches) >= 100:
                return json.dumps(sorted(matches)) + '\n[truncated at 100]'
    return json.dumps(sorted(matches)) if matches else '[]'


def _tool_read_file(inputs: dict, root: str, counter: list) -> str:
    if counter[0] >= MAX_FILES:
        return f'[File read limit ({MAX_FILES}) reached — stop reading and output the profile]'
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
    """
    Prompt the user on the terminal. Uses /dev/tty when stdin is a pipe
    so it works even in `eqgen.py | codegen.py --codebase ...` pipelines.
    """
    question = inputs.get('question', '')
    options = inputs.get('options', [])

    print('\n', file=sys.stderr)
    print('┌─ Codebase analysis needs your input ──────────────────────', file=sys.stderr)
    print(f'│  {question}', file=sys.stderr)
    if options:
        for i, opt in enumerate(options, 1):
            print(f'│  {i}. {opt}', file=sys.stderr)
    print('│', file=sys.stderr)
    print('│  Enter a number, type your answer, or press Enter to let Claude decide: ',
          end='', file=sys.stderr, flush=True)

    try:
        if not sys.stdin.isatty():
            with open('/dev/tty') as tty:
                raw = tty.readline().strip()
        else:
            raw = sys.stdin.readline().strip()
    except (OSError, EOFError):
        print('\n[Non-interactive — Claude will use best judgment]', file=sys.stderr)
        return 'Non-interactive environment. Use your best judgment based on what you found.'

    print('└────────────────────────────────────────────────────────────', file=sys.stderr)

    if not raw:
        return 'Use your best judgment based on what you found.'
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx]
    return raw


def _execute_tool(name: str, inputs: dict, root: str, counter: list) -> str:
    if name == 'glob':
        return _tool_glob(inputs.get('pattern', '**/*'), root)
    elif name == 'read_file':
        return _tool_read_file(inputs, root, counter)
    elif name == 'search_code':
        return _tool_search_code(inputs, root)
    elif name == 'ask_followup_question':
        return _tool_ask_followup_question(inputs)
    return f'[Unknown tool: {name!r}]'

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

TOOLS = [
    {
        'name': 'glob',
        'description': (
            'Find files matching a glob pattern. '
            'Examples: "**/*.java", "pom.xml", "**/CLAUDE.md", "src/**/*Base*.java". '
            'Returns sorted list of matching relative paths.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'pattern': {'type': 'string'},
            },
            'required': ['pattern'],
        },
    },
    {
        'name': 'read_file',
        'description': (
            'Read a file. Use start_line/end_line to read specific sections of large files '
            '(e.g. start_line=1, end_line=80 for the class declaration).'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'path': {'type': 'string', 'description': 'Relative path from codebase root'},
                'start_line': {'type': 'integer', 'description': '1-indexed first line (optional)'},
                'end_line': {'type': 'integer', 'description': 'Last line inclusive (optional)'},
                'max_lines': {'type': 'integer', 'default': 200},
            },
            'required': ['path'],
        },
    },
    {
        'name': 'search_code',
        'description': (
            'Regex search across files. '
            'Returns up to 40 matching lines with file:line context. '
            'Use this to find which classes implement an interface or extend a base class.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'directory': {'type': 'string', 'description': 'Directory to search (relative to root)'},
                'pattern': {'type': 'string', 'description': 'Regex pattern'},
                'file_ext': {'type': 'string', 'default': '.java'},
            },
            'required': ['directory', 'pattern'],
        },
    },
    {
        'name': 'ask_followup_question',
        'description': (
            'Ask the user a targeted question when the codebase cannot provide the answer. '
            'Use this when: (1) no base interface or abstract class can be identified, '
            '(2) multiple equally plausible candidates exist and you cannot determine the right one, '
            '(3) the package for the new class is unclear. '
            'Always include specific options derived from what you found — never ask open-ended questions.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'question': {'type': 'string', 'description': 'A specific, targeted question for the user'},
                'options': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Concrete options for the user to choose from (derived from type index findings)',
                },
            },
            'required': ['question', 'options'],
        },
    },
]

# ---------------------------------------------------------------------------
# Analysis system prompt
# ---------------------------------------------------------------------------

_ANALYSIS_SYSTEM = """\
You are analyzing a Java codebase to generate a new class that integrates correctly.

The alpha trading equation to implement:
{equation_text}

You have:
- Bootstrap context (CLAUDE.md, README, build manifest) — read this first
- A type index of ALL Java classes/interfaces

Strategy — follow in order, stop as soon as you have enough:
1. Read the bootstrap context to understand the architecture
2. Examine the type index: find interfaces/abstract classes that appear to be base types
   for computation (look for types that many other classes implement or extend)
3. glob or read_file the 1-2 best candidates — confirm their method signatures
4. search_code to find one concrete class that uses that base type
5. read_file that class (use start_line/end_line for large files — the class declaration + key methods are enough)
6. Stop. Output the CodebaseProfile.

Do not read more than {max_files} files total. Do not assume naming conventions.

When to use ask_followup_question:
- No base interface or abstract class can be identified after exploring the type index
- Multiple equally plausible candidates exist (present them as options)
- The correct package for the new class is ambiguous
Always include specific options from what you found — never ask open-ended questions.

Output (produce this when done):

## Build Constraints
(Java version, build system, key dependencies from pom.xml/build.gradle)

## Package
(exact package for the new class)

## Base Interface / Abstract Class
(full source of the type to implement/extend — all method signatures)

## Required Imports
(all import statements the generated class will need)

## Lifecycle Contract
(annotations required, constructor parameters, init/shutdown methods if any; "none" if simple)

## Implementation Pattern
(~60 lines from one real implementation — the exact pattern to follow)

## Codebase Rules
(any project-specific rules discovered during exploration)
"""

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
    Analyze a Java codebase and produce a CodebaseProfile for code generation.
    Returns profile markdown string.
    progress_cb(text) is called with streaming progress (stderr-suitable).
    """
    root_path = os.path.realpath(root_path)
    if not os.path.isdir(root_path):
        raise ValueError(f'Not a directory: {root_path}')

    # Phase 1a+1b: build type index and bootstrap context in parallel
    index, bootstrap = await asyncio.gather(
        asyncio.to_thread(_build_type_index, root_path),
        asyncio.to_thread(_bootstrap_context, root_path),
    )
    if progress_cb:
        progress_cb(f'[Type index: {len(index)} classes scanned]\n')

    # Initial context message
    initial = (
        f'Bootstrap context:\n{bootstrap}\n\n'
        f'Type index ({len(index)} classes):\n'
        f'{json.dumps(index, indent=2)}'
    )
    messages = [{'role': 'user', 'content': initial}]
    system = _ANALYSIS_SYSTEM.format(equation_text=equation_text, max_files=MAX_FILES)
    files_read = [0]

    for _ in range(MAX_TURNS):
        # Try with extended thinking first; fall back without if unsupported
        try:
            response = await asyncio.to_thread(
                client.messages.create,
                model=model,
                max_tokens=16000,
                thinking={'type': 'enabled', 'budget_tokens': 10000},
                tools=TOOLS,
                system=system,
                messages=messages,
            )
        except Exception:
            response = await asyncio.to_thread(
                client.messages.create,
                model=model,
                max_tokens=cfg.max_tokens,
                tools=TOOLS,
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

        # Execute tools and continue
        messages.append({'role': 'assistant', 'content': response.content})
        results = []
        for tu in tool_uses:
            if progress_cb:
                progress_cb(f'\n  [{tu.name}({json.dumps(tu.input, separators=(",", ":"))})]\n')
            output = _execute_tool(tu.name, tu.input, root_path, files_read)
            results.append({'type': 'tool_result', 'tool_use_id': tu.id, 'content': output})
        messages.append({'role': 'user', 'content': results})

    return '[Analysis incomplete — max turns reached]'


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

_VERIFY_SYSTEM = """\
You are a Java code reviewer. Check the generated code against the codebase profile.

Verify ALL of the following:
1. Implements/extends the correct base type from the profile's Base section
2. All abstract methods from the base type are implemented
3. All Required Imports are present
4. Lifecycle Contract is honoured (annotations, constructor args, init/shutdown)
5. Package declaration matches the profile
6. No NaN is ever returned (0.0 must be the fallback)

If the code is CORRECT, output exactly one word: VERIFIED

If there are issues, output the COMPLETE corrected code using === FILE: Name.java === delimiters.
Fix ALL issues. Output code only — no explanations.
"""


async def verify_generated_code(
    code: str,
    profile: str,
    client,
    model: str,
    cfg,
) -> str | None:
    """
    Verify generated Java code against the codebase profile.
    Returns None if verified, else the corrected code string.
    """
    messages = [{
        'role': 'user',
        'content': f'## Codebase Profile\n\n{profile}\n\n## Generated Code\n\n{code}',
    }]
    result = ''
    async for chunk in _call_with_continuation(_VERIFY_SYSTEM, messages, cfg, client, model):
        result += chunk
    stripped = result.strip()
    return None if stripped == 'VERIFIED' else (stripped or None)
