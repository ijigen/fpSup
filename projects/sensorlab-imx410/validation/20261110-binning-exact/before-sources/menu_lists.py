#!/usr/bin/env python3
"""SensorLab-IMX410 stock-menu rows: the lists, the CSV text, the summary text, and what a picked row does.

The reference for the menu side (notes/MENU_DESIGN.md).  On the camera the rows are written by slqs.c from its own
lists (res_list / fps_list / DCN, the same functions the QS footers use); this module is the host's copy of those
rules, required by test_menu.py to equal the spec page (preview/dcres.html, run in node by page_lists.js) row for
row, so the camera's CSV can later be compared with it byte for byte.

    python3 -B menu_lists.py OG 6048 4040 --res 3008x2010 --fps 29.97      # rows + CSV for one state

State (a dict, the page's S less the UI): dcW, dcH, res {w,h} (a custom RES) | resK (a fixed-K label) | resRatio,
fps, fpsCustom (the one tuned rate, or None), fine.  `bit` is the stock MV_DNGQuality row (0 8-bit, 1 10-bit,
2 12-bit): the bit-depth row stays on the stock setting.
"""
import argparse
import decimal
import json
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
FPS_DATA = HERE.parent / 'preview' / 'fps_data.js'

WMAX, HMAX, WMIN, HMIN = 6048, 4040, 256, 144
DCS = [('OG', 6048, 4040), ('HD', 6048, 3402), ('S35', 4192, 2358), ('APS-C', 3952, 2624), ('S16', 2096, 1240),
       ('SQ', 4032, 4032)]
RATIOS = [1, 2 / 3, 1 / 2, 1 / 3, 1 / 6]
KS = [1, 2, 3, 3.5, 4, 5, 6]
STD = [23.976, 24, 25, 29.97, 30, 47.952, 48, 50, 59.94, 60, 72, 90, 96, 100, 119.88, 120, 144, 150, 180, 200,
       239.76, 240, 300, 360, 400, 480, 500, 600, 1000]
CUSTOM = 'CUSTOM'
BIT_ROWS = (('8 bit', True), ('10 bit', True), ('RAW bit', True))   # v1 greyed 8 / 10 (Bei 10-29); 0.0.3test: selectable
# (Bei 11-08: 8 / 10-bit CinemaDNG -- the stock setting stays the source of truth, the picker answers TAB1 / TAB2)
BIT_SUMMARY = ('8 bit', '10 bit', 'RAW')
# list capacities the page edits are built for (cursor pairs, caps, CSV room): test_menu pins that no state needs more
CAP = {'DC': 7, 'RES': 10, 'FPS': 50, 'BIT': 3}
CSV_HEADER = 'NO,TEXT,Popup,IMAGE,Enabled,Enabled2'


# ---- the page's geometry (dcres.html, JavaScript doubles = Python floats) ------------------------------------
def a16(w):
    return math.floor(w / 16) * 16


def ev(h):
    return math.floor(h / 2) * 2


def js_round(x):
    return math.floor(x + 0.5)


def js_num(x):
    """String(x) for the numbers the page prints"""
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def to_fixed(x, n):
    """Number.prototype.toFixed: the exact value of the double, ties to the larger"""
    q = decimal.Decimal(1).scaleb(-n)
    return str(decimal.Decimal(x).quantize(q, rounding=decimal.ROUND_HALF_UP))


def k_label(w):
    x = w / 1024
    return (to_fixed(js_round(x * 10) / 10, 1) if x < 0.75 else js_num(js_round(x * 2) / 2)) + 'K'


def dc_name(W, H):
    return next((n for n, w, h in DCS if (w, h) == (W, H)), 'Custom')


def div_text(W, H, w, h):
    ks = [1, 2, 3, 4, 5, 6, 8, 12]
    n = next((k for k in ks if a16(W / k) == w), None)
    m = next((k for k in ks if ev(H / k) == h), None)
    return f"{n or ''}x{m or ''}" if n or m else ''


def res_list(W, H):
    """resList: clean ratios + 1K..6K (+ FHD / UHD on HD), one per W x H, by width"""
    items = []
    for r in RATIOS:
        w = a16(W * r)
        h = ev(H * r) if float(1 / r).is_integer() else ev(w * H / W)
        if w >= WMIN and h >= HMIN:
            items.append(dict(w=w, h=h, ratio=True, label=k_label(w)))
    for K in KS:
        w = a16(K * 1024)
        if w > W or ev(w * H / W) < HMIN:
            continue
        if any(i['ratio'] and i['label'] == js_num(K) + 'K' for i in items):
            continue
        items.append(dict(w=w, h=ev(w * H / W), ratio=False, label=js_num(K) + 'K'))
    if dc_name(W, H) == 'HD':
        items += [dict(w=3840, h=2160, ratio=False, label='UHD'), dict(w=1920, h=1080, ratio=False, label='FHD')]
    seen, out = set(), []
    for i in items:
        if (i['w'], i['h']) not in seen:
            seen.add((i['w'], i['h']))
            out.append(i)
    return sorted(out, key=lambda i: i['w'])          # stable, as Array.prototype.sort


