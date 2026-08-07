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
