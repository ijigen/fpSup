#!/usr/bin/env python3
"""The loader hook, run under emulation against the real firmware image.

    python3 -B -m unittest -v test_loader_hook

Assembles a --loader --loader-hook card, puts its loader where the AutoRun
would, maps out/MAIN_c0000000.bin, and runs the real loader and the real stage2
with the firmware routines they call (file API, allocator, power-off manager,
cache) replaced by Python.  The payload's own entry is stubbed: this is about
what the loader and stage2 do, not the worker.

What it proves, per LOADER_V2.md:
  - entered through the hook (+4), a good file loads and the AutoRun is NOT
    started; a missing file starts it with the firmware's own r0/r1/lr
  - every firmware word stage2 overwrites outside the cave is journaled with
    its stock value, and nothing in the cave is
  - the power-off routine puts every one of them back, and leaves 0xC03DA420
    pointing at the loader
  - a loader whose +4 is not this build's hook entry is never armed
"""
import pathlib
import re
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
IMAGE = HERE.parents[1] / 'out' / 'MAIN_c0000000.bin'

try:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                   UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR,
                                   UC_ARM_REG_PC)
except ImportError:                                      # pragma: no cover
    Uc = None

CAVE_LOW = 0xC072DE64
SITE, SITE_ORIG, AR_RET = 0xC03DA420, 0xEB0000CC, 0xC03DA424
AR_START = 0xC03DA758
MARK = 0xC072E040
CAVE_LO, CAVE_HI = 0xC072D000, 0xC0735000
HEAP, HEAP_SIZE = 0x45000000, 0x00400000
STACK = 0x46000000
DONE = 0x47000000                  # a return address nothing else uses

F = dict(F_MGR=0xC0444658, F_VOL=0xC0444698, F_CTOR=0xC0365E90,
         F_OPEN=0xC0365FB0, F_READ=0xC0366060, F_CLOSE=0xC0366020,
         F_DTOR=0xC0365ED0, DCACHE=0xC000E91C, ICACHE=0xC000EABC,
         TICK=0xC002B6E0, H_GET=0xC001D740, H_ADDR=0xC001D7F0,
         H_FREE=0xC001D7A0, MEM_HEAP=0xC001CF78, MEM_GET=0xC001D038,
         POFF_MGR=0xC0023A98, POFF_ADD=0xC0024118, AR_START=AR_START,
         D_TEXT=0xC03E4620, D_OSD=0xC03E3D00, D_SLEEP=0xC03705D8,
         D_FILE=0xC03E4270, CYC_DRAW=0xC05278F8, UI_CLEAR=0xC0527DD8,
         UI_FORCE=0xC0527E68)


DRAW, DRAW_STOCK, DRAW_PAUSED = 0xC0528700, 0xE92D4BF0, 0xE12FFF1E


def build(extra=(), hook=True):
    out = pathlib.Path(tempfile.mkdtemp())
    subprocess.run([sys.executable, '-B', str(HERE / 'build_autorun.py'),
                    '--loader', *(['--loader-hook'] if hook else []),
                    '--loader-hook-mark', hex(MARK),
                    '--out', str(out / 'AutoRun.txt'), *extra],
                   check=True, capture_output=True)
    text = (out / 'AutoRun.txt').read_text()
    sets = [(int(a, 16), int(v, 16)) for a, v in
            re.findall(r'^mem set (0x[0-9A-Fa-f]+) (0x[0-9A-Fa-f]+)', text, re.M)]
    loader = {a: v for a, v in sets if CAVE_LOW <= a < CAVE_LOW + 0x200}
    return loader, (out / 'fpSup.BIN').read_bytes()


