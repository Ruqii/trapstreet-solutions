# dabstep: model × harness

Four arms on the `dabstep` task (DABStep's questions, 25 cases: 5 easy, 20 hard),
built to separate what the model contributes from what the harness contributes,
and what each costs.

| Arm | Model | Harness | Route |
|---|---|---|---|
| `minimal-loop-opus5` | claude-opus-5 | minimal loop | Anthropic API |
| `minimal-loop-deepseek-flash` | deepseek-flash | minimal loop | DeepSeek, OpenAI format |
| `claude-code-deepseek-flash` | deepseek-flash | Claude Code | DeepSeek, Anthropic format |
| `dsh-deepseek-flash` | deepseek-flash | DeepSeek Harness (0.1.5-rc.1, locked) | DeepSeek, OpenAI format |

The two minimal-loop arms run the same file, [`minimal_loop.py`](minimal_loop.py), so
their difference is the model. The three deepseek-flash arms share a model, so
their differences are the harness. The minimal loop is DABStep's ReAct baseline
shape: one `run_python` tool, at most 10 runs, then a final answer, with no
planning, sub-agents or context management.

## Held fixed across arms

- **The question.** Each arm reads the case's `question.txt` and works in a
  scratch copy of the case directory (symlinks dereferenced), so the seven
  files are real files and nothing is written into the task.
- **Thinking.** Each arm uses its vendor's default: adaptive on Opus 5, on at
  effort high on DeepSeek.
- **Prompt caching.** Each arm uses its vendor's standard mechanism. DeepSeek
  caches on its own. For Claude the minimal loop turns on automatic caching (one
  top-level `cache_control`). Both loop arms therefore resend their growing
  transcript at cache rates, and their cost difference, like their score
  difference, is the model's.
- **Time.** Every arm gets 1800 seconds per case.
- **No network beyond the model.** Web search and fetch are off, and every
  HTTP(S) proxy variable points at a closed port for the harness and anything
  it runs. Loopback, where the cost proxy listens, is exempt.
- **Python.** Code runs under the `python3` on PATH (pandas, numpy).
- **No refusal fallback.** A fallback answers with a different model, so the arm
  would no longer be the model it names. The minimal loop logs a refusal and its
  category to stderr and gives no ANSWER line. Refusals are counted as their own
  outcome, not folded into wrong answers.

## Running an arm

```bash
cp dabstep/.env.example dabstep/.env          # then fill in both keys
direnv allow dabstep dabstep/claude-code-deepseek-flash
cd dabstep/minimal-loop-opus5 && tp run
```

tp's cost proxy reads each vendor's key and upstream from the shell that runs
`tp run`, so both come from direnv:

- `dabstep/.envrc` loads the keys from `dabstep/.env` (gitignored:
  `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`) for every arm;
- `claude-code-deepseek-flash/.envrc` also sets `ANTHROPIC_BASE_URL` to
  DeepSeek's Anthropic-format endpoint, the upstream the proxy forwards that
  arm's requests to.

Each solution refuses to start if its model calls would not pass through the
proxy.

The task is graded on uat.trapstreet.run, so pass `--server
https://uat.trapstreet.run` to send the answers there. Leave `TRAPSTREET_URL`
unset: tp also reads its price table from that variable, and only the
production table prices `deepseek-flash`.

## Reading the cost

Each case in `report.json` has `cost.by_model[]` with:

- `prompt_tokens`: uncached input;
- `cache_read_tokens` and `cache_write_tokens`;
- `completion_tokens`;
- `cost_usd`: the total;
- `cache_cost_usd`: the part of `cost_usd` spent on cache.

Two things to check on a first run:

- `by_model` should list only the arm's own model id.
- On `claude-code-deepseek-flash`, `cache_read_tokens` should be non-zero.
  DeepSeek's Anthropic-format endpoint does not document its cache fields. If it
  reports none, that arm's cost is an upper bound, while the OpenAI-format arms'
  costs are exact.

DeepSeek bills double during its peak hours (01:00–04:00 and 06:00–10:00 UTC,
Monday to Friday). The price table carries the off-peak rate.
