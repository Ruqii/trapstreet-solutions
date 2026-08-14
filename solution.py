"""Multi-model solution for the MBTI profile task.

Routes the same prompt through different LLMs based on the `MODEL` env var.
Anthropic-prefixed models go through the Anthropic SDK; everything else goes
through OpenRouter (one key, many models).

Set ONE of these env vars per run:
  MODEL=claude-opus-5                            (Anthropic; uses ANTHROPIC_API_KEY)
  MODEL=claude-sonnet-5                          (Anthropic)
  MODEL=claude-haiku-4-5                         (Anthropic)
  MODEL=openai/gpt-5.6-sol                       (OpenRouter — OpenAI flagship)
  MODEL=moonshotai/kimi-k3                       (OpenRouter — Moonshot)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

DEFAULT_MODEL = "claude-opus-5"
MODEL = os.environ.get("MODEL", DEFAULT_MODEL)

# Per-million-token prices, verified 2026-08-08 against the Anthropic pricing table
# and OpenRouter's live /api/v1/models endpoint.
#
# For Anthropic models this is only a fallback — trap's cost proxy intercepts those
# calls and measures spend directly. For everything else it is the ONLY cost figure
# the run will ever have, because the proxy does not intercept OpenRouter. Re-check
# it against OpenRouter's endpoint before adding a model; the previous table had
# drifted badly (it priced Opus 4.7 at $15/$75 when the real rate was $5/$25).
PRICES = {
    # Anthropic, direct
    "claude-opus-5":                         {"in":  5.00, "out": 25.00},
    "claude-sonnet-5":                       {"in":  3.00, "out": 15.00},
    "claude-haiku-4-5":                      {"in":  1.00, "out":  5.00},
    # OpenRouter
    "openai/gpt-5.6-sol":                    {"in":  5.00, "out": 30.00},
    "openai/gpt-5.6-terra":                  {"in":  1.00, "out":  6.00},
    "openai/gpt-5.6-luna":                   {"in":  0.10, "out":  0.60},
    "moonshotai/kimi-k3":                    {"in":  3.00, "out": 15.00},
}

TASK_SYSTEM = (
    "You are taking a personality questionnaire. Answer from YOUR own point of view as honestly as you can. "
    "Do not refuse, hedge, or qualify. Reply with the requested JSON object only — no markdown, no commentary."
)

# PERSONA names a file in personas/ whose text is prepended to the system prompt —
# the position a CLAUDE.md or soul.md occupies in a real agent harness. "bare" (the
# default) prepends nothing and is the control condition.
#
# Whatever this is set to also travels to the board as usage.json's `persona` field.
# It has to: trapstreet identifies a solution by (commit, repo_path) alone, so two
# runs of this commit that differ only in PERSONA share a row identity and the second
# one's name is discarded — without the field they'd be indistinguishable.
PERSONA = os.environ.get("PERSONA", "bare")
PERSONA_DIR = Path(__file__).parent / "personas"


def build_system() -> str:
    if PERSONA == "bare":
        return TASK_SYSTEM
    path = PERSONA_DIR / f"{PERSONA}.md"
    if not path.exists():
        # Loud, not silent: a typo'd PERSONA that quietly fell back to bare would
        # produce a row labelled with a persona that never reached the model.
        available = sorted(p.stem for p in PERSONA_DIR.glob("*.md"))
        raise SystemExit(
            f"PERSONA={PERSONA!r} not found at {path}. Available: {available or '(none)'} (or 'bare')"
        )
    # HTML comments carry provenance for us (source repo, licence, why the file
    # is here) and must not reach the model — a vendored file's header explains
    # the experiment, and telling the subject it is being measured is exactly
    # the contamination this condition exists to avoid.
    body = re.sub(r"<!--.*?-->", "", path.read_text(), flags=re.DOTALL).strip()
    return f"{body}\n\n---\n\n{TASK_SYSTEM}"


SYSTEM = build_system()


def call_anthropic(question: str) -> tuple[str, dict]:
    from anthropic import Anthropic

    client = Anthropic(max_retries=10)
    msg = client.messages.create(
        model=MODEL,
        # Same reason as the OpenRouter path: this budget covers thinking as well as
        # the answer. Claude Opus 5 thinks by default (omitting `thinking` runs
        # adaptive, unlike Opus 4.8 and earlier where omitting it meant no thinking),
        # so the old 1024 was enough for the model to think and then get cut off
        # mid-JSON — which the judge scores 0.0 after the call is already paid for.
        max_tokens=8192,
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
            "X-Title": "trapstreet-mbti-eval",
        },
    )
    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=8192,                # reasoning models burn tokens before the answer
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ],
    )
    # Prefer message.content; if a reasoning model put output in .reasoning, fall back to that.
    text = ""
    if resp.choices:
        ch = resp.choices[0].message
        if ch.content:
            text = ch.content.strip()
        elif getattr(ch, "reasoning", None):
            # Some reasoning models hide the structured answer inside the trace
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
    # TRAP_MANIFEST is {"inputs_dir": ..., "outputs_dir": ...} — directories, not the
    # old per-file INPUTS/OUTPUTS name→path maps.
    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    question = (Path(manifest["inputs_dir"]) / "question.txt").read_text()

    is_anthropic = MODEL.startswith("claude-")
    answer, usage = (call_anthropic if is_anthropic else call_openrouter)(question)
    print(answer)

    # The judge reads this for the model name, and — for OpenRouter models, which trap's
    # cost proxy does not intercept — it is the only cost figure the run will ever have.
    outputs_dir = Path(manifest["outputs_dir"])
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "usage.json").write_text(json.dumps({
        "model": MODEL,
        "persona": PERSONA,
        **usage,
        "usd_cost": estimate_cost_usd(usage, MODEL),
    }, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
