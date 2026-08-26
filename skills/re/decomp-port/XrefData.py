# Find data references to 0x80414028 (the 200000.0f SDA2 slot)
from ghidra.program.model.address import AddressFactory
addr = currentProgram.getAddressFactory().getAddress("0x80414028")
refs = list(currentProgram.getReferenceManager().getReferencesTo(addr))
print(f"[xref] {len(refs)} references to 0x80414028")
for r in refs[:40]:
    src = r.getFromAddress()
    fn = currentProgram.getFunctionManager().getFunctionContaining(src)
    fname = fn.getName() if fn else "?"
    print(f"  {src} in {fname}  type={r.getReferenceType()}")

# Also for 500000
addr2 = currentProgram.getAddressFactory().getAddress("0x8041402c")
refs2 = list(currentProgram.getReferenceManager().getReferencesTo(addr2))
print(f"[xref] {len(refs2)} references to 0x8041402c")
for r in refs2[:40]:
    src = r.getFromAddress()
    fn = currentProgram.getFunctionManager().getFunctionContaining(src)
    fname = fn.getName() if fn else "?"
    print(f"  {src} in {fname}  type={r.getReferenceType()}")
