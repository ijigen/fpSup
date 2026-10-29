#!/usr/bin/env python3
"""Sensor mode creator (module 1, notes/ARCHITECTURE.md): build all 8 per-mode table rows of a new IMX410 mode from
rules (offline/mode_rules.py explicit formulas + rules fitted on the 70 stock modes by offline/reconstruct.py) --
no donor copy.

    smc.py selftest                 rebuild the 70 stock modes from their attributes; report every differing field
    smc.py create KEY --crop WxH --out WxH [--fps F] [--json OUT]   rows for one readout_cfg plan

Rule kinds used per field: explicit formula (mode_rules.EXACT) / const / class lookup (cat on readout-class attrs)
/ linear / byte / 'nearest' (gated or 2-variable fits: value copied from the stock mode of the same class nearest
in geometry -- flagged, counted in the self-test). A new readout class (not among the 8 stock ones) is refused,
except 12fast = class 17 + the fast Family A set (IMX410_RULES §49).
"""
import argparse, json, pathlib, struct, sys
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / 'offline'))
import reconstruct as RC
import mode_rules as MR
import readout_export as X
import readout_cfg as C

TABLES = ['TIM', 'META', 'R28', 'R38', 'R14', 'R68', 'REG']
STRIDE = {t: X.ROM[t][1] for t in TABLES}
BASE_X0 = {1: 8, 2: 4, 3: 6}
BASE_Y0 = {16: 40, 17: 40, 18: 20, 19: 20, 20: 14, 21: 14, 22: 8, 23: 8}
VADD = {1: 1, 2: 2, 3: 2, 6: 3}
# R10 = the SoC readout-mode number, by readout class only (notes/MODE_TABLES.md §1). It sets the receiver for the
# class; a virtual mode that leaves the host's R10 (vmode keeps every table it is not given) gets the host's receiver:
# 1x1 / fast 2x2 under FHD60 (R10 6) recorded garbage (isp-lab validation/20261027-smoke, vm1 V41)
R10_OF_CLS = {16: 2, 17: 3, 18: 6, 19: 7, 20: 4, 21: 5, 22: 4, 23: 5}
_FIT = None


def fit():
    global _FIT
    if _FIT:
        return _FIT
    modes, attrs, fields = RC.load()
    rules = {}
    for f, vals in fields.items():
        if f[0].endswith('32'):
            continue
        if f in MR.EXACT:
            rules[f] = ('exact', None); continue
        kind, rule = RC.classify(vals, attrs)
        k = kind.split(':')[0]
        if k == 'const':
            rules[f] = ('const', next(iter(vals.values())))
        elif k == 'cat':
            keys = kind[4:].split('+')
            rules[f] = ('cat', (keys, {tuple(attrs[m][a] for a in keys): v for m, v in vals.items()}))
        elif k == 'lin' and rule is not None:
            xn = kind[4:].split('|')[0]; grp = kind.split('|')[1] if '|' in kind else None
            rules[f] = ('lin', (xn, grp, rule))
        elif k == 'byte':
            xn, sh = kind[5:].split('>>'); rules[f] = ('byte', (xn, int(sh)))
        else:
            rules[f] = ('nearest', {m: v for m, v in vals.items()})
    _FIT = (modes, attrs, fields, rules)
    return _FIT


def _nearest(vals, attrs, a):
    same = [m for m in vals if attrs[m]['cls'] == a['cls']] or list(vals)
    m = min(same, key=lambda m: abs(attrs[m]['width'] - a['width']) + abs(attrs[m]['height'] - a['height']))
    return vals[m]


def value(f, a, mode=None):
    modes, attrs, fields, rules = fit()
    kind, r = rules[f]
    if kind == 'exact':
        v, how = MR.predict(f, mode if mode is not None else -1, a)
        return v, how
    if kind == 'const':
        return r, 'const'
    if kind == 'cat':
        keys, look = r
        k = tuple(a[x] for x in keys)
        if k not in look:
            raise ValueError(f'{f}: no rule for {dict(zip(keys, k))} (class not among stock modes)')
        return look[k], 'cat'
    if kind == 'lin':
        xn, grp, rule = r
        g = a[grp] if grp else 0
        if g not in rule:
            raise ValueError(f'{f}: linear rule has no group {grp}={g}')
        sl, b = rule[g]
        return int(sl * a[xn] + b), 'lin'
    if kind == 'byte':
        xn, sh = r
        return (a[xn] >> sh) & 0xFF, 'byte'
    return _nearest(r, attrs, a), 'nearest'


def build(a, mode=None):
    """attrs -> {table: bytearray row}, {field: how}"""
    rows = {t: bytearray(STRIDE[t]) for t in TABLES}
    how = {}
    modes, attrs, fields, rules = fit()
    for f in rules:
        t, o = f
        v, h = value(f, a, mode)
        how[f] = h
        if t == 'REG':
            struct.pack_into('<I', rows['REG'], 4 * (1 + X.REG_ORDER.index(o)), v & 0xFFFFFFFF)
        else:
            struct.pack_into('<H', rows[t], o, v & 0xFFFF)
    return rows, how


