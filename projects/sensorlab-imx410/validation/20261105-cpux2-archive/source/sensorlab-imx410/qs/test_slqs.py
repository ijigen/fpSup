#!/usr/bin/env python3
"""SensorLab-IMX410 QS client v0.2.2test on the real ARM bytes, offline, against the preview it ports.

The real v4 core loads the real QSContainer_v0.2.4.BIN and the real SensorLab-IMX410_v0.2.2test.BIN against the real
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
import testcache as TC                     # noqa: E402  (test-only caches; README "Testing")

T3, F6 = Q1.T3, Q1.F6
SKIP = unittest.skipIf(Q1.T.Uc is None or not Q1.IMG or not __import__('shutil').which('node'),
                       'needs unicorn, out/MAIN_c0000000.bin and node; skipped = unverified')
PATH = '\\fpSup\\' + BS.file_name()
DC_ID, RES_ID, FPS_ID, RCP_ID, FMT_ID, MB_ID, QR_ID = 54, 55, 56, 57, 58, 59, 60   # the client's seven functions
SLOTS = (FMT_ID, DC_ID, RES_ID, FPS_ID, RCP_ID, QR_ID, MB_ID, 19)   # the page's MAIN: FORMAT DC RES FPS RECIPE QR MB/s, WB
FOOT = F6.FAKE + 0x9000                    # a struct qsc_foot for direct calls
FOOT_WORDS = 6 + 32 + 1
SUBS = 7
FX_BYTES = 4 * 8 + 4 * SUBS * 6 + 12 * SUBS + 28 * SUBS
# v0.2.1test: the page's switch-point bullet U+2022 is not in the camera's small-line font (live run 4 drew "?"); the
# client writes U+00B7, which that font has (the RES line's separator)
SMALL_MAP = (('\u2022 ', '\u00b7 '),)
_built = {}


def blob():
    if 'b' not in _built:
        _built['b'] = TC.cached('slqs', BS.build, key=TC.file_key(BS.SOURCE, BS.__file__))
    return _built['b']


def sqt(c, op, a=0, b=0, cc=0):
    fn = fn_addr(c, 'sq_test')
    c.mu.reg_write(Q1.T3.UC_ARM_REG_R3, cc)
    return c.call(fn & ~1, r0=op, r1=a, r2=b, thumb=True)[0]


# v0.5.0test: the firmware the apply unit (../apply/ap.c) calls, as tiny ARM stubs (no Python hook needed): the format
# getter (0 = CinemaDNG), the frame-rate getter / setter on a RAM word (FR_WORD), no live view, the list recompute
FR_WORD, DESC = 0xC3F80000, 0xC3F00000
AP_STUBS = {0xC005BE90: ['E3A00000', 'E12FFF1E'],                                   # GET_FMT: mov r0, #0
            0xC005C0F0: ['E59F0004', 'E5900000', 'E12FFF1E', f'{FR_WORD:08X}'],      # FR_GET: r0 = [FR_WORD]
            0xC005C0B8: ['E59F2004', 'E5821000', 'E12FFF1E', f'{FR_WORD:08X}'],      # FR_SET: [FR_WORD] = r1
            0xC0423C48: ['E3A00000', 'E12FFF1E'],                                   # LV_HOLDER: no LV
            0xC049EC58: ['E3A00000', 'E12FFF1E'], 0xC049EE78: ['E12FFF1E']}          # EXCL_MGR / RECOMPUTE


def ap_firmware(c, descriptor=False, fr=5):
    for a, ws in AP_STUBS.items():
        c.mu.mem_write(a, b''.join(struct.pack('<I', int(w, 16)) for w in ws))
    c.put(FR_WORD, fr)
    if descriptor:                       # the boot-built mode descriptor, as apply/test_apply.py builds it
        import struct as S
        img = Q1.IMG if isinstance(Q1.IMG, (bytes, bytearray)) else pathlib.Path(ROOT / 'out' / 'MAIN_c0000000.bin').read_bytes()
        modes = [S.unpack_from('<I', img, 0xC0B59500 - 0xC0000000 + 0x20 * i)[0] for i in range(70)]
        syn = DESC + 0x10000
        for i, m in enumerate(modes):
            c.mu.mem_write(syn + i * 0x5C, S.pack('<23I', m, *[(m << 16) | 0x1280 | k for k in range(1, 23)]))
        for off, v in {0x00: 0xC0B59500, 0x04: 70, 0x08: 0xC0B59DC0, 0x0C: 70, 0x10: 0xC0B5B918, 0x14: 70,
                       0x24: 0xC0B5BB48, 0x28: 70, 0x40: 0xC0B5C638, 0x44: 70, 0x48: 0xC0B5D588, 0x4C: 70,
                       0xF4: 0xC0B5DB00, 0xF8: 70, 0x128: syn, 0x12C: 70}.items():
            c.put(DESC + off, v)
        c.put(0xC343B588, DESC)
        c.put(0xC343B67C, 0xC0B5FDA4)


def boot(card=None, prepare=None, qr_force=1, descriptor=False):
    """Core + container + client; QS open on the CINE layout of the page's MAIN.  qr_force (sq_test 12): bit 0 no
    firmware display calls (no observer; QR.test_triple_buffer_and_present runs them).  descriptor: the apply unit
    finds a built mode descriptor (else every commit is AP_E_NOTREADY, as before the first live view)."""
    data = card if card is not None else blob()[0]

    def prep(cam):
        ap_firmware(cam, descriptor)
        if prepare:
            prepare(cam)
    c = Q1.boot([(Q1.CNAME, Q1.cblob()[0]), (BS.file_name(), data)], prepare=prep)
    c.layout()
    fn = fn_addr(c, 'sq_test')                           # the medium: SD UHS-II, the page's default (no firmware reads)
    c.mu.reg_write(Q1.T3.UC_ARM_REG_R3, 0)
    c.call(fn & ~1, r0=11, r1=1 + 3, r2=0, thumb=True)
    if qr_force is not None:
        sqt(c, 12, qr_force)
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
        r = subprocess.run(['node', str(runner_path()), str(PREVIEW / 'dcres.html'), str(d), str(s),
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


def runner_path():
    return pathlib.Path(os.environ.get('SLQS_RUNNER') or HERE / 'preview_runner.js')


def _page_states(seqs):
    return run_page(seqs, page_data(seqs))['out']


def page_states(seqs):
    """the page's states for `seqs`, cached on the page, the runner, the FPSDATA generator and the sequences (the
    Python it imports -- quality.py and the rest -- is in the cache's manifest)"""
    return TC.cached('slqs_page', _page_states, seqs, subprocesses=True,
                     key=TC.file_key(PREVIEW / 'dcres.html', PREVIEW / 'fps_data.js', PREVIEW / 'gen_fps.py',
                                     runner_path()))


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
        if sub is None and k >= 7:
            continue                                     # stock tiles: not ours (5 = QR, 6 = MB/s)
        title, v, s, ap = tile(c, k)
        if p is None:
            if (v, s) != (' ', ' '):
                diff.append((k, 'blank', v, s))
            continue
        pv = 'CUSTOM' if p['v'] == 'Custom' else p['v']
        ps = p['s'] if p['s'] else ' '
        for a, b in SMALL_MAP:
            ps = ps.replace(a, b)
        pt = 'RATIO' if p.get('lock') is not None else p['t']
        if p.get('lock') is not None:
            want_small = 'LOCK' if p['lock'] else ''
            if p['s'] != want_small:
                diff.append(('ratio fallback text', k, p['s'], want_small))
            want_width = 120 if p['lock'] else 0
            if c.vars[f'QSC_SW{k+1}'][1] != want_width or c.vars[f'QSC_LW{k+1}'][1]:
                diff.append(('native_small_lock_width', k, c.vars[f'QSC_SW{k+1}'][1], want_width))
            # The current container replaces the client's semantic fallback with its native small-line image.
            # RatioTile.test_ratio_lock_has_client_text_fallback checks the C callback before that replacement.
            ps = ' '
        if (v, s, ap) != (pv, ps, p['approx']):
            diff.append((k, (v, s, ap), (pv, ps, p['approx'])))
        if sub is not None and k > 0 and title != pt:
            diff.append((k, 'title', title, pt))
        if sub is None and k == 4 and title != 'RECIPE':
            diff.append((k, 'title', title))
    if 'qr' in st:                                       # compare() runs only while QS is open (see drive).
        on = c.w(sqt(c, 14))
        if bool(on) != st['qr']:
            diff.append(('qr visibility', bool(on), st['qr'], sub))
        code = c.cstr(sqt(c, 13), 64)
        if code != st['qrcode']:
            diff.append(('qr code', code, st['qrcode']))
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
            want = [(x['l'], x['s'], x['approx'], x['mark'], x['custom'], x['na'])
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
        # A non-QS layout may prepare QR text again; qr.on is then not proof of visible pixels.
        # The QR native-owner/observer tests check closed-screen rejection, not this text-state harness.
        if check and st['open']:
            d = compare(c, st)
            if d:
                bad.append((i, k, d))
                if len(bad) > 3:
                    break
        prev = st
    return bad


CPU2_KEYS = ['focus:2', 'f+', 'focus:4', 'ael', 'focus:6', 'f+', 'focus:4', 'f-', 'focus:6', 'f+', 'f+', 'f-', 'f+',
             'focus:4', 'focus:7', 'focus:0', 'ael', 'focus:3'] + ['f-'] * 10 + \
            ['focus:4', 'ael', 'focus:1', 'f+', 'focus:6', 'f-', 'f-', 'f+', 'f+', 'focus:4', 'f+', 'focus:1', 'f-', 'f+',
             'f+', 'ael', 'focus:5']
CPU2 = 'CPU \u00d72'
OG3K_HINT_KEYS = ['focus:1', 'f-', 'focus:2', 'f+', 'focus:2', 'ael', 'focus:1', 'focus:2', 'ael', 'focus:4', 'ael',
                  'focus:4', 'f-', 'ael', 'focus:2', 'ael', 'focus:1', 'focus:2', 'ael', 'focus:4', 'ael', 'focus:6', 'f+',
                  'ael', 'focus:2', 'ael', 'focus:1', 'focus:2', 'ael']
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
    # v0.7.0test (Bei 10-30 A): AEL on FPS opens the FPS sub-QS (FPS, FINE); FINE is the old fine spinner; leaving FINE
    # (focus to FPS, AEL back, QS closed) puts the tuned rate in the list
    dict(name='fps sub-QS: FINE tile, the tuned rate joins the list', keys=['focus:3', 'ael', 'focus:1', 'f+', 'f+',
         'f+', 'r+', 'r+', 'f-', 'ael', 'f+', 'f-', 'f-', 'ael', 'focus:1', 'r-', 'focus:0', 'f+', 'focus:1', 'f+',
         'ael', 'focus:4', 'focus:3', 'f+', 'ael', 'focus:1', 'r+', 'qs', 'qs', 'f+', 'f-']),
    dict(name='fps FINE at a switch point, marks', keys=['focus:1', 'f-', 'focus:2'] + ['f+'] * 6 +
         ['focus:3', 'f+', 'f+', 'f+', 'ael', 'focus:1', 'f-', 'f+', 'f+', 'r-', 'ael', 'f+', 'f-', 'focus:2', 'f-',
          'focus:3', 'ael', 'focus:1', 'r+', 'r+', 'ael']),
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
    dict(name='ISP HBIN dial through SOFT into STD (live5: STD unreachable)', keys=['focus:3'] + ['f-'] * 14 +
         ['focus:4', 'ael', 'focus:4', 'f-', 'f-', 'focus:6'] + ['f+'] * 13 + ['f-'] * 14 + ['focus:7', 'f+', 'f+']),
    # v0.4.0test
    dict(name='QR: automatic on main QS, focus and AEL independent, hidden on sub-QS and close',
         keys=['focus:5', 'ael', 'f+', 'ael', 'ael', 'focus:4', 'f+', 'focus:5', 'ael', 'qs', 'qs', 'focus:5', 'ael',
               'ok', 'qs', 'focus:3', 'ael', 'focus:1', 'r+', 'ael', 'focus:5', 'focus:2', 'ael', 'focus:1', 'f+',
               'focus:5']),
    dict(name='live6: HD 3K -> S35 -> APS-C -> S16, RES +1, back to HD (6K / 48)',
         keys=['focus:2', 'f+', 'focus:1', 'f+', 'f+', 'f+', 'focus:2', 'f+', 'f+', 'focus:1', 'f-', 'f-', 'f-',
               'focus:5', 'ael']),
    # v0.4.1test: no recipe chosen -> defaultPick (Bei 10-29: vertical merge, AD, horizontal merge, RS) on many cells
    dict(name='default recipe across FPS and DC x RES', keys=['focus:3'] + ['f-'] * 8 + ['f+'] * 16 +
         ['focus:1', 'f+', 'focus:2', 'f+', 'f-', 'focus:1', 'f+', 'f+', 'focus:2', 'f+', 'focus:1'] + ['f-'] * 4 +
         ['focus:3', 'f-', 'f-']),
    # v0.5.1test: OG 6K's true 14-bit 1:1 (FORMAT 14bit) against the scaled 14-bit AD ones (FORMAT 12bit), then the
    # DC WIDTH dial across the native readout widths 6048 / 5040 / 4144 / 3984 (marked) and their neighbours
    dict(name='true 14 vs scaled 14b AD; DC WIDTH native marks', keys=['focus:1', 'f-', 'focus:2'] + ['f+'] * 12 +
         ['focus:3'] + ['f-'] * 12 + ['focus:4'] + ['f+'] * 8 + ['f-'] * 8 + ['focus:2', 'f-', 'focus:4', 'f+', 'f+'] +
         ['focus:1', 'ael', 'focus:1'] + ['r-'] * 6 + ['f-'] * 3 + ['f-', 'f+'] + ['r-'] * 5 + ['f-'] * 6 + ['r-', 'f-']),
    # 10-30 (mutation survivors): HD 2K 11b 1x3 at 131.991 fps, its own maximum.  The ISP HBIN 3 variant (6064 wide)
    # tops out at 131.676: greyed "<131.68p" and the dial refuses it (a recipe never lowers the FPS); one rate down it
    # is taken, and SENSOR HBIN 2 / 3 then grey with "->I.HBIN1"
    dict(name='ISP bin just short of the FPS; I.HBIN reason', keys=['focus:4', 'ael', 'focus:1', 'f-', 'focus:4', 'f-',
         'f-', 'ael', 'focus:3'] + ['f+'] * 17 + ['focus:4', 'ael', 'focus:6', 'f+', 'f-', 'ael', 'focus:3', 'f-',
         'focus:4', 'ael', 'focus:6', 'f+', 'focus:4', 'f+', 'focus:6', 'f-']),
    # v0.7.38test: CPU x2 (ISP HBIN option 13, hbin 2; notes/CPU_X2_DESIGN.md "UI").  HD 3K: at SENSOR HBIN 2 it is grey
    # "->S.HBIN1"; SENSOR HBIN 1 makes it possible, the dial steps 1 <-> CPU x2 over the (absent) x3 kernels; the
    # RECIPE line says CPUx2; at 25 fps the 14-bit AD records true 14 (D11 (4), Bei 11-05 B: FORMAT 14bit), MB/s at the half width
    dict(name='CPU x2: grey, chosen, 14 bit, record line', keys=CPU2_KEYS),
    # v0.7.38test (Bei 11-05: the effective recipe is the single source): OG 3K -- sensor 2x2 ("2x2"), sensor 1x2 + RWZM
    # ("RWZM"), sensor 1x2 + CPU x2 (records 3024x2014, 6 rows short: "->3024x2014 · 2x2", was "2x" by geometry)
    dict(name='OG 3K merge hint from the effective recipe', keys=OG3K_HINT_KEYS),
    # v0.7.38test: HD 2K sensor 1x1 + ISP 3x3 (RWZM forced to 1025/1026: unity, "3x3"); ISP 3x1 + RWZM V ("RWZM")
    dict(name='HD 2K ISP 3x3 hint at the forced 1025', keys=['focus:3'] + ['f-'] * 6 +
         ['focus:4', 'ael', 'focus:4', 'f-', 'f-', 'focus:5', 'f-', 'f-', 'focus:6', 'f+', 'ael', 'focus:2', 'ael',
          'focus:1', 'ael', 'focus:4', 'ael', 'focus:7', 'f+', 'ael', 'focus:2', 'ael', 'focus:1']),
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
    # v0.2.2test: the RECIPE sub-QS never lowers the FPS ("max N" greyed); this passes for real now
    def test_10(self): self.run_seq(10)
    def test_11(self): self.run_seq(11)
    def test_12(self): self.run_seq(12)
    def test_13(self): self.run_seq(13)
    def test_14(self): self.run_seq(14)
    def test_15(self): self.run_seq(15)
    def test_16(self): self.run_seq(16)
    def test_17(self): self.run_seq(17)
    def test_18(self): self.run_seq(18)
    def test_19(self): self.run_seq(19)
    def test_20(self): self.run_seq(20)
    def test_21(self): self.run_seq(21)
    def test_22(self): self.run_seq(22)

    def test_isp_bins_count_in_the_hint(self):
        """v0.7.38test: sensor 1x1 + ISP 3x3 at RWZM 1025 shows "3x3" (unity); ISP 3x1 with RWZM V 1/3 shows RWZM"""
        every = self.states[22]['states']
        main = [s for s in every if s['sub'] is None]
        self.assertTrue(any('ISP 3x3' in s['tiles'][4]['s'] and s['tiles'][2]['s'].endswith('\u00b7 3x3') for s in main))
        self.assertTrue(any('ISP 3x1' in s['tiles'][4]['s'] and s['tiles'][2]['s'].endswith('\u00b7 RWZM') for s in main))

    def test_og3k_hint_is_the_effective_recipes_merge(self):
        """v0.7.38test (Bei 11-05): the RES tile and the RES WIDTH / HEIGHT sub-items show one hint, from the effective
        recipe: sensor merge x ISP bin per axis ("2x2" for 2x2 and for 1x2 + CPU x2), "RWZM" when RWZM scales"""
        every = self.states[21]['states']
        res = lambda s: s['tiles'][2]['s'] if s['sub'] is None else None
        rcp = [s for s in every if s['sub'] is None]
        cpu = [s for s in rcp if 'CPU\u00d72' in s['tiles'][4]['s']]
        self.assertTrue(cpu and all(res(s) == '3008\u00d72004 \u00b7 2x2' for s in cpu))
        self.assertTrue(any(s['tiles'][4]['v'] == '12b 1x2' and res(s).endswith('\u00b7 RWZM') for s in rcp))
        self.assertTrue(any(s['tiles'][4]['v'] == '12b 2x2' and res(s).endswith('\u00b7 2x2') for s in rcp))
        sub = [s for s in every if s['sub'] == 'res']
        self.assertIn('\u21923024\u00d72014 \u00b7 2x2', [s['tiles'][1]['s'] for s in sub])
        self.assertTrue(all(s['tiles'][1]['s'] == s['tiles'][2]['s'] for s in sub))
        self.assertTrue(any(s['tiles'][1]['s'].endswith('RWZM') for s in sub))

    def test_recipe_line_has_no_visible_suffix_and_one_decimal_rs(self):
        """v0.7.38test (Bei live 11-05): the RECIPE line ends "RS 25.6 ms"; the recorded size is on RES only"""
        import re as _re
        lines = [s['tiles'][4]['s'] for st in self.states for s in st['states'] if s['sub'] is None and s['tiles'][4]]
        lines = [x[0] if isinstance(x, list) else x for x in lines]
        self.assertTrue(lines and all(_re.search(r'RS \d+\.\d ms$', x) for x in lines if 'RS' in x), lines[:5])

    def test_cpu_x2_sequence_reaches_what_it_names(self):
        """v0.7.38test: seq 20 shows CPU x2 grey ("->S.HBIN1"), chosen ("RWZM off · ->3024"), 14bit (D11 (4)), and back to 1"""
        every = self.states[20]['states']
        hb = [s for s in every if s['sub'] == 'recipe' and s['focus'] == 6]
        lab = lambda s: [o['l'] for o in s['foot']['opts']]
        self.assertTrue(all(len(lab(s)) == 14 and lab(s)[13] == CPU2 and lab(s)[:13] == ['1'] + lab(s)[1:13] for s in hb))
        self.assertTrue(any(s['foot']['opts'][13]['na'] and s['foot']['opts'][13]['s'] == '\u2192S.HBIN1' for s in hb))
        on = [s for s in hb if s['tiles'][6]['v'] == CPU2]
        self.assertTrue(on and all(s['foot']['sel'] == 13 and s['tiles'][6]['s'] == 'RWZM off \u00b7 \u21923024' for s in on))
        self.assertTrue(any(s['tiles'][6]['v'] == '1' for s in hb[1:]))           # and back
        vb = [s for s in every if s['sub'] == 'recipe' and s['focus'] == 7]
        self.assertTrue(vb and all(len(s['foot']['opts']) == 13 and CPU2 not in lab(s) for s in vb))   # ISP VBIN unchanged
        # D11 (4) (Bei 11-05, choice B): the CPU x2 record skips RWZM, so a 14-bit AD records true 14 (FORMAT 14bit)
        self.assertTrue(any(s['sub'] is None and s['tiles'][0]['s'] == '14bit' and s['tiles'][4]['s'].startswith('14b 1x2 CPU\u00d72 \u00b7 RS')
                            for s in every))
        self.assertFalse(any(s['sub'] is None and s['tiles'][0]['s'] == '12bit' and s['tiles'][4]['s'].startswith('14b 1x2 CPU\u00d72')
                             for s in every))
        self.assertTrue(any(s['sub'] is None and s['tiles'][4]['s'].startswith('12b 1x2 CPU\u00d72 \u00b7 RS') and
                            s['tiles'][0]['s'] == '12bit' for s in every))
        mh = [s for s in every if s['sub'] == 'recipe' and s['focus'] == 4 and s['tiles'][6]['v'] == CPU2]
        self.assertTrue(any(any(o['na'] and o['s'] == '\u2192I.HBIN1' for o in s['foot']['opts']) for s in mh))

    def test_recorded_bits_and_native_width_marks(self):
        """v0.5.1test (Bei 10-30): FORMAT shows the RECORDED bits -- 14bit only for a true 1:1 14-bit recipe, 12bit for a
        scaled 14-bit AD one (the RECIPE / ADC tiles still say 14b); the DC WIDTH spinner is marked exactly on 6048 / 5040
        / 4144 / 3984"""
        every = [s for i in range(len(SEQS)) for s in self.states[i]['states']]
        fmt = [(s['tiles'][0]['s'], s['tiles'][4]['v']) for s in self.states[18]['states'] if s['tiles'][0] and s['tiles'][4]]
        self.assertIn(('14bit', '14b 1x1'), fmt)
        self.assertTrue(any(f == '12bit' and r.startswith('14b') for f, r in fmt), 'a scaled 14b-AD recipe records 12 bit')
        self.assertFalse(any(f == '14bit' and r != '14b 1x1' and not r.startswith('CUSTOM') for f, r in fmt))
        widths = {}
        for s in self.states[18]['states']:
            if s['sub'] == 'dc' and s['foot'] and 'spin' in s['foot'] and s['tiles'][s['focus']]['t'] == 'WIDTH':
                widths[int(s['foot']['spin'])] = s['foot']['mark']
        for w in (6048, 5040, 4144, 3984):
            self.assertIs(widths.get(w), True, (w, sorted(widths)))
        self.assertTrue(any(w not in (6048, 5040, 4144, 3984) for w in widths))
        self.assertFalse(any(m for w, m in widths.items() if w not in (6048, 5040, 4144, 3984)))
        del every

    def test_default_pick_examples(self):
        """Bei 10-29 / 10-30: the bits step compares the RECORDED bits, so HD 2K 29.97 / 59.94 / 90 -> 12b 3x3 (the scaled
        14b 1x3 records 12 bit); several distinct defaults on the way"""
        st = self.states[17]['states']
        pick = {(s['tiles'][1]['v'], s['tiles'][2]['v'], s['tiles'][3]['v']): s['tiles'][4]['v'] for s in st}
        self.assertEqual(pick[('HD', '2K', '59.94')], '12b 3x3')
        self.assertEqual(pick[('HD', '2K', '90')], '12b 3x3')
        self.assertGreaterEqual(len(set(pick.values())), 3)    # v0.5.1test: 4 -> 3 (the 14b 1x3 default is gone)

    def test_s16_back_to_hd_is_the_spec(self):
        """live6: S16 -> HD came back with RES 6K / FPS 48.  The page does the same: RES +1 on S16 picked the x1 ratio
        (2096 = S16's full width), and x1 on HD is 6K, whose fastest recipe is under 59.94 (fixFps -> 48)."""
        st = self.states[16]['states']
        hd3k = st[2]
        self.assertEqual((hd3k['tiles'][1]['v'], hd3k['tiles'][2]['v'], hd3k['tiles'][3]['v']), ('HD', '3K', '59.94'))
        self.assertEqual((st[7]['tiles'][1]['v'], st[7]['tiles'][2]['v']), ('S16', '1K'))     # RES /2 kept: 1040 x 620
        self.assertEqual(st[8]['tiles'][2]['v'], '1.5K')
        s16 = st[9]                                               # the RES dial up twice: /1.5, then x1 (live6 h -> i)
        self.assertEqual((s16['tiles'][1]['v'], s16['S']['res']), ('S16', {'w': 2096, 'h': 1240}))
        last = st[13]
        self.assertEqual((last['tiles'][1]['v'], last['tiles'][2]['v'], last['tiles'][3]['v']), ('HD', '6K', '48'))
        self.assertEqual(last['tiles'][6]['s'], 'LL \u2014')      # 6K 11b 1x1: a compressed frame over 16 MiB

    def test_sequences_reach_what_they_name(self):
        """the scripts reach the states the review asked for (else a passing comparison proves little)"""
        last = lambda i: self.states[i]['states'][-1]
        every = lambda i: self.states[i]['states']
        self.assertTrue(any(s['tiles'][1] and s['tiles'][1]['v'] == 'SQ' for s in every(0)))
        self.assertTrue(any(s['fine'] for s in every(7)))
        self.assertTrue(any(s['S']['fpsCustom'] for s in every(7)))
        # v0.7.0test: FINE is a sub-QS tile; the tuned rate shows (yellow) in the FPS list of the user's layout and of
        # the sub-QS's own FPS tile; FINE left by a focus move, by AEL and by closing QS
        fps = every(7)
        self.assertTrue(any(s['sub'] == 'fps' and s['tiles'][1]['t'] == 'FINE' and s['fine'] for s in fps))
        self.assertTrue(any(s['sub'] is None and s['focus'] == 3 and s['foot'] and 'opts' in s['foot'] and
                            any(o['custom'] for o in s['foot']['opts']) for s in fps))
        self.assertTrue(any(s['sub'] == 'fps' and s['focus'] == 0 and s['foot'] and 'opts' in s['foot'] and
                            any(o['custom'] for o in s['foot']['opts']) for s in fps))
        keys7 = SEQS[7]['keys']
        left = {keys7[i] for i in range(len(keys7)) if fps[i]['fine'] and not fps[i + 1]['fine']}
        self.assertTrue({'focus:0', 'ael', 'qs'} <= left, left)
        self.assertTrue(any(s['foot'] and 'opts' in s['foot'] and any(o['na'] for o in s['foot']['opts']) for s in every(6)))
        self.assertTrue(any(s['tiles'][2] and s['tiles'][2]['approx'] for s in every(11)))     # RES short (yellow)
        self.assertTrue(any(s['tiles'][0] and s['tiles'][0]['s'] == '14bit' for s in every(18)))   # v0.5.1: only true 1:1 14
        self.assertTrue(any(s['sub'] == 'recipe' and s['foot'] and 'opts' in s['foot'] and
                            any(o['s'].startswith(('no ', '\u2192')) or ' \u2192' in o['s'] for o in s['foot']['opts'])
                            for s in every(10)))
        self.assertTrue(any(s['sub'] == 'recipe' and s['tiles'][6]['v'].startswith('3[') for s in every(10)))   # an ISP bin
        self.assertTrue(any(s['sub'] == 'recipe' and s['tiles'][6]['s'].startswith('STD') for s in every(14)))   # the dial reaches STD
        # v0.2.2test: a greyed "max N.NN" reason in the recipe sub-QS, and the FPS never moves while the sub-QS is up
        self.assertTrue(any(s['sub'] == 'recipe' and s['foot'] and 'opts' in s['foot'] and
                            any(o['na'] and re.search(r'<\d+\.\d\dp$', o['s']) for o in s['foot']['opts'])
                            for i in range(len(SEQS)) for s in every(i)))
        for i in range(len(SEQS)):
            st = every(i)
            for a, b in zip(st, st[1:]):
                if a['sub'] == 'recipe' and b['sub'] == 'recipe':
                    self.assertEqual(a['S']['fps'], b['S']['fps'], SEQS[i]['name'])
        self.assertTrue(any(s['tiles'][4] and s['tiles'][4]['v'] == 'CUSTOM' for s in every(10)))
        self.assertTrue(any(s['tiles'][1] and s['tiles'][1]['v'] == 'Custom' for s in every(5)))
        self.assertTrue(any(s['foot'] and s['foot'].get('mark') for s in every(8)))
        # 10-30: an ISP option that exists but misses the FPS by a hair; the I.HBIN reason (seq 19)
        isp = [s for s in every(19) if s['sub'] == 'recipe' and s['foot'] and 'opts' in s['foot']]
        self.assertTrue(any(s['tiles'][6]['v'] == '1' and s['S']['fps'] > 131.9 and
                            all(o['na'] and o['s'].endswith('<131.68p') for o in s['foot']['opts'][1:13]) and
                            s['foot']['opts'][13] == dict(l=CPU2, s='not at this RES', na=True, mark=False, custom=False, approx=False)
                            for s in isp))   # v0.7.38test: 13 = CPU x2, no hbin-2 recipe at HD 2K
        self.assertTrue(any(any(o['na'] and o['s'] == '\u2192I.HBIN1' for o in s['foot']['opts']) for s in isp))
        self.assertTrue(any(s['tiles'][6]['v'].startswith('3[') for s in isp))

    def test_qr_auto_visibility_and_payload(self):
        """The QR is already visible before any input; AEL/focus do not toggle it, and changes refresh its payload."""
        qr = self.states[15]['states']
        self.assertTrue(qr[0]['qr'])
        self.assertEqual(len({s['qrcode'] for s in qr}), len({s['qrcode'] for s in qr if s['qrcode']}))
        self.assertGreaterEqual(len({s['qrcode'] for s in qr}), 3)
        self.assertTrue(any(not s['open'] for s in qr), 'the sequence closes QS')
        self.assertTrue(any(s['sub'] is not None for s in qr), 'the sequence enters a sub-QS')
        for i, state in enumerate(qr):
            expected = state['open'] and state['sub'] is None and bool(state['qrcode'])
            self.assertEqual(state['qr'], expected, (i, state['focus'], state['sub']))
        keys = SEQS[15]['keys']
        for i, k in enumerate(keys, 1):
            before, after = qr[i - 1], qr[i]
            if before['open'] and before['sub'] is None:
                if k.startswith('focus:') or (k == 'ael' and before['focus'] == 5):
                    self.assertTrue(after['qr'], (i, k))
                    self.assertEqual(after['qrcode'], before['qrcode'], (i, k))
                    self.assertIsNone(after['sub'], (i, k))
            if k == 'qs' and not before['open']:
                self.assertTrue(after['qr'], (i, 'reopening QS needs no AEL'))

    def test_qr_hidden_without_recipe(self):
        seq = dict(name='no recipe: QR stays hidden', keys=['focus:5', 'ael', 'left', 'ael', 'qs', 'qs'])
        got = run_page([seq], {'clk': 72_000_000, 'vmax_max': 32767, 'cases': {}})
        for state in got['out'][0]['states']:
            self.assertEqual(state['qrcode'], '')
            self.assertFalse(state['qr'])

    def test_custom_quality_keys_include_crop_dimensions(self):
        # Two free DC widths produce the same rounded RES. Their sensor plans must not share a case key.
        seq = dict(name='distinct custom crops, same RES',
                   keys=['focus:1', 'ael', 'focus:3', 'f+', 'focus:1', 'f-', 'f-'])
        got = run_page([seq], {'clk': 72_000_000, 'vmax_max': 32767, 'cases': {}})
        self.assertEqual(got['cells']['C6032x3402:2000x1134'], [6032, 3402, 2000, 1134])
        self.assertEqual(got['cells']['C6016x3402:2000x1134'], [6016, 3402, 2000, 1134])
        self.assertFalse(any(k.startswith('Custom:') for k in got['cells']))


@SKIP
class Tiles(unittest.TestCase):
    def test_qs_open(self):
        c = boot()
        self.assertEqual(Q1.stw(c, Q1.ST_N), 7)
        self.assertEqual(tile(c, 0)[1:], ('DNG', '12bit', False))       # v0.5.1test: the default HD 2K 59.94 = 12b 3x3
        self.assertEqual(tile(c, 1)[1:3], ('HD', '35.9 × 20.2 mm'))
        self.assertEqual(tile(c, 4)[0], 'RECIPE')                       # QSC_F_TITLE: text, not an icon
        self.assertTrue(tile(c, 3)[2].endswith(' recipes'))

    def test_recipe_sub_qs_has_seven_items(self):
        c = boot()
        c.guid(RCP_ID)
        press(c, 5, 4)
        self.assertEqual([tile(c, k)[0] for k in range(8)],
                         ['RECIPE', 'ADC', 'DC WIDTH', 'DC HEIGHT', 'SENSOR HBIN', 'SENSOR VBIN', 'ISP HBIN', 'ISP VBIN'])
        self.assertEqual(c.w(c.st() + TP.LAYOUT['sub_tile'] + 28), 72)    # the 7th item on UI 72

    def test_format_has_no_dial_and_mov_is_grey(self):
        c = boot()
        c.guid(FMT_ID)
        f = footer(c, FMT_ID)
        self.assertEqual([(x[0], x[5]) for x in f['items']], [('DNG', False), ('MOV', True)])
        before = tile(c, 0)
        press(c, 1, 0)
        self.assertEqual(tile(c, 0), before)

    def test_main_qs_layout_v021(self):
        """v0.2.1test (live run 4, main QS): RES options are labels only; the FPS switch point is marked with a
        character the small-line font has (U+00B7, not U+2022 which drew "?"); RECIPE asks for a text title (the
        container then draws no borrowed icon on it)."""
        c = boot()
        c.guid(RES_ID)
        f = footer(c, RES_ID)
        self.assertGreater(f['n'], 3)
        self.assertEqual([x[1] for x in f['items']], [''] * f['n'])
        c.guid(FPS_ID)
        seen = set()
        for _ in range(40):                                  # up the list until a switch point (a recipe's maximum)
            s = tile(c, 3)[2]
            seen.add(s[:2])
            self.assertNotIn('\u2022', s)
            self.assertTrue(all(ch < '\x7f' or ch in '\u00b7\u00d7' for ch in s), s)
            if s.startswith('\u00b7 '):
                break
            press(c, 1, 3)
        self.assertTrue(tile(c, 3)[2].startswith('\u00b7 '), seen)
        self.assertTrue(any(x[3] for x in footer(c, FPS_ID)['items']))   # and the footer marks it
        fx = c.st() + TP.LAYOUT['fx'] + FX_BYTES * (RCP_ID - 54)
        self.assertEqual(c.w(fx) & 4, 4)                     # QSC_F_TITLE on RECIPE only
        self.assertEqual(c.w(c.st() + TP.LAYOUT['fx'] + FX_BYTES * (FPS_ID - 54)) & 4, 0)


    def test_recipe_layout_v022(self):
        """v0.2.2test (RECIPE round): footer small "7.4ms" / " H2004"; greyed reasons short ("\u2192S.HBIN1",
        "max 60.56", "no 3x1"); the ISP bin value "3[1,2,1]" with the mode on the small line."""
        c = boot()
        c.guid(RCP_ID)
        for _ in range(12):                                  # v0.4.1test: the default is now 14b 1x3; this test is about 12b 2x3
            if tile(c, 4)[1] == '12b 2x3':
                break
            press(c, 2, 4)                                   # the dial down: 14b 1x3, 12b 1x3, 12b 1x2, 12b 3x2, 12b 2x3
        self.assertEqual(tile(c, 4)[1], '12b 2x3')
        f = footer(c, RCP_ID)
        self.assertGreater(f['n'], 3)
        for lab, sm, ap, *_ in f['items']:
            self.assertRegex(sm, r'^\d+\.\dms( H\d+)?$')
            self.assertEqual(ap, ' H' in sm)
        self.assertEqual(TP.st(c, 'foot_pitch'), 2)          # short enough: seven at the 128 px pitch
        press(c, 5, 4)                                       # AEL: the sub-QS
        # crop tiles: "S 6048" in the bold glyphs (fits VALUE_W, no plain fallback), the ISP crop "I 6048"
        self.assertEqual(tile(c, 2)[:3], ('DC WIDTH', 'S 6048', 'I 6048'))
        self.assertTrue(TP.texts(c)['QSC_V3'].startswith('<!font_menu_LB_id_S,CENTER> <!font_menu_LB_6'))
        reasons = []
        for k in range(1, 8):
            c.guid(focus_int(c, k))
            for lab, sm, ap, mark, cu, grey in footer(c, focus_int(c, k))['items']:
                if grey:
                    reasons.append(sm.split(' ', 1)[1] if sm.startswith(('SOFT ', 'STD ')) else sm)
        self.assertTrue(reasons)
        for r in reasons:
            self.assertRegex(r, r'^(\u2192(\d+bit|[SI]\.[HV]BIN\d+|CPU\u00d72)( (\d+bit|[SI]\.[HV]BIN\d+|CPU\u00d72))*|<\d+\.\d\dp|no \dx\d|not at this RES)$')
        c.guid(focus_int(c, 6))
        f = footer(c, focus_int(c, 6))
        self.assertEqual([x[0] for x in f['items']][:3], ['1', '3[1,1,1]', '3[1,2,1]'])
        self.assertEqual(TP.st(c, 'foot_pitch'), 3)          # container v0.2.4: "SOFT \u2192S.HBIN1" ~121 px -> 192 px pitch, 5 at once
        self.assertTrue(all(x[1].split(' ')[0] in ('SOFT', 'STD') for x in f['items'][1:13]))
        self.assertEqual((len(f['items']), f['items'][13][0]), (14, CPU2))   # v0.7.38test: CPU x2 last
        self.assertEqual(tile(c, 6)[1], '1')
        c.guid(focus_int(c, 4))
        press(c, 2, 4)                                       # SENSOR HBIN 2 -> 1: ISP HBIN 3 becomes possible
        c.guid(focus_int(c, 6))
        press(c, 1, 6)
        self.assertEqual(tile(c, 6)[1:3], ('3[1,2,1]', 'SOFT \u00b7 RWZM 1:1'))


@SKIP
class RatioTile(unittest.TestCase):
    def test_ratio_lock_has_client_text_fallback(self):
        # Query the registered client callback, before a newer container may
        # replace its text with an image. Older API 6 containers need this text.
        for main in (1, 2):
            with self.subTest(main=main):
                c = boot(); press(c, 5, main)
                fx = c.st() + TP.LAYOUT['fx'] + FX_BYTES * TP.st(c, 'sub_open')
                j = focus_int(c, 3) - 71  # UI tile 0 repeats the parent; sub-array starts at tile 1
                fn = c.w(fx + 32 + 4 * SUBS * 3 + 4 * j)
                arg = c.w(fx + 32 + 4 * SUBS * 2 + 4 * j)
                for expected in ('LOCK', '', 'LOCK'):
                    c.mu.mem_write(FOOT, bytes(4))
                    addr, _ = c.call(fn & ~1, r0=arg, r1=FOOT, thumb=bool(fn & 1))
                    self.assertEqual(c.cstr(addr, 64), expected)
                    self.assertEqual(c.w(FOOT), 0)
                    press(c, 1, 3)

    def test_common_aligned_cinema_and_tolerance_labels(self):
        c = boot()
        cases = [(0,1080,'-'), (1920,0,'-'), (1920,1080,'16:9'), (6048,4040,'3:2'),
                 (5088,3392,'3:2'), (4096,3072,'4:3'), (4000,3200,'5:4'),
                 (2000,2000,'1:1'), (4000,2000,'2:1'), (1080,1920,'9:16'),
                 (3000,4000,'3:4'), (4000,5000,'4:5'), (2000,3000,'2:3'),
                 (3700,2000,'1.85X'), (4780,2000,'2.39X'), (5088,4040,'1.26X'),
                 (5985,4000,'3:2'), (6015,4000,'3:2'),  # inclusive 0.25% boundary
                 (5984,4000,'1.50X'), (6016,4000,'1.50X')]
        for w, h, expected in cases:
            with self.subTest(w=w, h=h):
                addr, _ = c.call(fn_addr(c, 'sq_test') & ~1, r0=32, r1=w, r2=h, thumb=True)
                self.assertEqual(c.cstr(addr, 64), expected)

    def test_native_lock_only_on_ratio_and_cleared_on_exit(self):
        for main in (1,2):
            c = boot(); press(c, 5, main)
            self.assertEqual([c.vars[f'QSC_LW{k}'][1] for k in range(1,9)], [0]*8)
            self.assertEqual([c.vars[f'QSC_SW{k}'][1] for k in range(1,9)], [0,0,0,120,0,0,0,0])
            press(c, 1, 3)
            self.assertEqual([c.vars[f'QSC_SW{k}'][1] for k in range(1,9)], [0]*8)
            press(c, 1, 3)
            self.assertEqual(c.vars['QSC_SW4'][1], 120)
            press(c, 5, 3)
            self.assertEqual([c.vars[f'QSC_SW{k}'][1] for k in range(1,9)], [0]*8)

    def test_dc_res_small_icon_and_live_large_value(self):
        for main, ratio in [(1,3),(2,3)]:
            with self.subTest(main=main):
                c = boot(); c.guid(DC_ID if main == 1 else RES_ID); press(c, 5, main)
                # Both lock choices preserve aspect text in the bold value row.
                vals = []
                for _ in range(2):
                    c.guid(focus_int(c, ratio)); press(c, 1, ratio)
                    title, value, small, approx = tile(c, ratio)
                    vals.append(c.vars[f'QSC_SW{ratio+1}'][1])
                    self.assertEqual(title, 'RATIO')
                    self.assertRegex(value, r'^(?:[0-9]+:[0-9]+|[0-9]+\.[0-9]{2}X)$')
                    self.assertEqual(small, ' '); self.assertFalse(approx)
                    self.assertEqual(TP.texts(c)[f'QSC_V{ratio+1}'], TP.big(value))
                self.assertEqual(set(vals), {0, 120})
                # Unlocked width changes refresh the visible ratio without leaving the submenu.
                if c.vars[f'QSC_SW{ratio+1}'][1]: press(c, 1, ratio)
                before = tile(c, ratio)[1]
                for _ in range(10): press(c, 2, 1)
                self.assertNotEqual(tile(c, ratio)[1], before)
                self.assertEqual(tile(c, ratio)[0], 'RATIO')


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
        sys.path.insert(0, str(HERE.parent / 'menu'))
        import slm_page
        # Keep the previous code/data budget; v0.6 additionally embeds two
        # complete menu edits and their private resource pack; v0.7.26test + 2 KiB for the first-frame row
        # repair (apply/ap.c, ~1.4 KiB; the loader's limit is MAX_BLOCK 16 MiB, this is a growth guard only).
        # v0.7.32test + 16 KiB for the QR scan (qrdec.c ~11 KiB, the read-page hooks and the restore check);
        # v0.7.36test + 4 KiB: the boot apply (poller, standby-screen hook) and the RES recorded-size line;
        # CPU x2 + 8 KiB: the NEON kernels (tools/cpu_h2) and the streaming pass (apply/ap.c, notes/CPU_X2_DESIGN.md)
        self.assertLess(info['bytes'], 128 * 1024 + 0x800 + 0x5000 + 0x2000 + len(slm_page.build()) + len(slm_page.pack()))
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
        """sq_apply: the effective recipe's readout key, HMAX and the VMAX step of the selected rate (the smallest VMAX
        whose rate does not exceed it), the kernels.  v0.5.0test: every dial step is a change event, so it is current
        right after the press (it was leave() only before)"""
        import quality as Q
        c = boot()
        fn = fn_addr(c, 'sq_test')
        a, _ = c.call(fn & ~1, r0=10, thumb=True)
        press(c, 1, 1)                                               # S35, RES /3 = 1392 x 786, 59.94
        w = struct.unpack('<14I', bytes(c.mu.mem_read(a, 56)))
        valid, dcw, dch, rw, rh, key, hm, vmax, fn_, fd, kh, kv, km, ri = w
        self.assertEqual((valid, dcw, dch, rw, rh, fn_, fd, kh, kv, km), (1, 4192, 2358, 1392, 786, 5994, 100, 1, 1, 0))
        cs = Q.qualities(4192, 2358, 1392, 786, tol=0.02)
        _ad, mh, mv = re.fullmatch(r'(\d+)b (\d)x(\d)', tile(c, 4)[1]).groups()   # the default pick (defaultPick)
        c0 = [x for x in cs if (x['hbin'], x['vbin']) == (1, 1) and x['merge'] == f'{mh}x{mv}' and Q.hmax_of(x) == hm]
        self.assertTrue(c0, (mh, mv, hm))
        c0 = c0[0]
        f = 59.94
        self.assertLessEqual(Q.fps_at(c0, vmax), f + 1e-9)
        self.assertGreater(Q.fps_at(c0, vmax - 1), f)


AP_STATUS = ('bytes abi armed active cur mode_id pid result detail commits refusals lv_reloads owed picks lookups '
             'canvases recrates standby_picks carrier carrier_sets fast commit_us gated blacks').split()
AP_SEL = 'bytes abi valid fmt dcw dch rw rh key hbin vbin hm vmax fps_n fps_d kh kv km standby'.split()


def ap_status(c):
    a = sqt(c, 17)
    d = dict(zip(AP_STATUS, struct.unpack('<24I', bytes(c.mu.mem_read(a, 96)))))
    d['result'] = d['result'] - (1 << 32) if d['result'] & 0x80000000 else d['result']
    return d


def ap_sel(c):
    return dict(zip(AP_SEL, struct.unpack('<19i', bytes(c.mu.mem_read(sqt(c, 18), 76)))))


class ApplyUnit(unittest.TestCase):
    """v0.5.0test: the apply unit (../apply) inside the BIN, under the real v4 core and QSContainer v0.2.4.  Its own
    behaviour is apply/test_apply.py's; here: it is armed by sup_entry, the QS change events and leave() reach it with
    the effective selection, and the boot restore commits at the first leave() that finds a mode descriptor."""

    def test_entry_arms_it_and_the_change_events_reach_ap_request(self):
        c = boot()
        st = ap_status(c)
        self.assertEqual((st['armed'], st['abi']), (1, 3), 'ap_init in sup_entry: 26 hooks + the clock gate claimed')
        self.assertEqual(sqt(c, 21), 0, 'ap_init returned AP_OK')
        pushes = lambda: sqt(c, 20)                                   # noqa: E731
        n0 = pushes()
        press(c, 1, 1)                                               # a dial step on DC: S35
        self.assertGreater(pushes(), n0, 'adjust -> ap_request')
        a, w = ap_sel(c), struct.unpack('<14I', bytes(c.mu.mem_read(sqt(c, 10), 56)))
        self.assertEqual((a['bytes'], a['abi'], a['valid'], a['fmt'], a['standby']), (76, 3, 1, 0, 1))
        self.assertEqual((a['dcw'], a['dch'], a['rw'], a['rh'], a['key'], a['hm'], a['vmax'], a['fps_n'], a['fps_d']),
                         (w[1], w[2], w[3], w[4], w[5], w[6], w[7], w[8], w[9]))
        st = ap_status(c)
        self.assertEqual(st['result'], -3, 'no mode descriptor yet: AP_E_NOTREADY, owed')
        self.assertEqual((st['active'], st['owed']), (0, 1))
        n1 = pushes()
        c.layout()                                                   # leave()
        self.assertGreater(pushes(), n1, 'leave() -> ap_request / ap_flush')

    def test_sq_test_33_hands_out_the_first_frame_trace_read_only(self):
        """v0.7.27test: op 33 a=0 -> the trace inside the apply state, a=1 -> its record count (0: no take yet)"""
        c = boot()
        t = sqt(c, 33) & 0xFFFFFFFF
        base = sqt(c, 17) & 0xFFFFFFFF                               # the status lives in st, the trace in ap_mem
        self.assertTrue(t and t % 4 == 0)
        before = bytes(c.mu.mem_read(t, 16 * 4 + 12 * 56 * 4))
        self.assertEqual(sqt(c, 33, 1), 0)
        self.assertEqual(struct.unpack_from('<4I', before), (0, 0, 0, 0), 'nothing armed: an empty trace')
        self.assertEqual(bytes(c.mu.mem_read(t, len(before))), before, 'reading it changes nothing')
        self.assertNotEqual(t, base)

    def test_leave_flushes_the_owed_commit_once_the_descriptor_exists(self):
        c = boot()                                                   # boot restore: owed, NOTREADY
        self.assertEqual(ap_status(c)['active'], 0)

        ap_firmware(c, descriptor=True, fr=3)                        # the first live view built it; the menu was on 29.97
        c.layout()                                                   # leave() flushes
        st = ap_status(c)
        self.assertEqual((st['result'], st['active'], st['owed']), (0, 1, 0), st)
        self.assertIn(st['mode_id'], (230, 231))
        self.assertEqual((st['carrier'], c.w(FR_WORD), st['carrier_sets']), (5, 5, 1), '59.94: the carrier set natively')
        self.assertEqual(c.w(0xC0189440), 0x2C49F241, 'a slow recipe leaves the clock gate stock')
        n = st['commits']
        c.layout()
        self.assertEqual(ap_status(c)['commits'], n, 'the same selection again: no commit, no LV flash')
        press(c, 1, 1)                                               # a change event commits at once
        self.assertEqual(ap_status(c)['commits'], n + 1)
        self.assertEqual(sqt(c, 22), 0, 'sq_test 22: an invalid selection -> stock')
        self.assertEqual(ap_status(c)['active'], 0)

    def test_dials_publish_current_fallback_pair_without_leaving_qs(self):
        """Real BIN callbacks/commits + fallback veneer; LCD scheduling is not modeled."""
        from unicorn import arm_const as R
        c = boot(descriptor=True)
        c.mu.reg_write(R.UC_ARM_REG_C1_C0_2, 0xF00000)
        c.mu.reg_write(R.UC_ARM_REG_FPEXC, 0x40000000)
        c.mu.reg_write(R.UC_ARM_REG_FPSCR, 0)
        self.assertEqual(ap_status(c)['active'], 1)
        c.guid(focus_int(c, 1))
        press(c, 5, 1)  # DC sub-QS (AEL); WIDTH/HEIGHT are tiles 1/2.
        self.assertGreaterEqual(TP.st(c, 'sub_open'), 0)
        for tile_id in (1, 1, 2, 2, 1, 2):
            before = ap_status(c)['commits']
            c.guid(focus_int(c, tile_id))
            press(c, 4, tile_id)  # fine decrement, with QS kept open throughout
            st = ap_status(c)
            self.assertEqual((st['result'], st['active'], st['owed']), (0, 1, 0))
            self.assertGreater(st['commits'], before)
            # Ask the already-tested movie branch for this slot's aspect enum.
            c.mu.reg_write(R.UC_ARM_REG_CPSR, c.mu.reg_read(R.UC_ARM_REG_CPSR)&~0x20)
            c.mu.emu_start(0xC0306E70, 0xC0306E74, count=100000)
            self.assertEqual(c.mu.reg_read(R.UC_ARM_REG_PC), 0xC0306E74)
            enum = c.mu.reg_read(R.UC_ARM_REG_R0)
            self.assertIn(enum, (3, 9))
            reference, _ = c.call(0xC02DAFA0, r0=enum)
            expected = (c.w(reference), c.w(reference+4))
            c.mu.reg_write(R.UC_ARM_REG_CPSR, c.mu.reg_read(R.UC_ARM_REG_CPSR)&~0x20)
            c.mu.reg_write(R.UC_ARM_REG_R1, 0xABCD1234)
            c.mu.emu_start(0xC0306F28, 0xC0306F2C, count=100000)
            self.assertEqual(c.mu.reg_read(R.UC_ARM_REG_PC), 0xC0306F2C)
            pair = c.mu.reg_read(R.UC_ARM_REG_R1)
            state = st_addr(c)
            self.assertTrue(state <= pair < state + blob()[1]['dma_off'] - blob()[1]['state_off'])
            actual = (c.w(pair), c.w(pair+4))
            if enum == 9:
                self.assertEqual(actual, expected)
                self.assertEqual(pair, reference)
            else:
                # Compare actual native fits, since the stored fraction is rounded
                # and can land on the edge of the exact-rational 16:9 tolerance.
                self.assertEqual(expected, (16, 9))
                rect, display = FOOT+0x200, FOOT+0x220
                c.mu.mem_write(display, struct.pack('<2I',3,2))
                fitted=[]
                for aspect in (reference,pair):
                    c.mu.mem_write(rect, struct.pack('<4I',0,0,1620,1080))
                    c.call(0xC02F4410,r0=rect,r1=aspect,r2=display)
                    fitted.append(bytes(c.mu.mem_read(rect,16)))
                self.assertEqual(fitted[0],fitted[1])
            self.assertGreaterEqual(TP.st(c, 'sub_open'), 0)

    def test_playback_controls_and_ui_idle_are_integrated(self):
        c = boot()
        p = sqt(c, 23)
        self.assertEqual(c.w(p), 0x42504C53, 'resident SLPB status is reachable')
        # v0.7.9test: selected-clip canvas enabled with metadata admission; the v1 fallback remains selectable.
        self.assertEqual(sqt(c, 24, 0, 2), 1, 'default: selected-clip playback')
        self.assertEqual(c.w(p + 4), 2)
        self.assertEqual(sqt(c, 24, 0, 3), 0xFFFFFFFF, 'invalid policy is refused')
        self.assertEqual(c.w(p + 4), 2)
        self.assertEqual(sqt(c, 24, 0, 0), 2)
        self.assertEqual(sqt(c, 24, 3, 1), 1, 'default: metadata admission remains enabled')
        self.assertEqual(sqt(c, 24, 1, 0), 0, 'v1 default: no HUD tiles')
        self.assertEqual(c.w(p + 4 * 176), 1, 'block word (appended after tpl[4])')
        ap_firmware(c, descriptor=True, fr=3)
        c.layout()
        self.assertEqual(ap_status(c)['active'], 1)
        words = struct.unpack('<34I', bytes(c.mu.mem_read(p, 34 * 4)))
        self.assertEqual(words[33], 0, 'leave drains the queued HUD numbers in UI context')
        self.assertEqual(words[26], 0, 'v1: no NBR pack registered at the first MENU')
        self.assertGreater(words[27], 0, 'the queue was offered and refused, not left')


# ---------------------------------------------------------------------------------- QR (v0.4.0test)
QR_URL = 'https://ijigen.github.io/fpSup/sensor_lab_imx410/#'
QR_FIELDS = [('ver', 4), ('dcw', 13), ('dch', 12), ('rw', 13), ('rh', 12), ('fps', 5), ('vmax', 15), ('hmax', 16), ('ad', 2),
             ('mh', 2), ('mv', 3), ('hbin', 4), ('vbin', 4), ('key', 6), ('kh', 3), ('kv', 3), ('km', 1), ('rcustom', 1),
             ('visw', 13), ('vish', 12), ('rs', 17), ('fmt', 1), ('rescustom', 1), ('scw', 13), ('sch', 12), ('ww', 13),
             ('wh', 12)]                                  # notes/QR_QS_RESEARCH.md §3.4
B64U = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'


def crc8(bits):
    """CRC-8, poly 0x07, init 0, MSB first, no reflection / xor (the textbook register form)"""
    reg = 0
    for b in bits:
        reg ^= b << 7
        reg = ((reg << 1) ^ 0x07) & 0xFF if reg & 0x80 else (reg << 1) & 0xFF
    return reg


def qr_pack(vals):
    bits = [v >> i & 1 for (_n, w), v in zip(QR_FIELDS, vals) for i in range(w - 1, -1, -1)]
    assert len(bits) == 213
    c = crc8(bits)
    bits += [c >> i & 1 for i in range(7, -1, -1)] + [0]
    return ''.join(B64U[int(''.join(map(str, bits[i:i + 6])), 2)] for i in range(0, 222, 6))


def qr_unpack(code):
    bits = [int(b) for ch in code for b in format(B64U.index(ch), '06b')]
    out, k = {}, 0
    for n, w in QR_FIELDS:
        out[n] = int(''.join(map(str, bits[k:k + w])), 2)
        k += w
    return out, int(''.join(map(str, bits[213:221])), 2) == crc8(bits[:213]) and bits[221] == 0


def decode_qr(gray):
    """Verify pristine V5-L structure/RS/payload without scratchpad dependencies.

    Also decode with OpenCV when installed here or in SLQS_CV_PYTHON. Without
    it, the bounded reference parser verifies generated pixels only; phone/
    optical scanning is NOT verified. SLQS_REQUIRE_OPENCV=1 requires that check.
    """
    import numpy as np
    qr_tools = str(HERE.parent / 'tools' / 'qr')
    if qr_tools not in sys.path:
        sys.path.insert(0, qr_tools)
    from qr_v5_reference import decode_pristine_image
    img = np.ascontiguousarray(gray, dtype=np.uint8)
    try:
        verified = decode_pristine_image(img)
    except ValueError:
        return ''
    try:
        import cv2
        decoded = cv2.QRCodeDetector().detectAndDecode(img)[0]
    except ImportError:
        py = os.environ.get('SLQS_CV_PYTHON')
        if not py:
            if os.environ.get('SLQS_REQUIRE_OPENCV') == '1':
                raise RuntimeError('OpenCV required: set SLQS_CV_PYTHON to an interpreter with cv2 and numpy')
            return verified
        with tempfile.TemporaryDirectory(prefix='slqs-qr-') as t:
            f = pathlib.Path(t) / 'img.npy'
            np.save(f, img)
            r = subprocess.run([py, '-c', 'import sys,cv2,numpy as np;'
                                'print(cv2.QRCodeDetector().detectAndDecode(np.load(sys.argv[1]))[0], end="")', str(f)],
                               capture_output=True, text=True, check=True, cwd=t)
            decoded = r.stdout
    return verified if decoded == verified else ''


def qr_info(c):
    k = ('on', 'enc_ret', 'n', 'scale', 'x0', 'y0', 'mat', 'url', 'obs', 'draw', 'shows', 'hides', 'draws', 'why', 'side',
         'reg', 'group', 'tile', 'nbuf', 'restores', 'mask', 'slot')
    a = sqt(c, 14)
    return dict(zip(k, struct.unpack('<22I', bytes(c.mu.mem_read(a, 88)))))


QS_GUI, QS_GUI_VT = 0xC37859E0, 0xC0D1D6C4
UIC_DRAW_OBJ = 0xC38D3D0C                             # UicContentsIfBase::v16: the GUI's DrawingObserver


def TILE_X(k):
    return 256 * (k % 4)


def TILE_Y(k):
    return 77 + 231 * (k // 4)


class QRScreen:
    """The draw controller for the QR tests: groups 0 and 2 on one 16-bpp layer (live7), the GUI's observer in group 2
    slot 0; FUN_c0528300 / FUN_c05283D8 run for real (their lock and event calls are no-ops here)."""
    CTRL, LAYER, FB, DESC, ARG = 0xC3783020, 0x70600000, 0x70000000, 0x70610000, 0x70620000
    BUF = 0x160000

    def __init__(self, c):
        import numpy as np
        self.c = c
        c.put(QS_GUI, QS_GUI_VT)
        c.put(UIC_DRAW_OBJ + 8, QS_GUI)
        for a in (0xC0010298, 0xC00102D0, 0xC036D758):
            c.mu.mem_write(a, struct.pack('<I', 0xE12FFF1E))
        c.mu.mem_map(self.FB, 0x700000)
        c.mu.mem_write(self.CTRL, bytes(0x80))
        c.put(self.LAYER + 0x1C, 1)
        c.put(self.CTRL + 0x58 + 8 * 0, self.LAYER)               # groups 0 and 2 share the main layer
        c.put(self.CTRL + 0x58 + 8 * 2, self.LAYER)
        c.put(self.CTRL + 12 * 2, UIC_DRAW_OBJ)
        c.put(self.CTRL + 0x48 + 4 * 2, 1)
        for b in range(4):                                         # 3 rotating buffers + group 0's never-presented one
            d = self.DESC + 0x40 * b
            c.mu.mem_write(d, struct.pack('<4I', 0, self.FB + self.BUF * b, d + 0x20, 0) + bytes(16) +
                           struct.pack('<2I', 1024, 682))
        c.mu.mem_write(self.ARG, bytes(16))
        self.G = np.zeros((682, 1024), np.uint16)
        self.G[:77] = 0x0000
        for k in range(8):                                         # a GUI picture: tiles, text-ish white pixels
            x, y = TILE_X(k), TILE_Y(k)
            self.G[y:y + 223, x:x + 256] = 0xD222 + 0x111 * k
            self.G[y + 40:y + 80:3, x + 60:x + 200:2] = 0xFFFF
        self.G[531:] = 0x0000
        self.dirty = [None] * 3                                    # per buffer: rects it still has to repaint
        self.front, self.focused, self.cycles = 2, None, 0
        for b in range(3):
            self.put_buf(b, self.G)
            self.uic_record(b, 2, (0, 0, 1024, 682))
        self.dirty = [[(0, 0, 1024, 682)] for _ in range(3)]
        self.last_vars = c.vars.copy()
        self.commits = 0

    def uic_record(self, b, mode, rect):
        r = 0xC37B7048 + 0x18 + 0x20 * b
        self.c.mu.mem_write(r, struct.pack('<7I', 0, self.FB + self.BUF * b,
                                         *[v & 0xFFFFFFFF for v in rect], mode))

    def put_buf(self, b, img, rect=None):
        import numpy as np
        if rect is None:
            self.c.mu.mem_write(self.FB + self.BUF * b, img.astype('<u2').tobytes())
            return
        x, y, w, h = rect
        for r in range(y, y + h):
            self.c.mu.mem_write(self.FB + self.BUF * b + 2 * (1024 * r + x), img[r, x:x + w].astype('<u2').tobytes())

    def get_buf(self, b):
        import numpy as np
        return np.frombuffer(bytes(self.c.mu.mem_read(self.FB + self.BUF * b, 1024 * 682 * 2)), '<u2').reshape(682, 1024)

    def change(self, rects):                                       # the GUI changed these: every buffer repaints them
        for d in self.dirty:
            d.extend(rects)

    def tile(self, k, focused):                                # the focused tile: darker inside, the box (live6 2693)
        x, y = TILE_X(k), TILE_Y(k)
        self.G[y:y + 223, x:x + 256] = 0xE111 if focused else 0xD222 + 0x111 * k
        self.G[y + 40:y + 80:3, x + 60:x + 200:2] = 0xFFFF
        if focused:
            for sx, sy, w, h in [(x, y, 256, 5), (x, y + 218, 256, 5), (x, y, 4, 223), (x + 252, y, 4, 223)]:
                self.G[sy:sy + h, sx:sx + w] = 0xF4BE
        self.change([(x, y, 256, 223)])

    def focus(self, k):
        if self.focused is not None:
            self.tile(self.focused, False)
        self.focused = k
        self.tile(k, True)

    def hint(self, v):
        self.G[540:600, 700:1000] = 0xFFFF if v else 0
        self.change([(700, 540, 300, 60)])

    def slots(self, g):
        return [self.c.w(self.CTRL + 12 * g + 4 * k) for k in range(3)]

    def observers(self, g, desc):
        changed = 0
        for o in self.slots(g):
            if o and o != UIC_DRAW_OBJ:
                fn = self.c.w(self.c.w(o) + 0xC)
                changed |= self.c.call(fn & ~1, r0=o, r1=desc, r2=self.ARG, thumb=bool(fn & 1))[0]
        return changed

    def cycle(self, mode=0):
        """one FUN_c0528700 pass: group 0 (its buffer never presented), group 2 = GUI then the rest in slot order,
        present only when a drawer returns nonzero. Native mode 1 updates state but never paints/presents.
        Text-variable changes model a QS-panel redraw; explicit rect changes remain per buffer."""
        if self.last_vars != self.c.vars:
            self.change([(0, 77, 1024, 454)])
            self.last_vars = self.c.vars.copy()
        self.observers(0, self.DESC + 0x40 * 3)
        b = (self.front + 1) % 3
        rects = self.dirty[b]
        rect = (0, 0, 0, 0)
        if rects:
            x=min(r[0] for r in rects); y=min(r[1] for r in rects)
            rect=(x,y,max(r[0]+r[2] for r in rects)-x,max(r[1]+r[3] for r in rects)-y)
        self.uic_record(b, mode, rect)
        rendered = mode != 1 and bool(rects)
        if rendered:
            for r in rects: self.put_buf(b, self.G, r)
            self.dirty[b] = []
        qr = self.observers(2, self.DESC + 0x40 * b)
        if rendered or qr:
            self.front = b
            self.commits += 1
        self.cycles += 1
        return self.get_buf(self.front).copy()


class QRPayload(unittest.TestCase):
    def test_reference_crc_and_layout(self):
        """the Python reference itself: CRC-8/SMBUS check value, 213 data bits, 37 chars, the URL length"""
        self.assertEqual(crc8([int(b) for ch in b'123456789' for b in format(ch, '08b')]), 0xF4)
        self.assertEqual(sum(w for _n, w in QR_FIELDS), 213)
        code = qr_pack([1] * len(QR_FIELDS))
        self.assertEqual(len(code), 37)
        self.assertEqual(qr_unpack(code), ({n: 1 for n, _w in QR_FIELDS}, True))
        self.assertEqual(len(QR_URL), 50)
        self.assertEqual(len(QR_URL + code), 87)                 # V20-L takes 858 bytes
        self.assertIn('#define QR_URL      "' + QR_URL + '"', (HERE / 'slqs.c').read_text())

    def test_page_reference(self):
        """the page's qrPack (node) = the Python reference"""
        import random
        rnd = random.Random(7)
        vecs = [[rnd.randrange(1 << w) for _n, w in QR_FIELDS] for _ in range(200)]
        html = (PREVIEW / 'dcres.html').read_text()
        src = html[html.index('const QR_FIELDS'):html.index('function qrCode()')]
        js = src + 'const V=%s;console.log(JSON.stringify(V.map(v=>qrPack(Object.fromEntries(QR_FIELDS.map(([k],i)=>[k,v[i]]))))))' % json.dumps(vecs)
        got = json.loads(subprocess.run(['node', '-e', js], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(got, [qr_pack(v) for v in vecs])
        self.assertIn("const QR_URL = '" + QR_URL + "';", html)


@SKIP
class QR(unittest.TestCase):
    """Current V5-L QR: C payload/encoder, strict matrix parser and optional OpenCV,
    observer pixels and triple-buffer restoration; all camera execution is emulated."""

    def test_update_only_and_idle_do_not_flip_stale_qs(self):
        """A background/update-only UIC round must leave both framebuffer bytes and front pointer alone."""
        import numpy as np
        c=boot(qr_force=0);lcd=QRScreen(c);c.guid(FMT_ID)
        for _ in range(3): lcd.cycle()
        before=lcd.get_buf(lcd.front).copy();front=lcd.front;commits=lcd.commits
        back=(front+1)%3
        stale=np.full((682,1024),0xA123,np.uint16)    # another QS frame, not the current front
        lcd.put_buf(back,stale)
        lcd.hint(1)                                  # update pending, but mode 1 must not render it
        for _ in range(6):
            self.assertTrue((lcd.cycle(mode=1)==before).all())
            self.assertEqual((lcd.front,lcd.commits),(front,commits))
            self.assertTrue((lcd.get_buf(back)==stale).all())
        # The next real UIC draw refreshes the background; QR joins that existing present.
        lcd.change([(0,0,1024,682)])
        for _ in range(3): lcd.cycle()
        before=lcd.get_buf(lcd.front).copy();commits=lcd.commits
        for _ in range(6):self.assertTrue((lcd.cycle()==before).all())
        self.assertEqual(lcd.commits,commits)          # empty native rects are idle, not a QR animation

    def test_uic_record_lookup_matches_firmware_and_refuses_missing_or_invalid(self):
        # C055F0F0 getter: movw/movt r4=singleton base; returns r4+0x14.
        image=pathlib.Path(ROOT/'out/MAIN_c0000000.bin').read_bytes()
        wd=lambda a:struct.unpack_from('<I',image,a-0xC0000000)[0]
        imm=lambda v:((v>>4)&0xF000)|(v&0xFFF)
        lo,hi=wd(0xC055F0F4),wd(0xC055F0F8)
        self.assertEqual(wd(0xC055F180),0xE2840014)
        self.assertEqual(((imm(hi)<<16)|imm(lo))+0x14,0xC37B7048)
        c=boot(qr_force=1);lcd=QRScreen(c);c.guid(FMT_ID);q=qr_info(c)
        def draw():return c.call(q['draw']&~1,r0=q['obs'],r1=lcd.DESC,r2=lcd.ARG,thumb=True)[0]
        before=bytes(c.mu.mem_read(lcd.FB,1024*682*2))
        for mode,rect in ((1,(0,0,1024,682)),(3,(0,0,1024,682)),(0,(0,0,0,682)),(0,(0,0,1024,0)),(0,(0,0,-1,682))):
            lcd.uic_record(0,mode,rect);self.assertEqual(draw(),0)
            self.assertEqual(bytes(c.mu.mem_read(lcd.FB,len(before))),before)
        c.put(0xC37B7064,0)                           # no matching record
        self.assertEqual(draw(),0)
        lcd.uic_record(0,2,(0,0,1024,682));self.assertEqual(draw(),1)

    def test_auto_main_all_slots_without_focus_or_ael(self):
        """The QR follows its assigned tile, never the focused tile; no AEL or repeated encoding."""
        import numpy as np
        for slot in range(8):
            with self.subTest(slot=slot):
                c = boot(qr_force=0)
                lcd = QRScreen(c)
                slots = list(SLOTS)
                slots[slot], slots[5] = slots[5], slots[slot]
                TP.set_cine(c, slots)
                c.layout()
                c.guid(FMT_ID)
                i = qr_info(c)
                self.assertEqual((i['on'], i['reg'], i['tile']), (1, 1, slot))
                self.assertEqual((i['x0'], i['y0']), (TILE_X(slot) + 25, TILE_Y(slot) + 9))
                f = lcd.cycle()
                x,y,n = i['x0'], i['y0'], i['side']
                outside = np.ones(f.shape, bool); outside[y:y+n,x:x+n] = False
                self.assertTrue((f[outside] == lcd.G[outside]).all())
                self.assertEqual(set(np.unique(f[y:y+n,x:x+n])), {0xF000, 0xFFFF})
                c.guid(QR_ID); TP.press(c, 5, QR_ID); c.guid(MB_ID)
                self.assertEqual(qr_info(c)['shows'], i['shows'])
                self.assertEqual(qr_info(c)['on'], 1)

    def test_updates_across_rotating_buffers_then_restores_submenu(self):
        """Change the payload twice before all buffers have rotated: restore each one's own QR version."""
        import numpy as np
        c = boot(qr_force=0); lcd = QRScreen(c); c.guid(FMT_ID)
        for _ in range(3): lcd.cycle()
        old = c.cstr(qr_info(c)['url'], 96)
        for _ in range(2):
            press(c, 1, 3)
            info = qr_info(c)
            current = QR_URL + c.cstr(sqt(c, 13), 64)
            self.assertNotEqual(current, old)
            self.assertEqual(c.cstr(info['url'], 96), current)
            f = lcd.cycle()
            x,y,n = info['x0'],info['y0'],info['side']
            code = np.where(f[y:y+n,x:x+n] == 0xF000, 0, 255).astype(np.uint8)
            self.assertEqual(decode_qr(np.pad(code, 20, constant_values=255)), current)
            old = current
        press(c, 5, 1)                                   # DC sub-QS, without any layout load
        self.assertEqual(qr_info(c)['on'], 0)
        for _ in range(3): self.assertTrue((lcd.cycle() == lcd.G).all())
        self.assertEqual(qr_info(c)['nbuf'], 0)
        press(c, 5, 0)                                   # return to main QS, no AEL on QR
        self.assertEqual(qr_info(c)['on'], 1)
        self.assertTrue((lcd.cycle() != lcd.G).any())

    def test_native_owner_and_absent_tile_prevent_paint(self):
        """Text preparation on a non-QS page must not paint QR over liveview or menus."""
        c = boot(qr_force=0); lcd = QRScreen(c); c.guid(FMT_ID)
        for owner,vt in ((0, QS_GUI_VT), (QS_GUI + 0x100, QS_GUI_VT), (QS_GUI, 0)):
            c.put(UIC_DRAW_OBJ + 8, owner); c.put(QS_GUI, vt)
            self.assertTrue((lcd.cycle() == lcd.G).all())
        c.put(UIC_DRAW_OBJ + 8, QS_GUI); c.put(QS_GUI, QS_GUI_VT)
        lcd.change([(0, 0, 1024, 682)])                  # entering QS schedules a native full draw
        self.assertTrue((lcd.cycle() != lcd.G).any())
        TP.set_cine(c, [FMT_ID, DC_ID, RES_ID, FPS_ID, RCP_ID, 19, MB_ID, 20])
        c.layout()
        self.assertEqual(qr_info(c)['reg'], 0)
        self.assertEqual(lcd.slots(2), [UIC_DRAW_OBJ, 0, 0])
        for b in range(3): lcd.put_buf(b, lcd.G)           # native full layout redraw
        for _ in range(3): self.assertTrue((lcd.cycle() == lcd.G).all())

    def test_c_pack_equals_reference(self):
        import random
        c = boot()
        rnd = random.Random(1)
        vecs = [[(1 << w) - 1 for _n, w in QR_FIELDS], [0] * len(QR_FIELDS)] + \
               [[rnd.randrange(1 << w) for _n, w in QR_FIELDS] for _ in range(300)]
        buf = F6.FAKE + 0x9400
        for v in vecs:
            c.mu.mem_write(buf, struct.pack(f'<{len(v)}I', *v))
            self.assertEqual(c.cstr(sqt(c, 15, buf), 64), qr_pack(v), v)
        v = [1 << w for _n, w in QR_FIELDS]                       # a field past its width is cut to it
        c.mu.mem_write(buf, struct.pack(f'<{len(v)}I', *v))
        self.assertEqual(c.cstr(sqt(c, 15, buf), 64), qr_pack([0] * len(v)))

    def test_live_payload_is_the_selection(self):
        """the camera's payload = the selection and the effective recipe (what sq_apply would install)"""
        c = boot()
        press(c, 1, 1)                                            # HD -> S35: 1392 x 786 (RES /3), 59.94
        c.layout()                                                # sq_apply
        code = c.cstr(sqt(c, 13), 64)
        f, ok = qr_unpack(code)
        self.assertTrue(ok)
        ap = struct.unpack('<14I', bytes(c.mu.mem_read(sqt(c, 10), 56)))
        self.assertEqual((f['ver'], f['dcw'], f['dch'], f['rw'], f['rh'], f['fps'], f['fmt'], f['rescustom']),
                         (1, 4192, 2358, 1392, 786, 8, 0, 0))     # 59.94 = STD[8]
        self.assertEqual((f['key'], f['hmax'], f['vmax'], f['kh'], f['kv'], f['km']), (ap[5], ap[6], ap[7], 1, 1, 0))
        ad, mh, mv = re.fullmatch(r'(\d+)b (\d)x(\d)', tile(c, 4)[1]).groups()   # the RECIPE tile
        self.assertEqual((f['mh'], f['mv'], f['hbin'], f['vbin'], f['rcustom']), (int(mh), int(mv), 1, 1, 0))
        self.assertEqual(f['ad'], {11: 0, 12: 1, 14: 2}[int(ad)])
        self.assertAlmostEqual(f['rs'], float(re.search(r'RS ([\d.]+) ms', tile(c, 4)[2]).group(1)) * 1000, delta=50)   # v0.7.38test: one decimal
        self.assertEqual(f'{f["visw"]}×{f["vish"]}', tile(c, 2)[2].split(' ')[0])   # the RES tile's visible size
        # The crop/window fields were appended after the first QR tests. Check
        # them against the independent Python planner, not just the C packer.
        candidates = [r for hm, _lo, _name, r in G.case(f['dcw'], f['dch'], f['rw'], f['rh'], 0.02)
                      if (hm, r['ad'], r['mh'], r['mv'], r['hbin'], r['vbin'])
                      == (f['hmax'], int(ad), f['mh'], f['mv'], f['hbin'], f['vbin'])]
        self.assertTrue(candidates)
        expected_crops = {(r['scw'], r['sch'], *r['win']) for r in candidates}
        self.assertIn((f['scw'], f['sch'], f['ww'], f['wh']), expected_crops)
        self.assertEqual(tile(c, 5)[:3], ('QR', 'QR', code[:10] + '..'))

    def test_encoder_matrix(self):
        """Main QS prepares our encoder: version 5 (37 x 37), decoded to the URL exactly; the square sits in the
        QR tile (slot 6 here: x 256.., y 308..) inside its focus box, the largest integer module with a 2-module quiet
        zone"""
        import numpy as np
        c = boot(qr_force=1)
        c.guid(QR_ID)
        press(c, 5, 5)
        i = qr_info(c)
        url = QR_URL + c.cstr(sqt(c, 13), 64)
        self.assertEqual((i['on'], i['n'], i['why'], i['tile']), (1, 37, 0, 5))
        self.assertEqual(c.cstr(i['url'], 128), url)
        self.assertEqual(len(url), 87)
        m = np.frombuffer(bytes(c.mu.mem_read(i['mat'], 37 * 37)), np.uint8).reshape(37, 37)
        self.assertEqual(set(np.unique(m)), {0, 255})
        got = decode_qr(np.pad(np.kron(m, np.ones((6, 6), np.uint8)), 24, constant_values=255))
        if got is None:
            self.skipTest('no OpenCV (set SLQS_CV_PYTHON): matrix not decoded = unverified')
        self.assertEqual(got, url)
        tx, ty = TILE_X(5), TILE_Y(5)
        s, side = i['scale'], i['side']
        inner_w, inner_h = 256 - 2 * 4 - 2, 223 - 2 * 5 - 2
        self.assertEqual((s, side), (min(inner_w, inner_h) // (37 + 4), (37 + 4) * s))
        self.assertLess(min(inner_w, inner_h), (37 + 4) * (s + 1))
        self.assertGreaterEqual(i['x0'], tx + 4); self.assertLessEqual(i['x0'] + side, tx + 256 - 4)
        self.assertGreaterEqual(i['y0'], ty + 5); self.assertLessEqual(i['y0'] + side, ty + 223 - 5)

    def test_observer_rejects_other_dimensions_and_untouched_hidden_buffers(self):
        """A descriptor for another layer must not be written; hidden QR must not paint a new buffer."""
        c = boot(qr_force=1)
        lcd = QRScreen(c)
        c.guid(QR_ID)
        press(c, 5, 5)
        info = qr_info(c)
        desc = lcd.DESC
        before = bytes(c.mu.mem_read(lcd.FB, 1024 * 682 * 2))
        def draw(d):
            return c.call(info['draw'] & ~1, r0=info['obs'], r1=d, r2=lcd.ARG,
                          thumb=bool(info['draw'] & 1))[0]
        self.assertEqual(draw(0), 0)
        for width, height in ((1023, 682), (1024, 681), (0, 0)):
            c.mu.mem_write(desc + 0x20, struct.pack('<2I', width, height))
            self.assertEqual(draw(desc), 0)
            self.assertEqual(bytes(c.mu.mem_read(lcd.FB, len(before))), before)
        c.mu.mem_write(desc + 0x20, struct.pack('<2I', 1024, 682))
        self.assertEqual(draw(desc), 1)
        c.put(0xC35A952C, 1)
        c.guid(QR_ID)
        self.assertEqual(qr_info(c)['on'], 0)
        fresh = bytes(c.mu.mem_read(lcd.FB + lcd.BUF, len(before)))
        self.assertEqual(draw(desc + 0x40), 0)
        self.assertEqual(bytes(c.mu.mem_read(lcd.FB + lcd.BUF, len(before))), fresh)

    def test_triple_buffer_and_present(self):
        """The live7 failure, modelled: the main layer's three rotating buffers; per cycle the GUI (UIC) repaints into the
        back buffer only what changed since that buffer last had it (per-buffer, no front -> back copy: UicDrawHandler
        +0x1C = 0), then every observer of group 2 in slot order, then the present -- only groups 2 / 3 present
        (FUN_c0528178); group 0's drawing goes to a buffer that never reaches the LCD.  Required: the code on the LCD
        while shown, and after a hide every presented frame = the GUI's own picture (no leftover in any buffer)."""
        import numpy as np
        c = boot(qr_force=0)
        lcd = QRScreen(c)
        c.guid(QR_ID)
        lcd.focus(5)
        # The QR is shown by opening QS, without AEL.
        i = qr_info(c)
        self.assertEqual((i['on'], i['reg'], i['group'], i['slot'], i['why']), (1, 1, 2, 1, 0))
        url = QR_URL + c.cstr(sqt(c, 13), 64)
        x0, y0, side = i['x0'], i['y0'], i['side']
        for _ in range(4):
            f = lcd.cycle()
            out = np.ones(f.shape, bool); out[y0:y0 + side, x0:x0 + side] = False
            self.assertTrue((f[out] == lcd.G[out]).all())         # nothing else touched
            sq = np.where(f[y0:y0 + side, x0:x0 + side] == 0xF000, 0, 255).astype(np.uint8)
            got = decode_qr(np.pad(sq, 20, constant_values=255))
            if got is not None:
                self.assertEqual(got, url)
            self.assertEqual(set(np.unique(f[y0:y0 + side, x0:x0 + side])), {0xF000, 0xFFFF})
        self.assertEqual(qr_info(c)['nbuf'], 3)
        lcd.hint(1)
        c.put(0xC35A952C, 1)                                      # recording: restore all three buffers
        c.guid(QR_ID)
        self.assertEqual(qr_info(c)['on'], 0)
        for k in range(5):
            f = lcd.cycle()
            self.assertTrue((f == lcd.G).all(), f'frame {k} after hide: {(f != lcd.G).sum()} px differ')
        i = qr_info(c)
        self.assertEqual((i['nbuf'], i['restores']), (0, 3))
        c.put(0xC35A952C, 0)
        c.guid(QR_ID)                                             # shown again; focus may move freely
        lcd.cycle(); lcd.cycle()
        self.assertTrue((lcd.cycle()[y0:y0 + side, x0:x0 + side] != lcd.G[y0:y0 + side, x0:x0 + side]).any())
        lcd.focus(4)                                              # the GUI repaints both tiles (box, darker inside)
        c.guid(RCP_ID)
        self.assertEqual(qr_info(c)['on'], 1)
        press(c, 5, 4)                                            # entering a sub-QS hides it
        self.assertEqual(qr_info(c)['on'], 0)
        for k in range(5):
            f = lcd.cycle()
            self.assertTrue((f == lcd.G).all(), f'frame {k} after the focus moved: {(f != lcd.G).sum()} px differ')
        c.layout()
        c.put(UIC_DRAW_OBJ + 8, 0)                                 # native QS v11 leaves
        for _ in range(3):
            self.assertTrue((lcd.cycle() == lcd.G).all())

    def test_refused_without_a_free_slot_after_the_gui(self):
        c = boot(qr_force=0)
        lcd = QRScreen(c)
        for k in range(3):
            c.put(QRScreen.CTRL + 12 * 2 + 4 * k, [UIC_DRAW_OBJ, 0x1000, 0x1004][k])
        c.put(QRScreen.CTRL + 0x48 + 8, 3)
        c.guid(QR_ID)
        press(c, 5, 5)
        self.assertEqual((qr_info(c)['on'], qr_info(c)['why']), (0, 5))   # never FUN_c0528300's assert
        del lcd

    def test_locked_while_recording(self):
        c = boot(qr_force=1)
        c.put(0xC35A952C, 1)
        c.guid(QR_ID)
        press(c, 5, 5)
        self.assertEqual(qr_info(c)['on'], 0)
        self.assertEqual(TP.texts(c)['QSC_G6'], 1)               # greyed
        self.assertEqual((qr_info(c)['on'], qr_info(c)['why']), (0, 1))
        c.put(0xC35A952C, 0)
        c.guid(FMT_ID)
        self.assertEqual(qr_info(c)['on'], 1)

    def test_mbps_footer_short(self):
        """live6: item 1 overflowed its box; now "UHS-II" / "91%/42%" (and "—" when lossless refuses)"""
        c = boot()
        c.guid(MB_ID)
        f = footer(c, MB_ID)
        self.assertEqual(f['items'][0][0], 'UHS-II')
        self.assertRegex(f['items'][0][1], r'^\d+%/(\d+%|—)$')
        self.assertLessEqual(len(f['items'][0][1]), 9)


@SKIP
class CpuX2(unittest.TestCase):
    """v0.7.38test (notes/CPU_X2_DESIGN.md "UI"): the CPU x2 option on the camera itself -- the footer, the recorded
    bits, MB/s at the half width, the apply selection, the record and the QR payload round trip."""

    @classmethod
    def setUpClass(cls):
        cls.states = page_states(SEQS)[20]['states']

    def at(self, n):
        """the camera after the first n keys of seq 20"""
        c = boot()
        self.assertEqual(drive(c, CPU2_KEYS[:n], self.states[:n + 1], check=False), [])
        return c

    def test_footer_grey_then_chosen(self):
        c = self.at(5)                                            # HD 3K 12b 2x2, ISP HBIN focused
        it = footer(c, focus_int(c, 6))['items']
        self.assertEqual(len(it), 14)
        self.assertEqual(it[13], (CPU2, '\u2192S.HBIN1', False, False, False, True))
        self.assertEqual(len(footer(c, focus_int(c, 7))['items']), 13)
        c = self.at(10)                                           # SENSOR HBIN 1, then f+: CPU x2
        f = footer(c, focus_int(c, 6))
        self.assertEqual((f['cur'], f['items'][13]), (13, (CPU2, '', False, False, False, False)))
        self.assertEqual(tile(c, 6)[1:3], (CPU2, 'RWZM off \u00b7 \u21923024'))
        self.assertEqual(ap_sel(c)['hbin'], 2)

    def test_14bit_mbps_record_and_qr(self):
        n = CPU2_KEYS.index('ael', 30)                            # 14b CPU x2 at 25 fps, back on the main QS
        c = self.at(n + 1)
        self.assertEqual(tile(c, 0)[2], '14bit')                  # D11 (4): true 14 (the record skips RWZM)
        self.assertTrue(tile(c, 4)[2].startswith('14b 1x2 CPU\u00d72 \u00b7 RS'), tile(c, 4))
        self.assertEqual(tile(c, 6)[1], str(round(25 * (3024 * 1700 * 14 // 8 + 79184) / 1e6)))   # the half width, 14 bit
        self.assertEqual(tile(c, 6)[1], '227')
        code = c.cstr(sqt(c, 13), 64)
        f, ok = qr_unpack(code)
        self.assertTrue(ok)
        self.assertEqual((f['hbin'], f['vbin'], f['mh'], f['mv'], f['ad'], f['rw'], f['rh'], f['rcustom']),
                         (2, 1, 1, 2, 2, 3024, 1700, 1))
        want = [tile(c, k) for k in range(7)]
        c.layout()                                                # leave(): the record
        d = boot(card=c.written[PATH])
        self.assertEqual([tile(d, k) for k in range(7)], want)
        self.assertEqual(c.cstr(sqt(d, 13), 64), code)
        e = boot()                                                # the payload restores it exactly (qr_restore keep 1)
        buf = F6.FAKE + 0x9400
        e.mu.mem_write(buf, struct.pack(f'<{len(QR_FIELDS)}I', *[f[k] for k, _w in QR_FIELDS]))
        self.assertEqual(sqt(e, 41, buf, 1), 1)
        e.layout()
        self.assertEqual(c.cstr(sqt(e, 13), 64), code)
        self.assertEqual(tile(e, 0)[2], '14bit')


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
    ('apply: the dial does not reach ap_request', '    if (!busy()) sq_push(st);\n    return r;', '    (void)st;\n    return r;'),
    ('apply: leave() does not flush', '    sq_push(st);                                      /* v0.5.0test: leave() flushes', '    sq_apply(st);                                      /* v0.5.0test: leave() flushes'),
    ('apply: not armed at entry', '    st->ap_init_rc = ap_init(st->ap_mem, sizeof st->ap_mem, svc);', '    st->ap_init_rc = 0;'),
    ('apply: the sel misses the VMAX step', 'a->hm = c->hm; a->vmax = st->applied.vmax;', 'a->hm = c->hm; a->vmax = st->applied.vmax + 1u;'),
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
    # v0.7.0test: the FPS sub-QS
    ('v0.7: FINE not left on blur', '    if (st->s.fine) { fine_exit(st); st->dirty = 1; if (!busy()) sq_push(st); }   /* the tuned value lands',
     '    if (0) { fine_exit(st); st->dirty = 1; if (!busy()) sq_push(st); }   /* the tuned value lands'),
    ('v0.7: no blur registered', '            b->blur = fi == F_FPS ? sq_fine_blur : 0;', '            b->blur = 0; (void)sq_fine_blur;'),
    ('v0.7: FINE step is a list step', '        if (j == 1u && !s->fine) { s->fine = 1; s->fc_d = 0; }', '        if (j == 9u && !s->fine) { s->fine = 1; s->fc_d = 0; }'),
    ('v0.7: FINE footer is the list', '        if (j == 1u) {                                /* FINE: the K-style spinner', '        if (j == 9u) {                                /* FINE: the K-style spinner'),
    # equivalent, not listed: 'fine keeps the old tuned rate' -- fineExit always rewrites the tuned rate and the
    # fine-mode footer is the spinner, so the dropped rate is never visible
    ('no switch-point marks', '    for (u32 j = 0; j < n; j++) st->fl_e[j].mark = (u8)qmark(st, st->fl_e[j].f);', ''),
    ('recipe choice forgotten when fps is too high', 'if (rq_of(&c->r[i]) == st->s.rq && usable(st, &c->r[i])) return &c->r[i];',
     'if (usable(st, &c->r[i])) { st->s.rq = rq_of(&c->r[i]); return &c->r[i]; }'),
    ('ISP bins in the preset list', 'static int is_preset(const struct rcp *q) { return q->hb == 1 && q->vb == 1; }',
     'static int is_preset(const struct rcp *q) { (void)q; return 1; }'),
    ('a choice changes the others', '            if (k != key && k != K_SCW && k != K_SCH && pval(q, k) != pval(c, k)) ok = 0;', ''),
    ('no greyed reason', '                if (!ok_v(st, key, v)) { why_not(st, st->fs[i], key, v); o->small[i] = st->fs[i]; o->grey |= 1u << i; }',
     '                if (!ok_v(st, key, v)) { o->grey |= 1u << i; }'),
    ('3x1 offered', '    if (key == K_MH || key == K_MV) {', '    if (0) {'),
    ('kernel dial leaves the mode', 'int ki0 = 1 + 6 * (int)s->km + (int)*kk;', 'int ki0 = 1;'),   # v0.7.38test: pattern updated
    ('visible = nominal always', '    if (c) { *w = c->vis_w; *h = c->vis_h;', '    if (0) { *w = c->vis_w; *h = c->vis_h;'),
    ('FORMAT 14bit for 11/12', 'put_s(d, 0, TXT, rec_bits(c) == 14u ? "14bit" : "12bit");', 'put_s(d, 0, TXT, "12bit");'),
    ('FORMAT by AD, not the recorded bits', 'put_s(d, 0, TXT, rec_bits(c) == 14u ? "14bit" : "12bit");', 'put_s(d, 0, TXT, c->ad == 14u ? "14bit" : "12bit");'),
    ('rec_bits ignores the zoom', 'return q->ad == 14u && q->zh == 1024u && q->zv == 1024u && (q->hb', 'return q->ad == 14u && (q->hb'),   # D11 (4): pattern updated
    # v0.7.38test: CPU x2 (ISP HBIN option 13, hbin 2)
    ('CPU x2: rec_bits 12 for hbin 2 (D11 (4): a 14-bit AD records true 14)', 'q->zv == 1024u && (q->hb == 1u || q->hb == 2u) && q->vb == 1u ? 14u : 12u;', 'q->zv == 1024u && q->hb == 1u && q->vb == 1u ? 14u : 12u;'),
    ('CPU x2: option not offered', 'static u32 isp_nopt(u32 key) { return key == K_HB ? 14u : 13u; }', 'static u32 isp_nopt(u32 key) { (void)key; return 13u; }'),
    ('CPU x2: offered on ISP VBIN too', 'static u32 isp_nopt(u32 key) { return key == K_HB ? 14u : 13u; }', 'static u32 isp_nopt(u32 key) { (void)key; return 14u; }'),
    ('CPU x2: dial does not step over absent kernels', '            if (key == K_HB && b != 3u && jj >= 1 && jj <= 12 && !ok_v(st, key, 3u)) jj',
     '            if (0) jj'),
    ('CPU x2: not the current option', 'b == 2u ? ISP_OPT_CPU2 : 0;', '0;'),
    ('CPU x2: small line full width', 'put_u(d, n, TXT, c->rec_w);', 'put_u(d, n, TXT, c->win_w);'),
    ('CPU x2: RECIPE line ISP 2x1', '            if (c->hb == 2u) n = put_s(d, n, TXT, " " CPU2_SHORT);', '            if (0) n = put_s(d, n, TXT, " " CPU2_SHORT);'),
    # equivalent today, not listed: 'CPU x2: reason I.HBIN2' (short_name of hbin 2) -- every hbin-2 recipe has an hbin-1
    # twin with the same AD / sensor merge, so no greyed option's nearest recipe needs CPU x2 ("->CPUx2" never shows)
    ('CPU x2: value 1', 'put_s(d, 0, TXT, b == 2u ? CPU2_LABEL : "1");', 'put_s(d, 0, TXT, "1");'),
    ('CPU x2: footer label 1', 'put_s(st->fl[i], 0, FT, b == 2u ? CPU2_LABEL : "1");', 'put_s(st->fl[i], 0, FT, "1");'),
    ('CPU x2: picking it sets a kernel', '            if (jj && jj < ISP_OPT_CPU2) {', '            if (jj) {'),
    ('CPU x2: label x not U+00D7', '#define CPU2_LABEL "CPU \\xC3\\x97" "2"', '#define CPU2_LABEL "CPU x2"'),
    ('defaultPick by AD', 'if (rec_bits(a) != rec_bits(b)) return rec_bits(a) > rec_bits(b);', 'if (a->ad != b->ad) return a->ad > b->ad;'),
    ('MB/s by AD', 'b = rec_bits(c);', 'b = c->ad <= 12u ? 12u : 14u;'),
    ('no native width mark', 'if (f == F_DC && j == 1u) o->mark = native_w(st->s.dcw);', 'if (f == F_DC && j == 9u) o->mark = native_w(st->s.dcw);'),
    ('native widths off by one entry', 'static const u16 NATIVE_W[4] = {6048, 5040, 4144, 3984};', 'static const u16 NATIVE_W[4] = {6048, 5040, 4144, 4000};'),
    ('RS two decimals', 'n = put_fix(d, n, TXT, (u64)js_fixed_d(dratio(c->rs_us, 1000), 1), 1);\n        put_s(d, n, TXT, " ms");',
     'n = put_fix(d, n, TXT, (u64)js_fixed_d(dratio(c->rs_us, 1000), 2), 2);\n        put_s(d, n, TXT, " ms");'),
    # v0.7.38test (Bei 11-05): the merge hint from the effective recipe, one function for the RES tile and its sub-items
    ('hint: geometric with a recipe', '    if (c) { e->w = c->vis_w + 16u; e->h = c->vis_h + 10u; recipe_hint(c, e->hint); }',
     '    if (c) { e->w = c->vis_w + 16u; e->h = c->vis_h + 10u; div_text(e->hint, st->s.dcw, st->s.dch, e->w, e->h); }'),
    ('hint: RWZM never shown', 'static int z_unity(u32 z) { return 500u * (z > 1024u ? z - 1024u : 1024u - z) <= 1024u; }',
     'static int z_unity(u32 z) { (void)z; return 1; }'),
    ('hint: RWZM 1025 not unity', 'static int z_unity(u32 z) { return 500u * (z > 1024u ? z - 1024u : 1024u - z) <= 1024u; }',
     'static int z_unity(u32 z) { return z == 1024u; }'),
    ('hint: ISP bin not counted', 'u32 n = put_u(d, 0, 8, (u32)c->mh * c->hb);', 'u32 n = put_u(d, 0, 8, (u32)c->mh);'),
    ('hint: ISP vbin not counted', 'put_u(d, n, 8, (u32)c->mv * c->vb);', 'put_u(d, n, 8, (u32)c->mv);'),
    ('hint: sub-items by geometry', '            if (e.hint[0]) { if (n) n = put_s(d, n, TXT, " \\xC2\\xB7 "); put_s(d, n, TXT, e.hint); }',
     '            div_text(e.hint, st->s.dcw, st->s.dch, e.w, e.h);\n            if (e.hint[0]) { if (n) n = put_s(d, n, TXT, " \\xC2\\xB7 "); put_s(d, n, TXT, e.hint); }'),
    ('RECIPE line not yellow when short', '        put_s(d, n, TXT, " ms");\n        if (e.shr) *flags |= QSC_T_APPROX;',
     '        put_s(d, n, TXT, " ms");'),
    # equivalent, not listed (Exact proves both equal over their whole domain): mm by the rational px x 359 / 60480,
    # |p.w/p.h - asp| < 0.002 by rationals
    ('kLabel truncates', '        u32 x2 = (w + 256u) >> 9;', '        u32 x2 = w >> 9;'),
    ('Math.round half down', 'static int round_to(dbl x, int k) { x.e -= k == 2 ? 1 : 4; return (int)js_fixed_d(x, 0) * k; }',
     'static int round_to(dbl x, int k) { x.e -= k == 2 ? 1 : 4; return (int)dfloor(x) * k; }'),
    ('runner: the yellow flag lost', 'approx: !!approx, lock:', 'approx: false, lock:', 'preview_runner.js'),
    ('record written per dial step', '    st->dirty = 1;\n}\nstatic void set_dc(', '    st->dirty = 1;\n    rec_write(st);\n}\nstatic void set_dc('),
    ('writes without the self check', '    if (!path || svc->file_is(svc, path, st->block, SL4_HEADER_LEN) != SL_OK) { st->write_why = 2; st->write_fails++; return; }',
     '    if (!path) return;'),
    ('not locked while recording', '        f->flags = QSC_F_CINE | QSC_F_LOCK_REC |', '        f->flags = QSC_F_CINE |'),
    ('record not checked', '    for (u32 i = 0; i < REC_WORDS; i++) if (chk[i] != r[i]) return 0;', ''),
    ('fps footer not windowed', 'static u32 window(u32 n, int cur, u32 *lo)\n{\n    *lo = 0;\n    if (n <= N_LIST) return n;',
     'static u32 window(u32 n, int cur, u32 *lo)\n{\n    *lo = 0;\n    if (n <= N_LIST || 1) return n > N_LIST ? N_LIST : n;'),
    ('apply: VMAX rounded down (a rate above the selection)', 'v = udiv64(num + den - 1u, den, 0);', 'v = udiv64(num, den, 0);'),
    ('no leave() registered', '    st->t.leave = sq_leave;', '    st->t.leave = 0;'),
    ('v0.2.1test: RES footer keeps the ratio line', '        for (u32 i = 0; i < n; i++) o->label[i] = st->list[lo + i].lab;   /* v0.2.1test: label only, the ratio stays on the tile */',
     '        for (u32 i = 0; i < n; i++) { o->label[i] = st->list[lo + i].lab; o->small[i] = st->list[lo + i].div[0] ? st->list[lo + i].div : 0; }'),
    ('v0.2.1test: switch point as U+2022', '        if (qmark(st, fr)) n = put_s(d, 0, TXT, "\\xC2\\xB7 ");', '        if (qmark(st, fr)) n = put_s(d, 0, TXT, "\\xE2\\x80\\xA2 ");'),
    ('v0.2.1test: switch point unmarked', '        if (qmark(st, fr)) n = put_s(d, 0, TXT, "\\xC2\\xB7 ");', ''),
    ('v0.2.1test: RECIPE without a text title', '(fi == F_RECIPE || fi == F_MBPS || fi == F_QR ? QSC_F_TITLE : 0u);',
     '(fi == F_MBPS || fi == F_QR ? QSC_F_TITLE : 0u);'),   # 10-30: pattern follows the v0.4 MB/s / QR titles
    # v0.2.2test (RECIPE round)
    ('v0.2.2test: a recipe lowers the FPS again', '    if (!usable(st, q)) return;                       /* v0.2.2test',
     '    if (0) return;                       /* v0.2.2test'),
    ('v0.2.2test: ok() ignores the FPS', '    return n && usable(st, n);', '    return n != 0;'),
    # 10-30, equivalent, dropped: 'dial lands on a value that cannot reach the FPS' (!ok_v -> !combo in the dial's skip
    # loop).  It differs only when the next value's combination exists but misses the FPS while a value further on
    # reaches it; over every preset cell, 1014 custom DC x RES cells, every switch-point rate and every usable recipe, no
    # dial (ADC, S.HBIN, S.VBIN, crops) has such a gap: one step slower is never followed by a faster one.
    ('v0.2.2test: no "max N" reason', '    if (cb && !usable(st, cb)) {', '    if (0) {'),
    ('v0.2.2test: "max" with one decimal', 'n = put_fix(d, n, FT, (u64)js_fixed_d(dratio(CD_CLK, (u32)cb->hm * cb->lo), 2), 2);',
     'n = put_fix(d, n, FT, (u64)js_fixed_d(dratio(CD_CLK, (u32)cb->hm * cb->lo), 1), 1);'),
    ('v0.2.2test: footer RS two decimals', 'm = put_fix(st->fs[t], 0, FT, (u64)js_fixed_d(dratio(q->rs_us, 1000), 1), 1);',
     'm = put_fix(st->fs[t], 0, FT, (u64)js_fixed_d(dratio(q->rs_us, 1000), 2), 2);'),
    ('v0.2.2test: footer RS with a space', '                m = put_s(st->fs[t], m, FT, "ms");', '                m = put_s(st->fs[t], m, FT, " ms");'),
    ('v0.2.2test: footer H with the dot', 'm = put_s(st->fs[t], m, FT, " H");', 'm = put_s(st->fs[t], m, FT, " \\xC2\\xB7 H");'),
    ('v0.2.2test: long reason names', '"S.HBIN" : k == K_MV ? "S.VBIN"', '"SENSOR H" : k == K_MV ? "S.VBIN"'),
    ('v0.2.2test: ISP reason name', 'k == K_HB ? "I.HBIN" : "I.VBIN"', 'k == K_HB ? "ISP H" : "I.VBIN"'),
    ('v0.2.2test: "needs" prefix', '    n = put_s(d, 0, FT, "\\xE2\\x86\\x92");', '    n = put_s(d, 0, FT, "needs ");'),
    ('v0.2.2test: space after the arrow', '        if (!first) n = put_s(d, n, FT, " ");', '        n = put_s(d, n, FT, " "); (void)first;'),
    ('v0.2.2test: ISP value without the kernel', 'if (b == 3u) { n = put_s(d, 0, TXT, "3["); n = put_s(d, n, TXT, KERN[kk]); put_s(d, n, TXT, "]"); }',
     'if (b == 3u) { n = put_s(d, 0, TXT, "3"); (void)kk; (void)n; }'),
    ('v0.2.2test: ISP footer label without the kernel', 'm = put_s(st->fl[i], 0, FT, "3["); m = put_s(st->fl[i], m, FT, KERN[ki]); put_s(st->fl[i], m, FT, "]");',
     'put_s(st->fl[i], 0, FT, "3"); (void)ki;'),
    ('v0.2.2test: ISP small keeps the kernel', 'if (b == 3u) { n = put_s(d, 0, TXT, MODE[st->s.km]); n = put_s(d, n, TXT, " \\xC2\\xB7 "); }',
     'if (b == 3u) { n = put_s(d, 0, TXT, KERN[kk]); n = put_s(d, n, TXT, " \\xC2\\xB7 "); }'),
    ('v0.2.2test: ISP reason with the dot', 'if (i) m = put_s(st->fs[i], m, FT, " "); put_s(st->fs[i], m, FT, wn);',
     'if (i) m = put_s(st->fs[i], m, FT, " \\xC2\\xB7 "); put_s(st->fs[i], m, FT, wn);'),
    ('v0.2.2test: crop small line still the readout', 'key == K_SCW ? (iw < c->scw ? iw : c->scw) : (ih < c->sch ? ih : c->sch)); }',
     'key == K_SCW ? c->sw : c->sh); (void)iw; (void)ih; }'),
    ('v0.2.2test: crop value without S', 'key == K_SCW || key == K_SCH ? "S " : ""', '""'),
    ('v0.2.2test: old crop titles', '"DC WIDTH", "DC HEIGHT",', '"SENSOR HDC", "SENSOR VDC",'),
    # v0.4.0test (QR, MB/s footer)
    ('QR: RS generator on the wrong root', '        root = gf_mul(root, 2);', '        root = gf_mul(root, 3);'),
    ('QR: format bits without the xor mask', '    u32 b = (data << 10 | rem) ^ 0x5412u;', '    u32 b = (data << 10 | rem);'),
    ('QR: quiet zone 1 module', '#define QR_QZ       2u', '#define QR_QZ       1u'),
    ('QR: CRC poly 0x31', '        if (top) crc ^= 0x07u;', '        if (top) crc ^= 0x31u;'),
    ('QR: RES custom bit inverted', 'f[i++] = res_hit(st, rw, rh) < 0;', 'f[i++] = res_hit(st, rw, rh) >= 0;'),
    ('QR: ISP window fields swapped', 'f[i++] = c->win_w; f[i++] = c->win_h;', 'f[i++] = c->win_h; f[i++] = c->win_w;'),
    ('QR: auto display omitted', '        if (qs && W(qs + 0xBCu) < QS_SUB_ID0) qr_show(st);', ''),
    ('QR: draws on any layer', ' || W(dims) != OSD_W || W(dims + 4u) != OSD_H || !q->side) return 0;', ' || !q->side) return 0;'),
    ('QR: a full group registered anyway', '        if (W(DRAW_COUNT + 4u * g) >= 3u) return 5;', ''),
    # v0.4.1test: the live7 failure and its fix
    ('QR: group 0 again (the first 16-bpp layer, live7)', 'for (u32 k = 0; k < 3u; k++) if (W(DRAW_CTRL + 12u * g + 4u * k) == UIC_DRAW) gs = k;', 'gs = 0;'),
    ('QR: no restore at hide (live7: the code stays in the buffers)', '    qr_square(q, base, i, 1);', '    return 0;'),
    ('QR: only the presented buffer restored', '    q->buf[i] = q->buf[--q->nbuf];', '    q->nbuf = 0; (void)i;'),
    ('QR: the shadow never learns', '            if (!q->have_sh || dirty < 0 || b != was) sh[x] = b;', '            (void)dirty; if (!q->have_sh) sh[x] = b;'),
    ('defaultPick: R[0] again', '        if (!st->s.rd_ok) { if (!best || dpick_before(st, q, best, rw, rh)) best = q; continue; }',
     '        if (!st->s.rd_ok) { (void)rw; (void)rh; return q; }'),
    # 10-30, equivalent, dropped: 'defaultPick: horizontal before AD' (the recorded-bits step removed).  Only a true
    # 14-bit recipe (1x1, no zoom: RES = DC) records 14; at the same vertical merge its 12 / 11-bit rival has the same
    # horizontal distance and a shorter RS, so the RS step picks the same recipe (no preset or 294 custom cells at any
    # switch-point rate differ).  'defaultPick by AD' still exercises the bits step.
    ('defaultPick: RS ascending', '    return a->rs_us > b->rs_us;', '    return a->rs_us < b->rs_us;'),
    ('cur_recipe memo ignores the rate', 'st->cur->used_n, s->fps_n, s->fps_d,', 'st->cur->used_n, 0, 0,'),
    ('QR: shown while recording', '    if (busy()) { q->on = 0; q->why = 1; return 0; }', ''),
    ('MB/s: lossless refusal ignored', '    o->ll_no = fc > LL_MAX_FRAME;', '    o->ll_no = 0;'),
    ('MB/s: long footer label', '*name = "UHS-II";', '*name = "SD UHS-II";'),
    ('preview: QR code dropped from the runner', "qr: qrVisible(), qrcode: qrCode() || '',", "qr: qrVisible(), qrcode: '',", 'preview_runner.js'),
    ('v0.2.2test: ISP option ok ignores the FPS', 'u32 b = OPTS_B[i], ok = (u32)ok_v(st, key, b), m = 0;', 'u32 b = OPTS_B[i], ok = combo(st, key, b) != 0, m = 0;'),
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
        if env.get('SL_TESTCACHE', '1') != '0':
            env['SL_TESTCACHE'] = 'ro'                  # a mutant's build is a one-off: read the cache, never write it
        with tempfile.TemporaryDirectory(prefix='slqs-mut-') as t:
            env['PYTHONPYCACHEPREFIX'] = t              # an empty bytecode cache: no stale .pyc (same-size rewrites)
            if where and where[0] == 'preview_runner.js':
                p = HERE / f'.mut_runner_{os.getpid()}_{i}.js'
                p.write_text(rsrc.replace(old, new))
                env['SLQS_RUNNER'] = str(p)
            elif where:                                     # next to the original: its paths are relative to it
                p = HERE / f'.mut_build_slqs_{os.getpid()}_{i}.py'
                p.write_text(bsrc.replace(old, new))
                env['SLQS_BUILD_SRC'] = str(p)
            else:                                           # next to the original: it #includes qrdec.c (v0.7.38test)
                p = HERE / f'.mut_slqs_{os.getpid()}_{i}.c'
                p.write_text(src.replace(old, new))
                env['SLQS_SRC'] = str(p)
                try:                                        # a mutant must build: a compile error is no catch
                    BS.compile_text(p)
                except BS.BuildError as e:
                    print(f'  BAD MUTANT (does not build): {label}: {str(e)[:300]}', flush=True)
                    survived.append(label)
                    p.unlink()
                    continue
            try:
                r = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-q',
                                    *(['-f'] if os.environ.get('SL_MUT_FAILFAST') else []), 'test_slqs'],
                                   cwd=HERE, env=env, capture_output=True, text=True)
            finally:
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
