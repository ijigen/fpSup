#!/usr/bin/env python3
"""Dial Fix (decoder v6) under unicorn, with the real v4 core and the real firmware image.

    python3 -B -m unittest fpSup/dialfix/test_dialfix.py     (from the repo root)

1. The decoder is Andy_hal9000's v6: the sup's words from dial_v6 on are the
   words reference/v6/AutoRun.txt writes at C02E1CE8..C02E1E90, and clang
   assembles reference/v6/dial2_fast.S to exactly those, with no relocation.
2. Loading: vtable +0x10 points at the Thumb poll and +0x14/+0x18 at ARM edge
   wrappers in the sup's block (cached alias); the object state and the edge
   register are as his card leaves them; power-off restores the slots; no
   detector -> RELEASED, nothing written.
3. Behaviour: his code placed where his card puts it (reached through the
   stock edge handlers C02E20D8/C02E20F0) and the sup's copy give the same
   object state and counts over the same inputs.
4. The wheel: one click per detent, clockwise (B closes first, A opens last)
   = +1, slow turns seen by the poll and fast spins between two polls.
"""
import pathlib, random, re, shutil, struct, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
V4 = HERE.parent / 'loader-v4'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(V4))

import build_dialfix as D
import test_v4 as T

OBJ, VT, SLOTS, CFG = 0xC3425A78, 0xC0B4E778, 0xC0B4E788, 0x301502E4
ADC = 0x301502C0                      # +0 levels (A low, B high), +0x30 comparator (A bit 0, B bit 16)
STOCK = (0xC02E1D08, 0xC02E20D8, 0xC02E20F0)
REF = HERE / 'reference' / 'v6' / 'AutoRun.txt'
SRC = HERE / 'reference' / 'v6' / 'dial2_fast.S'
ORIG_AT, ORIG_END = 0xC02E1CE8, 0xC02E1E94          # 107 words
IRQ_AT = ORIG_AT + 0x90                             # his ARM stub
HI, LO = 4095, 0                                    # open, closed


def fragment_code():
    """{addr: word} of his final decoder (the last write of C02E1CE8 on)."""
    ws = [(int(a, 16), int(v, 16)) for a, v in
          re.findall(r'mem set (0x[0-9A-F]+) (0x[0-9A-F]+)', REF.read_text())]
    start = max(i for i, (a, _) in enumerate(ws) if a == ORIG_AT)
    return {a: v for a, v in ws[start:] if ORIG_AT <= a < ORIG_END}


