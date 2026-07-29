"""smolagents-claude — CodeAgent with PDF vision tool + Python interpreter.

Third architecture in the trapstreet pdf-reader comparison set:

  claude-pdf       : single-shot vision  · simple, fast, weak on arithmetic
  docling-claude   : preprocessing + LLM · loses tabular signal
  smolagents-claude: vision tool + code  · agent loops + computes arithmetic

The agent gets ONE PDF-reading tool (read_pdf), and smolagents' built-in
Python interpreter for free. It decides how many times to call read_pdf,
when to compute in Python, and when to stop. For straightforward extraction
questions ("what is the deposit amount?") it usually answers in one tool call.
For scenario questions ("compute total cost given clauses A, B, C and
months_early=14") it should extract values, then compute in Python — which
is exactly what single-shot LLMs get wrong about 30% of the time.

Prompt caching is preserved on read_pdf so the 1.8MB PDF only pays full
input price on the first call within a case.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

from anthropic import Anthropic
from smolagents import CodeAgent, LiteLLMModel, tool

MODEL = os.environ.get("MODEL", "claude-opus-4-7")
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "6"))

# Approximate Anthropic prices ($/M tokens, May 2026) — same table as claude-pdf
PRICES: dict[str, dict[str, float]] = {
    "claude-opus-4-7":    {"in": 15.00, "out": 75.00, "cache_read": 1.50,  "cache_write": 18.75},
    "claude-sonnet-4-6":  {"in":  3.00, "out": 15.00, "cache_read": 0.30,  "cache_write":  3.75},
    "claude-sonnet-4-5-20250929": {"in": 3.00, "out": 15.00, "cache_read": 0.30, "cache_write": 3.75},
}

# Module-level state so the @tool function can reach the loaded PDF + accumulate
# usage across the multiple LLM calls one agent run produces. Each `tp run`
# subprocess handles exactly one case, so there's no concurrency risk.
_pdf_b64: str = ""
_anthropic = Anthropic(max_retries=10)  # absorb 429/529 with exponential backoff
_tool_usage: list[object] = []           # one entry per read_pdf invocation


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
        model=MODEL,
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
- Do not hedge. Do not say "I cannot determine" if the answer is in the document.
- Be terse: one short sentence is usually right. Numbers should be just the number unless asked for currency formatting.
- For scenario questions requiring arithmetic, extract values via read_pdf, compute in Python, show the calculation, then give the final number.
- Stop as soon as you have the answer. Do not over-extract.

Question:
{question}
"""


def estimate_cost_usd(model: str, tool_usage: list[object], agent_in: int, agent_out: int) -> float:
    """Sum cost across the (tool-driven Anthropic calls) + (smolagents-driven planning calls).

    Tool calls come back as anthropic.types.Usage with cache_read/cache_write fields.
    Agent planning calls go via LiteLLM and don't surface those — we treat them as
    plain in/out at the no-cache rate (slight over-estimate, fine for ranking).
    """
    p = PRICES.get(model)
    if not p:
        return 0.0
    total = 0.0
    for u in tool_usage:
        cw = getattr(u, "cache_creation_input_tokens", 0) or 0
        cr = getattr(u, "cache_read_input_tokens", 0) or 0
        in_ = getattr(u, "input_tokens", 0) or 0
        out = getattr(u, "output_tokens", 0) or 0
        total += in_ * p["in"] + cw * p["cache_write"] + cr * p["cache_read"] + out * p["out"]
    total += agent_in * p["in"] + agent_out * p["out"]
    return round(total / 1_000_000, 6)


def main() -> int:
    global _pdf_b64

    inputs = json.loads(os.environ["INPUTS"])
    outputs = json.loads(os.environ.get("OUTPUTS", "{}"))
    question = Path(inputs["question.txt"]).read_text().strip()
    _pdf_b64 = base64.standard_b64encode(Path(inputs["document.pdf"]).read_bytes()).decode()

    model = LiteLLMModel(model_id=f"anthropic/{MODEL}")
    agent = CodeAgent(
        tools=[read_pdf],
        model=model,
        max_steps=MAX_STEPS,
    )

    # smolagents prints its full reasoning trace (the system prompt verbatim,
    # each step's generated code, tool outputs, final answer panel) to stdout.
    # `trap` reads case_stdout as the solution's answer and the judge grades
    # matchers like `leading_word` and `no_hedge` on its entire contents — so
    # the trace decoration trashes the score even when the agent answers
    # correctly. Redirect the trace to stderr (still visible for `tp run`
    # debugging) and emit ONLY the final answer to stdout.
    with redirect_stdout(sys.stderr):
        answer = agent.run(AGENT_PROMPT.format(question=question))
    # smolagents may return a non-string final (e.g. int, dict) when the agent
    # returns a Python value directly. Normalise.
    print(str(answer).strip())

    if "usage.json" in outputs:
        # smolagents tracks aggregate tokens on agent.monitor for the planning
        # / orchestration calls (does NOT include the Anthropic calls made
        # inside the read_pdf tool — those we track ourselves).
        monitor = getattr(agent, "monitor", None)
        agent_in_tokens = int(getattr(monitor, "total_input_token_count", 0) or 0)
        agent_out_tokens = int(getattr(monitor, "total_output_token_count", 0) or 0)

        tool_in = sum((getattr(u, "input_tokens", 0) or 0) for u in _tool_usage)
        tool_out = sum((getattr(u, "output_tokens", 0) or 0) for u in _tool_usage)
        tool_cache_r = sum((getattr(u, "cache_read_input_tokens", 0) or 0) for u in _tool_usage)
        tool_cache_w = sum((getattr(u, "cache_creation_input_tokens", 0) or 0) for u in _tool_usage)

        record = {
            "model": MODEL,
            "agent_framework": "smolagents",
            "tool_calls": len(_tool_usage),
            "tool_input_tokens": tool_in,
            "tool_output_tokens": tool_out,
            "tool_cache_read_input_tokens": tool_cache_r,
            "tool_cache_creation_input_tokens": tool_cache_w,
            "agent_planning_input_tokens": agent_in_tokens,
            "agent_planning_output_tokens": agent_out_tokens,
            "usd_cost": estimate_cost_usd(MODEL, _tool_usage, agent_in_tokens, agent_out_tokens),
        }
        Path(outputs["usage.json"]).write_text(json.dumps(record, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
