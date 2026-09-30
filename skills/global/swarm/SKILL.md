---
name: swarm
description: >-
  Fan many small, independently checkable coding jobs out to the free "Space Bunny" model
  (opencode or pi) in isolated git worktrees, and accept a result only when a scripted gate exits 0.
  Use for bulk mechanical work with an objective check — native overrides against an oracle,
  recovering modules that must compile or match, decomp functions that must byte-match — when the
  operator would otherwise do dozens of near-identical edits by hand. Bundles `swarm.py`.
---

# Gated swarm of free workers

`tools/swarm.py` runs each job in a detached worktree under
`<repo>/scratch/swarm/<run>/<id>/tree`, invokes a weak but free model there, snapshots its changes
to `patch.diff`, then runs the job's gate argv in that worktree. **Only gate exit 0 is
`accepted`**; the record cannot say otherwise (`JobResult` refuses it). Nothing is committed and
the main tree is never touched until the operator runs `apply`.

```text
swarm.py run jobs.jsonl [--backend opencode|pi] [--workers 8] [--retries N] [--name RUN]
swarm.py run jobs.jsonl --name RUN --resume   # continue an interrupted run in place
swarm.py report <repo>/scratch/swarm/<run>     # jobs, accepted, rejected by reason, failures, timeouts, wall
swarm.py apply  <repo>/scratch/swarm/<run> <id> # accepted only; refuses on conflict
swarm.py gc     <repo>/scratch/swarm/<run>     # git worktree remove, keeps results and logs
```

The repo must gitignore `scratch/` (the run refuses otherwise). Linux only: it refuses by name
elsewhere. Worker and gate output are in
`<id>/worker-<n>.log` and `<id>/gate-<n>.log`; the task handed to the worker is
`<id>/prompt-<n>.md`; the verdict is `<id>/result.json`.

**Never restart a batch from scratch.** To change workers or settings, or after the run was killed,
stop it by PID and rerun the same jobs file with `--name <run> --resume`. Do not `gc` it first.
A job the gate judged keeps its verdict. An unfinished or worker-failed job continues in the worktree it left, and its worker
is told to read `git diff` and carry on; that attempt does not count against `--retries`. A job
that never started runs fresh. A restart that discards in-flight work repeats up to an hour of
every worker's progress: 3 restarts of one psx batch on 2026-09-30 cost more than the batch produced.
Prompt changes need a new jobs file only for jobs that have not started.

## When to use it

Use it when the work splits into many jobs that are each small, independent, and **mechanically
judgeable**. Without a gate that can say no, do not use it: an ungated weak model produces
plausible wrong code faster than anyone can review it. It is not for design, cross-cutting
refactors, or anything whose correctness is "looks right".

## Writing a job a weaker model can pass

One JSON object per line:

```json
{"id": "ovr-8003a1c4", "repo": "../psxport", "prompt": "...", "files": ["src/ovr/room.cpp"],
 "gate": ["uv", "run", "--frozen", "python", "tools/check_override.py", "0x8003a1c4"],
 "timeout": 900, "gate_timeout": 1800}
```

- **One change per job.** Name the exact file and function to edit and say what must not change.
  A job that needs the model to explore the codebase is too big.
- **Put the evidence in the prompt or `files`**: the decompiled function, the oracle trace, the
  failing test's text, the neighbouring override to imitate. `files` are relative to the worktree.
- **The worker sees only its worktree.** Gitignored trees (generated decompilation) and
  uninitialised submodules are absent there; name them in `read_only` (paths relative to `repo`)
  and cite them in the prompt by absolute path. The opencode backend lets the worker read, not
  edit, those, and denies every other outside path; opencode's default `ask` aborts a
  non-interactive run. Never point a worker at the gate script: the runner runs it.
- **The gate tests the claim, not the effort.** It must fail on the unmodified tree (check that
  before launching) and pass only on a correct change: a focused test, an oracle diff, a byte-match,
  a type-check of the one module. Prefer the project's own verifier entry point through
  `uv run --frozen`. A worker that changes nothing is rejected as `empty-patch`.
- **The gate also enforces code quality.** Chain the project's formatter check, linter/type-check
  and structure verifier for the touched files after the correctness check, so a correct but messy
  patch is rejected with the finding as feedback. When reviewing accepted patches, also reject
  duplicated helpers, dumping-ground files, unclear names and dead code; fold repeated patterns
  into one owner before applying more of them.
- **Gate output is feedback.** With `--retries N` a rejected worker is re-prompted in the same
  worktree with the gate's last 60 lines, so make failures say what differed.
- `timeout` bounds each worker attempt; `gate_timeout` (default 3600 s) bounds each gate run.
  Neither counts time a unit spent paused by the pressure guard.
- Do not call `heavy.py` from inside a swarm gate: the runner already registers the gate's group
  as a unit and runs it under the reaper.
- **A prompt is a file, not an argument.** The runner writes it to `<id>/prompt-<n>.md` and the
  backend attaches it (`-f` for opencode, `@` for pi), because Linux caps one argv string at
  128 KiB and a long task plus gate feedback exceeds that. Retries reuse the same path with the
  feedback appended.

## Memory: nothing queues, the guard pauses

