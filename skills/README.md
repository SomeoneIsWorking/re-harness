# Skill taxonomy

The first directory is an applicability boundary, not a project name:

| Scope | Applies when | Skills |
|---|---|---|
| `global` | Any long-lived project or repository | codemap, go-public, issue-catalog, project-goals, project-info, project-state, safe-kill |
| `port` | A game port needs host-side ownership and composition, regardless of recomp/decomp strategy | game-port-structure |
| `re` | Work recovers ground truth from a binary, asset, emulator, or engine | decomp-port, ghidra-re, re-frontier, ue3-native-pass |
| `recomp` | Work depends specifically on whole-binary static recompilation | recomp-harness, recomp-init, recomp-overrides, recomp-port, recomp-recompiler |

Every package directory matches the `name:` in its `SKILL.md`. Skill names are
globally unique across categories because installation flattens them into agent
skill roots.

Reusable executables live under `../../tools/`. A package that exposes one uses
a relative symlink, so the repository retains one source of truth. Resources
used by only one skill stay inside that package.

Install or verify the shared global instruction, skill, and tool links with:

```text
python3 tools/install_skills.py install --replace
python3 tools/install_skills.py check
```
