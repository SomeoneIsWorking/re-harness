---
name: recomp-recompiler
description: >-
  The recompiler stage of a console→PC port: statically translating ROM/binary machine code
  into emitted C/C++, the "generated code is sacrosanct" rule, hybrid execution (leaving some
  functions to an interpreter/JIT), instruction-decoder coverage, and dispatch of indirect
  calls. Use when building, fixing, or extending the recompiler itself, or diagnosing a
  mistranslated instruction.
---

# The recompiler stage

Statically translate the original machine code into C/C++ that compiles to a native binary.
The recompiler is an **offline tool**: ROM/binary in, generated source out.

## Build the recompiler test-first (TDD)
The recompiler is the highest-leverage component to get right — a decoder/emitter bug
silently corrupts every generated function. **Develop it test-first**: for each instruction
/ addressing mode / edge case, write a test (input bytes → expected emitted-C behavior or
expected post-execution CPU state) before implementing, and keep the suite green as coverage
grows. The instruction-coverage table below should track tested, not just "written".

**Language matters for this.** A recompiler in a scripting language (e.g. Python) is the
easy place to start and TDD is natural there, but it will be slow on a large ROM — expect to
rewrite the hot path (or the whole tool) in C/C++ for throughput. TDD in C is more friction
than in a scripting language but is still worth doing for the decoder/emitter; lean on a
small unit-test harness and table-driven instruction tests. Pick the language deliberately:
prototype-in-script-then-port, or start in C and accept the slower test loop.

## Generated code is sacrosanct
Never hand-edit generated output — it's overwritten on the next run. To change behavior,
either fix the recompiler (decoder/emitter/config) and regenerate, or add a native override
(see recomp-overrides). Keep generated output gitignored and regenerable.

## Decode → emit
- A **decoder** turns each instruction into a typed operation; an **emitter** renders that
  operation as C/C++ against a modeled CPU state (registers, flags, memory accessors).
- Track **instruction coverage** explicitly — a table of which opcodes/addressing modes are
  implemented. Unimplemented ops are the first suspect for a boot hang or a wrong result.
- Model only what you must in-recomp; read live state through accessors so the runtime and
  any oracle can back the same memory.

## Hybrid execution — leave some functions to the emulator
Not everything should be recompiled. Functions that touch privileged/hardware state
(MMU/segments/TLB, cache control, hardware status registers, mode switches with side
effects) are safer routed to the reference emulator's interpreter/JIT, because only it
reproduces those side effects. A clear predicate ("does this function need the emulator?")
keeps boot from spinning. Pure computation stays in recomp.

## Dispatch & indirect calls
Direct calls become direct C calls. Indirect/dynamic targets (function pointers, jump
tables, computed branches, per-frame callbacks) go through a **dispatch table** keyed by
address. Targets reached *only* indirectly must be **explicitly seeded** as dispatchable, or
the call "misses" at runtime — maintain a seed list and treat a dispatch miss as a real bug
to diagnose (usually a missing seed or a decoder gap).

## Diagnosing a mistranslation
When the diff harness (recomp-harness) flags a divergence rooted in a recompiled function:
- Compare the emitted C against the original disassembly for that address.
- Suspect: wrong flag/carry semantics, sign/zero extension, operand width, addressing-mode
  edge cases, double-evaluation of side-effecting operands, return/stack-effect mismatch.
- Fix it in the emitter/decoder (so every similar site is fixed), regenerate, re-diff. Prefer
  a systemic decoder/emitter fix over special-casing one address.

## Determinism
The recomp side must be reproducible run-to-run (no uninitialized reads, no host-time
dependence in logic) so the harness diff is meaningful. Non-determinism is the enemy of the
whole method.
