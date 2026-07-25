# baseline-no-skill

No-skill baseline for [`python_bugfix_diff`](https://trapstreet.run/tasks/python-bugfix-diff).

This solution has **no system prompt at all** — `question.txt` is already a
self-contained task spec (role framing + the exact required JSON output
format), so this just sends it verbatim to the model and prints whatever
comes back. No SKILL.md, no reference files, no tool calls.

**Purpose:** any code-review skill solution submitted against this task should
be compared against this floor. If a skill doesn't score meaningfully higher
than this, it isn't earning its keep — it's just a differently-worded prompt
around a model that would've done the same thing anyway.

## Layout

```
solution.py                 # shared: reads question.txt, calls the provider API, prints the answer
claude-opus-4-8/trap.yaml   # Anthropic API, claude-opus-4-8
claude-sonnet-4-6/trap.yaml # Anthropic API, claude-sonnet-4-6
gpt-5.6-luna-pro/trap.yaml  # OpenRouter, openai/gpt-5.6-luna-pro
kimi-k3/trap.yaml           # OpenRouter, moonshotai/kimi-k3
```

Each variant is a subdirectory holding only a `trap.yaml`. The provider and
model are literal CLI arguments on the `cmd:` line (`--provider`, `--model`)
— not an env var — so `profile.model` (the self-reported field shown on the
leaderboard) and the model actually used can never drift out of sync.

## Running

Requires [trap](https://github.com/trapstreet/trap) (`tp`) and `uv`
(`solution.py` declares its `anthropic`/`openai` dependencies via PEP 723
inline script metadata — no separate `pyproject.toml`/`uv.lock` needed).
Credentials come from `.env` via direnv — copy `.env.example` to `.env` and
fill in `ANTHROPIC_API_KEY` and `OPENROUTER_API_KEY`.

```bash
tp run ./claude-opus-4-8 --task python-bugfix-diff --trust-remote
```

`--trust-remote` is needed since the task is now sourced from a pinned
git+URL (see `trap.yaml`) rather than a local path — see the top-level
`trapstreet-solution-scaffold` skill for why it's pinned to an exact
commit SHA rather than tracking the shared task repo's `main` branch.
Each variant keeps its own workspace (`.trap/runs/<solution>/...`) with
per-run reports.
