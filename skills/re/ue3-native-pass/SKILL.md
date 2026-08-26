---
name: ue3-native-pass
description: >-
  Reimplementing an Unreal Engine 3 rendering pass natively in a console→PC port — identifying
  which UE3 pass a draw belongs to, reading the title's Xenos/D3D9 microcode against UE3's own
  sources, and writing a replacement shader that is verified rather than declared. Covers the
  UE3 source layout, the pass taxonomy a frame decomposes into, the microcode reading traps
  (rotating swizzles, dropped constant terms), and the evidence gates. Use when porting or
  debugging UE3 rendering (base pass, post chain, bloom, motion blur, skinned materials), or
  when a draw renders black/wrong and you need to know what it was SUPPOSED to do.
---

# Native UE3 passes

Reimplementing a UE3 pass instead of translating its microcode. The translated shader is
ground truth for *what the title asked for*; UE3's source is ground truth for *what the pass
means*. You need both, and confusing them is the main way this goes wrong.

## Get the engine source first

Native work without the engine source is guesswork dressed as analysis.

    https://github.com/CodeRedModding/UnrealEngine3    # "Build 10897", 2013

Point an env var at a local checkout and record it in a **gitignored** `.env` — UE3 source is
licensed, so a path is fine and vendored content is not. Never commit it, and never let the
path into a tracked file.

**Version caveat, always worth stating in findings:** that tree is a 2013 build. Titles from
2006–2008 (Gears of War, early UE3) differ in individual `.usf` files while the pass
structure, `Development/Src/Engine/Src` layout and material interface still line up. Treat a
`.usf` as a hypothesis to check against the microcode, not as the answer.

What settles what:

| Path | Question it answers |
|---|---|
| `Development/Src/Engine/Src/SceneRendering.cpp` | The frame's pass order — what runs when |
| `Development/Src/Engine/Src/BasePassRendering.cpp` | What the base pass binds, and `DrawShared`'s state |
| `Engine/Shaders/BasePassPixelShader.usf`, `BasePassCommon.usf` | The base pass shading itself |
| `Engine/Shaders/MaterialTemplate.usf` | The interface every generated material implements |
| `Development/Src/Engine/Src/MaterialShared.cpp` | Material parameter layout — what the UBOs mirror |
| `Development/Src/Core/Inc/Color.h`, `Src/Color.cpp` | `FLinearColor`, gamma, sRGB — where colour questions belong |

The same organisation publishes **CodeRed-Generator**, a C++20 internal SDK generator that
recovers `UObject`/`UClass` layouts and property offsets. Not needed to write a pass, but it is
the standard route to "which guest function emitted this draw" when static analysis stalls.

## A UE3 frame decomposes into a fixed taxonomy

Attribute every draw before theorising about any of them. A frame is, in order: **clear →
depth prepass → base pass → occlusion queries → blended → post chain → resolve to front
buffer**. Build a per-draw table (surface, colour format, primitive, input primitives,
primitives after clip, fragment invocations, colour mask, blend enable, shader hashes) and
classify from register state, citing the `SceneRendering.cpp` line each rule keys on.

**Report what you cannot distinguish.** UE3's lights, decals, distortion and translucency all
draw blended, depth-tested, depth-write-off with the same register state. They are one band
unless you have the bound texture set or the emitting call site. A classifier that silently
splits them is inventing structure.

## Identify a pass by its pixel shader hash

A UE3 title binds the same microcode for the same pass every frame, so **the hash is the pass
identity**. That is the seam: substitute a native module keyed on the hash, and leave
everything else — geometry, render target, blend state, constants — coming from the guest,
because the guest is right about them. You do not need to identify the guest function that
emits the draw.

**Keep the translated shader alive.** Build both and A/B them on the same captured frame. A
native pass that cannot be compared against the translation is a native pass nobody can trust.

## Reading the microcode: the traps that actually bite

Xenos microcode is not readable by eye, and every one of these has produced a confident wrong
answer in practice:

- **Rotating accumulation swizzles.** `mad r5.xyz, rN, cM, r5.zxyy` chains rotate the
  accumulator every instruction. Ten of them in a row can cancel exactly, and you cannot see
  that from the listing. Reduce symbolically — simulate the register file into symbolic
  expressions — never read a chain by hand.
- **Dropped constant terms.** Reading `saturate(c.y - x)` off the listing while the reduction
  says `x = t + c.x` gives you the wrong gate and a wrong search direction. *Read the
  reduction to the end*, including the final output expression; do not truncate it.
- **Registers reused far apart.** A register loaded at instruction 60 and exported at 440 is
  almost certainly not the same value. Count the writes in between before claiming a chain.
- **Full-register writes have no mask.** `max o4, r2, r2` writes o4; a grep for `o4.` misses
  it and you conclude an interpolator is never exported.
- **Interpolator location N is register rN**, on both stages — that is how a debug shader can
  read exactly what the title's shader reads.
- **Predication and control flow.** A symbolic reducer must REFUSE these rather than skipping
  them; a partial reduction reads exactly like a complete one. If the pass you care about is
  inside predicated blocks, symbolic reduction is not available and you need a runtime probe.

## When a pass renders black, probe don't theorise

Substitute a **diagnostic** module for the pass's hash that writes an interpolator, a texture
sample or an intermediate out as colour, and read it with a per-pixel trace. This is the only
way to see values the shader computes.

- Keep it **out of the native-pass roster** — an acceptance gate that renders the whole roster
  would render your diagnostic. Give it its own knob.
- Make it **warn on every frame it substitutes**. A diagnostic frame that looks like a render
  is the worst possible outcome.
- Emit the **suspect and a known-good reference in different channels**, so one image carries
  both and successive builds cannot be confused.
- When you correct a probe, **keep emitting the old value too**. That is how a wrong
  measurement stops silently propagating.

Work multiplicatively: the output is a product of terms, so measure each term and let
arithmetic tell you which is zero. Then confirm by forcing that term and seeing the picture
change — and **say out loud that forcing a guest constant is a control arm, never a fix**. The
number comes from the guest; a wrong one is a bug upstream, and hardcoding it makes one frame
look right and breaks the next.

## The evidence gate

A pass is implemented when it is **verified**, not when it renders something plausible. Three
arms, all required:

1. **Pixels** — render a captured frame through both paths and compare per pixel. Delete the
   output before each arm (a stale file compares a frame against itself and reports a perfect
   match). Refuse rather than pass when an arm produces nothing or both frames are near-black.
2. **Interface** — re-run under the validation layer and fail on any descriptor or
   shader-interface warning. A pass can be bit-exact for days while declaring the wrong image
   view type, and pixels can never see that.
3. **Negative control** — a second capture, in the same invocation, that must NOT match. A
   comparison never shown able to report a difference has not been shown to be a comparison.

Generate shader modules ahead of time into checked-in headers rather than compiling at
runtime, so a pass cannot change under a driver update — and regenerate them in the same
commit that edits the shader.

## Keep the roster honest

List passes in a table with an explicit status, and distinguish **implemented** (a module
exists) from **declared** (an entry with no module). Lookup must refuse a declaration rather
than silently falling through to the translated shader, and the log must distinguish "native
passes off" from "on, and none exist". Withdraw a pass that turns out not to run in the title
rather than leaving it listed — absence is cleaner documentation than a tombstone.
