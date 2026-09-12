---
name: dynarec-port
description: >-
  Umbrella methodology for runtime dynamic-recompiler/JIT console-to-PC ports: executing
  guest instructions from the user's original binary, validating against an emulator
  oracle, adding native overrides, and keeping faithful behavior separate from enhancements.
  Use for whole-project architecture and migration away from generated-source recompilers.
---

# Console → PC dynamic-recompiler port

A dynamic recompiler translates reached guest instructions while the game runs and caches host
machine code. This skill connects the runtime, title policy, native overrides, and oracle.

## Focused skills

- **dynarec-init** — starting a runtime-translated port and its verification scaffold.
- **dynarec-runtime** — block lookup, decoding, lowering, code caching, and invalidation.
- **dynarec-overrides** — handwritten native behavior selected by guest address at runtime.
- **dynarec-harness** — differential verification against a reference emulator.

## Architecture boundary

The portable product contains a title-neutral CPU runtime, platform/runtime services, and
title-owned policy. The user's binary remains data. At runtime:

`guest PC → cache lookup → decode/lower missing block → emit host code → execute → return to dispatcher`

All execution paths share canonical CPU state, memory, exception, and service semantics. The global
dynarec policy governs the shipping JIT, bounded fallback, and analysis metadata boundaries.

## Migration from generated-source recompilers

Follow the global break-first deletion contract. Preserve independently useful behavioral evidence
and oracle scenarios, then expose one missing runtime-executor boundary. Wire CPU state, memory,
imports/syscalls, overrides, exits, and invalidation through that boundary. Resume from a real guest
entry point or deterministic savestate and expand coverage along reached control flow. The migration
is complete only after a fresh clone launches from the user's binary, ordinary cold blocks compile
before execution, and representative gameplay passes the oracle gate on each released host.

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

## Verification discipline

Verify deterministic real gameplay, audio, rendering, timing, and state against a trusted oracle;
name the measured interval and released host. See **dynarec-harness** for first-divergence evidence.
