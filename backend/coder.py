import asyncio
import os

from generator import _call_with_continuation


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

_WRITE_FILE_INSTRUCTION = """

---

## File Output Method
Use the write_file tool to output each file — one tool call per file.
Do NOT use === FILE: === text delimiters.
Write AlphaExpression.java first (if applicable), then one file per equation.
"""

_MAX_CODEGEN_TURNS = 40  # generous guard for large batches


async def _run_codegen_loop(system, user_msg, java_dir, cfg, client, model):
    """
    Tool-use loop for Ph2 code generation.
    Yields ('file', filename, count_so_far) for each file written.
    Follows Claude Code / DeepAgents pattern: write_file tool, one file per call.
    Handles max_tokens inline — no delimiter parsing, no fragility at scale.
    """
    messages = [{'role': 'user', 'content': user_msg}]
    count = 0

    for _ in range(_MAX_CODEGEN_TURNS):
        response = await asyncio.to_thread(
            client.messages.create,
            model=model,
            max_tokens=cfg.max_tokens,
            tools=[_WRITE_FILE_TOOL],
            system=system,
            messages=messages,
        )

        tool_uses = [b for b in response.content if b.type == 'tool_use']

        if tool_uses:
            messages.append({'role': 'assistant', 'content': response.content})
            results = []
            for tu in tool_uses:
                filename = tu.input.get('filename', '').strip()
                content = tu.input.get('content', '').strip()
                if filename and content:
                    path = os.path.join(java_dir, filename)
                    parent = os.path.dirname(path)
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                    await asyncio.to_thread(_write_one_file, path, content)
                    count += 1
                    yield ('file', filename, count)
                results.append({
                    'type': 'tool_result',
                    'tool_use_id': tu.id,
                    'content': f'Written: {filename}' if filename else 'Error: missing filename',
                })
            messages.append({'role': 'user', 'content': results})
            continue

        if response.stop_reason == 'max_tokens':
            messages.append({'role': 'assistant', 'content': response.content})
            messages.append({'role': 'user', 'content': 'Continue writing the remaining files using write_file.'})
            continue

        break  # end_turn — all files written


def _write_one_file(path: str, content: str) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


async def run_coder(code_policy_text, queue, version, version_mgr, cfg, client, model, stop_event):
    """
    Ph2 loop. Yields SSE-ready dicts.
    Drains the queue. Exits when queue is empty AND stop_event is set.
    All blocking I/O is offloaded to a thread so the event loop stays free.
    Safe to restart: recovers orphaned processing items and resumes from existing file count.
    """
    recovered = await asyncio.to_thread(queue.recover_processing)
    if recovered:
        yield {"stage": "recovered", "count": recovered}

    meta = await asyncio.to_thread(version_mgr.get_meta, version)
    coded_total = meta.java_file_count
    java_dir = version_mgr.java_dir(version)

    # Append write_file instruction at runtime — code.md is never modified
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
