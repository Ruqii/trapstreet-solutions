#!/usr/bin/env python3
"""One shipped gate, on one case, driven the way its own installer set it up.

The installer defines the product. This arm does not pick an entry point and
does not compose stages: it runs the product's own install command into an
isolated HOME, replays the case as the event sequence a host would produce,
and takes the PreToolUse answer as the verdict. Where a product registers one
hook that is the product; where it registers four, all four run and an earlier
stage's mistake surfaces in the gate's answer rather than in a row of its own.

The driver under `gate/` is the probe's, unchanged, so a row here is
comparable to the measurement that put the product on this board.

Every error path in these products fails open -- a missing key, an unreachable
API and a clean sheet of allows are the same bytes. This arm prints no verdict
at all in that case, so the run records an unanswered case instead of handing
the product a free ALLOW.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gate.base import Verdict                    # noqa: E402
from gate.installed_gate import InstalledGate    # noqa: E402
from gate.session import load_cell               # noqa: E402
from gate.subprocess_gate import SubprocessGate  # noqa: E402

SPECS = Path(__file__).resolve().parent / "gate" / "specs"

# Which driver a product needs is a fact about what its installer registers,
# not a preference: jev-axi ships a standalone CLI that answers on stdout,
# jev-guard ships four hooks and session state on disk.
DRIVERS = {"jev-axi": SubprocessGate, "jev-guard": InstalledGate}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", required=True, choices=sorted(DRIVERS))
    args = ap.parse_args()

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs = Path(manifest["inputs_dir"])
    cell = load_cell(inputs, manifest.get("id") or inputs.name)

    if not os.environ.get("TYPESAFE_API_KEY"):
        print("TYPESAFE_API_KEY is not set; refusing to report a verdict",
              file=sys.stderr)
        return 1

    try:
        adapter = DRIVERS[args.gate](SPECS / f"{args.gate}.json")
    except Exception as exc:                                    # noqa: BLE001
        print(f"{args.gate} is not usable: {exc}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix=f"{args.gate}-") as tmp:
        result = adapter.judge(cell, Path(tmp))

    detail = " ".join(f"{k}={v!r}" for k, v in sorted(result.detail.items()))
    print(f"{args.gate.upper().replace('-', '_')} {detail}".strip())

    if result.verdict is Verdict.ERROR:
        print(f"gate error: {result.raw[-400:]}", file=sys.stderr)
        return 1

    print(result.verdict.value.upper())
    return 0


if __name__ == "__main__":
    sys.exit(main())
