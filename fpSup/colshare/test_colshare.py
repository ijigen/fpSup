"""COL-Share(colshare.c)+ LUT(lut/native/cols.c)在 unicorn 上跑真的 ARM、真的韌體映像(DESIGN.md §11)。

沿用 lut/test_clist_native.py 的相機模型(LUT 那邊的斷言在那裡移植成「COL-Share + LUT」);
這裡是 COL-Share 本身:安裝與 claim、兩種載入順序、setter 依記錄寫 root、記錄越界、±框範圍、
錄影延後(兩個旗標落點)、舊 RAW-View 退出、LUT 單獨、關機寫回、暖開機殘留、大小。
不代表相機上的畫面、清單繪製或圖示快取(要上機,§12)。

    cd fpSup/colshare && python3 -B -m unittest test_colshare
    python3 -B mutate_colshare.py          # 突變:每個都要讓某個測試失敗
"""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'lut'), str(HERE.parent / 'loader-v4')]
import build_colshare as CS          # noqa: E402
import colshare_ui as CU             # noqa: E402
import test_clist_native as CN       # noqa: E402
import test_library_native as LN     # noqa: E402
import test_sup_native as NS         # noqa: E402
import test_sup_ui as U              # noqa: E402

COLS_ID = 0x534C4F43
LUT_ID = 0x3454554C
ROOT = 0xC2F1A064
# colshare.c struct cols offsets (build_colshare.layout = the C's _Static_asserts; checked against the api magic)
_LAY = CS.layout(CU.ROWS_PRODUCT)
O_REC, O_SHOWN, O_SHOWN_REC, O_DOWN, O_EFFMIN, O_EFFMAX, O_STOCK = (_LAY[k] for k in ('rec', 'shown', 'shown_rec', 'down',
                                                                                     'effmin', 'effmax', 'root_stock'))
O_API = _LAY['api']
O_PEND_PICK, O_POFFS, O_DEFERRED = _LAY['pend_pick'], _LAY['poffs'], _LAY['deferred']
ROOT_STOCK = {0x08: (0xC0B39CC8, 35), 0x10: (0xC0B3A010, 34), 0x28: (0xC2F1AAE8, 35), 0x48: (0xC0B3AAEC, 12),
              0x50: (0xC0B3AB1C, 36), 0x70: (0xC0B3D670, 36)}
LUT_ORDER = [0x10, 0x08, 0x28, 0x50, 0x70, 0x48, 0x4C]          # lvb.c lvb_rec: clist_stub_mc's "ours"
KEYS = (0xC3414D14, 0xC2F19D44, 0xC2F19D48)
# today's (clist.c) sixteen site writes, normalised: a bl to veneer slot k (16 B each), the vtable words
# v + 112 / + 128, the getter's movw/movt on the GUI table, mov r2, #16 + rows, BE 15.0 + rows (11-07 old-vs-new dump;
# 12 rows since 11-10: #28, 27.0)
SITE_SHAPE = {'MA1': 0, 'MA2': 0, 'MA3': 0, 'MJ': 16, 'MB': 32, 'ML': 48, 'MC': 64, 'EF': 80, 'EN': 96, 'ENF': 96}
MOV_SITES = {'GMOVW': 0xC06C07CC, 'GMOVT': 0xC06C07D0}
WORD_SITES = {0xC06C07D8: 0xE3A02000 | (16 + CU.ROWS_PRODUCT), 0xC1D6ED48: CS.adv_word(CU.ROWS_PRODUCT)}
V25, V26, FV = 0xC0D119FC, 0xC0D11A00, 0xC05E5BEC
COLS_FILE = '\\fpSup\\' + CS.NV.file_name('COLS')
OTHER_SITES = {**CN.SITES, 'GMOVW': 0xC06C07CC, 'GMOVT': 0xC06C07D0, 'GCNT': 0xC06C07D8, 'V25': V25, 'V26': V26,
               'ADV': 0xC1D6ED48, 'AI': 0xC05E2200}
