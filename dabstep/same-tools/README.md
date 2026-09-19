# same tools, different loop

Three harnesses on the `dabstep-shared-tools` board, each given the same three
tools and nothing else, so what separates two rows is the harness's loop, its
prompt and how it manages context.

The as-shipped board (`dabstep`) answers "which harness should I use". This one
answers the question that board cannot: with the toolbox held fixed, how much is
left?

| Arm (board name) | Harness | How the shared tools are mounted |
|---|---|---|
| `claude-code-deepseek-flash` (deepseek-flash · claude-code) | Claude Code, headless | MCP (`--mcp-config`, `--strict-mcp-config`), its own tools disallowed |
| `dsh-deepseek-flash` (deepseek-flash · dsh) | DSH 0.1.5-rc.1, headless profile | `dsh-mcp-client`, every tool plugin disabled |
| `pi-deepseek-flash` (deepseek-flash · pi) | Pi 0.85.1, `-p` | a pi extension, `--no-builtin-tools` (Pi has no MCP, by design) |

## The tools

[`tools.py`](tools.py) is the only implementation: `run_python`, `read_file`,
`list_dir`. One file holds the names, the descriptions, the JSON schemas, the
20,000-character truncation and the one shape an error takes (`error: <what>`),
because a result that two harnesses show differently is exactly the variable
this board removes. There is no shell tool: a shell would let each harness's own
environment back in through the side door.

[`mcp_server.py`](mcp_server.py) serves those tools over MCP on stdio for Claude
Code and DSH; [`pi_extension.ts`](pi_extension.ts) registers the same three in
Pi and shells every call back to `tools.py`. Both keep the `mcp__bench__` prefix
that an MCP client imposes on a server's tools, so the three tool lists match
name for name.

## Checking it, before paying for a run

[`probe_tools.py`](probe_tools.py) drives an arm with a fake model API — free,
no key — and prints every tool definition the harness sent:

```bash
python3 probe_tools.py -- python3 ../claude_code.py --model deepseek-flash \
    --key-env DEEPSEEK_API_KEY --all-slots --same-tools
python3 probe_tools.py --url-env DEEPSEEK_BASE_URL -- bash dsh_run.sh
python3 probe_tools.py --url-env DEEPSEEK_BASE_URL -- python3 pi_run.py --model deepseek/deepseek-flash
```

A row is admitted only when that list is the three shared tools and nothing
else. The check is not a formality: Claude Code 2.1.266 also ships Cron*,
Workflow, Skill, SendMessage and a worktree pair, which the first probe found
still on offer; DSH offers `exit_plan_mode` until its plan-mode plugin is
disabled too. Reading the flags would have caught neither.

With `--save FILE` the definitions are written out, and the three files diff
byte for byte: names, descriptions and schemas identical.

## What is still not identical

- **How each harness describes its tools in its own system prompt.** Pi lists
  them under "Available tools"; Claude Code and DSH write their own. That is the
  harness's prompt, which is what this board measures, so it stays.
- **The mounting.** MCP for two, an extension for Pi. The model sees the same
  bytes either way.
- **Everything the board is about**: the loop, the stopping rule, compaction,
  sub-agents (Claude Code and DSH have them; Pi does not).

## Running an arm

```bash
cd dabstep/same-tools/pi-deepseek-flash && tp run --trust-remote --server https://trapstreet.run
```

The jail, the cost proxy, the transcripts and the audit are the parent board's,
unchanged: see [`../README.md`](../README.md).
