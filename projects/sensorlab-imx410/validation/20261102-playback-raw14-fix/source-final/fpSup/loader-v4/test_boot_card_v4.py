"""The v4 core inside the shared splash / Instant (Fast Start 2) / Fast (Fast Start 3)
boot envelope that the merge page ships (build_v4.py --card).

Same harness ideas as v3/test_boot_options.py (real AutoRun loader words, real
store_boot path, warm loader hook), on test_v4's Camera (heap at both aliases)
with v4 sups.  Proves control flow and saved bytes, not timing or flash commit.

Run from fpSup/loader-v4:  python3 -B -m unittest test_boot_card_v4
"""
import pathlib
import re
import struct
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_v4 as T4                     # puts v3/ and fp_usb_shell/ on sys.path too
import build_v4 as B
import build_v3 as V3
import test_v3 as T3

# addresses as in v3/test_boot_options.py
SITE, SITE_STOCK = 0xC03DA420, 0xEB0000CC          # warm-boot loader hook site
STORE, BOOT_AT = 0xC3075264, 0xC072F700            # Fast Start 3 store, its bootstrap
ECHO, ECHO_STOCK, ABORT = 0xC0BAC2F8, 0xC03D99A0, 0xC072F080
TABLE, LINE, POP = 0xC2F20FC0, 0xC03DA7A8, 0xC0420D90
CTX, FOBJ = 0xC3010000, 0xC3010200
_built = {}


def built(instant, fast, splash=True):
    key = instant, fast, splash
    if key not in _built:
        _built[key] = B.boot_card(splash=splash, instant=instant, fast=fast)
    return _built[key]


class Camera(T4.Camera):
    """test_v4's Camera booted by a given AutoRun envelope (v3 boot-options setup)."""
    def __init__(self, ar, blob, sups, active=False):
        files = {'\\fpSup\\LOADER.BIN': blob}
        ents = [('LOADER.BIN', 0x20, len(blob))]
        for name, data in sups:
            files['\\fpSup\\' + name] = data
            ents.append((name, 0x20, len(data)))
        super().__init__(files, {'\\fpSup': ents})
        # replace the default AutoRun's loader words with this envelope's
        lo = T3.CAVE_LOW
        self.mu.mem_write(lo, bytes(0x200))
        for a, v in V3.loader_words(ar).items():
            self.mu.mem_write(a, struct.pack('<I', v))
        self.files.update({f'\\fpSup\\UI\\{i}.BIN': px for i, px in enumerate(V3.splash_frames())})
        self.put(T3.DRAW, T3.DRAW_PAUSED)          # a cold AutoRun pauses redraw
        for a, v in re.findall(rb'^mem set (0x[0-9A-Fa-f]+) (0x[0-9A-Fa-f]+)', ar, re.M):
            a, v = int(a, 16), int(v, 16)
            if BOOT_AT <= a < BOOT_AT + 0x100:
                self.put(a, v)
        self.by_addr[POP] = 'AR_POP'
        self.put(POP, 0xE12FFF1E)
        self.fallback = None
        self.put(TABLE + 0x21C, 2 if active else 0)
        self.put(TABLE + 36 + 4, 0xC03DA158)
        self.put(TABLE + 72 + 4, LINE)
        self.put(TABLE + 72 + 12, CTX)
        self.put(CTX + 0x90, 1 if active else 0)
        self.put(CTX + 0x94, FOBJ if active else 0)

    def _hook(self, mu, addr, size, data):
        if addr == T3.F['D_FILE']:
            path = self.cstr(self.w(self.r(T3.UC_ARM_REG_R2)))
            if path not in self.files:
                raise AssertionError('artwork path absent from card: ' + path)
        if addr == POP:
            self.calls.append('AR_POP')
            self.put(TABLE + 0x21C, self.w(TABLE + 0x21C) - 1)
            return self._ret(0)
        if addr == T3.F['AR_START']:
            self.fallback = tuple(self.r(x) for x in (T3.UC_ARM_REG_R0, T3.UC_ARM_REG_R1, T3.UC_ARM_REG_LR))
        return super()._hook(mu, addr, size, data)

    def power_off_all(self):
        for obj in dict.fromkeys(o for o, _ in self.registered):
            self.call(self.w(self.w(obj) + 12), r0=obj, r1=4)

    def loaded(self):
        return [t for c, _, _, t in self.loadlog() if c == T4.CODES['LOADED']]


