# Reading the board

Eight published rows over the same 1500 cases. Two things the score column
alone does not say.

## The top three are a statistical tie

Every arm ran the same cases, so the comparison to make is per case, not
between two independent proportions. McNemar over the discordant pairs, paired
against the top row:

| arm | Δ vs jev | right-wrong / wrong-right | p |
| --- | --- | --- | --- |
| Qwen3.8-27B | +0.13 pts | 56 / 54 | **0.85** |
| Qwen3.6-35B-A3B | +0.60 pts | 67 / 58 | **0.42** |
| von-1.0 | +22.33 pts | 387 / 52 | <1e-4 |
| word-overlap | +26.73 pts | 446 / 45 | <1e-4 |
| laya 421M | +47.93 pts | 746 / 27 | <1e-4 |
| RWKV-std | +51.60 pts | 798 / 24 | <1e-4 |
| RWKV-mid | +62.73 pts | 968 / 27 | <1e-4 |

0.745 against 0.744 is not a ranking. Jev and Qwen3.8-27B disagree on 110 of
1500 cases and split those 56/54 — they are not merely tied in total, they are
making close to the same decisions. Everything below von separates at p < 1e-4,
so the board is doing its job; it just should not be read to two decimal
places at the top.

This is the benchmark's finding, stated properly: three arms are
indistinguishable on accuracy while their overconfidence spans +0.062 to
+0.191, a factor of three. The calibration column is where they separate, and
it is the only column where they do.

## A fifth of the set defeats everything

Over the three arms that tie:

```
all three right   1024   68.3%
they disagree      175   11.7%
all three wrong    301   20.1%
```

Picking the best of the three per case — an oracle no solution could be — tops
out at **0.7993**. So roughly 20% of this material is where the board stops
discriminating among strong arms, and the headroom above 0.745 is about five
points, not twenty-five.

Those 301 are not uniformly impossible: von gets 33 of them and plain word
overlap gets 31. But nobody has read them, and the three explanations have
different consequences:

- **genuinely ambiguous** — the description supports two CWEs and NVD's analyst
  picked one. Then 0.80 is the material's ceiling and the README has to say so.
- **mislabelled** — then the case set needs cleaning and every score moves.
- **hard but determinate** — then there is real headroom and the board stays
  alive as models improve.

Reading a sample of the 301 is the cheapest experiment left and the one that
decides whether this task has a future as models get better.

## What the board does not show

- **Which rows ran offline.** The descriptions are NVD's own text, published
  verbatim; one search of the exact string returns the CVE and its CWE. Every
  arm so far is offline by construction — local models, or an API that only
  reads logits — so it does not bite yet. The first agent row is where it
  starts to, and nothing on the board marks the difference.
- **Uncertainty.** Point estimates only.
- **Cost.** Empty for seven of eight rows; only the jev arm self-reports.
