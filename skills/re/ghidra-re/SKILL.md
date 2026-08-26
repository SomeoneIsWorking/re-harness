---
name: ghidra-re
description: >-
  Ghidra headless RE workflow — decompile functions to C, walk call graphs, resolve pool
  constants, and disasm specific ranges via `analyzeHeadless` + reusable Jython scripts.
  Composes with a dynamic-observation harness (memory-write watchpoints, arg-reg capture)
  when static xrefs are missing (fn-ptr dispatch tables, base+offset loads that Ghidra's
  Reference DB doesn't materialize). Use whenever a session needs: "what function contains
  VA X", "who calls fn Y", "who reads/writes .data VA Z", "what's at ROM offset K",
  "disasm this range", "decompile these functions to C". Distinct from decomp-port (which
  is the higher-level game-port arc); this is the RE plumbing that decomp-port uses.
metadata:
  node_type: skill
  type: workflow
---

# ghidra-re — headless RE workflow

The `decomp-port` skill covers the *arc* (find the anchor, port the fn, verify). This
skill covers the *plumbing* — running Ghidra headless, composing Jython scripts, and
knowing when static Ghidra falls short so you extend with dynamic observation instead of
grinding at it manually.

## 1. Environment (pin per workspace)

- Pin the supported Ghidra version in the target project's documentation. Resolve
  `analyzeHeadless`/`pyghidraRun` from `PATH`, or derive it from `${GHIDRA_HOME}` in an untracked
  environment file. Never commit an installation path.
- Per-project Ghidra project lives at `<repo>/build/ghidra/<name>{,.gpr,.rep}`. The .gpr/
  .rep pair persists analysis state across runs — do NOT delete unless you actually want
  to re-analyze from scratch (auto-analysis of a 30MB console binary takes 20+ min).
- Scripts live at `<repo>/tools/ghidra_scripts/` and are Jython (each file starts with
  `#@runtime Jython`). ARGS pass via ENV vars (Ghidra's headless interface exposes no
  script argv). Convention: `<PROJECT_UPPER>_<PURPOSE>` (for example,
  `TARGET_CALL_TARGET`).

Reference invocation from a project root:
```
TARGET_CALL_TARGET=0x003CF3C4 \
  analyzeHeadless build/ghidra <project-name> \
    -process code.bin -noanalysis \
    -scriptPath tools/ghidra_scripts \
    -postScript ListCallers.py 2>&1 | grep -v INFO | tail -30
```

Replace the project name, program name, and environment prefix with the target project's recorded
values.

## 2. The reusable script library

These live at `<repo>/tools/ghidra_scripts/`. Reach for one before writing new code; they compose.

| script | purpose | env |
|---|---|---|
| `DecompDump.py` | Decompile fn containing VA to `build/decomp/<VA>.c`. With no targets file, dumps `functions.csv` inventory instead. | `DECOMP_TARGETS=path/to/targets.txt`, optional `DECOMP_SLIDE=0x...` when Ghidra rebased the image |
| `ListCallers.py` | List every fn that BLs to a target VA (uses Reference DB — catches bl call xrefs). | `<PROJECT>_CALL_TARGET=<hex>` |
| `FindDataWriters.py` | For each VA in targets file, list every code ref + access mode + enclosing fn. Ghidra's DB already resolves movw/movt + pool ldr + indexed-base offsets — no need to reimplement scanners. | `<PROJECT>_DATA_TARGETS=path/to/targets.txt` |
| `FindMovwMovtWriters.py` | Per-fn constant tracker (movw/movt pair recovery). Use ONLY when Reference DB misses a specific pattern; otherwise `FindDataWriters` is more accurate. | (VA range inside script) |
| `FindRangeRefs.py` | All refs to VAs inside a range — good for surfacing scattered pool constants. | `<PROJECT>_RANGE_START/END` |
| `Disasm.py` | Print instructions in [start, end) range. Named for "I need to see the raw ARM" — spot-verify with a named reason (not blanket disasm-everything). | `<PROJECT>_DISASM_START/END` |
| `FnAt.py` | Given a VA, print the fn that contains it. Cheap answer to "what function did LR point into." | `<PROJECT>_FN_AT` |
| `ReadWord.py` | Read u32(s) at listed VAs — pool-literal resolution (kMaxYawStep=267, kPathSpeed=8.0f style). Beats mem-poking in the harness when the value is a compile-time constant. | `<PROJECT>_READ_VAS=hex1,hex2,...` |

**Adding a new script.** Keep it tiny — one purpose, env-driven args, print one line per
hit. Start file with `#@runtime Jython`, use `currentProgram.getAddressFactory()
.getDefaultAddressSpace()` and `getFunctionManager()`/`getReferenceManager()`. Look at
`FnAt.py` (17 lines) for the minimal shape.

## 3. Compose primitives, don't grind

The pattern that keeps saving hours:

- **"What fn calls X?"** → `ListCallers` → decomp the caller.
- **"Where is the load of .data VA Y?"** → `FindDataWriters` → for each caller, decomp
  the ldr context.
- **"What's this pool constant?"** → `ReadWord` — do NOT decomp to guess; just read.
- **"What's the exact ARM at this store?"** → `Disasm` a narrow window — often reveals
  what the C decomp abstracted away (`vcvt.f32.s32` vs implied s16 was the pivotal
  finding this session).
- **"Which fn does this LR/PC belong to?"** → `FnAt`.
- **"Give me the C body"** → `DecompDump` with a small targets file.

## 4. When Ghidra falls short — pivot to dynamic

Ghidra's Reference DB does NOT catch:
- Function pointers dispatched via `ldr rN, [base, #K]; blx rN` where `base` is a struct
  ptr — the target ptr slot in .data shows zero xrefs from code. This session's
  `PathFollow_Update` at `0x003CF3C4` was reached this way; `ListCallers` returned only
  the .data slot at `0x00526DE8` (the fn-ptr storage), no calling code.
- Indexed dispatch via a vtable in .rodata where the table pointer itself is loaded from
  a heap struct field.
- Any dynamic (heap/stack) pointer arg.

The fix is NOT to run more Ghidra scans; it's to **let the running program tell you**.
Use the target project's dynamic-observation harness (or `recomp-harness` when it is a static
recomp project):
- Register a memory-write watchpoint at the target VA.
- Observe writer PC + LR + r0..r3 + SP at fire time.
- Cross-reference PC via `FnAt.py`, LR via `FnAt.py`, arg regs via harness live reads.

