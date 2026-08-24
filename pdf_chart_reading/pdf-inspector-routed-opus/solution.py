"""pdf-inspector used the way its README describes: classify, then route.

The library's headline claim is that it tells you which pages need OCR so you
can skip the expensive path for the ones that do not. The plain
`pdf-inspector` solution in this repo never acts on that — it takes
`process_pdf().markdown` and stops, which on a document whose second half is
images means it answers from half a document and scores 0.35.

This one uses the same library and adds the routing step:

    extract_pages_markdown(pdf)
      -> per page: markdown, needs_ocr
      -> text pages   : use the extracted markdown, free
      -> flagged pages: rasterise and send to the vision model

So the comparison between this solution and the plain one is not two libraries.
It is the same library with and without the thing it was built to enable.

Measured on this document, the classification is exact: pages_needing_ocr
returns [6,7,8,9,10,11], which is precisely the image half — no false
positives, no misses. Whatever this scores, the routing signal was not the
limiting factor.

Note what the library does NOT provide: a renderer or an OCR engine. Acting on
its verdict means supplying your own fallback path. Here that is PyMuPDF for
rasterising and the same model everything else in this task uses, so the only
variable against the plain solution is whether the flagged pages get reached
at all.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import sys
from pathlib import Path

MODEL = ""
CACHE_DIR = Path("/tmp/trapstreet-pdfinsp-routed-cache")
RENDER_DPI = 150

# Full list price, no cache discount — every case ships the same document, and
# a cached read would credit this solution for the task's shape rather than for
# anything it does.
PRICES = {
    "claude-sonnet-5": {"in": 3.00, "out": 15.00},
    "claude-opus-5": {"in": 5.00, "out": 25.00},
}

SYSTEM = (
    "You answer questions about a document. Part of it is given to you as text "
    "extracted by a PDF parser, and the pages that parser could not read are "
    "given to you as images. Use both. Be specific and give the figure asked for."
)


def split_pages(pdf: Path) -> tuple[str, list[int]]:
    """Return (text of the readable pages, page numbers needing another path).

    Page numbers are 1-based, matching what pdf-inspector reports.
    """
    import pdf_inspector

    result = pdf_inspector.extract_pages_markdown(str(pdf))
    text = "\n\n".join(
        f"--- page {p.page + 1} ---\n{p.markdown}"
        for p in result.pages
        if not p.needs_ocr and p.markdown.strip()
    )
    flagged = list(result.pages_needing_ocr)
    print(f"[routed] {len(result.pages)} pages: {len(result.pages) - len(flagged)} read as "
          f"text, {len(flagged)} flagged for OCR -> {flagged}", file=sys.stderr)
    return text, flagged


def render(pdf: Path, pages: list[int]) -> list[str]:
    """Rasterise the flagged pages to base64 PNG. Cached per document."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = CACHE_DIR / f"{hashlib.sha1(pdf.read_bytes()).hexdigest()[:16]}.json"
    if key.exists():
        return json.loads(key.read_text())

    import pymupdf

    doc = pymupdf.open(pdf)
    out = []
    for n in pages:
        pix = doc[n - 1].get_pixmap(dpi=RENDER_DPI)
        buf = io.BytesIO(pix.tobytes("png"))
        out.append(base64.standard_b64encode(buf.getvalue()).decode())
    key.write_text(json.dumps(out))
    return out


def ask(text: str, images: list[str], question: str) -> tuple[str, dict]:
    from anthropic import Anthropic

    content: list[dict] = []
    if text:
        content.append({"type": "text",
                        "text": f"DOCUMENT, pages the parser could read:\n\n{text}"})
    for i, b64 in enumerate(images, 1):
        content.append({"type": "text", "text": f"Page image {i} of {len(images)}:"})
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": b64}})
    content.append({"type": "text", "text": f"QUESTION: {question}\n\nAnswer:"})

    msg = Anthropic(max_retries=10).messages.create(
        # 4096, not 1024: these questions want a derivation, and a model that
        # spends its budget on reasoning tokens returns an empty text block.
        model=MODEL, max_tokens=4096, system=SYSTEM,
        messages=[{"role": "user", "content": content}],
    )
    u = msg.usage
    in_ = getattr(u, "input_tokens", 0) or 0
    cw = getattr(u, "cache_creation_input_tokens", 0) or 0
    cr = getattr(u, "cache_read_input_tokens", 0) or 0
    out = getattr(u, "output_tokens", 0) or 0
    p = PRICES.get(MODEL)
    usage = {
        "model": MODEL,
        "input_tokens": in_,
        "cache_creation_input_tokens": cw,
        "cache_read_input_tokens": cr,
        "output_tokens": out,
        # Every input token at list price, cached or not.
        "usd_cost": round(((in_ + cw + cr) * p["in"] + out * p["out"]) / 1_000_000, 6) if p else None,
    }
    # First TEXT block, not the first block: a thinking block sits at index 0
    # and has no .text.
    return next((b.text for b in msg.content if b.type == "text"), ""), usage


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

    pdf = inputs_dir / "document.pdf"
    question = (inputs_dir / "question.txt").read_text().strip()

    text, flagged = split_pages(pdf)
    images = render(pdf, flagged) if flagged else []

    answer, usage = ask(text, images, question)
    print(answer.strip())
    usage["pages_routed_to_vision"] = flagged
    (outputs_dir / "usage.json").write_text(json.dumps(usage, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
