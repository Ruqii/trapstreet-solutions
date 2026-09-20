#!/usr/bin/env python3
"""The `laya` arm: one Laya typed decision per case, run locally on Apple Silicon.

Laya is a 421M purpose-trained decision model (convaiinnovations/laya, the
`typed-decisions` checkpoint) served through mizorewww/laya-mlx. Its API is
TypeSafe-shaped -- state plus typed questions in, a choice with a probability
per option and a confidence out -- so this arm is the same shape as the `jev`
one, pointed at a different model.

The 30 options come from the task.md delivered with the case, never hardcoded.

Laya runs on this machine, so there is no API bill. What it costs is compute and
electricity, which tp cannot meter and this arm does not invent: no
UNMETERED_COST_USD line is printed, and the board shows the cost cells empty
rather than a number nobody measured.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

MODEL, SUBFOLDER = "convaiinnovations/laya", "typed-decisions"
OPTION = re.compile(r"^(CWE-\d+):\s*(.+)$", re.MULTILINE)
INSTRUCTIONS = "Which CWE weakness class best matches this vulnerability?"


def main() -> None:
    d = Path(json.loads(os.environ["TRAP_MANIFEST"])["inputs_dir"])
    options = dict(OPTION.findall((d / "task.md").read_text()))
    if not options:
        sys.exit("no options in task.md — the case delivered no label set")
    description = (d / "description.txt").read_text().strip()

    import laya_mlx as laya

    agent = laya.load(MODEL, subfolder=SUBFOLDER)
    answer = agent.system_one(
        {"cve_description": description},
        {"cwe": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": options}},
    )["answers"]["cwe"]

    print(f"ANSWER: {answer['choice']}")
    print(f"CONFIDENCE: {answer['confidence']:.4f}")
    print(f"LAYA_MODEL: {MODEL}/{SUBFOLDER}")


if __name__ == "__main__":
    main()
