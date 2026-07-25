# influencer-marketing-skill-cgallic — trapstreet solution

Runs the community Claude Skill [`cgallic/kai-cmo-harness`](https://github.com/cgallic/kai-cmo-harness)'s
`kai-influencer` skill against the
[`influencer_marketing_disclosure`](https://trapstreet.run/tasks/influencer-marketing-disclosure)
task.

Notable about this skill going into this comparison: it's designed to run
inside a larger project (expects to read `MARKETING.md` and a persona
index from the project root, auto-exploring the codebase to create them if
missing). Neither exists in this isolated single-question sandbox, so
`solution.py` adds a short note telling the model to skip that
context-loading phase and proceed directly — the fairest way to run a
project-dependent skill where there's no project to explore.

`SKILL.md` in this directory is a bundled copy of the real skill —
`solution.py` loads it as a system prompt and applies it via a direct
Anthropic API call, no approximation.

## Run

```bash
tp run . --task influencer-marketing-disclosure --trust-remote
```
