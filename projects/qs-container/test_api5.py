"""API 5 and stock-tile replacement, real ARM under the existing offline rig."""
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

import test_qsct as Q
import test_qs_page as P

HERE = pathlib.Path(__file__).resolve().parent
REPL = lambda internal: (internal + 1) << 16
FUNCS = [('DC', 'DC', 'menu_crop', 3 | REPL(12)),
         ('RES', 'RES', 'menu_cine_resolution', 3 | REPL(23)),
         ('FPS', 'FPS', 'menu_cine_fps', 6 | REPL(25)),
         ('FORMAT', 'FORMAT', 'menu_cine_format', REPL(21)),
         ('RECIPE', 'RECIPE', 'menu_crop', 3),
         ('QR', 'QR', 'menu_lock', 4)]
STOCK = [21, 12, 23, 25, 4, 19, 0, 48]
ABSENT = [0, 4, 19, 8, 1, 3, 47, 48]
_client = None


def client():
    global _client
    if _client is None:
        src = (Q.QT.HERE / 'qstest.c').read_text()
        old = 'f->flags = QSC_F_CINE | ((c->flags[i] & Q_LOCK) ? QSC_F_LOCK_REC : 0u);'
        assert src.count(old) == 1
        src = src.replace(old, old[:-1] + ' | (c->flags[i] & QSC_REPLACE_MASK);')
        src = src.replace('USED int sup_entry',
                          'static int qt_api5_state(void *arg) { return ((struct demo *)arg)->toggle; }\n\nUSED int sup_entry')
        src = src.replace('f->state = 0;', 'f->state = i == 1u ? qt_api5_state : 0;')
        # API 6: the demo's first sub-item ("Count") counts blur() calls in demo.unfines (+20)
        src = src.replace('USED int sup_entry',
                          'static void qt_api6_blur(void *arg) { ((struct demo *)arg)->unfines++; }\n\nUSED int sup_entry', 1)
        old6 = '            s->sub[i][0].footer = qt_count_spin;'
        assert src.count(old6) == 1
        src = src.replace(old6, old6 + '\n            s->sub[i][0].blur = qt_api6_blur;')
        with tempfile.TemporaryDirectory(prefix='qsc-api5-client-') as tmp:
            p = pathlib.Path(tmp) / 'client.c'
            p.write_text(src)
            _client = Q.QT.build(funcs=FUNCS, src=p)
    return _client


_client_fs = None


def client_fine_sub():
    """API 9 (0.0.2test, SensorLab's FPS): the fine-mode FPS also has a one-item sub-QS ("Count", a spinner)"""
    global _client_fs
    if _client_fs is None:
        src = (Q.QT.HERE / 'qstest.c').read_text()
        old = 'f->flags = QSC_F_CINE | ((c->flags[i] & Q_LOCK) ? QSC_F_LOCK_REC : 0u);'
        src = src.replace(old, old[:-1] + ' | (c->flags[i] & QSC_REPLACE_MASK);')
        old = ('            f->fine = qt_fine;\n            f->flags |= QSC_F_TITLE;\n            f->arg = d;\n'
               '            f->sub = 0;\n')
        assert src.count(old) == 1
        src = src.replace(old, old.replace('            f->sub = 0;\n',
            '            s->sub[i][0].reserved = 0; s->sub[i][0].icon = 0; s->sub[i][0].small = 0; s->sub[i][0].lock = 0;\n'
            '            s->sub[i][0].label = b + c->sub_label_off[0];\n'
            '            s->sub[i][0].value = qt_count_text; s->sub[i][0].adjust = qt_count_adjust;\n'
            '            s->sub[i][0].footer = qt_count_spin; s->sub[i][0].arg = d;\n'
            '            s->subs[i].n = 1; s->subs[i].item = s->sub[i];\n'
            '            f->sub = &s->subs[i];\n'))
        with tempfile.TemporaryDirectory(prefix='qsc-api9-client-') as tmp:
            p = pathlib.Path(tmp) / 'client.c'
            p.write_text(src)
            _client_fs = Q.QT.build(funcs=FUNCS, src=p)
    return _client_fs


def boot(slots=STOCK, fine_sub=False):
    c = Q.boot([(Q.CNAME, Q.cblob()[0]), (Q.TNAME, client_fine_sub() if fine_sub else client())])
    c.layout()
    P.set_cine(c, slots)
    return c