DNG_SITES = (0xC02C6920, 0xC02C6940, 0xC02C6950, 0xC02C7620, 0xC02C7640, 0xC02C7650,
             0xC02C5450, 0xC02C5E18, 0xC02CC1A0, 0xC02C55B4)
IMAGE = U.N.T3.IMAGE


def stock(a):
    return struct.unpack_from('<I', IMAGE.read_bytes(), a - 0xC0000000)[0]


class Camera(CN.Camera):
    residue = None                       # {addr: word} put in memory before the boot (a past boot's)

    def page_entries(self):
        super().page_entries()
        for a, w in (self.residue or {}).items():
            self.put(a, w)

    # ---- COL-Share ----
    def api(self):
        return self.callsvc('find', r1=COLS_ID)

    def cs(self, off, n=1):
        ctx = self.stub_ctx()
        assert self.w(ctx + O_API) == 0x31414C43, 'struct cols layout moved (O_API)'
        return self.w(ctx + off) if n == 1 else [self.w(ctx + off + 4 * i) for i in range(n)]

    def api_call(self, slot, r1=0, r2=0, r3=0):
        api = self.api()
        fn = self.w(api + slot)
        self.mu.reg_write(U.N.T4.UC_ARM_REG_R3, r3 & 0xFFFFFFFF)
        r, _sp = self.call(fn & ~1, r0=api, r1=r1, r2=r2, thumb=bool(fn & 1))
        return r - (1 << 32) if r >> 31 else r

    def set_record(self, key, rec, sup=LUT_ID):
        return self.api_call(16, sup, key, rec)

    SCRATCH = U.U.F6.FAKE + 0xE800

    def record(self, words, n=None):
        """A struct cols_rec in scratch memory: words = [(off, val), ...]."""
        blob = struct.pack('<I', len(words) if n is None else n)
        for off, val in words[:12]:
            blob += struct.pack('<HHI', off, 0, val)
        self.mu.mem_write(self.SCRATCH, blob.ljust(100, b'\0'))
        return self.SCRATCH

    def root_writes(self):
        """Arm a write log on the root's first 0x90 bytes: [(offset, value)]."""
        from unicorn import UC_HOOK_MEM_WRITE
        log = []
        NS.ORIGINAL_HOOK(self.mu, UC_HOOK_MEM_WRITE, lambda mu, acc, a, size, v, d: log.append((a - ROOT, v & 0xFFFFFFFF)),
                         None, ROOT, ROOT + 0x8F)
        return log

    def roots(self):
        return {o: (self.w(ROOT + o), self.w(ROOT + o + 4)) for o in ROOT_STOCK}

    def power_off(self):
        for o, _ in list(self.registered):
            self.call(self.w(self.w(o) + 12), r0=o, r1=4)

    def log_lines(self):
        return self.written.get('\\fpSup\\LOAD.LOG', b'').decode('latin-1').splitlines()


