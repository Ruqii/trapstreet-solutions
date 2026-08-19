# minecraft_one_life — dsh-minecraft

The same agent as the [obtain-diamond arm](../minecraft_obtain_diamond), against
the [`one_life`](https://github.com/trapstreet/trapstreet-tasks/tree/main/tasks/minecraft_one_life)
board — where nothing after the first death counts.

The only difference in the runner is one line:

```sh
export MC_ONE_LIFE=1
```

That matters more than it looks. Minecraft does not stop when you die; you
respawn on the spot and can grind to a diamond on your second life, and report a
perfectly true `{"obtained": true}` describing a run nobody had. With the flag
set, the plugin freezes the milestone set at the moment of death, every action
tool then refuses, `mc_observe` keeps working so the agent can see what
happened, and `deaths` / `milestones_at_death` are recorded when it occurs
rather than remembered afterwards.

## Installed from a commit, not a version

```sh
PLUGIN_SPEC="github:Ruqii/dsh-minecraft#a4e0de9…"
```

One-life support landed in `0.12.0`, which is not on npm yet — but a commit is
stronger provenance than a version tag regardless, since a tag can be
republished and a commit cannot. Set `PLUGIN_SPEC=dsh-minecraft@0.12.0` if you
would rather take it from npm once it is there.

Anything older reports neither `deaths` nor `milestones_at_death`, and a run on
this board would be judged malformed.

Verified from a clean profile: the pinned commit installs, registers all twelve
tools, and produces an outcome the task's own judge accepts — `format_ok: true`,
`deaths: 0`, no `milestones_at_death` required when nothing died.

Difficulty must be `easy` or harder. On `peaceful` nothing hostile spawns and
this board measures nothing — which is the whole reason it exists: the same
setup reached a diamond in 738 seconds on peaceful, and on easy reached an iron
pickaxe and then died four times to skeletons.
