import asyncio
import os
import random
import sys

from equation_parser import parse_equations


async def api_call_with_backoff(fn, *args, max_retries: int = 5, **kwargs):
    """
    Wraps a blocking API call with exponential backoff + jitter on 429 / rate-limit errors.
    Shared utility — used by generator, coder, codegen, codebase_analyzer.
    Follows Claude Code / DeepAgents pattern: retry rate limits, raise everything else.
    """
    for attempt in range(max_retries):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except Exception as e:
            is_rate_limit = (
                '429' in str(e) or
                'rate limit' in str(e).lower() or
                'resource exhausted' in str(e).lower() or
                'too many requests' in str(e).lower()
            )
            if not is_rate_limit or attempt == max_retries - 1:
                raise
            wait = (2 ** attempt) * 5 + random.uniform(0, 2)  # 5s, 12s, 26s, 54s...
            print(f'\n[rate limit — retrying in {wait:.1f}s (attempt {attempt + 1}/{max_retries})]',
                  file=sys.stderr, flush=True)
            await asyncio.sleep(wait)
    raise RuntimeError('unreachable')


async def _call_with_continuation(system: str, messages: list, cfg, client, model: str):
    """
    Async generator yielding text chunks.
    Handles stop_reason == "max_tokens" via continuation messages.
    Retries on 429 via api_call_with_backoff.
    """
    for _ in range(cfg.max_continuations + 1):
        response = await api_call_with_backoff(
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