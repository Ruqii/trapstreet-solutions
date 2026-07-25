# influencer-marketing-skill-mohitagw — trapstreet solution

Runs the community Claude Skill [`mohitagw15856/pm-claude-skills`](https://github.com/mohitagw15856/pm-claude-skills)'s
`influencer-brief` skill against the
[`influencer_marketing_disclosure`](https://trapstreet.run/tasks/influencer-marketing-disclosure)
task.

Notable about this skill going into this comparison: its actual
job-to-be-done is narrower than the other three — it's a campaign-brief
*document generator* (deliverables, timeline, creative guidelines
template), not a full advisory skill across sourcing/vetting/deal
structuring. Worth watching in particular on the `no_script` cases: a
skill whose entire purpose is producing detailed briefs could plausibly
lean toward over-specifying wording rather than correctly declining a
literal word-for-word script request.

`SKILL.md` in this directory is a bundled copy of the real skill —
`solution.py` loads it as a system prompt and applies it via a direct
Anthropic API call, no approximation.

## Run

```bash
tp run . --task influencer-marketing-disclosure --trust-remote
```
