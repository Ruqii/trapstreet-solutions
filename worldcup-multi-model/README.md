# worldcup-multi-model

A blind, multi-model predictor for the World Cup match tasks
([trapstreet-tasks `worldcup_*`](https://github.com/trapstreet/trapstreet-tasks/tree/main/tasks)).
One `solution.py` serves every match; pick the engine with the `MODEL` env var
(Anthropic SDK for `claude-*`, OpenRouter for everything else).

Assumes `trapstreet-tasks` is cloned as a sibling dir (the `traptask.local` paths
in `trap.yaml` are `../../trapstreet-tasks/tasks/worldcup_*`).

## Run a model on a match

```bash
ANTHROPIC_API_KEY=...  MODEL=claude-opus-4-8     tp run worldcup-pan-cro
ANTHROPIC_API_KEY=...  MODEL=claude-sonnet-4-6   tp run worldcup-pan-cro
OPENROUTER_API_KEY=... MODEL=openai/gpt-5.5      tp run worldcup-pan-cro
OPENROUTER_API_KEY=... MODEL=google/gemini-3-pro tp run worldcup-pan-cro
```

The model's stdout is its prediction, e.g. `{"home":0.18,"draw":0.26,"away":0.56}`.
Before `tp submit`, set `solution:` for that task in `trap.yaml` to the model you
ran — that's the leaderboard identity.

## Running BEFORE the match (no result yet) — this is fine

**Running produces a prediction, which needs only the question — not the result.**
So `tp run` works right now: the model reads the teams + kickoff, outputs its
`{home,draw,away}`, and trap saves it under `.trap/<task>/<timestamp>/<case>/`.
The case will show **ungraded** (the task's `judge.py` returns `score: null`
because the result is still null) — that's expected, not an error. You've captured
the blind prediction.

You just can't get a **score** until the match is played. Full flow per match:

```
1. (now, pre-match)   tp run            -> capture each model's blind prediction (ungraded)
2. (after full time)  in the task dir:
                        ODDS_API_KEY=... python3 snapshot.py   # fill odds (for ROI)
                        ODDS_API_KEY=... python3 grade.py      # fill the real result
3. (now gradeable)    tp run            -> the same blind prompt now SCORES
4.                    tp submit         -> leaderboard
```

Models are closed-book (no tools, training cutoff ~Jan 2026), so running them after
the whistle is still a genuine blind prediction — they can't know a June 2026
result. That makes "grade first, then run+submit" the simplest path to a scored
leaderboard. (If you want the *literal* pre-kickoff prediction to be the one that
counts, keep the step-1 output and score it with the task's `judge.py` after step 2,
instead of re-running.)

## Models

| `MODEL` | Provider | Key |
|---|---|---|
| `claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5` | Anthropic | `ANTHROPIC_API_KEY` |
| `openai/gpt-5.5`, `google/gemini-3-pro`, `x-ai/grok-4.3`, `deepseek/deepseek-v4-pro`, `meta-llama/llama-4-maverick` | OpenRouter | `OPENROUTER_API_KEY` |

Token usage + cost per case are written to `usage.json` and shown on the leaderboard.
