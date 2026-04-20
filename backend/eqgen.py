#!/usr/bin/env python3
"""CLI: generate a single alpha equation via Claude."""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from config import cfg
from providers import AnthropicProvider, VertexProvider
from generator import _call_with_continuation

POLICY_DIR = os.path.join(os.path.dirname(__file__), "policy")


async def main():
    parser = argparse.ArgumentParser(description="Generate one alpha equation")
    parser.add_argument("--objective", "-o", default="", help="Additional objective")
    parser.add_argument("--file", "-f", default=None, help="Also write output to this file")
    args = parser.parse_args()

    with open(os.path.join(POLICY_DIR, "policy.md")) as f:
        policy = f.read()

    provider = VertexProvider(cfg) if cfg.provider == "vertex" else AnthropicProvider(cfg)
    client = provider.get_client()
    model = provider.model_name

    user_msg = "Generate exactly 1 alpha equation following all rules in the policy."
    if args.objective:
        user_msg += f" Additional objective: {args.objective}"

    result = ""
    async for chunk in _call_with_continuation(
        system=policy,
        messages=[{"role": "user", "content": user_msg}],
        cfg=cfg, client=client, model=model,
    ):
        print(chunk, end="", flush=True)
        result += chunk

    print()
    if args.file:
        with open(args.file, "w") as f:
            f.write(result)
        print(f"[Written to {args.file}]", file=sys.stderr)


asyncio.run(main())
