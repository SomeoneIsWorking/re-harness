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
swarm.py report <repo>/scratch/swarm/<run>     # jobs, accepted, rejected by reason, failures, timeouts, wall
swarm.py apply  <repo>/scratch/swarm/<run> <id> # accepted only; refuses on conflict
swarm.py gc     <repo>/scratch/swarm/<run>     # git worktree remove, keeps results and logs
```

The repo must gitignore `scratch/` (the run refuses otherwise). Linux only: it refuses by name
elsewhere. Worker and gate output are in
`<id>/worker-<n>.log` and `<id>/gate-<n>.log`; the task handed to the worker is
`<id>/prompt-<n>.md`; the verdict is `<id>/result.json`.

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
 "heavy_gate": "run", "timeout": 900, "gate_timeout": 1800}
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
- `timeout` bounds each worker attempt; `gate_timeout` (default 3600 s) bounds each gate run
  from the moment it is admitted: time a heavy gate spends waiting for a build slot does not
  count. Neither counts time a unit spent paused for memory pressure.
- **`heavy_gate`** (optional: `"build"` or `"run"`) names the one kind of machine-wide slot the
  runner admits the gate on. Choose the kind that dominates the gate's time: `"build"` for
  compiling and verifiers, `"run"` for a game, browser or bot instance, even when a short ccache
  rebuild precedes it. A gate holds one kind only, so game runs never occupy build slots. Do not
  call `heavy.py` from inside a swarm gate, or from a worker checking its own patch against the
  gate: the job's one reservation already covers the gate's whole group, and a nested request
  queues behind requests that may be waiting on it.
- **`mem_mib`** (optional, whole MiB, `heavy_gate` only) is the peak this job's gate may grow
  into (default: its kind's reserve, 3072 MiB for `build`, 1536 MiB for `run`).
- **A prompt is a file, not an argument.** The runner writes it to `<id>/prompt-<n>.md` and the
  backend attaches it (`-f` for opencode, `@` for pi), because Linux caps one argv string at
  128 KiB and a long task plus gate feedback exceeds that. Retries reuse the same path with the
  feedback appended.

## Slots, heavy gates, and memory

- **Machine-wide slots.** Every swarm on the machine shares `<lock-dir>/swarm-slots/` (default
  `~/repo/scratch/locks`, or `$SWARM_LOCK_DIR`, or `--lock-dir`): 24 flock'd slot files, one held
  per running job. Several projects' swarms together never exceed the slot count. Keep `--slots`
  at the default unless every concurrent user agrees; the cap is only as strong as the smallest
  value in use. `--workers` (default 8) is this invocation's own ceiling.
- **Reservations.** Slots cap how many units run, not how big they get, and a free-model worker
  plus a gate build both grow after they start. Every admitted unit therefore reserves the memory
  it may still grow into: one file `<lock-dir>/reservations/<pid>.<n>.json` holding its process
  group (the group the unit's processes are in — for a heavy command, the wrapper's), `reserve_mib`
  and kind, deleted when the unit is released and ignored once its group is gone (a crashed swarm
  leaks nothing). A new unit starts only when
  `MemAvailable - outstanding - reserve >= --mem-floor-mib` (default 1024, the pressure watcher's
  pause threshold), where an entry's
  outstanding part is its reserve minus what its process group already has resident, read from
  `/proc` once per check. Check and write happen under one flock on `<lock-dir>/reservations.lock`,
  so two swarm invocations cannot both spend the same headroom. Admission is
  first come first served: a unit that does not fit leaves a ticket in
  `<lock-dir>/reservations/waiting/` and is refused while any older live ticket
  is still queued, so a large build is not starved by a stream of small workers.
  A unit that does not fit waits and
  says so, and gives up when the run is stopped.
- **Reserve what, by default.** A worker reserves 256 MiB (`--mem-reserve-mib`; opencode workers measure ~85 MiB), a `build` 3072 MiB
  and a `run` 1536 MiB. `heavy.py --mem-mib N` overrides one command, and a job's `mem_mib` field
  overrides its heavy gate. Raise these when a real job outgrew its default; do not lower them
  without measuring the peak.
- **Pressure pause.** While a unit is admitted, a watcher in the admitting process polls
  `MemAvailable` every 2 s. Below 1024 MiB it SIGSTOPs one of its own units, the most recently
  admitted first and the oldest last, and never leaves less than one unit running; above 2560 MiB
  it SIGCONTs the stopped groups oldest first. A paused unit is not working, so its deadline is
  extended by the time it spent stopped. This is the machine getting tight, not a failure: the
  run continues.
- **Heavy commands** go through `heavy.py [--kind build|run] [--mem-mib N] -- <command...>` (on
  PATH). `build` (compilers, verifiers; 2 at once, each with a moderate `-j`) and `run` (one game,
  browser, Ghidra or bot instance; 4 at once) are separate flock slot sets under
  `<lock-dir>/heavy-<kind>/`, and admission also keeps the same 1024 MiB floor. The wrapper
  holds the slot and the reservation, so a daemon the command leaves behind never keeps either. A
  job with `heavy_gate` runs its gate under that kind, admitted by the swarm runner itself: it
  takes one of the same slots and grows the job's one reservation from the worker's reserve to
  the gate's peak (`mem_mib`) for the gate's duration, then shrinks it back. Growing needs headroom
  only for the increase, so the job never waits on its own entry, and the long worker phase does not
  hold the gate's peak. The gate still runs
  under the reaper. Do not run heavy work outside it; the old
  single `heavy.lock` is retired.
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
  it was gone. The reservation, the pressure watcher and the run lifetime therefore track the
  wrapper's group, which is where the command lives (under `swarm.py` that group is the worker's,
  so the caller's own resident size is read as part of the unit's). A worker's detached helper
  (opencode runs retry scripts from /tmp under `setsid`/`nohup`) is therefore reaped with the
  worker; one such script once kept re-running a gate for an hour after its swarm was killed.
- Timeouts kill the worker's whole process group by its captured id. The opencode backend uses
  `--standalone` so its model server is inside that group; through the shared `opencode serve`
  service a timed-out session would keep editing the worktree.

## After the run

Read `report`, inspect each accepted `patch.diff` like any contributor's patch, `apply` the ones
you keep, gate the combined tree with the project's normal verifier, and commit as the operator.
Then `gc` the run and delete its directory with `tools/scratch_gc.py`.
