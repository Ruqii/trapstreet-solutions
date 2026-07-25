# code-review-skill-awesome — trapstreet solution

Runs the community Claude Skill [`awesome-skills/code-review-skill`](https://github.com/awesome-skills/code-review-skill)
against the [`python-bugfix-diff`](https://trapstreet.run/tasks/python-bugfix-diff)
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
