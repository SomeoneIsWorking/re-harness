---
name: release
description: Ship any product — a game port or an original game — through hosted CI, release packages, GitHub Releases, the Pages entry, signing, and the saves and settings location. Use when setting up CI, packaging, publishing a release or Pages entry, or handling signing keys. Ports also follow `port-release`; Android work also follows `android`.
---

# Releasing a product

## CI

- A release is built either by hosted CI, started by hand or from a release tag and never per push
  (global instructions), or locally by the project's release tool; `project-state.md` names which.
  Either way it covers every applicable shipping platform (Linux, Windows, macOS, Android), or
  `project-state.md` says why one is inapplicable, and it configures, builds, lints, tests and
  packages through the project's own tooling owners. A project that releases locally keeps no
  workflows.
- Where each platform builds:
  - Linux and Windows on our own Linux machines (Fedora, or the second machine when Fedora is
    loaded), never on hosted CI. Windows is cross-compiled with llvm-mingw (Clang for the MinGW
    target) and smoke-tested under Wine before it ships.
  - macOS on the Mac when it can be reached (a session there, or a queue its worker pulls), and on
    a hosted macOS runner only when it cannot.
- Workflows are deterministic and least-privileged: actions pinned by SHA, downloads checksummed,
  explicit timeouts and permissions, optional caches. No green placeholder jobs.

## Releases

- Every milestone publishes a GitHub Release with verified packages for every platform the product
  can run on: Windows `.exe`, macOS `.app` archive, Linux AppImage, Android `.apk`.
- A Linux AppImage meets the AppImage catalog's checks (appimage.github.io):
  - Built inside an Ubuntu 22.04 container, so it needs glibc 2.35 at most. SDL3 and other libraries
    22.04 lacks are built in the image from checksummed source tarballs. The packager reads every
    bundled ELF and refuses anything that needs a newer glibc.
  - Started with no arguments, it opens its window within 30 s. A missing game file means the
    first-run screen, never an exit or a terminal prompt.
  - The repository, the AppImage file name, the README title and the desktop entry's `Name=` all
    use the same product name. The entry passes `desktop-file-validate`, and an AppStream
    metainfo file ships with it.
  - It embeds update information (`gh-releases-zsync|OWNER|REPO|latest|<Name>-*-x86_64.AppImage.zsync`).
    The release publishes the `.zsync` next to the AppImage.
  - linuxdeploy runs with a pinned patchelf 0.19 or newer through `PATCHELF`. Older patchelf (the
    0.15 bundled with linuxdeploy, distribution packages) writes libraries that crash the loader.
  - The catalog finds the window with `xdotool` under `LANG=C.UTF-8`, and that search cannot match
    upstream SDL3's X11 `WM_NAME`, which it writes as `UTF8_STRING`. SDL comes from a
    `SomeoneIsWorking/SDL` fork branch carrying the ICCCM `WM_NAME` commit.
  - FreeType is on linuxdeploy's exclude list, so it is linked statically.
  - appimagetool writes the `.zsync` into its working directory, and only when `zsyncmake` is
    installed.
- WASM deploys only through `~/repo/pages/public/<slug>/`: import, run the Pages verifier, push,
  check the live URL. Every release refreshes its Pages entry (links, media, state snapshot).
- Saves and settings live in the OS user-data location (XDG, Application Support, app-data), never
  the checkout, AppImage mount, cwd or scratch; one shared resolver.
- Signing is agent-owned: find secrets with `gh secret list`, use them through CI, generate and
  upload missing keys (a test key for local builds, a stable shared key for published artifacts).
  Never print or commit key material; never rotate a published identity to pass a build.