class Camera:
    def __init__(self, loader, binfile, have_file=True):
        self.bin, self.have_file = binfile, have_file
        self.stock = IMAGE.read_bytes()
        mu = self.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        mu.mem_map(0xC0000000, 0x03000000)
        mu.mem_write(0xC0000000, self.stock[:0x03000000])
        mu.mem_map(0xC3000000, 0x01000000)                 # BSS: zero, as at boot
        mu.mem_map(HEAP, HEAP_SIZE)
        mu.mem_map(STACK - 0x10000, 0x10000)
        mu.mem_map(DONE, 0x1000)
        for a, v in loader.items():
            mu.mem_write(a, struct.pack('<I', v))
        self.heap_next = HEAP + 0x20000                    # staging buffer first
        self.calls, self.registered, self.ar_started = [], [], None
        self.by_addr = {v: k for k, v in F.items()}
        mu.hook_add(UC_HOOK_CODE, self._hook)
        self.entry = None
        self.draws = []
        self.now, self.slept = 1_400_000, 0

    def cstr(self, a):
        return bytes(self.mu.mem_read(a, 64)).split(b'\0')[0].decode()

    def r(self, reg):
        return self.mu.reg_read(reg)

    def word(self, a):
        return struct.unpack('<I', self.mu.mem_read(a, 4))[0]

    def _ret(self, value=None):
        if value is not None:
            self.mu.reg_write(UC_ARM_REG_R0, value & 0xFFFFFFFF)
        self.mu.reg_write(UC_ARM_REG_PC, self.r(UC_ARM_REG_LR))

    def _hook(self, mu, addr, size, _):
        if addr == DONE:
            mu.emu_stop()
            return
        if self.entry is not None and addr == self.entry:
            self.calls.append('ENTRY')
            return self._ret(0)
        name = self.by_addr.get(addr)
        if name is None:
            return
        self.calls.append(name)
        r0, r1, r2 = (self.r(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
        if name == 'AR_START':
            self.ar_started = (r0, r1, self.r(UC_ARM_REG_LR))
            mu.emu_stop()
            return
        if name == 'D_FILE':
            argv = [self.cstr(struct.unpack('<I', mu.mem_read(r2 + 4 * i, 4))[0])
                    for i in range(r1)]
            self.draws.append((name, tuple(argv), self.word(DRAW)))
            return self._ret(0)
        if name == 'CYC_DRAW':
            return self._ret(0xC3000200)
        if name == 'UI_FORCE':
            self.draws.append((name, tuple(struct.unpack('<3I', mu.mem_read(r1, 12))),
                               self.word(DRAW)))
            return self._ret(0)
        if name in ('D_TEXT', 'D_OSD'):
            argv = [self.cstr(struct.unpack('<I', mu.mem_read(r2 + 4 * i, 4))[0])
                    for i in range(r1)]
            quiet = struct.unpack('<I', mu.mem_read(r0, 4))[0]
            self.draws.append((name, tuple(argv), quiet))
            return self._ret(0)
        if name == 'F_OPEN':
            return self._ret(1 if self.have_file else 0)
        if name == 'F_READ':
            mu.mem_write(r1, self.bin[:r2])
            if self.bin[:4] == b'VBIN':          # stage2 runs from here; entry
                self.entry = r1 + struct.unpack_from('<I', self.bin, 8)[0]
            return self._ret(len(self.bin))
        if name == 'F_VOL':
            return self._ret(1)
        if name == 'H_ADDR':
            return self._ret(HEAP)
        if name == 'MEM_HEAP':
            return self._ret(0x1234)
        if name == 'MEM_GET':
            got, self.heap_next = self.heap_next, (self.heap_next + r1 + 15) & ~15
            self.assertion_size = r1
            return self._ret(got)
        if name == 'POFF_MGR':
            return self._ret(0xC3000100)
        if name == 'POFF_ADD':
            self.registered.append((r1, r2))
            return self._ret(1)
        if name == 'TICK':
            return self._ret(self.now)
        if name == 'D_SLEEP':
            self.slept += r0
            self.now += r0 * 1000
            return self._ret(0)
        return self._ret(0)

    def call(self, pc, r0=0, r1=0, lr=DONE, sp=STACK - 0x1004):
        mu = self.mu
        mu.reg_write(UC_ARM_REG_SP, sp)                    # 4 off, like the caller
        mu.reg_write(UC_ARM_REG_R0, r0)
        mu.reg_write(UC_ARM_REG_R1, r1)
        mu.reg_write(UC_ARM_REG_LR, lr)
        mu.emu_start(pc, DONE if lr == DONE else lr, count=5_000_000)
        return self.r(UC_ARM_REG_R0), self.r(UC_ARM_REG_SP)

    def sections(self):
        n = struct.unpack_from('<I', self.bin, 4)[0]
        return [struct.unpack_from('<II', self.bin, 16 + 8 * i) for i in range(n)]


@unittest.skipIf(Uc is None or not IMAGE.exists(), 'needs unicorn and the image')
class LoaderHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader, cls.bin = build()

    def boot(self, **kw):
        cam = Camera(self.loader, self.bin, **kw)
        cam.mu.mem_write(SITE, struct.pack('<I', 0xEB000000 | ((((CAVE_LOW + 4)
                         - SITE - 8) >> 2) & 0xFFFFFF)))    # armed by a past boot
        r0, sp = cam.call(CAVE_LOW + 4, r0=0xC0BABDD8, r1=1, lr=AR_RET,
                          sp=STACK - 0x1004)
        return cam, r0, sp

    def fw_sections(self, cam):
        return [(d, n) for d, n in cam.sections()
                if d >= 0x40000000 and not CAVE_LO <= d < CAVE_HI]

    def test_hook_loads_and_skips_the_autorun(self):
        cam, r0, sp = self.boot()
        self.assertIsNone(cam.ar_started)
        self.assertEqual(r0, 0)
        self.assertEqual(sp, STACK - 0x1004)
        self.assertIn('ENTRY', cam.calls)
        self.assertEqual([f for _, f in cam.registered], [0, 1])  # both lists
        self.assertEqual(len({o for o, _ in cam.registered}), 1)
        self.assertEqual(cam.word(SITE), 0xEB000000 | ((((CAVE_LOW + 4) - SITE - 8)
                                                        >> 2) & 0xFFFFFF))

    def test_journal_holds_stock_words_and_only_outside_the_cave(self):
        cam, _, _ = self.boot()
        x = cam.word(MARK + 8)
        self.assertEqual(cam.word(x), x - 8)
        self.assertEqual(cam.word(x + 4), x + 12)
        j, got = cam.word(x + 8), []
        while cam.word(j):
            a, n = cam.word(j), cam.word(j + 4)
            got.append((a, n, bytes(cam.mu.mem_read(j + 8, n))))
            j += 8 + n
        want = self.fw_sections(cam)
        self.assertTrue(want, 'the shell card patches firmware words')
        self.assertEqual([(a, n) for a, n, _ in got],
                         [(d, (n + 3) & ~3) for d, n in want])
        for a, n, orig in got:
            self.assertEqual(orig, cam.stock[a - 0xC0000000:a - 0xC0000000 + n], hex(a))
        self.assertLessEqual(j + 4 - x, cam.assertion_size)   # fits the block

    def test_power_off_puts_every_word_back_but_the_hook(self):
        cam, _, _ = self.boot()
        want = self.fw_sections(cam)
        self.assertTrue(any(bytes(cam.mu.mem_read(d, n)) !=
                            cam.stock[d - 0xC0000000:d - 0xC0000000 + n]
                            for d, n in want), 'nothing was patched to begin with')
        x = cam.word(MARK + 8)
        for _ in range(2):                                   # both lists call it
            cam.call(cam.word(x + 4), r0=x, r1=4)
        for d, n in want:
            self.assertEqual(bytes(cam.mu.mem_read(d, n)),
                             cam.stock[d - 0xC0000000:d - 0xC0000000 + n], hex(d))
        self.assertEqual(cam.word(MARK), 2)
        self.assertNotEqual(cam.word(SITE), SITE_ORIG)       # the hook stays

    def test_banner_is_drawn_after_the_load(self):
        cam, _, _ = self.boot()
        want = [('D_TEXT', ('fpSup!',)), ('D_OSD', ('1',))] * 3   # no clear
        self.assertEqual([(n, a) for n, a, _ in cam.draws], want)
        self.assertGreater(cam.calls.index('D_OSD'), cam.calls.index('ENTRY'))
        # ctx[0] is the handler's printf: it must be callable code, not zero
        self.assertTrue(all(q for _, _, q in cam.draws))
        self.assertGreaterEqual(cam.word(MARK + 12), 3_000_000)   # not before 3 s
        self.assertGreater(cam.slept, 0)

    def test_banner_does_not_wait_when_late_already(self):
        cam = Camera(self.loader, self.bin)
        cam.now = 15_000_000                                  # the AutoRun path
        cam.call(CAVE_LOW, r0=0, r1=0)
        self.assertEqual(cam.slept, 0)
        self.assertEqual(len(cam.draws), 6)

    def test_no_file_starts_the_autorun_as_the_firmware_would(self):
        cam, _, _ = self.boot(have_file=False)
        self.assertEqual(cam.ar_started, (0xC0BABDD8, 1, AR_RET))
        self.assertNotIn('ENTRY', cam.calls)
        self.assertEqual(cam.draws, [])

    def test_foreign_loader_is_not_armed(self):
        loader = dict(self.loader)
        loader[CAVE_LOW + 4] = 0xEA000010                    # someone else's +4
        cam = Camera(loader, self.bin)
        cam.call(CAVE_LOW, r0=0, r1=0)                        # the echo entry
        self.assertIn('ENTRY', cam.calls)
        self.assertEqual(cam.word(SITE), SITE_ORIG)

    def test_echo_entry_arms_the_hook(self):
        cam = Camera(self.loader, self.bin)
        self.assertEqual(cam.word(SITE), SITE_ORIG)
        r0, _ = cam.call(CAVE_LOW, r0=0, r1=0)
        self.assertEqual(r0, 1)
        self.assertNotEqual(cam.word(SITE), SITE_ORIG)


@unittest.skipIf(Uc is None or not IMAGE.exists(), 'needs unicorn and the image')
class FourBoxOnTheHookTests(unittest.TestCase):
    """--four-box-bar with --loader-hook: the warm path paints frame 0 and runs
    splash_finish itself; the AutoRun path is left exactly as it was."""
    @classmethod
    def setUpClass(cls):
        cls.loader, cls.bin = build(['--four-box-bar'])

    def test_warm_path_pauses_paints_frame0_then_finishes_and_restores(self):
        cam = Camera(self.loader, self.bin)
        cam.mu.mem_write(SITE, struct.pack('<I', 0xEB000000 | ((((CAVE_LOW + 4)
                         - SITE - 8) >> 2) & 0xFFFFFF)))
        self.assertEqual(cam.word(DRAW), DRAW_STOCK)
        r0, _ = cam.call(CAVE_LOW + 4, r0=0xC0BABDD8, r1=1, lr=AR_RET, sp=STACK - 0x1004)
        self.assertIsNone(cam.ar_started)
        files = [(a[0], a[3], a[4], d) for n, a, d in cam.draws if n == 'D_FILE']
        self.assertEqual(files[:3], [('\\FPSUPUI\\0.BIN', '1024', '56', DRAW_PAUSED)] * 3)
        self.assertEqual([f[0] for f in files[3:]], ['\\FPSUPUI\\4.BIN'] * 3)
        self.assertTrue(all(f[3] == DRAW_PAUSED for f in files))
        self.assertGreaterEqual(cam.slept, 1600)            # waited to ~3 s
        self.assertEqual(cam.draws[-1][0], 'UI_FORCE')
        self.assertEqual(cam.draws[-1][1], (0x101, 0xFFFFFFFF, 0))
        self.assertEqual(cam.word(DRAW), DRAW_STOCK)        # redraw back on
        # and the pause was journaled, so a power-off mid-hold restores it
        x = cam.word(MARK + 8)
        j, addrs = cam.word(x + 8), []
        while cam.word(j):
            addrs.append(cam.word(j))
            j += 8 + cam.word(j + 4)
        self.assertIn(DRAW, addrs)
        self.assertLessEqual(j + 4 - x, cam.assertion_size)

    def test_autorun_path_is_unchanged(self):
        cam = Camera(self.loader, self.bin)
        cam.now = 15_000_000
        cam.mu.mem_write(DRAW, struct.pack('<I', DRAW_PAUSED))   # the AutoRun did
        cam.call(CAVE_LOW, r0=0, r1=0)
        files = [a[0] for n, a, _ in cam.draws if n == 'D_FILE']
        self.assertEqual(files, ['\\FPSUPUI\\4.BIN'] * 3)   # no frame 0 from us
        self.assertEqual(cam.word(DRAW), DRAW_STOCK)


ECHO_SLOT, ECHO_ORIG = 0xC0BAC2F8, 0xC03D99A0
AR_TABLE, AR_LINEFN = 0xC2F20FC0, 0xC03DA7A8
STORE = 0xC3075264


@unittest.skipIf(Uc is None or not IMAGE.exists(), 'needs unicorn and the image')
class ThreeWayBootTests(unittest.TestCase):
    """--store-boot with --loader-hook: instant (hook), fast (store), slow.
    The abort that stops the AutoRun is armed only when an AutoRun is running;
    on the hook path there is none, and arming would leave `echo` pointing at
    the abort."""
    @classmethod
    def setUpClass(cls):
        cls.loader, cls.bin = build(['--store-boot'])

    def test_hook_path_leaves_echo_alone_and_seeds_the_store(self):
        cam = Camera(self.loader, self.bin)
        cam.mu.mem_write(AR_TABLE + 0x21C, struct.pack('<I', 0))   # no script
        cam.mu.mem_write(SITE, struct.pack('<I', 0xEB000000 | ((((CAVE_LOW + 4)
                         - SITE - 8) >> 2) & 0xFFFFFF)))
        cam.call(CAVE_LOW + 4, r0=0xC0BABDD8, r1=1, lr=AR_RET, sp=STACK - 0x1004)
        self.assertIsNone(cam.ar_started)
        self.assertEqual(cam.word(ECHO_SLOT), ECHO_ORIG)
        self.assertNotEqual(cam.word(STORE), 0)                 # magic written
        body = b''.join(struct.pack('<I', cam.word(STORE + 4 + 4 * i))
                        for i in range(8))
        want = b''.join(struct.pack('<I', self.loader[CAVE_LOW + 4 * i])
                        for i in range(8))
        self.assertEqual(body, want)                             # the loader

    def test_autorun_path_arms_the_abort(self):
        cam = Camera(self.loader, self.bin)
        cam.now = 15_000_000
        entry = AR_TABLE + 1 * 36
        cam.mu.mem_write(AR_TABLE + 0x21C, struct.pack('<I', 1))
        cam.mu.mem_write(entry + 4, struct.pack('<I', AR_LINEFN))
        cam.call(CAVE_LOW, r0=0, r1=0)
        self.assertNotEqual(cam.word(ECHO_SLOT), ECHO_ORIG)
        self.assertNotEqual(cam.word(SITE), SITE_ORIG)           # hook armed too

    def test_garbage_depth_is_not_walked(self):
        # the image file holds 0x38357C54 there; a live table never exceeds 15
        cam = Camera(self.loader, self.bin)
        cam.now = 15_000_000
        cam.mu.mem_write(AR_TABLE + 0x21C, struct.pack('<I', 0x38357C54))
        cam.call(CAVE_LOW, r0=0, r1=0)
        self.assertEqual(cam.word(ECHO_SLOT), ECHO_ORIG)

    def test_another_script_is_not_mistaken_for_the_autorun(self):
        cam = Camera(self.loader, self.bin)
        cam.now = 15_000_000
        cam.mu.mem_write(AR_TABLE + 0x21C, struct.pack('<I', 1))
        cam.mu.mem_write(AR_TABLE + 36 + 4, struct.pack('<I', 0xC0420C20))
        cam.call(CAVE_LOW, r0=0, r1=0)
        self.assertEqual(cam.word(ECHO_SLOT), ECHO_ORIG)


@unittest.skipIf(Uc is None or not IMAGE.exists(), 'needs unicorn and the image')
class PlainCardRestoreTests(unittest.TestCase):
    """A card without --loader-hook (every single-product release): the
    power-off restore is there -- payloads no longer carry their own -- but
    0xC03DA420 is never armed, so every boot runs the AutoRun."""
    @classmethod
    def setUpClass(cls):
        cls.loader, cls.bin = build(hook=False)

    def test_restores_at_power_off_but_does_not_arm(self):
        cam = Camera(self.loader, self.bin)
        cam.now = 15_000_000
        cam.call(CAVE_LOW, r0=0, r1=0)
        self.assertEqual(cam.word(SITE), SITE_ORIG)
        self.assertEqual([f for _, f in cam.registered], [0, 1])
        self.assertEqual(cam.draws, [])
        x = cam.word(MARK + 8)
        fw = [(d, n) for d, n in cam.sections()
              if d >= 0x40000000 and not CAVE_LO <= d < CAVE_HI]
        self.assertTrue(fw)
        cam.call(cam.word(x + 4), r0=x, r1=4)
        for d, n in fw:
            self.assertEqual(bytes(cam.mu.mem_read(d, n)),
                             cam.stock[d - 0xC0000000:d - 0xC0000000 + n], hex(d))


if __name__ == '__main__':
    unittest.main()
