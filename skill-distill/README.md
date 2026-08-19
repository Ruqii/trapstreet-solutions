# skill-distill

**A strong model writes the skill once. A cheap, fast model runs it forever.**

## What this is

Most "AI speed" advice reduces to "use a smaller model." That trades quality for
speed on every single call. This repo tests a different split: pay a strong
model's cost and latency **exactly once**, to have it write a general-purpose
skill (a system prompt / checklist) for a task class. From then on, every
actual call goes to a small, fast, cheap model running that skill — no strong
model in the loop at all.

```
one-time:  strong model  --writes-->  skill.txt
every call:  skill.txt + input  -->  cheap model  -->  answer
```

If the skill genuinely transfers the strong model's judgment, you get
close-to-strong-model quality at small-model latency and cost on every call
after the first. If it doesn't transfer, you find that out honestly too --
which is exactly what happened in the benchmark below.

This is not a trapstreet-specific trick, and it isn't tied to Claude models
specifically either -- it's a general pattern for any task where the same kind
of judgment gets applied over and over: any "author once, execute many"
split between an expensive reasoner and a cheap executor. trapstreet.run is
used here only as a way to get an apples-to-apples, third-party-scored number
instead of a self-reported claim.

## What's in this directory

| File | Role |
|---|---|
| `craft_skill.py` | One-time authoring step. Calls a strong model (Opus 4.8) once to write `skill.txt`. Never runs during scoring. |
| `skill.txt` | The generated artifact -- a static system prompt, checked in like compiled output. |
| `solution.py` | Runtime path. Every scored call: load `skill.txt`, call the cheap model (Haiku 4.5), done. No strong-model call ever happens here. |
| `claude-haiku-4-5/trap.yaml` | Wires this into a [trapstreet.run](https://trapstreet.run) task for third-party scoring. |

## Benchmark: does the skill actually transfer capability?

Wired against trapstreet's `python-bugfix-diff` task -- 10 real historical bugs
pulled from real open-source commits, find the bug, deterministic scoring.
The board already had a no-skill Opus baseline and three different
human-written "code review skill" system prompts competing on the same task,
which makes it a clean place to ask: **can a model-authored skill substitute
for the model itself?**

> **These numbers are superseded — do not cite them.** They were measured against
> task commit `d11b109` (2026-07-12). The task has since moved to `93d6ef2`
> (2026-07-30), which every other arm on the board now pins: 8 commits that replaced
> three non-discriminating cases with real bugs, rewrote three questions, changed
> `judge.py`, and widened keyword groups seven times to fix real false negatives.
> On the live board today the comparands score **0.8** (awesome), **0.8**
> (jeffallan/opus-4-8), **0.7** (alireza) and **0.6** (no-skill opus-4-8) — not the
> 0.6/0.4/0.3 below. This arm has not been re-run at `93d6ef2`, so its 0.1 is not
> comparable to anything and is probably understated.

| Approach | Score (at `d11b109`, superseded) | Cost (10 cases) | Latency (10 cases) |
|---|---|---|---|
| Opus 4.8, no skill | 0.3 | $0.218 | 46s |
| Opus 4.8 + human-written skill (best of 3) | **0.6** | $0.096 | 60s |
| Opus 4.8 + human-written skill (worst of 3) | 0.4 | $0.090 | 60s |
| **Opus-authored skill + Haiku 4.5 executor (this repo)** | **0.1** | $0.037 + $0.041 one-time | 51s |

The reading at the time was: **no, not here.** A checklist -- however well-written --
does not substitute for the reasoning depth this task actually needs. Haiku
running the Opus-written checklist scored *below* the no-skill Opus baseline.
**That conclusion is now provisional**: the judge that produced it had known false
negatives on seven of the ten cases, and this arm has not been re-run since they
were fixed. The one-time authoring cost ($0.041,
measured via token counting against Opus 4.8's published rate, not part of
the metered run) doesn't rescue it either.

This matters as a negative result, not just a null one: it says the
bottleneck on this task is raw model capability, not prompt quality --
so "have a smart model write better instructions" is not a free lunch for
speed on every task. The same split might still pay off on tasks where the
answer space is narrower and the job is closer to structured application of
known rules than open-ended judgment (e.g. calculation-heavy or
classification-heavy tasks) -- untested here, worth trying next.

## Reproducing

```bash
uv run craft_skill.py > skill.txt   # one-time; skip if skill.txt already exists
cd claude-haiku-4-5 && tp run        # scores against task commit 93d6ef2
```

Both scripts declare their dependencies inline (PEP 723), so `uv run` needs no
virtualenv setup.
