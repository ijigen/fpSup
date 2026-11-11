"""native/dng.c under unicorn: the six DNG-writer calls, the cube picked in the
COLOR list deciding which stock set the files carry (user 2026-11-03).

The three stock writers are replaced by Python at their entries: each records
the color-mode word the writer context holds when it is called and the two OFF
base tables, then returns.  The calls are made through the patched `bl` sites'
veneers, as the writers make them.

    cd fpSup/lut && python3 -B -m unittest test_dng_native
"""
import struct
import unittest

import library as L
import build_sup as P
import test_library_native as LN
import test_clist_native as CN
import test_sup_ui as U
from test_lut import make_cube

CM, HSM, CURVE = 0xC02C4A50, 0xC02C4D40, 0xC02C4E80
SITES = {(0xC02C6920, CM), (0xC02C6940, HSM), (0xC02C6950, CURVE),
         (0xC02C7620, CM), (0xC02C7640, HSM), (0xC02C7650, CURVE)}
TAB_A, TAB_D65, TAB_LEN = 0xC096FD74, 0xC096FCE4, 72
CTX = U.U.F6.FAKE + 0xF000                # a fake writer context (p3): +0x118 = 1, +0x34 = the mode word
OFF = 0x24


class Camera(CN.Camera):
    def __init__(self, files, autorun):
        self.writes = []
        super().__init__(files, autorun)

    def _hook(self, mu, addr, size, data):
        if addr in (CM, HSM, CURVE):
            sel = self.w(self.r(U.N.T3.UC_ARM_REG_R2) + 0x118)
            word = self.w(self.r(U.N.T3.UC_ARM_REG_R2) + 0x30 + 4 * sel)
            tabs = bytes(mu.mem_read(TAB_A, TAB_LEN)) + bytes(mu.mem_read(TAB_D65, TAB_LEN))
            self.writes.append((addr, word, tabs))
            return self._ret(0)
        return super()._hook(mu, addr, size, data)

    def write_dng(self, site, mode=OFF):
        """One stock call at `site`, the writer context's mode word `mode`; -> the word after."""
        for o in range(0, 0x120, 4):
            self.put(CTX + o, 0)
        self.put(CTX + 0x118, 1)
        self.put(CTX + 0x34, mode)
        self.writes = []
        self.run(self.stub_at(site), r0=0x1111, r1=0x2222, r2=CTX)
        return self.w(CTX + 0x34)


@unittest.skipIf(U.N.T4.Uc is None or not U.N.T3.IMAGE.exists(), 'requires Unicorn and firmware; skipped is unverified')
class DngNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LN.LibraryNativeTests.setUpClass.__func__(cls)
        root = cls.root / 'dng'; root.mkdir()
        m2 = b'# FPSUP_COLOR_MATRIX2 0.5 -0.1 0 -0.4 1.25 0.2 -0.1 0.2 0.5\n'
        m1 = b'# FPSUP_COLOR_MATRIX1 0.6 -0.2 0.1 -0.3 1.5 0.25 -0.05 0.1 0.75\n'
        tags = b'# FPSUP_INPUT_COLOR_SPACE rec709\n# FPSUP_INPUT_GAMMA gamma24\n'
        cubes = [('S.cube', b'# FPSUP_COLOR_MATRIX standard\n', lambda r, g, b: (r, g, b)),   # no line = off (11-05)
                 ('O.cube', b'# FPSUP_COLOR_MATRIX off\n', lambda r, g, b: (g, b, r)),
                 ('C.cube', b'# FPSUP_COLOR_MATRIX custom\n' + m1 + m2, lambda r, g, b: (b, r, g))]
        paths = []
        for name, extra, fn in cubes:
            p = root / name; p.write_bytes(tags + extra + make_cube(2, fn=fn)); paths.append(p)
        doc = L.import_cubes(L.blank(), paths)
        for name, *_ in cubes:
            doc = L.configure(doc, name, enabled=True)
        cls.ddoc = doc
        cls.dfiles = LN.with_library(cls.files, doc)           # the folder: these cubes alone

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def cam(self):
        return Camera(self.dfiles, self.ar)

    setter = CN.ClistNativeTests.setter

    def pick(self, c, cube):
        """The COLOR list's row of `cube` (rows: the cubes on, in library order; GUI 16 = row 1)."""
        rows = [e['filename'] for e in self.ddoc['luts'] if e['enabled']]
        CN.ClistNativeTests.pick_row(self, c, 16 + rows.index(cube))
        self.assertEqual(c.clist()['active'], rows.index(cube) + 1)

    def test_every_writer_site_goes_through_a_veneer_to_its_own_function(self):
        c = self.cam()
        for site, target in SITES:
            v = c.stub_at(site)
            self.assertTrue(c.veneer_ok(v), hex(site))
            ctx = c.w(v + 8)
            self.assertEqual(c.w(ctx + 8), target)                   # dng_ctx.original

    def test_no_lut_row_writes_the_stock_set(self):
        c = self.cam()
        for site, target in SITES:
            for mode in (OFF, 0x01):                                # stock OFF, a stock mode
                self.assertEqual(c.write_dng(site, mode), mode)
                self.assertEqual([(a, w) for a, w, _t in c.writes], [(target, mode)])
                self.assertEqual(c.writes[0][2], self.stock_tables(c))

    def stock_tables(self, c):
        img = U.N.T3.IMAGE.read_bytes()
        return img[TAB_A - 0xC0000000:][:TAB_LEN] + img[TAB_D65 - 0xC0000000:][:TAB_LEN]

    def test_standard_writes_the_standard_set_off_the_off_set(self):
        c = self.cam()
        self.pick(c, 'S.cube')
        for site, target in SITES:
            self.assertEqual(c.write_dng(site), OFF)                 # the row's word, back after
            (a, w, t), = c.writes
            self.assertEqual(a, target); self.assertNotEqual(w, OFF)  # Standard: not 0x24
            self.assertEqual(t, self.stock_tables(c))
        self.pick(c, 'O.cube')
        for site, target in SITES:
            self.assertEqual(c.write_dng(site), OFF)
            self.assertEqual(c.writes[0][:2], (target, OFF))

    def test_custom_writes_the_off_set_with_the_authors_base_matrices(self):
        c = self.cam()
        self.pick(c, 'C.cube')
        _layers, cm = L.layer_fields(L.find(self.ddoc, 'C.cube'))
        want = b''.join(struct.pack('<d', v / 2 ** 20) for v in cm[0] + cm[1])
        for site, target in SITES:
            self.assertEqual(c.write_dng(site), OFF)
            (a, w, t), = c.writes
            self.assertEqual((a, w), (target, OFF))
            self.assertEqual(t, want if target == CM else self.stock_tables(c), hex(site))
            self.assertEqual(bytes(c.mu.mem_read(TAB_A, TAB_LEN)) + bytes(c.mu.mem_read(TAB_D65, TAB_LEN)),
                             self.stock_tables(c))                   # restored after the call

    def test_the_q20_to_double_conversion_is_exact(self):
        c = self.cam()
        self.pick(c, 'C.cube')
        _layers, cm = L.layer_fields(L.find(self.ddoc, 'C.cube'))
        c.write_dng(0xC02C6920)
        got = struct.unpack('<18d', c.writes[0][2])
        self.assertEqual(list(got), [v / 2 ** 20 for v in cm[0] + cm[1]])
        self.assertTrue(any(v < 0 for v in got) and any(abs(v) >= 1 for v in got))


if __name__ == '__main__':
    unittest.main()
