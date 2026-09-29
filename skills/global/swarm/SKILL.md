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
`<id>/worker-<n>.log` and `<id>/gate-<n>.log`; the verdict is `<id>/result.json`.

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
 "heavy_gate": true, "timeout": 900, "gate_timeout": 1800}
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
- `timeout` bounds each worker attempt; `gate_timeout` (default 3600 s) bounds each gate run,
  including time spent waiting for a heavy slot.

## Slots, heavy gates, and memory

- **Machine-wide slots.** Every swarm on the machine shares `<lock-dir>/swarm-slots/` (default
  `~/repo/scratch/locks`, or `$SWARM_LOCK_DIR`, or `--lock-dir`): 24 flock'd slot files, one held
  per running job. Several projects' swarms together never exceed the slot count. Keep `--slots`
  at the default unless every concurrent user agrees; the cap is only as strong as the smallest
  value in use. `--workers` (default 8) is this invocation's own ceiling.
- **Heavy commands** go through `heavy.py [--kind build|run] -- <command...>` (on PATH). `build`
  (compilers, verifiers; 2 at once, each with a moderate `-j`) and `run` (one game, browser,
  Ghidra or bot instance; 4 at once) are separate flock slot sets under `<lock-dir>/heavy-<kind>/`,
  and admission also waits for 2048 MiB of `MemAvailable`. The wrapper holds the slot, so a daemon
  the command leaves behind never keeps it. A job with `heavy_gate: true` runs its gate as a
  `build`. Do not run heavy work outside it; the old single `heavy.lock` is retired.
- **Memory floor.** No worker starts while `MemAvailable` is below `--mem-floor-mib` (default 3072).
- Timeouts kill the worker's whole process group by its captured id. The opencode backend uses
  `--standalone` so its model server is inside that group; through the shared `opencode serve`
  service a timed-out session would keep editing the worktree.

## After the run

Read `report`, inspect each accepted `patch.diff` like any contributor's patch, `apply` the ones
you keep, gate the combined tree with the project's normal verifier, and commit as the operator.
Then `gc` the run and delete its directory with `tools/scratch_gc.py`.
