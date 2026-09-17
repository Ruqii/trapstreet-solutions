#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["anthropic", "typesafe-sdk"]
# ///
"""Arms on model_routing: does a routing layer keep Claude Opus 5's accuracy
while paying for it less often?

Cheap model: claude-haiku-4-5. Strong model: claude-opus-5. Router: TypeSafe
Jev (jev-1.13.0, pinned). One script; an arm is only the --arm flag.

  haiku-only        Haiku answers every question.
  opus-only         Opus answers every question.
  jev-cascade-30    Haiku answers; Jev judges whether that answer is wrong;
  jev-cascade-60    above the arm's threshold, Opus answers instead.
  jev-preroute-30   Before any answer, Jev judges whether a cheap model would
                    get the question wrong; above threshold Opus answers,
                    otherwise Haiku. Haiku never runs on escalated questions.
  random-30         Haiku answers; a fixed pseudo-random draw from the question
  random-60         text escalates the same share to Opus. The control a router
                    has to beat.
  haiku-verify-30   Haiku answers; a second Haiku call judges whether that
                    answer is wrong; above threshold Opus answers. The same
                    middle layer with an LLM instead of Jev.

Every threshold was fixed on MMLU-Pro calibration questions that are not in
the task (see calibration/), as the score above which the target share of those
questions fall. No answer key was used to set them.

Each case prints ESCALATED: yes|no, FIRST_ANSWER (Haiku's answer) whenever Haiku
answered before the route was chosen, and, when Jev ran, UNMETERED_COST_USD for
its input tokens (tp's cost proxy cannot see TypeSafe).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHEAP, STRONG = "claude-haiku-4-5", "claude-opus-5"
JEV_MODEL, JEV_PRICE_PER_MTOK = "jev-1.13.0", 0.042
MAX_TOKENS = 16000
THRESHOLDS = json.loads((HERE / "calibration" / "thresholds.json").read_text())["thresholds"]
ARMS = ("haiku-only", "opus-only", "jev-cascade-30", "jev-cascade-60", "jev-preroute-30",
        "random-30", "random-60", "haiku-verify-30")

# Identical to the calibration probe's prompt: thresholds were set on answers to it.
PROMPT = """Answer this multiple-choice question. Think it through briefly, then end with one line:
ANSWER: <letter>

Question: {question}

Options:
{options}
"""
PRE_ROUTE_Q = ("Would a fast, low-cost language model most likely choose the wrong option for `question`? "
               "Yes if the question needs specialised knowledge, careful multi-step reasoning, or has "
               "close distractors among `options`; no if it is straightforward.")
CASCADE_Q = ("Is `proposed_answer` the wrong option for `question`? Judge whether the option it names "
             "is the correct answer among `options`.")
VERIFY_PROMPT = """A model answered the multiple-choice question below. Estimate the probability that its
proposed answer is WRONG. Think briefly, then end with one line:
P_WRONG: <integer from 0 to 100>

Question: {question}

Options:
{options}

