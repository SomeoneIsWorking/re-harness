# -*- coding: utf-8 -*-
# Dump raw dwords around the native-function registration table entries that
# reference the PCSplitscreen exec-function name strings, to find the paired
# function pointer, then decompile it.
from ghidra.program.model.address import Address

addr_factory = currentProgram.getAddressFactory()

table_addrs = [0x019bda18, 0x019bda00, 0x019bda08, 0x019bda90, 0x019bda48, 0x019bda50]

def to_addr(v):
    return addr_factory.getDefaultAddressSpace().getAddress(v)

def read_dword(a):
    b = getBytes(a, 4)
    v = 0
    for i in range(4):
        v |= (b[i] & 0xff) << (8 * i)
    return v & 0xffffffff

for base in table_addrs:
    print("=== table region around 0x%08x ===" % base)
    for off in range(-4, 8, 4):
        a = to_addr(base + off)
        v = read_dword(a)
        func = getFunctionAt(to_addr(v)) if v > 0x400000 and v < 0x2000000 else None
        fname = func.getName() if func else ""
        print("  0x%08x: 0x%08x  %s" % (base + off, v, fname))
print("DONE")
