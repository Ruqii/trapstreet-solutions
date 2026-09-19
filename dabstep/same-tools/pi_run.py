"""Pi on the same-tools board: its own tools off, the three shared tools on.

Pi is run the plain way its docs describe -- `pi -p` with one prompt -- rather
than over ACP as the as-shipped pi arm is, because this board is about the
harness's own loop and a bridge between it and tp is one more thing that would
differ between rows.

  tools      --no-builtin-tools turns off read/write/edit/bash, and
             pi_extension.ts registers mcp__bench__{run_python,read_file,
             list_dir} from tools.py's own schema output. Pi has no MCP; the
             extension API is the plumbing, and what the model is shown is the
             same bytes Claude Code and DSH show (probe_tools.py diffs them).
  model      the arm's provider, routed through tp's cost proxy by
             pi_acp.pi_config, with only that provider's key in the jail.
  isolation  ../sandbox.py, as every other arm: the case copy is readable, the
             case root is writable, the cost proxy is the one open port.
  transcript Pi's session JSONL, copied into the case's outputs_dir.

    python3 pi_run.py --model deepseek/deepseek-flash --thinking high
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pi_acp  # noqa: E402  (install_pi, pi_config, ROUTES: one Pi install, one config)
import sandbox  # noqa: E402

HERE = Path(__file__).resolve().parent
TIMEOUT_S = int(os.environ.get("DABSTEP_DEADLINE_S", 1700))
DEAD_PROXY = "http://127.0.0.1:9"


def main() -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="<provider>/<id>, as pi names it")
    parser.add_argument("--thinking", default="high", help="pi's thinking level")
    args = parser.parse_args()

    provider, _, model = args.model.partition("/")
    if provider not in pi_acp.ROUTES or not model:
        raise SystemExit(f"--model must be <provider>/<id> with provider one of {sorted(pi_acp.ROUTES)}")
    base_var, key_var = pi_acp.ROUTES[provider]
    proxy = os.environ.get(base_var, "")
    port = sandbox.proxy_port(proxy)
    key = os.environ.get(key_var)
    if not key:
        raise SystemExit(f"{key_var} is not set")

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs, outputs = Path(manifest["inputs_dir"]), Path(manifest["outputs_dir"])
    prefix = pi_acp.install_pi()
    root = sandbox.new_case_root("dabstep-pi-same-")
    workdir = root / "work"
    shutil.copytree(inputs, workdir, dirs_exist_ok=True)  # follows the symlinks: real copies
    # The files the jail needs, never the directory: HERE holds the arms, and an
    # arm's .trap/ holds tp's checkout of the task (every other case's question).
    (root / "tools").mkdir()
    for name in ("tools.py", "pi_extension.ts"):
        shutil.copy2(HERE / name, root / "tools" / name)
    pi_acp.pi_config(root / "home", provider, model, args.thinking, proxy)
    extensions = root / "home/.pi/agent/extensions"
    extensions.mkdir(parents=True)
    shutil.copy2(root / "tools/pi_extension.ts", extensions / "bench.ts")

    prompt = (workdir / "question.txt").read_text().rstrip() + pi_acp.PROMPT_SUFFIX
    env = {k: v for k, v in os.environ.items() if not k.startswith(pi_acp.VENDOR_PREFIXES)}
    env = sandbox.jail_env(env, root)
    env.update({key_var: key, base_var: proxy})
    env.update(
        BENCH_TOOLS=str(root / "tools/tools.py"),
        PI_OFFLINE="1", PI_TELEMETRY="0", PI_SKIP_VERSION_CHECK="1",
        HTTP_PROXY=DEAD_PROXY, HTTPS_PROXY=DEAD_PROXY, ALL_PROXY=DEAD_PROXY,
        http_proxy=DEAD_PROXY, https_proxy=DEAD_PROXY,
        NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
    )
    cmd = [str(prefix / "node_modules/.bin/pi"), "--no-builtin-tools", "--no-themes",
           "--provider", provider, "--model", args.model, "--thinking", args.thinking, "-p", prompt]
    cmd = sandbox.wrap(cmd, root=root, readable=[prefix], port=port)
    sandbox.attest(root=root, readable=[prefix], port=port)
    print(json.dumps({"event": "start", "harness": "pi", "model": args.model,
                      "tools": "same-tools via pi extension"}), file=sys.stderr, flush=True)
    try:
        proc = subprocess.run(cmd, cwd=workdir, env=env, capture_output=True, text=True,
                              timeout=max(1, TIMEOUT_S - (time.monotonic() - started)))
    except subprocess.TimeoutExpired:
        proc = None
        print(json.dumps({"event": "timeout", "after_s": TIMEOUT_S}), file=sys.stderr)
    finally:
        sessions = root / "home/.pi/agent/sessions"
        for jsonl in sessions.rglob("*.jsonl") if sessions.is_dir() else ():
            dest = outputs / "transcripts" / jsonl.relative_to(sessions)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(jsonl, dest)
        shutil.rmtree(root, ignore_errors=True)

    if proc is None:  # graded as not answered, and the run still finishes; see sandbox.NO_REPLY
        print(sandbox.NO_REPLY)
        return 0
    if proc.stderr.strip():
        print(proc.stderr[-4000:], file=sys.stderr)
    print(proc.stdout.strip())
    return 0 if proc.returncode == 0 else proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
