# code-review-skill-alireza — trapstreet solution

Runs the community Claude Skill [`alirezarezvani/claude-skills`](https://github.com/alirezarezvani/claude-skills)
(the `engineering-team/code-reviewer` skill) against the
[`python-bugfix-diff`](https://trapstreet.run/tasks/python-bugfix-diff)
task on [trapstreet.run](https://trapstreet.run).

Loads the skill's real `SKILL.md` content as the system prompt, calls the
Anthropic API directly (model held constant at `claude-sonnet-4-6` across
all sibling `code-review-skill-*` solutions to isolate the skill's effect),
and prints the required JSON findings to stdout.

## Run

```bash
uv sync
tp run python-bugfix-diff
```

Requires `ANTHROPIC_API_KEY` in the environment and this repo checked out
as a sibling of `trapstreet-tasks` (see `trap.yaml`'s `source:` path).
