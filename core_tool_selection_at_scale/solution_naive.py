# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic",
#     "openai",
# ]
# ///
"""Flat-text variant for core_tool_selection_at_scale.

Sends inputs/<id>/prompt.txt verbatim as a plain user message -- the tool
catalog stays as JSON text inside the prompt, NOT passed through the
provider's native tools parameter. The model has to read the catalog and reply
with JSON itself, with no tool-calling machinery involved.

This is the "flat context aggregation" pattern the circulating regression
claims specifically describe, as opposed to solution.py's native tool_choice,
which is what most real agent frameworks actually do. Comparing the two
variants' breakdowns isolates whether any degradation comes from catalog size
itself or from how the catalog is presented.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def call_anthropic(model: str, effort: str, prompt: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(max_retries=10)
    kwargs: dict = {}
    if any(model.startswith(f"claude-{fam}-5") for fam in ("opus", "sonnet", "fable")):
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": effort}
        kwargs["max_tokens"] = 8192
    else:
        kwargs["max_tokens"] = 2048

    msg = client.messages.create(model=model, messages=[{"role": "user", "content": prompt}], **kwargs)
    content = "".join(b.text for b in msg.content if b.type == "text").strip()
    if not content:
        print(f"[anthropic] empty content: stop_reason={msg.stop_reason!r}", file=sys.stderr)
    return content


def call_openrouter(model: str, prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        max_retries=5,
    )
    resp = client.chat.completions.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    choice = resp.choices[0]
    content = (choice.message.content or "").strip()
    if not content:
        print(f"[openrouter] empty content: finish_reason={choice.finish_reason!r}", file=sys.stderr)
    return content


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="anthropic", choices=["anthropic", "openrouter"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", default="low", choices=["low", "medium", "high"])
    args = parser.parse_args()

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    prompt = (Path(manifest["inputs_dir"]) / "prompt.txt").read_text()

    if args.provider == "anthropic":
        print(call_anthropic(args.model, args.effort, prompt))
    else:
        print(call_openrouter(args.model, prompt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
