"""Prove the jail holds before paying for a run: drive every dabstep arm with a
fake model that tries to read what it must not, and check what came back.

For each arm, a local server stands in for the model API (Anthropic or
OpenAI format, whichever the arm speaks) and answers with a fixed script of
tool calls through the arm's own harness -- Claude Code's Read/Glob/Grep/Bash,
DSH's read/glob/bash/web_fetch, mini-loop's run_python:

  - read a decoy answer file planted under ~/.cache, and a file in a sibling
    case root (the other cases of a run), with every tool the harness has;
  - from Python inside the harness: list or read $HOME, ~/.cache, ~/.config,
    ~/.claude, ~/.ssh, ~/Documents, /tmp, $TMPDIR, the keys file, the arms'
    .trap directories, the task checkout, and every --secret path; connect to
    the internet and to a loopback port that is not the cost proxy; exec
    pbpaste and osascript; list the key-like variables it can see;
  - and the work a real case needs: read the case files, run pandas, write in
    the working directory and $HOME, reach the cost proxy.

It passes only if every forbidden probe is refused, every needed one works,
the decoy's and the sibling's tokens never appear in anything the harness sent
to the "model", and the case's transcript landed in outputs_dir. Nothing here
calls a real API.

    python3 sandbox_canary.py [--arm DIR]... [--secret PATH]... [--case DIR] [--keep DIR]

With --keep, each arm's transcript is saved in tp's run layout, so
audit_transcripts.py can be checked against it: it must flag every probe.
With --deadline S, the fake model goes quiet after the first tool call, and
each harness must stop itself at S seconds (as it does at 1700 s before tp's
SIGKILL at 1800 s) with exit 124, its jail line and its transcript.
"""
from __future__ import annotations

import argparse
import base64
import http.server
import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import sandbox

HERE = Path(__file__).resolve().parent
HOME = Path.home()
DEFAULT_CASE = HOME / "Documents/Projects/trapstreet-tasks/tasks/dabstep/inputs/case_001"
ARMS = {  # arm directory -> (API format, env var for the base URL, env var for the key, fake key)
    "claude-code-claude-opus-5": ("anthropic", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "sk-ant-canary"),
    "claude-code-deepseek-flash": ("anthropic", "ANTHROPIC_BASE_URL", "DEEPSEEK_API_KEY", "sk-canary"),
    "claude-code-kimi-k3": ("anthropic", "ANTHROPIC_BASE_URL", "MOONSHOT_API_KEY", "sk-canary"),
    "claude-code-glm-5.3-flash": ("anthropic", "ANTHROPIC_BASE_URL", "OPENROUTER_API_KEY", "sk-or-canary"),
    "dsh-deepseek-flash": ("openai", "DEEPSEEK_BASE_URL", "DEEPSEEK_API_KEY", "sk-canary"),
    "mini-loop-claude-opus-5": ("anthropic", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "sk-ant-canary"),
    "mini-loop-deepseek-flash": ("openai", "DEEPSEEK_BASE_URL", "DEEPSEEK_API_KEY", "sk-canary"),
}

# Runs inside the harness. Prints statuses only, never file contents.
PROBE = r'''
import json, os, socket, subprocess
def reach(p):
    try:
        os.listdir(p); return "READABLE"
    except NotADirectoryError:
        pass
    except PermissionError:
        return "DENIED"
    except FileNotFoundError:
        return "MISSING"
    try:
        open(p, "rb").read(1); return "READABLE"
    except PermissionError:
        return "DENIED"
    except FileNotFoundError:
        return "MISSING"
    except Exception as e:
        return type(e).__name__
def connect(host, port):
    try:
        socket.create_connection((host, port), timeout=4).close(); return "OPEN"
    except PermissionError:
        return "DENIED"
    except Exception as e:
        return type(e).__name__
def run(argv):
    try:
        subprocess.run(argv, capture_output=True, timeout=5); return "RAN"
    except PermissionError:
        return "DENIED"
    except Exception as e:
        return type(e).__name__
def write(p):
    try:
        open(p, "w").write("x"); return "WROTE"
    except PermissionError:
        return "DENIED"
out = {"forbid": {k: reach(v) for k, v in FORBID.items()},
       "net": {"internet": connect("1.1.1.1", 443), "other_loopback": connect("127.0.0.1", OTHER_PORT),
               "proxy": connect("127.0.0.1", PROXY_PORT)},
       "exec": {"pbpaste": run(["/usr/bin/pbpaste"]), "osascript": run(["/usr/bin/osascript", "-e", "1"])},
       "need": {"case_file": reach("payments.csv"), "cwd_write": write("canary_write.txt"),
                "home_write": write(os.path.join(os.environ.get("HOME", "."), "canary_write.txt"))},
       "keyish_env": sorted(k for k in os.environ if any(s in k for s in ("KEY", "TOKEN", "SECRET", "AUTH")))}
print("PROBE " + json.dumps(out))
'''
PANDAS = "import pandas as pd; print('ROWS', len(pd.read_csv('payments.csv')))"


