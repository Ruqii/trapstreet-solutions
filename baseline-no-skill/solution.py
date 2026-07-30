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
import sys
from pathlib import Path


def call_anthropic(model: str, question: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(max_retries=10)
    kwargs = {}
    # Claude 5-family models (opus-5, sonnet-5, fable-5) have adaptive
    # thinking ON by default, and thinking tokens now share the same
    # max_tokens budget as the final answer (unlike older models' separate
    # budget_tokens). At the API default effort ("high"), a 1024-token
    # budget was getting fully consumed by hidden reasoning before any
    # visible text -- empty output on 2/10 cases, and one case truncated
    # mid-JSON exactly at the token ceiling. "low" effort + a much larger
    # ceiling matches this task (single-shot, no tools, no iteration).
    # Gated to the 5-family only so the existing opus-4-8/sonnet-4-6
    # variants (which don't have adaptive thinking) are untouched.
    if any(model.startswith(f"claude-{fam}-5") for fam in ("opus", "sonnet", "fable")):
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": "low"}
        kwargs["max_tokens"] = 8192
    else:
        kwargs["max_tokens"] = 1024

    msg = client.messages.create(
        model=model,
        messages=[{"role": "user", "content": question}],
        **kwargs,
    )
    content = "".join(b.text for b in msg.content if b.type == "text").strip()
    if not content:
        # Diagnostic only -- goes to stderr, never scored (judge reads
        # stdout only) -- so this is safe to leave in permanently.
        thinking_len = sum(
            len(getattr(b, "thinking", "") or "") for b in msg.content if b.type == "thinking"
        )
        print(
            f"[call_anthropic] empty content: stop_reason={msg.stop_reason!r} "
            f"block_types={[b.type for b in msg.content]!r} thinking_len={thinking_len}",
            file=sys.stderr,
        )
    return content


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


def call_moonshot(model: str, question: str) -> str:
    from openai import OpenAI

    # Read the base URL from MOONSHOT_BASE_URL (not hardcoded) so trap-cli's
    # cost-tracking proxy override -- which redirects this exact env var --
    # actually takes effect; trap-cli decides whether to intercept based on
    # MOONSHOT_API_KEY being set in the environment *before* `tp run` starts
    # (e.g. via direnv loading .env when you cd into this directory), not
    # merely inside this subprocess.
    client = OpenAI(
        base_url=os.environ.get("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1"),
        api_key=os.environ["MOONSHOT_API_KEY"],
    )
    resp = client.chat.completions.create(
        model=model,
        # kimi-k3's OpenPlatform API defaults reasoning_effort to "max" --
        # full, unbounded thinking on every call, even a one-shot "spot the
        # bug in this snippet" question. That's what was burning 900-8192+
        # completion tokens per case (2 cases exhausted even an 8192 budget
        # purely on hidden reasoning, finish_reason="length", empty visible
        # content) and driving cost/latency far above the other baselines.
        # "low" is Moonshot's own documented setting for exactly this class
        # of task ("simple coding queries where sub-second responses matter
        # more than deep reasoning"). max_tokens stays generous as a ceiling,
        # not a target -- cost only reflects tokens actually used.
        extra_body={"reasoning_effort": "low"},
        max_tokens=8192,
        messages=[{"role": "user", "content": question}],
    )
    choice = resp.choices[0]
    content = (choice.message.content or "").strip()
    if not content:
        # Diagnostic only -- goes to stderr, never scored (judge reads
        # stdout only) -- so this is safe to leave in permanently.
        extra = getattr(choice.message, "model_extra", None) or {}
        reasoning = extra.get("reasoning_content")
        print(
            f"[call_moonshot] empty content: finish_reason={choice.finish_reason!r} "
            f"reasoning_content_len={len(reasoning) if reasoning else 0}",
            file=sys.stderr,
        )
    return content


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True, choices=["anthropic", "openrouter", "moonshot"])
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])
    question = (inputs_dir / "question.txt").read_text()

    if args.provider == "anthropic":
        answer = call_anthropic(args.model, question)
    elif args.provider == "openrouter":
        answer = call_openrouter(args.model, question)
    else:
        answer = call_moonshot(args.model, question)

    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
