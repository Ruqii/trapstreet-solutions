#!/usr/bin/env python3
"""The other end of the comparison: an LLM doing the classification itself.

This board already has Jev doing this job directly (`jev-direct`) and Jev
wrapped in five shipped products. What it did not have is the thing those
products exist to replace -- a general model asked the same question.

So this arm is deliberately unremarkable. It gets exactly what jev-direct
gets, the session and the pending call, with the task's own statement as the
system prompt, and it answers in one word. Nothing is tuned: no examples, no
chain-of-thought instruction, no rubric of ours. A prompt engineered against
these 84 cases would measure our prompt, and the row is here to measure the
model.

The three rows then differ in one thing each:

    llm-haiku    a general model, asked in prose
    jev-direct   a decision model, asked two typed questions
    the products a decision model, asked THEIR typed questions

which is the comparison the board was missing: not "is Jev good", but "is a
typed decision primitive a fair substitute for the LLM call it replaces".
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import anthropic

MODEL = "claude-haiku-4-5"
WORD = re.compile(r"\b(ALLOW|ASK|DENY)\b")
# Input and output per million tokens, for the cost line the runner records.
PRICE_IN, PRICE_OUT = 1.00 / 1e6, 5.00 / 1e6


def main() -> int:
    inputs = Path(json.loads(os.environ["TRAP_MANIFEST"])["inputs_dir"])
    session = (inputs / "session.txt").read_text()
    command = (inputs / "pending_call.txt").read_text().strip()
    statement = (inputs / "task.md").read_text()

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=MODEL,
            # Room to finish. At 256 a case was truncated mid-reasoning and
            # never reached its verdict -- an artefact of the instrument, not
            # an answer the model failed to give. The statement already asks
            # for one word; adding an instruction of ours to enforce it would
            # be tuning the prompt on these cases.
            max_tokens=2048,
            system=statement,
            messages=[{
                "role": "user",
                "content": f"{session}\n\n[pending call, not yet run]\n{command}",
            }],
        )
    except anthropic.APIError as exc:
        print(f"{type(exc).__name__}: {exc}"[:300], file=sys.stderr)
        return 1

    text = "".join(b.text for b in response.content if b.type == "text")
    usage = response.usage
    print(f"LLM_HAIKU model={response.model} in={usage.input_tokens} out={usage.output_tokens}")
    print(f"UNMETERED_COST_USD: "
          f"{usage.input_tokens * PRICE_IN + usage.output_tokens * PRICE_OUT:.8f}")

    # The judge reads the last verdict word; printing the reply first and the
    # verdict last keeps a model that reasons aloud readable on its answer.
    hits = WORD.findall(text.upper())
    if not hits:
        print(f"no verdict in: {text[:200]!r}", file=sys.stderr)
        return 1
    print(hits[-1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
