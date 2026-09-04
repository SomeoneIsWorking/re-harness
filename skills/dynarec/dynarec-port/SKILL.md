---
name: dynarec-port
description: >-
  Umbrella methodology for runtime dynamic-recompiler/JIT console-to-PC ports: executing
  guest instructions from the user's original binary, validating against an emulator
  oracle, adding native overrides, and keeping faithful behavior separate from enhancements.
  Use for whole-project architecture and migration away from generated-source recompilers.
---

# Console → PC dynamic-recompiler port

A dynamic recompiler translates guest instructions while the game runs and caches host
machine code. The shipped runtime consumes the user's original game binary directly. It does
not generate C/C++, compile per-title guest source, or depend on a pre-generated native image.

## Focused skills

- **dynarec-init** — starting a runtime-translated port and its verification scaffold.
- **dynarec-runtime** — block lookup, decoding, lowering, code caching, and invalidation.
- **dynarec-overrides** — handwritten native behavior selected by guest address at runtime.
- **dynarec-harness** — differential verification against a reference emulator.

## Architecture boundary

The portable product contains a title-neutral CPU runtime, platform/runtime services, and
title-owned policy. The user's binary remains data. At runtime:

`guest PC → cache lookup → decode/lower missing block → emit host code → execute → return to dispatcher`

The shipping emulated-runtime path is the dynarec/JIT. An interpreter may serve as an oracle or
bring-up engine only in a separate test/diagnostic target; the gameplay product must neither link nor
select it and contains no fallback. The test oracle may share the canonical CPU state, memory
accessors, exception model, and service boundary. Static analysis may produce reviewable symbols or
non-executable metadata; it must not produce guest function bodies or another title-specific source
corpus.

## Migration from generated-source recompilers

Use break-first ordering:

1. Preserve only independently useful binary/behavior evidence, native subsystem contracts, and
   oracle scenarios.
2. Delete the generator, generated-source build rules and corpora, static dispatch, generation-only
   seeds, static-only tests/config/selectors, and stale methodology before implementing the dynarec.
3. Make the resulting broken build name one explicit missing runtime-executor boundary. Do not keep
   the static product runnable as a bridge, comparison arm, fallback, or temporary convenience.
4. Put CPU state, memory, imports/syscalls, native overrides, bounded exits, and invalidation behind
   the runtime interface, then route real guest code through the dynarec and compare against an
   independent emulator, hardware, binary evidence, or separately built test oracle.
5. Expand runtime coverage through representative interactive gameplay and qualify each released
   host backend.

Do not preserve a compatibility mode that can silently select the old pipeline. A migration is
complete only when a fresh clone builds and launches the native/dynarec hybrid from the user-supplied
binary without an offline translation step or interpreter fallback.

## Core loop

`build runtime → run differential harness → stop at first divergence → identify decoder/lowering,
state, memory, invalidation, or service-boundary cause → fix the owning layer → re-verify`

Fix instruction semantics in the shared decoder/lowering path, not at one guest address. Native
overrides are for deliberately owned behavior or a proven service boundary, not a substitute for
missing CPU semantics.

## Faithful first, then enhance

Maintain a faithful mode that can be compared with the original before adding widescreen, frame
rate, rendering, input, or loading enhancements. Enhancements intentionally diverge and need their
own observable gates; they do not weaken the faithful baseline.

## Game-file provisioning

Game binaries stay outside Git and packages. Support both an environment/`.env` path and a repo
drop-in, with resolution order: explicit argument, environment/`.env`, then drop-in. Packaged apps
use the platform's file picker and persistent user-data location. Validate exact title identity
before execution.

## Verification discipline

Never claim parity from boot, a clean internal trace, or a single frame. Verify deterministic real
gameplay, audio, rendering, timing, and state against a trusted oracle, and name the measured scope.

Host qualification is per operating-system/architecture pair. In particular, AArch64 support must
cover both Apple Silicon macOS and Android arm64-v8a with the shipping backend. Test executable-memory
publication and protection changes, instruction-cache coherence, ABI transitions, signals/exceptions,
packaging, and representative gameplay on each; an emitter unit test or a different AArch64 OS is not
substitute evidence. Never fill an unimplemented host backend with the test interpreter.
