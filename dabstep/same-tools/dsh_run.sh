#!/usr/bin/env bash
# DSH on the same-tools board: its own tools off, the three shared tools mounted
# over MCP (same-tools/mcp_server.py), everything else as dsh-deepseek-flash runs
# it -- same pinned install, same stock headless profile, same jail, same
# per-case DSH_HOME, same session log kept for the audit.
#
# DSH's MCP client names a server's tools mcp__<serverName>__<tool>, which is
# also what Claude Code does, so with serverName "bench" both harnesses show the
# model the same names. What each offers is not taken on trust: run
# same-tools/probe_tools.py against this script and read the tool list it prints.
#
#   MODEL=deepseek-flash bash dsh_run.sh
set -uo pipefail

: "${TRAP_MANIFEST:?run under trap}"
: "${DEEPSEEK_API_KEY:?DEEPSEEK_API_KEY must be in the shell that runs tp (dabstep/.env via direnv)}"
case "${DEEPSEEK_BASE_URL:-}" in
    http://127.0.0.1:*|http://localhost:*) ;;
    *) echo "DEEPSEEK_BASE_URL is not the tp cost proxy; load dabstep/.env (direnv allow) before tp run" >&2; exit 2 ;;
esac

HERE=$(cd "$(dirname "$0")" && pwd)          # dabstep/same-tools
ARMS=$(cd "$HERE/.." && pwd)                 # dabstep
SANDBOX="$ARMS/sandbox.py"
LOCK_ID=$(shasum -a 256 "$ARMS/dsh-deepseek-flash/package-lock.json" | cut -c1-12)
TMP="${TMPDIR:-/tmp}"; TMP="${TMP%/}"
PREFIX="$TMP/dsh-dabstep-$LOCK_ID"
DSH="$PREFIX/node_modules/.bin/dsh"
TEMPLATE="$TMP/dsh-dabstep-home-template-$LOCK_ID"
export NODE_OPTIONS="--max-old-space-size=8192"

# Install and compose outside the jail, while the network is open; only the
# first case does any work here.
if [ ! -x "$DSH" ]; then
    mkdir -p "$PREFIX" \
        && cp "$ARMS/dsh-deepseek-flash/package.json" "$ARMS/dsh-deepseek-flash/package-lock.json" "$PREFIX"/ \
        && npm ci --silent --no-audit --no-fund --prefix "$PREFIX" >&2 || exit 1
fi
if [ ! -d "$TEMPLATE/profiles/headless" ]; then
    mkdir -p "$TEMPLATE/agents" \
        && DSH_HOME="$TEMPLATE" DSH_AGENTS_HOME="$TEMPLATE/agents" \
           "$DSH" --profile headless --dump-config >/dev/null 2>&1 || exit 1
fi
echo "{\"event\": \"start\", \"dsh\": \"$("$DSH" --version 2>/dev/null)\", \"lock\": \"$LOCK_ID\", \"tools\": \"same-tools over MCP\"}" >&2

{ read -r INPUTS; read -r OUTPUTS; read -r PORT; } < <(python3 -c '
import json, os, sys
sys.path.insert(0, sys.argv[1])
import sandbox
m = json.loads(os.environ["TRAP_MANIFEST"])
print(m["inputs_dir"], m["outputs_dir"], sandbox.proxy_port(os.environ["DEEPSEEK_BASE_URL"]), sep="\n")' "$ARMS")
[ -n "${PORT:-}" ] || exit 1
ROOT=$(cd "$(mktemp -d "$TMP/dabstep-dsh-same.XXXXXXXX")" && pwd -P)
keep() {
    [ -d "$ROOT/dsh-home/sessions" ] && mkdir -p "$OUTPUTS/transcripts" \
        && cp -R "$ROOT/dsh-home/sessions"/. "$OUTPUTS/transcripts"/
}
trap 'keep; rm -rf "$ROOT"' EXIT
trap 'exit 143' INT TERM
mkdir -p "$ROOT/work" "$ROOT/home" "$ROOT/tmp"
cp -RL "$INPUTS"/. "$ROOT/work"/
cp -R "$TEMPLATE" "$ROOT/dsh-home"
# The two files, never the directory: $HERE holds the arms, and an arm's .trap/
# holds tp's checkout of the task -- every other case's question.
mkdir -p "$ROOT/tools"
cp "$HERE/tools.py" "$HERE/mcp_server.py" "$ROOT/tools"/

# Every tool plugin the stock headless profile mounts, off; the shared tools on.
# A plugin left on would be a tool this board says is not there.
cat > "$ROOT/dsh-home/same-tools.patch.yml" <<PATCH
- id: tool-bash
  disabled: true
- id: tool-pwsh
  disabled: true
- id: tool-jobs
  disabled: true
- id: tool-fs
  disabled: true
- id: tool-fs-search
  disabled: true
- id: tool-skill
  disabled: true
- id: tool-subagent
  disabled: true
- id: tool-subagent-control
  disabled: true
- id: tool-subagent-list-agents
  disabled: true
- id: tool-subagent-fork
  disabled: true
- id: tool-workflow
  disabled: true
- id: tool-todo
  disabled: true
- id: tool-goal
  disabled: true
- id: tool-ralph
  disabled: true
- id: tool-web
  disabled: true
- id: plan-mode
  disabled: true   # it is what offers exit_plan_mode
# --patch can only change an entry that exists; a new plugin goes in with insert.
- insert:
    - id: mcp-bench
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: bench
        transport: stdio
        command: python3
        args: ['$ROOT/tools/mcp_server.py']
        cwd: '$ROOT/work'
PATCH

export DSH_HOME="$ROOT/dsh-home"
export DSH_AGENTS_HOME="$DSH_HOME/agents"
export DSH_PERMISSION_MODE=danger-full-access   # sandboxes do not nest; the jail confines it
unset ANTHROPIC_API_KEY ANTHROPIC_BASE_URL

PROMPT="$(cat "$ROOT/work/question.txt")

The files are in the current working directory."

export DEEPSEEK_SEARCH_BASE_URL=http://127.0.0.1:9
export HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 ALL_PROXY=http://127.0.0.1:9
export http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9
unset NO_PROXY no_proxy

cd "$ROOT/work" || exit 1
python3 "$SANDBOX" --root "$ROOT" --ro "$PREFIX" --ro "$TEMPLATE" --port "$PORT" \
    --timeout $(( ${DABSTEP_DEADLINE_S:-1700} - SECONDS )) -- \
    "$DSH" --profile headless --patch "$DSH_HOME/same-tools.patch.yml" "$PROMPT"
