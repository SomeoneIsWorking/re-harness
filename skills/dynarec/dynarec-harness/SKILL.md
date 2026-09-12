---
name: dynarec-harness
description: >-
  Differentially verify a dynamic-recompiler/JIT port against a reference emulator: deterministic
  lockstep state comparison, first-divergence diagnosis, translation coverage, cache
  invalidation tests, headless runs, and frame or audio evidence.
---

# Dynamic-recompiler differential harness

The harness proves that the shipping runtime behaves like the original. It drives the dynarec and a
trusted emulator oracle from the same state and stops at the first meaningful divergence.

## Compare the shipping execution path

- Start both legs from a bit-identical boot or savestate boundary.
- Pin input and replace host-time dependence with a deterministic guest time source.
- Advance at the smallest practical architectural boundary and compare CPU state, relevant memory,
  exceptions/service events, audio state, and presented frames.
- Report the first divergent guest PC, boundary, region, expected value, and actual value.

The runtime leg must include its real dispatcher, decoder, lowered blocks, cache, and invalidation.
A helper that separately evaluates instructions is not evidence for the product.

## Make execution coverage visible

Apply the global runtime telemetry contract to both legs. A JIT-specific gate must fail when the
discriminator was reached only by fallback, even if state matches the oracle. Report a separate
interpreter-only oracle independently and inspect the default selector and bounded fallback entry
edges in gameplay gates.

Add discriminators that must exercise both a cache hit and a retranslation after guest code changes.
Validate that the instrumentation can report the opposite result before trusting a clean run.

## Residual divergences

Record a residual only after proving why it is benign and what observation would falsify that
classification. Timing counters, uninitialized state, and presentation skew are not blanket excuses;
bound the exact field and lifecycle in which they differ.

## Diagnosis loop

1. Reproduce deterministically.
2. Locate the first divergent guest instruction or runtime boundary.
3. Classify the owner: decode/semantic lowering, cache invalidation, CPU state transfer, memory map,
   exception/timing, service emulation, or native override.
4. Fix that owner and add the smallest regression through the shipping path.
5. Re-run the focused discriminator.

## Artifacts

Keep the minimal state dump, frame, or audio sample needed to explain the first divergence. Parity
claims require real title data and must name the exercised interval; boot alone is not parity.
