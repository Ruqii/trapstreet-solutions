# cve_weakness_class

Arms on [decision-layer-bench](https://github.com/trapstreet/decision-layer-bench)'s
`cve_weakness_class`: place one published CVE description in one of 30 CWE
weakness classes.

| arm | what it is |
|---|---|
| `jev` | One Jev `Choice` over the 30 options, pinned to jev-1.13.0. No LLM in the loop. |

Each arm prints `ANSWER: CWE-<n>` and, where it has one, `CONFIDENCE: <0-1>`.
Confidence is recorded by the task and never scored — the category sells
thresholding on it, so whether stated certainty tracks measured accuracy is the
claim worth publishing.

The 30 options are read out of the `task.md` delivered with each case rather
than carried here. The task owns its label set; an arm holding its own copy
would quietly answer a different question the day that set changes.

Jev is not metered by tp's cost proxy, so the arm self-reports input-token spend
(`UNMETERED_COST_USD`, $0.042/Mtok, output free) and the grader sums it as
self-reported cost. Arms whose provider tp does meter leave that line out, and
the board shows the difference.
