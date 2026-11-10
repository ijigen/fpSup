"""API 8 (container v0.3.8, QSC_F_DIAL_HINT): the dial guide in the QS footer guide line.

Users did not know the rear dial adjusts.  A function that sets QSC_F_DIAL_HINT gets, while the focus is on its
tile (fine mode included, tile 1 of its sub-QS) or one of its sub-items with an adjust() and not locked, the stock
front / rear dial glyphs with their steps at the left end of the footer guide band (README v0.3.8).

Three layers, offline:
  * real ARM: the container and QSTest (functions with the new Q_DIAL config bit) under test_qsct's rig -- the
    focus is FUN_c0582da0's `bl FUN_c057f310` (c.guid), the keys are QSC_Key notifications (test_qs_page.press),
    recording is MOV_ACTIVE = 1;  the old containers (v0.3.7, v0.3.2, v0.2.3 BINs as built and deployed) with the
    same client: the bit is ignored;
  * the QS page as the record layer feeds it (test_qs_page.parse) judged with qs_page_data.Model: the guide object,
    its bindings, its geometry against the stock band / tiles / strip;
  * the stock resources the guide text names (the NBR's XCI images, English.nloc's own dial strings).
What emulation cannot show: the GUI drawing it -- the inline glyphs' placement in a left-aligned line, the plain
font's digit widths (the box's right end is an estimate), the box under the text (README v0.3.8 "live").

    cd projects/qs-container && python3 -B -m unittest test_api8
    python3 -B test_api8.py --mutate
"""
import hashlib
import os
import pathlib
import re
import struct
import subprocess
import sys
import tempfile
import unittest

import test_qsct as Q
import test_qs_page as P

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
QP, QT, E = Q.QP, Q.QT, Q.E
MOV_ACTIVE = 0xC35A952C
D = QT.Q_DIAL
FUNCS = [('A', 'QS Test A', 'menu_crop', QT.Q_DEMO | QT.Q_LOCK | D),   # 54: adjust, sub-items, LOCK_REC
         ('B', 'QS Test B', 'menu_lock', D),                          # 55: no adjust
         ('C', 'QS Test C', 'menu_cine_fps', QT.Q_FINE | D),          # 56: fine mode, no LOCK_REC
         ('D', 'QS Test D', 'menu_crop', QT.Q_DEMO),                  # 57: adjust and sub-items, no flag
         ('QR', 'QR', 'menu_crop', QT.Q_GO | D)]                      # 58: GO, no adjust
FI = {'A': 0, 'B': 1, 'C': 2, 'D': 3, 'QR': 4}
SLOTS = (21, 54, 55, 56, 57, 58, 9, 19)
SHOW4, SHOW3 = QP.DIAL_TEXTS                                          # rear +-10 (API 4), +-1 (API 3 / 2)
# the containers before the bit, as built (sha256 of their build records) -- what is on cards
OLD = {'QSContainer_v0.3.7.BIN': '646ef5202ac5e250f96fba593a4ee937f76b40aa1c7a52b56679be280881abbc',
       'QSContainer_v0.3.2.BIN': 'a73c9fcd6d7ca8c122a085cd77251e59209778442427e0930a2ebacbdcaff512',
       'QSContainer_v0.2.3.BIN': '86f8f451b87a9714729fe8942cec06d35792892dba2df7f2970ab99ebc5fed3d'}
_clients = {}


def client(funcs=FUNCS, patch=(), api3=False):
    """QSTest with `funcs`; `patch` = ((old, new), ...) edits of its source (each old once)."""
    key = (repr(funcs), patch, api3)
    if key not in _clients:
        if not patch:
            _clients[key] = Q.tblob(funcs=funcs, api3=api3) if api3 else Q.tblob(funcs=funcs)
        else:
            src = (QT.HERE / 'qstest.c').read_text()
            for old, new in patch:
                assert src.count(old) == 1, old
                src = src.replace(old, new)
            with tempfile.TemporaryDirectory(prefix='qsc-api8-client-') as tmp:
                p = pathlib.Path(tmp) / 'client.c'
                p.write_text(src)
                _clients[key] = QT.build(funcs=funcs, src=p, api3=api3)
    return _clients[key]


