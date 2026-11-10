#!/usr/bin/env python3
"""The QS container stage 2 (the Quick Set page) on the real ARM bytes, offline.

The real v4 core loads the real QSContainer_v0.2.0.BIN and QSTest_v0.2.0.BIN
against the real firmware image (test_qsct's camera).  The container's record
layer is entered at the real hooked FUN_c05e6400 for EVERY record of the stock
QS_CINE page, in order, with a reader {+4 position, +0x24 base}; what it hands
the parser (the stub at C05E6404 records it) is the page the GUI would build.
The tests judge that stream with qs_page_data.Model, the playback model also
run on the stock page (where it reproduces the 2026-10-29 live bug), so a
check means "this data, played this way".

Python models (declared, not the firmware): the parser body after its first
instruction, the resource cache's v2/v3 (record the call; v3 with the cache
empties it), the UI app's variable registry / subscription / post queue
(uishare tab test_ft6), FUN_c05666a0's QS state (+0xBC = the focused tile's
internal id), the settings getters.  What emulation cannot show: the GUI
building the page (objects, drawing, timing) -- see README "not verified".

    cd projects/qs-container && python3 -B -m unittest test_qs_page
    python3 -B test_qs_page.py --mutate
"""
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
import test_qsct as Q1                     # noqa: E402  (the camera, boot helpers)
import qs_page_data as QP                  # noqa: E402
import editor_data as E                    # noqa: E402

T3, F6 = Q1.T3, Q1.F6
READER2 = F6.FAKE + 0xE000                 # the reader the parser is called with
DESC = F6.FAKE + 0x7800
_, QS_ENTRY, QS_LEN = E.O.resource_set(QP.PAGE)
STOCK = QP.Page()
STOCK_RECS = [STOCK.rec(o) for o, _t, _s in STOCK.recs]
CINE_IDS = sorted({ui for ui, _img in E.csv_rows(0)})
NEW_IDS = list(range(QP.UI_FN0, QP.UI_LAST + 1))
KEY_OBJECTS = ('FR', 'FL', 'BR', 'BL', 'AEL')
SKIP = Q1.SKIP


def info():
    return Q1.cblob()[1]


def text_of(cam):
    """A string field: the stock pool, or a private id (address - 0x80000000)."""
    def text(off):
        if off == 0xFFFFFFFF:
            return None
        if off < E.POOL_LEN:
            return E.pool_str(off)
        return cam.cstr((off + 0x80000000) & 0xFFFFFFFF)
    return text


def parse(cam, offsets=None):
    """Every stock QS_CINE record (or those at `offsets`) through the hooked
    C05E6400: [(stock offset, [records the parser got])]."""
    out = []
    for o, _t, s in STOCK.recs if offsets is None else [(o, None, STOCK.at[o][1]) for o in offsets]:
        cam.parsed.clear()
        cam.put(READER2 + 0x24, Q1.NBU)
        cam.put(READER2 + 4, QS_ENTRY + o)
        cam.call(Q1.REC_PARSE, r0=READER2, thumb=True, sp=T3.STACK - 0x1004)
        assert cam.w(READER2 + 0x24) == Q1.NBU, 'base not put back'
        assert cam.w(READER2 + 4) == QS_ENTRY + o + s, ('position', hex(o))
        out.append((o, [r for _b, _p, r in cam.parsed]))
    return out


def stream(parsed):
    return [r for _o, rs in parsed for r in rs]


SUBS = 7


def _layout():
    """Offsets of the stage-2 fields of struct st (qsct.c), computed the way the
    C lays them out (all u32 / arrays of u32 / char arrays, 4-aligned)."""
    o = Q1._CNT + 4 * 12                                   # past saves..emitted
    o += 4 * 2 + 4 * 4 + 4 * 2 + 4 * 2 + 4 * 2             # fv_result..page_bytes
    o += 4 * 6                                             # struct qsc_api (API 5: open; API 6: timing)
    fx = 4 * 8 + 4 * 6 * SUBS + 12 * SUBS + 28 * SUBS                # QSC_SUB_MAX (v0.2.2: 7)
    names = {'fx': o}
    o += fx * 16
    for n in ('qs_result', 'qs_ready', 'qs_pre', 'qs_boot', 'qs_inreload', 'qs_reloads',
              'qs_hits', 'qs_foreign', 'qs_entry_bad', 'qs_vars', 'next_qsrec', 'tab_extra'):
        names[n] = o
        o += 4
    names['qs_out'] = o
    o += 4 * 160
    names['sub_open'] = o
    o += 4
    names['sub_tile'] = o
    o += 32
    for n in ('keys', 'dials', 'aels', 'opens', 'closes', 'adjusts', 'locked', 'posts'):
        names[n] = o
        o += 4
    o += 4 * 8 + 4 * 8 * 4                                 # g_last, t_sel
    for n in ('menus', 'focus_calls', 'guid_sets', 'qs_fresh', 'sub_home', 'focus', 'fb_last', 'arw_last',
              'foot_on'):
        names[n] = o
        o += 4
    o += 4 * QP.N_SLOT * len(QP.FOOT_ROLES)                # f_sel
    o += 8 * 4 * 2 * 512 + QP.N_SLOT * len(QP.FOOT_ROLES) * 2 * 64   # txt, ftxt (FT_BYTES 64)
    o += 4                                                 # next_guid
    o += 4 * 16 * 3                                        # xfine, leave_fn, leave_arg (v0.2.2)
    for n in ('n_leave', 'fine_on', 'fines', 'leaves', 'rears', 'foot_pitch'):
        names[n] = o
        o += 4
    return names


LAYOUT = _layout()


def st(cam, name):
    v = cam.w(cam.st() + LAYOUT[name])
    return v - (1 << 32) if name == 'sub_open' and v >> 31 else v


def ready(**kw):
    c = Q1.std(**kw)
    c.layout()
    return c


def set_cine(cam, slots):
    for k, v in enumerate(slots):
        cam.set_slot(1, k, v)


def press(cam, code, focus):
    """A keyEvent of ours wrote QSC_Key = code while tile `focus` (internal) is focused."""
    cam.put(Q1.QSOBJ + 0xBC, focus)
    cam.posts.clear()
    cam.notify('QSC_Key', code)
    return list(cam.posts)


def texts(cam):
    return {n: v[1] for n, v in cam.vars.items() if n.startswith('QSC_')}


