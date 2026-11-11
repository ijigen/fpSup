"""native/lvb.c under unicorn: the active LUT on the ISP (user 2026-11-04: Live View,
MOV and JPG; DNG tags stay stock), the real ARM bytes against the real image.

The root struct (0xC2F1A064) is seg1's stock bytes.  Which tone table the ISP
gets is asked of the firmware's own FUN_c02d2f40 (with FUN_c02cf490 and
FUN_c02d25e8 under it, all real); the fit is compared with
projects/lut-sup/probes/lv_fit.py's float algorithm on the same samples and
weights (the oracle), and its result is scored with lv_fit.predict_isp, the
model the camera matched on 2026-11-03 (validation/20261103-lv-isp-05).

    cd fpSup/lut && python3 -B -m unittest test_lvb_native
"""
from pathlib import Path
import struct
import sys
import unittest

import numpy as np

import library as L
import build_sup as P
import test_library_native as LN
import test_clist_native as CN
import test_dng_native as DN
import test_sup_ui as U
import test_sup_native as NS
from test_lut import make_cube

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / 'projects/lut-sup/probes'))
import lv_fit as F                                          # noqa: E402

SEG1 = ROOT_DIR / 'out/seg1_c2ef6e00.bin'
ROOT = 0xC2F1A064
P08, P10, P48, P70 = ROOT + 8, ROOT + 0x10, ROOT + 0x48, ROOT + 0x70
STOCK = {P08: (0xC0B39CC8, 35), P10: (0xC0B3A010, 34), P48: (0xC0B3AAEC, 12), P70: (0xC0B3D670, 36)}
S124, S12D, S34, LIVE = 0xC02C5450, 0xC02C5E18, 0xC02CC1A0, 0xC02D3A90
GETTONE, CURVES, OFF = 0xC02D2F40, 0xC0971114, 0x24
MAGIC = 0x3142564C
WHITE, N = 1918, 2048


class Camera(DN.Camera):
    """+ the firmware's tone-slot lookup as Python (decomp blk_c02.c FUN_c02d2f40, FUN_c02cf490,
    FUN_c02d25e8; the same model lv_backend_probe.Fake used, camera-confirmed 2026-11-03)."""
    CACHE_MODE, CACHE_HIT = 0xC3414D14, 0xC3414D10
    CONTRAST = 0xC02D25E8

    def page_entries(self):
        super().page_entries()
        seg = SEG1.read_bytes()
        self.mu.mem_write(ROOT, seg[ROOT - 0xC2EF6E00:][:0x100])   # the stock root, before the sup's entry
        ycm = 0xC2F1AAE8                                          # root+0x28's YCMAT table (RAM .data) as after boot:
        tab = bytearray(seg[ycm - 0xC2EF6E00:][:35 * 0x14])       # FUN_c02d5e00 fills Y = 1224/2403/469
        for k in range(35):
            struct.pack_into('<3h', tab, k * 0x14 + 4, 1224, 2403, 469)
        self.mu.mem_write(ycm, bytes(tab))
        self.put(self.CACHE_MODE, 0x24); self.put(0xC2F19D44, 0x5555)   # a past boot's caches
        self.by_addr[GETTONE] = 'LVB_GETTONE'; self.by_addr[self.CONTRAST] = 'LVB_CONTRAST'
        self.by_addr[LIVE] = 'LVB_LIVE'
        if self.color_setting is not None:                 # the saved COLOR mode (bank A)
            self.put(0xC31B32BC + 0x12C, self.color_setting)

    color_setting = None

    def contrast(self, key, table, n):
        return next((self.w(table + 8 * i + 4) for i in range(n) if self.w(table + 8 * i) == key), 0x7FFFFFFF)

    def three(self, root, mode):                        # FUN_c02cf490, with its one-entry cache
        if mode == self.w(self.CACHE_MODE):
            return self.mu.mem_read(self.CACHE_HIT, 1)[0]
        hit = int(mode in [self.w(self.w(root + 0x48) + 4 * k) for k in range(self.w(root + 0x4C))])
        self.mu.mem_write(self.CACHE_HIT, bytes([hit])); self.put(self.CACHE_MODE, mode)
        return hit

    def gettone(self, p1, mode, p3):
        root = self.w(p1)
        base = next((self.w(self.w(root + 0x70) + 8 * i + 4) for i in range(self.w(root + 0x74))
                     if self.w(self.w(root + 0x70) + 8 * i) == mode), 5)
        c = self.contrast(p3, self.w(root + 0x78), self.w(root + 0x7C))
        if self.three(p1 and root, mode):
            c *= 3
        return (c + base) & 0xFFFFFFFF

    def _hook(self, mu, addr, size, data):
        name = self.by_addr.get(addr)
        if name == 'LVB_LIVE':                             # FUN_c02d3a90: obj + 0x1C, or + 0x110
            r0, r1 = self.r(U.N.T3.UC_ARM_REG_R0), self.r(U.N.T3.UC_ARM_REG_R1)
            return self._ret(r0 + (0x1C if not (r1 & 0xFF) else 0x110))
        if name in ('LVB_GETTONE', 'LVB_CONTRAST'):
            r = [self.r(getattr(U.N.T3, f'UC_ARM_REG_R{k}')) for k in range(3)] + [self.r(U.N.T4.UC_ARM_REG_R3)]
            self.lvb_fw.append((name, *r))
            if name == 'LVB_GETTONE':
                return self._ret(self.gettone(*r[:3]))
            return self._ret(self.contrast(r[1], r[2], r[3]))
        return super()._hook(mu, addr, size, data)

    lvb_fw = []

    def lvb(self):
        """lut4_state.lvb, found by its magic."""
        _api, state = self.lut()
        blob = bytes(self.mu.mem_read(state, 4096))
        at = next(i for i in range(0, 4096, 4) if struct.unpack_from('<I', blob, i)[0] == MAGIC)
        w = struct.unpack_from('<23I', blob, at)
        return dict(ready=w[1], installed=w[2], keyed=w[3], result=w[4], fits=w[5], shift=w[11],
                    calls124=w[12], calls12d=w[13], mat=[x - (1 << 32) if x >> 31 else x for x in w[14:23]])

    def roots(self):
        return {p: (self.w(p), self.w(p + 4)) for p in STOCK}

    def entry(self, table, n, mode=OFF):
        for i in range(n):
            if self.w(table + 0x18 * i) == mode:
                return struct.unpack('<9h', bytes(self.mu.mem_read(table + 0x18 * i + 4, 18)))

    HOLDER = U.U.F6.FAKE + 0xF800

    def tone_tables(self, key=0):
        """FUN_c02d2f40(&root, OFF, key) -> slot -> the table(s) the ISP gets."""
        self.put(self.HOLDER, ROOT); self.put(self.CACHE_MODE, 0xFFFFFFFF)
        idx = self.gettone(self.HOLDER, OFF, key)
        n = 3 if self.three(ROOT, OFF) else 1
        return [self.w((CURVES + ((idx + c) & 0xFFFFFFFF) * 8 + 4) & 0xFFFFFFFF) for c in range(n)]

    def tone_at(self, addr):
        return np.frombuffer(bytes(self.mu.mem_read(addr, 2 * N)), '<u2')

    def arm(self, pc, *args):
        """An ARM call through a veneer; r0."""
        return self.call(pc, *args)[0]


