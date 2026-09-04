# Project state

## Comparison baseline

The baseline is duplicated user-maintained instructions, skills, and command-line tools scattered
across individual agent homes and project copies. re-harness makes one portable repository the
authority, installs relative discovery links for supported agents, and verifies both successful and
refused behavior.

## Current focus

No capability gap is currently active; S009 completed the portable-tooling verification scope.

## Capability inventory

| ID | Capability or outcome | State | Factual dependency | Goals |
|---|---|---|---|---|
| S001 | Project-agnostic skills are packaged under the global scope | verified | — | G001, G002 |
| S002 | Port architecture guidance is usable without the dynarec stack | verified | S001 | G002 |
| S003 | Reverse-engineering skills are grouped independently of runtime-execution methodology | verified | S001 | G002 |
| S004 | Dynamic guest-execution skills replace the removed generated-source methodology | verified | S001 | G002 |
| S005 | Reusable CLIs have canonical implementations and stable compatibility entry points | verified | S001 | G003 |
| S006 | Codex, Claude, and generic agent homes converge instructions, skills, and tools through safe relative links | verified | S001, S002, S003, S004, S005 | G001, G002, G003 |
| S007 | The shared tools and installer have positive and negative verification controls | verified | S005, S006 | G001, G003 |
| S008 | Global project guidance requires every maintained project and catalogue to expose a complete stateful intended-feature inventory | verified | S001, S005 | G001, G002 |
| S009 | Hosted CI exercises the portable repository on every applicable platform | verified | S007 | G001, G003 |

## State details and evidence

### S001 — Global skill packaging: verified

Evidence: `skills/global/` contains the project-agnostic packages, each with a
directory name matching its unique `SKILL.md` name; the skill validator and
installer discovery checks pass.

### S002 — Port skill independence: verified

Evidence: `skills/port/game-port-structure/` owns host-side port architecture
without depending on dynamic translation or another game repository, and the
package validator passes.

### S003 — RE skill independence: verified

Evidence: `skills/re/` owns selective decompilation, Ghidra plumbing, ordered RE
frontier work, and UE3 pass recovery; every package validates independently.

### S004 — Dynamic guest-execution scope: verified

Evidence: `skills/dynarec/` contains runtime translation, initialization,
override, and differential-verification guidance; the former generated-source
skill family is absent and every replacement package validates independently.

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
intended capability's `verified`, `partial`, `blocked`, or `missing` state from that authority. They
also require projects derived from an existing product to name the comparison baseline, split each
independently stateable user-visible delta into its own item, and display that baseline beside the
portfolio feature list. Portfolio and catalogue entries must provide a baseline even for greenfield
projects, using the prior manual, fragmented, or absent workflow as the comparison.

### S009 — Cross-platform hosted verification: verified

Evidence: the pinned workflow runs the canonical full-history self-test on Linux, Windows, and macOS and
enables real symbolic-link checkout on Windows. GitHub Actions run `33881539583` passed all three
jobs from commit `951b2ba`; its first Windows execution also falsified locale-dependent fixture and
subprocess handling before the UTF-8 boundary was corrected. Android is inapplicable here: this
repository ships host-side Python instructions, skills, and maintenance tools, not an Android
runtime, package, or native library.
