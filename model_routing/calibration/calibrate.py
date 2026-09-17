"""Fix every arm's routing threshold on the calibration questions.

The task publishes 200 MMLU-Pro question ids it never scores
(tasks/model_routing/calibration_question_ids.json). scores.jsonl holds, for
each of them, Haiku 4.5's chosen option and Jev's two scores, recorded by the
task's build-gate probe with the same prompts solution.py uses. It carries no
answer key, and none is used here: a threshold is the score above which the
arm's target share of calibration questions fall.

    uv run calibrate.py thresholds                 # free: recompute thresholds.json
    uv run --with anthropic --with pandas --with pyarrow calibrate.py haiku-verify
                                                   # paid: Haiku verifier scores
"""
from __future__ import annotations

import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

TARGETS = {"jev-cascade-30": ("jev_cascade_haiku", 0.30), "jev-cascade-60": ("jev_cascade_haiku", 0.60),
           "jev-preroute-30": ("jev_pre_route", 0.30), "haiku-verify-30": ("haiku_verify", 0.30)}
RANDOM = {"random-30": 0.30, "random-60": 0.60}
REVISION = "b189ec765aa7ed75c8acfea42df31fdae71f97be"
PARQUET = f"https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro/resolve/{REVISION}/data/test-00000-of-00001.parquet"
LETTERS = "ABCDEFGHIJ"


def rows() -> list[dict]:
    return [json.loads(l) for l in (HERE / "scores.jsonl").read_text().splitlines()]


def threshold_for(scores: list[float], share: float) -> tuple[float, float]:
    """The candidate cut (a score value) whose escalated share is closest to `share`."""
    best = None
    for t in sorted(set(scores)):
        got = sum(s >= t for s in scores) / len(scores)
        if best is None or abs(got - share) < abs(best[1] - share):
            best = (t, got)
    return best


def cmd_thresholds() -> None:
    data = rows()
    out = {"_doc": ("Routing thresholds fixed on the task's calibration questions (score quantiles, no "
                    "answer key). escalate when score >= threshold; random arms escalate when a draw "
                    "from the question text is < rate."), "thresholds": {}, "calibration_share": {}}
    for arm, (key, share) in TARGETS.items():
        scores = [r[key] for r in data if r.get(key) is not None]
        if len(scores) < len(data):
            print(f"{arm}: {key} missing for {len(data) - len(scores)} questions; run its calibration first")
            continue
        t, got = threshold_for(scores, share)
        out["thresholds"][arm], out["calibration_share"][arm] = t, round(got, 3)
    for arm, rate in RANDOM.items():
        out["thresholds"][arm], out["calibration_share"][arm] = rate, rate
    (HERE / "thresholds.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out["thresholds"]), json.dumps(out["calibration_share"]))


def cmd_haiku_verify() -> None:
    import io

    import pandas as pd
    import solution
    with urllib.request.urlopen(PARQUET) as r:
        df = pd.read_parquet(io.BytesIO(r.read()))
    by_id = {int(x.question_id): x for x in df.itertuples()}
    client = solution.claude()
    data = rows()

    def one(r: dict) -> float | None:
        item = by_id[r["question_id"]]
        q = {"question": item.question, "options": {LETTERS[i]: str(o) for i, o in enumerate(item.options)}}
        if r["haiku_choice"] is None:
            return 1.0
        text = solution.ask(client, solution.CHEAP, solution.VERIFY_PROMPT.format(
            question=q["question"], options=solution.options_text(q),
            proposed=f"{r['haiku_choice']}. {q['options'][r['haiku_choice']]}"))
        found = solution.P_WRONG_RE.findall(text)
        return min(100, int(found[-1])) / 100 if found else 1.0

    with ThreadPoolExecutor(max_workers=12) as pool:
        for r, p in zip(data, pool.map(one, data)):
            r["haiku_verify"] = p
    (HERE / "scores.jsonl").write_text("".join(json.dumps(r) + "\n" for r in data))
    print("haiku verify scores recorded for", len(data))


if __name__ == "__main__":
    {"thresholds": cmd_thresholds, "haiku-verify": cmd_haiku_verify}[sys.argv[1]]()
