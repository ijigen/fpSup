#!/usr/bin/env python3
"""Phase-1 analysis: results-phase1.jsonl (+ each take's ring) -> the BlackLevel error by factor, and the candidate
fix tag' = tag + (pedestal - 1024) / 4 (DN12) tried on every take.

    python3 -B analyze.py [--json summary.json]
"""
import collections, json, pathlib, statistics, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'tools/live'))
import blk_snap as D                                       # noqa: E402


def load():
    out = []
    for line in (HERE / 'results-phase1.jsonl').read_text().splitlines():
        r = json.loads(line)
        if 'err' not in r:
            continue
        ring = HERE / 'takes' / r['tag'] / 'ring.bin'
        try:
            _, recs = D.parse(ring.read_bytes())
            last = D.row(recs[-1])
            r['ped'], r['branch'], r['ob'], r['lock'] = last['ped'], last['branch'], last['ob_b'], last['lock']
            r['fixed_err'] = r['err'] - (r['ped'] - 1024) / 4
        except Exception as e:                              # noqa: BLE001
            r['ring_error'] = repr(e)[:100]
        out.append(r)
    return out


def stats(v):
    v = sorted(v)
    return dict(n=len(v), mean=statistics.fmean(v), lo=v[0], hi=v[-1])


def table(rows, key, title):
    g = collections.defaultdict(list)
    for r in rows:
        g[key(r)].append(r)
    print(f'\n{title}')
    print('  %-34s %3s  %8s %7s %7s | %8s %7s %7s' % ('', 'n', 'err', 'lo', 'hi', 'fixed', 'lo', 'hi'))
    for k in sorted(g, key=str):
        e = stats([r['err'] for r in g[k]])
        f = [r['fixed_err'] for r in g[k] if 'fixed_err' in r]
        fs = stats(f) if f else None
        print('  %-34s %3d  %+8.3f %+7.3f %+7.3f | %s' % (k, e['n'], e['mean'], e['lo'], e['hi'],
              '%+8.3f %+7.3f %+7.3f' % (fs['mean'], fs['lo'], fs['hi']) if fs else '-'))
    return g


def main():
    rows = load()
    bad = [json.loads(l) for l in (HERE / 'results-phase1.jsonl').read_text().splitlines() if 'err' not in json.loads(l)]
    print(f'{len(rows)} takes measured, {len(bad)} without a measurement')
    table(rows, lambda r: (r['bits'], r['stratum'][1], r['stratum'][2]), 'recorded bits x video clamp x path')
    table(rows, lambda r: (r['bits'], r['stratum'][1], r['iso']), 'recorded bits x video clamp x ISO')
    table(rows, lambda r: (r['bits'], r['stratum'][1], r.get('ped')), 'recorded bits x video clamp x pedestal')
    table(rows, lambda r: (r['stratum'][0], r['stratum'][1]), 'readout family x video clamp')
    worst = sorted(rows, key=lambda r: abs(r['err']), reverse=True)[:12]
    print('\nlargest |err|')
    for r in worst:
        print('  %-40s iso %4d bits %d err %+6.3f ped %s fixed %s  %s %s' % (
            r['tag'], r['iso'], r['bits'], r['err'], r.get('ped'),
            '%+6.3f' % r['fixed_err'] if 'fixed_err' in r else '-', r['cell'], r['label']))
    for b in bad:
        print('  no measurement:', b['tag'], b.get('error') or b.get('analysis_error'))
    if '--json' in sys.argv:
        pathlib.Path(sys.argv[sys.argv.index('--json') + 1]).write_text(json.dumps(rows, indent=1) + '\n')


if __name__ == '__main__':
    main()
