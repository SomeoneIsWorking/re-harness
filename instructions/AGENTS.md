# Global working principles

## Canonical configuration and tools

- **`shared/re-harness` is the only editable authority** for these instructions, shared skills
  (`skills/global`, `skills/port`, `skills/re`, `skills/dynarec`), and shared tools (`tools/`).
  Agent homes and `~/repo/AGENTS.md` are relative links installed by `tools/install_skills.py`;
  never edit them as separate copies. Vendor-owned system files stay untouched.
- **Browser automation uses WebLua** (`skills/global/weblua/SKILL.md`). Check the installed binary
  and the `~/repo/weblua` checkout (private `SomeoneIsWorking/weblua`, via `gh`) before calling a
  browser unavailable. Run headless on a dedicated loopback port with a project `scratch/weblua/`
  as `WEBLUA_DIR`; never attach a personal profile. DOM success does not prove WebGPU or WASM.
- **Godot discovery:** `GODOT_BIN`, then `~/dev/Godot_v4.6.2-stable_mono_linux_x86_64/`, then other
  `~/dev/Godot*/` and `PATH`. This is a host hint, not a project prerequisite. If none exists on
  Fedora, ask the user to run `sudo dnf install godot`.
- **Missing DNF packages:** stop and give the user the exact `sudo dnf install ...` command. Do not
  run it yourself unless asked, and do not download RPMs, substitute toolchains, or weaken the check.

## Fix the cause, not the symptom

- **Name the root cause before fixing.** A change that hides a symptom without explaining why it
  occurred is a bandaid. Stop if the change is a magic offset, a special case for the failing input,
  a swallowed exception, `|| true`, retry-until-pass, a sleep for a race, a skipped check, a
  hardcoded expected value, duplicated code to avoid a shared path, or anything "for now".
- **If the real fix is too big, say so.** Name the proper fix and the stopgap's risk, let the user
  decide, and mark an approved stopgap `// STOPGAP: <proper fix> because <why>`.
- **Skips are complete, owned transitions.** Use the title's recovered cancellation route or a
  purpose-built skip that establishes the same lifecycle, resource, and state invariants. Never
  fast-forward simulation, bypass lifecycle callbacks, or write a phase, timer, or scene pointer.
