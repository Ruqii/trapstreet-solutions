# influencer-marketing-skill-coreyhaines — trapstreet solution

Runs the community Claude Skill [`coreyhaines31/marketingskills`](https://github.com/coreyhaines31/marketingskills)'s
`influencer-marketing` skill against the
[`influencer_marketing_disclosure`](https://trapstreet.run/tasks/influencer-marketing-disclosure)
task.

`SKILL.md` in this directory is a bundled copy of the real skill (version
1.0.0 at the time this solution was built) — `solution.py` loads it as a
system prompt and applies it via a direct Anthropic API call, no
approximation.

## Run

```bash
tp run . --task influencer-marketing-disclosure --trust-remote
```
