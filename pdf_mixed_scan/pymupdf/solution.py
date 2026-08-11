"""PyMuPDF text-layer baseline.

Exists to answer a question the leaderboard otherwise leaves open: is the
text-layer tier's score a property of one library, or of the approach? On a
document whose second half carries no text layer, any parser that reads only
that layer receives nothing for those pages. This solution is the control that
makes that attributable — same extraction strategy as pdf-inspector's
`process_pdf().markdown`, different library entirely.

PyMuPDF is also the fastest text extractor measured here (0.09 s against
pdf-inspector's 0.42 s and MinerU's ~700 s), so the row doubles as the floor of
the cost/latency axis.

Deliberately NOT doing any of the things that would rescue it: no page
classification, no rasterising, no routing to a vision model. The point is what
a text-layer-only pipeline can reach.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

MODEL = ""
CACHE_DIR = Path("/tmp/trapstreet-pymupdf-cache")

# Full list price, no cache discount. Every case ships the same document, so a
# cached read would credit this solution for an artefact of the task's shape
# rather than for anything it does. See ../../pdf_reader/claude-pdf/solution.py.
PRICES = {
    "claude-sonnet-5": {"in": 3.00, "out": 15.00},
    "claude-opus-5": {"in": 5.00, "out": 25.00},
}

SYSTEM = (
    "You answer questions about a document. You are given the document as text "
    "extracted by a PDF parser. Answer only from that text. Be specific and give "
    "the figure asked for. If the text does not contain what is asked, say so."
)


def extract(pdf: Path) -> str:
    """Extract once per document and reuse — every case ships the same PDF."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{hashlib.sha1(pdf.read_bytes()).hexdigest()[:16]}.txt"
    if cache.exists():
        return cache.read_text()

    import pymupdf

    doc = pymupdf.open(pdf)
    text = "\n".join(page.get_text() for page in doc)

    # Diagnostic only, on stderr, never acted on. A page with no text layer
    # yields nothing here and that is the measurement, not a condition to
    # branch on.
    empty = sum(1 for page in doc if not page.get_text().strip())
    print(f"[pymupdf] {len(text)} chars over {doc.page_count} pages; "
          f"{empty} page(s) yielded no text", file=sys.stderr)

    cache.write_text(text)
    return text


def ask(system: str, user: str) -> tuple[str, dict]:
    from anthropic import Anthropic

    msg = Anthropic(max_retries=10).messages.create(
        # 4096, not 1024: these questions want a derivation, and a model that
        # spends its budget on reasoning tokens returns an empty text block —
        # which reads as a wrong answer rather than as a truncated one.
        model=MODEL, max_tokens=4096, system=system,
        messages=[{"role": "user", "content": user}],
    )
    u = msg.usage
    in_ = getattr(u, "input_tokens", 0) or 0
    out = getattr(u, "output_tokens", 0) or 0
    p = PRICES.get(MODEL)
    # First TEXT block, not the first block: a thinking block sits at index 0
    # and has no .text.
    return next((b.text for b in msg.content if b.type == "text"), ""), {
        "model": MODEL,
        "input_tokens": in_,
        "output_tokens": out,
        "usd_cost": round((in_ * p["in"] + out * p["out"]) / 1_000_000, 6) if p else None,
    }


def main() -> int:
    global MODEL
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True,
                    help="full model id; must match profile.model in trap.yaml")
    MODEL = ap.parse_args().model

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])
    outputs_dir = Path(manifest["outputs_dir"])
    outputs_dir.mkdir(parents=True, exist_ok=True)

    question = (inputs_dir / "question.txt").read_text().strip()
    document = extract(inputs_dir / "document.pdf")

    answer, usage = ask(
        SYSTEM,
        f"DOCUMENT (extracted text):\n\n{document}\n\nQUESTION: {question}\n\nAnswer:",
    )
    print(answer.strip())
    (outputs_dir / "usage.json").write_text(json.dumps(usage, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
