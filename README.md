# re-harness

The bookkeeping every reverse-engineering port in this tree needs, in one place
instead of one fork per project.

| Tool | Answers |
|---|---|
| `info.py` | **claims** (what was proven, its evidence, and whether it still holds) and **instruments** (which tools can be trusted to produce evidence). `info.py brief <words>` is one query across every registry. |
| `re_frontier.py` | the ordered RE dependency chain — which step is real reverse engineering and which is a **hack** that jumped ahead of it. `next` gives the next ready step, `hacks` the debt list. |
| `catalog.py` | `docs/issues/` — symptom-keyed bugs, root causes and dead ends. Consult *before* re-deriving. |

## Why it is shared

It was forked into every project and drifted: nine copies of `info.py` in seven
distinct versions, ten of `re_frontier.py` in nine, eight of `catalog.py` in
four. The forks were not deliberate variants — they were the same tool improved
in whichever project happened to need the improvement, with none of the others
getting it.

The versions seeded here are the most developed of each, chosen after checking
that each still reads another project's data unchanged. Two improvements that
were stranded in one fork and now apply everywhere:

- `info.py` warns that `[holds]` means *unchallenged, not current*, and prints
  the codemap section.
- `re_frontier.py` reports its denominator — "none of the 36 parsed steps is
  ready" rather than a bare "(none)", so "nothing is ready" and "nothing was
  parsed" stop looking alike.

## How a port uses it

Every tool resolves the project from the **working directory**, never from its
own location, so one copy serves every port. Run them from the port's root.

The tools live here; the **data stays in the port** — `docs/info/claims/`,
`docs/info/instruments/`, `docs/issues/`, `docs/re-frontier.md`.

`pc/xmen2` consumes it through three-line shims in its `tools/` (so every
existing command and doc keeps working) that locate this repo via its
`tools/shared_dir.py`. That resolver refuses and names every path it tried
rather than falling back to a vendored copy — a stale in-tree copy silently
winning is the failure this split exists to end.

## Migration status

Consuming this repo: `pc/xmen2`.

Still on their own forks: `psx/*`, `gameboy/ffa`, `x360/gears1`, `pc/openbl2`,
`zelda3d`. Each needs its output diffed against its fork before switching —
the data format proved compatible for xmen2, but that was checked, not assumed,
and it should be checked per project rather than taken on faith.
