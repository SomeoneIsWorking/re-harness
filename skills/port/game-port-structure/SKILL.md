---
name: game-port-structure
description: Structure or refactor a game-port project around cohesive responsibility owners and explicit dependency boundaries. Use when creating a port, adding a host subsystem, reorganizing a port, integrating UI/input/rendering/audio/configuration, or when a port entry point or subsystem is becoming monolithic.
---

# Game Port Structure

There is no reference game whose tree defines the architecture. Start from the target's verified
behavior, platform/runtime boundaries, language, lifecycle, and product requirements. The target's
codemap is the placement authority; the principles below define the reusable structure standard.

Choose boundaries where invariants, lifetime, dependency direction, platform coupling, test seams,
or rates of change differ. Reusing a proven shared library is encouraged when it owns the exact
contract, but copying another game's directory names or class layout is not design.

For C++, model stateful owners as focused classes with RAII lifetimes and explicit dependencies.
Pure transformations remain namespace-scoped free functions or value types. In C, use an opaque context and cohesive
module API. Avoid service locators and unrelated subsystems gathered into one class.

## Required workflow

1. Read the target project's `AGENTS.md`, codemap, and existing subsystem tree.
2. Identify the behaviors, state, lifetimes, external dependencies, and test boundaries involved.
3. Name the target project's responsibility owners, dependency direction, and narrow interfaces
   before editing.
4. Split a touched monolith at the relevant responsibility boundary before extending it.
5. Keep the host entry point as composition only: construct owners, connect interfaces, run the loop,
   and shut down in reverse order.
6. Put pure rules and state transitions behind testable seams; tests must exercise production logic.
7. Route logging and configuration through their owners; pass each subsystem only the dependencies
   and configuration fields it needs.
8. Extend the project's structure gate for any new boundary and update its codemap in the same
   change. Record the concrete owner and dependency direction, not a generic template.

## Title deltas

Every title gets widescreen and loading removal; titles below 60 fps get interpolation. Each delta
is its own item in `project-state.md`'s comparison baseline.

- **Widescreen is a deterministic projection change.** Same vertex stream with topology, UVs, depth
  and colours preserved; widen the horizontal projection/viewport and override the title's draw
  area/scissor and every horizontal cull it owns (world, actors, particles, shadows), so the margins
  show what the view would. The native renderer ignores the title's culls and draws from object
  memory, animating margin-only objects itself, with guest memory untouched. Only where the camera
  window decides whether objects exist (spawn/unload, side-scrollers) widen that guest window,
  recorded as a gameplay delta. Edge HUD moves to the widened edges, centred UI stays centred,
  nothing stretches. Never sample adjacent frames, infer geometry from pixels, or stretch the image.
- **Interpolation** is a separate opt-in feature over matching source geometry only.
- **Loading-only screens do not ship.** Keep loading asynchronous and go straight to the next real
  presentation. Logo screens accept Start/confirm through a complete cancellation route. Authored
  transition cutscenes stay; a title may give one a minimum duration (Tomba! 2's area transition:
  five seconds).
- **Skips are complete, owned transitions** through the title's recovered cancellation route or a
  purpose-built skip with the same lifecycle, resource and state invariants. Never fast-forward
  simulation, bypass lifecycle callbacks, or write a phase, timer or scene pointer.

## Product shape

- A control channel is built in and always open on loopback (an env var may move the port, never
  close it) so agents can drive input, read state and capture frames. Automated runs are headless,
  silent and never steal focus.
- Engine migrations preserve the game source: adapt only engine-coupled APIs; prefer direct
  compilation, then a deterministic transpiler; a manual gameplay rewrite needs proof neither works
  and the user's authorization.
- Multi-title repos follow the user's title priority; a change for one title must not break another.

## Asking the player for game files

A port that needs the player's own ROM, disc image, or install owns the picker and the title's
identity, but not the screen: that is `shared/setup-ui`, and the `first-run-setup` skill covers
adopting it. Do not design a setup dialog, message box, or terminal prompt as part of a port's
structure.

## Shared port assets

Use `${PORT_ASSETS_DIR}` when set, otherwise `${SHARED_DIR}/port-assets` when `SHARED_DIR` is set.
If neither is configured, consult the workspace registry or ask for the checkout. This is the source
of generic art shared by ports:
device icons, keyboard caps, controller glyphs, and future cross-project UI assets. Search its
manifests before drawing or importing an equivalent asset.