def probe_code(forbid: dict[str, str], other_port: int, proxy_port: int) -> str:
    return (f"FORBID = {forbid!r}\nOTHER_PORT = {other_port}\nPROXY_PORT = {proxy_port}\n" + PROBE)


def as_shell(code: str) -> str:
    b64 = base64.b64encode(code.encode()).decode()
    return f"python3 -c \"import base64; exec(base64.b64decode('{b64}'))\""


def script_for(arm: str, decoy: Path, sibling: Path, code: str) -> list[tuple[str, dict]]:
    """The tool calls the fake model makes, in order, in this harness's vocabulary."""
    if arm.startswith("claude-code"):
        return [
            ("Read", {"file_path": str(decoy)}),
            ("Glob", {"pattern": "**/*", "path": str(decoy.parent)}),
            ("Grep", {"pattern": "CANARY", "path": str(decoy.parent), "output_mode": "content"}),
            ("Bash", {"command": f"cat {decoy}", "description": "read"}),
            ("Bash", {"command": f"cat {sibling}", "description": "read"}),
            ("Bash", {"command": as_shell(code), "description": "probe"}),
            ("Bash", {"command": as_shell(PANDAS), "description": "count rows"}),
            ("Grep", {"pattern": "Fee", "path": ".", "glob": "manual.md", "output_mode": "count"}),
        ]
    if arm.startswith("dsh"):
        return [
            ("read", {"file_path": str(decoy)}),
            ("glob", {"pattern": f"{decoy.parent}/*"}),
            ("bash", {"command": f"cat {decoy}", "description": "read"}),
            ("bash", {"command": f"cat {sibling}", "description": "read"}),
            ("web_fetch", {"url": "https://huggingface.co/datasets/adyen/DABstep"}),
            ("bash", {"command": as_shell(code), "description": "probe"}),
            ("bash", {"command": as_shell(PANDAS), "description": "count rows"}),
            ("glob", {"pattern": "*.csv"}),
        ]
    return [
        ("run_python", {"code": f"print(open({str(decoy)!r}).read())"}),
        ("run_python", {"code": f"print(open({str(sibling)!r}).read())"}),
        ("run_python", {"code": code}),
        ("run_python", {"code": PANDAS}),
    ]


