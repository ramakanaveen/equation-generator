import asyncio
import os
import re

from generator import _call_with_continuation


async def run_coder(code_policy_text, queue, version, version_mgr, cfg, client, model, stop_event):
    """
    Ph2 loop. Yields SSE-ready dicts.
    Drains the queue. Exits when queue is empty AND stop_event is set.
    All blocking I/O is offloaded to a thread so the event loop stays free.
    Safe to restart: recovers orphaned processing items and resumes from existing file count.
    """
    # Recover any items stuck in processing from a previous interrupted run
    recovered = await asyncio.to_thread(queue.recover_processing)
    if recovered:
        yield {"stage": "recovered", "count": recovered}

    # Resume from existing count so meta doesn't reset to 0
    meta = await asyncio.to_thread(version_mgr.get_meta, version)
    coded_total = meta.java_file_count
    java_dir = version_mgr.java_dir(version)

    while True:
        item = await asyncio.to_thread(queue.dequeue)
        if item is None:
            if stop_event.is_set():
                break
            # Auto-exit if Ph1 is done and queue is fully drained
            current_meta = await asyncio.to_thread(version_mgr.get_meta, version)
            counts = await asyncio.to_thread(queue.counts)
            ph1_done = current_meta.status in ("coding", "done")
            queue_empty = counts["pending"] == 0 and counts["processing"] == 0
            if ph1_done and queue_empty:
                break
            await asyncio.sleep(1.5)
            continue

        try:
            eq_text = _format_equations_for_coding(item.equations)
            user_msg = f"Generate Java code for these {len(item.equations)} alpha equations:\n\n{eq_text}"

            full_code = ""
            async for chunk in _call_with_continuation(
                system=code_policy_text,
                messages=[{"role": "user", "content": user_msg}],
                cfg=cfg,
                client=client,
                model=model,
            ):
                full_code += chunk
                yield {"stage": "token", "text": chunk, "phase": "code"}

            count = await asyncio.to_thread(_write_java_files, full_code, java_dir)
            await asyncio.to_thread(queue.mark_done, item)
            coded_total += count
            await asyncio.to_thread(version_mgr.update_meta, version, java_file_count=coded_total)
            yield {"stage": "code_batch_done", "batch_id": item.id, "count": count, "total": coded_total}

        except Exception as e:
            await asyncio.to_thread(queue.mark_failed, item, str(e))
            yield {"stage": "error", "text": str(e), "batch_id": item.id}

    await asyncio.to_thread(version_mgr.update_meta, version, status="done")
    yield {"stage": "code_complete", "total": coded_total}


def _format_equations_for_coding(equations: list) -> str:
    return "\n\n---\n\n".join(eq.get("raw_markdown", str(eq)) for eq in equations)


def _write_java_files(code_text: str, java_dir: str) -> int:
    """Blocking: parse and write Java files. Runs in thread pool."""
    pattern = r"=== FILE: (.+?) ===\n(.*?)=== END FILE ==="
    matches = re.findall(pattern, code_text, re.DOTALL)
    for filename, content in matches:
        path = os.path.join(java_dir, filename.strip())
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.strip())
    return len(matches)
