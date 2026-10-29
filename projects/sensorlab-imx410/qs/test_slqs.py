#!/usr/bin/env python3
"""SensorLab-IMX410 QS client v0.2.0test on the real ARM bytes, offline, against the preview it ports.

The real v4 core loads the real QSContainer_v0.2.2.BIN and the real SensorLab-IMX410_v0.2.0test.BIN against the real
firmware image (the container's test camera, projects/qs-container/test_qsct.py + test_qs_page.py).  Everything the
tests read comes out of the client's C: the texts the container posts for the tiles, the client's footer callback
called directly, the record written into its own BIN, the recipes the C core computes on the "camera".

The reference is the preview itself (preview/dcres.html, Bei's spec): preview_runner.js runs the page's own logic in
node over scripted key sequences; FPSDATA for every cell a sequence visits (custom DC x RES included) is generated
from the same Python (preview/gen_fps.py fpsdata(): isp-lab/host/quality.py, tol 2 %).  After every step the C
client's visible state must equal the page's.

    cd projects/sensorlab-imx410/qs && python3 -B -m unittest test_slqs
    python3 -B test_slqs.py --mutate [--part=k/n]   # every mutant must fail a test (part k of n: run in parallel)
    python3 -B test_slqs.py --timing           # core_qualities cost in emulation
"""
import json
import os
import re
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
QSC = ROOT / 'projects' / 'qs-container'
PREVIEW = HERE.parent / 'preview'
sys.path[:0] = [str(HERE), str(QSC), str(PREVIEW)]
if os.environ.get('SLQS_BUILD_SRC'):        # mutation runs of the build script itself
    import importlib.util
    _spec = importlib.util.spec_from_file_location('build_slqs', os.environ['SLQS_BUILD_SRC'])
    BS = importlib.util.module_from_spec(_spec)
    sys.modules['build_slqs'] = BS
    _spec.loader.exec_module(BS)
else:
    import build_slqs as BS                # noqa: E402
import test_qsct as Q1                     # noqa: E402
import test_qs_page as TP                  # noqa: E402
import gen_fps as G                        # noqa: E402

T3, F6 = Q1.T3, Q1.F6
SKIP = unittest.skipIf(Q1.T.Uc is None or not Q1.IMG or not __import__('shutil').which('node'),
                       'needs unicorn, out/MAIN_c0000000.bin and node; skipped = unverified')
PATH = '\\fpSup\\' + BS.file_name()
DC_ID, RES_ID, FPS_ID, RCP_ID, FMT_ID = 54, 55, 56, 57, 58      # the client's five functions (the only client)
SLOTS = (FMT_ID, DC_ID, RES_ID, FPS_ID, RCP_ID, 9, 27, 19)        # the page's MAIN: FORMAT DC RES FPS RECIPE + stock
FOOT = F6.FAKE + 0x9000                    # a struct qsc_foot for direct calls
FOOT_WORDS = 6 + 32 + 1
SUBS = 7
FX_BYTES = 4 * 8 + 4 * SUBS * 6 + 12 * SUBS + 28 * SUBS
LOCK = {'\U0001F512': '<!menu_select_lock,CENTER>', '\U0001F513': '<!menu_select_unlock,CENTER>'}
OPT_MAP = {'\U0001F512 固定': 'LOCK', '\U0001F513 自由': 'FREE'}
_built = {}


def blob():
    if 'b' not in _built:
        _built['b'] = BS.build()
    return _built['b']


def boot(card=None, prepare=None):
    """Core + container + client; QS open on the CINE layout of the page's MAIN."""
    data = card if card is not None else blob()[0]
    c = Q1.boot([(Q1.CNAME, Q1.cblob()[0]), (BS.file_name(), data)], prepare=prepare)
    c.layout()
    TP.set_cine(c, SLOTS)
    c.layout()
    return c


def st_addr(c):
    return Q1.T.blocks(c)[BS.file_name()] + blob()[1]['state_off']


def fn_addr(c, name):
    return Q1.T.blocks(c)[BS.file_name()] + blob()[1]['code_off'] + blob()[1]['functions'][name]


def plain(t):
    return TP.plain(t)


def tile(c, k):
    """(title, value, small, approx) of tile k (0-based), glyph markup back to text"""
    t = TP.texts(c)
    y = t[f'QSC_Y{k + 1}']
    return (plain(t[f'QSC_L{k + 1}']), plain(t[f'QSC_V{k + 1}']), plain(y if y != ' ' else t[f'QSC_S{k + 1}']),
            y != ' ')


def focus_int(c, k):
    """the internal id of tile k now (the user's layout, or the open sub-QS)"""
    if TP.st(c, 'sub_open') >= 0:
        return c.w(c.st() + TP.LAYOUT['sub_tile'] + 4 * k) + 5
    return SLOTS[k]


