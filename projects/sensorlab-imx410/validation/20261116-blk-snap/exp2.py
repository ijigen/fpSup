#!/usr/bin/env python3
"""Can ISO 3200 / 12800 beat stock?  Two experiments, lens capped, the H_BLV + BLK-SNAP build on the card.

    BLK_BUILD=blv/out-blk-snap-blv/build-0.0.7test.json BLK_TAKES=blv/takes-exp2 python3 -B exp2.py

A. stock FHD (sq_test 30 1) at ISO 3200 and 12800, 8 takes each, WITH the ring saved (its pedestal per take): is stock's
   small error at those ISOs stable, or the luck of an unmoved pedestal?
B. four strata worse than stock at 3200 / 12800, five member recipes each (different crops, spread over the window
   area), at both ISOs: does the error stay with the stratum (a stratum x gain table works) or move with the crop?
-> blv/exp2.jsonl (resumable)
"""
import json, os, pathlib, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
sys.argv = sys.argv[:1]
sys.path[:0] = [str(HERE), str(HERE.parents[1] / 'tools/live')]
import take as T                                            # noqa: E402
import accept as A                                          # noqa: E402
import blk_plan as P                                        # noqa: E402

A.OUT = OUT = HERE / 'blv' / 'exp2.jsonl'
A.TAKES = TAKES = HERE / os.environ.get('BLK_TAKES', 'blv/takes-exp2')
STRATA = [('f12v3', '-', 'RWZM'), ('12', '-', '1:1'), ('12h2', '-', 'RWZM'), ('12h3v2', '-', 'RWZM')]


def members(n=5):
    d, recs = P.load_list()
    consts = P.page_consts()
    out = []
    for s in STRATA:
        g = sorted((r for r in recs if P.stratum(r, coarse=True) == s),
                   key=lambda r: (r['r']['win'][0] * r['r']['win'][1], r['cell']))
        pick = [g[round(i * (len(g) - 1) / (n - 1))] for i in range(n)] if len(g) >= n else g
        seen = set()
        for r in pick:
            if (r['cell'], r['label']) in seen:
                continue
            seen.add((r['cell'], r['label']))
            f = P.qr_fields(r, consts, d['clk'], d['vmax_max'])
            out.append(dict(stratum=list(s), cell=r['cell'], label=r['label'], key=r['r']['key'],
                            win=r['r']['win'], code=P.qr_pack(f, consts['qr_fields'])))
    return out


def main():
    TAKES.mkdir(parents=True, exist_ok=True)
    have = A.done()
    stock = [(f'stock-iso{iso}-{k}', iso) for iso in (3200, 12800) for k in range(1, 9)]
    if any(t not in have for t, _ in stock):
        print('sq_test 30 1 ->', T.op(30, 1), flush=True)
        time.sleep(4)
        try:
            for tag, iso in stock:
                if tag in have:
                    continue
                extra = A.stock_take(tag, iso)
                (TAKES / tag / 'ring.bin').write_bytes(T.D.read_camera(T.BUILD, T.BLOCK))
                A.measure(tag, extra)
        finally:
            print('sq_test 30 0 ->', T.op(30, 0), flush=True)
            time.sleep(4)
    for m in members():
        for iso in (3200, 12800):
            tag = f"m-{'-'.join(m['stratum']).replace(':', '')}-{m['cell'].replace(':', '_')}-iso{iso}"
            if tag in A.done():
                continue
            if (HERE / 'STOP').exists():
                print('STOP'); return 0
            r = subprocess.run([sys.executable, '-B', str(HERE / 'take.py'), tag, m['code'], str(iso)],
                               capture_output=True, text=True, cwd=HERE, timeout=400, env=os.environ)
            (TAKES.parent / 'logs').mkdir(exist_ok=True)
            (TAKES.parent / 'logs' / f'{tag}.txt').write_text(r.stdout + r.stderr)
            if r.returncode:
                tail = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()][-1:]
                print(f'{tag}: rc {r.returncode} {tail}', flush=True)
                if any('not the recipe' in t or 'no frame' in t for t in tail):
                    continue
                return 3
            A.measure(tag, dict(kind='member', iso=iso, **m))
    T.fsh('menu SetIso 3200')
    T.set_recipe(A.ORIGINAL)
    time.sleep(4)
    print('restored:', T.live_code() == A.ORIGINAL, 'iso', T.fsh('menu SetIso').strip(), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
