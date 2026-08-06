"""smolagents-claude-split — same agent architecture, but routes planning to
sonnet and extraction (read_pdf vision calls) to opus.

The hypothesis: smolagents-claude paid opus prices on every planning call
even though "decide whether to call read_pdf, decide whether to compute in
Python, generate the final answer" is short text reasoning that sonnet
handles fine. The extraction step — actually parsing the PDF document with
vision — is where opus's accuracy advantage matters.

Splitting:
- TOOL_MODEL (claude-opus-4-7) drives every read_pdf call → vision quality preserved.
- PLANNER_MODEL (claude-sonnet-4-6) drives the agent's reasoning loop → planning cost ↓~5×.

Expected outcome vs smolagents-claude (the single-opus version):
- Accuracy: roughly equal (the extraction calls are unchanged)
- Cost per case: ~40-50% lower (planning calls were the chunk that sonnet
  handles cheaper at similar quality)
- Latency: slightly lower (sonnet is ~2× faster than opus on planning calls)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

from anthropic import Anthropic
from smolagents import CodeAgent, LiteLLMModel, tool

# Two-model split: planner is the agent's reasoning brain, tool is the
# extraction worker. Both are set from CLI arguments in main(), never from
# env vars — trap.yaml's profile.model is self-reported, and an env var
# drifts from it silently, putting the wrong engine on the leaderboard.
# Module-level so the @tool function below can close over TOOL_MODEL.
PLANNER_MODEL = ""
TOOL_MODEL = ""
MAX_STEPS = 6

# Anthropic list prices ($/M tokens). Opus-tier is $5/$25 — the table
# previously carried $15/$75, which overstated every opus run ~3x.
# cache_write = 1.25x input (5m TTL), cache_read = 0.1x input.
PRICES: dict[str, dict[str, float]] = {
    "claude-opus-4-7":    {"in":  5.00, "out": 25.00, "cache_read": 0.50,  "cache_write":  6.25},
    "claude-sonnet-4-6":  {"in":  3.00, "out": 15.00, "cache_read": 0.30,  "cache_write":  3.75},
    "claude-sonnet-4-5-20250929": {"in": 3.00, "out": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-opus-5":      {"in":  5.00, "out": 25.00, "cache_read": 0.50,  "cache_write":  6.25},
    "claude-sonnet-5":    {"in":  3.00, "out": 15.00, "cache_read": 0.30,  "cache_write":  3.75},
}

_pdf_b64: str = ""
_anthropic = Anthropic(max_retries=10)
_tool_usage: list[object] = []


@tool
def read_pdf(question: str) -> str:
    """Send the loaded tenancy PDF to Claude vision with a focused question; return the answer.

    Use this tool for any information that lives in the document — rent figures,
    dates, deposit amounts, clause presence, schedule values. For arithmetic on
    extracted values, do the math in Python rather than asking the tool to compute.

    The PDF is cached server-side via prompt caching, so repeated calls within
    one case re-use the document at ~10% input cost.

    Args:
        question: a focused, specific question about the PDF content
                  (e.g. "What is the monthly rent in year 2?",
                   "What is the deposit amount in GBP?").
    """
    msg = _anthropic.messages.create(
        model=TOOL_MODEL,
        max_tokens=1024,
        system=(
            "You extract literal facts from a UK Assured Shorthold Tenancy agreement. "
            "Answer exactly what's in the document. One short sentence; just the value "
            "if a value is asked for."
        ),
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": _pdf_b64,
                    },
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": question},
            ],
        }],
    )
    _tool_usage.append(msg.usage)
    return next((b.text for b in msg.content if b.type == "text"), "").strip()


AGENT_PROMPT = """You answer one question about a UK Assured Shorthold Tenancy (AST) agreement.

You have:
  - read_pdf(question): ask focused questions about the document, get short answers back
  - Python: compute arithmetic, format numbers, parse dates, double-check answers

Rules:
- Answer ONLY based on what the document says — no general knowledge fill-in.
- Answer the question literally and completely. Multi-part questions get all parts answered.
- Follow any format constraint stated (DD/MM/YYYY, yes/no, GBP amount, 'N/A' if not specified, etc.).
- Do not hedge. Do not say you cannot determine if the answer is in the document.
- Be terse: one short sentence is usually right. Numbers should be just the number unless asked for currency formatting.
- For scenario questions requiring arithmetic, extract values via read_pdf, compute in Python, show the calculation, then give the final number.
- Stop as soon as you have the answer. Do not over-extract.

