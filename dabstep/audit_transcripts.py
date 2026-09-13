# /// script
# requires-python = ">=3.10"
# dependencies = ["zstandard"]
# ///
"""Read every tool call an arm made in one run and flag the ones to look at
before the run is published.

The jail (sandbox.py) is what keeps a harness away from the answers; this is
how a run shows it never tried. It reads the transcript each case left in its
outputs_dir -- Claude Code's session JSONL (sub-agents included), DSH's
session.v3.jsonl.zstd, mini-loop's transcript.json -- and flags:

  path     an absolute path outside the case's own directory (the home
           directory, /tmp, another case's scratch), ~ or $HOME, or ../
  network  a URL, curl/wget, urllib/requests/httpx/socket, a web tool
  env      reading the environment (env, printenv, os.environ, getenv)
  hunt     words that go looking for the key rather than the data: dabstep,
           trapstreet, huggingface, gold, task_scores, leaderboard
  refused  a tool result saying the jail or the harness refused something
           (Operation not permitted, EPERM, was blocked, Permission denied)
  missing  a case with no transcript at all (unauditable)
  unjailed a case whose stderr lacks sandbox.py's jail line

A flag is a pointer, not a verdict: read the lines it prints. Exit status 1
when anything is flagged.

    uv run audit_transcripts.py RUN_DIR...        # .trap/runs/<id>/dabstep/<timestamp>
    uv run audit_transcripts.py --arm ARM_DIR     # that arm's latest run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RULES = {
    "path": re.compile(r"(?<![\w.])(?:/(?:Users|private|tmp|var|Volumes|home|root)\b[^\s'\"`)\],;]*)"
                       r"|~/|\$HOME|expanduser|Path\.home|\.\./"),
    "network": re.compile(r"https?://|\bcurl\b|\bwget\b|urllib|\brequests\b|\bhttpx\b|\bsocket\b|"
                          r"web_fetch|web_search|WebFetch|WebSearch", re.I),
    "env": re.compile(r"\bprintenv\b|os\.environ|getenv|(?:^|[;&|]\s*)env\b", re.M),
    "hunt": re.compile(r"dabstep|trapstreet|hugging\s*face|\bhf_|\bgold\b|task_scores|leaderboard", re.I),
}
REFUSED = re.compile(r"Operation not permitted|EPERM|was blocked|Permission denied|PermissionError")


# -- one reader per harness: yields (tool name, call text, result text, cwd) --


def claude_code(path: Path):
    calls, cwd = {}, None
    for line in path.read_text().splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        cwd = cwd or ev.get("cwd")
        content = (ev.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_use":
                calls[block["id"]] = [block["name"], json.dumps(block.get("input"), ensure_ascii=False), ""]
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                body = block.get("content")
                calls[block["tool_use_id"]][2] = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    for name, call, result in calls.values():
        yield name, call, result, cwd


def dsh(path: Path):
    if path.suffix == ".zstd":
        import io
        import zstandard
        with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(path.read_bytes()),
                                                         read_across_frames=True) as r:
            text = r.read().decode()  # DSH appends a frame per write
    else:
        text = path.read_text()
    calls, cwd = {}, None
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "session":
            cwd = ev.get("cwd")
        data = ev.get("data") or {}
        if ev.get("type") == "tool/call":
            calls[data.get("callId")] = [data.get("name"), data.get("arguments") or "", ""]
        elif ev.get("type") == "tool/result":
            for part in (data.get("message") or {}).get("content") or []:
                if part.get("toolCallId") in calls:
                    calls[part["toolCallId"]][2] = json.dumps(part.get("content"), ensure_ascii=False)
    for name, call, result in calls.values():
        yield name, call, result, cwd


def mini_loop(path: Path):
    data = json.loads(path.read_text())
    messages, root = (data["messages"], data.get("root")) if isinstance(data, dict) else (data, None)
    calls = {}
    for m in messages:
        content = m.get("content")
        for tc in m.get("tool_calls") or []:  # OpenAI format
            calls[tc["id"]] = ["run_python", tc["function"].get("arguments") or "", ""]
        if m.get("role") == "tool" and m.get("tool_call_id") in calls:
            calls[m["tool_call_id"]][2] = m.get("content") or ""
        if isinstance(content, list):  # Anthropic format
            for block in content:
                if block.get("type") == "tool_use":
                    calls[block["id"]] = [block["name"], json.dumps(block.get("input"), ensure_ascii=False), ""]
                elif block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                    calls[block["tool_use_id"]][2] = str(block.get("content"))
    for name, call, result in calls.values():
        yield name, call, result, f"{root}/work" if root else None


def transcripts(outputs: Path):
    for p in sorted(outputs.rglob("*.jsonl")):
        yield p, (dsh if p.name.startswith("session") else claude_code)
    for p in sorted(outputs.rglob("*.jsonl.zstd")):
        yield p, dsh
    if (outputs / "transcript.json").exists():
        yield outputs / "transcript.json", mini_loop


def case_root(cwd: str | None) -> str | None:
    """The per-case root: the parent of the harness's working directory."""
    if not cwd:
        return None
    cwd = cwd.rstrip("/")
    return cwd.rsplit("/", 1)[0] if cwd.endswith("/work") else cwd