def footer(c, internal):
    """the client's footer callback for the function / sub-item `internal`, called directly:
    dict(n, cur, spin, items [(label, small, approx, mark, custom, grey)])"""
    i = internal - 54 if internal < 70 else TP.st(c, 'sub_open')
    fx = c.st() + TP.LAYOUT['fx'] + FX_BYTES * i
    if internal < 71:
        fn, arg = c.w(fx + 28), c.w(fx + 16)
    else:
        j = internal - 71
        fn, arg = c.w(fx + 32 + 4 * SUBS * 4 + 4 * j), c.w(fx + 32 + 4 * SUBS * 2 + 4 * j)
    c.mu.mem_write(FOOT, bytes(4 * FOOT_WORDS))
    n, _sp = c.call(fn & ~1, r0=arg, r1=FOOT, thumb=bool(fn & 1))
    w = struct.unpack(f'<{FOOT_WORDS}I', bytes(c.mu.mem_read(FOOT, 4 * FOOT_WORDS)))
    items = []
    for k in range(n):
        lab = c.cstr(w[6 + k], 256)
        sm = c.cstr(w[6 + 16 + k], 256) if w[6 + 16 + k] else ''
        items.append((lab, sm, bool(w[2] >> k & 1), bool(w[4] >> k & 1), bool(w[5] >> k & 1), bool(w[38] >> k & 1)))
    return dict(n=n, cur=w[1], spin=w[3], items=items)


def press(c, code, k):
    return TP.press(c, code, focus_int(c, k))


# ---------------------------------------------------------------------------------- the preview in node
def run_page(seqs, data):
    with tempfile.TemporaryDirectory(prefix='slqs-page-') as t:
        d, s = pathlib.Path(t) / 'data.json', pathlib.Path(t) / 'seq.json'
        d.write_text(json.dumps(data))
        s.write_text(json.dumps(seqs))
        r = subprocess.run(['node', os.environ.get('SLQS_RUNNER') or str(HERE / 'preview_runner.js'), str(PREVIEW / 'dcres.html'), str(d), str(s),
                            '--cells'], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr)
        return json.loads(r.stdout)


_DATA = {}


def page_data(seqs):
    """FPSDATA for the presets and every cell the sequences visit (custom ones generated too)"""
    key = json.dumps(seqs)
    if key in _DATA:
        return _DATA[key]
    cells = [(f'{n}:{w}x{h}', W, H, w, h) for n, W, H, rs in G.preset_lists() for w, h in rs]
    data = G.fpsdata(cells)
    seen = {k: (W, H, w, h) for k, W, H, w, h in cells}
    for _ in range(3):                                   # visiting a cell can lead to more cells
        got = run_page(seqs, data)['cells']
        new = [(k, *v) for k, v in got.items() if k not in data['cases']]
        for k, v in got.items():
            if k in seen and seen[k] != tuple(v):
                raise AssertionError(f'two custom DCs share the page key {k}: {seen[k]} / {v}')
            seen[k] = tuple(v)
        if not new:
            break
        more = G.fpsdata(new)
        data['cases'].update(more['cases'])
        data['nominal'].update(more['nominal'])
    _DATA[key] = data
    return data


def page_states(seqs):
    return run_page(seqs, page_data(seqs))['out']


def window(n, cur):
    if n <= 16:
        return 0, n
    a = max(0, min(cur - 7, n - 15))
    return a, 15


def compare(c, st):
    """the C client's visible state vs the page's: list of differences"""
    diff = []
    sub = st['sub']
    for k, p in enumerate(st['tiles']):
        if sub is None and k >= 5:
            continue                                     # stock tiles: not ours
        title, v, s, ap = tile(c, k)
        if p is None:
            if (v, s) != (' ', ' '):
                diff.append((k, 'blank', v, s))
            continue
        pv = 'CUSTOM' if p['v'] == 'Custom' else LOCK.get(p['v'], p['v'])
        ps = p['s'] if p['s'] else ' '
        if (v, s, ap) != (pv, ps, p['approx']):
            diff.append((k, (v, s, ap), (pv, ps, p['approx'])))
        if sub is not None and k > 0 and title != p['t']:
            diff.append((k, 'title', title, p['t']))
        if sub is None and k == 4 and title != 'RECIPE':
            diff.append((k, 'title', title))
    f = st['foot']
    if f is not None:
        got = footer(c, focus_int(c, st['focus']))
        if 'spin' in f:
            want = (1, [f['spin']], f['mark'])
            have = (got['spin'], [x[0] for x in got['items']], bool(got['items'] and got['items'][0][3]))
            if have != want:
                diff.append(('spin', have, want))
        else:
            o = f['opts']
            lo, n = window(len(o), f['sel'])
            want = [(OPT_MAP.get(x['l'], x['l']), x['s'], x['approx'], x['mark'], x['custom'], x['na'])
                    for x in o[lo:lo + n]]
            if [x for x in got['items']] != want:
                diff.append(('foot', got['items'], want))
            wcur = f['sel'] - lo if f['sel'] >= 0 else n
            if got['cur'] != wcur:
                diff.append(('foot cur', got['cur'], wcur))
    return diff


def drive(c, keys, states, check=True):
    """replay `keys` on the camera; after each, compare with the page's state.  Returns [(step, diff)]"""
    bad = []
    prev = states[0]
    if check:
        c.guid(focus_int(c, prev['focus']))
        d = compare(c, prev)
        if d:
            bad.append((0, 'start', d))
    for i, k in enumerate(keys, 1):
        st = states[i]
        if k in ('f+', 'f-', 'r+', 'r-'):
            if prev['open']:
                press(c, {'f+': 1, 'f-': 2, 'r+': 3, 'r-': 4}[k], prev['focus'])
        elif k == 'ael':
            if prev['open']:
                press(c, 5, prev['focus'])
                if c.w(Q1.QSOBJ + 0xBC) != focus_int(c, st['focus']):
                    bad.append((i, k, 'focus', c.w(Q1.QSOBJ + 0xBC), focus_int(c, st['focus'])))
        elif k in ('qs', 'ok'):
            c.layout()                                   # QS closed (or opened): a layout load
            if st['open']:
                c.guid(focus_int(c, st['focus']))
        else:                                            # a focus move (arrow keys, a tile touched)
            if st['open'] and (st['focus'] != prev['focus'] or st['fine'] != prev['fine']):
                c.guid(focus_int(c, st['focus']))
        if check and st['open']:
            d = compare(c, st)
            if d:
                bad.append((i, k, d))
                if len(bad) > 3:
                    break
        prev = st
    return bad