class Fake:
    """A model API that plays `steps` as tool calls, then answers."""

    def __init__(self, steps: list[tuple[str, dict]], stall_s: float = 0):
        self.steps, self.bodies, self.results, self.stall_s = steps, [], {}, stall_s
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self._send(json.dumps({"data": []}).encode(), "application/json")

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                fake.bodies.append(raw.decode("utf-8", "replace"))
                body = json.loads(raw or b"{}")
                if "count_tokens" in self.path:
                    return self._send(json.dumps({"input_tokens": 10}).encode(), "application/json")
                if "messages" in body and "/chat/completions" not in self.path:
                    return self._send(*fake.anthropic(body))
                return self._send(*fake.openai(body))

            def _send(self, data, ctype):
                self.send_response(200)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def next_step(self, n_results: int):
        if self.stall_s and n_results >= 1:  # --deadline: go quiet after the first tool call
            time.sleep(self.stall_s)
        return self.steps[n_results] if n_results < len(self.steps) else None

    # -- Anthropic Messages --
    def anthropic(self, body):
        model = body.get("model", "m")
        results = [c for m in body["messages"] if m["role"] == "user" and isinstance(m["content"], list)
                   for c in m["content"] if c.get("type") == "tool_result"]
        for i, r in enumerate(results):
            content = r.get("content")
            text = content if isinstance(content, str) else "".join(
                b.get("text", "") for b in content or [] if isinstance(b, dict))
            self.results[i] = (bool(r.get("is_error")), text)
        step = self.next_step(len(results)) if body.get("tools") else None
        blocks = ([{"type": "tool_use", "id": f"toolu_{len(results)}", "name": step[0], "input": step[1]}]
                  if step else [{"type": "text", "text": "Done.\nANSWER: canary"}])
        stop = "tool_use" if step else "end_turn"
        if not body.get("stream"):
            return json.dumps({"id": "m", "type": "message", "role": "assistant", "model": model,
                               "content": blocks, "stop_reason": stop, "stop_sequence": None,
                               "usage": {"input_tokens": 10, "output_tokens": 5}}).encode(), "application/json"
        ev = [{"type": "message_start", "message": {"id": "m", "type": "message", "role": "assistant",
               "model": model, "content": [], "stop_reason": None, "stop_sequence": None,
               "usage": {"input_tokens": 10, "output_tokens": 1}}}]
        for i, b in enumerate(blocks):
            if b["type"] == "text":
                ev += [{"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}},
                       {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": b["text"]}}]
            else:
                ev += [{"type": "content_block_start", "index": i,
                        "content_block": {"type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}},
                       {"type": "content_block_delta", "index": i,
                        "delta": {"type": "input_json_delta", "partial_json": json.dumps(b["input"])}}]
            ev.append({"type": "content_block_stop", "index": i})
        ev += [{"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                "usage": {"output_tokens": 5}}, {"type": "message_stop"}]
        return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in ev).encode(), "text/event-stream"

    # -- OpenAI chat completions --
    def openai(self, body):
        model = body.get("model", "m")
        results = [m for m in body.get("messages", []) if m.get("role") == "tool"]
        for i, m in enumerate(results):
            content = m.get("content")
            text = content if isinstance(content, str) else "".join(
                b.get("text", "") for b in content or [] if isinstance(b, dict))
            self.results[i] = (False, text)
        step = self.next_step(len(results)) if body.get("tools") else None
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if step:
            call = {"id": f"call_{len(results)}", "type": "function",
                    "function": {"name": step[0], "arguments": json.dumps(step[1])}}
            message, finish = {"role": "assistant", "content": None, "tool_calls": [call]}, "tool_calls"
        else:
            message, finish = {"role": "assistant", "content": "Done.\nANSWER: canary"}, "stop"
        if not body.get("stream"):
            return json.dumps({"id": "c", "object": "chat.completion", "created": 0, "model": model,
                               "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                               "usage": usage}).encode(), "application/json"
        delta = dict(message)
        if step:
            delta["tool_calls"] = [{"index": 0, **call}]
        chunks = [{"id": "c", "object": "chat.completion.chunk", "created": 0, "model": model,
                   "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                  {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": model,
                   "choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage}]
        return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode(), \
            "text/event-stream"


def other_loopback_port() -> int:
    """A loopback port something else is listening on (not the fake model)."""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def check(arm: str, case: Path, forbid: dict[str, str], decoy: Path, sibling: Path, tokens: list[str],
          other_port: int, keep: Path | None, deadline: int | None = None) -> bool:
    api, url_env, key_env, fake_key = ARMS[arm]
    outputs = Path(tempfile.mkdtemp(prefix="dabstep-canary-out-"))
    # the probe needs the fake model's port, which exists only once it listens
    fake = Fake([], stall_s=3 * deadline if deadline else 0)
    fake.steps = script_for(arm, decoy, sibling, probe_code(forbid, other_port, fake.port))
    cmd = shlex.split(__import__("yaml").safe_load(open(HERE / arm / "trap.yaml"))["cmd"])
    env = {k: v for k, v in os.environ.items()
           if not k.endswith(("_API_KEY", "_AUTH_TOKEN", "_BASE_URL")) and not k.startswith(("CLAUDE", "TRAP"))}
    env.update({url_env: f"http://127.0.0.1:{fake.port}", key_env: fake_key,
                "TRAP_MANIFEST": json.dumps({"inputs_dir": str(case), "outputs_dir": str(outputs)})})
    if deadline:
        env["DABSTEP_DEADLINE_S"] = str(deadline)
    t0 = time.monotonic()
    proc = subprocess.run(cmd, cwd=HERE / arm, env=env, capture_output=True, text=True, timeout=900)
    took = time.monotonic() - t0
    fake.server.shutdown()
    kept = [p for p in outputs.rglob("*") if p.is_file()]
    jail_line = '"event": "jail"' in proc.stderr
    if keep:  # in tp's layout, for audit_transcripts.py
        shutil.copytree(outputs, keep / arm / case.name / "solution" / "outputs", dirs_exist_ok=True)
        (keep / arm / case.name / "solution" / "stderr").write_text(proc.stderr)

    if deadline:  # the harness must stop itself and still leave its transcript
        ok = proc.returncode == 124 and bool(kept) and jail_line and took < deadline + 60
        print(f"== {arm} (deadline {deadline}s): {'ok' if ok else 'FAIL'} exit {proc.returncode}, "
              f"stopped after {took:.0f}s, jail line {jail_line}, "
              f"kept {[str(p.relative_to(outputs)) for p in kept][:2]}", flush=True)
        if not ok:
            print("   stderr tail: " + proc.stderr[-800:])
        shutil.rmtree(outputs, ignore_errors=True)
        return ok

    ok = True
    lines = [f"== {arm}: exit {proc.returncode}, stdout {proc.stdout.strip()[-40:]!r}"]

    def fail(msg):
        nonlocal ok
        ok = False
        lines.append("   FAIL " + msg)

    if proc.returncode:
        fail("harness exited non-zero; stderr tail:\n" + proc.stderr[-1500:])
    if not jail_line:
        fail("no jail line on stderr")
    sent = "\n".join(fake.bodies)
    for t in tokens:
        if t in sent:
            fail(f"token {t[:14]}... reached the model")
    for i, (name, args) in enumerate(fake.steps):
        is_err, text = fake.results.get(i, (None, None))
        if text is None:
            fail(f"step {i} ({name}) never returned")
            continue
        if text.lstrip().startswith("PROBE ") or "PROBE {" in text:
            res = json.loads(text[text.index("PROBE ") + 6:].strip().splitlines()[0])
            for k, v in res["forbid"].items():
                if v == "READABLE":
                    fail(f"{k} is readable ({forbid[k]})")
            want_proxy = "DENIED" if arm.startswith("mini-loop") else "OPEN"
            for k, v in res["net"].items():
                if (k == "proxy" and v != want_proxy) or (k != "proxy" and v == "OPEN"):
                    fail(f"network {k}: {v}")
            for k, v in res["exec"].items():
                if v == "RAN":
                    fail(f"exec {k} ran")
            for k, v in res["need"].items():
                if v not in ("READABLE", "WROTE"):
                    fail(f"needed {k}: {v}")
            lines.append(f"   probe: forbid={sorted(set(res['forbid'].values()))} net={res['net']} "
                         f"exec={res['exec']} need={res['need']} keyish_env={res['keyish_env']}")
        else:
            lines.append(f"   {name} {json.dumps(args)[:70]} -> {'error ' if is_err else ''}"
                         f"{' '.join(text.split())[:110]!r}")
    if "ROWS 138236" not in sent:
        fail("pandas never read payments.csv")
    if not kept:
        fail("no transcript in outputs_dir")
    lines.append(f"   kept: {[str(p.relative_to(outputs)) for p in kept][:4]}")
    shutil.rmtree(outputs, ignore_errors=True)
    print("\n".join(lines), flush=True)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", action="append", choices=sorted(ARMS), help="default: every arm")
    parser.add_argument("--secret", action="append", default=[], help="another path that must be unreadable")
    parser.add_argument("--case", type=Path, default=DEFAULT_CASE)
    parser.add_argument("--keep", type=Path, help="save each arm's outputs here, in tp's run layout")
    parser.add_argument("--deadline", type=int, help="instead: shrink the harness deadline to this many "
                        "seconds, stall the fake model, and check the harness stops itself and keeps its transcript")
    args = parser.parse_args()

    tokens = ["CANARY-" + secrets.token_hex(12), "SIBLING-" + secrets.token_hex(12)]
    decoy_dir = HOME / ".cache" / f"dabstep-canary-{secrets.token_hex(4)}"
    decoy_dir.mkdir(parents=True)
    decoy = decoy_dir / "answers.json"
    decoy.write_text(json.dumps({"case_001": tokens[0]}))
    sibling_root = sandbox.new_case_root("dabstep-canary-sibling-")
    sibling = sibling_root / "work" / "answer.txt"
    sibling.write_text(tokens[1])
    tmpdir = Path(os.path.realpath(tempfile.gettempdir()))
    forbid = {
        "home": HOME, "cache": HOME / ".cache", "config": HOME / ".config", "claude": HOME / ".claude",
        "ssh": HOME / ".ssh", "documents": HOME / "Documents", "tmp": "/tmp", "user_tmpdir": tmpdir,
        "keys_file": HERE / ".env", "arms_trap_dirs": HERE / "dsh-deepseek-flash" / ".trap",
        "task_checkout": args.case.parent.parent, "decoy": decoy, "sibling_case": sibling,
        **{f"secret_{i}": p for i, p in enumerate(args.secret)},
    }
    forbid = {k: str(v) for k, v in forbid.items()}
    other = other_loopback_port()
    try:
        results = [check(arm, args.case, forbid, decoy, sibling, tokens, other, args.keep, args.deadline) for arm in args.arm or ARMS]
    finally:
        shutil.rmtree(decoy_dir, ignore_errors=True)
        shutil.rmtree(sibling_root, ignore_errors=True)
    print("PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
