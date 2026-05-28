import asyncio
import hashlib
import os
import re
import sys

from generator import _call_with_continuation, api_call_with_backoff, UsageTracker

# Session-level classpath cache — keyed by codebase_root; avoids repeated Maven calls
_CP_CACHE: dict[str, str] = {}


def _find_java_src_roots(codebase_root: str) -> list[str]:
    """Find all src/main/java directories (handles multimodule Maven). Returns up to 10."""
    roots = []
    for dirpath, dirnames, _ in os.walk(codebase_root):
        dirnames[:] = [d for d in dirnames if d not in {'.git', 'target', 'build', '.gradle', 'node_modules'}]
        if dirpath.endswith(os.path.join('src', 'main', 'java')):
            roots.append(dirpath)
            if len(roots) >= 10:
                break
    return roots or [codebase_root]


async def _discover_java_classpath(codebase_root: str) -> str:
    """
    Auto-discover the compile classpath for a Java project.
    Priority: session cache → Maven → Gradle build output → target/classes → empty.
    """
    if codebase_root in _CP_CACHE:
        return _CP_CACHE[codebase_root]

    cp = ''
    pom = os.path.join(codebase_root, 'pom.xml')
    gradle = next(
        (os.path.join(codebase_root, f) for f in ('build.gradle', 'build.gradle.kts')
         if os.path.isfile(os.path.join(codebase_root, f))), None
    )

    if os.path.isfile(pom):
        cp_file = f'/tmp/codegen_cp_{hashlib.md5(codebase_root.encode()).hexdigest()[:8]}.txt'
        try:
            proc = await asyncio.create_subprocess_exec(
                'mvn', 'dependency:build-classpath', '-q',
                '-DincludeScope=compile',
                f'-Dmdep.outputFile={cp_file}',
                '-f', pom,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=60)
            if os.path.isfile(cp_file):
                cp = open(cp_file).read().strip()
        except Exception:
            pass

    if not cp and gradle:
        classes = os.path.join(codebase_root, 'build', 'classes', 'java', 'main')
        if os.path.isdir(classes):
            cp = classes

    if not cp:
        target = os.path.join(codebase_root, 'target', 'classes')
        if os.path.isdir(target):
            cp = target

    _CP_CACHE[codebase_root] = cp
    return cp


async def _run_compile_check(java_file_path: str, codebase_root: str) -> str:
    """Run javac on the generated file. Returns errors or 'Compiled successfully.'"""
    classpath = await _discover_java_classpath(codebase_root)
    src_roots = _find_java_src_roots(codebase_root)
    out_dir = '/tmp/codegen_compile_out'
    os.makedirs(out_dir, exist_ok=True)

    cmd = ['javac', '-nowarn', '-d', out_dir]
    if classpath:
        cmd += ['-cp', classpath]
    if src_roots:
        cmd += ['-sourcepath', os.pathsep.join(src_roots)]
    cmd.append(java_file_path)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        output = stderr.decode('utf-8', errors='replace').strip()
        return 'Compiled successfully.' if proc.returncode == 0 else (output or 'Compilation failed.')
    except asyncio.TimeoutError:
        return 'Compile check timed out (30s).'
    except FileNotFoundError:
        return 'javac not found — ensure JDK is installed and on PATH.'


async def _run_python_compile_check(py_file_path: str) -> str:
    """Run py_compile on the generated file. Returns errors or 'Compiled successfully.'"""
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, '-m', 'py_compile', py_file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        output = stderr.decode('utf-8', errors='replace').strip()
        return 'Compiled successfully.' if proc.returncode == 0 else output
    except asyncio.TimeoutError:
        return 'Compile check timed out (10s).'


_WRITE_FILE_TOOL = {
    'name': 'write_file',
    'description': (
        'Write one generated code file to disk. '
        'Call once per file — do not batch multiple files into one call.'
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'filename': {
                'type': 'string',
                'description': 'Filename with extension, e.g. Alpha_Momentum.java or AlphaExpression.java',
            },
            'content': {
                'type': 'string',
                'description': 'Complete file content — no markdown fences, just the code',
            },
        },
        'required': ['filename', 'content'],
    },
}

_READ_FILE_TOOL = {
    'name': 'read_file',
    'description': (
        'Read a file. Checks the output directory first (for verification of what you wrote), '
        'then the codebase root (to look up existing classes, utilities, or patterns). '
        'If you find issues in what you wrote, call write_file again with corrections.'
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'filename': {
                'type': 'string',
                'description': 'Filename or relative path to read',
            },
        },
        'required': ['filename'],
    },
}

