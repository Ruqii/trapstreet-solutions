# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic",
#     "openai",
# ]
# ///
"""Reference solution for core_tool_selection_at_scale.

Parses the ```json tool catalog fenced in inputs/<id>/prompt.txt and the
"# User request" line, then hands the catalog to the model through its
provider's NATIVE tool-calling parameter -- not as text the model has to
eyeball and answer in prose. That is what real agent frameworks do, and it is
the path this task is trying to measure.

Providers:
  anthropic  -- tools=[...] with tool_choice={"type": "any"}
  openrouter -- OpenAI-compatible tools=[...] with tool_choice="required"

Each variant directory picks provider/model/effort via CLI args in its own
trap.yaml `cmd:` line.

A failure to emit any tool call is reported as an empty object, which the
judge scores 0.0 with failure_mode "unparseable". That is deliberate: for a
model that cannot reliably emit tool calls at all, refusing to fall back to
prose-parsing keeps the variant's numbers honest rather than quietly
measuring something else.
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
    fence = FENCE_RE.search(prompt)
    if not fence:
        raise ValueError("no ```json tool catalog fence found in prompt.txt")
    tools_raw = json.loads(fence.group(1))

    query = QUERY_RE.search(prompt)
    if not query:
        raise ValueError("no '# User request' section found in prompt.txt")

    return tools_raw, query.group(1).strip()


def call_anthropic(model: str, effort: str, tools_raw: list[dict], query: str) -> dict:
    from anthropic import Anthropic

    client = Anthropic(max_retries=10)
    # Anthropic's tool schema calls it input_schema, not parameters.
    tools = [
        {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
        for t in tools_raw
    ]

    kwargs: dict = {}
    if any(model.startswith(f"claude-{fam}-5") for fam in ("opus", "sonnet", "fable")):
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": effort}
        kwargs["max_tokens"] = 8192
    else:
        kwargs["max_tokens"] = 2048

    msg = client.messages.create(
        model=model,
        tools=tools,
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": query}],
        **kwargs,
    )
    uses = [b for b in msg.content if b.type == "tool_use"]
    if not uses:
        print(f"[anthropic] no tool_use block: stop_reason={msg.stop_reason!r} "
              f"blocks={[b.type for b in msg.content]!r}", file=sys.stderr)
        return {}
    return {"name": uses[0].name, "arguments": uses[0].input}


def call_openrouter(model: str, tools_raw: list[dict], query: str) -> dict:
    from openai import OpenAI

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        max_retries=5,
    )
    tools = [
        {"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["parameters"],
        }}
        for t in tools_raw
    ]

    def request(tool_choice: str):
        return client.chat.completions.create(
            model=model,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=2048,
            messages=[{"role": "user", "content": query}],
        )

    # Not every small open-weight model's provider honours "required"; fall
    # back to "auto" rather than scoring a provider limitation as a wrong pick.
    try:
        resp = request("required")
    except Exception as exc:  # noqa: BLE001 -- provider errors vary widely
        print(f"[openrouter] tool_choice=required failed ({exc}); retrying with auto", file=sys.stderr)
        resp = request("auto")

    # OpenRouter signals upstream provider failures with a 200 carrying an
    # `error` object and choices=None, rather than raising. Left unhandled
    # that crashes with a bare TypeError; surfaced here it is diagnosable as
    # the provider outage it is, instead of looking like a model that cannot
    # select tools.
    if not getattr(resp, "choices", None):
        err = getattr(resp, "error", None) or getattr(resp, "model_extra", {}).get("error")
        raise RuntimeError(f"provider returned no choices: {err}")

    choice = resp.choices[0]
    calls = getattr(choice.message, "tool_calls", None)
    if not calls:
        print(f"[openrouter] no tool_calls: finish_reason={choice.finish_reason!r} "
              f"content={(choice.message.content or '')[:200]!r}", file=sys.stderr)
        return {}

    fn = calls[0].function
    try:
        arguments = json.loads(fn.arguments) if isinstance(fn.arguments, str) else fn.arguments
    except (json.JSONDecodeError, TypeError):
        print(f"[openrouter] tool_call arguments were not valid JSON: {fn.arguments!r}", file=sys.stderr)
        arguments = {}
    return {"name": fn.name, "arguments": arguments}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True, choices=["anthropic", "openrouter"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", default="low", choices=["low", "medium", "high"],
                        help="Anthropic output_config effort; ignored by other providers.")
    args = parser.parse_args()

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    prompt = (Path(manifest["inputs_dir"]) / "prompt.txt").read_text()
    tools_raw, query = parse_prompt(prompt)

    if args.provider == "anthropic":
        call = call_anthropic(args.model, args.effort, tools_raw, query)
    else:
        call = call_openrouter(args.model, tools_raw, query)

    print(json.dumps(call))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
