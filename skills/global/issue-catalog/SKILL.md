---
name: issue-catalog
description: Catalogue the project's lowest-level work points — tasks, bugs, investigations, blockers, findings, root causes, and dead ends — in a searchable registry linked to project-state items. Consult it before re-deriving a symptom or starting atomic work. Ships a zero-dependency CLI (catalog.py) to add/search/list/resolve entries. Capability status belongs to project state, not this catalog.
---

# Issue catalog — a symptom-keyed registry of issues, findings & dead ends

The single most wasteful failure mode across sessions is **re-deriving something
a past session already solved, or re-chasing a cause it already ruled out**. The
fix is a durable, *searchable* catalog keyed by **symptom** — you look up "why
does X happen" and find the entry, including the dead ends someone already
walked. This is the read-then-write loop the global AGENTS.md mandates
("Read before you re-derive"); this skill is its reference implementation.

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

# Run from the REPO ROOT. The default dir is relative, so a `cd` into build/ or tools/ used
# to make every read command answer "(no entries)" -- a missing catalog and an empty one are
# not the same thing, and the queries here are exactly where the two look identical. Reads now
# refuse with exit 2 and say what they searched; `add` still creates a catalog, because
# bootstrapping one is a legitimate write.

# Tags: --tags and --tag are the same option and REPEATS ACCUMULATE.
#   --tag reported --tag rendering --tags "a,b"   ->  reported,rendering,a,b
# Before this was fixed, argparse prefix-matched --tag onto --tags with no append action and
# each occurrence silently overwrote the last, so a repeated --tag kept only the final one.
# Nine entries lost their `reported` tag that way and went missing from the queue query, which
# is the one failure the catalog exists to prevent. Filed and unlistable is lost.
catalog.py show 7
catalog.py resolve 7 "p_Masks.B is the emissive mask; zone C = 1-R-G complement"
catalog.py deadend 7 "tried per-vertex tint -> wrong; blend lives in the DXBC shader"
catalog.py note 7 "…" --status investigating
catalog.py reopen 7 "regression after shader change"
```

`--dir` (or `$CATALOG_DIR`) overrides the catalog location. Statuses: `open`,
`investigating`, `resolved`, `wontfix`, `dead-end`. Search weights symptom
highest, then title, tags, body.

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

The tool + skill are global (reusable); the catalog DATA belongs in the project
repo so it is durable and portable to other machines (per AGENTS.md: project
findings belong in the project, not an agent vendor's machine-local memory).
Two ways to run it:

- **Zero-setup**: invoke this skill's `catalog.py` by its path from the project
  root; entries land in `docs/issues/` in the repo. Commit that dir.
- **Portable / for collaborators** (recommended for shared repos): copy
  `catalog.py` into the project's `tools/` and commit it, so anyone without this
  skill can use the same registry. Add a one-line pointer in the project's
  `AGENTS.md`/`AGENTS.md` ("findings registry: `tools/catalog.py` +
  `docs/issues/`; search it before investigating"). If a project already has a
  findings registry under another name (e.g. `docs/findings/`), point `--dir` at
  it instead of making a second one.

## Extending the tool

`catalog.py` is deliberately small — extend it per project when a real need
appears (don't gold-plate up front): e.g. a `link`/related-entries field, a
`--json` output for other tooling, a git-blame/commit backref, or a full-text
index if a catalog grows past what linear scan handles comfortably. Keep it
stdlib-only and keep entries greppable Markdown — the storage format is the
durable part; the CLI is just convenience over it.