_SEARCH_CODE_TOOL = {
    'name': 'search_code',
    'description': (
        'Regex search across codebase source files. '
        'Use to find patterns, utility classes, how something is used, or check conventions.'
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'pattern': {'type': 'string', 'description': 'Regex pattern to search for'},
            'directory': {'type': 'string', 'description': 'Subdirectory to search (omit for whole codebase)'},
            'file_ext': {'type': 'string', 'description': 'File extension filter e.g. ".java", ".py" (omit for all)'},
        },
        'required': ['pattern'],
    },
}

_QUERY_SYMBOLS_TOOL = {
    'name': 'query_symbols',
    'description': (
        'Look up classes, interfaces, and types in the codebase symbol index. '
        'Use to find base types, check inheritance, or discover utility classes. '
        'Faster than search_code for structural discovery.'
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'kind': {'type': 'string', 'description': 'Filter: "class", "interface", "abstract class", etc.'},
            'name_pattern': {'type': 'string', 'description': 'Optional regex filter on fully-qualified name'},
            'test': {'type': 'boolean', 'description': 'false=production only, true=test only, omit=all'},
            'limit': {'type': 'integer', 'default': 50},
        },
    },
}

_COMPILE_CHECK_TOOL = {
    'name': 'compile_check',
    'description': (
        'Compile the generated file with the real compiler to check for errors. '
        'Returns compiler errors or "Compiled successfully.". '
        'Always call this after write_file. '
        'If errors are returned: fix them with write_file, then call compile_check again to confirm.'
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'filename': {
                'type': 'string',
                'description': 'Filename written by write_file (e.g. MySignal.java)',
            },
        },
        'required': ['filename'],
    },
}

_BASE_CODEGEN_TOOLS = [_WRITE_FILE_TOOL, _READ_FILE_TOOL]
_CODEBASE_TOOLS = [_SEARCH_CODE_TOOL, _QUERY_SYMBOLS_TOOL]

_WRITE_FILE_INSTRUCTION = """

---

## File Output Method
Use the write_file tool to output each file — one tool call per file.
Do NOT use === FILE: === text delimiters.
Write AlphaExpression.java first (if applicable), then one file per equation.
After writing each file, use read_file to verify the content is correct.
If you find issues, call write_file again with the corrected content.
If you need to look up patterns or types in the codebase, use read_file, search_code, or query_symbols.
"""

_MAX_CODEGEN_TURNS = 60
_MAX_FILE_READ_CHARS = 80_000
_COMPACT_THRESHOLD = 200_000  # ~50K tokens — compact before hitting 200K limit

_COMPACT_SYSTEM = """
You are summarising a code generation session to save context space.

Produce a compact but complete summary that includes:
- Files written so far: name, language, class/function signatures, key logic
- Codebase patterns and constraints discovered during generation
- Any corrections applied and why
- What has been verified vs still in progress

This summary will replace the full history. Be dense but accurate.
""".strip()


async def _compact_messages(messages: list, cfg, client, model: str, tracker=None) -> list:
    """
    Claude Code /compact pattern: summarise older history, keep recent turns intact.
    Only fires when total message content exceeds _COMPACT_THRESHOLD.
    """
    total = sum(len(str(m)) for m in messages)
    if total <= _COMPACT_THRESHOLD:
        return messages

    keep_recent = messages[-4:]
    to_summarise = messages[:-4]
    if not to_summarise:
        return messages

    try:
        summary_resp = await api_call_with_backoff(
            client.messages.create,
            model=model,
            max_tokens=2048,
            system=_COMPACT_SYSTEM,
            messages=to_summarise + [{'role': 'user', 'content': 'Summarise the session so far.'}],
        )
        if tracker:
            tracker.record(summary_resp)
        summary = next((b.text for b in summary_resp.content if b.type == 'text'), '')
        compacted = [
            {'role': 'user', 'content': f'[Compacted session history]\n{summary}'},
            {'role': 'assistant', 'content': 'Understood — continuing from the current state.'},
        ]
        return compacted + keep_recent
    except Exception:
        return messages  # if compact fails, continue with full history


def _gen_search_code(inputs: dict, root: str) -> str:
    """Inline search — no language dependency, searches all files by default."""
    pattern = inputs.get('pattern', '')
    directory = inputs.get('directory', root)
    file_ext = inputs.get('file_ext', '')
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f'[Invalid pattern: {e}]'
    root_real = os.path.realpath(root)
    results = []
    for dirpath, _, filenames in os.walk(directory):
        for fname in filenames:
            if file_ext and not fname.endswith(file_ext):
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


