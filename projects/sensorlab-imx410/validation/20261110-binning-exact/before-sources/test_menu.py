#!/usr/bin/env python3
"""Offline tests for the SensorLab-IMX410 menu rows (notes/MENU_DESIGN.md).  No camera.

    cd projects/sensorlab-imx410/menu && python3 -B -m unittest test_menu        # ~10 s, needs node
    python3 -B test_menu.py --mutate                                             # every mutant must be caught

Lists       menu_lists.py == the spec page (preview/dcres.html in node, page_lists.js): the DC / RES / FPS rows,
            the greyed rows, the current row and the summary, over every preset DC x RES and the edge states
CSV         the stock .cvm form (byte-equal with the stock B2_5_5.cvm when given its texts), header-driven parse
            back, CRLF on the last row, the text rules, the room
Capacity    no state needs more rows than the page edits are built for (CAP)
Plan        b25_plan.py's guards are the image's words; the counts the page edit is built on are pinned
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import menu_lists as M     # noqa: E402
import b25_plan as P       # noqa: E402

PAGE = HERE.parent / 'preview' / 'dcres.html'
DCS = {n: (w, h) for n, w, h in M.DCS}


def states():
    """every preset DC x RES cell of FPSDATA at several rates, plus the edge states"""
    out = []
    for key in sorted(M.fps_data()['cases']):
        n, wh = key.split(':')
        w, h = (int(v) for v in wh.split('x'))
        W, H = DCS[n]
        for fps in (24, 59.94, 119.88):
            out.append(dict(dcW=W, dcH=H, res=dict(w=w, h=h), fps=fps))
    hd = DCS['HD']
    out += [
        dict(dcW=hd[0], dcH=hd[1], resK='UHD', fps=29.97),                      # fixed K on HD
        dict(dcW=6048, dcH=4040, resK='UHD', fps=29.97),                        # ... falls back on OG
        dict(dcW=2096, dcH=1240, resRatio=1 / 6, fps=24),                       # x1/6 too small: x1, not forgotten
        dict(dcW=4192, dcH=2358, resRatio=2 / 3, fps=24),
        dict(dcW=6048, dcH=3402, resRatio=1 / 3, fps=59.94, fpsCustom=57.123),  # a tuned rate in the list
        dict(dcW=6048, dcH=3402, resRatio=1 / 3, fps=57.123, fpsCustom=57.123),
        dict(dcW=6048, dcH=3402, resRatio=1 / 3, fps=43.66504926108374),        # a recipe max (marked) is current
        dict(dcW=6048, dcH=3402, resRatio=1 / 3, fps=59.94, fine=True),
        dict(dcW=6048, dcH=4040, res=dict(w=3008, h=2010), fps=24),             # a custom RES: CUSTOM row
        dict(dcW=6048, dcH=3402, res=dict(w=3008, h=1692), fps=24),             # ... on HD: the longest RES list
        dict(dcW=5040, dcH=2834, resRatio=1 / 2, fps=24),                       # a custom DC (w18): no FPSDATA
        dict(dcW=3984, dcH=2240, resRatio=1, fps=24),
        dict(dcW=256, dcH=144, resRatio=1, fps=24),                             # the smallest DC
    ]
    return out


_PAGE_OUT = None


def page_out(sts):
    global _PAGE_OUT
    if _PAGE_OUT is None:
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(sts, f)
        r = subprocess.run(['node', str(HERE / 'page_lists.js'), str(PAGE), str(M.FPS_DATA), f.name],
                           capture_output=True, text=True, check=True)
        pathlib.Path(f.name).unlink()
        _PAGE_OUT = json.loads(r.stdout)
    return _PAGE_OUT


def compare(sts, pages):
    """[] when menu_lists gives the page's rows for every state, else the differences"""
    bad = []
    for s, p in zip(sts, pages):
        rows, cur, summ, _ = M.dc_rows(s)
        want = p['dc']['opts'] + [M.CUSTOM]
        if [t for t, _ in rows] != want or cur != (p['dc']['sel'] if p['dc']['sel'] >= 0 else len(want) - 1) or \
                summ != (p['dc']['v'] if p['dc']['sel'] >= 0 else M.CUSTOM):
            bad.append(('DC', s, rows, cur, summ, p['dc']))
        rows, cur, summ, acts = M.res_rows(s)
        want = p['res']['opts'] + [M.CUSTOM]
        if [t for t, _ in rows] != want or cur != (p['res']['sel'] if p['res']['sel'] >= 0 else len(want) - 1) or \
                summ != (p['res']['v'] if p['res']['sel'] >= 0 else M.CUSTOM) or \
                (p['res']['sel'] >= 0 and (acts[cur]['w'], acts[cur]['h']) != (p['res']['w'], p['res']['h'])):
            bad.append(('RES', s, rows, cur, summ, p['res']))
        rows, cur, summ, acts = M.fps_rows(s)
        want = [((M.CUSTOM + ' ' + o['l']) if o['custom'] else o['l'], not o['na']) for o in p['fps']['opts']]
        if not any(o['custom'] for o in p['fps']['opts']):
            want.append((M.CUSTOM, True))
        if not p['fps']['opts']:
            want = [('Unavailable', False), (M.CUSTOM, False)]
        want_cur = (p['fps']['sel'] if p['fps']['sel'] >= 0 else len(want) - 1) if p['fps']['opts'] else 0
        if rows != want or cur != want_cur or summ != p['fps']['v'] or \
                any((a['op'] == 'none') != (not on) for a, (_t, on) in zip(acts, rows)):
            bad.append(('FPS', s, rows[:4], cur, summ, p['fps']['sel'], p['fps']['v']))
    return bad


