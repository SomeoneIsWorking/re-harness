---
name: project-info
description: The project information system — ONE query across epic goals, factual project state, atomic issues, ownership, the RE frontier, claims, and instruments, plus ledgers for what was proven and which tools are trustworthy. Use at the start of non-trivial work with `info.py brief TERMS` and when proving, falsifying, or auditing evidence.
---

# The project information system

The project registries answer different levels of question. This skill does **not** replace them:

| registry | keyed by | question it answers | tool |
|---|---|---|---|
| project-goals | epic outcome | why does the project exist, what defines success | `docs/project-goals.md` |
| project-state | capability/outcome | what is verified, partial, blocked, or missing | `docs/project-state.md` |
| issue-catalog | atomic point/symptom | what work, bug, blocker, or dead end is recorded | `catalog.py` → `docs/issues/` |
| codemap | subsystem | who owns X, where it lives, and where it should go | `codemap.py` → `docs/codemap.md` |
| re-frontier | RE step | is this REAL or a hack, what's next | `re_frontier.py` → `docs/re-frontier.md` |

This skill adds the **entry point** and the **two missing ledgers**.

## `info.py brief <words>`

Run one query across goals, state, claims, instruments, issues, codemap, and
the RE frontier at the start of non-trivial work.

## Claims

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

`--expires-on` states what would disprove the claim. When it is falsified,
find and recheck dependent claims and documentation.

### `claim check` — a `holds` claim is UNCHALLENGED, not CURRENT

`status: holds` means nobody has falsified a claim; it does not prove the cited
code or evidence is unchanged. Record code dependencies so the checker can find
changes since the claim's commit.

```
info.py claim check          # exit 1 if any claim is stale, exit 2 if there is no corpus to check
info.py check                # the same pass, summarised, for a pre-commit gate
```

- **Scope is symbol-level**, so unrelated edits in the same file do not
  automatically make a claim stale.
- **The baseline is the commit that ADDED the claim**, not its `created:` date, because a claim is
  usually committed alongside the very change it documents. `claim confirm` resets it.
- **Submodules are indexed too.** The most-cited file in this corpus lives in one; the superproject's
  `git log` sees only pointer bumps, whose dates say nothing about the function.
- **`--depends` is the precise form**; older claims can be checked through
  file/function names mined from evidence prose. Unresolved claims are reported
  as unchecked, never fresh.

**Read the denominator, not the headline.** Every run prints how many claims were checked, how many
record no dependency at all, and what the check still cannot see (evidence resting on a ROM, an
asset, a trace, a tool's behaviour; or a change to a *caller* that invalidates an untouched callee).
"0 stale" alone is indistinguishable from "never looked" — which is the failure this whole check
exists to prevent. An empty or missing claims directory makes it **exit 2 and refuse**, never
"nothing stale, exit 0".

`--selftest` checks edited symbols, unaffected symbols, blind claims, and an
empty corpus. Run it after changing the detector. Triage stale claims with
`claim confirm` or `claim falsify`; `--no-stale` is an explicit opt-out.

## Instruments

Evidence comes from tools, and **a broken tool fails silently**: "no signal" and "instrument
returning nothing" are indistinguishable. Uniform output — all-black, all-zero, all-identical,
"no diff" — is the tell, because real systems are noisy and broken tools are clean.

```
info.py instrument add "<tool>" --validated "<how you proved it can show the OTHER answer>"
info.py instrument distrust <id> --why "<failure mode>"
info.py instrument list [--distrusted]
```

Validate an instrument by feeding it a case that must differ and observing the
different result. Check this ledger before trusting a suspiciously uniform
result.

## `info.py check`

Reports distrusted instruments and falsified claims still in play, and **exits 1 on a ledger that
contradicts itself** — so it is worth wiring into a pre-commit hook alongside the project's other
gates rather than only running it by hand.

It also folds in the staleness pass above (`--no-stale` opts out), so a gate reports rotting claims
without anyone remembering to ask.

It also catches contradictory claim links (a claim that falsifies another still
marked `holds`) and claims with no falsifier.

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