def res_of(s):
    """res(): the RES the state selects"""
    if s.get('res'):
        return s['res']['w'], s['res']['h']
    W, H = s['dcW'], s['dcH']
    if s.get('resK'):
        it = next((i for i in res_list(W, H) if i['label'] == s['resK']), None)
        if it:
            return it['w'], it['h']
    r = s.get('resRatio', 1 / 3)
    if a16(W * r) < WMIN or ev(H * r) < HMIN:
        r = 1
    w = a16(W * r)
    return w, (ev(H * r) if float(to_fixed(1 / r, 6)).is_integer() else ev(w * H / W))


# ---- FPS (FPSDATA = preview/fps_data.js, preset DC x RES only; the camera computes the rest) -------------------
_DATA = None


def fps_data(path=FPS_DATA):
    global _DATA
    if _DATA is None:
        t = pathlib.Path(path).read_text()
        t = t[t.index('const FPSDATA = ') + len('const FPSDATA = '):].rstrip().rstrip(';')
        _DATA = json.loads(t)
    return _DATA


def same(a, b):
    return abs(a - b) < 5e-4


def quals(s, data=None):
    data = data or fps_data()
    W, H = s['dcW'], s['dcH']
    w, h = res_of(s)
    c = data['cases'].get(f'{dc_name(W, H)}:{w}x{h}')
    if not isinstance(c, list):
        return None
    return [dict(hm=hm, lo=lo, max=data['clk'] / (hm * lo)) for hm, lo, _q, d in c if d['hbin'] == 1 and d['vbin'] == 1]


def fps_list(s, data=None):
    """fpsList: every common rate (above the max = grey) + each recipe's max (marked) + the one tuned rate"""
    Q = quals(s, data)
    if not Q:
        return []
    M = min(1000, max(q['max'] for q in Q))
    out = [dict(f=f, std=True, na=f > M + 5e-4, custom=False) for f in STD]
    for q in Q:
        if q['max'] <= 1000 and not any(same(o['f'], q['max']) for o in out):
            out.append(dict(f=q['max'], std=False, na=False, custom=False))
    for o in out:
        o['mark'] = any(same(q['max'], o['f']) for q in Q)
    fc = s.get('fpsCustom')
    if fc and fc <= M + 5e-4 and not any(same(o['f'], fc) for o in out):
        out.append(dict(f=fc, std=False, na=False, custom=True, mark=any(same(q['max'], fc) for q in Q)))
    return sorted(out, key=lambda o: o['f'])


def fmt_f(o):
    return js_num(o['f']) if o['std'] else to_fixed(o['f'], 3)


def fps_value(s, data=None):
    """FPS.v(): the QS tile's value, and the menu row's summary"""
    if not quals(s, data):
        return '—'
    o = next((o for o in fps_list(s, data) if same(o['f'], s['fps'])), None)
    return to_fixed(s['fps'], 3) if s.get('fine') or not o else fmt_f(o)


# ---- the four menu rows ------------------------------------------------------------------------------------------
def dc_rows(s):
    """[(text, selectable)], current row, summary, actions"""
    i = next((k for k, (n, w, h) in enumerate(DCS) if (w, h) == (s['dcW'], s['dcH'])), -1)
    rows = [(n, True) for n, _w, _h in DCS]
    acts = [dict(op='set_dc', w=w, h=h) for _n, w, h in DCS]
    rows.append((CUSTOM, True))
    acts.append(dict(op='open', sub='DC'))
    return rows, (i if i >= 0 else len(rows) - 1), (DCS[i][0] if i >= 0 else CUSTOM), acts


def res_rows(s):
    L = res_list(s['dcW'], s['dcH'])
    r = res_of(s)
    i = next((k for k, it in enumerate(L) if (it['w'], it['h']) == r), -1)
    rows = [(it['label'], True) for it in L]
    acts = [dict(op='set_res', w=it['w'], h=it['h']) for it in L]
    rows.append((CUSTOM, True))
    acts.append(dict(op='open', sub='RES'))
    return rows, (i if i >= 0 else len(rows) - 1), (L[i]['label'] if i >= 0 else CUSTOM), acts


