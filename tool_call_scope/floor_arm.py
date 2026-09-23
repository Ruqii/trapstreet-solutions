#!/usr/bin/env python3
"""The trivial strategies, on the board rather than only in the README.

A board whose floor is a paragraph is a board where nobody checks it. This arm
is here so every product row is read against a line that is visibly in the same
table, scored by the same judge on the same items.

  always-ask     refuses everything by handing it back. Perfect on catch,
                 perfect on the ask class, and 1.00 false refusal -- it is on
                 the board precisely because it will rank near the top by
                 `score` and the three rate columns are what say why that
                 number is worth nothing.

A second arm, `count-names`, was withdrawn on 2026-09-23. It compared how many
rows a command reached against how many the request named, and it topped the
board -- but the reaching half was a table of the four selector shapes THIS
case set uses. A floor has to be a rule that would have been written without
the case set in front of you; that one was written with it, so its 0.383
advantage was partly the vocabulary and there is no way to say how much.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

def read_case() -> tuple[str, str]:
    d = Path(json.loads(os.environ["TRAP_MANIFEST"])["inputs_dir"])
    return (d / "session.txt").read_text(), (d / "pending_call.txt").read_text().strip()


def main() -> None:
    arm = sys.argv[sys.argv.index("--arm") + 1]
    assert arm == "always-ask", arm
    read_case()          # read what a solution is given, so the arm is honest
    print("ASK")


if __name__ == "__main__":
    main()
