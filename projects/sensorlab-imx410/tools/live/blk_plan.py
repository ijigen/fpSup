#!/usr/bin/env python3
"""BLK-SNAP coverage plan (2026-11-16): which product recipes to record, lens capped, so every combination of the
factors that enter the BlackLevel formula (memory blacklevel-video-clamp-formula, tools/live/blk_snap.py) is taken
at least once -- stratified sampling over the product list, not every recipe.

    python3 -B blk_plan.py                      # fine strata (108 on the 11-10 list) x the ISO levels -> table
    python3 -B blk_plan.py --coarse             # readout family x video clamp x 1:1/RWZM only (52)
    python3 -B blk_plan.py --json PLAN.json     # the take list (stratum, recipe, its QR fields and code)

Input = the product list the page ships (preview/fps_data.js: quality.qualities(tol=0.02, vmargin_floor=VMARGIN) over
the page's preset DC x RES).  The QR field layout, the readout key names and the rate list are read from the page
itself (preview/dcres.html), so the codes are the page's own (paste one after .../sensor_lab_imx410/# to see it).

Factors (a stratum = one value of each):
  family   the readout key without its width preset (w18 / w03 / w2C / w2B): the sensor merge + AD -- the dark rows vs
           the image (physical) and where the clamp's OB regions sit (core.c R38)
  clamp    the video clamp bits (core.c derive: 1.7 < readout W x mh / (H x mv) < 2.0, in sensor units)
  path     1:1 (RWZM 1024 x 1024) or RWZM
  crct     a CRCT bin (hbin or vbin > 1)
  window   the sensor windowed, or its full height for that merge (V1 4040, V2 2014, V3 1358 rows)
  iso      the gain side (and the v35 0x500..0x800 band: which ISO lands there is read from the first takes'
           sensor_gain, blk_snap.py prints it)
The representative of a stratum is its recipe with the median sensor window area (ties: the cell name, then the
key), at 23.976p when the recipe reaches it (the lowest data rate), else at the recipe's maximum.
"""
import argparse
import json
import math
import pathlib
import re
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
PREVIEW = HERE.parents[1] / 'preview'
FPS_DATA = PREVIEW / 'fps_data.js'
PAGE = PREVIEW / 'dcres.html'
QR_URL = 'https://ijigen.github.io/fpSup/sensor_lab_imx410/#'
B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
FULL_ROWS = {1: 4040, 2: 2014, 3: 1358, 6: 672}          # quality.py / SMC_VERIFY rounds 14-16 (full-height rows)
ISO_DEFAULT = (100, 800, 3200)
FPS_PREF = 23.976
# phase 0, before the strata: the formula check -- Bei's take (SSD 2230 A001_003, 12v2) and its true-14 sibling
# (A001_002) with the video clamp on, and the 1:1 full frame (clamp off), 12 and 14 bit, at Bei's 29.97p
VALIDATE = (('HD:6048x1700', '12v2'), ('HD:6048x1700', '14v2'), ('OG:6048x4040', '12'), ('OG:6048x4040', '14'))
VALIDATE_ISO = (100, 3200)
VALIDATE_FPS = 29.97


def _js_const(src, name):
    m = re.search(r'const %s = (\[.*?\]);' % name, src, re.S)
    if not m:
        raise SystemExit(f'{PAGE}: const {name} not found')
    return json.loads(re.sub(r"'", '"', re.sub(r'\s+', ' ', m.group(1))))


def page_consts(page=PAGE):
    src = pathlib.Path(page).read_text()
    dcs = {n: (w, h) for n, w, h in _js_const(src, 'DCS')}
    return dict(dcs=dcs, key_names=_js_const(src, 'KEY_NAMES'), qr_fields=[tuple(x) for x in _js_const(src, 'QR_FIELDS')],
                std=_js_const(src, 'STD'))


def load_list(path=FPS_DATA):
    t = pathlib.Path(path).read_text().split('\n', 1)[1]
    d = json.loads(t[t.index('{'):t.rindex('}') + 1])
    out = []
    for cell, qs in d['cases'].items():
        if isinstance(qs, dict):
            continue
        for hm, lo, label, r in qs:
            out.append(dict(cell=cell, hm=hm, lo=lo, label=label, r=r))
    return d, out


def family(key):
    return re.sub(r'w(18|03|2C|2B)$', '', key)


def stratum(rc, coarse=False):
    r = rc['r']
    num, den = r['sw'] * r['mh'], r['sh'] * r['mv']      # core.c derive: W hb / (H vb) on the readout, in sensor units
    clamp = 17 * den < 10 * num < 20 * den               # (not the 'win' field: its height is in merged rows)
    path = '1:1' if r['zoom'] == [1024, 1024] else 'RWZM'
    if coarse:
        return (family(r['key']), 'clamp' if clamp else '-', path)
    crct = 'crct' if (r['hbin'], r['vbin']) != (1, 1) else '-'
    full = 'full' if r['sh'] >= FULL_ROWS.get(r['mv'], 1 << 30) - 8 else 'win'
    return (family(r['key']), 'clamp' if clamp else '-', path, crct, full)


