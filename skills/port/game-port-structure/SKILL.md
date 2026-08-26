---
name: game-port-structure
description: Structure or refactor a game-port project using Dusklight as the default architecture reference. Use when creating a port, adding a host subsystem, reorganizing a port, integrating UI/input/rendering/audio/configuration, or when a port entry point or subsystem is becoming monolithic.
---

# Game Port Structure

Use Dusklight as the default reference for host-side ownership and composition. Resolve it through
`${DUSKLIGHT_REPO}` or the workspace's documented shared-repository registry. If neither identifies
the checkout, ask for its location instead of assuming a home-directory layout. Read its current
source tree before designing a non-trivial host subsystem; do not rely on a remembered snapshot.

Copy boundaries and ownership patterns, not platform-specific implementations or names. Dusklight's
Aurora/WebGPU RmlUi backend, for example, is not an SDL port's backend; the reusable pattern is that
the backend, document/window, navigation, and binding model are separate owners.

## Required workflow

1. Read the target project's `AGENTS.md`, codemap, and existing subsystem tree.
2. Read the corresponding current Dusklight subsystem and identify its ownership boundaries.
3. Name the target project's modules and narrow interfaces before editing.
4. Split a touched monolith at the relevant responsibility boundary before extending it.
5. Keep the host entry point as composition only: construct owners, connect interfaces, run the loop,
   and shut down in reverse order.
6. Put pure rules and state transitions behind testable seams; tests must exercise production logic.
7. Add or tighten a mechanical structure gate. Use 1,200 lines as the default source-file cap and
   treat 2,000+ lines as critical extraction territory. Freeze oversized legacy files at their current
   line counts; lower a legacy cap whenever code is extracted. Never raise a cap just to land a
   feature.
8. Update the target project's codemap and `AGENTS.md` in the same change, recording how Dusklight's
   pattern maps onto this port. If capability coverage changed, update `docs/project-state.md`
   separately; the codemap records ownership and placement only.

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

## Ownership map

Prefer cohesive peer subsystems such as:

- `app`: lifecycle and composition, with no renderer/input/UI implementation absorbed into it.
- `platform`: OS/window/event translation only.
- `video`: scene construction and rendering; diagnostic probes are separate from shipping passes.
- `audio`: device/mixer ownership.
- `input`: device discovery, action bindings, mapping persistence, and game-facing state.
- `ui`: backend adapter, document/window components, navigation, and view-model/capture state as
  separate units.
- `config` or `save`: storage mechanics only; feature owners define meaning and defaults.
- `overrides` or `game`: native game behavior, separate from host platform translation.

One class or module owns one cohesive concept and its invariants. Avoid `Utils`, `Manager`, `Common`,
numbered fragments, forwarding-only files, or a new container class that merely relocates a god file.

## Acceptance gate

Before landing, verify:

- The normal launcher reaches the intended product path.
- New behavior is reachable through its real user-facing path, not a hidden feature flag.
- The structure checker passes and reports exact files/counts on failure.
- Unit tests cover pure policies and a focused end-to-end run covers integration.
- Shared UI art resolves from `port-assets`, passes that repository's checks, and is not duplicated.
- The codemap names each new owner, interface, and current or intended location.
- Project state records any verified, partial, blocked, or missing capability change and its evidence.

If a direct Dusklight pattern conflicts with the target's renderer, platform, language, or verified game
behavior, keep the ownership boundary and adapt the implementation. Record that decision rather than
forcing incompatible code into the port.