SEQS = [
    dict(name='dc dial, stops at the ends', keys=['focus:1'] + ['f+'] * 6 + ['f-'] * 7 + ['f+']),
    dict(name='res dial, from custom', keys=['focus:2', 'f-', 'f-', 'f-'] + ['f+'] * 12 +
         ['focus:1', 'f+', 'focus:2', 'f-', 'f-', 'f+']),
    dict(name='dc sub, locked aspect (live 3 drift)', keys=['focus:1', 'ael', 'focus:1'] + ['f-'] * 7 + ['f+'] * 7 +
         ['f-', 'f+', 'f-', 'f-', 'f+', 'f+', 'focus:2', 'f-', 'f+', 'r-', 'r+', 'focus:3', 'f+', 'focus:2', 'f-', 'f+', 'focus:3', 'f+', 'focus:1',
         'r+', 'r+', 'r-', 'ael']),
    dict(name='res sub and per-crop memory', keys=['focus:2', 'ael', 'focus:1', 'f-', 'f+', 'f-', 'focus:2', 'f-',
         'focus:3', 'f+', 'focus:2', 'f-', 'f+', 'f+', 'focus:1', 'r-', 'ael', 'focus:1', 'f+', 'f-', 'focus:2', 'f+',
         'focus:1', 'f+', 'f-']),
    dict(name='fixed K by label across DCs', keys=['focus:2', 'f+', 'f+', 'f+', 'f+', 'focus:1', 'f-', 'f+', 'f+',
         'f+', 'f+', 'f-', 'f-', 'f-', 'focus:2', 'f+', 'f-']),
    dict(name='ratio kept on a small DC', keys=['focus:2', 'f-', 'f-', 'f-', 'focus:1', 'ael', 'focus:1'] +
         ['r-'] * 34 + ['r+'] * 6 + ['ael', 'focus:2']),
    dict(name='fps list, grey skipped, fixFps', keys=['focus:3'] + ['f+'] * 10 + ['f-'] * 3 +
         ['focus:2', 'f+', 'f+', 'f+', 'f+', 'focus:3'] + ['f+'] * 5 + ['f-'] * 4),
    dict(name='fps fine mode', keys=['focus:3', 'ael', 'f+', 'f+', 'f+', 'r+', 'r+', 'f-', 'ael', 'f+', 'f-', 'f-',
         'ael', 'r-', 'focus:4', 'focus:3', 'f+', 'ael', 'r+', 'qs', 'qs', 'f+', 'f-']),
    dict(name='fps fine at a switch point, marks', keys=['focus:1', 'f-', 'focus:2'] + ['f+'] * 6 +
         ['focus:3', 'f+', 'f+', 'f+', 'ael', 'f-', 'f+', 'f+', 'r-', 'ael', 'f+', 'f-', 'focus:2', 'f-', 'focus:3', 'ael',
          'r+', 'r+', 'ael']),
    dict(name='recipe dial, choice kept while fps is too high', keys=['focus:4'] + ['f+'] * 8 + ['f-'] * 10 +
         ['focus:3'] + ['f+'] * 6 + ['focus:4', 'f+', 'f-', 'focus:3'] + ['f-'] * 6 + ['focus:4']),
    dict(name='recipe sub-QS', keys=['focus:4', 'ael', 'focus:1', 'f+', 'f+', 'f-', 'focus:2', 'f+', 'f-', 'focus:4',
         'f-', 'f-', 'focus:5', 'f-', 'f-', 'f+', 'f-', 'f-', 'focus:6', 'f+', 'f+', 'f+', 'f-', 'focus:7', 'f+', 'f+',
         'focus:3', 'f+', 'focus:6', 'f-', 'f-', 'focus:1', 'f-', 'f-', 'ael', 'focus:0', 'focus:3']),
    dict(name='OG 3K, a short recipe, FORMAT 14bit', keys=['focus:1', 'f-', 'focus:2', 'f+', 'focus:3'] + ['f-'] * 12 +
         ['focus:4'] +
         ['f+'] * 7 + ['focus:0', 'focus:4'] + ['f-'] * 7 + ['focus:2']),
    dict(name='QS closed with the sub-QS up', keys=['focus:2', 'ael', 'focus:1', 'f-', 'qs', 'qs', 'focus:2', 'f+',
         'ok', 'qs', 'focus:3', 'f+']),
    dict(name='S16 and SQ, sensor windows', keys=['focus:1', 'f+', 'f+', 'f+', 'focus:2', 'f-', 'focus:4', 'ael',
         'focus:2', 'f+', 'f-', 'focus:3', 'f+', 'f-', 'focus:4', 'f-', 'f+', 'ael', 'focus:1', 'f+', 'focus:4', 'f+',
         'f+', 'focus:3', 'f+']),
]


