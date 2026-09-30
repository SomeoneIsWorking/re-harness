---
name: piagent
description: >-
  Drive one long-running pi agent by name from another agent: start it detached, ask what it is
  doing, steer it mid-run, queue a follow-up, and stop it cleanly. Use for a single open-ended
  investigation or implementation you want to redirect while it works — when you need to watch
  and steer, not when a scripted gate can judge the result. Bundles `piagent.py`.
---

# Steer one long-running pi agent

`tools/piagent.py` runs `pi --mode rpc` under a detached supervisor, so a `pi -p "<task>"`
fire-and-forget becomes something you can talk to. Each agent is a NAME under
`~/repo/scratch/piagent/<name>/` (or `$PIAGENT_DIR`, or `--state-dir`): `events.jsonl` (every
stdout record, verbatim), `stderr.log`, `meta.json`, and a mode-0600 `ctl.sock`.

```text
piagent.py start NAME --cwd DIR [--message TEXT | --brief FILE] [--model M] [--thinking L]
piagent.py status NAME                  # alive/dead, streaming/idle, model, tool, files, tokens
piagent.py send NAME "different plan"   # steer while streaming, prompt while idle
piagent.py send NAME "then also ..." --follow-up
piagent.py tail NAME [-n N] [--follow]  # assistant text, tool calls, results, errors, retries
piagent.py wait NAME [--timeout S]      # 0 settled, 1 dead, 2 timed out; prints the last message
piagent.py abort NAME                   # stop the current run; the agent stays alive
piagent.py stop NAME                    # abort, then end pi and the supervisor by pid
piagent.py list
```

With neither `--message` nor `--brief`, the agent comes up idle and waits for `send`. A name
that is already live is refused; a stale socket from a crashed supervisor is cleaned on `start`.

## When to use it, and when not to

- **piagent**: one open-ended job you cannot script a check for — an investigation, a port, a
  refactor — where you want to read the transcript, redirect it when it goes wrong, and see the
  report at the end.
- **swarm.py**: many small jobs that each have an objective gate. Without a gate, do not fan out
  a weak model: it produces plausible wrong code faster than anyone can review it.

One agent at a time per task. They are separate processes with separate sessions, but two agents
editing the same tree will fight over it.

## What the operator still owes

- **The agent never commits, stages, or pushes.** It edits the tree; the operator reviews, gates,
  and lands. Tell it so in the brief.
- **Verify the report, do not relay it.** A finished agent is a contributor, not evidence. Check
  the files it claims to have changed, then run the project's own gate.
- **Kill with `piagent.py stop NAME`.** Never `pkill pi`: the binary is shared with the operator's
  own session and with every other agent.
- Long runs belong in a worktree (`git worktree add`) when the agent's changes must not land in
  the main tree, and `~/repo/scratch/` when only the output matters.
- `status` is the cheapest way to see whether it is stuck: it shows the current or last tool call,
  the files written with the `edit`/`write` tools, context usage, and pi's own stderr when the agent
  dies. Changes it made with `bash` (`>> file`, a generator script) do not appear in the file list —
  read the `tool` line and the working tree.

