import asyncio
import os
import re

from generator import _call_with_continuation, api_call_with_backoff


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
        'Read a file you previously wrote to verify its content is correct. '
        'If you find issues, call write_file again with the corrected content.'
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'filename': {
                'type': 'string',
                'description': 'Filename to read (same name used in write_file)',
            },
        },
        'required': ['filename'],
    },
}

_CODEGEN_TOOLS = [_WRITE_FILE_TOOL, _READ_FILE_TOOL]

_WRITE_FILE_INSTRUCTION = """

---

## File Output Method
Use the write_file tool to output each file — one tool call per file.
Do NOT use === FILE: === text delimiters.
Write AlphaExpression.java first (if applicable), then one file per equation.
After writing each file, use read_file to verify the content is correct.
If you find issues, call write_file again with the corrected content.
"""

_MAX_CODEGEN_TURNS = 60  # generous — includes read_file + correction turns


async def _run_codegen_loop(system, user_msg, out_dir, cfg, client, model):
    """
    Tool-use loop for Ph2 code generation (Claude Code pattern).
    write_file: writes file to disk, yields ('file', filename, count).
    read_file:  reads back what was written so LLM can self-verify inline.
    No separate verifier call — LLM decides correctness within this loop.
    """
    messages = [{'role': 'user', 'content': user_msg}]
    count = 0

    for _ in range(_MAX_CODEGEN_TURNS):
        response = await api_call_with_backoff(
            client.messages.create,
            model=model,
            max_tokens=cfg.max_tokens,
            tools=_CODEGEN_TOOLS,
            system=system,
            messages=messages,
        )

        tool_uses = [b for b in response.content if b.type == 'tool_use']

        if tool_uses:
            messages.append({'role': 'assistant', 'content': response.content})
            results = []
            for tu in tool_uses:
                if tu.name == 'write_file':
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
                    else:
                        result_text = 'Error: filename and content are required'

                elif tu.name == 'read_file':
                    filename = tu.input.get('filename', '').strip()
                    path = os.path.join(out_dir, filename) if filename else ''
                    if filename and os.path.isfile(path):
                        try:
                            result_text = open(path, encoding='utf-8').read()
                        except OSError as e:
                            result_text = f'Error reading {filename}: {e}'
                    else:
                        result_text = f'File not found: {filename}'
                else:
                    result_text = f'Unknown tool: {tu.name}'

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

        break  # end_turn — all files written and verified


def _strip_fences(content: str) -> str:
    """Safety net: remove markdown code fences if LLM wrapped content despite tool instructions."""
    content = content.strip()
    if content.startswith('```'):
        content = re.sub(r'^```[^\n]*\n?', '', content)
        content = re.sub(r'\n?```\s*$', '', content)
    return content.strip()


def _write_one_file(path: str, content: str) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(_strip_fences(content))


async def run_coder(code_policy_text, queue, version, version_mgr, cfg, client, model, stop_event):
    """
    Ph2 loop. Yields SSE-ready dicts.
    Drains the queue. Exits when queue is empty AND stop_event is set.
    """
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

            async for _, filename, count in _run_codegen_loop(system, user_msg, java_dir, cfg, client, model):
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
