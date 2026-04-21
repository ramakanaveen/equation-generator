"""
Codebase analyzer for codegen.py — language-agnostic.

Supports Java, Python, TypeScript, Kotlin, Go out of the box.
Language is auto-detected from file extension counts.

Architecture: 3 parallel Explorer subagents + 1 Synthesizer (Claude Code Ultra pattern).

Context strategy (Claude Code / DeepAgents / Cline pattern):
  - Symbol index stays in Python; exposed via query_symbols tool (lazy, never pre-dumped)
  - All tool results hard-capped at MAX_TOOL_RESULT_CHARS (~20K tokens)
  - Explorers run on Haiku (fast + cheap); synthesizer uses full model
  - max_tokens handled with inline continuation inside explorer loop
  - Build output dirs pruned; test dirs included (test files implement real interfaces)
"""
import asyncio
import fnmatch
import hashlib
import json
import os
import re
import sys

from generator import _call_with_continuation, api_call_with_backoff

# ---------------------------------------------------------------------------
# Profile cache  (OpenCode pattern: content-hash, project-local, no git needed)
# ---------------------------------------------------------------------------

_CACHE_DIR_NAME = '.codegen-cache'
_CACHE_FILE = 'profile.json'


def _cache_dir(root_path: str) -> str:
    return os.path.join(root_path, _CACHE_DIR_NAME)


def _content_hash(root_path: str, extensions: tuple) -> str:
    """
    SHA256 of all source file paths + contents.
    No git dependency — works on any filesystem.
    Reliable: content change always changes the hash (unlike mtimes).
    OpenCode uses the same file-content-hash approach.
    """
    hasher = hashlib.sha256()
    skip = _COMMON_SKIP_DIRS | {_CACHE_DIR_NAME}
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        for fname in sorted(filenames):
            if any(fname.endswith(ext) for ext in extensions):
                fpath = os.path.join(dirpath, fname)
                try:
                    rel = os.path.relpath(fpath, root_path)
                    hasher.update(rel.encode())
                    with open(fpath, 'rb') as f:
                        hasher.update(f.read())
                except OSError:
                    pass
    return hasher.hexdigest()[:24]


def _load_cached_profile(root_path: str, extensions: tuple) -> str | None:
    cache_file = os.path.join(_cache_dir(root_path), _CACHE_FILE)
    if not os.path.isfile(cache_file):
        return None
    try:
        data = json.loads(open(cache_file, encoding='utf-8').read())
        if data.get('key') == _content_hash(root_path, extensions):
            return data.get('profile')
    except Exception:
        pass
    return None


def _save_cached_profile(root_path: str, extensions: tuple, profile: str) -> None:
    cache_path = _cache_dir(root_path)
    os.makedirs(cache_path, exist_ok=True)
    # Auto-add to .gitignore if inside a git repo
    gitignore = os.path.join(root_path, '.gitignore')
    try:
        existing = open(gitignore).read() if os.path.isfile(gitignore) else ''
        if _CACHE_DIR_NAME not in existing:
            with open(gitignore, 'a') as f:
                f.write(f'\n{_CACHE_DIR_NAME}/\n')
    except OSError:
        pass
    cache_file = os.path.join(cache_path, _CACHE_FILE)
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump({'key': _content_hash(root_path, extensions), 'profile': profile}, f)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILES_PER_EXPLORER = 8
MAX_TURNS_EXPLORER = 10
BOOTSTRAP_CAP = 6000
MAX_TOOL_RESULT_CHARS = 80_000  # ~20K tokens @ 4 chars/token (DeepAgents threshold)

# Build output only — test/generated source is intentionally included
# (test files implement real interfaces, useful for fan-in discovery)
_COMMON_SKIP_DIRS = frozenset({'.git', '__pycache__'})

# ---------------------------------------------------------------------------
# Language config
# ---------------------------------------------------------------------------

