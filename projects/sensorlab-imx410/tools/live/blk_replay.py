#!/usr/bin/env python3
"""Replay a BlackLevel correction rule on every lens-capped take of 2026-11-16 (validation/20261116-blk-snap) before it
goes into ap_calc.c (Bei 11-16: "會不會修完把原本好的修壞也不知道").

    python3 -B blk_replay.py            # the release rule; exit 1 if it is worse than the gate

Each take carries its raw error (data black - the firmware's tag, DN12) and the pedestal at the time, so any rule can be
replayed offline.  The gate: no more takes worse than stock than the release rule had (11 of 431), and no larger mean.
Stock = the largest |error| of the stock FHD takes at that ISO (accept.jsonl + exp2.jsonl, 2..8 takes per ISO).
"""
import json, pathlib, statistics, sys

RUN = pathlib.Path(__file__).resolve().parents[2] / 'validation/20261116-blk-snap'
GATE = dict(worse_than_stock=11, mean=0.17)


def takes():
    rows = []
    for r in json.loads((RUN / 'summary-phase1.json').read_text()):       # recorded without the hook: raw = measured
        rows.append(dict(tag=r['tag'], iso=r['iso'], bits=r['bits'], one=r['stratum'][2] == '1:1', key=r['key'],
                         ped=r['ped'], raw=r['err']))
    for r in json.loads((RUN / 'blv/summary-iso.json').read_text()):      # with the first hook: raw reconstructed
        rows.append(dict(tag=r['tag'], iso=r['iso'], bits=r['bits'], one=r['stratum'][2] == '1:1', key=r['key'],
                         ped=r['ped'], raw=r['raw_err']))
    return rows


def stock():
    out = {}
    for name in ('blv/accept.jsonl', 'blv/exp2.jsonl'):
        for line in (RUN / name).read_text().splitlines():
            r = json.loads(line)
            if r['tag'].startswith('stock') and 'err' in r:
                out[r['iso']] = max(out.get(r['iso'], 0), abs(r['err']))
    return out


def release_rule(t):
    """ap_calc.c apc_blv table, DN12: (pedestal - 1024) / 4, and -0.375 for a 12-bit 1:1 record"""
    if not 1012 <= t['ped'] <= 1027:
        return 0.0
    return (t['ped'] - 1024) / 4 - (0.375 if t['bits'] == 12 and t['one'] else 0)


def score(rule, rows=None, st=None):
    rows, st = rows or takes(), st or stock()
    new = [t['raw'] - rule(t) for t in rows]
    a = sorted(abs(x) for x in new)
    return dict(n=len(a), mean=statistics.fmean(a), p90=a[int(.9 * len(a))], max=a[-1],
                worse_than_before=sum(abs(x) > abs(t['raw']) + 0.05 for t, x in zip(rows, new)),
                worse_than_stock=sum(abs(x) > st[t['iso']] for t, x in zip(rows, new)),
                above_025=sum(x > 0.25 for x in a))


def main():
    s = score(release_rule)
    print(json.dumps({k: round(v, 3) if isinstance(v, float) else v for k, v in s.items()}))
    ok = s['worse_than_stock'] <= GATE['worse_than_stock'] and s['mean'] <= GATE['mean']
    print('PASS' if ok else 'FAIL: worse than the release rule')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
