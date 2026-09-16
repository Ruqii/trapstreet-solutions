"""Pi, driven over the Agent Client Protocol by `tp shape acp`, as the harness for
the model an arm names.

One script for both pi arms, in two roles:

  solution  (trap.yaml `cmd`, no --agent): prepares the case and runs
            `tp shape acp --agent-id pi-acp`, which starts the agent, picks the
            model and thinking level through ACP, asks the question once,
            grants tool permissions one call at a time, and prints Pi's last
            message. Its stderr (the config the case ran with, Pi's earlier
            messages, every tool call, self-reported usage) is the case's.
  agent     (--agent, the shape's --agent-cmd): starts pi-acp, which starts
            `pi --mode rpc`, inside ../sandbox.py's jail.

Why a solution around the shape rather than the shape as `cmd`:
- The shape refuses a case whose inputs hold a symlink, and every dabstep case
  links its seven files to one shared copy. So the case is copied here first,
  links dereferenced (as every other arm does), and the shape is handed that
  copy. The same copy's question.txt gets the sentence every other arm adds:
  "The files are in the current working directory."
- The shape reports a stopped turn with a non-zero exit (124 at its deadline,
  20-22 for a refusal or a limit, 23 when the agent failed the turn). The site
  records a non-zero exit as SOLVER_ERRORED, which leaves the case pending and
  the run never scored. Those become exit 0 here: an answer the judge can read,
  or a no-reply line. A config error (24) still fails.
- Pi's session file is the transcript audit_transcripts.py reads. It lives in
  the jail's $HOME, outside the shape's work directory (which the shape
  removes), and is copied to the case's outputs_dir afterwards.

The shape's work directory is not a sandbox; the jail is. Its root is a fresh
per-case directory, and the shape's own $TMPDIR is pointed inside it, so the
work directory the shape creates is one the jail can write. Pi reads the case
copy, its pinned install (pi/package-lock.json) and the system trees, writes
only the case root, and connects only to the cost proxy. Its tools are Pi's
defaults (read, write, edit, bash); Pi has no web tools.

Metering: tp points the arm's base URL (ANTHROPIC_BASE_URL or DEEPSEEK_BASE_URL)
at its cost proxy, and Pi's models.json routes the provider there. Only the
arm's own provider is configured and only its key is passed in, so no request
can go out under another model. Commands Pi runs get no API key
(shellCommandPrefix unsets it).
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import sandbox

HERE = Path(__file__).resolve().parent
# Under trap.yaml's 1800 s: tp SIGKILLs a case there, which no cleanup survives.
# DABSTEP_DEADLINE_S is for sandbox_canary.py's timeout check.
TIMEOUT_S = int(os.environ.get("DABSTEP_DEADLINE_S", 1700))
# What the shape needs after its deadline: 10 s for Pi to take the cancel, 2 s
# to stop its process group, and the work directory's removal.
SHAPE_WRAPUP_S = 30
# tp with `tp shape acp` (trapstreet/trap main). DABSTEP_TP overrides it, e.g.
# with a local checkout's `tp`.
TRAP_COMMIT = "c190486850ecdc800e3953eaa37968b5e38e7429"
TP = ("uvx", "--quiet", "--python", "3.13", "--from", f"git+https://github.com/trapstreet/trap@{TRAP_COMMIT}", "tp")
PROMPT_SUFFIX = "\n\nThe files are in the current working directory."
# The reply for a turn the agent failed; like sandbox.NO_REPLY, graded as not
# answered, and deliberately free of "answer:".
AGENT_FAILED = "(no reply: the agent failed the turn)"
DEAD_PROXY = "http://127.0.0.1:9"
# provider -> (base URL variable, key variable)
ROUTES = {"anthropic": ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY"),
          "deepseek": ("DEEPSEEK_BASE_URL", "DEEPSEEK_API_KEY")}
# Credentials and endpoints for any model a harness could reach; the agent gets
# only its own provider's pair back.
VENDOR_PREFIXES = ("ANTHROPIC_", "DEEPSEEK_", "OPENAI_", "MOONSHOT_", "OPENROUTER_", "MISTRAL_",
                   "GEMINI_", "GOOGLE_", "XAI_", "GROQ_", "AWS_", "AZURE_", "KIMI_", "ZAI_")
# DeepSeek's endpoint serves deepseek-flash, the id every other deepseek arm uses
# and the one the price table knows. Pi 0.85.1 lists the same model as
# deepseek-v4-flash; this entry is that one's definition under the served id.
DEEPSEEK_FLASH = {
    "id": "deepseek-flash", "name": "DeepSeek Flash", "api": "openai-completions", "reasoning": True,
    "input": ["text"], "contextWindow": 1000000, "maxTokens": 384000,
    "cost": {"input": 0.14, "output": 0.28, "cacheRead": 0.0028, "cacheWrite": 0},
    "compat": {"supportsStore": False, "supportsDeveloperRole": False, "maxTokensField": "max_tokens",
               "requiresReasoningContentOnAssistantMessages": True, "thinkingFormat": "deepseek"},
    "thinkingLevelMap": {"minimal": None, "low": "low", "medium": None, "high": "high", "max": "max"},
}


def install_pi() -> Path:
    """pi and pi-acp from pi/package-lock.json, installed once per lock under
    $TMPDIR, outside the jail and while the network is open."""
    lock = (HERE / "pi/package-lock.json").read_bytes()
    prefix = Path(tempfile.gettempdir()) / f"dabstep-pi-{hashlib.sha256(lock).hexdigest()[:12]}"
    done = prefix / ".installed"
    if done.exists():
        return Path(os.path.realpath(prefix))
    prefix.mkdir(parents=True, exist_ok=True)
    with open(prefix / ".lock", "w") as held:  # cases may start at once
        fcntl.flock(held, fcntl.LOCK_EX)
        if not done.exists():
            shutil.copy2(HERE / "pi/package.json", prefix)
            shutil.copy2(HERE / "pi/package-lock.json", prefix)
            subprocess.run(["npm", "ci", "--silent", "--no-audit", "--no-fund", "--prefix", str(prefix)],
                           check=True, stdout=sys.stderr)
            done.touch()
    return Path(os.path.realpath(prefix))


def pi_config(home: Path, provider: str, model: str, thinking: str, proxy: str) -> None:
    agent = home / ".pi/agent"
    agent.mkdir(parents=True)
    if provider == "anthropic":
        providers = {"anthropic": {"baseUrl": proxy}}
    else:
        providers = {"deepseek": {"baseUrl": proxy, "apiKey": "$DEEPSEEK_API_KEY", "api": "openai-completions",
                                  "models": [DEEPSEEK_FLASH]}}
    (agent / "models.json").write_text(json.dumps({"providers": providers}, indent=2))
    (agent / "settings.json").write_text(json.dumps({
        "defaultProvider": provider, "defaultModel": model, "defaultThinkingLevel": thinking,
        "quietStartup": True, "enableInstallTelemetry": False, "defaultProjectTrust": "never",
        "shellCommandPrefix": "unset " + " ".join(key for _, key in ROUTES.values()),
    }, indent=2))


def solution(args: argparse.Namespace) -> int:
    started = time.monotonic()
    provider, _, model = args.model.partition("/")
    if provider not in ROUTES or not model:
        raise SystemExit(f"--model must be <provider>/<id> with provider one of {sorted(ROUTES)}")
    base_var, key_var = ROUTES[provider]
    # tp points the base URL at its cost proxy only when the key was already in
    # tp's own environment. Without the proxy the run spends money and records no
    # cost, so refuse before the first request.
    proxy = os.environ.get(base_var, "")
    sandbox.proxy_port(proxy)
    if not os.environ.get(key_var):
        raise SystemExit(f"{key_var} is not set")

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs, outputs = Path(manifest["inputs_dir"]), Path(manifest["outputs_dir"])
    prefix = install_pi()
    root = sandbox.new_case_root("dabstep-pi-")
    case = root / "inputs" / inputs.name
    shutil.copytree(inputs, case)  # follows the symlinks: real copies
    question = case / "question.txt"
    question.write_text(question.read_text().rstrip() + PROMPT_SUFFIX)
    pi_config(root / "home", provider, model, args.thinking, proxy)

    env = dict(os.environ)
    env.update(
        TRAP_MANIFEST=json.dumps({**manifest, "inputs_dir": str(case)}),
        TMPDIR=str(root / "tmp") + "/",  # the shape's work directory, inside the jail's root
        TRAP_PI_ROOT=str(root), TRAP_PI_PREFIX=str(prefix), TRAP_PI_PROVIDER=provider,
    )
    tp = shlex.split(os.environ["DABSTEP_TP"]) if os.environ.get("DABSTEP_TP") else list(TP)
    deadline = max(10.0, TIMEOUT_S - (time.monotonic() - started) - SHAPE_WRAPUP_S)
    cmd = [*tp, "shape", "acp", "--agent-id", "pi-acp",
           "--agent-cmd", shlex.join([sys.executable, str(Path(__file__).resolve()), "--agent"]),
           "--model", args.model, "--option", f"thought_level={args.thinking}",
           "--scrub", str(inputs.parent.parent), "--deadline", f"{deadline:.0f}"]
    print(json.dumps({"event": "start", "shape": cmd[:-2] + ["--deadline", f"{deadline:.0f}"],
                      "pi_lock": prefix.name}), file=sys.stderr, flush=True)
    shape = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, text=True, start_new_session=True)
    signal.signal(signal.SIGTERM, lambda *_: shape.terminate())
    backstop = False
    try:
        # The shape stops itself at its deadline; this is only for a shape that doesn't.
        reply, _ = shape.communicate(timeout=TIMEOUT_S - (time.monotonic() - started) + SHAPE_WRAPUP_S / 2)
        status = shape.returncode
    except subprocess.TimeoutExpired:
        backstop = True
        os.killpg(shape.pid, signal.SIGKILL)
        reply, status = "", 124
    finally:
        keep = outputs / "transcripts"
        sessions = root / "home/.pi/agent/sessions"
        for jsonl in sessions.rglob("*.jsonl") if sessions.is_dir() else ():
            dest = keep / jsonl.relative_to(sessions)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(jsonl, dest)
        shutil.rmtree(root, ignore_errors=True)

    print(json.dumps({"event": "shape_exit", "status": status, "backstop": backstop}), file=sys.stderr)
    reply = (reply or "").strip()
    if status == 124:  # graded as not answered, and the run still finishes; see sandbox.NO_REPLY
        print(json.dumps({"event": "timeout", "after_s": round(time.monotonic() - started)}), file=sys.stderr)
        print(sandbox.NO_REPLY)
        return 0
    if status in (0, 20, 21, 22):  # an answer, a refusal, or a turn cut short: the judge reads what there is
        print(reply)
        return 0
    if status == 23:  # the agent failed the turn (the provider erred, or no model answered): not answered
        print(AGENT_FAILED)
        return 0
    return status  # 24, a config error, and anything else: fail loudly


def agent() -> int:
    """pi-acp in the jail. The shape starts this in its work directory, with the
    case's scrubbed environment, and speaks ACP over its stdio."""
    root = Path(os.environ["TRAP_PI_ROOT"])
    prefix = Path(os.environ["TRAP_PI_PREFIX"])
    base_var, key_var = ROUTES[os.environ["TRAP_PI_PROVIDER"]]
    proxy, key = os.environ[base_var], os.environ[key_var]
    port = sandbox.proxy_port(proxy)
    if root not in Path.cwd().resolve().parents:
        raise SystemExit(f"the shape's work directory {Path.cwd()} is outside the jail's root {root}")

    env = {k: v for k, v in os.environ.items() if not k.startswith(VENDOR_PREFIXES)}
    env = sandbox.jail_env(env, root)
    env.update({key_var: key, base_var: proxy})
    env.update(
        PI_ACP_PI_COMMAND=str(prefix / "node_modules/.bin/pi"),
        PI_OFFLINE="1", PI_TELEMETRY="0", PI_SKIP_VERSION_CHECK="1",
        HTTP_PROXY=DEAD_PROXY, HTTPS_PROXY=DEAD_PROXY, ALL_PROXY=DEAD_PROXY,
        http_proxy=DEAD_PROXY, https_proxy=DEAD_PROXY,
        NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
    )
    cmd = sandbox.wrap([str(prefix / "node_modules/.bin/pi-acp")], root=root, readable=[prefix], port=port)
    sandbox.attest(root=root, readable=[prefix], port=port)
    os.execve(cmd[0], cmd, env)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", help="<provider>/<id>, as pi-acp lists it")
    parser.add_argument("--thinking", default="high", help="pi-acp's thought_level")
    parser.add_argument("--agent", action="store_true", help="the shape's --agent-cmd (internal)")
    args = parser.parse_args()
    if args.agent:
        return agent()
    if not args.model:
        parser.error("--model is required")
    return solution(args)


if __name__ == "__main__":
    raise SystemExit(main())
