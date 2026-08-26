---
name: project-goals
description: "Consult and maintain a project's epic-level goals: why the project exists, which durable outcomes matter, their success conditions, constraints, and non-goals. Use for project purpose, goals, epics, scope, or strategic outcome questions. Goals do not track current work or what is done/missing; that belongs to project state."
---

# Project goals — epic-level intent

The canonical goals document is `docs/project-goals.md`. It answers **why does
this project exist and which durable outcomes define success?** It is not a
roadmap, progress report, task list, or inventory of code.

If a project already has an equivalent goals document, migrate it to the
canonical path and update its callers. Never leave two apparent authorities.

## Model

Each goal is an epic-level outcome with a stable ID such as `G001` and:

- a concise user-visible outcome;
- why it matters;
- observable success conditions;
- constraints and explicit non-goals;
- links to state items that currently contribute to it.

Goals may overlap, and a state item may contribute to more than one goal. Do not
encode capability progress in the goal. A goal changes only
when product intent changes, not whenever implementation advances.

## Boundaries

- `docs/project-goals.md`: epic-level intent and success conditions.
- `docs/project-state.md`: the authoritative verified/partial/blocked/missing
  capability and outcome inventory.
- `docs/issues/`: atomic work points, bugs, investigations, and blockers.
- `docs/codemap.md`: which subsystem owns a responsibility and where it lives
  or should live.
- `docs/info/claims/`: evidence that an observed statement holds.
- `docs/re-frontier.md`: the specialized ground-truth dependency chain for RE,
  not the general project-state inventory.

## Consulting and maintaining

Read the goals document before answering why the project exists, what outcomes
are in scope, or what overall success means. If it is missing, state that no
authoritative project goals are recorded; do not reconstruct them from the
codemap, TODOs, commit history, or current focus.

Update it in the same change that alters scope, success conditions, constraints,
or non-goals. Preserve stable goal IDs. When implementation progress changes,
update project state or issues instead.