MARK_AT, MARK_DATA, MARK_BYTES = 0xC072E064, 0xC072E0B4, 0x98
LOAD_START_US, LOAD_DONE_US, CAVE_BUMP = 0xC072F6F4, 0xC072F6F8, 0xC072E060
MRK1, MRKD, NONE = 0x314B524D, 0x444B524D, 0x454E4F4E


def run_autorun(cam, ar):
    """Interpret the AutoRun the way the shell does, one line at a time:
    `mem set` writes, `echo` calls whatever the echo slot holds (stock = no-op;
    the loader's abort routine stops the script), `display osdfile` must name a
    file on the card.  Returns (lines run, stopped_by_abort)."""
    n = 0
    for raw in ar.decode().splitlines():
        line = raw.strip()
        n += 1
        m = re.match(r'^mem set (0x[0-9A-Fa-f]+) (0x[0-9A-Fa-f]+)$', line)
        if m:
            cam.put(int(m.group(1), 16), int(m.group(2), 16))
        elif line == 'echo':
            h = cam.w(ECHO)
            if h in (ECHO_STOCK, 0xC000E91C, 0xC000EABC):   # stock / cache publish: stubs here
                continue
            _r, sp = cam.call(h)
            assert sp == T3.STACK - 0x1004, hex(sp)
            if h == ABORT:
                return n, True
        elif line.startswith('display osdfile '):
            path = line.split()[2]
            assert path in cam.files, path
    return n, False


def marks(cam):
    magic, count = cam.w(MARK_DATA), cam.w(MARK_DATA + 4)
    return magic, [cam.w(MARK_DATA + 8 + 4 * i) for i in range(count)]


