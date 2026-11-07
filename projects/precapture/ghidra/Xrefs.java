// List references to addresses, with the containing function.
// Args: <out.txt> <hex-addr> [<hex-addr> ...]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;

import java.io.PrintWriter;

public class Xrefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        try (PrintWriter out = new PrintWriter(args[0], "UTF-8")) {
            for (int i = 1; i < args.length; i++) {
                Address target = toAddr(Long.parseLong(args[i].replace("0x", ""), 16));
                out.println("== refs to " + target);
                ReferenceIterator refs = currentProgram.getReferenceManager().getReferencesTo(target);
                int count = 0;
                while (refs.hasNext()) {
                    Reference ref = refs.next();
                    Function from = getFunctionContaining(ref.getFromAddress());
                    out.println("   " + ref.getFromAddress() + "  " + ref.getReferenceType() + "  "
                            + (from != null ? from.getName() + "@" + from.getEntryPoint() : "?"));
                    count++;
                }
                if (count == 0) {
                    out.println("   (none)");
                }
            }
        }
    }
}
