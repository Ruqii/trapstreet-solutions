# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic",
#     "openai",
# ]
# ///
"""No-skill baseline -- shared across model/provider variants and across
tasks (python_bugfix_diff, ab_test_planning, influencer_marketing_disclosure).

Sends question.txt verbatim as the only message, with no system prompt, no
SKILL.md, no reference files. Each task's question.txt is already a
self-contained spec (role framing + the exact required JSON output format),
so this is the zero point any skill solution has to clear to prove it's
earning its keep over a bare model.

Each variant directory (../claude-opus-4-8, ../gpt-5.6-luna-pro, ...) picks
the provider and model via CLI args in its own trap.yaml `cmd:` line -- not
an env var -- so profile.model (self-reported, shown on the leaderboard) and
the model actually used can never drift out of sync.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def call_anthropic(model: str, question: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(max_retries=10)
    msg = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": question}],
    )
    return next((b.text for b in msg.content if b.type == "text"), "").strip()


def call_openrouter(model: str, question: str) -> str:
    from openai import OpenAI

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
    resp = client.chat.completions.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": question}],
    )
    return (resp.choices[0].message.content or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True, choices=["anthropic", "openrouter"])
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])
    question = (inputs_dir / "question.txt").read_text()

    if args.provider == "anthropic":
        answer = call_anthropic(args.model, question)
    else:
        answer = call_openrouter(args.model, question)

    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
