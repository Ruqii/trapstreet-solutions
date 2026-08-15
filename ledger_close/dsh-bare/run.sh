#!/usr/bin/env bash
# Stock DeepSeek Harness against one ledger_close case.
#
# The case is copied to a scratch directory before the harness sees it, so
# that anything it writes while working -- scratch scripts, intermediate
# CSVs -- lands there and not in the task's inputs.
set -uo pipefail

: "${TRAP_MANIFEST:?run.sh must run under trap}"
: "${DEEPSEEK_API_KEY:?set DEEPSEEK_API_KEY before running}"

INPUTS=$(python3 -c '
import json, os, sys
sys.stdout.write(json.loads(os.environ["TRAP_MANIFEST"])["inputs_dir"])')

WORK=$(mktemp -d "${TMPDIR:-/tmp}/ledger-close.XXXXXXXX")
trap 'rm -rf "$WORK"' EXIT INT TERM
cp -R "$INPUTS"/. "$WORK"/

cd "$WORK" || exit 1
npx -y @deepseek-ai/dsh@0.1.0-rc.6 --profile headless \
    "Read README.md in this directory and carry out what it asks. Follow its output instructions exactly."
