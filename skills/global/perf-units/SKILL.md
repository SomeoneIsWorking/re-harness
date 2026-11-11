---
name: perf-units
description: Measure a program's cost in units host load does not move (instructions retired per thread and phase, deterministic GPU work counts per present, allocations) and its pacing from the presenter's own schedule, then compare two builds against their run-to-run spread. Use for any performance, weak-hardware or "is this faster" question, before removing expensive work, or when a change might scale CPU work with resolution.
---

# Load-independent cost units

Weak hardware is met by removing redundant, repeated or resolution-scaled work, never by generating host
load or by timing a run. Cost is counted in units that read the same on a busy host and a quiet one, so
two builds are compared on any machine, paced or unpaced.

## Units

- **CPU: user-space instructions retired**, per product thread, split by the program's own phases (per
  logic frame: update, present, audio, the rest). Each thread reads only its own counter; threads that
  hand control to each other (fibers on threads) bank at each handoff. Reference: Lucent `lucent::perf`
  (`ThreadWorkCounter`, `WorkClock`, `CountHistogram`).
- **Thread CPU time only as a labelled fallback** where no counter opens (`perf_event_paranoid` above 2,
  a VM without a PMU, macOS, Windows). Every line names its unit; CPU time moves with load and frequency,
  so its spread is wider.
- **GPU: deterministic work counts per present**, counted on the CPU as the work is recorded: draws,
  pipeline binds, render passes, texture copies, triangles, pixels covered at internal resolution, copy
  pixels, upload bytes. They follow from the input, the internal resolution and the canvas, never from
  the host. GPU timestamps are a supplement where the API has them, not the comparison.
- **Allocations**: count and bytes per frame, where a hot path is suspected.
- Report per-frame/per-present p50, p99 and max plus the exact run total, at run end, one line each.

## Pacing

- Derive cadence from the presenter's own plan: each scheduled present is due the fields its pacer held
  it for; a simulated 60.00 Hz display shows the newest present due at each vblank, and the line counts
  the logic ticks each vblank advances. It reads the same unpaced and under load.
- One wall-clock real-time run on a quiet host checks only the player's pacing (present intervals,
  misses), once per pass.

## Comparing two builds

1. Same deterministic recipe on both: the same debug warp or route, held inputs, unpaced, the judgement
   resolution and sink, the cost channels on.
2. Repeat each side at least twice. The run-to-run spread, (max - min) / mean, is the noise floor; state
   it with every comparison. Deterministic GPU counts repeat exactly.
3. Compare the run-end lines with `perf_compare.py` (linked here, re-harness `tools/`):
   ```text
   uv run --no-project python tools/perf_compare.py A1.log A2.log --vs B1.log B2.log [--field p99]
   uv run --no-project python tools/perf_compare.py A1.log A2.log       # one build's spread
   ```
   It parses `[perf] <name>: p50 … p99 … max … <unit>/<per>, total … <unit>` lines (`--tag` for another
   bracket), warns when the `… run-end:` headers differ (frames or presents metered, unit), and marks a
   line CHANGED only when its delta exceeds the larger side's spread. Exit 1 when any line changed.
4. A difference above the spread is the change; one inside it is not a result.

## Rules

- Never ms budgets, wall-clock tests, frame-time thresholds or generated host load.
- Nothing on the CPU scales with internal resolution or sink: run the recipe at two resolutions; GPU
  pixel counts scale with the square, CPU phases must not. A CPU phase that grows is a defect to file.
- Measure the meter's own overhead (whole-process `perf stat -e instructions:u` with the channel on and
  off) and state it. Off, each hook is one cached branch.
- Reference implementation: psxport `runtime/psx/debug/gpu_perf.*` (`docs/presentation.md`, Cost and
  cadence) on Lucent `lucent::perf`.
