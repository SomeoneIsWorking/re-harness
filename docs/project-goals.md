# Project goals

## G001 — One portable authority for global agent configuration

Maintain a versioned repository that can be checked out on another machine and serve as the single
editable source for every supported agent's global instructions, shared skills, and reusable tools.

Success conditions:

- Codex, Claude, and generic agent homes discover the same instructions, skill packages, and tools.
- Installed entries and the `~/repo` instruction scope point back to this checkout instead of
  becoming independent copies.
- The repository contains no dependency on one operator's absolute home path.
- The instructions stay short enough that the core rules (find the owner, one implementation, prove
  it in the product) are not buried.

## G002 — Applicability is explicit and composable

Separate project-agnostic, game-port, reverse-engineering, and dynamic guest-execution
guidance so a project receives only the methodology relevant to its architecture.

Success conditions:

- Every skill has one category based on the invariant that triggers it.
- Port and RE skills can be used independently of the dynarec stack.
- Skill names remain globally unique when categories are flattened for agent
  discovery.

## G003 — Shared behavior has one implementation

Keep reusable tools authoritative in one location.

Success conditions:

- Skill packages link to canonical tools rather than vendoring copies.

## Constraints and non-goals

- Project-specific knowledge and status stay in each project repository.
- Agent-vendor system skills remain owned by their vendor and are not replaced.
- Categories express applicability, not which project first needed a skill.
- The historical repository name may remain for compatibility; it does not
  constrain the skill taxonomy.
