"""RAW-View 0.4.0test as a COL-Share client (fpSup/colshare/DESIGN.md P3; Bei 2026-11-07 §9.1),
together with COL-Share and LUT, on the real v4 core, the real firmware image and the actual ARM.

    cd projects/rawview/build && python3 -B -m unittest test_v4_cols_rawview

Reuses fpSup/colshare/test_colshare.py's camera (COL-Share + LUT, cubes A and B on, A the library's
active one).  Covered: install and claims (LOAD.LOG), the row first in the list, both load orders,
switching LUT <-> RAW <-> stock writes the right root records and restores stock, the copies'
OFF entries follow the gain stub, the playback command, the boxes gated on "the root shows RAW",
the record in its own file (picked through on_pick), the boot restore through picked(), power-off
journal, a warm boot's residue, no COL-Share (no row, no point, the fpSup page says why), LUT's
custom DNG matrix still reaching the writer with RAW-View's OFF-constant redirect in place.

Emulated, not on the camera.
"""
import struct
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT_DIR = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT_DIR / 'fpSup/colshare'), str(ROOT_DIR / 'fpSup/lut'),
                str(ROOT_DIR / 'fpSup/loader-v4')]
import build_v3_rawview as V            # noqa: E402
import test_colshare as TC              # noqa: E402

CN, LN, U = TC.CN, TC.LN, TC.U
RAWV_ID, LUT_ID = 0x56574152, 0x3454554C
RV_FILE = '\\fpSup\\' + V.COLS_FILE
ROOT = TC.ROOT
SITE_A, SITE_B, SV, PQ = 0xC0313244, 0xC032F728, 0xC0088C60, 0xC02B8E64
SA_AJ, ZC_AJ = 0xC056D5F8, 0xC056D548
SA_CONV, ZC_CONV, PUBLISH, SV_ORIG, PQ_ORIG = 0xC06C1060, 0xC06C0EC0, 0xC0593F30, 0xC0088660, 0xC02B97A8
DNG_MOVWT = (0xC02C4BE4, 0xC02C4BE8, 0xC02C4C98, 0xC02C4C9C)
P_FLAG, P_EFF, P_MODE, P_VAR, P_MAT, P_SAT, P_CON, P_BLOCK = 0x04, 0x08, 0x18, 0x1A4, 0x1A8, 0x1B0, 0x1C4, 0x1CC
P_MODEN, P_SATTAB = 0x124, 0x1D0
BANK_A, KEY_CTX0 = 0xC31B32BC, 0xC2F19D44
OFF_COLOR = {BANK_A + 0x12C: 0xC}
SV_GROUP, SV_COLOR = 0x58CC, 0x13C
CFG_OFF = 48
CB_PICKED, CB_ROWIDX, CB_ROWED, CB_REC, CB_ROW, CB_BOX = 28, 48, 52, 108, 208, 240
AI, AI_ORIG = 0xC05E2200, 0xC05D6BB8
_LAY = TC.CS.layout(TC.CU.ROWS_PRODUCT)                 # colshare.c struct cols: snap / live / glyph (12 rows: 11-10)
SNAP = _LAY['snap']; LIVE = SNAP + 4 * (TC.CU.ROWS_PRODUCT + 1); GLYPH = LIVE + 4 * (TC.CU.ROWS_PRODUCT + 1)
EN_SITE, EF_SITE = CN.SITES['EN'], CN.SITES['EF']
STOCK_POOL = 0xC18C0474
K06, K07, LB5, ID_S, ID_G, ID_A = 0xC18E6BA0, 0xC18E6BB8, 0xC18E67B0, 0xC18E6A80, 0xC18E6990, 0xC18E6918


OWN_SITES = {SITE_A, SITE_B, 0xC056D5F8, 0xC056D498, 0xC059588C, 0xC05959E4,       # gain, saturation
             0xC056D548, 0xC056D3E8, 0xC056D5A0, 0xC056D440, 0xC059581C, 0xC0595974, 0xC0595854, 0xC05959AC,
             *DNG_MOVWT, SV, PQ}


def imm(w):
    return ((w >> 4) & 0xF000) | (w & 0xFFF)


