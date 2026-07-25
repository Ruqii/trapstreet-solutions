"""Code-review Claude Skill solution: loads the real community SKILL.md
(sitting next to this script) PLUS its full set of Python-relevant and
cross-cutting reference guides (under reference/), and applies them to
review the one file shown in each case's question.txt, via a direct
Anthropic API call.

The skill's other-language reference files (react.md, vue.md, rust.md,
etc.) are intentionally NOT included -- this task is Python-only, so those
guides can never be relevant. Everything Python-relevant or language-
agnostic that the skill's own dispatch table points to for a Python case
IS included, so the skill's full designed methodology is available, not
just its top-level SKILL.md summary.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from anthropic import Anthropic

MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")
HERE = Path(__file__).resolve().parent
SKILL_MD = (HERE / "SKILL.md").read_text()

REFERENCE_FILES = [
    "reference/python.md",
    "reference/architecture-review-guide.md",
    "reference/performance-review-guide.md",
    "reference/security-review-guide.md",
    "reference/code-quality-universal.md",
    "reference/common-bugs-checklist.md",
    "reference/code-review-best-practices.md",
    "reference/cross-cutting/sql-injection-prevention.md",
    "reference/cross-cutting/n-plus-one-queries.md",
    "reference/cross-cutting/error-handling-principles.md",
    "reference/cross-cutting/async-concurrency-patterns.md",
]

REFERENCE_BLOCK = "\n\n".join(
    f"=== BEGIN {path} ===\n{(HERE / path).read_text()}\n=== END {path} ==="
    for path in REFERENCE_FILES
)

SYSTEM = f"""You must act EXACTLY as Claude would when the following Claude \
Skill is loaded and active. This is a real Skill file (SKILL.md format), \
shown below along with the full text of every reference guide it points to \
that could be relevant to a Python code review (its guides for other \
languages like React/Vue/Rust/etc. are omitted as genuinely inapplicable \
here). Internalize the skill's review methodology, principles, and \
process -- including these reference guides, exactly as the skill's own \
dispatch table intends -- and apply it faithfully when reviewing the code \
the user shows you.

=== BEGIN SKILL.md ===
{SKILL_MD}
=== END SKILL.md ===

{REFERENCE_BLOCK}

Now apply this skill's review process to the code the user shows you. The \
user's message is itself the full task specification, including the exact \
required JSON output format -- follow it exactly. That JSON schema takes \
precedence over any output template described in the skill above, since \
it's the actual task contract you're being graded against."""


def main() -> int:
    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])
    question = (inputs_dir / "question.txt").read_text()

    client = Anthropic(max_retries=10)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": question}],
    )
    answer = next((b.text for b in msg.content if b.type == "text"), "").strip()
    print(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
