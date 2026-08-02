"""pdf-inspector + Claude, in two deliberately separate modes.

`firecrawl/pdf-inspector` is a pure-Rust PDF parser: classification, position-aware
text extraction, and markdown conversion, with no ML models and no OCR. On native-text
PDFs it is very fast — this 16-page contract parses in tens of milliseconds against
tens of seconds for a vision model and ~18 minutes for a docling OCR pass.

## The two modes, and why they are separate

This document's text layer is a DocuSign font subset stored at codepoint-29, so
"ASSURED SHORTHOLD TENANCY" comes out as "$6685(' 6+257+2/' 7(1$1&<". pdf-inspector
has no OCR, so it cannot route around a broken text layer — it returns the bytes it
finds. Measured here:

    --mode vanilla   process_pdf().markdown                34ms    0/16 gold strings
    --mode deshift   extract_text() + auto-detected shift  41ms   16/16, and 11/11
                                                                  structural
                                                                  associations intact

The shift is ~15 lines of code in *this file*, not in the library. pdf-inspector's
contribution in `deshift` mode is "hand me the raw bytes"; the recovery is the
harness. Reporting a single blended number would credit the library for the
harness's work, so the two run as separate leaderboard entries and the gap is
stated rather than argued about.

## Read `vanilla`'s score as a real result, not a bug

Near-zero is the honest measurement of this library on this document, and it is
the same failure docling's default pipeline has: both ask "is there a text layer?"
and neither asks "is it usable?". MinerU does not fail this way, because it OCRs
unconditionally.

Worth knowing if you build on this library: its two entry points disagree here.
`detect_pdf()` — the fast classification path — reports `has_encoding_issues=False`,
`pages_needing_ocr=0`, `text_based`, confidence 1.0. Only the full `process_pdf()`
parse sets `has_encoding_issues=True` and flags all 16 pages. A pipeline that routes
on `detect_pdf()` alone is told the document is clean and then handed mojibake.

Contract: reads TRAP_MANIFEST ({inputs_dir, outputs_dir}), prints the answer to
stdout, writes usage.json into outputs_dir.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

MODEL = ""

# Anthropic list prices ($/M tokens). No prompt caching on this path (only the
# extracted text is sent, never the PDF), so billed == full input price.
PRICES = {
    "claude-opus-4-8":   {"in": 5.00, "out": 25.00},
    "claude-opus-4-7":   {"in": 5.00, "out": 25.00},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00},
}

CACHE_DIR = Path("/tmp/trapstreet-pdfinspector-cache")

# Words this contract is dense with; used to score a candidate shift.
_PROBE_WORDS = ("the", "and", "tenant", "rent", "landlord", "shall")

SYSTEM = """You answer questions from a UK Assured Shorthold Tenancy (AST) agreement
that has been extracted from the PDF as plain text. Layout may be flattened and the
extraction may contain minor errors.

- Answer ONLY based on what the document says -- no general-knowledge fill-in.
- State your answer clearly and commit to it; don't hedge if the document contains the answer.
- Match any format the question asks for (a date as DD/MM/YYYY; a yes/no; "N/A" when the
  document does not specify).
- For multi-part questions, answer every part.
- For calculation questions, give the final figure and show the arithmetic.
"""


def convert_vanilla(pdf: Path) -> str:
    """The library's headline API, used as its README shows it."""
    import pdf_inspector

    return pdf_inspector.process_pdf(str(pdf)).markdown


def _score(text: str) -> int:
    return sum(text.lower().count(w) for w in _PROBE_WORDS)


def convert_deshift(pdf: Path) -> str:
    """Raw bytes from pdf-inspector, then undo a uniform codepoint shift.

    HARNESS CODE, NOT LIBRARY CAPABILITY. Everything below the extract_text() call
    is repair this file performs on pdf-inspector's output.

    The shift is discovered, not hardcoded: try every offset and keep the one that
    maximises English-word density. On this document +29 scores 2349 against a
    distant second, so it is unambiguous — and because nothing is tuned to this
    file, the same routine handles any uniformly-shifted CID subset.

    Uses extract_text() rather than process_pdf().markdown deliberately: the
    markdown converter sanitises control bytes 0x01-0x1f, and that is exactly
    where the shifted digits and spaces live. Sanitising them leaves the letters
    readable and destroys every number in the document.
    """
    import pdf_inspector

    raw = pdf_inspector.extract_text(str(pdf))

    def shifted(text: str, off: int) -> str:
        return "".join(
            chr(ord(c) + off) if 0 < ord(c) + off < 0x7F and ord(c) not in (9, 10, 13) else c
            for c in text
        )

    best_off, best = 0, _score(raw)
    for off in range(-64, 65):
        if off == 0:
            continue
        s = _score(shifted(raw, off))
        if s > best:
            best_off, best = off, s

    if best_off == 0:
        return raw  # already readable; nothing to repair
    print(f"[pdf-inspector] detected codepoint shift {best_off:+d} "
          f"(word score {best} vs {_score(raw)} unshifted)", file=sys.stderr)
    return shifted(raw, best_off)


MODES = {"vanilla": convert_vanilla, "deshift": convert_deshift}


def extract_text_for(pdf: Path, mode: str) -> str:
    """Extract once per (document, mode) and reuse — every case ships the same PDF."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(pdf.read_bytes()).hexdigest()[:16]
    cache_file = CACHE_DIR / f"{h}.{mode}.txt"
    if cache_file.exists():
        return cache_file.read_text()

    text = MODES[mode](pdf)

    # Diagnostic only, on stderr — never acted on. Which path to take is the
    # mode's decision, made once, up front. (An earlier docling solution here
    # branched on a readability check at runtime; the check passed on output
    # that was missing half the numbers, so it silently answered from an
    # incomplete document. Report, don't route.)
    readable = sum(len(re.findall(rf"\b{w}\b", text, re.I)) for w in _PROBE_WORDS)
    print(f"[pdf-inspector:{mode}] {len(text)} chars, {readable} common-word hits "
          f"({'readable' if readable >= 100 else 'UNREADABLE — the broken text layer'})",
          file=sys.stderr)

    cache_file.write_text(text)
    return text


def ask(system: str, user: str) -> tuple[str, dict]:
    from anthropic import Anthropic

    msg = Anthropic(max_retries=10).messages.create(
        model=MODEL, max_tokens=1024, system=system,
        messages=[{"role": "user", "content": user}],
    )
    u = msg.usage
    in_ = getattr(u, "input_tokens", 0) or 0
    out = getattr(u, "output_tokens", 0) or 0
    p = PRICES.get(MODEL)
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
    ap.add_argument("--mode", required=True, choices=sorted(MODES),
                    help="which extraction path to measure; see module docstring")
    args = ap.parse_args()
    MODEL = args.model

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])
    outputs_dir = Path(manifest["outputs_dir"])
    outputs_dir.mkdir(parents=True, exist_ok=True)

    question = (inputs_dir / "question.txt").read_text().strip()
    contract = extract_text_for(inputs_dir / "document.pdf", args.mode)

    answer, usage = ask(
        SYSTEM,
        f"CONTRACT (extracted text):\n\n{contract}\n\nQUESTION: {question}\n\nAnswer:",
    )
    print(answer.strip())
    usage["pdf_inspector_mode"] = args.mode
    (outputs_dir / "usage.json").write_text(json.dumps(usage, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
