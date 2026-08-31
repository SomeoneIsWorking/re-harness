# Project state

## Current focus

None. The initial convergence capability set is verified.

## Capability inventory

| ID | Capability or outcome | State | Factual dependency | Goals |
|---|---|---|---|---|
| S001 | Project-agnostic skills are packaged under the global scope | verified | — | G001, G002 |
| S002 | Port architecture guidance is usable without the recomp stack | verified | S001 | G002 |
| S003 | Reverse-engineering skills are grouped independently of recomp methodology | verified | S001 | G002 |
| S004 | Static-recompiler-only skills are grouped under an explicit recomp scope | verified | S001 | G002 |
| S005 | Reusable CLIs have canonical implementations and stable compatibility entry points | verified | S001 | G003 |
| S006 | Codex, Claude, and generic agent homes converge instructions, skills, and tools through safe relative links | verified | S001, S002, S003, S004, S005 | G001, G002, G003 |
| S007 | The shared tools and installer have positive and negative verification controls | verified | S005, S006 | G001, G003 |
| S008 | Global project guidance requires every maintained project and catalogue to expose a complete stateful intended-feature inventory | verified | S001, S005 | G001, G002 |

## State details and evidence

### S001 — Global skill packaging: verified

Evidence: `skills/global/` contains the project-agnostic packages, each with a
directory name matching its unique `SKILL.md` name; the skill validator and
installer discovery checks pass.

### S002 — Port skill independence: verified

Evidence: `skills/port/game-port-structure/` owns host-side port architecture
without depending on static recompilation, and the package validator passes.

### S003 — RE skill independence: verified

Evidence: `skills/re/` owns selective decompilation, Ghidra plumbing, ordered RE
frontier work, and UE3 pass recovery; every package validates independently.

### S004 — Recomp scope: verified

Evidence: `skills/recomp/` contains only whole-binary static-recompiler
methodology and its focused stages; every package validates independently.

### S005 — Canonical tools and compatibility: verified

Evidence: reusable executables live under `tools/`, skill-local executable names
resolve there through relative links, and the historical root entry points
resolve to the same files.

### S006 — Cross-agent convergence: verified

Evidence: `tools/install_skills.py` creates and verifies relative links from the global instruction,
every categorized skill, and every public shared tool into all supported agent homes plus
`~/repo/AGENTS.md`; it preserves unrelated entries and passes its isolated-home controls.

### S007 — Instrument controls: verified

Evidence: `tests/run.py` exercises finding and not inventing claims, state items, and issues;
validates accepted and rejected state graphs; proves claim baselines are identical across distinct
host timezones; proves the claim checker refuses shallow history rather than manufacturing symbol
movement at the checkout boundary; runs the RE frontier's edit-preservation self-test; proves scoped
cleanup; and proves instruction, skill, and tool installer success and tamper detection.

### S008 — Required feature-state publication: verified

Evidence: the canonical global instructions and `project-state` skill require a complete
`docs/project-state.md` in every maintained project and require portfolios/catalogues to show each
intended capability's `verified`, `partial`, `blocked`, or `missing` state from that authority.
