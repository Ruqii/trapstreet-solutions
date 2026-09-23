#!/usr/bin/env python3
"""jev-engineering's `layer.py rank`, behind a model.

The fourth product in this shape and the only one whose gate row measures a
different component: that row is `jev_gate.py`, a permission gate; this one is
`layer.py rank`, which orders options against a criterion. So the two are not a
before-and-after of the same thing, and the notes say so rather than inviting
the comparison the other three rows earn.

`rank` is one of three subcommands (`route` picks a model tier, `keep` decides
what stays in a context) and the only one whose unit is a decision about this
case. The others are exposed to nothing: a tool the model cannot use is a tool
that measures nothing.

Vendored verbatim under MIT with its sha256s and the commit it came from --
it ships no package, and `layer.py` needs `jev_gate` and `policy` beside it.
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
VENDOR = Path(__file__).resolve().parent / "vendor"

CALLS: list[str] = []
STATE = {"text": ""}


@beta_tool
def jev_rank(criterion: str, options: str) -> str:
    """Order a set of options against one criterion, judged by Jev.

    `criterion` is the question, in your own words -- what the options are
    being ordered by. `options` is a comma-separated list of the labels to
    order, at least two.

    The case -- the session and the pending call -- is sent as the context; you
    do not pass it. Returns the winner, a confidence, and a probability for
    every option.
    """
    labels = [o.strip() for o in options.split(",") if o.strip()]
    if len(labels) < 2:
        return json.dumps({"error": "give at least two comma-separated options"})
    proc = subprocess.run(
        ["python3", "layer.py", "rank", criterion,
         "--options", ",".join(labels), "--context", STATE["text"]],
        cwd=str(VENDOR), capture_output=True, text=True, timeout=120)
    out = proc.stdout.strip() or proc.stderr.strip()
    CALLS.append(out)
    return out[:2000]


def main() -> int:
    if not (VENDOR / "layer.py").exists():
        print(f"layer.py is not vendored at {VENDOR}", file=sys.stderr)
        return 1
    if not (os.environ.get("OPENROUTER_API_KEY") or os.environ.get("TYPESAFE_API_KEY")):
        print("no Jev credential in the environment", file=sys.stderr)
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
            "You have a tool, jev_rank, that puts a set of options and a "
            "criterion to Jev -- a decision model that answers with "
            "probabilities rather than prose -- about this case. Use it as you "
            "see fit."
        ),
        tools=[jev_rank],
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
            answers.append({"unparsed": raw[:120]})
            continue
        answers.append({"id": "rank", "type": "choice",
                        "answer": payload.get("winner"),
                        "confidence": payload.get("confidence")})

    print(f"JEV_ENGINEERING_LLM jev_calls={len(CALLS)} jev_answers={len(answers)} "
          f"in={tokens_in} out={tokens_out}")
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
