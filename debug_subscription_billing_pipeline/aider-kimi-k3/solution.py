# /// script
# requires-python = ">=3.10"
# dependencies = ["aider-chat", "audioop-lts; python_version>='3.13'"]
# ///
"""Framework under test: Aider, run non-interactively, backed by Kimi K3
(Moonshot AI, routed through litellm's native `moonshot/` provider --
MOONSHOT_API_KEY, default base https://api.moonshot.ai/v1).

Aider's native mode is to edit files in place -- it does not emit a JSON
edit list itself. So this adapter lets Aider edit a scratch copy of the CSVs
as it naturally would, then DIFFS before/after state into the task's
required edit-list format (keyed by each table's own ID column). Aider never
sees the task's own README.md (which instructs a "print JSON to stdout"
contract meant for a different kind of agent) -- ticket.md plus the four
report scripts' own docstrings are enough business context, and mixing in
the JSON-output instruction risks Aider trying to print JSON as chat text
instead of editing files.

`--no-fancy-input` works around a real crash: aider's confirmation UI
(prompt_toolkit) raises OSError([Errno 22] Invalid argument) registering a
non-tty stdin as an asyncio selector on macOS -- happens even with
--yes-always, which only skips the confirm_ask() *decision*, not this UI
setup. --no-fancy-input disables prompt_toolkit entirely.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ID_COLUMN = {
    "customers.csv": "customer_id",
    "subscriptions.csv": "subscription_id",
    "plans.csv": "plan_id",
    "tiers.csv": "tier_id",
    "addons.csv": "addon_id",
    "discount_codes.csv": "code",
    "regions.csv": "region_id",
    "invoices.csv": "invoice_id",
}

READ_ONLY_FILES = [
    "ticket.md",
    "billing_summary.py", "invoice_detail.py",
    "finance_ledger.py", "customer_statement.py",
]

PROMPT = (
    "Read ticket.md for the change request. Read the four report scripts "
    "to understand which fields are baked (historical, frozen at the time) "
    "vs live (recomputed from current tables) -- each script's docstring "
    "explains its own resolution path. Edit ONLY the CSV files, and ONLY "
    "the rows the ticket actually requires, so that all four reports come "
    "out correct after your fix. Do not edit the .py files. Do not touch "
    "rows or tables outside what the ticket calls for."
)


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def normalize(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        return round(float(s), 6)
    except ValueError:
        return s


def diff_tables(before_dir: Path, after_dir: Path) -> list[dict]:
    """Rows deleted by the agent aren't representable in this edit format
    (no delete op) -- the task never requires deletion, so they're silently
    skipped rather than crashing the adapter."""
    edits = []
    for fname, id_col in ID_COLUMN.items():
        before = {r[id_col]: r for r in load_csv(before_dir / fname) if id_col in r}
        after = {r[id_col]: r for r in load_csv(after_dir / fname) if id_col in r}
        for key, after_row in after.items():
            if key not in before:
                edits.append({"file": fname, "op": "insert", "row": after_row})
                continue
            before_row = before[key]
            changed = {
                k: v for k, v in after_row.items()
                if k != id_col and normalize(before_row.get(k)) != normalize(v)
            }
            if changed:
                edits.append({
                    "file": fname, "op": "update",
                    "match": {id_col: key}, "set": changed,
                })
    return edits


def load_dotenv(path: Path) -> None:
    """Minimal .env loader -- .envrc/direnv only activates in an interactive
    shell that cd's into this directory; trap-cli invokes `uv run
    solution.py` as a subprocess directly, bypassing direnv entirely, so
    MOONSHOT_API_KEY must be loaded here or the subprocess never sees it."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    load_dotenv(Path(__file__).parent / ".env")

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])

    with tempfile.TemporaryDirectory() as td:
        work_dir = Path(td) / "work"
        shutil.copytree(inputs_dir, work_dir)

        cmd = [
            "aider",
            "--model", args.model,
            "--model-settings-file", str(Path(__file__).parent / "model_settings.yml"),
            "--yes-always",
            "--no-analytics", "--no-check-update", "--no-show-model-warnings",
            "--no-pretty", "--no-fancy-input", "--no-stream",
            "--no-git", "--no-auto-commits",
            "--message", PROMPT,
        ]
        for f in READ_ONLY_FILES:
            if (work_dir / f).exists():
                cmd += ["--read", f]
        for f in ID_COLUMN:
            if (work_dir / f).exists():
                cmd += ["--file", f]

        result = subprocess.run(
            cmd, cwd=work_dir, capture_output=True, text=True,
            timeout=350, stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            raise RuntimeError(f"aider exited {result.returncode}: {result.stderr[-2000:]}")

        edits = diff_tables(inputs_dir, work_dir)
        print(json.dumps(edits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
