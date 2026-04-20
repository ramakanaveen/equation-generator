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
    if args.dir:
        _write_java_files(result, args.dir)


def _write_java_files(code_text: str, out_dir: str):
    pattern = r"=== FILE: (.+?) ===\n(.*?)=== END FILE ==="
    matches = re.findall(pattern, code_text, re.DOTALL)
    if not matches:
        print("[No === FILE: ... === blocks found in output]", file=sys.stderr)
        return
    os.makedirs(out_dir, exist_ok=True)
    for filename, content in matches:
        path = os.path.join(out_dir, filename.strip())
        with open(path, "w") as f:
            f.write(content.strip())
        print(f"[Written: {path}]", file=sys.stderr)


asyncio.run(main())
