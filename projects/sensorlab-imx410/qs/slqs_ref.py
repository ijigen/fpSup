#!/usr/bin/env python3
"""SensorLab-IMX410 QS (DC / RES): the reference model, a line-by-line port of
preview/dcres.html (Bei's reference behaviour: resList, divText, kLabel, res,
setDC0, setRes0, the DC / RES / WIDTH / HEIGHT / RATIO tiles) with JavaScript's
number semantics (IEEE doubles, Math.round = floor(x + 0.5), toFixed = exact
value, ties up).  The C client (slqs.c) is tested against it, and it against
matrix.json.  No device I/O.

    python3 -B slqs_ref.py            # print every preset DC's RES list
"""
import json
import math
import pathlib
from decimal import Decimal, ROUND_HALF_UP

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MATRIX = ROOT / 'projects' / 'isp-lab' / 'host' / 'matrix.json'

PX_MM = 35.9 / 6048
WMAX, HMAX, WMIN, HMIN = 6048, 4040, 256, 144
# the presets: matrix.json's x1 RES of each DC (the 16 x 2 aligned crop), display names as Bei wrote them
DCS = [('OG', 6048, 4040), ('HD', 6048, 3402), ('S35', 4192, 2358), ('APS-C', 3952, 2624),
       ('S16', 2096, 1240), ('SQ', 4032, 4032)]
MATRIX_DC = {'OG': 'OG', 'HD': 'HD', 'S35': 'S35', 'APS-C': 'APSC', 'S16': 'S16', 'SQ': 'SQ'}
RATIOS = [(1, 1), (2, 3), (1, 2), (1, 3), (1, 6)]          # x1, /1.5, /2, /3, /6 as num / den
KS = [1, 2, 3, 3.5, 4, 5, 6]
HD_EXTRA = [('UHD', 3840, 2160), ('FHD', 1920, 1080)]
DIVK = [1, 2, 3, 4, 5, 6, 8, 12]
DEF_DC, DEF_RAT = 1, 3                                      # HD, /3 (the preview's start)
CUSTOM = 'CUSTOM'


def a16(w):
    return math.floor(w / 16) * 16


def ev(h):
    return math.floor(h / 2) * 2


def js_round(x):
    return math.floor(x + 0.5)


def to_fixed(x, n):
    return str(Decimal(x).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))


def k_label(w):
    x = w / 1024
    if x < 0.75:
        return to_fixed(js_round(x * 10) / 10, 1) + 'K'
    v = js_round(x * 2) / 2
    return (str(int(v)) if v == int(v) else str(v)) + 'K'


def k_name(K):
    return (str(int(K)) if K == int(K) else str(K)) + 'K'


def mm(px):
    return to_fixed(px * PX_MM, 1)


def div_text(W, H, w, h):
    n = next((k for k in DIVK if a16(W / k) == w), None)
    m = next((k for k in DIVK if ev(H / k) == h), None)
    return (str(n or '') + 'x' + str(m or '')) if (n or m) else ''


def rat_size(r, W, H):
    num, den = RATIOS[r]
    w = a16(W * (num / den))
    h = ev(H * (num / den)) if num == 1 else ev(w * H / W)
    return w, h


def dc_name(W, H):
    return next((n for n, w, h in DCS if (w, h) == (W, H)), None)


def res_list(W, H):
    """[{w, h, ratio (index or None), label, div}], small to large."""
    items = []
    for r in range(len(RATIOS)):
        w, h = rat_size(r, W, H)
        if w >= WMIN:
            items.append(dict(w=w, h=h, ratio=r, label=k_label(w), div=div_text(W, H, w, h)))
    for K in KS:
        w = a16(K * 1024)
        if w > W:
            continue
        if any(i['ratio'] is not None and i['label'] == k_name(K) for i in items):
            continue
        h = ev(w * H / W)
        items.append(dict(w=w, h=h, ratio=None, label=k_name(K), div=div_text(W, H, w, h)))
    if dc_name(W, H) == 'HD':
        for n, w, h in HD_EXTRA:
            items.append(dict(w=w, h=h, ratio=None, label=n, div=div_text(W, H, w, h)))
    seen, out = set(), []
    for i in items:
        if (i['w'], i['h']) not in seen:
            seen.add((i['w'], i['h']))
            out.append(i)
    return sorted(out, key=lambda i: i['w'])                 # stable: JS Array.sort is stable


