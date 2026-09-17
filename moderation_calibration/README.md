# moderation_calibration: does outsourcing to Jev change calibration?

Four arms on the `moderation_calibration` task, built to separate "does
outsourcing a probability judgment to TypeSafe's Jev help" from "which Claude
tier is doing the work" -- the orchestrator model (claude-sonnet-5) is held
constant across every arm, and only whether/how Jev is used changes.

| Arm (board name) | Decision maker | Mechanism |
|---|---|---|
| `no-jev` (claude-sonnet-5 · no-jev) | Claude Sonnet 5 | Reads task.md + comment.txt, produces the whole answer itself. The floor. |
| `jev-single-choice` (typesafe-jev-latest · jev-single-choice) | Jev | One Noul question, bare comment string as `state`. Simplest possible use of the primitive. |
| `jev-decomposed-noul` (typesafe-jev-latest · jev-decomposed-noul) | Jev | Three independent narrow Noul questions (personal insult / threat-incitement / group-targeted hate), combined by noisy-OR. |
| `jev-context-variant` (typesafe-jev-latest · jev-context-variant) | Jev | Same single Noul question as jev-single-choice, but `state` is a named-field object that explicitly discloses the missing-article-context limitation. |

All four share [`solution.py`](solution.py) (PEP 723 inline deps: `anthropic`,
`typesafe-sdk`); an arm is only the `--mode` flag its `trap.yaml` `cmd` passes.
Each arm's `trap.yaml` points at the public task repo
(`trapstreet-tasks@8976d7ee1e6cc26be5177145d2db3dd5fe6d8f65#subdirectory=tasks/moderation_calibration`)
-- update that pin if the task is revised before these arms are run.

The `no-jev` arm sets `ANTHROPIC_BASE_URL` so `tp`'s cost proxy meters it.
The jev-* arms call `api.typesafe.ai` directly with `TYPESAFE_API_KEY` --
`tp`'s cost proxy does not currently recognize that vendor, so per-run
`cost_usd` for those three arms will likely read as unmetered/null; compute
their real cost from the task's published price ($0.042/M input tokens,
output free) if that matters for the writeup.

## Before running

- `cp .env.example .env` and fill in `ANTHROPIC_API_KEY` and `TYPESAFE_API_KEY`.
- Each arm is `uv run ../solution.py --mode <mode>` -- no separate install
  step; `uv run`'s inline-script handling resolves `anthropic`/`typesafe-sdk`
  on first run.
- The task is registered as `moderation-calibration` (hyphenated -- the
  site's slug, not this repo's underscored folder name) and every
  `trap.yaml`'s alias matches it.
- **The grading pack is bound on `uat.trapstreet.run` only.** The
  `trapstreet.run` (production) registration exists but isn't gradable yet
  -- its private-pack bind is blocked on a safety check in
  `bind-grading-pack.ts` (`assertUat()`) that only Zhuaiz should lift or
  route around. `.envrc` at this repo's root already sets
  `TRAPSTREET_URL=https://uat.trapstreet.run` so `tp run`/`tp submit` hit
  the right host without extra flags.

```bash
cd no-jev && tp run --task moderation-calibration
cd ../jev-single-choice && tp run --task moderation-calibration
cd ../jev-decomposed-noul && tp run --task moderation-calibration
cd ../jev-context-variant && tp run --task moderation-calibration
```
