"""build_v4.py --slim: the smaller bootstrap (--slim-open; with Fast Start 2
--lhook-in-file, with Fast Start 3 --store-slim), the AutoRun interpreted line by line.

What it proves, on test_v4's Camera (real loader.S / store_boot_slim.S / lhook_stub.S / stage2 / v4 core
under unicorn): the slim cards load v4 SHELL + a test sup on every path -- cold
slow path, Fast Start 3 from the store, Fast Start 2 through the stub stage2
placed after the loader -- that a foreign store is left alone, that the slim loader opens
the CARD even when F_VOL names an SSD, and that a failed open can never run a
stale "VBIN" left in the staging buffer.  Not timing, not flash commit.

    cd fpSup/loader-v4 && python3 -B -m unittest test_boot_slim_v4
    python3 -B test_boot_slim_v4.py --mutate
"""
import pathlib
import re
import struct
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_v4 as T4
import build_v4 as B
import test_v3 as T3
import test_boot_card_v4 as TB

STORE, BOOT_AT, SITE, SITE_STOCK = TB.STORE, TB.BOOT_AT, TB.SITE, TB.SITE_STOCK


def bl_target(site, word):
    off = word & 0xFFFFFF
    off -= (off & 0x800000) << 1
    return site + 8 + 4 * off
_built = {}


def built(instant=True, fast=True, markers=False, slim=True):
    key = instant, fast, markers, slim
    if key not in _built:
        _built[key] = B.boot_card(splash=True, instant=instant, fast=fast, markers=markers, slim=slim)
    return _built[key]


