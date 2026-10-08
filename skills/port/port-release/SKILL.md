---
name: port-release
description: Port-only release rules on top of `release` and `android` — real-title data kept out of CI and packages, runtime checks for JIT hosts, accepting the player's ROM/EXE in packaged builds, the shared native Android layer, ARM64 qualification. Use when shipping or doing Android work on a game port.
---

# Releasing a port

The general rules are in the `release` and `android` skills; this adds what a port needs.

## CI

- Jobs run runtime checks (JIT, executable memory, icache, ABI, invalidation, install) on the
  matching host. Linux uses Clang, macOS AppleClang, Windows a documented MSVC/clang-cl setup.
- Real-title conformance stays local. Game files and derived caches never enter CI, secrets,
  caches, commits or packages; release packages are asset-free.

## Game files in packaged builds

- Packaged builds have a no-terminal first-run setup (see the `first-run-setup` skill): native
  Browse picker, validation, persistence in the platform's user-config store. Accept the primary
  ROM/EXE directly or from one bounded ZIP searched by content: exactly one identity match; reject
  unsafe paths, duplicates, corrupt entries and oversize archives; keep the previous valid
  selection on failure. Lucent owns ZIP mechanics; the port owns identity and install policy.
  AppImages use the desktop launcher; Android uses SAF with persisted grants.

## Android

- Platform mechanics live in `shared/android-port`: Activity/SAF adapters, persisted grants, private
  staging, contact/inset handoff, pinned Gradle/AGP/NDK/JDK, the native dependency prefix, SDL
  runtime staging, APK signing/inspection, emulator policy. Titles own package identity, install
  validation, native entry, JNI bridge, touch layout and art, orientation, performance evidence.
- Minimum API 21 unless a runtime dependency needs more; guard newer calls; prefixes per API and ABI.
- ARM64 means both Apple Silicon macOS and Android arm64-v8a, each with a real AArch64 backend
  qualified separately (executable memory, icache, ABI, signals, packaging, gameplay).
