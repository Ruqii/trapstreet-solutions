"""What a harness actually shows the model, captured from its own requests.

The same-tools board claims that every row was given the same tools. The claim
is only worth what it can be checked against, so this drives a harness with a
fake model API, keeps the requests, and prints:

  - every tool definition the harness sent (name, description, schema), which is
    what the model saw -- the thing to diff between harnesses;
  - whether a call to one of the shared tools came back with our text;
  - anything the harness added of its own.

Nothing here calls a real API, so it is free and needs no key.

    python3 probe_tools.py --case DIR -- <the arm's command>
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sandbox_canary import Fake  # noqa: E402  (the fake Anthropic/OpenAI model server)

HOME = Path.home()
DEFAULT_CASE = HOME / "Documents/Projects/trapstreet-tasks/tasks/dabstep/inputs/case_001"


def tool_definitions(bodies: list[str]) -> list[dict]:
    """The tools array of the first request that carried one."""
    for raw in bodies:
        body = json.loads(raw)
        tools = body.get("tools")
        if tools:
            return tools
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, default=DEFAULT_CASE)
    parser.add_argument("--key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--url-env", default="ANTHROPIC_BASE_URL")
    parser.add_argument("--call", default="list_dir", help="the shared tool to make one call to")
    parser.add_argument("--save", type=Path, help="write the tool definitions here, as JSON")
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        parser.error("give the arm's command after --")

    outputs = Path(tempfile.mkdtemp(prefix="dabstep-probe-out-"))
    fake = Fake([])
    # One call to a shared tool, under both spellings a harness may use for it.
    fake.steps = [(args.call, {}), (f"mcp__bench__{args.call}", {})]
    env = {k: v for k, v in os.environ.items()
           if not k.endswith(("_API_KEY", "_AUTH_TOKEN", "_BASE_URL")) and not k.startswith(("CLAUDE", "TRAP"))}
    env.update({args.url_env: f"http://127.0.0.1:{fake.port}", args.key_env: "sk-probe",
                "TRAP_MANIFEST": json.dumps({"inputs_dir": str(args.case), "outputs_dir": str(outputs)})})
    proc = subprocess.run(cmd, cwd=Path(cmd[0]).resolve().parent if Path(cmd[0]).exists() else None,
                          env=env, capture_output=True, text=True, timeout=900)
    fake.server.shutdown()

    tools = tool_definitions(fake.bodies)
    print(f"exit {proc.returncode}, {len(fake.bodies)} request(s), {len(tools)} tool(s) offered to the model\n")
    for tool in tools:
        # Anthropic sends {name, description, input_schema}; OpenAI wraps the same
        # three in {"type": "function", "function": {...}}, and a harness's format
        # is its vendor's, not a difference this board is about.
        tool = tool.get("function", tool)
        name = tool.get("name")
        schema = tool.get("input_schema") or tool.get("parameters") or {}
        print(f"  {name}\n    description: {' '.join(str(tool.get('description', '')).split())[:110]}"
              f"\n    schema: {json.dumps(schema, sort_keys=True)[:200]}")
    named = [t.get("function", t) for t in tools]
    shared = [t for t in named if str(t.get("name", "")).endswith(("run_python", "read_file", "list_dir"))]
    others = [t.get("name") for t in named if t not in shared]
    print(f"\n  shared tools offered: {[t.get('name') for t in shared]}")
    print(f"  anything else offered: {others or 'none'}")

    for index, (step_name, _) in enumerate(fake.steps):
        got = fake.results.get(index)
        if got:
            is_error, text = got
            print(f"  call {step_name}: {'error ' if is_error else ''}{' '.join(text.split())[:120]!r}")
    if args.save:
        args.save.write_text(json.dumps(tools, indent=2, sort_keys=True))
        print(f"\n  tool definitions written to {args.save}")
    if proc.returncode != 0:
        print("\nstderr tail:\n" + proc.stderr[-1200:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
