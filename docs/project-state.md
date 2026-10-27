# Project state

## Comparison baseline

Before this repo, instructions, skills and tools were copied into each agent home and project and
drifted. Now one checkout is the authority and every agent home links to it.

## Current focus

none

## Capability inventory

| ID | Capability or outcome | State | Factual dependency | Goals |
|---|---|---|---|---|
| S001 | Project-agnostic skills are packaged under the global scope | verified | — | G001, G002 |
| S002 | Port architecture guidance is usable without the dynarec stack | verified | S001 | G002 |
| S003 | Reverse-engineering skills are grouped independently of runtime-execution methodology | verified | S001 | G002 |
| S004 | Dynamic guest-execution skills replace the removed generated-source methodology | verified | S001 | G002 |
| S005 | Reusable CLIs have one implementation under `tools/`, linked from skill packages | verified | S001 | G003 |
| S006 | Codex, Claude, and generic agent homes converge instructions, skills, and tools through relative links | verified | S001–S005 | G001, G002, G003 |

## Evidence

- S001–S004: `skills/README.md` lists each package under its scope; `install_skills.py check`
  discovers every package by its `name:`.
- S005: skill packages hold relative links into `tools/` (`codemap.py`, `go_public.py`,
  `re_frontier.py`).
- S006: `uv run --no-project python tools/install_skills.py check` reports 0 problems.