def _derive_java_dest(content: str, filename: str, codebase_root: str) -> str | None:
    """
    Derive the correct codebase path for a generated Java file from its package declaration.
    Returns absolute path or None if package cannot be determined.
    """
    m = re.search(r'^\s*package\s+([\w.]+)\s*;', content, re.MULTILINE)
    if not m:
        return None
    pkg = m.group(1)
    pkg_path = pkg.replace('.', os.sep)
    src_roots = _find_java_src_roots(codebase_root)
    for root in src_roots:
        dest_dir = os.path.join(root, pkg_path)
        if os.path.isdir(dest_dir):
            return os.path.join(dest_dir, filename)
    # Fallback: use first src root even if directory doesn't exist yet
    dest_dir = os.path.join(src_roots[0], pkg_path)
    return os.path.join(dest_dir, filename)


def _derive_python_dest(content: str, filename: str, codebase_root: str) -> str | None:
    """
    Derive the correct codebase path for a generated Python file.
    Looks for '# module: foo.bar' comment or uses the package structure.
    """
    m = re.search(r'^#\s*module:\s*([\w.]+)', content, re.MULTILINE)
    if not m:
        return None
    mod = m.group(1)
    mod_path = mod.replace('.', os.sep) + '.py'
    # Try common source roots
    for src_root_name in ('src', 'lib', ''):
        candidate = os.path.join(codebase_root, src_root_name, mod_path) if src_root_name else os.path.join(codebase_root, mod_path)
        parent = os.path.dirname(candidate)
        if os.path.isdir(parent):
            return candidate
    return None


async def _run_codegen_loop(
    system, user_msg, out_dir, cfg, client, model,
    codebase_root=None, symbol_index=None, tracker=None,
    language: str = 'java', update_codebase: bool = False,
    progress_cb=None,
):
    """
    Tool-use loop for code generation (Claude Code pattern).
    write_file: write to output directory (and optionally codebase with --update).
    compile_check: runs javac/py_compile and returns errors for the LLM to fix.
    read_file, search_code, query_symbols: codebase lookup (rarely needed with rich orientation).
    """
    messages = [{'role': 'user', 'content': user_msg}]
    count = 0
    if tracker is None:
        tracker = UsageTracker()

    tools = list(_BASE_CODEGEN_TOOLS)
    if codebase_root and symbol_index is not None:
        tools += _CODEBASE_TOOLS
    if codebase_root and language in ('java', 'python'):
        tools = tools + [_COMPILE_CHECK_TOOL]

    for _ in range(_MAX_CODEGEN_TURNS):
        messages = await _compact_messages(messages, cfg, client, model, tracker=tracker)

        response = await api_call_with_backoff(
            client.messages.create,
            model=model,
            max_tokens=cfg.max_tokens,
            tools=tools,
            system=system,
            messages=messages,
        )
        tracker.record(response)

        tool_uses = [b for b in response.content if b.type == 'tool_use']

        if tool_uses:
            messages.append({'role': 'assistant', 'content': response.content})
            results = []
            for tu in tool_uses:
                name = tu.name

                if name == 'write_file':
                    filename = tu.input.get('filename', '').strip()
                    content = tu.input.get('content', '').strip()
                    if filename and content:
                        path = os.path.join(out_dir, filename)
                        parent = os.path.dirname(path)
                        if parent:
                            os.makedirs(parent, exist_ok=True)
                        await asyncio.to_thread(_write_one_file, path, content)
                        count += 1
                        yield ('file', filename, count)
                        result_text = f'Written: {filename}'
                        # --update: copy to correct location in the codebase
                        if update_codebase and codebase_root:
                            clean = _strip_fences(content)
                            if language == 'java':
                                dest = _derive_java_dest(clean, filename, codebase_root)
                            elif language == 'python':
                                dest = _derive_python_dest(clean, filename, codebase_root)
                            else:
                                dest = None
                            if dest:
                                os.makedirs(os.path.dirname(dest), exist_ok=True)
                                await asyncio.to_thread(_write_one_file, dest, clean)
                                yield ('update', dest, count)
                    else:
                        result_text = 'Error: filename and content are required'

                elif name == 'compile_check' and codebase_root:
                    cc_filename = tu.input.get('filename', '').strip()
                    written_path = os.path.join(out_dir, cc_filename)
                    if not cc_filename or not os.path.isfile(written_path):
                        result_text = f'File not found: {cc_filename!r} — call write_file first'
                    elif language == 'java':
                        result_text = await _run_compile_check(written_path, codebase_root)
                    elif language == 'python':
                        result_text = await _run_python_compile_check(written_path)
                    else:
                        result_text = 'compile_check not supported for this language'
                    if progress_cb:
                        progress_cb(f'  [compile_check: {result_text[:120]}]\n')

                elif name == 'read_file':
                    filename = tu.input.get('filename', '').strip()
                    out_path = os.path.join(out_dir, filename) if filename else ''
                    cb_path = os.path.join(codebase_root, filename) if (filename and codebase_root) else ''
                    if filename and os.path.isfile(out_path):
                        try:
                            content = open(out_path, encoding='utf-8').read()
                            result_text = content[:_MAX_FILE_READ_CHARS]
                        except OSError as e:
                            result_text = f'Error: {e}'
                    elif cb_path and os.path.isfile(cb_path):
                        try:
                            content = open(cb_path, encoding='utf-8').read()
                            result_text = content[:_MAX_FILE_READ_CHARS]
                        except OSError as e:
                            result_text = f'Error: {e}'
                    else:
                        result_text = f'File not found: {filename}'

                elif name == 'search_code' and codebase_root:
                    result_text = _gen_search_code(tu.input, codebase_root)

                elif name == 'query_symbols' and symbol_index is not None:
                    from codebase_analyzer import _tool_query_symbols
                    result_text = _tool_query_symbols(tu.input, symbol_index)

                else:
                    result_text = f'Unknown tool: {name}'

                results.append({
                    'type': 'tool_result',
                    'tool_use_id': tu.id,
                    'content': result_text,
                })
            messages.append({'role': 'user', 'content': results})
            continue

        if response.stop_reason == 'max_tokens':
            messages.append({'role': 'assistant', 'content': response.content})
            messages.append({'role': 'user', 'content': 'Continue writing the remaining files using write_file.'})
            continue

        break

    yield ('summary', tracker.summary('Phase 2: Code Generation'), count)


