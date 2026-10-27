---
name: project-state
description: "A project's three docs: goals (docs/project-goals.md: why it exists, success conditions, non-goals), state (docs/project-state.md: each intended capability as verified, partial, blocked or missing, one current focus, the comparison baseline) and issues (docs/issues/: one bug, task or dead end per file). Use for project purpose, scope, status, done/missing, gaps, blockers, current focus, or before re-deriving a symptom."
---

# Project goals, state and issues

Read the doc before answering from it. If one is missing, say so and create it when the project is
in scope; never infer it from the codemap, commit history or TODOs.

## Goals: `docs/project-goals.md`

Why the project exists. Each goal has a stable ID (`G001`), a user-visible outcome, observable
success conditions, and constraints and non-goals. It changes only when intent changes, never as
work advances.

## State: `docs/project-state.md`

What the project demonstrably does now.

- One table row per capability or user-visible outcome, with a stable ID (`S001`), its state, its
  factual dependencies and its goals. The table covers the whole intended set, absent items included.
- `verified`: observed in the product. `partial`: names the demonstrated subset and the gap.
  `blocked`: names its issue or missing dependency. `missing`: absent.
- A row is one line. Its evidence is a pointer (an issue, a commit, a warp command), never a
  measurement narrative.
- Exactly one current focus, or `none`.
- `## Comparison baseline` names the original product or prior workflow, and each user-visible
  delta from it (widescreen, loading, controls, platforms, ...) is its own row.

Update it in the change that shows a capability, finds a gap, changes a blocker or moves the focus.
Keep IDs. When evidence is falsified, move the row back to the honest state.

## Issues: `docs/issues/NNNN-slug.md`

One bug, task, investigation or dead end per file. Frontmatter: `id`, `title`, `status`
(`open|investigating|resolved|wontfix|dead-end`), `symptom`, `state_items`, `tags`, `created`,
`updated`.

- Search before investigating: `rg -i '<symptom words>' docs/issues` or `catalog.py search`.
- On resolve, write the root cause and the fix, not "fixed". Record ruled-out paths as dead ends.
- Fix a wrong note instead of adding another. Link affected `S` IDs; a capability change goes in
  the state table, not the issue.
