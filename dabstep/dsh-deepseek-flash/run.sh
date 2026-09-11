#!/usr/bin/env bash
# DeepSeek Harness 0.1.5-rc.1 (npm's `latest` when this arm was built), stock
# headless profile, zero plugins, on one dabstep case. Its default model is
# deepseek-flash with thinking on at effort high, which is what this arm runs;
# nothing here overrides it.
#
# The case is copied (symlinks dereferenced) to a scratch directory, so
# anything the harness writes lands there and not in the task's inputs.
set -uo pipefail

: "${TRAP_MANIFEST:?run.sh must run under trap}"
: "${DEEPSEEK_API_KEY:?export DEEPSEEK_API_KEY in the shell that runs tp (../run-arm.sh does)}"
# tp points DEEPSEEK_BASE_URL at its cost proxy only when DEEPSEEK_API_KEY was
# already in tp's own environment. Without the proxy the run spends money and
# records no cost, so refuse before the first request.
case "${DEEPSEEK_BASE_URL:-}" in
    http://127.0.0.1:*|http://localhost:*) ;;
    *) echo "DEEPSEEK_BASE_URL is not the tp cost proxy; launch with ../run-arm.sh" >&2; exit 2 ;;
esac

# The harness is pinned by package-lock.json, not by a version string: dsh's
# own package.json takes its ~50 sub-packages with caret ranges, which float to
# whatever release candidate is newest on the day of install.
HERE=$(cd "$(dirname "$0")" && pwd)
LOCK_ID=$(shasum -a 256 "$HERE/package-lock.json" | cut -c1-12)
PREFIX="${TMPDIR:-/tmp}/dsh-dabstep-$LOCK_ID"
DSH="$PREFIX/node_modules/.bin/dsh"
export DSH_HOME="${TMPDIR:-/tmp}/dsh-dabstep-home-$LOCK_ID"
export DSH_AGENTS_HOME="$DSH_HOME/agents"   # empty: no user-global skills or AGENTS.md
export NODE_OPTIONS="--max-old-space-size=8192"   # composing a profile OOMs at node's 2 GB default
mkdir -p "$DSH_AGENTS_HOME"

# Install the harness and compose its profile while the network is still open.
# Only the first case does any work here.
if [ ! -x "$DSH" ]; then
    mkdir -p "$PREFIX" && cp "$HERE/package.json" "$HERE/package-lock.json" "$PREFIX"/ \
        && npm ci --silent --no-audit --no-fund --prefix "$PREFIX" >&2 || exit 1
fi
if [ ! -d "$DSH_HOME/profiles/headless" ]; then
    "$DSH" --profile headless --dump-config >/dev/null 2>&1
fi
echo "{\"event\": \"start\", \"dsh\": \"$("$DSH" --version 2>/dev/null)\", \"lock\": \"$LOCK_ID\"}" >&2

INPUTS=$(python3 -c '
import json, os, sys
sys.stdout.write(json.loads(os.environ["TRAP_MANIFEST"])["inputs_dir"])')
WORK=$(mktemp -d "${TMPDIR:-/tmp}/dabstep-dsh.XXXXXXXX")
trap 'rm -rf "$WORK"' EXIT INT TERM
cp -RL "$INPUTS"/. "$WORK"/

PROMPT="$(cat "$WORK/question.txt")

The files are in the current working directory."

# No web. DeepSeek's search is a separate request: send it to a closed port.
# Everything else (web_fetch, anything a command tries) goes to a proxy that
# isn't there. DSH always reaches loopback directly, so the cost proxy still
# sees every model request.
export DEEPSEEK_SEARCH_BASE_URL=http://127.0.0.1:9
export HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 ALL_PROXY=http://127.0.0.1:9
export http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9
unset NO_PROXY no_proxy

cd "$WORK" || exit 1
"$DSH" --profile headless "$PROMPT"
