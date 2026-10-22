---
name: dynamic-scan
description: Find a port's defects by running it unattended instead of playing it. The product reports its own defects at the owning layer, a scan runs every reachable state through the title's warps, and a small test program with known ground truth exercises the framework layers. Use before judging a port by play, after any shared-framework change, or when a defect took a long trace to find.
---

# Dynamic scan

Playing a game to find a defect is slow: real time, a quiet host, a walk from boot. Most defects can be
found faster by running the product unattended and letting the owners report what they could not do.
A scan is not a gate or a harness. It is the product's own logging plus the routes it already has.

## 1. Owners report their own defects

Every layer that an enhancement depends on reports, at run end, what it could not handle. Each item names
the guest function or address responsible and carries a count. The report is one line per item through
the project logger.

- An interpolation or identity layer lists draws that came in without identity or went around the layer,
  and in-betweens it refused, with the reason.
- A widescreen layer lists draws culled or clipped at the original edges.
- A loading or skip layer lists waits it could not remove.

Report only defect classes that cost real time, and report redundancy as a defect too. That covers a draw
claimed by two owners, two code paths producing the same thing, and an owner that never fires in any
scanned state (dead code). Never report a pass count, a census of what already works, or a surface check
on output that cannot tell good code from bad.

A layer whose concept can be bypassed should be restructured so the bypass is reported on the first
frame it happens (`game-port-structure`: one entry point per concept).

## 2. Scan every reachable state

Run each title unpaced and hidden through every target of its debug warp. Give each target a few seconds
idle, then go through boot and attract mode. Collect the run-end reports, ordered by state.

- Identity, coverage and culling defects need no player input or motion. Pacing and feel still need a
  real-time run, which is done once to close a pass.
- A state no warp reaches is a scan gap. Add the warp (title-owned, through the game's own transition
  owner) rather than steering gameplay to get there.
- The result is the work list: guest functions without an owner, ordered by state. Fix the first state's
  items first.

## 3. A test program for the framework

A shared framework gets its own small guest program, built from source with no game assets. It draws
scenes whose correct output it knows exactly, and stresses the framework the way games do (projected
models, sprites, fades, empty draw-list slots, objects appearing mid-motion, the game's logic rate, load
holds, movies). Its in-between frames can be compared with the same scene drawn at the exact time, so
framework errors are measured rather than judged. It starts in under a second, needs no disc, and can run
in CI.

It covers the framework, not titles. A title's own defects come from that title's scan, and a title fix is
proven in that title.

## Keep it lean

Building the owner reports, the warps a scan needs and the test program is required work, not optional
tooling, even when it takes a long pass; it is what makes every later pass fast. Lean means no layers around
them: one test program, one way to run a scan, no selftests, ledgers or wrappers.
