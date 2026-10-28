// Decompile functions to a text file.
// Args: <out.c> <hex-addr> [<hex-addr> ...]
// An address inside a function decompiles the containing function; if no
// function exists there one is created first.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

import java.io.PrintWriter;

public class Decomp extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            printerr("usage: Decomp <out.c> <hex-addr>...");
            return;
        }
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        try (PrintWriter out = new PrintWriter(args[0], "UTF-8")) {
            for (int i = 1; i < args.length; i++) {
                Address addr = toAddr(Long.parseLong(args[i].replace("0x", ""), 16));
                Function function = getFunctionContaining(addr);
                if (function == null) {
                    disassemble(addr);
                    function = createFunction(addr, null);
                }
                if (function == null) {
                    out.println("// no function at " + addr);
                    continue;
                }
                out.println("\n// ===== " + function.getName() + " @ " + function.getEntryPoint()
                        + " (requested " + addr + ") =====");
                DecompileResults result = decompiler.decompileFunction(function, 120, monitor);
                if (result != null && result.decompileCompleted()) {
                    out.println(result.getDecompiledFunction().getC());
                } else {
                    out.println("// decompile failed: "
                            + (result != null ? result.getErrorMessage() : "null result"));
                }
            }
        } finally {
            decompiler.dispose();
        }
    }
}
