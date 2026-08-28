#!/usr/bin/env bash
# Claude Code with one thing added: a memory file that does not move when the
# working directory does.
#
# Nothing here computes an answer or carries one between the sessions. The
# model reads the ledger, does the arithmetic, decides whether to write, and
# in session 2 decides whether to read. All this script supplies is a durable
# address and permission to use it -- which is what a memory plugin supplies.
set -uo pipefail

STORE_DIR="${SMR_STORE_DIR:-$HOME/.trap-smr-memory}"
STORE="$STORE_DIR/store.md"
mkdir -p "$STORE_DIR"

PROMPT="${!#}"

# A store that outlives the run would let session 2 answer from a PREVIOUS
# run's value while this run's session 1 did nothing -- a pass that measured
# nothing. Session 1 is the start of a case, so the store is emptied there.
if [[ "$PROMPT" == *"PART 1 of 2"* ]]; then
    : > "$STORE"
fi

exec claude -p --model sonnet \
    --add-dir "$STORE_DIR" \
    --allowedTools Read Write \
    --append-system-prompt "You have a memory file at $STORE that persists across \
sessions and is independent of the working directory. Read it whenever a session \
begins. When you are asked to remember something, write it there before you finish." \
    "$PROMPT"
