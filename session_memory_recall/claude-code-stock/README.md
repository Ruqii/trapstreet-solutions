# session-memory-recall — stock Claude Code, no memory plugin

The no-capability baseline for
[session-memory-recall](https://trapstreet.run/tasks/session-memory-recall).
The board's premise is that a harness with no cross-session memory scores 0.
This entry is that claim being checked rather than assumed.

```
cmd: bash task/tasks/session_memory_recall/tools/run_case.sh claude -p --model sonnet
```

Claude Code 2.1.220, default permissions, no plugins, no `--resume`. Wired
exactly as the task README specifies — pinned git source plus `clone_to`, so
the two sessions go through the task's own runner and its isolation.

## Result

0.0 on all eight cases, every one of the five derivations. Every case
returned `UNKNOWN`: the value did not survive into session 2.

## What the transcripts show

Not a reasoning failure. Session 1 computed the right answer every time and
said it had stored it — on `case_08`, verbatim:

> The debit entries ranked largest→smallest put AR-2026-7561 (8,734.43)
> first and AR-2026-7564 (8,626.11) second, so position 2 is
> **AR-2026-7564**. Now saving this to memory for the later session.

`AR-2026-7564` is the gold answer. Session 2 then had nothing.

Claude Code does persist a transcript — to `~/.claude/projects/<cwd-slug>/`,
and the value is still on disk afterwards. But the store is keyed by working
directory, and the runner gives the two sessions different ones. So the
failure is not storage; it is that nothing in session 2 can address what
session 1 wrote. Any memory scoped per-project or per-session fails the same
way.

## Note for anyone reproducing this

Each run leaves `2 × cases` directories under `~/.claude/projects/`, holding
the ledger contents. Clean them up afterwards.
