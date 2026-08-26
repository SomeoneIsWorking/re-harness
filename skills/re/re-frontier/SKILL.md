---
name: re-frontier
description: Track the ordered reverse-engineering evidence dependency chain toward faithful implementation — which step is grounded in the binary or asset versus a hack that jumped ahead. Use for the RE frontier, hack debt, or next ground-truth-ready RE step. This is not the project's goals or general state inventory; the codemap only maps ownership and placement.
---

# RE frontier — the ordered RE progress tracker

Reverse-engineering a game (or any binary) toward a faithful reimplementation is
a **dependency chain**: you cannot faithfully render the menu logo until you've
RE'd the import-resolution mechanism; you cannot drive AI until the behavior
graph runs. The single most damaging failure mode is **jumping ahead** — faking
the output of a step whose RE isn't done (a magic offset, a C++ clone standing in
for the real mechanism, a native overlay instead of the real UI) — which makes a
broken reimplementation *look* finished and quietly blocks the real work.

**Build the map from BOOT toward the target, not bottom-up from features.** An RE
map is essential on any RE project, and it must be organized as the real
EXECUTION SPINE — the ordered sequence the program actually runs from process
boot to the target behavior — not an arbitrary list of features. When a target
(a menu, a level, a screen) is wrong "in every way," the cause is almost always
that an early stage of that spine was never reproduced (an init/Kismet/Matinee/
setup step), and every downstream symptom flows from that one gap. So: **RE the
whole spine boot→target FIRST**, find the earliest missing stage, and reimplement
from there — do NOT debug individual downstream symptoms. **Debugging an
unimplemented feature is the anti-pattern**: if an output is missing/wrong on a
feature that was never faithfully implemented, that is not a bug to debug, it is a
stub to RE and implement. Reach for a debugger only on a faithfully-implemented
feature that regressed.

This tracker exists to make that distinction impossible to lose. Each RE step
carries a status on one axis: **real RE vs jumped-ahead hack.**

## The RE-project tracking stack

- **project goals** (`project-goals` skill) — *which epic-level outcome matters
  and why.* Keyed by durable intent.
- **project state** (`project-state` skill) — *what capability or outcome is
  verified, partial, blocked, or missing.* Keyed by factual current coverage.
- **codemap** (`codemap` skill) — *which subsystem owns a responsibility and
  where it lives or should live.* Keyed by subsystem.
- **issue-catalog** (`issue-catalog` skill) — *did a past session already hit /
  rule out this atomic point.* Keyed by issue or symptom.
- **re-frontier** (this skill) — *which ordered RE step is real vs a hack, and
  what's the next RE-ready step.* Keyed by RE dependency order.

They compose: goals state the epic outcome, project state records factual
coverage, codemap points at the owner, re-frontier tells which RE dependency is
honestly ready, and the issue catalog holds the atomic work and history.

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

`⛔ hack` is never an acceptable resting state. It is the debt list. A step is
only `re-verified` with **cited ground-truth evidence** (a binary function, a
cooked-asset chain) AND a real verification on real data — never "compiles",
never a vibe.

## The tool: `re_frontier.py` (bundled)

Zero-dependency, stdlib-only. Operates over a greppable markdown roadmap
(`docs/re-frontier.md` by default; override with `$RE_FRONTIER_ROADMAP`).

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

## Bootstrapping in a new RE project

1. Copy `re_frontier.py` into the project's `tools/` (it resolves the roadmap
   relative to itself: `<repo>/docs/re-frontier.md`).
2. `tools/re_frontier.py scaffold` → edit `docs/re-frontier.md` into the real
   ordered chain (steps + deps + honest statuses + cited evidence).
3. Reference it from the project's `AGENTS.md`/`AGENTS.md` alongside codemap and
   issue-catalog ("consult `re_frontier.py next` first; update it — and run
   `check` — in the same commit that changes a step"). Put project-specific
   status vocabulary / area names in a project-level `re-frontier` skill.

**Honesty is the whole value** — same as the codemap. The moment a hack is
mislabeled `re-verified`, the tracker lies and stops protecting against
jumping-ahead, which is the exact failure it exists to prevent.
