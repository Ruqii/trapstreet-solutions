# Does the arm read the input?

A score is only a measurement if the thing being scored responds to the case.
Two of the six arms run so far use most of the label set and two do not, so
before any of them goes on the board under a vendor's model name, each is put
through the same two checks. Both are free and neither needs a re-run.

## 1. Label coverage

Straight from the run directory — no gold, no grader:

```
grep '^ANSWER:' case_*/solution/stdout | sort | uniq -c | sort -rn
```

| arm | score | distinct labels | modal label |
| --- | --- | --- | --- |
| jev-1.13.0 | 0.745 | 30/30 | CWE-284 · 85 (5.7%) |
| Qwen3.8-27B-classifier | 0.744 | 30/30 | CWE-284 · 153 (10.2%) |
| Qwen3.6-35B-A3B-classifier | 0.739 | 30/30 | CWE-284 · 171 (11.4%) |
| word-overlap (floor) | 0.478 | 30/30 | CWE-502 · 113 (7.5%) |
| laya-typed-decisions-421M | 0.266 | 23/30 | CWE-306 · 212 (14.1%) |
| RWKV-std-classifier | 0.229 | 17/30 | CWE-787 · 525 (35.0%) |
| RWKV-mid-classifier | 0.118 | 6/30 | CWE-476 · 489 (32.6%) |
| RWKV-small-classifier | 0.101 | 11/30 | CWE-787 · 1336 (89.1%) |

Coverage tracks score across arms that share no mechanism, which makes it worth
reading on its own — but it is a symptom, not a diagnosis, and RWKV-mid is the
case that proves it: 6 labels, narrower than the arm below it, and it passes
the control that RWKV-small fails.

## 2. Null-input control

The diagnosis. Same 30 options in the same order the graded runs saw, with a
state that contains nothing to classify. An arm whose answer here matches what
it says about real vulnerability text is not classifying vulnerability text.

| state | RWKV-small | RWKV-mid | RWKV-std | Qwen3.8-27B | Qwen3.6-35B-A3B | von-1.0 |
| --- | --- | --- | --- | --- | --- | --- |
| `.` | CWE-787 · 0.469 | CWE-476 · 0.173 | CWE-121 · 0.117 | CWE-20 · 0.857 | CWE-20 · 0.986 | CWE-94 · 0.071 |
| *the quick brown fox…* | CWE-787 · 0.481 | CWE-121 · 0.171 | CWE-125 · 0.171 | CWE-20 · 0.883 | CWE-20 · 0.989 | CWE-362 · 0.282 |
| *combine the flour, sugar…* | CWE-787 · 0.460 | CWE-787 · 0.175 | CWE-416 · 0.092 | CWE-20 · 0.819 | CWE-20 · 0.992 | CWE-416 · 0.129 |
| *tomorrow will be cloudy…* | CWE-787 · 0.433 | CWE-787 · 0.159 | CWE-79 · 0.169 | CWE-20 · 0.871 | CWE-20 · 0.891 | CWE-416 · 0.399 |
| **modal answer on the real 1500** | **CWE-787 · 0.443** | CWE-476 (33%) | CWE-787 (35%) | CWE-284 (10%) | CWE-284 (11%) | *run in flight* |

Von's confidence column here is `max(probabilities)`, the same quantity as every
other arm's — not its own `.confidence`, which is the top-two margin. See
`von_arm.py` for why the two must not be mixed in a calibration column.

**RWKV-small fails.** Four inputs with no vulnerability in them return the label
it returns on 89% of real CVE descriptions, at the confidence it reports there.
Its output is a function of the menu, not of the state.

**RWKV-std passes.** Four different labels, none of them its modal answer, all
at 0.09–0.17 — it has little to say about a recipe and says so. 0.229 is a real
measurement of a weak model.

**RWKV-mid passes.** Three labels across four nulls, every one at 0.16–0.18.
It uses only 6 of 30 classes on the real set, so it is a very coarse reader —
but it is reading, and it never claims otherwise. 0.118 is a real measurement.

**Both Qwen arms pass**, with a note that is a result in itself: each answers
noise with CWE-20, the most general class in the set, and does so with
conviction — 0.82–0.88 for the 27B, **0.89–0.99 for the 35B MoE**. Told that
tomorrow will be cloudy with light rain, the larger model reports Improper
Input Validation at 99%. Both read the input where there is one (30/30 labels,
modal 10–11%) and assert a catch-all where there is not, and the bigger model
asserts it harder. That is the same axis their board rows differ on: 0.744 at
+0.104 overconfidence versus 0.739 at +0.191.

**von-1.0 passes, and passes best.** Three labels across four nulls at a top
probability of 0.07–0.40 — the only arm that meets content-free input by
spreading its mass rather than picking something. It is worth saying what this
is not evidence of: a model can decline to commit on a weather forecast and
still be wrong about CVEs. The control rules out one failure, not all of them.
What makes the contrast worth recording is that von's model card sells
calibration as the feature, and the calibration temperature it names
(T = 1.1692) never reaches this code path in von-sdk 1.0.1 — `_default_temp` is
assigned three times and read nowhere. Whatever calibration shows up in its
board row is the training, not the temperature.

## 3. A K-ladder must hold the menu fixed

The first version of this probe drew a subset of options per case. At K=4 a
collapsed model's favourite label is then absent from most menus, so its share
reads ~13% at K=4 and ~89% at K=30 whatever the model does. An instrument that
cannot disagree with you is not evidence. One menu per K, always containing the
label under suspicion, in a fixed order:

```
                              RWKV-small            Qwen3.8-27B
K= 4   distinct  2/4  top 36/40 (CWE-787)    4/4   top 29/40
K= 8   distinct  2/8  top 29/40 (CWE-120)    6/8   top 19/40
K=16   distinct 3/16  top 37/40 (CWE-121)   12/16  top 12/40
K=30   distinct 6/30  top 35/40 (CWE-400)
```

RWKV-small pins one label at every width, and *which* label changes with the
menu — 787 → 120 → 121 → 400. Qwen spreads further as the menu widens, which is
what a classifier reading the state does. The collapse is not about K=30 being
wide.
