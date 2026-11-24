---
name: slant-stage
description: The Slant Stage title selector - a port or multi-game app's games side by side as still pictures from the player's own files, split by slanted seams; the selected one is wider and in colour, the others grey; picking slides the seams off and boots the picked game. Use when building or changing a title or game selector that chooses between the games (or editions) a product can run.
---

# Slant Stage

The title selector for any product that runs more than one game. The user named it (2026-11-17) and
changed it to still pictures (2026-11-24): nothing runs until a game is picked.

## The format

- Every game that is set up has a panel, side by side across the window, split by slanted seams.
  The selected panel is the wider one (about 64% of the width); the others share the rest.
- A panel shows the game's own art (its title illustration or wordmark), read from the player's own
  disc or files with the game's own codec and drawn the way its title screen draws it. No game art is
  committed or cached as a picture of ours. A game with no art found yet is a plain tile.
- Every panel draws its art at one whole-pixel scale: the largest at which every art fits the window's
  height and the selected panel's clear width. The selected panel is in colour, the others greyscale.
  Selection changes widths and colour, never the scale.
- Left and right (pad, keys) or a click move the selection round the ring; the seams ease across.
- A, Start or a click on the selected panel picks it: the seams ease out past the window's sides, then
  the game boots. Returning from the game ends its session and shows the selector again on that game.
- A dark band along the bottom holds each game's title (bright for the selected one) and the hint line
  for the last device used. The options and setup screens open over it as they would anywhere else.
- One game in the library: no selector.

## What the host must provide

1. **Art from the player's files.** Each game names where its art lives (recorded in its decomp) and
   decodes it there; the host draws the result. The decode runs once per selector start.
2. **The window stays the host's.** The selector draws with the menu's existing renderer, canvas, font
   and hint line, never a second implementation inside a game's overlay. The window and device outlive
   every game session.
3. **One session at a time.** A pick creates the game's session; a return destroys it.

## Proof

- Logs: `picker: on <title>` on each selection, `picker: picking <title>` on each pick; input tests
  wait on these lines.
- Frames at the player's resolution: every panel's art at one scale, after a move (widths and colour
  changed, scale not), partway through the pick's slide, the picked game booted, and the selector again
  after a return. Two runs give the same pictures.

## Reference implementation

`psxport`: `runtime/psx/host/picker_*`, `panel_art.*`, `runtime/psx/present/art_scene.*`, and each title's
`GameRuntime::panelArt` (psx-tomba `game/core/assets/title_art.cpp`, psx-spyro `game/core/wad_wordmark.cpp`).
The design record is psxport `docs/plans/static-title-picker.md`. `3ds/z3d-mods` still runs the earlier live
stage.