# Each entry: extensions, skip_dirs, how to parse symbols
_LANG_CFG: dict = {
    'java': {
        'extensions': ('.java',),
        'skip_dirs': {'target', 'build', '.gradle'},
        'bootstrap_files': ['CLAUDE.md', 'README.md', 'pom.xml', 'build.gradle', 'build.gradle.kts'],
    },
    'kotlin': {
        'extensions': ('.kt',),
        'skip_dirs': {'target', 'build', '.gradle'},
        'bootstrap_files': ['CLAUDE.md', 'README.md', 'pom.xml', 'build.gradle', 'build.gradle.kts'],
    },
    'python': {
        'extensions': ('.py',),
        'skip_dirs': {'.venv', 'venv', 'dist', '.eggs', 'site-packages', '.tox'},
        'bootstrap_files': ['CLAUDE.md', 'README.md', 'pyproject.toml', 'setup.py', 'setup.cfg'],
    },
    'typescript': {
        'extensions': ('.ts', '.tsx'),
        'skip_dirs': {'node_modules', 'dist', '.next', '.nuxt'},
        'bootstrap_files': ['CLAUDE.md', 'README.md', 'package.json', 'tsconfig.json'],
    },
    'javascript': {
        'extensions': ('.js', '.jsx', '.mjs'),
        'skip_dirs': {'node_modules', 'dist', '.next', '.nuxt'},
        'bootstrap_files': ['CLAUDE.md', 'README.md', 'package.json'],
    },
    'go': {
        'extensions': ('.go',),
        'skip_dirs': {'vendor'},
        'bootstrap_files': ['CLAUDE.md', 'README.md', 'go.mod', 'go.sum'],
    },
}

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def _detect_language(root_path: str) -> str:
    """Count source files per language; return the dominant one."""
    counts: dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in _COMMON_SKIP_DIRS]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            for lang, cfg in _LANG_CFG.items():
                if ext in cfg['extensions']:
                    counts[lang] = counts.get(lang, 0) + 1
    return max(counts, key=lambda l: counts[l]) if counts else 'java'


def _skip_dirs_for(lang: str) -> frozenset:
    return _COMMON_SKIP_DIRS | frozenset(_LANG_CFG.get(lang, {}).get('skip_dirs', set()))


def _extensions_for(lang: str) -> tuple:
    return _LANG_CFG.get(lang, _LANG_CFG['java'])['extensions']

# ---------------------------------------------------------------------------
# Model selection  (Claude Code pattern: cheap model for explorers)
# ---------------------------------------------------------------------------

def _explorer_model(model: str) -> str:
    if 'haiku' in model.lower():
        return model
    if '@' in model:
        return 'claude-haiku-4-5@20251001'
    return 'claude-haiku-4-5-20251001'



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
# Tool result cap
# ---------------------------------------------------------------------------

def _cap_result(text: str, hint: str = '') -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    remaining = len(text) - MAX_TOOL_RESULT_CHARS
    tip = hint or 'use start_line/end_line or a narrower search'
    return text[:MAX_TOOL_RESULT_CHARS] + f'\n[... {remaining} chars truncated — {tip}]'

# ---------------------------------------------------------------------------
# Symbol index  (language-aware regex scan)
# ---------------------------------------------------------------------------

# Java / Kotlin
_JAVA_PACKAGE_RE = re.compile(r'^\s*package\s+([\w.]+)\s*;?', re.MULTILINE)
_JAVA_TYPE_RE = re.compile(
    r'(?:(?:public|internal|open|data|sealed|value)\s+)*(?:(abstract)\s+)?'
    r'(class|interface|enum(?:\s+class)?|object|annotation\s+class)\s+(\w+)'
    r'(?:\s*:\s*([\w.<>, ()\n]+?))?(?=\s*[{(<])',
    re.MULTILINE,
)
_JAVA_METHOD_RE = re.compile(
    r'(?:public|protected|override|open)\s+(?:(?:suspend|inline|abstract)\s+)*'
    r'(?:fun|void|[\w<>\[\].,?]+)\s+(\w+)\s*\(',
    re.MULTILINE,
)

# Python
_PY_CLASS_RE = re.compile(r'^class\s+(\w+)\s*(?:\(([^)]*)\))?:', re.MULTILINE)
_PY_METHOD_RE = re.compile(r'^\s+def\s+(\w+)\s*\(', re.MULTILINE)

# TypeScript / JavaScript
_TS_TYPE_RE = re.compile(
    r'(?:export\s+)?(?:(abstract)\s+)?'
    r'(class|interface|type|enum)\s+(\w+)'
    r'(?:\s+extends\s+([\w.<>, ]+?))?(?:\s+implements\s+([\w.<>, ]+?))?\s*[{<]',
    re.MULTILINE,
)
_TS_METHOD_RE = re.compile(
    r'(?:public|protected|private|readonly|async)?\s+(\w+)\s*[(<]',
    re.MULTILINE,
)