Add genuinely reusable art to that shared repository, with SVG as the authored source, a manifest,
an author/check script where the set is generated, and the shared repository's raster/visual tests.
Do not vendor a copy into the consumer. A port may embed or rasterise the shared SVG at build time so
the shipped binary does not depend on a machine-specific runtime path; preserve provenance in the
build rule and fail by naming the missing shared checkout or glyph instead of substituting text or a
private copy.

## README and release-facing documentation

Every game-port project maintains a useful root `README.md` for a new player or contributor. Keep
these concerns explicit and separate:

- what the port is and its honest current status;
- the user-visible features it implements;
- enhancements over the vanilla/original game, clearly labelled as additions rather than implied
  original behavior;
- setup from a fresh clone, including supported platforms, exact native dependencies, user-supplied
  game-file requirements, and the supported launcher command; and
- a small gallery of intentional, current screenshots under `docs/screenshots/` when visual output
  is part of the project.

Screenshots are curated product documentation, not a diagnostic frame corpus. Capture them from the
current intended product path, caption the state they show, and do not use known-broken or stale
intermediate output to imply completeness. They may document the running game, but never replace
the rule that copyrighted game files and reconstructable game assets stay out of the repository.
Use a representative practical display size; a 4K capture is not itself a feature, and resolution
support belongs in the setup/status text when it is actually supported.
Update the README in the same change whenever a user-facing feature, supported setup path, launcher,
or visible enhancement changes. Keep detailed evidence and unfinished coverage in the project's
state/evidence docs instead of turning the README into a work log.

## Ownership map

Prefer cohesive peer subsystems such as:

- `app`: lifecycle and composition, with no renderer/input/UI implementation absorbed into it.
- `platform`: OS/window/event translation only.
- `video`: scene construction and rendering; diagnostic probes are separate from shipping passes.
- `audio`: device/mixer ownership.
- `input`: device discovery, action bindings, mapping persistence, and game-facing state.
- `ui`: backend adapter, document/window components, navigation, and view-model/capture state as
  separate units.
- `save`: persistent game-state storage mechanics only; feature owners define meaning and defaults.
- `config`: the only owner of environment/CLI/file ingestion, precedence, validation, and typed
  immutable configuration. Other owners receive only the configuration fields they use.
- `logging`: the only product diagnostic sink/filter/format boundary. C++20 ports use Lucent; product
  modules never call stderr, platform debug-print APIs, or ad-hoc logger macros directly.
- `overrides` or `game`: native game behavior, separate from host platform translation.

One class or module owns one cohesive concept and its invariants. Avoid `Utils`, `Manager`, `Common`,
numbered fragments, forwarding-only files, or a new container class that merely relocates a god file.

## Structure acceptance

Check that each new owner has a narrow interface, its dependencies point in the documented direction,
and the host entry point only composes owners. Exercise the production interface with focused tests;
prove the structure gate rejects a representative forbidden edge. The codemap must name the actual
owners and locations. Release, CI and Android rules are in the `release` and `android` skills, plus `port-release`.

## Shared repositories

`shared/` repos are consumed, never vendored; the resolver refuses by naming every path it tried.
Put what a second project will want in `shared/` the first time; land it there first, then build the
consumer against it. `shared/android-port` alone may vendor Lucent at a pinned revision.

| Repo | Holds |
|---|---|
| `re-harness` | global instructions, skills, shared tools |
| `port-assets` | SVG controller glyphs and key caps |
| `alchemy` | Alchemy engine (X-Men 2, MUA): neutral core plus `x86`/`x360` adapters |
| `jit-common` | ISA-neutral executable memory and block cache |
| `x86port` | x86-32 runtime JIT plus a test-oracle interpreter |
| `x360port` | Xbox 360 runtime over Xenia's dynarecs |
| `x360ue3` | UE3-on-360 engine contracts over `x360port`; no title data |
| `ue3` | developer reference only, never a dependency |
| `android-port` | Android Activity/SAF, packaging, signing, emulator |
| `setup-ui` | RmlUi first-run setup and picker |
| `touch-ui` | touch overlay and glyph rasterization |
| `bug-report` | in-app bug reports for RmlUi C++ apps |

UE3 360 titles depend `title -> x360ue3 -> x360port -> Xenia`; MUA uses `x360port` and `alchemy`.
Lucent is a helper library (logging, config, HTTP, paths, identity, ZIP, touch routing), not a port
framework.