def boot(funcs=FUNCS, patch=(), api3=False, slots=SLOTS, container=None):
    cname, cblob = container or (Q.CNAME, Q.cblob()[0])
    c = Q.boot([(cname, cblob), (Q.TNAME, client(funcs, patch, api3))])
    c.layout()
    P.set_cine(c, slots)
    c.posts.clear()
    c.layout()
    return c


def api(c):
    return c.callsvc('find', 0x54435351)


def ui_id(c, name, sup_id=0x53545351):
    a = api(c)
    p = Q.F6.FAKE + 0x7C00
    c.mu.mem_write(p, name.encode() + b'\0')
    fn = c.w(a + 8)
    r = c.call(fn & ~1, r0=a, r1=sup_id, r2=p, thumb=bool(fn & 1))[0]
    return r - (1 << 32) if r >> 31 else r


def guide(c):
    """(the guide text, its box) as the variables hold them now"""
    return c.vars['QSC_DH'][1], c.vars['QSC_DHB'][1]


def guide_posts(c):
    return [(n, v) for n, v in c.posts if n in ('QSC_DH', 'QSC_DHB')]


SHOWN4, SHOWN3, HIDDEN = (SHOW4, 1), (SHOW3, 1), (' ', 0)


def demo(c, name):
    table = c.callsvc('find', 0x53545351 ^ 0x80808080)
    return c.w(c.w(table + 8) + 60 * FI[name] + 44)


def dial_off():
    return P.info()['dial_off']