# Go
_GO_PACKAGE_RE = re.compile(r'^package\s+(\w+)', re.MULTILINE)
_GO_TYPE_RE = re.compile(r'type\s+(\w+)\s+(interface|struct)\s*\{', re.MULTILINE)
_GO_METHOD_RE = re.compile(r'func\s+\(\w+\s+\*?\w+\)\s+(\w+)\s*\(', re.MULTILINE)

_TEST_PATH_MARKERS = ('/test/', '/tests/', 'Test.', 'Tests.', '_test.', 'test_', 'spec.')


def _is_test_file(rel_path: str) -> bool:
    p = rel_path.replace(os.sep, '/')
    return any(m in p for m in _TEST_PATH_MARKERS)


def _parse_java(src: str, rel_path: str, root_real: str) -> list[dict]:
    pkg_m = _JAVA_PACKAGE_RE.search(src)
    package = pkg_m.group(1) if pkg_m else ''
    methods = list(dict.fromkeys(_JAVA_METHOD_RE.findall(src)))[:20]
    results = []
    for m in _JAVA_TYPE_RE.finditer(src):
        abstract_flag = m.group(1)
        kind_raw = m.group(2).replace('\n', ' ').strip()
        name = m.group(3)
        supertypes_raw = (m.group(4) or '').strip()

        if 'interface' in kind_raw:
            kind = 'interface'
            extends, implements = [s.strip() for s in supertypes_raw.split(',') if s.strip()], []
        elif abstract_flag or kind_raw.startswith('abstract'):
            kind = 'abstract class'
            extends, implements = [], [s.strip() for s in supertypes_raw.split(',') if s.strip()]
        else:
            kind = kind_raw.split()[0]  # class / enum / object / etc.
            extends, implements = [], [s.strip() for s in supertypes_raw.split(',') if s.strip()]

        fqn = f'{package}.{name}' if package else name
        results.append({
            'fqn': fqn, 'file': rel_path, 'kind': kind,
            'extends': extends, 'implements': implements,
            'methods': methods, 'package': package,
            'test': _is_test_file(rel_path),
        })
    return results


def _parse_python(src: str, rel_path: str, root_real: str) -> list[dict]:
    # Derive module from path: src/foo/bar.py → foo.bar
    parts = rel_path.replace(os.sep, '/').replace('.py', '').split('/')
    if parts and parts[0] in ('src', 'lib'):
        parts = parts[1:]
    module = '.'.join(parts)
    methods = list(dict.fromkeys(_PY_METHOD_RE.findall(src)))[:20]
    results = []
    for m in _PY_CLASS_RE.finditer(src):
        name = m.group(1)
        bases_raw = (m.group(2) or '').strip()
        bases = [b.strip() for b in bases_raw.split(',') if b.strip()] if bases_raw else []
        fqn = f'{module}.{name}' if module else name
        results.append({
            'fqn': fqn, 'file': rel_path, 'kind': 'class',
            'extends': bases, 'implements': [],
            'methods': methods, 'package': module,
            'test': _is_test_file(rel_path),
        })
    return results


def _parse_typescript(src: str, rel_path: str, root_real: str) -> list[dict]:
    methods = list(dict.fromkeys(_TS_METHOD_RE.findall(src)))[:20]
    results = []
    for m in _TS_TYPE_RE.finditer(src):
        abstract_flag, kind_raw, name = m.group(1), m.group(2), m.group(3)
        extends_raw = (m.group(4) or '').strip()
        implements_raw = (m.group(5) or '').strip()
        kind = 'abstract class' if abstract_flag else kind_raw
        module = rel_path.replace(os.sep, '/').rsplit('.', 1)[0]
        results.append({
            'fqn': f'{module}.{name}', 'file': rel_path, 'kind': kind,
            'extends': [e.strip() for e in extends_raw.split(',') if e.strip()],
            'implements': [i.strip() for i in implements_raw.split(',') if i.strip()],
            'methods': methods, 'package': module,
            'test': _is_test_file(rel_path),
        })
    return results


def _parse_go(src: str, rel_path: str, root_real: str) -> list[dict]:
    pkg_m = _GO_PACKAGE_RE.search(src)
    package = pkg_m.group(1) if pkg_m else ''
    methods = list(dict.fromkeys(_GO_METHOD_RE.findall(src)))[:20]
    results = []
    for m in _GO_TYPE_RE.finditer(src):
        name, kind = m.group(1), m.group(2)
        fqn = f'{package}.{name}' if package else name
        results.append({
            'fqn': fqn, 'file': rel_path, 'kind': kind,
            'extends': [], 'implements': [],
            'methods': methods, 'package': package,
            'test': _is_test_file(rel_path),
        })
    return results


