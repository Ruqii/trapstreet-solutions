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

**Requires `dsh-minecraft` ≥ 0.12.0.** Earlier versions report neither field,
so a run on this board would be judged malformed.

Difficulty must be `easy` or harder. On `peaceful` nothing hostile spawns and
this board measures nothing — which is the whole reason it exists: the same
setup reached a diamond in 738 seconds on peaceful, and on easy reached an iron
pickaxe and then died four times to skeletons.
