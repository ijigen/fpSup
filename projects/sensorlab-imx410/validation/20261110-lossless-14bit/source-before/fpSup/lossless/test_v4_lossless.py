#!/usr/bin/env python3
"""LOSS.BIN (build_v4_lossless.py) under the real Loader v4 core (unicorn).

    python3 -B -m unittest test_v4_lossless        (from fpSup/lossless)

The recording code is v3's, covered by test_v3_lossless.py and the native
tests; this checks what v4 changed: the header and cached execution, the ten
claims (no string site), the Lossless RAW row on the fpSup page driving the
value the REC decision reads, the saved record, power-off.
"""
import pathlib, struct, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'loader-v4')]
import build_v4_lossless as L4                           # noqa: E402
import build_card as C                                   # noqa: E402
import build_v4 as B                                     # noqa: E402
import test_v4 as T                                      # noqa: E402

STRING_SITES = C.SHARED_SITES
SITES = {a: s for a, (s, _) in C.SITES.items() if a not in STRING_SITES}
ENGINE = 0x300D0000
ROW = '<HHIIIIIII'                                        # struct sl_row (32 B)


class LosslessCamera(T.Camera):
    """v4's camera, with the IRQ routines lossless reaches at load."""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        for at, name in ((0xC000EC14, 'IRQ_OFF'), (0xC000EC24, 'IRQ_ON')):
            self.mu.mem_write(at, struct.pack('<I', 0xE12FFF1E))
            self.by_addr[at] = name