def fps_rows(s, mode='qs', data=None):
    """mode 'qs': the QS footer's list (Bei 10-29 「和 QS FPS 同一份清單」); 'std': the 29 common rates plus the current
    rate when it is not one of them (a recipe's max) and the tuned one -- the shorter list asked about in §9."""
    L = fps_list(s, data)
    if not L:
        return [('Unavailable', False), (CUSTOM, False)], 0, fps_value(s, data), [dict(op='none'), dict(op='none')]
    if mode == 'qs' and len(L) + (not any(o['custom'] for o in L)) > CAP['FPS']:
        mode = 'std'                                  # more recipe maxima than the page edit has rows for
    if mode == 'std':
        L = [o for o in L if o['std'] or o['custom'] or same(o['f'], s['fps'])]
    rows, acts = [], []
    for o in L:
        if o['custom']:
            rows.append((f"{CUSTOM} {to_fixed(o['f'], 3)}", True))
            acts.append(dict(op='open', sub='FPS', fps=o['f']))
        else:
            rows.append((fmt_f(o), not o['na']))
            acts.append(dict(op='set_fps', fps=o['f']) if not o['na'] else dict(op='none'))
    cur = next((k for k, o in enumerate(L) if same(o['f'], s['fps'])), -1)
    if not any(o['custom'] for o in L):
        rows.append((CUSTOM, True))
        acts.append(dict(op='open', sub='FPS', fps=s['fps']))
    return rows, (cur if cur >= 0 else len(rows) - 1), fps_value(s, data), acts


def bit_rows(s):
    b = s.get('bit', 2)
    return list(BIT_ROWS), b, BIT_SUMMARY[b], [dict(op='stock', value=0), dict(op='stock', value=1), dict(op='stock', value=2)]


ROWS = {'DC': dc_rows, 'RES': res_rows, 'FPS': fps_rows, 'BIT': bit_rows}


# ---- the CSV ------------------------------------------------------------------------------------------------------
class TextError(ValueError):
    pass


def check_text(t):
    """a literal TEXT cell (fp-native-ui §2 rule 4): printable ASCII; no , " (CSV), no < > (markup)"""
    if not t or len(t) > 31 or any(not (32 <= ord(c) < 127) or c in ',"<>' for c in t):
        raise TextError(f'not a literal menu text: {t!r}')
    return t


def csv_bytes(rows, cap=None):
    """the stock .cvm form: UTF-8 BOM, the header, every row (the last one too) ended by CRLF; grey = 0,0"""
    if not rows or (cap is not None and len(rows) > cap):
        raise TextError(f'{len(rows)} rows (room for {cap})')
    lines = [CSV_HEADER] + [f"{i},{check_text(t)},Popup,blank,{'1,2' if on else '0,0'}"
                            for i, (t, on) in enumerate(rows, 1)]
    return b'\xef\xbb\xbf' + ''.join(line + '\r\n' for line in lines).encode('ascii')


def parse_csv(data):
    """header-driven (never fixed columns), as the firmware reads it -> [(text, selectable)]"""
    import csv
    import io
    if not data.startswith(b'\xef\xbb\xbf') or not data.endswith(b'\r\n'):
        raise TextError('no BOM / the last row has no CRLF (it would not be read)')
    rd = list(csv.reader(io.StringIO(data[3:].decode('ascii'), newline='')))
    head = rd[0]
    t, e1, e2, no = head.index('TEXT'), head.index('Enabled'), head.index('Enabled2'), head.index('NO')
    out = []
    for k, r in enumerate(rd[1:], 1):
        if int(r[no]) != k or (r[e1], r[e2]) not in (('1', '2'), ('0', '0')):
            raise TextError(f'row {k}: {r}')
        out.append((r[t], r[e1] == '1'))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('dc', choices=[n for n, _w, _h in DCS] + ['Custom'])
    ap.add_argument('w', type=int, nargs='?')
    ap.add_argument('h', type=int, nargs='?')
    ap.add_argument('--res', help='WxH (a custom RES) or a label (1K, 3.5K, UHD ...)')
    ap.add_argument('--fps', type=float, default=59.94)
    ap.add_argument('--tuned', type=float)
    ap.add_argument('--mode', choices=('qs', 'std'), default='qs')
    a = ap.parse_args(argv)
    W, H = next(((w, h) for n, w, h in DCS if n == a.dc), (a.w, a.h))
    s = dict(dcW=W, dcH=H, fps=a.fps, fpsCustom=a.tuned)
    if a.res and 'x' in a.res:
        w, h = (int(v) for v in a.res.split('x'))
        s['res'] = dict(w=w, h=h)
    elif a.res:
        s['resK'] = a.res
    for k, fn in ROWS.items():
        rows, cur, summ, _acts = fn(s, a.mode) if k == 'FPS' else fn(s)
        print(f"{k:3} summary {summ!r}  current row {cur}  rows {len(rows)}: " +
              ' | '.join(t + ('' if on else ' (grey)') for t, on in rows))
        if rows:
            sys.stdout.write(csv_bytes(rows, CAP[k]).decode('utf-8-sig').replace('\r\n', '\n'))


if __name__ == '__main__':
    main()
