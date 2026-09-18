---
name: first-run-setup
description: Give a port a no-terminal first-run screen for the player's own game files — a ROM picker, disc-image picker, or install picker — using the shared setup-ui module instead of a system message box, terminal argument, or environment variable. Use when a port needs a ROM/BIOS/disc/install from the player, when an AppImage or APK must ask for game files without a terminal, or when replacing an existing SDL_ShowMessageBox, zenity, or argv-only selection path.
---

# First-run setup: asking a player for their game files

A packaged port must not require a terminal to find its game files. The screen that asks is
`shared/setup-ui`: RmlUi markup drawn inside the port's own SDL3 window, density-independent, with
a short-viewport layout for a handset. It is a consumed checkout, never vendored.

**`shared/setup-ui/README.md` is the authority.** Read its "Adopting this in a port" section before
writing code; this page exists so you know that module is there and what it decides for you.

## What the shared module owns, and what you keep

The module owns presentation, layout, staged-selection state, and the requests the player makes.
You own the platform picker, your title's identity and validation, where an accepted selection is
persisted, and the decision to start. Environment variables and argv remain maintainer overrides,
never player prerequisites.

Do not put title identity, ROM hashes, extension lists, wording about your game, or picker
mechanics into the shared module. Do not grow a second setup screen in your port because the shared
one is missing something — extend it there and land it before the consumer that needs it.

## Two decisions, before any code

1. **Named set, or one selection you judge?** A port needing specific nameable files (several disk
   images, a ROM plus a BIOS) lists them and may accept one ZIP. A port where any one of several
   differently named things means "the game" — a `.gb`, a `.zip` of it, an installer, a folder —
   uses a single `FileSpec` with an empty `name` and decides in its Validator. Most emulator/ROM
   ports are the second shape. Never identify a ROM by its extension in the config.
2. **`Placement::Stage` or `Placement::Adopt`?** Stage copies into private storage — right for a
   self-contained file the port wants its own copy of. Adopt hands over the player's location
   untouched — required when the selection is a directory or a file whose neighbours are part of
   the install, and right when your own resolver already extracts into user data.

## Worked examples, in this workspace

- **LF2** (`pc/lf2/runtime/ui/setup_screen.cpp`, `setup_screen_policy.cpp`, and
  `runtime/platform/game_picker.c`) — one judged location, adopted; installer/ZIP/executable/tree
  all resolve through the port's own resolver. The closest model for a single-ROM port.
- **Benefactor** (`benefactor/src/platform/setup_flow.cpp`) — three named disk images, staged, with
  desktop and Android SAF pickers.

Split policy (what you ask for, how you judge it) from the loop (SDL and RmlUi) as LF2 does, so a
test can drive the shipping config and Validator without opening a window.

## Verify before claiming it works

- Drive the shipping config and Validator in a test: the accept path, a refusal with its reason, and
  a file with the right name and wrong bytes. A screen that can only refuse passes a weak test.
- Capture the screen at a landscape handset (2340x1080 at density 3.0 = 780x360 dp), portrait, and a
  desktop window, using `ViewOptions::offscreen` with `setup-ui/tools/frame_png.py`, and look at
  whether the confirm button and footer are on screen.
- Record the capability in the consuming project's `docs/project-state.md`, and the new owners in
  its codemap, in the same change.

## Build wiring traps

- A title that already links RmlUi must add this module **after** RmlUi and SDL3; the build reuses
  an existing `RmlUi::RmlUi` target rather than configuring a second copy of the same tree.
- If the module fails to compile against the RmlUi your port pins, fix the module to use API every
  pinned version has. Bumping a consumer's RmlUi to adopt a setup screen is the wrong direction.
- Land the shared change and bump the consumer's pin before building the consumer; a local
  uncommitted shared tree passes here and fails in CI, which builds the pin.
