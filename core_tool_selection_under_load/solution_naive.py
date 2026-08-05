# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic",
# ]
# ///
"""Naive-text variant for core_tool_selection_under_load.

Sends inputs/<id>/prompt.txt verbatim as a plain text user message -- the
tool catalog stays as JSON text inside the prompt, NOT passed via the
provider's native `tools` parameter. The model has to read the catalog and
reply with JSON itself, no tool-calling machinery involved.

This is the "flat context aggregation" pattern the circulating regression
claims describe (as opposed to solution.py's native tool_choice="any",
which is what most real agent frameworks actually do). Comparing this
variant's by-category breakdown against solution.py's isolates whether any
degradation comes from stacking itself, or specifically from not using
native tool-calling to present the catalog.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def call_anthropic(model: str, prompt: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(max_retries=10)
    kwargs = {}
    if any(model.startswith(f"claude-{fam}-5") for fam in ("opus", "sonnet", "fable")):
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": "low"}
        kwargs["max_tokens"] = 4096
    else:
        kwargs["max_tokens"] = 1024

    msg = client.messages.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    content = "".join(b.text for b in msg.content if b.type == "text").strip()
    if not content:
        print(f"[call_anthropic] empty content: stop_reason={msg.stop_reason!r}", file=sys.stderr)
    return content


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])
    prompt = (inputs_dir / "prompt.txt").read_text()

    answer = call_anthropic(args.model, prompt)
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
