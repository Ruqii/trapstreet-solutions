#!/usr/bin/env bash
# Plays one run of minecraft-obtain-diamond and prints the outcome JSON as the
# last line of stdout, which is what judge.py reads. Everything else is stderr.
#
# This actually plays the game every time. It would be far cheaper to print a
# previously recorded outcome.json, and it would also be a lie: the platform
# re-runs a solution to measure reproducibility, and a static file makes that
# machinery measure nothing.
set -uo pipefail
say() { echo "[run] $*" >&2; }

: "${DEEPSEEK_API_KEY:?run.sh needs DEEPSEEK_API_KEY}"
MC_HOST="${MC_HOST:-127.0.0.1}"
MC_PORT="${MC_PORT:-25565}"
PLUGIN_VERSION="${PLUGIN_VERSION:-0.9.1}"
DSH_PKG="${DSH_PKG:-@deepseek-ai/dsh@0.1.0-rc.6}"

WORK="$(mktemp -d)"
export DSH_HOME="$WORK/dsh"
export MC_RECORD_DIR="${MC_RECORD_DIR:-$WORK/recording}"
export MC_ONE_LIFE=1
export MC_SEED="${MC_SEED:-diamondrun}"
mkdir -p "$MC_RECORD_DIR"

# The server is the entrant's to stand up -- the task says so, and a run
# against someone else's world would not be comparable anyway.
if ! nc -z "$MC_HOST" "$MC_PORT" 2>/dev/null; then
  say "no Minecraft server on $MC_HOST:$MC_PORT. Start a Java 1.20.4 offline-mode server first."
  echo '{"obtained": false, "item": "diamond", "count": 0, "inventory": [], "milestones": [], "video": "", "error": "no server reachable"}'
  exit 1
fi

say "installing dsh-minecraft@$PLUGIN_VERSION"
npx -y "$DSH_PKG" --profile headless --dump-config >/dev/null 2>&1
npx -y "$DSH_PKG" plugin --profile headless add "dsh-minecraft@$PLUGIN_VERSION" >/dev/null 2>&1

# A DSH profile installs plugin dependencies without running install scripts, so
# the native canvas binary is missing and recording declines silently. 0.11.0+
# repairs this itself; this line is what makes 0.9.1 able to film at all.
CANVAS="$DSH_HOME/profiles/headless/node_modules/canvas"
if [ -d "$CANVAS" ] && [ ! -f "$CANVAS/build/Release/canvas.node" ]; then
  say "building the canvas native module"
  ( cd "$CANVAS" && npm rebuild canvas >/dev/null 2>&1 )
fi

# The game gets its own ceiling, well inside trap's. Without one the whole
# script was killed at the outer timeout with exit 124 and empty stdout: the
# mux never ran and the outcome was never printed, so a real run scored 0.0 for
# having said nothing. The task's own limit is 30 minutes; leave the rest of
# trap's budget for finishing up.
PLAY_SECONDS="${PLAY_SECONDS:-1800}"
say "playing (ceiling ${PLAY_SECONDS}s)"
npx -y "$DSH_PKG" --profile headless \
  "You are playing Minecraft on a local survival server. Connect to it, then obtain a diamond, and report your full inventory at the end." \
  >&2 2>/dev/null &
play_pid=$!
( sleep "$PLAY_SECONDS"; kill -TERM $play_pid 2>/dev/null ) & watchdog=$!
wait $play_pid; play_rc=$?
kill -TERM $watchdog 2>/dev/null
say "play finished (rc=$play_rc)"

# A run killed at its ceiling never reaches mc_disconnect, so the frames are on
# disk with no mp4 and outcome.json still has an empty video field. Finish both
# here rather than submitting a diamond run that scores zero for lack of a link.
if [ ! -f "$MC_RECORD_DIR/run.mp4" ] && [ -d "$MC_RECORD_DIR/frames" ]; then
  say "muxing frames left behind by a killed run"
  ffmpeg -y -framerate 10 -i "$MC_RECORD_DIR/frames/f%06d.jpg" -c:v libx264 \
    -pix_fmt yuv420p -vf scale=1280:720 "$MC_RECORD_DIR/run.mp4" >/dev/null 2>&1
fi

python3 - "$MC_RECORD_DIR" <<'PY'
import json, pathlib, sys
d = pathlib.Path(sys.argv[1])
oc = d / "outcome.json"
if not oc.exists():
    print(json.dumps({"obtained": False, "item": "diamond", "count": 0,
                      "inventory": [], "milestones": [], "video": "",
                      "error": "the run produced no outcome.json"}))
    raise SystemExit(0)
o = json.loads(oc.read_text())
mp4 = d / "run.mp4"
# Local path only. Replace with a public URL before submitting if you want the
# recording to mean anything to a reader -- the judge only checks it is non-empty.
if not o.get("video") and mp4.exists():
    o["video"] = str(mp4)
o.pop("partial", None)
print(json.dumps(o))
PY