def oracle(target, strength):
    """lv_fit's float fit on lvb.c's samples and weights."""
    t = np.arange(N) / WHITE
    curves = np.maximum.accumulate(target(np.repeat(t[:, None], 3, 1), strength), axis=0)
    k = np.stack(np.meshgrid(*[np.arange(11)] * 3, indexing='ij'), -1).reshape(-1, 3)
    xs = (2047 / WHITE) * (k / 10.) ** 2
    base = target(xs, 0)
    sat = F.saturation(base)
    w = (1 - 2.5 * sat / 8) ** 8
    M = F.fit_rows(xs, target(xs, strength), t, curves, w)
    q = F.quantise_rows(M, F.Q9)
    tone = np.round(F.TONE_MAX * np.clip(curves, 0, 1)).T.astype(np.uint16)
    return dict(M=M, q=q, tone=tone)


@unittest.skipIf(U.N.T4.Uc is None or not U.N.T3.IMAGE.exists() or not SEG1.exists(),
                 'requires Unicorn, firmware and seg1; skipped is unverified')
class LvbNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LN.LibraryNativeTests.setUpClass.__func__(cls)
        root = cls.root / 'lvb'; root.mkdir()
        tags = b'# FPSUP_INPUT_COLOR_SPACE rec709\n# FPSUP_INPUT_GAMMA gamma24\n'
        # a per-channel look (matrix + three curves holds it exactly) and one that mixes in code
        # space (it does not: lv_fit itself scores dE ~12 on it)
        look = lambda r, g, b: (r ** 1.25, 0.1 + 0.85 * g, b ** 0.8)
        twist = lambda r, g, b: (0.9 * r + 0.1 * g, 0.85 * g + 0.15 * b, 0.2 * r + 0.8 * b)
        cubes = [('M.cube', look), ('T.cube', twist)]
        paths = []
        for name, fn in cubes:
            p = root / name; p.write_bytes(tags + make_cube(9, fn=fn)); paths.append(p)
        doc = L.import_cubes(L.blank(), paths)
        for name, _ in cubes:
            doc = L.configure(doc, name, enabled=True)
        cls.ldoc = cls.ddoc = doc
        cls.lfiles = LN.with_library(cls.files, doc)           # the folder: these cubes alone
        cls.cubes = {name: (root / name) for name, _ in cubes}

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def cam(self):
        c = Camera(self.lfiles, self.ar); c.lvb_fw = []
        return c

    def pick(self, c, cube):
        """What the COLOR list's close does with a LUT row (clist_closed -> library_pick = api.pick)."""
        DN.DngNativeTests.pick(self, c, cube)
        index = [e['filename'] for e in self.ldoc['luts']].index(cube)
        self.assertEqual(c.invoke(8, index), 0)

    def unpick(self, c):
        """A stock row: clist_closed picks none."""
        CN.ClistNativeTests.pick_row(self, c, 6)
        self.assertEqual(c.invoke(8, 0xFFFFFFFF), 0)
    setter = CN.ClistNativeTests.setter

    def target(self, name):
        from cube import Cube
        return F.make_target(Cube.read(self.cubes[name]), 'rec709', 'gamma24')

    def test_installed_at_the_entry_and_stock_until_a_lut_row(self):
        c = self.cam()
        v = c.lvb()
        self.assertEqual((v['ready'], v['installed']), (1, 0))
        self.assertEqual(c.roots(), STOCK)
        for site in (S124, S12D, S34):
            self.assertTrue(c.veneer_ok(c.stub_at(site)), hex(site))

    def test_a_lut_row_points_all_four_roots_at_copies_with_our_off_entries(self):
        c = self.cam()
        self.pick(c, 'M.cube')
        v = c.lvb()
        self.assertEqual((v['installed'], v['result'], v['fits']), (1, 1, 1))     # only the picked row's set (Bei 11-10)
        r = c.roots()
        self.assertTrue(all(r[p][0] != STOCK[p][0] for p in STOCK))
        self.assertEqual([r[p][1] for p in (P08, P10, P70)], [35, 34, 36])
        self.assertEqual(r[P48][1], 13)
        for p, (table, n) in ((P08, STOCK[P08]), (P10, STOCK[P10])):
            self.assertEqual(list(c.entry(r[p][0], n)), v['mat'], hex(p))       # both groups: the same M
            for mode in (0x00, 0x01, 0x23, 0x09):                             # every other mode: stock
                self.assertEqual(c.entry(r[p][0], n, mode), c.entry(table, n, mode), (hex(p), mode))

    def test_the_firmware_finds_our_three_tables_at_every_contrast(self):
        c = self.cam()
        stock = c.tone_tables()
        self.assertEqual(len(stock), 1)
        self.pick(c, 'M.cube')
        got = c.tone_tables()
        self.assertEqual(len(got), 3)
        keys = [c.w(0xC0B3D790 + 8 * i) for i in range(11)]                    # the contrast table's keys
        for k in keys:
            self.assertEqual(c.tone_tables(k), got, k)
        self.assertEqual(len(set(got)), 3)

    def test_the_fit_matches_lv_fit_on_the_same_samples(self):
        c = self.cam()
        self.pick(c, 'M.cube')
        tabs = c.tone_tables()
        want = oracle(self.target('M.cube'), 100)
        for ch in range(3):
            d = c.tone_at(tabs[ch]).astype(int) - want['tone'][ch].astype(int)
            self.assertLessEqual(np.abs(d).max(), 2, ch)
            self.assertLess(abs(d.mean()), 0.2, ch)            # rounded, not truncated (bias -0.5)
        q = np.array(F.table_order(want['q']))
        self.assertLessEqual(np.abs(np.array(c.lvb()['mat']) - q).max(), 3, (c.lvb()['mat'], q.tolist()))

    def test_the_fitted_backend_shows_the_cube_as_well_as_the_oracle(self):
        """dE76 of lv_fit.predict_isp(camera's M and tables) vs the cube, against the oracle's."""
        for name in ('M.cube', 'T.cube'):
            c = self.cam()
            self.pick(c, name)
            tabs = c.tone_tables()
            v = c.lvb()
            mat = np.array(v['mat'])
            q = np.array([[mat[0], mat[1], mat[2]], [mat[4], mat[3], mat[5]], [mat[7], mat[8], mat[6]]])
            fit = dict(q=q, tone=np.stack([c.tone_at(t) for t in tabs]).astype(float))
            target = self.target(name)
            _xs, hold = F.samples()
            y, base = target(hold, 100), target(hold, 0)
            got = F.report(y, F.predict_isp(fit, hold), base)['dE76_mean']
            o = oracle(target, 100)
            ref = F.report(y, F.predict_isp(dict(q=o['q'], tone=o['tone'].astype(float)), hold), base)['dE76_mean']
            self.assertLessEqual(got, ref + 0.1, (name, got, ref))
            if name == 'M.cube':
                self.assertLess(got, 0.6, got)

    @staticmethod
    def mapped(c, p):
        try:
            c.mu.mem_read(p, 4); return True
        except Exception:
            return False

    def test_the_saved_active_lut_is_on_the_isp_from_the_entry(self):
        doc = L.configure(self.ldoc, 'M.cube', active=True)
        files = dict(self.lfiles)
        files[LN.BIN], _ = P.build_sup(collection=doc)
        c = Camera.__new__(Camera); c.color_setting = 0xC        # a saved LUT row: COLOR (menu enum) is OFF
        Camera.__init__(c, files, self.ar); c.lvb_fw = []
        v = c.lvb()
        self.assertEqual((v['installed'], v['result'], v['fits']), (1, 1, 1))     # the saved row alone (Bei 11-10)
        self.assertEqual(len(c.tone_tables()), 3)
        # the row fitted from its cube, loaded into the borrowed asset area (native/borrow.c), which went back
        # with the fit's samples: no asset is kept; the one ISP set (borrowed too) is what the root shows
        _api, state = c.lut()
        words = struct.unpack('<1024I', bytes(c.mu.mem_read(state, 4096)))
        asset = [p for p in words if p > 0xC0000000 and not p & 3 and self.mapped(c, p) and c.w(p) == 0x31554C46]   # s->asset (FLU1)
        self.assertEqual(asset, [])
        gets, frees, out = NS.borrows(c)
        self.assertEqual(gets, frees + 1)
        self.assertEqual(self.sets(out), list(out))
        self.assertEqual(len(out), 1)
        self.assertEqual(NS.dangling(c, self.kept(c)), [])
        loaded = [snap for _q, m, snap in c.borrow_freed if m >= P.CAPACITY]
        self.assertTrue(loaded)
        ids = {L.record_identity(e) for e in doc['luts']}
        for snap in loaded:                                                # each a cube of the library, keyed as its record
            a = next(k for k in range(0, 128, 8) if snap[k:k + 4] == b'FLU1')
            self.assertIn(snap[a + 136:a + 168], ids)

    @staticmethod
    def sets(out):
        """The borrowed areas outstanding that are an ISP set (lvb.c struct lvb_set, 25 984 B)."""
        return [q for q, m in out.items() if 25984 <= m < 32768]

    def kept(self, c):
        """What stays in the block and could point anywhere: lvb's region, and the ISP's root words."""
        blob = c.files[LN.BIN]
        _api, state = c.lut()
        block = state - struct.unpack_from('<I', blob, 48 + 4)[0]
        return [(block + struct.unpack_from('<I', blob, 48 + 44)[0], P.LVB_CAP), (ROOT, 0x90)]

    def test_the_cursor_shows_the_picked_row_and_stock_on_the_others(self):
        """Bei 2026-11-10: the cursor previews a row from its .JFT (lvb_preview; test_capacity covers that).  Here the
        rows have no current .JFT (the harness's header-only files): no fit at the cursor (seconds), so T shows the
        stock look until it is picked; the picked row M keeps its set and shows it at once."""
        c = self.cam()
        self.pick(c, 'M.cube')
        fits, mine = c.lvb()['fits'], c.roots()
        for gui, want in ((17, None), (16, mine), (17, None)):          # T (not picked), M, T
            c.put(0xC2F19D44, 0x1234); c.put(0xC2F19D48, 0x1234); c.put(c.CACHE_MODE, OFF)
            CN.ClistNativeTests.pick_row(self, c, gui, site='MJ')   # the COLOR key's preview path
            self.assertEqual(c.roots(), want or STOCK, gui)
            self.assertEqual((c.w(0xC2F19D44), c.w(0xC2F19D48), c.w(c.CACHE_MODE)), (0xFFFFFFFF,) * 3)   # PQ re-reads
            self.assertEqual(c.arm(c.stub_at(S124)) != ROOT, want is not None)   # DNG: ours only while it shows
        self.assertEqual(c.lvb()['fits'], fits)                         # nothing fitted on the way
        self.assertEqual(len(self.sets(NS.borrows(c)[2])), 1)
        self.pick(c, 'T.cube')                                          # picked: T's set, M's given back
        self.assertEqual(len(self.sets(NS.borrows(c)[2])), 1)
        self.assertNotEqual(c.roots(), STOCK)
        self.assertNotEqual(c.roots()[P08][0], mine[P08][0])
        CN.ClistNativeTests.pick_row(self, c, 6, site='MJ')            # a stock mode: stock at once
        self.assertEqual(c.roots(), STOCK)
        self.assertEqual(c.arm(c.stub_at(S124)), ROOT)

    def test_off_or_another_mode_puts_everything_back(self):
        c = self.cam()
        self.pick(c, 'M.cube')
        self.assertEqual(c.lvb()['installed'], 1)
        self.unpick(c)                                           # a stock mode in the COLOR list
        self.assertEqual(c.roots(), STOCK)
        self.assertEqual(c.lvb()['installed'], 0)

    def test_same_settings_do_not_refit_another_strength_does(self):
        c = self.cam()
        self.pick(c, 'M.cube')
        t100 = c.tone_at(c.tone_tables()[0]).copy()
        self.pick(c, 'M.cube')
        self.assertEqual(c.lvb()['fits'], 1)                     # the picked row only; the same again: no more
        rc = c.invoke(4, 50)                                     # api.strength(50): the active one
        self.assertEqual(rc, 0)
        v = c.lvb()
        self.assertEqual((v['fits'], v['installed']), (2, 1))
        self.assertGreater(np.abs(c.tone_at(c.tone_tables()[0]).astype(int) - t100).max(), 50)   # a per-channel look: the curves move

    # ---- native/borrow.c (2026-11-07): the cube and the fit's samples are borrowed for a fit, not resident
    def test_a_strength_fit_borrows_its_areas_and_returns_them(self):
        """A row whose .JFT is not current (the strength moved) is fitted from its cube: the asset area and
        the samples are borrowed for it and back before the refresh returns; no pointer into them stays."""
        c = self.cam()
        self.pick(c, 'M.cube')
        g0, f0, out = NS.borrows(c)
        self.assertEqual((g0, len(out), self.sets(out)), (f0 + 1, 1, list(out)))   # the shown row's set alone
        self.assertEqual(c.invoke(4, 50), 0)                               # api.strength: M fitted again
        v = c.lvb()
        self.assertEqual((v['fits'], v['installed']), (2, 1))
        g1, f1, out = NS.borrows(c)
        self.assertEqual((g1 - g0, f1 - f0), (4, 4))                       # the new set, a .JFT buffer, the asset area, the samples; the old set back
        self.assertEqual((len(out), self.sets(out)), (1, list(out)))
        sizes = sorted(n for k, _q, n in c.borrow_log[-8:] if k == 'get')
        self.assertGreaterEqual(sizes[-1], P.CAPACITY)
        self.assertEqual(NS.dangling(c, self.kept(c)), [])
        rc, _ = c.render([[.1, .2, .3]])                                  # the API's render: one load, given back
        self.assertEqual(rc, 0)
        g2, f2, out = NS.borrows(c)
        self.assertEqual((g2 - g1, f2 - f1, len(out)), (1, 1, 1))
        self.assertEqual(NS.dangling(c, self.kept(c)), [])

    def test_nothing_is_borrowed_while_recording(self):
        """library_busy(): no fit, no load, no render (the allocator model raises on any ask while recording)."""
        c = self.cam()
        self.pick(c, 'M.cube')
        g0, fits = NS.borrows(c)[0], c.lvb()['fits']
        NS.recording(c)
        self.assertEqual(c.invoke(4, 50), 0)                               # taken; the refit waits
        self.assertEqual(c.lvb()['fits'], fits)
        self.assertEqual(c.render([[.1, .2, .3]])[0], -17)                 # RECORD_BUSY
        index = [e['filename'] for e in self.ldoc['luts']].index('T.cube')
        self.assertEqual(c.invoke(8, index), -17)                          # library_pick refuses first
        self.assertEqual(NS.borrows(c)[0], g0)
        NS.recording(c, False)
        self.assertEqual(c.render([[.1, .2, .3]])[0], 0)
        g, f, out = NS.borrows(c)
        self.assertEqual((g - g0, g, len(self.sets(out)), len(out)), (1, f + 1, 1, 1))

    def test_a_refused_borrow_fails_cleanly_and_is_tried_again(self):
        """The allocator says no: the fit fails (0x500, its row stock), the load says NO_MEMORY (-18) and changes
        nothing, nothing stays borrowed; the next refresh fits it."""
        c = LN.without_jft(self.cam, 'T.cube')                             # T not converted: its pick checks the cube
        self.pick(c, 'M.cube')
        fits, before = c.lvb()['fits'], c.status()
        c.borrow_fail = lambda n: n >= P.CAPACITY                          # the asset area
        self.assertEqual(c.invoke(4, 50), 0)
        v = c.lvb()
        self.assertEqual((v['fits'], v['result']), (fits, 0x500))
        self.assertEqual(NS.borrows(c)[2], {})                             # the new set and the samples went back; the 100 % set too
        self.assertEqual(c.roots(), STOCK)                                 # (it no longer matches): the row is stock
        self.assertEqual(c.render([[.1, .2, .3]])[0], -18)                 # NO_MEMORY
        index = [e['filename'] for e in self.ldoc['luts']].index('T.cube')
        self.assertEqual(c.invoke(8, index), -18)
        after = c.status()
        self.assertEqual((after['asset'], after['color'], after['gamma']), (before['asset'], before['color'], before['gamma']))
        self.assertEqual(NS.borrows(c)[2], {})
        c.borrow_fail = None
        self.assertEqual(c.invoke(4, 50), 0)                               # the same strength: fitted now
        self.assertEqual(c.lvb()['fits'], fits + 1)
        out = NS.borrows(c)[2]
        self.assertEqual((len(out), self.sets(out)), (1, list(out)))
        self.assertEqual(NS.dangling(c, self.kept(c)), [])

    def test_dng_makernote_sees_stock_roots_while_ours_are_in(self):
        c = self.cam()
        H = c.HOLDER; c.put(H, ROOT)
        stock_slot = c.gettone(H, OFF, 0)
        self.assertEqual(c.arm(c.stub_at(S124)), ROOT)              # not installed: the real root
        self.pick(c, 'M.cube')
        self.assertNotEqual(c.gettone(H, OFF, 0), stock_slot)      # the ISP's answer is ours now
        r124 = c.arm(c.stub_at(S124))
        self.assertNotEqual(r124, ROOT)
        self.assertEqual((c.w(r124 + 8), c.w(r124 + 12)), STOCK[P08])
        before = c.w(c.CACHE_MODE)
        self.assertEqual(c.arm(c.stub_at(S12D), H, OFF, 0), stock_slot)
        self.assertEqual(c.w(c.CACHE_MODE), before)                # FUN_c02cf490's cache untouched
        for mode in (0x00, 0x01, 0x23):                            # other modes: the firmware's own answer
            c.put(c.CACHE_MODE, 0xFFFFFFFF)
            self.assertEqual(c.arm(c.stub_at(S12D), H, mode, 0), c.gettone(H, mode, 0), mode)
        self.unpick(c)
        self.assertEqual(c.arm(c.stub_at(S124)), ROOT)
        v = c.lvb()
        self.assertGreaterEqual(v['calls124'], 3); self.assertGreaterEqual(v['calls12d'], 4)

    def test_makernote_0x34_sees_the_stock_matrix_in_the_live_block(self):
        """Camera 2026-11-04 (validation/20261104-lvb-sup-01): 0x34 carried the LUT's matrix."""
        c = self.cam()
        obj = U.U.F6.FAKE + 0xF000
        self.assertEqual(c.arm(c.stub_at(S34), obj, 0), obj + 0x1C)          # not installed: the real block
        self.pick(c, 'M.cube')
        mat = [x & 0x7FF for x in c.lvb()['mat']]
        words = [0x11111111] + mat + mat + list(range(100, 100 + 0x3D - 19))     # as the camera held it
        c.mu.mem_write(obj + 0x1C, struct.pack('<61I', *words))
        got = c.arm(c.stub_at(S34), obj, 0)
        self.assertNotEqual(got, obj + 0x1C)
        out = list(struct.unpack('<61I', bytes(c.mu.mem_read(got, 244))))
        ident = [512, 0, 0, 512, 0, 0, 512, 0, 0]
        self.assertEqual(out, [0x11111111] + ident + ident + words[19:])
        self.assertEqual(struct.unpack('<61I', bytes(c.mu.mem_read(obj + 0x1C, 244))), tuple(words))   # untouched
        self.unpick(c)
        self.assertEqual(c.arm(c.stub_at(S34), obj, 0), obj + 0x1C)


    def test_power_off_puts_everything_back_and_clears_the_pq_caches(self):
        """Camera 2026-11-04: a warm restart with a LUT row on froze (validation/20261104-lvb-sup-01)."""
        c = self.cam()
        self.pick(c, 'M.cube')
        self.assertEqual(c.lvb()['installed'], 1)
        c.put(0xC2F19D44, 0x1234); c.put(0xC2F19D48, 0x1234); c.put(c.CACHE_MODE, OFF)
        # since 2026-11-08 one object in both lists, COL-Share's (the root and the PQ caches, moved from LUT's
        # lvb_poweroff with the root words); LUT registers none (camera: the lists were full, lvb never ready)
        ours = [o for o, _ in c.registered if c.w(o + 4) & 1 == 0 and c.w(o + 12) & 1]
        self.assertEqual(len(ours), 2)
        self.assertEqual(len(set(ours)), 1)
        _api, state = c.lut()
        self.assertFalse(any(state <= o < state + 4096 for o in ours))   # not LUT's
        from unicorn import UC_HOOK_CODE
        import test_sup_native as SN
        for o in sorted(set(ours)):
            self.assertEqual(c.w(o), o - 8)
            at, sps = c.w(o + 12) & ~1, []
            SN.ORIGINAL_HOOK(c.mu, UC_HOOK_CODE, lambda mu, a, n, d: sps.append(mu.reg_read(U.N.T3.UC_ARM_REG_SP)),
                             None, at, at)
            sp4 = (U.N.T3.STACK - 0x1000) & ~7 | 4                     # sp = 4 (mod 8), as the firmware may
            c.call(c.w(c.w(o) + 12), r0=o, r1=4, sp=sp4)
            self.assertTrue(sps and all(sp % 8 == 0 for sp in sps), [hex(x) for x in sps])   # AAPCS at the C routine
        self.assertEqual(c.roots(), STOCK)
        self.assertEqual((c.w(0xC2F19D44), c.w(0xC2F19D48), c.w(c.CACHE_MODE)), (0xFFFFFFFF,) * 3)   # ctx1 too (11-05)
        for o in sorted(set(ours)):
            c.call(c.w(c.w(o) + 12), r0=o, r1=4)                         # the second list: harmless
        self.assertEqual(c.roots(), STOCK)
        self.assertEqual(c.invoke(4, 50), 0)                             # after power-off: no refit
        self.assertEqual((c.lvb()['installed'], c.roots()), (0, STOCK))

    def test_the_entry_clears_the_pq_caches(self):
        c = self.cam()
        self.assertEqual((c.w(0xC2F19D44), c.w(0xC2F19D48), c.w(c.CACHE_MODE)), (0xFFFFFFFF,) * 3)   # ctx1 too (11-05)


