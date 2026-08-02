"""Docling + Claude — Docling converts the PDF to markdown, Claude answers from the text.

Peer of mineru-claude: a local parser front-end instead of sending the PDF to a
vision model. Docling is the lightest of the three parser solutions — it pulls no
multi-GB weight bundle and needs no globally-installed CLI, just `pip install docling`
(RapidOCR rides along).

## Why this file is not just `DocumentConverter().convert(pdf)`

The AST PDF has a text layer, and that text layer is wrong. Its DocuSign font subset
is stored at `codepoint - 29`, so "ASSURED SHORTHOLD TENANCY" extracts as
"$6685(' 6+257+2/' 7(1$1&<". Docling's default pipeline trusts the text layer when
one is present, so it happily returns ~101k characters of mojibake, at full speed,
with no error. Measured on this document: 0/8 gold-answer strings recoverable.

That is the interesting failure. "Has a text layer" and "has a *usable* text layer"
are different questions, and a parser that only asks the first one fails silently
here rather than loudly. (pdf-inspector fails identically; MinerU does not, because
it OCRs unconditionally.)

So this solution does not trust any single extraction path:

  1. convert with OCR forced over the whole page (`OcrMode.FULL_PAGE`)
  2. **check the result is readable English** before using it
  3. if it isn't, rasterise the pages with PyMuPDF — destroying the text layer
     outright — and convert the images instead

Step 2 is the load-bearing one. Without it a bad conversion reaches Claude as
context and the run scores zero with no indication of why.

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
import tempfile
from pathlib import Path

# The model is a CLI argument, never an env var — trap.yaml's profile.model is
# self-reported, and an env var drifts from it silently, putting the wrong engine
# on the leaderboard.
MODEL = ""

# Anthropic list prices ($/M tokens). No prompt caching on this path (only markdown
# is sent, never the PDF), so billed == full price and the two agree by construction.
PRICES = {
    "claude-opus-4-8":   {"in": 5.00, "out": 25.00},
    "claude-opus-4-7":   {"in": 5.00, "out": 25.00},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00},
}

CACHE_DIR = Path("/tmp/trapstreet-docling-cache")

# Every case ships the same document, so parse once and reuse. Keyed by content
# hash, not filename — the v2 PDF is a redacted rebuild of v1's and must not hit
# a v1 cache entry.
RASTER_DPI = 200

SYSTEM = """You answer questions from a UK Assured Shorthold Tenancy (AST) agreement
that has been converted to markdown by Docling. The conversion is OCR-based and may
contain minor character errors.

- Answer ONLY based on what the document says -- no general-knowledge fill-in.
- State your answer clearly and commit to it; don't hedge if the document contains the answer.
- Match any format the question asks for (a date as DD/MM/YYYY; a yes/no; "N/A" when the
  document does not specify).
- For multi-part questions, answer every part.
- For calculation questions, give the final figure and show the arithmetic.
"""


def _looks_like_english(md: str) -> bool:
    """Is this a real conversion, or the -29-shifted mojibake?

    Counts common words this contract is dense with. A good conversion of the AST
    scores in the hundreds; the mojibake scores 0, because every letter is shifted
    out of the alphabet. The threshold is deliberately far from both.
    """
    hits = sum(len(re.findall(rf"\b{w}\b", md, re.I)) for w in ("the", "tenant", "landlord", "rent"))
    return hits >= 100


def _convert_pdf_direct(pdf: Path) -> str:
    """Docling straight at the PDF, with OCR forced over the full page."""
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    opts = PdfPipelineOptions()
    opts.do_ocr = True
    opts.do_table_structure = True
    try:  # non-deprecated knob; `force_full_page_ocr` is deprecated and a no-op here
        from docling.datamodel.pipeline_options import OcrMode
        opts.ocr_options.mode = OcrMode.FULL_PAGE
    except ImportError:  # older docling
        opts.ocr_options.force_full_page_ocr = True

    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    return conv.convert(str(pdf)).document.export_to_markdown()


def _convert_rasterised(pdf: Path) -> str:
    """Render each page to PNG, then convert the images.

    The fallback. A page image has no text layer at all, so there is nothing for
    Docling to mistakenly trust — OCR is the only path available to it.
    """
    import fitz  # pymupdf
    from docling.document_converter import DocumentConverter

    conv = DocumentConverter()
    doc = fitz.open(pdf)
    pages: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, page in enumerate(doc):
            png = Path(tmp) / f"page_{i + 1:02d}.png"
            page.get_pixmap(dpi=RASTER_DPI).save(png)
            pages.append(conv.convert(str(png)).document.export_to_markdown())
    doc.close()
    return "\n\n".join(pages)


def extract_markdown(pdf: Path) -> str:
    """PDF -> markdown, cached by content hash. Verifies before trusting."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(pdf.read_bytes()).hexdigest()[:16]
    cache_file = CACHE_DIR / f"{h}.md"
    if cache_file.exists():
        return cache_file.read_text()

    md = _convert_pdf_direct(pdf)
    if not _looks_like_english(md):
        # Diagnostic on stderr only — stdout is the graded answer.
        print(
            f"[docling] direct conversion returned {len(md)} chars of unreadable text "
            f"(broken text layer); falling back to rasterised pages",
            file=sys.stderr,
        )
        md = _convert_rasterised(pdf)
        if not _looks_like_english(md):
            sys.exit("[docling] both conversion paths produced unreadable text — refusing "
                     "to answer from garbage. Inspect the PDF's font encoding.")

    cache_file.write_text(md)
    return md


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
    answer = next((b.text for b in msg.content if b.type == "text"), "")
    return answer, {
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
    contract_md = extract_markdown(inputs_dir / "document.pdf")

    answer, usage = ask(
        SYSTEM,
        f"CONTRACT (markdown):\n\n{contract_md}\n\nQUESTION: {question}\n\nAnswer:",
    )
    print(answer.strip())
    (outputs_dir / "usage.json").write_text(json.dumps(usage, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