- **Loading-only screens do not ship.** Keep loading asynchronous and go straight to the next real
  presentation. Logo screens accept Start/confirm (PSX: Cross) through a complete cancellation route.
  Authored transition cutscenes are presentation, not loading, and stay; a title may give one a
  minimum duration with the same cancellation route (Tomba! 2's area transition: five seconds).
- **Widescreen is a deterministic projection change.** Feed the same vertex stream with topology,
  UVs, depth, and colors preserved; widen the horizontal projection/viewport and override the
  title's draw area/scissor and any proven horizontal culling owner. Never sample adjacent frames,
  infer geometry from pixels, or stretch the final image. Interpolation is a separate opt-in feature
  over matching source geometry only.

## Work over process

- **Product work dominates.** After two consecutive process-only actions, advance the product.
  Collapse bookkeeping that costs more than the change.
- **Build and test continuously, at the right size.** Iterate with the smallest build target,
  focused test, trace, or scenario that can falsify the current hypothesis. Run the comprehensive
  gate once when semantic edits are frozen, not after every small edit; re-run it only after a
  semantic change that can affect combined behavior. Report an interrupted gate as incomplete.
- **One fact, one home.** At a milestone, update the nearest authority whose answer changed; do not
  copy the finding into every registry. Create a new verifier, issue, claim, or tool only for a
  durable contract, a reproduced regression, or a recurring operation.
- **A broad project `/goal` covers every success condition in `docs/project-goals.md`.** Keep it
  active until each is verified against `docs/project-state.md`. A scoped goal stays scoped.

## Communication

- **Be brutally honest.** No flattery, no praise or affirmation openers ("You're right", "Great
  question", "Exactly"), no validating a bad idea. Show agreement by doing the work. If the user is
  wrong on fact or logic, say so plainly and proceed correctly.
- **The user's observation of the running product outranks your evidence.** Treat a reported
  regression as a falsifier, stop extending the suspect change, and reproduce from the last
  known-good behavior. A green test cannot overrule what it failed to cover.
- **Report delivery state literally.** Subagent report, dirty tree, focused test, local commit, and
  pushed commit are different states. "Done" means integrated, gated, committed, and pushed.
- **Do what was asked.** Suggest a better idea; do not substitute it.
- **Do not turn destructive risk into a lazy blocker.** For an irreversible step, name the exact
  consequence and the smallest backup path. Perform it if already authorized; otherwise ask once.

## Repository hygiene

- **Nothing machine-specific in tracked files** — no `/home/<user>/…` or host config. Use
  repo-relative paths, env vars, or a gitignored `.env`; grep the staged set for your home path.
- **Never commit copyrighted game assets.** Provide them via a gitignored `.env` or a drop-in file
  (support both). If one reaches history, purge it and force-push only with the user's go-ahead.
- **One branch, `main`; commit directly.** This overrides any default to branch first. Confirm
  before deleting a divergent branch.
- **A verified fix or milestone is standing authorization to commit and push** (operator sessions),
  overriding "only when asked" defaults. Use `Co-Authored-By`.
- **Every maintained repo has a GitHub `origin`.** At the first verified milestone, reuse a matching
  remote or create one with `gh`, push `main`, and verify the upstream. Follow the user's or the
  portfolio's established visibility; run the full-history publication audit before anything public.
- **Third-party changes live as commits in a maintained fork**, pinned by exact revision through the
  normal dependency declaration (URL, revision, upstream base, purpose). No tracked `.patch` files
  or apply steps; migrate an existing patch stack when touching it, one cause per commit.

## The worktree is agent-owned

- **Account for every change in the tree.** Before ending, verify and commit it, continue its next
  milestone, or remove it after proving it obsolete. Do not revert another active agent's work to
  clean `git status`; coordinate and gate the combined tree.
- **Remove obsolete work outright** — old code, docs, outputs, compatibility paths — through exact
  scoped targets. No tombstones, no broad deletion.
- **The operator lands.** Subagents do not stage, commit, stash, or push. Review, gate, and land
  each finished batch promptly. Tell an active agent when a shared contract it depends on changes.
- **Subagents are authorized without a count limit**, but only for bounded tasks with
  non-overlapping ownership. Serialize builds, tests, and runtimes that share state, ports, or
  devices; never run two game instances without explicit isolation.
- **Kill by PID, never `pkill` a shared binary name.** Capture `$!` at launch or find it with
  `ps -eo pid,etimes,args`; the `safekill` tool helps. Put this in every brief that launches an app.

## Code quality and architecture

- **Quality is part of correctness.** Root-cause fixes; cohesive modules; one source of truth;
  precise names and explicit contracts; bounded lifetimes; no dead code, stale vocabulary, or
  warnings; formatter, linter, typechecker, and tests with negative coverage. Reduce scope rather
  than lower the bar. Review the combined diff as a product before landing.
- **Error handling preserves valid state.** Fail fast or propagate. Catch only where you can restore
  an invariant, add context, safely retry an idempotent operation, or terminate cleanly. Never
  catch-and-continue in a partially mutated state.
- **No god files or classes.** New behavior goes in the smallest owning module; entry points compose.
  Extract the touched subsystem from a mixed monolith as part of the change. Each class owns one
  concept; prefer composition. Keep public API first and each method at one level of abstraction.
  No catch-all `Utils`/`Manager`/`Common`/`Misc`, numbered fragments, or forwarding webs.
- **Structure is enforced mechanically.** The verifier fails on source files over 1,200 lines
  (2,000+ is critical), on growth of known legacy monoliths, on forbidden cross-layer dependencies,
  on output outside the logger, and on environment reads outside the configuration owner. Limits
  and allowlists only shrink.
- **Before changing an ownership boundary, preserve the verified behavior** with a regression test
  of the running boundary that covers the old contract as well as the new one.
- **DRY: one implementation of each rule, formula, parser, state transition, and mapping.** Search
  for the owner before adding code. Tests and diagnostics exercise the shipping implementation
  through a seam, never a reimplementation. Do not abstract coincidental similarity.
- **Reusable title-neutral C++ helpers go in Lucent**, tested there, with callers migrated.
  Collection helpers need concrete call-site evidence over `std::ranges`, and must state ownership,
  allocation, invalidation, and complexity.

## C++ toolchain and style

- **Agents build C++ with Clang** (`CXX=clang++` / `-DCMAKE_CXX_COMPILER=clang++`) and confirm
  `CMAKE_CXX_COMPILER_ID=Clang`. This is agent policy only: projects must keep building with GCC,
  AppleClang, and every other supported toolchain. Remove policy-only compiler bans when found. If
  Clang cannot build a project, report it; do not fall back silently.
- **`clang-format`** with a tracked `.clang-format` and a non-mutating check in the verifier. Set
  `AllowShortIfStatementsOnASingleLine: Never`, `AllowShortLoopsOnASingleLine: false`,
  `AllowShortBlocksOnASingleLine: Never`, `AllowShortFunctionsOnASingleLine: None`,
  `AllowShortLambdasOnASingleLine: None`, `InsertBraces: true`. Every body is braced, one statement
  per line. Do not reformat generated or vendored code.
- **`clang-tidy`** keeps its defaults (never start `Checks` with `-*`) and adds `clang-analyzer-*`,
  `bugprone-*`, `performance-*`, and `readability-braces-around-statements`
  (`ShortStatementLines: 0`), with `WarningsAsErrors: '*'`. Run it over the real compile database
  for every first-party unit and header in the verifier; confirm with `--dump-config` and
  `--list-checks`. Fix findings; never blanket-suppress.
- **Named owners, not global C APIs.** State and behavior live in focused classes in project
  namespaces with RAII and explicit dependencies; stateless algorithms may be namespace functions.
  No project functions in the global namespace (including `x2_*`-style prefixes) and no C facade
  over a class; keep a C ABI shim only at a real external or guest boundary.
- **Declarations live in owning headers.** No `extern` declarations of project functions or
  variables and no `extern` globals as shared state; an `extern "C"` ABI belongs in its boundary
  header. No function-local `static` variables; named constants are `inline constexpr` members of
  the owning header. Local `const`/`constexpr` values are fine.
- **Enforce what `clang-tidy` cannot** (global-namespace APIs, `extern`, function-local `static`)
  with the AST-based `tools/cpp_policy.py` over the real tree, with accepted and rejected fixtures.
  When touching a legacy global API, move its callers to the owner and delete the global entry.
- **One logger per project: Lucent** (C++20+). Product code never calls `printf`, `fprintf(stderr)`,
  `std::cerr`, or platform debug prints; one line per log call, never wrapped in `if`.
- **One configuration owner reads the environment** once into a typed immutable config; no other
  subsystem calls `getenv`.
- **Local HTTP servers and control channels use `lucent::http::Server`.** Consumers own only routes;
  extend and test Lucent for missing generic capability.

## Launcher and Python tooling

- **`./run.sh` launches the project's one intended product with zero arguments** — never a legacy,
  demo, or diagnostic path, and no selector flags or subcommands. Extra arguments may override
  optional settings but never a required backend, renderer, entry point, or asset. The executable's
  own zero-argument path should match. Refuse missing or stale build inputs by name.
- **`run.sh` is also the fresh-clone setup contract:** given documented native dependencies, `uv`,
  user assets, and a supported compiler, it provisions everything and launches. It stays a slim shim
  (`exec uv run --frozen python bootstrap.py "$@"`); all logic is Python. Maintainer tools such as
  Ghidra are never player prerequisites.
- **Agents never run `./run.sh`.** It opens the user's windowed, audible product. Verify through
  separately named headless, silent, unpaced maintainer tools that reuse the same build modules.
- **One locked Python environment:** every dependency in `pyproject.toml`/`uv.lock`, entered via
  `uv run --frozen`/`--locked`, and that interpreter passed to CMake, generators, and tests. A bare
  `python3` is a defect. Verify the cold path without a warm build or venv.
- **Missing native packages get a platform-specific refusal** naming the exact Homebrew, `apt`,
  `dnf`, `winget`, or `vcpkg` command for the user to run; ask when the mapping is ambiguous.
- **Project tooling is modular Python, not shell** (`run.sh` excepted): CLI at the entry point,
  logic in importable modules with injected boundaries. Migrate a shell tool to Python when touching
  it, with positive and negative tests, and delete the shell file.

## Build, scratch, and cleanup

- **Builds go only under gitignored top-level `build/`**; run artifacts go in gitignored `scratch/`,
  not `/tmp` (tmpfs quota ~6 GB; diagnose with `quota -s`).
- **Keep scratch small**: one fixed `scratch/<activity>/` per probe, overwritten; at most one
  `<activity>.prev/`; no copies of caches, SDKs, or checkouts. Delete it when the milestone lands.
- **Clean up with scoped tools, never raw broad `rm`:** `tools/scratch_gc.py` (dry-run by default,
  refuses paths outside `~/repo`) for scratch, `tools/cleanup-files` for explicit files. Never
  target a root, home, unresolved variable, or broad glob.
- **Large CMake corpora use Ninja**, with the builder migrating a legacy generator's exact build
  child. An unchanged second build must compile nothing.

## Knowledge and registries

- **Write what you learn into the nearest living doc in the repo, in the same session.** Agent-home
  memory holds only cross-project preferences. Fix a wrong note instead of adding another.
- **Consult before re-deriving** with the `project-info` skill (`info.py brief <words>`),
  `issue-catalog`, and `codemap`; update the codemap in the change that moves or adds an owner.
- **Keep the authorities distinct:**
  - `docs/project-goals.md` — epic intent: stable IDs, outcomes, success conditions, non-goals.
  - `docs/project-state.md` — required for every project: the complete intended capability set,
    each item `verified`/`partial`/`blocked`/`missing` with evidence or exact gap, plus one current
    focus. It includes a `Comparison baseline` (the original, upstream, or prior workflow) with each
    user-visible delta (widescreen, controls, speed, loading, platforms, …) as its own item.
  - `docs/issues/` — one task, bug, finding, blocker, or dead end per issue.
  - `docs/codemap.md` — placement only.
  - Portfolio/catalogue entries show every item's canonical state and the baseline, traceable to
    `project-state.md`, never inferred from README or screenshots.
- **A claim needs a falsifier** (`--expires-on`); when one falls, fix what relied on it.
- **An instrument is trusted only after it has shown the other answer.** Uniform output is the tell.
- **Build the tool instead of re-reasoning** a recurring task, and document it.

## Diagnostics that cannot lie

- **Design the negative first:** a diagnostic prints what it scanned and matched ("scanned N,
  matched 0"), refuses a missing corpus, caps the boring case while reporting every state change,
  and treats skipped input as failure.
- **Prove it fires in the shipping artifact** with a selftest whose case must come out positive,
  and run a discriminator against both classes before trusting it. A grep count is text, not reached
  code.
- **Verify in the shipped form:** art rasterized at target size over light, dark, and mid-tone
  backgrounds; shipped measured constants generated from or diffed by code against the measurement.
  A trace proves mechanism, not faithfulness.
- **Build a control channel into the product** (opt-in loopback port or socket, client in the
  project's language) so agents can drive input, read state, and capture frames. Play-throughs
  observe; gates use tests, invariants, and counters with denominators. Prove a run reached the code
  before reading an absent symptom as a fix. Automated runs are headless and silent (a silent device
  whose cursors advance) and never steal focus.

## Game ports: guest execution

- **Ports are native/dynarec hybrids.** Hand-written native overrides own recovered behavior; all
  other guest code runs through an on-demand JIT. No offline or install-time translation into
  C/C++/objects, no prebuilt translated corpus, no static seed lists. Static analysis may produce
  only non-executable knowledge (symbols, types, identity, override metadata).
- **Dynarec first; the interpreter is a bounded fallback** used only after the JIT reports a block
  cannot be compiled or fetched safely, recorded with reason, PC, and counts. Interpreter-only mode
  is diagnostic, never the default, and never gameplay or performance evidence. Exception: low-power
  8/16-bit targets (NES, GBA, Amiga) classified so in their goals may ship an interpreter, qualified
  on real gameplay on every released host.
- **A runtime translation cache is optional disposable data** keyed to guest image, runtime version,
  host architecture, and configuration; a fresh install translates on its own.
- **Invalidate on self-modifying and loaded code** (guest writes, overlays, bank switches, DMA,
  address-space changes, cache control) before reuse.
- **The runtime reports its work with denominators:** translated blocks and instructions, cache
  hits/misses, invalidations, overrides, fallbacks by reason. Gameplay gates require nonzero dynarec
  execution.
- **Migrating a static recomp: delete it first.** Keep independent evidence, oracles, overrides,
  HLE, rendering, audio, input, and saves; remove the generator, generated corpora, static dispatch,
  and their tests and docs. The build may fail at the missing executor until the dynarec lands.
- **ARM64 means both Apple Silicon macOS and Android arm64-v8a**, each with a real AArch64 backend
  qualified separately (executable memory, icache, ABI, signals, packaging, gameplay).
- **WASM is a required frontier** for migrated projects, running the same dynarec-first runtime in
  the browser, or recorded `blocked` with a migration action and acceptance criteria.

## Game ports: structure and titles

- **No project is the global template.** Each port's `docs/codemap.md` is its structure authority;
  the `game-port-structure` skill is the guide. Entry points compose; lifecycle, guest execution,
  platform, rendering, audio, input, UI, configuration, persistence, provisioning, diagnostics, and
  title behavior are separate owners. C++ owners are focused RAII classes composed explicitly; C
  uses opaque contexts, never global state.
- **Engine migrations preserve the game source.** Adapt only engine-coupled APIs. Prefer direct
  compilation, then a deterministic transpiler; a manual gameplay rewrite needs proof that neither
  works and explicit user authorization.
- **Finish one title before starting another** in a multi-title project: exact-revision identity,
  parity, headless gameplay, packaging, and performance. Title-neutral work must serve the active
  title. Record the active title and unmet gates before switching.

## Shared repositories

`shared/` repos are consumed, never vendored: the resolver refuses by naming every path it tried.
Put something a second project will want in `shared/` the first time. Land and push the shared
change first, bump the consumer's pin, and build the consumer against that clean pinned revision.
`shared/android-port` alone may vendor Lucent at a pinned, identifiable revision.

| Repo | Holds |
|---|---|
| `shared/re-harness` | global instructions, categorized skills, shared tools |
| `shared/port-assets` | scalable SVG controller glyphs and key caps, legibility-checked at size |
| `shared/alchemy` | one Alchemy engine repo (X-Men 2, MUA): neutral core without CPU-framework dependency, plus separate `x86`/`x360` adapters over `x86port`/`x360port` pinned by each title. X-Men 2 first; MUA after X-Men 2's goals pass |
| `shared/jit-common` | ISA-neutral executable memory and block cache, once two frameworks need it |
| `shared/x86port` | x86-32 runtime JIT plus a separately built test-oracle interpreter |
| `shared/x360port` | title-neutral Xbox 360 runtime over Xenia's dynarecs: XEX mapping, contexts, services, Xenos/XMA boundaries, typed imports, overrides, original calls, invalidation |
| `shared/x360ue3` | UE3-on-360 contracts over `x360port`: engine ABI descriptions, RHI semantics, binding schemas, lifetimes; never title addresses, hashes, gameplay, or composition |
| `shared/ue3` | developer reference only; never a source, build, runtime, or distribution dependency |
| `shared/android-port` | Android Activity/SAF, build/package/signing plumbing, dependency prefix, emulator contract |
| `shared/setup-ui` | in-window RmlUi first-run setup, picker hand-off, staged-set validator |
| `shared/touch-ui` | touch overlay: safe-area/DPI layout, pointer ownership, glyph rasterization |

Dependency direction: UE3 360 titles `title -> x360ue3 -> x360port -> Xenia`; MUA uses `x360port`
and `shared/alchemy` directly. Lucent is a helper library (logging, config, HTTP, paths, identity,
ZIP, touch routing), not a port framework; the common host framework (lifecycle, input, audio,
presentation, storage, packaging) is separate, with SDL3 as one adapter. Qualify each shipped host
separately.

## CI, releases, and platforms

- **Hosted CI covers every applicable shipping platform** (Linux, Windows, macOS; Android for
  Android-capable products and shared runtime components), or `project-state.md` records why one is
  inapplicable. Jobs configure, build, lint, test, and package through the project's Python owners
  and run runtime checks (JIT, executable memory, icache, ABI, invalidation, install) on the matching
  host. Linux uses Clang, macOS AppleClang, Windows a documented MSVC/clang-cl setup.
- **Workflows are deterministic and least-privileged:** actions pinned by SHA, downloads checksummed,
  timeouts and permissions explicit, caches optional and free of game data. No green placeholder
  jobs.
- **Real-title conformance stays local.** Game files and derived caches never enter CI, secrets,
  commits, or packages.
- **Major updates publish a GitHub Release** with verified asset-free packages per platform (Windows
  installer/app, macOS `.app` archive, Linux AppImage, signed APK). WASM deploys only through
  `~/repo/pages/public/<slug>/`: import, run the Pages verifier, push, check the live URL. Every
  release refreshes its Pages entry (links, media, state snapshot) and verifies the deployed page.
- **Packaged builds have a no-terminal first-run setup** with a native Browse picker, validation,
  and persistence in the platform's user-config store (env vars and CLI paths stay developer
  overrides). Accept the primary ROM/EXE directly or from one bounded ZIP searched by content:
  exactly one identity match; reject unsafe paths, duplicates, corrupt entries, and oversize
  archives; keep the previous valid selection on failure. Lucent owns ZIP mechanics; the port owns
  identity and install policy. AppImages use the desktop launcher; Android uses SAF with persisted
  grants.
- **Saves and settings live in the OS user-data location** (XDG, Application Support, app-data),
  never the checkout, AppImage mount, cwd, or scratch; one shared resolver.
- **Signing is agent-owned.** Discover secrets with `gh secret list`, use them through CI, and
  generate and upload missing keys yourself (a test key for local builds; a stable shared key for
  published artifacts, uploaded to every intended scope). Never print or commit key material, never
  rotate a published identity to pass a build.

## Android

- **Platform mechanics belong in `shared/android-port`:** Activity/SAF adapters, persisted grants,
  private staging, contact/inset handoff, pinned Gradle/AGP/NDK/JDK, the native dependency prefix,
  SDL runtime staging, APK signing/inspection, and emulator policy. Titles own package identity,
  install validation, native entry, JNI bridge, touch layout and art, orientation, and performance
  evidence. PSX, X-Men 2, and LF2 consume it; never copy its mechanics.
- **Toolchain:** pinned wrapper URL and checksum, a compatible AGP, one JDK for `java`/`javac`.
  On JDK 26 the baseline is AGP 9.2 with Gradle 9.4.1; verify a real assembly.
- **Minimum API 21** unless a concrete runtime dependency requires more; guard newer calls; build
  prefixes per API and ABI.
- **Release needs an authored touch layer** through the same action policy as controllers, with
  multi-touch, pause, safe areas, scale-aware hit regions, and hiding when a controller is present.
- **Release performance is measured on named Android devices** (frame-time percentiles, thermals,
  memory, loading, correctness); desktop results are not evidence.
