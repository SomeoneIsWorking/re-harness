# Codemap

Dependency direction: `instructions/` names skills; skills link to `tools/`; `tools/install_skills.py`
links all three into agent homes. Nothing in `tools/` reads this repo's docs.

| Module | Owns |
|---|---|
| `instructions/AGENTS.md` | global agent rules: problem workflow, docs, communication, code, C++, tooling, repository |
| `skills/global/` | codemap find and module maps, go-public history audit, project goals/state/issues, kill by PID, WebLua browser automation |
| `skills/ship/` | release, CI, packaging, signing, Android, Play Console |
| `skills/port/` | port structure and layers, first-run game-file setup, port release, dynamic scan and test program |
| `skills/re/` | Ghidra headless decompile/xrefs/loaders, RE frontier, UE3 native passes |
| `skills/dynarec/` | dynarec port method, bring-up and oracle compare, JIT runtime, native overrides |
| `tools/codemap.py` | codemap find: definitions by name, value and comment across linked checkouts; duplicate groups |
| `tools/catalog.py` | issue catalog: add, search, resolve `docs/issues/` entries |
| `tools/re_frontier.py` | RE frontier: ordered RE steps, hack debt, preserving in-place edits of `docs/re-frontier.md` |
| `tools/cpp_policy.py` | C++ ownership scan: global functions, extern, block statics, stray main, retired calls; config audit |
| `tools/libclang_ast.py` | libclang ctypes binding: parse a unit, first-party declarations, qualified watched references |
| `tools/unit_cache.py` | per-unit result cache keyed by command and every file the parse read |
| `tools/go_public.py` | history audit: assets, home paths, private references; filter-repo rules |
| `tools/scratch_gc.py` | scratch cleanup honouring `.scratch-keep` |
| `tools/cleanup-files` | remove an explicit list of in-tree files |
| `tools/play_api.py`, `tools/play_console.py` | Google Play publishing: API tracks and uploads, console web UI through WebLua |
| `tools/install_skills.py` | installer: instruction, skill and tool links into agent homes, retired-link removal |

## Where does new work go?

- Guidance used by any project goes in `skills/global/`.
- Port architecture that applies regardless of binary translation strategy goes in `skills/port/`.
- Ground-truth recovery from binaries/assets goes in `skills/re/`.
- Guidance whose invariant depends on runtime interpretation or dynamic translation goes in
  `skills/dynarec/`.
- A reusable executable used by more than one skill lives in `tools/`; skill packages link to it
  instead of copying it.
