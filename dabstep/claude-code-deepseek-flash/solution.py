"""Claude Code, headless, driving DeepSeek's deepseek-flash through DeepSeek's
Anthropic-format endpoint.

Claude Code runs as shipped (its own system prompt, tool loop, sub-agents, task
list), not in --bare mode: --bare sets CLAUDE_CODE_SIMPLE=1 and cuts Claude Code
down to a minimal toolset, which is the weak harness this arm is compared
against. Isolation from this machine comes from a fresh CLAUDE_CONFIG_DIR per
case instead: no user settings, hooks, plugins, memory or CLAUDE.md.

Every model Claude Code might pick -- main loop, sub-agents, its small/fast side
calls -- is set to the same DeepSeek id, so no request goes out under a Claude
name (DeepSeek would answer it, and the cost proxy would price it at Claude
rates).

Metering: the upstream is set in the shell that launches `tp run`
(ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic, see ../run-arm.sh); tp
then points ANTHROPIC_BASE_URL at its cost proxy for this process. Setting the
DeepSeek URL here instead would bypass the proxy and the run would carry no
cost.

No web: WebSearch/WebFetch are disallowed, and every HTTP(S) proxy variable
points at a closed port for Claude Code and the commands it runs, with only
loopback (the cost proxy) exempt.

stdout carries only Claude Code's final reply; its own JSON summary (turns,
its view of usage) goes to stderr for cross-checking.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MODEL = "deepseek-flash"
TIMEOUT_S = 1700  # under trap.yaml's timeout, so a slow case still reports
DEAD_PROXY = "http://127.0.0.1:9"
TOOLS = ("Read Glob Grep Write Edit NotebookEdit Agent TaskCreate TaskUpdate TaskList TaskGet "
         "Bash(python3:*) Bash(ls:*) Bash(head:*) Bash(wc:*)")
PROMPT_SUFFIX = "\n\nThe files are in the current working directory."


def main() -> int:
    proxy = os.environ.get("ANTHROPIC_BASE_URL", "")
    if not proxy.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise SystemExit("ANTHROPIC_BASE_URL is not the tp cost proxy; launch with ../run-arm.sh")
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise SystemExit("DEEPSEEK_API_KEY is not set")

    inputs = Path(json.loads(os.environ["TRAP_MANIFEST"])["inputs_dir"])
    prompt = (inputs / "question.txt").read_text().rstrip() + PROMPT_SUFFIX
    workdir = Path(tempfile.mkdtemp(prefix="dabstep-cc-"))
    config_dir = Path(tempfile.mkdtemp(prefix="dabstep-cc-config-"))
    shutil.copytree(inputs, workdir, dirs_exist_ok=True)  # follows the symlinks: real copies

    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("TRAP", "CLAUDE", "ANTHROPIC_AUTH", "VIRTUAL_ENV"))}
    env.update(
        ANTHROPIC_BASE_URL=proxy,
        ANTHROPIC_API_KEY=key,
        CLAUDE_CONFIG_DIR=str(config_dir),
        ANTHROPIC_MODEL=MODEL,
        ANTHROPIC_DEFAULT_OPUS_MODEL=MODEL,
        ANTHROPIC_DEFAULT_SONNET_MODEL=MODEL,
        ANTHROPIC_DEFAULT_HAIKU_MODEL=MODEL,
        ANTHROPIC_SMALL_FAST_MODEL=MODEL,
        CLAUDE_CODE_SUBAGENT_MODEL=MODEL,
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
        DISABLE_AUTOUPDATER="1",
        API_TIMEOUT_MS="600000",
        HTTP_PROXY=DEAD_PROXY, HTTPS_PROXY=DEAD_PROXY, ALL_PROXY=DEAD_PROXY,
        http_proxy=DEAD_PROXY, https_proxy=DEAD_PROXY,
        NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
    )
    cmd = [
        "claude", "-p", prompt,
        "--model", MODEL,
        "--output-format", "json",
        "--permission-mode", "acceptEdits",
        "--allowedTools", TOOLS,
        "--disallowedTools", "WebSearch WebFetch",
        "--no-session-persistence",
    ]
    try:
        proc = subprocess.run(cmd, cwd=workdir, env=env, capture_output=True, text=True, timeout=TIMEOUT_S)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        shutil.rmtree(config_dir, ignore_errors=True)

    try:
        summary = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(proc.stderr[-4000:], file=sys.stderr)
        raise SystemExit(f"claude exited {proc.returncode} without a JSON result")
    reply = summary.pop("result", "") or ""
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    print(json.dumps({"event": "claude_code_summary", "claude_code": version, "exit": proc.returncode,
                      **summary}, default=str), file=sys.stderr)
    print(reply.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
