# -*- coding: utf-8 -*-
# Locate the PCSplitscreen exec-function strings, their xrefs, and the referencing
# function/data context so we can find the real native function pointer.
from ghidra.program.model.symbol import RefType

listing = currentProgram.getListing()
memory = currentProgram.getMemory()
ref_mgr = currentProgram.getReferenceManager()
dt_mgr = currentProgram.getDataTypeManager()

targets = [
    "UWillowGFxMoviePressStartexecPlayAttractLoop",
    "UWillowGFxMoviePressStartexecIsAttractPlaying",
    "UWillowGFxMoviePressStartexecStopAttractLoop",
]

def dump_bytes_around(addr, n=64):
    try:
        b = getBytes(addr, n)
        return " ".join("%02x" % (x & 0xff) for x in b)
    except Exception as e:
        return "ERR %s" % e

data_iter = currentProgram.getListing().getDefinedData(True)
found = {}
for d in data_iter:
    if not d.hasStringValue():
        continue
    val = d.getValue()
    if val is None:
        continue
    try:
        sval = unicode(val).encode('ascii', 'replace')
    except Exception:
        continue
    for t in targets:
        if t == sval:
            found.setdefault(t, []).append(d.getAddress())

for t in targets:
    print("=== %s ===" % t)
    addrs = found.get(t, [])
    if not addrs:
        print("  NOT FOUND as defined Data (may need raw scan)")
        continue
    for a in addrs:
        print("  STRING AT %s" % a)
        refs = ref_mgr.getReferencesTo(a)
        for r in refs:
            frm = r.getFromAddress()
            func = getFunctionContaining(frm)
            fname = func.getName() if func else "unknown"
            print("    REF FROM %s in func %s (reftype=%s)" % (frm, fname, r.getReferenceType()))
        # dump a small window of bytes before/after the string pointer's own
        # location in memory, in case it's inside an array-of-structs table
        print("    bytes near string: %s" % dump_bytes_around(a, 32))
print("DONE")
