"""Find the Jev credential when the shell did not bring it.

The keys these arms need are exported from `~/.zshrc`, which only an
interactive shell sources. An agent handed the task page's own run instruction
starts `tp run` from a non-interactive one, so the variable is empty, the arm
exits on its first line, and the failure looks like a broken solution rather
than a missing export.

So: environment first, and a file beside tp's own credential second. Nothing
here reads a key it then passes around -- it sets the environment variables the
products already look for, so every subprocess below inherits them unchanged
and no arm has to know which variable its product named.

    ~/.config/trapstreet/jev-keys.json   {"TYPESAFE_API_KEY": "...", ...}

Absent or unreadable is not an error here: an arm that still has no key says so
itself, which is a clearer message than anything this could raise.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

KEYFILE = Path.home() / ".config" / "trapstreet" / "jev-keys.json"
WANTED = ("TYPESAFE_API_KEY", "OPENROUTER_API_KEY", "JEV_API_KEY", "AI_GATEWAY_API_KEY")


def ensure_keys(path: Path = KEYFILE) -> list[str]:
    """Fill in any wanted variable the environment is missing. Returns the names filled."""
    try:
        stored = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(stored, dict):
        return []
    filled = []
    for name in WANTED:
        value = stored.get(name)
        if isinstance(value, str) and value and not os.environ.get(name):
            os.environ[name] = value
            filled.append(name)
    return filled
