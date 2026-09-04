---
name: decomp-port
description: >-
  Ghidra-headless decompilation pipeline for porting specific functions/behaviors out of a
  console/game binary into your own C — turn a stripped ROM/executable into readable C, find
  anchor functions, and (when the target is a remake/re-port of a game you already have
  decompiled) use that source as a Rosetta stone to align + diff + port the divergences. Use
  when reverse-engineering or porting a game's logic from its binary (any arch: ARM/MIPS/PPC/
  x86), especially a remake whose original has a community decomp. Complements runtime guest
  execution by selectively decompiling and re-implementing owned behavior. Bundles a reusable
  headless decompile script (DecompDump.py).
---

# Ghidra decompilation & behavior-porting pipeline

Reusable across projects/games. The job: a stripped game binary → readable C for the functions
you care about → re-implemented natively in your engine, verified against ground truth. This is
the "porting machine." Game/arch specifics below are PARAMETERS — fill them per target.

## When this vs runtime guest execution

- **dynarec-port / dynarec-runtime** — execute the complete guest binary through an interpreter or
  on-demand dynamic translator.
- **decomp-port (this)** — selectively decompile specific functions or subsystems and re-implement
  them as maintained native code. They compose: a recovered function can become a
  `dynarec-overrides` implementation while every unowned guest path stays executable at runtime.

## 0. Get the code image (per platform)
Extract the executable and know its **load base** (so `file_offset = vaddr − load_base`).
- 3DS: NCCH ExeFS `.code`, often BLZ-compressed (Nintendo backward-LZSS); load base commonly
  `0x00100000`. N64: the ROM's code segments (MIPS, base from the boot/entry). GC/Wii: DOL/REL
  (PPC). PS2: ELF. Verify the image against **live emulator RAM** at a few addresses if you have an
  oracle — a wrong base or bad decompression poisons everything downstream.
