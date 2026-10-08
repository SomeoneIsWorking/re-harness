---
name: port-release
description: Ship a game port — hosted CI, release packages, first-run setup, saves and settings location, signing, Android. Use when setting up CI, packaging, publishing a GitHub Release or Pages entry, or doing Android work.
---

# Releasing a port

## CI

- Hosted CI covers every applicable shipping platform (Linux, Windows, macOS; Android for
  Android-capable products and shared runtime components), or `project-state.md` says why one is
  inapplicable. Jobs configure, build, lint, test and package through the project's Python owners,
  and run runtime checks (JIT, executable memory, icache, ABI, invalidation, install) on the
  matching host. Linux uses Clang, macOS AppleClang, Windows a documented MSVC/clang-cl setup.
- Workflows are deterministic and least-privileged: actions pinned by SHA, downloads checksummed,
  explicit timeouts and permissions, caches optional and free of game data. No green placeholder jobs.
- Real-title conformance stays local. Game files and derived caches never enter CI, secrets,
  commits or packages.

## Releases

- A major update publishes a GitHub Release with verified asset-free packages per platform
  (Windows installer/app, macOS `.app` archive, Linux AppImage, signed APK).
- WASM deploys only through `~/repo/pages/public/<slug>/`: import, run the Pages verifier, push,
  check the live URL. Every release refreshes its Pages entry (links, media, state snapshot).
- Packaged builds have a no-terminal first-run setup (see the `first-run-setup` skill): native
  Browse picker, validation, persistence in the platform's user-config store. Accept the primary
  ROM/EXE directly or from one bounded ZIP searched by content: exactly one identity match; reject
  unsafe paths, duplicates, corrupt entries and oversize archives; keep the previous valid
  selection on failure. Lucent owns ZIP mechanics; the port owns identity and install policy.
  AppImages use the desktop launcher; Android uses SAF with persisted grants.
- Saves and settings live in the OS user-data location (XDG, Application Support, app-data), never
  the checkout, AppImage mount, cwd or scratch; one shared resolver.
- Signing is agent-owned: find secrets with `gh secret list`, use them through CI, generate and
  upload missing keys (a test key for local builds, a stable shared key for published artifacts).
  Never print or commit key material; never rotate a published identity to pass a build.

## Android

- Platform mechanics live in `shared/android-port`: Activity/SAF adapters, persisted grants, private
  staging, contact/inset handoff, pinned Gradle/AGP/NDK/JDK, the native dependency prefix, SDL
  runtime staging, APK signing/inspection, emulator policy. Titles own package identity, install
  validation, native entry, JNI bridge, touch layout and art, orientation, performance evidence.
- Toolchain: pinned wrapper URL and checksum, a compatible AGP, one JDK for `java`/`javac`. On JDK
  26 the baseline is AGP 9.2 with Gradle 9.4.1; verify a real assembly.
- Minimum API 21 unless a runtime dependency needs more; guard newer calls; prefixes per API and ABI.
- Launcher icons: Honor's MagicOS launcher draws some adaptive icons unmasked (seen with Godot's
  adaptive icon, which always carries a monochrome layer), so the full 108dp canvas shows as a
  square. Make the foreground the art alone with transparent corners, and bake the shape into the
  background layer: a rounded plate inset 1/16 of the canvas, corner radius about 22% of the plate.
  Masking launchers crop that margin away. Check it on a device beside other apps.
- A release needs an authored touch layer through the same action policy as controllers:
  multi-touch, pause, safe areas, scale-aware hit regions, hidden when a controller is present.
- Release performance is measured on named Android devices (frame-time percentiles, thermals,
  memory, loading, correctness); desktop results are not evidence.
- ARM64 means both Apple Silicon macOS and Android arm64-v8a, each with a real AArch64 backend
  qualified separately (executable memory, icache, ABI, signals, packaging, gameplay).