class LosslessV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory(prefix='fpl-v4-test-') as t:
            cls.sup, cls.facts = L4.sup_file(pathlib.Path(t))
        from armasm import symbols
        cls.sym = symbols(HERE / 'native' / 'card.S', cls.facts['defines'])

    def boot(self, *others, sup=None):
        cam = LosslessCamera(*T.card(*others, ('LOSS.BIN', sup or self.sup)))
        cam.boot()
        self.assertIsNone(cam.error)
        return cam

    def stock(self, cam, a):
        return struct.unpack_from('<I', cam.img, a - 0xC0000000)[0]

    def row(self, cam):
        self.assertEqual(cam.callsvc('page_count'), 1)
        p = cam.callsvc('page_row', 0)
        return struct.unpack(ROW, cam.mu.mem_read(p, 32))

    def fn(self, cam, f, *args):
        return cam.call(f & ~1, *args, thumb=bool(f & 1))[0]

    # ---- header and load -------------------------------------------------
    def test_header(self):
        h = struct.unpack_from('<12I', self.sup)
        self.assertEqual((h[0], h[1], h[2]), (B.SL4_MAGIC, 48, len(self.sup)))
        self.assertEqual(h[4], 48)                                         # entry: card.S `entry`
        self.assertEqual(h[8], B.SL_F_CACHED_OK)
        self.assertEqual(h[7], 5)                                          # page_add, file_is
        name = self.sup[h[11]:self.sup.index(b'\0', h[11])]
        self.assertEqual(name, b'Lossless')
        self.assertLessEqual(h[11] + 9, 48 + self.facts['state_off'])      # before the state

    def test_loads_cached_claims_ten_sites_and_the_engine(self):
        cam = self.boot()
        loaded = T.blocks(cam)
        self.assertIn('LOSS.BIN', loaded)
        at = loaded['LOSS.BIN']
        self.assertTrue(at >= 0xC0000000 and at % 64 == 0, hex(at))
        self.assertEqual(sorted(a for a, n, _ in cam.journal()), sorted(SITES))
        for a in STRING_SITES:                                             # the core's alone
            self.assertNotIn(a, [x for x, _, _ in cam.journal()])
        for a in SITES:                                                    # every site armed
            self.assertNotEqual(cam.w(a), SITES[a], hex(a))
        self.assertEqual(cam.tasks[-1] & 0xF0000000, 0xC0000000)           # the codec task, cached

    def test_power_off_puts_every_site_back(self):
        cam = self.boot()
        cam.power_off()
        for a, s in SITES.items():
            self.assertEqual(cam.w(a), s, hex(a))

    # ---- the row ---------------------------------------------------------
    def test_the_row_is_a_toggle_on_the_fpsup_page(self):
        cam = self.boot()
        kind, n, title, value, get, set_, choices, open_, arg = self.row(cam)
        self.assertEqual((kind, n, value, open_), (2, 2, 0, 0))            # SL_ROW_TOGGLE
        self.assertEqual(cam.cstr(title), 'Lossless')                      # user 2026-10-25 (was Lossless-CDNG)
        self.assertEqual([cam.cstr(cam.w(choices + 4 * i)) for i in range(2)], ['OFF', 'ON'])
        at = T.blocks(cam)['LOSS.BIN']
        self.assertTrue(at <= arg < at + struct.unpack_from('<I', self.sup, 12)[0])   # resident
        self.assertEqual(self.fn(cam, get, arg), 1)                        # built ON (user 2026-10-24)

    def test_the_row_sets_what_rec_reads(self):
        cam = self.boot()
        _, _, _, _, get, set_, _, _, arg = self.row(cam)
        menu = arg                                                         # struct fpl_menu
        self.assertEqual(self.fn(cam, set_, arg, 1), 0)
        self.assertEqual(self.fn(cam, get, arg), 1)
        self.assertEqual(cam.w(menu + 4), 1)                               # value
        self.assertEqual(cam.w(menu + 28), 1)                              # sets
        self.assertNotEqual(self.fn(cam, set_, arg, 2), 0)                 # not a choice
        self.assertEqual(self.fn(cam, get, arg), 1)
        self.assertEqual(self.fn(cam, set_, arg, 0), 0)
        self.assertEqual(self.fn(cam, get, arg), 0)

    def with_record(self, on, check=None):
        sup = bytearray(self.sup)
        at = 48 + self.sym['settings']
        magic = 0x54534C46
        chk = magic ^ 1 ^ on ^ 0xFFFFFFFF if check is None else check
        struct.pack_into('<4I', sup, at, magic, 1, on, chk)
        return bytes(sup)

    def test_the_record_is_built_on_at_48_plus_settings(self):
        # v4 installs ON (user 2026-10-24); v3 stays built OFF
        at = 48 + self.sym['settings']
        self.assertEqual(struct.unpack_from('<4I', self.sup, at),
                         (0x54534C46, 1, 1, 0x54534C46 ^ 1 ^ 1 ^ 0xFFFFFFFF))

    def test_a_saved_off_starts_the_row_off(self):
        cam = self.boot(sup=self.with_record(0))
        _, _, _, _, get, _, _, _, arg = self.row(cam)
        self.assertEqual(self.fn(cam, get, arg), 0)                        # the user's OFF wins

    def test_a_saved_on_starts_the_row_on(self):
        cam = self.boot(sup=self.with_record(1))
        _, _, _, _, get, _, _, _, arg = self.row(cam)
        self.assertEqual(self.fn(cam, get, arg), 1)

    def test_a_damaged_record_starts_off(self):
        cam = self.boot(sup=self.with_record(1, check=0x12345678))
        _, _, _, _, get, _, _, _, arg = self.row(cam)
        self.assertEqual(self.fn(cam, get, arg), 0)

    def test_the_fpsup_page_shows_the_row(self):
        import test_ui_v4 as U
        cam_cls = U.Cam

        class PageCamera(cam_cls):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                for at, name in ((0xC000EC14, 'IRQ_OFF'), (0xC000EC24, 'IRQ_ON')):
                    self.mu.mem_write(at, struct.pack('<I', 0xE12FFF1E))
                    self.by_addr[at] = name
        U.Cam = PageCamera
        try:
            cam = U.boot(('LOSS.BIN', self.with_record(1)))
        finally:
            U.Cam = cam_cls
        self.assertIsNone(cam.error)
        s = U.slot(cam, 0)
        # a TOGGLE's Off / On are the fpSup page's stock texts (localized), shown by FT_Tog / FT_TOn
        self.assertEqual((s['N'], U.shown(s), s['Tog'], s['Visible']), ('Lossless', 'On', 1, 1))


if __name__ == '__main__':
    unittest.main()