@Q.SKIP
class DialGuide(unittest.TestCase):
    # ---- the API, the variables, the texts -------------------------------------------------------------
    def test_api_version_and_variables(self):
        c = boot()
        self.assertEqual((c.w(api(c)), c.w(api(c) + 4)), (0x31415351, 9))   # 0.0.2test: API 9
        self.assertEqual(c.vars['QSC_DH'][0], 2)                         # a text
        self.assertEqual(c.vars['QSC_DHB'][0], 0)                        # an int
        self.assertEqual(QP.NAMES[-2:], ['QSC_DH', 'QSC_DHB'])           # appended: the older ids stay
        self.assertEqual([ui_id(c, n) for n in FI], [49, 50, 51, 52, 53])
        blob = Q.cblob()[0]
        for k, t in enumerate(QP.DIAL_TEXTS):                            # the BIN's two slots, right after the go text
            at = dial_off() + QP.DIAL_TEXT_BYTES * k
            self.assertEqual(blob[at:at + QP.DIAL_TEXT_BYTES].split(b'\0')[0].decode(), t)
        self.assertEqual(dial_off(), P.info()['go_text_off'] + QP.GO_TEXT_BYTES)

    def test_texts_name_the_stock_images_and_steps(self):
        self.assertEqual(SHOW4, '<!font_G_dial_front,CENTER><!font_G_plusminus,CENTER>1<!44sp,CENTER>'
                                '<!font_G_dial_rear,CENTER><!font_G_plusminus,CENTER>10')
        self.assertEqual(SHOW3, SHOW4[:-2] + '1')
        self.assertEqual(QP.CODE_REAR, 2)                                # BL / BR are codes 3 / 4: QSC_STEP_REAR
        sys.path.insert(0, str(ROOT / 'research' / 'ui' / 'tools'))
        import nbr_stock as N
        nbr = N.StockNbr((ROOT / 'out' / 'seg0_c0000000.bin').read_bytes())
        by = {e.path.rsplit('/', 1)[-1]: e for e in nbr.entries}
        sizes = {n: struct.unpack_from('<HH', nbr._bytes(by[n + '.xci'].data_address, 12), 8) for n in QP.DIAL_IMAGES}
        self.assertEqual(sizes, {'font_G_dial_front': (88, 76), 'font_G_dial_rear': (88, 76),
                                 'font_G_plusminus': (36, 54), '44sp': (44, 1)})
        self.assertEqual(set(re.findall(r'<!([A-Za-z0-9_]+),CENTER>', SHOW4)), set(QP.DIAL_IMAGES))
        # the stock English strings use the same glyphs the same way (the setup menu's dial rows, a +- value)
        en = next(e for e in nbr.entries if e.path.endswith('English.nloc'))
        d = nbr._bytes(en.data_address, en.size)
        for key, text in ((b'0759', b'<!font_G_dial_front,CENTER>Front Dial'),
                          (b'0760', b'<!font_G_dial_rear,CENTER>Rear Dial'),
                          (b'0739', b'<!font_G_plusminus,CENTER>10%'),
                          (b'Footer14_K', b'<!font_G_bt_AEL_K187,CENTER>Further Options')):
            self.assertIn(key + b'\0' + text + b'\0', d)
        self.assertNotIn(b'font_G_dial_front_K', d)                       # no footer-sized dial glyph exists

    def test_texts_are_borrowed(self):
        """The GUI keeps the posted pointer: both slots lie in a range the container borrowed (C05E61C8 owns)."""
        c = boot()
        reader, pool = Q.F6.FAKE + 0x7400, Q.F6.FAKE + 0x7480
        c.mu.mem_write(pool, b'stock-0\0stock-8\0')
        c.put(reader + 0x10, 16)
        c.put(reader + 0x14, pool)
        base = c.block_of(Q.CNAME) + dial_off()
        for p in (base, base + QP.DIAL_TEXT_BYTES, base + 2 * QP.DIAL_TEXT_BYTES - 1):
            self.assertEqual(c.call(0xC05E61C8, r0=reader, r1=p, thumb=True)[0], 1, hex(p))

    # ---- where it shows --------------------------------------------------------------------------------
    def test_shown_only_where_the_dials_act(self):
        c = boot()
        self.assertEqual(guide(c), HIDDEN)                                # registered blank, box off
        c.guid(54)                                                       # A: adjust, flag
        self.assertEqual(guide(c), SHOWN4)
        self.assertEqual([v for n, v in c.posts if n == 'QSC_Arw'][-1], 1, 'the arrows agree')
        for ui, why in ((55, 'B: no adjust'), (57, 'D: no flag'), (58, 'QR: GO, no adjust'), (23, 'stock RES'),
                        (21, 'stock FORMAT'), (9, 'stock')):
            c.guid(54)
            c.guid(ui)
            self.assertEqual(guide(c), HIDDEN, why)
        c.guid(56)                                                       # C: fine-mode function with adjust
        self.assertEqual(guide(c), SHOWN4)
        c.guid(55)                                                       # B: no "AEL Further Options" (0)
        n = len(c.guid_sets)
        c.guid(23)
        self.assertEqual(c.guid_sets[n:], [('QS_FooterGuidDisp', 1)], 'stock tiles keep their stock guide')

    def test_posted_only_on_change(self):
        c = boot()
        c.posts.clear()
        c.guid(54)
        self.assertEqual(guide_posts(c), [('QSC_DH', SHOW4), ('QSC_DHB', 1)])
        c.posts.clear()
        c.guid(54)
        P.press(c, 1, 54)                                                # a dial step: the focus is redone
        P.press(c, 3, 54)
        self.assertEqual(guide_posts(c), [])
        c.posts.clear()
        c.guid(56)                                                       # another flagged tile: the same guide
        self.assertEqual(guide_posts(c), [])
        c.guid(23)
        self.assertEqual(guide_posts(c), [('QSC_DH', ' '), ('QSC_DHB', 0)])

    def test_locked_greyed_or_recording_hidden(self):
        c = boot()
        c.put(MOV_ACTIVE, 1)                                             # recording: A has LOCK_REC
        c.guid(54)
        self.assertEqual(guide(c), HIDDEN)
        P.press(c, 1, 54)
        self.assertEqual(guide(c), HIDDEN)
        c.guid(56)                                                       # C: no LOCK_REC, its dials still act
        self.assertEqual(guide(c), SHOWN4)
        c.put(MOV_ACTIVE, 0)
        c.guid(54)
        self.assertEqual(guide(c), SHOWN4)
        # greyed: state() non-0 (C gets a state() that returns its demo's lock word, demo + 8)
        c = boot(patch=(('        f->state = 0;\n', '        f->state = (c->flags[i] & Q_FINE) ? '
                         '(int (*)(void *))qt_lock_state : 0;\n'),))
        c.put(demo(c, 'C') + 8, 1)
        c.guid(56)
        self.assertEqual(guide(c), HIDDEN)
        c.put(demo(c, 'C') + 8, 0)
        c.guid(55)
        c.guid(56)
        self.assertEqual(guide(c), SHOWN4)

    def test_fine_mode(self):
        c = boot()
        c.guid(56)
        P.press(c, 5, 56)                                                # AEL: fine mode on, the tile stays
        self.assertEqual(P.st(c, 'fine_on'), 3)
        self.assertEqual(guide(c), SHOWN4)
        P.press(c, 1, 56)
        P.press(c, 3, 56)                                                # rear: +10, as the guide says
        self.assertEqual((P.plain(P.texts(c)['QSC_V4']), guide(c)), ('N=11', SHOWN4))
        P.press(c, 5, 56)                                                # fine off
        self.assertEqual((P.st(c, 'fine_on'), guide(c)), (0, SHOWN4))

    def test_sub_qs_items(self):
        """A's sub-QS: tile 1 (A itself), Count (a spinner), Toggle (no adjust in this client), Ratio (a lock icon,
        the dial flips it), the blank tile; D's sub-QS: no flag, nothing anywhere."""
        c = boot(patch=(('            s->sub[i][1].adjust = qt_toggle_adjust;',
                         '            s->sub[i][1].adjust = 0;'),))
        P.press(c, 5, 54)
        self.assertEqual(P.st(c, 'sub_open'), 0)
        self.assertEqual(guide(c), SHOWN4, 'tile 1 = A')
        for internal, want in ((71, SHOWN4), (72, HIDDEN), (73, SHOWN4), (77, HIDDEN), (70, SHOWN4)):
            c.guid(internal)
            self.assertEqual(guide(c), want, internal)
        c.guid(71)
        P.press(c, 4, 71)                                                # the rear dial on the spinner
        self.assertEqual(guide(c), SHOWN4)
        c.put(MOV_ACTIVE, 1)                                             # A is LOCK_REC: its items too
        c.guid(73)
        self.assertEqual(guide(c), HIDDEN)
        c.put(MOV_ACTIVE, 0)
        P.press(c, 5, 73)                                                # AEL back on A's own tile
        self.assertEqual((P.st(c, 'sub_open'), guide(c)), (-1, SHOWN4))
        P.press(c, 5, 57)                                                # D's sub-QS
        self.assertEqual(P.st(c, 'sub_open'), 3)
        for internal in (70, 71, 72, 73):
            c.guid(internal)
            self.assertEqual(guide(c), HIDDEN, internal)

    def test_api3_table_shows_its_rear_step(self):
        funcs = [('A', 'QS Test A', 'menu_crop', QT.Q_DEMO | QT.Q_LOCK | D), ('B', 'QS Test B', 'menu_lock', D)]
        c = boot(funcs=funcs, api3=True, slots=(21, 54, 23, 25, 39, 9, 55, 19))
        c.guid(54)
        self.assertEqual(guide(c), SHOWN3)
        P.press(c, 3, 54)                                                # rear on API 3: +1
        self.assertEqual((P.plain(P.texts(c)['QSC_V2']), guide(c)), ('N=1', SHOWN3))
        c.guid(55)
        self.assertEqual(guide(c), HIDDEN)

    def test_old_containers_ignore_the_bit(self):
        """v0.3.7 / v0.3.2 / v0.2.3 as deployed: the flagged functions register as before, the dials and arrows
        work, nothing of the guide exists."""
        for name, sha in OLD.items():
            blob = (HERE / 'out' / 'fpSup' / name).read_bytes()
            self.assertEqual(hashlib.sha256(blob).hexdigest(), sha, name)
            c = boot(container=(name, blob), funcs=FUNCS[:4], slots=(21, 54, 55, 56, 57, 9, 23, 19))
            self.assertEqual([ui_id(c, n) for n in ('A', 'B', 'C', 'D')], [49, 50, 51, 52], name)
            self.assertNotIn('QSC_DH', c.vars, name)
            c.posts.clear()
            c.guid(54)
            self.assertEqual([v for n, v in c.posts if n == 'QSC_Arw'], [2, 1], name)
            P.press(c, 3, 54)
            self.assertEqual(P.plain(P.texts(c)['QSC_V2']), 'N=10', name)

    # ---- the QS page data --------------------------------------------------------------------------------
    def test_page_carries_the_dial_guide(self):
        c = boot()
        m = QP.Model(P.stream(P.parse(c)), P.text_of(c))
        bound = [E.be(m.recs[i], 24) for i, r in enumerate(m.recs) if E.be(r, 0) == QP.T_EVENT
                 and m.comp(i) == 'appVariableEvent' and m.values(i).get('variable-name') == 'QSC_DH']
        self.assertEqual(len(bound), 1, 'one object shows QSC_DH')
        ids = P.info()['qs_notes'].get('dial', {})
        opt = m.named('Option')
        footer = m.objs[opt]['parent']
        oid, tog, none, box = ids['text'], ids['toggle'], ids['none'], ids['box']
        self.assertEqual(bound, [oid])
        self.assertEqual((m.objs[oid]['name'], m.objs[oid]['parent']), ('String', footer))
        self.assertEqual(m.children(oid), [tog])
        self.assertEqual(sorted(m.children(tog)), [none, box])
        self.assertEqual(m.objs[footer]['n_children'], len(m.children(footer)))
        # the text: Option's drawText (font, size, vertical centre) left-aligned, bound to QSC_DH
        dt, = [m.values(i) for i in m.comps(oid, 'drawText')]
        sdt, = [m.values(i) for i in m.comps(opt, 'drawText')]
        for k in ('font-setting', 'font-size', 'vert-align', 'wrap-mode', 'outline-color'):
            self.assertEqual(dt[k], sdt[k], k)
        self.assertEqual(dt['horz-align'], 1, 'left-aligned')
        rect = struct.unpack('>4f', dt['rect'])
        self.assertEqual(rect, QP.DIAL_RECT)
        b, = [m.values(i) for i in m.events(oid, 'appVariableEvent').values()]
        self.assertEqual((b['variable-name'], b['property-name'], b['component-id']), ('QSC_DH', 'text', 1))
        base = m.values(m.comps(oid, 'objectBase')[0])
        self.assertEqual(base, m.values(m.comps(opt, 'objectBase')[0]), "the stock guide band's place and size")
        # the box: a toggle on QSC_DHB -- child 0 nothing, child 1 the stock BG (60 % black) ending past the text
        tb, = [m.values(i) for i in m.events(tog, 'appVariableEvent').values()]
        self.assertEqual((tb['variable-name'], tb['property-name']), ('QSC_DHB', 'select-value'))
        self.assertEqual([i for i in m.children(tog) if m.comps(i, 'drawRect')], [box])
        self.assertLess(m.objs[none]['rec'], m.objs[box]['rec'], 'child 0 = none, child 1 = the box')
        sbg = [i for i in m.children(opt) if m.objs[i]['name'] == 'BG'][0]
        self.assertEqual(m.values(m.comps(box, 'drawRect')[0]), m.values(m.comps(sbg, 'drawRect')[0]))
        bb, sb = m.values(m.comps(box, 'objectBase')[0]), m.values(m.comps(sbg, 'objectBase')[0])
        self.assertEqual({k: v for k, v in bb.items() if k != 'position'}, {k: v for k, v in sb.items() if k != 'position'})
        bx, by = struct.unpack('>ff', bb['position'])
        bw, bh = struct.unpack('>ff', bb['size'])
        self.assertEqual((by, bx + bw), (0.0, QP.DIAL_BOX_RIGHT))
        self.assertLessEqual(bx, 0.0, 'the box starts off the left edge')
        # geometry on the screen: the band is the stock guide's (Footer y 608 - 69 = 539..608); the glyphs (88 x 76,
        # opaque rows 6..67) from the line top = rect y + (h - size) / 2 stay clear of the tiles (end 531) and the
        # option strip (from 608); the stock line (rect y 8) would run them 6 px into the strip
        fy = struct.unpack('>ff', m.values(m.comps(footer, 'objectBase')[0])['position'])[1]
        band = fy + struct.unpack('>ff', base['position'])[1]
        tile5 = m.named('QS_CINE5')
        t5 = struct.unpack('>ff', m.values(m.comps(tile5, 'objectBase')[0])['position'])[1] + \
            struct.unpack('>ff', m.values(m.comps(tile5, 'objectBase')[0])['size'])[1]
        top = band + rect[1] + (rect[3] - dt['font-size']) / 2
        self.assertEqual((band, fy, t5, top), (539.0, 608.0, 531.0, 540.0))
        self.assertGreaterEqual(top + 6, t5)
        self.assertLessEqual(top + 67, fy - 1)
        srect = struct.unpack('>4f', sdt['rect'])
        self.assertGreater(band + srect[1] + 67, fy - 1, 'the stock line would not fit the glyphs')
        # left of the stock guide: "AEL Further Options" right-aligned at 969 (114 px glyph + ~238 px text at 54)
        # and its box from 43 px before it
        self.assertLess(QP.DIAL_BOX_RIGHT, srect[0] + srect[2] - (114 + 238) - 43)
        # the stock guide is untouched but for frame 14
        self.assertEqual(m.objs[opt]['n_children'], 1)

    def test_header_and_local_ids(self):
        """The generic page checks (test_qs_page.Layer) hold with the guide: budgets, counts, local ids."""
        c = boot()
        parsed = P.parse(c)
        m = QP.Model(P.stream(parsed), P.text_of(c))
        ids = P.info()['qs_notes']['dial']
        for oid in ids.values():
            locs = sorted(E.be(m.recs[i], QP.LOCAL[E.be(m.recs[i], 0)]) for i in m.own.get(oid, [])
                          if E.be(m.recs[i], 0) in QP.LOCAL)
            self.assertEqual(len(locs), len(set(locs)), oid)
            self.assertEqual(m.objs[oid]['n_local'], len(locs), oid)
        self.assertEqual(set(P.info()['qs']['targets']) & QP.shared_recipe_records(P.STOCK), set())


