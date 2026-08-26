# Project goals

## G001 — One portable authority for reusable agent skills

Maintain a versioned repository that can be checked out on another machine and
serve as the single editable source for every supported agent's shared skills.

Success conditions:

- Codex, Claude, and generic agent skill roots can discover the same packages.
- Installed discovery entries point back to this checkout instead of becoming
  independent copies.
- The repository contains no dependency on one operator's absolute home path.

## G002 — Applicability is explicit and composable

Separate project-agnostic, game-port, reverse-engineering, and static-recompiler
guidance so a project receives relevant skills without being treated as a recomp
project by default.

Success conditions:

- Every skill has one category based on the invariant that triggers it.
- Port and RE skills can be used independently of the recomp stack.
- Skill names remain globally unique when categories are flattened for agent
  discovery.

## G003 — Shared behavior has one implementation

Keep reusable registry, validation, and hygiene tools authoritative in one
location while preserving stable compatibility entry points for current users.

Success conditions:

- Skill packages link to canonical tools rather than vendoring copies.
- Existing root-level tool invocations continue to resolve.
- Positive and negative controls exercise the shipping implementations.

## Constraints and non-goals

- Project-specific knowledge and status stay in each project repository.
- Agent-vendor system skills remain owned by their vendor and are not replaced.
- Categories express applicability, not which project first needed a skill.
- The historical repository name may remain for compatibility; it does not
  constrain the skill taxonomy.
