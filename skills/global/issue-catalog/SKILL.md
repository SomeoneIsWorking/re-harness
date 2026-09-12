---
name: issue-catalog
description: Catalogue the project's lowest-level work points — tasks, bugs, investigations, blockers, findings, root causes, and dead ends — in a searchable registry linked to project-state items. Consult it before re-deriving a symptom or starting atomic work. Ships a zero-dependency CLI (catalog.py) to add/search/list/resolve entries. Capability status belongs to project state, not this catalog.
---

# Issue catalog — a symptom-keyed registry of issues, findings & dead ends

A searchable symptom catalog records causes and ruled-out paths so later work
does not re-derive them.

It is the lowest-level project-work registry: each entry is one actionable
point, bug, investigation, blocker, finding, or dead end. Link it to affected
state-item IDs when known. The codemap separately answers which subsystem owns
the work and where it belongs; project state separately answers what is
verified, partial, blocked, or missing.

## The tool: `catalog.py` (bundled with this skill)

A single-file, dependency-free (stdlib-only) Python CLI in this skill's
directory. It stores one Markdown file per entry under a catalog dir (default
`docs/issues/`), each with a small frontmatter block — so entries stay
human-readable and **greppable even without the tool**. Run it from the project
root; the catalog data lives IN the project repo so it travels with the code.

```
catalog.py add "shader colors wrong" --symptom "creature meshes render grey" \
    --state-item S014 --tags render,material --status investigating
catalog.py search "grey enemy color"     # rank by symptom>title>tag>body match, with snippets
catalog.py list --status open            # or --tag render / --state-item S014

catalog.py show 7
catalog.py resolve 7 "p_Masks.B is the emissive mask; zone C = 1-R-G complement"
catalog.py deadend 7 "tried per-vertex tint -> wrong; blend lives in the DXBC shader"
catalog.py note 7 "…" --status investigating
catalog.py reopen 7 "regression after shader change"
```

`--dir` (or `$CATALOG_DIR`) overrides the catalog location. Statuses: `open`,
`investigating`, `resolved`, `wontfix`, `dead-end`. Search weights symptom
highest, then title, tags, body. Run from the project root: reads refuse with
exit 2 when the catalog is missing; `add` can create it. Repeated `--tag` and
`--tags` options accumulate.

## The loop (use it every investigation)

1. **Before investigating** a non-trivial symptom: `catalog.py search "<the
   symptom in your words>"`. If there's a hit, read it first — it may hand you
   the root cause, the fix, or the dead ends already ruled out. (Also grep the
   catalog dir directly; it's plain Markdown.)
2. **While investigating**: `add` an entry early (status `investigating`) so the
   symptom + what you're trying is captured as you go, not reconstructed later.
3. **On resolving**: `resolve <id> "<root cause + fix, not just 'fixed'>"`. State
   WHY it happened, not only what changed.
4. **On ruling something out**: `deadend <id> "tried X -> broke/ruled out
   because Y"`. Negative results save the next session as much as positive ones.
5. **Keep it honest & self-correcting**: if you later find a note was wrong,
   `note`/`reopen` and FIX it — a confidently-wrong entry sends the next session
   down the same dead end (worse than none).

Issues are atomic points, not state items. If one entry describes several
independently completable outcomes, split it. If resolving it itself defines a
project-visible capability change, create or update a project-state item and
link the issue rather than promoting the issue catalog into the state ledger.
Use repeatable `--state-item S014` links; the relation does not determine issue
priority or state.

## Adopting the catalog in a project

Keep catalog data in the project under `docs/issues/` and invoke the canonical
shared `catalog.py` from the project root. Expose it through the project's
shared-tool resolver for collaborators; do not copy the implementation. If a
project already has a findings registry under another name, point `--dir` at it
instead of making a second one.

## Extending the tool

Extend the shared CLI for a demonstrated general need. Keep entries greppable
Markdown; their storage format is the durable contract.
