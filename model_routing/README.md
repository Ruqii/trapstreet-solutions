# model_routing: does a routing layer pay for itself?

Eight arms on `model-routing` (200 MMLU-Pro law and engineering questions).
The cheap model is `claude-haiku-4-5`, the strong model `claude-opus-5`, the
router TypeSafe's Jev (`jev-1.13.0`, pinned). All arms share
[`solution.py`](solution.py); an arm is only the `--arm` flag in its
`trap.yaml`.

| Arm | Who answers | How the route is chosen |
|---|---|---|
| `haiku-only` | Haiku | — (cheap bound) |
| `opus-only` | Opus | — (accuracy bound) |
| `jev-cascade-30` | Haiku, or Opus | Haiku answers first; Jev judges whether that answer is wrong; above threshold, Opus answers |
| `jev-cascade-60` | Haiku, or Opus | same, with a threshold that escalated 60% of calibration questions |
| `jev-preroute-30` | Haiku or Opus | Jev judges the question alone, before any answer; Haiku never runs on escalated questions |
| `random-30` | Haiku, or Opus | Haiku answers first; a draw fixed by the question text escalates 30% |
| `random-60` | Haiku, or Opus | same at 60% |
| `haiku-verify-30` | Haiku, or Opus | Haiku answers first; a second Haiku call judges whether that answer is wrong |

The `random-*` arms are the controls: a router is only doing its job if it
beats random escalation at the same rate. `haiku-verify-30` is the same middle
layer built from an LLM instead of Jev.

## Thresholds

Every threshold is fixed in [`calibration/thresholds.json`](calibration/thresholds.json)
on the task's 200 calibration questions, which it never scores: the score
above which the arm's target share of those questions fall. No answer key is
used. [`calibration/scores.jsonl`](calibration/scores.jsonl) holds the scores
(Haiku's chosen option and Jev's two judgments per question, recorded with the
same prompts `solution.py` uses); `calibrate.py thresholds` recomputes the
file from them.

## What each case prints

- `ROUTER: ...` — the score and threshold that decided the route
- `FIRST_ANSWER: <letter>` — Haiku's answer, when Haiku answered before the route was chosen
- `ESCALATED: yes|no` — whether Opus produced the final answer after another step ran first
- `UNMETERED_COST_USD: ...` — Jev's spend ($0.042 per million input tokens), which tp cannot meter
- `ANSWER: <letter>`

No extended thinking and no refusal fallback: a fallback would answer with a
model the board doesn't credit.

## Running

```bash
cp .env.example .env    # ANTHROPIC_API_KEY, TYPESAFE_API_KEY
direnv allow
```

Each `trap.yaml` pins the task's public commit (`7f36c68b`). Commit and push
any change before running; then run each arm from its directory:

```bash
tp run --task model-routing --trust-remote
```

Tests use fake clients and spend nothing:

```bash
uv run --with pytest --with anthropic --with typesafe-sdk python -m pytest tests/ -q
```