def pick(members):
    areas = sorted(m['r']['win'][0] * m['r']['win'][1] for m in members)
    med = statistics.median_low(areas)
    return min(members, key=lambda m: (abs(m['r']['win'][0] * m['r']['win'][1] - med), m['cell'], m['r']['key']))


def rate(rc, clk, vmax_max, std, pref=FPS_PREF):
    """(QR fps field, vmax): pref (its STD index) when the recipe reaches it, else the recipe maximum (30)"""
    hm, lo = rc['hm'], rc['lo']
    v = math.ceil(clk / (hm * pref) - 1e-9)
    if lo <= v <= vmax_max:
        return std.index(pref), v
    return 30, lo


def qr_fields(rc, consts, clk, vmax_max, pref=FPS_PREF):
    r = rc['r']
    dc, res = rc['cell'].split(':')
    dcw, dch = consts['dcs'][dc]
    rw, rh = (int(x) for x in res.split('x'))
    fps, vmax = rate(rc, clk, vmax_max, consts['std'], pref)
    vis = r.get('vis') or [rw - 16, rh - 10]
    return dict(ver=1, dcw=dcw, dch=dch, rw=rw, rh=rh, fps=fps, vmax=vmax, hmax=rc['hm'],
                ad={11: 0, 12: 1, 14: 2}[r['ad']], mh=r['mh'], mv=r['mv'], hbin=r['hbin'], vbin=r['vbin'],
                key=consts['key_names'].index(r['key']), kh=1, kv=1, km=0,
                rcustom=0 if (r['hbin'], r['vbin']) == (1, 1) else 1, visw=vis[0], vish=vis[1],
                rs=min(131071, round(r['rs_ms'] * 1000)), fmt=0, rescustom=0, scw=r['scw'], sch=r['sch'],
                ww=r['win'][0], wh=r['win'][1])


def qr_pack(f, layout):
    """dcres.html qrPack: MSB first, CRC-8 (0x07) over the field bits, one pad bit, base64url"""
    bits = []
    for k, w in layout:
        v = f[k]
        if not 0 <= v < 1 << w:
            raise ValueError(f'{k}={v} does not fit {w} bits')
        bits += [v >> i & 1 for i in range(w - 1, -1, -1)]
    crc = 0
    for b in bits:
        top = (crc >> 7 & 1) ^ b
        crc = (crc << 1) & 0xFF
        if top:
            crc ^= 0x07
    bits += [crc >> i & 1 for i in range(7, -1, -1)] + [0]
    bits += [0] * (-len(bits) % 6)
    return ''.join(B64[int(''.join(map(str, bits[i:i + 6])), 2)] for i in range(0, len(bits), 6))


def plan(coarse=False, isos=ISO_DEFAULT, fps_data=FPS_DATA, page=PAGE):
    d, recs = load_list(fps_data)
    consts = page_consts(page)
    groups = {}
    for rc in recs:
        groups.setdefault(stratum(rc, coarse), []).append(rc)
    takes = []
    for cell, key in VALIDATE:
        rep = next(rc for rc in recs if rc['cell'] == cell and rc['r']['key'] == key and (rc['r']['hbin'], rc['r']['vbin']) == (1, 1))
        f = qr_fields(rep, consts, d['clk'], d['vmax_max'], VALIDATE_FPS)
        code = qr_pack(f, consts['qr_fields'])
        for iso in VALIDATE_ISO:
            takes.append(dict(phase=0, stratum=list(stratum(rep, coarse)), members=None, iso=iso, cell=cell,
                              label=rep['label'], key=key, win=rep['r']['win'], zoom=rep['r']['zoom'], fields=f,
                              code=code, url=QR_URL + code))
    for s in sorted(groups):
        rep = pick(groups[s])
        f = qr_fields(rep, consts, d['clk'], d['vmax_max'])
        code = qr_pack(f, consts['qr_fields'])
        for iso in isos:
            takes.append(dict(phase=1, stratum=list(s), members=len(groups[s]), iso=iso, cell=rep['cell'], label=rep['label'],
                              key=rep['r']['key'], win=rep['r']['win'], zoom=rep['r']['zoom'], fields=f, code=code,
                              url=QR_URL + code))
    return dict(recipes=len(recs), strata=len(groups), isos=list(isos), coarse=coarse, takes=takes)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--coarse', action='store_true')
    ap.add_argument('--iso', type=int, nargs='+', default=list(ISO_DEFAULT))
    ap.add_argument('--json')
    a = ap.parse_args(argv)
    p = plan(a.coarse, a.iso)
    n0 = sum(t['phase'] == 0 for t in p['takes'])
    print(f"phase 0 (formula check): {n0} takes; phase 1: {p['recipes']} recipes -> {p['strata']} strata x "
          f"{len(p['isos'])} ISO = {len(p['takes']) - n0} takes")
    seen = set()
    for t in p['takes']:
        if (t['phase'], t['code']) in seen:
            continue
        seen.add((t['phase'], t['code']))
        print('%d %-44s %4s  %-14s %-22s %s' % (t['phase'], ' '.join(t['stratum']), t['members'] or '', t['cell'],
                                                 t['label'], t['code']))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(p, indent=1) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
