---
name: codemap
description: Stop code being written twice. Before writing any new function, lambda, constant, type, conversion, formula or magic number, run `codemap.py find` for the concept; it searches every definition in the repo and in every checkout it links to (the framework, Lucent, submodules), which plain grep in a title repo cannot see. Also covers docs/codemap.md, the short module map that says where code goes when nothing exists yet.
---

# Codemap: find before you write

Duplication happens for two reasons. The searcher cannot see the owner: in a game repo the
framework is a gitignored symlink, so `rg` and Grep skip it, and `vendor/` hides Lucent. Or the
searcher uses a different name for the same thing (`expand5`, `scale5to8`, `kVramWidth`,
`kDeviceVramWidth`). `codemap.py find` fixes both. It searches definitions only, across every
linked checkout, by name words, by value and by the comment above the definition.

## Before writing a definition

Run it for every new function, lambda, constant, type, enum value, macro or conversion that might
already exist. That covers anything that is not plainly local to the code being changed:

```
~/.claude/skills/codemap/codemap.py find 'vram width' 1024
~/.claude/skills/codemap/codemap.py find expand5 '5 to 8' 'rgb555'
```

- Give two or three phrasings. Each phrase is one alternative, and every word in a phrase must
  match. Include the literal value of any constant: numbers match by value, so `1024` finds
  `0x400`.
- Results list your own repos first, then third-party checkouts marked `[3p]`.
- **Hit:** use it. If it is almost right, change the owner; never write a second one beside it.
- **Several hits for one concept:** that is an existing duplicate. Merge them into the owner the
  module map names as part of the change, and do not add a further copy.
- **No hit:** write it in the module `docs/codemap.md` names for that layer. Give it a name that
  carries the concept's words. Where the name cannot carry them, add one short comment line above
  it with the words someone would search for, which `find` reads.

## docs/codemap.md: the module map

The map answers what `find` cannot: where code that does not exist yet belongs. It is short and
changes only when modules change:

- One line of dependency direction: which layer may call which.
- One line per module: its path and the concepts it owns, in the words someone would search for.
  For example: `runtime/psx/present/vram_*  VRAM size and geometry, the 555 pixel and its 5-to-8
  expand, texpage and CLUT words`.

It does not list symbols, because `find` reads them from the code and a copied list goes stale. It
never holds goals, state, progress, issues or verification claims. Update a module's line in the
same change that adds, moves, splits or re-owns that module. `codemap.py check` reports cited paths
that no longer exist and top-level dirs the map does not mention. `codemap.py tree` prints line
counts for orientation.
