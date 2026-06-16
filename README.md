# trapstreet-solutions

Reference agent implementations for [trapstreet.run](https://trapstreet.run)
benchmarks. Each subdirectory is a self-contained `uv` project that can be run
against a task with the [`tp` CLI](https://github.com/AntiNoise-ai/trap).

Each solution holds the **reasoning layer constant** (Claude) so the variable
is the **PDF / document handling layer**. This makes head-to-head comparison
of OSS vs frontier parsers meaningful.

## Solutions

| Folder | Approach | Setup | First-case latency |
|---|---|---|---|
| [`claude-pdf/`](./claude-pdf/) | Native vision-LLM: PDF → Claude reads pages directly | `anthropic` SDK only | ~10–30s |
| [`docling-claude/`](./docling-claude/) | IBM [Docling](https://github.com/DS4SD/docling) extracts → markdown → Claude reasons over text | Docling + RapidOCR ONNX (~50 MB) | ~60s (then cached) |
| [`marker-claude/`](./marker-claude/) | [Marker](https://github.com/VikParuchuri/marker) extracts → markdown → Claude reasons over text | Marker weights (~2 GB) | 2–5 min on CPU |

All three use Anthropic prompt caching so the same document costs ~10% of its
input price after the first case.

## Layout assumption (important)

These solutions reference task definitions in the **sibling**
[`trapstreet-tasks`](https://github.com/AntiNoise-ai/trapstreet-tasks) repo
via a relative path inside each `trap.yaml`:

```yaml
traptask: ../../trapstreet-tasks/tasks/pdf_reader/tenancy_agreement
```

So **clone both repos side-by-side**:

```bash
mkdir -p ~/projects && cd ~/projects
git clone git@github.com:AntiNoise-ai/trapstreet-tasks.git
git clone git@github.com:Ruqii/trapstreet-solutions.git
```

If you put them somewhere else, edit `traptask:` accordingly (relative or
absolute path both work).

## Run one solution

```bash
cd trapstreet-solutions/claude-pdf
uv sync                                                 # one-time install
export ANTHROPIC_API_KEY=sk-ant-...
uv run tp run                                           # runs all 19 cases
uv run tp run --fail-fast                               # stop on first failure
uv run tp run -t money                                  # tag-filter
```

Each run lands a `report.json` under `.trap/tenancy-agreement/latest/` with
per-case score, latency, and USD cost.

## Submit to the leaderboard

If you have a runner API key from <https://trapstreet.run/settings>:

```bash
export TRAPSTREET_API_KEY=ts_...
uv run tp submit tenancy-agreement
```

The result appears at <https://trapstreet.run/tasks/tenancy-agreement>.

## Cost (per full 19-case sweep)

With prompt caching enabled, on **Claude Opus 4.7** (May 2026 pricing):

| Solution | Cost | Notes |
|---|---|---|
| claude-pdf | ~$2.30 | 1× cache write of ~68k-token PDF + 18× cache reads |
| docling-claude | ~$2.65 | Smaller payload (~12k token markdown) but Opus output dominates |
| marker-claude | n/a — runs but Surya layout model OOMs on Apple Silicon MPS; CPU exceeds trap's per-case timeout |

Switching the `MODEL` env var to `claude-sonnet-4-6` cuts cost ~5× but
requires a higher input-tokens-per-minute rate limit than the default
(30k TPM caps a 68k-token PDF call).

## CUAD — contract clause extraction (separate task family)

A different task from the PDF set above:
[`trapstreet.run/tasks/cuad`](https://trapstreet.run/tasks/cuad) — read a
contract and extract a clause span, or correctly say the clause is absent.

| Folder | Approach | Setup |
|---|---|---|
| [`cuad-baseline/`](./cuad-baseline/) | Always answers `NO CLAUSE FOUND` — a $0 wiring check | none (no API key) |

The baseline is stdlib-only (no model, no deps), so it runs with the global `tp`
directly — no `uv sync` needed:

```bash
cd cuad-baseline
tp run                        # 32 cases; verified ~0.375 (passes 12/12 absent, fails 20/20 present)
tp submit cuad                # post to the leaderboard
```

The ~0.375 split (`precision_absent = 1.0`, `recall_present = 0.0`) confirms the
harness + judge are wired correctly before testing a real model.

> **Note on `traptask`:** the current `tp` (`trapstreet-cli`) expects `traptask`
> as a `TaskSource` object (`{ local: <path> }`), not a bare string. The older
> PDF solutions in this repo still use the string form and will need the same
> update when run against the newer CLI.

## Build your own solution

The interface is small. A solution is anything that:

1. Reads the JSON in `$INPUTS` env var to find the question and PDF
2. Prints the answer to stdout

Minimal example (`solution.py`):

```python
import json, os
inputs = json.loads(os.environ["INPUTS"])
question = open(inputs["question.txt"]).read().strip()
pdf_path = inputs["document.pdf"]
print(my_agent(question, pdf_path))   # ← your agent here
```

Add a `pyproject.toml` (with `trap` as a dep, from
`git+https://github.com/AntiNoise-ai/trap.git@feat/tp-submit`) and a
`trap.yaml` pointing at the task. See any of the three folders for a
working template.
