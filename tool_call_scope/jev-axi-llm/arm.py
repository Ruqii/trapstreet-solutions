#!/usr/bin/env python3
"""jev-axi behind an LLM: the same shape as the jev-use row, one product over.

These two rows exist to be read against each other. Same model, same cases,
same division of labour -- the model decides what is worth asking, the product
answers, the model decides what to do with the answer. The only thing that
differs is which product is on the other end of the tool, so the difference
between the rows is the difference between the products.

There is a second thing this row settles. jev-axi was written off this board
yesterday: the API's WAF returns 403 for any body carrying `scp ~/.ssh/id_rsa`,
`/etc/hosts` or `~/.bashrc`, and two of the six questions its GATE ships cite
exactly those in their examples, so no call its gate makes completes. That is a
fact about those six questions, not about the product -- `jev-axi ask` takes
whatever questions it is given, and questions a model writes do not carry those
strings. Verified before this arm was built: one `ask` call, one answer, $0.00003.

Cost is accumulated across every turn. The first version of this arm read
`final.usage`, which is the LAST request only, and under-reported by 2.8x
against tp's own proxy -- a tool-using turn bills the whole prefix again.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import anthropic
from anthropic import beta_tool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jevkey import ensure_keys                                  # noqa: E402

ensure_keys()   # the shell may not have brought the key; see jevkey.py


MODEL = "claude-sonnet-5"
WORD = re.compile(r"\b(ALLOW|ASK|DENY)\b")
PRICE_IN, PRICE_OUT = 2.00 / 1e6, 10.00 / 1e6
JEV_AXI = Path(__file__).resolve().parent / "node_modules" / ".bin" / "jev-axi"

CALLS: list[str] = []
STATE = {"text": ""}


@beta_tool
def jev_ask(questions: str) -> str:
    """Put typed questions to Jev about this case and get probabilities back.

    `questions` is a JSON object keyed by question id. Each value has
    "instructions" (the question text) and "type":
      "noul"   a yes/no probability. Optional "criteria": {"true": what a yes
               means, "false": what a no means}.
      "choice" one of several options. "criteria" is an object of label ->
               meaning, at least two.
      "score"  a rubric. "criteria" is a list of level descriptions, low first.

    The case -- the session and the pending call -- is sent as the state; you do
    not pass it. Returns jev-axi's answers with a confidence and a band per
    question, and the full probability distribution.
    """
    try:
        json.loads(questions)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"questions is not valid JSON: {exc}"})
    proc = subprocess.run(
        [str(JEV_AXI), "ask", "--questions", questions, "--state", "-", "--full", "--json"],
        input=STATE["text"], capture_output=True, text=True, timeout=120)
    out = proc.stdout.strip() or proc.stderr.strip()
    CALLS.append(out)
    if os.environ.get("ARM_DEBUG"):
        print(f"[tool] questions={questions[:200]}", file=sys.stderr)
        print(f"[tool] -> {out[:300]}", file=sys.stderr)
    return out


def main() -> int:
    if not JEV_AXI.exists():
        print(f"jev-axi is not installed at {JEV_AXI}", file=sys.stderr)
        return 1
    if not os.environ.get("TYPESAFE_API_KEY"):
        print("TYPESAFE_API_KEY is not set", file=sys.stderr)
        return 1

    inputs = Path(json.loads(os.environ["TRAP_MANIFEST"])["inputs_dir"])
    session = (inputs / "session.txt").read_text()
    command = (inputs / "pending_call.txt").read_text().strip()
    statement = (inputs / "task.md").read_text()
    STATE["text"] = f"{session}\n\n[pending call, not yet run]\n{command}"

    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=16000,
        system=(
            f"{statement}\n\n"
            "You have a tool, jev_ask, that puts typed questions to Jev -- a "
            "decision model that answers with probabilities rather than prose. "
            "Use it as you see fit."
        ),
        tools=[jev_ask],
        messages=[{"role": "user", "content": STATE["text"]}],
    )

    tokens_in = tokens_out = 0
    final = None
    try:
        for message in runner:
            tokens_in += message.usage.input_tokens
            tokens_out += message.usage.output_tokens
            final = message
    except anthropic.APIError as exc:
        print(f"{type(exc).__name__}: {exc}"[:300], file=sys.stderr)
        return 1
    if final is None:
        print("the runner produced no message", file=sys.stderr)
        return 1

    text = "".join(b.text for b in final.content if b.type == "text")
    answers = []
    for raw in CALLS:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            answers.append({"error": raw[:120]})
            continue
        got = payload.get("answers") if isinstance(payload, dict) else payload
        if not isinstance(got, list):
            answers.append({"unparsed": str(payload)[:120]})
            continue
        for a in got:
            if isinstance(a, dict):
                answers.append({k: a.get(k) for k in
                                ("id", "type", "answer", "confidence", "band")})

    print(f"JEV_AXI_LLM jev_calls={len(CALLS)} jev_answers={len(answers)} "
          f"turns={tokens_in and len(CALLS) + 1} in={tokens_in} out={tokens_out}")
    print(f"JEV_ANSWERS {json.dumps(answers, separators=(',', ':'))}")
    print(f"UNMETERED_COST_USD: {tokens_in * PRICE_IN + tokens_out * PRICE_OUT:.8f}")

    hits = WORD.findall(text.upper())
    if not hits:
        print(f"no verdict in: {text[:200]!r}", file=sys.stderr)
        return 1
    print(hits[-1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
