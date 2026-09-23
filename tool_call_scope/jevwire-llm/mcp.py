"""A minimal MCP stdio client: jevwire ships its tools no other way.

Its `bin` is the stdio server, so calling `jev_evaluate` means speaking the
protocol -- JSON-RPC 2.0, one message per line. Nothing here interprets the
tool's answer; it is handed back verbatim.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


class McpStdio:
    def __init__(self, argv: list[str], cwd: Path, env: dict[str, str]):
        self.proc = subprocess.Popen(
            argv, cwd=str(cwd), env=env, text=True, bufsize=1,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._id = 0
        self._request("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "tool-call-scope-arm", "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, message: dict) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def _read(self) -> dict | None:
        assert self.proc.stdout
        while True:
            line = self.proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue

    def _request(self, method: str, params: dict) -> dict | None:
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        return self._read()

    def call_tool(self, name: str, arguments: dict) -> str:
        reply = self._request("tools/call", {"name": name, "arguments": arguments})
        if reply is None:
            return json.dumps({"error": "the server stopped answering"})
        if "error" in reply:
            return json.dumps({"error": reply["error"]})
        result = reply.get("result", {})
        structured = result.get("structuredContent")
        if structured is not None:
            return json.dumps(structured)
        return "".join(b.get("text", "") for b in result.get("content", []))

    def close(self) -> None:
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:                                       # noqa: BLE001
            self.proc.kill()
