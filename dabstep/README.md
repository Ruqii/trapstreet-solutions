# dabstep: model × harness

Four arms on the `dabstep` task (DABStep's questions, 25 cases: 5 easy, 20 hard),
built to separate what the model contributes from what the harness contributes,
and what each costs.

| Arm (board name) | Model | Harness | Route |
|---|---|---|---|
| `mini-loop-claude-opus-5` (claude-opus-5 · mini-loop) | claude-opus-5 | mini-loop | Anthropic API |
| `mini-loop-deepseek-flash` (deepseek-flash · mini-loop) | deepseek-flash | mini-loop | DeepSeek, OpenAI format |
| `claude-code-deepseek-flash` (deepseek-flash · claude-code) | deepseek-flash | Claude Code | DeepSeek, Anthropic format |
| `dsh-deepseek-flash` (deepseek-flash · dsh) | deepseek-flash | DeepSeek Harness (0.1.5-rc.1, locked) | DeepSeek, OpenAI format |
| `claude-code-claude-opus-5` (claude-opus-5 · claude-code) | claude-opus-5 | Claude Code | Anthropic API |
| `claude-code-kimi-k3` (kimi-k3 · claude-code) | kimi-k3 | Claude Code | Moonshot, Anthropic format |
| `claude-code-glm-5.3-flash` (z-ai/glm-5.3-flash · claude-code) | z-ai/glm-5.3-flash | Claude Code | OpenRouter, Anthropic format |

The two mini-loop arms run the same file, [`mini_loop.py`](mini_loop.py), so
their difference is the model. The three deepseek-flash arms share a model, so
their differences are the harness. mini-loop is DABStep's ReAct baseline
shape: one `run_python` tool, at most 10 runs, then a final answer, with no
planning, sub-agents or context management.

The claude-code arms share [`claude_code.py`](claude_code.py) (the first one,
`claude-code-deepseek-flash`, runs the same logic from its own `solution.py`).
Each is set up the way its vendor documents Claude Code: Anthropic with the
defaults (Claude Code's own small/fast model for side calls); Kimi per Kimi's
guide (kimi-k3[1m] everywhere but the haiku slot, kimi-k2.7-code; effort max;
a 1M auto-compact window); DeepSeek and GLM with every model slot pinned to the
one model. A third-party key goes in `ANTHROPIC_AUTH_TOKEN` with
`ANTHROPIC_API_KEY` blanked. GLM goes through OpenRouter, whose cached tokens
the site cannot price yet, so its cost can show as unknown.

## Held fixed across arms

- **The question.** Each arm reads the case's `question.txt` and works in a
  scratch copy of the case directory (symlinks dereferenced), so the seven
  files are real files and nothing is written into the task.
- **Thinking.** Each arm uses its vendor's default: adaptive on Opus 5, on at
  effort high on DeepSeek.
- **Prompt caching.** Each arm uses its vendor's standard mechanism. DeepSeek
  caches on its own. For Claude mini-loop turns on automatic caching (one
  top-level `cache_control`). Both loop arms therefore resend their growing
  transcript at cache rates, and their cost difference, like their score
  difference, is the model's.
- **Time.** Every arm gets 1800 seconds per case.
- **No network beyond the model.** Web search and fetch are off, and every
  HTTP(S) proxy variable points at a closed port for the harness and anything
  it runs. Loopback, where the cost proxy listens, is exempt.
- **Python.** Code runs under the `python3` on PATH (pandas, numpy).
- **No refusal fallback.** A fallback answers with a different model, so the arm
  would no longer be the model it names. mini-loop logs a refusal and its
  category to stderr and gives no ANSWER line. Refusals are counted as their own
  outcome, not folded into wrong answers.

## Running an arm

```bash
cp dabstep/.env.example dabstep/.env          # then fill in both keys
direnv allow dabstep dabstep/*/
cd dabstep/mini-loop-claude-opus-5 && tp run --server https://uat.trapstreet.run
```

tp's cost proxy reads each vendor's key and upstream from the shell that runs
`tp run`, so both come from direnv:

- `dabstep/.envrc` loads the keys from `dabstep/.env` (gitignored:
  `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY`,
  `OPENROUTER_API_KEY`) for every arm;
- each claude-code arm's `.envrc` sets `ANTHROPIC_BASE_URL` to its vendor's
  endpoint (Anthropic, DeepSeek, Moonshot or OpenRouter), the upstream the
  proxy forwards that arm's requests to;
- each arm's `.envrc` sets `TRAP_AGENT` to its harness. A site-graded run that
  declares no name is listed as `<model> · <agent>`, so the board reads
  `deepseek-flash · mini-loop`, `deepseek-flash · claude-code` and so on.

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
