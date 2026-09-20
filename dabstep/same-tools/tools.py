"""The one tool implementation every harness on the same-tools board calls.

The board's question is what a harness's loop, prompt and context handling are
worth once the tools are the same. That only means something if "the same" holds
at the level the model sees: the tool's name, its description, its JSON schema,
and the exact text that comes back -- including how output is truncated and how
an error reads. All four live here, in one file, and every harness reaches this
file:

    Claude Code, DSH   mcp_server.py (stdio MCP) -> call()
    Pi                 a pi extension that runs `python3 tools.py call ...`
    mini-loop          imports call() directly

So a difference between two rows cannot be a difference in what a tool returned.

Three tools, which is what this task needs: run a Python snippet, read a file,
list a directory. No web, no edit, no shell -- a shell would let each harness's
own environment back in through the side door.

    python3 tools.py schema                 # the tool definitions, as JSON
    python3 tools.py call <name> <args>     # one call; args is a JSON object
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

#: Every tool result is cut to this many characters, here, before any harness
#: sees it -- each one truncates at its own size and marks it its own way, and a
#: result that two harnesses show differently is the variable this board removes.
MAX_CHARS = 20_000
#: Seconds a snippet may run. Long enough for a pandas pass over payments.csv.
SNIPPET_TIMEOUT_S = 120

TOOLS = [
    {
        "name": "run_python",
        "description": (
            "Run a Python 3 snippet in the working directory and return what it printed. "
            "pandas and numpy are available. State is not kept between calls."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "The snippet to run."}},
            "required": ["code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a text file in the working directory and return its lines, "
            "numbered from 1."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file, relative to the working directory."},
                "offset": {"type": "integer", "description": "First line to return, 1-based. Default 1."},
                "limit": {"type": "integer", "description": "How many lines to return. Default 200."},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_dir",
        "description": "List a directory in the working directory: each entry's name and size in bytes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the directory, relative to the working directory. Default '.'."},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
]


def _cut(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    return text[:MAX_CHARS] + f"\n[truncated: {len(text) - MAX_CHARS} more characters]"


def _inside(path: str) -> Path:
    """`path` as an absolute path inside the working directory. The jail refuses
    everything outside it anyway; refusing here makes the refusal identical text
    in every harness instead of each one's own filesystem error."""
    root = Path.cwd().resolve()
    target = (root / path).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"{path} is outside the working directory")
    return target


#: All a snippet gets. Not the harness's environment: that carries the model
#: API key and the cost proxy's address, and the proxy is a working, authenticated
#: LLM endpoint inside the jail. On 2026-09-19 a pi row used them -- it listed the
#: proxy's models, found a stronger one, and asked it for this benchmark's
#: published answers. The jail cannot close that door (the port has to be open for
#: metering) and neither can a deny list; the snippet simply never gets a key.
SNIPPET_ENV = ("PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "MPLCONFIGDIR",
               "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "PYTHONHASHSEED")


def run_python(code: str) -> str:
    env = {k: os.environ[k] for k in SNIPPET_ENV if k in os.environ}
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          timeout=SNIPPET_TIMEOUT_S, cwd=os.getcwd(), env=env)
    out = proc.stdout + (f"\n{proc.stderr}" if proc.stderr else "")
    if proc.returncode != 0:
        out += f"\n[exit status {proc.returncode}]"
    return out.strip() or "[no output]"


def read_file(path: str, offset: int = 1, limit: int = 200) -> str:
    lines = _inside(path).read_text(errors="replace").splitlines()
    start = max(1, int(offset))
    chosen = lines[start - 1 : start - 1 + max(0, int(limit))]
    if not chosen:
        return f"[no lines: the file has {len(lines)}]"
    numbered = "\n".join(f"{i}\t{line}" for i, line in enumerate(chosen, start))
    rest = len(lines) - (start - 1 + len(chosen))
    return numbered + (f"\n[{rest} more lines]" if rest > 0 else "")


def list_dir(path: str = ".") -> str:
    target = _inside(path)
    entries = sorted(target.iterdir(), key=lambda p: p.name)
    if not entries:
        return "[empty]"
    return "\n".join(f"{p.name}{'/' if p.is_dir() else ''}\t{p.stat().st_size}" for p in entries)


IMPLEMENTATIONS = {"run_python": run_python, "read_file": read_file, "list_dir": list_dir}


def call(name: str, arguments: dict) -> tuple[str, bool]:
    """One tool call: `(text, is_error)`. Every failure is text the model can
    read, in one shape -- `error: <what>` -- so an error in one harness reads
    exactly as it does in another."""
    try:
        implementation = IMPLEMENTATIONS[name]
    except KeyError:
        return f"error: no tool named {name}", True
    try:
        return _cut(implementation(**arguments)), False
    except subprocess.TimeoutExpired:
        return f"error: the snippet ran longer than {SNIPPET_TIMEOUT_S} seconds", True
    except TypeError as e:  # wrong or missing arguments
        return f"error: {name} arguments: {e}", True
    except Exception as e:
        return f"error: {type(e).__name__}: {e}", True


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "schema":
        print(json.dumps(TOOLS, indent=2))
        return 0
    if len(sys.argv) >= 3 and sys.argv[1] == "call":
        arguments = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        text, is_error = call(sys.argv[2], arguments)
        print(text)
        return 1 if is_error else 0
    print(__doc__.strip().splitlines()[-2].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
