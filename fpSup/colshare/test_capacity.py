"""COL-Share 12 列與 LUT 的容量(Bei 2026-11-10):真的 ARM、真的韌體映像(unicorn),COL-Share + LUT(+ RAW-View 0.4)。

    cd fpSup/colshare && python3 -B -m unittest test_capacity

- API v3:rows_max = 12、room(sup) = 12 − 其他客戶的列;
- 12 個 LUT = 12 列;CSV 與圖示複本只給存在的列、大小剛好,列不見了就還記憶體(c.freed)、表項 stock 字清 0;
- Manager:「開著」不能超過 room(標題 LUT (on/room)、List full);RAW-View 後到(先開 12 個 LUT 再啟用 RAW-View):
  照 library 順序前 11 個是列、最後一個標「No COLOR row: list full」;
- 11 個 LUT 列(RAW-View 在)每列都選得到,選到後 root 指向那個 cube 的 ISP 表(由它的 .JFT,每個 cube 一個記號矩陣);
  LUT 只借著「顯示中那一列」的一份 ISP set,別列的游標預覽是原廠;錄影中選:不讀檔、原廠,停錄後下一次關選單才載入;
- 常駐:COL-Share ≤ 64 KB;LUT 的常駐比改動前小(數字在 RESIDENT_BEFORE)。
不代表相機上的畫面(上機:README.md「12 列」)。
"""
import os
import struct
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT_DIR = HERE.parents[1]
sys.path[:0] = [str(HERE), str(HERE.parent / 'lut'), str(HERE.parent / 'loader-v4'),
                str(ROOT_DIR / 'projects/rawview/build')]
import build_colshare as CS          # noqa: E402
import colshare_ui as CU             # noqa: E402
import test_colshare as TC           # noqa: E402

CN, LN, NS, U = TC.CN, TC.LN, TC.NS, TC.U
L, P = LN.L, LN.P
LAY = CS.layout(CU.ROWS_PRODUCT)
LUT_ID, RAWV_ID = 0x3454554C, 0x56574152
ROOT = TC.ROOT
OFF = 0x24
SET_BYTES = 26016                    # sizeof(struct lvb_set) (lvb.c): the one ISP set LUT holds (JFIT v6: + the CKNEE's 32 B)
LUT_SOURCE = os.environ.get('LUT_MUTANT_SOURCE')   # mutate_capacity.py: a mutated lut4.c (its folder holds the rest)
# Resident bytes before this change (2026-11-10 snapshot projects/lut-sup/private/src-snapshot-20261110-0555):
# COL-Share 4 rows; LUT.BIN for test_colshare's library (A, B, Unknown).  Measured, see README.md.
RESIDENT_BEFORE = {'COLS': 33024, 'LUT': 723520}
N_CUBES = 13


def fnv(b):
    h = 2166136261
    for x in b:
        h = ((h ^ x) * 16777619) & 0xFFFFFFFF
    return h


def marker(i):
    """Cube i's matrix (table order, Q9): a plain identity but for two words that name it."""
    return [400 + i, 112 - i, 0, 512, 0, 0, 512, 0, 0]


SEG1 = ROOT_DIR / 'out/seg1_c2ef6e00.bin'                # RAM .data: the YCMAT table a .JFT's OFF record goes into


