"""The COLOR list's LUT rows -- COL-Share (fpSup/colshare) + LUT (native/cols.c) as clients
since 2026-11-07 -- on the actual ARM bytes, offline.  Every assertion of the clist.c
version holds on the pair: the sixteen sites, the copies, the rows, the box, the labels.

The stock functions the stubs tail-call are modelled here (GUI <-> enum reads
the table through the getter words the install patched, as the firmware's
getter does); the stubs, both entries, the FPUI copies and the syncs are real.
No claim about the camera's list drawing, its parse timing or the icons'
cache (projects/lut-sup/notes/NATIVE_COLOR_LIST_RESEARCH.md: to verify).
"""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'colshare'))
import build_colshare as CS
import colshare_ui as CU
import import_ui as IU
import test_library_native as LN
import test_sup_ui as U

GUI_TO_ENUM, GUI_TO_ENUM_AJ, ENUM_TO_GUI = 0xC06C0718, 0xC06C07E8, 0xC06C0768
EF_CONV, EN_CONV, PUBLISH = 0xC06C0D20, 0xC06C0D70, 0xC0593F30
V25, V26 = 0xC05687E0, 0xC0568888
COLOR_ITEM = 0xC31ACDC4
SITES = {'MA1': 0xC0568950, 'MA2': 0xC056D028, 'MA3': 0xC05818B8, 'MJ': 0xC05689A8, 'MB': 0xC0595734,
         'ML': 0xC059DA1C, 'MC': 0xC0075CF4, 'EF': 0xC0568A3C, 'EN': 0xC0595908, 'ENF': 0xC05957B0}
SET_BANK_A, OFF_COLOR = 0xC31B32BC, 0x12C
STOCK_GUI = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (15, 6), (6, 7), (7, 8), (8, 9), (13, 10),
             (9, 11), (10, 12), (14, 13), (11, 14), (12, 15)]


