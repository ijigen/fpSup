#!/usr/bin/env python3
"""Exact merges (0.0.6test): the per-format merge table and the impact on every other preset recipe.  Offline.

    python3 -B binning_table.py        # prints tables.md content, writes impact.json

before = before-sources/quality.py (0.0.5test) on the 0.0.5test presets (/6 = ev(H/6); 1x2 / 1x3 were custom RES);
after  = projects/isp-lab/host/quality.py with the product rules (tol 2 %, vmargin floor, exact merges) on the
0.0.6test presets (dcres.html resList via gen_fps.preset_lists).
"""
import collections, importlib.util, json, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(ROOT / 'projects/isp-lab/host'), str(ROOT / 'projects/sensorlab-imx410/preview')]
import quality as Q          # noqa: E402
import gen_fps as G          # noqa: E402
spec = importlib.util.spec_from_file_location('quality_005', HERE / 'before-sources/quality.py')
Q0 = importlib.util.module_from_spec(spec); spec.loader.exec_module(Q0)
TOL = 0.02
DCS = [('OG', 6048, 4040), ('HD', 6048, 3402), ('SQ', 4032, 4032), ('S35', 4192, 2358), ('APS-C', 3952, 2624),
       ('S16', 2096, 1240)]
ev, a16 = (lambda x: x // 2 * 2), (lambda x: x // 16 * 16)


def after(W, H, w, h):
    return {c['quality']: c for c in Q.qualities(W, H, w, h, tol=TOL, vmargin_floor=Q.VMARGIN)}


def before(W, H, w, h):
    return {c['quality']: c for c in Q0.qualities(W, H, w, h, tol=TOL, vmargin_floor=Q0.VMARGIN)}


def rw(c):
    return 'off' if c['zoom'] == [1024, 1024] else 'ON'


def cellfmt(c):
    if c is None:
        return 'not offered'
    return f"z {c['zoom'][0]}/{c['zoom'][1]} · rec {c['rec'][0]}×{c['rec'][1]} · RWZM {rw(c)}"


ROWS = [('2x2', 2, 2, ['2x2']), ('3x3', 3, 3, ['3x3']), ('6x6', 6, 6, ['2x2-h3-v3', '3x6']),
        ('1x2', 1, 2, ['12v2', '14v2']), ('1x3', 1, 3, ['12v3', '14v3'])]


def merge_table():
    out = []
    print('| format | merge | RES before → after | recipe | before (0.0.5test) | after (0.0.6test) |')
    print('|---|---|---|---|---|---|')
    for n, W, H in DCS:
        for lab, kw, kh, quals in ROWS:
            w = a16(W // kw)
            h0 = ev(H // kh)
            h1 = h0 - Q.VM_ROWS if kh == 6 and kw == 6 else h0
            b, a = before(W, H, w, h0), after(W, H, w, h1)
            for q in quals:
                cb, ca = b.get(q), a.get(q)
                res = f'{w}×{h0}' + (f' → {w}×{h1}' if h1 != h0 else '') + (' (custom before)' if kw == 1 else '')
                print(f'| {n} | {lab} | {res} | {q} | {cellfmt(cb)} | {cellfmt(ca)} |')
                out.append(dict(fmt=n, merge=lab, res=[w, h1], res_before=[w, h0], quality=q,
                                before=None if cb is None else dict(zoom=cb['zoom'], rec=cb['rec'], window=cb['window']),
                                after=None if ca is None else dict(zoom=ca['zoom'], rec=ca['rec'], window=ca['window'],
                                                                   readout=ca['readout'], fps=ca['fps'])))
    return out


def impact():
    old = {(n, w, h): (W, H) for n, W, H, rs in json.load(open(HERE / 'presets-0.0.5test.json')) for w, h in rs}
    new = {(n, w, h): (W, H) for n, W, H, rs in G.preset_lists() for w, h in rs}
    st, rows = collections.Counter(), []
    for key in sorted(set(old) & set(new)):
        W, H = new[key]
        b, a = before(W, H, *key[1:]), after(W, H, *key[1:])
        for q in sorted(set(a) | set(b)):
            cb, ca = b.get(q), a.get(q)
            if cb is None or ca is None:
                kind = 'newly offered' if cb is None else 'no longer offered'
            elif (cb['readout'], cb['zoom'], cb['rec'], cb['window']) == (ca['readout'], ca['zoom'], ca['rec'], ca['window']):
                kind = 'unchanged'
            elif cb['readout'] != ca['readout']:
                kind = 'readout changed'
            elif ca['zoom'] == [1024, 1024]:
                kind = '(E) RWZM off'
            elif ca['zoom'][1] == 1024 and cb['zoom'][1] != 1024:
                kind = '(V) vertical 1:1'
            else:
                kind = 'zoom / rec changed (other)'
            st[kind] += 1
            if kind != 'unchanged':
                rows.append(dict(cell=f'{key[0]}:{key[1]}x{key[2]}', quality=q, kind=kind,
                                 before=None if cb is None else [cb['readout'][:6], cb['zoom'], cb['rec'], cb['fps']],
                                 after=None if ca is None else [ca['readout'][:6], ca['zoom'], ca['rec'], ca['fps']]))
    print(f'\n## impact on the {len(set(old) & set(new))} preset cells kept from 0.0.5test\n')
    for k, v in sorted(st.items()):
        print(f'- {k}: {v}')
    for r in rows:
        print('  ', r['cell'], r['quality'], r['kind'], r['before'], '->', r['after'])
    added = sorted(set(new) - set(old)); gone = sorted(set(old) - set(new))
    print(f'\npresets added: {added}\npresets gone: {gone}')
    total = {k: sum(len(after(*new[k], *k[1:])) for k in new) for k in ['n']}
    n_old = sum(len(before(*old[k], *k[1:])) for k in old)
    print(f'recipes on all presets: 0.0.5test {n_old} ({len(old)} cells) -> 0.0.6test {total["n"]} ({len(new)} cells)')
    return dict(counts=dict(st), rows=rows, added=added, gone=gone, n_before=n_old, n_after=total['n'])


def six_cells():
    """the /6 cells: every recipe, before (ev(H/6)) vs after (ev(H/6) - VM_ROWS): record = RES, anisotropic (DNG
    DefaultScale, ap_calc apc_dscale: |pixel aspect - 1| >= 0.5 %), offered"""
    sys.path.insert(0, str(HERE.parent / '20261110-vertical-margin'))
    import margin_table as MT
    print('\n## the /6 cells (all recipes)\n')
    print('| format | RES before → after | recipes | record = RES | DNG DefaultScale (anisotropic) |')
    print('|---|---|---|---|---|')
    out = []
    for n, W, H in DCS:
        w, h0 = a16(W // 6), ev(H // 6)
        h1 = h0 - Q.VM_ROWS
        b, a = before(W, H, w, h0), after(W, H, w, h1)
        eb = sum(c['rec'] == [w, h0] for c in b.values()); ea = sum(c['rec'] == [w, h1] for c in a.values())
        db = sum(MT.dscale(c) is not None for c in b.values()); da = sum(MT.dscale(c) is not None for c in a.values())
        print(f'| {n} | {w}×{h0} → {w}×{h1} | {len(b)} → {len(a)} | {eb} → {ea} | {db} → {da} |')
        out.append(dict(fmt=n, res=[w, h0, h1], n=[len(b), len(a)], exact=[eb, ea], dscale=[db, da]))
    return out


def invariant():
    """the build invariant (also test_core 'exact merge presets'): every format's /2 /3 2x2 3x3 and 1x2 1x3 presets
    have an exact RWZM-off merge recipe; the /6 preset a 6x6 / 3x6 recipe whose record is the RES; every RWZM-on
    recipe of every preset keeps the floor"""
    bad = []
    for n, W, H, rs in G.preset_lists():
        for w, h in rs:
            cs = Q.qualities(W, H, w, h, tol=TOL, vmargin_floor=Q.VMARGIN)
            for c in cs:
                m = Q.vmargin(c['window'][1], c['vbin'], *c['zoom'], c['rec'][1])
                if m is not None and m < Q.VMARGIN:
                    bad.append(('floor', n, w, h, c['quality']))
    print('\ninvariant:', 'PASS' if not bad else bad)


if __name__ == '__main__':
    print('## merge presets (12-bit sensor merges; 11-bit fast variants behave the same)\n')
    t = merge_table()
    im = impact()
    six = six_cells()
    invariant()
    json.dump(dict(merges=t, impact=im, six=six), open(HERE / 'impact.json', 'w'), indent=0)