_PARSERS = {
    'java': _parse_java, 'kotlin': _parse_java,
    'python': _parse_python,
    'typescript': _parse_typescript, 'javascript': _parse_typescript,
    'go': _parse_go,
}


def _build_symbol_index(root_path: str, lang: str) -> dict:
    """
    Scan all source files for the detected language.
    Returns {fqn: {file, kind, extends, implements, methods, package, test}}.
    """
    parser = _PARSERS.get(lang, _parse_java)
    extensions = _extensions_for(lang)
    skip = _skip_dirs_for(lang)
    index: dict = {}
    root_real = os.path.realpath(root_path)

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fname in filenames:
            if not any(fname.endswith(ext) for ext in extensions):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, encoding='utf-8', errors='replace') as f:
                    src = f.read()
            except (IOError, OSError):
                continue
            rel = os.path.relpath(fpath, root_real)
            for entry in parser(src, rel, root_real):
                index[entry['fqn']] = {k: v for k, v in entry.items() if k != 'fqn'}

    return index


def _bootstrap_context(root_path: str, lang: str) -> str:
    files = _LANG_CFG.get(lang, _LANG_CFG['java'])['bootstrap_files']
    parts = []
    for fname in files:
        fpath = os.path.join(root_path, fname)
        if os.path.isfile(fpath):
            try:
                with open(fpath, encoding='utf-8', errors='replace') as f:
                    content = f.read(BOOTSTRAP_CAP)
                parts.append(f'=== {fname} ===\n{content}')
            except (IOError, OSError):
                pass
    return '\n\n'.join(parts) or '(No project config files found at root)'

# ---------------------------------------------------------------------------
# Tool implementations
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
    if counter[0] >= MAX_FILES_PER_EXPLORER:
        return f'[File read limit ({MAX_FILES_PER_EXPLORER}) reached — output your findings now]'
    try:
        path = _safe_path(inputs['path'], root)
    except ValueError as e:
        return f'[Error: {e}]'
    if not os.path.isfile(path):
        return f'[Not a file: {inputs["path"]!r}]'
    start = inputs.get('start_line')
    end = inputs.get('end_line')
    max_lines = inputs.get('max_lines')  # only applied when LLM explicitly requests it
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        if start is not None:
            s = max(0, int(start) - 1)
            e = int(end) if end is not None else (s + int(max_lines)) if max_lines else len(lines)
            result = ''.join(lines[s:e])
        elif max_lines is not None:
            result = ''.join(lines[:int(max_lines)])
        else:
            result = ''.join(lines)  # full file — capped by MAX_TOOL_RESULT_CHARS below
        counter[0] += 1
        return _cap_result(result, 'use start_line/end_line to read specific sections')
    except (IOError, OSError) as ex:
        return f'[Error: {ex}]'


def _tool_search_code(inputs: dict, root: str, lang: str) -> str:
    try:
        directory = _safe_path(inputs.get('directory', root), root)
    except ValueError as e:
        return f'[Error: {e}]'
    pattern = inputs.get('pattern', '')
    # Default extension from detected language; caller can override
    default_ext = _extensions_for(lang)[0]
    ext = inputs.get('file_ext', default_ext)
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
                                return _cap_result('\n'.join(results), 'use a more specific pattern')
            except (IOError, OSError):
                pass
    return '\n'.join(results) if results else f'[No matches for {pattern!r}]'


def _tool_query_symbols(inputs: dict, symbol_index: dict) -> str:
    """Lazy structural query against the in-memory symbol index."""
    kind_filter = inputs.get('kind', '').lower()
    name_pattern = inputs.get('name_pattern', '')
    limit = min(int(inputs.get('limit', 50)), 100)
    test_filter = inputs.get('test')  # None = all, True = test only, False = non-test only

    try:
        name_re = re.compile(name_pattern, re.IGNORECASE) if name_pattern else None
    except re.error as e:
        return f'[Invalid name_pattern: {e}]'

    results = {}
    for fqn, entry in symbol_index.items():
        if kind_filter and kind_filter not in entry['kind'].lower():
            continue
        if name_re and not name_re.search(fqn):
            continue
        if test_filter is not None and entry.get('test') != test_filter:
            continue
        results[fqn] = {f: entry[f] for f in ('file', 'kind', 'extends', 'implements', 'package', 'test')}
        if len(results) >= limit:
            break

    if not results:
        return f'[No symbols matching kind={kind_filter!r} name_pattern={name_pattern!r}]'

    total_matching = sum(
        1 for e in symbol_index.values()
        if not kind_filter or kind_filter in e['kind'].lower()
    )
    suffix = (
        f'\n[showing {len(results)} of {total_matching} — use name_pattern, kind, or test=false to narrow]'
        if total_matching > len(results) else ''
    )
    return _cap_result(json.dumps(results, indent=2) + suffix, 'use name_pattern to narrow')


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


