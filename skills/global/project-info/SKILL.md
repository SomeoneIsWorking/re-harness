---
name: project-info
description: The project information system — ONE query across epic goals, factual project state, atomic issues, ownership, the RE frontier, claims, and instruments, plus ledgers for what was proven and which tools are trustworthy. Use at the start of non-trivial work with `info.py brief TERMS` and when proving, falsifying, or auditing evidence.
---

# The project information system

**The problem this solves:** knowledge gets lost between sessions, and memories don't fix it —
they are per-machine, unsearchable at the moment of need, invisible to subagents, and they record
*conclusions* rather than the evidence a conclusion rests on. So sessions re-derive solved things,
re-chase ruled-out causes, and — worst — keep citing "verified" results that stopped being true.

The project registries answer different levels of question. This skill does **not** replace them:

| registry | keyed by | question it answers | tool |
|---|---|---|---|
| project-goals | epic outcome | why does the project exist, what defines success | `docs/project-goals.md` |
| project-state | capability/outcome | what is verified, partial, blocked, or missing | `docs/project-state.md` |
| issue-catalog | atomic point/symptom | what work, bug, blocker, or dead end is recorded | `catalog.py` → `docs/issues/` |
| codemap | subsystem | who owns X, where it lives, and where it should go | `codemap.py` → `docs/codemap.md` |
| re-frontier | RE step | is this REAL or a hack, what's next | `re_frontier.py` → `docs/re-frontier.md` |

This skill adds the **entry point** and the **two missing ledgers**.

## 1. `info.py brief <words>` — run this FIRST

One query across *every* registry (goals, project state, claims, instruments, issues, codemap,
re-frontier, plus a
pointer to project-local trackers). It exists because three separate CLIs that each must be
*remembered* get consulted by nobody. One command, at task start, every time.

## 2. CLAIMS — what was "proven", and does it still hold

A claim is a result cited as proof: "X is verified", "the gate is 0-diff", "the sweep is clean".
Claims **rot**, and a rotten claim is worse than no claim because work is built on it.

```
info.py claim add "<claim>" --evidence "<how it was proven>" --expires-on "<what would falsify it>" \
                            --depends runtime/recomp/gpu_vk.cpp#render_geom
info.py claim falsify <id> --why "<what disproved it>"     # then re-check everything citing it
info.py claim confirm  <id> --evidence "<re-proof>"        # also resets the staleness baseline
info.py claim list [--falsified]
info.py claim check [--strict] [--verbose] [--selftest]    # has the ground under a claim MOVED?
```

**`--expires-on` is the important field.** A claim with no stated falsifier is a belief, not a
result. Real failures this ledger is built from:
- "item menu is pixel-correct — 0/76800 vs the reference renderer", quoted all day as proof, when
  it only ever proved *we match the reference* — and the reference shared the fault.
- "SBS is 0-diff" cited from a stale run while the gate was actually red.
- "duplicate ownership swept clean", measured against a **stale binary** because the build had
  silently failed.

When you falsify a claim, the tool tells you to grep for who relied on it. Do that — the damage of
a bad claim is always downstream.

### `claim check` — a `holds` claim is UNCHALLENGED, not CURRENT

The issue catalog pulls resolutions forward: a resolved issue *reads* resolved. Claims had no
equivalent — `status: holds` stayed `holds` forever unless a human remembered to falsify it. What
that cost, in one real case:

> **C099** (2026-07-29 02:54): "the logo screens are black because `gpu_vk.cpp`'s `render_geom`
> band 1 passes `clearColorBlack=true` unconditionally." **95 minutes later** two commits rewrote
> exactly that function and both screens were verified rendering. Nobody falsified C099. A week on
> it still read as a live description of the renderer, and it nearly bought a whole native producer
> as a workaround for what was actually a one-line regression somewhere else entirely.

The lever is that **C099's evidence named the code it depended on**. Record that, and "has the
ground under this claim moved?" is a `git log` query that nobody has to remember to ask.

```
info.py claim check          # exit 1 if any claim is stale, exit 2 if there is no corpus to check
info.py check                # the same pass, summarised, for a pre-commit gate
```

- **Scope is symbol-level, not file-level**, and that is what makes it readable rather than noise.
  On the real corpus `gpu_vk.cpp` took 5 commits in C099's window and only 2 touched `render_geom`;
  `native_boot.cpp` took 2 commits in C001's window while `crt0_setup` — what C001 is actually about
  — took **zero**. File granularity flags C001, which still holds. Symbol granularity separates them.
- **The baseline is the commit that ADDED the claim**, not its `created:` date, because a claim is
  usually committed alongside the very change it documents. `claim confirm` resets it.
