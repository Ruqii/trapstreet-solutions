#!/usr/bin/env bash
# DeepSeek Harness + dsh_workflow against one ledger_close case.
#
# Identical to the dsh-noplugins entry except that one plugin is installed
# into the profile, so a difference in score between the two entries is
# attributable to the plugin and not to anything else.
set -uo pipefail

: "${TRAP_MANIFEST:?run.sh must run under trap}"
: "${DEEPSEEK_API_KEY:?set DEEPSEEK_API_KEY before running}"

DSH="npx -y @deepseek-ai/dsh@0.1.0-rc.6"
PLUGIN_REPO="github:icetomoyo/dsh_workflow"
PLUGIN_NAME="@dsh-external/workflow"
export DSH_HOME="${TMPDIR:-/tmp}/dsh-workflow-home"

# Install once, then reuse across cases. Bootstrapping and pnpm-installing on
# every case would add minutes per case for no benefit.
if [ ! -d "$DSH_HOME/profiles/headless/node_modules/$PLUGIN_NAME" ]; then
    $DSH --profile headless --dump-config >/dev/null 2>&1   # bootstrap the home
    $DSH plugin --profile headless add "$PLUGIN_REPO" >&2
fi

# Installing is not the same as activating: a package only becomes a profile
# layer if it declares dsh.bundle, and dsh warns on stderr rather than
# failing when it does not. Read the composed tree and refuse to run a
# "with-plugin" entry that is silently running without the plugin.
if ! $DSH --profile headless --dump-config 2>/dev/null | grep -q "$PLUGIN_NAME"; then
    echo "FATAL: $PLUGIN_NAME is not in the composed profile tree" >&2
    exit 3
fi

INPUTS=$(python3 -c '
import json, os, sys
sys.stdout.write(json.loads(os.environ["TRAP_MANIFEST"])["inputs_dir"])')

WORK=$(mktemp -d "${TMPDIR:-/tmp}/ledger-close.XXXXXXXX")
trap 'rm -rf "$WORK"' EXIT INT TERM
cp -R "$INPUTS"/. "$WORK"/

cd "$WORK" || exit 1
$DSH --profile headless \
    "Read README.md in this directory and carry out what it asks. Follow its output instructions exactly."