# ---- mutations: (label, qsct.c old, new, test) or (label, 'qs', qs_page_data mutation, test) ------------------
MUTANTS = [
    ('flag ignored', 'if (adj && (x->flags & QSC_F_DIAL_HINT)) dh', 'if (adj) dh', 'test_shown_only_where_the_dials_act'),
    ('adjust ignored', 'if (adj && (x->flags & QSC_F_DIAL_HINT)) dh', 'if ((x->flags & QSC_F_DIAL_HINT)) dh',
     'test_shown_only_where_the_dials_act'),
    ('lock ignored', 'if (adj && (x->flags & QSC_F_DIAL_HINT)) dh',
     'if ((item < 0 ? x->adjust : x->sa[item]) && (x->flags & QSC_F_DIAL_HINT)) dh', 'test_locked_greyed_or_recording_hidden'),
    ('function tile only', 'if (adj && (x->flags & QSC_F_DIAL_HINT)) dh', 'if (adj && item < 0 && (x->flags & QSC_F_DIAL_HINT)) dh',
     'test_sub_qs_items'),
    ('hidden in fine mode', 'if (adj && (x->flags & QSC_F_DIAL_HINT)) dh', 'if (adj && !s->fine_on && (x->flags & QSC_F_DIAL_HINT)) dh',
     'test_fine_mode'),
    ('API 3 shown with +-10', 'dh = (x->flags & FX_API4) ? 1u : 2u;', 'dh = 1u;', 'test_api3_table_shows_its_rear_step'),
    ('stock tiles not cleared', '    qc_dial_hint(s, dh);                                             /* stock / blank ids: none */',
     '    if (i >= 0) qc_dial_hint(s, dh);', 'test_shown_only_where_the_dials_act'),
    ('posted every time', '    if (dh == s->dh_last) return;\n', '', 'test_posted_only_on_change'),
    ('box never shown', '(u32)(uintptr_t)qc_name(s, S_DHB), dh ? 1u : 0u);', '(u32)(uintptr_t)qc_name(s, S_DHB), 0u);',
     'test_posted_only_on_change'),
    ('wrong text slot', 'DH_BYTES * (dh - 1u)', 'DH_BYTES * dh', 'test_shown_only_where_the_dials_act'),
    ('box registered as text', '                     k == S_GO || k == S_DHB), def[3];', '                     k == S_GO), def[3];',
     'test_api_version_and_variables'),
    ('texts not borrowed', 'svc->borrow(svc, s->block + c->names_off, s->block + c->dial_off + 2u * DH_BYTES)',
     'svc->borrow(svc, s->block + c->names_off, s->block + c->go_text_off + GO_TEXT)', 'test_texts_are_borrowed'),
    ('API version still 8', 's->api.version = 9;', 's->api.version = 8;', 'test_api_version_and_variables'),
    ('data: no guide object', 'qs', 'nodialhint', 'test_page_carries_the_dial_guide'),
    ('data: right-aligned (over the stock guide)', 'qs', 'dialright', 'test_page_carries_the_dial_guide'),
    ('data: the stock line (glyphs into the strip)', 'qs', 'dialline', 'test_page_carries_the_dial_guide'),
    ('data: box bound to the text', 'qs', 'dialboxbind', 'test_page_carries_the_dial_guide'),
    ('data: box shown at 0', 'qs', 'dialboxalways', 'test_page_carries_the_dial_guide'),
]


