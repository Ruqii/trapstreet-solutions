#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["typesafe-sdk"]
# ///
"""Arms on cve_weakness_class: place one CVE description in one of 30 CWE classes.

  jev   One Jev Choice over the 30 options, pinned to a model id recorded at
        run time. Returns the class and the confidence behind it.

The option list is read out of the task.md delivered with the case, never
hardcoded here: the task owns its label set, and an arm that carried its own
copy would answer a different question the day that set changes.

Jev is not metered by tp's cost proxy, so the arm reports its own spend on an
UNMETERED_COST_USD line, which the task's grader sums as self-reported cost. It
is priced on input tokens only, $0.042 per million, output free.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

JEV_MODEL = "jev-1.13.0"
JEV_PRICE_PER_MTOK = 0.042
OPTION = re.compile(r"^(CWE-\d+):\s*(.+)$", re.MULTILINE)
INSTRUCTIONS = "Which CWE weakness class best matches this vulnerability?"


def read_case() -> tuple[dict[str, str], str]:
    """(options, description) for the one case this process was handed."""
    d = Path(json.loads(os.environ["TRAP_MANIFEST"])["inputs_dir"])
    options = dict(OPTION.findall((d / "task.md").read_text()))
    if not options:
        sys.exit("no options found in task.md — the case did not deliver a label set")
    return options, (d / "description.txt").read_text().strip()


def run_jev() -> None:
    from typesafe_sdk import TypeSafeClient, Choice

    options, description = read_case()
    resp = TypeSafeClient().system_one(
        state={"cve_description": description},
        model=JEV_MODEL,
        questions={"cwe": Choice(instructions=INSTRUCTIONS, criteria=options)},
    )
    answer = resp.choices["cwe"]
    print(f"ANSWER: {answer.choice}")
    print(f"CONFIDENCE: {answer.confidence:.4f}")

    tokens = getattr(resp.usage, "input_tokens", 0) or 0
    print(f"JEV_USAGE: model={resp.model} input_tokens={tokens}")
    print(f"UNMETERED_COST_USD: {tokens * JEV_PRICE_PER_MTOK / 1e6:.8f}")


ARMS = {"jev": run_jev}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--arm", required=True, choices=sorted(ARMS))
    ARMS[p.parse_args().arm]()


if __name__ == "__main__":
    main()
