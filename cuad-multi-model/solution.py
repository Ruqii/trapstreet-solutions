"""Multi-model solution for the CUAD contract-clause-extraction task.

Routes the same prompt through different LLMs based on the `MODEL` env var.
Anthropic-prefixed models go through the Anthropic SDK; everything else goes
through OpenRouter (one key, many models).

Switch the engine purely from the terminal — no code edits:
  MODEL=claude-haiku-4-5     tp run        (Anthropic; uses ANTHROPIC_API_KEY)
  MODEL=claude-sonnet-4-6    tp run        (Anthropic)
  MODEL=claude-opus-4-8      tp run        (Anthropic)
  MODEL=openai/gpt-5.5       tp run        (OpenRouter; needs OPENROUTER_API_KEY)
  MODEL=x-ai/grok-4.3        tp run        (OpenRouter)

The question.txt already contains the full contract + the clause question + the
output-format instruction, so we send it as a single user message.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULT_MODEL = "claude-haiku-4-5"
MODEL = os.environ.get("MODEL", DEFAULT_MODEL)

# Per-million-token prices (June 2026 approximate). Mirror the other solutions.
PRICES = {
    "claude-opus-4-8":             {"in": 15.00, "out": 75.00},
    "claude-sonnet-4-6":           {"in":  3.00, "out": 15.00},
    "claude-haiku-4-5":            {"in":  0.80, "out":  4.00},
    "openai/gpt-5.5":              {"in":  5.00, "out": 30.00},
    "x-ai/grok-4.3":               {"in":  1.25, "out":  2.50},
    "meta-llama/llama-4-maverick": {"in":  0.15, "out":  0.60},
    "deepseek/deepseek-v4-pro":    {"in":  0.435, "out": 0.870},
    "qwen/qwen3-235b-a22b":        {"in":  0.455, "out": 1.820},
}

SYSTEM = (
    "You are a meticulous contract-review assistant. You are given a contract "
    "and a question about one specific clause type. Follow the instructions in "
    "the prompt exactly. If the clause is present, output ONLY the exact, "
    "verbatim text of the relevant span(s) copied from the contract. If the "
    "clause is absent, output exactly: NO CLAUSE FOUND. No explanations, no "
    "markdown, no commentary — just the span(s) or NO CLAUSE FOUND."
)


def call_anthropic(question: str) -> tuple[str, dict]:
    from anthropic import Anthropic

    client = Anthropic(max_retries=10)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM,
        messages=[{"role": "user", "content": question}],
    )
    text = next((b.text for b in msg.content if b.type == "text"), "").strip()
    u = msg.usage
    usage = {
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
    }
    return text, usage


def call_openrouter(question: str) -> tuple[str, dict]:
    from openai import OpenAI

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set — needed for non-Anthropic models")
    client = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        max_retries=10,
        default_headers={
            "HTTP-Referer": "https://github.com/Ruqii/trapstreet-solutions",
            "X-Title": "trapstreet-cuad-eval",
        },
    )
    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=2048,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ],
    )
    text = ""
    if resp.choices:
        ch = resp.choices[0].message
        if ch.content:
            text = ch.content.strip()
        elif getattr(ch, "reasoning", None):
            text = ch.reasoning.strip()
    u = resp.usage
    usage = {
        "input_tokens": getattr(u, "prompt_tokens", 0) or 0,
        "output_tokens": getattr(u, "completion_tokens", 0) or 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    return text, usage


def estimate_cost_usd(usage: dict, model: str) -> float:
    p = PRICES.get(model, {"in": 0, "out": 0})
    in_tokens = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
    return round(
        (in_tokens * p["in"] + usage.get("output_tokens", 0) * p["out"]) / 1_000_000,
        6,
    )


def main() -> int:
    inputs = json.loads(os.environ["INPUTS"])
    outputs = json.loads(os.environ.get("OUTPUTS", "{}"))
    question = Path(inputs["question.txt"]).read_text()

    is_anthropic = MODEL.startswith("claude-")
    answer, usage = (call_anthropic if is_anthropic else call_openrouter)(question)
    print(answer)

    if "usage.json" in outputs:
        Path(outputs["usage.json"]).write_text(json.dumps({
            "model": MODEL,
            **usage,
            "usd_cost": estimate_cost_usd(usage, MODEL),
        }, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
