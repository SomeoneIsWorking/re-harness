# Shared agent-skills codemap

The repository separates applicability from implementation: `instructions/` owns global policy,
categorized skill packages decide when specialized guidance applies, `tools/` owns reusable code,
tests verify the shared interfaces, and installed locations only discover symlinks.

Project intent lives in [`project-goals.md`](project-goals.md) and factual
coverage in [`project-state.md`](project-state.md). This map owns placement only.

## Ownership map

| Subsystem | Responsibility | Current or target location | Entry point | Deep doc |
|---|---|---|---|---|
| Global instructions | One portable policy authority shared by supported agents and the `~/repo` scope | `instructions/` | `instructions/AGENTS.md` | `README.md` |
| Global skills | Project-agnostic goals, state, ownership, issues, information, publication, and process hygiene | `skills/global/` | each package's `SKILL.md` | [`skills/README.md`](../skills/README.md) |
| WebLua guidance | Browser-session discovery, isolated automation, and evidence collection; implementation remains in the separate WebLua repository | `skills/global/weblua/` | `SKILL.md` | WebLua checkout's `README.md` and `server.go` |
| Port skills | Host/game-port architecture independent of guest execution strategy | `skills/port/` | each package's `SKILL.md` | [`skills/README.md`](../skills/README.md) |
| RE skills | Binary, asset, decompiler, frontier, and engine-pass reverse engineering | `skills/re/` | each package's `SKILL.md` | [`skills/README.md`](../skills/README.md) |
| Dynarec skills | Runtime guest execution, dynamic translation, overrides, and differential harness | `skills/dynarec/` | each package's `SKILL.md` | [`skills/README.md`](../skills/README.md) |
| Project registries | This repository's epic intent, factual capability coverage, and ownership map | `docs/` | `project-goals.md`, `project-state.md`, `codemap.md` | — |
| Shared tools | One authoritative implementation of reusable registry and hygiene CLIs, including complete-history enforcement for Git-derived claim evidence | `tools/` | individual Python/executable tools | `README.md` |
| Source-boundary scanner | Data-driven tracked-tree traversal and deterministic source/path/shell-policy reporting; projects own their rule manifests | `tools/source_boundary.py` | `main`, `inspect_tree` | — |
| C++ policy check | Effective clang-tidy/clang-format config audit and compile-database-backed AST scan of global functions, extern declarations, function-local statics, `main` outside `--entry-root` and references to a `--retired-name` outside the entry roots, one process per translation unit in parallel, each unit's result reused while its command and every file it read are unchanged; projects own exact exclusions and ABI entry points | `tools/cpp_policy.py` | `main()`, `inspect_configs()`, `check_database()`, `check_unit()`, `unit_findings()`, `apply_accepted()` | `README.md` |
| Clang AST access | Loads the libclang beside a compile command's Clang driver through ctypes, parses one unit and walks only declarations and requested-name references that expand in first-party files, reporting each with its spelling file, line and scope, plus every file the parse read | `tools/libclang_ast.py` | `parse()`, `library_for()` | `README.md` |
| Unit result cache | Per-unit result files keyed by the caller's unit description and validated by the content hash of every dependency and the file listing of every watched directory | `tools/unit_cache.py` | `UnitCache` | `README.md` |
| Claim baseline time | Owns timezone-aware evidence timestamps and deterministic parsing of legacy baselines so operators and CI agree on staleness. | `tools/info_time.py` | `now_stamp()`, `timestamp_epoch()` | `README.md` |
| Claim history preconditions | Refuses symbol-staleness conclusions when an indexed repository has shallow history | `tools/info_history.py` | `shallow_repositories()` | `README.md` |
| Project brief sources | Search and render project goals, state, issues, codemap, frontier, and local trackers for the information brief | `tools/brief_sources.py` | `emit_external_sources()` | `README.md` |
| Gated LLM swarm | Fan-out of bounded jobs to a free model in detached worktrees, machine-wide flock slots and heavy-gate lock, gate-only acceptance, apply/report/gc; backends one module each | `tools/swarm.py`, `tools/swarmkit/` | `swarm.main()`, `runner.run_jobs()`, `backends.BACKENDS` | |
| Google Play publishing | Play Developer API releases and reads through a service account (JWT signed by openssl through a pipe), and the console's web UI through one shared headless WebLua session addressed by package; account facts live outside the repo | `tools/play_api.py`, `tools/play_console.py`, `skills/ship/play-console/` | `play_api.main()`, `play_console.Session` | `skills/ship/play-console/SKILL.md` |
| Global-surface installer | Portable instruction, skill, and tool links for Codex, Claude, generic agents, and `~/repo` | `tools/install_skills.py` | `main()` | `README.md` |
| Compatibility entrypoints | Existing consumers that invoke root tool names | root symlinks to `tools/` | `info.py`, `catalog.py`, `re_frontier.py`, `project_state.py` | `README.md` |
| Verification | Positive and negative controls for every shared instrument and installer | `tests/run.py` | `main()` | — |

## Source map

```text
skills/
├── global/     project-agnostic skills
├── port/       port architecture independent of guest execution strategy
├── re/         reverse-engineering-specific skills
└── dynarec/    runtime guest execution and dynamic-translation skills
instructions/   canonical global agent instructions
tools/          canonical reusable CLI implementations
tests/          cross-skill/tool behavior checks
docs/           repository goals, state, and ownership
*.py            stable compatibility symlinks into tools/
```

## Where does new work go?

- Guidance used by any project goes in `skills/global/`.
- Port architecture that applies regardless of binary translation strategy goes
  in `skills/port/`.
- Ground-truth recovery from binaries/assets goes in `skills/re/`.
- Guidance whose invariant depends on runtime interpretation or dynamic translation goes in
  `skills/dynarec/`.
- A reusable executable used by more than one skill lives in `tools/`; skill
  packages link to it instead of copying it.
