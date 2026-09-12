# /// script
# requires-python = ">=3.10"
# dependencies = ["anthropic>=0.60", "openai>=1.60"]
# ///
"""mini-loop: the simple harness shared by every mini-loop arm on dabstep.

One tool (run a Python snippet in the case directory, get stdout/stderr back),
at most MAX_ROUNDS rounds of it, then one last request with tools switched off
if the model is still asking for code. No planning prompt, no sub-agents, no
context management, no retries on a wrong answer. This is the shape of DABStep's
own ReAct baseline.

Every mini-loop arm runs these exact bytes; an arm is only a --api/--model
pair in its trap.yaml, so a score difference between two such arms is the
model's, not the harness's.

- Thinking is left at each vendor's default (Opus 5: adaptive; DeepSeek:
  enabled, effort high), matching what Claude Code and DSH send.
- Prompt caching is each vendor's standard mechanism: DeepSeek caches on its
  own; for Claude the loop turns on automatic caching (one top-level
  cache_control), so both arms resend their growing transcript at cache rates
  and their cost difference is the model's, like their score difference.
- Refusals are an outcome of their own. No server-side fallback is enabled,
  because a fallback answers with a different model and the arm would no
  longer be the model it names. A refusal is logged to stderr with its
  category and the case ends with no ANSWER line.
- The snippets run with the same `python3` Claude Code and DSH would find on
  PATH, in ../sandbox.py's jail: they read the case copy and the system trees,
  write only the case root, open no network connection at all, and get no API
  keys in their environment.
- The whole conversation (every snippet and what it printed) is kept in the
  case's outputs_dir as transcript.json, for auditing before a run is
  published.

stdout carries only the model's final reply; everything else goes to stderr.
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

MAX_ROUNDS = 10
CODE_TIMEOUT_S = 120
OUTPUT_CAP = 10_000  # characters of stdout+stderr returned per snippet
MAX_TOKENS = 32_000
DEAD_PROXY = "http://127.0.0.1:9"

SYSTEM = (
    "You answer questions about data files by running Python. The files named in "
    "the question are in the current working directory. You have one tool, "
    f"run_python, which runs a Python snippet there and returns what it prints; "
    f"you can call it at most {MAX_ROUNDS} times. There is no network access."
)
TOOL_NAME = "run_python"
TOOL_DESCRIPTION = (
    "Run a self-contained Python 3 snippet in the directory holding the data files "
    "and return its stdout and stderr. pandas and numpy are installed. State is "
    "not kept between calls, so each snippet must load what it needs."
)
TOOL_SCHEMA = {
    "type": "object",
    "properties": {"code": {"type": "string", "description": "The Python source to run."}},
    "required": ["code"],
}
LAST_CALL = (
    f"You have used all {MAX_ROUNDS} runs of run_python. Give your final answer now, "
    "from what you have seen, ending with the ANSWER line."
)


def log(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, default=str), file=sys.stderr, flush=True)


# -- the tool ------------------------------------------------------------------


def analysis_python() -> str:
    """The python3 on PATH once uv's own environment is taken off it, i.e. the one
    Claude Code's and DSH's shells resolve."""
    own = Path(sys.prefix).resolve()
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep)
            if d and not Path(d).resolve().is_relative_to(own)]
    found = shutil.which("python3", path=os.pathsep.join(dirs))
    if not found:
        raise SystemExit("no python3 on PATH outside uv's environment")
    return found


def sandbox_env() -> dict[str, str]:
    secret = ("_API_KEY", "_AUTH_TOKEN", "_BASE_URL", "_API_BASE")
    env = {k: v for k, v in os.environ.items()
           if not k.endswith(secret) and not k.startswith(("TRAP", "VIRTUAL_ENV", "UV_"))}
    env.update(HTTP_PROXY=DEAD_PROXY, HTTPS_PROXY=DEAD_PROXY, ALL_PROXY=DEAD_PROXY,
               http_proxy=DEAD_PROXY, https_proxy=DEAD_PROXY, NO_PROXY="", no_proxy="")
    return env


def interpreter_roots(python: str) -> list[Path]:
    """Where the snippet interpreter is installed (bin/ up one, the root up two),
    for the symlink and its target alike, so the jail can read it wherever it is."""
    return sorted({Path(p).parent.parent for p in (python, os.path.realpath(python))})


def jailed(cmd: list[str], root: Path, python: str) -> list[str]:
    return sandbox.wrap(cmd, root=root, readable=interpreter_roots(python), port=None)


def run_python(code: str, root: Path, python: str, env: dict[str, str], n: int) -> str:
    workdir = root / "work"
    script = workdir / f".run_{n:02d}.py"
    script.write_text(code)
    try:
        proc = subprocess.run(jailed([python, script.name], root, python), cwd=workdir, env=env,
                              capture_output=True, text=True, timeout=CODE_TIMEOUT_S)
        out = proc.stdout + (f"\n[stderr]\n{proc.stderr}" if proc.stderr else "")
        if proc.returncode:
            out += f"\n[exit code {proc.returncode}]"
    except subprocess.TimeoutExpired:
        out = f"[timed out after {CODE_TIMEOUT_S}s]"
    if len(out) > OUTPUT_CAP:
        head, tail = out[: OUTPUT_CAP * 4 // 5], out[-OUTPUT_CAP // 5:]
        out = f"{head}\n[... {len(out) - len(head) - len(tail)} characters cut ...]\n{tail}"
    return out or "[no output]"


# -- one adapter per API format -----------------------------------------------


class Anthropic:
    """Claude through the Anthropic SDK (ANTHROPIC_BASE_URL is the tp cost proxy)."""

    def __init__(self, model: str) -> None:
        import anthropic

        self.model = model
        self.client = anthropic.Anthropic(max_retries=4)
        self.tools = [{"name": TOOL_NAME, "description": TOOL_DESCRIPTION, "input_schema": TOOL_SCHEMA}]

    def start(self, question: str) -> list:
        return [{"role": "user", "content": question}]

    def ask(self, messages: list, tools_on: bool):
        with self.client.messages.stream(
            model=self.model, max_tokens=MAX_TOKENS, system=SYSTEM, tools=self.tools,
            tool_choice={"type": "auto" if tools_on else "none"}, messages=messages,
            cache_control={"type": "ephemeral"},  # automatic caching of the resent transcript
        ) as stream:
            response = stream.get_final_message()
        messages.append({"role": "assistant", "content": response.content})  # thinking blocks included
        calls = [(b.id, b.input.get("code", "")) for b in response.content if b.type == "tool_use"]
        text = "\n".join(b.text for b in response.content if b.type == "text")
        refusal = None
        if response.stop_reason == "refusal":
            refusal = getattr(response.stop_details, "category", None) or "unspecified"
        usage = response.usage
        return calls, text, response.stop_reason, refusal, {
            "input": usage.input_tokens, "output": usage.output_tokens,
            "cache_read": usage.cache_read_input_tokens, "cache_write": usage.cache_creation_input_tokens,
        }

    def answer_tools(self, messages: list, results: list[tuple[str, str]], note: str | None) -> None:
        content = [{"type": "tool_result", "tool_use_id": i, "content": r} for i, r in results]
        if note:
            content.append({"type": "text", "text": note})
        messages.append({"role": "user", "content": content})


class DeepSeek:
    """DeepSeek through its OpenAI-format endpoint (DEEPSEEK_BASE_URL is the tp cost
    proxy). Its reasoning_content is passed back on every later request, which
    DeepSeek requires whenever tools are present."""

    def __init__(self, model: str) -> None:
        from openai import OpenAI

        self.model = model
        self.client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                             base_url=os.environ["DEEPSEEK_BASE_URL"], max_retries=4, timeout=900)
        self.tools = [{"type": "function", "function": {
            "name": TOOL_NAME, "description": TOOL_DESCRIPTION, "parameters": TOOL_SCHEMA}}]

    def start(self, question: str) -> list:
        return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]

    def ask(self, messages: list, tools_on: bool):
        response = self.client.chat.completions.create(
            model=self.model, max_tokens=MAX_TOKENS, messages=messages, tools=self.tools,
            tool_choice="auto" if tools_on else "none",
        )
        choice = response.choices[0]
        reply = {"role": "assistant", "content": choice.message.content}
        reasoning = getattr(choice.message, "reasoning_content", None)
        if reasoning is not None:
            reply["reasoning_content"] = reasoning
        if choice.message.tool_calls:
            reply["tool_calls"] = [tc.model_dump() for tc in choice.message.tool_calls]
        messages.append(reply)
        calls = []
        for tc in choice.message.tool_calls or []:
            try:
                code = json.loads(tc.function.arguments or "{}").get("code", "")
            except json.JSONDecodeError:
                code = ""
            calls.append((tc.id, code))
        usage = response.usage.model_dump() if response.usage else {}
        return calls, choice.message.content or "", choice.finish_reason, None, {
            "input": usage.get("prompt_tokens"), "output": usage.get("completion_tokens"),
            "cache_read": usage.get("prompt_cache_hit_tokens"),
        }

    def answer_tools(self, messages: list, results: list[tuple[str, str]], note: str | None) -> None:
        messages.extend({"role": "tool", "tool_call_id": i, "content": r} for i, r in results)
        if note:
            messages.append({"role": "user", "content": note})


# -- guards: refuse to spend money on a run the cost proxy cannot see ----------


def check_metering(api: str, model: str) -> None:
    def proxied(var: str) -> bool:
        return os.environ.get(var, "").startswith(("http://127.0.0.1:", "http://localhost:"))

    if api == "anthropic":
        if not model.startswith("claude-"):
            raise SystemExit(f"--api anthropic expects a Claude model, got {model!r}")
        if not proxied("ANTHROPIC_BASE_URL"):
            raise SystemExit("ANTHROPIC_BASE_URL is not the tp cost proxy; run this under `tp run`")
        if not os.environ.get("ANTHROPIC_API_KEY", "").startswith("sk-ant-"):
            raise SystemExit("ANTHROPIC_API_KEY is not an Anthropic key")
    else:
        if not model.startswith("deepseek-"):
            raise SystemExit(f"--api deepseek expects a DeepSeek model, got {model!r}")
        if not proxied("DEEPSEEK_BASE_URL"):
            raise SystemExit("DEEPSEEK_BASE_URL is not the tp cost proxy; export "
                             "DEEPSEEK_API_KEY in the shell that runs `tp run`")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", choices=["anthropic", "deepseek"], required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    check_metering(args.api, args.model)

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs, outputs = Path(manifest["inputs_dir"]), Path(manifest["outputs_dir"])
    question = (inputs / "question.txt").read_text()
    root = sandbox.new_case_root("dabstep-loop-")
    shutil.copytree(inputs, root / "work", dirs_exist_ok=True)  # follows the symlinks: real copies
    python = analysis_python()
    env = sandbox.jail_env(sandbox_env(), root)
    versions = subprocess.run(jailed([python, "-c", "import sys,pandas,numpy;print(sys.version.split()[0],"
                                      "'pandas',pandas.__version__,'numpy',numpy.__version__)"], root, python),
                              cwd=root / "work", env=env, capture_output=True, text=True)
    if versions.returncode:
        raise SystemExit(f"python3 does not start in the jail: {versions.stderr[-2000:]}")
    log("start", api=args.api, model=args.model, python=python, versions=versions.stdout.strip(),
        root=str(root))

    llm = Anthropic(args.model) if args.api == "anthropic" else DeepSeek(args.model)
    messages = llm.start(question)
    rounds, text, stop, refusal, forced = 0, "", None, None, False
    try:
        while True:
            calls, text, stop, refusal, usage = llm.ask(messages, tools_on=not forced)
            log("reply", round=rounds, stop=stop, tool_calls=len(calls), usage=usage)
            if refusal or not calls or forced:
                break
            results = []
            for call_id, code in calls:
                if rounds < MAX_ROUNDS:
                    rounds += 1
                    results.append((call_id, run_python(code, root, python, env, rounds)))
                else:
                    results.append((call_id, "[not run: no runs left]"))
            forced = rounds >= MAX_ROUNDS
            llm.answer_tools(messages, results, LAST_CALL if forced else None)
    finally:
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "transcript.json").write_text(json.dumps(
            messages, indent=1, default=lambda o: o.model_dump() if hasattr(o, "model_dump") else str(o)))
        shutil.rmtree(root, ignore_errors=True)

    if refusal:
        log("refusal", category=refusal)
    log("done", rounds=rounds, forced_final=forced, stop=stop, refusal=refusal)
    print(text.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
