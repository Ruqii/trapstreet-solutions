#!/usr/bin/env python3
"""The `lexical` arm: no model at all — pick the option whose NAME shares the
most words with the description.

It is on the board because a reader cannot otherwise tell whether a score is
evidence of anything. CVE descriptions routinely name their own weakness class
in prose ("out-of-bounds write", "SQL injection"), so a matcher that reads no
meaning still collects a large share of the set. Any arm that does not clear
this line has not demonstrated it understands the task.

Scored per case, with no corpus statistics: a solution sees one case, so it
cannot fit IDF over the other 1,499. That makes it weaker than the task's
offline floor probe, which does fit over the whole set (0.541) -- and it is the
honest number for a board where every arm is under the same constraint.

Ties break on the option order in task.md, which is itself a fixed shuffle, so
the answer is deterministic and no tie-break smuggles in a prior.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

OPTION = re.compile(r"^(CWE-\d+):\s*(.+)$", re.MULTILINE)
STOP = set(
    "the a an of in to for and or with without by on at from is are be as its "
    "it this that use used using".split()
)


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in STOP}


def main() -> None:
    d = Path(json.loads(os.environ["TRAP_MANIFEST"])["inputs_dir"])
    options = dict(OPTION.findall((d / "task.md").read_text()))
    if not options:
        sys.exit("no options in task.md — the case delivered no label set")
    described = words((d / "description.txt").read_text())

    best, best_score = next(iter(options)), -1.0
    for cwe, name in options.items():
        w = words(name)
        # share of the option's own words the description contains, so a long
        # class name is not rewarded simply for having more words to match
        score = len(w & described) / len(w) if w else 0.0
        if score > best_score:
            best, best_score = cwe, score

    print(f"ANSWER: {best}")
    print(f"LEXICAL_OVERLAP: {best_score:.4f}")


if __name__ == "__main__":
    main()