def _strip_fences(content: str) -> str:
    content = content.strip()
    if content.startswith('```'):
        content = re.sub(r'^```[^\n]*\n?', '', content)
        content = re.sub(r'\n?```\s*$', '', content)
    return content.strip()


def _write_one_file(path: str, content: str) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(_strip_fences(content))


async def run_coder(code_policy_text, queue, version, version_mgr, cfg, client, model, stop_event):
    """Ph2 loop. Yields SSE-ready dicts."""
    recovered = await asyncio.to_thread(queue.recover_processing)
    if recovered:
        yield {"stage": "recovered", "count": recovered}

    meta = await asyncio.to_thread(version_mgr.get_meta, version)
    coded_total = meta.java_file_count
    java_dir = version_mgr.java_dir(version)
    system = code_policy_text + _WRITE_FILE_INSTRUCTION

    while True:
        item = await asyncio.to_thread(queue.dequeue)
        if item is None:
            if stop_event.is_set():
                break
            await asyncio.sleep(3)
            current_meta = await asyncio.to_thread(version_mgr.get_meta, version)
            counts = await asyncio.to_thread(queue.counts)
            ph1_done = current_meta.status in ("coding", "done")
            queue_empty = counts["pending"] == 0 and counts["processing"] == 0
            if ph1_done and queue_empty:
                break
            continue

        try:
            eq_text = _format_equations_for_coding(item.equations)
            user_msg = f"Generate code for these {len(item.equations)} alpha equation(s):\n\n{eq_text}"
            batch_count = 0

            async for etype, payload, count in _run_codegen_loop(system, user_msg, java_dir, cfg, client, model):
                if etype == 'summary':
                    yield {"stage": "usage_summary", "text": payload + '\n', "phase": "code"}
                    continue
                filename = payload
                batch_count = count
                coded_total += 1
                await asyncio.to_thread(version_mgr.update_meta, version, java_file_count=coded_total)
                yield {"stage": "token", "text": f"[Written: {filename}]\n", "phase": "code"}

            await asyncio.to_thread(queue.mark_done, item)
            yield {"stage": "code_batch_done", "batch_id": item.id, "count": batch_count, "total": coded_total}

        except Exception as e:
            await asyncio.to_thread(queue.mark_failed, item, str(e))
            yield {"stage": "error", "text": str(e), "batch_id": item.id}

    await asyncio.to_thread(version_mgr.update_meta, version, status="done")
    yield {"stage": "code_complete", "total": coded_total}


def _format_equations_for_coding(equations: list) -> str:
    return "\n\n---\n\n".join(eq.get("raw_markdown", str(eq)) for eq in equations)
