# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Framework under test: Claude Code itself, run headless (`claude -p`) as
the agent. This is NOT a bare API relay -- it shells out to the real `claude`
CLI so the agent gets Claude Code's actual read/search/bash tool loop, the
same thing a developer would get interactively, just non-interactive.

Tools are explicitly scoped to read-only + `python3` execution (no Write/
Edit/general Bash) -- the agent never mutates inputs_dir directly, it must
report its fix as a JSON edit list on stdout per the task's own README.md
contract (already present in inputs_dir, no need to restate it here).

`--bare` skips hooks/CLAUDE.md/memory/plugin sync so the run is
deterministic and isolated from whatever's configured on this machine, and
pins auth strictly to ANTHROPIC_API_KEY.

Model is baked into this variant's trap.yaml `cmd:` as a literal CLI arg,
not read from an env var -- see baseline-no-skill/solution.py in this repo
for why (profile.model and the model actually used must never drift apart).

Known scope limit: `claude` only talks to Anthropic models. There is no
Kimi K2/K3 variant of this solution -- testing this task against Kimi
requires a different framework (e.g. Aider/OpenHands/SWE-agent via
OpenRouter or Moonshot's API) with its own solution.py.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

PROMPT = (
    "Read ticket.md and README.md in the current directory, and whatever "
    "CSV and .py files you need to understand and fix the issue described "
    "in the ticket. Follow README.md's Output format section exactly. "
    "Output ONLY the JSON array of edits -- no other text, no markdown fences."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])

    result = subprocess.run(
        [
            "claude", "-p", PROMPT,
            "--model", args.model,
            "--output-format", "text",
            "--allowedTools", "Read Glob Grep Bash(python3:*)",
            "--bare",
        ],
        cwd=inputs_dir,
        capture_output=True, text=True, timeout=380,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI exited {result.returncode}: {result.stderr[:2000]}")

    print(result.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
