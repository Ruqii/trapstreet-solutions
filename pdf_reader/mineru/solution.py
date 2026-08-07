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

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

# The model is a CLI argument, never an env var or an alias table: trap.yaml's
# profile.model is self-reported, and anything that resolves indirectly can
# drift from it silently, putting the wrong engine on the leaderboard. Pass the
# full id. A "/" routes to OpenRouter; anything else goes to Anthropic.
MODEL = ""

# Anthropic list prices ($/M tokens). No caching on this path — the PDF is
# parsed to markdown locally and only text is sent — so billed == full price.
PRICES = {
    "claude-opus-4-8":   {"in": 5.00, "out": 25.00},
    "claude-opus-4-7":   {"in": 5.00, "out": 25.00},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00},
}

CACHE_DIR = Path("/tmp/trapstreet-mineru-cache")


# The contract is read from MinerU's markdown; the model must answer accurately and in the
# format the task asks for. These instructions restate the task's own published rubric
# (commit to one answer, match the requested format, answer every part, show calculations) —
# they help the model express a correct answer cleanly, not invent one.
SYSTEM = """You answer questions from a UK Assured Shorthold Tenancy (AST) agreement
that has been converted to markdown by MinerU. The conversion may have minor OCR errors.

- Answer ONLY based on what the document says -- no general-knowledge fill-in.
- State your answer clearly and commit to it; don't hedge if the document contains the answer.
- Match any format the question asks for (e.g. a date as DD/MM/YYYY; a yes/no; "N/A" when the
  document does not specify).
- For multi-part questions, answer every part.
- For calculation questions, give the final figure and show the arithmetic.
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


def ask(system: str, user: str) -> tuple[str, dict]:
    """Route to Anthropic (Claude IDs) or OpenRouter (any slug containing '/')."""
    if "/" in MODEL:  # OpenRouter — OpenAI-compatible API
        from openai import OpenAI
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )
        resp = client.chat.completions.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content, {}
    from anthropic import Anthropic  # Claude — direct, cost-tracked by trap's proxy
    msg = Anthropic().messages.create(
        model=MODEL, max_tokens=1024, system=system,
        messages=[{"role": "user", "content": user}],
    )
    u = msg.usage
    in_ = getattr(u, "input_tokens", 0) or 0
    out = getattr(u, "output_tokens", 0) or 0
    p = PRICES.get(MODEL)
    # Take the first TEXT block, not the first block. Models that emit a
    # thinking block put it at index 0, and content[0].text then raises
    # AttributeError — which took out nineteen of twenty cases on the first
    # run against claude-sonnet-5. The other solutions in this repo already
    # did it this way; this one had been left behind.
    return next((b.text for b in msg.content if b.type == "text"), ""), {
        "model": MODEL,
        "input_tokens": in_,
        "output_tokens": out,
        "usd_cost": round((in_ * p["in"] + out * p["out"]) / 1_000_000, 6) if p else None,
    }


def main() -> None:
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
    user = f"CONTRACT (markdown):\n\n{contract_md}\n\nQUESTION: {question}\n\nAnswer:"
    answer, usage = ask(SYSTEM, user)
    print(answer.strip())
    if usage:
        (outputs_dir / "usage.json").write_text(json.dumps(usage, indent=2))


if __name__ == "__main__":
    main()
