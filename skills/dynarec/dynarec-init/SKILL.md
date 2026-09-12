---
name: dynarec-init
description: >-
  Start a console-to-PC dynamic-recompiler/JIT port or convert a static generated-code port.
  Covers runtime architecture, game-file provisioning, oracle integration, first translated
  blocks, and differential verification before title-specific enhancements.
---

# Starting a dynamic-recompiler port

## Choose the execution owner

Identify the guest ISA, executable format, address-space rules, and required hardware services.
Prefer a maintained runtime translator already used by the platform ecosystem. If a shared project
under `shared/` owns that ISA or host-code backend, extend it there instead of creating a title-local
engine.

Choose an accurate, scriptable reference emulator as the oracle. It may also supply hardware models
during bring-up, but the product's execution boundary must remain explicit.

Declare host backends as concrete OS/architecture pairs so their executable-memory,
instruction-cache, ABI, and exception boundaries can be verified independently.

## Scaffold runtime ownership

Create cohesive modules for CPU context, guest memory/address spaces, decoder/IR, host backend and
code cache, platform services, native overrides, bounded fallback, and the differential harness.
Wire their shared execution contract before adding title-specific behavior.

## Provision the user's game file

Resolve an explicit argument, environment/`.env`, then repo drop-in in that order. Validate the
exact revision before mapping it.

## Build the harness first

Give both the runtime and oracle the same initial state, deterministic time, and scripted input.
Compare CPU state, relevant memory, service events, audio, and frames at boundaries fine enough to
locate the first divergence. See **dynarec-harness**.

## Translate the first real path

Start at the title entry point or a deterministic savestate boundary. Compile a bounded block,
execute it, and prove its post-state against the oracle. Then expand coverage along reached control
flow. An unsupported or unsafe block must fail with a precise guest PC or enter the bounded fallback
contract.

Initialization is complete when the runtime consumes the user's binary directly, produces at least
one oracle-proven translated block, and proves ordinary cold blocks compile before execution.

## Enter the port loop

Continue with **dynarec-port**: build, diff, stop at the first divergence, fix the owning runtime or
service boundary, and re-verify. Add **dynarec-overrides** only for deliberately native ownership.