This session's path_node pinning went: static Ghidra → 0 refs → JIT watchpoint on speed_xz
(caught PC + stale LR) → static `FnAt` on LR (confirmed it was inside `Math_Atan2S`, stale
from an inner BL) → HARNESS EXTENSION to capture r0..r3 → stack-slot watchpoint at
`sp+0xC` inside `FUN_003CF3C4`'s frame → `r2=path_node` at PC=`0x003CF3C4` entry ✓.

**Rule:** if you find yourself decomp'ing a fifth fn to trace an arg through several BLs,
stop — instrument the harness and watch the value at its destination instead.

## 5. Recording findings

Write RE'd function bodies to the target's cohesive source module with this shape:
- Per-fn header: `/** VA — decomp source — verification (JIT? disasm? cross-fn?) */`
- Named field-offset `#define`s at the top of the file, NEVER raw byte offsets inside
  the body (search for "raw byte offset" in the AGENTS.md hard rules).
- One-line comment per function citing `build/decomp/<VA>.c` as the Ghidra source.

Update `docs/*.md` in the same commit — the RE'd fn body + the derivation trail. Future
sessions read the doc before re-deriving.

## 6. Machine-specific paths — the hard rule

Committed scripts must not contain a user's absolute home path. Use bare tool names on `$PATH`
(`analyzeHeadless`) or repo-relative paths (`build/ghidra/...`). If a script needs to locate Ghidra,
read `${GHIDRA_HOME}` from untracked environment configuration and fail by naming that requirement;
never commit the resolved install path.