class State:
    """The selection (preview S), with the preview's transitions."""

    def __init__(self):
        self.dcW, self.dcH = DCS[DEF_DC][1:]
        self.dcLock = self.resLock = True
        self.rat, self.custom, self.memory = DEF_RAT, None, {}

    def key(self):
        return (self.dcW, self.dcH)

    def res(self):
        return self.custom or rat_size(self.rat, self.dcW, self.dcH)

    def set_dc(self, w, h):
        if self.custom:
            self.memory[self.key()] = self.custom
        self.dcW = max(WMIN, min(WMAX, a16(w)))
        self.dcH = max(HMIN, min(HMAX, ev(h)))
        self.custom = self.memory.get(self.key())
        if self.custom and (self.custom[0] > self.dcW or self.custom[1] > self.dcH):
            self.custom = None
        if not self.custom and rat_size(self.rat, self.dcW, self.dcH)[0] < WMIN:
            self.rat = 0

    def set_res(self, w, h):
        w = max(WMIN, min(self.dcW, a16(w)))
        h = max(HMIN, min(self.dcH, ev(h)))
        hit = [i for i in res_list(self.dcW, self.dcH) if i['w'] == w and i['h'] == h and i['ratio'] is not None]
        if hit:
            self.rat, self.custom = hit[0]['ratio'], None
            self.memory.pop(self.key(), None)
        else:
            self.custom = (w, h)

    # ---- the tiles ----
    def dc_value(self):
        return dc_name(self.dcW, self.dcH) or CUSTOM

    def dc_small(self):
        return f'{mm(self.dcW)} × {mm(self.dcH)} mm'

    def res_sel(self):
        r = self.res()
        L = res_list(self.dcW, self.dcH)
        return next((k for k, i in enumerate(L) if (i['w'], i['h']) == tuple(r)), -1), L

    def res_value(self):
        k, L = self.res_sel()
        return L[k]['label'] if k >= 0 else CUSTOM

    def res_small(self):
        w, h = self.res()
        d = div_text(self.dcW, self.dcH, w, h)
        return f'{w}×{h}' + (f' · {d}' if d else '')

    def dc_adj(self, d):
        k = next((i for i, x in enumerate(DCS) if (x[1], x[2]) == (self.dcW, self.dcH)), -1)
        k = (0 if d > 0 else len(DCS) - 1) if k < 0 else (k + d) % len(DCS)
        self.set_dc(DCS[k][1], DCS[k][2])

    def res_adj(self, d):
        k, L = self.res_sel()
        k = 0 if k < 0 else max(0, min(len(L) - 1, k + d))
        self.set_res(L[k]['w'], L[k]['h'])

    def dim_adj(self, which, axis, d):
        """WIDTH / HEIGHT: 16 / 2 px a click; locked: the other follows at the current aspect
        (the preview's float w / asp; the C uses w * h0 / w0 in integers -- tests check they agree)."""
        is_dc = which == 'dc'
        lock = self.dcLock if is_dc else self.resLock
        w0, h0 = (self.dcW, self.dcH) if is_dc else tuple(self.res())
        asp = w0 / h0
        w, h = w0, h0
        if axis == 'w':
            w += d * 16
            if lock:
                h = ev(w / asp)
        else:
            h += d * 2
            if lock:
                w = a16(h * asp)
        if is_dc:
            w, h = min(w, WMAX), min(h, HMAX)
            if w >= WMIN and h >= HMIN:
                self.set_dc(w, h)
        else:
            self.set_res(w, h)


def matrix_res():
    """{DC: sorted [(w, h)]} of matrix.json."""
    out = {}
    for r in json.loads(MATRIX.read_text()):
        out.setdefault(r['dc'], set()).add(tuple(r['res']))
    return {k: sorted(v) for k, v in out.items()}


if __name__ == '__main__':
    for n, W, H in DCS:
        print(f'{n:6} {W}x{H}:', ', '.join(f"{i['label']} {i['w']}x{i['h']}{(' ' + i['div']) if i['div'] else ''}"
                                         for i in res_list(W, H)))
