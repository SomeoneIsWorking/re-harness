---
name: recomp-harness
description: >-
  The differential compare harness for a console→PC port: running the recompiled binary and
  a reference emulator (oracle) in lockstep, comparing state each frame/call, stopping at the
  first real divergence, enforcing determinism, and maintaining a residual/known-divergence
  list. Also covers headless runs and frame dumps. Use when building or using the verification
  harness, or chasing a divergence.
---

# Differential compare harness

The harness is the heart of verification: it proves whether the recompiled binary behaves
like the original by diffing it against a trusted reference emulator (the **oracle**). Build
it early (see recomp-init) — it makes every recompile and override change checkable.

## How it works
- Run the recomp and the oracle emulator **in lockstep**, advancing both one step (frame or
  call) at a time.
- After each step, compare state — RAM regions, CPU registers, framebuffer — and **stop at
  the first real divergence**. The first divergence is the root; later ones are usually
  cascades from it.
- Surface where/when it diverged precisely enough to map back to a function or address.

## Determinism is a precondition
A diff is only meaningful if both sides are reproducible. Before trusting the harness:
- **Freeze and restore a savestate** so both sides start from a bit-identical point (live
  boot often drifts run-to-run).
- Use a **fake/monotonic time base** so timing loops elapse identically.
- **Pin input** (scripted, not live).
Non-determinism (free-running counters, host-time reads, uninitialized memory) makes the
diff lie. Eliminate it or classify it as a residual (below).

## Residual / known-divergence list
Some divergences are benign and expected (free-running RNG/timing counters, a 1-frame skew
between a synchronous host blitter and the hardware, uninitialized shadow registers). Keep an
explicit list of these so they aren't re-chased, and **always record WHY** each is benign.
The discipline: every divergence is either a real bug or a documented residual — never
"probably fine."

## Chasing a divergence
1. Confirm determinism (a "bug" that moves run-to-run is a determinism problem first).
2. Get the first divergence's address/region/frame.
3. Decide: recompiler mistranslation (→ recomp-recompiler) or a function that needs a native
   override (→ recomp-overrides)? Keeping recomp bodies alive (recomp-overrides) lets the
   harness test even overridden functions.
4. Fix at the systemic level, re-run, confirm the divergence is gone and nothing regressed.

## Headless runs and frame dumps
- Run **headless** with scripted input and a frame cap for reproducible automated runs.
- **Dump presented frames as PNG** to verify rendering — direct window capture is often black
  under Wayland/XWayland, so an explicit frame-dump path is the reliable visual check.

## Where harness output goes — NEVER `/tmp`
Diff logs, ccall traces, and frame dumps are large (a full ccall trace can hit multiple GB; a
few hundred framedump PNGs another GB) and the harness runs them often. `/tmp` here is a
RAM-backed **tmpfs with a ~6 GB per-user quota** — dumping there fills it in a couple of runs
and breaks everything with "Disk quota exceeded" (this actually happened: 6.3 GB of
`sb_ccall_full.log`, `sb_oldframes_ccall/`, and `*.log` filled the quota). Rules:
- **Write every artifact under a gitignored `scratch/` in the project**, never `/tmp`. The
  project home has hundreds of GB free and survives reboots. Split by type per the global
  hygiene rule: `scratch/logs/`, `scratch/raw/` (state/trace dumps), `scratch/frames/` (PNGs).
- **Make the run scripts default there** — e.g. read `SB_SCRATCH=$REPO/scratch` (or the
  harness's own env var) and route logs/dumps relative to it; don't hardcode `/tmp/...`.
- **Cap the firehose.** Full per-call ccall tracing produces multi-GB logs — gate it behind a
  flag, and rotate/size-cap so one run can't balloon unbounded.
- **Clean stale artifacts at run start** (wipe `scratch/logs/` or age out files older than a
  few days) so old runs don't accumulate to the same failure.

## Verification discipline
Never claim "matches"/"fixed" without a verified result on **real** data (bit-exact compare
on real gameplay/audio, not a cherry-picked sample). Cite the harness output.