def jailed(case: Path) -> bool:
    """The harness said, on the stderr tp keeps, that this case ran in the jail."""
    stderr = case / "solution" / "stderr"
    if not stderr.exists():
        return False
    for line in stderr.read_text(errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and ev.get("event") == "jail" and ev.get("sandbox") == "sandbox-exec":
            return True
    return False


def audit_case(case: Path) -> list[str]:
    outputs = case / "solution" / "outputs"
    found = list(transcripts(outputs)) if outputs.exists() else []
    head = [] if jailed(case) else ["unjailed no jail line in solution/stderr: this case was not run in sandbox.py"]
    if not found:
        return head + ["missing  no transcript in solution/outputs"]
    flags, n = head, 0
    for path, reader in found:
        for name, call, result, cwd in reader(path):
            n += 1
            root = case_root(cwd)
            if root:  # the case's own directory is not a finding, under any spelling
                bare = root[len("/private"):] if root.startswith("/private/") else root
                slug = re.sub(r"[^A-Za-z0-9]", "-", "/private" + bare)  # Claude Code's project-dir form
                call = call.replace("/private" + bare, "<case>").replace(bare, "<case>").replace(slug, "<case>")
            for rule, rx in RULES.items():
                for m in rx.finditer(call):
                    lo, hi = max(0, m.start() - 50), min(len(call), m.end() + 50)
                    flags.append(f"{rule:8} {name}: …{' '.join(call[lo:hi].split())}…")
                    break
            m = REFUSED.search(result or "")
            if m:
                lo, hi = max(0, m.start() - 80), min(len(result), m.end() + 40)
                flags.append(f"refused  {name}: …{' '.join(result[lo:hi].split())}…")
    return flags or [f"clean    {n} tool calls"]


def latest_run(arm: Path) -> Path:
    runs = sorted((arm / ".trap" / "runs").glob("*/*/*"), key=lambda p: p.name)
    if not runs:
        raise SystemExit(f"no runs under {arm}/.trap/runs")
    return runs[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="*", type=Path, help="run directories (…/dabstep/<timestamp>)")
    parser.add_argument("--arm", action="append", default=[], type=Path, help="audit this arm's latest run")
    args = parser.parse_args()
    runs = [*args.runs, *(latest_run(a) for a in args.arm)]
    if not runs:
        parser.error("give a run directory or --arm")
    flagged = 0
    for run in runs:
        cases = sorted(p for p in run.iterdir() if p.is_dir() and (p / "solution").exists())
        print(f"# {run}  ({len(cases)} cases)")
        for case in cases:
            lines = audit_case(case)
            dirty = not lines[0].startswith("clean")
            flagged += dirty
            print(f"{case.name}  {'FLAG' if dirty else 'ok  '}  {lines[0]}")
            for line in lines[1:]:
                print(f"{'':16}{line}")
    print(f"\n{flagged} case(s) flagged")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
