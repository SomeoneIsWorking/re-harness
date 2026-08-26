---
name: codemap
description: Consult and maintain a project's codemap — the single-page ownership and placement map for which subsystem owns each responsibility, where it lives now, and where new responsibility should go. Use when orienting in a codebase or adding, moving, splitting, or re-owning a subsystem. A codemap is not a goals, project-state, task, issue, or evidence tracker.
---

# Codemap — subsystem ownership and placement

A codemap answers **which subsystem owns this responsibility, where does it
live now, and where should related work go?** It prevents architecture and
placement from being re-derived by grepping. It is keyed by subsystem, not by
goal, state item, issue, or proof.

Canonical location: `docs/codemap.md` (fall back to `CODEMAP.md` only when a
project already uses it; migrate rather than create a second authority).

## What a codemap contains

- A short layer diagram or prose map of the architecture and ownership
  boundaries.
- An annotated source tree, generated with `codemap.py tree`, so existing
  locations are visible without hand-maintained counts.
- An ownership table: `Subsystem | Responsibility | Current/target location |
  Entry point | Deep doc`.
- A “Where does X go?” index from common capabilities to their existing or
  intended owner.

For a missing responsibility, the target location names where it should be
implemented. It does not assert whether the capability is verified or missing.

The codemap must not contain goals, project-state assertions, progress checklists,
current or next work, blockers, exit criteria, definitions of done, issue
queues, or verification claims.

## Information boundaries

- `docs/project-goals.md`: epic-level intent and success conditions.
- `docs/project-state.md`: authoritative verified/partial/blocked/missing
  capabilities and outcomes.
- `docs/issues/`: atomic tasks, bugs, investigations, blockers, and findings.
- `docs/info/claims/`: evidence that an observed statement holds.
- `docs/re-frontier.md`: specialized reverse-engineering dependency state.

When planning or progress is found in a codemap, move it to its correct
authority and leave only ownership and placement. Do not copy it and leave two
sources of truth.

## Tool

The bundled dependency-free `codemap.py` operates from the project root:

```
codemap.py tree [roots...] [--depth N] [--files] [--min-lines N]
    Print an annotated source tree with recursive line and file counts.

codemap.py scaffold [roots...] > docs/codemap.md
    Emit an ownership-table scaffold, annotated source tree, and index.

codemap.py check [--map docs/codemap.md] [roots...]
    Report source subsystems absent from the map and referenced paths that no
    longer exist. Exit 1 on drift.
```

The tool builds and audits Markdown; it never owns architectural decisions.

## Consulting

1. Find the responsibility in the ownership table or “Where does X go?” index.
2. Open the current or target module and entry point.
3. Follow a deep doc only when implementation detail is needed.
4. For capability status, current focus, or done/missing, consult project state
   instead of inferring from file presence, row order, or tree gaps.

## Maintaining

Update the codemap in the same change that adds, removes, moves, splits, or
re-owns a subsystem:

1. Correct the responsibility, owner, current/target location, and entry point.
2. Refresh the generated tree when paths change.
3. Run `codemap.py check` and fix uncovered subsystems or stale paths.
4. Update any machine-readable ownership twin if the project has one.

Do not touch the codemap merely because a state item or issue changed; no
ownership boundary changed in that case.

## Bootstrapping

Run `codemap.py scaffold > docs/codemap.md`, then replace placeholders with
precise responsibilities, current/target locations, and entry points. Wire
`codemap.py check` into the normal verifier when practical. Project-specific
mechanics belong in a project-level codemap skill; this skill remains generic.
