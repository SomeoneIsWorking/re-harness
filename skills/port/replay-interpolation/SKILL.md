---
name: replay-interpolation
description: Present a fixed-logic-rate game at 60 Hz or higher by re-running the title's own draw code with its moving inputs blended between two logic ticks, inside a sandbox that rolls back every write. Covers finding the draw section, the sandbox, motion tracks and identity, cuts, pacing and proof. Use when adding or extending frame interpolation in any port (static recompilation, dynarec or emulator-based), when an in-between shows something at the logic rate, flickers, runs too fast or leaks into the next tick, or when replacing per-object interpolation producers.
---

# Replay interpolation

The logic runs at its own rate, untouched. Each in-between at fraction t is the title's own draw code
run again with the inputs it reads written t of the way between two logic ticks, and what that run
emits is the in-between, whole. The title's draw code is the only renderer.

Do not build interpolation any other way:

- Per-object producers that re-render each thing at t. They need an ownership ledger, still miss every
  writer nobody keyed, and grow with every area.
- A search of uniforms, constant banks or vertex buffers for matrices that move like a camera or an object.
- Image-space motion estimation, frame generation, or reading pixels back to decide geometry.

A native producer is kept only for a draw section the replay cannot run (one that reaches a device), and
the owner reports it.

## 1. The draw section

- RE the frame loop to the point where the tick's logic is done and the picture is derived (a process
  manager's execute/draw split, a game-state draw, a render-list build). Decompile it end to end and list
  everything it does besides drawing: scene draws that step counters, collision or particle updates,
  state machines that live in a draw slot, resource loads.
- The section must rebuild its lists rather than append to them. Record the address that shows it.
- Dispatch the replay with the port's overrides in force, so it draws what the real frame draws
  (widescreen culls included).
- If the frame makes more than one submission, the replay names the one it replaces by what it is, never
  by a packet or list address that moves with the scene.
- First probe: run the section once at t = 1 in the sandbox and compare its output with the real draw's,
  byte for byte. That proves the section and the sandbox before any blend exists.

## 2. The sandbox

Every write the replay makes is undone before the next logic step: guest memory, CPU and coprocessor
state, timers and GPU registers. Guest time is frozen and interrupts are off. Device stores are dropped,
and a device read, upload or syscall refuses that in-between, so the present repeats the newest real
frame.

Without the sandbox, every draw-time side effect runs once more per in-between. The usual ones are random
numbers drawn in a draw, sound starts, countdown timers in a draw slot, draw methods that advance their
own animation or flash, eased lights, frame counters, one-shot flags the draw consumes, state machines in
a draw slot, and resource-load steps. Gating these one site at a time is a bandaid. The sandbox removes
the class.

- With store-level hooks (an interpreter or a dynarec with a memory callback), journal the stores.
- Without them, snapshot what a census shows the draw writes (actor bodies, the module's data and bss)
  and restore it. Exclude by address, with the reason, the state the process manager owns (process and
  draw-list links, draw tags), because restoring it corrupts a list another thread or the next step
  mutates.
- Restore the blended inputs last, so a blend over a value the draw itself steps composes.
- Proof that nothing leaks: the same input sequence run with interpolation on and off reaches identical
  logic state after N ticks (RNG seeds, positions, frame counter).

## 3. Motion tracks

A track is the small set of moving state the draw reads, sampled before each real draw. It is written at
the earliest input the draw reads, so everything derived from it follows: billboards, culling, lights,
shadows.

- **Camera.** Use the inputs the draw derives the view from (eye, target, up, bank, fov), not the derived
  matrix. Blend the unshaken camera, then add the new tick's shake.
- **Objects.** Position and angles, or the model's joint world matrices after the animation has been
  computed.
- **Poses.** A pose blends as a unit (current frame, next frame, progress), never its index bytes alone.
  An animation switch cross-blends.
- **Pools.** Particles, lines, trails, chains, cloth points, effect tables, plant hit slots.
- **Material frames, texture scroll and fades.**

Rules:

- **Identity.** The record's address plus the title's key words (generation, class, owner). Liveness comes
  from the title's own free list or live byte. Never use draw order, occurrence index or nearest match.
- **Pairing.** A slot pairs only while it is live in both samples and its key words are unchanged. An
  unpaired record is drawn as it is now. A counter that includes free slots means nothing.
- **Blends.** Matrices: rotation slerped along the shorter arc, translation straight. Angles go the short
  way and carry into any turn count above the angle bits from the earlier sample. Scrolls wrap. There is
  one implementation of each blend in the framework.
- **Joints.** A joint hidden on the real draw and not written since is drawn at the current tick. A joint
  whose matrix did not change takes no part in a cut test.
- **Reports.** An owner reports unpaired, unblendable and refused items at run end (`dynamic-scan`), not
  pass counts.

## 4. Cuts

A cut holds the interval: the in-between shows the current tick exactly. Cuts come from the title's own
declarations, found by RE: a camera reset, a shot change, a switch into a demo camera, a warp, a respawn,
a scene change. That includes cuts the game declares only after the draw, which the presenter must hold.
A per-object teleport holds that object only. A distance or angle limit only catches what the declared
cuts missed, is named as such, and never stands in for finding the declaration.

## 5. Pacing

- The logic rate is measured unchanged with interpolation on, in ticks per second with denominators.
- The fraction comes from the flip time. Plan in-between counts that divide the refresh evenly.
- Each in-between the presenter keeps alive gets its own output buffer.
- Measure the cost of each pass, and shed passes over the frame budget.

## 6. Proof

- Show crops of one moving object across consecutive presents, with each in-between visibly halfway
  between its neighbours, judged as the player sees them.
- The t = 1 replay is identical to the real frame (the null case).
- One paced real-time run on a quiet host shows about 0.5 tick per vblank at 60 Hz.
- A "pixels changed between presents" count is not proof: it reads the same with the defect present.

## Reference implementations

- `psxport` `docs/plans/replay-interpolation.md` with `runtime/psx/present/{replay_frame,motion_set,guest_redraw}`:
  the framework owner (sandboxed `GuestRedraw`, `MotionSet`), on Spyro 1-3 and Tomba! 2.
- `wiiuport` `docs/frame-interpolation.md`, "The game-side in-between frame": Wind Waker HD under a Cemu
  runtime, the gated tick's draw phase re-run at the midpoint. It does not have the sandbox yet.
- ZeldaWWHDRecomp (MPL-2.0, `runtime/src/interp/`): the same method on a static recompilation. Each
  drawn actor is saved before its hold-pass draw and put back after the paint, excluding the process and
  draw tags. Its commit log lists draw-time side effects by guest address.
- `RetroPortingToolKit/psxrecomp` `docs/RENDER_PASSES.md` (PolyForm Noncommercial: design only, no code):
  render passes with a motion set and a bit-exact sandbox.
