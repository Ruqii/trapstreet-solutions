# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic",
# ]
# ///
"""Code-review Claude Skill solution: loads the real community SKILL.md
(sitting next to this script) PLUS its full set of reference files (under
references/), and applies them to review the one file shown in each case's
question.txt, via a direct Anthropic API call.

All 6 files this skill's Reference Guide table points to are small and
language-agnostic, so all are included -- this skill's full designed
methodology is available, not just its top-level SKILL.md summary.

Shared across every model variant in this repo: each variant's trap.yaml
picks the model via a --model CLI argument baked directly into its cmd:
line (never a MODEL env var -- keeps the leaderboard-reported model and the
model actually run from ever drifting apart), e.g.
``uv run ../solution.py --model claude-opus-4-8``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from anthropic import Anthropic

HERE = Path(__file__).resolve().parent
SKILL_MD = (HERE / "SKILL.md").read_text()

REFERENCE_FILES = [
    "references/review-checklist.md",
    "references/common-issues.md",
    "references/feedback-examples.md",
    "references/report-template.md",
    "references/spec-compliance-review.md",
    "references/receiving-feedback.md",
]

REFERENCE_BLOCK = "\n\n".join(
    f"=== BEGIN {path} ===\n{(HERE / path).read_text()}\n=== END {path} ==="
    for path in REFERENCE_FILES
)

SYSTEM = f"""You must act EXACTLY as Claude would when the following Claude \
Skill is loaded and active. This is a real Skill file (SKILL.md format), \
shown below along with the full text of every reference file its own \
"Reference Guide" table points to. Internalize the skill's review \
methodology, principles, and process -- including these reference files, \
exactly as the skill's own dispatch table intends -- and apply it \
faithfully when reviewing the code the user shows you.

=== BEGIN SKILL.md ===
{SKILL_MD}
=== END SKILL.md ===

{REFERENCE_BLOCK}

Now apply this skill's review process to the code the user shows you. \
There is no PR description in this context (this is a single-file, \
isolated review, not a full pull request) -- skip the "summarize PR \
intent" checkpoint and proceed directly to reviewing the code shown. The \
user's message is itself the full task specification, including the exact \
required JSON output format -- follow it exactly. That JSON schema takes \
precedence over any output template described in the skill above, since \
it's the actual task contract you're being graded against."""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])
    question = (inputs_dir / "question.txt").read_text()

    client = Anthropic(max_retries=10)
    msg = client.messages.create(
        model=args.model,
        max_tokens=1024,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": question}],
    )
    answer = next((b.text for b in msg.content if b.type == "text"), "").strip()
    print(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