@unittest.skipIf(T4.Uc is None or not T3.IMAGE.exists(), 'needs unicorn and firmware image')
class BootMarkersTests(unittest.TestCase):
    """build_v4.py --card --boot-markers, the AutoRun actually interpreted."""
    def setUp(self):
        self.stock_a = T3.word(T3.IMAGE.read_bytes(), T4.SITE_A)

    def sups(self):
        ts = B.test_sup(T4.cfg(claims=[(T4.SITE_A, self.stock_a, 2, T4.NOP)]), 'AAAA',
                        flags=B.SL_F_CACHED_OK)
        return [('SHELL.BIN', B.shell_sup()), ('TEST.BIN', ts)]

    def cold(self, ar, blob):
        cam = Camera(ar, blob, self.sups(), active=True)
        cam.mu.mem_write(MARK_AT, bytes(MARK_BYTES))
        return cam

    def test_off_is_byte_identical(self):
        self.assertEqual(built(True, True)[0], B.boot_card(splash=True, instant=True, fast=True, markers=False)[0])
        self.assertNotIn(b'0xC072E064', built(True, True)[0])

    def test_slow_path_seven_stamps_around_the_loader(self):
        ar, blob, _ = B.boot_card(splash=True, instant=True, fast=True, markers=True)
        cam = self.cold(ar, blob)                       # store empty: Fast Start 3 misses
        _n, stopped = run_autorun(cam, ar)
        self.assertFalse(stopped)
        magic, st = marks(cam)
        self.assertEqual(magic, MRKD, 'the core saw this boot\'s AutoRun')
        self.assertEqual(len(st), 7)                    # S0 S1 S2 S3 S4 S5 S6
        self.assertEqual(st, sorted(st))
        start, done = cam.w(LOAD_START_US), cam.w(LOAD_DONE_US)
        self.assertTrue(st[5] < start < done < st[6], (st, start, done))
        self.assertEqual(cam.loaded(), ['SHELL.BIN', 'TEST.BIN'])
        self.assertEqual(cam.w(T4.SITE_A), T4.NOP)
        self.assertGreaterEqual(cam.w(CAVE_BUMP), MARK_AT + MARK_BYTES, 'the block is reserved')
        code = bytes(cam.mu.mem_read(MARK_AT, 0x44))
        self.assertEqual(code[:4], struct.pack('<I', 0xE92D4070), 'the routine survived the load')
        self.assertEqual(cam.misaligned, [])

    def test_fast_start_3_hit_five_stamps_then_loader_profile(self):
        ar, blob, _ = B.boot_card(splash=True, instant=True, fast=True, markers=True)
        cam = self.cold(ar, blob)
        run_autorun(cam, ar)                            # first boot fills the store
        stored = bytes(cam.mu.mem_read(STORE, 512))
        cam.power_off_all()
        cam.registered.clear()
        cam.heap_next = T4.HEAP
        cam.written.pop('\\fpSup\\LOAD.LOG', None)
        cam.mu.mem_write(T3.CAVE_LOW, bytes(0x200))     # cold: cave and arena empty
        cam.mu.mem_write(MARK_AT, bytes(MARK_BYTES))
        cam.put(SITE, SITE_STOCK)
        cam.put(T3.DRAW, T3.DRAW_PAUSED)
        cam.put(TABLE + 0x21C, 2)
        cam.put(CTX + 0x90, 1)
        cam.put(CTX + 0x94, FOBJ)
        _n, stopped = run_autorun(cam, ar)
        self.assertTrue(stopped, 'the fast path stops the script')
        self.assertEqual(bytes(cam.mu.mem_read(STORE, 512)), stored)
        magic, st = marks(cam)
        self.assertEqual(magic, MRKD)
        self.assertEqual(len(st), 5)                    # S0..S4; LOAD_START/DONE carry the rest
        self.assertTrue(st[4] < cam.w(LOAD_START_US) < cam.w(LOAD_DONE_US))
        self.assertEqual(cam.loaded(), ['SHELL.BIN', 'TEST.BIN'])
        self.assertEqual(cam.misaligned, [])

    def test_fast_start_2_warm_boot_empties_the_stale_array(self):
        ar, blob, _ = B.boot_card(splash=True, instant=True, fast=True, markers=True)
        cam = self.cold(ar, blob)
        run_autorun(cam, ar)
        first_done = cam.w(LOAD_DONE_US)
        cam.power_off_all()
        cam.registered.clear()
        cam.heap_next = T4.HEAP
        cam.written.pop('\\fpSup\\LOAD.LOG', None)
        cam.put(TABLE + 0x21C, 0)
        r, sp = cam.call(T3.CAVE_LOW + 4, r0=123, r1=456)  # the warm loader hook, no AutoRun
        self.assertEqual((r, sp), (0, T3.STACK - 0x1004))
        self.assertEqual(marks(cam), (NONE, []), 'previous boot\'s stamps are not this boot\'s')
        self.assertTrue(first_done < cam.w(LOAD_START_US) < cam.w(LOAD_DONE_US))
        self.assertEqual(cam.loaded(), ['SHELL.BIN', 'TEST.BIN'])


