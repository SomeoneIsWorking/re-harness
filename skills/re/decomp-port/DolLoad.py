# -*- coding: utf-8 -*-
# Ghidra preScript — rebuilds memory blocks for a GameCube DOL after BinaryLoader
# has imported the raw file. BinaryLoader loads the DOL flat at a single base; this
# script parses the DOL header (7 text sections + 11 data sections + BSS + entry),
# deletes the flat block, and creates properly-addressed memory blocks per section
# using the file bytes read via DOL_PATH.
#
# Env:
#   DOL_PATH   path to the .dol file to reparse (required)
#
# Run before analysis:
#   analyzeHeadless <projdir> <projname> -import <dol> -processor "PowerPC:BE:32:default" \
#       -loader BinaryLoader -loader-baseAddr 0x80003100 \
#       -scriptPath <dir> -preScript DolLoad.py
import os, struct
from ghidra.program.model.mem import MemoryConflictException
from ghidra.util.task import ConsoleTaskMonitor
from java.io import ByteArrayInputStream

DOL_PATH = os.environ.get("DOL_PATH")
if not DOL_PATH or not os.path.isfile(DOL_PATH):
    print("[DolLoad] FATAL: DOL_PATH env not set or file missing: %r" % DOL_PATH)
    raise SystemExit(1)

with open(DOL_PATH, "rb") as f:
    dol = f.read()

# Header: 7 text file_off + 11 data file_off + 7 text mem_addr + 11 data mem_addr
# + 7 text size + 11 data size + bss_addr + bss_size + entry
def U32s(off, n):
    return struct.unpack(">%dI" % n, dol[off:off+4*n])
t_off = U32s(0, 7)
d_off = U32s(28, 11)
t_addr = U32s(72, 7)
d_addr = U32s(100, 11)
t_size = U32s(144, 7)
d_size = U32s(172, 11)
bss_addr, bss_size, entry = struct.unpack(">III", dol[216:228])

program = currentProgram
mem = program.getMemory()
af = program.getAddressFactory().getDefaultAddressSpace()
mon = ConsoleTaskMonitor()

# Delete the flat block created by BinaryLoader (any block whose name matches the file basename)
existing = list(mem.getBlocks())
print("[DolLoad] existing blocks: %d" % len(existing))
for b in existing:
    print("[DolLoad]   drop '%s' 0x%x..0x%x (size 0x%x)" % (
        b.getName(), b.getStart().getOffset(), b.getEnd().getOffset(), b.getSize()))
    mem.removeBlock(b, mon)

def add_block(name, mem_addr, sz, file_off, initialized=True):
    start = af.getAddress(mem_addr)
    if initialized:
        bytes_java = jarray_from(dol[file_off:file_off+sz])
        blk = mem.createInitializedBlock(name, start, ByteArrayInputStream(bytes_java),
                                         sz, mon, False)
    else:
        blk = mem.createUninitializedBlock(name, start, sz, False)
    blk.setRead(True); blk.setWrite(True); blk.setExecute(name.startswith("text"))
    return blk

def jarray_from(pystr):
    # In Jython, bytes → a Python 2 str. We need a Java byte[]; ByteArrayInputStream takes any.
    return pystr

for i in range(7):
    if t_size[i]:
        add_block("text%d" % i, t_addr[i], t_size[i], t_off[i], True)
        print("[DolLoad] TEXT%d 0x%08x size=0x%x" % (i, t_addr[i], t_size[i]))
for i in range(11):
    if d_size[i]:
        add_block("data%d" % i, d_addr[i], d_size[i], d_off[i], True)
        print("[DolLoad] DATA%d 0x%08x size=0x%x" % (i, d_addr[i], d_size[i]))
if bss_size:
    add_block("bss", bss_addr, bss_size, 0, initialized=False)
    print("[DolLoad] BSS 0x%08x size=0x%x" % (bss_addr, bss_size))

# Set entry symbol for reference
try:
    sym = program.getSymbolTable().createLabel(af.getAddress(entry), "__start",
        program.getGlobalNamespace(), 0)
    program.getSymbolTable().addExternalEntryPoint(af.getAddress(entry))
except Exception as e:
    print("[DolLoad] entry-label warn: %s" % e)
print("[DolLoad] entry 0x%08x" % entry)
print("[DolLoad] DONE — analysis will run over correctly-based sections")
