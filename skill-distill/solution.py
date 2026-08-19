# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic",
# ]
# ///
"""
Runtime path -- this is the only script that runs during a scored `tp run`.
Loads the pre-authored skill.txt (see craft_skill.py / README.md) as the
system prompt and answers with a single cheap-tier model call. No
strong-model calls happen here.
"""

import json
import os
import sys
from pathlib import Path

import anthropic

EXECUTOR_MODEL = "claude-haiku-4-5-20251001"
SKILL_PATH = Path(__file__).parent / "skill.txt"


def read_input():
    manifest = os.environ.get("TRAP_MANIFEST")
    if manifest:
        m = json.loads(manifest)
        with open(os.path.join(m["inputs_dir"], "question.txt")) as f:
            return f.read()
    inputs = os.environ.get("INPUTS")
    if inputs:
        m = json.loads(inputs)
        with open(m["question.txt"]) as f:
            return f.read()
    return sys.stdin.read()


def main():
    question = read_input()
    skill = SKILL_PATH.read_text()

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=EXECUTOR_MODEL,
        max_tokens=1024,
        system=skill,
        messages=[{"role": "user", "content": question}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    print(text)


if __name__ == "__main__":
    main()