@unittest.skipIf(T4.Uc is None or not T3.IMAGE.exists(), 'needs unicorn and firmware image')
class BootCardV4Tests(unittest.TestCase):
    def setUp(self):
        img = T3.IMAGE.read_bytes()
        self.stock_a = T3.word(img, T4.SITE_A)

    def sups(self):
        ts = B.test_sup(T4.cfg(claims=[(T4.SITE_A, self.stock_a, 2, T4.NOP)]), 'AAAA',
                        flags=B.SL_F_CACHED_OK)
        return [('SHELL.BIN', B.shell_sup()), ('TEST.BIN', ts)]

    def test_card_build_is_the_merge_page_shell(self):
        ar, _blob, info = built(True, True)
        backup = HERE.parents[1] / 'projects/loader-v4/validation/card-backup-20261020/AutoRun.txt'
        if backup.exists():
            self.assertEqual(ar, backup.read_bytes())
        self.assertTrue(info['instant'] and info['fast'] and info['splash'])
        self.assertIn(b'display osdfile \\fpSup\\UI\\0.BIN', ar)

    def test_four_options_load_v4_and_restore(self):
        for instant in (False, True):
            for fast in (False, True):
                with self.subTest(instant=instant, fast=fast):
                    ar, blob, _ = built(instant, fast)
                    cam = Camera(ar, blob, self.sups(), active=True)
                    before = bytes(cam.mu.mem_read(STORE, 512))
                    _r, sp = cam.boot()
                    self.assertEqual(sp, T3.STACK - 0x1004)
                    self.assertEqual(cam.misaligned, [])
                    self.assertEqual(cam.loaded(), ['SHELL.BIN', 'TEST.BIN'])
                    self.assertEqual(cam.w(T4.SITE_A), T4.NOP)
                    self.assertEqual(cam.w(SITE) != SITE_STOCK, instant)
                    if fast:
                        words = b''.join(struct.pack('<I', v) for a, v in sorted(V3.loader_words(ar).items()))
                        self.assertEqual(bytes(cam.mu.mem_read(STORE + 4, len(words))), words)
                        self.assertNotEqual(cam.w(STORE), 0)
                        self.assertEqual(cam.w(ECHO), ABORT)
                    else:
                        self.assertEqual(bytes(cam.mu.mem_read(STORE, 512)), before)
                        self.assertEqual(cam.w(ECHO), ECHO_STOCK)
                    cam.power_off_all()
                    self.assertEqual(cam.w(T4.SITE_A), self.stock_a)
                    self.assertEqual(cam.w(T3.DRAW), T3.DRAW_STOCK)

    def test_fast_start_2_warm_restart_reloads_v4_without_autorun(self):
        for fast in (False, True):
            with self.subTest(fast=fast):
                ar, blob, _ = built(True, fast)
                cam = Camera(ar, blob, self.sups())
                cam.boot()
                cam.power_off_all()
                self.assertEqual(cam.w(T4.SITE_A), self.stock_a)
                cam.registered.clear()
                cam.heap_next = T4.HEAP
                cam.written.pop('\\fpSup\\LOAD.LOG', None)
                cam.put(TABLE + 0x21C, 0)
                r, sp = cam.call(T3.CAVE_LOW + 4, r0=123, r1=456)      # the warm hook
                self.assertEqual((r, sp), (0, T3.STACK - 0x1004))
                self.assertIsNone(cam.fallback, 'warm path never starts the AutoRun')
                self.assertEqual(cam.loaded(), ['SHELL.BIN', 'TEST.BIN'])
                self.assertEqual(cam.w(T4.SITE_A), T4.NOP)
                self.assertEqual(cam.w(ECHO), ECHO_STOCK)
                self.assertEqual(cam.misaligned, [])

    def test_fast_start_3_cold_boot_from_store_loads_v4(self):
        for instant in (False, True):
            with self.subTest(instant=instant):
                ar, blob, _ = built(instant, True)
                cam = Camera(ar, blob, self.sups(), active=True)
                r, sp = cam.call(BOOT_AT)                              # first boot: store empty
                self.assertEqual((r, sp), (0, T3.STACK - 0x1004))
                self.assertEqual(cam.opened, [], 'miss returns before file I/O')
                cam.boot()                                             # the script's normal path
                stored = bytes(cam.mu.mem_read(STORE, 512))
                cam.power_off_all()
                cam.registered.clear()
                cam.heap_next = T4.HEAP
                cam.written.pop('\\fpSup\\LOAD.LOG', None)
                cam.put(T3.DRAW, T3.DRAW_PAUSED)
                cam.mu.mem_write(T3.CAVE_LOW, bytes(0x200))            # cold: cave empty
                cam.put(SITE, SITE_STOCK)
                cam.put(TABLE + 0x21C, 2)
                cam.put(CTX + 0x90, 1)
                cam.put(CTX + 0x94, FOBJ)
                r, sp = cam.call(BOOT_AT)                              # second boot: from store
                self.assertEqual(sp, T3.STACK - 0x1004)
                self.assertEqual(bytes(cam.mu.mem_read(STORE, 512)), stored)
                self.assertEqual(cam.loaded(), ['SHELL.BIN', 'TEST.BIN'])
                self.assertEqual(cam.w(T4.SITE_A), T4.NOP)
                self.assertEqual(cam.w(SITE) != SITE_STOCK, instant)
                self.assertEqual(cam.w(ECHO), ABORT)
                self.assertEqual(cam.misaligned, [])


if __name__ == '__main__':
    unittest.main()
