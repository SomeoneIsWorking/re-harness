# -*- coding: utf-8 -*-
# Dump raw instruction bytes+mnemonics for target functions so we can identify
# the exact call-site to patch (byte-for-byte, same length, no relocation needed).
addr_factory = currentProgram.getAddressFactory()
listing = currentProgram.getListing()

targets = [0x0079a9f0, 0x0079ae40, 0x0079ae80]

def to_addr(v):
    return addr_factory.getDefaultAddressSpace().getAddress(v)

for t in targets:
    print("=== function @ 0x%08x ===" % t)
    func = getFunctionAt(to_addr(t))
    if func is None:
        print("  no function here")
        continue
    body = func.getBody()
    instr = listing.getInstructionAt(to_addr(t))
    while instr is not None and body.contains(instr.getAddress()):
        b = instr.getBytes()
        bstr = " ".join("%02x" % (x & 0xff) for x in b)
        print("  %s  [%2d]  %-30s  %s" % (instr.getAddress(), len(b), bstr, instr.toString()))
        instr = instr.getNext()
print("DONE")
