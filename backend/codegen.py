#!/usr/bin/env python3
"""CLI: generate code for alpha equations via Claude."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

import argparse
from config import cfg
from providers import AnthropicProvider, VertexProvider
from coder import _WRITE_FILE_TOOL, _WRITE_FILE_INSTRUCTION, _write_one_file
from generator import api_call_with_backoff

POLICY_DIR = os.path.join(os.path.dirname(__file__), "policy")
_MAX_CODEGEN_TURNS = 40


async def _run_codegen_loop(system, user_msg, out_dir, profile, client, model, cfg):
    """
    Tool-use loop for CLI code generation.
    Writes files via write_file tool calls — one file per call.
    When profile provided (--codebase), verifies each file immediately after writing.
    """
    from codebase_analyzer import verify_generated_code

    messages = [{'role': 'user', 'content': user_msg}]

    for _ in range(_MAX_CODEGEN_TURNS):
        response = await api_call_with_backoff(
            client.messages.create,
            model=model,
            max_tokens=cfg.max_tokens,
            tools=[_WRITE_FILE_TOOL],
            system=system,
            messages=messages,
        )

        tool_uses = [b for b in response.content if b.type == 'tool_use']
        text_blocks = [b for b in response.content if b.type == 'text']

        for b in text_blocks:
            if b.text:
                print(b.text, end='', flush=True)

        if tool_uses:
            messages.append({'role': 'assistant', 'content': response.content})
            results = []
            for tu in tool_uses:
                filename = tu.input.get('filename', '').strip()
                content = tu.input.get('content', '').strip()

                if not filename or not content:
                    results.append({
                        'type': 'tool_result',
                        'tool_use_id': tu.id,
                        'content': 'Error: filename and content are required',
                    })
                    continue

                # Per-file verification when codebase profile available
                if profile:
                    corrected = await verify_generated_code(content, profile, client, model, cfg)
                    if corrected:
                        print(f'\n[{filename}: issues found — corrections applied]', file=sys.stderr)
                        content = corrected
                    else:
                        print(f'\n[{filename}: verified ✓]', file=sys.stderr)

                if out_dir:
                    path = os.path.join(out_dir, filename)
                    parent = os.path.dirname(path)
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                    await asyncio.to_thread(_write_one_file, path, content)
                    print(f'[Written: {path}]', file=sys.stderr)
                else:
                    # No --dir: print file to stdout with a header
                    print(f'\n// === {filename} ===\n{content}')

                results.append({
                    'type': 'tool_result',
                    'tool_use_id': tu.id,
                    'content': f'Written: {filename}',
                })
            messages.append({'role': 'user', 'content': results})
            continue

        if response.stop_reason == 'max_tokens':
            messages.append({'role': 'assistant', 'content': response.content})
            messages.append({'role': 'user', 'content': 'Continue writing the remaining files using write_file.'})
            continue

        break  # end_turn


async def main():
    parser = argparse.ArgumentParser(description="Generate code for alpha equations")
    parser.add_argument(
        "--input", "-i", default=None,
        help="Equation markdown file. Omit to read from stdin (supports piping from eqgen.py)",
    )
    parser.add_argument(
        "--dir", "-d", default=None,
        help="Output directory to write files into",
    )
    parser.add_argument(
        "--codebase", "-c", default=None,
        help="Path to local project root for codebase-aware generation (any language)",
    )
    args = parser.parse_args()

    with open(os.path.join(POLICY_DIR, "code.md")) as f:
        code_policy = f.read()

    if args.input:
        with open(args.input) as f:
            equation_text = f.read()
    else:
        equation_text = sys.stdin.read()

    if not equation_text.strip():
        print("Error: no equation input provided.", file=sys.stderr)
        sys.exit(1)

    provider = VertexProvider(cfg) if cfg.provider == "vertex" else AnthropicProvider(cfg)
    client = provider.get_client()
    model = provider.model_name

    # Phase 1: codebase analysis (only when --codebase is set)
    profile = None
    if args.codebase:
        from codebase_analyzer import analyze_codebase
        cb_path = os.path.realpath(args.codebase)
        if not os.path.isdir(cb_path):
            print(f"Error: --codebase path is not a directory: {args.codebase}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Phase 1: Analyzing codebase at {cb_path}]", file=sys.stderr)
        profile = await analyze_codebase(
            root_path=cb_path,
            equation_text=equation_text,
            client=client,
            model=model,
            cfg=cfg,
            progress_cb=lambda t: print(t, end="", flush=True, file=sys.stderr),
        )
        code_policy += f"\n\n---\n\n## Target Codebase\n\n{profile}"
        print("\n\n[Phase 2: Generating code]\n", file=sys.stderr)
    else:
        print("[Generating code]\n", file=sys.stderr)

    # Append write_file instruction at runtime — code.md is never modified
    code_policy += _WRITE_FILE_INSTRUCTION

    user_msg = f"Generate code for this alpha equation:\n\n{equation_text}"
    await _run_codegen_loop(code_policy, user_msg, args.dir, profile, client, model, cfg)
    print()


asyncio.run(main())
