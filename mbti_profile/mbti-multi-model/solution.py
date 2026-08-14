# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic",
#     "openai",
# ]
# ///
"""Multi-model solution for the MBTI profile task.

Shared across model variants: each `<model>/trap.yaml` names its own model as a
literal `cmd:` argument, so the model that runs and the model that gets reported
are the same string in the same file and cannot drift apart.

PERSONA stays an environment variable, deliberately. The model is the solution's
identity; the persona is the experimental condition varied *across* runs of one
identity, and baking it into `cmd:` would mean a directory per (model, persona)
cell for no gain.

  PERSONA=bare            personas/ is not read at all — the control
  PERSONA=<name>          personas/<name>.md is prepended to the system prompt
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Per-million-token prices. Anthropic verified against the published pricing
# table; everything else against OpenRouter's live /api/v1/models on 2026-08-15.
#
# For Anthropic models this is only a fallback — trap's cost proxy intercepts
# those calls and measures spend directly. For everything else it is the ONLY
# cost figure the run will ever have, because the proxy does not intercept
# OpenRouter. Re-check before adding a model; the table this replaced had
# drifted badly (it priced Opus 4.7 at $15/$75 when the real rate was $5/$25).
PRICES = {
    # Anthropic, direct
    "claude-opus-5":                         {"in":  5.00, "out": 25.00},
    "claude-sonnet-5":                       {"in":  3.00, "out": 15.00},
    "claude-haiku-4-5":                      {"in":  1.00, "out":  5.00},
    # OpenRouter — OpenAI
    "openai/gpt-5.6-sol-pro":                {"in":  5.00, "out": 30.00},
    "openai/gpt-5.6-sol":                    {"in":  5.00, "out": 30.00},
    "openai/gpt-5.6-terra":                  {"in":  1.00, "out":  6.00},
    "openai/gpt-5.6-luna":                   {"in":  0.10, "out":  0.60},
    # OpenRouter — everyone else
    "deepseek/deepseek-v4-pro-0813":         {"in":  0.43, "out":  0.87},
    "z-ai/glm-5.2":                          {"in":  1.19, "out":  3.74},
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
# Whatever this is set to also travels to the board as usage.json's `persona` field,
# and the task page keys its cards on (model, persona). Without the field two runs
# of one commit that differ only in environment would pool onto the same card, and
# the persona condition would be invisible.
PERSONA = os.environ.get("PERSONA", "bare")
PERSONA_DIR = Path(__file__).parent / "personas"

# Enough headroom for a reasoning model to think and *then* answer. This budget
# covers thinking as well as the response text, and a run that gets cut off
# mid-JSON scores 0.0 after the call is already paid for — so the cap is set
# well above what any of these models needs rather than close to it.
MAX_TOKENS = 16384


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


def call_anthropic(model: str, question: str) -> tuple[str, dict]:
    from anthropic import Anthropic

    client = Anthropic(max_retries=10)
    msg = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
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


def call_openrouter(model: str, question: str) -> tuple[str, dict]:
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
        model=model,
        max_tokens=MAX_TOKENS,
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
    p = PRICES.get(model)
    if p is None:
        # Zero would be indistinguishable from a genuinely free call, and this is
        # the only cost figure an OpenRouter run ever gets. Fail instead.
        raise SystemExit(f"No price entry for {model!r} — add one to PRICES (check OpenRouter's /api/v1/models)")
    in_tokens = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
    return round(
        (in_tokens * p["in"] + usage.get("output_tokens", 0) * p["out"]) / 1_000_000,
        6,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True, choices=["anthropic", "openrouter"])
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    # TRAP_MANIFEST is {"inputs_dir": ..., "outputs_dir": ...} — directories, not the
    # old per-file INPUTS/OUTPUTS name→path maps.
    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    question = (Path(manifest["inputs_dir"]) / "question.txt").read_text()

    call = call_anthropic if args.provider == "anthropic" else call_openrouter
    answer, usage = call(args.model, question)
    print(answer)

    # The judge reads this for the model name, the persona label, and — for OpenRouter
    # models, which trap's cost proxy does not intercept — the only cost figure the run
    # will ever have.
    outputs_dir = Path(manifest["outputs_dir"])
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "usage.json").write_text(json.dumps({
        "model": args.model,
        "persona": PERSONA,
        **usage,
        "usd_cost": estimate_cost_usd(usage, args.model),
    }, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
