---
name: release
description: Ship any product — a game port or an original game — through hosted CI, release packages, GitHub Releases, the Pages entry, signing, and the saves and settings location. Use when setting up CI, packaging, publishing a release or Pages entry, or handling signing keys. Ports also follow `port-release`; Android work also follows `android`.
---

# Releasing a product

## CI

- Hosted CI covers every applicable shipping platform (Linux, Windows, macOS, Android), or
  `project-state.md` says why one is inapplicable. Jobs configure, build, lint, test and package
  through the project's own tooling owners.
- Workflows are deterministic and least-privileged: actions pinned by SHA, downloads checksummed,
  explicit timeouts and permissions, optional caches. No green placeholder jobs.

## Releases

- A major update publishes a GitHub Release with verified packages per platform (Windows
  installer/app, macOS `.app` archive, Linux AppImage or archive, signed APK/AAB).
- WASM deploys only through `~/repo/pages/public/<slug>/`: import, run the Pages verifier, push,
  check the live URL. Every release refreshes its Pages entry (links, media, state snapshot).
- Saves and settings live in the OS user-data location (XDG, Application Support, app-data), never
  the checkout, AppImage mount, cwd or scratch; one shared resolver.
- Signing is agent-owned: find secrets with `gh secret list`, use them through CI, generate and
  upload missing keys (a test key for local builds, a stable shared key for published artifacts).
  Never print or commit key material; never rotate a published identity to pass a build.
