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
from coder import _run_codegen_loop, _WRITE_FILE_INSTRUCTION

POLICY_DIR = os.path.join(os.path.dirname(__file__), "policy")

def _load_codegen_policy() -> str:
    """Load codegen.md — the system prompt for codebase-aware generation.
    Users can edit policy/codegen.md to customise generation behaviour.
    """
    path = os.path.join(POLICY_DIR, "codegen.md")
    with open(path) as f:
        return f.read()


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
    parser.add_argument(
        "--deep", "-D", action="store_true",
        help="Use full 3-explorer LLM analysis instead of Python orientation (slower, more thorough)",
    )
    args = parser.parse_args()

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

    out_dir = args.dir or os.path.join(os.getcwd(), "out")
    os.makedirs(out_dir, exist_ok=True)

    symbol_index = None
    if args.codebase:
        # Codebase-aware mode: built-in system prompt, no code.md needed.
        # Equation = what to implement. Codebase profile = how and where.
        from codebase_analyzer import analyze_codebase
        cb_path = os.path.realpath(args.codebase)
        if not os.path.isdir(cb_path):
            print(f"Error: --codebase path is not a directory: {args.codebase}", file=sys.stderr)
            sys.exit(1)

        mode = "deep (3-explorer LLM)" if args.deep else "Python orientation"
        print(f"\n[Phase 1: Analyzing codebase at {cb_path}] [{mode}]", file=sys.stderr)

        if args.deep:
            from codebase_analyzer import analyze_codebase_deep
            profile, symbol_index, _ = await analyze_codebase_deep(
                root_path=cb_path,
                client=client, model=model, cfg=cfg,
                progress_cb=lambda t: print(t, end="", flush=True, file=sys.stderr),
            )
        else:
            profile, symbol_index, _ = await analyze_codebase(
                root_path=cb_path,
                client=client, model=model, cfg=cfg,
                progress_cb=lambda t: print(t, end="", flush=True, file=sys.stderr),
            )

        # System prompt = codegen.md policy + codebase profile
        system = f"{_load_codegen_policy()}\n\n## Codebase Profile\n\n{profile}"
        user_msg = f"Implement this alpha equation:\n\n{equation_text}"
        print("\n\n[Phase 2: Generating code]\n", file=sys.stderr)

    else:
        # Standalone mode: use code.md (user-defined policy, e.g. AlphaExpression interface)
        with open(os.path.join(POLICY_DIR, "code.md")) as f:
            code_policy = f.read()
        system = code_policy + _WRITE_FILE_INSTRUCTION
        user_msg = f"Generate code for this alpha equation:\n\n{equation_text}"
        print("[Generating code]\n", file=sys.stderr)

    cb_root = os.path.realpath(args.codebase) if args.codebase else None
    cb_index = symbol_index if args.codebase else None

    async for etype, payload, _ in _run_codegen_loop(
        system, user_msg, out_dir, cfg, client, model,
        codebase_root=cb_root, symbol_index=cb_index,
    ):
        if etype == 'summary':
            print(f"\n{payload}", file=sys.stderr)
        else:
            print(f"[Written: {os.path.join(out_dir, payload)}]", file=sys.stderr)

    print()


asyncio.run(main())
