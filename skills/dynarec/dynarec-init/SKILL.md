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

Declare host backends as concrete OS/architecture pairs. ARM64 projects include both Apple Silicon
macOS and Android arm64-v8a unless the project explicitly excludes one; design executable-memory,
instruction-cache, ABI, and exception boundaries so each can be verified independently without an
interpreter fallback.

## Scaffold runtime ownership

Create cohesive modules for CPU context, guest memory/address spaces, decoder/IR, host backend and
code cache, platform services, native overrides, and the differential harness. A test-only
interpreter may be a separate diagnostic module and target. The gameplay host entry point composes
only product modules; it does not link or select the interpreter.

The build contains only redistributable runtime code and metadata. Do not add an offline translator,
generated-source directory, per-title emitted functions, or a build step that derives native code
from the game binary.

## Provision the user's game file

Support explicit argument, environment/`.env`, and repo drop-in discovery in that order. Validate
the exact revision before mapping it. Never commit or package the game file. A packaged first run
uses the native file picker and persists the validated selection in OS user data.

## Build the harness first

Give both the runtime and oracle the same initial state, deterministic time, and scripted input.
Compare CPU state, relevant memory, service events, audio, and frames at boundaries fine enough to
locate the first divergence. See **dynarec-harness**.

## Translate the first real path

Start at the title entry point or a deterministic savestate boundary. Compile a bounded block,
execute it, and prove its post-state against the oracle. Then expand coverage along reached control
flow. Unsupported behavior fails with a precise guest PC; it does not silently enter the interpreter.

Initialization is complete when the runtime consumes the user's binary directly, produces at least
one proven translated block, and build/link/selector checks prove that the gameplay target contains
no interpreter or fallback.

## Enter the port loop

Continue with **dynarec-port**: build, diff, stop at the first divergence, fix the owning runtime or
service boundary, and re-verify. Add **dynarec-overrides** only for deliberately native ownership.
