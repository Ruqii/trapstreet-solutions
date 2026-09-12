"""Claude Code, headless, as the harness for any model it can reach.

One script for every claude-code arm; an arm is only the flags in its trap.yaml
`cmd` (which model, where its key lives, how the vendor says to set it up) plus
the upstream in its .envrc. So a score difference between two claude-code arms
is the model and its setup, not this adapter.

Claude Code runs as shipped (its own system prompt, tool loop, sub-agents, task
list), not in --bare mode: --bare sets CLAUDE_CODE_SIMPLE=1 and cuts Claude Code
down to a minimal toolset. Its configuration is a fresh CLAUDE_CONFIG_DIR per
case instead: no user settings, hooks, plugins, memory or CLAUDE.md.

The whole Claude Code process runs in ../sandbox.py's jail, not just its Bash
tool: Read, Glob and Grep run in-process. It can read the case copy, its own
binary and the system trees, write only the case root, and connect only to the
cost proxy. Its session transcript is kept (copied to the case's outputs_dir)
so every tool call can be audited before a run is published.

Each arm is set up the way its vendor documents it:
- Anthropic: the defaults. --model picks the main model and Claude Code keeps
  its own small/fast model for side calls.
- A third-party Anthropic-format endpoint: the key goes in
  ANTHROPIC_AUTH_TOKEN with ANTHROPIC_API_KEY blanked (--auth bearer), and every
  model slot Claude Code might use is pinned (--all-slots, and --env for any
  slot the vendor sets differently), so no request goes out under a Claude name
  -- the endpoint would answer it, and the cost proxy would price it at Claude
  rates.

Metering: the upstream is set in the shell that launches `tp run` (the arm's
.envrc); tp then points ANTHROPIC_BASE_URL at its cost proxy for this process.
Setting a vendor URL here instead would bypass the proxy and the run would carry
no cost.

No web: WebSearch/WebFetch are disallowed, the jail allows one loopback port
(the cost proxy), and every HTTP(S) proxy variable points at a closed port.
Commands Claude Code runs get no API key (CLAUDE_CODE_SUBPROCESS_ENV_SCRUB).

stdout carries only Claude Code's final reply; its own JSON summary (turns,
its view of usage) goes to stderr for cross-checking.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import sandbox

# Under trap.yaml's 1800 s: tp SIGKILLs a case there, which no cleanup survives.
# DABSTEP_DEADLINE_S is for sandbox_canary.py's timeout check.
TIMEOUT_S = int(os.environ.get("DABSTEP_DEADLINE_S", 1700))
DEAD_PROXY = "http://127.0.0.1:9"
# Shell access is the read-only data toolkit a person would reach for (no rm, no
# installs, no network).
TOOLS = ("Read Glob Grep Write Edit NotebookEdit Agent TaskCreate TaskUpdate TaskList TaskGet "
         "Bash(python3:*) Bash(python:*) Bash(ls:*) Bash(head:*) Bash(tail:*) Bash(wc:*) Bash(cat:*) "
         "Bash(awk:*) Bash(sort:*) Bash(uniq:*) Bash(cut:*) Bash(tr:*) Bash(grep:*) Bash(jq:*) Bash(echo:*)")
PROMPT_SUFFIX = "\n\nThe files are in the current working directory."
MODEL_SLOTS = ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
               "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL", "ANTHROPIC_SMALL_FAST_MODEL",
               "CLAUDE_CODE_SUBAGENT_MODEL")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="the main model, as the endpoint names it")
    parser.add_argument("--key-env", required=True, help="the environment variable holding the key")
    parser.add_argument("--auth", choices=["x-api-key", "bearer"], default="x-api-key",
                        help="bearer: ANTHROPIC_AUTH_TOKEN, with ANTHROPIC_API_KEY blanked")
    parser.add_argument("--all-slots", action="store_true", help="pin every model slot to --model")
    parser.add_argument("--env", action="append", default=[], metavar="KEY=VALUE",
                        help="an extra setting from the vendor's guide; applied last")
    args = parser.parse_args()

    proxy = os.environ.get("ANTHROPIC_BASE_URL", "")
    if not proxy.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise SystemExit("ANTHROPIC_BASE_URL is not the tp cost proxy; run `tp run` from the arm's "
                         "directory with its .envrc loaded (direnv allow)")
    key = os.environ.get(args.key_env)
    if not key:
        raise SystemExit(f"{args.key_env} is not set")

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs, outputs = Path(manifest["inputs_dir"]), Path(manifest["outputs_dir"])
    prompt = (inputs / "question.txt").read_text().rstrip() + PROMPT_SUFFIX
    claude = os.path.realpath(shutil.which("claude") or "claude")
    root = sandbox.new_case_root("dabstep-cc-")
    workdir, config_dir = root / "work", root / "config"
    config_dir.mkdir()
    shutil.copytree(inputs, workdir, dirs_exist_ok=True)  # follows the symlinks: real copies

    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("TRAP", "CLAUDE", "ANTHROPIC_", "VIRTUAL_ENV"))}
    env = sandbox.jail_env(env, root)
    env.update(
        ANTHROPIC_BASE_URL=proxy,
        CLAUDE_CONFIG_DIR=str(config_dir),
        CLAUDE_CODE_TMPDIR=str(root / "tmp"),
        CLAUDE_CODE_SUBPROCESS_ENV_SCRUB="1",
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
        DISABLE_AUTOUPDATER="1",
        API_TIMEOUT_MS="600000",
        HTTP_PROXY=DEAD_PROXY, HTTPS_PROXY=DEAD_PROXY, ALL_PROXY=DEAD_PROXY,
        http_proxy=DEAD_PROXY, https_proxy=DEAD_PROXY,
        NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
    )
    if args.auth == "bearer":
        env.update(ANTHROPIC_AUTH_TOKEN=key, ANTHROPIC_API_KEY="")
    else:
        env["ANTHROPIC_API_KEY"] = key
    if args.all_slots:
        env.update({slot: args.model for slot in MODEL_SLOTS})
    for setting in args.env:
        name, _, value = setting.partition("=")
        env[name] = value

    cmd = [
        claude, "-p", prompt,
        "--model", args.model,
        "--output-format", "json",
        "--permission-mode", "acceptEdits",
        "--allowedTools", TOOLS,
        "--disallowedTools", "WebSearch WebFetch",
    ]
    port = sandbox.proxy_port(proxy)
    cmd = sandbox.wrap(cmd, root=root, readable=[Path(claude)], port=port)
    sandbox.attest(root=root, readable=[Path(claude)], port=port)
    # tp stops a case at trap.yaml's 1800 s with SIGKILL, which no cleanup
    # survives; stopping Claude Code at TIMEOUT_S keeps its transcript.
    try:
        proc = subprocess.run(cmd, cwd=workdir, env=env, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc = None
        print(json.dumps({"event": "timeout", "after_s": TIMEOUT_S}), file=sys.stderr)
    finally:
        keep = outputs / "transcripts"
        for jsonl in (config_dir / "projects").rglob("*.jsonl"):  # the session and any sub-agents'
            dest = keep / jsonl.relative_to(config_dir / "projects")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(jsonl, dest)
        shutil.rmtree(root, ignore_errors=True)

    if proc is None:
        return 124  # tp's own code for a timed-out case
    try:
        summary = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(proc.stderr[-4000:], file=sys.stderr)
        raise SystemExit(f"claude exited {proc.returncode} without a JSON result")
    reply = summary.pop("result", "") or ""
    version = subprocess.run([claude, "--version"], capture_output=True, text=True).stdout.strip()
    print(json.dumps({"event": "claude_code_summary", "claude_code": version, "exit": proc.returncode,
                      **summary}, default=str), file=sys.stderr)
    print(reply.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
