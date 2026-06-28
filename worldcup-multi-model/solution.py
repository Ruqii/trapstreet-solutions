"""Multi-model solution for the World Cup match-prediction tasks.

Each task gives one match BLIND — teams + kickoff, no odds — and asks for a
probability over {home, draw, away}. This solution routes the same prompt through
different LLMs via the `MODEL` env var: Anthropic-prefixed models go through the
Anthropic SDK; everything else goes through OpenRouter (one key, many models).

Switch the engine purely from the terminal — no code edits:
  MODEL=claude-opus-4-8     tp run worldcup-pan-cro     (Anthropic; ANTHROPIC_API_KEY)
  MODEL=claude-sonnet-4-6   tp run worldcup-pan-cro     (Anthropic)
  MODEL=openai/gpt-5.5      tp run worldcup-pan-cro     (OpenRouter; OPENROUTER_API_KEY)
  MODEL=google/gemini-3-pro tp run worldcup-pan-cro     (OpenRouter)

The model is closed-book (no tools, no web). question.txt is self-contained, so it
is sent as a single user message. Output is the model's JSON prediction on stdout,
which the task's judge.py parses.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def extract_json(text: str) -> str:
    """Pull the bare JSON object out of a model reply.

    Models sometimes wrap the answer in ```json ... ``` fences or add a sentence.
    The task's judge does a strict json.loads, so a fenced/prefixed reply would
    score 0 even when the prediction is fine. Strip to the first {...} object.
    """
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.S)
    if m:
        return m.group(1).strip()
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        return m.group(0).strip()
    return t

DEFAULT_MODEL = "claude-opus-4-8"
MODEL = os.environ.get("MODEL", DEFAULT_MODEL)

# Per-million-token prices (June 2026 approximate). Mirror the other solutions.
PRICES = {
    "claude-opus-4-8":             {"in": 15.00, "out": 75.00},
    "claude-sonnet-4-6":           {"in":  3.00, "out": 15.00},
    "claude-haiku-4-5":            {"in":  0.80, "out":  4.00},
    "openai/gpt-5.5":              {"in":  5.00, "out": 30.00},
    "x-ai/grok-4.3":               {"in":  1.25, "out":  2.50},
    "google/gemini-3.1-pro-preview":         {"in":  1.25, "out": 10.00},
    "meta-llama/llama-4-maverick": {"in":  0.15, "out":  0.60},
    "deepseek/deepseek-v4-pro":    {"in":  0.435, "out": 0.870},
}

SYSTEM = (
    "You are a football analyst predicting a single match. You are given only the "
    "two teams and the kickoff time — no odds. Using your own knowledge of the "
    "teams, output ONLY a JSON object on one line with keys \"home\", \"draw\", "
    "\"away\" whose values are probabilities that sum to 1. No explanation, no "
    "markdown — just the JSON."
)


def call_anthropic(question: str) -> tuple[str, dict]:
    from anthropic import Anthropic

    client = Anthropic(max_retries=10)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1024,
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
            "X-Title": "trapstreet-worldcup-eval",
        },
    )
    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=1024,
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


CACHE_DIR = Path(__file__).parent / "predictions"


def _cache_path(case_id: str, model: str) -> Path:
    return CACHE_DIR / f"{case_id}__{model.replace('/', '_')}.json"


def main() -> int:
    inputs = json.loads(os.environ["INPUTS"])
    outputs = json.loads(os.environ.get("OUTPUTS", "{}"))
    qpath = Path(inputs["question.txt"])
    case_id = qpath.parent.name                      # inputs/<case_id>/question.txt
    cache = _cache_path(case_id, MODEL)

    # Route B — freeze the pre-match prediction. First run calls the model and
    # caches the answer; later runs REPLAY the cached prediction (no new model
    # call), so the prediction that scores after the match is exactly the one made
    # before kickoff. Set REFRESH=1 (or delete the cache file) to re-capture.
    if cache.exists() and os.environ.get("REFRESH") != "1":
        cached = json.loads(cache.read_text())
        answer, usage = cached["prediction"], cached.get("usage", {})
    else:
        question = qpath.read_text()
        is_anthropic = MODEL.startswith("claude-")
        answer, usage = (call_anthropic if is_anthropic else call_openrouter)(question)
        answer = extract_json(answer)            # strip fences/prose so judge can parse
        CACHE_DIR.mkdir(exist_ok=True)
        cache.write_text(json.dumps({
            "case_id": case_id,
            "model": MODEL,
            "prediction": answer,
            "usage": usage,
            "captured_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat(),
        }, indent=2) + "\n")

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
