#!/usr/bin/env python3
"""h2_packed.S (SensorLab CPU x2) on the real assembled ARM bytes under unicorn, against an independent reference.

    python3 -B test_h2_packed.py            # the suite
    python3 -B test_h2_packed.py --mutate   # each mutant must fail

Covers: packed 12 / 14 MSB-first round trips of the reference itself, every edge value pair, random streams, in place
(dst == src) and separate buffers, guards (exact write extent; h2_p14's documented +4 read / +1 write), invalid sizes,
AAPCS preservation (r4-r11, sp, d8-d15), and the instruction count per input pixel.
"""
import itertools
import pathlib
import random
import struct
import subprocess
import sys
import tempfile
import unittest

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn import arm_const as A

HERE = pathlib.Path(__file__).resolve().parent
SRC_S = HERE / 'h2_packed.S'
CODE, BUF, OUT, STACK, DONE = 0x10000000, 0x20000000, 0x30000000, 0x40100000, 0x10F00000
REGION = 0x00100000
RNG = random.Random(0x5C2)


# ---------------------------------------------------------------------------------------------- reference (Python)
def unpack(data, bits):
    v = int.from_bytes(data, 'big')
    n = len(data) * 8 // bits
    return [(v >> (bits * (n - 1 - i))) & ((1 << bits) - 1) for i in range(n)]