- **Launch a long swarm as a systemd user unit, not a session's background shell:**
  `systemd-run --user --collect --unit swarm-<name> --working-directory <repo> --setenv=PATH="$PATH" swarm.py run ... --name <name>`
  (the unit does not inherit your shell's PATH; without it workers fail with no `opencode`)
  (follow it with `journalctl --user -u swarm-<name> -f`; stop it with `systemctl --user stop
  swarm-<name>`, then `--resume`). Claude Code's low-memory reaper kills a session's background
  shells, and on 2026-09-30 it took two launchers with it; a unit belongs to no session.

- **Nothing is admitted ahead of time.** A job starts as soon as one of this invocation's
  `--workers` (default 8) is free, and `heavy.py` starts its command at once. There are no
  machine-wide slots, no predicted memory reservations and no `-j` cap. Per-kind slots and
  reserved peaks (3 GiB per build, against measured compiles of ~400 MiB) queued builds for up to
  50 minutes on 2026-09-30 while the host had 7 GiB free and half its cores idle; they were
  removed.
- **Units.** Every running worker, gate and `heavy.py` command registers its process group in
  `<lock-dir>/units/` (default `~/repo/scratch/locks`, or `$SWARM_LOCK_DIR`, or `--lock-dir`) and
  removes the entry when it ends; an entry whose group is gone is pruned.
- **The pressure guard is the one memory countermeasure.** `pressure_guard.py` runs as the systemd
  user service `pressure-guard` and polls `MemAvailable` every 0.5 s. Below 2048 MiB (before
  Claude Code's own low-memory reaper kills background shells) it SIGSTOPs
  the newest running unit (its pages can go to swap while older units finish), one per poll, and
  never the last running one; above 3584 MiB it SIGCONTs every unit it stopped. A paused swarm unit
  is not working, so its deadline is extended by the time it spent stopped. On start the guard
  resumes every registered unit (a guard that died cannot remember what it stopped), and on exit
  it resumes what it stopped. Check it with `systemctl --user status pressure-guard`; the watchdog
  alerts when its heartbeat (`<lock-dir>/guard/heartbeat`) is older than 60 s.
- **Heavy commands** go through `heavy.py [--kind build|run] -- <command...>` (on PATH) so they
  are guarded units and die with their caller. `build` is a compiler or verifier; `run` is one
  game, browser, Ghidra or bot instance. The kind is a label for reports.
- **Every unit's whole subtree dies with the run that started it** -- a `heavy.py` command, and
  under `swarm.py` every worker and every gate. The wrapper's direct child is a reaper
  (`swarmkit.reaper`, started by `command_argv(argv, parent)`), not the command. It runs the
  command in the caller's own process group, never a new session, so the group kill a timeout
  sends reaches the command and not only the wrapper; and it arms `PR_SET_PDEATHSIG` (SIGTERM,
  catchable, not SIGKILL) on itself, refusing to start if its named parent is already gone, so a
  wrapper killed on its own hands the subtree over to it. The command's environment is the
  caller's, unchanged: the reaper finds its own package without `PYTHONPATH`. The reaper
  calls `prctl(PR_SET_CHILD_SUBREAPER)`, so a descendant orphaned when its own parent dies is
  reparented to the reaper instead of init, and it then SIGTERMs every remaining descendant,
  waits 5 s, SIGKILLs the survivors and exits with the command's status. Descendants are found
  through the `/proc` parent graph (`procs.descendants`), not by process group, so a daemon that
  left the group with `setsid` -- a Gradle or MSBuild node -- is still taken down. This matters:
  `PR_SET_PDEATHSIG` reaches exactly the one process it is set on, so a gate whose direct child
  was `cmake` once left `ninja` and the rest of the build compiling after the worker that started
  it was gone. The unit entry and the run lifetime therefore track the wrapper's group, which is
  where the command lives (under `swarm.py` that group is the worker's or the gate's). A worker's detached helper
  (opencode runs retry scripts from /tmp under `setsid`/`nohup`) is therefore reaped with the
  worker; one such script once kept re-running a gate for an hour after its swarm was killed.
- Timeouts kill the worker's whole process group by its captured id. The opencode backend uses
  `--standalone` so its model server is inside that group; through the shared `opencode serve`
  service a timed-out session would keep editing the worktree.

## After the run

Read `report`, inspect each accepted `patch.diff` like any contributor's patch, `apply` the ones
you keep, gate the combined tree with the project's normal verifier, and commit as the operator.
Then `gc` the run and delete its directory with `tools/scratch_gc.py`.

## Watchdog

`watchdog.py [--kill] [--repo PATH ...] [--shared PATH ...]` checks the machine for the failure
modes that stalled agent work, prints one line per alert, and appends them to
`<lock-dir>/watchdog/alerts.log`. Run it from a systemd user timer every few minutes, and have the
operator session act on the log. It alerts on:
- a runaway process: 4 GiB or more, grown 256 MiB since the last check, not a registered unit
  (the guard pauses those instead), and not a Claude or desktop process. With `--kill` it is
  stopped by PID.
- the pressure guard not running (heartbeat older than 60 s);
- a swarm with no new verdict for 90 min;
- a pinest agent idle for 15 min, meaning finished and unreviewed;
- a `--repo` whose origin/main landed nothing for 90 min;
- a `--shared` checkout with modified tracked files or a submodule uninitialised or off its commit;
- a process in an agent worktree whose parent is init, meaning an agent detached it.

