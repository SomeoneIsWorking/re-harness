---
name: dynarec-runtime
description: >-
  Build or debug a runtime dynamic recompiler/JIT: guest block discovery, typed IR, host-code
  emission, code-cache ownership, invalidation, exceptions, test-only interpretation, and indirect
  control flow. Use for CPU execution engines and migrations away from generated C/C++.
---

# Dynamic-recompiler runtime

The runtime consumes guest bytes and translates executable blocks on demand. There is no offline
guest-code emission step and no generated C/C++ corpus in the build.

## One execution contract

Define one CPU context and one set of memory, exception, timing, and runtime-service interfaces.
Translated blocks, native overrides, the bounded fallback, and the differential harness use that
contract. The interpreter calls the same semantic owners rather than duplicating flag formulas,
memory behavior, exceptions, or call conventions.

## Block lifecycle

- Look up the current guest PC in the code cache.
- On a miss, decode a bounded basic block from the live mapped guest bytes into typed operations or
  IR, validate every instruction, lower it, emit host code, publish the block, and execute it.
- End blocks at control-flow, exception, synchronization, mode, and other architecture-defined
  boundaries. Link direct successors only through patch points the cache can safely revoke.
- Return indirect branches, calls, and exceptional exits through the runtime dispatcher unless the
  target is already proven and guarded.

Unimplemented or invalid instructions fail with the guest PC and decoded bytes or enter the bounded
fallback with that exact reason. They never become a no-op, guessed translation, or silent fallback.

## Code cache and invalidation

The cache owns emitted memory and its lifetime. Enforce write/execute policy without leaving pages
simultaneously writable and executable where the host can avoid it. Cache keys include every mode or
mapping property that changes semantics.

Writes that can alter executable guest bytes, overlay/module replacement, address-space changes, and
relevant cache-control instructions invalidate affected blocks before they can run again. Test both
the ordinary cache-hit path and a mutation that must force retranslation. Whole-cache flushing is a
correctness fallback, not the final design when bounded invalidation is available.

## Bounded interpreter fallback

The zero-argument product always starts in dynarec mode and offers every cold block to the JIT. An
interpreter may execute a block only after the JIT explicitly refuses compilation or safe fetch. The
fallback records a typed reason, guest PC, block count, and instruction count, then returns to JIT
dispatch. It is not a profiling first pass, an asynchronous-compilation bridge, a missing-backend
substitute, or a general compatibility mode.

An interpreter-only mode may provide a correctness oracle and bring-up route only behind an explicit
test/diagnostic target or option. Enforce the dynarec default, bounded entry edges, and telemetry with
build/selector and positive/negative tests. A zero fallback count alone does not prove the boundary.

## Instruction semantics

Use table-driven positive and negative tests for instruction widths, signedness, flags/carry,
overflow, delay slots, alignment, memory faults, floating-point modes, atomics, and return/stack
effects as applicable. Tests execute the shipping decoder and lowered block; a duplicated test-only
implementation proves nothing.

When a differential run finds a mistranslation, fix the shared semantic owner and add the smallest
instruction or block regression that reproduces it. Never special-case the failing address.

## Determinism and diagnostics

Provide block compile/hit/invalidation counters, guest-PC-aware failures, bounded traces, and
fallback blocks/instructions by reason with denominators. Test targets report oracle and
interpreter-only entries separately.
Deterministic inputs and guest time are required for differential verification. Prove diagnostic
positive and negative cases before trusting a silent result.
