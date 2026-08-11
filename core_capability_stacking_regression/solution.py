# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic",
#     "openai",
# ]
# ///
"""core_capability_stacking_regression -- solution for trap-cli.

Shared across every model/provider variant in this repo: each variant's
trap.yaml picks the provider and model via CLI arguments baked directly
into its cmd: line (never an env var -- see
../references/trap-yaml-schema.md in the trapstreet-solution-scaffold
skill for why that matters), e.g.
``uv run ../solution.py --provider anthropic --model claude-opus-4-8``.

Customize build_prompt() below for your solution's actual logic (e.g.
loading a SKILL.md + reference files as the system prompt). The default
is a bare relay: no system prompt, question.txt sent verbatim.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def build_prompt(question: str) -> tuple[str | None, str]:
    """Return (system_prompt_or_None, user_message).

    Customize this for your solution's real logic -- e.g. read a SKILL.md
    and reference files next to this script and return them as the system
    prompt. Left as a bare relay by default: no system prompt at all.
    """
    return None, question


def call_anthropic(model: str, system: str | None, user_message: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(max_retries=10)
    kwargs = {}
    if system is not None:
        kwargs["system"] = system
    msg = client.messages.create(
        model=model,
        # 1024 is enough for the JSON array these cases ask for, but a model
        # that preambles before the array can run past it and get truncated
        # mid-JSON -- which the judge scores `unparseable`, a harness artifact
        # rather than a selection failure. 4096 is what the matrix runs used.
        max_tokens=4096,
        messages=[{"role": "user", "content": user_message}],
        **kwargs,
    )
    return next((b.text for b in msg.content if b.type == "text"), "").strip()


def call_openrouter(model: str, system: str | None, user_message: str) -> str:
    from openai import OpenAI

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
    messages = []
    if system is not None:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_message})
    resp = client.chat.completions.create(model=model, max_tokens=1024, messages=messages)
    return (resp.choices[0].message.content or "").strip()


PROVIDERS = {
    "anthropic": call_anthropic,
    "openrouter": call_openrouter,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])
    # This task names its input prompt.txt, not question.txt. It is
    # self-contained -- skill catalog, request and output instruction all in
    # one file -- so a bare relay is the whole solution.
    question = (inputs_dir / "prompt.txt").read_text()

    system, user_message = build_prompt(question)
    answer = PROVIDERS[args.provider](args.model, system, user_message)

    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