def request(c, name, how, sup_id=0x53545351):
    api = c.callsvc('find', 0x54435351)
    assert (c.w(api), c.w(api + 4)) == (0x31415351, 9)     # 0.0.2test: API 9 (fine + sub); open() unchanged since 5
    p = Q.F6.FAKE + 0x7C00
    c.mu.mem_write(p, name.encode() + b'\0')
    c.mu.reg_write(Q.T3.UC_ARM_REG_R3, how)
    fn = c.w(api + 16)
    return c.call(fn & ~1, r0=api, r1=sup_id, r2=p, thumb=bool(fn & 1))[0]


def posted_slots(c):
    posts = dict(c.posts)
    return [posts.get(n) for n in Q.NAMES]


@Q.SKIP
class Api5(unittest.TestCase):
    def test_stock_focus_dial_and_exit_preserve_settings(self):
        c = boot()
        before = bytes(c.mu.mem_read(c.image(), 0x4F00))
        c.posts.clear()
        c.guid(23)  # the first native focus, before any dynamic UI id exists
        self.assertEqual(c.w(Q.QSOBJ + 0xBC), 55)
        self.assertEqual(posted_slots(c), [52, 49, 50, 51, c.to_ui(4), c.to_ui(19), c.to_ui(0), c.to_ui(48)])
        self.assertIn(('QS_QSMode', 50), c.posts)
        self.assertEqual(P.plain(P.texts(c)['QSC_V3']), 'N=0')
        posts = P.press(c, 1, 23)  # even a stale native id must route to our RES
        self.assertEqual(c.w(Q.QSOBJ + 0xBC), 55)
        self.assertEqual(P.plain(P.texts(c)['QSC_V3']), 'N=1')
        self.assertFalse(any(n.startswith(('MV_Resolution', 'MV_FrameRate', 'MV_RecordingFormat', 'CM_DCCrop')) for n, _ in posts))
        self.assertEqual(c.hp(23), [])
        self.assertEqual(bytes(c.mu.mem_read(c.image(), 0x4F00)), before)
        c.posts.clear()
        c.guid(23)  # a later native refresh is repaired on the next focus
        self.assertEqual(posted_slots(c)[:4], [52, 49, 50, 51])
        c.posts.clear()
        c.layout()  # restore before the next page's body/editor can observe ids
        self.assertEqual(posted_slots(c), [c.to_ui(x) for x in STOCK])
        self.assertEqual([c.slot(1, k) for k in range(8)], STOCK)
        flash = c.save()
        self.assertEqual(list(struct.unpack_from('<8I', flash, Q.ARR[1])), STOCK)
        # Replacement routing is scoped to QS, not a menu's stale focused id.
        self.assertNotEqual(c.hp(23), [])

    def test_editor_hides_replacement_rows_and_keeps_other_functions(self):
        c = boot()
        for _name, address, _size in Q.E.CSVS:
            _head, rows = Q.csv_records(c.csv(address))
            self.assertEqual(len(rows), Q.E.STOCK_ROWS + 2)
            self.assertEqual([r[3] for r in rows[-2:]], ['RECIPE', 'QR'])
            self.assertEqual([int(r[1]) for r in rows[-2:]], [53, 54])
            self.assertEqual([int(r[0]) for r in rows[-2:]], [33, 34])
        # The hidden functions keep stable runtime ids; only the list is short.
        self.assertEqual(c.to_int(50), 55)
        self.assertEqual(c.to_ui(55), 50)
        for p, page in enumerate(Q.E.PAGES):
            _a, data, hdr, _off = c.page_copy(p)
            _r, _o, tiles = Q.copy_tiles(data)
            _h, rows = Q.csv_records(c.csv(Q.E.CSVS[Q.E.PAGE_CSV[page]][1]))
            for i, stock_id in enumerate((12, 23, 25, 21, None, None)):
                row_ui = c.to_ui(stock_id) if stock_id is not None else 49 + i
                row = next(j for j, r in enumerate(rows) if r[1] == str(row_ui))
                for tile in tiles:
                    self.assertEqual(Q.page_build_state(tile, 49 + i)['row'], float(row), (page, i))
            ds = Q.EditorPages.deltas(self, c, hdr)
            vm = Q.E.visible_max(page)
            shift = sum(n for at, n in ds if at <= vm)
            self.assertEqual(struct.unpack_from('>f', data, vm + shift)[0], 33.0)
            for (pos, _old), want in zip(Q.E.total_digits(page), (3, 4)):
                shift = sum(n for at, n in ds if at <= pos)
                self.assertEqual(Q.E.pool_str(Q.E.be(data, pos + shift)), f'font_menu_S_{want}')

    def test_sub_open_is_queued_once_and_returns_to_replacement(self):
        c = boot()
        self.assertEqual(request(c, 'RES', 1), 1)
        self.assertEqual(P.st(c, 'sub_open'), -1)
        c.layout()  # the menu->QS transition does not consume the request
        c.guid(21)
        self.assertEqual((P.st(c, 'sub_open'), c.w(Q.QSOBJ + 0xBC)), (1, 70))
        P.press(c, 5, 70)
        self.assertEqual(P.st(c, 'sub_open'), -1)
        self.assertEqual(c.w(Q.QSOBJ + 0xBC), 55)
        self.assertEqual(posted_slots(c)[:4], [52, 49, 50, 51])
        c.guid(23)
        self.assertEqual(P.st(c, 'sub_open'), -1, 'consumed request must not reopen')
        self.assertEqual([c.slot(1, k) for k in range(8)], STOCK)

    def test_absent_function_opens_standalone_sub_or_fine(self):
        c = boot(ABSENT)
        self.assertEqual(request(c, 'RES', 1), 1)
        c.guid(0)
        self.assertEqual(P.st(c, 'sub_open'), 1)
        self.assertEqual(posted_slots(c), [65, 66, 67, 68, 72, 72, 72, 72])
        P.press(c, 5, 70)
        self.assertEqual(posted_slots(c), [c.to_ui(x) for x in ABSENT])
        self.assertEqual(c.w(Q.QSOBJ + 0xBC), ABSENT[0])
        self.assertEqual(request(c, 'FPS', 2), 1)
        c.guid(0)
        self.assertEqual((P.st(c, 'fine_on'), P.st(c, 'sub_open')), (3, -1))
        self.assertEqual(posted_slots(c), [51, 72, 72, 72, 72, 72, 72, 72])
        self.assertEqual(P.plain(P.texts(c)['QSC_V1']), 'N=0')
        P.press(c, 3, 56)
        self.assertEqual(P.plain(P.texts(c)['QSC_V1']), 'N=10')
        P.press(c, 5, 56)
        self.assertEqual(P.st(c, 'fine_on'), 0)
        self.assertEqual(posted_slots(c), [c.to_ui(x) for x in ABSENT])
        self.assertEqual(c.w(Q.QSOBJ + 0xBC), ABSENT[0])
        self.assertEqual([c.slot(1, k) for k in range(8)], ABSENT)

    def test_last_request_wins_and_invalid_requests_do_not_replace_it(self):
        c = boot()
        self.assertEqual(request(c, 'RES', 1), 1)
        self.assertEqual(request(c, 'FPS', 2), 1)
        for name, how in [('MISSING', 1), ('FORMAT', 1), ('RES', 2), ('FPS', 99), ('RESxxxxxxxxxxxx', 1)]:
            self.assertEqual(request(c, name, how), 0)
        c.guid(23)
        self.assertEqual((P.st(c, 'sub_open'), P.st(c, 'fine_on')), (-1, 3))

    def test_recording_or_non_cine_at_consumption_discards_request(self):
        for why in ('recording', 'still'):
            c = boot()
            self.assertEqual(request(c, 'RES', 1), 1)
            if why == 'recording': c.put(0xC35A952C, 1)
            else: c.cine = False
            c.guid(23)
            self.assertEqual(P.st(c, 'sub_open'), -1)
            self.assertEqual(request(c, 'RES', 1), 0)
            c.put(0xC35A952C, 0); c.cine = True
            c.guid(23)
            self.assertEqual(P.st(c, 'sub_open'), -1)

    def test_client_lock_rechecked_and_rejected_request_keeps_prior(self):
        c = boot()
        table = c.callsvc('find', 0x53545351 ^ 0x80808080)
        # qsc_func is 60 bytes on ARM; RES arg points to the demo's count/toggle.
        arg = c.w(c.w(table + 8) + 60 + 44)
        self.assertEqual(request(c, 'RES', 1), 1)
        c.put(arg + 4, 1)
        c.guid(23)
        self.assertEqual(P.st(c, 'sub_open'), -1)
        self.assertEqual(request(c, 'FPS', 2), 1)
        self.assertEqual(request(c, 'RES', 1), 0)
        c.put(arg + 4, 0)
        c.guid(23)
        self.assertEqual(P.st(c, 'fine_on'), 3)

    def test_layout_closes_standalone_fine_and_clears_display(self):
        c = boot(ABSENT)
        self.assertEqual(request(c, 'FPS', 2), 1)
        c.guid(0)
        self.assertEqual(P.st(c, 'fine_on'), 3)
        c.posts.clear()
        c.layout()
        self.assertEqual(P.st(c, 'fine_on'), 0)
        self.assertEqual(posted_slots(c), [c.to_ui(x) for x in ABSENT])


    # ---- API 6 (v0.3.1): open a sub-QS focused on a sub-item; a sub-item's blur() when the focus leaves it
    def blurs(self, c, fi=0):
        table = c.callsvc('find', 0x53545351 ^ 0x80808080)
        arg = c.w(c.w(table + 8) + 60 * fi + 44)
        return c.w(arg + 20)

    def test_open_sub_at_focuses_the_item_present_or_standalone(self):
        for slots, home in ((STOCK, 1), (ABSENT, 0)):
            c = boot(slots)
            self.assertEqual(request(c, 'DC', 1 | 4 << 8), 0, 'past the last sub-item')
            self.assertEqual(request(c, 'FPS', 2 | 1 << 8), 0, 'fine has no item')
            self.assertEqual(request(c, 'DC', 1 | 1 << 16), 0, 'unknown bits')
            self.assertEqual(request(c, 'DC', 1 | 2 << 8), 1)   # QSC_OPEN_SUB_AT(1): "Toggle", tile 3
            c.layout()
            c.posts.clear()
            c.guid(slots[0])
            self.assertEqual((P.st(c, 'sub_open'), c.w(Q.QSOBJ + 0xBC)), (0, 72))
            self.assertIn(('QS_FocusPos', 2), c.posts)
            self.assertIn(('QS_QSMode', 67), c.posts)
            self.assertEqual(posted_slots(c)[:4], [65, 66, 67, 68])
            P.press(c, 5, 72)                                  # AEL: back on the function's own tile
            self.assertEqual(P.st(c, 'sub_open'), -1)
            self.assertEqual(P.st(c, 'sub_home'), home)

    def test_api9_fine_and_sub_on_one_function(self):
        """0.0.2test (Bei 11-07, SensorLab's FPS): a function with fine() AND a sub-QS registers; AEL on its tile is the
        fine mode in place (no sub-QS, the layout stays); the sub-QS opens only through open(QSC_OPEN_SUB_AT)"""
        c = boot(fine_sub=True)
        self.assertEqual(c.callsvc('find', 0x54435351) and c.w(c.callsvc('find', 0x54435351) + 4), 9)
        c.guid(25)                                            # the stock FPS tile: ours (56)
        self.assertEqual(c.w(Q.QSOBJ + 0xBC), 56)
        self.assertEqual(c.guid_cur, 1)                       # "AEL more options"
        c.posts.clear()
        P.press(c, 5, 56)                                     # AEL: fine in place
        self.assertEqual((P.st(c, 'fine_on'), P.st(c, 'sub_open')), (3, -1))
        self.assertEqual(posted_slots(c), [None] * 8, 'the layout stays')
        P.press(c, 1, 56)
        self.assertEqual(P.plain(P.texts(c)['QSC_V4']), 'N=1')
        P.press(c, 5, 56)                                     # AEL again: fine off, still no sub-QS
        self.assertEqual((P.st(c, 'fine_on'), P.st(c, 'sub_open')), (0, -1))
        self.assertEqual(request(c, 'FPS', 1 | 1 << 8), 1)    # QSC_OPEN_SUB_AT(0): the menu's way in
        c.layout()
        c.guid(21)
        self.assertEqual((P.st(c, 'sub_open'), P.st(c, 'fine_on'), c.w(Q.QSOBJ + 0xBC)), (2, 0, 71))
        self.assertEqual(posted_slots(c)[:2], [65, 66])
        P.press(c, 5, 71)                                     # AEL in the sub-QS: back, not fine
        self.assertEqual((P.st(c, 'sub_open'), P.st(c, 'fine_on'), c.w(Q.QSOBJ + 0xBC)), (-1, 0, 56))
        P.press(c, 5, 56)                                     # and AEL on the tile is fine again
        self.assertEqual((P.st(c, 'fine_on'), P.st(c, 'sub_open')), (3, -1))
        self.assertEqual(request(c, 'FPS', 1), 1)             # an open() while fine: fine ends, the sub-QS opens
        c.guid(56)
        self.assertEqual((P.st(c, 'sub_open'), P.st(c, 'fine_on')), (2, 0))

    def test_blur_on_focus_move_back_and_layout_not_on_dials(self):
        c = boot()
        c.guid(12)                                            # QS focus on the stock DC tile: ours (54)
        P.press(c, 5, 54)                                     # AEL on DC (replaces stock 12): sub-QS, tile 1 focused
        self.assertEqual(P.st(c, 'sub_open'), 0)
        c.guid(71)                                            # "Count": has blur()
        P.press(c, 1, 71); P.press(c, 3, 71)                  # dials stay on it
        self.assertEqual(self.blurs(c), 0)
        c.guid(72)                                            # focus moved: once
        self.assertEqual(self.blurs(c), 1)
        c.guid(72); c.guid(70)                                # "Toggle" and the function have none
        self.assertEqual(self.blurs(c), 1)
        c.guid(71)
        P.press(c, 5, 71)                                     # AEL back from the item
        self.assertEqual((self.blurs(c), P.st(c, 'sub_open')), (2, -1))
        P.press(c, 5, 54)
        c.guid(71)
        c.layout()                                            # QS closed with the item focused
        self.assertEqual(self.blurs(c), 3)
        c.layout(); c.guid(21)
        self.assertEqual(self.blurs(c), 3, 'never twice')
        self.assertEqual(request(c, 'DC', 1 | 1 << 8), 1)      # the menu path lands on it: blur when leaving
        c.layout(); c.guid(21)
        self.assertEqual(c.w(Q.QSOBJ + 0xBC), 71)
        c.guid(70)
        self.assertEqual(self.blurs(c), 4)


    def test_layout_timing_words(self):
        """API 6 qsc_api.timing: the first layout load's phases in order (a +1000 us tick), then max / last / count"""
        tick = ['E59F1008', 'E5910000', 'E2800FFA', 'E5810000', 'E12FFF1E', 'C3F80100']
        c = Q.boot([(Q.CNAME, Q.cblob()[0]), (Q.TNAME, client())],
                   prepare=lambda cam: cam.mu.mem_write(0xC002B6E0, b''.join(struct.pack('<I', int(w, 16)) for w in tick)))
        api = c.callsvc('find', 0x54435351)
        tm = lambda: struct.unpack('<12I', bytes(c.mu.mem_read(c.w(api + 20), 48)))
        self.assertEqual(tm(), (0,) * 12)
        c.layout()
        t = tm()
        self.assertTrue(t[0] < t[1] < t[2] <= t[3] < t[4] < t[5], t)    # entry, collection, leave(), stock loader
        self.assertEqual((t[7], t[10], t[8], t[9]), (1, t[5] - t[0], t[5] - t[0], t[5] - t[0]))
        c.layout()
        u = tm()
        self.assertEqual(u[:7] + (u[10],), t[:7] + (t[10],), 'the first layout kept')
        self.assertEqual(u[7], 2)
        self.assertEqual(u[8], max(t[8], u[9]))

    # ---- v0.3.2: AEL dead after boot until the focus crossed the stock K tile (live4 #8, SensorLab v1-live2 #7/#9)
    def aelbtn(self, c):
        """the last QS_AELbtn the container posted (None: none)"""
        v = [x for n, x in c.posts if n == 'QS_AELbtn']
        return v[-1] if v else None

    def test_ael_object_shown_on_our_tiles(self):
        """The stock page shows the AEL object (8514, where our keyEvent lives) only while QS_AELbtn == 1, and only
        the stock QSMode holders write it -- nothing of ours does.  So the container posts it on every focus of ours:
        1 where AEL acts (sub-QS, fine, back), 0 where it does not; a stock tile is left to its holder."""
        import qs_page_data as QP
        import editor_data as E
        m = QP.Model(P.STOCK_RECS, E.pool_str)
        btn = m.named('Button', 1)
        ael = m.named('AEL', btn)
        gate = {}
        for lid, i in m.events(btn, 'appVariableChangeEvent').items():
            v = m.values(i)
            if v.get('variable-name') == 'QS_AELbtn':
                for a in m.actions(btn, lid):
                    av = m.values(a)
                    self.assertEqual((av['object-id'], av['component-property']), (ael, 'is-visible'))
                    gate[v.get('equal-value')] = av.get('formula')
        self.assertEqual(gate, {None: None, 1.0: '1'})          # any change -> hidden, == 1 -> shown
        cam = P.boot_c()
        built = QP.Model(P.stream(P.parse(cam)), P.text_of(cam))       # the page as the camera parses it
        writers = [o for o in built.objs if o >= QP.OBJ_BASE for a in built.comps(o, tag=QP.T_ACTION)
                   if built.values(a).get('destination-variable') == 'QS_AELbtn']
        self.assertEqual(writers, [])
        self.assertEqual(Q.IMG[0xC2DAAD34 - 0xC0000000:][:10], b'QS_AELbtn\0')   # qsct.c AELBTN_NAME
        c = boot()
        c.posts.clear()
        c.guid(12)                                            # first focus after boot, on DC (ours, sub-items)
        self.assertEqual(self.aelbtn(c), 1)
        c.posts.clear()
        c.guid(21)                                            # FORMAT (ours, nothing behind AEL)
        self.assertEqual(self.aelbtn(c), 0)
        c.guid(12)
        P.press(c, 5, 54)                                     # sub-QS: AEL returns, so shown on every tile
        c.posts.clear()
        c.guid(71)
        self.assertEqual(self.aelbtn(c), 1)
        c.posts.clear()
        c.guid(4)                                             # a stock tile: its holder's business
        self.assertIsNone(self.aelbtn(c))
        # the menu's CUSTOM jump: QS opens straight into the sub-QS on an item / into fine mode
        for how, name in ((1 | 2 << 8, 'DC'), (2, 'FPS')):
            c = boot()
            self.assertEqual(request(c, name, how), 1)
            c.layout()
            c.posts.clear()
            c.guid(STOCK[0])
            self.assertEqual(self.aelbtn(c), 1, name)

    # ---- v0.3.2: the RATIO tile's lock icon covered its small text (live4 #15)
    @staticmethod
    def icon_rows(name):
        """(height, first and last opaque row) of a stock image"""
        sys.path.insert(0, str(HERE.parents[1] / 'research' / 'ui' / 'tools'))
        import numpy as np
        import nbr_stock as N
        import render_xci as R
        nbr = N.StockNbr((HERE.parents[1] / 'out' / 'seg0_c0000000.bin').read_bytes())
        e, = [x for x in nbr.entries if x.path.endswith('/' + name + '.xci')]
        _w, h, a, _m = R.decode_plane(nbr.read(e.path))
        ys = np.nonzero(np.asarray(a)[..., -1] > 32)[0]
        return h, int(ys.min()), int(ys.max())

    def test_title_qs_lock_clear_of_large_value(self):
        """Explicit native drawImage rect; no assumption about inline text alignment."""
        import qs_page_data as QP
        h, y0, y1 = self.icon_rows('menu_lock_qs')
        x, y, w, height = QP.TITLE_LOCK_RECT
        self.assertEqual((w, height), (150, h))
        self.assertEqual(x + w / 2, QP.TILE_SIZE[0] / 2)
        self.assertLessEqual(x + w, QP.TILE_SIZE[0])
        self.assertGreaterEqual(y + y0, QP.TEXT_RECT['L'][1])
        self.assertLess(y + y1, QP.TEXT_RECT['V'][1] + (QP.TEXT_RECT['V'][3] - QP.TEXT_SIZE['V']) / 2)

    def test_small_qs_lock_clear_of_the_large_value(self):
        import qs_page_data as QP
        h, y0, y1 = self.icon_rows('menu_lock_qs')
        x, y, w, height = QP.SMALL_LOCK_RECT
        self.assertEqual(x + w / 2, QP.TILE_SIZE[0] / 2)
        self.assertAlmostEqual(w / 150, height / h)
        self.assertGreaterEqual(y + y0 * height / h, QP.TEXT_RECT['V'][1] + QP.TEXT_RECT['V'][3])
        self.assertGreaterEqual(y + y0 * height / h, QP.TEXT_RECT['S'][1])
        self.assertLess(y + y1 * height / h, QP.TEXT_RECT['S'][1] + QP.TEXT_RECT['S'][3])

    def test_lock_icon_clear_of_the_text(self):
        """The drawn geometry: an inline image in a tile drawText starts at the line top, rect y + (h - font size) / 2
        (live4 SS2585: '6048' glyphs and the key both start at tile y ~100 in the value rect 96 + 62, font 54); the
        rect's vertical centre as the other reading.  The icon in the value line, its opaque rows must stay clear of
        the row the text is posted in -- with the small text in the title row (v0.3.2), not in the small row."""
        import qs_page_data as QP
        src = (Q.QT.HERE / 'qstest.c').read_text()
        old = '            s->sub[i][2].lock = qt_lock_state;'
        assert src.count(old) == 1
        with tempfile.TemporaryDirectory(prefix='qsc-lock-client-') as tmp:
            p = pathlib.Path(tmp) / 'client.c'
            p.write_text(src.replace(old, old + '\n            s->sub[i][2].small = qt_toggle_small;'))   # "STEP 1"
            t = Q.QT.build(funcs=Q.QT.FUNCS, src=p)
        c = Q.boot([(Q.CNAME, Q.cblob()[0]), (Q.TNAME, t)])
        c.layout()
        P.set_cine(c, (21, 54, 23, 25, 39, 9, 55, 19))
        c.layout()
        c.guid(54)
        P.press(c, 5, 54)                                     # A's sub-QS: tile 4 = Ratio (lock + small)
        icons = []
        for flip in (0, 1):
            v = P.texts(c)
            icon = v['QSC_V4'][2:-8]
            self.assertIn(icon, ('menu_select_lock', 'menu_select_unlock'))
            self.assertEqual(v['QSC_V4'], f'<!{icon},CENTER>')
            self.assertEqual((v['QSC_L4'], v['QSC_S4'], v['QSC_Y4']), ('STEP 1', ' ', ' '))
            icons.append(icon)
            P.press(c, 1, 73)                                 # the dial flips the lock
        self.assertEqual(sorted(icons), ['menu_select_lock', 'menu_select_unlock'])
        # no small text: the title stays (the test client's own Ratio, SensorLab's never)
        c = P.boot_c()
        c.guid(54); P.press(c, 5, 54)
        self.assertEqual(P.texts(c)['QSC_L4'], 'Ratio')
        # geometry: which row holds text, against the icon's opaque rows in the value rect
        texted = {'L': QP.TEXT_RECT['L']}
        _x, vy, _w, vh = QP.TEXT_RECT['V']
        for name in icons:
            h, y0, y1 = self.icon_rows(name)
            for top in (vy + (vh - QP.TEXT_SIZE['V']) / 2, vy + (vh - h) / 2):     # line top / rect centre
                a, b = top + y0, top + y1
                for role, (_x, ty, _w, th) in texted.items():
                    self.assertTrue(b < ty or a > ty + th, (name, top, role))
                sy, sh = QP.TEXT_RECT['S'][1], QP.TEXT_RECT['S'][3]
                if top == vy + (vh - QP.TEXT_SIZE['V']) / 2:
                    self.assertTrue(a < sy + sh and b > sy, 'the model reproduces live4 #15')


