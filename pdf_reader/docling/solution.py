"""Docling + Claude, in three deliberately separate modes.

The point of splitting this into modes rather than shipping one "smart" pipeline
is to keep the measurement honest. Docling does not fail on this document because
its OCR or layout analysis are weak — both are good. It fails on a *routing*
decision: the PDF has a text layer, docling trusts a present text layer, and this
one is wrong. The DocuSign font subset is stored at codepoint-29, so "ASSURED
SHORTHOLD TENANCY" extracts as "$6685(' 6+257+2/' 7(1$1&<".

Deciding whether to trust a text layer is part of what docling *is*. A pipeline
that rasterises first has patched out docling's worst weakness before measuring
it, and would report a number that says more about the harness than the library.
So each mode does exactly one thing, and the gaps between them are the finding:

  --mode vanilla   DocumentConverter().convert(pdf)          docling, out of the box
  --mode ocr       + OcrMode.FULL_PAGE                        docling, configured
  --mode raster    PyMuPDF -> page PNGs -> docling            docling, with the
                                                              routing decision
                                                              taken away from it

Measured on this document (16 pages, gold-answer strings recoverable):

  vanilla   ~50s     0/8    ~101k chars of mojibake, no error, full speed
  ocr       ~1050s   5/8    readable prose, but loses 2100/2400, 13.2, 144/480
  raster    ~1100s   7/7 on the page tested individually

An earlier version of this file tried to pick a mode at runtime by checking
whether the output "looked like English". That check passed on the ocr output
(1355 hits on common words) while half the gold numbers were missing, so the
fallback never fired and the solution answered from an incomplete document. The
lesson is in the failure: readable is not the same as complete, and a heuristic
that conflates them is worse than no heuristic, because it also hides the two
clean measurements underneath. Hence: no runtime branching. Pick a mode, own it.

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

MODEL = ""

# Anthropic list prices ($/M tokens). No prompt caching on this path (only the
# converted markdown is sent, never the PDF), so billed == full input price.
PRICES = {
    "claude-opus-4-8":   {"in": 5.00, "out": 25.00},
    "claude-opus-4-7":   {"in": 5.00, "out": 25.00},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00},
}

CACHE_DIR = Path("/tmp/trapstreet-docling-cache")
RASTER_DPI = 200

SYSTEM = """You answer questions from a UK Assured Shorthold Tenancy (AST) agreement
that has been converted to markdown by Docling. The conversion may contain errors.

- Answer ONLY based on what the document says -- no general-knowledge fill-in.
- State your answer clearly and commit to it; don't hedge if the document contains the answer.
- Match any format the question asks for (a date as DD/MM/YYYY; a yes/no; "N/A" when the
  document does not specify).
- For multi-part questions, answer every part.
- For calculation questions, give the final figure and show the arithmetic.
"""


def convert_vanilla(pdf: Path) -> str:
    """What you get from `pip install docling` and the first line of its README."""
    from docling.document_converter import DocumentConverter

    return DocumentConverter().convert(str(pdf)).document.export_to_markdown()


def convert_ocr(pdf: Path) -> str:
    """Docling with OCR forced over the whole page — a documented, first-class
    option. Still docling's own pipeline; no external library involved.

    NB: `ocr_options.force_full_page_ocr = True` is deprecated and silently does
    nothing on 2.117; `mode = OcrMode.FULL_PAGE` is the setting that takes effect.
    """
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import OcrMode, PdfPipelineOptions

    opts = PdfPipelineOptions()
    opts.do_ocr = True
    opts.do_table_structure = True
    opts.ocr_options.mode = OcrMode.FULL_PAGE
    conv = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
    return conv.convert(str(pdf)).document.export_to_markdown()


def convert_raster(pdf: Path) -> str:
    """Render each page to PNG first, then convert the images.

    A page image has no text layer, so docling has no bad text layer to trust —
    the routing decision is made by the harness, not by docling. This is the mode
    that measures docling's OCR and layout in isolation, and the one whose score
    should be read as "docling plus engineering", not "docling".
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


MODES = {"vanilla": convert_vanilla, "ocr": convert_ocr, "raster": convert_raster}


def extract_markdown(pdf: Path, mode: str) -> str:
    """Convert once per (document, mode) and reuse. Every case ships the same PDF."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(pdf.read_bytes()).hexdigest()[:16]
    cache_file = CACHE_DIR / f"{h}.{mode}.md"
    if cache_file.exists():
        return cache_file.read_text()

    md = MODES[mode](pdf)

    # Diagnostics only — printed to stderr, never acted on. Deciding what to do
    # about a bad conversion is the mode's job, made once, up front.
    readable = sum(len(re.findall(rf"\b{w}\b", md, re.I))
                   for w in ("the", "tenant", "landlord", "rent"))
    print(f"[docling:{mode}] {len(md)} chars, {readable} common-word hits "
          f"({'readable' if readable >= 100 else 'UNREADABLE — likely the broken text layer'})",
          file=sys.stderr)

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
                    help="which conversion path to measure; see module docstring")
    args = ap.parse_args()
    MODEL = args.model

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])
    outputs_dir = Path(manifest["outputs_dir"])
    outputs_dir.mkdir(parents=True, exist_ok=True)

    question = (inputs_dir / "question.txt").read_text().strip()
    contract_md = extract_markdown(inputs_dir / "document.pdf", args.mode)

    answer, usage = ask(
        SYSTEM,
        f"CONTRACT (markdown):\n\n{contract_md}\n\nQUESTION: {question}\n\nAnswer:",
    )
    print(answer.strip())
    usage["docling_mode"] = args.mode
    (outputs_dir / "usage.json").write_text(json.dumps(usage, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
