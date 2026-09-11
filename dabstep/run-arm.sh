#!/usr/bin/env bash
# Launch one dabstep arm under tp, with the environment that arm's cost
# metering needs. Extra arguments go to `tp run`, e.g.
#
#   dabstep/run-arm.sh minimal-loop-opus5 -t easy
#
# tp's cost proxy takes each vendor's upstream from tp's own environment and
# only intercepts a vendor whose key is already set there. So the keys and the
# Anthropic-format upstream are set here, around `tp run`, and never inside a
# solution (a solution that sets a base URL bypasses the proxy and records no
# cost).
set -euo pipefail

ARM=${1:?usage: run-arm.sh <arm> [tp run args...]}
shift
HERE=$(cd "$(dirname "$0")" && pwd)
[ -d "$HERE/$ARM" ] || { echo "no arm named $ARM in $HERE" >&2; exit 2; }

# Keys live in dabstep/.env (gitignored): ANTHROPIC_API_KEY, DEEPSEEK_API_KEY.
if [ -f "$HERE/.env" ]; then
    set -a; . "$HERE/.env"; set +a
fi

# Price every arm against the same table, the production one. UAT's table has
# no deepseek-flash row, so a DeepSeek arm priced there records a null cost.
unset TRAPSTREET_URL

case "$ARM" in
    minimal-loop-opus5)
        : "${ANTHROPIC_API_KEY:?}"
        export ANTHROPIC_BASE_URL=https://api.anthropic.com ;;
    claude-code-deepseek-flash)
        : "${DEEPSEEK_API_KEY:?}"
        export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic ;;
    minimal-loop-deepseek-flash|dsh-deepseek-flash)
        : "${DEEPSEEK_API_KEY:?}"
        export ANTHROPIC_BASE_URL=https://api.anthropic.com ;;
    *) echo "run-arm.sh does not know how to meter $ARM" >&2; exit 2 ;;
esac

cd "$HERE/$ARM"
exec tp run "$@"
