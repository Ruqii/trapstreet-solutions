"""Code-review Claude Skill solution: loads the real community SKILL.md
(sitting next to this script) PLUS its Python language rules (rules/,
languages/), AND -- unlike a purely text-based skill -- actually EXECUTES
this skill's real bundled `code_quality_checker.py` script against the
exact code shown in each case, feeding its genuine deterministic output
into the model's context. This is the skill's own designed methodology
(inline guidance + real scripts), not a text-only approximation of it.

`pr_analyzer.py` and `review_report_generator.py` are not executed: both
require a git diff / a full PR-analysis-plus-quality-analysis pairing that
doesn't exist in this single-file, isolated-snippet context. Their
existence and purpose are still described to the model via the SKILL.md
"Tools" section, which is included verbatim.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from anthropic import Anthropic

MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")
HERE = Path(__file__).resolve().parent
SKILL_MD = (HERE / "SKILL.md").read_text()

REFERENCE_FILES = [
    "rules/universal.md",
    "languages/python.md",
]

REFERENCE_BLOCK = "\n\n".join(
    f"=== BEGIN {path} ===\n{(HERE / path).read_text()}\n=== END {path} ==="
    for path in REFERENCE_FILES
)

LINE_RE = re.compile(r"^\s*(\d+)\| ?(.*)$")
FILE_RE = re.compile(r"^File:\s*(.+)$", re.MULTILINE)


def extract_snippet(question: str) -> tuple[str, str]:
    """Pull the real file path and the de-numbered source code back out of
    question.txt's line-numbered display, so the actual quality-checker
    script can run against real (re-indented, prefix-stripped) Python."""
    file_match = FILE_RE.search(question)
    file_path = file_match.group(1).strip() if file_match else "unknown.py"

    lines = []
    for line in question.splitlines():
        m = LINE_RE.match(line)
        if m:
            lines.append(m.group(2))
    return file_path, "\n".join(lines) + "\n"


def run_quality_checker(file_path: str, source: str) -> str:
    """Materialize the snippet as a real .py file and run the skill's own
    code_quality_checker.py against it, exactly as the skill's dispatch
    table intends for a .py file. Returns the tool's raw JSON output, or a
    clear failure note if the script itself errors."""
    suffix = Path(file_path).suffix or ".py"
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        f.write(source)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [sys.executable, str(HERE / "scripts" / "code_quality_checker.py"),
             tmp_path, "--language", "python", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return (
            f"(code_quality_checker.py exited {result.returncode}, "
            f"no usable output. stderr: {result.stderr.strip()[:500]})"
        )
    except Exception as e:  # noqa: BLE001 -- tool failure must not crash the review
        return f"(code_quality_checker.py failed to run: {e})"
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# Split into a STABLE prefix (identical every case -- SKILL.md + reference
# files -- cached) and a VARYING suffix (this case's live tool output --
# never cached, since it's different every time).
SYSTEM_PREFIX = f"""You must act EXACTLY as Claude would when the following Claude \
Skill is loaded and active. This is a real Skill file (SKILL.md format), \
shown below along with its Python-specific rule files (rules/universal.md, \
languages/python.md) that its own "Loading order for every review" section \
says to always load for a .py file.

=== BEGIN SKILL.md ===
{SKILL_MD}
=== END SKILL.md ===

{REFERENCE_BLOCK}"""


def build_system_suffix(tool_output: str) -> str:
    return f"""=== LIVE OUTPUT of this skill's own scripts/code_quality_checker.py, run \
just now against the EXACT code shown below (via `python \
code_quality_checker.py <file> --language python --json`) ===
{tool_output}
=== END live tool output ===

(Note: this skill's other two scripts, pr_analyzer.py and \
review_report_generator.py, are not run here -- both require a git diff \
between branches or a paired PR-plus-quality analysis that doesn't exist \
in this single-file, isolated-snippet context. Their purpose is described \
in the SKILL.md "Tools" section above.)

Now apply this skill's review process -- including the real tool output \
above, exactly as the skill's own methodology intends -- to the code the \
user shows you. The user's message is itself the full task specification, \
including the exact required JSON output format -- follow it exactly. That \
JSON schema takes precedence over any output template described in the \
skill above, since it's the actual task contract you're being graded \
against."""


def main() -> int:
    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])
    question = (inputs_dir / "question.txt").read_text()

    file_path, source = extract_snippet(question)
    tool_output = run_quality_checker(file_path, source)
    system_suffix = build_system_suffix(tool_output)

    client = Anthropic(max_retries=10)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=[
            {"type": "text", "text": SYSTEM_PREFIX, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": system_suffix},
        ],
        messages=[{"role": "user", "content": question}],
    )
    answer = next((b.text for b in msg.content if b.type == "text"), "").strip()
    print(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
