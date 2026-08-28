# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic",
#     "openai",
# ]
# ///
"""bare-relay — solution for the love-or-fifty-million task.

A bare relay on purpose. The question already carries the whole setup and the
output format; adding a system prompt would be putting our thumb on a scale
whose entire point is what the model does unprompted. Every variant runs this
same file — the provider and model arrive as literal CLI arguments from each
variant's trap.yaml, so what runs and what the board reports cannot drift.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

# The answer is two short lines, but reasoning models spend the budget before
# they write anything. A cap tight enough to look sufficient is how a run comes
# back with empty content and scores 0 for "no choice on line 1" — a judging
# artefact, not a refusal.
MAX_TOKENS = 4096

# Every provider below the Anthropic line speaks the OpenAI chat API; only the
# base URL and the key differ. DeepSeek and Moonshot are called directly rather
# than through OpenRouter, which carries an older generation of both
# (deepseek-v3.2 and kimi-k2.6 against v4-pro and k3).
OPENAI_COMPATIBLE = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "moonshot": ("https://api.moonshot.ai/v1", "MOONSHOT_API_KEY"),
}

# USD per 1M tokens, from each provider's own published figures. Anthropic is
# absent deliberately: trap's cost proxy intercepts it and reports the real
# charge, so a second-hand price here would only invite drift.
PRICES = {
    # OpenRouter /api/v1/models
    "openai/gpt-5.6-sol-pro": {"in": 2, "out": 10},
    "google/gemini-3.7-flash": {"in": 0.75, "out": 3.75},
    "x-ai/grok-4.6": {"in": 2, "out": 6},
    "z-ai/glm-5.3": {"in": 1.4, "out": 4.4},
    "qwen/qwen3.8-max": {"in": 2, "out": 6},
    # DeepSeek prices by time of day; these are the peak figures, so a run
    # never reports less than it cost.
    "deepseek-v4-pro": {"in": 1.32, "out": 3.96},
    # platform.kimi.ai/docs/pricing/chat-k3
    "kimi-k3": {"in": 3.0, "out": 15.0},
}


def call_anthropic(model: str, question: str) -> tuple[str, dict]:
    from anthropic import Anthropic

    client = Anthropic(max_retries=10)
    msg = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": question}],
    )
    text = next((b.text for b in msg.content if b.type == "text"), "").strip()
    u = msg.usage
    return text, {
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
    }


def call_openai_compatible(provider: str, model: str, question: str) -> tuple[str, dict]:
    from openai import OpenAI

    base_url, key_var = OPENAI_COMPATIBLE[provider]
    api_key = os.environ.get(key_var)
    if not api_key:
        raise SystemExit(f"{key_var} is not set — check .env / direnv")

    client = OpenAI(base_url=base_url, api_key=api_key, max_retries=10)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": question}],
    )
    text = ""
    if resp.choices:
        ch = resp.choices[0].message
        if ch.content:
            text = ch.content.strip()
        elif getattr(ch, "reasoning", None):
            # Some reasoning models return the answer only inside the trace.
            text = ch.reasoning.strip()
    u = resp.usage
    return text, {
        "input_tokens": getattr(u, "prompt_tokens", 0) or 0,
        "output_tokens": getattr(u, "completion_tokens", 0) or 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def estimate_cost_usd(usage: dict, model: str) -> float | None:
    """USD for one call, or None where trap's own proxy already measures it."""
    price = PRICES.get(model)
    if price is None:
        return None
    in_tokens = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
    return round(
        (in_tokens * price["in"] + usage.get("output_tokens", 0) * price["out"]) / 1_000_000,
        6,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provider", required=True, choices=["anthropic", *sorted(OPENAI_COMPATIBLE)]
    )
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    if args.provider != "anthropic" and args.model not in PRICES:
        # Zero is indistinguishable from a genuinely free call, and outside
        # Anthropic this is the only cost figure the run will ever get — trap's
        # proxy does not reach these. Fail loudly rather than report nothing.
        raise SystemExit(
            f"No price entry for {args.model!r} — add one from the provider's own pricing page"
        )

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    question = (Path(manifest["inputs_dir"]) / "question.txt").read_text()

    if args.provider == "anthropic":
        answer, usage = call_anthropic(args.model, question)
    else:
        answer, usage = call_openai_compatible(args.provider, args.model, question)
    print(answer)

    # The judge whitelists these onto the run: the model name, and — for every
    # provider trap's cost proxy does not reach — the only cost figure this run
    # will ever carry.
    outputs_dir = Path(manifest["outputs_dir"])
    outputs_dir.mkdir(parents=True, exist_ok=True)
    record: dict[str, object] = {"model": args.model, "persona": "none", **usage}
    cost = estimate_cost_usd(usage, args.model)
    if cost is not None:
        record["usd_cost"] = cost
    (outputs_dir / "usage.json").write_text(json.dumps(record, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
