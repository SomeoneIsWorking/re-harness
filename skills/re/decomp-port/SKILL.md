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

The job is to recover selected functions from a stripped binary, implement the owned behavior
natively, and verify it against ground truth. Fill in the target's architecture and image layout.

## When this vs runtime guest execution

- **dynarec-port / dynarec-runtime** — execute the guest binary on demand.
- **decomp-port (this)** — selectively decompile specific functions or subsystems and re-implement
  them as maintained native code. They compose: a recovered function can become a
  `dynarec-overrides` implementation while every unowned guest path stays executable at runtime.

## 0. Get the code image (per platform)
Extract the executable and know its **load base** (so `file_offset = vaddr − load_base`).
- 3DS: NCCH ExeFS `.code`, often BLZ-compressed (Nintendo backward-LZSS); load base commonly
  `0x00100000`. N64: the ROM's code segments (MIPS, base from the boot/entry). GC/Wii: DOL/REL
  (PPC). PS2: ELF. Verify the image against **live emulator RAM** at a few addresses if you have an
  oracle — a wrong base or bad decompression poisons everything downstream.
- Keep the derived image out of git.

## 1. Import + auto-analyze in Ghidra headless
Use Ghidra's function analysis and decompiler; verify boundaries in mixed-mode code rather than
trusting a linear disassembly sweep.

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
analyzeHeadless <projdir> <projname> -import <code.bin>
# GC DOL specifically: turn off the OptionDialog symbol-map prompt (headless can't show it):
analyzeHeadless <projdir> <projname> -import <code.dol> -loader-autoloadMaps false
# Fallback (no format loader available):
analyzeHeadless <projdir> <projname> -import <code.bin> \
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

**Script runtime:** The bundled `DecompDump.py` is marked `#@runtime Jython` and uses Jython 2.
Ghidra 11.x includes that engine. Ghidra 12.x requires installing the optional
[Jython extension](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/Configurations/Public_Release/src/global/docs/WhatsNew.md)
before running it with `analyzeHeadless`. PyGhidra runs CPython 3 scripts through
`pyghidraRun -H`, but does not turn this bundled script into Python 3. See `ghidra-re` for the
runtime distinction and [official headless arguments](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/RuntimeScripts/support/analyzeHeadlessREADME.md).

**Legacy pre-script fallback** (`DolLoad.py`) — only for Ghidra 11.x installs without the
GameCube loader extension. See DolLoad.py header for the flag set. NOT needed once the extension
is installed.

## 2. Inventory + decompile to C  (bundled `DecompDump.py`)
Run the bundled headless script against the analyzed project (`-process`, `-noanalysis`). Confirm
the targets file exists first: this script currently emits the full inventory when the variable is
unset or the named file is missing.
```
# Ghidra 11.x, or Ghidra 12.x with the Jython extension installed:
DECOMP_TARGETS=<targets-file> analyzeHeadless <projdir> <projname> -process <code.bin> -noanalysis \
    -scriptPath <dir-of-DecompDump.py> -postScript DecompDump.py
```
- No `DECOMP_TARGETS` → writes `build/decomp/functions.csv` (`vaddr,size,name` for all functions).
  Grep it to pick targets and gauge sizes.
- `DECOMP_TARGETS=targets.txt` (one hex vaddr per line, `#` comments) → writes
  `build/decomp/<vaddr>.c`, readable C per function. `DECOMP_OUT` overrides the output directory.
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
3. **Diff** the two — the remake's changes (different animation system, tweaked constants, new state)
   identify the behavior to investigate. Preserve source provenance and implement the recovered
   contract in the owning module.
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
- Jython scripts use Python 2 syntax; PyGhidra scripts use CPython 3. Check the script's runtime
  marker and installed Ghidra version before choosing a launcher.
