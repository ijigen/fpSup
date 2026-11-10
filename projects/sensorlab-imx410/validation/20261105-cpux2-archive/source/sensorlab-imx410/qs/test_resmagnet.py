"""v0.7.35test (Bei 11-04): the RES "magnet" on bin-native resolutions -- the page (preview/dcres.html, run in node) and
the camera (slqs.c under unicorn, string for string with the page).

The overlay: the dial moves the RES itself (the adjust value) by one step; the RES the user gets is the recipe's own
visible size (+ 16 x 10 margins).  The core takes recipes up to 2 % short, so a bin-native recipe used to stay for
several clicks past its size.  Now a recipe more than one step short of the RES is not that RES's recipe (cell_now /
allQuals), and the bin hint follows the effective RES (eff_res / effRes).

  - from every bin-native RES of three DCs, locked and free: each WIDTH / HEIGHT click changes the RES; the bin-native
    size stays displayed for at most one click on the way up and none on the way down;
  - the WIDTH / HEIGHT / RES hint is present exactly when the effective RES is a bin-native size (divText non-empty);
  - the camera equals the page on these sequences (HD, both locks).

    cd projects/sensorlab-imx410/qs && python3 -B -m unittest test_resmagnet
    python3 -B test_resmagnet.py --mutate
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_slqs as S                     # noqa: E402

DCS = {'HD': [], 'OG': ['focus:1', 'f-'], 'S35': ['focus:1', 'f+']}
SIZE = re.compile(r'^(\d+)×(\d+)')
UP, DOWN = 3, 3


def div_text(W, H, w, h):
    """the page's divText"""
    import math
    a16 = lambda x: math.floor(x / 16) * 16           # the page's a16 / ev: floor
    ev = lambda x: math.floor(x / 2) * 2
    n = next((k for k in (1, 2, 3, 4, 5, 6, 8, 12) if a16(W / k) == w), None)
    m = next((k for k in (1, 2, 3, 4, 5, 6, 8, 12) if ev(H / k) == h), None)
    return ('%s' % (n or '') + 'x' + '%s' % (m or '')) if (n or m) else ''


def seqs():
    out = []
    for dc, pre in DCS.items():
        for lock in (True, False):
            for k in range(14):
                for axis in (1, 2):                     # WIDTH, HEIGHT
                    keys = pre + ['focus:2'] + ['f-'] * 16 + ['f+'] * k + ['ael']
                    if not lock:
                        keys += ['focus:3', 'f+']
                    keys += ['focus:%d' % axis] + ['f+'] * UP + ['f-'] * (UP + DOWN)
                    out.append(dict(name=f'{dc} {"lock" if lock else "free"} entry {k} axis {axis}', keys=keys))
    return out


def states():
    return S.page_states(seqs())


def run_of(keys):
    """index of the first dial key on the dimension tile"""
    return next(i for i in range(len(keys)) if keys[i].startswith('focus:') and keys[i] in ('focus:1', 'focus:2')
                and i > keys.index('ael'))


class Page(unittest.TestCase):
    def test_each_click_moves_the_shown_res(self):
        moved = 0
        for seq, got in zip(seqs(), states()):
            st, keys = got['states'], seq['keys']
            a = run_of(keys) + 1
            if not st[a]['open'] or st[a].get('sub') is None:
                continue
            k = 1 if keys[a - 1] == 'focus:1' else 2
            for i in range(a + 1, len(st)):
                if st[i]['S']['res'] != st[i - 1]['S']['res']:
                    self.assertNotEqual(st[i]['tiles'][k]['v'], st[i - 1]['tiles'][k]['v'], (seq['name'], i))
                    r = st[i]['S']['res']
                    self.assertEqual(st[i]['tiles'][k]['v'], str((r['w'] - 16) if k == 1 else (r['h'] - 10)))
                    moved += 1
        self.assertGreater(moved, 500)

    def test_the_small_line_shows_the_recorded_size_exactly_when_a_tolerance_recipe_applies(self):
        tol = plain = 0
        for seq, got in zip(seqs(), states()):
            for s in got['states']:
                if not s['open'] or s.get('sub') is None:
                    continue
                m = SIZE.match(s['tiles'][0]['s'] or '')          # the RES tile: the recipe's own visible size
                if not m:
                    continue
                r = s['S']['res']
                ew, eh = int(m.group(1)) + 16, int(m.group(2)) + 10
                # v0.7.38test (Bei 11-05): one hint, from the effective recipe (sensor merge x ISP bin, or RWZM),
                # the RES tile's own -- never the geometric DC / RES division while a recipe is in effect
                t0 = s['tiles'][0]['s']
                dv = t0.split(' \u00b7 ', 1)[1] if ' \u00b7 ' in t0 else ''
                self.assertRegex(dv, r'^(RWZM|\d+x\d+)$', seq['name'])
                active = (ew, eh) != (r['w'], r['h'])
                rec = '\u2192%d\u00d7%d' % (ew, eh) if active else ''
                want = rec + ' \u00b7 ' + dv if rec and dv else rec or dv
                self.assertEqual((s['tiles'][1]['s'], s['tiles'][2]['s']), (want, want), seq['name'])
                if active:
                    tol += 1
                else:
                    plain += 1
        self.assertGreater(tol, 30)
        self.assertGreater(plain, 100)

    def test_no_recipe_is_dropped(self):
        import json
        d = json.loads((S.PREVIEW / 'fps_data.js').read_text().split('const FPSDATA = ', 1)[1].rstrip(';\n'))
        self.assertEqual(sum(len(v) for v in d['cases'].values()), 849)   # 837 + 12 CPU x2 (hbin 2)
        html = (S.PREVIEW / 'dcres.html').read_text()
        self.assertNotIn('shortOk', html)                         # the 2 % tolerance opens the path (Bei 11-05)