def _execute_tool(
    name: str, inputs: dict, root: str | None,
    counter: list | None, symbol_index: dict | None, lang: str = 'java',
) -> str:
    if name == 'query_symbols' and symbol_index is not None:
        return _tool_query_symbols(inputs, symbol_index)
    if name == 'glob' and root:
        return _tool_glob(inputs.get('pattern', '**/*'), root)
    if name == 'read_file' and root and counter is not None:
        return _tool_read_file(inputs, root, counter)
    if name == 'search_code' and root:
        return _tool_search_code(inputs, root, lang)
    if name == 'ask_followup_question':
        return _tool_ask_followup_question(inputs)
    return f'[Unknown tool: {name!r}]'

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_EXPLORER_TOOLS = [
    {
        'name': 'query_symbols',
        'description': (
            'Fast structural lookup against the symbol index — use this FIRST before reading files. '
            'Works for any language: Java classes/interfaces, Python classes, TypeScript types, Go structs, etc. '
            'Returns file, kind, extends, implements, package, test (test=true means from test source). '
            'Prefer test=false entries as implementation patterns. '
            'kind examples: "class", "interface", "abstract class", "struct", "enum".'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'kind': {'type': 'string', 'description': 'Filter by kind: "class", "interface", "abstract class", "struct", etc.'},
                'name_pattern': {'type': 'string', 'description': 'Optional regex filter on fully-qualified symbol name'},
                'test': {'type': 'boolean', 'description': 'Filter by test file: false = production only, true = test only, omit = all'},
                'limit': {'type': 'integer', 'default': 50, 'description': 'Max results (default 50, max 100)'},
            },
        },
    },
    {
        'name': 'glob',
        'description': 'Find files by glob pattern (e.g. "**/*.py", "**/*.java", "go.mod"). Returns sorted paths.',
        'input_schema': {
            'type': 'object',
            'properties': {'pattern': {'type': 'string'}},
            'required': ['pattern'],
        },
    },
    {
        'name': 'read_file',
        'description': (
            'Read a file. Returns the full file by default. '
            'Use start_line/end_line to read a specific section of a large file.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'path': {'type': 'string'},
                'start_line': {'type': 'integer', 'description': 'First line to read (1-based)'},
                'end_line': {'type': 'integer', 'description': 'Last line to read (inclusive)'},
                'max_lines': {'type': 'integer', 'description': 'Limit lines returned (omit for full file)'},
            },
            'required': ['path'],
        },
    },
    {
        'name': 'search_code',
        'description': 'Regex search across source files. Returns up to 40 matching lines with file:line context.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'directory': {'type': 'string'},
                'pattern': {'type': 'string'},
                'file_ext': {'type': 'string', 'description': 'Override default extension (e.g. ".py", ".ts")'},
            },
            'required': ['directory', 'pattern'],
        },
    },
]

# ---------------------------------------------------------------------------
# Explorer system prompts  (language-agnostic)
# ---------------------------------------------------------------------------

_SYSTEM_EXPLORER_1 = """\
You are Explorer 1. Find the base class, interface, protocol, or abstract type that new \
computation/signal classes should extend or implement in this codebase.

Language: {lang}
Equation/task being implemented: {equation_text}

Strategy:
1. Call query_symbols(kind="interface") and query_symbols(kind="abstract class") — look for \
types with high fan-in (many classes extending/implementing them)
2. For Python: look for ABC subclasses, Protocol types, or classes with abstract methods
3. For the 1-2 strongest candidates, call read_file to confirm their full signatures
4. Stop as soon as you confirm the right base type

Report format:
## Base Type Found
Name: ...
File: ...
Full source: (paste complete source)

## Why This Is The Right Base Type
(fan-in count, naming, package/module context)

Max {max_files} file reads."""