def elf_text(path):
    """(.text bytes, names of the relocation sections) of an ELF32 object."""
    d = path.read_bytes()
    shoff, = struct.unpack_from('<I', d, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', d, 0x2E)
    sh = [struct.unpack_from('<10I', d, shoff + i * shentsize) for i in range(shnum)]
    strtab = sh[shstrndx][4]
    names = {d[strtab + s[0]:d.index(b'\0', strtab + s[0])].decode(): s for s in sh}
    t = names['.text']
    return d[t[4]:t[4] + t[5]], [n for n in names if n.startswith('.rel')]


class Camera(T.Camera):
    """The v4 test camera plus the two peripheral pages the sup touches."""
    def __init__(self, files, dirs, stale=None, obj=True, cfg=0x30):
        super().__init__(files, dirs, stale)
        # one page: the ADC block.  Nothing else is mapped up there, so a
        # register address outside it faults here as it froze the camera
        # (0x321522E4 until 2026-11-10: the test had mapped that page too)
        assert CFG & ~0xFFF == ADC & ~0xFFF
        self.mu.mem_map(ADC & ~0xFFF, 0x1000)
        self.mu.mem_write(CFG, struct.pack('<I', cfg))
        # obj=False: something else at the address (another firmware build)
        self.mu.mem_write(OBJ, struct.pack('<7I', 0, VT if obj else VT + 0x40, 9, 9, 9, 9, 9))


def boot(**kw):
    files, dirs = T.card((D.FILE, D.dialfix_sup()))
    cam = Camera(files, dirs, **kw)
    cam.boot()
    return cam


def words(cam, a, n):
    return list(struct.unpack(f'<{n}I', cam.mu.mem_read(a, 4 * n)))


@unittest.skipIf(T.Uc is None or not T.T3.IMAGE.exists(), 'needs unicorn and the image')
class DialFixTests(unittest.TestCase):
    def test_code_is_his_v6(self):
        ref = fragment_code()
        self.assertEqual(len(ref), (ORIG_END - ORIG_AT) // 4)
        blob = D.dialfix_sup()
        cam = boot()
        poll = words(cam, SLOTS, 1)[0]
        off = (poll & ~1) - T.blocks(cam)[D.FILE]
        body = blob[off:off + len(ref) * 4]
        self.assertEqual(list(struct.unpack(f'<{len(ref)}I', body)), [ref[a] for a in sorted(ref)])

    @unittest.skipIf(shutil.which('clang') is None, 'needs clang')
    def test_the_register_is_the_one_his_installer_writes(self):
        """His card sets the edge bits with eight ARM words run once at
        C02E1E78 (AutoRun.txt, before the decoder overwrites them): the
        address is their movw / movt, not a constant copied by hand."""
        w = {}
        for line in (HERE / 'reference/v6/AutoRun.txt').read_text().splitlines():
            p = line.split()
            if p[:2] == ['mem', 'set'] and int(p[2], 16) in (0xC02E1E78, 0xC02E1E7C):
                w.setdefault(int(p[2], 16), int(p[3], 16))          # the first write: the installer
        movw, movt = w[0xC02E1E78], w[0xC02E1E7C]
        self.assertEqual((movw >> 20, movt >> 20, movw >> 12 & 15, movt >> 12 & 15), (0xE30, 0xE34, 2, 2))
        imm = lambda x: (x >> 4 & 0xF000) | (x & 0xFFF)
        self.assertEqual(imm(movt) << 16 | imm(movw), CFG)
        self.assertIn(f'0x{CFG:08X}u', (HERE / 'dialfix.c').read_text())

    def test_his_source_assembles_to_his_card(self):
        with tempfile.TemporaryDirectory() as t:
            o = pathlib.Path(t) / 'd.o'
            subprocess.run(['clang', '--target=armv7a-none-eabi', '-mcpu=cortex-a9', '-c', str(SRC), '-o', str(o)],
                           check=True)
            text, rel = elf_text(o)
        self.assertEqual(rel, [])                                   # position independent
        ref = fragment_code()
        self.assertEqual(list(struct.unpack(f'<{len(text) // 4}I', text)), [ref[a] for a in sorted(ref)])

    def test_load_patches_slots_state_and_register(self):
        cam = boot(cfg=0x30)
        log = cam.loadlog()
        self.assertIn(T.CODES['LOADED'], [c for c, *_ in log], log)
        block = T.blocks(cam)[D.FILE]
        self.assertGreaterEqual(block, 0xC0000000)              # cached alias
        poll, ea, eb = words(cam, SLOTS, 3)
        self.assertTrue(poll & 1, hex(poll))                    # Thumb poll
        self.assertFalse(ea & 1 or eb & 1)                      # ARM edge wrappers
        for p in (poll, ea, eb):
            self.assertTrue(block < p < block + 0x400, hex(p))
        self.assertEqual((ea - block) - ((poll & ~1) - block), 4 * 107)   # wrappers right after his code
        self.assertEqual(words(cam, OBJ + 8, 5), [3, 0, 0, 4, 0])
        self.assertEqual(words(cam, CFG, 1)[0], 0x3F)
        self.assertEqual([(a, n) for a, n, _ in cam.journal()], [(SLOTS, 12)])
        cam.power_off()
        self.assertEqual(words(cam, SLOTS, 3), list(STOCK))

    def test_no_detector_releases_and_writes_nothing(self):
        cam = boot(obj=False, cfg=0x30)
        self.assertIn(T.CODES['RELEASED'], [c for c, *_ in cam.loadlog()])
        self.assertEqual(words(cam, SLOTS, 3), list(STOCK))
        self.assertEqual(words(cam, CFG, 1)[0], 0x30)
        self.assertEqual(words(cam, OBJ + 8, 5), [9] * 5)

    def run_seq(self, cam, fns, seq):
        """seq of (kind, adc, comparator); returns [(obj state, count or None)]."""
        poll, ea, eb = fns
        out = []
        for kind, adc, dig in seq:
            cam.mu.mem_write(ADC, struct.pack('<I', adc))
            cam.mu.mem_write(ADC + 0x30, struct.pack('<I', dig))
            if kind == 'poll':
                cam.call(poll & ~1, r0=OBJ, r1=T.T3.STACK - 0x2000, thumb=bool(poll & 1))
                n = struct.unpack('<i', cam.mu.mem_read(T.T3.STACK - 0x2000, 4))[0]
            else:
                cam.call(ea if kind == 'a' else eb, r0=OBJ)
                n = None
            out.append((tuple(words(cam, OBJ + 8, 5)), n))
        return out

    def mine(self):
        cam = boot()
        return cam, words(cam, SLOTS, 3)

    def theirs(self):
        """His code where his card writes it, reached the stock way."""
        cam = boot()
        for a, v in fragment_code().items():
            cam.mu.mem_write(a, struct.pack('<I', v))
        cam.mu.mem_write(OBJ + 8, struct.pack('<5I', 3, 0, 0, 4, 0))
        return cam, (ORIG_AT | 1, STOCK[1], STOCK[2])

    def test_stock_edge_handlers_reach_his_stub(self):
        """dial_edge_a/b stand in for C02E20D8/C02E20F0: those must be `r1 = ch; bl C02E1D78`."""
        cam = boot()
        def bl_target(at):
            w = cam.w(at)
            self.assertEqual(w >> 24, 0xEB, hex(w))
            return at + 8 + (((w & 0xFFFFFF) ^ 0x800000) - 0x800000) * 4
        for at, ch in ((STOCK[1], 0), (STOCK[2], 1)):
            ws = words(cam, at, 6)
            self.assertIn(0xE3A01000 | ch, ws, [hex(w) for w in ws])     # mov r1, #ch
            bl = next(at + 4 * i for i, w in enumerate(ws) if w >> 24 == 0xEB)
            self.assertEqual(bl_target(bl), IRQ_AT)

    def test_same_behaviour_as_his_card(self):
        rnd = random.Random(20261107)
        levels = [0, 600, 1199, 1200, 2000, 2896, 2897, 4095]
        seq = [(rnd.choice(['poll', 'poll', 'a', 'b']),
                rnd.choice(levels) | rnd.choice(levels) << 16,
                rnd.getrandbits(1) | rnd.getrandbits(1) << 16) for _ in range(600)]
        m, mf = self.mine()
        t, tf = self.theirs()
        self.assertEqual(self.run_seq(m, mf, seq), self.run_seq(t, tf, seq))

    # one detent: rest (both open) -> ... -> rest.  (A, B), 1 = open
    CW = [(1, 0), (0, 0), (0, 1), (1, 1)]                # B closes first, A opens last
    CCW = [(0, 1), (0, 0), (1, 0), (1, 1)]

    @staticmethod
    def edges(states, prev=(1, 1)):
        """The edge IRQ for each change, with the ADC and comparator at the new state."""
        out = []
        for s in states:
            ch = 'a' if s[0] != prev[0] else 'b'
            adc = (HI if s[0] else LO) | (HI if s[1] else LO) << 16
            out.append((ch, adc, s[0] | s[1] << 16))
            prev = s
        return out

    def turn(self, fns_of, states, n, how):
        cam, fns = fns_of()
        rest = ('poll', HI | HI << 16, 1 | 1 << 16)
        seq = [rest]
        for _ in range(n):
            e = self.edges(states)
            if how == 'poll':                              # slow: the poll sees every position
                seq += [('poll', a, d) for _, a, d in e]
            elif how == 'mixed':                           # irqs, with a poll while away
                seq += e[:2] + [('poll', e[1][1], e[1][2])] + e[2:] + [rest]
            else:                                          # fast: all between two polls
                seq += e
        seq.append(rest)
        return sum(c for _, c in self.run_seq(cam, fns, seq) if c)

    def test_one_click_per_detent_clockwise_plus(self):
        for fns_of in (self.mine, self.theirs):
            for how in ('poll', 'mixed', 'fast'):
                with self.subTest(fns_of.__name__, how=how):
                    self.assertEqual(self.turn(fns_of, self.CW, 3, how), 3)
                    self.assertEqual(self.turn(fns_of, self.CCW, 3, how), -3)

    def test_spring_back_is_no_click(self):
        """Away and back the same way without both closing: nothing."""
        for fns_of in (self.mine, self.theirs):
            cam, fns = fns_of()
            rest = ('poll', HI | HI << 16, 1 | 1 << 16)
            seq = [rest] + self.edges([(1, 0), (1, 1)]) + [rest]
            self.assertEqual(sum(c for _, c in self.run_seq(cam, fns, seq) if c), 0)


if __name__ == '__main__':
    unittest.main()
