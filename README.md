# trapstreet-solutions

All [trapstreet.run](https://trapstreet.run) solutions in one place, organized by task
so they're findable — replaces a growing pile of separate single-purpose repos.

```
trapstreet-solutions/
  baseline-no-skill/                    # cross-task: bare model, no system prompt, no skill
    solution.py
    claude-opus-4-8/trap.yaml
    claude-sonnet-4-6/trap.yaml
    gpt-5.6-luna-pro/trap.yaml
    kimi-k3/trap.yaml
  code_review_skill/                    # solutions for tasks/code_review_skill/python_bugfix_diff
    jeffallan/                          # Jeffallan/claude-skills, multi-model
    awesome/                            # community "awesome" code-review skill
    alireza/                            # alirezarezvani/claude-skills
  influencer_marketing_disclosure/      # solutions for tasks/influencer_marketing_disclosure
    coreyhaines/                        # coreyhaines31/marketingskills
    nexscope/                           # nexscope-ai/eCommerce-Skills
    mohitagw/                           # mohitagw15856/pm-claude-skills
    cgallic/                            # cgallic/kai-cmo-harness
  pdf_reader/                           # solutions for tasks/pdf_reader (task slug: pdf-reader)
    claude-pdf/                         # was Ruqii/claude-pdf — direct vision-LLM, no parser
    smolagents/                         # was Ruqii/smolagents-claude — CodeAgent + PDF vision tool
    smolagents-split/                   # was Ruqii/smolagents-claude-split — opus vision / sonnet planner
    mineru/                             # was Ruqii/mineru-claude — MinerU parser → Claude
    marker/                             # was Ruqii/marker-claude — Marker parser → Claude
```

`pdf_reader/`'s five solutions predate the current `trap-cli` contract: their
`trap.yaml` uses the old `tasks: {<alias>: {solution:, traptask:, ...}}` shape
and `solution.py` reads `INPUTS`/`OUTPUTS` env vars instead of the current
`TRAP_MANIFEST`. They won't run as-is under the current CLI — kept here for
reference/portfolio purposes, migrate schema + manifest handling before
re-running any of them.

Each solution subdirectory works exactly like a standalone repo did before —
`tp run <path> --task <alias> --trust-remote` from inside it, same as always.

## Why one repo instead of many

A previous attempt at this (a monorepo tried in an earlier phase of this
project) was abandoned because `tp run`'s provenance requires a **clean**
working tree at run time, and a monorepo with many solutions being actively
iterated on tends to have *something* uncommitted somewhere — which
silently strips solution-side git provenance for everyone, not just the
one being edited.

The fix isn't structural, it's discipline: **always commit and push before
running**, never run with unrelated uncommitted changes sitting elsewhere
in the tree. As long as that holds, one well-organized repo works fine —
`baseline-no-skill` has run this way (multiple model variants, one repo)
for the whole time it's existed without an issue.