_SYSTEM_EXPLORER_2 = """\
You are Explorer 2. Find one concrete implementation that shows the exact pattern \
new classes should follow in this codebase.

Language: {lang}
Equation/task being implemented: {equation_text}

Strategy:
1. Call query_symbols(kind="class", test=false) to find production implementations
2. Look for classes that extend/implement something — prefer ones in non-test source
3. Read 1-2 files — focus on: class declaration, main compute/evaluate method, any decorators

Report format:
## Example Implementation Found
File: ...
Package/module: ...
Pattern (key parts): (paste class declaration + main compute method + any annotations/decorators)

## Observations
(naming conventions, decorators/annotations, constructor pattern, any framework lifecycle)

Max {max_files} file reads."""

_SYSTEM_EXPLORER_3 = """\
You are Explorer 3. Determine build constraints and the correct package/module for new classes.

Language: {lang}
You have the project bootstrap context (CLAUDE.md, README, build manifest). \
Read additional config files if needed.

Report format:
## Build Constraints
Language/runtime version: ...
Build system: ...
Key dependencies: ...

## Package / Module for New Classes
(exact package or module path, e.g. com.trading.signals or trading.signals)

## Project Rules
(from CLAUDE.md or README — file placement, naming conventions, required decorators/annotations)

Max {max_files} file reads."""

_SYSTEM_SYNTHESIZER = """\
You are the Synthesizer. Three parallel explorer subagents have reported back. \
Merge their findings into a single coherent CodebaseProfile.

Language: {lang}
Task to implement: {equation_text}

{clarification_note}\
Output this exact format (all sections required):

## Language
{lang}

## Build Constraints
(runtime version, build system, key deps)

## Package / Module
(exact location for the new file — if genuinely unknown write: UNCLEAR: <brief reason>)

## Base Type
(full source of the class/interface/protocol/ABC to extend or implement \
— if genuinely unknown write: UNCLEAR: <brief reason and candidates found>)

## Required Imports
(all import statements the generated code needs)

## Lifecycle Contract
(decorators, constructor args, init/teardown; "none" if simple)

## Implementation Pattern
(from Explorer 2's example — the exact pattern to follow)

## Codebase Rules
(from Explorer 3 + any other rules discovered)"""

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
    symbol_index: dict,
    lang: str,
    progress_cb=None,
) -> str:
    messages = [{'role': 'user', 'content': initial_msg}]
    files_read = [0]
    exp_model = _explorer_model(model)
    use_thinking = 'haiku' not in exp_model.lower()

    for _ in range(MAX_TURNS_EXPLORER):
        if use_thinking:
            try:
                response = await api_call_with_backoff(
                    client.messages.create,
                    model=exp_model,
                    max_tokens=8192,
                    thinking={'type': 'enabled', 'budget_tokens': 5000},
                    tools=_EXPLORER_TOOLS,
                    system=system,
                    messages=messages,
                )
            except Exception as e:
                if 'thinking' in str(e).lower() or 'unsupported' in str(e).lower():
                    use_thinking = False
                    response = await api_call_with_backoff(
                        client.messages.create,
                        model=exp_model,
                        max_tokens=cfg.max_tokens,
                        tools=_EXPLORER_TOOLS,
                        system=system,
                        messages=messages,
                    )
                else:
                    raise
        else:
            response = await api_call_with_backoff(
                client.messages.create,
                model=exp_model,
                max_tokens=cfg.max_tokens,
                tools=_EXPLORER_TOOLS,
                system=system,
                messages=messages,
            )

        tool_uses = [b for b in response.content if b.type == 'tool_use']
        text_blocks = [b for b in response.content if b.type == 'text']

        if tool_uses:
            messages.append({'role': 'assistant', 'content': response.content})
            results = []
            for tu in tool_uses:
                if progress_cb:
                    progress_cb(f'  [{name}] {tu.name}({json.dumps(tu.input, separators=(",", ":"))}) \n')
                output = _execute_tool(tu.name, tu.input, root_path, files_read, symbol_index, lang)
                results.append({'type': 'tool_result', 'tool_use_id': tu.id, 'content': output})
            messages.append({'role': 'user', 'content': results})
            continue

        if response.stop_reason == 'max_tokens':
            messages.append({'role': 'assistant', 'content': response.content})
            messages.append({'role': 'user', 'content': 'Continue your report from where you left off.'})
            continue

        report = '\n'.join(b.text for b in text_blocks).strip()
        if progress_cb:
            progress_cb(f'[{name}: done]\n')
        return report or f'[{name}: no findings]'

    return f'[{name}: max turns reached]'

# ---------------------------------------------------------------------------
# Profile completeness check  (orchestrator-level, Claude Code pattern)
# ---------------------------------------------------------------------------

