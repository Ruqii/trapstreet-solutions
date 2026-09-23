"""Drive a product through whatever its own installer registered.

The installer defines the product. We do not choose an entry point and we
do not compose stages ourselves: we run the product's install command into
an isolated HOME, read the hook list it wrote, and replay the session as
the event sequence a host would produce. Where a product registers one hook
(jev-axi: PreToolUse only) that is the product; where it registers four
(jev-guard: SessionStart, UserPromptSubmit, PostToolUse, PreToolUse) all
four run and the PreToolUse answer is the verdict -- an earlier stage's
mistake surfaces there rather than in a row of its own.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

from .base import Adapter, Result, Verdict

# The arm directory: `npm ci` (setup_cmd) installs the product beside the
# trap.yaml, and every case runs with cwd and HOME on a throwaway dir, so the
# binary has to be addressed absolutely from here.
ROOT = Path.cwd()


class InstalledGate(Adapter):
    needs_network = True

    def __init__(self, spec_path: Path):
        self.spec = json.loads(Path(spec_path).read_text())
        self.name = self.spec["name"]
        self.bin = str(ROOT / self.spec["bin"])
        if not Path(self.bin).exists():
            raise RuntimeError(f"{self.name}: {self.bin} is not installed")
        self._preflight()

    def _preflight(self) -> None:
        """Ask the product whether it can work at all, before the batch.

        These gates fail open by design: with no credentials jev-guard's
        hooks return rc=0 and empty stdout, which is indistinguishable from
        a genuine allow. One call to a command that answers out loud turns a
        silent sheet of permissions into a startup error."""
        args = self.spec.get("preflight_args")
        if not args:
            return
        env = dict(os.environ)
        for var in self.spec.get("key_env", []):
            env[var] = os.environ.get("TYPESAFE_API_KEY", "")
        proc = subprocess.run([self.bin] + args, env=env, capture_output=True,
                              text=True, timeout=60)
        blob = (proc.stdout + proc.stderr).lower()
        for bad in self.spec.get("preflight_fail_on", []):
            if bad.lower() in blob:
                raise RuntimeError(
                    f"{self.name}: not usable — {(proc.stdout + proc.stderr).strip()[:200]}")

    # ---------------------------------------------------------------- setup

    def _install(self, home: Path, env: dict) -> list[dict]:
        """Run the product's own installer; return the hooks it registered."""
        cmd = [self.bin] + self.spec["install_args"]
        subprocess.run(cmd, env=env, cwd=home, capture_output=True, text=True, timeout=60)
        settings = home / self.spec["settings_path"]
        if not settings.exists():
            raise RuntimeError(f"{self.name}: installer wrote no {self.spec['settings_path']}")
        hooks = json.loads(settings.read_text()).get("hooks", {})
        return {event: entries for event, entries in hooks.items()}

    def _env(self, home: Path) -> dict:
        env = dict(os.environ)
        env["HOME"] = str(home)
        # the product names its own credential variables; map ours onto them
        key = os.environ.get("TYPESAFE_API_KEY", "")
        for var in self.spec.get("key_env", []):
            env[var] = key
        env.update(self.spec.get("env", {}))
        return env

    # ------------------------------------------------------------- replay

    def _events(self, cell, transcript: Path, cwd: Path, session_id: str) -> list[dict]:
        base = {"session_id": session_id, "transcript_path": str(transcript), "cwd": str(cwd)}
        events = [dict(base, hook_event_name="SessionStart", source="startup")]
        for m in cell.messages:
            if m["role"] == "user":
                events.append(dict(base, hook_event_name="UserPromptSubmit", prompt=m["content"]))
            elif m["role"] == "tool":
                events.append(dict(base, hook_event_name="PostToolUse",
                                   tool_name=m.get("name", "Bash"),
                                   tool_input={}, tool_response=m["content"]))
        events.append(dict(base, hook_event_name="PreToolUse", tool_name="Bash",
                           tool_input={"command": cell.command}))
        return events

    def judge(self, cell, workdir: Path) -> Result:
        from .session import to_transcript_jsonl

        home = workdir / "home"
        proj = workdir / "proj"
        home.mkdir(parents=True, exist_ok=True)
        proj.mkdir(parents=True, exist_ok=True)
        env = self._env(home)
        session_id = uuid.uuid4().hex
        transcript = proj / "transcript.jsonl"
        transcript.write_text(to_transcript_jsonl(cell))

        try:
            registered = self._install(home, env)
        except Exception as exc:                        # noqa: BLE001
            return Result(cell.cell_id, self.name, Verdict.ERROR, raw=f"install: {exc}"[:300])

        last, trace = None, []
        for event in self._events(cell, transcript, proj, session_id):
            name = event["hook_event_name"]
            if name not in registered:
                trace.append(f"{name}: not registered, skipped")
                continue
            proc = subprocess.run(
                [self.bin] + self.spec["hook_args"], input=json.dumps(event),
                env=env, cwd=proj, capture_output=True, text=True,
                timeout=self.spec.get("timeout", 60),
            )
            trace.append(f"{name}: rc={proc.returncode} out={proc.stdout.strip()[:160]}")
            if name == "PreToolUse":
                last = proc
        if last is None:
            return Result(cell.cell_id, self.name, Verdict.ERROR,
                          raw="no PreToolUse hook registered\n" + "\n".join(trace))

        # liveness: a gate that never wrote its own state did not run
        live = self.spec.get("liveness_path")
        if live and not any((home / live).glob("**/*")):
            return Result(cell.cell_id, self.name, Verdict.ERROR,
                          raw="gate wrote no state — it failed open\n" + "\n".join(trace),
                          detail={"shape": "no-state"})

        verdict, detail = self._map(last)
        return Result(cell.cell_id, self.name, verdict, raw="\n".join(trace)[-2000:], detail=detail)

    # -------------------------------------------------------------- verdict

    def _map(self, proc) -> tuple[Verdict, dict]:
        """Claude Code's PreToolUse contract: no output means the normal flow
        continues (an allow); a decision object asks or denies."""
        out = proc.stdout.strip()
        if not out:
            return Verdict.ALLOW, {"shape": "empty"}
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return Verdict.ERROR, {"shape": "unparseable"}
        node = data.get("hookSpecificOutput", data)
        decision = str(node.get("permissionDecision") or node.get("decision") or "").lower()
        reason = str(node.get("permissionDecisionReason") or node.get("reason") or "")[:200]
        table = {"allow": Verdict.ALLOW, "ask": Verdict.ASK, "deny": Verdict.DENY,
                 "block": Verdict.DENY, "": Verdict.ALLOW}
        detail = {"decision": decision or "(none)", "reason": reason}
        # a gate that fails open turns a dead key into a sheet of allows
        if "no api key" in reason.lower() or "unavailable" in reason.lower():
            return Verdict.ERROR, detail
        return table.get(decision, Verdict.ERROR), detail
