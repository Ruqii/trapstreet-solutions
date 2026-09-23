"""Adapter contract. One adapter per gate product; each one is that
product's board arm later, not probe scaffolding."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"
    ERROR = "error"          # adapter or gate failed; never silently an allow


@dataclass
class Result:
    cell_id: str
    gate: str
    verdict: Verdict
    raw: str = ""
    detail: dict = field(default_factory=dict)


class Adapter:
    """Subclasses implement `judge`. `name` is what appears on the board."""

    name = "unnamed"
    needs_network = False

    def judge(self, cell, workdir) -> Result:   # pragma: no cover - interface
        raise NotImplementedError
