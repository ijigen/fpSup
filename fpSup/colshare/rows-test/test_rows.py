"""COL-Share 列數測試版(build_colshare.py --rows N)的離線測試:真的 ARM、真的韌體映像(unicorn)。

    cd fpSup/colshare && python3 -B -m unittest rows-test/test_rows.py      (或 python3 -B rows-test/test_rows.py)

每個 N(5、8、12、19)開一次機(卡 = LUT 卡拿掉 LUT.BIN、COL-Share 換成測試版):
- 安裝:載入成功、getter 筆數 16+N、GUI 表 = 原廠 16 + (0xC, 16..15+N)、AEL 頁範圍 BE 15+N;
- 檔案重導:三份 CSV 複本 = rows_csv(f, N)、N 個 donor 各一份且互不相同、表的容量 64、每個 FPUI 區塊 <= 8 個檔案;
- 頁面複本:記錄結構完整(逐筆走到尾)、物件 id 唯一且與原廠同一組(重複 id 曾讓相機凍結)、
  6 個列數上限 + Effect 框 = 15+N、文字終點 500+33N、大標籤 clip 16+N 格(時間嚴格遞增、落在各自 GUI 之前)、
  每列標籤字串 = "TEST j";
- 選列:每個 GUI 16..15+N 都成為 active、root 一字不動(假客戶沒有記錄)、關選單後客戶記得;15+N+1 不是列;
  QS 的 15 不是選列;LV_ColorMode 16.. -> 15;
- 產品:12 列(Bei 2026-11-10;這個測試版 19 列上機通過之後),常駐 <= 64 KB,colshare_ui 回到產品列數。
  (2026-11-10 起 CSV 與圖示複本在機上、同步時才配,只給存在的列:區塊裡沒有 OP_FILE。)
不代表相機上的繪製、捲動、圖示快取(上機:rows-test/README.md)。
"""
import struct
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CSDIR = HERE.parent
sys.path[:0] = [str(CSDIR), str(CSDIR.parent / 'lut'), str(CSDIR.parent / 'loader-v4')]
import build_colshare as CS          # noqa: E402
import colshare_ui as CU             # noqa: E402
import test_clist_native as CN       # noqa: E402
import test_library_native as LN     # noqa: E402
import test_sup_ui as U              # noqa: E402

ROWS = (5, 8, 12, CU.ROWS_LIMIT)
COLS_FILE = '\\fpSup\\' + CS.NV.file_name('COLS')
ROOT = 0xC2F1A064
IMG = U.N.T3.IMAGE


def stock_word(a):
    return struct.unpack_from('<I', IMG.read_bytes(), a - 0xC0000000)[0]


def be(c, a):
    return struct.unpack('>I', bytes(c.mu.mem_read(a, 4)))[0]


def be_f(c, a):
    return struct.unpack('>f', bytes(c.mu.mem_read(a, 4)))[0]


def records(page):
    """(offset, tag, size) of every record, and where the walk stopped."""
    out, off = [], 0
    while off + 8 <= len(page):
        tag, size = struct.unpack_from('>2I', page, off)
        if size < 8 or off + size > len(page):
            break
        out.append((off, tag, size))
        off += size
    return out, off


def object_ids(page):
    recs, _end = records(page)
    return [struct.unpack_from('>I', page, o + 20)[0] for o, tag, _s in recs if tag == 0x10003]


