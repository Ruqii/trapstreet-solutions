"""Drive a real gate as a subprocess, one gate per spec file.

Specs live in `gates/*.json` and are filled in from the gate's ACTUAL
interface -- never from its README. A spec starts life with
`"verified": false` and the runner refuses it: a guessed field name makes a
gate fail open, and a board of allows reads as "this gate permits anything"
when it means "we fed it nothing it understood".

Fill a spec by running the gate's own help and one hand-made payload, then
record what you saw in `verified_notes`.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .base import Adapter, Result, Verdict


class SpecNotVerified(RuntimeError):
    pass


class SubprocessGate(Adapter):
    needs_network = True

    def __init__(self, spec_path: Path, allow_unverified: bool = False):
        self.spec = json.loads(Path(spec_path).read_text())
        self.name = self.spec["name"]
        if not self.spec.get("verified") and not allow_unverified:
            raise SpecNotVerified(
                f"{self.name}: spec is not verified against the installed gate. "
                f"Run `python3 verify_gate.py {spec_path}` first."
            )

    def judge(self, cell, workdir: Path) -> Result:
        from .session import to_hook_payload, to_transcript_jsonl

        transcript = workdir / "transcript.jsonl"
        transcript.write_text(to_transcript_jsonl(cell))
        payload = to_hook_payload(cell, transcript, workdir)

        env = dict(os.environ)
        env["HOME"] = str(workdir)          # state isolation: see README
        env.update(self.spec.get("env", {}))

        # `{root}` is the probe directory: a gate installed here must be
        # addressed absolutely, because every case runs with cwd and HOME
        # pointed at a throwaway state dir.
        root = Path.cwd()
        argv = [a.format(workdir=workdir, transcript=transcript, root=root)
                for a in self.spec["argv"]]
        stdin = json.dumps(payload) if self.spec.get("stdin") == "hook_payload" else None
        try:
            proc = subprocess.run(
                argv, input=stdin, env=env, cwd=workdir,
                capture_output=True, text=True, timeout=self.spec.get("timeout", 60),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return Result(cell.cell_id, self.name, Verdict.ERROR, raw=str(exc))

        return Result(cell.cell_id, self.name, self._map(proc), detail=self._detail(proc),
                      raw=(proc.stdout + proc.stderr)[-2000:])

    def _detail(self, proc) -> dict:
        """What to print beside the verdict: the gate's own fields, in the
        shape it prints them -- `key: value` lines, or a hook JSON object."""
        if self.spec["verdict_from"] == "claude_hook_stdout":
            try:
                data = json.loads(proc.stdout.strip() or "{}")
            except json.JSONDecodeError:
                return {"stdout": proc.stdout.strip()[:200]}
            node = data.get("hookSpecificOutput", data)
            return {k: str(v)[:200] for k, v in node.items() if k != "hookEventName"}
        fields = {}
        for line in proc.stdout.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fields[k.strip()] = v.strip().strip('"')
        return fields

    def _map(self, proc) -> Verdict:
        rule = self.spec["verdict_from"]
        if rule == "keyed_lines":
            # `key: value` lines, as jev-axi --explain prints them.
            fields = {}
            for line in proc.stdout.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fields[k.strip()] = v.strip().strip('"')
            # A gate that fails open turns a dead key into a clean sheet of
            # allows. Whatever the decision says, an error is an error.
            err_field, err_values = self.spec.get("error_when", ["", []])
            if fields.get(err_field) in err_values:
                return Verdict.ERROR
            decision = fields.get(self.spec.get("decision_field", "decision"), "")
            return Verdict(self.spec["verdict_map"].get(decision.lower(), "error"))
        if rule == "claude_hook_stdout":
            # Claude Code's own PreToolUse convention: no output means the
            # normal flow continues. A product that fails open prints its
            # reason on stderr and still exits 0 with an empty stdout, which
            # is byte-identical to a genuine allow -- so the markers it says
            # that with are checked before the silence is read as permission.
            blob = (proc.stdout + proc.stderr).lower()
            if any(mark.lower() in blob for mark in self.spec.get("fail_open_markers", [])):
                return Verdict.ERROR
            out = proc.stdout.strip()
            if not out:
                return Verdict.ALLOW
            try:
                data = json.loads(out)
            except json.JSONDecodeError:
                return Verdict.ERROR
            node = data.get("hookSpecificOutput", data)
            decision = str(node.get("permissionDecision") or node.get("decision") or "").lower()
            return Verdict(self.spec["verdict_map"].get(decision, "error"))
        if rule == "exit_code":
            table = self.spec["exit_codes"]        # e.g. {"0": "allow", "2": "deny"}
            return Verdict(table.get(str(proc.returncode), "error"))
        if rule == "stdout_json":
            try:
                value = json.loads(proc.stdout)
                for key in self.spec["stdout_path"]:
                    value = value[key]
            except Exception:
                return Verdict.ERROR
            return Verdict(self.spec["verdict_map"].get(str(value).lower(), "error"))
        raise ValueError(f"unknown verdict_from: {rule}")
