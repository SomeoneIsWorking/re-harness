---
name: dynarec-overrides
description: >-
  Add or refactor handwritten native functions in a dynamic-recompiler/JIT game port. Covers
  guest-address dispatch, ABI and stack fidelity, scoped activation, calls back into guest code,
  cache interaction, and differential evidence against the ordinary runtime path.
---

# Native overrides in a dynarec port

A native override deliberately transfers ownership of behavior at a known guest entry address to
maintained host code. It is runtime dispatch policy, independent of block compilation.

## Runtime registration

Register overrides in one address-keyed table consulted before ordinary translation dispatch. Make
selection explicit and observable. Adding or toggling an override must not regenerate guest code or
rebuild a title-specific source corpus.

Keep the ordinary dynarec/interpreter path available behind a diagnostic toggle until the faithful
override is proven. This provides same-binary A/B evidence without retaining any static-generated
function body.

## Required contracts

- Use the runtime's canonical CPU context and memory/service accessors.
- Reproduce the guest ABI, argument widths, return values, preserved registers, stack effect,
  exceptions, and timing boundary relevant to callers.
- Scope an override when the same address can have different meaning across overlays, modules, or
  address spaces. The key must include the identity needed to prevent stale selection.
- A call from native code back into guest code enters the normal dispatcher without recursively
  selecting the same override unless that recursion is part of the original behavior.
- Installing or removing an override invalidates or unlinks any cached block whose direct link would
  bypass the new dispatch decision.

## Evidence gate

Require the owning guest address/module identity, disassembly or recovered behavior, the reason for
native ownership, and an observable expected result. Native code is not a workaround for missing
instruction semantics, an unknown crash, or an unmeasured performance suspicion.

Faithful overrides must match the ordinary runtime and oracle on relevant state and output.
Enhancement overrides intentionally diverge only from a separately verified faithful baseline.