@unittest.skipIf(U.N.T4.Uc is None or not IMAGE.exists(), 'requires Unicorn and firmware; skipped is unverified')
class ColShareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LN.LibraryNativeTests.setUpClass.__func__(cls)            # COL-Share + LUT (A, B on; A active)
        cls.ui = CN.ClistNativeTests('test_install_patches_every_site_and_sync_fills_two_rows')

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def cam(self, files=None, residue=None, color=None):
        c = Camera.__new__(Camera); c.residue = residue
        Camera.__init__(c, files or self.files, self.ar)
        return c

    def pick(self, c, gui, site='MA2'): return self.ui.pick_row(c, gui, site)

    def close(self, c):
        c.run(c.w(V25), r0=0); c.run(c.w(V26), r0=0)

    # ------------------------------------------------------------------ install
    def test_the_sixteen_site_writes_are_todays(self):
        """One client: byte for byte the clist.c writes (bl targets normalised to the veneer slots)."""
        c = self.cam()
        v = c.stub_at(CN.SITES['MA1'])
        ctx = c.stub_ctx()
        for name, slot in SITE_SHAPE.items():
            self.assertEqual(c.stub_at(CN.SITES[name]) - v, slot, name)
        for k in range(9):
            self.assertEqual((c.w(v + 16 * k), c.w(v + 16 * k + 4), c.w(v + 16 * k + 8)), (0xE59FC000, 0xE59FF000, ctx), k)
        self.assertEqual((c.w(V25) - v, c.w(V26) - v), (112, 128))
        tab = ctx + _LAY['guitab']
        for name, a in MOV_SITES.items():
            w = c.w(a)
            self.assertEqual(w & 0xFFF0F000, stock(a) & 0xFFF0F000, name)
            self.assertEqual(((w >> 4) & 0xF000) | (w & 0xFFF), (tab >> 16 if name == 'GMOVT' else tab) & 0xFFFF, name)
        for a, w in WORD_SITES.items():
            self.assertEqual(c.w(a), w, hex(a))

    def test_claims_in_load_log_and_the_api(self):
        c = self.cam()
        lines = c.log_lines()
        mine = [l for l in lines if CS.NV.file_name('COLS') in l]
        self.assertTrue(mine and mine[-1].split()[0] == '%02X' % 10, lines)         # L_LOADED
        self.assertEqual(int(mine[-1].split()[2], 16), 16 + 1 + 6 + 1)             # sites, C05E5BEC, root pairs, the v2 glyph site
        lut = [l for l in lines if 'LUT_v' in l and '.BIN' in l]
        self.assertEqual(int(lut[-1].split()[2], 16), 6 + 2 + 5 + 6)               # DNG 6 + 2 tables, lvb 5, CKNEE 3 desc + 3 tables (JFIT v6): no root
        api = c.api()
        self.assertEqual((c.w(api), c.w(api + 4)), (0x31414C43, 3))
        self.assertEqual(c.w(c.w(api + 28) + 8), ROOT_STOCK[0x08][0])               # stock_root

    def test_a_refused_claim_releases_and_writes_nothing(self):
        """Another sup holds the AEL page word: COL-Share does not load, every site stays stock, LUT has no rows."""
        src = Path(self.temp.name) / 'holder.c'
        src.write_text('#include "sloader4.h"\nint sup_entry(void *b, const struct sl_svc *svc, const char *p) {\n'
                       '    (void)b; (void)p; uint32_t w = 0x00004041u;\n'
                       '    return svc->claim(svc, 0xC1D6ED48u, 4u, &w, SL_EXCL) == SL_OK ? SL_KEEP : SL_RELEASE; }\n')
        holder = CS.B.c_sup(src, 'HOLD', name='Holder')
        files = dict(self.files); files['\\fpSup\\AAHOLD.BIN'] = holder
        c = self.cam(files)
        self.assertEqual(c.api(), 0)
        for name, a in OTHER_SITES.items():
            self.assertEqual(c.w(a), stock(a), name)
        self.assertEqual(c.w(FV), 0x60681840)
        api, _ = c.lut()
        self.assertEqual(c.w(api + 9 * 4), 8)
        for a in DNG_SITES:
            self.assertEqual(c.w(a), stock(a), hex(a))

    def test_no_client_keeps_the_stock_sixteen_rows(self):
        files = {p: d for p, d in self.files.items() if p != LN.BIN}
        c = self.cam(files)
        table = self.ui.redirect_table(c)                             # no rows: no copies (Bei 11-10), the stock files
        self.assertEqual(set(table) & {a for _n, a, _s in CU.CSV} | set(table) & {d[1] for d in CU.ALL_DONORS}, set())
        self.assertEqual(c.w(c.stub_ctx() + _LAY['heap']), 0)
        self.assertEqual(c.clist()['n'], 0)
        self.pick(c, 16)                                              # GUI 16 is no row: not a pick
        self.assertEqual((c.clist()['active'], c.clist()['pend']), (0, 0))

    # ------------------------------------------------------------------ registration
    def state(self, c):
        L = c.clist()
        return dict(n=L['n'], active=L['active'], eff=L['eff'], tab=c.table(),
                    csv=[bytes(c.mu.mem_read(*self.ui.redirect_table(c)[a])) for _n, a, _s in CU.CSV])

    def test_both_load_orders_give_the_same_rows_table_and_active(self):
        """COL-Share before LUT (add) and after it (LUT provides COLS_TAG, COL-Share's entry collects it)."""
        off = {0xC31B32BC + 0x12C: 0xC}                               # the saved COLOR mode: OFF (a LUT row)
        a = self.cam(residue=off)
        files = dict(self.files); files['\\fpSup\\ZZ' + CS.NV.file_name('COLS')] = files.pop(COLS_FILE)
        b = self.cam(files, residue=off)
        sa, sb = self.state(a), self.state(b)
        self.assertEqual(sa, sb)
        self.assertEqual((sa['n'], sa['active']), (2, 1))
        api, _ = b.lut()
        self.assertEqual(b.w(api + 9 * 4), 0)                        # attached later
        for site in DNG_SITES:                                        # LUT's own points, from attached()
            self.assertEqual(b.w(site) >> 24, 0xEB, hex(site))
        ra, rb = a.roots(), b.roots()                                 # both show A (their own copies: other addresses)
        self.assertEqual({o: n for o, (_p, n) in ra.items()}, {o: n for o, (_p, n) in rb.items()})
        self.assertEqual(rb[0x48][1], 13)
        self.assertTrue(all(rb[o][0] != ROOT_STOCK[o][0] for o in (0x08, 0x10, 0x48, 0x70)))
        self.assertEqual((a.cs(O_SHOWN), b.cs(O_SHOWN)), (1, 1))

    # ------------------------------------------------------------------ the setter
    def test_the_setter_writes_the_record_in_order_and_stock_in_reverse(self):
        c = self.cam()
        self.pick(c, 15)                                              # OFF first: stock shown
        self.assertEqual(c.cs(O_SHOWN_REC), 0)
        log = c.root_writes()
        self.pick(c, 17)                                              # B
        self.assertEqual([o for o, _ in log], LUT_ORDER)
        rec = c.cs(O_REC + 8)
        self.assertEqual(c.cs(O_SHOWN_REC), rec)
        self.assertEqual([c.w(k) for k in KEYS], [0xFFFFFFFF] * 3)
        del log[:]
        for k in KEYS: c.put(k, 0x1234)
        self.pick(c, 15)                                              # OFF: the stock values, reverse order
        self.assertEqual([o for o, _ in log], LUT_ORDER[::-1])
        self.assertEqual(c.roots(), ROOT_STOCK)
        self.assertEqual(c.w(ROOT + 0x4C), 12)
        self.assertEqual([c.w(k) for k in KEYS], [0xFFFFFFFF] * 3)
        del log[:]
        self.pick(c, 16); self.ui.setter(c, 3)                        # a row, then a stock mode: stock again
        self.assertEqual(c.roots(), ROOT_STOCK)

    def test_a_row_without_a_record_leaves_the_root_and_a_later_record_shows_at_once(self):
        c = self.cam()
        self.pick(c, 15)
        b_rec = c.cs(O_REC + 8)
        self.assertEqual(c.set_record(1, 0), 0)                       # B's record withdrawn (key = library index 1)
        self.assertEqual(c.cs(O_REC + 8), 0)
        log = c.root_writes()
        self.pick(c, 17)
        self.assertEqual((c.clist()['active'], log), (2, []))         # active moved, root untouched
        self.assertEqual(c.set_record(1, b_rec), 0)                   # selected: written now
        self.assertEqual([o for o, _ in log], LUT_ORDER)
        self.assertEqual(c.cs(O_SHOWN), 2)

    def test_a_record_outside_the_claimed_words_is_refused(self):
        c = self.cam()
        self.assertEqual(c.set_record(0, c.record([(0x40, 1)])), -3)          # +0x40: not claimed
        self.assertEqual(c.set_record(0, c.record([(0x09, 1)])), -3)          # unaligned
        self.assertEqual(c.set_record(0, c.record([(0x10, 1)] * 12, n=13)), -3)
        self.assertEqual(c.set_record(0, c.record([], n=0)), -3)
        self.assertEqual(c.set_record(0, c.record([(0x10, 1)]), sup=0x12345678), -3)   # not a client
        self.assertEqual(c.set_record(0, c.record([(0x74, ROOT_STOCK[0x70][1])])), 0)   # in the set: taken
        self.assertEqual(c.cs(O_REC + 4), c.SCRATCH)

    # ------------------------------------------------------------------ the box
    def test_the_box_clamps_to_each_rows_range_and_close_saves_once(self):
        c = self.cam()
        self.pick(c, 16)
        ctx = c.stub_ctx()
        c.put(ctx + O_EFFMIN + 4, (-2) & 0xFFFFFFFF); c.put(ctx + O_EFFMAX + 4, 3)   # row 1: -2 .. +3
        self.assertEqual(c.run(c.stub_at(CN.SITES['EF']), r1=5), 0)
        self.assertEqual(c.clist()['eff'][1], 3)
        c.run(c.stub_at(CN.SITES['EF']), r1=-4 & 0xFFFFFFFF)
        self.assertEqual(c.clist()['eff'][1], -2)
        c.put(ctx + O_EFFMIN + 4, (-5) & 0xFFFFFFFF); c.put(ctx + O_EFFMAX + 4, 0)
        c.run(c.stub_at(CN.SITES['EF']), r1=-1 & 0xFFFFFFFF)
        before = c.bin_writes
        c.run(c.w(V26), r0=0)
        self.assertEqual(c.status()['strength'], 80)
        self.assertEqual(c.bin_writes - before, 1)                    # one save: strength_set once (pick: same cube)
        c.run(c.w(V25), r0=0); c.run(c.w(V26), r0=0)                  # nothing changed: nothing saved
        self.assertEqual(c.bin_writes - before, 1)

    # ------------------------------------------------------------------ recording
    def recording_case(self, flag, selector):
        c = self.cam()
        c.put(0xC347D1D4, selector)
        c.mu.mem_write(flag, b'\1')
        c.run(c.w(V25), r0=0)
        self.pick(c, 17)                                              # B while recording
        c.run(c.w(V26), r0=0)
        self.assertEqual(c.cs(O_PEND_PICK), 1)                        # not delivered
        self.assertGreaterEqual(c.cs(O_DEFERRED), 1)
        self.assertEqual(LN.L.recover(self.doc, c.written.get(LN.BIN, c.files[LN.BIN]))['active'], self.doc['luts'][0]['id'])
        c.mu.mem_write(flag, b'\0')
        self.close(c)                                                 # the next close after the take
        self.assertEqual(c.cs(O_PEND_PICK), 0)
        self.assertEqual(LN.L.recover(self.doc, c.written.get(LN.BIN, c.files[LN.BIN]))['active'], self.doc['luts'][1]['id'])

    def test_recording_defers_the_callbacks_flag_at_0x157(self):
        self.recording_case(0xC347E08F, 0)

    def test_recording_defers_the_callbacks_flag_at_0x3d(self):
        self.recording_case(0xC3476609, 0x21)

    # ------------------------------------------------------------------ old RAW-View, LUT alone
    def test_old_raw_view_releases_col_share_and_nothing_is_written(self):
        files = dict(self.files); files['\\fpSup\\RAWV.BIN'] = CN.ClistNativeTests.old_rawview_header()
        c = self.cam(files)
        self.assertEqual(c.api(), 0)
        for name, a in OTHER_SITES.items():
            self.assertEqual(c.w(a), stock(a), name)
        self.assertEqual(c.w(FV), 0x60681840)
        self.assertTrue(any('old RAW-View' in l for l in c.log_lines()), c.log_lines())

    def test_a_raw_view_client_or_a_disabled_old_one_keeps_col_share(self):
        new = dict(self.files); new['\\fpSup\\RAWV.BIN'] = CN.ClistNativeTests.old_rawview_header(CU.RAWVIEW_CLIENT)
        self.assertNotEqual(self.cam(new).api(), 0)
        both = dict(new); both['\\fpSup\\RAW-View_v0.3.1.BIN'] = CN.ClistNativeTests.old_rawview_header()
        self.assertNotEqual(self.cam(both).api(), 0)                   # the newer one loads (and is a client)
        off = dict(self.files); off['\\fpSup\\RAWV.BIN'] = CN.ClistNativeTests.old_rawview_header()
        off['\\fpSup\\LOADER.BIN'] = CS.B.with_disabled(off['\\fpSup\\LOADER.BIN'], ['RAWV'])
        c = self.cam(off)
        self.assertNotEqual(c.api(), 0)
        self.assertEqual(c.clist()['n'], 2)

    def test_lut_alone_writes_no_colour_root_or_dng_point_and_the_manager_works(self):
        files = {p: d for p, d in self.files.items() if p != COLS_FILE}
        c = self.cam(files)
        self.assertEqual(c.api(), 0)
        for name, a in OTHER_SITES.items():
            self.assertEqual(c.w(a), stock(a), name)
        for a in DNG_SITES + (0xC010A160, 0xC096FD74, 0xC096FCE4):
            self.assertEqual(c.w(a), stock(a), hex(a))
        lut = [l for l in c.log_lines() if 'LUT_v' in l and '.BIN' in l]
        self.assertEqual(int(lut[-1].split()[2], 16), 0)             # LOADED, no claim
        api, _ = c.lut()
        self.assertEqual(c.w(api + 9 * 4), 8)
        c.open_color()
        self.assertEqual(c.vars['LC_Header'][1], 'LUT (2/12)')
        self.assertEqual(c.vars['LC_OK'][1], 'COLOR list needs COL-Share')
        self.assertEqual(c.invoke(8, 1), 0)                           # library_pick still works

    # ------------------------------------------------------------------ power-off, warm boot
    def test_power_off_puts_every_word_back_and_the_setter_stays_stock(self):
        c = self.cam()
        self.pick(c, 16)                                              # A: the library's active row, its set held
        self.assertNotEqual(c.roots(), ROOT_STOCK)
        for k in KEYS: c.put(k, 0x1234)
        ctx = c.stub_ctx()
        c.power_off()
        self.assertEqual(c.roots(), ROOT_STOCK)
        for name, a in OTHER_SITES.items():
            self.assertEqual(c.w(a), stock(a), name)
        self.assertEqual(c.w(FV), 0x60681840)
        self.assertEqual([c.w(k) for k in KEYS], [0xFFFFFFFF] * 3)
        self.assertEqual((c.w(ctx + O_DOWN), c.w(ctx + O_POFFS) >= 1), (1, True))

    def test_power_off_routine_alone_restores_the_root(self):
        """COL-Share's own routine (without the loader's journal): the root and the caches."""
        c = self.cam()
        self.pick(c, 16)
        po = c.stub_ctx() + _LAY['pend_pick'] + 20                   # struct cols .poff
        self.assertEqual(c.w(po), po - 8)
        c.call(c.w(c.w(po) + 12), r0=po, r1=4, sp=(U.N.T3.STACK - 0x1000) & ~7 | 4)
        self.assertEqual(c.roots(), ROOT_STOCK)
        log = c.root_writes()
        self.pick(c, 17)                                              # after it: no root write
        self.assertEqual(log, [])

    def test_a_warm_boots_residue_is_repaired_by_the_claims(self):
        """A past boot's words (no power-off ran): the claim writes stock first, the boot is as a cold one."""
        res = {CN.SITES['MC']: 0xEB000000, ROOT + 0x08: 0x40404040, ROOT + 0x4C: 13, 0xC1D6ED48: 0x00009841, FV: 0xF000B800}
        c = self.cam(residue=res)
        self.assertEqual(c.api() != 0, True)
        rep = [l for l in c.log_lines() if l.startswith('%02X' % 12)]   # L_REPAIRED
        self.assertGreaterEqual(len(rep), 4, c.log_lines())
        self.assertEqual(c.cs(O_STOCK + 8), ROOT_STOCK[0x08][0])        # the snapshot is stock
        self.assertEqual(self.state(c), self.state(self.cam()))
        c.power_off()
        self.assertEqual(c.w(CN.SITES['MC']), stock(CN.SITES['MC']))
        self.assertEqual(c.roots(), ROOT_STOCK)

    def test_full_power_off_lists_leave_lut_ready_and_col_share_loaded(self):
        """Camera 2026-11-08: XC_PowerOffMgr's lists (ten slots each) were full -> LUT's own registration failed,
        lvb_install returned 7, no records, no grading.  LUT registers nothing now; COL-Share's is optional."""
        ref = self.cam()
        base = len([o for o, _ in ref.registered if o != ref.stub_ctx() + _LAY['pend_pick'] + 20])   # the loader's own

        class Full(Camera):
            def _hook(self, mu, addr, size, data):
                if addr == 0xC0024118 and len(self.registered) >= base:
                    return self._ret(0)                               # the list is full
                return super()._hook(mu, addr, size, data)
        c = Full.__new__(Full); c.residue = None
        Full.__init__(c, self.files, self.ar)
        self.assertNotEqual(c.api(), 0)
        self.assertEqual(c.cs(_LAY['pend_pick'] + 52), 3)            # poff_missing: both lists
        lv = [w for w in struct.unpack('<1024I', bytes(c.mu.mem_read(c.lut()[1], 4096)))]
        at = lv.index(0x3142564C)
        self.assertEqual(lv[at + 1], 1)                               # lvb ready
        self.assertEqual(lv[at + 61], 0)                              # lvb_result 0 (after lvb's 11-10 counters)
        self.assertEqual(c.cs(O_REC + 4, 2) != [0, 0], True)          # the records are in
        self.pick(c, 16)                                              # A, the picked one (11-10: only its set exists)
        self.assertNotEqual(c.roots(), ROOT_STOCK)                    # and a row grades

    def test_lut_registers_no_power_off_routine(self):
        c = self.cam()
        _api, state = c.lut()
        self.assertFalse(any(state <= o < state + 4096 for o, _ in c.registered))

    # ------------------------------------------------------------------ size
    def test_resident_sizes(self):
        _blob, facts = CS.build()
        self.assertLessEqual(facts['block_bytes'], CS.RESIDENT_MAX)
        _lut, lf = LN.P.build_sup(collection=self.doc)
        self.assertLessEqual(lf['block_bytes'], LUT_BLOCK_BEFORE)        # LUT's resident must not grow
        self.assertLessEqual(lf['file_bytes'], LUT_FILE_BEFORE)


# LUT.BIN for this class's library before COL-Share (the clist.c build, 2026-11-07 backup), measured
# (lut-before-colshare: block 748416 B, file 603396 B; after: 723520 / 578516)
LUT_BLOCK_BEFORE, LUT_FILE_BEFORE = 748416, 603396


if __name__ == '__main__':
    unittest.main()