_CRITICAL_SECTIONS = ('Base Type', 'Package / Module')
_UNCLEAR_MARKERS = ('unclear:', 'not found', 'unknown', 'ambiguous', 'multiple candidates')


def _extract_section(profile: str, heading: str) -> str:
    m = re.search(
        rf'##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##\s|\Z)',
        profile, re.DOTALL | re.IGNORECASE,
    )
    return m.group(1).strip() if m else ''


def _unclear_sections(profile: str) -> list[str]:
    """Return critical section names that are empty or explicitly marked UNCLEAR."""
    missing = []
    for section in _CRITICAL_SECTIONS:
        content = _extract_section(profile, section).lower()
        if not content or any(m in content for m in _UNCLEAR_MARKERS):
            missing.append(section)
    return missing


def _extract_candidates_for(field: str, reports: list[str]) -> list[str]:
    """Pull concrete candidates from explorer reports to offer as options."""
    combined = '\n'.join(reports)
    candidates: list[str] = []
    if 'Base Type' in field:
        for m in re.finditer(
            r'(?:class|interface|abstract class|protocol|ABC)\s+(\w[\w.]*)', combined
        ):
            name = m.group(1)
            if name not in candidates:
                candidates.append(name)
    elif 'Package' in field:
        for m in re.finditer(r'(?:package|module)\s+([\w.]+)', combined, re.IGNORECASE):
            pkg = m.group(1)
            if pkg not in candidates:
                candidates.append(pkg)
    return candidates[:4]

# ---------------------------------------------------------------------------
# Synthesizer  (stateless _call_with_continuation — Claude Code pattern)
# ---------------------------------------------------------------------------

async def _synthesize(
    reports: list[str],
    equation_text: str,
    lang: str,
    client,
    model: str,
    cfg,
    clarification_note: str = '',
    progress_cb=None,
) -> str:
    """
    Stateless synthesis — no tool loop.
    Follows Claude Code pattern: parent synthesizes subagent outputs in a single call.
    If ambiguous, synthesizer writes UNCLEAR: in that section; orchestrator handles it.
    """
    r1, r2, r3 = reports
    user_content = (
        f'Explorer 1 report (Base Types):\n{r1}\n\n'
        f'Explorer 2 report (Implementations):\n{r2}\n\n'
        f'Explorer 3 report (Build + Conventions):\n{r3}'
    )
    if clarification_note:
        user_content += f'\n\nUser clarifications:\n{clarification_note}'

    if progress_cb:
        label = 'Synthesizer: re-running with clarifications' if clarification_note else 'Synthesizer: merging reports'
        progress_cb(f'[{label}]\n')

    system = _SYSTEM_SYNTHESIZER.format(
        lang=lang,
        equation_text=equation_text,
        clarification_note=f'User clarifications:\n{clarification_note}\n\n' if clarification_note else '',
    )
    messages = [{'role': 'user', 'content': user_content}]
    profile = ''
    async for chunk in _call_with_continuation(system, messages, cfg, client, model):
        profile += chunk
        if progress_cb:
            progress_cb(chunk)
    if progress_cb:
        progress_cb('\n')

    return profile.strip() or '[No profile produced]'