@SKIP
class Preview(unittest.TestCase):
    """The page's visible state, step for step, for every scripted sequence."""

    @classmethod
    def setUpClass(cls):
        cls.states = page_states(SEQS)

    def run_seq(self, i):
        seq, got = SEQS[i], self.states[i]
        c = boot()
        bad = drive(c, seq['keys'], got['states'])
        self.assertEqual(bad, [], seq['name'])

    def test_00(self): self.run_seq(0)
    def test_01(self): self.run_seq(1)
    def test_02(self): self.run_seq(2)
    def test_03(self): self.run_seq(3)
    def test_04(self): self.run_seq(4)
    def test_05(self): self.run_seq(5)
    def test_06(self): self.run_seq(6)
    def test_07(self): self.run_seq(7)
    def test_08(self): self.run_seq(8)
    def test_09(self): self.run_seq(9)
    def test_10(self): self.run_seq(10)
    def test_11(self): self.run_seq(11)
    def test_12(self): self.run_seq(12)
    def test_13(self): self.run_seq(13)

    def test_sequences_reach_what_they_name(self):
        """the scripts reach the states the review asked for (else a passing comparison proves little)"""
        last = lambda i: self.states[i]['states'][-1]
        every = lambda i: self.states[i]['states']
        self.assertTrue(any(s['tiles'][1] and s['tiles'][1]['v'] == 'SQ' for s in every(0)))
        self.assertTrue(any(s['fine'] for s in every(7)))
        self.assertTrue(any(s['S']['fpsCustom'] for s in every(7)))
        self.assertTrue(any(s['foot'] and 'opts' in s['foot'] and any(o['na'] for o in s['foot']['opts']) for s in every(6)))
        self.assertTrue(any(s['tiles'][2] and s['tiles'][2]['approx'] for s in every(11)))     # RES short (yellow)
        self.assertTrue(any(s['tiles'][0] and s['tiles'][0]['s'] == '14bit' for s in every(11)))
        self.assertTrue(any(s['sub'] == 'recipe' and s['foot'] and 'opts' in s['foot'] and
                            any(o['s'].startswith(('no ', 'needs')) or ' · needs' in o['s'] for o in s['foot']['opts'])
                            for s in every(10)))
        self.assertTrue(any(s['sub'] == 'recipe' and s['tiles'][6]['v'] == '3' for s in every(10)))   # an ISP bin
        self.assertTrue(any(s['tiles'][4] and s['tiles'][4]['v'] == 'CUSTOM' for s in every(10)))
        self.assertTrue(any(s['tiles'][1] and s['tiles'][1]['v'] == 'Custom' for s in every(5)))
        self.assertTrue(any(s['foot'] and s['foot'].get('mark') for s in every(8)))


@SKIP
class Tiles(unittest.TestCase):
    def test_qs_open(self):
        c = boot()
        self.assertEqual(Q1.stw(c, Q1.ST_N), 5)
        self.assertEqual(tile(c, 0)[1:], ('DNG', '12bit', False))
        self.assertEqual(tile(c, 1)[1:3], ('HD', '35.9 × 20.2 mm'))
        self.assertEqual(tile(c, 4)[0], 'RECIPE')                       # QSC_F_TITLE: text, not an icon
        self.assertTrue(tile(c, 3)[2].endswith(' recipes'))

    def test_recipe_sub_qs_has_seven_items(self):
        c = boot()
        c.guid(RCP_ID)
        press(c, 5, 4)
        self.assertEqual([tile(c, k)[0] for k in range(8)],
                         ['RECIPE', 'ADC', 'SENSOR HDC', 'SENSOR VDC', 'SENSOR HBIN', 'SENSOR VBIN', 'ISP HBIN', 'ISP VBIN'])
        self.assertEqual(c.w(c.st() + TP.LAYOUT['sub_tile'] + 28), 72)    # the 7th item on UI 72

    def test_format_has_no_dial_and_mov_is_grey(self):
        c = boot()
        c.guid(FMT_ID)
        f = footer(c, FMT_ID)
        self.assertEqual([(x[0], x[5]) for x in f['items']], [('DNG', False), ('MOV', True)])
        before = tile(c, 0)
        press(c, 1, 0)
        self.assertEqual(tile(c, 0), before)


