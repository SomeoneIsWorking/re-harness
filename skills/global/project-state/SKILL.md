---
name: project-state
description: "Consult and maintain the project's factual current-state ledger: the independent capability/outcome inventory of what is verified, partial, blocked, and missing, with evidence and current focus. Use for project status, progress, current state, done/missing, gaps, blockers, or what is being worked on. Epic intent belongs to goals; atomic work belongs to issues; this is not a roadmap or schedule."
---

# Project state — factual delivery coverage

The canonical state document is `docs/project-state.md`. It answers **what can
the project demonstrably do now, what is partial or blocked, what is absent, and
which state item is the current focus?**

This is independent of the goals document. A state item may support one goal,
several goals, or enabling infrastructure. The state inventory remains useful
even when goals are regrouped.

## Model

Each capability or observable outcome has a stable ID such as `S001` and:

- a factual description of the capability/outcome, not an activity;
- state: `verified`, `partial`, `blocked`, or `missing`;
- observable conditions for `verified`;
- evidence links for observed behavior;
- factual dependency IDs where one capability cannot work without another;
- related goal and issue IDs without requiring a one-parent hierarchy.

`Verified` requires observable conditions and durable evidence. `Partial` names
the exact demonstrated subset and remaining gap. `Blocked` names an atomic issue
or unavailable dependency. `Missing` means the capability is absent, not merely
that nobody checked it.

Record exactly one **current focus** state item, or explicitly record that none
is active. Current focus is attention, not a fifth capability state: an item can
be both `partial` and the current focus.

The complete state table is the authoritative answer to **done versus missing**.
It is not a roadmap, release schedule, historical changelog, or ordered list of
future promises.

Every maintained project must have this inventory. Missing project state is a
workflow defect to correct, not permission to substitute a README, codemap,
issue list, source-tree survey, or portfolio copy. The table must cover the
complete intended capability set, including absent and blocked features; an
inventory containing only implemented highlights is incomplete.

When the project changes, replaces, ports, remakes, or wraps an existing
product, add a `## Comparison baseline` section that names the exact original,
upstream, emulated, or prior workflow being improved. This section is required
for every project shown in a portfolio or catalogue; greenfield projects name
the manual, fragmented, or absent prior workflow. Make each independently
stateable user-visible difference its own state item. A catch-all row such as
“modern features” is not an inventory when speed, controls, physics, loading,
presentation, cheats, packaging, or other differences can advance or regress
independently.

Any portfolio, catalogue, status page, or generated project index must present
feature-level state from this authority. Its snapshot must remain traceable to
state IDs and must show `partial`, `blocked`, and `missing` items as plainly as
`verified` ones. When a comparison baseline exists, show it beside the list so
the audience can understand what changes from the original or upstream product.
A project-wide badge may summarize the work but never replace the
intended-feature inventory.

## Validator

Run the bundled validator from the project root:

```
python project_state.py --root .
```

It checks the state vocabulary, unique and resolvable `S` IDs, factual
dependencies, goal links, issue links, exactly one current focus (or explicit
`none`), a detail section for every state item, and state-specific evidence/gap
text. It prints the number of state items, goals, and issue links checked so an
empty corpus cannot look green.

## Boundaries

- Goals are epic-level intent and success conditions; they do not track current
  capability state.
- Project state is the current coverage inventory of observable outcomes.
- Issues are atomic tasks, bugs, investigations, findings, and blockers linked
  to affected state items.
- The codemap says which subsystem owns a responsibility and where it belongs.
- Claims supply evidence for state assertions; they do not define priority.
- The RE frontier is a specialized ground-truth dependency view beneath relevant
  state items, not general project state.

## Consulting and maintaining

Read `docs/project-state.md` before answering project status, current focus,
done/missing, gaps, or blockers. If it is missing, say that no authoritative
project-state inventory exists and create it when the project is in scope; do
not infer state from the codemap, goals, commit history, or a visible TODO.

Update the state document in the same change that demonstrates a capability,
discovers a gap, changes a blocker, falsifies evidence, or changes current
focus. Preserve IDs. Cite claims or direct durable evidence for `verified` and
the demonstrated subset of `partial` items. If evidence is falsified, move the
item back to the honest state and review dependent items.

Run `project_state.py --root .` after every state or issue-link edit and make it
part of the normal verifier when practical.

Keep implementation detail in subsystem docs, historical session narrative out
of the state inventory, and atomic work in `docs/issues/`.
