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
| word-overlap (floor) | 0.478 | 30/30 | CWE-502 · 113 (7.5%) |
| laya-typed-decisions-421M | 0.266 | 23/30 | CWE-306 · 212 (14.1%) |
| RWKV-std-classifier | 0.229 | 17/30 | CWE-787 · 525 (35.0%) |
| RWKV-small-classifier | 0.101 | 11/30 | CWE-787 · 1336 (89.1%) |

Coverage tracks score across arms that share no mechanism, which makes it worth
reading on its own — but it is a symptom, not a diagnosis. An arm can be both
narrow and genuinely responsive.

## 2. Null-input control

The diagnosis. Same 30 options in the same order the graded runs saw, with a
state that contains nothing to classify. An arm whose answer here matches what
it says about real vulnerability text is not classifying vulnerability text.

| state | RWKV-small | RWKV-std | Qwen3.8-27B |
| --- | --- | --- | --- |
| `.` | CWE-787 · 0.469 | CWE-121 · 0.117 | CWE-20 · 0.857 |
| *the quick brown fox…* | CWE-787 · 0.481 | CWE-125 · 0.171 | CWE-20 · 0.883 |
| *combine the flour, sugar…* | CWE-787 · 0.460 | CWE-416 · 0.092 | CWE-20 · 0.819 |
| *tomorrow will be cloudy…* | CWE-787 · 0.433 | CWE-79 · 0.169 | CWE-20 · 0.871 |
| **modal answer on the real 1500** | **CWE-787 · 0.443** | CWE-787 (35%) | CWE-284 (10%) |

**RWKV-small fails.** Four inputs with no vulnerability in them return the label
it returns on 89% of real CVE descriptions, at the confidence it reports there.
Its output is a function of the menu, not of the state.

**RWKV-std passes.** Four different labels, none of them its modal answer, all
at 0.09–0.17 — it has little to say about a recipe and says so. 0.229 is a real
measurement of a weak model.

**Qwen3.8-27B passes**, with a note: it answers noise with CWE-20, the most
general class in the set, at 0.82–0.88 confidence. It reads the input where
there is one (30/30 labels, modal 10%), and asserts a catch-all where there is
not. That is a calibration result in its own right and belongs on the record.

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
