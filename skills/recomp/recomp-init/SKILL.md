---
name: recomp-init
description: >-
  How to start a new static-recompiler console→PC port from scratch — e.g. beginning a new
  SNES, N64, or other console recomp. Covers choosing a reference emulator, vendoring it as
  a submodule, repo/build scaffolding, ROM provisioning, and standing up the differential
  harness BEFORE any game logic. Use when initializing a brand-new recompilation project.
---

# Starting a new recompilation port from scratch

The order here matters: build the verification scaffold first, get the binary to boot under
the oracle, and only then begin recompiling game logic. Skipping ahead to "port the game"
means porting blind.

## 0. Decide the shape
- Identify the target CPU/ISA and the binary format (cartridge ROM, disc image, floppy set).
- Pick a **reference emulator** for that system that is (a) accurate, (b) open-source, and
  (c) embeddable as a library or drivable headlessly. This becomes both the oracle for the
  diff harness and, often, the source of runtime subsystems (video/audio/input) early on.

## 1. Scaffold the repo
- Single `main` branch.
- A build system (CMake or similar) with a clear split:
  - the **offline recompiler** (ROM/binary → emitted C/C++),
  - the **generated output** dir (gitignored — regenerable),
  - the **runtime** (host video/audio/input + the dispatch layer),
  - **overrides** (hand-written native replacements),
  - the **harness** target(s).
- Gitignore generated output, build dirs, `.env`, and any ROM/disk artifacts.

## 2. Vendor the reference emulator as a submodule
Add the emulator as a **git submodule** (do not copy its source in). Pin it. You'll both
diff against it and potentially call into its subsystems, so a clean, updatable vendor point
matters.

## 3. ROM provisioning (both modes from day one)
ROM/disk lives outside the repo. Support **both** an `.env`/env-var path and a repo-dir
drop-in, resolved arg > env/`.env` > drop-in. A tiny `KEY=VALUE` `.env` reader shared by all
binaries is enough. Never commit the ROM. (See recomp-port › ROM provisioning.)

## 4. Stand up the differential harness FIRST
Before recompiling game logic, build the harness that runs your (near-empty) binary and the
oracle in lockstep and compares state. Make it **deterministic** immediately (savestate
freeze/restore, fake monotonic time base, pinned input) — determinism is a precondition, not
a later cleanup. See recomp-harness for the full design.

## 5. Minimal recompiler → first boot
Get the recompiler emitting just enough to reach the entry point and run a few frames under
the oracle's subsystems. Expect to route hardware-touching / privileged instructions to the
emulator initially (hybrid execution — see recomp-recompiler). Success criterion for "init
done": the binary boots and the harness reports a clean (or only-known-residual) diff for
the first N frames.

## 6. Enter the loop
From here it's recomp-port's core loop: build → diff → first divergence → fix → re-verify.
Add overrides (recomp-overrides) as you turn opaque generated paths into PC-owned systems.

## Set up workspace hygiene early
A gitignored, type-separated scratch dir (dumps / screenshots / raw / wav / logs) from the
start — runs become comparable instead of a flat pile.
