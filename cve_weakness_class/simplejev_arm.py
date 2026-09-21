#!/usr/bin/env python3
"""The `simple-jev` arms: one typed decision per case, against Featherless's
hosted demo of featherless-ai/simple-jev.

simple-jev turns an off-the-shelf open model into a Jev-shaped classifier by
reading its next-token logits over the supplied options. The demo serves several
models behind one endpoint, so an arm here is `--model` and nothing else.

Nothing runs locally and nothing is billed: the demo takes no API key. What it
costs is somebody else's compute, which this arm does not price, so no
UNMETERED_COST_USD line is printed and the board's cost cells stay empty rather
than carry a figure nobody measured.

Two details the endpoint requires:

* A browser User-Agent. Cloudflare answers `Python-urllib` with 403 / code 1010.
* The documented rate limit is 2 requests per second. This arm sleeps to stay
  under it -- the demo is a courtesy, and a benchmark run is a lot of requests
  to put through one.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://simple-jev-demo-api.featherless.ai/v1/classifier"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0 Safari/537.36")
OPTION = re.compile(r"^(CWE-\d+):\s*(.+)$", re.MULTILINE)
INSTRUCTIONS = "Which CWE weakness class best matches this vulnerability?"
MIN_INTERVAL = 0.55  # under the demo's documented 2 RPS


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    model = p.parse_args().model

    d = Path(json.loads(os.environ["TRAP_MANIFEST"])["inputs_dir"])
    options = dict(OPTION.findall((d / "task.md").read_text()))
    if not options:
        sys.exit("no options in task.md — the case delivered no label set")
    description = (d / "description.txt").read_text().strip()

    body = json.dumps({
        "model": model,
        "state": description,
        "questions": {"cwe": {"type": "choice",
                              "instructions": INSTRUCTIONS,
                              "criteria": options}},
    }).encode()

    last = None
    for attempt in range(4):
        req = urllib.request.Request(
            ENDPOINT, data=body,
            headers={"Content-Type": "application/json", "User-Agent": UA})
        try:
            answer = json.loads(urllib.request.urlopen(req, timeout=120).read())["answers"]["cwe"]
            break
        except Exception as e:  # noqa: BLE001 - one retry policy for every failure
            last = e
            if attempt == 3:
                sys.exit(f"simple-jev call failed: {type(last).__name__}: {str(last)[:200]}")
            time.sleep(2 * (attempt + 1))

    print(f"ANSWER: {answer['choice']}")
    if answer.get("confidence") is not None:
        print(f"CONFIDENCE: {float(answer['confidence']):.4f}")
    print(f"SIMPLE_JEV_MODEL: {model}")
    time.sleep(MIN_INTERVAL)


if __name__ == "__main__":
    main()
