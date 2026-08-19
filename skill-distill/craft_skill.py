# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "anthropic",
# ]
# ///
"""
One-time authoring step. Run manually, not part of any benchmark run:

    python3 craft_skill.py > skill.txt

Calls a strong model once to write a reusable, general-purpose code-review
checklist. The checklist is checked into the repo as skill.txt and every
runtime call (solution.py) reuses that static file -- no strong-model calls
happen during scored runs. See README.md for why this split exists.
"""

import anthropic

AUTHOR_MODEL = "claude-opus-4-8"

AUTHOR_PROMPT = """You are writing a reusable system prompt (a "skill") for a much \
smaller, faster model whose job is: look at one source file (shown with real line \
numbers) and find the single most significant real bug in it, in this exact output \
shape:

{"findings": [{"file": "<file path>", "line": <line number>, "description": "<1-2 \
sentence description>"}, ...]}

The smaller model will see files pulled from many different real open-source \
repositories, in many languages and domains, each frozen right before a real \
historical bug was fixed. You do not know in advance which bug category any given \
file contains.

Write a checklist-style system prompt that:
- Teaches a systematic scan order for spotting real bugs in unfamiliar code, not \
just the "famous" textbook gotchas (only look for those alongside everything else, \
never instead of).
- Explicitly covers a wide spread of bug categories a competent reviewer checks, \
e.g.: off-by-one / boundary errors, null/None dereference, logic inversions, race \
conditions and other concurrency bugs, resource leaks, missing authorization/permission \
checks, mutable default arguments, overly broad exception handling that swallows \
real errors, cache/state invalidation bugs, numeric precision or truncation/rounding \
order bugs -- and leaves room for categories not on this list.
- Tells the model to reason about what the surrounding code is trying to accomplish \
before flagging something, so it reports the bug that actually breaks that intent \
rather than a stylistic nitpick.
- Reinforces the required output format (valid JSON only, ordered most-confident-first, \
at most a handful of findings) and that being right about one real bug beats listing \
many speculative ones.

Output ONLY the system prompt text itself -- no preamble, no markdown fences, no \
meta-commentary about what you wrote."""


def main():
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=AUTHOR_MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": AUTHOR_PROMPT}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    print(text.strip())


if __name__ == "__main__":
    main()
