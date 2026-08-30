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

## Portable release setup and storage

For an AppImage or APK release, the first launch is a product setup flow, not a terminal workflow.
When the required ROM/EXE is absent, show a native setup screen with a Browse action and a platform
file picker, validate the selection, and persist the path or URI in the platform's user configuration
or app-data store. Environment variables and command-line paths may remain developer overrides, but
must not be required by players. AppImages use their desktop launcher; SDL3 Android ports use the
Android Activity/Storage Access Framework bridge and retain URI permission when needed. Neither
package may include unlicensed game content.

Accept the title's primary ROM/EXE directly and accept a ZIP containing exactly one matching primary
file at any folder depth. Validate archive paths, entry counts, compressed and expanded byte budgets,
checksums, executable/ROM identity, and every required sibling asset before replacing a previously
valid selection. Lucent owns reusable safe ZIP discovery/extraction and bounded archive mechanics;
the port owns title identity and complete-install validation. Android may copy a transient SAF
selection into bounded app-private staging instead of retaining external URI access; commit that
staging only after native validation succeeds, and preserve the prior valid install on failure.

An Android port also needs an authored touch-control owner before release. Map virtual controls
through the same action/input policy as physical controllers, with documented reachability, safe-area
insets, scale-aware hit regions, multi-touch, pause/cancel behavior, and hide/reconfigure behavior
when a controller is connected. The Activity must not become a second input implementation.

Treat Android performance as an evidence gate. Qualify named device classes using frame-time
percentiles, sustained thermal behavior, memory, loading, and rendering/audio correctness. Desktop
results, including Apple Silicon laptop results, do not predict Android performance; publish the
device/renderer/settings matrix and keep the APK state partial until it exists.

Pin Android's Gradle wrapper distribution and checksum together with an Android Gradle Plugin version
that officially supports it. Select a coherent installed JDK whose `java` and `javac` come from the
same home and whose major version the pinned Gradle release supports. Prefer updating the maintained
Gradle/AGP pair when that makes the host's current JDK supported; do not require an older JDK merely
because the project retained an obsolete wrapper ceiling. Keep release signing fail-closed and use a
clearly named ephemeral key only for local pipeline verification, never for a published APK.

Saves and settings must use one per-application OS user-data resolver (XDG on Linux, Application
Support on macOS, app-data APIs on Windows/Android), never the checkout, current working directory,
AppImage mount, or scratch. Put the resolver in a shared library when that library owns the boundary;
otherwise keep a narrow consumer module and avoid copying the policy between ports. When a reusable
resolver or picker capability is missing from Lucent, extend and test Lucent first, then consume it
from the port rather than creating divergent implementations.

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
- Package tests reject embedded game content and exercise direct-file, nested-ZIP, duplicate-match,
  unsafe-path, incomplete-install, and over-budget selections through the shipping setup owner.
- A release APK is signed and signature-verified, and remains unreleased until its named-device
  correctness/performance matrix passes.
- Android build evidence records the pinned Gradle/AGP pair, wrapper checksum, coherent JDK home, and
  a real release assembly; a wrapper version banner alone is not assembly evidence.
- Shared UI art resolves from `port-assets`, passes that repository's checks, and is not duplicated.
- The codemap names each new owner, interface, and current or intended location.
- Project state records any verified, partial, blocked, or missing capability change and its evidence.

If a direct Dusklight pattern conflicts with the target's renderer, platform, language, or verified game
behavior, keep the ownership boundary and adapt the implementation. Record that decision rather than
forcing incompatible code into the port.