class Camera(TC.Camera):
    """test_colshare's camera; the stock routines RAW-View's stubs tail-call return a marker."""
    def page_entries(self):
        super().page_entries()
        for a in (SA_CONV, ZC_CONV, SV_ORIG, PQ_ORIG, AI_ORIG):
            self.by_addr[a] = 'RV_MODEL'
        self.rv_calls = []
        self.rv_r2 = []

    def _hook(self, mu, addr, size, data):
        if self.by_addr.get(addr) == 'RV_MODEL':
            self.rv_calls.append(addr)
            self.rv_r2.append(self.r(U.N.T3.UC_ARM_REG_R2))
            return self._ret(0x55)
        if addr == U.N.T3.F['F_OPEN'] and self.r(U.N.T3.UC_ARM_REG_R2) == 7 and \
                self.cstr(self.r(U.N.T3.UC_ARM_REG_R1)) == RV_FILE:     # mode 7 keeps what is there
            self.written.setdefault(RV_FILE, self.files.get(RV_FILE, b''))
            r = super()._hook(mu, addr, size, data)
            return r
        return super()._hook(mu, addr, size, data)

    def res(self):
        """RAW-View's resident params: site A -> veneer (ldr pc, [pc, #-4]) -> stub_gs."""
        w = self.w(SITE_A)
        off = (w & 0xFFFFFF) << 2
        ven = (SITE_A + 8 + (off - (1 << 26) if off & (1 << 25) else off)) & 0xFFFFFFFF
        return self.w(ven + 4) - self.facts['res_syms']['stub_gs']

    def cb(self):
        return self.w(self.res() + P_BLOCK) + self.cb_off


