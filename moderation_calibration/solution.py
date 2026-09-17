#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["anthropic", "typesafe-sdk"]
# ///
"""Four arms of one question: does outsourcing a moderation-escalation
judgment to TypeSafe's Jev (a "System One" typed-decision model) change
probability calibration versus a Claude model reasoning about it directly --
and does *how* Jev is used matter?

One shared script; an arm is only the --mode flag its trap.yaml `cmd` passes.
The orchestrator model (claude-sonnet-5) is held constant across every arm on
purpose: the comparison is about whether/how Jev is used, not about which
Claude tier is doing the work. See each MODE_* constant below for exactly
what differs between arms.

--mode no-jev:
    Claude reads task.md + comment.txt (as delivered by the task) and
    produces the whole answer itself, including the ANSWER: line -- a bare
    relay, no extra scaffolding. This is the floor: what a general-purpose
    model does with no help from a decision primitive.

--mode jev-single-choice:
    Skips Claude entirely for the decision itself. The comment goes straight
    to Jev as one Noul question over a bare string state. Whatever Jev
    reports as the "violation" probability is the answer -- outsourcing the
    judgment completely, in the simplest possible shape.

--mode jev-decomposed-noul:
    Same comment, but instead of one broad Noul question, three independent,
    narrow Noul questions run in parallel (personal insult, threat/incitement,
    group-targeted hate) per TypeSafe's own guidance to keep each judgment
    narrow and coherent. Combined via noisy-OR (the standard way to combine
    independent "does this specific failure mode apply" probabilities into
    "does any failure mode apply"): p = 1 - prod(1 - p_i).

--mode jev-context-variant:
    Same single Noul question as jev-single-choice, but the `state` is a
    named-field object that explicitly discloses the one piece of context
    this task withholds (no surrounding article/thread), instead of a bare
    string. Tests whether naming that limitation in `state` (as TypeSafe's
    docs recommend for "policies, current facts") measurably changes Jev's
    calibration versus leaving it unstated.

Every mode prints exactly one line starting with "ANSWER:" as its last
matching line, per this task's contract (see comment.txt's sibling task.md).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def read_inputs() -> tuple[str, str]:
    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])
    task_md = (inputs_dir / "task.md").read_text()
    comment = (inputs_dir / "comment.txt").read_text().strip()
    return task_md, comment


def emit(probability: float, note: str = "") -> None:
    p = min(1.0, max(0.0, probability))
    if note:
        print(note)
    print(f"ANSWER: {p:.4f}")


# ---------------------------------------------------------------------------
# no-jev: Claude alone
# ---------------------------------------------------------------------------

def run_no_jev(model: str, task_md: str, comment: str) -> None:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"{task_md}\n\n--- comment.txt ---\n{comment}\n",
        }],
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    print(text)


# ---------------------------------------------------------------------------
# Jev arms: outsource the decision, no Claude call for the judgment itself
# ---------------------------------------------------------------------------

# Same policy substance as task.md's own instructions, phrased for Jev's
# instructions/criteria fields rather than for a chat model reading a prompt.
SINGLE_INSTRUCTIONS = (
    "Does this comment violate a community harassment/toxicity policy? A "
    "violation includes insulting, demeaning, or harassing language directed "
    "at a specific person or group -- personal insults, threats, or language "
    "intended to humiliate. Ordinary criticism, disagreement, or blunt "
    "commentary about ideas, policies, or a public figure's actions is NOT a "
    "violation on its own."
)

DECOMPOSED_INSTRUCTIONS = {
    "personal_insult": (
        "Does this comment contain a personal insult or demeaning language "
        "directed at a specific person (e.g. calling them stupid, a liar, "
        "subhuman, or similar), rather than criticizing their ideas or "
        "actions?"
    ),
    "threat_or_incitement": (
        "Does this comment contain a threat of harm to someone, or language "
        "inciting others to harm or harass someone?"
    ),
    "group_targeted_hate": (
        "Does this comment contain hostile or demeaning language targeting a "
        "group based on identity (e.g. nationality, religion, ethnicity), "
        "rather than an individual's specific actions?"
    ),
}

CONTEXT_NOTE = (
    "This comment is shown without the surrounding news article or comment "
    "thread it was originally posted under. Judge it on this text alone, the "
    "way a first-pass triage system would; do not assume missing context "
    "would make it more or less severe than it reads on its own."
)


def _client():
    from typesafe_sdk import TypeSafeClient

    return TypeSafeClient()


def run_jev_single_choice(comment: str) -> None:
    from typesafe_sdk import Noul

    with _client() as client:
        resp = client.system_one(
            state=comment,
            questions={"violation": Noul(instructions=SINGLE_INSTRUCTIONS)},
        )
    emit(resp.nouls["violation"].noul, note=f"jev single-choice noul={resp.nouls['violation'].noul:.4f}")


def run_jev_decomposed_noul(comment: str) -> None:
    from typesafe_sdk import Noul

    questions = {key: Noul(instructions=text) for key, text in DECOMPOSED_INSTRUCTIONS.items()}
    with _client() as client:
        resp = client.system_one(state=comment, questions=questions)

    probs = {key: resp.nouls[key].noul for key in DECOMPOSED_INSTRUCTIONS}
    # Noisy-OR: probability that at least one independent failure mode
    # applies, from each mode's own probability of applying.
    p_none = 1.0
    for p in probs.values():
        p_none *= (1.0 - p)
    combined = 1.0 - p_none
    note = "jev decomposed " + ", ".join(f"{k}={v:.4f}" for k, v in probs.items()) + f" -> combined={combined:.4f}"
    emit(combined, note=note)


def run_jev_context_variant(comment: str) -> None:
    from typesafe_sdk import Noul

    state = {"comment": comment, "context_note": CONTEXT_NOTE}
    with _client() as client:
        resp = client.system_one(
            state=state,
            questions={"violation": Noul(instructions=SINGLE_INSTRUCTIONS)},
        )
    emit(resp.nouls["violation"].noul, note=f"jev context-variant noul={resp.nouls['violation'].noul:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        required=True,
        choices=["no-jev", "jev-single-choice", "jev-decomposed-noul", "jev-context-variant"],
    )
    parser.add_argument("--model", default="claude-sonnet-5", help="orchestrator model for --mode no-jev")
    args = parser.parse_args()

    task_md, comment = read_inputs()

    if args.mode == "no-jev":
        run_no_jev(args.model, task_md, comment)
    elif args.mode == "jev-single-choice":
        run_jev_single_choice(comment)
    elif args.mode == "jev-decomposed-noul":
        run_jev_decomposed_noul(comment)
    elif args.mode == "jev-context-variant":
        run_jev_context_variant(comment)


if __name__ == "__main__":
    main()
