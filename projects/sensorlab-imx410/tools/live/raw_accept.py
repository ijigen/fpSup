#!/usr/bin/env python3
"""RAW output acceptance on the camera (2026-11-17, Bei: tests must check the output, not the design).

    python3 -B raw_accept.py --build BUILD.json --block 0x... --out DIR [--set smoke|nonhd|all] [--frames 40]

Per recipe x ISO: set the recipe over USB, record 3 s, fetch N consecutive frames, and judge the OUTPUT:
  clip      a clip exists and has the frames asked for
  decode    every fetched frame decodes; no flat (noise-free) row inside the DefaultCrop margin
  steady    the frame mean has no step: |mean - median of its 8 neighbours| <= 0.15 DN12 on every frame
            (the 14-bit clamp-off flicker was 0.25 = 1 DN14 on ~50 % of the frames)
  fresh     no two fetched frames are the same picture (11-17: with Lossless 0.3.2test the fast AD x V3 1:1
            recipes recorded old buffer contents: repeated frames, an earlier frame's payload as garbage)
  black     lens capped only (p99.9 - tag < 64): |mean - tag| <= the gate (default 0.66 = the 0.0.8test worst case)
            and the four CFA channels within 0.5 of each other
NOT tested here (say so in any report): lit-scene colour and linearity, frames beyond the N fetched, clips longer
than 3 s, heat, MOV, 8 / 10-bit, playback, ISO other than those asked, stock modes.
A recipe the camera refuses is reported, not skipped silently.  `touch DIR/STOP` ends after the current take.
"""
import argparse, json, os, pathlib, statistics, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
RUN = ROOT / 'projects/sensorlab-imx410/validation/20261116-blk-snap'
sys.path[:0] = [str(HERE), str(RUN)]


def judge(rows, gate=0.66):
    """rows: per frame {mean, tag, means{}, flat_inside, p_hi} in the frame's own DN.  -> {check: (ok, detail)}"""
    s = 4 if rows[0]['tag'] > 600 else 1
    m = [r['mean'] / s for r in rows]
    out = {}
    bad = [i for i, r in enumerate(rows) if r['flat_inside']]
    out['decode'] = (not bad, f'{len(bad)} frames with flat rows inside the crop' if bad else f'{len(rows)} frames')
    steps = []
    for i, v in enumerate(m):
        nb = m[max(0, i - 4):i] + m[i + 1:i + 5]
        if nb and abs(v - statistics.median(nb)) > 0.15:
            steps.append(i)
    if len(m) < 12 and not steps:
        out['steady'] = (None, f'only {len(m)} frames: not judged')
    else:
        out['steady'] = (not steps, f'{len(steps)} of {len(m)} frames step > 0.15 DN12' if steps else
                         f'max deviation {max(abs(v - statistics.median(m)) for v in m):.3f}')
    keys = [(round(r['mean'], 9),) + tuple(round(v, 9) for v in r['means'].values()) for r in rows]
    rep = len(keys) - len(set(keys))
    out['fresh'] = (rep == 0, f'{rep} repeated frames' if rep else 'no repeats')
    dark = all((r['p_hi'] - r['tag']) / s < 64 for r in rows)
    if dark:
        err = statistics.fmean((r['mean'] - r['tag']) / s for r in rows)
        ch = [statistics.fmean(r['means'][k] for r in rows) / s for k in rows[0]['means']]
        ok = abs(err) <= gate and max(ch) - min(ch) <= 0.5
        out['black'] = (ok, f'mean - tag {err:+.3f}, channel spread {max(ch) - min(ch):.3f}')
    else:
        out['black'] = (None, 'not dark: not judged')
    return out