@S.SKIP
class Camera(unittest.TestCase):
    def test_the_camera_keeps_every_recipe(self):
        c = S.boot()
        import json
        d = json.loads((S.PREVIEW / 'fps_data.js').read_text().split('const FPSDATA = ', 1)[1].rstrip(';\n'))
        dcs = {'OG': (6048, 4040), 'HD': (6048, 3402), 'S35': (4192, 2358), 'APS-C': (3952, 2624), 'S16': (2096, 1240),
               'SQ': (4032, 4032)}
        n = 0
        for cell, rs in d['cases'].items():
            dc, wh = cell.split(':')
            w, h = map(int, wh.split('x'))
            W, H = dcs[dc]
            got = S.sqt(c, 9, W << 16 | H, w << 16 | h)
            self.assertEqual(got, len(rs), cell)
            n += got
        self.assertEqual(n, 849)

    def test_the_camera_equals_the_page(self):
        sq = [x for x in seqs() if x['name'].startswith('HD ')][::3]
        got = S.page_states(sq)
        for seq, g in zip(sq, got):
            c = S.boot()
            bad = S.drive(c, seq['keys'], g['states'])
            self.assertEqual(bad, [], seq['name'])


MUTANTS = [
    ('slqs.c', '} else { res_now(st, &w, &h); w -= 16u; h -= 10u; }', '} else visible(st, &w, &h, &w);'),
    ('slqs.c', '            if (e.w != e.rw || e.h != e.rh) {', '            if (0) {'),
    ('slqs.c', '            if (e.hint[0]) { if (n)', '            div_text(e.hint, st->s.dcw, st->s.dch, e.rw, e.rh);\n            if (e.hint[0]) { if (n)'),
    # v0.7.38test (Bei 11-05): the hint of the effective recipe, one source for the tile and the sub-items
    ('dcres.html', '      const {e, hint: dv} = effDisplay();', '      const {e} = effDisplay(), dv = divText(S.dcW, S.dcH, e.w, e.h);'),
    ('dcres.html', 'function hintDiv() { return effDisplay().hint; }', 'function hintDiv() { const e = effRes(); return divText(S.dcW, S.dcH, e.w, e.h); }'),
    ('dcres.html', "      const rec = e.w !== r.w || e.h !== r.h ? `→${e.w}×${e.h}` : '';", "      const rec = '';"),
    ('dcres.html', '    v() { const r = isDC ? {w: S.dcW, h: S.dcH} : (x => ({w: x.w - 16, h: x.h - 10}))(res()); return String(axis === \'w\' ? r.w : r.h); },',
     '    v() { const r = isDC ? {w: S.dcW, h: S.dcH} : visible(); return String(axis === \'w\' ? r.w : r.h); },'),
]


def mutate():
    survived = []
    for f, a, b in MUTANTS:
        path = HERE / f if f == 'slqs.c' else HERE.parent / 'preview' / f
        src = path.read_text()
        assert src.count(a) == 1, (f, a)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        if env.get('SL_TESTCACHE', '1') != '0':
            env['SL_TESTCACHE'] = 'ro'
        with tempfile.TemporaryDirectory(prefix='res-mut-') as t:
            env['PYTHONPYCACHEPREFIX'] = t
            if f == 'slqs.c':
                m = pathlib.Path(t) / 'slqs.c'
                m.write_text(src.replace(a, b))
                shutil.copy(HERE / 'qrdec.c', pathlib.Path(t) / 'qrdec.c')
                env['SLQS_SRC'] = str(m)
                tests = ['test_resmagnet.Camera.test_the_camera_equals_the_page']
                r = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-q', *tests], cwd=HERE, env=env,
                                   capture_output=True, text=True)
            else:                                       # the page: a mutated copy in place, put back after
                path.write_text(src.replace(a, b))
                try:
                    r = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-q', 'test_resmagnet.Page'],
                                       cwd=HERE, env=dict(env, SL_TESTCACHE='0'), capture_output=True, text=True)
                finally:
                    path.write_text(src)
            caught = r.returncode != 0 and ('FAILED' in r.stderr or 'Error' in r.stderr)
        print(('caught   ' if caught else 'SURVIVED ') + f + ': ' + a[:60], flush=True)
        if not caught:
            survived.append(a[:60])
    return survived


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        s = mutate()
        print('survived:', s)
        sys.exit(1 if s else 0)
    unittest.main()