@SKIP
class Exact(unittest.TestCase):
    """The JavaScript doubles the page computes with, against node, over the whole domain (sq_test in the BIN)."""

    @classmethod
    def setUpClass(cls):
        cls.c = boot()

    def t(self, op, a=0, b=0, cc=0):
        fn = fn_addr(self.c, 'sq_test')
        self.c.mu.reg_write(Q1.T3.UC_ARM_REG_R3, cc)
        r, _ = self.c.call(fn & ~1, r0=op, r1=a, r2=b, thumb=True)
        return r - (1 << 32) if r >> 31 else r

    def txt(self, op, a=0, b=0):
        return self.c.cstr(self.t(op, a, b) & 0xFFFFFFFF, 64)

    def node(self, src):
        return json.loads(subprocess.run(['node', '-e', src], capture_output=True, text=True, check=True).stdout)

    def test_ratios_widths_heights(self):
        want = self.node('const a16=w=>Math.floor(w/16)*16, ev=h=>Math.floor(h/2)*2, R=[1,2/3,1/2,1/3,1/6];'
                         'const o=[];for(let W=0;W<=6064;W+=2)for(let r=0;r<5;r++)o.push([a16(W*R[r]),ev(W*R[r])]);'
                         'console.log(JSON.stringify(o))')
        got, k = [], 0
        for W in range(0, 6065, 2):
            for r in range(5):
                got.append([self.t(1, W, r), self.t(2, W, r)])
        self.assertEqual(got, want)

    def test_texts(self):
        """mm (px * (35.9 / 6048)).toFixed(1) for every even px, kLabel for every 16th width, (w / h).toFixed(3)"""
        want = self.node('const P=35.9/6048, o=[];for(let p=0;p<=6064;p+=2)o.push((p*P).toFixed(1));'
                         'for(let w=16;w<=6064;w+=16){const x=w/1024;o.push((x<0.75?(Math.round(x*10)/10).toFixed(1):'
                         'String(Math.round(x*2)/2))+"K")}'
                         'for(let w=256;w<=6048;w+=48)for(let h=144;h<=4040;h+=26)o.push((w/h).toFixed(3));'
                         'console.log(JSON.stringify(o))')
        got = [self.txt(3, p) for p in range(0, 6065, 2)] + [self.txt(5, w) for w in range(16, 6065, 16)]
        got += [self.txt(4, w, h) for w in range(256, 6049, 48) for h in range(144, 4041, 26)]
        self.assertEqual(got, want)

    def test_lock_rounding_and_aspect(self):
        """rh(w / asp), rw(h * asp) for the page's aspects, and |p.w/p.h - asp| < 0.002"""
        asps = [(6048, 3402), (6048, 4040), (4192, 2358), (3952, 2624), (2096, 1240), (4032, 4032), (2016, 1134),
                (2000, 1124), (3008, 2010), (1008, 672), (1392, 786), (6032, 3402), (4080, 2296)]
        want = self.node('const A=%s;const o=[];for(const [a,b] of A){const asp=a/b;'
                         'for(let w=240;w<=6064;w+=16)o.push(Math.round(w/asp/2)*2);'
                         'for(let h=140;h<=4044;h+=2)o.push(Math.round(h*asp/16)*16);}console.log(JSON.stringify(o))'
                         % json.dumps(asps))
        got = []
        for a, b in asps:
            got += [self.t(6, w, a, b) for w in range(240, 6065, 16)]
            got += [self.t(7, h, a, b) for h in range(140, 4045, 2)]
        self.assertEqual(got, want)
        pairs = [(pw, ph, a, b) for pw, ph in ((6048, 3402), (4192, 2358), (2016, 1134), (2016, 1132), (3008, 1692),
                                               (2000, 1124), (2032, 1144), (1008, 566), (6048, 3400), (4032, 2268))
                 for a, b in asps] + [(500, 1, 1001, 2), (501, 1, 1001, 2), (1002, 2, 1001, 2)]
        want = self.node('const P=%s;console.log(JSON.stringify(P.map(([pw,ph,a,b])=>Math.abs(pw/ph-a/b)<0.002?1:0)))'
                         % json.dumps(pairs))
        self.assertEqual([self.t(8, pw << 16 | ph, a, b) for pw, ph, a, b in pairs], want)


class Build(unittest.TestCase):
    def test_flat_image_needs_no_relocation(self):
        b, info = blob()
        self.assertIn('core_qualities_tol', info['functions'])
        self.assertTrue(info['functions']['sup_entry'] & 1)
        self.assertLess(info['bytes'], 96 * 1024)
        self.assertLessEqual(info['state_off'] + BS.STATE_RESERVE, info['dma_off'])
        self.assertEqual(info['code_off'] % 8, 0)                      # the image (and its tables) 8-aligned
        self.assertTrue(all(o < info['code'] for o in info['functions'].values()))

    def test_link_refuses_what_needs_a_load_relocation(self):
        src = 'static const char *const p[2] = {"a", "b"}; int sup_entry(int i) { return p[i][0]; }'
        with tempfile.TemporaryDirectory() as t:
            f = pathlib.Path(t) / 'x.c'
            f.write_text(src)
            with self.assertRaises(BS.BuildError):
                BS.compile_text(f)


