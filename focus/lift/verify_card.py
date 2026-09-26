"""Emulate an exact Focus Lift card; task scheduling and native I/O are mocked."""
from pathlib import Path
import re
import struct
import sys

from test_focus_lift import B, T, STACK, TONE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP


class Card(T.Camera):
    def __init__(self, loader, binary):
        self.allocations = 0
        self.tasks = []
        super().__init__(loader, binary)
        self.mu.mem_write(B.SEG1_BASE, B.SEG1.read_bytes())

    def _hook(self, mu, addr, size, data):
        if addr == self.entry:
            self.entry = None  # Run the actual chain, USB bootstrap and Focus Lift entry.
        if addr == T.F['H_ADDR']:
            result = T.HEAP + self.allocations * 0x100000
            self.allocations += 1
            return self._ret(result)
        if addr == 0xC0016A58:
            assert self.r(UC_ARM_REG_SP) % 8 == 0
            self.tasks.append(struct.unpack('<8I', mu.mem_read(self.r(UC_ARM_REG_R0), 32)))
            return self._ret(len(self.tasks))
        if addr == 0xC0016BC0:
            assert self.r(UC_ARM_REG_SP) % 8 == 0
            assert 1 <= self.r(UC_ARM_REG_R0) <= len(self.tasks)
            assert self.r(UC_ARM_REG_R1) == 0
            return self._ret(0)
        return super()._hook(mu, addr, size, data)


def verify(path):
    pairs = [(int(a, 16), int(w, 16)) for a, w in re.findall(
        r'^mem set (0x\w+) (0x\w+)', (path / 'AutoRun.txt').read_text(), re.M)]
    loader = {a: w for a, w in pairs if T.CAVE_LOW <= a < T.CAVE_LOW + 0x200}
    bootstrap = {a: w for a, w in pairs if 0xC072F700 <= a < 0xC0730000}
    c = Card(loader, (path / 'fpSup.BIN').read_bytes())
    c.now = 15_000_000
    c.mu.mem_write(T.AR_TABLE + 0x21C, struct.pack('<I', 0))
    for mode in ('ordinary loader', 'stored bootstrap', 'warm hook'):
        c.allocations = 0
        c.tasks.clear()
        c.registered.clear()
        c.heap_next = T.HEAP + 0x20000
        if mode == 'stored bootstrap':
            for a, w in bootstrap.items():
                c.mu.mem_write(a, struct.pack('<I', w))
            entry = 0xC072F700
        else:
            entry = T.CAVE_LOW + (4 if mode == 'warm hook' else 0)
        c.call(entry, r0=0xC0BABDD8, r1=1, sp=STACK)
        assert c.r(UC_ARM_REG_SP) == STACK
        assert c.ar_started is None
        assert c.word(0xC06C07D8) == 0xE3A02011
        assert c.word(TONE) != 0xE5901004
        assert len(c.tasks) == 2  # USB shell and Focus Auto
        assert c.tasks[1][3:5] == (28, 0x2000)
        assert T.HEAP + 0x300000 <= c.tasks[1][2] < T.HEAP + 0x307000
        assert len(c.registered) == 2
        assert c.word(T.STORE) != 0
        obj = c.registered[0][0]
        c.call(c.word(obj + 4), r0=obj, r1=4, sp=STACK)
        for a, word, _ in B.hook_sites(True):
            assert bytes(c.mu.mem_read(a, 4)) == word, hex(a)
        assert c.word(T.DRAW) == T.DRAW_STOCK
        print(mode + ': real payload installed, both tasks created, shutdown restored all Focus Lift sites')


if __name__ == '__main__':
    verify(Path(sys.argv[1]))
