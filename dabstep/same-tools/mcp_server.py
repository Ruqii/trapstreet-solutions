"""tools.py over MCP, on stdio: how Claude Code and DSH mount the shared tools.

One JSON-RPC message per line, no SDK -- the dependency would be one more thing
that differs between the two harnesses, and the protocol's server half is this
small: initialize, tools/list, tools/call, and the notifications a client sends
on the way in and out.

The tool definitions come from tools.py unchanged, so what the model is shown
here and what a pi extension shows are the same bytes; a harness may still
namespace the *name* (Claude Code renames an MCP tool to
mcp__<server>__<tool>), which is the one difference this board reports rather
than hides.

    python3 mcp_server.py        # speaks MCP on stdin/stdout
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tools  # noqa: E402  (after sys.path, so the server runs from any cwd)

#: Answered with the version the client asks for when we know it, else this one.
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER = {"name": "bench", "version": "1.0.0"}


def _result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle(message: dict) -> dict | None:
    """The reply to one client message, or None for a notification (which by the
    protocol gets no reply -- answering one is what makes a client hang)."""
    method, request_id = message.get("method"), message.get("id")
    params = message.get("params") or {}
    if request_id is None:
        return None
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _result(request_id, {
            "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER,
        })
    if method == "tools/list":
        return _result(request_id, {"tools": tools.TOOLS})
    if method == "tools/call":
        text, is_error = tools.call(params.get("name", ""), params.get("arguments") or {})
        return _result(request_id, {"content": [{"type": "text", "text": text}], "isError": is_error})
    if method == "ping":
        return _result(request_id, {})
    return _error(request_id, -32601, f"method not found: {method}")


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue  # a client that sends noise is not a reason to die mid-case
        reply = handle(message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
