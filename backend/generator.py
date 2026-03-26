import asyncio
import os

from equation_parser import parse_equations


async def _call_with_continuation(system: str, messages: list, cfg, client, model: str):
    """
    Async generator yielding text chunks.
    Handles stop_reason == "max_tokens" via continuation messages.
    """
    for _ in range(cfg.max_continuations + 1):
        response = await asyncio.to_thread(
            client.messages.create,
            model=model,
            max_tokens=cfg.max_tokens,
            system=system,
            messages=messages,
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        yield text
        if response.stop_reason != "max_tokens":
            return
        messages = messages + [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": "Continue exactly where you left off. Do not repeat anything already written."},
        ]


async def run_generator(policy_text, objective, queue, version, version_mgr, cfg, client, model, stop_event):
    """
    Ph1 loop. Yields SSE-ready dicts.
    Runs until stop_event is set OR target_count reached.
    All blocking I/O is offloaded to a thread so the event loop stays free.
    """
    generated_total = 0
    batch_number = 0
    eq_dir = version_mgr.equations_dir(version)

    while not stop_event.is_set():
        if cfg.target_count > 0 and generated_total >= cfg.target_count:
            break

        remaining = (cfg.target_count - generated_total) if cfg.target_count > 0 else cfg.eq_batch_size
        ask_count = min(cfg.eq_batch_size, remaining)

        user_msg = (
            f"Generate exactly {ask_count} alpha equations following all rules in the policy. "
            f"This is batch {batch_number + 1}. Total equations already generated in previous batches: {generated_total}. "
            f"{('Additional objective: ' + objective) if objective else ''}"
        )

        full_text = ""
        async for chunk in _call_with_continuation(
            system=policy_text,
            messages=[{"role": "user", "content": user_msg}],
            cfg=cfg,
            client=client,
            model=model,
        ):
            full_text += chunk
            yield {"stage": "token", "text": chunk, "phase": "equations"}

        # All blocking work offloaded to thread pool
        batch_file = os.path.join(eq_dir, f"batch_{batch_number + 1:03d}.md")
        equations = await asyncio.to_thread(_process_batch, full_text, batch_file, queue, batch_number)

        generated_total += len(equations)
        batch_number += 1
        await asyncio.to_thread(version_mgr.update_meta, version, equation_count=generated_total)

        yield {"stage": "batch_done", "batch": batch_number, "count": len(equations), "total": generated_total}

    await asyncio.to_thread(version_mgr.update_meta, version, status="coding")
    yield {"stage": "gen_complete", "total": generated_total}


def _process_batch(full_text: str, batch_file: str, queue, batch_number: int) -> list:
    """Blocking: write file + parse + enqueue. Runs in thread pool."""
    with open(batch_file, "w", encoding="utf-8") as f:
        f.write(full_text)
    equations = parse_equations(full_text)
    queue.enqueue(equations, batch_number)
    return equations
