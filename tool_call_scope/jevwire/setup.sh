#!/usr/bin/env bash
# jevwire publishes no package, so the arm builds it from a pinned commit.
# The plugin its own build produces (plugin/dist/hook.mjs) is what the adapter
# runs -- the same file the Claude Code plugin registers.
set -euo pipefail
COMMIT=757468d6743f55225b9635e1d5f24524da79c2bc
here="$(cd "$(dirname "$0")" && pwd)"
src="$here/src-jevwire"
if [ ! -d "$src/.git" ]; then
  git clone -q https://github.com/Brainwires/jevwire "$src"
fi
git -C "$src" fetch -q --depth 1 origin "$COMMIT" 2>/dev/null || git -C "$src" fetch -q origin
git -C "$src" checkout -q "$COMMIT"
(cd "$src" && npm ci --silent >/dev/null 2>&1 || npm install --silent >/dev/null 2>&1)
(cd "$src" && npm run build --silent >/dev/null)
test -f "$src/plugin/dist/hook.mjs" || { echo "jevwire: build produced no plugin/dist/hook.mjs" >&2; exit 1; }
echo "jevwire built at $COMMIT"
