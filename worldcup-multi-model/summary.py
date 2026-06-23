"""Render the frozen pre-match predictions (predictions/*.json) as a table.

Use it to post each model's blind prediction to social media before kickoff:
  python3 summary.py            # all matches
  python3 summary.py PAN_CRO    # filter by case-id substring
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

CACHE = Path(__file__).parent / "predictions"


def pct(pred: str) -> str:
    try:
        o = json.loads(pred)
        return f"home {round(o['home']*100)}% · draw {round(o['draw']*100)}% · away {round(o['away']*100)}%"
    except Exception:
        return pred.strip().replace("\n", " ")[:60]


def main() -> None:
    needle = sys.argv[1] if len(sys.argv) > 1 else ""
    by_case: dict[str, dict[str, str]] = defaultdict(dict)
    for f in sorted(CACHE.glob("*.json")):
        d = json.loads(f.read_text())
        if needle and needle not in d["case_id"]:
            continue
        by_case[d["case_id"]][d["model"]] = d["prediction"]

    if not by_case:
        print("no cached predictions yet — run `tp run <task>` first")
        return

    for case_id, models in by_case.items():
        print(f"\n⚽ {case_id}  —  {len(models)} models predict (blind, no odds)")
        for model, pred in models.items():
            print(f"   {model:<26} {pct(pred)}")


if __name__ == "__main__":
    main()