class Camera(LN.Camera):
    def __init__(self, files, autorun):
        self.models = []
        super().__init__(files, autorun)

    def page_entries(self):
        super().page_entries()
        for a in (GUI_TO_ENUM, GUI_TO_ENUM_AJ, ENUM_TO_GUI, EF_CONV, EN_CONV, V25, V26):
            self.by_addr[a] = 'CLIST_MODEL'
        self.by_addr[0xC05818BC] = 'CLIST_QS_RET'      # QS's caller after its GUI -> enum: stop here

    def table(self):
        """The GUI <-> enum table as the getter now names it (movw / movt r2, mov r2, #n)."""
        lo, hi, cnt = self.w(0xC06C07CC), self.w(0xC06C07D0), self.w(0xC06C07D8)
        imm = lambda w: ((w >> 4) & 0xF000) | (w & 0xFFF)
        at = imm(lo) | imm(hi) << 16
        return [struct.unpack_from('<2I', self.mu.mem_read(at + 8 * i, 8)) for i in range(cnt & 0xFF)]

    def _hook(self, mu, addr, size, data):
        if self.by_addr.get(addr) == 'CLIST_QS_RET':
            return mu.reg_write(U.N.T3.UC_ARM_REG_PC, U.N.T3.DONE)
        if self.by_addr.get(addr) == 'CLIST_MODEL':
            r0, r1 = self.r(U.N.T3.UC_ARM_REG_R0), self.r(U.N.T3.UC_ARM_REG_R1)
            self.models.append((addr, r0, r1))
            if addr in (GUI_TO_ENUM, GUI_TO_ENUM_AJ):
                return self._ret(next((e for e, g in self.table() if g == r1), 0xFFFFFFFF))
            if addr == ENUM_TO_GUI:
                return self._ret(next((g for e, g in self.table() if e == r0), 0xFFFFFFFF))
            if addr == EF_CONV:
                return self._ret(r1 & 0xFF)
            if addr == EN_CONV:
                return self._ret(0x77)
            return self._ret(0)
        return super()._hook(mu, addr, size, data)

    def stub_at(self, site):
        """The stub a patched `bl` site reaches through its veneer."""
        w = self.w(site)
        assert w >> 24 == 0xEB, hex(w)
        off = (w & 0xFFFFFF) << 2
        veneer = (site + 8 + (off - (1 << 26) if off & (1 << 25) else off)) & 0xFFFFFFFF
        return veneer                                  # ldr ip, [pc]; ldr pc, [pc]; context; stub

    def veneer_ok(self, veneer):
        return self.w(veneer) == 0xE59FC000 and self.w(veneer + 4) == 0xE59FF000

    EXTRA = {'r4': 'UC_ARM_REG_R4', 'r6': 'UC_ARM_REG_R6', 'r7': 'UC_ARM_REG_R7', 'sl': 'UC_ARM_REG_R10'}

    def run(self, pc, lr=None, **regs):
        """Call `pc` (ARM) with r0..r2 and the callee-saved registers the stubs read."""
        from unicorn import arm_const
        for k in [k for k in regs if k in self.EXTRA]:
            self.mu.reg_write(getattr(arm_const, self.EXTRA[k]), regs.pop(k) & 0xFFFFFFFF)
        kw = {} if lr is None else {'lr': lr}
        return self.call(pc, **kw, **regs)[0]

    def clist(self):
        """struct cols' head (colshare.c; clist.h's names): through the stubs' context word."""
        ctx = self.stub_ctx()
        m = CU.ROWS_PRODUCT
        words = struct.unpack(f'<{8 + m + 1}I', self.mu.mem_read(ctx, 4 * (8 + m + 1)))
        names = ('magic', 'n', 'active', 'pend', 'cur', 'menu', 'changed')
        out = dict(zip(names, words))
        out['eff'] = [struct.unpack('<i', struct.pack('<I', w))[0] for w in words[7:8 + m]]
        out['eff_dirty'] = words[8 + m]
        return out

    def stub_ctx(self):
        """COL-Share's struct cols (colshare.c), the context word of every veneer."""
        v = self.stub_at(SITES['MB'])
        assert self.veneer_ok(v)
        return self.w(v + 8)

    COLS_PAGE = CS.layout(CU.ROWS_PRODUCT)['page']   # colshare.c struct cols .page (build_colshare.layout)

    def lut_cols(self):
        """LUT's struct lut_cols (native/cols.h), found by its magic in the LUT state."""
        _api, state = self.lut()
        blob = bytes(self.mu.mem_read(state, 4096))
        at = next(i for i in range(0, 4096, 4) if struct.unpack_from('<I', blob, i)[0] == 0x3143434C)
        w = struct.unpack_from('<7I', blob, at)
        return dict(magic=w[0], attached=w[1], n=w[2], map=list(w[3:7]))