if __name__ == '__main__':
    unittest.main()


# ---------------------------------------------------------------- the joint-fit file (.JFT, jft.py) path
P28, P50 = ROOT + 0x28, ROOT + 0x50
STOCK28, STOCK50 = (0xC2F1AAE8, 35), (0xC0B3AB1C, 36)
S129, YGW, YG_SHADOW = 0xC02C55B4, 0xC010A160, 0x30212140


@unittest.skipIf(U.N.T4.Uc is None or not U.N.T3.IMAGE.exists() or not SEG1.exists(),
                 'requires Unicorn, firmware and seg1; skipped is unverified')
class JftNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LvbNativeTests.setUpClass.__func__(cls)
        import jft
        cls.jft = jft
        e = next(x for x in cls.ldoc['luts'] if x['filename'] == 'M.cube')
        sha = L.record_identity(e)                                         # the record's key (the file, by name)
        data, cls.stats = jft.convert(cls.cubes['M.cube'], 6, 1, 100, sha, 1)       # rec709 / gamma24, as the tags; matrix off (no author line, 11-05)
        cls.u = jft.unpack(data)
        cls.jpath = '\\' + jft.path_for(sha.hex()).replace('/', '\\')
        cls.jfiles = dict(cls.lfiles); cls.jfiles[cls.jpath] = data
        stale = bytearray(data); struct.pack_into('<I', stale, 32, 50)                 # another strength in the key
        cls.stale = dict(cls.lfiles); cls.stale[cls.jpath] = bytes(stale)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    cam_of = lambda self, files: Camera(files, self.ar)
    pick = LvbNativeTests.pick
    setter = CN.ClistNativeTests.setter

    def setUp(self):
        Camera.lvb_fw = []

    def cursor_to_m(self, c):
        """M picked in the COLOR menu (open, the row, close: on_pick -> its set from the file; Bei 11-10: a row's
        set is made when it is picked, not ahead)."""
        rows = [e['filename'] for e in self.ldoc['luts'] if e['enabled']]
        c.run(c.w(0xC0D119FC), r0=0)
        CN.ClistNativeTests.pick_row(self, c, 16 + rows.index('M.cube'))
        c.run(c.w(0xC0D11A00), r0=0)

    def lvb_extra(self, c):
        _api, state = c.lut()
        blob = bytes(c.mu.mem_read(state, 4096))
        at = next(i for i in range(0, 4096, 4) if struct.unpack_from('<I', blob, i)[0] == MAGIC)
        w = struct.unpack_from('<64I', blob, at)
        # magic..mat (23), calls34, poffs, ctx 4 x 4, poff 4 -> jfts, ygam_posts, why[4]
        return dict(jfts=w[23 + 2 + 16 + 4], ygam_posts=w[23 + 2 + 16 + 5], why=list(w[23 + 2 + 16 + 6:23 + 2 + 16 + 10]))

    def off_record(self, c, holder, rec, n, mode=OFF):
        ptr, cnt = c.w(holder), c.w(holder + 4)
        raw = bytes(c.mu.mem_read(ptr, cnt * rec))
        i = [struct.unpack_from('<I', raw, k * rec)[0] for k in range(cnt)].index(mode)
        return ptr, raw[i * rec + 4:i * rec + 4 + n]

    def test_a_converted_row_puts_the_files_tables_on_the_isp(self):
        c = self.cam_of(self.jfiles)
        self.assertEqual(self.lvb_extra(c)['jfts'], 0)                       # nothing picked: no set made
        self.assertEqual((c.w(P28), c.w(P28 + 4)), STOCK28)                  # still stock until the row shows
        self.cursor_to_m(c)
        self.assertEqual(self.lvb_extra(c)['jfts'], 1)                       # picked: M's set from the file
        hw = self.u['hw']
        ptr, rec = self.off_record(c, P28, 0x14, 14)
        self.assertNotEqual(ptr, STOCK28[0])
        self.assertEqual(list(struct.unpack('<4hHHh', rec)), hw['ycmat'])
        ptr, rec = self.off_record(c, P50, 0x124, 288)
        self.assertNotEqual(ptr, STOCK50[0])
        self.assertEqual(list(struct.unpack('<72H', rec[144:])), [v for p in hw['ceq'] for v in p])
        self.assertEqual(list(struct.unpack('<72H', rec[:144])),                # ORG untouched
                         list(struct.unpack('<72H', bytes(c.mu.mem_read(STOCK50[0] + [struct.unpack_from('<I', bytes(c.mu.mem_read(STOCK50[0] + k * 0x124, 4)))[0] for k in range(36)].index(OFF) * 0x124 + 4, 144)))))
        self.assertEqual(list(c.entry(c.w(P08), c.w(P08 + 4))), hw['m2'])          # set 2: the chroma
        self.assertEqual(list(c.entry(c.w(P10), c.w(P10 + 4))), hw['m1'])          # set 1: the luma (JFIT v5)
        tabs = c.tone_tables()
        self.assertEqual(len(tabs), 3)
        for k in range(3):
            self.assertTrue((c.tone_at(tabs[k]) == hw['tone'][k]).all(), k)
        # back to a stock mode: everything stock at once
        CN.ClistNativeTests.pick_row(self, c, 6, site='MJ')
        self.assertEqual((c.w(P28), c.w(P28 + 4)), STOCK28)
        self.assertEqual((c.w(P50), c.w(P50 + 4)), STOCK50)

    def test_makernote_0x129_sees_the_stock_root(self):
        c = self.cam_of(self.jfiles)
        self.cursor_to_m(c)
        got = c.arm(c.stub_at(S129))
        self.assertNotEqual(got, ROOT)
        self.assertEqual((c.w(got + 0x28), c.w(got + 0x2C)), STOCK28)
        self.assertEqual((c.w(got + 0x08), c.w(got + 0x0C)), STOCK[P08])
        self.assertEqual((c.w(got + 0x50), c.w(got + 0x54)), STOCK50)
        CN.ClistNativeTests.pick_row(self, c, 6, site='MJ')
        self.assertEqual(c.arm(c.stub_at(S129)), ROOT)                      # stock row: the real root

    def ygam_call(self, c, ctx):
        try:
            c.mu.mem_map(0x30200000, 0x100000)
        except Exception:
            pass
        buf = U.U.F6.FAKE + 0xA000
        c.mu.mem_write(buf, bytes(0x544))
        c.call(YGW, r0=buf, r1=ctx, thumb=True)
        base = c.w(0xC07D4360 + 4 * ctx)
        return list(struct.unpack('<18I', bytes(c.mu.mem_read((base + YG_SHADOW) & 0xFFFFFFFF, 72))))

    def test_ygam_after_the_stock_write_on_ctx0_and_ctx1(self):
        """ctx 0 (LV) and ctx 1 (stills: 11-05 JPEGs came out red without it) take the file's YGAM."""
        c = self.cam_of(self.jfiles)
        w = c.w(YGW)
        self.assertTrue((w & 0xF800) == 0xF000 and (w >> 16) & 0xD000 == 0x9000, hex(w))   # the entry is a B.W now
        stock0 = self.ygam_call(c, 0)                                          # stock row: the firmware's own words
        self.assertNotEqual(stock0, self.u['hw']['ygam'])
        self.cursor_to_m(c)
        self.assertEqual(self.ygam_call(c, 0), self.u['hw']['ygam'])
        self.assertEqual(self.ygam_call(c, 1), self.u['hw']['ygam'])          # stills context too (11-05)
        base0 = (c.w(0xC07D4360) + YG_SHADOW) & 0xFFFFFFFF
        c.mu.mem_write(base0, struct.pack('<18I', *([0x5A5A5A5A] * 18)))
        self.ygam_call(c, 1)                                                  # a ctx 1 write must not touch ctx 0
        self.assertEqual(list(struct.unpack('<18I', bytes(c.mu.mem_read(base0, 72)))), [0x5A5A5A5A] * 18)
        self.assertGreaterEqual(self.lvb_extra(c)['ygam_posts'], 1)
        CN.ClistNativeTests.pick_row(self, c, 6, site='MJ')
        self.assertEqual(self.ygam_call(c, 0), stock0)

    def test_a_stale_file_falls_back_to_the_fit(self):
        c = self.cam_of(self.stale)
        self.assertEqual(self.lvb_extra(c)['jfts'], 0)
        self.cursor_to_m(c)
        self.assertEqual((c.w(P28), c.w(P28 + 4)), STOCK28)                  # the fit's set: YCMAT / CEQ stock
        self.assertNotEqual(c.w(P08), STOCK[P08][0])                         # but its matrix and tones are in

    def with_m1(self, m1):
        """M's file with its set-1 table replaced (and its checksums)"""
        b = bytearray(self.jfiles[self.jpath])
        struct.pack_into('<9h', b, 64 + 12544, *m1)
        struct.pack_into('<I', b, 56, self.jft.fnv(bytes(b[64:64 + self.jft.PAYLOAD])))
        u = self.jft.unpack(bytes(b[:64 + self.jft.PAYLOAD]))
        return self.jft.pack(u['key'], u['hw'], u['stats'], self.jft.read_chart(self.jfiles[self.jpath]))

    def test_set_1_and_set_2_come_from_the_file_apart(self):
        """JFIT v5 (2026-11-11): root+0x10 (set 1, the luma) gets the file's m1, root+0x08 (set 2) its m2, each in its own
        OFF record; MakerNote 0x34's copy shows both as the stock identity."""
        m2 = self.u['hw']['m2']
        m1 = [m2[0] + 37, m2[1] - 11, m2[2] + 5, m2[3] - 21, m2[4] + 9, m2[5], m2[6] + 13, m2[7] - 4, m2[8] + 2]
        c = self.cam_of(dict(self.jfiles, **{self.jpath: self.with_m1(m1)}))
        self.cursor_to_m(c)
        self.assertEqual(self.lvb_extra(c)['jfts'], 1)
        self.assertEqual(list(c.entry(c.w(P10), c.w(P10 + 4))), m1)
        self.assertEqual(list(c.entry(c.w(P08), c.w(P08 + 4))), m2)
        self.assertNotEqual(c.w(P10), c.w(P08))
        obj = U.U.F6.FAKE + 0xF000
        words = [0x11111111] + [x & 0x7FF for x in m1] + [x & 0x7FF for x in m2] + list(range(100, 100 + 0x3D - 19))
        c.mu.mem_write(obj + 0x1C, struct.pack('<61I', *words))
        out = list(struct.unpack('<61I', bytes(c.mu.mem_read(c.arm(c.stub_at(S34), obj, 0), 244))))
        ident = [512, 0, 0, 512, 0, 0, 512, 0, 0]
        self.assertEqual(out, [0x11111111] + ident + ident + words[19:])
        CN.ClistNativeTests.pick_row(self, c, 6, site='MJ')                  # a stock mode: both stock again
        self.assertEqual((c.w(P10), c.w(P08)), (STOCK[P10][0], STOCK[P08][0]))

    def test_0x34_finds_the_sets_the_hardware_holds_divided_by_2_to_the_shift(self):
        """Camera 2026-11-11 (validation/20261111-untie-live): a v5 Fuji 3513 (shift 1) -- records 441 / 364, the live
        block 220 / 182 (toward zero: -109 -> -54); the exact-match scrub missed them, 0x34 carried the LUT."""
        m2 = self.u['hw']['m2']
        m1 = [m2[0] + 37, m2[1] - 11, m2[2] + 5, m2[3] - 21, m2[4] + 9, m2[5], m2[6] + 13, m2[7] - 4, m2[8] + 2]
        u = self.jft.unpack(self.with_m1(m1)[:64 + self.jft.PAYLOAD])
        hw = dict(u['hw'], shift=1)
        data = self.jft.pack(u['key'], hw, u['stats'], self.jft.read_chart(self.jfiles[self.jpath]))
        c = self.cam_of(dict(self.jfiles, **{self.jpath: data}))
        self.cursor_to_m(c)
        self.assertEqual(self.lvb_extra(c)['jfts'], 1)
        half = lambda m: [(-((-v) >> 1) if v < 0 else v >> 1) & 0x7FF for v in m]
        obj = U.U.F6.FAKE + 0xF000
        ident = [512, 0, 0, 512, 0, 0, 512, 0, 0]
        for a, b in ((half(m1), half(m2)), (m1, m2)):
            words = [0x11111111] + [x & 0x7FF for x in a] + [x & 0x7FF for x in b] + list(range(100, 100 + 0x3D - 19))
            c.mu.mem_write(obj + 0x1C, struct.pack('<61I', *words))
            out = list(struct.unpack('<61I', bytes(c.mu.mem_read(c.arm(c.stub_at(S34), obj, 0), 244))))
            self.assertEqual(out, [0x11111111] + ident + ident + words[19:])
        other = [0x11111111] + [x & 0x7FF for x in half([v + 9 for v in m2])] + [0] * (0x3D - 10)   # not ours: kept
        c.mu.mem_write(obj + 0x1C, struct.pack('<61I', *other))
        out = list(struct.unpack('<61I', bytes(c.mu.mem_read(c.arm(c.stub_at(S34), obj, 0), 244))))
        self.assertEqual(out, other)

    def test_an_older_jfit_file_falls_back_to_the_fit(self):
        """JFIT_VERSION 7 (2026-11-11, the CKNEE slope / 16): a file an older fit made (+40 = 1 .. 6) is stale -- not read
        (why 4); a v4-sized one (no m1) or a v5-sized one (no CKNEE block) is refused by its size too (why 2)."""
        self.assertEqual((self.u['jfit_version'], self.jft.JFIT_VERSION), (7, 7))
        for n in (12544, 12564):
            short = bytearray(self.jfiles[self.jpath][:64 + n]); struct.pack_into('<I', short, 12, 64 + n)
            c = self.cam_of(dict(self.lfiles, **{self.jpath: bytes(short)}))
            self.cursor_to_m(c)
            self.assertEqual(self.lvb_extra(c)['jfts'], 0, n)
        for v in (1, 2, 3, 4, 5, 6):
            old = bytearray(self.jfiles[self.jpath]); struct.pack_into('<I', old, 40, v)
            c = self.cam_of(dict(self.lfiles, **{self.jpath: bytes(old)}))
            self.cursor_to_m(c)
            self.assertEqual(self.lvb_extra(c)['jfts'], 0, v)                # (the same bytes with +40 = 5: 1, above)
            lc = c.lut_cols()                                                  # stale = not converted: M is no row (11-10:
            self.assertEqual((lc['n'], lc['map'][0]), (1, 1), v)              # only rows' files are read, at their pick)

    def test_power_off_puts_the_new_roots_back(self):
        c = self.cam_of(self.jfiles)
        self.cursor_to_m(c)
        ours = [o for o, _ in c.registered if c.w(o + 4) & 1 == 0 and c.w(o + 12) & 1]
        for o in sorted(set(ours)):                                      # LUT's and COL-Share's
            c.call(c.w(c.w(o) + 12), r0=o, r1=4)
        self.assertEqual((c.w(P28), c.w(P28 + 4)), STOCK28)
        self.assertEqual((c.w(P50), c.w(P50 + 4)), STOCK50)
        before = self.lvb_extra(c)['ygam_posts']
        self.ygam_call(c, 0)
        self.assertEqual(self.lvb_extra(c)['ygam_posts'], before)             # the hook is inert after power-off