@SKIP
class Record(unittest.TestCase):
    """The selection in this BIN's own record, written at the container's leave() (a layout load), in place,
    never creating the file; nothing while recording."""

    def rec(self, data):
        off = blob()[1]['rec_off']
        return struct.unpack(f'<{BS.REC_WORDS}I', data[off:off + 4 * BS.REC_WORDS])

    def test_written_at_leave_and_restored_next_boot(self):
        c = boot()
        c.written.pop(PATH, None)
        press(c, 1, 1)                                               # HD -> S35
        self.assertNotIn(PATH, c.written)                            # not from the dial
        c.layout()                                                   # leave()
        self.assertNotIn(PATH, c.created)
        r = self.rec(c.written[PATH])
        self.assertEqual(r[:4], (0x32514C53, 2, 4192, 2358))
        self.assertEqual(c.written[PATH][:48], blob()[0][:48])
        d = boot(card=c.written[PATH])
        self.assertEqual((tile(d, 1)[1], tile(d, 2)[1]), ('S35', '1.5K'))

    def test_fps_recipe_kernels_restored(self):
        c = boot()
        c.guid(FPS_ID)
        press(c, 1, 3)
        press(c, 1, 3)
        c.guid(RCP_ID)
        press(c, 1, 4)
        want = [tile(c, k) for k in range(5)]
        c.layout()
        d = boot(card=c.written[PATH])
        self.assertEqual([tile(d, k) for k in range(5)], want)

    def test_a_damaged_record_is_the_default(self):
        c = boot()
        press(c, 1, 1)
        c.layout()
        bad = bytearray(c.written[PATH])
        bad[blob()[1]['rec_off'] + 4 * 10] ^= 1
        d = boot(card=bytes(bad))
        self.assertEqual((tile(d, 1)[1], tile(d, 2)[1]), ('HD', '2K'))

    def test_never_creates_or_writes_a_file_that_is_not_ours(self):
        c = boot()
        c.files[PATH] = b'FSB4 something else'.ljust(64, b'\0')
        c.written.pop(PATH, None)
        press(c, 1, 1)
        c.layout()
        self.assertNotIn(PATH, c.written)
        del c.files[PATH]
        press(c, 1, 1)
        c.layout()
        self.assertNotIn(PATH, c.created)
        self.assertNotIn(PATH, c.written)

    def test_locked_while_recording(self):
        c = boot()
        c.put(0xC35A952C, 1)
        c.written.pop(PATH, None)
        before = [tile(c, k) for k in range(5)]
        for k in range(1, 5):
            press(c, 1, k)
        press(c, 5, 3)
        self.assertEqual([tile(c, k)[1:] for k in range(5)], [b[1:] for b in before])
        self.assertEqual(TP.st(c, 'sub_open'), -1)
        self.assertEqual(TP.st(c, 'fine_on'), 0)
        c.layout()
        self.assertNotIn(PATH, c.written)
        self.assertEqual(TP.texts(c)['QSC_G2'], 1)                   # greyed

    def test_stock_settings_untouched(self):
        c = boot()
        press(c, 1, 1); press(c, 1, 2); press(c, 5, 1); press(c, 2, 1)
        c.layout()
        self.assertEqual([c.slot(1, k) for k in range(8)], list(SLOTS))
        self.assertEqual([p for p in c.posts if p[0].startswith(('MV_Res', 'MV_Rec', 'MV_Frame', 'CM_'))], [])


@SKIP
class Apply(unittest.TestCase):
    def test_apply_hook_records_the_effective_selection(self):
        """sq_apply (the hook point of the later 'apply' step) runs at leave(), outside the key path: the effective
        recipe's readout key, HMAX and the VMAX step of the selected rate (the smallest VMAX whose rate does not
        exceed it), the kernels"""
        import quality as Q
        c = boot()
        fn = fn_addr(c, 'sq_test')
        a, _ = c.call(fn & ~1, r0=10, thumb=True)
        press(c, 1, 1)                                               # S35, RES /3 = 1392 x 786, 59.94
        before = struct.unpack('<14I', bytes(c.mu.mem_read(a, 56)))
        self.assertEqual(before[1:3], (6048, 3402))                  # the dial did not apply: only leave() does
        c.layout()
        self.assertGreaterEqual(TP.st(c, 'leaves'), 1)
        w = struct.unpack('<14I', bytes(c.mu.mem_read(a, 56)))
        valid, dcw, dch, rw, rh, key, hm, vmax, fn_, fd, kh, kv, km, ri = w
        self.assertEqual((valid, dcw, dch, rw, rh, fn_, fd, kh, kv, km), (1, 4192, 2358, 1392, 786, 5994, 100, 1, 1, 0))
        cs = Q.qualities(4192, 2358, 1392, 786, tol=0.02)
        c0 = [x for x in cs if (x['hbin'], x['vbin']) == (1, 1)][0]          # the page's first usable preset
        self.assertEqual((Q.RCF.BY_KEY[c0['readout'][0]] is not None, hm), (True, Q.hmax_of(c0)))
        f = 59.94
        self.assertLessEqual(Q.fps_at(c0, vmax), f + 1e-9)
        self.assertGreater(Q.fps_at(c0, vmax - 1), f)


def timing():
    """instructions of one core_qualities_tol call (a cache miss: the RES dial on a new cell), stack depth"""
    from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, \
        UC_ARM_REG_R2, UC_ARM_REG_R3
    c = boot()
    fn = fn_addr(c, 'sq_test')
    out = []
    for cell in ((6048, 4040, 1008, 672), (6048, 3402, 2016, 1134), (4192, 2358, 688, 392), (6048, 4040, 6048, 4040)):
        def run(count):
            sp = T3.STACK - 0x1004
            c.mu.mem_write(sp - 0x8000, b'\xA5' * 0x8000)
            c.mu.reg_write(UC_ARM_REG_SP, sp)
            c.mu.reg_write(UC_ARM_REG_LR, T3.DONE)
            for reg, v in ((UC_ARM_REG_R0, 9), (UC_ARM_REG_R1, cell[0] << 16 | cell[1]), (UC_ARM_REG_R2, cell[2] << 16 | cell[3]),
                           (UC_ARM_REG_R3, 0)):
                c.mu.reg_write(reg, v)
            c.mu.emu_start(fn | 1, T3.DONE, count=count)
            done = c.r(UC_ARM_REG_PC) == T3.DONE
            low = bytes(c.mu.mem_read(sp - 0x8000, 0x8000))
            depth = 0x8000 - next(i for i in range(0x8000) if low[i] != 0xA5)
            return done, c.r(UC_ARM_REG_R0), depth
        lo, hi = 1, 1 << 27
        while lo < hi:
            mid = (lo + hi) // 2
            if run(mid)[0]:
                hi = mid
            else:
                lo = mid + 1
        _d, n, depth = run(lo)
        out.append((cell, n, lo, depth))
    return out