class Camera(TC.Camera):
    """test_colshare's camera; every .JFT it is asked for is a whole, valid one (header + tables), its matrix the
    record's marker(index): picking a row is a file read, never a fit."""
    def page_entries(self):
        super().page_entries()
        seg = SEG1.read_bytes()                               # test_lvb_native's: root+0x28's YCMAT as after boot
        ycm = 0xC2F1AAE8
        tab = bytearray(seg[ycm - 0xC2EF6E00:][:35 * 0x14])
        for k in range(35):
            struct.pack_into('<3h', tab, k * 0x14 + 4, 1224, 2403, 469)
        self.mu.mem_write(ycm, bytes(tab))

    def synth_jft(self, path):
        blob = self.files[LN.BIN]
        if getattr(self, '_lut_block', None) is None:
            heap = bytes(self.mu.mem_read(U.N.T4.HEAP, U.N.T4.HEAP_SIZE)); at = heap.find(blob[:48 + 56])
            self._lut_block = U.N.T4.HEAP + at if at >= 0 else 0
        if not self._lut_block:
            return
        lib = self._lut_block + struct.unpack_from('<I', blob, 48 + 28)[0]
        count = struct.unpack_from('<I', bytes(self.mu.mem_read(lib, 64)), 16)[0]
        for i in range(min(count, 32)):
            r = bytes(self.mu.mem_read(lib + 64 + 256 * i, 256))
            if '\\' + LN.jft.path_for(r[:32].hex()).replace('/', '\\') != path:
                continue
            _flags, color, gamma, amount = struct.unpack_from('<4I', r, 96); matrix = struct.unpack_from('<I', r, 128)[0]
            tone = b''.join(struct.pack('<2048H', *[min(8190, 4 * k + i) for k in range(2048)]) for _c in range(3))
            pay = struct.pack('<I9h2x', 0, *marker(i)) + tone + bytes(16) + bytes(144) + bytes(72) + struct.pack('<9h2x', *marker(i))
            pay += bytes(16)                                                        # JFIT v6: the CKNEE block, off
            assert len(pay) == 12580                                                # + m1 (set 1 = set 2 here)
            self.files[path] = struct.pack('<4I8s5I3I2I', 0x3154464A, 1, 64, 64 + 12580, r[:8], color, gamma, amount, matrix,
                                           7, 63, 63, 63, fnv(pay), 0) + pay   # JFIT v7 (11-11: v5's untied M1 + the CKNEE, slope /16)
            return

    # ---- COL-Share
    def cols(self, name):
        return self.w(self.stub_ctx() + LAY[name])

    def room(self, sup):
        api = self.api()
        fn = self.w(api + 36)
        return self.call(fn & ~1, r0=api, r1=sup, thumb=bool(fn & 1))[0]

    def files_of_cols(self):
        """struct cols .file[]: (entry, raw, buf, cap, len) for the 3 CSVs and 12 icons."""
        at = self.stub_ctx() + LAY['file']
        return [struct.unpack('<5I', bytes(self.mu.mem_read(at + 20 * k, 20))) for k in range(3 + CU.ROWS_PRODUCT)]

    def off_matrix(self):
        """root+0x08's table: its OFF entry (table order, Q9)."""
        t, n = self.w(ROOT + 8), self.w(ROOT + 12)
        for k in range(n):
            if self.w(t + 0x18 * k) == OFF:
                return list(struct.unpack('<9h', bytes(self.mu.mem_read(t + 0x18 * k + 4, 18))))

    def lut_over(self):
        lc = self.lut_cols()
        _api, state = self.lut()
        blob = bytes(self.mu.mem_read(state, 4096))
        at = next(i for i in range(0, 4096, 4) if struct.unpack_from('<I', blob, i)[0] == 0x3143434C)
        return struct.unpack_from('<I', blob, at + 12 + 4 * 12 + 4 * 12 + 4)[0], lc


def held_sets(c):
    """LUT's borrowed areas outstanding now that are ISP sets."""
    out = NS.borrows(c)[2]
    return [q for q, m in out.items() if m >= SET_BYTES and m < 64 * 1024]


@unittest.skipIf(U.N.T4.Uc is None or not TC.IMAGE.exists() or not SEG1.exists(),
                 'requires Unicorn, firmware and seg1; skipped is unverified')
class CapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LN.LibraryNativeTests.setUpClass.__func__(cls)            # A, B on (A active), Unknown not set up: test_colshare's
        cls.ui = CN.ClistNativeTests('test_install_patches_every_site_and_sync_fills_two_rows')
        tags = b'# FPSUP_INPUT_COLOR_SPACE rec709\n# FPSUP_INPUT_GAMMA gamma24\n'
        paths = []
        for i in range(N_CUBES):
            p = cls.root / f'C{i:02}.cube'
            p.write_bytes(tags + f'TITLE "C{i:02}"\n'.encode() + LN.make_cube(2, fn=lambda r, g, b, i=i: (r, g, b * (1 - i / 40))))
            paths.append(p)
        doc = L.import_cubes(L.blank(), paths)
        for i in range(12):
            doc = L.configure(doc, f'C{i:02}.cube', enabled=True, active=i == 0)
        cls.big_doc = doc
        cls.big = LN.with_library(cls.files, doc)
        if LUT_SOURCE:
            cls.big[LN.BIN], _f = P.build_sup(LUT_SOURCE, collection=doc)
            cls.files = dict(cls.files); cls.files[LN.BIN], _f = P.build_sup(LUT_SOURCE, collection=cls.doc)
        import build_v3_rawview as V
        sup, _facts, _rows = V.build(v4=True, name=b'RAW-View\0', cols=True)
        cls.rv_file = '\\fpSup\\' + V.COLS_FILE
        cls.big_raw = dict(cls.big); cls.big_raw[cls.rv_file] = sup

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def cam(self, files):
        c = Camera.__new__(Camera); c.residue = {0xC31B32BC + 0x12C: 0xC}        # COLOR (menu enum) is OFF
        Camera.__init__(c, files, self.ar)
        return c

    def lut_row_names(self, c):
        """The LUT names of the COLOR list's rows, in order (COL-Share's big labels)."""
        lc = c.lut_cols()
        _api, state = c.lut()
        blob = bytes(c.mu.mem_read(state, 4096))
        at = next(i for i in range(0, 4096, 4) if struct.unpack_from('<I', blob, i)[0] == 0x3143434C)
        n = struct.unpack_from('<I', blob, at + 8)[0]
        idx = struct.unpack_from(f'<{n}I', blob, at + 12)
        return [self.big_doc['luts'][i]['filename'] for i in idx], lc

    def pick_close(self, c, gui):
        c.run(c.w(TC.V25), r0=0)
        self.ui.pick_row(c, gui)
        c.run(c.w(TC.V26), r0=0)

    # ------------------------------------------------------------------ the API
    def test_v3_reports_rows_max_and_each_clients_room(self):
        c = self.cam(self.big)
        api = c.api()
        self.assertEqual((c.w(api + 4), c.w(api + 32)), (3, 12))
        self.assertEqual(c.cols('magic') if False else c.w(c.stub_ctx() + 4), 12)          # rows present: 12 LUTs
        self.assertEqual((c.room(LUT_ID), c.room(RAWV_ID)), (12, 0))
        c = self.cam(self.big_raw)
        self.assertEqual(c.w(c.stub_ctx() + 4), 12)
        self.assertEqual((c.room(LUT_ID), c.room(RAWV_ID)), (11, 1))
        c = self.cam(self.files)                                                       # A, B: 2 rows
        self.assertEqual((c.room(LUT_ID), c.room(0x12345678)), (12, 10))

    # ------------------------------------------------------------------ copies only for rows that exist
    def test_twelve_rows_get_twelve_icons_and_csvs_sized_to_them(self):
        c = self.cam(self.big)
        table = self.ui.redirect_table(c)
        for f, (_n, stock, _s) in enumerate(CU.CSV):
            copy, size = table[stock]
            self.assertEqual(bytes(c.mu.mem_read(copy, size)), CU.rows_csv(f, 12), CU.CSV[f][0])
        names, _lc = self.lut_row_names(c)
        self.assertEqual(names, [f'C{i:02}.cube' for i in range(12)])
        for j in range(12):
            copy, size = table[CU.DONORS[j][1]]
            self.assertEqual(bytes(c.mu.mem_read(copy, size)), self.ui.tile(names[j]), j)
        files = c.files_of_cols()
        self.assertTrue(all(raw and cap - 64 < ln <= cap for _e, raw, _b, cap, ln in files))   # sized to the content
        self.assertEqual(c.cols('heap'), sum(cap + 64 for _e, _r, _b, cap, _l in files))
        self.assertLessEqual(c.cols('heap'), 12 * (CU.ICON_CAP + 128) + 3 * 2048)   # LUT's tiles are ~12.8 KB each
        self.assertEqual(NS.borrows(c)[2].keys() - set(held_sets(c)), set(), 'LUT keeps no tile slot or .JFT buffer')

    def test_two_rows_have_two_icons_and_rows_that_go_free_theirs(self):
        c = self.cam(self.files)                                           # A, B on
        files = c.files_of_cols()
        self.assertEqual([bool(f[1]) for f in files], [True] * 5 + [False] * 10)
        table = self.ui.redirect_table(c)
        self.assertEqual({a for a in table if a} & {d[1] for d in CU.ALL_DONORS}, {CU.DONORS[0][1], CU.DONORS[1][1]})
        b_raw, b_entry = files[4][1], files[4][0]
        c.open_color(); c.choose('B.cube', 0)                               # B off: one row
        self.assertEqual(c.w(c.stub_ctx() + 4), 1)
        self.assertEqual(c.w(b_entry), 0, 'its entry no longer matches a file')
        self.assertIn(b_raw, c.freed)
        csv = [f[1] for f in c.files_of_cols()[:3]]
        c.choose('A.cube', 0)                                               # none: the stock files, nothing held
        self.assertEqual(c.w(c.stub_ctx() + 4), 0)
        self.assertTrue(all(r in c.freed for r in csv))
        self.assertEqual((c.cols('heap'), [f[1] for f in c.files_of_cols()]), (0, [0] * 15))
        self.assertEqual({a for a in self.ui.redirect_table(c) if a} & ({d[1] for d in CU.ALL_DONORS} | {s for _n, s, _z in CU.CSV}), set())
        c.choose('A.cube', 1)                                               # back: made again, the same entries reused
        self.assertEqual(c.w(c.stub_ctx() + 4), 1)
        self.assertEqual(bytes(c.mu.mem_read(*self.ui.redirect_table(c)[CU.CSV[0][1]])), CU.rows_csv(0, 1))

    def test_no_copy_is_made_while_recording(self):
        c = self.cam(self.files)
        before = (len(c.allocs), c.cols('heap'))
        NS.recording(c)
        api = c.api()
        c.call(c.w(api + 12) & ~1, r0=api, r1=LUT_ID, thumb=bool(c.w(api + 12) & 1))   # changed(): deferred
        self.assertEqual((len(c.allocs), c.cols('heap')), before)
        self.assertGreaterEqual(c.cols('sync_late'), 1)
        NS.recording(c, False)
        c.run(c.w(TC.V26), r0=0)                                            # the next close syncs
        self.assertEqual(c.cols('sync_late'), 1)

    # ------------------------------------------------------------------ the manager's cap
    def test_the_manager_refuses_more_than_room(self):
        c = self.cam(self.big)
        c.open_color()
        self.assertEqual(c.vars['LC_Header'][1], 'LUT (12/12)')
        writes = c.bin_writes
        c.choose('C12.cube', 1)
        self.assertEqual(c.vars['LC_OK'][1], 'List full: disable one')
        self.assertEqual(c.bin_writes, writes)
        self.assertFalse(L.recover(self.big_doc, c.written.get(LN.BIN, c.files[LN.BIN]))['luts'][12]['enabled'])
        c.choose('C11.cube', 0)
        self.assertEqual(c.vars['LC_Header'][1], 'LUT (11/12)')
        c.choose('C12.cube', 1)
        self.assertEqual(c.vars['LC_Header'][1], 'LUT (12/12)')
        names, _lc = self.lut_row_names(c)
        self.assertEqual(names[-1], 'C12.cube')

    def test_raw_view_after_twelve_luts_the_last_one_waits_and_is_flagged(self):
        c = self.cam(self.big_raw)
        names, _lc = self.lut_row_names(c)
        self.assertEqual(names, [f'C{i:02}.cube' for i in range(11)])      # list order: C11 has no row
        over, _ = c.lut_over()
        self.assertEqual(over, 1)
        c.open_color()
        self.assertEqual(c.vars['LC_Header'][1], 'LUT (12/11)')
        self.assertEqual(c.find_row('C11.cube')[1]['A'], 'No COLOR row: list full')
        self.assertEqual(c.find_row('C10.cube')[1]['A'], ' ')
        c.choose('C12.cube', 1)
        self.assertEqual(c.vars['LC_OK'][1], 'List full: disable one')
        c.choose('C03.cube', 0)                                             # one off: C11 gets its row back
        names, _lc = self.lut_row_names(c)
        self.assertEqual(names[-1], 'C11.cube')
        self.assertEqual(c.find_row('C11.cube')[1]['A'], ' ')
        self.assertEqual(c.vars['LC_Header'][1], 'LUT (11/11)')

    # ------------------------------------------------------------------ 11 rows, each its own ISP set
    def test_eleven_lut_rows_each_pick_shows_its_own_set_and_only_one_is_held(self):
        c = self.cam(self.big_raw)
        self.assertEqual(c.off_matrix(), marker(0))                         # C00 the library's active one, on the ISP
        self.assertEqual(len(held_sets(c)), 1)
        for j in range(11):
            gui = 17 + j                                                    # 16 is RAW-View's row
            self.pick_close(c, gui)
            self.assertEqual(c.clist()['active'], 2 + j)
            self.assertEqual(c.off_matrix(), marker(j), f'row {gui}: C{j:02}')
            self.assertEqual(len(held_sets(c)), 1, 'one set: the shown row\'s')
            self.assertEqual(NS.dangling(c, [(ROOT, 0x90)]), [])
            saved = L.recover(self.big_doc, c.written.get(LN.BIN, c.files[LN.BIN]))
            self.assertEqual(saved['active'], self.big_doc['luts'][j]['id'])
        self.pick_close(c, 16)                                              # RAW-View: LUT gives its set back
        self.assertEqual(held_sets(c), [])
        self.assertEqual(NS.dangling(c, [(ROOT, 0x90)]), [])
        self.pick_close(c, 15)                                              # OFF
        self.assertEqual(c.roots(), TC.ROOT_STOCK)

    def previews(self, c):
        return c.cols('previews')

    def test_the_cursor_previews_each_row_at_once_and_holds_at_most_two_sets(self):
        """Bei 2026-11-10: the cursor on a LUT row shows that LUT at once (as before), but no set per row: the row's
        set is made when the cursor lands (its .JFT), the one it leaves goes back; the picked row's set stays."""
        c = self.cam(self.big)
        self.assertEqual((c.off_matrix(), len(held_sets(c))), (marker(0), 1))
        c.run(c.w(TC.V25), r0=0)                                            # the menu opens
        for gui in (18, 19, 25, 17):                                        # C02, C03, C09, C01: each at once
            opened = len(c.opened)
            self.ui.pick_row(c, gui, site='MJ')
            self.assertEqual(c.off_matrix(), marker(gui - 16), gui)
            self.assertEqual(c.w(0xC2F19D44), 0xFFFFFFFF)                   # the PQ caches re-read it
            self.assertEqual(len(held_sets(c)), 2, 'the picked row\'s + the previewed one')
            self.assertEqual(len([p for p in c.opened[opened:] if p.endswith('.JFT')]), 1, 'one .JFT read a step')
            self.assertEqual(NS.dangling(c, [(ROOT, 0x90)]), [])
        self.ui.pick_row(c, 16, site='MJ')                                  # back on C00 (picked): its set, the preview back
        self.assertEqual((c.off_matrix(), len(held_sets(c))), (marker(0), 1))
        self.ui.pick_row(c, 15, site='MJ')                                  # OFF: stock
        self.assertEqual(c.roots(), TC.ROOT_STOCK)
        self.ui.pick_row(c, 20, site='MJ')                                  # C04, then closed on it: the preview becomes the pick
        before = len(c.borrow_log)
        c.run(c.w(TC.V26), r0=0)
        self.assertEqual(c.off_matrix(), marker(4))
        self.assertEqual(len(held_sets(c)), 1)
        made = [n for k, _q, n in c.borrow_log[before:] if k == 'get' and SET_BYTES <= n < 64 * 1024]
        self.assertEqual(made, [], 'no second build at the close (the pick\'s cube load only)')
        self.assertEqual(NS.dangling(c, [(ROOT, 0x90)]), [])

    def test_a_preview_costs_one_jft_read_and_a_bounded_build(self):
        """The latency of a cursor step (UI thread): instructions executed in COL-Share's setter stub + LUT's preview,
        the .JFT read itself being the firmware's (counted apart: one file, 12 800 B)."""
        from unicorn import UC_HOOK_CODE
        c = self.cam(self.big)
        c.run(c.w(TC.V25), r0=0)
        n = [0]
        h = c.mu.hook_add(UC_HOOK_CODE, lambda mu, a, s, d: n.__setitem__(0, n[0] + 1))
        self.ui.pick_row(c, 21, site='MJ')
        c.mu.hook_del(h)
        self.assertEqual(c.off_matrix(), marker(5))
        print(f'\n  cursor step with a preview: {n[0]} instructions (excluding the firmware file read)')
        self.assertLess(n[0], 400_000)

    def test_while_recording_the_cursor_reads_no_file(self):
        c = self.cam(self.big)
        c.run(c.w(TC.V25), r0=0)
        self.ui.pick_row(c, 18, site='MJ')                                  # C02 previewed before the take
        NS.recording(c)
        opened, p0 = len(c.opened), self.previews(c)
        self.ui.pick_row(c, 19, site='MJ')                                  # C03: no set, no read: stock
        self.assertEqual(c.roots(), TC.ROOT_STOCK)
        self.ui.pick_row(c, 18, site='MJ')                                  # C02: its set is still held: shown
        self.assertEqual(c.off_matrix(), marker(2))
        self.ui.pick_row(c, 16, site='MJ')                                  # C00, the picked one
        self.assertEqual(c.off_matrix(), marker(0))
        self.assertEqual((c.opened[opened:], self.previews(c)), ([], p0))

    def test_a_pick_while_recording_reads_no_file_and_loads_after_the_take(self):
        c = self.cam(self.big)
        NS.recording(c)
        opened = len(c.opened)
        self.pick_close(c, 20)                                              # C04 during a take
        self.assertEqual(c.opened[opened:], [])
        self.assertEqual(c.roots(), TC.ROOT_STOCK)                          # not loaded: the stock look
        self.assertEqual(c.clist()['active'], 5)
        NS.recording(c, False)
        c.run(c.w(TC.V25), r0=0); c.run(c.w(TC.V26), r0=0)                  # the next close after the take
        self.assertEqual(c.off_matrix(), marker(4))
        self.assertEqual(len(held_sets(c)), 1)

    # ------------------------------------------------------------------ resident
    def test_resident_sizes(self):
        _b, f = CS.build()
        self.assertLessEqual(f['block_bytes'], CS.RESIDENT_MAX)
        self.assertLess(f['block_bytes'], RESIDENT_BEFORE['COLS'], 'twelve rows in less than the old four')
        _l, lf = P.build_sup(collection=self.doc)
        self.assertLess(lf['block_bytes'], RESIDENT_BEFORE['LUT'] - 100 * 1024, 'LUT: no resident ISP sets')


if __name__ == '__main__':
    unittest.main()