def frame_stats(path):
    import numpy as np, rawpy
    with rawpy.imread(str(path)) as r:
        v = r.raw_image_visible.astype(np.float64)
    tag = float(subprocess.run(['exiftool', '-s3', '-BlackLevel', str(path)], capture_output=True,
                               text=True).stdout.split()[0])
    h, w = v.shape
    c = v[h // 8:h - h // 8, w // 8:w - w // 8]
    rs = v.std(1)
    comp = subprocess.run(['exiftool', '-s3', '-Compression', str(path)], capture_output=True, text=True).stdout.strip()
    return dict(mean=float(c.mean()), tag=tag, p_hi=float(np.percentile(c, 99.9)), compressed=comp != 'Uncompressed',
                means={f'{y}{x}': float(c[y::2, x::2].mean()) for y in (0, 1) for x in (0, 1)},
                flat_inside=bool(any(5 <= i < h - 5 for i in np.nonzero(rs == 0)[0])))


def recipes(which):
    import blk_plan as P
    d, recs = P.load_list()
    consts = P.page_consts()
    code = lambda r, fps=P.FPS_PREF: P.qr_pack(P.qr_fields(r, consts, d['clk'], d['vmax_max'], fps), consts['qr_fields'])
    find = lambda cell, label: next(r for r in recs if r['cell'] == cell and r['label'] == label)
    out = [('bei-14v2-full', code(find('OG:6048x2020', '14b 1x2'), 29.97)),      # Bei's 11-17 SSD clips (flicker)
           ('bei-12v2-full', code(find('OG:6048x2020', '12b 1x2'), 29.97)),
           ('bei-12v2-hd', 'G9BqVegakGVFwG9VCJRJeQaaFNwXoNSr0DUxa'),             # Bei's 11-16 clip (green)
           ('hd-14v2', 'G9BqVegakGKTgOPlCKxJeQaaKrQXoNSr0DU2U')]
    if which in ('nonhd', 'all'):
        plan = P.plan(coarse=True, isos=(0,))
        for t in plan['takes']:
            if t['phase'] == 1 and (which == 'all' or t['stratum'][1] == '-'):
                out.append(('s-' + '-'.join(t['stratum']).replace(':', ''), t['code']))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', required=True); ap.add_argument('--block', required=True, type=lambda x: int(x, 0))
    ap.add_argument('--out', required=True, type=pathlib.Path)
    ap.add_argument('--set', default='smoke', choices=('smoke', 'nonhd', 'all'))
    ap.add_argument('--iso', default='100,3200'); ap.add_argument('--frames', type=int, default=40)
    ap.add_argument('--gate', type=float, default=0.66)
    ap.add_argument('--only', default='', help='comma list: only recipes whose name contains one of these')
    a = ap.parse_args()
    os.environ['BLK_BUILD'] = str(pathlib.Path(a.build).resolve())
    sys.argv = sys.argv[:1]
    import take as T
    T.BLOCK = a.block; T.SQ = a.block + T.INFO['sq_test_off']
    a.out.mkdir(parents=True, exist_ok=True)
    res = a.out / 'results.jsonl'
    done = {json.loads(l)['tag'] for l in res.read_text().splitlines()} if res.exists() else set()
    original = T.live_code(); iso0 = T.fsh('menu SetIso').strip()
    fails = 0
    try:
        for name, code in recipes(a.set):
            if a.only and not any(k in name for k in a.only.split(',')):
                continue
            for iso in (int(x) for x in a.iso.split(',')):
                tag = f'{name}-iso{iso}'
                if tag in done:
                    continue
                if (a.out / 'STOP').exists():
                    print('STOP'); return 0
                rec = dict(tag=tag, code=code, iso=iso, checks={})
                try:
                    assert 'is_recording -> 0' in T.fsh('status get is_recording'), 'recording or no answer'
                    T.fsh(f'menu SetIso {iso}')
                    T.set_recipe(code); time.sleep(4)
                    clip0 = T.newest_clip()[0]
                    subprocess.run(['zsh', str(T.SHELL / 'rec_take.sh'), '3'], capture_output=True, timeout=120)
                    if 'is_recording -> 0' not in T.fsh('status get is_recording'):
                        print(f'{tag}: STILL RECORDING: stopping'); return 2
                    clip, date = T.newest_clip()
                    d = a.out.resolve() / 'takes' / tag; d.mkdir(parents=True, exist_ok=True)
                    rows = []
                    if clip != clip0:
                        # from frame 6 (past the start-up frames); a clip the card cut short (11-17: 6048x4040
                        # fast, 2 frames on SD) is read from frame 2 -- frame 1 is the uncompressed one
                        for first in (6, 2):
                            for n in range(first, first + a.frames):
                                f = d / f'f{n:04d}.DNG'
                                try:
                                    T.fetch(f'\\CINEMA\\{clip}\\{clip}_{date}_{n:06d}.DNG', f)
                                except SystemExit:
                                    break
                                rows.append(frame_stats(f)); f.unlink()
                            if rows:
                                break
                    rec['clip'] = clip if clip != clip0 else None
                    rec['checks']['clip'] = (len(rows) >= 1, f'{len(rows)} frames fetched')
                    rec['short'] = len(rows) < 12   # 12: a 3 s 14-bit 6K take on SD keeps ~20 frames
                    if rows:
                        rec['checks'].update(judge(rows, a.gate))
                        rec['bits'] = 14 if rows[0]['tag'] > 600 else 12
                        rec['compressed'] = sum(r['compressed'] for r in rows)
                        rec['checks']['note'] = (None, f"{rec['compressed']} of {len(rows)} compressed")
                        (d / 'frames.json').write_text(json.dumps(rows))
                except SystemExit as e:
                    rec['checks']['recipe'] = (False, str(e)[:160])
                bad = [k for k, (ok, _) in rec['checks'].items() if ok is False]
                fails += bool(bad)
                with open(res, 'a') as f:
                    f.write(json.dumps(rec) + '\n')
                print(f"{tag}: {'FAIL ' + ','.join(bad) if bad else 'pass'}  " +
                      '  '.join(f'{k}: {v[1]}' for k, v in rec['checks'].items()), flush=True)
    finally:
        try:
            T.fsh(f'menu SetIso {iso0}'); T.set_recipe(original)
            print('restored', T.live_code() == original, flush=True)
        except BaseException as e:                     # noqa: BLE001
            print('NOT RESTORED:', e, flush=True)
    print(f'{fails} failing takes'); return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
