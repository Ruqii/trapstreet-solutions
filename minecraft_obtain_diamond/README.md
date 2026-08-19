# minecraft_obtain_diamond — dsh-minecraft

A wrapper. The agent is DeepSeek Harness driving a Mineflayer bot through the
[`dsh-minecraft`](https://www.npmjs.com/package/dsh-minecraft) plugin. No
planning code lives here: `run.sh` installs a pinned plugin version, gives the
agent one sentence, and prints what happened.

The plugin exposes game actions and nothing above them — it will not place a
crafting table for the agent, gather a missing ingredient, or encode the recipe
chain. Working out that wood becomes planks becomes a pickaxe, that stone needs
one, and where diamonds are, is the agent's problem, which is the only reason a
score here means anything.

```
DEEPSEEK_API_KEY=sk-...  tp run
```

You provide a **Minecraft Java 1.20.4** server on `127.0.0.1:25565`, offline
mode, survival — the task asks each entrant to stand up their own. Plus
`ffmpeg`, and Chrome if you want the run filmed.

| Variable | Default |
|---|---|
| `MC_HOST` / `MC_PORT` | `127.0.0.1` / `25565` |
| `PLUGIN_VERSION` | `0.9.1` — pinned on purpose |
| `PLAY_SECONDS` | `1800`, the game's own ceiling inside trap's `timeout` |
| `MC_SEED` | `diamondrun`, copied into the outcome |

## Two things learned the expensive way

**Pin the plugin.** `source_url` on a leaderboard entry points at a commit of
this repo, but the thing that actually plays is downloaded at run time. Left on
`latest`, the entry slowly stops describing the run it came from.

**Bound the game inside the script.** The first real `tp run` came back
`exit_code: 124`, `reason: "empty stdout"`, score 0.0 — trap's outer timeout
killed the whole thing mid-game, so the frames were never muxed and the outcome
was never printed. A run that played for forty minutes scored zero for having
said nothing. `PLAY_SECONDS` is why that does not happen again.

## It really plays

`run.sh` plays a fresh run every time rather than replaying a stored result.
Printing a recorded `outcome.json` would be cheaper and would also be a lie: the
platform re-runs a solution to measure reproducibility, and a static file makes
that machinery measure nothing.
