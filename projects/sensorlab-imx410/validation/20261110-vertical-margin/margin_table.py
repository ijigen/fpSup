#!/usr/bin/env python3
"""Vertical margin vs first-frame purple: every archived condition, every stock CinemaDNG profile, and the product
impact of the fix.  Offline; reads only archived numbers, the stock profile table and quality.py.

    python3 -B margin_table.py            # prints the three tables (README.md) and writes impact.json

margin = the RWZM input rows left below the record, as the firmware lays the record in (ContSet_Adr1 @C031BE60,
decomp blk_c03.c 19833-19853): R = META_h // vbin; est = (Zv/2 + R*1024) // Zv when Zv > 1024 (else R);
crop y0 = (est - N) // 4 * 2 (0x300F0684 high half); margin = R - (y0 + N) * Zv / 1024.  The RWZM (0x300F0900) is on
when either axis is not 1:1 (FUN_c032d9a0); with both 1:1 there is no scaler and no margin (BUFA0 route).
"""
import collections, json, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(ROOT / 'projects/isp-lab/host'), str(ROOT / 'projects/sensorlab-imx410/preview')]
import quality as Q          # noqa: E402


def margin(R, N, zh, zv, vbin=1):
    m = Q.vmargin(R, vbin, zh, zv, N)
    if m is None:
        return None, None
    z = max(zv, 1024)
    Rv = R // vbin
    est = (z // 2 + Rv * 1024) // z if z > 1024 else Rv
    return m / 1024, (est - N) // 4 * 2 if est > N else 0


# (condition, route, RX rows = META_h, record rows N, Zh, Zv, purple, takes, source)
EVIDENCE = [
    ('12v2 DC 6048x4040 -> 3024x2014 (full height)', 'BUFA1', 2014, 2014, 2048, 1024, 15, 18,
     '20261103-first-frame-purple t02-t19 (8/9 + IMXB 7/9)'),
    ('12v2 DC 6048x4020 -> 3024x2010 (window)', 'BUFA1', 2010, 2010, 2048, 1024, 8, 8, '20261103-first-frame-purple t28-t35'),
    ('14v2 full height (A001_355-387)', 'BUFA1', 2014, 2014, 2048, 1024, 33, 33, 'archive'),
    ('14v2 full height (defect-virtual)', 'BUFA1', 2014, 2014, 2048, 1024, 4, 4, 'defect-virtual/live'),
    ('14v2 HMAX 1000', 'BUFA1', 2014, 2014, 2048, 1024, 8, 10, '20261103-purple-hmax'),
    ('12v2 RES 3008x2004 (rec 1998, Zv 1032)', 'BUFA1', 2014, 1998, 2058, 1032, 10, 10, '20261103-purple-vratio'),
    ('1x1 12-bit OG -> 3024x2020 (2:1)', 'BUFA1', 4040, 2020, 2048, 2048, 3, 14, 'defect-virtual/live'),
    ('12h2 OG -> 3024x2020 (h 1:1, v 2:1)', 'BUFA1', 4040, 2020, 1024, 2048, 1, 5, '20261104-first-frame-trace (v27)'),
    ('14 1x1 OG -> 3024x2020 (2:1)', 'BUFA1', 4040, 2020, 2048, 2048, 0, 1, 'A001_014'),
    ('SensorLab 2x2 OG -> 3024x2014 (1:1 both)', 'no RWZM', 2014, 2014, 1024, 1024, 0, 10, '20261103-purple-2x2 (not BUFA1: v27)'),
    ('A: UHD 29.97 12b 1x1, DC 6048x3402 -> 3840x2160', 'BUFA1', 3402, 2160, 1612, 1612, 24, 42, '20261110-purple-live baseline'),
    ('A + NOWIN (sensor full height, RX 3402)', 'BUFA1', 3402, 2160, 1612, 1612, 4, 6, '20261110-purple-live'),
    ('A + SBSTOCK (stock standby)', 'BUFA1', 3402, 2160, 1612, 1612, 2, 6, '20261110-purple-live'),
    ('A + ROWS (stock RX 3412, our 2160 @1612)', 'BUFA1', 3412, 2160, 1612, 1612, 0, 6, '20261110-purple-live'),
    ('A + RWZM (our RX 3402, stock 2170 @1600)', 'BUFA1', 3402, 2170, 1600, 1600, 0, 6, '20261110-purple-live'),
    ('A + ROWS|RWZM (= stock UHD at BUFA1 start)', 'BUFA1', 3412, 2170, 1600, 1600, 0, 6, '20261110-purple-live'),
    ('UHD 25p 12fastW (same geometry as A)', 'BUFA1', 3402, 2160, 1612, 1612, 13, 27, '11-08 sweep'),
    ('stock UHD 29.97 (mode 7)', 'BUFA1', 3412, 2170, 1600, 1600, 0, 29, '20261103-stock-uhd-first-frame'),
    ('stock FHD 29.97 (mode 106)', 'BUFA7', 1708, 1090, 1600, 1600, 0, 9, 'original survey'),
]


def stock_profiles():
    d = json.loads((ROOT / 'research/other/external/FP3K-technical-handoff-2026-09-10/analysis/firmware/raw-profiles.json').read_text())
    tim = {}                                   # mode -> receiver rows (TIM y1 - y0, offline/mode_tables.csv)
    import csv
    for m in csv.DictReader(open(ROOT / 'projects/imx410-lab/offline/mode_tables.csv')):
        tim[int(m['mode'])] = int(m['TIM+10']) - int(m['TIM+0E'])
    out = collections.OrderedDict()
    for r in d['movie_routes']:
        k = (r['name'], r['sensor_mode'])
        if k in out:
            continue
        R = r['sensor_raster'][1]
        assert tim[r['sensor_mode']] == R, (k, tim[r['sensor_mode']], R)
        zh, zv = r['zoom']
        out[k] = (r['profile_id'], R, r['raw_dimensions'][1], max(zh, 1024), max(zv, 1024))
    return out


def main():
    print('## archived evidence\n')
    print('| condition | route | R | N | Zv | y0 | margin (rows) | purple |')
    print('|---|---|---|---|---|---|---|---|')
    for name, route, R, N, zh, zv, p, n, src in EVIDENCE:
        m, y0 = margin(R, N, zh, zv)
        print(f"| {name} | {route} | {R} | {N} | {zv} | {'—' if y0 is None else y0} | "
              f"{'n/a (RWZM off)' if m is None else f'{m:.2f}'} | {p}/{n} |")
    print('\n## stock CinemaDNG profiles (raw-profiles.json movie_routes; R = TIM rows = META height)\n')
    print('| profile (pid, mode) | R | N | Zv | y0 | margin |')
    print('|---|---|---|---|---|---|')
    floor = None
    for (name, mode), (pid, R, N, zh, zv) in stock_profiles().items():
        m, y0 = margin(R, N, zh, zv)
        if m is not None:
            floor = m if floor is None else min(floor, m)
        print(f"| {name} ({pid}, {mode}) | {R} | {N} | {zv} | {'—' if y0 is None else y0} | "
              f"{'n/a (1:1, RWZM off)' if m is None else f'{m:.3f}'} |")
    print(f'\nleast stock margin with the RWZM on: {floor} rows; quality.VMARGIN = {Q.VMARGIN / 1024}')
    assert floor == Q.VMARGIN / 1024
    impact()


def limit(n, d, lim=1000):
    """ap_calc.c apc_limit: n / d reduced, else the best rational with denominator <= lim"""
    from math import gcd
    g = gcd(n, d); n //= g; d //= g
    if d <= lim:
        return n, d
    p0, q0, p1, q1, N, D = 0, 1, 1, 0, n, d
    while True:
        a = N // D; q2 = q0 + a * q1
        if q2 > lim:
            break
        p0, q0, p1, q1 = p1, q1, p0 + a * p1, q2
        N, D = D, N - a * D
    k = (lim - q0) // q1
    bn, bd = p0 + k * p1, q0 + k * q1
    e2, e1 = abs(p1 * d - n * q1), abs(bn * d - n * bd)
    return (p1, q1) if e2 * bd <= e1 * q1 else (bn, bd)


def dscale(c):
    """ap_calc.c apc_dscale: the DNG DefaultScale of a case (None = off)"""
    m = [int(x) for x in c['merge'].split('x')]
    zh, zv = (max(z, 1024) for z in c['zoom'])
    rw, rh = c['rec']
    an, ad = rw * zh * m[0] * c['hbin'], rh * zv * m[1] * c['vbin']
    pn, pd = an * rh, ad * rw
    if 200 * abs(pn - pd) < pd:
        return None
    return ('h', limit(pn, pd)) if pn > pd else ('v', limit(pd, pn))


def impact():
    import gen_fps as G
    cells = [(f'{n}:{w}x{h}', W, H, w, h) for n, W, H, rs in G.preset_lists() for w, h in rs]
    st, rows, dropped, fov, asp, ds = collections.Counter(), [], [], [], 0.0, []
    for key, W, H, w, h in cells:
        a = {c['quality']: c for c in Q.qualities(W, H, w, h, tol=0.02)}
        b = {c['quality']: c for c in Q.qualities(W, H, w, h, tol=0.02, vmargin_floor=Q.VMARGIN)}
        assert not set(b) - set(a)
        for q in sorted(set(a) - set(b)):
            p = a[q]
            dropped.append((key, q, p['zoom'], p['rec'], p['window']))
        for q, o in b.items():
            p = a[q]
            # Bei 11-10: the readout, so RS and every fps, exactly as before
            assert (o['readout'], o['window'], o['fps']) == (p['readout'], p['window'], p['fps']), (key, q)
            assert Q.vmax_range(o) == Q.vmax_range(p) and Q.settings(o)[0]['rolling_ms'] == Q.settings(p)[0]['rolling_ms']
            m0 = Q.vmargin(p['window'][1], p['vbin'], *p['zoom'], p['rec'][1])
            m1 = Q.vmargin(o['window'][1], o['vbin'], *o['zoom'], o['rec'][1])
            assert m1 is None or m1 >= Q.VMARGIN
            kind = ('RWZM off' if m1 is None else 'already' if m0 >= Q.VMARGIN else
                    ('both ratios smaller + shorter record' if o['rec'] != p['rec'] else 'both ratios smaller')
                    if o['zoom'] != p['zoom'] else 'shorter record')
            st[kind] += 1
            if kind.startswith('both ratios smaller'):
                fov.append(max(1 - o['zoom'][0] / p['zoom'][0], 1 - o['zoom'][1] / p['zoom'][1]))
                asp = max(asp, abs(o['zoom'][0] * p['zoom'][1] / (o['zoom'][1] * p['zoom'][0]) - 1))
            if dscale(o) != dscale(p):
                ds.append((key, q, dscale(p), dscale(o)))
            rows.append(dict(cell=key, quality=q, kind=kind, zoom=[p['zoom'], o['zoom']], rec=[p['rec'], o['rec']],
                             margin=[None if m0 is None else m0 / 1024, None if m1 is None else m1 / 1024]))
    print(f'\n## impact on the {len(cells)} preset cells ({sum(st.values()) + len(dropped)} recipes before)\n')
    print(dict(st), f'not offered: {len(dropped)}')
    print('RS, VMAX range and fps of every offered recipe: identical to the pre-fix core (asserted)')
    fov.sort()
    print(f'FOV loss (both ratios smaller): median {fov[len(fov) // 2] * 100:.2f} %, max {fov[-1] * 100:.2f} %; '
          f'pixel aspect change max {asp * 100:.4f} %; DNG DefaultScale changed: {len(ds)}')
    for x in ds[:10]:
        print('   DS', x)
    print('shorter record cells', sorted({r['cell'] for r in rows if r['kind'] == 'shorter record'}))
    print('not offered:')
    for x in dropped:
        print('  ', x)
    json.dump(dict(rows=rows, dropped=dropped, ds=ds), open(HERE / 'impact.json', 'w'), indent=0)


if __name__ == '__main__':
    main()
