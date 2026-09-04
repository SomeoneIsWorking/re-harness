---
name: dynarec-runtime
description: >-
  Build or debug a runtime dynamic recompiler/JIT: guest block discovery, typed IR, host-code
  emission, code-cache ownership, invalidation, exceptions, interpreter fallback, and indirect
  control flow. Use for CPU execution engines and migrations away from generated C/C++.
---

# Dynamic-recompiler runtime

The runtime consumes guest bytes and translates executable blocks on demand. There is no offline
guest-code emission step and no generated C/C++ corpus in the build.

## One execution contract

Define one CPU context and one set of memory, exception, timing, and runtime-service interfaces.
Translated blocks, the interpreter fallback, native overrides, and the differential harness all use
that contract. Do not maintain parallel flag formulas, memory semantics, or call conventions.

## Block lifecycle

- Look up the current guest PC in the code cache.
- On a miss, decode a bounded basic block from the live mapped guest bytes into typed operations or
  IR, validate every instruction, lower it, emit host code, publish the block, and execute it.
- End blocks at control-flow, exception, synchronization, mode, and other architecture-defined
  boundaries. Link direct successors only through patch points the cache can safely revoke.
- Return indirect branches, calls, and exceptional exits through the runtime dispatcher unless the
  target is already proven and guarded.

Unimplemented or invalid instructions fail with the guest PC and decoded bytes. They never become a
no-op or a guessed translation.

## Code cache and invalidation

The cache owns emitted memory and its lifetime. Enforce write/execute policy without leaving pages
simultaneously writable and executable where the host can avoid it. Cache keys include every mode or
mapping property that changes semantics.

Writes that can alter executable guest bytes, overlay/module replacement, address-space changes, and
relevant cache-control instructions invalidate affected blocks before they can run again. Test both
the ordinary cache-hit path and a mutation that must force retranslation. Whole-cache flushing is a
correctness fallback, not the final design when bounded invalidation is available.

## Interpreter fallback

Fallback is an explicit runtime policy for cold code, rare instructions, privileged behavior, or
bring-up. It must preserve exact architectural state and re-enter the dispatcher at a defined guest
PC. Count and report fallback coverage with a denominator so an accidentally all-interpreted run
cannot be presented as JIT evidence.

## Instruction semantics

Use table-driven positive and negative tests for instruction widths, signedness, flags/carry,
overflow, delay slots, alignment, memory faults, floating-point modes, atomics, and return/stack
effects as applicable. Tests execute the shipping decoder and lowered block; a duplicated test-only
implementation proves nothing.

When a differential run finds a mistranslation, fix the shared semantic owner and add the smallest
instruction or block regression that reproduces it. Never special-case the failing address.

## Determinism and diagnostics

Provide block compile/hit/invalidation/fallback counters, guest-PC-aware failures, and bounded traces.
Deterministic inputs and guest time are required for differential verification. Prove diagnostic
positive and negative cases before trusting a silent result.
