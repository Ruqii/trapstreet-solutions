"""Deterministic Python baseline for the cross_timezone scheduler task.

No LLM. Pure regex + zoneinfo math. Cost: $0. Latency: ~10ms.

The whole point: this task's "AI difficulty" is really NL parsing + TZ math,
which can both be done deterministically given a well-structured brief. If
this solution scores 100% while frontier LLMs miss DST/half-hour traps, that's
the trapstreet headline: "don't pay $$ for an LLM to do `zoneinfo` work."
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


# Match attendee lines of the form (be liberal about dash characters):
#   - Alice — San Francisco (America/Los_Angeles) — available 06:00–08:00 local
ATTENDEE_RE = re.compile(
    r"^[-*•]\s+(?P<name>\w+)\s*[—–\-]\s+.+?"
    r"\((?P<tz>[A-Za-z]+/[A-Za-z_]+)\)\s*[—–\-]\s+"
    r"available\s+(?P<start>\d{1,2}:\d{2})\s*[–\-—]\s*(?P<end>\d{1,2}:\d{2})\s+local",
    re.MULTILINE,
)
TODAY_RE = re.compile(r"Today is (\d{4}-\d{2}-\d{2})")
EXPLICIT_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
DURATION_RE = re.compile(r"(\d+)[-\s]?(?:minute|min|m)\b", re.IGNORECASE)
UTC = ZoneInfo("UTC")


def parse_brief(text: str) -> tuple[date, int, list[dict]]:
    """Extract meeting_date, duration_min, and attendee list from a brief."""
    m_today = TODAY_RE.search(text)
    today = date.fromisoformat(m_today.group(1)) if m_today else date.today()

    # Prefer the first explicit date AFTER "today" mention (the meeting date) — fall back to tomorrow.
    meeting_date = today + timedelta(days=1)
    if m_today:
        after_today = text[m_today.end():]
        m_date = EXPLICIT_DATE_RE.search(after_today)
        if m_date:
            meeting_date = date.fromisoformat(m_date.group(1))

    m_dur = DURATION_RE.search(text)
    duration_min = int(m_dur.group(1)) if m_dur else 60

    attendees = [
        {"name": m.group("name"), "tz": m.group("tz"),
         "start": m.group("start"), "end": m.group("end")}
        for m in ATTENDEE_RE.finditer(text)
    ]
    return meeting_date, duration_min, attendees


def local_dt(d: date, t: str, tz: ZoneInfo) -> datetime:
    h, mi = (int(x) for x in t.split(":"))
    return datetime(d.year, d.month, d.day, h, mi, tzinfo=tz)


def candidate_windows(att: dict, meeting_date: date) -> list[tuple[datetime, datetime]]:
    """Return (utc_start, utc_end) for the attendee's window placed on each of
    meeting_date - 1, meeting_date, meeting_date + 1. Handles day-shift cases
    (e.g. Sam in Sydney whose 'morning' is the next local day)."""
    tz = ZoneInfo(att["tz"])
    out: list[tuple[datetime, datetime]] = []
    for offset in (-1, 0, 1):
        d = meeting_date + timedelta(days=offset)
        ls = local_dt(d, att["start"], tz)
        le = local_dt(d, att["end"], tz)
        out.append((ls.astimezone(UTC), le.astimezone(UTC)))
    return out


def find_meeting_start(meeting_date: date, duration_min: int, attendees: list[dict]) -> datetime | None:
    """Brute-force 1-min search across a 72-hour window centered on meeting_date.
    Find the EARLIEST UTC start time T such that for every attendee, [T, T+duration]
    fits entirely inside ONE of their three candidate windows. Prefer t.date() == meeting_date."""
    duration = timedelta(minutes=duration_min)
    windows = {att["name"]: candidate_windows(att, meeting_date) for att in attendees}

    base_utc = datetime(meeting_date.year, meeting_date.month, meeting_date.day, tzinfo=UTC)
    earliest = base_utc - timedelta(hours=24)
    latest = base_utc + timedelta(hours=48)

    def fits(t: datetime) -> bool:
        t_end = t + duration
        return all(
            any(ws <= t and t_end <= we for ws, we in windows[att["name"]])
            for att in attendees
        )

    # First pass: prefer start times whose UTC date equals meeting_date.
    for pass_filter in (lambda t: t.date() == meeting_date, lambda t: True):
        t = earliest
        while t < latest:
            if pass_filter(t) and fits(t):
                return t
            t += timedelta(minutes=1)

    return None


def main() -> int:
    inputs = json.loads(os.environ["INPUTS"])
    outputs = json.loads(os.environ.get("OUTPUTS", "{}"))
    brief = Path(inputs["question.txt"]).read_text()

    meeting_date, duration_min, attendees = parse_brief(brief)

    if not attendees:
        print(json.dumps({"start_utc": None, "duration_min": duration_min,
                          "attendees": [], "reason": "parse failure — no attendees found"}))
        return 0

    start = find_meeting_start(meeting_date, duration_min, attendees)
    if start is None:
        print(json.dumps({"start_utc": None, "duration_min": duration_min,
                          "attendees": [], "reason": "no overlap exists"}))
        # Still write a zero-cost usage record so the grader picks it up
        if "usage.json" in outputs:
            Path(outputs["usage.json"]).write_text(json.dumps({
                "model": "deterministic-python", "input_tokens": 0, "output_tokens": 0,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                "usd_cost": 0.0,
            }))
        return 0

    result_atts = []
    for att in attendees:
        tz = ZoneInfo(att["tz"])
        local = start.astimezone(tz)
        result_atts.append({
            "name": att["name"],
            "tz": att["tz"],
            "local_start": local.strftime("%Y-%m-%d %H:%M"),
        })

    print(json.dumps({
        "start_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_min": duration_min,
        "attendees": result_atts,
    }))

    if "usage.json" in outputs:
        Path(outputs["usage.json"]).write_text(json.dumps({
            "model": "deterministic-python",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "usd_cost": 0.0,
        }))

    return 0


if __name__ == "__main__":
    sys.exit(main())
