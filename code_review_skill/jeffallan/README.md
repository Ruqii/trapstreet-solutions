# code-review-skill-jeffallan — trapstreet solution

Runs the community Claude Skill [`Jeffallan/claude-skills`](https://github.com/Jeffallan/claude-skills)
(the `code-reviewer` skill) against the
[`python-bugfix-diff`](https://trapstreet.run/tasks/python-bugfix-diff)
task on [trapstreet.run](https://trapstreet.run).

Loads the skill's real `SKILL.md` content as the system prompt, calls the
Anthropic API directly, and prints the required JSON findings to stdout.

## Layout

```
solution.py                 # shared: loads SKILL.md + references, calls the model, prints the answer
claude-opus-4-8/trap.yaml   # Anthropic API, claude-opus-4-8
claude-sonnet-4-6/trap.yaml # Anthropic API, claude-sonnet-4-6
```

Each variant is a subdirectory holding only a `trap.yaml`. The model is a
literal CLI argument on the `cmd:` line (`--model`) -- not an env var -- so
`profile.model` (the self-reported field shown on the leaderboard) and the
model actually used can never drift out of sync.

## Run

Requires [trap](https://github.com/trapstreet/trap) (`tp`) and `uv`
(`solution.py` declares its `anthropic` dependency via PEP 723 inline
script metadata -- no separate `pyproject.toml`/`uv.lock` needed).
Credentials come from `.env` via direnv -- copy `.env.example` to `.env`
and fill in `ANTHROPIC_API_KEY`.

```bash
tp run python-bugfix-diff --solution ./claude-opus-4-8
tp run python-bugfix-diff --solution ./claude-sonnet-4-6
```

Each variant keeps its own `.trap/` workspace with per-run reports. This
repo needs to sit as a sibling of `trapstreet-tasks` (see each variant's
`trap.yaml` `source:` path).
