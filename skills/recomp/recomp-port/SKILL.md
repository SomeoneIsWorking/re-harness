---
name: recomp-port
description: >-
  Umbrella methodology for static-recompiler + native-hybrid console-to-PC game ports:
  the build→diff→root-cause→fix→re-verify loop, faithful-first-then-enhance phasing,
  ROM provisioning, and verification discipline. Ties together the focused sub-skills
  recomp-init, recomp-recompiler, recomp-overrides, and recomp-harness. Use when
  working on or reasoning about a console→PC recompilation port at the whole-project level.
---

# Console → PC static-recompiler port — overall methodology

This is the umbrella skill. It covers the loop and disciplines that span a whole port, and
points to the focused sub-skills for each stage. Concrete commands live in the project's
own docs; this layer is tool-agnostic.

## The sub-skills
- **recomp-init** — starting a new port from scratch (oracle submodule, build, first boot).
- **recomp-recompiler** — the recompiler stage: ROM/binary → emitted C/C++ → native binary.
- **recomp-overrides** — replacing generated functions with hand-written native code.
- **recomp-harness** — the differential compare harness against a reference emulator.

## Sibling: decomp-port (selective decompilation, not whole-binary recompile)
**decomp-port** is the complementary approach when you don't want to recompile the WHOLE binary but
to DECOMPILE specific functions/subsystems out of a game (Ghidra headless → readable C) and
re-implement them natively in your own engine — e.g. porting one game's actor/behavior into an
existing PC port, especially a remake whose original you already have decompiled (Rosetta-stone
diff). It composes with this family: a decompiled function is exactly what recomp-overrides
hand-writes. Reach for decomp-port for targeted RE/porting; recomp-* for a whole-game recompile.

## Pipeline shape
ROM/binary → decode/disassemble → emit C/C++ → compile → native binary, with a runtime
layer supplying the host's video/audio/input (often borrowing a reference emulator's
subsystems). **Generated code is sacrosanct** — never hand-edit it; change behavior through
recompiler config or an override.

## The core loop
`build → run the differential harness vs a reference-emulator oracle → find the FIRST
divergence → root-cause → fix (recompiler bug, or add a native override) → re-verify →
repeat.` The harness (recomp-harness) is what makes every other step verifiable; stand it
up before porting game logic.

## Faithful first, then enhance
Two phases, kept distinct: (1) a faithful port verified identical to the original; (2)
PC-native enhancements (widescreen, 60fps, higher internal resolution, flicker-free
sprites) that intentionally diverge. Don't mix them — you can't diff an enhancement against
the oracle, so enhancement work must sit on a proven-faithful base.

## ROM provisioning
ROMs/disk images stay **outside** the repo (a shared ROM store). **Never copy a ROM into
the repo** — it duplicates large files and risks committing a copyrighted ROM. The loader
should support **both** provisioning modes so the repo is easy to share:
  1. **`.env` / env var** pointing at the external file/dir (the `.env` is gitignored).
  2. **Drop-in** — a collaborator drops the ROM/disk into the repo dir and it just runs.
Resolution order: explicit CLI arg > env/`.env` > drop-in default. A minimal `KEY=VALUE`
`.env` reader (real env wins) shared across the game and harness binaries is enough. If a
ROM ever slips into git history, purge it (git-filter-repo/BFG) and force-push — with the
user's approval, since it rewrites shared history.

## Verification discipline
Never claim "matches" / "fixed" without a verified result on **real** data (bit-exact
compare on real gameplay/audio, not a cherry-picked sample). Cite the harness output.
