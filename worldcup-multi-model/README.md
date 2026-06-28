# worldcup-multi-model

> **Before you submit — checklist (avoids "ran it, can't submit"):**
> 1. **The task must be registered on the server first.** Create it at
>    [trapstreet.run/tasks/new](https://trapstreet.run/tasks/new) by pasting the
>    task's GitHub URL (e.g. `…/trapstreet-tasks/tree/main/tasks/worldcup_pan_cro`).
>    Only registered tasks accept `tp submit`; an unregistered one 404s.
> 2. **Don't submit before the match.** A pre-match run is ungraded → submitting
>    posts a 0% entry. `tp submit` only after `grade.py` has filled the result.
> 3. **Engine label must match the model you ran.** Use `./predict.sh <task> <model>`
>    (it syncs `trap.yaml`'s `solution:` to the model) instead of bare `tp run`,
>    or the leaderboard mislabels the engine.
> 4. `tp auth status` shows a valid token; `metadata.repo` is declared (it is);
>    push the solution commit before submit.


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
OPENROUTER_API_KEY=... MODEL=google/gemini-3.1-pro-preview tp run worldcup-pan-cro
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
leaderboard.

## Route B — freeze the pre-kickoff prediction (for social + "predicted live")

`solution.py` caches each prediction to `predictions/<case_id>__<model>.json` on
first run, and **replays** it on later runs. So the prediction that scores after
the match is *exactly* the one made before kickoff — no second model call.

```bash
# 1. BEFORE kickoff — capture each model's blind prediction (it gets cached)
ANTHROPIC_API_KEY=...  MODEL=claude-opus-4-8     tp run worldcup-pan-cro
ANTHROPIC_API_KEY=...  MODEL=claude-sonnet-4-6   tp run worldcup-pan-cro
OPENROUTER_API_KEY=... MODEL=openai/gpt-5.5      tp run worldcup-pan-cro
#    -> predictions/wc26_20260623_PAN_CRO__claude-opus-4-8.json  (frozen)

# 2. Post to social — render the frozen predictions
python3 summary.py PAN_CRO
#    ⚽ wc26_20260623_PAN_CRO — 3 models predict (blind, no odds)
#       claude-opus-4-8   home 18% · draw 26% · away 56%
#       ...

# 3. AFTER full time — fill the result, then re-run (REPLAYS the cached prediction)
cd ../../trapstreet-tasks/tasks/worldcup_pan_cro
ODDS_API_KEY=... python3 snapshot.py && python3 grade.py
cd -
MODEL=claude-opus-4-8 tp run worldcup-pan-cro    # replays cache -> now SCORES
tp submit                                        # set trap.yaml `solution:` first
```

Re-capture a prediction with `REFRESH=1 tp run ...` or by deleting its cache file.
Commit `predictions/` if you want the frozen predictions on public record (the
credibility hook for "predicted before kickoff").

## Models

| `MODEL` | Provider | Key |
|---|---|---|
| `claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5` | Anthropic | `ANTHROPIC_API_KEY` |
| `openai/gpt-5.5`, `google/gemini-3.1-pro-preview`, `x-ai/grok-4.3`, `deepseek/deepseek-v4-pro`, `meta-llama/llama-4-maverick` | OpenRouter | `OPENROUTER_API_KEY` |

Token usage + cost per case are written to `usage.json` and shown on the leaderboard.