class Camera(TB.Camera):
    """TB.Camera that records the volume every file object is built on, and can
    play an attached SSD: F_VOL names volume 5 and nothing opens there."""
    def __init__(self, *a, ssd=False, **kw):
        self.ssd, self.vols, self.stale = ssd, [], False
        super().__init__(*a, **kw)

    def _alloc(self, n, align=8):
        p = super()._alloc(n, align)
        if self.stale:            # an earlier load's staging buffer, never cleared
            junk = struct.pack('<4I', 0x4E494256, 0x7FFFFFF0, 0xC0000000, 0x10) * (n // 16)
            self.mu.mem_write(p, junk)
        return p

    def _hook(self, mu, addr, size, data):
        if addr == T3.F['F_VOL'] and self.ssd:
            return self._ret(5)
        if addr == T3.F['F_CTOR']:
            self.vols.append(self.r(T3.UC_ARM_REG_R1))
            self._vol = self.r(T3.UC_ARM_REG_R1)
        if addr == T3.F['F_OPEN'] and self.ssd and getattr(self, '_vol', 1) != 1:
            self.opened.append(self.cstr(self.r(T3.UC_ARM_REG_R1)))
            self.fobj[self.r(T3.UC_ARM_REG_R0)] = None
            return self._ret(0)
        return super()._hook(mu, addr, size, data)


def cold_again(cam):
    """Power-off, then a cold boot: RAM cave and arena gone, settings block kept."""
    cam.power_off_all()
    cam.registered.clear()
    cam.heap_next = T4.HEAP
    cam.written.pop('\\fpSup\\LOAD.LOG', None)
    cam.mu.mem_write(T3.CAVE_LOW, bytes(0x200))
    cam.mu.mem_write(BOOT_AT, bytes(0x100))
    cam.put(SITE, SITE_STOCK)
    cam.put(T3.DRAW, T3.DRAW_PAUSED)
    cam.put(TB.TABLE + 0x21C, 2)
    cam.put(TB.CTX + 0x90, 1)
    cam.put(TB.CTX + 0x94, TB.FOBJ)
    cam.opened.clear()
    cam.vols.clear()


@unittest.skipIf(T4.Uc is None or not T3.IMAGE.exists(), 'needs unicorn and firmware image')
class SlimBootTests(unittest.TestCase):
    def setUp(self):
        self.stock_a = T3.word(T3.IMAGE.read_bytes(), T4.SITE_A)

    def sups(self):
        ts = B.test_sup(T4.cfg(claims=[(T4.SITE_A, self.stock_a, 2, T4.NOP)]), 'AAAA',
                        flags=B.SL_F_CACHED_OK)
        return [('SHELL.BIN', B.shell_sup()), ('TEST.BIN', ts)]

    def cam(self, ar, blob, **kw):
        return Camera(ar, blob, self.sups(), active=True, **kw)

    # ---------------------------------------------------------------- shape
    def test_off_is_unchanged_and_on_is_smaller(self):
        for fast in (False, True):
            plain, slim = built(fast=fast, slim=False)[0], built(fast=fast)[0]
            self.assertEqual(plain, B.boot_card(splash=True, instant=True, fast=fast)[0])
            self.assertNotEqual(plain, slim)
            cnt = lambda ar, lo, hi: sum(lo <= int(a, 16) < hi for a in
                                         re.findall(rb'^mem set (0x[0-9A-Fa-f]+) ', ar, re.M))
            lo = T3.CAVE_LOW
            self.assertEqual(cnt(plain, lo, lo + 0x200), 81)
            self.assertEqual(cnt(slim, lo, lo + 0x200), 62)
            if fast:
                self.assertEqual(cnt(plain, BOOT_AT, BOOT_AT + 0x100), 30)
                self.assertEqual(cnt(slim, BOOT_AT, BOOT_AT + 0x100), 26)

    # ------------------------------------------------------- normal (no FS3)
    def test_no_fs3_cold_loads_and_warm_hook_reloads(self):
        ar, blob, _ = built(fast=False)
        cam = self.cam(ar, blob)
        _n, stopped = TB.run_autorun(cam, ar)
        self.assertFalse(stopped)
        self.assertEqual(cam.loaded(), ['SHELL.BIN', 'TEST.BIN'])
        self.assertEqual(cam.w(T4.SITE_A), T4.NOP)
        self.assertEqual(cam.vols[0], 1, 'the loader opens the card')
        self.assertNotEqual(cam.w(SITE), SITE_STOCK)
        cam.power_off_all()
        self.assertEqual(cam.w(T4.SITE_A), self.stock_a)
        cam.registered.clear()
        cam.heap_next = T4.HEAP
        cam.written.pop('\\fpSup\\LOAD.LOG', None)
        cam.put(TB.TABLE + 0x21C, 0)
        stub = bl_target(SITE, cam.w(SITE))
        self.assertGreater(stub, T3.CAVE_LOW + 4, 'the hook points at the stub, not the loader')
        r, sp = cam.call(stub, r0=123, r1=456)                        # Fast Start 2
        self.assertEqual((r, sp), (0, T3.STACK - 0x1004))
        self.assertIsNone(cam.fallback)
        self.assertEqual(cam.loaded(), ['SHELL.BIN', 'TEST.BIN'])
        self.assertEqual(cam.misaligned, [])

    def test_ssd_attached_slim_opens_the_card_directly(self):
        for slim in (False, True):
            with self.subTest(slim=slim):
                ar, blob, _ = built(fast=False, slim=slim)
                cam = self.cam(ar, blob, ssd=True)
                TB.run_autorun(cam, ar)
                self.assertEqual(cam.loaded(), ['SHELL.BIN', 'TEST.BIN'])
                self.assertEqual(cam.vols[0], 1 if slim else 5)

    def test_missing_file_never_runs_a_stale_vbin(self):
        ar, blob, _ = built(fast=False)
        cam = self.cam(ar, blob)
        del cam.files['\\fpSup\\LOADER.BIN']
        cam.stale = True                                               # every word of it "VBIN"-headed
        _n, stopped = TB.run_autorun(cam, ar)
        self.assertFalse(stopped)
        self.assertEqual(cam.loaded(), [])
        self.assertEqual(cam.w(T4.SITE_A), self.stock_a)
        self.assertIn('\\fpSup\\LOADER.BIN', cam.opened)

    # ----------------------------------------------------------------- FS3
    def test_fs3_slow_then_store_hit_without_cave_copy(self):
        for markers in (False, True):
            with self.subTest(markers=markers):
                ar, blob, _ = built(markers=markers)
                cam = self.cam(ar, blob)
                if markers:
                    cam.mu.mem_write(TB.MARK_AT, bytes(TB.MARK_BYTES))
                _n, stopped = TB.run_autorun(cam, ar)                  # store empty: slow path
                self.assertFalse(stopped)
                self.assertEqual(cam.loaded(), ['SHELL.BIN', 'TEST.BIN'])
                lw = {int(a, 16): int(v, 16) for a, v in
                      re.findall(rb'^mem set (0x[0-9A-Fa-f]+) (0x[0-9A-Fa-f]+)', ar, re.M)
                      if T3.CAVE_LOW <= int(a, 16) < T3.CAVE_LOW + 0x200}
                body = b''.join(struct.pack('<I', lw[a]) for a in sorted(lw))
                self.assertEqual(bytes(cam.mu.mem_read(STORE + 4, len(body))), body)
                self.assertNotEqual(cam.w(STORE), 0, 'stage2 wrote the magic')
                stub = bl_target(SITE, cam.w(SITE))
                self.assertEqual(stub, (T3.CAVE_LOW + len(body) + 7) & ~7)
                stored = bytes(cam.mu.mem_read(STORE, 512))
                cold_again(cam)
                if markers:
                    cam.mu.mem_write(TB.MARK_AT, bytes(TB.MARK_BYTES))
                _n, stopped = TB.run_autorun(cam, ar)                  # second cold boot
                self.assertTrue(stopped, 'Fast Start 3 stops the script')
                self.assertEqual(bytes(cam.mu.mem_read(STORE, 512)), stored)
                self.assertEqual(bytes(cam.mu.mem_read(T3.CAVE_LOW, len(body))), body,
                                 'the stored loader was copied into the cave')
                self.assertEqual(bl_target(SITE, cam.w(SITE)), stub, 'and the stub re-placed and armed')
                self.assertEqual(cam.loaded(), ['SHELL.BIN', 'TEST.BIN'])
                self.assertEqual(cam.w(T4.SITE_A), T4.NOP)
                if markers:
                    magic, st = TB.marks(cam)
                    self.assertEqual(magic, TB.MRKD)
                    self.assertTrue(st[-1] < cam.w(TB.LOAD_START_US) < cam.w(TB.LOAD_DONE_US))
                self.assertEqual(cam.misaligned, [])

    def test_fs2_warm_hook_runs_through_the_stub(self):
        ar, blob, _ = built()
        cam = self.cam(ar, blob)
        TB.run_autorun(cam, ar)
        stub = bl_target(SITE, cam.w(SITE))
        self.assertTrue(T3.CAVE_LOW < stub < T3.CAVE_LOW + 0x200)
        cam.power_off_all()
        cam.registered.clear()
        cam.heap_next = T4.HEAP
        cam.written.pop('\\fpSup\\LOAD.LOG', None)
        cam.put(TB.TABLE + 0x21C, 0)
        r, sp = cam.call(stub, r0=123, r1=456)
        self.assertEqual((r, sp), (0, T3.STACK - 0x1004))
        self.assertIsNone(cam.fallback, 'warm path never starts the AutoRun')
        self.assertEqual(cam.loaded(), ['SHELL.BIN', 'TEST.BIN'])
        self.assertEqual(cam.misaligned, [])

    def test_foreign_store_is_left_alone(self):
        ar, blob, _ = built()
        cam = self.cam(ar, blob)
        junk = bytes(range(256)) * 2
        cam.mu.mem_write(STORE, junk)                                  # the camera's own settings
        for a, v in re.findall(rb'^mem set (0x[0-9A-Fa-f]+) (0x[0-9A-Fa-f]+)', ar, re.M):
            if BOOT_AT <= int(a, 16) < BOOT_AT + 0x100:
                cam.put(int(a, 16), int(v, 16))
        r, sp = cam.call(BOOT_AT)
        self.assertEqual((r, sp), (0, T3.STACK - 0x1004))
        self.assertEqual(cam.opened, [], 'a miss returns before any file I/O')
        self.assertEqual(bytes(cam.mu.mem_read(STORE, 512)), junk)


# ------------------------------------------------------------------ mutation
MUTANTS = [
    ('asm/store_boot_slim.S', 'bne     7f', 'nop', 'store: copies and branches into a foreign store'),
    ('asm/store_boot_slim.S', 'bne     7f', 'b       7f', 'store: never takes the fast path'),
    ('asm/store_boot_slim.S', '    mov     r0, r5\n', '    add     r0, r5, #4\n', 'store: wrong entry'),
    ('asm/store_boot_slim.S', 'ldr     r0, [r1], #4', 'ldr     r0, [r1, #4]!', 'store: checks the wrong word'),
    ('asm/lhook_stub.S', 'bxne    lr', 'nop', 'stub: starts the AutoRun after a good load'),
    ('asm/lhook_stub.S', 'cmp     r0, #0', 'cmp     r0, #1', 'stub: misreads the load result'),
    ('asm/loader.S', 'streq   r8, [r6]', 'nop', 'slim: stale VBIN survives a failed open'),
    ('asm/loader.S', 'mov     r1, #VOL_SD', 'mov     r1, r0', 'slim: opens the volume F_VOL names'),
    ('asm/loader.S', '    beq     load_shut\n#else', '    nop\n#else', 'slim: reads after a failed open'),
]


def mutate():
    import subprocess
    root = HERE.parent / 'fp_usb_shell'             # the mutants are its asm/ sources
    killed = 0
    for path, old, new, what in MUTANTS:
        p = root / path
        src = p.read_text()
        assert src.count(old) == 1, (path, old)
        p.write_text(src.replace(old, new))
        try:
            r = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'test_boot_slim_v4'],
                               cwd=HERE, capture_output=True, text=True, timeout=1800)
        finally:
            p.write_text(src)
        dead = r.returncode != 0
        killed += dead
        print(('KILLED  ' if dead else 'SURVIVED') + f'  {what}', flush=True)
    print(f'{killed}/{len(MUTANTS)} mutants killed')
    return killed == len(MUTANTS)


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        sys.exit(0 if mutate() else 1)
    unittest.main()