@unittest.skipIf(U.N.T4.Uc is None or not IMG.exists(), 'requires Unicorn and firmware; skipped is unverified')
class RowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LN.LibraryNativeTests.setUpClass.__func__(cls)                # a LUT card with COL-Share; LUT taken out below
        cls.ui = CN.ClistNativeTests('test_install_patches_every_site_and_sync_fills_two_rows')
        cls.boots = {}
        for n in ROWS:
            blob, facts = CS.build(rows=n)
            files = {p: d for p, d in cls.files.items() if p != LN.BIN}
            files[COLS_FILE] = blob
            cls.boots[n] = (files, facts)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def cam(self, n):
        files, facts = self.boots[n]
        c = CN.Camera(files, self.ar)
        CU.configure(n, test=True)                                   # the host side of what we compare
        self.addCleanup(CU.configure, CU.ROWS_PRODUCT)
        return c, facts

    def ctx(self, c):
        return c.stub_ctx()

    # ------------------------------------------------------------------ the product stays
    def test_the_product_is_twelve_rows_within_64k(self):
        _blob, facts = CS.build()
        self.assertEqual((CU.MAX_ROWS, CU.TEST, facts['max_rows'], facts['test_rows']), (12, False, 12, 0))
        self.assertLessEqual(facts['block_bytes'], CS.RESIDENT_MAX)

    def test_one_fpui_block_no_file_copies_and_no_new_ids(self):
        for n in ROWS:
            with self.subTest(n=n):
                CU.configure(n, test=True)
                try:
                    _s, ops, _f = CU.fpui.decode(CU.block())
                    codes = [code for code, _a in ops]
                    self.assertEqual(codes[0], CU.fpui.OP_HOOK_FV)
                    self.assertEqual(codes.count(CU.fpui.OP_FILE), 0, 'the copies are made on the camera, per row')
                    self.assertEqual(CU.extra_blocks(), 0)
                    for code, a in ops:
                        if code == CU.fpui.OP_PAGE:
                            self.assertEqual(a[4], 0, 'the page copy reserves no new object ids')
                finally:
                    CU.configure(CU.ROWS_PRODUCT)

    # ------------------------------------------------------------------ install
    def test_install_rows_table_and_page_words(self):
        for n in ROWS:
            with self.subTest(n=n):
                c, facts = self.cam(n)
                lines = [l for l in c.written.get('\\fpSup\\LOAD.LOG', b'').decode('latin-1').splitlines()
                         if CS.NV.file_name('COLS') in l]
                self.assertTrue(lines and lines[-1].split()[0] == '%02X' % 10, lines)       # L_LOADED
                ctx = self.ctx(c)
                self.assertEqual(c.w(ctx + 4), n, 'rows present')
                self.assertEqual(c.w(0xC06C07D8), 0xE3A02000 | (16 + n))
                self.assertEqual(c.w(0xC1D6ED48), CS.adv_word(n))
                self.assertEqual(be_f(c, 0xC1D6ED48), 15.0 + n)
                tab = c.table()
                stock = [struct.unpack_from('<2I', IMG.read_bytes(), 0x2E412BC + 8 * i) for i in range(16)]
                self.assertEqual(tab[:16], stock)
                self.assertEqual(tab[16:], [(0xC, 16 + j) for j in range(n)])
                self.assertEqual(c.w(ctx + 8), 0, 'no row active after a cold boot')

    def test_redirects_hold_n_rows_and_n_distinct_icons(self):
        for n in ROWS:
            with self.subTest(n=n):
                c, _f = self.cam(n)
                table = self.ui.redirect_table(c)
                for f, (_name, a, _s) in enumerate(CU.CSV):
                    copy, size = table[a]
                    self.assertEqual(bytes(c.mu.mem_read(copy, size)), CU.rows_csv(f, n), CU.CSV[f][0])
                tiles = []
                for j, (name, a, _s) in enumerate(CU.DONORS):
                    copy, size = table[a]
                    tile = bytes(c.mu.mem_read(copy, size))
                    self.assertEqual(tile, CU.icon(CU.placeholder_name(j)), name)
                    tiles.append(tile)
                self.assertEqual(len(set(tiles)), n, 'every row its own tile')
                self.assertEqual(len(table), 3 + n)
                w = c.w(0xC05E5BEC); hw1, hw2 = w & 0xFFFF, w >> 16
                s = (hw1 >> 10) & 1; j1 = (hw2 >> 13) & 1; j2 = (hw2 >> 11) & 1
                off = s << 24 | (1 ^ (j1 ^ s)) << 23 | (1 ^ (j2 ^ s)) << 22 | (hw1 & 0x3FF) << 12 | (hw2 & 0x7FF) << 1
                if s: off |= 0xFE000000
                entry = c.w((0xC05E5BEC + 4 + off + 4) & 0xFFFFFFFF)
                _code, ent, tw = CU.O.handler()
                self.assertEqual(c.w(c.w(entry - ent + tw) + 12), CU.FV_CAPACITY)

    def page_copy(self, c, n):
        page = c.w(self.ctx(c) + CS.layout(n)['page'])                 # struct cols .page
        hdr = (page & ~3) - 128
        self.assertEqual(c.w(hdr), 0x47505346, 'FSPG')
        return page, bytes(c.mu.mem_read(page, c.w(hdr + 12)))

    def test_the_page_copy_is_whole_ids_unique_and_every_limit_is_15_plus_n(self):
        a, _off, size = CU.O.resource_set('ColorButtonMenu')
        stock = CU.O.at(CU.O.image(), a, size)
        stock_ids = object_ids(stock)
        self.assertEqual(len(stock_ids), len(set(stock_ids)))
        for n in ROWS:
            with self.subTest(n=n):
                c, _f = self.cam(n)
                page, copy = self.page_copy(c, n)
                self.assertEqual(len(copy), size + 10 * n, 'only the label keys were inserted')
                recs, end = records(copy)
                srecs, send = records(stock)
                self.assertEqual((len(recs), end - send), (len(srecs), 10 * n), 'every record walks, none added')
                ids = object_ids(copy)
                self.assertEqual(len(ids), len(set(ids)), 'duplicate object id')
                self.assertEqual(sorted(ids), sorted(stock_ids))
                floats, text_off, text_base = CU.page_offsets()
                for k, o in enumerate(floats):
                    self.assertEqual(be_f(c, page + o), 15.0 + n, f'limit {k}')
                self.assertEqual(be(c, page + text_off), text_base + 33 * n)
                clip = page + CU.LABEL_CLIP - a
                self.assertEqual((be(c, clip), be(c, clip + 4), be(c, clip + 28)), (0x1000A, 48 + 10 * (16 + n), 16 + n))
                times = [be(c, clip + 48 + 10 * i + 2) for i in range(16 + n)]
                self.assertEqual(times, sorted(set(times)), 'key times strictly increase')
                for j in range(n):
                    t = times[16 + j]
                    self.assertTrue(33.3 * (15 + j) < t <= 33.3 * (16 + j), (j, t))
                    sid = be(c, clip + 48 + 10 * (16 + j) + 6)
                    text = bytes(c.mu.mem_read(sid + 0x80000000, 32)).split(b'\0')[0].decode()
                    self.assertEqual(text, f'TEST {j + 1}')

    # ------------------------------------------------------------------ picks
    def test_every_row_picks_without_touching_the_root_and_the_client_remembers(self):
        for n in ROWS:
            with self.subTest(n=n):
                c, _f = self.cam(n)
                ctx = self.ctx(c)
                root = bytes(c.mu.mem_read(ROOT, 0x90))
                tc = ctx + CS.layout(n)['previews'] + 4                # struct cols .tc (after the v3 counters)
                self.assertEqual((c.w(tc), c.w(tc + 8)), (0x31434C43, 0x54535443))
                for j in range(1, n + 1):
                    c.run(c.w(0xC0D119FC), r0=0)                           # the menu opens (v25)
                    enum, z = self.ui.pick_row(c, 15 + j)
                    self.assertEqual((enum, z, c.w(ctx + 8)), (0xC, 0, j), j)
                    tab = c.table()
                    self.assertEqual(tab[15][1], 15 + j, 'the active row first among OFF\'s GUIs')
                    self.assertEqual(sorted(g for e, g in tab if e == 0xC), list(range(15, 16 + n)), 'each GUI once')
                    c.run(c.w(0xC0D11A00), r0=0)                           # and closes (v26): on_pick
                    self.assertEqual(c.w(tc + 56), j, 'on_pick reached the client')   # .tpick: after the client's 14 words (v3 preview)
                    self.assertEqual(bytes(c.mu.mem_read(ROOT, 0x90)), root, 'no record: the root stays')
                self.ui.pick_row(c, 16 + n)                                # past the last row: no row
                self.assertEqual(c.w(ctx + 12), 0)
                self.ui.pick_row(c, 15, site='MA2')                        # OFF
                self.assertEqual(c.w(ctx + 8), 0)
                enum = c.run(c.stub_at(CN.SITES['MA3']), r1=15, lr=0xC05818BC)
                self.assertEqual(c.w(ctx + 12), 0, 'QS 15 is no pick')
                for g in (16, 15 + n):
                    self.assertEqual(c.run(c.stub_at(CN.SITES['ML']), r0=0xC), 15)
                c.models.clear()


if __name__ == '__main__':
    unittest.main()
