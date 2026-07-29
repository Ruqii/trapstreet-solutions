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

# Short aliases so you can run `MODEL=haiku tp run test` instead of the full ID.
# Anthropic models (no "/") go through the Anthropic SDK; anything with a "/" is
# treated as an OpenRouter slug. Unrecognized values pass through unchanged, so
# full IDs / any OpenRouter slug (e.g. "qwen/qwen-2.5-72b-instruct") work too.
MODEL_ALIASES = {
    # Anthropic (direct, cost-tracked by trap's proxy)
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
    "claude-opus": "claude-opus-4-8",
    "claude-sonnet": "claude-sonnet-4-6",
    "claude-haiku": "claude-haiku-4-5-20251001",
    # OpenRouter (via OPENROUTER_API_KEY)
    "gpt4o": "openai/gpt-4o",
    "gpt4o-mini": "openai/gpt-4o-mini",
    "gemini": "google/gemini-2.5-flash",
    "gemini-lite": "google/gemini-2.5-flash-lite",
    "deepseek": "deepseek/deepseek-chat",
    "llama": "meta-llama/llama-3.3-70b-instruct",
}
_model = os.environ.get("MODEL") or "sonnet"   # unset OR empty -> default
MODEL = MODEL_ALIASES.get(_model.lower(), _model)
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


def ask(system: str, user: str) -> str:
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
        return resp.choices[0].message.content
    from anthropic import Anthropic  # Claude — direct, cost-tracked by trap's proxy
    msg = Anthropic().messages.create(
        model=MODEL, max_tokens=1024, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text


def main() -> None:
    inputs = json.loads(os.environ["INPUTS"])
    question = Path(inputs["question.txt"]).read_text().strip()
    contract_md = extract_markdown(Path(inputs["document.pdf"]))
    user = f"CONTRACT (markdown):\n\n{contract_md}\n\nQUESTION: {question}\n\nAnswer:"
    print(ask(SYSTEM, user).strip())


if __name__ == "__main__":
    main()
