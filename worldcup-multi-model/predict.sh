#!/usr/bin/env bash
# Run a model on a World Cup task and keep the leaderboard ENGINE label in sync.
#
#   ./predict.sh <task> [model]
#   ./predict.sh worldcup-pan-cro claude-opus-4-8
#   ./predict.sh worldcup-pan-cro openai/gpt-5.5
#
# It sets every task's `solution:` in trap.yaml to <model> (you run one model at a
# time across matches), so what you submit can't be mislabelled as the wrong model.
# Submit AFTER the match is graded:  tp submit <task>
set -euo pipefail

task="${1:?usage: ./predict.sh <task> [model]}"
model="${2:-${MODEL:-claude-opus-4-8}}"

# Sync the engine label (every `solution:` line) to the model actually being run.
sed -i '' "s|^\([[:space:]]*solution:\).*|\1 ${model}|" trap.yaml

echo ">> running ${task} with MODEL=${model} (engine label synced)"
MODEL="${model}" tp run "${task}"

cat <<EOF

Done. Prediction captured (cached under predictions/).
- Pre-match: this case is UNGRADED — do NOT 'tp submit' yet (it would post 0%).
- After full time, in ../../trapstreet-tasks/tasks/<dir>/:
    ODDS_API_KEY=... python3 snapshot.py && python3 grade.py
  then back here:
    ./predict.sh ${task} ${model}      # replays the cached prediction, now scores
    tp submit ${task}                  # engine label already = ${model}
EOF
