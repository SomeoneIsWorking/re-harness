---
name: slant-stage
description: The Slant Stage title selector - a port or multi-game app's games running live side by side, split by a slanted edge; the selected one is wider and runs, the other is held grey; picking slides the edge off and the picked game plays on without a reload. Use when building or changing a title or game selector that chooses between two games (or editions) a product can run.
---

# Slant Stage

The title selector where the games themselves are the menu. The user named and specified it
(2026-11-17); it is the selector for any product that runs more than one game.

## The format

- Every game that is set up is loaded at once, each in its own emulated system or guest instance,
  with its own settings and saves. No game is booted twice and no savestate swaps one in for another.
- One slanted edge splits the window. The selected game's side is the wider one (about 64% of the
  width) and only that game is stepped, with its sound. The other is not stepped: its last frame is
  shown greyed and darkened.
- Left and right (pad, keys) or a click on the other side move the selection. The edge eases across;
  the newly selected game resumes from the frame where it stopped and the other freezes grey.
- A, Start or a click on the selected side picks it. The edge eases out past the window's side while
  the picked game keeps running, it fills the window and plays on in the same instance, and the other
  instance is unloaded.
- Each side's picture covers its four-cornered shape. A game without a frame yet, or not set up,
  shows its icon (from the player's own files) on a plain tile.
- A dark band along the bottom holds each game's title (bright for the selected one, dim for the
  other) and the hint line for the last device used. The options and setup screens open over it as
  they would anywhere else.
- One game in the library: its side is the whole window. More than two is not this format.

## What the host must provide

1. **Several guest instances in one process.** Find every process-wide singleton the core reaches,
   such as a static system instance, `Global<>` accessors, or singletons inside HLE services. Put
   them behind a current-instance pointer that the frontend sets before it loads, steps, saves or
   shuts down an instance; the default instance remains for frontends that run one. Survey what
   else is static: console identity and input can be shared, guest state cannot.
2. **The window stays the menu's.** The core renders without presenting and without holding a
   swapchain or context on the window, so the menu's own renderer draws there. The stepped game's
   screen is read back each frame through the core's screenshot path and uploaded as a texture.
   When a game is picked, the core takes the window on its next frame, after the menu renderer is
   destroyed.
3. **Input belongs to the menu.** While the stage runs, the games receive no host input (a pad
   mode with no table). The menu pumps the events itself, and the core's end-of-frame hook only
   counts the frame.
4. **Hand-over, not reload.** The selector returns the picked instance to the play loop. Only a
   game set up just now, which has no instance yet, is booted by the play loop.

The stage is drawn with the menu's existing canvas, font and hint line. It is never a second
implementation of them inside the core's overlay.

## Proof

- Logs: the selector writes `picker: on <title>` on each selection and `picker: picked <title>`
  on each pick; input tests wait on these lines.
- Frames: the stage with the first game selected and running, after a move (the edge on the other
  side, the first game grey at its last frame), partway through the pick's slide, and then the
  game in play, showing it continued and did not restart.

## Reference implementation

`3ds/z3d-mods`: `app/src/title_picker.{hpp,cpp}` (the stage), `emulator.cpp` (each `Emulator`
owns a `Core::System` and makes it current), and the Azahar fork's `System::MakeCurrent` and
`Settings::values.present_to_window`. The design record is `docs/plans/title-stage.md`.
