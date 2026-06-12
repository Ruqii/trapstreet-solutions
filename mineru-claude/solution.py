"""MinerU + Claude agent — MinerU extracts PDF → markdown, Claude answers from the text.

MinerU's pipeline backend does layout analysis + OCR (the AST PDF has no clean text
layer, so naive text extraction fails — this is why the task rewards real parsers).
Same caching strategy as marker-claude / docling-claude: the AST PDF is identical across
all cases, so we parse once (cached by content hash) and reuse the markdown.

MinerU is installed as a global CLI tool (`uv tool install "mineru[core]"`), not a project
dependency, because its PyTorch + model stack is multi-GB and shared across solutions.
On a cache miss this shells out to `mineru`; with the cache warm it never runs.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from anthropic import Anthropic

MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")
CACHE_DIR = Path("/tmp/trapstreet-mineru-cache")


SYSTEM = """You answer questions from a UK Assured Shorthold Tenancy (AST) agreement
that has been converted to markdown by MinerU. The conversion may have minor OCR errors.

The grader is strict and gives no partial credit, so:
- LEAD WITH THE ANSWER. The very first thing in your reply must BE the answer, before any
  explanation. For a number question, the FIRST number in your reply must be the answer
  itself -- do NOT state any dates, durations, clause numbers, or other figures before it.
  For yes/no, the first word must be "Yes" or "No". You may explain afterwards.
- Answer ONLY based on what the markdown says -- no general-knowledge fill-in.
- Commit to a single answer. Never hedge ("I cannot determine", "as an AI", "unclear").
- Match any format the question states: a date -> DD/MM/YYYY; "N/A if not specified" ->
  answer exactly N/A when absent.
- For multi-part questions, answer every part.
- For scenario/calculation questions, state the final number FIRST, then show the arithmetic.
- Give figures plainly (e.g. 2250 or £2,250), not a range.
"""


def extract_markdown(pdf_path: Path) -> str:
    """Convert PDF to markdown via MinerU. Caches by content hash (parse-once)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(pdf_path.read_bytes()).hexdigest()[:16]
    cache_file = CACHE_DIR / f"{h}.md"
    if cache_file.exists():
        return cache_file.read_text()

    out_dir = CACHE_DIR / h
    try:
        subprocess.run(
            ["mineru", "-p", str(pdf_path), "-o", str(out_dir), "-b", "pipeline", "-m", "auto"],
            check=True, capture_output=True, text=True,
        )
    except FileNotFoundError:
        sys.exit("mineru CLI not found. Install it with: uv tool install \"mineru[core]\"")
    # MinerU 3.x layout: <out>/<stem>/auto/<stem>.md
    md = (out_dir / pdf_path.stem / "auto" / f"{pdf_path.stem}.md").read_text()
    cache_file.write_text(md)
    return md


def main() -> None:
    inputs = json.loads(os.environ["INPUTS"])
    question = Path(inputs["question.txt"]).read_text().strip()
    contract_md = extract_markdown(Path(inputs["document.pdf"]))

    client = Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": f"CONTRACT (markdown):\n\n{contract_md}\n\nQUESTION: {question}\n\nAnswer:",
        }],
    )
    print(msg.content[0].text.strip())


if __name__ == "__main__":
    main()