MUTANTS = [
    ('link: data relocations accepted', "            raise BuildError(f'a data relocation in {tname} (a pointer in read-only data)')", '            continue', 'build_slqs.py'),
    ('build: code 4-aligned', '    lead += -(hdr + lead) % 8', '    lead += -(hdr + lead) % 4', 'build_slqs.py'),
    ('link: MOVW addend ignored', '                A = A - 0x10000 if A & 0x8000 else A', '                A = 0', 'build_slqs.py'),
    ('DC dial wraps', 'else k = sq_max(0, sq_min((int)N_DC - 1, k + d));', 'else k = (k + d + (int)N_DC) % (int)N_DC;'),
    ('aspect recomputed each step (live 3 drift)', 'u32 isdc = f == F_DC, lock = isdc ? s->dclock : s->reslock, aw = isdc ? s->daw : s->raw, ah = isdc ? s->dah : s->rah;',
     'u32 isdc = f == F_DC, lock = isdc ? s->dclock : s->reslock, aw, ah;\n        if (isdc) { aw = s->dcw; ah = s->dch; } else res_now(st, &aw, &ah);'),
    ('no snap onto a preset', '        if (pw >= 0 && lock) { nw = pw; nh = ph; }', '        if (pw >= 0 && lock) { (void)ph; }'),
    ('fixed K not remembered by label', '    else if (hit >= 0) { s->resk = st->list[hit].kl + 1u;', '    else if (hit >= 0) { s->resk = 0;'),
    ('small DC forgets the ratio', '    if (a16r((int)s->dcw, r) < WMIN || evr((int)s->dch, r) < HMIN) r = 0;', '    if (a16r((int)s->dcw, r) < WMIN || evr((int)s->dch, r) < HMIN) r = s->rat = 0;'),
    ('no per-crop memory', '    if (s->custom) mem_put(s, s->dcw, s->dch, s->cw, s->ch);', ''),
    ('grey rates not skipped', '        while (jj >= 0 && jj < L && st->fl_e[jj].na) jj += d;', ''),
    ('fixFps raises to the max', '    for (u32 i = 0; i < st->n_fl; i++) if (st->fl_e[i].std && !st->fl_e[i].na) to = st->fl_e[i].f;', ''),
    ('fine step may repeat the shown value', '        if (f3_same(best, f)) { f = best; n--; continue; }', ''),
    ('tuned rate not inserted', '    if (hit) s->fc_d = 0; else { s->fc_n = f.n; s->fc_d = f.d; }', '    if (hit) s->fc_d = 0; else { s->fc_n = f.n; s->fc_d = 0; }'),
    # equivalent, not listed: 'fine keeps the old tuned rate' -- fineExit always rewrites the tuned rate and the
    # fine-mode footer is the spinner, so the dropped rate is never visible
    ('no switch-point marks', '    for (u32 j = 0; j < n; j++) st->fl_e[j].mark = (u8)qmark(st, st->fl_e[j].f);', ''),
    ('recipe choice forgotten when fps is too high', 'if (rq_of(&c->r[i]) == st->s.rq && usable(st, &c->r[i])) return &c->r[i];',
     'if (usable(st, &c->r[i])) { st->s.rq = rq_of(&c->r[i]); return &c->r[i]; }'),
    ('ISP bins in the preset list', 'static int is_preset(const struct rcp *q) { return q->hb == 1 && q->vb == 1; }',
     'static int is_preset(const struct rcp *q) { (void)q; return 1; }'),
    ('a choice changes the others', '            if (k != key && k != K_SCW && k != K_SCH && pval(q, k) != pval(c, k)) ok = 0;', ''),
    ('fps not lowered for a slower recipe', '    if (lt_tol(m, f)) { s->fps_n = m.n; s->fps_d = m.d; }', '    if (lt_tol(m, f)) { (void)m; }'),
    ('no greyed reason', '                if (!combo(st, key, v)) { why_not(st, st->fs[i], key, v); o->small[i] = st->fs[i]; o->grey |= 1u << i; }',
     '                if (!combo(st, key, v)) { o->grey |= 1u << i; }'),
    ('3x1 offered', '    if (key == K_MH || key == K_MV) {', '    if (0) {'),
    ('kernel dial leaves the mode', '            int jj = b == 3u ? 1 + (int)*kk + d : (d > 0 ? 1 + (int)*kk : -1);',
     '            int jj = b == 3u ? 1 + (int)*kk + d : (d > 0 ? 1 : -1);'),
    ('visible = nominal always', '    if (c) { *w = c->vis_w; *h = c->vis_h;', '    if (0) { *w = c->vis_w; *h = c->vis_h;'),
    ('FORMAT 14bit for 11/12', 'put_s(d, 0, TXT, c->ad == 14u ? "14bit" : "12bit");', 'put_s(d, 0, TXT, "12bit");'),
    ('RS one decimal', 'n = put_fix(d, n, TXT, (u64)js_fixed_d(dratio(c->rs_us, 1000), 2), 2);\n        n = put_s(d, n, TXT, " ms");',
     'n = put_fix(d, n, TXT, (u64)js_fixed_d(dratio(c->rs_us, 1000), 1), 1);\n        n = put_s(d, n, TXT, " ms");'),
    # equivalent, not listed (Exact proves both equal over their whole domain): mm by the rational px x 359 / 60480,
    # |p.w/p.h - asp| < 0.002 by rationals
    ('kLabel truncates', '        u32 x2 = (w + 256u) >> 9;', '        u32 x2 = w >> 9;'),
    ('Math.round half down', 'static int round_to(dbl x, int k) { x.e -= k == 2 ? 1 : 4; return (int)js_fixed_d(x, 0) * k; }',
     'static int round_to(dbl x, int k) { x.e -= k == 2 ? 1 : 4; return (int)dfloor(x) * k; }'),
    ('runner: the yellow flag lost', "    return {t: f.t, v: String(f.v()), s: s || '', approx: !!approx};", "    return {t: f.t, v: String(f.v()), s: s || '', approx: false};", 'preview_runner.js'),
    ('record written per dial step', '    st->dirty = 1;\n}\nstatic void set_dc(', '    st->dirty = 1;\n    rec_write(st);\n}\nstatic void set_dc('),
    ('writes without the self check', '    if (!path || svc->file_is(svc, path, st->block, SL4_HEADER_LEN) != SL_OK) { st->write_why = 2; st->write_fails++; return; }',
     '    if (!path) return;'),
    ('not locked while recording', '        f->flags = QSC_F_CINE | QSC_F_LOCK_REC |', '        f->flags = QSC_F_CINE |'),
    ('record not checked', '    for (u32 i = 0; i < REC_WORDS; i++) if (chk[i] != r[i]) return 0;', ''),
    ('fps footer not windowed', 'static u32 window(u32 n, int cur, u32 *lo)\n{\n    *lo = 0;\n    if (n <= N_LIST) return n;',
     'static u32 window(u32 n, int cur, u32 *lo)\n{\n    *lo = 0;\n    if (n <= N_LIST || 1) return n > N_LIST ? N_LIST : n;'),
    ('apply: VMAX rounded down (a rate above the selection)', 'v = udiv64(num + den - 1u, den, 0);', 'v = udiv64(num, den, 0);'),
    ('no leave() registered', '    st->t.leave = sq_leave;', '    st->t.leave = 0;'),
]


