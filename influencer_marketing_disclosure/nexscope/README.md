# influencer-marketing-skill-nexscope — trapstreet solution

Runs the community Claude Skill [`nexscope-ai/eCommerce-Skills`](https://github.com/nexscope-ai/eCommerce-Skills)'s
`tiktok-influencer-marketing` skill against the
[`influencer_marketing_disclosure`](https://trapstreet.run/tasks/influencer-marketing-disclosure)
task.

Notable about this skill going into this comparison: a keyword scan of its
source found **zero** mentions of disclosure, FTC, or gifting anywhere in
it — a genuine content gap, not manufactured, expected to show up directly
on this task's `gifting_disclosure` cases.

`SKILL.md` in this directory is a bundled copy of the real skill —
`solution.py` loads it as a system prompt and applies it via a direct
Anthropic API call, no approximation.

## Run

```bash
tp run . --task influencer-marketing-disclosure --trust-remote
```
