"""Pick the page element whose rendered text overlaps the goal most.

No model, no API call, no cost. This is the floor a real solution has to beat:
it reads the page and does the dumbest possible thing with language. On the
46-case set it scores 0.022.

It exists to exercise the runner, the judge and the grader end to end for free,
and to give the board a row that says what "no understanding" looks like.
"""
from __future__ import annotations

import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path

ATTRS = ("aria_label", "title", "alt", "value", "placeholder", "type")


class Elements(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list = []
        self.found: dict[str, tuple] = {}

    def handle_starttag(self, tag, attrs):
        self.stack.append((tag, dict(attrs), []))

    def handle_endtag(self, tag):
        while self.stack:
            t, a, buf = self.stack.pop()
            bid = a.get("backend_node_id")
            if bid and bid not in self.found:
                self.found[bid] = (t, a, " ".join(buf).strip())
            if self.stack:
                self.stack[-1][2].extend(buf)
            if t == tag:
                break

    def handle_data(self, data):
        data = data.strip()
        if data and self.stack:
            self.stack[-1][2].append(data)


def describe(tag: str, attrs: dict, text: str) -> str:
    parts = [f"<{tag}>"] + [f'{k}="{attrs[k][:60]}"' for k in ATTRS if attrs.get(k)]
    if text:
        parts.append(text[:100])
    return " ".join(parts)


def words(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def main() -> None:
    m = json.loads(os.environ["TRAP_MANIFEST"])
    inputs = Path(m["inputs_dir"])
    step = json.loads((inputs / "step.json").read_text())
    parser = Elements()
    parser.feed((inputs / "page.html").read_text())
    while parser.stack:
        t, a, buf = parser.stack.pop()
        bid = a.get("backend_node_id")
        if bid and bid not in parser.found:
            parser.found[bid] = (t, a, " ".join(buf).strip())

    target = words(step["goal"])
    best, pick = -1.0, None
    for bid, el in parser.found.items():
        w = words(describe(*el))
        if not w:
            continue
        score = len(w & target) / len(w | target)
        if score > best:
            best, pick = score, bid

    print(f"Scanned {len(parser.found)} elements for overlap with the goal.")
    print(f"ELEMENT: {pick or 0}")
    print("OP: CLICK")
    print("VALUE:")


if __name__ == "__main__":
    main()
