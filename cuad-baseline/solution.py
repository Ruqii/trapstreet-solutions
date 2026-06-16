"""Baseline CUAD solution — always answers "NO CLAUSE FOUND".

A zero-cost wiring check: no model call, no inputs read. On the default 32-case
slice it should score ~0.375 — passing all 12 ABSENT cases
(precision_absent = 1.0) and failing all 20 PRESENT cases (recall_present = 0.0).
Seeing exactly that split confirms the harness feeds cases and the judge's two
matchers (span_f1 / no_clause) are wired correctly before you spend on a model.
"""

print("NO CLAUSE FOUND")
