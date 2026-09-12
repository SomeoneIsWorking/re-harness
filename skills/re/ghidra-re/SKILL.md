---
name: ghidra-re
description: Use Ghidra headless to decompile a function, find callers or data references, read constants, and disassemble narrow ranges. Pivot to runtime observation when static references cannot reveal indirect dispatch or live arguments.
---

# Ghidra headless RE

Use this for a specific binary question. `decomp-port` covers the broader behavior-porting workflow.

## Project and script runtime

Keep the analyzed Ghidra project under the consumer's `build/ghidra/`; reuse it across queries.
Resolve `analyzeHeadless` from `PATH` or an untracked `GHIDRA_HOME`. Keep scripts that encode only
tool behavior in their shared owner; put title addresses and identities in the consuming project.

The current [Ghidra scripting documentation](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/Features/PyGhidra/src/main/py/README.md)
describes PyGhidra for CPython 3. For Ghidra 12.x, Jython scripts require the optional
[Jython extension](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/Configurations/Public_Release/src/global/docs/WhatsNew.md);
`#@runtime Jython` selects that engine. Ghidra 11.x includes Jython. Do not relabel a Jython 2
script as Python 3 or assume a `.py` script runs under the same engine on both versions. Run
PyGhidra scripts with `pyghidraRun -H` and Jython scripts with `analyzeHeadless` after verifying
the extension is available. Both accept headless `-process`, `-noanalysis`, `-scriptPath`, and
`-postScript` arguments. [Headless arguments](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/RuntimeScripts/support/analyzeHeadlessREADME.md)
also support arguments following a script name; use environment variables only when the existing
script contract requires them.

```text
analyzeHeadless build/ghidra <project> -process <program> -noanalysis \
  -scriptPath <script-directory> -postScript <script-name.py> <script-args>
```

Use the Jython extension for the bundled `decomp-port/DecompDump.py`; it is explicitly marked
`#@runtime Jython` and uses Jython 2 syntax. Porting it to PyGhidra requires a separate code change
and verification, not a launcher substitution.

## Answer one question at a time

| Question | Ghidra operation |
|---|---|
| Which function contains this VA? | Function manager lookup at the address. |
| Who directly calls this function? | Reference manager code references, then inspect each enclosing caller. |
| Who reads or writes this data VA? | Reference manager access mode and enclosing function. |
| What constant is stored here? | Read bytes from program memory with the target's endianness. |
| What does the function do? | Decompile its entry; preserve decompiler warnings and a narrow raw-disassembly check. |
| What instruction caused this behavior? | Disassemble a small address range around the observed PC. |

Prefer an existing project script for the operation. A new script should have one purpose, explicit
inputs, and output that reports both matches and the number of candidates scanned. Missing programs,
addresses, or target files must fail visibly. A zero-reference result is evidence only that the
reference database did not materialize an edge.

## When static references stop helping

Function pointers, vtables loaded through objects, base-plus-offset accesses, and live pointer
arguments may have no useful static cross-reference. Capture the destination PC and relevant
registers with the target's runtime observation harness, then map those PCs back to functions in
Ghidra. At the suspected writer, watch the address and record writer PC, caller context, arguments,
and stack state. Repeating broad decompilation is not a substitute for observing indirect dispatch.

Record the identified function, address, evidence path, and verification in the nearest living RE
document. Decompiled C is a reading aid; use it to implement behavior in the owning source module,
then verify the result against real binary or runtime evidence.