Question:
{question}
"""


def estimate_cost_usd(tool_usage: list[object], agent_in: int, agent_out: int) -> float:
    """Sum tool-call cost (priced at TOOL_MODEL rates, with cache splits) +
    agent-planning cost (priced at PLANNER_MODEL rates, no cache fields)."""
    tool_p = PRICES.get(TOOL_MODEL, {})
    plan_p = PRICES.get(PLANNER_MODEL, {})
    total = 0.0
    if tool_p:
        for u in tool_usage:
            cw = getattr(u, "cache_creation_input_tokens", 0) or 0
            cr = getattr(u, "cache_read_input_tokens", 0) or 0
            in_ = getattr(u, "input_tokens", 0) or 0
            out = getattr(u, "output_tokens", 0) or 0
            # Full input price on cached tokens — see module docstring note.
            total += (in_ + cw + cr) * tool_p["in"] + out * tool_p["out"]
    if plan_p:
        total += agent_in * plan_p["in"] + agent_out * plan_p["out"]
    return round(total / 1_000_000, 6)


def main() -> int:
    global _pdf_b64, PLANNER_MODEL, TOOL_MODEL, MAX_STEPS

    ap = argparse.ArgumentParser()
    ap.add_argument("--planner-model", required=True, help="agent's reasoning model")
    ap.add_argument("--tool-model", required=True, help="vision model behind read_pdf")
    ap.add_argument("--max-steps", type=int, default=6)
    args = ap.parse_args()
    PLANNER_MODEL, TOOL_MODEL, MAX_STEPS = args.planner_model, args.tool_model, args.max_steps

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])
    outputs_dir = Path(manifest["outputs_dir"])
    outputs_dir.mkdir(parents=True, exist_ok=True)
    question = (inputs_dir / "question.txt").read_text().strip()
    _pdf_b64 = base64.standard_b64encode((inputs_dir / "document.pdf").read_bytes()).decode()

    # Planner runs through LiteLLM; vision tool calls Anthropic directly (above).
    planner = LiteLLMModel(model_id=f"anthropic/{PLANNER_MODEL}")
    agent = CodeAgent(
        tools=[read_pdf],
        model=planner,
        max_steps=MAX_STEPS,
    )

    # See smolagents-claude/solution.py for why we redirect: smolagents prints
    # its reasoning trace (including the verbatim system prompt) to stdout,
    # which `trap` reads as the agent's answer. Send the trace to stderr;
    # only the final answer goes to stdout.
    with redirect_stdout(sys.stderr):
        answer = agent.run(AGENT_PROMPT.format(question=question))
    print(str(answer).strip())

    monitor = getattr(agent, "monitor", None)
    agent_in_tokens = int(getattr(monitor, "total_input_token_count", 0) or 0)
    agent_out_tokens = int(getattr(monitor, "total_output_token_count", 0) or 0)

    tool_in = sum((getattr(u, "input_tokens", 0) or 0) for u in _tool_usage)
    tool_out = sum((getattr(u, "output_tokens", 0) or 0) for u in _tool_usage)
    tool_cache_r = sum((getattr(u, "cache_read_input_tokens", 0) or 0) for u in _tool_usage)
    tool_cache_w = sum((getattr(u, "cache_creation_input_tokens", 0) or 0) for u in _tool_usage)

    record = {
        "planner_model": PLANNER_MODEL,
        "tool_model": TOOL_MODEL,
        "agent_framework": "smolagents",
        "tool_calls": len(_tool_usage),
        "tool_input_tokens": tool_in,
        "tool_output_tokens": tool_out,
        "tool_cache_read_input_tokens": tool_cache_r,
        "tool_cache_creation_input_tokens": tool_cache_w,
        "agent_planning_input_tokens": agent_in_tokens,
        "agent_planning_output_tokens": agent_out_tokens,
        "usd_cost": estimate_cost_usd(_tool_usage, agent_in_tokens, agent_out_tokens),
    }
    (outputs_dir / "usage.json").write_text(json.dumps(record, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
