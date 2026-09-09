# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic",
#     "openai",
# ]
# ///
"""opus-ceiling -- solution for trap-cli.

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

# Set per run, not per arm: every arm in a given comparison uses the same
# value, so a pair never differs by output budget.
MAX_TOKENS = int(os.environ.get("TRAP_MAX_TOKENS", "16000"))


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
    # Streamed, not because we want the tokens as they arrive but because the SDK
    # refuses a non-streaming request whose max_tokens implies more than ten
    # minutes of work. At 16000 that never fired; raising the budget for the open
    # briefs made every Anthropic call fail before it left the machine.
    with client.messages.stream(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": user_message}],
        **kwargs,
    ) as stream:
        msg = stream.get_final_message()
    return next((b.text for b in msg.content if b.type == "text"), "").strip()


# OpenAI-compatible endpoints. Moonshot is called directly rather than through
# OpenRouter because the key is separate and the routed catalogue is not the
# same catalogue — matching the pattern already used in love_or_fifty_million.
OPENAI_COMPATIBLE = {
    # Direct, not routed. OpenRouter's weekly key limit refused a 32000-token
    # request twice in two days, and a route is a variable we are not trying to
    # measure. Note the catalogues differ: OpenRouter lists gpt-5.6-terra-pro,
    # the direct API does not — it has gpt-5.6-terra.
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "moonshot": ("https://api.moonshot.ai/v1", "MOONSHOT_API_KEY"),
}


def call_openai_compatible(provider: str, model: str, system: str | None, user_message: str) -> str:
    from openai import OpenAI

    base_url, key_var = OPENAI_COMPATIBLE[provider]
    client = OpenAI(base_url=base_url, api_key=os.environ[key_var], max_retries=10)
    messages = []
    if system is not None:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_message})
    # OpenAI's own API rejects `max_tokens` for these models and wants
    # `max_completion_tokens`; OpenRouter and Moonshot still take the old name
    # and translate. Same budget either way — only the spelling differs.
    budget = ({"max_completion_tokens": MAX_TOKENS} if provider == "openai"
              else {"max_tokens": MAX_TOKENS})
    resp = client.chat.completions.create(model=model, messages=messages, **budget)
    return (resp.choices[0].message.content or "").strip()


PROVIDERS = {
    "anthropic": lambda m, s, u: call_anthropic(m, s, u),
    "openrouter": lambda m, s, u: call_openai_compatible("openrouter", m, s, u),
    "moonshot": lambda m, s, u: call_openai_compatible("moonshot", m, s, u),
    "openai": lambda m, s, u: call_openai_compatible("openai", m, s, u),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    manifest = json.loads(os.environ["TRAP_MANIFEST"])
    inputs_dir = Path(manifest["inputs_dir"])
    question = (inputs_dir / "brief.md").read_text()

    system, user_message = build_prompt(question)
    answer = PROVIDERS[args.provider](args.model, system, user_message)

    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