- **Submodules are indexed too.** The most-cited file in this corpus lives in one; the superproject's
  `git log` sees only pointer bumps, whose dates say nothing about the function.
- **`--depends` is the precise form; prose mining is the migration path.** ~150 claims predate the
  field, so `check` mines file names and function names out of the evidence text. Measured hit rate
  on the spyro corpus: **76 of 129 live claims (59%)**. The other 41% are counted, named, and
  reported as *unchecked* — never as fresh.

**Read the denominator, not the headline.** Every run prints how many claims were checked, how many
record no dependency at all, and what the check still cannot see (evidence resting on a ROM, an
asset, a trace, a tool's behaviour; or a change to a *caller* that invalidates an untouched callee).
"0 stale" alone is indistinguishable from "never looked" — which is the failure this whole check
exists to prevent. An empty or missing claims directory makes it **exit 2 and refuse**, never
"nothing stale, exit 0".

`--selftest` builds a fixture repo and runs the detector against a claim whose cited function was
edited (**must** come back stale), one whose file changed *around* an untouched function (**must**
come back fresh), one naming no code (**must** be counted blind, not fresh), and an empty corpus
(**must** refuse). Run it after touching the detector — it has already caught the symbol resolver
failing closed, which had silently under-reported the blind spot.

**First run on an existing corpus is a backlog, not a bug** — spyro's showed 46 stale. Triage them
with `claim confirm` / `claim falsify`; `--no-stale` exists as a visible opt-out, and reaching for it
permanently means the ledger is being kept for show.

## 3. INSTRUMENTS — can the tool be trusted to show the *other* answer?

Evidence comes from tools, and **a broken tool fails silently**: "no signal" and "instrument
returning nothing" are indistinguishable. Uniform output — all-black, all-zero, all-identical,
"no diff" — is the tell, because real systems are noisy and broken tools are clean.

```
info.py instrument add "<tool>" --validated "<how you proved it can show the OTHER answer>"
info.py instrument distrust <id> --why "<failure mode>"
info.py instrument list [--distrusted]
```

**Validation means feeding it a case that MUST differ and watching it say so.** Six instruments
were caught lying in a single session: a screenshot tool that returned black for every paused frame;
a z-fight ranker using `>` where the rasterizer uses `>=` (reporting the exact inverse); a sweep
whose "reference" leg was a no-op, so it compared a thing to itself; a build check whose grep could
not match the compiler's own error format; a verify mode that suppressed the very overrides it was
meant to gate; and an argument parsed as decimal, so a run checked nothing and came back green.

Each produced *confident, wrong* answers, and each cost hours. Before trusting a number from a tool
you have not personally validated in this session, check here.

## 4. `info.py check`

Reports distrusted instruments and falsified claims still in play, and **exits 1 on a ledger that
contradicts itself** — so it is worth wiring into a pre-commit hook alongside the project's other
gates rather than only running it by hand.

It also folds in the staleness pass above (`--no-stale` opts out), so a gate reports rotting claims
without anyone remembering to ask.

Two self-contradictions it catches, both observed in practice:

- **A killer recorded without flipping its victim.** A claim whose text says "FALSIFIES C016" while
  C016 still reads `[holds]`. This is worse than never recording the refutation: the dead claim keeps
  being served by `brief` with the ledger's authority behind it. (Real case: C017 was filed as
  "FALSIFIES C016" and C016 went on reading `[holds]` for the rest of the session.) The reverse
  phrasing — a holding claim saying it is "falsified by C017" — is checked separately, because one
  pattern for both directions reports the victim as the killer.
- **A claim with an empty falsifier section.** A claim that states no observation which would
  disprove it is a belief, not a result, and the ledger should not launder it into one.

## Storage

`docs/info/{claims,instruments}/NNN-slug.md` — greppable Markdown with small frontmatter, **inside
the repo**, so it travels with the code, reaches other agents that cannot see vendor-local memories,
and survives without this tool. Link or expose the canonical `info.py` through the project's tooling
resolver when collaborators lack the skill; do not fork its implementation.

## The loop

**Start:** `info.py brief <topic>` — and believe it over your instinct about what's already known.
Before *citing* a `holds` claim as fact, `info.py claim check`: `holds` only means nobody has
falsified it yet.
**During:** if a tool gives a suspiciously clean answer, validate it before building on it.
**End:** record what you proved (`claim add`), what you disproved (`claim falsify`), and any tool you
caught lying (`instrument distrust`). Epic intent goes to project goals; capability coverage to
project state; atomic work/findings/dead ends to the issue catalog; ownership and placement to
the codemap. This skill is for the evidence ledgers those cannot hold.
