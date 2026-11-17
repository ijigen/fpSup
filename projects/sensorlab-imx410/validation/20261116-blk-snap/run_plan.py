#!/usr/bin/env python3
"""Phase 1 of the BLK-SNAP coverage plan (tools/live/blk_plan.py --coarse): one take per stratum x ISO, lens capped.

    python3 -B run_plan.py [--fine] [--limit N]      # resumable: a take with takes/<tag>/take.json is skipped

Per take: take.py (recipe over USB, ISO, 2 s record, ring, one DNG), then dark.py -> one line in results-phase1.jsonl.
A recipe the camera does not give exactly is logged and skipped; anything else (no pong, still recording) stops the
run.  `touch STOP` ends it after the current take (yield-camera rule).
"""
import json, os, pathlib, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SHELL = ROOT / 'fpSup/fp_usb_shell'
sys.path[:0] = [str(HERE), str(ROOT / 'projects/sensorlab-imx410/tools/live')]
import blk_plan as P                                       # noqa: E402
import dark                                                # noqa: E402

OUT = HERE / os.environ.get('BLK_RESULTS', 'results-phase1.jsonl')
TAKES = HERE / os.environ.get('BLK_TAKES', 'takes')


def ping():
    r = subprocess.run([str(SHELL / 'host/fpsh'), 'ping'], capture_output=True, text=True, cwd=SHELL, timeout=30)
    return 'pong' in r.stdout


def main():
    fine = '--fine' in sys.argv
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None
    isos = [int(x) for x in sys.argv[sys.argv.index('--iso') + 1].split(',')] if '--iso' in sys.argv else None
    plan = P.plan(coarse=not fine, isos=isos) if isos else P.plan(coarse=not fine)
    takes = [t for t in plan['takes'] if t['phase'] == 1]
    takes.sort(key=lambda t: (t['code'], t['iso']))          # one recipe at a time, its ISOs in a row
    done = n = 0
    t0 = time.time()
    for t in takes:
        tag = f"p1-{'-'.join(t['stratum']).replace(':', '')}-iso{t['iso']}"
        if (TAKES / tag / 'take.json').exists():
            done += 1
            continue
        if (HERE / 'STOP').exists():
            print('STOP file: ending', flush=True)
            break
        if limit is not None and n >= limit:
            break
        if not ping():
            print(f'{tag}: NO PONG before the take: stopping', flush=True)
            return 2
        r = subprocess.run([sys.executable, '-B', str(HERE / 'take.py'), tag, t['code'], str(t['iso'])],
                           capture_output=True, text=True, cwd=HERE, timeout=400, env=os.environ)
        (TAKES.parent / 'logs').mkdir(exist_ok=True)
        (TAKES.parent / 'logs' / f'{tag}.txt').write_text(r.stdout + r.stderr)
        n += 1
        rec = dict(tag=tag, stratum=t['stratum'], iso=t['iso'], cell=t['cell'], label=t['label'], key=t['key'],
                   code=t['code'], rc=r.returncode)
        if r.returncode:
            err = [l for l in (r.stdout + r.stderr).splitlines() if l.strip() and not l.lstrip().startswith(
                ('code', 'verify', 'stage'))][-1:]
            rec['error'] = err[0][:200] if err else '?'
            with open(OUT, 'a') as f:
                f.write(json.dumps(rec) + '\n')
            print(f'{tag}: rc {r.returncode} {rec["error"]}', flush=True)
            if 'not the recipe' in rec['error'] or 'no frame 3 or 2' in rec['error']:
                continue                                    # this recipe only: go on
            return 3                                        # anything else: stop and look
        try:
            for name in ('f3', 'f1'):                       # frame 3 (or 2); frame 1 (uncompressed) when it is not valid
                p = TAKES / tag / f'{name}.DNG'
                if not p.exists():
                    continue
                d = dark.dark(p)
                rec.setdefault('checked', []).append(dict(frame=name, valid=d['valid'], flat_rows=d['flat_rows']))
                if d['valid']:
                    break
            if not d['valid']:
                raise ValueError('no valid frame')
            s = 4 if d['tag'] > 600 else 1
            rec.update(frame=name, bits=14 if s == 4 else 12, data=d['mean'] / s, tag_dng=d['tag'] / s,
                       err=(d['mean'] - d['tag']) / s, std=d['std'] / s, p_hi=d['p_hi'] / s,
                       take=json.loads((TAKES / tag / 'take.json').read_text()))
        except Exception as e:                              # the take is on disk; analysis can be redone
            rec['analysis_error'] = repr(e)[:200]
        with open(OUT, 'a') as f:
            f.write(json.dumps(rec) + '\n')
        el = time.time() - t0
        left = len(takes) - done - n
        print(f'{tag}: err {rec.get("err", float("nan")):+.3f}  ({done + n}/{len(takes)}, '
              f'{el / n:.0f} s/take, ~{left * el / n / 60:.0f} min left)', flush=True)
    print(f'end: {done} done before, {n} this run, {len(takes)} planned', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