@unittest.skipIf(U.N.T4.Uc is None or not TC.IMAGE.exists(), 'requires Unicorn and firmware; skipped is unverified')
class RawViewColsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LN.LibraryNativeTests.setUpClass.__func__(cls)        # COL-Share + LUT (A, B on; A active)
        cls.ui = CN.ClistNativeTests('test_install_patches_every_site_and_sync_fills_two_rows')
        cls.sup, cls.facts, cls.rows = V.build(v4=True, name=b'RAW-View\0', cols=True)
        cls.sites = {a: s for a, s, _ in cls.rows}
        cls.all = dict(cls.files); cls.all[RV_FILE] = cls.sup
        cls.cb_off = cls.facts['blob_off'] - cls.facts['launch'] + cls.facts['launch_syms']['cb_state']

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def cam(self, files=None, residue=None, sup=None):
        f = dict(files or self.all)
        if sup is not None:
            f[RV_FILE] = sup
        c = Camera.__new__(Camera); c.residue = residue; c.facts = self.facts; c.cb_off = self.cb_off
        Camera.__init__(c, f, self.ar)
        return c

    def pick(self, c, gui): return self.ui.pick_row(c, gui)
    def close(self, c): c.run(c.w(TC.V26), r0=0)

    def with_cfg(self, *words):
        s = bytearray(self.sup)
        s[CFG_OFF:CFG_OFF + 32] = struct.pack('<8I', *(list(words) + [0] * (8 - len(words))))
        return bytes(s)

    def claims(self, c, name):
        line = [l for l in c.log_lines() if name in l and l.startswith('0A')]
        return int(line[-1].split()[2], 16) if line else None

    def raw_rec(self, c):
        res = c.res()
        return {0x70: c.w(res + P_MODE), 0x08: c.w(res + P_MAT)}

    def gain(self, c, rel=800):
        """stub_gs at standby (FUN_c03131e0: r5 = helper with gain_state 0, r6 = the relative gain)."""
        from unicorn import arm_const
        helper = c.SCRATCH + 0x200
        c.put(helper + 0xC, 0)
        c.mu.reg_write(arm_const.UC_ARM_REG_R5, helper)
        c.mu.reg_write(arm_const.UC_ARM_REG_R6, rel)
        c.call(c.res() + self.facts['res_syms']['stub_gs'])
        return c.r(arm_const.UC_ARM_REG_R2)

    # ------------------------------------------------------------------ install
    def test_loads_after_col_share_with_its_own_sites_and_the_first_row(self):
        c = self.cam()
        self.assertEqual(self.claims(c, V.COLS_FILE), 20)
        self.assertEqual(self.claims(c, 'COL-Share'), 24)                  # 16 + FV + 6 root pairs + the glyph site
        self.assertEqual(self.claims(c, 'LUT_v'), 19)   # 13 + the CKNEE's 6 (JFIT v6)
        h = struct.unpack_from('<12I', self.sup)
        self.assertEqual((h[5], h[6]), (RAWV_ID, 0x000400))                # COL-Share: >= 0x000400 is a client
        self.assertEqual(sorted(self.sites), sorted(OWN_SITES))           # the twenty, written out here
        self.assertEqual({a: k for a, _s, k in self.rows}[SV], V.CHAIN)
        self.assertEqual({a: k for a, _s, k in self.rows}[PQ], V.CHAIN)
        for a in self.sites:
            if a not in DNG_MOVWT:
                self.assertEqual(c.w(a) >> 24, 0xEB, hex(a))
        cm = c.res() + V.symbols(HERE / 'rv_resident.S', ['V3=1', 'V4=1', 'COLS=1'])['cm_buf']
        self.assertEqual(imm(c.w(DNG_MOVWT[0])) | imm(c.w(DNG_MOVWT[1])) << 16, cm)
        self.assertEqual(imm(c.w(DNG_MOVWT[2])) | imm(c.w(DNG_MOVWT[3])) << 16, cm + 72)
        for name, a in TC.OTHER_SITES.items():                             # COL-Share's sites: COL-Share's veneers
            if name in CN.SITES:
                self.assertTrue(c.veneer_ok(c.stub_at(a)), name)
        self.assertEqual(c.clist()['n'], 3)
        rec = c.cs(TC.O_REC + 4)                                          # row 1 = RAW (order 0)
        self.assertEqual(c.w(rec), 2)
        got = {c.w(rec + 4 + 8 * k) & 0xFFFF: c.w(rec + 8 + 8 * k) for k in range(2)}
        self.assertEqual(got, self.raw_rec(c))
        self.assertTrue(all(v != TC.ROOT_STOCK[o][0] for o, v in got.items()))
        self.assertEqual((c.cs(TC.O_EFFMIN + 4), c.cs(TC.O_EFFMAX + 4)), (0xFFFFFFFB, 5))   # SA -5 / GA +5 (Bei 11-08)
        self.assertEqual((c.cs(SNAP + 4), c.cs(LIVE + 4)), (1, c.cb() + CB_BOX))   # snap, live word
        self.assertNotEqual(c.cs(GLYPH + 4), 0)
        self.assertEqual((c.cs(SNAP + 8), c.cs(LIVE + 8), c.cs(GLYPH + 8)), (0, 0, 0))   # LUT (no box): the plain box
        self.assertNotEqual(c.cs(TC.O_REC + 8), 0)                          # LUT A, B: rows 2, 3
        # the copies equal stock until RAW is in effect
        mode, mat = self.raw_rec(c)[0x70], self.raw_rec(c)[0x08]
        self.assertEqual(bytes(c.mu.mem_read(mode, 0x120)), bytes(c.mu.mem_read(0xC0B3D670, 0x120)))
        self.assertEqual(bytes(c.mu.mem_read(mat, 35 * 24)), bytes(c.mu.mem_read(0xC0B39CC8, 35 * 24)))
        self.assertEqual(c.rv_calls, [])

    def test_the_row_table_puts_raw_first(self):
        c = self.cam()
        tab = c.table()
        self.assertEqual(tab[16:19], [(0xC, 16), (0xC, 17), (0xC, 18)])
        icon = (HERE / 'rv_raw_icon.xci').read_bytes()
        table = self.ui.redirect_table(c)
        copies = [bytes(c.mu.mem_read(cp, n)) for cp, n in table.values()]
        self.assertIn(icon, copies)                                       # cb_icon's tile, copied into a donor

    # ------------------------------------------------------------------ switching
    def test_switching_lut_raw_stock_writes_the_records_and_restores_stock(self):
        c = self.cam(residue=OFF_COLOR)
        self.pick(c, 15)
        self.assertEqual(c.roots(), TC.ROOT_STOCK)
        log = c.root_writes()
        self.pick(c, 16)                                                  # RAW
        self.assertEqual([o for o, _ in log], [0x70, 0x08])
        r = c.roots(); want = self.raw_rec(c)
        self.assertEqual({o: p for o, (p, _n) in r.items()},
                         {o: want.get(o, TC.ROOT_STOCK[o][0]) for o in TC.ROOT_STOCK})
        self.assertEqual({o: n for o, (_p, n) in r.items()}, {o: n for o, (_p, n) in TC.ROOT_STOCK.items()})
        self.assertEqual(c.cs(TC.O_SHOWN), 1)
        del log[:]
        self.pick(c, 17)                                                  # LUT A: its record; +0x70 / +0x08 its own
        self.assertEqual([o for o, _ in log], TC.LUT_ORDER)
        self.assertTrue(all(c.w(ROOT + o) not in (want[o], TC.ROOT_STOCK[o][0]) for o in (0x70, 0x08)))
        del log[:]
        self.pick(c, 16)                                                  # back to RAW: LUT's words stock, reverse
        offs = [o for o, _ in log]
        self.assertEqual(offs[:5], [0x4C, 0x48, 0x50, 0x28, 0x10])        # LUT's own, reverse, skipping 0x70/0x08
        self.assertEqual(offs[5:], [0x70, 0x08])
        self.assertEqual({o: p for o, (p, _n) in c.roots().items()},
                         {o: want.get(o, TC.ROOT_STOCK[o][0]) for o in TC.ROOT_STOCK})
        del log[:]
        self.pick(c, 15)                                                  # OFF: stock, reverse of RAW's
        self.assertEqual([o for o, _ in log], [0x08, 0x70])
        self.assertEqual(c.roots(), TC.ROOT_STOCK)
        self.pick(c, 16); self.ui.setter(c, 3)                            # RAW, then a stock mode: stock
        self.assertEqual(c.roots(), TC.ROOT_STOCK)

    def test_on_pick_follows_the_menu_and_one_row_is_active(self):
        c = self.cam(residue=OFF_COLOR)
        res, cb = c.res(), c.cb()
        self.assertEqual(c.clist()['active'], 2)                           # LUT A (library), RAW not remembered
        c.run(c.w(TC.V25), r0=0); self.pick(c, 16); self.close(c)
        self.assertEqual((c.w(res + P_FLAG), c.w(cb + CB_PICKED)), (1, 1))
        lib = LN.L.recover(self.doc, c.written.get(LN.BIN, c.files[LN.BIN]))
        self.assertIsNone(lib['active'])                                   # LUT was told: COLS_NONE
        c.run(c.w(TC.V25), r0=0); self.pick(c, 18); self.close(c)          # LUT B
        self.assertEqual((c.w(res + P_FLAG), c.w(cb + CB_PICKED)), (0, 0))
        c.run(c.w(TC.V25), r0=0); self.pick(c, 16); self.close(c)
        api = c.api()                                                      # a resync (LUT changed()) keeps RAW
        c.call(c.w(api + 12) & ~1, r0=api, r1=LUT_ID, thumb=bool(c.w(api + 12) & 1))
        self.assertEqual((c.clist()['active'], c.cs(TC.O_SHOWN)), (1, 1))

    # ------------------------------------------------------------------ the box: SA / GA (Bei 11-08)
    def ef(self, c, v):
        return c.run(c.stub_at(EF_SITE), r1=v & 0xFFFFFFFF)

    def en(self, c):
        r = c.run(c.stub_at(EN_SITE), r7=0xC)
        return r - (1 << 32) if r >> 31 else r

    def test_the_box_on_the_raw_row_snaps_sa_ga_and_persists(self):
        c = self.cam(residue=OFF_COLOR)
        res, cb = c.res(), c.cb()
        c.run(c.w(TC.V25), r0=0); self.pick(c, 16)
        self.assertEqual(self.en(c), -5)                                   # SA (0.3.1's default)
        self.assertEqual(self.ef(c, -4), 0)                                # a step up from -5: GA
        self.assertEqual((c.clist()['eff'][1], c.w(cb + CB_BOX)), (5, 5))  # live at once
        self.assertEqual(self.en(c), 5)
        posts = [(n, v) for n, v in c.posts][-2:]
        self.assertEqual([v for _n, v in posts], [5, 5])                   # the box (AJ and FIX) back on +5
        self.assertEqual(self.gain(c), 7)
        self.assertEqual(c.w(res + P_VAR), 1)                              # the curve follows before the close
        self.ef(c, 5)                                                      # our own publish echoing: no move
        self.assertEqual(c.clist()['eff'][1], 5)
        self.close(c)                                                      # strength_set: GA
        self.assertEqual(c.w(res + P_VAR), 1)
        got = self.save(c)
        self.assertEqual(struct.unpack('<3I', got[CFG_OFF:CFG_OFF + 12]), (V.CFG_MAGIC, 1, 1))
        nxt = dict(self.all); nxt[LN.BIN] = c.written[LN.BIN]
        d = self.cam(nxt, residue={**OFF_COLOR, SITE_A: 0xEB0DEAD0}, sup=got)     # warm: a past boot's residue
        self.assertEqual((d.clist()['active'], d.w(d.cb() + CB_BOX), d.w(d.res() + P_VAR)), (1, 5, 1))
        self.assertEqual(d.clist()['eff'][1], 5)
        self.assertEqual(self.en(d), 5)
        self.ef(d, 4)                                                      # a step down: SA
        self.assertEqual((d.clist()['eff'][1], d.w(d.cb() + CB_BOX)), (-5, 0xFFFFFFFB))
        self.close(d)
        self.assertEqual(d.w(d.res() + P_VAR), 0)

    def test_switching_rows_changes_the_box(self):
        c = self.cam(residue=OFF_COLOR)
        self.pick(c, 16)
        self.ef(c, -3)
        self.assertEqual(c.clist()['eff'][1], 5)                           # RAW: snapped
        self.pick(c, 17)                                                   # LUT A: -5..0, no snap, no live word
        before = c.w(c.cb() + CB_BOX)
        self.assertEqual(self.en(c), c.clist()['eff'][2])
        self.ef(c, 3)
        self.assertEqual(c.clist()['eff'][2], 0)                           # clamped to LUT's max
        self.ef(c, -2)
        self.assertEqual(c.clist()['eff'][2], -2)
        self.assertEqual(c.w(c.cb() + CB_BOX), before)
        self.pick(c, 16)
        self.assertEqual(self.en(c), 5)

    def glyph(self, c, name, container=0x177):
        from unicorn import arm_const
        w = c.w(AI); hw1, hw2 = w & 0xFFFF, w >> 16
        self.assertEqual((hw1 & 0xF800, hw2 & 0xD000), (0xF000, 0xD000))   # BL
        sg = (hw1 >> 10) & 1; j1 = (hw2 >> 13) & 1; j2 = (hw2 >> 11) & 1
        off = sg << 24 | (1 ^ (j1 ^ sg)) << 23 | (1 ^ (j2 ^ sg)) << 22 | (hw1 & 0x3FF) << 12 | (hw2 & 0x7FF) << 1
        ven = (AI + 4 + (off - (1 << 25) if sg else off)) & 0xFFFFFFFF
        self.assertEqual((c.w(ven), c.w(ven + 4), c.w(ven + 8)), (0xC004F8DF, 0xF004F8DF, c.stub_ctx()))
        node = c.SCRATCH + 0x600
        c.put(node + 0x18, container)
        c.mu.reg_write(arm_const.UC_ARM_REG_R11, node)
        c.rv_r2.clear()
        c.call(ven, r2=name, thumb=True)
        return c.rv_r2[-1]

    def test_the_box_glyphs_follow_the_raw_row(self):
        c = self.cam(residue=OFF_COLOR)
        self.pick(c, 16)
        self.assertEqual([self.glyph(c, n) for n in (K06, K07, LB5)], [ID_S, ID_G, ID_A])
        self.assertEqual(self.glyph(c, K06, container=0x200), K06)         # not the effect box
        self.assertEqual(self.glyph(c, 0xC18E6000), 0xC18E6000)            # not in the table
        self.pick(c, 17)                                                   # LUT row: stock glyphs
        self.assertEqual(self.glyph(c, K06), K06)
        c.run(c.stub_at(CN.SITES['MA2']), r1=16)                         # cursor on RAW, LUT still active
        self.assertEqual((c.clist()['cur'], c.clist()['active']), (16, 2))
        self.assertEqual(self.glyph(c, K06), K06)

    def test_a_version_1_client_has_no_box_field(self):
        """A client that says api 1: whatever lies past its struct's arg is not a box() (here: RAW-View's cb_box).
        LUT is a v3 client since 2026-11-10 (icon(COLS_NONE)); its struct is made to say 1 for this."""
        c = self.cam(residue=OFF_COLOR)
        _api, state = c.lut()
        blob = bytes(c.mu.mem_read(state, 4096))
        at = next(i for i in range(0, 4096, 4) if struct.unpack_from('<I', blob, i)[0] == 0x3143434C)
        client = state + at + 120                                          # struct lut_cols .client (cols.h, CL_MAX 12)
        self.assertEqual((c.w(client), c.w(client + 4)), (0x31434C43, 3))
        c.put(client + 4, 1)                                               # a version-1 client
        c.put(client + 48, c.w(c.cb() + 56 + 48))                          # box = cb_box
        api = c.api()
        c.call(c.w(api + 12) & ~1, r0=api, r1=LUT_ID, thumb=bool(c.w(api + 12) & 1))
        self.assertEqual([c.cs(o + 8) for o in (SNAP, LIVE, GLYPH)], [0, 0, 0])

    # ------------------------------------------------------------------ the copies follow the gain stub
    def test_gain_stub_switches_the_copies_not_the_root(self):
        c = self.cam(residue=OFF_COLOR)
        res = c.res()
        mode, mat = self.raw_rec(c)[0x70], self.raw_rec(c)[0x08]
        sat = [struct.unpack('<6I', bytes(c.mu.mem_read(res + P_SATTAB + 24 * k, 24))) for k in range(2)]
        self.assertEqual(self.gain(c), 0)                                  # LUT shown: nothing, stock gain
        self.assertEqual((c.w(res + P_EFF), c.w(mode + 0x11C)), (0, 82))
        self.pick(c, 16)
        c.put(res + P_SAT, 1)
        log = c.root_writes()
        c.put(KEY_CTX0, 0x1234)
        self.assertEqual(self.gain(c), 7)                                  # RAW in effect: 12-bit rule
        self.assertEqual(log, [])                                          # the root is COL-Share's
        self.assertEqual(c.w(res + P_EFF), 1)
        self.assertEqual(c.w(mode + 0x11C), c.w(res + P_MODEN))
        self.assertEqual(struct.unpack('<6I', bytes(c.mu.mem_read(mat + 34 * 24, 24))), sat[1])
        self.assertEqual(c.w(KEY_CTX0), 0xFFFFFFFF)
        c.put(BANK_A + 0x784, 1)                                           # MOV: not in effect, stock contents
        self.assertEqual(self.gain(c), 0)
        self.assertEqual((c.w(res + P_EFF), c.w(mode + 0x11C)), (0, 82))
        self.assertEqual(struct.unpack('<6I', bytes(c.mu.mem_read(mat + 34 * 24, 24))), sat[0])
        c.put(BANK_A + 0x784, 0)
        self.gain(c)
        self.pick(c, 17)                                                   # LUT: RAW not shown -> stock contents
        self.gain(c)
        self.assertEqual((c.w(res + P_EFF), c.w(mode + 0x11C)), (0, 82))
        self.assertEqual(struct.unpack('<6I', bytes(c.mu.mem_read(mat + 34 * 24, 24))), sat[0])

    def test_playback_command_puts_stock_contents_back(self):
        c = self.cam(residue=OFF_COLOR)
        res = c.res()
        mode = self.raw_rec(c)[0x70]
        self.pick(c, 16)
        self.gain(c)
        self.assertEqual(c.w(res + P_EFF), 1)
        log = c.root_writes()
        c.run(res + self.facts['res_syms']['stub_pq'], r1=0xC)
        self.assertEqual(c.rv_calls, [PQ_ORIG])
        self.assertEqual(log, [])
        self.assertEqual((c.w(res + P_EFF), c.w(mode + 0x11C)), (2, 82))

    def test_the_boxes_act_only_while_the_root_shows_raw(self):
        c = self.cam(residue=OFF_COLOR)
        res = c.res()
        self.assertEqual(c.run(res + self.facts['res_syms']['stub_sa'], r1=1), 0x55)   # LUT row: the stock conversion
        self.assertEqual(c.rv_calls, [SA_CONV])
        self.pick(c, 16)
        self.assertEqual(c.run(res + self.facts['res_syms']['stub_sa'], r1=1), 0)
        self.assertEqual(c.w(res + P_SAT), 1)
        self.assertEqual(c.run(res + self.facts['res_syms']['stub_zc'], r1=1), 0)
        self.assertEqual(c.w(res + P_CON), 1)
        self.assertEqual(c.rv_calls, [SA_CONV])

    # ------------------------------------------------------------------ the record in its own file, boot
    def save(self, c, color=0xC, group=0):
        from unicorn import arm_const
        obj = c.SCRATCH + 0x400
        c.mu.mem_write(obj, b'\0' * 0x5900)
        c.put(obj + SV_GROUP, group); c.put(obj + SV_COLOR, color)
        c.mu.reg_write(arm_const.UC_ARM_REG_R4, obj)
        r0, _sp = c.call(c.res() + self.facts['res_syms']['stub_sv'], r0=0x11, sp=(U.N.T3.STACK - 0x1000) & ~7)
        self.assertEqual(r0, 0x55)
        return c.written.get(RV_FILE)

    def test_the_pick_is_saved_into_its_own_file_and_restored_through_picked(self):
        c = self.cam(residue=OFF_COLOR)
        c.run(c.w(TC.V25), r0=0); self.pick(c, 16); self.close(c)
        c.put(c.res() + P_SAT, 1); c.put(c.res() + P_VAR, 1)
        got = self.save(c)
        self.assertEqual(got[:CFG_OFF], self.sup[:CFG_OFF])
        self.assertEqual(got[CFG_OFF + 32:], self.sup[CFG_OFF + 32:])
        self.assertEqual(struct.unpack('<5I', got[CFG_OFF:CFG_OFF + 20]), (V.CFG_MAGIC, 1, 1, 0, 1))
        nxt = dict(self.all); nxt[LN.BIN] = c.written[LN.BIN]              # LUT was told COLS_NONE (saved)
        d = self.cam(nxt, residue=OFF_COLOR, sup=got)                       # next boot
        self.assertEqual((d.clist()['active'], d.cs(TC.O_SHOWN)), (1, 1))
        self.assertEqual({o: d.w(ROOT + o) for o in (0x70, 0x08)}, self.raw_rec(d))
        self.assertEqual((d.w(d.res() + P_SAT), d.w(d.res() + P_VAR), d.w(d.res() + P_FLAG)), (1, 1, 1))
        lib = LN.L.recover(self.doc, d.written.get(LN.BIN, d.files[LN.BIN]))
        self.assertIsNone(lib['active'])                                    # one active row in the whole system
        f = self.cam(residue=OFF_COLOR, sup=got)                            # LUT still names A: registered first, it wins
        self.assertEqual((f.clist()['active'], f.w(f.cb() + CB_PICKED)), (2, 0))   # RAW told COLS_NONE
        e = self.cam(nxt, residue={BANK_A + 0x12C: 3}, sup=got)             # COLOR changed without the card
        self.assertEqual((e.clist()['active'], e.cs(TC.O_SHOWN), e.w(e.res() + P_FLAG)), (0, 0, 0))

    def test_a_replaced_file_is_not_written(self):
        c = self.cam(residue=OFF_COLOR)
        c.run(c.w(TC.V25), r0=0); self.pick(c, 16); self.close(c)
        c.files[RV_FILE] = b'\0' * len(self.sup); c.written.pop(RV_FILE, None)
        self.save(c)
        self.assertNotIn(RV_FILE, c.written)

    # ------------------------------------------------------------------ order, absence
    def state(self, c):
        L = c.clist()
        return dict(n=L['n'], active=L['active'], tab=c.table(), shown=c.cs(TC.O_SHOWN),
                    rows=[c.cs(TC.O_EFFMIN + 4 * j) for j in range(4)],
                    csv=[bytes(c.mu.mem_read(*self.ui.redirect_table(c)[a])) for _n, a, _s in TC.CU.CSV])

    def test_both_load_orders_give_the_same_rows(self):
        cfg = self.with_cfg(V.CFG_MAGIC, 1, 0, 0, 0)                       # RAW remembered, LUT none
        p = self.cam(residue=OFF_COLOR)
        p.run(p.w(TC.V25), r0=0); self.pick(p, 16); self.close(p)
        base = dict(self.all); base[LN.BIN] = p.written[LN.BIN]
        a = self.cam(base, residue=OFF_COLOR, sup=cfg)
        files = dict(base); files['\\fpSup\\ZZ' + TC.CS.NV.file_name('COLS')] = files.pop(TC.COLS_FILE)
        b = self.cam(files, residue=OFF_COLOR, sup=cfg)
        self.assertEqual(self.state(a), self.state(b))
        self.assertEqual((self.state(b)['n'], self.state(b)['active'], self.state(b)['shown']), (3, 1, 1))
        self.assertEqual(self.claims(b, V.COLS_FILE), 0)                    # early: its claims in COL-Share's entry
        self.assertEqual(self.claims(b, 'COL-Share'), 24 + 20 + 19)         # (LUT's too, as before; 19 since the CKNEE, JFIT v6)
        for x in (a, b):
            for s in self.sites:
                self.assertNotEqual(x.w(s), TC.stock(s), hex(s))
            self.assertEqual({o: x.w(ROOT + o) for o in (0x70, 0x08)}, self.raw_rec(x))
        cb = b.cb()
        self.assertEqual((b.w(cb + CB_ROWED), b.w(cb + CB_ROW + 8)), (1, 0))   # the page row's reason cleared

    def test_without_col_share_no_row_no_point_and_the_page_says_why(self):
        files = {p: d for p, d in self.all.items() if p != TC.COLS_FILE}
        c = self.cam(files, residue=OFF_COLOR)
        self.assertEqual(self.claims(c, V.COLS_FILE), 0)
        for a in self.sites:
            self.assertEqual(c.w(a), TC.stock(a), hex(a))
        self.assertEqual({o: c.w(ROOT + o) for o in (0x08, 0x70)}, {o: TC.stock(ROOT + o) for o in (0x08, 0x70)})
        self.assertTrue(any('RAW-View: no COL-Share' in l for l in c.log_lines()), c.log_lines())
        # the fpSup page: an ACTION row "RAW-View" / "needs COL-Share" (found through the core's page_row)
        n = c.callsvc('page_count')
        found = []
        for i in range(n):
            r = c.callsvc('page_row', r1=i)
            found.append((c.cstr(c.w(r + 4)), c.cstr(c.w(r + 8)) if c.w(r + 8) else None))
        self.assertIn(('RAW-View', 'needs COL-Share'), found)

    # ------------------------------------------------------------------ power-off, warm boot
    def test_power_off_puts_every_word_back(self):
        c = self.cam(residue=OFF_COLOR)
        self.pick(c, 16)
        self.gain(c)
        c.power_off()
        self.assertEqual(c.roots(), TC.ROOT_STOCK)
        for a, s in self.sites.items():
            self.assertEqual(bytes(c.mu.mem_read(a, len(s))), s, hex(a))
        for name, a in TC.OTHER_SITES.items():
            self.assertEqual(c.w(a), TC.stock(a), name)

    def test_a_warm_boots_residue_is_repaired_then_armed(self):
        res = {SITE_A: 0xEB0DEAD0, SV: 0xEB0DEAD0, DNG_MOVWT[0]: 0xE3012345, ROOT + 0x70: 0x40404040}
        c = self.cam(residue={**res, **OFF_COLOR})
        self.assertEqual(self.claims(c, V.COLS_FILE), 20)
        rep = [l for l in c.log_lines() if l.startswith('0C')]
        for a in (SITE_A, SV, DNG_MOVWT[0]):
            self.assertTrue(any('%08X' % a in l for l in rep), (hex(a), rep))
        self.assertEqual(self.state(c), self.state(self.cam(residue=OFF_COLOR)))
        self.assertEqual(c.w(c.res() + self.facts['res_syms']['sv_next']), SV_ORIG)

    # ------------------------------------------------------------------ LUT's custom DNG matrix
    def test_luts_custom_dng_matrix_reaches_the_redirected_off_constants(self):
        """RAW-View points FUN_c02c4a50's OFF constants (movw / movt r2) at its cm_buf; LUT's custom-matrix
        swap (dng.c) writes where the writer reads now, and puts it back.  The writer is modelled reading
        through those instruction words, as the firmware does."""
        import test_dng_native as DN

        class Cam(DN.Camera, Camera):
            def _hook(self, mu, addr, size, data):
                if addr == DN.CM:
                    a = imm(self.w(DNG_MOVWT[0])) | imm(self.w(DNG_MOVWT[1])) << 16
                    d = imm(self.w(DNG_MOVWT[2])) | imm(self.w(DNG_MOVWT[3])) << 16
                    self.writes.append((addr, None, bytes(mu.mem_read(a, 72)) + bytes(mu.mem_read(d, 72))))
                    return self._ret(0)
                return super()._hook(mu, addr, size, data)

        DN.DngNativeTests.setUpClass.__func__(K := type('K', (), {}))
        try:
            files = dict(K.dfiles); files[RV_FILE] = self.sup
            c = Cam.__new__(Cam); c.residue = OFF_COLOR; c.facts = self.facts; c.cb_off = self.cb_off
            Cam.__init__(c, files, K.ar)
            cm = c.res() + V.symbols(HERE / 'rv_resident.S', ['V3=1', 'V4=1', 'COLS=1'])['cm_buf']
            stock = bytes(c.mu.mem_read(cm, 144))
            rows = [e['filename'] for e in K.ddoc['luts'] if e['enabled']]
            self.pick(c, 17 + rows.index('C.cube'))                      # RAW is row 1
            _layers, m = LN.L.layer_fields(LN.L.find(K.ddoc, 'C.cube'))
            want = b''.join(struct.pack('<d', v / 2 ** 20) for v in m[0] + m[1])
            c.write_dng(0xC02C6920)
            self.assertEqual(c.writes[0][2], want)
            self.assertEqual(bytes(c.mu.mem_read(cm, 144)), stock)          # put back
            self.pick(c, 16)                                                # RAW: LUT's swap stays out
            c.write_dng(0xC02C6920)
            self.assertEqual(c.writes[0][2], stock)
        finally:
            K.temp.cleanup()


if __name__ == '__main__':
    unittest.main()
