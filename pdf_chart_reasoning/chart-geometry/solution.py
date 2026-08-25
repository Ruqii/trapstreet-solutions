"""Measure the charts, then let the model answer from the measurements.

Every other arm on this task hands the model either extracted text (which the
figure pages do not have) or a picture of the page (which the model then has to
estimate from). This one measures the geometry -- bar heights against the
printed axis, markers counted -- and hands over a table. The model still does
all the reading of the question: which figure, which panel, which bin, whether
"3.88 or higher" includes the boundary, and when the figure cannot answer at
all. The code does not understand anything; it only guarantees that a 9 is a 9.

Provenance note, because it changes how the score should be read: the measuring
code was developed and validated against the SEP released after the March 2026
FOMC meeting, never against this task's document or its answers. On that
held-out release all nineteen histogram panels reproduce exactly. Marker
counting in the dot plot is weaker -- one of four columns exact, the others
within one to five dots -- and that is disclosed rather than tuned away.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import chart_reader

MODEL = ""
CACHE = Path("/tmp/trapstreet-chart-geometry-cache")
PRICES = {"claude-sonnet-5": {"in": 3.00, "out": 15.00}}

SYSTEM = (
    "You answer questions about a document's figures. You are given measurements "
    "taken from those figures: for each panel, how many participants fall in each "
    "labelled bin, and for the dot plot, how many dots sit at each rate level. "
    "Answer only from these measurements. If they do not contain what is asked, "
    "say so and say why."
)


def measure(pdf: Path) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / f"{hashlib.sha1(pdf.read_bytes()).hexdigest()[:16]}.txt"
    if key.exists():
        return key.read_text()

    figures = chart_reader.read_document(pdf)
    lines = []
    for title, f in figures.items():
        lines.append(f"--- {title}  (page {f['page']})")
        for p in f["panels"]:
            bins = ", ".join(f"{k}: {v}" for k, v in p["counts"].items())
            lines.append(f"  panel {p['panel']}: {bins}   (total {p['total']})")
        for c in f["columns"]:
            lvl = ", ".join(f"{k}: {v}" for k, v in c["counts"].items())
            lines.append(f"  column {c['column']}: {lvl}   (total {c['total']})")
    out = "\n".join(lines)
    key.write_text(out)
    print(f"[chart-geometry] measured {len(figures)} figures, {len(out)} chars",
          file=sys.stderr)
    return out


def ask(table: str, question: str) -> tuple[str, dict]:
    from anthropic import Anthropic

    msg = Anthropic(max_retries=10).messages.create(
        model=MODEL, max_tokens=1500, system=SYSTEM,
        messages=[{"role": "user", "content":
                   f"MEASUREMENTS:\n\n{table}\n\nQUESTION: {question}\n\nAnswer:"}],
    )
    u = msg.usage
    in_, out_ = getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0
    p = PRICES.get(MODEL)
    usage = {"model": MODEL, "input_tokens": in_, "output_tokens": out_,
             "usd_cost": round((in_ * p["in"] + out_ * p["out"]) / 1e6, 6) if p else None}
    return next((b.text for b in msg.content if b.type == "text"), ""), usage


def main() -> int:
    global MODEL
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    MODEL = ap.parse_args().model

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir, outputs_dir = Path(manifest["inputs_dir"]), Path(manifest["outputs_dir"])
    outputs_dir.mkdir(parents=True, exist_ok=True)

    table = measure(inputs_dir / "document.pdf")
    question = (inputs_dir / "question.txt").read_text().strip()
    answer, usage = ask(table, question)
    print(answer.strip())
    (outputs_dir / "usage.json").write_text(json.dumps(usage, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
