#!/usr/bin/env python3
"""lens_probe.py — read the L-mount lens's memory over the USB shell.
Uses CmdRead(lens_mgr=0xC347CB14, addr, len, dest, 0) via an injected routine.

  from lens_probe import LensProbe
  lp = LensProbe(); lp.read(0x000000, 32)         # read 32 bytes @ lens addr 0
  lp.scan(0, 0x400, 64)                           # scan a range
"""
import sys, time
sys.path.insert(0,'/Users/dido/Developer.localized/SIGMAfp_re/codex/fpshell_tool/monitor')
import fpstate as F
LENS_WORDS = (0xE92D4FF0,0xE59F0034,0xE5901000,0xE5902004,0xE59F302C,0xE3A04000,0xE52D4004,
              0xE30C0B14,0xE34C0347,0xE59FC01C,0xE12FFF3C,0xE28DD004,0xE59F1008,0xE5810008,
              0xE8BD4FF0,0xE12FFF1E,0,0,0xC0355BE0)
# The last three words are the literal pool.  Two of them were the scratch
# and destination addresses, written down; they are zero here and filled in
# from the allocator, by INDEX rather than by matching the old value -- a
# value that also appears as an instruction would match twice.
W_SCR, W_DEST = 16, 17
# Asked for, not chosen.  0xC072FA00 and 0xC072FF00 were also two of the
# lossless probes' code limit and log, which is two tools agreeing by hand
# about the same bytes.  The routine is a hand-assembled word list and two of
# its words ARE these addresses -- the literal pool at the end -- so they are
# substituted rather than left behind.
def _at():
    import sys, pathlib as _p
    sys.path.insert(0, str(_p.Path(__file__).resolve().parents[2]
                           / 'fp_usb_shell'))
    import cave
    code = cave.claim('lens_probe.code', len(LENS_WORDS) * 4)
    scr = cave.claim('lens_probe.scr', 16)
    dest = cave.claim('lens_probe.dest', 0x100)
    if (LENS_WORDS[W_SCR], LENS_WORDS[W_DEST]) != (0, 0):
        raise SystemExit('LENS_WORDS[16] and [17] are the literal pool and '
                         'must be zero for the allocator to fill them')
    words = list(LENS_WORDS)
    words[W_SCR], words[W_DEST] = scr, dest
    return code, scr, dest, tuple(words)
class LensProbe:
    def __init__(self, sock='/tmp/fpshell.sock'):
        self.sh = F.Shell(sock, mock=False); self._inj=False
    def _inject(self):
        if self._inj: return
        CODE, SCR, DEST, words = _at()
        self._at = (CODE, SCR, DEST)
        for i,w in enumerate(words): self.sh._set_mem(CODE+4*i, w)
        self._inj = True
    def read(self, addr, n):
        self._inject()
        CODE, SCR, DEST = self._at
        self.sh._set_mem(SCR+0, addr & 0xFFFFFF)
        self.sh._set_mem(SCR+4, n & 0xFF if n<=0xFF else n)
        self.sh._call(CODE)
        ret = F.u32(self.sh, SCR+8)
        data = self.sh.read_mem(DEST, min(n,0xFF))
        return ret, data
if __name__=='__main__':
    lp=LensProbe()
    for addr in [0x000000, 0x000010, 0x000100]:
        ret,data = lp.read(addr, 16)
        print(f"lens[0x{addr:06X}] ret={ret} : {data.hex()}  '{bytes(c if 32<=c<127 else 46 for c in data).decode()}'")
