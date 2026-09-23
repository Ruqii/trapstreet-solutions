"""Drive a gate whose hot path is a loopback daemon, not a process per call.

jevwire's plugin registers PreToolUse as an HTTP post to 127.0.0.1:10522 and
gives it no command fallback -- UserPromptSubmit has one, the gate does not --
so the daemon its SessionStart hook starts is not an optimisation, it is the
product. This adapter starts it the way the plugin does and posts the same
events to the same URLs with the same headers.

Two of its properties decide how the answers are read.

`allow` is not representable: the handler says so in a comment and a test named
never-allow asserts it. A call it does not object to comes back `{}`, which is
Claude Code's "carry on" -- so an empty body is an ALLOW here, and the row says
"this gate let the call through", not "this gate had nothing to say".

And every failure fails open in silence -- no key, a timeout, a refused
connection all produce exactly that same empty body. So the adapter preflights
a call that only the model path can answer, and treats a dead daemon as an
error rather than a permission.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .base import Adapter, Result, Verdict

ROOT = Path.cwd()


class DaemonGate(Adapter):
    needs_network = True

    def __init__(self, spec_path: Path):
        self.spec = json.loads(Path(spec_path).read_text())
        self.name = self.spec["name"]
        self.plugin = ROOT / self.spec["plugin_root"]
        self.hook = self.plugin / self.spec["hook_entry"]
        if not self.hook.exists():
            raise RuntimeError(f"{self.name}: {self.hook} is not built")
        self.base = self.spec["daemon_url"]
        self.key = os.environ.get(self.spec.get("key_env", "TYPESAFE_API_KEY"), "")
        if not self.key:
            raise RuntimeError(f"{self.name}: no key in {self.spec.get('key_env')}")

    # ---------------------------------------------------------------- daemon

    def _session_start(self, home: Path, cwd: Path, session_id: str) -> None:
        """The plugin's own SessionStart hook, which is what starts the daemon."""
        env = dict(os.environ, HOME=str(home), CLAUDE_PLUGIN_ROOT=str(self.plugin))
        event = {"session_id": session_id, "cwd": str(cwd),
                 "hook_event_name": "SessionStart", "source": "startup"}
        subprocess.run(["node", str(self.hook), "SessionStart"], input=json.dumps(event),
                       env=env, cwd=cwd, capture_output=True, text=True, timeout=30)

    def _post(self, event_name: str, payload: dict) -> dict | None:
        """One hook post. None means the daemon did not answer at all."""
        request = urllib.request.Request(
            f"{self.base}/v1/hook/{event_name}", data=json.dumps(payload).encode(),
            headers={"content-type": "application/json", "X-Jev-Protocol": "1",
                     "X-Jev-Env-Key": self.key}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.spec.get("timeout", 60)) as response:
                return json.loads(response.read() or b"{}")
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None

    def _preflight(self, home: Path, cwd: Path) -> str | None:
        """Prove the model path answers, not just that a port is open.

        A tripwire fires from a code rule with no key at all, so denying
        `rm -rf ~/` proves nothing about credentials. The probe below is a call
        the classifier has to speak to, and its advisory names its own source.
        """
        session_id = uuid.uuid4().hex
        self._session_start(home, cwd, session_id)
        # A fresh host each time: this gate remembers fingerprints across a
        # session and a repeated probe would be answered as a repeat.
        probe = self.spec["preflight_command"].format(nonce=uuid.uuid4().hex[:8])
        answer = self._post("PreToolUse", {
            "session_id": session_id, "cwd": str(cwd), "hook_event_name": "PreToolUse",
            "tool_name": "Bash", "tool_input": {"command": probe}})
        if answer is None:
            return "the daemon did not answer"
        blob = json.dumps(answer)
        if self.spec["preflight_expect"] not in blob:
            return f"the model path is silent: {blob[:200]}"
        return None

    # -------------------------------------------------------------- verdict

    def judge(self, cell, workdir: Path) -> Result:
        home, proj = workdir / "home", workdir / "proj"
        home.mkdir(parents=True, exist_ok=True)
        proj.mkdir(parents=True, exist_ok=True)

        failure = self._preflight(home, proj)
        if failure:
            return Result(cell.cell_id, self.name, Verdict.ERROR, raw=failure)

        session_id = uuid.uuid4().hex
        self._session_start(home, proj, session_id)
        base = {"session_id": session_id, "cwd": str(proj)}
        trace = []
        for message in cell.messages:
            if message["role"] == "user":
                self._post("UserPromptSubmit", dict(
                    base, hook_event_name="UserPromptSubmit", prompt=message["content"]))
            elif message["role"] == "tool":
                self._post("PostToolUse", dict(
                    base, hook_event_name="PostToolUse", tool_name=message.get("name", "Bash"),
                    tool_input={}, tool_response=message["content"]))
            time.sleep(0.05)      # the daemon records a session's turns in order

        answer = self._post("PreToolUse", dict(
            base, hook_event_name="PreToolUse", tool_name="Bash",
            tool_input={"command": cell.command}))
        if answer is None:
            return Result(cell.cell_id, self.name, Verdict.ERROR,
                          raw="the daemon stopped answering mid-case")

        node = answer.get("hookSpecificOutput", answer)
        decision = str(node.get("permissionDecision") or "").lower()
        detail = {
            "decision": decision or "(none)",
            "reason": str(node.get("permissionDecisionReason") or "")[:300],
            # The advisory is the classifier's own words. It is recorded and
            # never scored: this gate reports scope rather than gating on it,
            # and a column that scored the note would be scoring our reading
            # of it instead of the product's decision.
            "advisory": str(node.get("additionalContext") or "")[:400],
        }
        table = {"allow": Verdict.ALLOW, "ask": Verdict.ASK, "deny": Verdict.DENY,
                 "block": Verdict.DENY, "": Verdict.ALLOW}
        return Result(cell.cell_id, self.name, table.get(decision, Verdict.ERROR),
                      raw=json.dumps(answer)[:2000], detail=detail)
