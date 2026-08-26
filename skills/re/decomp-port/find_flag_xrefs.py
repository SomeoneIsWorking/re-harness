# -*- coding: utf-8 -*-
# Find all references to the DAT_01ad0bf0 global (the PCSplitscreenEnabled flag)
# so we can see what code actually branches on it.
addr_factory = currentProgram.getAddressFactory()
ref_mgr = currentProgram.getReferenceManager()

def to_addr(v):
    return addr_factory.getDefaultAddressSpace().getAddress(v)

flag_addr = to_addr(0x01ad0bf0)
refs = ref_mgr.getReferencesTo(flag_addr)
seen = set()
print("=== xrefs to DAT_01ad0bf0 ===")
for r in refs:
    frm = r.getFromAddress()
    func = getFunctionContaining(frm)
    fname = func.getName() if func else "unknown"
    faddr = func.getEntryPoint() if func else None
    key = str(faddr)
    if key not in seen:
        seen.add(key)
        print("  FUNC %s @ %s" % (fname, faddr))
    print("    ref from %s (type=%s)" % (frm, r.getReferenceType()))
print("DONE, %d unique functions" % len(seen))