@unittest.skipIf(U.N.T4.Uc is None or not U.N.T3.IMAGE.exists(), 'requires Unicorn and firmware; skipped is unverified')
class ClistNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): LN.LibraryNativeTests.setUpClass.__func__(cls)     # the same cubes and card

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def cam(self, files=None, color=0xC):
        c = Camera(files or self.files, self.ar)
        return c

    def test_install_patches_every_site_and_sync_fills_two_rows(self):
        c = self.cam()
        api, _state = c.lut()
        self.assertEqual(c.w(api + 9 * 4), 0, 'clist_install result')
        for name, site in SITES.items():
            self.assertEqual(c.w(site) >> 24, 0xEB, name)
        self.assertEqual(c.w(0xC06C07D8), 0xE3A02000 | (16 + CU.ROWS_PRODUCT))
        self.assertEqual(c.w(0xC1D6ED48), CS.adv_word(CU.ROWS_PRODUCT))
        L = c.clist()
        self.assertEqual((L['magic'], L['n']), (0x4E55524C, 2))            # A, B on; Unknown not set up
        tab = c.table()
        stock = [struct.unpack('<2I', U.N.T3.IMAGE.read_bytes()[0x2E412BC + 8 * i:0x2E412BC + 8 * i + 8]) for i in range(16)]
        self.assertEqual(tab[:16], stock)
        self.assertEqual(tab[16:], [(0xC, 16 + j) for j in range(CU.ROWS_PRODUCT)])

    def test_power_off_puts_the_shared_file_redirect_back(self):
        """Camera 2026-11-04 (validation/20261104-lvb-sup-01, bisect B2..B5): the block's
        HOOK_FV B.W at C05E5BEC was never claimed, so the core did not write it back;
        a poff restart kept it, pointing into a heap that boot had reused -> froze."""
        c = self.cam()
        api, _state = c.lut()
        self.assertEqual(c.w(api + 9 * 4), 0, 'clist_install result')
        self.assertNotEqual(c.w(0xC05E5BEC), 0x60681840)                 # redirected while up
        objs = [o for o, _ in c.registered]
        self.assertTrue(objs)
        for o in objs:
            c.call(c.w(c.w(o) + 12), r0=o, r1=4)
        self.assertEqual(c.w(0xC05E5BEC), 0x60681840, 'C05E5BEC after power-off')
        image = U.N.T3.IMAGE.read_bytes()
        for name, site in SITES.items():                                 # the claimed sites too
            self.assertEqual(c.w(site), struct.unpack_from('<I', image, site - 0xC0000000)[0], name)

    def test_redirected_copies_hold_the_rows_and_icons_of_the_cubes_on(self):
        c = self.cam()
        table = self.redirect_table(c)
        for f, (_n, stock, _s) in enumerate(CU.CSV):
            copy, size = table[stock]
            self.assertEqual(bytes(c.mu.mem_read(copy, size)), CU.rows_csv(f, 2), CU.CSV[f][0])
        for j, name in enumerate(('A.cube', 'B.cube')):
            copy, size = table[CU.DONORS[j][1]]
            self.assertEqual(bytes(c.mu.mem_read(copy, size)), self.tile(name))   # drawn by import.c

    ATLAS = None

    def tile(self, name):
        if ClistNativeTests.ATLAS is None:
            ClistNativeTests.ATLAS = IU.atlas()
        return IU.xci_literal(IU.label_tile(name, ClistNativeTests.ATLAS))

    def redirect_table(self, c):
        w = c.w(0xC05E5BEC); hw1, hw2 = w & 0xFFFF, w >> 16
        s = (hw1 >> 10) & 1; j1 = (hw2 >> 13) & 1; j2 = (hw2 >> 11) & 1
        off = s << 24 | (1 ^ (j1 ^ s)) << 23 | (1 ^ (j2 ^ s)) << 22 | (hw1 & 0x3FF) << 12 | (hw2 & 0x7FF) << 1
        if s: off |= 0xFE000000
        entry = c.w((0xC05E5BEC + 4 + off + 4) & 0xFFFFFFFF)
        _code, ent, tw = CU.O.handler()
        table = c.w(entry - ent + tw)
        n = c.w(table + 8)
        return {c.w(table + 16 + 12 * i): (c.w(table + 20 + 12 * i), c.w(table + 24 + 12 * i)) for i in range(n)}

    def pick_row(self, c, gui, site='MA2'):
        """The menu's pick: GUI -> enum through the stub, then the setter's compare."""
        enum = c.run(c.stub_at(SITES[site]), r1=gui)
        flags_z = self.setter(c, enum)
        return enum, flags_z

    def setter(self, c, new, old=0):
        c.run(c.stub_at(SITES['MC']), r4=COLOR_ITEM, r6=new, sl=old)
        return (c.r(U.N.T3.UC_ARM_REG_CPSR) >> 30) & 1

    def test_the_colour_cursor_variables_follow_the_active_row(self):
        """11-05 camera: after a boot the COLOR cursor sat on OFF while a LUT was on -- CM_COLFIX/COLAJ_ColorMode
        (the menu's cursor, GUI values) come only from the stock notifier on an enum change, and our rows are all
        OFF's enum.  clist_sync posts them: 15 + the active row (15 = OFF)."""
        c = self.cam()
        last = lambda name: [v for n, v in c.posts if n == name][-1]
        a = c.clist()['active']
        self.assertEqual((last('CM_COLFIX_ColorMode'), last('CM_COLAJ_ColorMode')), (15 + a, 15 + a))
        other = 16 if a != 1 else 17
        self.pick_row(c, other)
        c.run(c.w(0xC0D11A00), r0=0)                   # the menu closes: the pick is saved, the list synced
        a2 = c.clist()['active']
        self.assertEqual(a2, other - 15)
        self.assertEqual((last('CM_COLFIX_ColorMode'), last('CM_COLAJ_ColorMode')), (15 + a2, 15 + a2))

    def test_picking_a_row_makes_it_active_and_every_enum_to_gui_lands_on_it(self):
        c = self.cam()
        enum, z = self.pick_row(c, 17)                 # the second LUT row
        self.assertEqual((enum, z), (0xC, 0))           # Z = 0: the stock 'changed' path
        L = c.clist()
        self.assertEqual((L['active'], L['changed'], L['pend']), (2, 1, 0))
        self.assertEqual(c.run(c.stub_at(SITES['MB']), r0=0xC), 17)
        self.assertEqual(c.run(c.stub_at(SITES['ML']), r0=0xC), 15)     # LV_ColorMode: 16.. are tints
        tab = c.table()
        self.assertEqual([g for e, g in tab if e == 0xC], [17, 15, 16] + list(range(18, 16 + CU.ROWS_PRODUCT)))
        enum, z = self.pick_row(c, 15)                 # OFF
        self.assertEqual(c.clist()['active'], 0)
        self.assertEqual(c.run(c.stub_at(SITES['MB']), r0=0xC), 15)
        self.pick_row(c, 16); self.setter(c, 3)         # a stock mode afterwards: no row
        self.assertEqual(c.clist()['active'], 0)

    def test_qs_resync_and_rows_past_n_are_not_picks(self):
        c = self.cam()
        c.run(c.stub_at(SITES['MA3']), r1=15, lr=0xC05818BC)
        self.assertEqual(c.clist()['pend'], 0)
        c.run(c.stub_at(SITES['MA2']), r1=18)          # only two rows exist
        self.assertEqual(c.clist()['pend'], 0)

    def test_the_box_is_the_active_rows_strength_and_close_saves_it(self):
        c = self.cam()
        self.pick_row(c, 16)                           # A.cube
        c.models.clear()
        self.assertEqual(c.run(c.stub_at(SITES['EF']), r1=2), 0)        # up past 0: clamped, boxes reset
        self.assertEqual(c.clist()['eff'][1], 0)
        self.assertEqual([(m[0]) for m in c.models], [])                # no stock conversion
        self.assertEqual(c.run(c.stub_at(SITES['EF']), r1=-3 & 0xFFFFFFFF), 0)
        self.assertEqual(c.clist()['eff'][1], -3)
        self.assertEqual(c.run(c.stub_at(SITES['EN']), r7=0xC), -3 & 0xFFFFFFFF)
        self.assertEqual(c.run(c.stub_at(SITES['ENF']), r7=0xC), -3 & 0xFFFFFFFF)
        self.assertEqual(c.run(c.stub_at(SITES['EN']), r7=3), 0x77)     # a stock mode: stock conversion
        mx = c.w(0xC0D11A00)
        c.run(mx, r0=0)                                # the menu closes: pick A, save 40 %
        self.assertEqual(c.status()['strength'], 40)
        saved = LN.L.recover(self.doc, c.written[LN.BIN])
        self.assertEqual(saved['active'], self.doc['luts'][0]['id'])
        self.assertEqual(LN.L.resolved(saved['luts'][0])['strength_percent'], 40)

    @staticmethod
    def old_rawview_header(version=1):
        """An FSB4 header of RAW-View (sup_id RAWV, v0.3.1's version word 1); entry 0 so the loader skips it."""
        return struct.pack('<12I', 0x34425346, 48, 48, 48, 0, 0x56574152, version, 6, 1, 0, 0, 0)

    def test_raw_view_on_the_card_keeps_its_sites_and_ours_stay_stock(self):
        """Old RAW-View (<= 0.3.x) on the card: COL-Share leaves (DESIGN.md §6, Bei #4), LUT has no rows."""
        files = dict(self.files); files['\\fpSup\\RAWV.BIN'] = self.old_rawview_header()
        c = self.cam(files)
        api, _state = c.lut()
        self.assertEqual(c.w(api + 9 * 4), 8)                            # no COL-Share
        img = U.N.T3.IMAGE.read_bytes()
        for name, site in SITES.items():
            self.assertEqual(c.w(site), struct.unpack_from('<I', img, site - 0xC0000000)[0], name)
        self.assertEqual(c.w(0xC06C07D8), 0xE3A02010)
        self.assertEqual(c.w(0xC1D6ED48), 0x00004041)
        c.open_color(); self.assertEqual(c.vars['LC_Header'][1], 'LUT (2/12)')  # the manager works (no COL-Share: CL_MAX)
        self.assertEqual(c.vars['LC_OK'][1], 'COLOR list needs COL-Share')      # and says why

    def test_the_manager_pages_never_write_into_the_colour_list(self):
        """11-05 camera: 163 UI variables in a 160-word ui_cache -- mv_forget / mv_int wrote past it into struct
        clist (magic, n, active zeroed): the COLOR list fell back to OFF.  Open the manager, a cube's settings and
        back, and the list's head must be what clist_sync left."""
        c = self.cam()
        before = c.clist()
        self.assertEqual(before['magic'], 0x4E55524C)
        c.open_color()
        c.edit('Unknown_709.cube'); c.press(70)
        c.open_color()
        after = c.clist()
        self.assertEqual((after['magic'], after['n'], after['active']), (before['magic'], before['n'], before['active']))
        lc = c.lut_cols()                                   # LUT's own side, right after ui_cache's neighbours
        self.assertEqual((lc['magic'], lc['attached'], lc['n']), (0x3143434C, 1, before['n']))

    LABEL_CLIP_STOCK = 0xC1D66BC8               # ColorButtonMenu: Text 121's text clip (owner 121, clip 2)

    def label_page(self, c):
        """The ColorButtonMenu copy the COLOR list reads: (page bytes, set start in the image)."""
        a, entry_off, n = CU.O.resource_set('ColorButtonMenu')
        L_page = c.w(c.stub_ctx() + c.COLS_PAGE)            # struct cols .page
        hdr = (L_page & ~3) - 128
        self.assertEqual(c.w(hdr), 0x47505346, 'an FSPG copy')
        length = c.w(hdr + 12)
        return bytes(c.mu.mem_read(L_page, length)), a, hdr

    def label_keys(self, c):
        """(time, text) of every key of Text 121's text clip in the copy, the text read where the
        firmware resolves it (a private id + 0x80000000, else the stock pool)."""
        page, a, _hdr = self.label_page(c)
        at = self.LABEL_CLIP_STOCK - a                      # before the insert: unmoved
        tag, size = struct.unpack_from('>II', page, at)
        self.assertEqual((tag, struct.unpack_from('>3I', page, at + 20)), (0x1000A, (121, 2, struct.unpack_from('>I', page, at + 28)[0])))
        n = struct.unpack_from('>I', page, at + 28)[0]
        self.assertEqual(size, 48 + 10 * n)
        img = U.N.T3.IMAGE.read_bytes()
        out = []
        for k in range(n):
            t, v = struct.unpack_from('>II', page, at + 48 + 10 * k + 2)
            if 0x40000000 <= v < 0x80000000:
                s = c.cstr(v + 0x80000000)
            else:
                p = 0xC18C0474 - 0xC0000000 + v
                s = img[p:img.index(b'\0', p)].decode()
            out.append((t, s))
        return out

    def test_the_big_label_names_each_lut_row(self):
        """Bei 11-07 (SS__3198): every LUT row's big name said "Off".  It is Text 121's text clip, keyed by
        GUI x 33.3 (apply-frame CM_COLAJ_ColorMode); the stock keys end at 500 (GUI 15, Off) and the copy only
        had its interval lengthened (+33 a row), so GUI 16.. held Off.  Each row needs its own key, before
        its GUI's time and after the previous one's, whose text is the row's cube."""
        c = self.cam()
        L = c.clist()
        keys = self.label_keys(c)
        self.assertEqual(len(keys), 16 + CU.MAX_ROWS)
        self.assertEqual(keys[15], (500, keys[15][1]))
        names = [e['filename'] for e in self.doc['luts']]
        on = [CU.row_label(n) for n in ('A.cube', 'B.cube')]
        for j in range(L['n']):
            gui = 16 + j
            time = gui * 100 / 3                            # the apply-frame's time for that GUI value
            shown = [s for t, s in keys if t <= time][-1]   # a text clip holds its last key
            self.assertEqual(shown, on[j], f'GUI {gui}')
        for gui in range(16):                               # the stock rows keep theirs
            self.assertEqual([s for t, s in keys if t <= gui * 100 / 3][-1], [s for t, s in keys[:16] if t <= gui * 100 / 3][-1])
        self.assertTrue(all(n in names for n in ('A.cube', 'B.cube')))
        # the interval still ends at 500 + 33 n, in the copy (past the insert), and the header's key budget
        page, a, hdr = self.label_page(c)
        text_end = CU.O.COLOR_TEXT_END - a + CU.LABEL_INSERT
        self.assertEqual(struct.unpack_from('>I', page, text_end)[0], 500 + 33 * L['n'])
        head = struct.unpack_from('>I', page, 4)[0]
        self.assertEqual(struct.unpack_from('>I', page, head - 12)[0], 16 + CU.MAX_ROWS)
        self.assertEqual((c.w(hdr + 24), c.w(c.w(hdr + 32)), c.w(c.w(hdr + 32) + 4)),
                         (1, CU.label_clip()[1], CU.LABEL_INSERT))   # the copy's one insert: ours

    def test_a_long_or_foreign_name_is_cut_and_printable(self):
        self.assertEqual(CU.row_label('Kodak2383_1.6K.cube'), 'Kodak2383_1.6K')
        self.assertEqual(CU.row_label('p2d60toARRI709_1_ABCDEFGHIJKLMNOPQRSTUVWXYZ.CUBE'),
                         'p2d60toARRI709_1_ABCDEFGHIJKLMN')
        self.assertEqual(CU.row_label('色.cube'), '???')
        self.assertEqual(CU.row_label('.cube'), '?')

    def test_turning_a_cube_on_in_the_manager_adds_its_row(self):
        c = self.cam()
        c.open_color()
        c.edit('Unknown_709.cube'); c.choose('Color space', 6); c.choose('Gamma', 1); c.press(70)
        c.choose('Unknown_709.cube', 1)
        self.assertEqual(c.clist()['n'], 3)
        table = self.redirect_table(c)
        copy, size = table[CU.CSV[0][1]]
        self.assertEqual(bytes(c.mu.mem_read(copy, size)), CU.rows_csv(0, 3))
        copy, size = table[CU.DONORS[2][1]]
        self.assertEqual(bytes(c.mu.mem_read(copy, size)), self.tile('Unknown_709.cube'))
        keys = self.label_keys(c)                       # and its big name
        self.assertEqual([s for t, s in keys if t <= 18 * 100 / 3][-1], 'Unknown_709')
        page, a, _hdr = self.label_page(c)
        self.assertEqual(struct.unpack_from('>I', page, CU.O.COLOR_TEXT_END - a + CU.LABEL_INSERT)[0], 500 + 33 * 3)


if __name__ == '__main__':
    unittest.main()