Proposed answer: {proposed}
"""
# The judge's parser: models write the sentinel in markdown ("**ANSWER: G**"), and a
# line-start-only pattern silently dropped 23 of 200 Haiku answers on the first run.
ANSWER_RE = re.compile(r"^[ \t>*_#-]*ANSWER:[ \t*_]*\(?([A-Ja-j])\)?[ \t*_]*(?![A-Za-z])", re.MULTILINE)
P_WRONG_RE = re.compile(r"^\s*P_WRONG:\s*(\d{1,3})\s*$", re.MULTILINE)


def read_question() -> dict:
    d = Path(json.loads(os.environ["TRAP_MANIFEST"])["inputs_dir"])
    return json.loads((d / "question.json").read_text())


def options_text(q: dict) -> str:
    return "\n".join(f"{k}. {v}" for k, v in q["options"].items())


def claude():
    import anthropic
    return anthropic.Anthropic(max_retries=8)


def ask(client, model: str, prompt: str) -> str:
    msg = client.messages.create(model=model, max_tokens=MAX_TOKENS, messages=[{"role": "user", "content": prompt}])
    if msg.stop_reason == "refusal":
        return ""
    return "".join(b.text for b in msg.content if b.type == "text")


def answer(client, model: str, q: dict) -> str | None:
    found = ANSWER_RE.findall(ask(client, model, PROMPT.format(question=q["question"], options=options_text(q))))
    choice = found[-1].upper() if found else None
    return choice if choice in q["options"] else None


class Jev:
    def __init__(self) -> None:
        from typesafe_sdk import TypeSafeClient
        self.client, self.input_tokens = TypeSafeClient(), 0

    def noul(self, state: dict, instructions: str) -> float:
        from typesafe_sdk import Noul
        r = self.client.system_one(state=state, model=JEV_MODEL, questions={"q": Noul(instructions=instructions)})
        self.input_tokens += getattr(r.usage, "input_tokens", 0) or 0
        return r.nouls["q"].noul

    def cost_line(self) -> str:
        return f"UNMETERED_COST_USD: {self.input_tokens * JEV_PRICE_PER_MTOK / 1e6:.8f}"


def jev_state(q: dict, proposed: str | None = None) -> dict:
    state = {"question": q["question"], "options": q["options"]}
    if proposed is not None:
        state["proposed_answer"] = f"{proposed}. {q['options'][proposed]}"
    return state


def draw(q: dict) -> float:
    """A uniform number in [0, 1) fixed by the question text: reproducible, blind to difficulty."""
    return int(hashlib.sha256(q["question"].encode()).hexdigest()[:8], 16) / 2**32


def route(arm: str, q: dict, client, jev_factory=Jev) -> tuple[str | None, bool, list[str]]:
    """Returns (final choice, escalated, extra output lines)."""
    lines: list[str] = []
    if arm == "haiku-only":
        return answer(client, CHEAP, q), False, lines
    if arm == "opus-only":
        return answer(client, STRONG, q), False, lines
    if arm == "jev-preroute-30":
        jev = jev_factory()
        p = jev.noul(jev_state(q), PRE_ROUTE_Q)
        up = p >= THRESHOLDS[arm]
        lines += [f"ROUTER: jev pre-route p={p:.3f} threshold={THRESHOLDS[arm]}", jev.cost_line()]
        return answer(client, STRONG if up else CHEAP, q), up, lines

    cheap = answer(client, CHEAP, q)
    if cheap is not None:
        lines.append(f"FIRST_ANSWER: {cheap}")
    if arm.startswith("jev-cascade"):
        jev = jev_factory()
        if cheap is None:
            up = True
            lines.append("ROUTER: cheap model gave no answer")
        else:
            p = jev.noul(jev_state(q, cheap), CASCADE_Q)
            up = p >= THRESHOLDS[arm]
            lines.append(f"ROUTER: jev cascade p={p:.3f} threshold={THRESHOLDS[arm]}")
        lines.append(jev.cost_line())
    elif arm.startswith("random"):
        u = draw(q)
        up = cheap is None or u < THRESHOLDS[arm]
        lines.append(f"ROUTER: random u={u:.4f} rate={THRESHOLDS[arm]}")
    elif arm == "haiku-verify-30":
        if cheap is None:
            up = True
            lines.append("ROUTER: cheap model gave no answer")
        else:
            text = ask(client, CHEAP, VERIFY_PROMPT.format(question=q["question"], options=options_text(q),
                                                         proposed=f"{cheap}. {q['options'][cheap]}"))
            found = P_WRONG_RE.findall(text)
            p = min(100, int(found[-1])) / 100 if found else 1.0  # an unreadable verdict escalates
            up = p >= THRESHOLDS[arm]
            lines.append(f"ROUTER: haiku verify p={p:.2f} threshold={THRESHOLDS[arm]}")
    else:
        raise SystemExit(f"unknown arm {arm}")
    return (answer(client, STRONG, q) if up else cheap), up, lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=ARMS)
    arm = ap.parse_args().arm
    q = read_question()
    choice, escalated, lines = route(arm, q, claude())
    for line in lines:
        print(line)
    print(f"ESCALATED: {'yes' if escalated else 'no'}")
    print(f"ANSWER: {choice}" if choice else "NO ANSWER")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
