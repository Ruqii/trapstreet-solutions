# frontend_silent_defects — three bare relays

One question: do the six deterministic cases separate frontier models at all?
One arm had run before and passed everything, which is not an answer.

Three arms, identical in every respect but the model — same `solution.py`, a
bare relay with no system prompt, no tools, `max_tokens=16000`:

| arm | model |
|---|---|
| `opus-relay` | `claude-opus-5` |
| `gpt-terra` | `openai/gpt-5.6-terra-pro` (OpenRouter) |
| `kimi-k3` | `moonshotai/kimi-k3` (OpenRouter) |

`opus-relay` repeats the 2026-08-31 probe on the same day as the other two, so
the comparison is not across judge versions.

## Running

The `scored-only` task alias points at a six-case subset built from the real
task — the three open briefs score `null` and cannot answer this question:

```bash
T=../../trapstreet-tasks/unvalidated/frontend_silent_defects
mkdir -p /tmp/task-scored/inputs /tmp/task-scored/expected
cp -R $T/check $T/fixtures $T/judge.py $T/grader.py /tmp/task-scored/
for c in 01 02 03 04 05 06; do
  cp -R $T/inputs/case_$c /tmp/task-scored/inputs/
  cp -R $T/expected/case_$c /tmp/task-scored/expected/
done
# then drop the case_07..09 blocks from a copy of $T/traptask.yaml
```

```bash
tp run --task scored-only
```

## The decision rule, written before the run

- Two arms differing on **two or more cases** → the task discriminates.
- Every arm passing every case → it does not, and it does not ship.
