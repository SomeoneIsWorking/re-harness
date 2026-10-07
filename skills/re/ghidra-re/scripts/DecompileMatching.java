// Decompiles functions whose full name matches a regex, or the callers of those functions.
// Args: <methods|callers> <regex> <output file>
//@category Analysis
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

import java.io.PrintWriter;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.regex.Pattern;

public class DecompileMatching extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 3 || !(args[0].equals("methods") || args[0].equals("callers"))) {
            throw new IllegalArgumentException("usage: <methods|callers> <regex> <output file>");
        }
        Pattern pattern = Pattern.compile(args[1]);
        Set<Function> matched = new LinkedHashSet<>();
        int scanned = 0;
        for (Function function : currentProgram.getFunctionManager().getFunctions(true)) {
            scanned++;
            if (pattern.matcher(function.getName(true)).find()) {
                matched.add(function);
            }
        }
        Set<Function> targets = matched;
        if (args[0].equals("callers")) {
            targets = new LinkedHashSet<>();
            for (Function callee : matched) {
                for (Reference ref : getReferencesTo(callee.getEntryPoint())) {
                    Function caller = getFunctionContaining(ref.getFromAddress());
                    if (caller != null) {
                        targets.add(caller);
                    }
                }
            }
        }

        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        try (PrintWriter out = new PrintWriter(args[2], "UTF-8")) {
            out.printf("// %s: scanned %d functions, matched %d, writing %d%n", currentProgram.getName(),
                    scanned, matched.size(), targets.size());
            for (Function function : targets) {
                DecompileResults result = decompiler.decompileFunction(function, 120, monitor);
                out.printf("%n// ==== %s @ %s%n", function.getName(true), function.getEntryPoint());
                if (result.decompileCompleted()) {
                    out.println(result.getDecompiledFunction().getC());
                } else {
                    out.println("// decompile failed: " + result.getErrorMessage());
                }
            }
        }
        decompiler.dispose();
        println(String.format("scanned %d, matched %d, wrote %d", scanned, matched.size(), targets.size()));
    }
}
