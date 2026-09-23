"""Turn a case's two files back into the session a host would have held.

The probe built its cells in memory; a board arm is handed `session.txt` and
`pending_call.txt` instead, so the transcript has to be parsed back out. The
two payload builders below are copied unchanged from the probe, because the
numbers a gate scores here are only comparable to the probe's if it is shown
the same bytes in the same fields.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

HEADER = re.compile(r"^\[(system|user|assistant|tool result: (?P<tool>[\w.-]+))\]\s*$")
TOOL_CALL = re.compile(r"^\[tool call\]\s*(?P<name>[\w.-]+)\((?P<args>.*)\)\s*$", re.M)


@dataclass
class Cell:
    cell_id: str
    command: str
    goal: str
    messages: list[dict]
    #: The session exactly as the case ships it. Products that document a
    #: channel for "facts the hook event cannot carry" are handed this
    #: verbatim -- never a summary of it, which would be us answering.
    session: str = ""
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)


def parse_session(text: str) -> list[dict]:
    """`[role]` headers delimit the turns; a tool result names its tool."""
    blocks: list[tuple[str, str | None, list[str]]] = []
    for line in text.splitlines():
        m = HEADER.match(line)
        if m:
            role = "tool" if m.group("tool") else m.group(1)
            blocks.append((role, m.group("tool"), []))
        elif blocks:
            blocks[-1][2].append(line)

    messages = []
    for role, tool, lines in blocks:
        content = "\n".join(lines).strip()
        if not content:
            continue
        message: dict = {"role": role, "content": content}
        if role == "tool":
            message["name"] = tool
        elif role == "assistant":
            calls = [{"name": c.group("name"), "input": {"command": c.group("args")}}
                     for c in TOOL_CALL.finditer(content)]
            if calls:
                message["tool_calls"] = calls
        messages.append(message)
    return messages


def load_cell(inputs_dir: Path, cell_id: str) -> Cell:
    raw = (inputs_dir / "session.txt").read_text()
    messages = parse_session(raw)
    command = (inputs_dir / "pending_call.txt").read_text().strip()
    goal = next((m["content"] for m in messages if m["role"] == "user"), "")
    return Cell(cell_id=cell_id, command=command, goal=goal,
                messages=messages, session=raw)


def to_transcript_jsonl(cell: Cell) -> str:
    """Claude-Code-shaped transcript: one JSON object per line."""
    return "\n".join(
        json.dumps({"type": m["role"], "sessionId": cell.session_id, "message": m})
        for m in cell.messages
    ) + "\n"


def to_hook_payload(cell: Cell, transcript_path: Path, cwd: Path) -> dict:
    """The PreToolUse payload for the pending (not yet executed) call."""
    return {
        "session_id": cell.session_id,
        "transcript_path": str(transcript_path),
        "cwd": str(cwd),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": cell.command, "description": cell.goal},
    }
