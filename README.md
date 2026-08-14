# trapstreet-solutions

My own reference solutions for [trapstreet.run](https://trapstreet.run) tasks, organized by
task so they're findable — one repo instead of a growing pile of single-purpose ones.

These are examples, not a registry. Solutions live in **their author's own repository**;
anyone can publish from anywhere public and submit a run. This is just where mine happen to
live.

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
  mbti_profile/                         # solutions for the do-llms-dream-of-intj task
    mbti-multi-model/                   # shared solution.py; PERSONA picks the condition
      personas/                         # the .md files a run can carry
      claude-opus-5/trap.yaml
      deepseek-v4-pro/trap.yaml
      glm-5.2/trap.yaml
      gpt-5.6-sol-pro/trap.yaml
  pdf_reader/                           # solutions for the pdf-reader-v2 task
    claude-pdf/                         # direct vision-LLM, no parser          [migrated]
    smolagents-split/                   # opus vision / sonnet planner          [migrated]
    mineru/                             # MinerU parser → Claude                [migrated]
    smolagents/                         # CodeAgent + PDF vision tool           [not migrated]
    marker/                             # Marker parser → Claude               [ABANDONED]
```

### `mbti_profile/` — a variant dir per model, a persona per run

The model is a literal `cmd:` argument in each `<model>/trap.yaml`, so what runs and what
`profile.model` reports are the same string in one file. `PERSONA` stays an env var: it is
the condition varied *across* runs of one model, not part of the model's identity, and
baking it in would mean a directory per (model, persona) cell.

`PERSONA` names a file in `mbti-multi-model/personas/` whose text is prepended to the
system prompt — the slot a `CLAUDE.md` or `soul.md` occupies in a real agent harness.
`PERSONA=bare` prepends nothing and is the control.

```bash
cd mbti_profile/mbti-multi-model/glm-5.2
PERSONA=soul-sentinel tp run . --task do-llms-dream-of-intj --trust-remote
```

`PERSONA` also travels to the board inside `usage.json`, and the task page keys its cards
on `(model, persona)`. That field is the *only* thing that keeps a persona run distinct
there: the platform identifies a solution by `(commit, repo_path)`, so two runs of one
commit that differ only in environment collapse onto the same row identity. Adding a
persona file without also reporting its name produces a card that silently pools two
different conditions.

Which files exist, why each one is there, and what a new one has to avoid to stay
interpretable are in [`mbti-multi-model/personas/README.md`](mbti_profile/mbti-multi-model/personas/README.md).

### `pdf_reader/` migration status

All five predate the current `trap-cli` contract (old `tasks: {<alias>:
{solution:, traptask:}}` yaml, `INPUTS`/`OUTPUTS` env vars instead of
`TRAP_MANIFEST`). Three are now migrated and target **`pdf-reader-v2`**, pinned
at the commit the platform has registered:

| | contract | task alias | notes |
|---|---|---|---|
| `claude-pdf` | current | `pdf-reader-v2` | smoke-tested 2/2; the cheapest and fastest of the three |
| `smolagents-split` | current | `pdf-reader-v2` | migrated, **never run** — agent loop, cost unmeasured |
| `mineru` | current | `pdf-reader-v2` | migrated, **never run** — first case shells out to MinerU (~18 min CPU) |
| `smolagents` | old | `pdf-reader` | not migrated |
| `marker` | old | *(dead path)* | **abandoned — do not migrate** |

`marker` is abandoned: it pulls ~2 GB of Surya weights, is forced onto CPU
(the models exceed the 9 GB MPS limit on Apple Silicon), and its `traptask:`
points at `tasks/pdf_reader/tenancy_agreement`, a path that no longer exists.
The code is kept for reference only — it is not expected to run again.

**Cost accounting.** Every migrated solution charges cached tokens at the full
input rate in its `usd_cost`, and reports what was actually paid separately as
`usd_cost_billed`. This task reuses one document across all 20 cases, so
crediting the cache would rank an artefact of the task shape rather than real
efficiency. Note `tp`'s own `cost.by_model` is *not* the graded figure — the
grader sums `metrics.usd_cost`, which comes from these tables.

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