MUTANTS = [
    ('stock focus not routed', '        u32 resolved = qc_qs_id(s, id);',
     '        u32 resolved = id;', 'test_stock_focus_dial_and_exit_preserve_settings'),
    ('replacement stays in editor', '        if (was_qs) qc_emit(s);', '        (void)was_qs;',
     'test_stock_focus_dial_and_exit_preserve_settings'),
    ('pending replayed', '    s->pending_fn = 0; s->pending_how = 0;', '    /* mutation: retain request */',
     'test_sub_open_is_queued_once_and_returns_to_replacement'),
    ('recording check removed on consume', '    if (!s->qs_active || i >= s->n || busy() || qc_locked(s, i)) return 0;',
     '    if (!s->qs_active || i >= s->n) return 0;', 'test_recording_or_non_cine_at_consumption_discards_request'),
    ('no standalone sub', '    if (k0 == 8u && !allow_standalone) return;',
     '    (void)allow_standalone; if (k0 == 8u) return;', 'test_absent_function_opens_standalone_sub_or_fine'),
    ('client lock ignored on consume', '    if (!s->qs_active || i >= s->n || busy() || qc_locked(s, i)) return 0;',
     '    if (!s->qs_active || i >= s->n || busy()) return 0;', 'test_client_lock_rechecked_and_rejected_request_keeps_prior'),
    ('hidden functions displace editor rows', 'fst_int_to_f32((int32_t)s->editor_row[csv][fi], &v);',
     '(void)csv; fst_int_to_f32((int32_t)(row0 + fi), &v);', 'test_editor_hides_replacement_rows_and_keeps_other_functions'),
    ('hidden functions counted in editor total', 'u32 total = row0 + editor_count(s, n), tens = 0;',
     'u32 total = row0 + n, tens = 0;', 'test_editor_hides_replacement_rows_and_keeps_other_functions'),
    ('dynamic id range shortened to visible row count', 'u32 count = x->b ? editor_count(s, n) : n;',
     'u32 count = editor_count(s, n);', 'test_editor_hides_replacement_rows_and_keeps_other_functions'),
    ('stale native key focus not written back', 'foc = qc_qs_id(s, native);',
     'foc = native;', 'test_stock_focus_dial_and_exit_preserve_settings'),
    # API 6 (v0.3.1)
    ('open at item ignored', '    W(((fn0)QS_STATE)() + QS_FOCUS) = INT_MAIN + at;',
     '    W(((fn0)QS_STATE)() + QS_FOCUS) = INT_MAIN;', 'test_open_sub_at_focuses_the_item_present_or_standalone'),
    ('open at item not bounded', '(!s->fx[i].nsub || at > s->fx[i].nsub)', '(!s->fx[i].nsub)',
     'test_open_sub_at_focuses_the_item_present_or_standalone'),
    ('blur never armed', 's->blur_id = id; s->blur_fn = s->sblur[i][item];', 's->blur_id = id; s->blur_fn = 0;',
     'test_blur_on_focus_move_back_and_layout_not_on_dials'),
    ('no blur when the sub-QS closes', '    qc_blur(s, 0xFFFFFFFFu);\n', '\n',
     'test_blur_on_focus_move_back_and_layout_not_on_dials'),
    ('first layout times overwritten', '    if (first) { s->tm[5] = t1; s->tm[10] = d; }', '    { s->tm[5] = t1; s->tm[10] = d; }',
     'test_layout_timing_words'),
    ('blur on every focus call', '    if (!s->blur_fn || s->blur_id == id) return;', '    if (!s->blur_fn || !id) return;',
     'test_blur_on_focus_move_back_and_layout_not_on_dials'),
    # API 9 (0.0.2test)
    ('fine + sub refused (API 8)', '(v4 ? !fn_ok(q->reserved) : q->reserved != 0)))) {',
     '(v4 ? !fn_ok(q->reserved) : q->reserved != 0))) || (v4 && q->fine && q->sub)) {',
     'test_api9_fine_and_sub_on_one_function'),
    ('AEL opens the sub-QS before fine', '    if (s->xfine[i]) qc_fine_begin(s, i);\n    else qc_sub_open(s, i, 0, 0);',
     '    if (s->fx[i].nsub) qc_sub_open(s, i, 0, 0);\n    else qc_fine_begin(s, i);', 'test_api9_fine_and_sub_on_one_function'),
    # v0.3.2
    ('AEL object left to the last stock tile', '            ((fn3)POST_INT)(0, AELBTN_NAME, inner || more ? 1u : 0u);\n', '',
     'test_ael_object_shown_on_our_tiles'),
    ('AEL object shown only with more options', '((fn3)POST_INT)(0, AELBTN_NAME, inner || more ? 1u : 0u);',
     '((fn3)POST_INT)(0, AELBTN_NAME, more ? 1u : 0u);', 'test_ael_object_shown_on_our_tiles'),
    ('lock text left under the icon', '                        if (sm[0] && !(sm[0] == \' \' && !sm[1])) { l = sm; sm = qc_blank(s); approx = 0; }\n',
     '', 'test_lock_icon_clear_of_the_text'),
    ('lock text over the title even without one', 'if (sm[0] && !(sm[0] == \' \' && !sm[1])) { l = sm;',
     'if (1) { l = sm;', 'test_lock_icon_clear_of_the_text'),
]


def mutate():
    source = (HERE / 'qsct.c').read_text()
    passed = True
    for label, old, new, test in MUTANTS:
        assert source.count(old) == 1, label
        with tempfile.TemporaryDirectory(prefix='qsc-api5-mut-') as tmp:
            src = pathlib.Path(tmp) / 'qsct.c'
            src.write_text(source.replace(old, new))
            Q.Q.build(src=src)  # a compile failure must never count as a catch
            env = dict(os.environ, QSCT_SRC=str(src), PYTHONDONTWRITEBYTECODE='1')
            p = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-q', 'test_api5.Api5.' + test],
                               cwd=HERE, env=env, capture_output=True, text=True)
        caught = p.returncode != 0 and ('FAIL: ' + test) in p.stderr
        print(('CAUGHT' if caught else 'UNVERIFIED/SURVIVED') + ': ' + label, flush=True)
        if not caught:
            print(p.stdout + p.stderr)
            passed = False
    return 0 if passed else 1


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        raise SystemExit(mutate())
    unittest.main()
