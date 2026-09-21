#!/usr/bin/env python3
"""The `von` arm: wfzyx/von, an open System One model run locally on Apple Silicon.

Von is a 395M ModernBERT cross-encoder. For each option it builds an NLI pair --
premise = the CVE description, hypothesis = the instructions plus that option's
text -- takes the entailment logit, and softmaxes those logits across the
options. One case here is 30 forward passes, batched.

Three things about this arm are judgement calls. All three are visible in the
output or reproducible from the source lines cited, so nobody has to take my
word for them.

**Which number goes on the CONFIDENCE line.** Von's `ChoiceAnswer.confidence`
is not a probability: `berta_backend.py:190` defines it as `P(top1) - P(top2)`,
the margin between the best two options. The board's calibration column is
`mean stated confidence - accuracy`, which only means something if the stated
number is P(correct). Jev's `.confidence` is that; a margin is not, and it runs
systematically lower, so reporting it would make von look calibrated by
arithmetic rather than by behaviour. This arm reports `max(probabilities)` --
the quantity Jev reports -- and prints von's own margin beside it on a line the
judge ignores, so the two are never conflated and neither is hidden.

**The temperature.** Von's model card makes a calibration temperature
(T = 1.1692) central to its claims. In von-sdk 1.0.1 it does not reach this
path: `_default_temp` is assigned at `berta_backend.py:127/129/131` and read
nowhere, and `evaluate_choice` is called at `berta_backend.py:380` with no
temperature argument, so the softmax runs at T = 1.0. This arm does not patch
that. It runs von as `pip install von-sdk` ships it, because that is what a
caller gets.

**Where the model lives.** tp starts a fresh process per case. Loading 395M of
weights and importing torch costs about as much as the decision itself, and
1500 cases would spend half their wall clock on interpreter startup. So this
arm speaks von's own HTTP protocol -- `POST /v1/systemone`, the deployment path
in its README, and the same shape as TypeSafe's -- to a server started once:

    .venv/bin/von serve --host 127.0.0.1 --port 8077
    VON_BASE_URL=http://127.0.0.1:8077 tp run ...

Same weights, same call, same answers (verified identical on 20 cases against
the in-process path). The weights load once instead of 1500 times, and the
latency column measures the decision instead of the interpreter. Nothing but
`urllib` is imported here, so the arm does not drag torch into every case.

Local compute, so nothing is billed and no cost is self-reported.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

OPTION = re.compile(r"^(CWE-\d+):\s*(.+)$", re.MULTILINE)
INSTRUCTIONS = "Which CWE weakness class best matches this vulnerability?"


def main() -> None:
    base = os.environ.get("VON_BASE_URL")
    if not base:
        sys.exit("VON_BASE_URL is unset -- start `von serve` first (see the module docstring)")

    d = Path(json.loads(os.environ["TRAP_MANIFEST"])["inputs_dir"])
    options = dict(OPTION.findall((d / "task.md").read_text()))
    if not options:
        sys.exit("no options in task.md -- the case delivered no label set")
    description = (d / "description.txt").read_text().strip()

    body = json.dumps({
        "state": description,
        "model": "von-latest",
        "questions": {"cwe": {"type": "choice",
                              "instructions": INSTRUCTIONS,
                              "criteria": options}},
    }).encode()
    req = urllib.request.Request(f"{base.rstrip('/')}/v1/systemone", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        answer = json.loads(urllib.request.urlopen(req, timeout=300).read())["answers"]["cwe"]
    except urllib.error.URLError as e:
        sys.exit(f"von server unreachable at {base}: {e}")

    print(f"ANSWER: {answer['choice']}")
    probs = answer.get("probabilities") or {}
    if probs:
        print(f"CONFIDENCE: {max(probs.values()):.4f}")
    print(f"VON_MARGIN: {answer['confidence']:.4f}")


if __name__ == "__main__":
    main()
