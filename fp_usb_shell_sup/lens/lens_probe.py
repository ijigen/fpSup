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
              0xE8BD4FF0,0xE12FFF1E,0xC072FF00,0xC072FA00,0xC0355BE0)
CODE, SCR, DEST = 0xC072F980, 0xC072FF00, 0xC072FA00
class LensProbe:
    def __init__(self, sock='/tmp/fpshell.sock'):
        self.sh = F.Shell(sock, mock=False); self._inj=False
    def _inject(self):
        if self._inj: return
        for i,w in enumerate(LENS_WORDS): self.sh._set_mem(CODE+4*i, w)
        self._inj = True
    def read(self, addr, n):
        self._inject()
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
