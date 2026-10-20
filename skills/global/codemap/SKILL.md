---
name: codemap
description: Consult and maintain a project's codemap — the module map that exists so nothing is written twice: every module, every concept it owns, and the exact symbols that implement them, searchable by the words someone would use for the feature. Use before writing any function, constant, type, conversion or formula, and when adding, moving, splitting or re-owning a module. A codemap is not a goals, project-state, task, issue or evidence tracker.
---

# Codemap: a module map against duplication

The codemap exists to stop code being written twice. Someone about to write a helper, constant,
conversion, formula, parser or state transition searches the codemap for the feature. They either
find the symbol that already does it, or they learn that none exists and which module should own
it. A codemap that names subsystems but not the concepts and symbols inside them fails at this job.

Location: `docs/codemap.md`.

## What it contains

One section per module (a directory, or a file group with one owner), in dependency order:

```
## present/vram  —  runtime/psx/present/vram_rect.h, vram_pixel.h
VRAM geometry and the 555 pixel.
- VRAM size, 1024x512, halfwords: `psx::vram::kWidth`, `kHeight`, `kHalfwords`
- point / rect / clip / overlap: `VramRect`, `VramRect::overlaps`, `clipToVram`
- 555 to RGB888, 5-to-8 bit expand: `vram::toRgb888`, `vram::expand5`
- texpage / CLUT word decode: `Texpage::decode`, `ClutWord`
Not here: GP0 command decode (`gpu/gp0`), display-area readout (`present/display`).
```

- **Concept lines** start with the words a searcher would type: synonyms, the hardware name and
  the guest name. They end with the exact public symbols. A grep for `rgb`, `555`, `1024`,
  `expand` or `clut` must land on the owner.
- **Every public symbol that another module may call** is listed. A shared helper missing from the
  map counts as missing from the code, and the next agent will write it again.
- **Hardware facts and magic numbers** (sizes, rates, masks, addresses) are concept lines too,
  because they are the most often redefined.
- **"Not here" lines** name the nearby concepts that live elsewhere, so a near miss still leads to
  the right owner.
- **A one-line dependency direction** at the top: which layer may call which.

There is no prose architecture essay, no annotated tree and no table of subsystem blurbs. Deep
detail goes in the module's own doc, linked from its heading. The codemap never holds goals, state,
progress, issues or verification claims.

## Consulting (before writing code)

1. Before adding any function, constant, type or conversion, grep `docs/codemap.md` for the
   concept under two or three names.
2. On a hit, use that symbol. If it is almost right, extend the owner; never write a second
   version beside it.
3. On a miss, grep the source for the same terms. Code that exists but is absent from the map is
   a map defect: add its line, then use it.
4. Only when both searches miss, write the code in the module the map says owns that layer, and
   add its concept line in the same change.

## Maintaining

Every change that adds, removes, renames or moves a public symbol updates its concept line in the
same commit. When two implementations of one concept are found, the fix is to merge them into the
owner and leave one line, never to record both.

`codemap.py tree` prints the source tree with line counts for orientation. `codemap.py check`
reports referenced paths that no longer exist.

Project-specific mechanics belong in a project-level codemap skill; this skill stays generic.
