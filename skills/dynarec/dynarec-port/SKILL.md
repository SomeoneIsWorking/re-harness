---
name: dynarec-port
description: >-
  Dynarec/JIT port methodology: architecture, bring-up, oracle compare (first divergence),
  migration from generated-source recompilers. Use for whole-project architecture, starting a
  runtime-translated port, or comparing it against an emulator oracle.
---

# Console → PC dynamic-recompiler port

A dynamic recompiler translates reached guest instructions while the game runs and caches host
machine code. This skill connects the runtime, title policy, native overrides, and oracle.

## Focused skills

- **dynarec-runtime** — block lookup, decoding, lowering, code caching, and invalidation.
- **dynarec-overrides** — handwritten native behavior selected by guest address at runtime.

## Architecture boundary

The portable product contains a title-neutral CPU runtime, platform/runtime services, and
title-owned policy. The user's binary remains data. At runtime:

`guest PC → cache lookup → decode/lower missing block → emit host code → execute → return to dispatcher`

All execution paths share canonical CPU state, memory, exception, and service semantics.

## Execution policy

- Ports are native/dynarec hybrids. Hand-written native overrides own recovered behaviour; all other
  guest code runs through an on-demand JIT. No offline or install-time translation into C/C++ or
  objects, no prebuilt translated corpus, no static seed lists. Static analysis produces only
  non-executable knowledge (symbols, types, identity, override metadata).
- The interpreter is a bounded fallback, used only after the JIT reports a block cannot be compiled
  or fetched safely, recorded with reason, PC and counts. Interpreter-only mode is diagnostic, never
  the default or gameplay/performance evidence. Low-power 8/16-bit targets (NES, GBA, Amiga)
  classified so in their goals may ship an interpreter, qualified on gameplay on every host.
- A runtime translation cache is optional disposable data keyed to guest image, runtime version,
  host architecture and configuration.
- Invalidate on self-modifying and loaded code (guest writes, overlays, bank switches, DMA,
  address-space changes, cache control) before reuse.
- The runtime logs its work at run end (translated blocks, fallbacks by reason).
- WASM is a required frontier for migrated projects, running the same runtime in the browser, or
  recorded `blocked` with a migration action and acceptance criteria. ARM64 hosts: see `port-release`.

## Bring-up

- Identify the guest ISA, executable format, address-space rules and hardware services. If a
  `shared/` project owns that ISA or host backend, extend it there instead of a title-local engine.
  Choose an accurate, scriptable reference emulator as the oracle.
- Resolve the user's game file from an explicit argument, then `.env`, then a repo drop-in; validate
  the exact revision before mapping it.
- Start at the title entry point or a deterministic savestate. Compile a bounded block, execute it,
  and match its post-state against the oracle, then expand along reached control flow. An
  unsupported block fails with its guest PC or enters the bounded fallback.
- Bring-up is done when the runtime consumes the user's binary directly, one translated block
  matches the oracle, and ordinary cold blocks compile before execution.

## Migration from generated-source recompilers

Delete the static recomp first: the generator, generated corpora, static dispatch, and their tests and docs; the build may fail at the missing executor until the dynarec lands. Preserve independently useful behavioral evidence
and oracle scenarios, then expose one missing runtime-executor boundary. Wire CPU state, memory,
imports/syscalls, overrides, exits, and invalidation through that boundary. Resume from a real guest
entry point or deterministic savestate and expand coverage along reached control flow. The migration
is complete only after a fresh clone launches from the user's binary, ordinary cold blocks compile
before execution, and representative gameplay passes the oracle gate on each released host.

## Oracle compare

Drive the shipping runtime (real dispatcher, decoder, lowered blocks, cache, invalidation) and the
oracle from the same state:

- a bit-identical boot or savestate, pinned input, and a deterministic guest time source;
- compare CPU state, relevant memory, service events, audio and frames at the smallest practical
  boundary;
- audio is always compared, not only frames. Compare each sound voice's state (key on/off, pitch,
  envelope phase, volume) per field at aligned guest state, because removed loads mean raw sample
  streams never line up. A voice left keyed on, or one that never starts, is a divergence like any other;
- report the first divergent guest PC, boundary, region, expected and actual value.

Then classify the owner (decode/lowering, invalidation, CPU state transfer, memory map,
exception/timing, service emulation, native override), fix that owner, and re-run. Fix instruction
semantics in the shared decoder/lowering path, never at one guest address. Native overrides are for
deliberately owned behavior or a proven service boundary, not a substitute for missing CPU semantics.

## Faithful first, then enhance

Keep a faithful mode that compares with the oracle before adding widescreen, frame rate, rendering,
input or loading enhancements. Enhancements diverge on purpose and never weaken the faithful mode.
