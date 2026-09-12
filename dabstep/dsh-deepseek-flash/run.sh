#!/usr/bin/env bash
# DeepSeek Harness 0.1.5-rc.1 (npm's `latest` when this arm was built), stock
# headless profile, zero plugins, on one dabstep case. Its default model is
# deepseek-flash with thinking on at effort high, which is what this arm runs;
# nothing here overrides it.
#
# The case is copied (symlinks dereferenced) into a fresh per-case root, and DSH
# runs in ../sandbox.py's jail there: it reads the case copy, its own install
# and the system trees, writes only the case root, and connects only to the cost
# proxy. DSH's own command sandbox (workspace-write, which limits writes but
# not reads) is switched off with its documented DSH_PERMISSION_MODE, because
# macOS cannot apply a sandbox inside another; the jail is the stricter of the
# two. Each case also gets its own DSH_HOME, so no session, cache or memory
# carries from one case to the next, and its session log is kept in the case's
# outputs_dir for auditing.
set -uo pipefail

: "${TRAP_MANIFEST:?run.sh must run under trap}"
: "${DEEPSEEK_API_KEY:?DEEPSEEK_API_KEY must be in the shell that runs tp (dabstep/.env via direnv)}"
# tp points DEEPSEEK_BASE_URL at its cost proxy only when DEEPSEEK_API_KEY was
# already in tp's own environment. Without the proxy the run spends money and
# records no cost, so refuse before the first request.
case "${DEEPSEEK_BASE_URL:-}" in
    http://127.0.0.1:*|http://localhost:*) ;;
    *) echo "DEEPSEEK_BASE_URL is not the tp cost proxy; load dabstep/.env (direnv allow) before tp run" >&2; exit 2 ;;
esac

# The harness is pinned by package-lock.json, not by a version string: dsh's
# own package.json takes its ~50 sub-packages with caret ranges, which float to
# whatever release candidate is newest on the day of install.
HERE=$(cd "$(dirname "$0")" && pwd)
SANDBOX="$HERE/../sandbox.py"
LOCK_ID=$(shasum -a 256 "$HERE/package-lock.json" | cut -c1-12)
TMP="${TMPDIR:-/tmp}"; TMP="${TMP%/}"
PREFIX="$TMP/dsh-dabstep-$LOCK_ID"
DSH="$PREFIX/node_modules/.bin/dsh"
TEMPLATE="$TMP/dsh-dabstep-home-template-$LOCK_ID"   # a composed profile, never run
export NODE_OPTIONS="--max-old-space-size=8192"   # composing a profile OOMs at node's 2 GB default

# Install the harness and compose its profile, outside the jail and while the
# network is still open. Only the first case does any work here.
if [ ! -x "$DSH" ]; then
    mkdir -p "$PREFIX" && cp "$HERE/package.json" "$HERE/package-lock.json" "$PREFIX"/ \
        && npm ci --silent --no-audit --no-fund --prefix "$PREFIX" >&2 || exit 1
fi
if [ ! -d "$TEMPLATE/profiles/headless" ]; then
    mkdir -p "$TEMPLATE/agents" \
        && DSH_HOME="$TEMPLATE" DSH_AGENTS_HOME="$TEMPLATE/agents" \
           "$DSH" --profile headless --dump-config >/dev/null 2>&1 || exit 1
fi
echo "{\"event\": \"start\", \"dsh\": \"$("$DSH" --version 2>/dev/null)\", \"lock\": \"$LOCK_ID\"}" >&2

{ read -r INPUTS; read -r OUTPUTS; read -r PORT; } < <(python3 -c '
import json, os, sys
sys.path.insert(0, sys.argv[1])
import sandbox
m = json.loads(os.environ["TRAP_MANIFEST"])
print(m["inputs_dir"], m["outputs_dir"], sandbox.proxy_port(os.environ["DEEPSEEK_BASE_URL"]), sep="\n")' "$HERE/..")
[ -n "${PORT:-}" ] || exit 1
ROOT=$(cd "$(mktemp -d "$TMP/dabstep-dsh.XXXXXXXX")" && pwd -P)
keep() {  # the session log, for audit_transcripts.py
    [ -d "$ROOT/dsh-home/sessions" ] && mkdir -p "$OUTPUTS/transcripts" \
        && cp -R "$ROOT/dsh-home/sessions"/. "$OUTPUTS/transcripts"/
}
trap 'keep; rm -rf "$ROOT"' EXIT
trap 'exit 143' INT TERM
mkdir -p "$ROOT/work" "$ROOT/home" "$ROOT/tmp"
cp -RL "$INPUTS"/. "$ROOT/work"/
cp -R "$TEMPLATE" "$ROOT/dsh-home"
export DSH_HOME="$ROOT/dsh-home"
export DSH_AGENTS_HOME="$DSH_HOME/agents"   # empty: no user-global skills or AGENTS.md
export DSH_PERMISSION_MODE=danger-full-access   # the jail confines it; see the top of this file

PROMPT="$(cat "$ROOT/work/question.txt")

The files are in the current working directory."

# No web. DeepSeek's search is a separate request: send it to a closed port.
# Everything else (web_fetch, anything a command tries) goes to a proxy that
# isn't there, and the jail refuses every connection but the cost proxy's.
export DEEPSEEK_SEARCH_BASE_URL=http://127.0.0.1:9
export HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 ALL_PROXY=http://127.0.0.1:9
export http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9
unset NO_PROXY no_proxy

# tp stops a case at trap.yaml's 1800 s with SIGKILL, which no cleanup survives;
# stop DSH first, 1700 s from the start of this script, so the session log is
# still copied out. (DABSTEP_DEADLINE_S is for sandbox_canary.py's timeout check.)
cd "$ROOT/work" || exit 1
python3 "$SANDBOX" --root "$ROOT" --ro "$PREFIX" --ro "$TEMPLATE" --port "$PORT" \
    --timeout $(( ${DABSTEP_DEADLINE_S:-1700} - SECONDS )) -- "$DSH" --profile headless "$PROMPT"