def pack(px, bits):
    v = 0
    for p in px:
        v = (v << bits) | p
    return v.to_bytes(len(px) * bits // 8, 'big')


def h2_ref(px):
    return [((px[i] + px[i + 2] + 1) >> 1) for g in range(0, len(px), 4) for i in (g, g + 1)]


# ---------------------------------------------------------------------------------------------- build (clang, ELF)
def build(src_text=None):
    text = src_text if src_text is not None else SRC_S.read_text()
    with tempfile.TemporaryDirectory() as t:
        s, o = pathlib.Path(t) / 'h2.S', pathlib.Path(t) / 'h2.o'
        s.write_text(text)
        r = subprocess.run(['clang', '-target', 'armv7-none-eabi', '-mfpu=neon', '-mfloat-abi=softfp', '-c', str(s),
                            '-o', str(o)], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr)
        elf = o.read_bytes()
    shoff, = struct.unpack_from('<I', elf, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', elf, 0x2E)
    sh = [struct.unpack_from('<IIIIIIIIII', elf, shoff + i * shentsize) for i in range(shnum)]
    names = sh[shstrndx]
    nm = lambda off, tab: elf[tab[4] + off:elf.index(b'\0', tab[4] + off)].decode()
    by = {nm(x[0], names): (i, x) for i, x in enumerate(sh)}
    ti, tx = by['.text']
    body = elf[tx[4]:tx[4] + tx[5]]
    _, st = by['.symtab']
    _, strt = by['.strtab']
    syms = {}
    for off in range(st[4], st[4] + st[5], 16):
        name, value, _sz, _info, _oth, shndx = struct.unpack_from('<IIIBBH', elf, off)
        if shndx == ti and name:
            syms[nm(name, strt)] = value
    if by.get('.rel.text'):
        raise RuntimeError('relocations in .text')
    return body, syms


# ---------------------------------------------------------------------------------------------- the rig
class Rig:
    def __init__(self, body, syms):
        self.mu = m = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        m.ctl_set_cpu_model(A.UC_CPU_ARM_CORTEX_A9)
        for base in (CODE, BUF, OUT, STACK - REGION, DONE):
            m.mem_map(base, REGION)
        m.mem_write(CODE, body)
        m.reg_write(A.UC_ARM_REG_C1_C0_2, 0x00F00000)
        m.reg_write(A.UC_ARM_REG_FPEXC, 0x40000000)
        self.syms, self.end = syms, CODE + len(body)
        self.n = 0
        self.rd, self.wr = [], []
        m.hook_add(UC_HOOK_CODE, self._code)
        m.hook_add(UC_HOOK_MEM_READ, lambda mu, a, addr, size, v, d: self.rd.append((addr, size)))
        m.hook_add(UC_HOOK_MEM_WRITE, lambda mu, a, addr, size, v, d: self.wr.append((addr, size)))

    def _code(self, mu, addr, size, _):
        if addr != DONE:
            assert CODE <= addr < self.end, hex(addr)
            self.n += 1

    def call(self, fn, dst, src, nbytes, check_regs=True):
        m = self.mu
        canary = {r: 0x1000 * (i + 1) + 0xA5 for i, r in enumerate(range(A.UC_ARM_REG_R4, A.UC_ARM_REG_R11 + 1))}
        for r, v in canary.items():
            m.reg_write(r, v)
        dvals = {i: 0x0102030405060708 * (i + 1) & 0xFFFFFFFFFFFFFFFF for i in range(8, 16)}
        for i, v in dvals.items():
            m.reg_write(getattr(A, f'UC_ARM_REG_D{i}'), v)
        m.reg_write(A.UC_ARM_REG_SP, STACK - 0x100)
        m.reg_write(A.UC_ARM_REG_LR, DONE)
        m.reg_write(A.UC_ARM_REG_R0, dst)
        m.reg_write(A.UC_ARM_REG_R1, src)
        m.reg_write(A.UC_ARM_REG_R2, nbytes)
        self.n, self.rd, self.wr = 0, [], []
        m.emu_start(CODE + self.syms[fn], DONE, count=50_000_000)
        rc = m.reg_read(A.UC_ARM_REG_R0)
        if check_regs:
            for r, v in canary.items():
                assert m.reg_read(r) == v, ('callee-saved r', r)
            for i, v in dvals.items():
                assert m.reg_read(getattr(A, f'UC_ARM_REG_D{i}')) == v, ('callee-saved d', i)
            assert m.reg_read(A.UC_ARM_REG_SP) == STACK - 0x100
        return rc if rc < 0x80000000 else rc - (1 << 32)


BODY, SYMS = build()
RIG = Rig(BODY, SYMS)
STEP = {12: 48, 14: 28}
FN = {12: 'h2_p12', 14: 'h2_p14'}


def run(bits, data, inplace=True):
    """data = packed input (len a multiple of the step); returns the output bytes and the rig extents"""
    m = RIG.mu
    slack = 64
    m.mem_write(BUF - 0, b'\xEE' * 0)
    m.mem_write(BUF, bytes(data) + b'\xA5' * slack)
    if inplace:
        dst = BUF
    else:
        dst = OUT
        m.mem_write(OUT, b'\xCC' * (len(data) // 2 + slack))
    rc = RIG.call(FN[bits], dst, BUF, len(data))
    out = bytes(m.mem_read(dst, len(data) // 2))
    return rc, out, dst


class Reference(unittest.TestCase):
    def test_pack_round_trip(self):
        for bits in (12, 14):
            px = [RNG.randrange(1 << bits) for _ in range(64)]
            self.assertEqual(unpack(pack(px, bits), bits), px)


class Kernel(unittest.TestCase):
    def check(self, bits, px, inplace=True):
        data = pack(px, bits)
        rc, out, dst = run(bits, data, inplace)
        self.assertEqual(rc, 0)
        want = pack(h2_ref(px), bits)
        self.assertEqual(out, want, f'{bits}-bit inplace={inplace} n={len(px)}')
        # writes: only [dst, dst + len/2) (+1 for p14 past the end)
        hi = dst + len(data) // 2 + (1 if bits == 14 else 0)
        for a, s in RIG.wr:
            if a >= STACK - REGION:
                continue
            self.assertTrue(dst <= a and a + s <= hi, (hex(a), s, hex(dst), hex(hi)))
        # reads: inside the input (+4 past the end for p14), or the kernel's own code / table
        rhi = BUF + len(data) + (4 if bits == 14 else 0)
        for a, s in RIG.rd:
            if CODE <= a < RIG.end or a >= STACK - REGION:
                continue
            self.assertTrue(BUF <= a and a + s <= rhi, (hex(a), s))
        return RIG.n

    def test_edges_every_pair(self):
        for bits in (12, 14):
            top = (1 << bits) - 1
            vals = [0, 1, 2, top - 1, top, 1 << (bits - 1), (1 << (bits - 1)) - 1, 0x555 & top, 0xAAA & top]
            pairs = list(itertools.product(vals, repeat=2))
            px = []
            for a, b in pairs:                        # A pair (a, b) and B pair (b, a): both lanes, both orders
                px += [a, b, b, a]
            step_px = STEP[bits] * 8 // bits
            while len(px) % step_px:
                px += [top, 0, 0, top]
            self.check(bits, px)

    def test_random_streams_in_place_and_separate(self):
        for bits in (12, 14):
            step_px = STEP[bits] * 8 // bits
            for k in (1, 2, 3, 7, 33):
                px = [RNG.randrange(1 << bits) for _ in range(step_px * k)]
                self.check(bits, px, inplace=True)
                self.check(bits, px, inplace=False)

    def test_a_raster_with_rows(self):
        """a 6048-wide row x 3 rows: the flat stream equals row-by-row processing (pairs never straddle rows)"""
        for bits in (12, 14):
            w, h = 6048, 3
            px = [RNG.randrange(1 << bits) for _ in range(w * h)]
            data = pack(px, bits)
            rc, out, _ = run(bits, data)
            rows = b''.join(pack(h2_ref(px[r * w:(r + 1) * w]), bits) for r in range(h))
            self.assertEqual((rc, out), (0, rows))

    def test_zero_and_bad_sizes(self):
        for bits in (12, 14):
            rc, _out, _ = run(bits, b'')
            self.assertEqual(rc, 0)
            self.assertEqual([w for w in RIG.wr if w[0] < STACK - REGION], [])
            RIG.mu.mem_write(BUF, b'\0' * 64)
            self.assertEqual(RIG.call(FN[bits], BUF, BUF, STEP[bits] - 1), -1)

    def test_instructions_per_pixel(self):
        for bits, limit in ((12, 1.1), (14, 4.5)):
            step_px = STEP[bits] * 8 // bits
            px = [RNG.randrange(1 << bits) for _ in range(step_px * 40)]
            n = self.check(bits, px)
            ipp = n / len(px)
            print(f'  {bits}-bit: {ipp:.3f} instructions / input pixel ({n} for {len(px)} px)')
            self.assertLess(ipp, limit)


MUTANTS = [
    ('p12 truncating mean', 'vrhadd.u16 q3, q3, q4', 'vhadd.u16 q3, q3, q4'),
    ('p12 B truncating', 'vrhadd.u16 q5, q5, q6', 'vhadd.u16 q5, q5, q6'),
    ('p12 nibble mask lost', '    vshl.u8    d14, d2, #4\n    vshr.u8    d14, d14, #4\n', '    vmov       d14, d2\n'),
    ('p12 no pair split', '    vuzp.8  d2, d3\n', ''),
    ('p14 truncating', 'vrhadd.u32 d4, d4, d5', 'vhadd.u32 d4, d4, d5'),
    ('p14 wrong shift', '.word -18, -12, -14, -16', '.word -18, -12, -14, -17'),
    ('p14 mask 13 bit', 'vorr.i32 q7, #0xFF ', 'vorr.i32 q7, #0x7F '),
    ('p14 pack shift', 'vshl.u64 d9, d9, #28', 'vshl.u64 d9, d9, #27'),
    ('p14 no d8 save', '    push    {r4, lr}\n    vpush   {d8-d15}\n', '    push    {r4, lr}\n'),
]


def mutate():
    src = SRC_S.read_text()
    survived = []
    for name, a, b in MUTANTS:
        assert src.count(a) >= 1, name
        global BODY, SYMS, RIG
        try:
            BODY, SYMS = build(src.replace(a, b, 1))
            RIG = Rig(BODY, SYMS)
        except Exception as e:
            print('caught (does not build)', name, str(e)[:80])
            continue
        r = unittest.TextTestRunner(stream=open('/dev/null', 'w')).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(Kernel))
        ok = r.wasSuccessful()
        print(('SURVIVED ' if ok else 'caught   ') + name)
        if ok:
            survived.append(name)
    print('survived:', survived)
    return not survived


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        sys.exit(0 if mutate() else 1)
    unittest.main()
