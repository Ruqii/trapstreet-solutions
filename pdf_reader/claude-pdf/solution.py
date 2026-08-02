"""Claude PDF agent — sends the PDF directly to Claude as a document attachment.

Vision-LLM approach: the model "sees" the page, including the layout that
text-extraction parsers struggle with (DocuSign font encoding, form fields,
signature blocks).

Prompt caching: the PDF block is marked with cache_control so case 2-N
re-use the same 16-page document at ~10% input cost (90% savings after
the first call).

Contract: reads TRAP_MANIFEST ({inputs_dir, outputs_dir}), prints the answer
to stdout. The model is a CLI argument, not an env var — profile.model in
trap.yaml is self-reported and drifts from a MODEL env var silently, which
would put the wrong engine on the leaderboard.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

from anthropic import Anthropic

# Approximate Anthropic prices ($/M tokens, May 2026)
PRICES = {
    "claude-opus-4-7":    {"in": 15.00, "out": 75.00, "cache_read": 1.50,  "cache_write": 18.75},
    "claude-opus-4-8":    {"in": 15.00, "out": 75.00, "cache_read": 1.50,  "cache_write": 18.75},
    "claude-sonnet-4-6":  {"in":  3.00, "out": 15.00, "cache_read": 0.30,  "cache_write":  3.75},
    "claude-sonnet-4-5-20250929": {"in": 3.00, "out": 15.00, "cache_read": 0.30, "cache_write": 3.75},
}


SYSTEM = """You answer questions from a UK Assured Shorthold Tenancy (AST) agreement.

Rules:
- Answer ONLY based on what the document says — no general knowledge fill-in.
- Answer the question literally and completely. If the question has multiple parts, answer ALL parts.
- Follow any format constraint stated in the question (e.g. "DD/MM/YYYY", "yes/no", "GBP amount").
- Do not hedge. Do not say "I cannot determine" if the answer is in the document.
- Be terse — one short sentence is usually right. Numbers should be just the number unless asked for currency formatting.
"""


def estimate_cost_usd(usage, model: str) -> float:
    """Compute USD cost. Per Anthropic spec, `input_tokens` is the count NOT
    counted as cache read/write — so we sum directly, no subtraction."""
    p = PRICES.get(model)
    if not p:
        return 0.0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    in_ = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    return round((in_ * p["in"] + cw * p["cache_write"] + cr * p["cache_read"] + out * p["out"]) / 1_000_000, 6)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="Anthropic model id; must match profile.model in trap.yaml")
    args = ap.parse_args()

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])
    outputs_dir = Path(manifest["outputs_dir"])

    question = (inputs_dir / "question.txt").read_text().strip()
    pdf_b64 = base64.standard_b64encode((inputs_dir / "document.pdf").read_bytes()).decode()

    client = Anthropic(max_retries=10)  # absorb transient 429/529 with backoff
    msg = client.messages.create(
        model=args.model,
        max_tokens=1024,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                    "cache_control": {"type": "ephemeral"},  # cache the PDF across all cases
                },
                {"type": "text", "text": f"Question: {question}\n\nAnswer:"},
            ],
        }],
    )

    answer = next((b.text for b in msg.content if b.type == "text"), "").strip()
    print(answer)

    # Per-case token counts + cost estimate. Under the current contract the
    # solution writes into outputs_dir directly; the old schema's
    # `file_outputs:` declaration + OUTPUTS env var no longer exist.
    u = msg.usage
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "usage.json").write_text(json.dumps({
        "model": args.model,
        "input_tokens": getattr(u, "input_tokens", 0),
        "output_tokens": getattr(u, "output_tokens", 0),
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        "usd_cost": estimate_cost_usd(u, args.model),
    }, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
