---
name: recomp-overrides
description: >-
  Replacing a recompiled function with hand-written native C/C++ in a console→PC port. The
  preferred design is a RUNTIME override wired independently of the recompiler that KEEPS the
  recomp body alive (so it stays diffable and A/B-toggleable), the super-call, scoped
  overrides, dispatch routing, ABI/stack fidelity, and the evidence gate. Use when adding,
  designing, or refactoring native overrides.
---

# Native overrides

Replace a recompiled function with hand-written native C/C++, keyed by the **original
function's entry address**. This is how opaque generated paths become understandable
PC-owned systems and how PC-native behavior gets in.

## Preferred design: runtime override, independent of the recompiler, recomp body kept alive
Register the override into a table that the dispatch consults at call time. The defining
properties:
- **Independent of regeneration.** Adding/removing/toggling an override needs no recompiler
  run — it's runtime wiring, not a codegen step.
- **The recomp body stays compiled in, just bypassed.** Do **not** exclude the overridden
  function from recomp. Keeping its recompiled body is what preserves the two things that
  make a port verifiable:
  1. **A/B the handwritten override against the recomp body** — via a runtime toggle, same
     binary, same run. No regen round-trip.
  2. **Catch recompiler bugs in that function** — the recomp body is still there to run
     through the diff harness against the oracle.

### Avoid: compile-time overrides that exclude the function from recomp
Stripping the generated body at codegen time (rewriting call sites + dispatch to point only
at the override) looks clean — "no point compiling a body you've replaced" — but it
**destroys the recomp body**, so you can no longer A/B handwritten-vs-recomp or check the
recompiler in that function, and every override change forces a regeneration. Independence
from regen, with the body preserved, is the target.

## Patterns
- **Runtime toggle** (per-override or global) selecting handwritten vs recomp body. This is
  the payoff of keeping the body alive: A/B is flip-a-flag, and the body stays diffable.
- **Super-call** — invoke the original recomp body from inside your override without
  re-entering the override. Needed for wrap/augment behavior, for the A/B comparison, and to
  avoid infinite recursion through the dispatch.
- **Scoped overrides** — when the same address means different things in different phases
  (e.g. an override that fires only during gameplay, not in menus).
- **Fixed ABI/signature convention** so all call sites are uniform (a single
  `regs-in → result-out` shape, or a `(ctx)` shape — pick one and keep it).
- **Stack/return fidelity** — an override replacing a function that returns must replicate
  the original's stack effect (e.g. a CPU whose return pops the stack: adjust the modeled
  stack pointer exactly as the original `RET`/`RTS` would).

## Dispatch routing is mandatory
An override only fires if its address is routed in the dispatch path. Functions reached
*only* via indirect/dynamic dispatch (callbacks, jump tables, computed targets) must be
**explicitly seeded** as dispatchable, or the call misses. (See recomp-recompiler › Dispatch.)

## Evidence gate — don't override on a whim
Before adding an override, have: the specific owning entry address, its disassembly, a
concrete reason the generated path is wrong or too opaque, and **output-oriented evidence**
(a wrong sprite/layer/palette/timing/value). An override that only shuffles code without
clarifying ownership or fixing observable behavior isn't worth the surface area.

## Verify
A faithful override must be **state/pixel-identical** to the recomp body — with the runtime
toggle that's flip-and-re-diff in the same run. Enhancement overrides that intentionally
diverge can't be A/B'd against the oracle; they belong on a proven-faithful base (see
recomp-port › Faithful first, then enhance). Never claim it matches without citing the diff.