def attrs_from_plan(p):
    r = C.BY_KEY[p['key']]
    # matrix classes (readout_cfg new=True, IMX410_RULES §67): link/REG class of their AD (14 -> 16, 12/fast -> 17)
    # and their own measured first image row; the binning itself goes in hbin/vbin (META, R14, R38, R68 formulas)
    cls = r.get('cls') or {'14': 16, '12': 17, '12fast': 17, '12fastW': 17}.get(p['key'], X.CLS.get(p['key']))
    hb, vb = r['mh'], r['mv']
    x0 = BASE_X0[hb] + (p['fmt_w'] - p['raster_w']) // 2
    if p.get('line_w', p['fmt_w']) < p['fmt_w']:     # short line (§72): stay inside its real columns, x0 even (phase)
        x0 = max(0, min(x0, p['line_w'] - p['raster_w']) // 2 * 2)
    y0 = (r.get('y0') or BASE_Y0[cls]) + p.get('y_skip', 0)   # V3 window margin rows (readout_cfg V3_MARGIN, §76)
    sens = dict(p['sensor'])
    win = sens.get(0x0003, 0)
    ws = sens.get(0x0022, 0) | sens.get(0x0023, 0) << 8
    wh = sens.get(0x0024, 0) | sens.get(0x0025, 0) << 8
    v016 = sens.get(0x0016, r['v016'])
    a = dict(cls=cls, hbin=hb, vbin=vb, vadd=VADD[vb], bits=r['bits'], width=p['raster_w'], height=p['out_h'],
             hmax=p['soc']['hmax'], tail=p['soc']['hmax'], vmax=p['soc']['vmax'], f5c=2 * v016,
             x0=x0, x1=x0 + p['raster_w'], y0=y0, y1=y0 + p['out_h'], fpsn=int(round(p['fps'])),
             win=win, wstart=ws, wh=wh, rows=p['out_h'], acq=0, crop=0, cont=0, y_skip=p.get('y_skip', 0),
             # R68 +0x2C defect-table y offset, matched to hot pixels of the matrix classes (G7, captures/g7):
             # v2 needs 2 (as the stock acq 2x2 modes), v3 (skip-sampled 2 of 3, y type 1) needs 66 with y0 = 20
             dyo={2: 2, 3: 66}.get(vb, 0) if r.get('new') else 0)
    return a


def create(p):
    a = attrs_from_plan(p)
    rows, how = build(a)
    rows['R10'] = bytearray(struct.pack('<II', R10_OF_CLS[a['cls']], 0))
    # sensor writes the plan insists on (format, window, blanking) and the fast Family A set
    writes = list(p['sensor'])
    if p['fast_set']:
        import bins
        writes = list(bins.diff('8', '139')) + writes
    for reg, val in writes:
        struct.pack_into('<I', rows['REG'], 4 * (1 + X.REG_ORDER.index(reg)), val)
    return a, rows, how


def selftest():
    modes, attrs, fields, rules = fit()
    bad = {}
    approx = 0
    for m in modes:
        a = attrs[m]
        rows, how = build(a, mode=m)
        for f in rules:
            t, o = f
            want = fields[f][m]
            got = struct.unpack_from('<I' if t == 'REG' else '<H', rows[t], 4 * (1 + X.REG_ORDER.index(o)) if t == 'REG' else o)[0]
            if how[f] == 'nearest':
                approx += 1
            if got != want:
                bad.setdefault(f, []).append((m, want, got))
    import vmode as V
    _, rom, st, key = V.TABLES['R10']
    img = (HERE.parents[1] / 'out' / 'MAIN_c0000000.bin').read_bytes()
    r10 = {struct.unpack_from('<I', img, rom - 0xC0000000 + st * i + key)[0]:
           struct.unpack_from('<I', img, rom - 0xC0000000 + st * i)[0] for i in range(V.N)}
    for m in modes:
        if R10_OF_CLS.get(attrs[m]['cls']) != r10.get(m):
            bad.setdefault(('R10', 0), []).append((m, r10.get(m), R10_OF_CLS.get(attrs[m]['cls'])))
    n = len(rules) * len(modes)
    nbad = sum(len(v) for v in bad.values())
    print(f'self-test: {n - nbad}/{n} values reproduced ({100 * (n - nbad) / n:.2f} %), fields with a miss: {len(bad)}; '
          f'values from "nearest" rules: {approx}')
    for f, lst in sorted(bad.items(), key=lambda kv: -len(kv[1]))[:20]:
        print(f'  {f[0]} {"%04X" % f[1] if f[0] == "REG" else "+0x%02X" % f[1]}: {len(lst)} modes e.g. {lst[:3]}')
    return nbad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=('selftest', 'create'))
    ap.add_argument('key', nargs='?'); ap.add_argument('--crop'); ap.add_argument('--out'); ap.add_argument('--fps', type=float)
    ap.add_argument('--json')
    a = ap.parse_args()
    if a.cmd == 'selftest':
        sys.exit(1 if selftest() else 0)
    cw, ch = (int(x) for x in a.crop.split('x')); ow, oh = (int(x) for x in a.out.split('x'))
    p = C.plan(a.key, cw, ch, ow, oh, a.fps)
    at, rows, how = create(p)
    kinds = {}
    for h in how.values():
        kinds[h] = kinds.get(h, 0) + 1
    out = dict(plan_id=p['id'], attrs=at, how_counts=kinds, rows={t: rows[t].hex() for t in rows})
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(out, indent=1))
    print(json.dumps(dict(plan_id=p['id'], attrs=at, how_counts=kinds), indent=1))


if __name__ == '__main__':
    main()
