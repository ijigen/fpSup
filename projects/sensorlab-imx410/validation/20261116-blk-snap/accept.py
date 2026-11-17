#!/usr/bin/env python3
"""H_BLV live acceptance (Bei 11-16: "not worse than stock"), lens capped, the H_BLV + BLK-SNAP build on the card.

    BLK_BUILD=blv/out-blk-snap-blv/build-0.0.7test.json BLK_TAKES=blv/takes python3 -B accept.py

1. stock baseline: sq_test 30 1 (stock, kept), ISO 100 / 800 / 3200, two takes each, then sq_test 30 0
2. phase 0 again (the 8 takes of the morning, now corrected)
3. the 14 largest |err| of phase 1 (one take each, its own ISO)
-> blv/accept.jsonl (resumable: a tag already in it is skipped)
"""
import json, os, pathlib, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
sys.argv = sys.argv[:1]
sys.path.insert(0, str(HERE))
import take as T                                            # noqa: E402
import dark                                                 # noqa: E402

OUT = HERE / 'blv' / 'accept.jsonl'
TAKES = HERE / os.environ.get('BLK_TAKES', 'blv/takes')
P0 = [('p0-12v2', 'G9BqVegakGVFwG9VCJRJeQaaFNwXoNSr0DUxa'), ('p0-14v2', 'G9BqVegakGKTgOPlCKxJeQaaKrQXoNSr0DU2U'),
      ('p0-12full', 'G9B-Reg_IGVFwG9UiIJJeQ--MWWXoPyL0H5DO'), ('p0-14full', 'G9B-Reg_I8QOgOPkiIBJeQ--ZR-XoPyL0H5Ha')]
ORIGINAL = 'G9B-QvQfkGVFwG9VCJRIvAfKGLKXoPyL0D7yK'      # Bei's selection before the run


def done():
    return {json.loads(l)['tag'] for l in OUT.read_text().splitlines()} if OUT.exists() else set()


def measure(tag, extra):
    rec = dict(tag=tag, **extra)
    for name in ('f3', 'f1'):
        p = TAKES / tag / f'{name}.DNG'
        if not p.exists():
            continue
        d = dark.dark(p)
        if d['valid']:
            s = 4 if d['tag'] > 600 else 1
            rec.update(frame=name, bits=14 if s == 4 else 12, data=d['mean'] / s, tag_dng=d['tag'] / s,
                       err=(d['mean'] - d['tag']) / s, ch=[v / s - d['tag'] / s for v in d['means'].values()])
            break
    else:
        rec['error'] = 'no valid frame'
    with open(OUT, 'a') as f:
        f.write(json.dumps(rec) + '\n')
    print(f"{tag}: err {rec.get('err', float('nan')):+.3f}  tag {rec.get('tag_dng', 0):.3f}", flush=True)


def stock_take(tag, iso):
    out = TAKES / tag
    out.mkdir(parents=True, exist_ok=True)
    assert 'is_recording -> 0' in T.fsh('status get is_recording')
    T.fsh(f'menu SetIso {iso}')
    clip0 = T.newest_clip()[0]
    subprocess.run(['zsh', str(T.SHELL / 'rec_take.sh'), '2'], capture_output=True, timeout=90)
    assert 'is_recording -> 0' in T.fsh('status get is_recording'), 'still recording'
    mode = T.pf.mem_get(0xC343B590)[0]
    clip, date = T.newest_clip()
    assert clip != clip0, 'no new clip'
    for fr in (3, 2):
        try:
            T.fetch(f'\\CINEMA\\{clip}\\{clip}_{date}_{fr:06d}.DNG', out / 'f3.DNG')
            break
        except SystemExit:
            time.sleep(3)
    T.fetch(f'\\CINEMA\\{clip}\\{clip}_{date}_000001.DNG', out / 'f1.DNG')
    return dict(kind='stock', iso=iso, mode=mode, clip=clip)


def main():
    have = done()
    todo_stock = [(f'stock-iso{iso}-{k}', iso) for iso in (100, 800, 3200) for k in (1, 2)]
    if any(t not in have for t, _ in todo_stock):
        print('sq_test 30 1 ->', T.op(30, 1), flush=True)
        time.sleep(4)
        try:
            for tag, iso in todo_stock:
                if tag not in have:
                    measure(tag, stock_take(tag, iso))
        finally:
            print('sq_test 30 0 ->', T.op(30, 0), flush=True)
            time.sleep(4)
    jobs = [(f'{n}-iso{iso}', code, iso, 'phase0') for n, code in P0 for iso in (100, 3200)]
    rows = json.loads((HERE / 'summary-phase1.json').read_text())
    worst = sorted(rows, key=lambda r: abs(r['err']), reverse=True)[:14]
    jobs += [('w-' + r['tag'], r['code'], r['iso'], 'worst') for r in worst]
    for tag, code, iso, kind in jobs:
        if tag in done():
            continue
        if (HERE / 'STOP').exists():
            print('STOP'); break
        r = subprocess.run([sys.executable, '-B', str(HERE / 'take.py'), tag, code, str(iso)], capture_output=True,
                           text=True, cwd=HERE, timeout=400, env=os.environ)
        (TAKES.parent / 'logs').mkdir(parents=True, exist_ok=True)
        (TAKES.parent / 'logs' / f'{tag}.txt').write_text(r.stdout + r.stderr)
        if r.returncode:
            print(f'{tag}: take failed rc {r.returncode}: stopping', flush=True)
            return 3
        before = next((x['err'] for x in rows if 'w-' + x['tag'] == tag), None)
        measure(tag, dict(kind=kind, iso=iso, code=code, err_before=before))
    T.fsh('menu SetIso 3200')
    got, rc = T.set_recipe(ORIGINAL)
    time.sleep(4)
    print('restored:', T.live_code() == ORIGINAL, 'iso', T.fsh('menu SetIso').strip(), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