# --------------------------------------------------------------------------------
@SKIP
class Layer(unittest.TestCase):
    """The record layer: what the parser is fed, and that it is the reference."""

    @classmethod
    def setUpClass(cls):
        cls.cam = ready()
        cls.parsed = parse(cls.cam)
        cls.model = QP.Model(stream(cls.parsed), text_of(cls.cam))

    def test_collected_and_built(self):
        c = self.cam
        self.assertEqual(st(c, 'qs_result'), 0)
        self.assertEqual(st(c, 'qs_ready'), 1)
        self.assertEqual(st(c, 'qs_vars'), len(QP.NAMES))
        self.assertEqual({n for n in c.vars if n.startswith('QSC_')}, set(QP.NAMES))
        for k, n in enumerate(QP.NAMES):
            self.assertEqual(c.vars[n][0], 0 if k in QP.INT_NAMES else 2, n)
        self.assertEqual(c.vars['QSC_FB'][1], QP.BOX_NONE)
        self.assertEqual([n for _o, n, _f in c.subs if n.startswith('QSC_')], ['QSC_Key'])

    def test_untouched_records_pass_as_they_are(self):
        targets = set(info()['qs']['targets'])
        n = 0
        for o, rs in self.parsed:
            if o not in targets:
                self.assertEqual(rs, [STOCK.rec(o)], hex(o))
                n += 1
        self.assertEqual(n, len(STOCK.recs) - len(targets))
        self.assertEqual(st(self.cam, 'qs_hits'), len(targets))

    def test_the_camera_builds_what_the_reference_builds(self):
        """qsct.c's engine against qs_page_data.apply_table, every target, with
        the boot's private ids and the clients' looks."""
        c = self.cam
        blob = Q1.cblob()[0]
        qs = info()['qs']
        tab = blob[info()['qs_off']:]
        names_at = c.block_of(Q1.CNAME) + info()['names_off']
        looks = QP.qs_icon_looks(info()['icons'])
        values = {(QP.P_STR, k): names_at + 12 * k - 0x80000000 for k in range(len(QP.NAMES))}
        values[(QP.P_GO, 0)] = c.block_of(Q1.CNAME) + info()['go_text_off'] - 0x80000000   # v0.3.7: the go request
        icons = [info()['icons'].index(n) for n in ('menu_crop', 'menu_lock')]
        default = info()['icons'].index(E.DEFAULT_ICON)
        for i in range(16):
            ic = icons[i] if i < 2 else default
            for sel in range(4):
                values[(QP.P_LOOK, i << 2 | sel)] = looks[ic][sel]
        want = QP.apply_table(tab, qs, STOCK.rec, values)
        got = {o: b''.join(rs) for o, rs in self.parsed if o in want}
        self.assertEqual(set(got), set(want))
        for o in want:
            self.assertEqual(got[o], want[o], hex(o))

    def test_header_budget_covers_the_page(self):
        """Record 0 (0x10002): object and component counts equal the stream's,
        the pair / prop / key budgets keep the stock invariants and cover every
        group's pairs; each touched object's local / group / child counts are
        what the stream holds (the stock page satisfies the same checks)."""
        sizes = []
        for recs in (STOCK_RECS, stream(self.parsed)):
            m = QP.Model(recs, text_of(self.cam))
            h = recs[0]
            from ui import rows as R
            comps, arrays = R.header_layout(h)
            arr = [[E.be(h, cnt + 4 + 4 * i) for i in range(w * E.be(h, cnt))] for cnt, _e, w in arrays]
            kinds = {E.pool_str(E.be(h, c - 4)): E.be(h, c) for c in comps}
            self.assertEqual(E.be(h, 8), len(m.objs))
            count = {}
            for r in recs:
                t = E.be(r, 0)
                if t in (QP.T_COMP, QP.T_DRAW, QP.T_EVENT, QP.T_ACTION, QP.T_CTRL, 0x10007, 0x10008):
                    n = m.text(E.be(r, 8))
                    count[n] = count.get(n, 0) + 1
            for name, n in count.items():
                self.assertEqual(kinds[name], n, name)
            groups = [g for gs in m.groups.values() for g in gs]
            self.assertEqual(sum(arr[0][2::3]), len(arr[1]))
            self.assertEqual(kinds['animationClip'], len(arr[1]))
            self.assertEqual(sum(arr[1]), len(arr[2]))
            self.assertEqual(len(arr[0]) // 3, len(groups))
            self.assertGreaterEqual(len(arr[1]), sum(len(g['pairs']) for g in groups))
            sizes.append({oid: (o['n_local'] - len({E.be(m.recs[i], QP.LOCAL[E.be(m.recs[i], 0)])
                                                    for i in m.own.get(oid, []) if E.be(m.recs[i], 0) in QP.LOCAL}),
                                o['n_children'] - len(m.children(oid)), o['n_groups'] - len(m.groups.get(oid, [])))
                          for oid, o in m.objs.items()})
        stock, ours = sizes
        for oid, d in ours.items():               # every object's counts relate to its records as in stock
            self.assertEqual(d, stock.get(oid, (0, 0, 0)), oid)

    def test_no_record_shared_with_the_res_custom_qs_recipe(self):
        """Nested layers pass each other's copies: a record both serve would lose
        an edit.  The recipe's 171 QS_CINE records and ours are disjoint."""
        theirs = QP.shared_recipe_records(STOCK)
        self.assertGreater(len(theirs), 100)
        self.assertEqual(set(info()['qs']['targets']) & theirs, set())

    def test_new_local_ids_are_unique_per_object(self):
        """events and clips share an object's local numbering (fp-native-ui §8b:
        a collision hangs the camera)."""
        m = self.model
        for oid in m.objs:
            seen = {}
            for i in m.own.get(oid, []):
                t = E.be(m.recs[i], 0)
                if t in (QP.T_EVENT, QP.T_CLIP):
                    lid = E.be(m.recs[i], QP.LOCAL[t])
                    self.assertNotIn(lid, seen, (oid, lid))
                    seen[lid] = i


@SKIP
class KeyClips(unittest.TestCase):
    """The live bug: after a stock tile, our tile's dial / AEL ran the previous
    tile's handler.  For every new id, after every stock or new id, the only
    live keyEvent in FR / FL / BR / BL / AEL is ours, writing QSC_Key."""

    @classmethod
    def setUpClass(cls):
        cls.cam = ready()
        cls.model = QP.Model(stream(parse(cls.cam)), text_of(cls.cam))
        cls.stock = QP.Model(STOCK_RECS, E.pool_str)

    def active(self, m, name, seq):
        t = m.frame_after(lambda u: m.key_gate(name, u), seq)
        return {m.key_name(name, l) for l in m.active_keys(name, t)}, t

    def test_the_model_reproduces_the_live_bug_on_the_stock_page(self):
        m = self.stock
        self.assertEqual(self.active(m, 'FR', [20, 49])[0], {'19'})        # FORMAT -> ours: FORMAT changed
        self.assertEqual(self.active(m, 'FR', [21, 49])[0], {'20'})        # RES -> ours: resolution 2 -> 3
        self.assertEqual(self.active(m, 'AEL', [20, 49])[0], {'19'})       # ... and AEL would open B2_5
        self.assertFalse(m.dial_admits(49))
        self.assertEqual(self.active(m, 'FR', [48, 49])[0], {'48'})       # the headphone tile before

    def test_only_our_key_event_is_live_on_every_new_id(self):
        m = self.model
        codes = info()['qs_notes']['codes']
        for name in KEY_OBJECTS:
            ours = None
            for x in NEW_IDS:
                for prev in CINE_IDS + NEW_IDS:
                    names, t = self.active(m, name, [prev, x])
                    self.assertEqual(t, Fraction(x * 100, 3), (name, prev, x))       # applied: nothing stale
                    self.assertEqual(names, {'QSC_Key'}, (name, prev, x))
                obj, clip = m.key_clip(name)
                lid, = m.active_keys(name, Fraction(x * 100, 3))
                ours = lid
            acts = m.key_actions(name, ours)
            self.assertEqual(acts, [('controlAppVariable', {'destination-variable': 'QSC_Key',
                                                            'value': str(codes[name])})], name)
        self.assertEqual(codes, {'FR': 1, 'FL': 2, 'BR': 4, 'BL': 3, 'AEL': 5})   # v0.2.2: the rear dial 3 / 4

    def test_stock_ids_keep_their_key_events(self):
        for name in KEY_OBJECTS:
            for s in CINE_IDS:
                self.assertEqual(self.active(self.model, name, [s])[0], self.active(self.stock, name, [s])[0],
                                 (name, s))

    def test_headphone_closing_key(self):
        """keyEvent '48' (the headphone volume) is on at 48 and off from 49 on;
        in stock its key is still 1 at t(49) (no closing key)."""
        for name in ('FR', 'FL', 'BR', 'BL'):
            _obj, clip = self.stock.key_clip(name)
            lid48 = [l for l in (p.c for p in clip.props) if self.stock.key_name(name, l) == '48'][0]
            p = [p for p in clip.props if p.c == lid48][0]
            self.assertEqual(QP.prop_value_at(p, Fraction(49 * 100, 3)), 1)
            _obj, clip = self.model.key_clip(name)
            p = [p for p in clip.props if p.c == lid48][0]
            self.assertEqual(QP.prop_value_at(p, Fraction(48 * 100, 3)), 1)
            for x in NEW_IDS:
                self.assertEqual(QP.prop_value_at(p, Fraction(x * 100, 3)), 0, (name, x))

    def test_dial_range_and_dial_on(self):
        m = self.model
        self.assertTrue(all(m.dial_admits(x) for x in NEW_IDS))
        self.assertFalse(m.dial_admits(73))
        dial = m.named('DialKeyEvent')
        hits = []
        for oid, o in m.objs.items():
            for lid, i in m.events(oid, 'appVariableChangeEvent').items():
                v = m.values(i)
                if v.get('variable-name') == 'QS_QSMode' and v.get('range-lowerlimit-value') == 49.0:
                    acts = [m.values(a) for a in m.actions(oid, lid)]
                    if any(a.get('animationset') == 'Dial' for a in acts):
                        hits.append((oid, acts))
        self.assertEqual(len(hits), 1)
        _oid, acts = hits[0]
        self.assertEqual(len(acts), 1)
        self.assertEqual((acts[0]['animationset-owner'], acts[0]['animationset'], acts[0]['interval']),
                         (dial, 'Dial', 'ON'))


@SKIP
class Tiles(unittest.TestCase):
    """Drawing: every tile, every new id (the data; the GUI's drawing itself is
    not emulated)."""

    @classmethod
    def setUpClass(cls):
        cls.cam = ready()
        cls.model = QP.Model(stream(parse(cls.cam)), text_of(cls.cam))
        cls.stock = QP.Model(STOCK_RECS, E.pool_str)

    def tile(self, m, k):
        root = m.named(f'QS_CINE{k}')
        return root, m.named('Icon01', root), m.named('Icon02', root)

    def test_every_tile_applies_every_new_id(self):
        for k in range(1, 9):
            for m, want in ((self.model, True), (self.stock, False)):
                root, i1, i2 = self.tile(m, k)
                for x in NEW_IDS:
                    var = f'MV_QSMENU_QS{k}'
                    for o, g in ((i1, 'Icon01_CINE'), (i2, 'Icon02')):
                        self.assertEqual(m.event_admits(o, var, x) and m.interval_admits(o, g, x), want, (k, x, g))

    def test_icon_look_and_icon02_hidden(self):
        m = self.model
        looks = dict(zip(info()['icons'], QP.qs_icon_looks(info()['icons'])))
        for k in range(1, 9):
            _root, i1, i2 = self.tile(m, k)
            g1 = m.group(i1, 'Icon01_CINE')
            (ob, cid), = [p for p in g1['pairs'] if p[0] == i1]
            for x, icon in ((49, 'menu_crop'), (50, 'menu_lock'), (51, E.DEFAULT_ICON)):
                t = Fraction(x * 100, 3)
                got = (m.prop_at(ob, cid, 'image', 0, t),) + tuple(
                    QP.f32(m.prop_at(ob, cid, n, d, t)) for n, d in (('rect', 2), ('size', 0), ('position', 0)))
                self.assertEqual(got, looks[icon], (k, x))
            for x in range(QP.UI_SUB0, QP.UI_LAST + 1):
                t = Fraction(x * 100, 3)
                self.assertEqual(m.prop_at(ob, cid, 'size', 0, t), 0.0)
                self.assertEqual(m.prop_at(ob, cid, 'rect', 2, t), 0.0)
            hide = [p for p in m.group(i2, 'Icon02')['pairs'] if p[0] == i2]
            self.assertEqual(len(hide), 1, k)
            for x in CINE_IDS:
                self.assertEqual(m.prop_at(*hide[0], 'is-visible', 0, Fraction(x * 100, 3)), 1)
            for x in NEW_IDS:
                self.assertEqual(m.prop_at(*hide[0], 'is-visible', 0, Fraction(x * 100, 3)), 0)

    def test_stock_ids_draw_as_before(self):
        """Every prop of the tiles' id groups, the footer and the key groups at
        every stock id: as stock."""
        groups = []
        for k in range(1, 9):
            for nm in ('Icon01', 'Icon02'):
                o = self.stock.named(nm, self.stock.named(f'QS_CINE{k}'))
                groups.append((o, 'Icon01_CINE' if nm == 'Icon01' else 'Icon02'))
        groups.append((self.stock.named('QSMode'), 'Footer'))
        for name in ('FR', 'FL', 'BR', 'BL'):
            groups.append((self.stock.named(name, self.stock.named('DialKeyEvent')), name))
        groups.append((self.stock.named('Button', 1), 'Btn'))
        for owner, g in groups:
            for pair in self.stock.group(owner, g)['pairs']:
                if pair not in self.stock.clips:
                    continue
                sc, mc = self.stock.clips[pair], self.model.clips[pair]
                for p in sc.props:
                    q = [x for x in mc.props if x.c == p.c and x.name == p.name and x.dim == p.dim]
                    self.assertEqual(len(q), 1)
                    for x in CINE_IDS:
                        t = Fraction(x * 100, 3)
                        self.assertEqual(QP.prop_value_at(q[0], t), QP.prop_value_at(p, t), (pair, p.name, x))

    def test_native_qs_lock_position_and_binding(self):
        """Inspect actual ARM-emitted page records, not a manually centred drawing.
        All eight tiles get an image at x=53, hidden by width=0 until QSC_LWk=150.
        The SS__2900 inline origin x=128 would extend beyond the right edge.
        """
        m = self.model
        for k in range(1, 9):
            root, _, _ = self.tile(m, k)
            nodes = [i for i in m.children(root) if i >= QP.OBJ_BASE and m.comps(i, 'drawImage')]
            self.assertEqual(len(nodes), 2)
            oid = min(nodes); di, = m.comps(oid, 'drawImage')
            val = m.values(di)
            self.assertEqual(val['image'], 'menu_lock_qs')
            x, y, w, h = struct.unpack('>4f', val['rect'])
            self.assertEqual((x, y, w, h), (53., 42., 0., 74.))
            self.assertEqual(x + 150 / 2, 256 / 2)
            self.assertLessEqual(x + 150, 256)
            binds = [m.values(i) for i in m.events(oid, 'appVariableEvent').values()]
            self.assertEqual(binds, [{'type': 0, 'variable-name': f'QSC_LW{k}', 'component-id': 1,
                                     'property-name': 'rect', 'property-subindex': 2, 'decimal-places': 6}])
            self.assertIn((oid, 3), m.group(root, 'Color')['pairs'])
            self.assertTrue(all(p.name == 'color' for p in m.clips[(oid, 3)].props))

    def test_small_qs_lock_position_and_binding(self):
        m = self.model
        for k in range(1, 9):
            root, _, _ = self.tile(m, k)
            nodes = [i for i in m.children(root) if i >= QP.OBJ_BASE and m.comps(i, 'drawImage')]
            oid = max(nodes); di, = m.comps(oid, 'drawImage')
            val = m.values(di)
            self.assertEqual(val['image'], 'menu_lock_qs')
            rect = struct.unpack('>4f', val['rect'])
            for actual, expected in zip(rect, (68., 147., 0., 59.2)):
                self.assertAlmostEqual(actual, expected, places=4)
            binds = [m.values(i) for i in m.events(oid, 'appVariableEvent').values()]
            self.assertEqual(binds, [{'type': 0, 'variable-name': f'QSC_SW{k}', 'component-id': 1,
                                     'property-name': 'rect', 'property-subindex': 2, 'decimal-places': 6}])
            self.assertIn((oid, 3), m.group(root, 'Color')['pairs'])

    def test_title_value_and_small_text_objects(self):
        m = self.model
        for k in range(1, 9):
            root, i1, i2 = self.tile(m, k)
            mine = sorted(i for i in m.children(root) if i >= QP.OBJ_BASE)
            self.assertEqual(len(mine), 6, k)
            color = m.group(root, 'Color')
            for oid, role in zip(mine, ('L', 'V', 'S', 'Y')):
                dt, = m.comps(oid, 'drawText')
                dlid = E.be(m.recs[dt], 24)
                binds = [m.values(i) for i in m.events(oid, 'appVariableEvent').values()]
                self.assertEqual(binds, [{'type': 0, 'variable-name': f'QSC_{role}{k}', 'component-id': dlid,
                                          'property-name': 'text', 'decimal-places': 6}], (k, role))
                rect = struct.unpack('>4f', m.values(dt)['rect'])
                self.assertEqual(rect, QP.TEXT_RECT[role])
                self.assertEqual(m.values(dt)['font-size'], QP.TEXT_SIZE[role])
                self.assertIn((oid, 3), color['pairs'])
                cl = m.clips[(oid, 3)]
                self.assertEqual({(p.name, p.c) for p in cl.props}, {('color', dlid)})
            label = mine[0]
            ev = [m.values(i) for i in m.events(label, 'appVariableChangeEvent').values()]
            self.assertEqual(ev, [{'variable-name': f'QSC_G{k}'}])
            lid = list(m.events(label, 'appVariableChangeEvent'))[0]
            act, = [m.values(a) for a in m.actions(label, lid)]
            self.assertEqual((act['animationset-owner'], act['apply-frame']), (root, f'QSC_G{k}'))
            # the small lines: grey and yellow, darker than the title's white at every grey frame
            white = m.clips[(mine[0], 3)]
            for oid, tint in ((mine[2], QP.TEXT_TINT['S']), (mine[3], QP.TEXT_TINT['Y'])):
                for p in m.clips[(oid, 3)].props:
                    q = [x for x in white.props if x.dim == p.dim][0]
                    for t in (0, 33, 66):
                        want = QP.prop_value_at(q, t) * (tint[p.dim] if p.dim < 3 else 1)
                        self.assertAlmostEqual(QP.prop_value_at(p, t), want, 5)


@SKIP
class Release(unittest.TestCase):
    """The QS layout the cache parsed before us is let go once, after a load of
    another layout, with the cache object (ogc_qslay's rule)."""

    def test_released_once_after_another_layout(self):
        c = ready()
        self.assertEqual(c.rcache_calls, [('RC_V3', Q1.RCACHE), ('RC_V2', Q1.RCACHE)])
        self.assertEqual(st(c, 'qs_reloads'), 1)
        c.put(Q1.RCACHE + 4, Q1.QSLAY)                         # the cache took it again
        c.layout()
        self.assertEqual(len(c.rcache_calls), 2)

    def test_not_cached_counts_as_parsed_fresh(self):
        """Fix 6 (live 2026-10-29: reparse 0 but hits 114): when the cache does not hold the QS layout
        any more (it holds whatever page loaded last), there is nothing to let go -- the next QS open
        parses through us anyway.  qs_fresh counts that case; qs_reloads stays 0."""
        c = Q1.std(prepare=lambda cam: cam.put(Q1.RCACHE + 4, 0))
        c.layout()
        self.assertEqual((st(c, 'qs_reloads'), st(c, 'qs_fresh')), (0, 1))
        self.assertEqual(c.rcache_calls, [])
        c.layout()
        self.assertEqual(st(c, 'qs_fresh'), 1)                  # once

    def test_not_while_it_is_the_one_loading(self):
        c = Q1.std()
        c.call(Q1.LAY_SITE, r0=Q1.QSLAY, thumb=True, sp=T3.STACK - 0x1004)
        self.assertEqual(c.rcache_calls, [])
        c.layout()
        self.assertEqual(len(c.rcache_calls), 2)

    def test_not_when_someone_else_holds_it(self):
        c = Q1.std(prepare=lambda cam: cam.put(Q1.QSTREE + 0xC, 2))
        c.layout()
        self.assertEqual(c.rcache_calls, [])

    def test_not_when_the_layer_did_not_build(self):
        def poke(cam):                                         # a target QS record changed in place
            o = info()['qs']['targets'][2]
            a = STOCK.addr + o + 9
            cam.mu.mem_write(a, bytes([cam.mu.mem_read(a, 1)[0] ^ 1]))
        c = Q1.std(prepare=poke)
        c.layout()
        self.assertNotEqual(st(c, 'qs_result'), 0)
        self.assertEqual(st(c, 'qs_ready'), 0)
        self.assertEqual(Q1.stw(c, Q1.ST_N), 0)                # no function offered at all
        self.assertEqual(Q1.st_word(c, 'freeze'), 6)
        self.assertEqual(c.rcache_calls, [])
        self.assertEqual(stream(parse(c, [STOCK.recs[1][0]])), [STOCK.rec(STOCK.recs[1][0])])

    def test_before_collection_every_record_passes(self):
        c = Q1.std()
        o = info()['qs']['targets'][0]
        self.assertEqual(stream(parse(c, [o])), [STOCK.rec(o)])

    def test_another_layers_copy_passes(self):
        c = ready()
        o = info()['qs']['targets'][3]
        copy = F6.FAKE + 0x20000
        c.mu.mem_write(copy, STOCK.rec(o))
        c.parsed.clear()
        c.put(READER2 + 0x24, copy - (QS_ENTRY + o))
        c.put(READER2 + 4, QS_ENTRY + o)
        c.call(Q1.REC_PARSE, r0=READER2, thumb=True, sp=T3.STACK - 0x1004)
        self.assertEqual([r for _b, _p, r in c.parsed], [STOCK.rec(o)])
        self.assertEqual(st(c, 'qs_foreign'), 1)


# the glyph markup the container writes, back to text (build_qsct.GLYPHS)
_MARK = {}
for _font in Q1.Q.GLYPHS:
    for _c, _n in _font.items():
        _MARK[f'<!{_n},CENTER>'] = '×' if _c == 128 else chr(_c)


def plain(t):
    """A posted text with every glyph image back to its character."""
    import re
    return re.sub(r'<![A-Za-z0-9_]+,CENTER>', lambda m: _MARK.get(m.group(0), m.group(0)), t)


def big(text):
    """What the container posts for `text` in the stock bold value glyphs."""
    inv = {}
    for mk, ch in _MARK.items():
        if mk.startswith('<!font_menu_LB'):
            inv[ch] = mk
    return ''.join(inv.get(ch, ch) for ch in text)


def small(text):
    inv = {}
    for mk, ch in _MARK.items():
        if mk.startswith('<!font_menu_SB'):
            inv[ch] = mk
    return ''.join(inv.get(ch, ch) for ch in text)


SLOTS = [(8 - 5 + 2 * q) for q in range(5)]              # QS Test A's five options: slots 3, 5, 7, 9, 11


def foot(cam):
    """{slot: (label, small, approx)} of the non-blank footer slots, and the box (the label: top or, v0.2.3,
    centred when the option has no second line)."""
    v = texts(cam)
    out = {}
    for j in range(QP.N_SLOT):
        lab = v[f'QSC_FL{j}'] if v[f'QSC_FL{j}'] != ' ' else v[f'QSC_FP{j}']
        x = (lab, v[f'QSC_FS{j}'], v[f'QSC_FY{j}'])
        if x != (' ', ' ', ' '):
            out[j] = x
    return out, v['QSC_FB']


@SKIP
class Keys(unittest.TestCase):
    """QSC_Key: the dial on our tiles, AEL's sub-QS, MENU, the texts the tiles show."""

    def boot(self, slots=(21, 54, 23, 25, 39, 9, 55, 19), rec=False):
        c = ready()
        set_cine(c, slots)
        if rec:
            c.put(0xC35A952C, 1)
        c.posts.clear()
        c.layout()                                             # QS opens: a layout load
        return c

    def test_texts_on_qs_open(self):
        c = self.boot()
        v = texts(c)
        self.assertEqual((v['QSC_V2'], v['QSC_L2'], v['QSC_S2']), (big('N=0'), ' ', 'STEP 1'))   # v0.2.2: plain small
        # v0.2.2 (live run 3: CUSTOM filled the tile): wider than VALUE_W in the bold glyphs -> the plain font
        self.assertEqual((v['QSC_V7'], v['QSC_L7'], v['QSC_S7']), ('QS Test B', ' ', ' '))
        for k in (1, 3, 4, 5, 6, 8):
            self.assertEqual([v[f'QSC_{r}{k}'] for r in 'LVSY'], [' '] * 4)
        c.posts.clear()
        c.layout()
        self.assertEqual([n for n, _v in c.posts if n.startswith('QSC_') and n != 'QSC_Arw'], [])   # unchanged

    def test_value_is_drawn_in_the_stock_bold_glyphs(self):
        """Fix 4: the value line is the stock values' glyph set (font_menu_LB, the images the stock
        tiles draw '2500' / 'DNG' with); characters it lacks stay text in the same line."""
        c = self.boot()
        v = texts(c)
        self.assertEqual(v['QSC_V2'], '<!font_menu_LB_id_N,CENTER>=<!font_menu_LB_0,CENTER>')
        self.assertEqual(plain(v['QSC_V2']), 'N=0')
        # live run 3: the small glyph images are not tinted (white, the stock line is grey) -> the plain font
        self.assertEqual(v['QSC_S2'], 'STEP 1')
        self.assertNotIn('<!font_menu_SB', ''.join(str(x) for x in v.values()))

    def test_dial_adjusts_the_focused_function_only(self):
        c = self.boot()
        posts = press(c, 1, 54)                                # FR on QS Test A
        self.assertIn(('QSC_Key', 0), posts)
        self.assertEqual(plain(texts(c)['QSC_V2']), 'N=1')
        press(c, 2, 54)
        press(c, 2, 54)
        self.assertEqual(plain(texts(c)['QSC_V2']), 'N=999')   # wraps
        press(c, 1, 55)                                        # QS Test B: no adjust
        self.assertEqual(plain(texts(c)['QSC_V7']), 'QS Test B')
        before = texts(c)
        press(c, 1, 23)                                        # a stock tile (RES): nothing of ours
        self.assertEqual({k: v for k, v in texts(c).items() if not k.startswith('QSC_F') and k != 'QSC_Arw'},
                         {k: v for k, v in before.items() if not k.startswith('QSC_F') and k != 'QSC_Arw'})
        self.assertEqual(st(c, 'adjusts'), 3)

    def test_recording_greys_and_locks(self):
        c = self.boot(rec=True)
        self.assertEqual(texts(c)['QSC_G2'], 1)                # A has QSC_F_LOCK_REC
        self.assertEqual(texts(c)['QSC_G7'], 0)
        press(c, 1, 54)
        self.assertEqual(plain(texts(c)['QSC_V2']), 'N=0')
        press(c, 5, 54)
        self.assertEqual(st(c, 'sub_open'), -1)
        self.assertEqual(st(c, 'locked'), 2)
        c.guid(54)
        self.assertEqual(texts(c)['QSC_Arw'], 0)               # locked: no arrows, no hint
        self.assertEqual(c.guid_cur, 0)
        c.put(0xC35A952C, 0)
        c.layout()
        self.assertEqual(texts(c)['QSC_G2'], 0)

    def test_ael_opens_the_sub_qs_with_the_function_on_tile_1_and_returns(self):
        """§10 (Bei 10-29): the function moves to tile 1 (focused), its sub-items follow, the rest
        blank; AEL returns, the focus back on the function's own tile."""
        c = self.boot()
        posts = press(c, 5, 54)
        mv = [(n, v) for n, v in posts if n.startswith('MV_QSMENU')]
        self.assertEqual(mv, [('MV_QSMENU_QS1', 65), ('MV_QSMENU_QS2', 66), ('MV_QSMENU_QS3', 67),
                              ('MV_QSMENU_QS4', 68), ('MV_QSMENU_QS5', 72), ('MV_QSMENU_QS6', 72),
                              ('MV_QSMENU_QS7', 72), ('MV_QSMENU_QS8', 72)])
        self.assertIn(('QS_FocusPos', 0), posts)
        self.assertIn(('QS_QSMode', 65), posts)
        self.assertEqual(c.w(Q1.QSOBJ + 0xBC), 70)
        self.assertEqual(st(c, 'sub_home'), 1)
        v = texts(c)
        self.assertEqual(plain(v['QSC_V1']), 'N=0')                       # tile 1: the function
        self.assertEqual((v['QSC_L2'], plain(v['QSC_V2'])), ('Count', 'N=0'))
        self.assertEqual((v['QSC_L3'], plain(v['QSC_V3'])), ('Toggle', 'Off'))
        self.assertEqual((v['QSC_L4'], v['QSC_V4']), ('Ratio', '<!menu_select_lock,CENTER>'))   # API 4: icon as the value
        for k in (5, 6, 7, 8):
            self.assertEqual((v[f'QSC_L{k}'], v[f'QSC_V{k}']), (' ', ' '))
        self.assertEqual([c.slot(1, k) for k in range(8)], [21, 54, 23, 25, 39, 9, 55, 19])   # settings untouched
        press(c, 1, 70)                                        # dial on tile 1: the function
        press(c, 1, 71)                                        # dial on "Count"
        press(c, 2, 72)                                        # dial on "Toggle"
        v = texts(c)
        self.assertEqual((plain(v['QSC_V1']), plain(v['QSC_V2']), plain(v['QSC_V3'])), ('N=2', 'N=2', 'On'))
        posts = press(c, 5, 72)                                # AEL on a sub tile: back
        self.assertEqual([(n, val) for n, val in posts if n.startswith('MV_QSMENU')],
                         [(f'MV_QSMENU_QS{k + 1}', c.to_ui(v0)) for k, v0 in
                          enumerate([21, 54, 23, 25, 39, 9, 55, 19])])
        self.assertIn(('QS_FocusPos', 1), posts)               # the function's own tile again
        self.assertIn(('QS_QSMode', 49), posts)
        self.assertEqual(c.w(Q1.QSOBJ + 0xBC), 54)
        self.assertEqual(st(c, 'sub_open'), -1)
        v = texts(c)
        self.assertEqual((v['QSC_L1'], v['QSC_V1'], v['QSC_V3']), (' ', ' ', ' '))
        self.assertEqual(plain(v['QSC_V2']), 'N=2')

    def test_menu_is_the_stock_one_by_default(self):
        """Live run 3: MENU in the sub-QS returned AND ran the stock MENU (QS closed, the main menu opened).
        v0.2.2 default (MENU_BACK off): the page has no MENU switch (stock MENU everywhere, it closes QS and the
        layout load closes the sub-QS), a code 6 changes nothing, AEL returns."""
        c = self.boot()
        press(c, 5, 54)
        posts = press(c, 6, 71)
        self.assertEqual((st(c, 'sub_open'), st(c, 'closes')), (0, 0))
        self.assertEqual([n for n, _v in posts if n.startswith(('MV_QSMENU', 'QS_'))], [])
        c.layout()                                             # the stock MENU closes QS: a layout load
        self.assertEqual((st(c, 'sub_open'), st(c, 'closes')), (-1, 1))

    def test_leaving_qs_with_the_sub_qs_up_restores_the_layout(self):
        c = self.boot()
        press(c, 5, 54)
        c.posts.clear()
        c.layout()
        mv = [(n, v) for n, v in c.posts if n.startswith('MV_QSMENU')]
        self.assertEqual(len(mv), 8)
        self.assertEqual(st(c, 'sub_open'), -1)
        self.assertNotIn('QS_QSMode', [n for n, _v in c.posts])

    def test_ael_without_sub_items_does_nothing(self):
        c = self.boot()
        posts = press(c, 5, 55)                                # QS Test B
        self.assertEqual([n for n, _v in posts if n.startswith('MV_')], [])
        posts = press(c, 5, 23)                                # a stock tile
        self.assertEqual([n for n, _v in posts if n.startswith('MV_')], [])
        self.assertEqual(st(c, 'opens'), 0)

    def test_the_converter_knows_the_sub_ids(self):
        """The QS GUI turns QS_QSMode (UI) into +0xBC (internal) with the converter: 65..72 <-> 70..77."""
        c = self.boot()
        for x in range(QP.UI_SUB0, QP.UI_LAST + 1):
            self.assertEqual(c.to_int(x), x + 5)
            self.assertEqual(c.to_ui(x + 5), x)

    def test_sub_ids_are_ours_for_the_headphone_guard(self):
        c = self.boot()
        self.assertEqual(c.hp(70), [])
        self.assertEqual(c.hp(77), [])
        self.assertEqual(c.hp(53), [(Q1.SETTINGS, 7, 1)])

    def test_api_2_tables_still_load(self):
        """A client built against API 2 (magic QSF1, 48-byte functions, 16-byte sub-items) keeps working."""
        old = (HERE / 'validation' / 'qstest_v0.2.0.BIN')
        self.assertTrue(old.exists())
        c = Q1.boot([(Q1.CNAME, Q1.cblob()[0]), ('QSTest_v0.2.0.BIN', old.read_bytes())])
        c.layout()
        set_cine(c, (21, 54, 23, 25, 39, 9, 55, 19))
        c.layout()
        self.assertEqual(Q1.stw(c, Q1.ST_N), 2)
        self.assertEqual(plain(texts(c)['QSC_V2']), 'N=0')
        press(c, 5, 54)
        self.assertEqual((texts(c)['QSC_L2'], texts(c)['QSC_L3']), ('Count', 'Toggle'))


@SKIP
class Footer(unittest.TestCase):
    """Fix 2 / 3: the option strip under our tiles, the arrows, the AEL hint."""

    def boot(self):
        c = Keys.boot(self)
        return c

    def test_options_centred_and_boxed_and_following_the_dial(self):
        c = self.boot()
        c.guid(54)                                             # focus on QS Test A
        got, box = foot(c)
        self.assertEqual({j: x[0] for j, x in got.items()}, dict(zip(SLOTS, ['C0', 'C1', 'C2', 'C3', 'C4'])))
        self.assertEqual(box, SLOTS[0])
        press(c, 1, 54)
        self.assertEqual(foot(c)[1], SLOTS[1])                 # the box moves with the dial
        press(c, 2, 54)
        press(c, 2, 54)
        self.assertEqual(foot(c)[1], SLOTS[4])                 # 999 mod 5 = 4

    def test_slot_formula_centres_every_count(self):
        """n options sit on slots 8 - n + 2q: centred on the 1024 px strip (slot j's centre 64 (j + 1))."""
        for n in range(1, 8):
            slots = [8 - n + 2 * q for q in range(n)]
            centre = sum(64 * (j + 1) for j in slots) / n
            self.assertEqual(centre, 512, n)
            self.assertTrue(all(0 <= j < QP.N_SLOT for j in slots))

    def test_nothing_without_options(self):
        c = self.boot()
        c.guid(54)
        c.guid(55)                                             # QS Test B: no footer
        self.assertEqual(foot(c), ({}, QP.BOX_NONE))
        c.guid(54)
        c.guid(23)                                             # a stock tile: ours cleared
        self.assertEqual(foot(c), ({}, QP.BOX_NONE))

    def test_arrows_only_with_adjust_and_hint_only_with_sub_items(self):
        c = self.boot()
        c.posts.clear()
        c.guid(54)                                             # A: adjust, sub-items
        self.assertEqual([v for n, v in c.posts if n == 'QSC_Arw'], [2, 1])
        self.assertEqual(c.guid_cur, 1)
        c.posts.clear()
        c.guid(55)                                             # B: neither
        self.assertEqual([v for n, v in c.posts if n == 'QSC_Arw'], [2, 0])
        self.assertEqual(c.guid_sets[-1], ('QS_FooterGuidDisp', 0))
        n = len(c.guid_sets)
        c.guid(23)                                             # stock: FUN_c057f310 itself (1 for RES)
        self.assertEqual(c.guid_sets[n:], [('QS_FooterGuidDisp', 1)])
        posts = press(c, 5, 54)                                # the sub-QS: no stock "AEL back" -> no hint
        self.assertNotIn(('QS_FooterGuid1', QP.HINT_BACK), posts)
        self.assertEqual(c.guid_cur, 0)
        posts = press(c, 5, 70)                                # AEL back: "AEL Further Options" again
        self.assertEqual(c.guid_cur, 1)                        # A has sub-items

    def test_spinner_and_approximate_lines_in_the_sub_qs(self):
        c = self.boot()
        press(c, 5, 54)
        c.guid(71)                                             # "Count": a spinner
        got, box = foot(c)
        self.assertEqual(sorted(got), [5, 7, 9])
        self.assertEqual((got[5][0], got[7][0], got[9][0]),
                         ('<!menu_arrow_M_left,CENTER>', 'N=0', '<!menu_arrow_M_right,CENTER>'))
        self.assertEqual(box, QP.BOX_NONE)
        c.guid(72)                                             # "Toggle": OFF | ON, ON's small is approximate
        got, box = foot(c)
        self.assertEqual(got, {6: ('Off', ' ', ' '), 8: ('On', ' ', 'STEP 1')})      # two: slots 6, 8
        self.assertEqual(box, 6)
        press(c, 1, 72)
        self.assertEqual(foot(c)[1], 8)
        v = texts(c)
        self.assertEqual((v['QSC_S3'], plain(v['QSC_Y3'])), (' ', 'STEP 1'))   # approximate -> the yellow line


@SKIP
class SubTiles(unittest.TestCase):
    """Fix 5: a sub-QS tile is title (or icon / lock) + bold value + small line, like a stock tile."""

    def test_tile_parts(self):
        c = Keys.boot(self)
        press(c, 5, 54)
        v = texts(c)
        look = QP.qs_icon_looks(['menu_crop'])[0][0]
        # API 4: the label as text (live run 3: the inline look sat off centre); API 3 keeps the look (Api3 below)
        self.assertEqual(v['QSC_L1'], 'QS Test A')
        self.assertNotEqual(v['QSC_L1'], f'<!{E.pool_str(look)},CENTER>')
        self.assertEqual(v['QSC_V2'], big('N=0'))
        self.assertEqual((v['QSC_L3'], v['QSC_V3'], v['QSC_S3']), ('Toggle', big('Off'), 'STEP 1'))
        # API 4: the title stays, the lock icon is the value (live run 3: over the title it overlapped LOCK)
        self.assertEqual((v['QSC_L4'], v['QSC_V4']), ('Ratio', '<!menu_select_lock,CENTER>'))
        press(c, 1, 73)                                        # the dial flips the ratio lock
        v = texts(c)
        self.assertEqual((v['QSC_L4'], v['QSC_V4']), ('Ratio', '<!menu_select_unlock,CENTER>'))


@SKIP
class Icon02Return(unittest.TestCase):
    """Fix 1 (live 2026-10-29 step 11): back from the sub-QS the stock tiles drew their titles but
    no values.  Icon02 hides itself (is-visible 0) on our ids, and an invisible object's events do
    not fire: its own MV_QSMENU_QSn event never brought it back.  [model: an event fires only while
    its object is visible; Icon02's visibility is its hide clip at the frame applied last]"""

    @classmethod
    def setUpClass(cls):
        cls.cam = ready()
        cls.model = QP.Model(stream(parse(cls.cam)), text_of(cls.cam))

    def after(self, m, k, seq):
        root = m.named(f'QS_CINE{k}')
        i2 = m.named('Icon02', root)
        hide, = [p for p in m.group(i2, 'Icon02')['pairs'] if p[0] == i2]
        var = f'MV_QSMENU_QS{k}'
        triggers = []
        for oid in m.objs:
            for lid, i in m.events(oid, 'appVariableChangeEvent').items():
                v = m.values(i)
                if v.get('variable-name') != var:
                    continue
                for a in m.actions(oid, lid):
                    av = m.values(a)
                    if av.get('animationset-owner') == i2 and av.get('animationset') == 'Icon02':
                        triggers.append((oid, v))
        frame, visible = None, True
        for ui in seq:
            fired = any((oid != i2 or visible) and v.get('range-lowerlimit-value', 0.0) <= ui <=
                        v.get('range-upperlimit-value', 0.0) for oid, v in triggers)
            if fired and m.interval_admits(i2, 'Icon02', ui):
                frame = Fraction(ui * 100, 3)
                visible = bool(m.prop_at(*hide, 'is-visible', 0, frame))
        return frame, visible

    def test_values_come_back_after_the_sub_qs(self):
        m = self.model
        for k in range(1, 9):
            for stock in (20, 21, 23, 25):
                for sub in range(QP.UI_SUB0, QP.UI_LAST + 1):
                    self.assertEqual(self.after(m, k, [stock, sub, stock]), (Fraction(stock * 100, 3), True),
                                     (k, stock, sub))

    def test_the_hide_itself_stays(self):
        """Our ids still hide Icon02 (the stale stock values must not show on our tiles)."""
        for x in QP.UI_FN0, QP.UI_SUB0, QP.UI_LAST:
            self.assertEqual(self.after(self.model, 2, [20, x])[1], False)


@SKIP
class PageStrip(unittest.TestCase):
    """The page side of fixes 2/3 and MENU: the strip's objects, the cursor / arrow events, the
    tile Menu keyEvent switch."""

    @classmethod
    def setUpClass(cls):
        cls.cam = ready()
        cls.model = QP.Model(stream(parse(cls.cam)), text_of(cls.cam))

    def test_strip_objects(self):
        m = self.model
        qsmode = m.named('QSMode')
        cont, = [i for i in m.children(qsmode) if i >= QP.OBJ_BASE]
        texts_, tog = [], None
        for oid in m.children(cont):
            if m.comps(oid, 'drawText'):
                b, = [m.values(i) for i in m.events(oid, 'appVariableEvent').values()]
                pos = struct.unpack('>ff', m.values(m.comps(oid, 'objectBase')[0])['position'])
                texts_.append((b['variable-name'], pos[0]))
            else:
                tog = oid
        want = sorted((f'QSC_{r}{j}', 64.0 * j) for j in range(QP.N_SLOT) for r in QP.FOOT_ROLES)
        self.assertEqual(QP.FOOT_ROLES, ('FL', 'FS', 'FY', 'FG', 'FC', 'FN', 'FM', 'FP', 'FQ', 'FR'))
        self.assertEqual(sorted(texts_), want)
        b, = [m.values(i) for i in m.events(tog, 'appVariableEvent').values()]
        self.assertEqual((b['variable-name'], b['property-name']), ('QSC_FB', 'select-value'))
        boxes = m.children(tog)
        self.assertEqual(len(boxes), QP.N_SLOT + 1)
        for j, oid in enumerate(sorted(boxes)[:QP.N_SLOT]):
            pos = struct.unpack('>ff', m.values(m.comps(oid, 'objectBase')[0])['position'])
            self.assertEqual(pos[0] + QP.BOX_W / 2, 64.0 * (j + 1))
            self.assertEqual(len(m.comps(oid, 'drawRect')), 1)
        self.assertEqual(m.comps(sorted(boxes)[-1], 'drawRect'), [])

    def test_cursor_off_and_arrow_events(self):
        m = self.model
        cont, = [i for i in m.children(m.named('QSMode')) if i >= QP.OBJ_BASE]
        evs = {lid: m.values(i) for lid, i in m.events(cont, 'appVariableChangeEvent').items()}
        acts = {lid: [(m.values(a).get('animationset'), m.values(a).get('interval')) for a in m.actions(cont, lid)]
                for lid in evs}
        self.assertEqual((evs[1]['variable-name'], evs[1]['range-lowerlimit-value'], evs[1]['range-upperlimit-value']),
                         ('QS_QSMode', 49.0, 72.0))
        self.assertEqual(acts[1], [('Cursor', 'OFF')])
        self.assertEqual((evs[2]['variable-name'], evs[2].get('equal-value'), acts[2]), ('QSC_Arw', 1.0, [('Arrow', 'ON')]))
        self.assertEqual((evs[3]['variable-name'], evs[3].get('equal-value', 0.0), acts[3]),
                         ('QSC_Arw', 0.0, [('Arrow', 'OFF')]))

    def test_hint_frame_menu_back(self):
        """The footer hint at frame 14 is the stock key Footer03_K ('MENU Back'); frames 0..13 as stock."""
        m = self.model
        opt = m.named('Option')
        g = m.group(opt, 'Option')
        (ob, cid), = [p for p in g['pairs'] if p[0] == opt]
        p, = m.clips[(ob, cid)].props
        self.assertEqual(m.text(QP.prop_value_at(p, Fraction(QP.HINT_BACK * 100, 3))), 'Footer03_K')
        self.assertEqual(m.text(QP.prop_value_at(p, Fraction(100, 3))), 'Footer14_K')
        self.assertTrue(m.interval_admits(opt, 'Option', QP.HINT_BACK))
        stock = QP.Model(STOCK_RECS, E.pool_str)
        sp, = stock.clips[(ob, cid)].props
        for f in range(QP.HINT_BACK):
            t = Fraction(f * 100, 3)
            self.assertEqual(QP.prop_value_at(p, t), QP.prop_value_at(sp, t), f)

    def test_no_menu_switch_by_default(self):
        """v0.2.2 (live run 3): the stock 'Menu' keyEvent of every tile is as stock -- no clip of ours, no
        keyEvent of ours -- so MENU is the stock MENU at every id."""
        m = self.model
        stock = QP.Model(STOCK_RECS, E.pool_str)
        for k in range(1, 9):
            root = m.named(f'QS_CINE{k}')
            ours = [lid for lid, i in m.events(root, 'keyEvent').items() if m.text(E.be(m.recs[i], 20)) == 'QSC_Key']
            self.assertEqual(ours, [], k)
            self.assertEqual(sorted(m.events(root, 'keyEvent')), sorted(stock.events(root, 'keyEvent')), k)
            g1 = m.group(m.named('Icon01', root), 'Icon01_CINE')
            self.assertEqual([p for p in g1['pairs'] if p[0] == root], [], k)

    @unittest.skipUnless(QP.MENU_BACK, 'QSCT_MENU_BACK=1 only (the v0.2.1 MENU switch)')
    def test_menu_key_switches_at_the_sub_ids(self):
        """§10: on every tile the stock 'Menu' keyEvent (closes QS) is on at every stock and function
        id and off at 65..72, where ours (QSC_Key <- 6) is on."""
        m = self.model
        for k in range(1, 9):
            root = m.named(f'QS_CINE{k}')
            i1 = m.named('Icon01', root)
            g1 = m.group(i1, 'Icon01_CINE')
            sw, = [p for p in g1['pairs'] if p[0] == root]
            keys = {m.text(E.be(m.recs[i], 20)): lid for lid, i in m.events(root, 'keyEvent').items()}
            ours = [lid for lid, i in m.events(root, 'keyEvent').items() if m.text(E.be(m.recs[i], 20)) == 'QSC_Key']
            self.assertEqual(len(ours), 1)
            acts = [m.values(a) for a in m.actions(root, ours[0])]
            self.assertEqual(acts, [{'destination-variable': 'QSC_Key', 'value': '6'}])
            for x in CINE_IDS + list(range(QP.UI_FN0, QP.UI_SUB0)):
                t = Fraction(x * 100, 3)
                self.assertEqual((m.prop_at(*sw, 'type', 0, t) if False else
                                  [QP.prop_value_at(p, t) for p in m.clips[sw].props]), [2, 0], (k, x))
            for x in range(QP.UI_SUB0, QP.UI_LAST + 1):
                t = Fraction(x * 100, 3)
                self.assertEqual([QP.prop_value_at(p, t) for p in m.clips[sw].props], [0, 2], (k, x))
            self.assertEqual([p.c for p in m.clips[sw].props], [keys['Menu'], ours[0]])


# ---- mutations: each must make at least one test fail ----------------------------------
FUNCS_C = Q1.QT.FUNCS + [('C', 'QS Test C', 'menu_cine_fps', Q1.QT.Q_FINE)]


def boot_c(api3=False, slots=(21, 54, 56, 25, 39, 9, 55, 19)):
    """Container + QSTest (A, B, and with API 4 the fine-mode C = id 56); QS open."""
    t = Q1.tblob(api3=True) if api3 else Q1.tblob(funcs=FUNCS_C)
    c = Q1.boot([(Q1.CNAME, Q1.cblob()[0]), (Q1.TNAME, t)])
    c.layout()
    set_cine(c, slots if not api3 else (21, 54, 23, 25, 39, 9, 55, 19))
    c.posts.clear()
    c.layout()
    return c


def roles(cam):
    """{slot: {role: text}} of the footer's non-blank role texts (v0.2.2: seven roles)"""
    v = texts(cam)
    out = {}
    for j in range(QP.N_SLOT):
        for r in QP.FOOT_ROLES:
            if v[f'QSC_{r}{j}'] != ' ':
                out.setdefault(j, {})[r] = v[f'QSC_{r}{j}']
    return out


@SKIP
class Api4(unittest.TestCase):
    """v0.2.2 / API 4: fine mode, the rear dial, footer grey / custom / mark, QSC_F_TITLE, leave(); API 3
    clients keep the API 3 behaviour."""

    def test_footer_roles(self):
        c = boot_c()
        c.guid(56)
        r = roles(c)
        # five options on slots 3, 5, 7, 9, 11: C1 grey + its reason line, C2 yellow, C3 marked
        # v0.2.3: no second line -> the centred roles (FP white, FR yellow); C1 has one -> the top role FG
        self.assertEqual(r[3], {'FP': 'C0'})
        self.assertEqual(r[5], {'FG': 'C1', 'FN': 'Off'})
        self.assertEqual(r[7], {'FR': 'C2'})
        self.assertEqual(r[9], {'FP': 'C3', 'FM': QP.MARK_TEXT})
        self.assertEqual(texts(c)['QSC_FB'], 3)

    def test_fine_mode(self):
        c = boot_c()
        c.guid(56)
        self.assertEqual(c.guid_cur, 1)                        # C has a fine mode: "AEL Further Options"
        posts = press(c, 5, 56)                                # AEL: fine on, the layout stays
        self.assertEqual([n for n, _v in posts if n.startswith('MV_QSMENU')], [])
        self.assertEqual((st(c, 'fine_on'), st(c, 'fines'), st(c, 'sub_open')), (3, 1, -1))
        self.assertEqual(c.guid_cur, 0)                        # no stock "AEL back": no hint
        r = roles(c)
        self.assertEqual((r[5]['FP'], r[7], r[9]['FP']), ('<!menu_arrow_M_left,CENTER>', {'FP': 'N=0', 'FM': QP.MARK_TEXT},
                                                          '<!menu_arrow_M_right,CENTER>'))
        press(c, 1, 56)                                        # front dial: 1 step
        self.assertEqual(roles(c)[7], {'FP': 'N=1'})
        press(c, 3, 56)                                        # rear dial: +10 (API 4)
        self.assertEqual((plain(texts(c)['QSC_V3']), st(c, 'rears')), ('N=11', 1))
        press(c, 4, 56)
        self.assertEqual(plain(texts(c)['QSC_V3']), 'N=1')
        press(c, 5, 56)                                        # AEL again: fine off, the list is back
        self.assertEqual(st(c, 'fine_on'), 0)
        self.assertIn('FG', roles(c)[5])
        self.assertIn(QP.HINT_MORE, [v for n, v in c.posts if n == 'QS_FooterGuid1'][-1:])   # v0.2.3: our hint back
        press(c, 5, 56)                                        # fine on, then the focus moves away: off
        c.guid(54)
        self.assertEqual(st(c, 'fine_on'), 0)
        press(c, 5, 56)                                        # fine on, then QS closes: off
        c.layout()
        self.assertEqual(st(c, 'fine_on'), 0)

    def test_title_text_and_leave(self):
        c = boot_c()
        v = texts(c)
        self.assertEqual(v['QSC_L3'], 'QS Test C')             # QSC_F_TITLE: the label as the title
        self.assertEqual(v['QSC_L2'], ' ')                     # A: the borrowed icon look, no text
        n = st(c, 'leaves')
        self.assertEqual(st(c, 'n_leave'), 1)
        mine = Q1.T.blocks(c)[Q1.TNAME]
        mine += c.w(mine + 48 + 12) + 60 * 16 + 20             # QSTest's struct st: f[16], t, leaves
        m = c.w(mine)
        c.layout()
        self.assertEqual((st(c, 'leaves'), c.w(mine)), (n + 1, m + 1))   # every layout load calls the client's leave()
        press(c, 1, 56)
        self.assertEqual((st(c, 'leaves'), c.w(mine)), (n + 1, m + 1))   # never from the key path

    def test_api3_client_keeps_api3(self):
        c = boot_c(api3=True)
        press(c, 3, 54)                                        # rear dial on an API 3 function: +1
        self.assertEqual(plain(texts(c)['QSC_V2']), 'N=1')
        self.assertEqual(st(c, 'rears'), 0)
        press(c, 5, 54)
        v = texts(c)
        look = QP.qs_icon_looks(['menu_crop'])[0][0]
        self.assertEqual(v['QSC_L1'], f'<!{E.pool_str(look)},CENTER>')        # tile 1: the look
        self.assertEqual((v['QSC_L4'], plain(v['QSC_V4'])), ('<!menu_select_lock,CENTER>', 'LOCK'))   # lock over the title
        self.assertEqual(st(c, 'n_leave'), 0)



def boot_t(texts=(), funcs=None, slots=(21, 54, 56, 25, 39, 9, 55, 19)):
    """boot_c with QSTest's strings replaced (build_qstest texts=)"""
    t = Q1.tblob(funcs=funcs or FUNCS_C, texts=tuple(dict(texts).items()))
    c = Q1.boot([(Q1.CNAME, Q1.cblob()[0]), (Q1.TNAME, t)])
    c.layout()
    set_cine(c, slots)
    c.posts.clear()
    c.layout()
    return c


@SKIP
class Recipe024(unittest.TestCase):
    """v0.2.4 (RECIPE round): footer options wider than a 128 px slot get a wider pitch and fewer at once; a value's
    "[...]" part is plain (bold "3", thin "[1,2,1]")."""

    def slots(self, c):
        return sorted(roles(c)), texts(c)['QSC_FB'], st(c, 'foot_pitch')

    def test_short_lines_keep_the_128_px_pitch(self):
        c = boot_t()
        c.guid(56)
        self.assertEqual(self.slots(c), (SLOTS, SLOTS[0], 2))

    def test_a_long_reason_widens_the_pitch(self):
        # "SOFT →S.HBIN1 S.VBIN1" ~ 184 px: wider than 3 x 64 - 10 -> pitch 4, four options at slots 1, 5, 9, 13
        c = boot_t({'Off': 'SOFT \u2192S.HBIN1 S.VBIN1'})
        c.guid(56)
        self.assertEqual(self.slots(c), ([1, 5, 9, 13], 1, 4))
        self.assertEqual(roles(c)[5]['FG'], 'C1')
        for _ in range(4):                                      # the window follows the dial: C4 at the end
            press(c, 1, 56)
        got, box, _p = self.slots(c)
        self.assertEqual((got, box, roles(c)[13]['FP']), ([1, 5, 9, 13], 13, 'C4'))

    def test_a_long_label_counts(self):
        c = boot_t({'C2': 'LONGLABEL12'})                     # ~108 px small-font, 4/3 as a label: pitch 3, five
        c.guid(56)
        self.assertEqual(self.slots(c), ([1, 4, 7, 10, 13], 1, 3))

    def test_an_even_count_takes_an_even_pitch(self):
        c = boot_t({'STEP 1': 'STEP 1 ABCDEFGHIJKL'}, funcs=Q1.QT.FUNCS, slots=(21, 54, 23, 25, 39, 9, 55, 19))
        press(c, 5, 54)
        c.guid(72)                                              # "Toggle": Off | On, On's small ~150 px
        got, box, p = self.slots(c)
        self.assertEqual((got, p), ([5, 9], 4))

    def test_the_window_centres_the_current_option(self):
        """10-30 (mutation survivor 'window not re-centred'): ten options at pitch 3 (five at once): the current one
        sits in the middle slot (7) while it can, the window clamps at both ends"""
        src = (Q1.QT.HERE / 'qstest.c').read_text()
        old = ('    for (u32 k = 0; k < 5u; k++) f->label[k] = d->opt[k];\n    f->small[1] = d->off;\n'
               '    f->grey = 2u; f->custom = 4u; f->mark = 8u;\n    f->n = 5;\n'
               '    f->cur = qt_mod5(d->count < 0 ? -d->count : d->count);\n    return 5;')
        self.assertEqual(src.count(old), 1)
        src = src.replace(old, '    for (u32 k = 0; k < 10u; k++) f->label[k] = d->opt[k % 5u];\n    f->n = 10;\n'
                               '    u32 c = (u32)(d->count < 0 ? -d->count : d->count);\n    while (c >= 10u) c -= 10u;\n'
                               '    f->cur = c;\n    return 10;')
        with tempfile.TemporaryDirectory(prefix='qsp-window-') as t:
            f = pathlib.Path(t) / 'qstest.c'
            f.write_text(src)
            blob = Q1.QT.build(funcs=FUNCS_C, src=f, texts=(('C2', 'LONGLABEL12'),))
        c = Q1.boot([(Q1.CNAME, Q1.cblob()[0]), (Q1.TNAME, blob)])
        c.layout()
        set_cine(c, (21, 54, 56, 25, 39, 9, 55, 19))
        c.layout()
        c.guid(56)
        boxes = []
        for _ in range(10):
            got, box, p = self.slots(c)
            self.assertEqual((got, p), ([1, 4, 7, 10, 13], 3))
            boxes.append(box)
            press(c, 1, 56)
        self.assertEqual(boxes, [1, 4, 7, 7, 7, 7, 7, 7, 10, 13])

    def test_bracket_part_in_the_plain_font(self):
        funcs = Q1.QT.FUNCS + [('D', '3[1;2]', '', 0)]
        c = boot_t(funcs=funcs, slots=(21, 54, 56, 25, 39, 9, 55, 19))
        v = texts(c)['QSC_V3']
        self.assertEqual(v, '<!font_menu_LB_3,CENTER>[1;2]')


@SKIP
class MainQS(unittest.TestCase):
    """v0.2.3 (live run 4, the main QS screen): a one-line option centred and the mark thin; no borrowed icon on a
    QSC_F_TITLE tile; our tiles set the hint text (QS_FooterGuid1) themselves."""

    @classmethod
    def setUpClass(cls):
        cls.cam = boot_c()
        cls.model = QP.Model(stream(parse(cls.cam)), text_of(cls.cam))

    def drawn(self, var):
        """(rect, font size) of the strip's drawText bound to `var`"""
        m = self.model
        cont, = [i for i in m.children(m.named('QSMode')) if i >= QP.OBJ_BASE]
        for oid in m.children(cont):
            if not m.comps(oid, 'drawText'):
                continue
            b, = [m.values(i) for i in m.events(oid, 'appVariableEvent').values()]
            if b['variable-name'] == var:
                d = m.values(m.comps(oid, 'drawText')[0])
                return struct.unpack('>4f', d['rect']), d['font-size']
        raise AssertionError(var)

    def test_one_line_label_centred_and_mark_thin(self):
        for j in (0, 7, 14):
            top, size = self.drawn(f'QSC_FL{j}')
            for r in ('FP', 'FQ', 'FR'):
                rect, rsize = self.drawn(f'QSC_{r}{j}')
                self.assertEqual(rect[1] + rect[3] / 2, QP.FOOT_H / 2, (r, j))      # centred in the box
                self.assertEqual((rect[0], rect[2], rect[3], rsize), (top[0], top[2], top[3], size))   # same text
            (_x, y, _w, h), msize = self.drawn(f'QSC_FM{j}')
            lab = self.drawn(f'QSC_FP{j}')[0]
            self.assertLessEqual((h, msize), (12.0, 12))                                # thin
            self.assertGreaterEqual(y, lab[1] + lab[3] / 2 + QP.FOOT_SIZE['FP'] / 2)   # under the centred label
            self.assertLessEqual(y + h, QP.FOOT_H)                                       # inside the box

    def test_title_function_has_no_icon(self):
        """boot_c: tile 2 = A (menu_crop look, an icon), tile 3 = C (QSC_F_TITLE): Icon01 width / height 0 at C's id"""
        m = self.model
        looks = dict(zip(info()['icons'], QP.qs_icon_looks(info()['icons'])))
        for k in (2, 3):
            i1 = m.named('Icon01', m.named(f'QS_CINE{k}'))
            (ob, cid), = [p for p in m.group(i1, 'Icon01_CINE')['pairs'] if p[0] == i1]
            a, c = Fraction(49 * 100, 3), Fraction(51 * 100, 3)
            self.assertEqual(QP.f32(m.prop_at(ob, cid, 'size', 0, a)), looks['menu_crop'][QP.LOOK_SIZE], k)
            self.assertNotEqual(m.prop_at(ob, cid, 'size', 0, a), 0.0)
            self.assertEqual((m.prop_at(ob, cid, 'size', 0, c), m.prop_at(ob, cid, 'rect', 2, c)), (0.0, 0.0), k)
        self.assertEqual(texts(self.cam)['QSC_L3'], 'QS Test C')                       # the title text stays

    def test_hint_text_ours(self):
        c = boot_c()
        hint = lambda: [v for n, v in c.posts if n == 'QS_FooterGuid1']
        c.posts.clear()
        c.guid(54)                                             # A: sub-items -> our "AEL Further Options"
        self.assertEqual(hint(), [QP.HINT_MORE])
        c.posts.clear()
        c.guid(55)                                             # B: none -> no text (the stock K's frame cleared)
        self.assertEqual(hint(), [0])
        c.guid(56)
        posts = press(c, 5, 56)                                # fine mode: no stock "AEL back" -> none
        self.assertEqual([v for n, v in posts if n == 'QS_FooterGuid1'][-1], 0)
        press(c, 5, 56)
        posts = press(c, 5, 54)                                # A's sub-QS: none
        self.assertEqual([v for n, v in posts if n == 'QS_FooterGuid1'][-1], 0)
        posts = press(c, 5, 70)                                # back on A: ours again
        self.assertEqual([v for n, v in posts if n == 'QS_FooterGuid1'][-1], QP.HINT_MORE)
        c.posts.clear()
        c.guid(23)                                             # a stock tile: left to the stock code
        self.assertEqual(hint(), [])


MUTANTS = [
    # v0.2.3 (live run 4, main QS)
    ('data: one-line labels at the top (v0.2.3)', 'qs', 'footertop'),
    ('data: the v0.2.2 mark (v0.2.3)', 'qs', 'fatmark'),
    ('one-line label in the top role (v0.2.3)', 'qsct.c', 'else if (f.label[o]) t[grey ? 8 : cu ? 9 : 7] = f.label[o];',
     'else if (f.label[o]) t[grey ? 3 : cu ? 4 : 0] = f.label[o];'),
    ('spinner arrows in the top role (v0.2.3)', 'qsct.c', 't[7] = (const char *)(s->block + s->cfg->arrow_off[j == 9u]);',
     't[0] = (const char *)(s->block + s->cfg->arrow_off[j == 9u]);'),
    ('title function keeps the borrowed icon (v0.2.3)', 'qsct.c',
     'if (fi < n && (s->fx[fi].flags & QSC_F_TITLE) && (sel == 1u || sel == 2u)) *v = 0;', ''),
    ('hint text left to the stock (v0.2.3)', 'qsct.c', '((fn3)POST_INT)(0, GUID1_NAME, h ? (inner ? HINT_BACK : HINT_MORE) : 0u);', ''),
    ('hint text always "more" (v0.2.3)', 'qsct.c', '((fn3)POST_INT)(0, GUID1_NAME, h ? (inner ? HINT_BACK : HINT_MORE) : 0u);',
     '((fn3)POST_INT)(0, GUID1_NAME, HINT_MORE);'),
    ('data: MENU switch built although MENU_BACK is off (live 3)', 'qs', 'menuswitch'),
    ('data: no MENU Back hint frame', 'qs', 'nohint'),
    ('data: Icon02 triggered only by itself (fix 1)', 'qs', 'notrigger'),
    # 'nomenu' / 'menuopen' (v0.2.1's MENU switch) and the MENU-return / hint-switch mutants of qsct.c are equivalent
    # while MENU_BACK is off (v0.2.2 default): not listed
    ('data: stock footer cursor not switched off (fix 2)', 'qs', 'nocursoroff'),
    ('data: no footer strip (fix 2)', 'qs', 'nostrip'),
    ('data: no headphone closing key', 'qs', 'noclose'),
    ('data: tile events keep range 48', 'qs', 'norange'),
    ('data: dial controlValue keeps max 48', 'qs', 'nodialmax'),
    ('data: key intervals end at 1600', 'qs', 'nointerval'),
    ('data: our keyEvent never enabled', 'qs', 'noourkey'),
    ('data: Icon02 not hidden', 'qs', 'nohide'),
    ('data: text bound to the wrong component', 'qs', 'nobind'),
    ('data: header not updated', 'qs', 'noheader'),
    ('data: no Dial ON for our ids', 'qs', 'nodialon'),
    ('data: AEL writes the dial code', 'qs', 'aelcode'),
    ('data: no icon look keys', 'qs', 'nolook'),
    ('data: footer edits the shared recipe records', 'qs', 'footershared'),
    ('base not swapped', 'qsct.c', '    W(reader + R_BASE) = out - pos;\n', '    W(reader + R_BASE) = base;\n'),
    ('position not put past the stock record', 'qsct.c', '    W(reader + R_POS) = pos + t->len;', '    W(reader + R_POS) = pos + t->out_len;'),
    ('foreign copy edited', 'qsct.c', '    if (base != NBU_BASE) { s->qs_foreign++; return next(reader); }  /* another layer\'s copy */', ''),
    ('fnv not checked', 'qsct.c', '    if (rd_be(src + 4u) != t->len || fnv_bytes(src, t->len) != t->fnv) return 1;', '    if (rd_be(src + 4u) != t->len) return 1;'),
    # equivalent, not listed: the size written at the first appended record ignoring the
    # inserts -- no anchor record of this table has an insert of its own
    ('patches not applied', 'qsct.c', '        wr_be(out + pt->out, v);', '        (void)v;'),
    ('released while loading it', 'qsct.c', '    if (held == layout || !qc_releasable(held)) return;             /* later */', '    if (!qc_releasable(held)) return;'),
    ('v3 given the tree', 'qsct.c', '    ((fn1)RCACHE_V3)(RCACHE);', '    ((fn1)RCACHE_V3)(held);'),
    ('released every time', 'qsct.c', '    s->qs_boot = 1;\n    s->qs_inreload = 1;', '    s->qs_inreload = 1;'),
    ('fresh parse not counted (fix 6)', 'qsct.c', 's->qs_boot = 1; s->qs_fresh++; return;', 's->qs_boot = 1; return;'),
    ('QS layer failure still offers functions', 'qsct.c', '    if (n && (s->qs_result = qc_qs_build(s, n)) != 0) { s->freeze = F_QS; n = 0; }', '    if (n) s->qs_result = qc_qs_build(s, n);'),
    ('key not reset', 'qsct.c', '    ((fn3)POST_INT)(0, (u32)(uintptr_t)qc_name(s, S_KEY), 0);\n    if (s->phase', '    if (s->phase'),
    ('dial direction', 'qsct.c', 'code == CODE_UP || code == CODE_RUP ? 1 : -1', 'code == CODE_UP || code == CODE_RUP ? -1 : 1'),
    ('lock ignored', 'qsct.c', '    if (qc_locked(s, (u32)i)) { s->locked++; return; }\n    u32 fp = item', '    u32 fp = item'),
    ('sub-QS keeps the function in place (§10)', 'qsct.c', 'u32 id = k == 0 ? UI_MAIN :', 'u32 id = k == k0 ? UI_BASE + i :'),
    ('sub-QS focus not on tile 1 (§10)', 'qsct.c', '    ((fn3)POST_INT)(0, s->cfg->focuspos_name, at);\n', ''),
    ('return does not restore', 'qsct.c', '        ((fn3)POST_INT)(0, QS_NAME0 + 0x10u * k, ui);\n        if (k == home)', '        if (k == home)'),
    ('return focus not on the own tile (§10)', 'qsct.c', '    if (focus && home < 8u) {\n        ((fn3)POST_INT)(0, s->cfg->focuspos_name, home);\n', '    if (focus && home < 8u) {\n'),
    ('return leaves the focus stale', 'qsct.c', '        ((fn3)POST_INT)(0, s->cfg->qsmode_name, fui);', ''),
    ('layout load keeps the sub-QS', 'qsct.c', '        if (s->sub_open >= 0) qc_sub_close(s, 0);', ''),
    ('texts posted every time', 'qsct.c', '    if (i < cap && t[i] == cur[i]) return;                       /* unchanged */', ''),
    ('grey never posted', 'qsct.c', '            ((fn3)POST_INT)(0, (u32)(uintptr_t)qc_name(s, S_G + k), g);', '            (void)g;'),
    ('sub ids not converted', 'qsct.c', 's->tab_n = n + s->n + extra(s);', 's->tab_n = n + s->n;'),
    ('headphone guard: functions only', 'qsct.c', 'ours_qs(s, W(((fn0)QS_STATE)() + QS_FOCUS))', 'ours(s, W(((fn0)QS_STATE)() + QS_FOCUS))'),
    ('value in the plain font (fix 4)', 'qsct.c', 'qc_post_text(s, k, R_V, v, vfont);', 'qc_post_text(s, k, R_V, v, FONT_PLAIN);'),
    ('small line not drawn (fix 5)', 'qsct.c', 'qc_post_text(s, k, R_S, approx ? qc_blank(s) : sm, FONT_PLAIN);', 'qc_post_text(s, k, R_S, qc_blank(s), FONT_PLAIN);'),
    ('approximate line ignored', 'qsct.c', 'qc_post_text(s, k, R_Y, approx ? sm : qc_blank(s), FONT_PLAIN);', 'qc_post_text(s, k, R_Y, qc_blank(s), FONT_PLAIN);'),
    ('lock icon ignored (fix 5)', 'qsct.c', '                if (x->slock[j]) {', '                if (0) {'),
    ('tile 1 without the function look (fix 5)', 'qsct.c', '                    l = mk;\n                }\n            } else {', '                }\n            } else {'),
    ('footer not following the dial (fix 2)', 'qsct.c', '        qc_focus(s, foc, 1);                                        /* the footer follows the dial */', ''),
    ('footer not centred (fix 2)', 'qsct.c', 'u32 j0 = 7u - (p * (m ? m - 1u : 0u)) / 2u;', 'u32 j0 = 8u - m;'),
    ('footer box never drawn (fix 2)', 'qsct.c', '            if (o == f.cur) box = j;', ''),
    ('spinner ignored', 'qsct.c', 'u32 box = BOX_NONE, spin = n && f.spin,', 'u32 box = BOX_NONE, spin = 0,'),
    ('arrows always on (fix 3)', 'qsct.c', '((fn3)POST_INT)(0, (u32)(uintptr_t)qc_name(s, S_ARW), adj);', '((fn3)POST_INT)(0, (u32)(uintptr_t)qc_name(s, S_ARW), 1u);'),
    ('hint for every function (fix 3)', 'qsct.c', 'u32 inner = s->sub_open >= 0 || s->fine_on, h = inner ? qc_back_hint(s) : more;',
     'u32 inner = s->sub_open >= 0 || s->fine_on, h = 1u;'),
    ('stock hint not set', 'qsct.c', '    if (s->phase != PH_READY || !s->qs_ready || !ours_qs(s, id)) ((fn1)s->next_guid)(id);\n', ''),
    # v0.2.2 / API 4 and the live run 3 fixes
    ('fine mode never starts', 'qsct.c', '    if (s->xfine[i]) qc_fine_begin(s, i);\n    else qc_sub_open(s, i, 0, 0);', '    qc_sub_open(s, i, 0, 0);'),
    ('fine survives the focus moving', 'qsct.c', '            qc_fine_end(s, standalone);', '            (void)standalone;'),
    ('fine survives the layout load', 'qsct.c', '        qc_fine_end(s, 0);                                          /* QS was left in fine mode */', ''),
    ('rear dial +-1 on API 4', 'qsct.c', 'if (rear && (s->fx[i].flags & FX_API4)) { step *= QSC_STEP_REAR; s->rears++; }', 'if (0) { }'),
    ('rear dial +-10 on API 3 too', 'qsct.c', 'if (rear && (s->fx[i].flags & FX_API4))', 'if (rear)'),
    ('grey bit ignored', 'qsct.c', 'u32 grey = f.grey >> o & 1u, cu = f.custom >> o & 1u;', 'u32 grey = 0, cu = f.custom >> o & 1u;'),
    ('custom bit ignored', 'qsct.c', 'u32 grey = f.grey >> o & 1u, cu = f.custom >> o & 1u;', 'u32 grey = f.grey >> o & 1u, cu = 0;'),
    ('mark never drawn', 'qsct.c', '            if (f.mark >> o & 1u) t[6] =', '            if (0) t[6] ='),
    ('API 3 footer bits honoured', 'qsct.c', '    if (!v4) f.mark = f.custom = f.grey = 0;', ''),
    ('leave never called', 'qsct.c', '            ((void (*)(void *))s->leave_fn[j])((void *)(uintptr_t)s->leave_arg[j]);', ''),
    ('title flag ignored', 'qsct.c', '                if (x->flags & QSC_F_TITLE) l = s->f[i].label;', ''),
    ('small lines in the glyphs again (live 3)', 'qsct.c', 'qc_post_text(s, k, R_S, approx ? qc_blank(s) : sm, FONT_PLAIN);', 'qc_post_text(s, k, R_S, approx ? qc_blank(s) : sm, FONT_SMALL);'),
    ('wide values stay bold (live 3)', 'qsct.c', '    if (font == FONT_BIG && qc_value_width(s, t) > VALUE_W) font = FONT_PLAIN;', ''),
    ('API 4 lock over the title (live 3)', 'qsct.c', 'if ((lk == QSC_LOCK_OPEN || lk == QSC_LOCK_SHUT) && (x->flags & FX_API4))', 'if (0)'),
    ('API 4 tile 1 keeps the inline look (live 3)', 'qsct.c', '                else if (id == INT_MAIN && (x->flags & FX_API4)) l = s->f[i].label;', ''),
    ('MENU returns by default (live 3)', 'qsct.c', '        if (s->cfg->flags & CF_MENU_BACK) { qc_fine_end(s, 1); if (s->sub_open >= 0) qc_sub_close(s, 1); }',
     '        qc_fine_end(s, 1); if (s->sub_open >= 0) qc_sub_close(s, 1);'),
    ('back hint shown without MENU back', 'qsct.c', 'static u32 qc_back_hint(const struct st *s) { return s->cfg->flags & CF_MENU_BACK ? 1u : 0u; }',
     'static u32 qc_back_hint(const struct st *s) { (void)s; return 1u; }'),
    ('API 2 tables refused', 'qsct.c', 't->magic != QSC_TABLE_MAGIC && t->magic != QSC_TABLE_MAGIC2)', 't->magic != QSC_TABLE_MAGIC)'),
    # v0.2.4 (RECIPE round)
    ('v0.2.4: pitch never widens', 'qsct.c', '        if (wmax + 10u <= 64u * p || p >= 7u) break;', '        break;'),
    ('v0.2.4: labels not measured', 'qsct.c', 'b = f.label[o] ? (qc_small_w(f.label[o]) * 4u) / 3u : 0u;', 'b = 0u;'),
    ('v0.2.4: odd pitch with an even count', 'qsct.c', '        if ((p & 1u) && !(m & 1u) && p < 7u) { p++; continue; }', ''),
    ('v0.2.4: the arrow measured narrow', 'qsct.c', '{ w += 18u; i += 2u; }   /* U+2192 */', '{ w += 8u; i += 2u; }   /* U+2192 */'),
    ('v0.2.4: window not re-centred for fewer options', 'qsct.c', '            lo = f.cur > m / 2u ? f.cur - m / 2u : 0u;',
     '            lo = f.cur > 3u ? f.cur - 3u : 0u;'),
    ('v0.2.4: the bracket part bold', 'qsct.c', "        if (c == '[') font = FONT_PLAIN;", ''),
    ('v0.2.4: the bracket part measured as glyphs', 'qsct.c', "        if (c == '[') return w + 22u * qc_chars(t + i);", ''),
]


def mutate():
    src = (HERE / 'qsct.c').read_text()
    survived = []
    only = [a for a in sys.argv[1:] if a != '--mutate' and not a.startswith('--part=')]
    part = [a for a in sys.argv[1:] if a.startswith('--part=')]      # k/n: mutant i runs when i % n == k
    k_part, n_part = (int(x) for x in part[0][7:].split('/')) if part else (0, 1)
    for i_m, m in enumerate(MUTANTS):
        label = m[0]
        if (only and not any(o in label for o in only)) or i_m % n_part != k_part:
            continue
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        if env.get('SL_TESTCACHE', '1') != '0':
            env['SL_TESTCACHE'] = 'ro'              # a mutant's build is a one-off: read the cache, never write it
        with tempfile.TemporaryDirectory(prefix='qsp-mut-') as t:
            env['PYTHONPYCACHEPREFIX'] = t              # an empty bytecode cache: no stale .pyc
            if m[1] == 'qs':
                env['QSCT_QS_MUTATE'] = m[2]
            else:
                old, new = m[2], m[3]
                if src.count(old) != 1:
                    print(f'  BAD MUTANT (pattern x{src.count(old)}): {label}')
                    survived.append(label)
                    continue
                p = pathlib.Path(t) / 'qsct.c'
                p.write_text(src.replace(old, new))
                env['QSCT_SRC'] = str(p)
            r = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-q', *(['-f'] if os.environ.get('SL_MUT_FAILFAST') else []), 'test_qs_page'], cwd=HERE,
                               env=env, capture_output=True, text=True)
        failed = r.returncode != 0 and ('FAILED' in r.stderr or 'Error' in r.stderr)
        print(f'  {"caught " if failed else "SURVIVED"}  {label}', flush=True)
        if not failed:
            survived.append(label)
    n = len([m for i_m, m in enumerate(MUTANTS) if (not only or any(o in m[0] for o in only)) and i_m % n_part == k_part])
    print(f'{n - len(survived)}/{n} mutants caught')
    return 1 if survived else 0


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        sys.exit(mutate())
    unittest.main()
