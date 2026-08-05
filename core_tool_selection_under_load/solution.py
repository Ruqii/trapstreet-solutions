# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic",
# ]
# ///
"""Reference solution for core_tool_selection_under_load.

Parses the ```json tool catalog fenced in inputs/<id>/prompt.txt and the
"# User request" line, then calls the model with the catalog passed via
Anthropic's native `tools` parameter (tool_choice="any" forces exactly one
call) -- not as text the model has to eyeball and reply to in prose. This
exercises the model's actual tool-selection machinery, which is the thing
this task is trying to measure, rather than its instruction-following on a
"please output JSON" text prompt.

Each variant directory (../claude-sonnet-5, ...) picks the model via CLI
args in its own trap.yaml `cmd:` line.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

FENCE_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)
QUERY_RE = re.compile(r"# User request\s*\n\n(.*?)\n\n# Your task", re.DOTALL)


def parse_prompt(prompt: str) -> tuple[list[dict], str]:
    fence_match = FENCE_RE.search(prompt)
    if not fence_match:
        raise ValueError("no ```json tool catalog fence found in prompt.txt")
    tools_raw = json.loads(fence_match.group(1))

    query_match = QUERY_RE.search(prompt)
    if not query_match:
        raise ValueError("no '# User request' section found in prompt.txt")
    query = query_match.group(1).strip()

    # Anthropic tool schema uses input_schema, not parameters.
    tools = [
        {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
        for t in tools_raw
    ]
    return tools, query


def call_anthropic(model: str, tools: list[dict], query: str) -> dict:
    from anthropic import Anthropic

    client = Anthropic(max_retries=10)
    kwargs = {}
    if any(model.startswith(f"claude-{fam}-5") for fam in ("opus", "sonnet", "fable")):
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": "low"}
        kwargs["max_tokens"] = 4096
    else:
        kwargs["max_tokens"] = 1024

    msg = client.messages.create(
        model=model,
        tools=tools,
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": query}],
        **kwargs,
    )
    tool_uses = [b for b in msg.content if b.type == "tool_use"]
    if not tool_uses:
        print(
            f"[call_anthropic] no tool_use block: stop_reason={msg.stop_reason!r} "
            f"block_types={[b.type for b in msg.content]!r}",
            file=sys.stderr,
        )
        return {}
    first = tool_uses[0]
    return {"name": first.name, "arguments": first.input}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True, choices=["anthropic"])
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])
    prompt = (inputs_dir / "prompt.txt").read_text()

    tools, query = parse_prompt(prompt)
    call = call_anthropic(args.model, tools, query)
    print(json.dumps(call))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
