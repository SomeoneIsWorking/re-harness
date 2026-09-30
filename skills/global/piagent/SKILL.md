---
name: piagent
description: >-
  Run and steer long-running Space Bunny (pi) agents as sessions of the one shared PiNest host
  process: spawn a named agent in a directory with a brief, ask what it is doing, steer it mid-run,
  queue a follow-up, wait for it, and stop it. Use for open-ended investigations or implementations
  you want to watch and redirect — not when a scripted gate can judge the result (use swarm).
---

# Steer pi agents on the shared PiNest host

Every agent is a session `agent:<NAME>` inside ONE pi process (the PiNest host, systemd user unit
`pinest-host`), so ten agents cost one process instead of ten. They also appear in the user's PiNest
app. `pinest-agent` is on PATH:

```sh
pinest-agent spawn NAME --cwd WORKTREE --model opencode/space-bunny-free --brief brief.md
pinest-agent status            # every agent: idle/working, model, queued messages, cwd
pinest-agent status NAME       # plus its last tool calls and last reply
pinest-agent send NAME "…"     # steers a working agent, prompts an idle one; --follow-up queues
pinest-agent tail NAME -n 20   # recent transcript
pinest-agent wait NAME --timeout 1800   # exit 0 idle (prints last reply), 2 timeout
pinest-agent cancel NAME       # abort the current turn, keep the session
pinest-agent stop NAME         # cancel and close the session
```

If `spawn` reports no host, start it (it restores sessions and serves the agent socket):
`systemctl --user start pinest-host` if the unit exists, else the `systemd-run` command in the
PiNest README ("Local agents").

Rules:
- Give each agent its own git worktree as `--cwd`; agents never commit. The operator verifies the
  result, gates it and lands it.
- Stop an agent when its task is done; an idle agent still holds context in the host.
- Builds and game runs inside an agent go through `heavy.py`, as everywhere.
- Put in every brief: run long commands in the foreground, never `nohup …&`, `setsid` or `disown`.
  The host's bash tool moves a command still running after 30 s to the background itself, and when
  that command ends it wakes the agent with the result. A command the agent detaches itself is
  invisible to the host. The agent then ends its turn to poll the PID, and nothing ever wakes it.
- Put in every brief: never move, delete or re-point a path while a backgrounded command is still
  using it.
- Kill nothing by name. `stop` ends a session; the host process is shared and stays up.

`tools/piagent.py` (one pi process per agent) is the previous mechanism, kept only until the agents
already running under it finish; start new agents with `pinest-agent`.