- Keep the image OUT of git (it's ROM-derived). ROMs stay external (see dynarec-port provisioning).

## 1. Import + auto-analyze in Ghidra headless
Ghidra is the only reliable function-boundary + C decompiler for stripped, mixed-mode binaries
(linear capstone/objdump sweeps DESYNC on variable-length / mixed ARM↔Thumb / delay-slot code).

**Prefer a format-specific loader over BinaryLoader** when one exists — a real Loader parses
sections, sets the right load base per section, marks code vs data, and populates the entry
point. BinaryLoader flattens the whole file at a single base and misses ALL of that (the file
header (e.g. GC DOL's 256-byte header) ends up mapped INTO the code section, offsetting every
function address by the header size → `FUN_8019ffa4` where the real function is at
`0x8019ffe4`, and every RE cross-reference silently derails).

Known extensions to install first (use Ghidra's **File → Install Extensions** interface, or its
documented user-extension directory):
| platform | extension | loader/lang |
|---|---|---|
| GC · Wii / DOL · REL | [Cuyler36/Ghidra-GameCube-Loader](https://github.com/Cuyler36/Ghidra-GameCube-Loader) release matching your Ghidra version | Nintendo GameCube/Wii Binary + `PowerPC:BE:32:Gekko_Broadway` |

```
GHIDRA=/opt/ghidra_*/support/analyzeHeadless     # 11.x/12.x; needs a JDK
$GHIDRA <projdir> <projname> -import <code.bin>  # loader auto-detects when installed
# GC DOL specifically: turn off the OptionDialog symbol-map prompt (headless can't show it):
$GHIDRA <projdir> <projname> -import <code.dol> -loader-autoloadMaps false
# Fallback (no format loader available):
$GHIDRA <projdir> <projname> -import <code.bin> \
    -processor <LANG_ID> -loader BinaryLoader -loader-baseAddr <BASE>
```
Pick `LANG_ID` for the target arch (`analyzeHeadless ... -processor ?` lists them):
| platform | LANG_ID |
|---|---|
| 3DS / ARM Thumb-2 | `ARM:LE:32:Cortex` |
| N64 / MIPS | `MIPS:BE:32:default` |
| GC·Wii / PowerPC (stock, no loader ext) | `PowerPC:BE:32:default` |
| GC·Wii / PowerPC (with GameCube loader ext — paired singles + Broadway) | `PowerPC:BE:32:Gekko_Broadway` |
| PSX·PS2 / MIPS LE | `MIPS:LE:32:default` |
| x86-32 | `x86:LE:32:default` |
Analysis of a few-MB binary takes minutes–tens of minutes and saves into the project. Set
`-Djava.io.tmpdir=<repo>/scratch/ghidra-tmp` so Ghidra's cache stays in the project's gitignored,
bounded scratch area instead of a host-global temporary directory.

**Ghidra ≥12 scripts:** Jython is gone; postScripts run under PyGhidra. Launch headless with
`pyghidraRun -H <projdir> …` (not `analyzeHeadless`) so `-postScript foo.py` works. `analyzeHeadless`
still works for `-import` / `-preScript` runs where no Python script fires.

**Legacy pre-script fallback** (`DolLoad.py`) — only for Ghidra 11.x installs without the
GameCube loader extension. See DolLoad.py header for the flag set. NOT needed once the extension
is installed.

## 2. Inventory + decompile to C  (bundled `DecompDump.py`)
Run the bundled headless script against the ANALYZED project (`-process`, `-noanalysis`):
```
# Ghidra 12+: run the bundled Python 3 script through PyGhidra.  Its CLI
# accepts the binary path directly; DECOMP_TARGETS selects addresses/functions.
OOT_REPO=$PWD DECOMP_TARGETS=<targets-file> pyghidra --skip-analysis \
    --project-path <projdir> --project-name <projname> <code.bin> \
    <dir-of-DecompDump.py>/DecompDump.py

# Ghidra 11 and older only (Jython postScript provider):
OOT_REPO=$PWD analyzeHeadless <projdir> <projname> -process <code.bin> -noanalysis \
    -scriptPath <dir-of-DecompDump.py> -postScript DecompDump.py
```
- No `DECOMP_TARGETS` → writes `build/decomp/functions.csv` (`vaddr,size,name` for all functions).
  Grep it to pick targets and gauge sizes.
- `DECOMP_TARGETS=targets.txt` (one hex vaddr per line, `#` comments) → writes
  `build/decomp/<vaddr>.c`, clean readable C per function. `OOT_REPO`/`DECOMP_OUT` set the out dir.
Re-decompiling is cheap; iterate (rename a struct/type in the project, re-dump).

## 3. Find anchors — where to start decompiling
You rarely want all N thousand functions; you want the ones behind a behavior. Locate them by:
- **Live oracle (best):** read the object/actor's function pointers from emulator RAM (its
  update/draw/init handlers) — those vaddrs ARE the functions to decompile. (See dynarec-harness for
  standing up an oracle: scriptable RAM read/write + input + screenshot.)
- **Strings:** `__FILE__` assert strings / log format strings name the source file + line; xref
  them to bound a translation unit's functions. NB many toolchains emit these PC-relative (ADR),
  so an absolute-literal search misses them — let Ghidra's xrefs find them.
- **Entry/known structs:** crt0 init table at entry; vtables; jump tables.

## 4. The Rosetta-stone method (the force multiplier for remakes/re-ports)
If the target is a **remake or re-port of a game whose source you already have decompiled** (e.g. a
3DS/HD/Switch remake of an N64/GC title with a community decomp, or a sequel sharing an engine):
DON'T read blind disassembly. For each target function:
1. Ghidra-decompile the binary function to C.
2. **Align** it to its twin in the reference source by structure + call graph + string/const
   fingerprints (same branch shape, same magic numbers, same call order).
3. **Diff** the two — the remake's CHANGES (different anim system, tweaked constants, new state) are
   exactly what you're porting; everything identical you can copy from the readable reference.
This is ~10x faster than cold decompilation and tells you *why* the remake behaves differently.
Keep a durable `addr ↔ reference-name` map as you go.

## 5. Re-implement + verify (faithful first)
Port each function into your engine's types, then VERIFY against ground truth before claiming it
works: frame-accurate RAM/behavior compare vs the live oracle, or bit-exact vs the reference. Never
mark "ported/fixed" on a vibe — that mark gets falsified by playtest. Faithful port first; PC-native
enhancements only on a proven-faithful base (see dynarec-port "faithful first, then enhance").

## Gotchas
- Ghidra types are guesses: `undefined4`/`int` everywhere. Define the real struct once in the
  project (or annotate offsets from your oracle) and re-dump — readability jumps.
- Mixed ARM/Thumb: if a function decompiles to garbage, the bytes may be the other mode; check
  Ghidra's disassembly and force the mode at that address.
- The decompiled `<vaddr>.c` is a READING/PORTING aid, not buildable as-is — it references absolute
  addresses and Ghidra intrinsics. Re-express it in your engine's symbols.
- Jython (Ghidra scripts) is Python 2: ASCII or a `# -*- coding: utf-8 -*-` header.
