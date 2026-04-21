#!/usr/bin/env python3
"""CLI: generate Java code for a single alpha equation via Claude."""
import argparse
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from config import cfg
from providers import AnthropicProvider, VertexProvider
from generator import _call_with_continuation

POLICY_DIR = os.path.join(os.path.dirname(__file__), "policy")


async def main():
    parser = argparse.ArgumentParser(description="Generate Java code for one alpha equation")
    parser.add_argument(
        "--input", "-i", default=None,
        help="Equation markdown file. Omit to read from stdin (supports piping from eqgen.py)",
    )
    parser.add_argument(
        "--dir", "-d", default=None,
        help="Output directory to write .java files into",
    )
    parser.add_argument(
        "--codebase", "-c", default=None,
        help="Path to local Java project root for codebase-aware generation",
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

    # Provider created before codebase block (needed for analysis)
    provider = VertexProvider(cfg) if cfg.provider == "vertex" else AnthropicProvider(cfg)
    client = provider.get_client()
    model = provider.model_name

    # Phase 1: codebase analysis (only when --codebase is set)
    profile = None
    if args.codebase:
        from codebase_analyzer import analyze_codebase, verify_generated_code
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
        print("[Generating code (no codebase provided)]\n", file=sys.stderr)

    # Phase 2: generate
    user_msg = f"Generate Java code for this alpha equation:\n\n{equation_text}"
    result = ""
    async for chunk in _call_with_continuation(
        system=code_policy,
        messages=[{"role": "user", "content": user_msg}],
        cfg=cfg, client=client, model=model,
    ):
        print(chunk, end="", flush=True)
        result += chunk
    print()

    # Phase 3: verify (only when codebase was provided)
    if profile:
        print("\n[Phase 3: Verifying output]\n", file=sys.stderr)
        corrected = await verify_generated_code(result, profile, client, model, cfg)
        if corrected:
            print("[Issues found — corrections applied]\n", file=sys.stderr)
            result = corrected
        else:
            print("[Verified ✓]\n", file=sys.stderr)

    if args.dir:
        _write_files(result, args.dir)


def _write_files(code_text: str, out_dir: str):
    pattern = r"=== FILE: (.+?) ===\n(.*?)=== END FILE ==="
    matches = re.findall(pattern, code_text, re.DOTALL)
    if not matches:
        print("[No === FILE: ... === blocks found in output]", file=sys.stderr)
        return
    os.makedirs(out_dir, exist_ok=True)
    for filename, content in matches:
        path = os.path.join(out_dir, filename.strip())
        # Create intermediate dirs (e.g. trading/signals/foo.py)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        content = content.strip()
        # Strip markdown code fences if Claude wrapped the content
        if content.startswith('```'):
            content = re.sub(r'^```\w*\n?', '', content)
            content = re.sub(r'\n?```$', '', content)
        with open(path, "w") as f:
            f.write(content.strip())
        print(f"[Written: {path}]", file=sys.stderr)


asyncio.run(main())
