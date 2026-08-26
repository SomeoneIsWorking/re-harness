# Look for references from ANY code to the address range 0x80414020..0x80414050
from ghidra.program.model.address import AddressFactory
af = currentProgram.getAddressFactory()
rm = currentProgram.getReferenceManager()
fm = currentProgram.getFunctionManager()
lo = 0x80414020; hi = 0x80414050
print(f"[xref] scanning range 0x{lo:x}..0x{hi:x}")
callers = {}
for va in range(lo, hi, 4):
    a = af.getAddress(f"0x{va:x}")
    for r in rm.getReferencesTo(a):
        src = r.getFromAddress()
        fn = fm.getFunctionContaining(src)
        fname = fn.getName() if fn else "?"
        callers.setdefault(fname, []).append((str(src), va, str(r.getReferenceType())))
if not callers: print("  no references (Ghidra hasn't tracked data xrefs)")
for name, hits in callers.items():
    print(f"  {name} ({len(hits)} refs)")
    for src, va, t in hits[:5]:
        print(f"    from {src} -> 0x{va:x} type={t}")
