---
name: ghidra-re
description: "Ghidra headless: decompile, callers/refs, constants, loaders per platform, anchor finding, align against a community decomp. Pivot to runtime observation when static references cannot reveal indirect dispatch or live arguments. Bundles DecompDump.py and DecompileMatching.java."
---

# Ghidra headless RE

If the project has its own Ghidra pipeline (psx: `psxport/docs/workspace/GHIDRA.md`,
`decomp_pipeline.py`), use it; this skill is for projects without one.

## Get the code image

Extract the executable and know its load base (`file_offset = vaddr - load_base`). 3DS: NCCH ExeFS
`.code`, often BLZ-compressed, base commonly `0x00100000`. N64: ROM code segments. GC/Wii: DOL/REL.
PS2: ELF. Check a few addresses against live emulator RAM if an oracle exists; a wrong base poisons
everything downstream. The derived image stays out of git.

## Import and analyze

Keep the analyzed project under the consumer's `build/ghidra/` and reuse it. Resolve
`analyzeHeadless` from `PATH` or an untracked `GHIDRA_HOME`; set
`-Djava.io.tmpdir=<repo>/scratch/ghidra-tmp`.

Prefer a format loader over `BinaryLoader`: it maps sections at their own bases and marks code and
data. `BinaryLoader` maps the whole file at one base, so a header (GC DOL's 256 bytes) shifts every
function address.

| Platform | Loader extension | Language |
|---|---|---|
| GC, Wii (DOL/REL) | [Cuyler36/Ghidra-GameCube-Loader](https://github.com/Cuyler36/Ghidra-GameCube-Loader), matching your Ghidra | `PowerPC:BE:32:Gekko_Broadway` |

```text
analyzeHeadless <projdir> <projname> -import <code.bin>
analyzeHeadless <projdir> <projname> -import <code.dol> -loader-autoloadMaps false   # GC DOL
analyzeHeadless <projdir> <projname> -import <code.bin> \
    -processor <LANG_ID> -loader BinaryLoader -loader-baseAddr <BASE>                # no loader
```

| Platform | `LANG_ID` |
|---|---|
| 3DS, ARM Thumb-2 | `ARM:LE:32:Cortex` |
| N64, MIPS | `MIPS:BE:32:default` |
| GC, Wii, stock | `PowerPC:BE:32:default` |
| PSX, PS2 | `MIPS:LE:32:default` |
| x86-32 | `x86:LE:32:default` |

## Scripts

PyGhidra runs CPython 3 scripts (`pyghidraRun -H`). `#@runtime Jython` scripts use Python 2 and
need the optional Jython extension on Ghidra 12.x (built into 11.x). Check the runtime marker before
choosing a launcher; relabelling a script is not a port. Both accept `-process`, `-noanalysis`,
`-scriptPath` and `-postScript <script> <args>`.

- `scripts/DecompileMatching.java` (no extra runtime): `-postScript DecompileMatching.java
  <methods|callers> <regex> <out>` decompiles every function whose name matches, or their callers.
  It also reads Dalvik (DEX) programs where jadx fails.
- `scripts/DecompDump.py` (Jython): with `DECOMP_TARGETS=<file>` (one hex vaddr per line) writes
  `build/decomp/<vaddr>.c`; without it writes `build/decomp/functions.csv` (`vaddr,size,name`).
  `DECOMP_OUT` moves the output, `DECOMP_SLIDE` adds an image-base slide.

## Answer one question at a time

| Question | Ghidra operation |
|---|---|
| Which function contains this VA? | Function manager lookup at the address. |
| Who directly calls this function? | Reference manager code references, then inspect each enclosing caller. |
| Who reads or writes this data VA? | Reference manager access mode and enclosing function. |
| What constant is stored here? | Read bytes from program memory with the target's endianness. |
| What does the function do? | Decompile its entry; keep decompiler warnings and a narrow raw-disassembly check. |
| What instruction caused this behavior? | Disassemble a small address range around the observed PC. |

A missing program, address or target file must fail visibly. A zero-reference result only means the
reference database has no edge.

## Find anchors

- Live oracle: read an object's update/draw/init handler pointers from emulator RAM; those are the
  functions to decompile.
- Strings: `__FILE__` asserts and log formats bound a translation unit. Many toolchains emit them
  PC-relative, so use Ghidra's xrefs, not an absolute-literal search.
- Entry and known structures: the crt0 init table, vtables, jump tables.

## Align against a community decomp

For a remake or re-port of a game that has a decomp (or a sequel sharing its engine), do not read
blind disassembly. Decompile the binary function, align it to its twin by branch shape, call order,
strings and constants, and diff: the differences are the behavior to investigate. Keep an
`addr <-> reference name` map as you go, and keep the source's provenance.

## When static references stop helping

Function pointers, vtables, base-plus-offset accesses and live arguments may have no static
cross-reference. Capture the destination PC and registers with the target's runtime observation
harness and map them back to functions. At a suspected writer, watch the address and record writer
PC, caller, arguments and stack.

## Gotchas

- Ghidra types are guesses. Define the real struct once in the project and re-dump.
- Mixed ARM/Thumb: a function that decompiles to garbage may be in the other mode; force it.
- Decompiled C is a reading aid: it uses absolute addresses and Ghidra intrinsics. Re-express it in
  the owning module's symbols, and record the function, address and evidence in the nearest RE doc.