class Lists(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sts = states()
        cls.pages = page_out(cls.sts)

    def test_rows_are_the_pages(self):
        bad = compare(self.sts, self.pages)
        self.assertEqual(bad[:3], [])

    def test_the_states_reach_every_case(self):
        p = self.pages
        self.assertTrue(any(x['dc']['sel'] < 0 for x in p), 'a custom DC')
        self.assertTrue(any(x['res']['sel'] < 0 for x in p), 'a custom RES')
        self.assertTrue(any(o['custom'] for x in p for o in x['fps']['opts']), 'a tuned rate')
        self.assertTrue(any(o['na'] for x in p for o in x['fps']['opts']), 'a greyed rate')
        self.assertTrue(any(not x['fps']['q'] for x in p), 'no FPSDATA (the camera computes)')
        self.assertTrue(any('UHD' in x['res']['opts'] for x in p), 'HD extras')

    def test_custom_rows_open_the_sub_qs(self):
        s = dict(dcW=6048, dcH=4040, res=dict(w=3008, h=2010), fps=24)
        rows, cur, summ, acts = M.res_rows(s)
        self.assertEqual((rows[cur][0], summ, acts[cur]), (M.CUSTOM, M.CUSTOM, dict(op='open', sub='RES')))
        rows, cur, summ, acts = M.dc_rows(dict(s, dcW=5040, dcH=2834))
        self.assertEqual((rows[-1][0], cur, acts[-1]), (M.CUSTOM, 6, dict(op='open', sub='DC')))
        s = dict(dcW=6048, dcH=3402, resRatio=1 / 3, fps=59.94, fpsCustom=57.123)
        rows, cur, summ, acts = M.fps_rows(s)
        k = next(i for i, (t, _) in enumerate(rows) if t.startswith(M.CUSTOM))
        self.assertEqual((rows[k][0], acts[k]['op'], acts[k]['sub']), ('CUSTOM 57.123', 'open', 'FPS'))
        self.assertEqual(summ, '59.94')
        # CUSTOM is always an entry into fine adjustment, even at a preset.
        s = dict(dcW=6048, dcH=3402, resRatio=1 / 3, fps=59.94)
        for fn in (M.dc_rows, M.res_rows, M.fps_rows):
            self.assertTrue(any(t.startswith(M.CUSTOM) for t, _ in fn(s)[0]), fn.__name__)
            self.assertEqual(fn(s)[3][-1]['op'], 'open')

    def test_bit_row(self):
        rows, cur, summ, acts = M.bit_rows(dict(bit=2))
        self.assertEqual(rows, [('8 bit', True), ('10 bit', True), ('RAW bit', True)])   # 0.0.3test: 8 / 10 selectable
        self.assertEqual((cur, summ), (2, 'RAW'))
        self.assertEqual(acts, [dict(op='stock', value=v) for v in (0, 1, 2)])
        self.assertEqual(M.bit_rows(dict(bit=0))[2], '8 bit')       # a stock 8-bit setting is shown as it is

    def test_std_mode(self):
        s = dict(dcW=6048, dcH=3402, resRatio=1 / 3, fps=43.66504926108374, fpsCustom=57.123)
        rows, cur, summ, _ = M.fps_rows(s, 'std')
        self.assertEqual(len(rows), 29 + 2)                         # the common rates + the current max + tuned
        self.assertEqual((rows[cur][0], summ), ('43.665', '43.665'))


class Csv(unittest.TestCase):
    def test_writer_is_the_stock_form(self):
        img = P.Image().img
        stock = img[0xC0F8E848 - P.B:0xC0F8E848 - P.B + 257]                       # B2_5_5.cvm
        texts = ['0316', '1916', '0317', '0318', '2115', '0319', '0320', '0321', '0322']
        self.assertEqual(M.csv_bytes([(t, True) for t in texts]), stock)
        stock = img[0xC0F8E71C - P.B:0xC0F8E71C - P.B + 113]                       # B2_5_2_excl.cvm: 0,0 greys
        self.assertEqual(M.csv_bytes([('0305', True), ('0306', False), ('0307', False)]), stock)

    def test_round_trip_and_room(self):
        for s in states()[::7]:
            for k, fn in M.ROWS.items():
                rows = fn(s)[0]
                if rows:
                    self.assertEqual(M.parse_csv(M.csv_bytes(rows, M.CAP[k])), rows)

    def test_the_last_row_needs_its_crlf(self):
        data = M.csv_bytes([('1K', True), ('2K', True)])
        with self.assertRaises(M.TextError):
            M.parse_csv(data[:-2])

    def test_text_rules(self):
        for t in ('', 'A,B', '"x"', '23.98p<', 'a' * 32, '×'):
            with self.assertRaises(M.TextError):
                M.check_text(t)
        with self.assertRaises(M.TextError):
            M.csv_bytes([('x', True)] * 4, cap=3)


class Capacity(unittest.TestCase):
    def test_no_state_needs_more_rows(self):
        worst = {k: 0 for k in M.CAP}
        for s in states():
            for k, fn in M.ROWS.items():
                worst[k] = max(worst[k], len(fn(s)[0]))
        for W in range(256, 6049, 64):                                           # any custom DC: the RES list
            for H in range(144, 4041, 32):
                worst['RES'] = max(worst['RES'], len(M.res_list(W, H)) + 1)
        for k in M.CAP:
            self.assertLessEqual(worst[k], M.CAP[k], k)
        self.assertEqual((worst['DC'], worst['RES'], worst['BIT']), (7, 10, 3))   # pinned: the page edits' sizes
        self.assertGreaterEqual(worst['FPS'], 46)

    def test_too_many_maxima_fall_back_to_the_common_rates(self):
        data = dict(clk=72e6, cases={'HD:2016x1134': [[400, 1800 + 7 * i, 'q', dict(hbin=1, vbin=1)]
                                                    for i in range(60)]})
        s = dict(dcW=6048, dcH=3402, resRatio=1 / 3, fps=24)
        rows = M.fps_rows(s, data=data)[0]
        self.assertLessEqual(len(rows), M.CAP['FPS'])
        self.assertEqual(len(rows), 30)


class Plan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.im = P.Image()
        cls.plan = P.plan(cls.im)

    def test_guards_hold_the_stock_words(self):
        for k, v in self.plan.items():
            for e in v['renames'] + v['summary'] + v['caps']:
                at = e['addr'] - P.B
                self.assertEqual(P.u32(self.im.img, at), e['word'], (k, e))
            for e in v['renames'] + v['summary']:
                self.assertEqual(self.im.text(e['word']), e['old'], (k, e))

    def test_counts_the_edit_is_built_on(self):
        n = {k: (len(v['renames']), len(v['summary'])) for k, v in self.plan.items()}
        self.assertEqual(n, {'RES': (10, 2), 'FPS': (18, 9), 'BIT': (2, 1), 'DC': (11, 2)})
        caps = {k: {c['owner_name']: c['value'] for c in v['caps']} for k, v in self.plan.items()}
        self.assertEqual(caps['RES']['List'], 1.0)          # 2 stock rows
        self.assertEqual(caps['FPS']['List'], 8.0)          # 9
        self.assertEqual(caps['BIT']['List'], 2.0)          # 3
        self.assertEqual(caps['DC']['List'], 2.0)           # Off / On / Auto
        for k in ('RES', 'FPS', 'BIT'):
            self.assertIn('IconChange', caps[k])            # the third cap (fp-native-ui §2 rule 9)

    def test_every_stock_name_of_a_row_is_renamed(self):
        for k, row in P.ROWS.items():
            seen = {e['old'] for e in self.plan[k]['renames']}
            for old in row['rename']:
                if old in row['csv'] or not old.startswith('B2_5_'):
                    self.assertIn(old, seen, (k, old))

    def test_private_names(self):
        pool = self.im.pool
        names = {e['new'] for v in self.plan.values() for e in v['renames']}
        self.assertTrue({'SLM_Res', 'EXCL_SLM_Res', 'SLM_Fps', 'EXCL_SLM_Fps', 'SLM_Dc', 'EXCL_SLM_Dc'} <= names)
        for s in names:
            self.assertTrue(s.startswith(('SLM_', 'EXCL_SLM_')), s)
            self.assertNotIn(b'\0' + s.encode() + b'\0', pool, s)


MUTANTS = [
    ('res_list keeps duplicates', 'res_list', lambda f: lambda W, H: f(W, H) + f(W, H)[:1]),
    ('no FHD / UHD on HD', 'dc_name', lambda f: lambda W, H: 'X' if f(W, H) == 'HD' else f(W, H)),
    ('K label rounds half to even', 'js_round', lambda f: lambda x: round(x)),
    ('grey without the tolerance', 'same', lambda f: lambda a, b: abs(a - b) < 1e-9),
    ('common rates as toFixed', 'fmt_f', lambda f: lambda o: M.to_fixed(o['f'], 3)),
    ('no CUSTOM row for a custom RES', 'res_rows',
     lambda f: lambda s: (lambda r: ([x for x in r[0] if x[0] != M.CUSTOM], r[1], r[2], r[3]))(f(s))),
    ('tuned rate not listed', 'fps_list', lambda f: lambda s, d=None: [o for o in f(s, d) if not o['custom']]),
    ('the last CRLF dropped', 'csv_bytes', lambda f: lambda rows, cap=None: f(rows, cap)[:-2]),
    ('greys written selectable', 'csv_bytes', lambda f: lambda rows, cap=None: f([(t, True) for t, _ in rows], cap)),
    ('RES cap too small', 'CAP', lambda c: dict(c, RES=9)),
    ('plan misses the list names', 'clip_strings', lambda f: lambda rec: []),
    ('0.0.3test: 8 / 10 bit greyed again', 'BIT_ROWS', lambda r: (('8 bit', False), ('10 bit', False), r[2])),
]


def mutate():
    failed = []
    for name, attr, make in MUTANTS:
        mod = P if hasattr(P, attr) and not hasattr(M, attr) else M
        old = getattr(mod, attr)
        setattr(mod, attr, make(old))
        try:
            r = unittest.TextTestRunner(stream=open('/dev/null', 'w'), verbosity=0).run(
                unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
            caught = not r.wasSuccessful()
        finally:
            setattr(mod, attr, old)
        print(('caught  ' if caught else 'MISSED  ') + name)
        if not caught:
            failed.append(name)
    return failed


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        sys.exit(1 if mutate() else 0)
    unittest.main()