# ---------------------------------------------------------------- JFIT v6 (2026-11-11): the CKNEE through the PQ tables
KN_PTR = (0xC0B38B84, 0xC0B3F094, 0xC0B3F8F4)                  # Acq, Monit, Movie {table, count}
KN_STOCK = (0xC0B39078, 0xC3424E48, 0xC34251F0)
KN_DESC = (0xC0B39B04, 0xC0B3F6C0, 0xC0B3FEF8)                  # desc 0x1F +4 en, +5 up (+6, +7: 0)
KN_MAGIC = 0x31454E4B
KNEE_CODES = [157, 14, 30, 21, 227, 9, 400, 0]                 # knee, slope for +Cb, -Cb, +Cr, -Cr


@unittest.skipIf(U.N.T4.Uc is None or not U.N.T3.IMAGE.exists() or not SEG1.exists(),
                 'requires Unicorn, firmware and seg1; skipped is unverified')
class KneeNativeTests(unittest.TestCase):
    """research/imaging-hw/isp-colour-blocks-20260927/blocks-20261104/cknee-write-point.md §4.1 (candidate A): a v6 .JFT's
    CKNEE goes to the ISP through the three PQ parameter objects' table {pointer, count} and desc 0x1F's en / up -- no
    hook.  On: our record (resident) -> the pointers -> en, up.  Off: en 0 first (up stays 1: the periodic post writes
    the stock knee), the stock pointers and up 0 only at a later call, LVB_KN_HOLD (2 s) on.  Power-off: the loader's
    journal, en before the pointers.  Never en 1 on the stock (zero) record."""

    @classmethod
    def setUpClass(cls):
        JftNativeTests.setUpClass.__func__(cls)
        u = cls.jft.unpack(cls.jfiles[cls.jpath])
        cls.knee = cls.repack(u, KNEE_CODES)
        cls.plain = cls.repack(u, None)

    @classmethod
    def repack(cls, u, codes):
        hw = dict(u['hw'], knee=codes)
        return cls.jft.pack(u['key'], hw, u['stats'], u['chart'])

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    cam_of = JftNativeTests.cam_of
    cursor_to_m = JftNativeTests.cursor_to_m
    pick = LvbNativeTests.pick
    unpick = LvbNativeTests.unpick
    setter = CN.ClistNativeTests.setter

    def setUp(self):
        Camera.lvb_fw = []

    def cam(self, data):
        return self.cam_of(dict(self.jfiles, **{self.jpath: data}))

    def words(self, c):
        """the nine: three {table, count}, three desc words (en | up << 8 | ...)"""
        return [(c.w(a), c.w(a + 4)) for a in KN_PTR], [c.w(a) for a in KN_DESC]

    STOCK9 = ([(a, 1) for a in KN_STOCK], [0, 0, 0])

    def kn(self, c):
        """lvb_mem.kn (lvb.c), by its magic in the lvb region"""
        block, n = LvbNativeTests.kept(self, c)[0]
        raw = bytes(c.mu.mem_read(block, n))
        at = next(i for i in range(0, n, 4) if struct.unpack_from('<I', raw, i)[0] == KN_MAGIC)
        w = struct.unpack_from('<18I', raw, at)
        return dict(claimed=w[1], on=w[2], pend=w[3], buf=w[4], rec=[w[6:10], w[10:14]], enables=w[14], switches=w[15],
                    offs=w[16], restores=w[17], at=block + at)

    def watch(self, c):
        """every write to the nine words and lvb's region, in order: (address, size)"""
        from unicorn import UC_HOOK_MEM_WRITE
        log = []
        block, n = LvbNativeTests.kept(self, c)[0]
        h = [c.mu.hook_add(UC_HOOK_MEM_WRITE, lambda mu, acc, a, sz, v, d: log.append((a, sz, v)), None, lo, hi)
             for lo, hi in ((0xC0B38B80, 0xC0B3FF00), (block, block + n))]
        return log, lambda: [c.mu.hook_del(x) for x in h]

    @staticmethod
    def first(log, addrs):
        return min((i for i, (a, sz, _v) in enumerate(log) for b, m in addrs if b <= a < b + m), default=None)

    @staticmethod
    def last(log, addrs):
        return max((i for i, (a, sz, _v) in enumerate(log) for b, m in addrs if b <= a < b + m), default=None)

    def test_a_knee_file_points_the_three_tables_at_our_record_then_turns_en_up_on(self):
        c = self.cam(self.knee)
        self.assertEqual(self.words(c), self.STOCK9)                          # nothing until the row shows
        self.assertEqual(self.kn(c)['claimed'], 1)
        log, done = self.watch(c)
        self.cursor_to_m(c)
        done()
        ptrs, desc = self.words(c)
        rec = ptrs[0][0]
        self.assertEqual(ptrs, [(rec, 1)] * 3)                                 # all three classes: JPG, STILL LV, CINE LV / MOV
        want = self.jft.knee_record(self.jft.unpack(self.knee)['hw'])
        self.assertEqual(bytes(c.mu.mem_read(rec, 16)), want)
        self.assertEqual(want[:4], b'\0' * 4)                                  # thr 0
        self.assertEqual(struct.unpack('<2H2B2H2B', want[4:]), (157, 30, 14, 21, 227, 400, 9, 0))   # A, C, B, D halves
        self.assertEqual(desc, [0x0001, 0x0101, 0x0101])                       # en 1; up 1 Monit / Movie, Acq's 0
        k = self.kn(c)
        self.assertEqual((k['on'], k['enables']), (1, 1))
        self.assertTrue(k['at'] <= rec < k['at'] + 72)                         # resident (lvb_mem), not in a borrowed set
        for q, m in NS.borrows(c)[2].items():
            self.assertFalse(q <= rec < q + m)
        # the order: the record, then the pointers, then en / up
        r_last = self.last(log, [(rec, 16)])
        p_first, p_last = self.first(log, [(a, 8) for a in KN_PTR]), self.last(log, [(a, 8) for a in KN_PTR])
        e_first = self.first(log, [(a, 2) for a in KN_DESC])
        self.assertIsNotNone(r_last); self.assertIsNotNone(e_first)
        self.assertLess(r_last, p_first); self.assertLess(p_last, e_first)
        self.assertFalse([x for x in log if any(a + 2 <= x[0] < a + 4 for a in KN_DESC)])   # +6 / +7 never written

    def test_the_saved_knee_row_is_on_from_the_entry(self):
        """a saved active row with a knee file (COLOR on the LUT row): lc_attached -> lvb_refresh puts the knee on with
        the roots -- no menu, no cursor"""
        doc = L.configure(self.ldoc, 'M.cube', active=True)
        files = dict(self.jfiles, **{self.jpath: self.knee})
        files[LN.BIN], _ = P.build_sup(LN.MUTANT_SOURCE or P.SOURCE, collection=doc)
        c = Camera.__new__(Camera); c.color_setting = 0xC
        Camera.__init__(c, files, self.ar); c.lvb_fw = []
        self.assertEqual(c.lvb()['installed'], 1)
        ptrs, desc = self.words(c)
        self.assertEqual(desc, [0x0001, 0x0101, 0x0101])
        self.assertEqual(bytes(c.mu.mem_read(ptrs[0][0], 16)), self.jft.knee_record(self.jft.unpack(self.knee)['hw']))

    def test_off_en_first_then_after_the_hold_the_stock_tables_and_up(self):
        c = self.cam(self.knee)
        self.cursor_to_m(c)
        rec = self.words(c)[0][0][0]
        log, done = self.watch(c)
        self.unpick(c)                                                         # a stock mode: the menu's close
        done()
        ptrs, desc = self.words(c)
        self.assertEqual(ptrs, [(rec, 1)] * 3)                                 # the pointers stay on our record ...
        self.assertEqual(desc, [0x0000, 0x0100, 0x0100])                       # ... en 0; up still 1 (the stock knee via
        self.assertFalse([x for x in log if any(a <= x[0] < a + 8 for a in KN_PTR)])   # the periodic post)
        self.assertEqual((self.kn(c)['on'], self.kn(c)['pend']), (0, 1))
        self.assertEqual(bytes(c.mu.mem_read(rec, 16)), self.jft.knee_record(self.jft.unpack(self.knee)['hw']))
        c.invoke(8, 0xFFFFFFFF)                                                # another call at once: still held
        self.assertEqual(self.words(c)[1], [0x0000, 0x0100, 0x0100])
        c.ms = getattr(c, 'ms', 0) + 2500                                     # LVB_KN_HOLD later
        log, done = self.watch(c)
        c.invoke(8, 0xFFFFFFFF)
        done()
        self.assertEqual(self.words(c), self.STOCK9)
        self.assertEqual((self.kn(c)['pend'], self.kn(c)['restores']), (0, 1))
        self.assertLess(self.last(log, [(a, 8) for a in KN_PTR]), self.first(log, [(a + 1, 1) for a in KN_DESC]))   # pointers, then up

    def test_power_off_puts_the_nine_back_en_before_the_pointers(self):
        c = self.cam(self.knee)
        self.cursor_to_m(c)
        self.assertNotEqual(self.words(c), self.STOCK9)
        log, done = self.watch(c)
        for o in [o for o, _ in c.registered]:                                 # COL-Share's routine and the loader's journal
            c.call(c.w(c.w(o) + 12), r0=o, r1=4)
        done()
        self.assertEqual(self.words(c), self.STOCK9)
        self.assertLess(self.first(log, [(a, 4) for a in KN_DESC]), self.first(log, [(a, 8) for a in KN_PTR]))
        c.invoke(4, 50); c.ms = getattr(c, 'ms', 0) + 5000; c.invoke(8, 0xFFFFFFFF)   # late calls: nothing comes back
        self.assertEqual(self.words(c), self.STOCK9)

    def test_a_file_without_a_knee_never_touches_them(self):
        c = self.cam(self.plain)
        self.assertIsNone(self.jft.unpack(self.plain)['hw']['knee'])
        log, done = self.watch(c)
        self.cursor_to_m(c)
        self.unpick(c)
        self.cursor_to_m(c)
        done()
        self.assertEqual(self.words(c), self.STOCK9)
        self.assertFalse([x for x in log if any(a <= x[0] < a + 8 for a in KN_PTR + KN_DESC)])
        self.assertEqual(self.lvb_extra(c)['jfts'], 2)                          # the file was used (twice), its other tables in
        self.assertNotEqual(c.w(P28), STOCK28[0])
        k = self.kn(c)
        self.assertEqual((k['on'], k['enables']), (0, 0))

    lvb_extra = JftNativeTests.lvb_extra

    def test_the_cursor_shows_each_rows_knee_at_once(self):
        """menu open, the COLOR cursor (COL-Share's v3 preview, lvb_preview): M on -- its knee; a stock mode -- en 0; M
        again -- on with the same record (no new one); closed on the stock mode -- off, the hold, then stock."""
        c = self.cam(self.knee)
        c.run(c.w(0xC0D119FC), r0=0)                                           # the COLOR menu opens
        CN.ClistNativeTests.pick_row(self, c, 16)
        ptrs, desc = self.words(c)
        self.assertEqual(desc, [0x0001, 0x0101, 0x0101])
        rec = ptrs[0][0]
        CN.ClistNativeTests.pick_row(self, c, 6)
        self.assertEqual(self.words(c)[1], [0x0000, 0x0100, 0x0100])
        CN.ClistNativeTests.pick_row(self, c, 16)
        self.assertEqual(self.words(c), ([(rec, 1)] * 3, [0x0001, 0x0101, 0x0101]))
        self.assertEqual((self.kn(c)['switches'], self.kn(c)['enables']), (1, 2))
        CN.ClistNativeTests.pick_row(self, c, 6)
        c.run(c.w(0xC0D11A00), r0=0)                                           # closed on the stock mode
        self.assertEqual(self.words(c)[1], [0x0000, 0x0100, 0x0100])
        c.ms = getattr(c, 'ms', 0) + 2500
        c.invoke(8, 0xFFFFFFFF)
        self.assertEqual(self.words(c), self.STOCK9)

    def test_a_second_knee_goes_into_the_other_record(self):
        """two rows with a knee each, the cursor between them while on: the new record is written into the one the ISP
        is not reading, then the pointers move, en stays 1"""
        e = next(x for x in self.ldoc['luts'] if x['filename'] == 'T.cube')
        sha = L.record_identity(e)
        u = self.jft.unpack(self.knee)
        alt = [100, 19, 100, 19, 100, 19, 100, 19]
        tfile = self.jft.pack((sha, *u['key'][1:]), dict(u['hw'], knee=alt), u['stats'], u['chart'])
        tpath = '\\' + self.jft.path_for(sha.hex()).replace('/', '\\')
        c = self.cam_of(dict(self.jfiles, **{self.jpath: self.knee, tpath: tfile}))
        self.assertEqual(c.lut_cols()['n'], 2)
        c.run(c.w(0xC0D119FC), r0=0)
        CN.ClistNativeTests.pick_row(self, c, 16); a = self.words(c)
        log, done = self.watch(c)
        CN.ClistNativeTests.pick_row(self, c, 17); b = self.words(c)
        done()
        recs = {bytes(c.mu.mem_read(x[0][0][0], 16)) for x in (a, b)}
        self.assertEqual(recs, {self.jft.knee_record(u['hw']), self.jft.knee_record(dict(knee=alt))})
        self.assertNotEqual(a[0][0][0], b[0][0][0])
        self.assertEqual((a[1], b[1]), ([0x0001, 0x0101, 0x0101],) * 2)
        self.assertFalse([x for x in log if any(d <= x[0] < d + 4 for d in KN_DESC)])   # en / up never dropped
        self.assertLess(self.last(log, [(b[0][0][0], 16)]), self.first(log, [(p_, 8) for p_ in KN_PTR]))
        self.assertFalse([x for x in log if a[0][0][0] <= x[0] < a[0][0][0] + 16])       # the one being read: untouched
        CN.ClistNativeTests.pick_row(self, c, 16)
        self.assertEqual(self.words(c), a)                                     # back: the first record again
        c.run(c.w(0xC0D11A00), r0=0)