def mutate():
    src = (HERE / 'slqs.c').read_text()
    survived = []
    part = [a for a in sys.argv[1:] if a.startswith('--part=')]
    only = [a for a in sys.argv[1:] if a != '--mutate' and not a.startswith('--part=')]
    k, n_parts = (int(x) for x in part[0][7:].split('/')) if part else (0, 1)
    bsrc = (HERE / 'build_slqs.py').read_text()
    for i, (label, old, new, *where) in enumerate(MUTANTS):
        if (only and not any(o in label for o in only)) or i % n_parts != k:
            continue
        rsrc = (HERE / 'preview_runner.js').read_text()
        target = (rsrc if where[0] == 'preview_runner.js' else bsrc) if where else src
        if target.count(old) != 1:
            print(f'  BAD MUTANT (pattern x{target.count(old)}): {label}')
            survived.append(label)
            continue
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        env.pop('PYTHONPYCACHEPREFIX', None)
        with tempfile.TemporaryDirectory(prefix='slqs-mut-') as t:
            if where and where[0] == 'preview_runner.js':
                p = HERE / f'.mut_runner_{os.getpid()}.js'
                p.write_text(rsrc.replace(old, new))
                env['SLQS_RUNNER'] = str(p)
            elif where:                                     # next to the original: its paths are relative to it
                p = HERE / f'.mut_build_slqs_{os.getpid()}.py'
                p.write_text(bsrc.replace(old, new))
                env['SLQS_BUILD_SRC'] = str(p)
            else:
                p = pathlib.Path(t) / 'slqs.c'
                p.write_text(src.replace(old, new))
                env['SLQS_SRC'] = str(p)
                try:                                        # a mutant must build: a compile error is no catch
                    BS.compile_text(p)
                except BS.BuildError as e:
                    print(f'  BAD MUTANT (does not build): {label}: {str(e)[:300]}', flush=True)
                    survived.append(label)
                    continue
            r = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-q', 'test_slqs'], cwd=HERE, env=env,
                               capture_output=True, text=True)
        if where:
            p.unlink()
        failed = r.returncode != 0 and ('FAILED' in r.stderr or 'Error' in r.stderr)
        killed = sorted(set(re.findall(r'^(?:FAIL|ERROR): (\w+) \((?:test_slqs\.)?(\w+)\)', r.stderr, re.M)))
        print(f'  {"caught " if failed else "SURVIVED"}  {label}  <- ' + ' '.join(f'{c}.{m}' for m, c in killed), flush=True)
        if not failed:
            survived.append(label)
    n = len([m for i, m in enumerate(MUTANTS) if (not only or any(o in m[0] for o in only)) and i % n_parts == k])
    print(f'{n - len(survived)}/{n} mutants caught')
    return 1 if survived else 0


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        sys.exit(mutate())
    if '--timing' in sys.argv:
        for cell, n, instr, depth in timing():
            print(f'{cell}: {n} recipes, {instr} instructions, stack {depth} B')
        sys.exit(0)
    unittest.main()
