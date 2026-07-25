# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic",
# ]
# ///
"""Influencer-marketing Claude Skill solution: loads the real community
SKILL.md (sitting next to this script, cgallic/kai-cmo-harness's
kai-influencer skill) and applies it via a direct Anthropic API call.

This skill is designed to run inside a larger project (it expects to read
MARKETING.md and a persona index from the project root, auto-exploring the
codebase to create them if missing). Neither exists in this isolated,
single-question sandbox, so a short note is added telling the model to
skip that context-loading phase and proceed directly using only the
scenario in the user's message -- the fairest way to run a
project-dependent skill in a context with no project to explore, without
silently letting it get stuck trying to read/create files that can't
exist here.
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

SYSTEM = f"""You must act EXACTLY as Claude would when the following Claude \
Skill is loaded and active. This is a real Skill file (SKILL.md format), \
shown below in full. Internalize its methodology, principles, and process, \
and apply it faithfully when advising the user on their influencer/creator \
marketing situation.

=== BEGIN SKILL.md ===
{SKILL_MD}
=== END SKILL.md ===

Note on Phase 0 of this skill: there is no project root, no MARKETING.md, \
and no persona index available in this context -- this is a single, \
isolated scenario question, not a real project you can explore the \
filesystem of. Skip Phase 0 entirely and proceed directly to Phase 1 \
using only the information given in the user's message.

Now apply this skill's guidance to the situation the user describes. The \
user's message is itself the full task specification, including the exact \
required JSON output format -- follow it exactly. That JSON schema takes \
precedence over any output format described in the skill above, since it's \
the actual task contract you're being graded against."""


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
