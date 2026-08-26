# Query Ghidra for SDA2 (r2) and SDA1 (r13) bases used during analysis.
prog = currentProgram
symtab = prog.getSymbolTable()
lang = prog.getLanguage()
regs = lang.getRegisters()
# Ghidra stores register values as ContextRegister values. Look for gpLightManager symbol.
for name in ['_SDA_BASE_', '_SDA2_BASE_', 'gpLightManager', 'gpTLightCommonLightAry']:
    it = symtab.getSymbols(name)
    for sym in it:
        print(f'SYM {name} = {sym.getAddress()}')

# Ghidra program context register values
pc = prog.getProgramContext()
for r in ['r2', 'r13']:
    reg = lang.getRegister(r)
    if reg:
        # Sample at the ctor address 0x80228534
        addr = prog.getAddressFactory().getAddress("0x80228534")
        val = pc.getRegisterValue(reg, addr)
        print(f'{r} at 0x80228534 = {val}')