def mutate():
    source = (HERE / 'qsct.c').read_text()
    passed, caught_n = True, 0
    only = [a for a in sys.argv[1:] if a != '--mutate']
    todo = [m for m in MUTANTS if not only or any(o in m[0] for o in only)]
    for label, old, new, test in todo:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        if env.get('SL_TESTCACHE', '1') != '0':
            env['SL_TESTCACHE'] = 'ro'
        with tempfile.TemporaryDirectory(prefix='qsc-api8-mut-') as tmp:
            env['PYTHONPYCACHEPREFIX'] = tmp
            if old == 'qs':
                env['QSCT_QS_MUTATE'] = new
                os.environ['QSCT_QS_MUTATE'] = new
                try:
                    Q.Q.build()                                    # a build failure must never count as a catch
                finally:
                    del os.environ['QSCT_QS_MUTATE']
            else:
                assert source.count(old) == 1, label
                src = pathlib.Path(tmp) / 'qsct.c'
                src.write_text(source.replace(old, new))
                Q.Q.build(src=src)                                 # a compile failure must never count as a catch
                env['QSCT_SRC'] = str(src)
            p = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-q', 'test_api8.DialGuide.' + test],
                               cwd=HERE, env=env, capture_output=True, text=True)
        caught = p.returncode != 0 and ('FAIL: ' + test) in p.stderr
        caught_n += caught
        print(('CAUGHT' if caught else 'UNVERIFIED/SURVIVED') + ': ' + label, flush=True)
        if not caught:
            print(p.stdout + p.stderr)
            passed = False
    print(f'{caught_n}/{len(todo)} mutants caught')
    return 0 if passed else 1


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        raise SystemExit(mutate())
    unittest.main()
