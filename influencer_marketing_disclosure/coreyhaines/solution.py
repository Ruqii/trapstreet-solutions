# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic",
# ]
# ///
"""Influencer-marketing Claude Skill solution: loads the real community
SKILL.md (sitting next to this script, coreyhaines31/marketingskills'
influencer-marketing skill) and applies it via a direct Anthropic API call.

This skill is fully self-contained in one SKILL.md (no separate
references/ files it depends on to answer a single scenario question), so
the whole file is bundled and used as-is.

Shared across every model variant in this repo: each variant's trap.yaml
picks the model via a --model CLI argument baked directly into its cmd:
line (never a MODEL env var), e.g. ``uv run ../solution.py --model
claude-sonnet-4-6``.
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