async def _synthesize_with_clarification(
    reports: list[str],
    equation_text: str,
    lang: str,
    client,
    model: str,
    cfg,
    progress_cb=None,
) -> str:
    """
    Synthesize → check completeness → ask user if UNCLEAR → re-synthesize.
    Orchestrator-level clarification loop (Claude Code parent loop pattern).
    Full explorer reports are always preserved and re-sent on retry — no data loss.
    """
    profile = await _synthesize(reports, equation_text, lang, client, model, cfg, progress_cb=progress_cb)

    unclear = _unclear_sections(profile)
    if not unclear:
        return profile

    # Ask user about each unclear field (orchestrator handles this, not the LLM)
    clarifications = []
    for field in unclear:
        candidates = _extract_candidates_for(field, reports)
        answer = _tool_ask_followup_question({
            'question': f'Could not determine {field} from the codebase. Please clarify:',
            'options': candidates or ['Provide manually'],
        })
        clarifications.append(f'{field}: {answer}')

    clarification_note = '\n'.join(clarifications)
    return await _synthesize(
        reports, equation_text, lang, client, model, cfg,
        clarification_note=clarification_note,
        progress_cb=progress_cb,
    )

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
    Analyze any language codebase using 3 parallel explorer subagents + 1 synthesizer.
    Language is auto-detected. Returns CodebaseProfile markdown string.
    """
    root_path = os.path.realpath(root_path)
    if not os.path.isdir(root_path):
        raise ValueError(f'Not a directory: {root_path}')

    lang = _detect_language(root_path)
    extensions = _extensions_for(lang)

    # Cache check — OpenCode pattern: content hash, project-local, no git needed
    cached = await asyncio.to_thread(_load_cached_profile, root_path, extensions)
    if cached:
        if progress_cb:
            progress_cb(f'[Language: {lang} | Profile cache hit — skipping analysis]\n')
        return cached

    symbol_index, bootstrap = await asyncio.gather(
        asyncio.to_thread(_build_symbol_index, root_path, lang),
        asyncio.to_thread(_bootstrap_context, root_path, lang),
    )

    n_base = sum(1 for e in symbol_index.values() if e['kind'] in ('interface', 'abstract class'))
    n_with_parents = sum(1 for e in symbol_index.values() if e['extends'] or e['implements'])
    exp_model = _explorer_model(model)

    if progress_cb:
        progress_cb(
            f'[Language: {lang} | Symbols: {len(symbol_index)} '
            f'({n_base} base types, {n_with_parents} with inheritance) | '
            f'Explorers: {exp_model} | Launching 3 in parallel]\n'
        )

    r1, r2, r3 = await asyncio.gather(
        _run_explorer(
            name='Explorer-1 (Base Types)',
            system=_SYSTEM_EXPLORER_1.format(
                lang=lang, equation_text=equation_text, max_files=MAX_FILES_PER_EXPLORER,
            ),
            initial_msg=(
                f'Language: {lang}. Codebase has {len(symbol_index)} symbols '
                f'({n_base} base types, {n_with_parents} with inheritance). '
                f'Use query_symbols(kind="interface") or query_symbols(kind="abstract class") '
                f'to discover base type candidates.'
            ),
            root_path=root_path, client=client, model=model, cfg=cfg,
            symbol_index=symbol_index, lang=lang, progress_cb=progress_cb,
        ),
        _run_explorer(
            name='Explorer-2 (Implementations)',
            system=_SYSTEM_EXPLORER_2.format(
                lang=lang, equation_text=equation_text, max_files=MAX_FILES_PER_EXPLORER,
            ),
            initial_msg=(
                f'Language: {lang}. Codebase has {len(symbol_index)} symbols. '
                f'Use query_symbols(kind="class", test=false) to find production implementations.'
            ),
            root_path=root_path, client=client, model=model, cfg=cfg,
            symbol_index=symbol_index, lang=lang, progress_cb=progress_cb,
        ),
        _run_explorer(
            name='Explorer-3 (Build + Conventions)',
            system=_SYSTEM_EXPLORER_3.format(lang=lang, max_files=MAX_FILES_PER_EXPLORER),
            initial_msg=f'Language: {lang}\n\nBootstrap context:\n{bootstrap}',
            root_path=root_path, client=client, model=model, cfg=cfg,
            symbol_index=symbol_index, lang=lang, progress_cb=progress_cb,
        ),
    )

    profile = await _synthesize_with_clarification([r1, r2, r3], equation_text, lang, client, model, cfg, progress_cb)

    # Save to project-local cache for future runs
    await asyncio.to_thread(_save_cached_profile, root_path, extensions, profile)

    return profile

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

_VERIFY_SYSTEM = """\
You are a code reviewer. Check this single generated file against the codebase profile.

Verify:
1. Extends/implements the correct base type from the profile
2. All required abstract methods are implemented
3. All required imports are present
4. Lifecycle contract is honoured (decorators, constructor, lifecycle methods)
5. Package/module declaration matches the profile
6. No NaN or None returned unexpectedly — use 0.0 / 0 as the safe fallback

If correct, output exactly: VERIFIED
If there are issues, output ONLY the complete corrected file content — plain code, no markdown fences,
no === FILE: === delimiters. Just the corrected file content ready to write to disk."""


async def verify_generated_code(
    code: str,
    profile: str,
    client,
    model: str,
    cfg,
) -> str | None:
    """Verify a single file's content. Returns corrected code or None if verified."""
    messages = [{
        'role': 'user',
        'content': f'## Codebase Profile\n\n{profile}\n\n## Generated File\n\n{code}',
    }]
    result = ''
    async for chunk in _call_with_continuation(_VERIFY_SYSTEM, messages, cfg, client, model):
        result += chunk
    stripped = result.strip()
    return None if stripped == 'VERIFIED' else (stripped or None)
