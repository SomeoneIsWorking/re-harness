---
name: re-frontier
description: Track the ordered reverse-engineering evidence dependency chain toward faithful implementation — which step is grounded in the binary or asset versus a hack that jumped ahead. Use for the RE frontier, hack debt, or next ground-truth-ready RE step. This is not the project's goals or general state inventory; the codemap only maps ownership and placement.
---

# RE frontier

Faithful behavior depends on an ordered chain of recovered mechanisms. A plausible output can hide
an unimplemented upstream stage. Track the chain so the next task starts at the earliest missing
mechanism, not a downstream symptom.

Build the map along the execution path from boot to the target. If a menu or level is broadly
wrong, check which setup, initialization, or dispatch stage first diverges. Debug a regression in
implemented behavior; reverse-engineer a stage that has never been implemented.

Each step records whether its implementation is grounded in binary or asset evidence, is still in
progress, or is a shortcut awaiting replacement. Project goals, capability state, issues, and
ownership remain in their separate authorities.

## Statuses (the core axis)

```
✅ re-verified    RE'd from ground truth (binary / cooked asset) + implemented + VERIFIED on real data
🟡 re-partial     real RE, but a documented honest gap remains
🔬 in-progress    actively being RE'd/implemented, not yet verified
⛔ hack           a shortcut standing in for absent RE — DEBT, must be removed (no-hacks / no-fallbacks rule)
✍ authored       NOT reverse engineering and never can be: the information is not in the target,
                 so the step is a hand-made judgement (placement, look, framing). Distinguished
                 from ⛔ hack, which IS debt — an authored step has nothing to recover.
⬜ todo           not started
➖ skip-by-design deliberately not implemented (out of scope)
⏸ blocked         COMPUTED: a todo/in-progress step whose deps aren't all satisfied
```

`hack` is debt. A step is `re-verified` only with cited ground-truth evidence and verification on
real data; compiling alone does not qualify.

## Shared tool: `tools/re_frontier.py`

Run the canonical `shared/re-harness/tools/re_frontier.py` from the consuming repository root. It
reads that repository's `docs/re-frontier.md` by default; `$RE_FRONTIER_ROADMAP` overrides the path.
Use the discoverable `re_frontier.py` link when installed. Never copy the shared implementation into
the consumer.

```
re_frontier.py next [--area A]   steps ready to work (all deps satisfied) + hacks to replace  <-- START HERE
re_frontier.py hacks             the debt list — every ⛔ hack standing in for real RE
re_frontier.py tree [--area A]   dependency tree (see exactly where the frontier is)
re_frontier.py blocked           steps waiting on upstream RE
re_frontier.py list [--area A] [--status S]
re_frontier.py show <id>         full entry + each dep's status
re_frontier.py stats             counts by (effective) status
re_frontier.py check             integrity: unknown deps, cycles, re-verified-without-evidence; exit 1 on drift
re_frontier.py scaffold [--area A]   bootstrap an empty roadmap where none exists
re_frontier.py add <id> --title T --area A [--status S] [--deps a,b] [--evidence E] [--where W] [--gap G] [--notes N]
re_frontier.py set <id> status=... gap=... ...   update fields (clean round-trip)
```

## Consulting (START of a task) — read before you re-derive or "jump to output"

1. `re_frontier.py next --area <the area you're working>` — the next RE-ready
   step (all its deps are real). Work THAT, not a downstream step whose RE isn't
   ready — that's how jumping-ahead happens.
2. `re_frontier.py tree --area <area>` — see the whole chain and where ✅ turns
   into ⬜/⛔. That boundary is the frontier.
3. `re_frontier.py hacks` — if the thing you're about to touch is a hack, the job
   is to REPLACE it with the real mechanism, not extend it.
4. Don't re-derive what a step's `evidence`/`gap` already records.

## Maintaining (END of a step) — same commit that changes it

1. Flip the status. **Only `re-verified` with cited evidence + a real
   verification.** If you implemented the real mechanism but haven't verified on
   real data yet, it's `in-progress`, not `re-verified`.
2. When you replace a hack with the real mechanism: set the hack step to the real
   status (or delete it) AND `set` the real step. The hack must not survive its
   replacement (no-fallbacks: existing shortcut paths get REMOVED as the real one
   lands, not left beside it).
3. Add a step for newly-discovered RE work (`add`), wiring its `deps` so the
   chain stays honest.
4. `re_frontier.py check` before committing — fix unknown deps / cycles /
   re-verified-without-evidence. Glance at `hacks` — is the debt shrinking?

## Bootstrapping

Run `re_frontier.py scaffold` from the consumer root, then replace the scaffold with the actual
boot-to-target dependency chain, honest statuses, and cited evidence. Keep project-specific area
names in the project's roadmap; the shared tool and status meanings stay in one place.
