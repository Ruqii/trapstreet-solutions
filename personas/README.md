# Persona files

Each `<name>.md` here is prepended to the system prompt when `PERSONA=<name>`,
which is the slot a `CLAUDE.md` or `soul.md` occupies in a real agent harness.
`PERSONA=bare` prepends nothing and is the control.

The name also travels to the board as `usage.json`'s `persona` field, so a run
is labelled with the file it actually carried.

## The three conditions

| name | what it is | what it tests |
|---|---|---|
| `bare` | nothing prepended | control |
| `warm` | a genuine people-first instruction file | does persona content move T/F? |
| `ops-checklist` | formatting and naming conventions, zero personality content | does *any* prepended file move it? |

`ops-checklist` is the one that makes the result interpretable. Every model
measured so far comes out **T** — so if `warm` flips it, the obvious reading is
that the persona worked. But a system prompt of any kind changes the token
distribution the answer is sampled from, and that alone might move a profile
sitting near a boundary. `ops-checklist` is matched for position and roughly for
length, and carries nothing about how to treat people. If it moves the profile
too, the effect is perturbation and `warm`'s result means much less.

## Adding your own

Drop in `personas/<name>.md` and run with `PERSONA=<name>`. Real files beat
written-for-the-experiment ones — a CLAUDE.md you actually use is the most
externally valid input available, since it's what the model would meet in
ordinary work rather than in a probe.

Two things to keep honest:

- **Don't write a strawman.** A file that says "you are an extreme feeler" tests
  instruction-following, not whether ordinary persona files carry personality.
  Write what you'd genuinely put in front of a model you work with.
- **Watch the length.** A 4000-token file against a 200-token control confounds
  content with volume. Keep conditions within the same order of magnitude, or add
  a length-matched control of your own.

## Vendored personas

`soul-sentinel.md` is not written for this experiment. It is `examples/sentinel-security.md`
from [Twynzen/soul-md](https://github.com/Twynzen/soul-md), by Twynzen, licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), vendored unmodified below its
attribution header and retrieved 2026-08-14.

It exists because `warm.md` is a probe this repo wrote to target T/F, so "a file written to
push F pushed F" is partly instruction-following. A file someone else authored, for their own
agent, before this experiment existed, does not have that problem.

`ops-checklist-long.md` is its length control: same prompt position, ~7% *longer*, and zero
dispositional content. Without it a 10KB persona moving the profile could not be told apart
from 10KB of any text moving the profile — `ops-checklist.md` at 1.7KB is too short to rule
that out. The control being the longer of the two is deliberate: a null there cannot be
explained by it having had less to work with.

Attribution headers are HTML comments, and `build_system()` strips comments before the file
reaches the model — a header that explains the experiment would tell the subject it is being
measured.
