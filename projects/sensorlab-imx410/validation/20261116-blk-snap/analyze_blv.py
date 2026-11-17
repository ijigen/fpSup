#!/usr/bin/env python3
"""Takes recorded WITH H_BLV: per take, what the hook added (DNG tag - the firmware's own value from the ring), whether
that equals the table entry for the take's pedestal, the raw (uncorrected) error, and the sensor gain word.

    python3 -B analyze_blv.py blv/results-iso.jsonl blv/takes-iso      # or blv/accept.jsonl blv/takes
"""
import collections, json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'tools/live'))
import blk_snap as D                                        # noqa: E402


def table_d(bits, one, ped):
    """the producer's table (ap_calc.c apc_blv_table), in DN at the tag's depth"""
    if not 1012 <= ped <= 1027:
        return 0.0
    return (ped - 1024) if bits == 14 else (ped - 1024) / 4 - (0.375 if one else 0)


def load(results, takes):
    out = []
    for line in pathlib.Path(results).read_text().splitlines():
        r = json.loads(line)
        if 'err' not in r or r['tag'].startswith('stock'):
            continue
        ring = pathlib.Path(takes) / r['tag'] / 'ring.bin'
        if not ring.exists():
            continue
        _, recs = D.parse(ring.read_bytes())
        last = recs[-1]
        row = D.row(last)
        bits = r['bits']
        s = 4 if bits == 14 else 1
        fw = row['fw'] * s if row['fw'] is not None else None           # the firmware's tag value, tag units
        one = r.get('stratum', [None, None, '1:1'])[2] == '1:1' if 'stratum' in r else None
        r.update(ped=row['ped'], gain=last['sensor_gain'], fw_tag=fw,
                 applied=(r['tag_dng'] * s - fw) if fw is not None else None)
        if one is not None:
            r['table'] = table_d(bits, one, row['ped'])
            r['raw_err'] = r['err'] + r['table'] / s                    # what the error was before the hook
        out.append(r)
    return out


def main():
    rows = load(sys.argv[1], sys.argv[2])
    bad = [r for r in rows if r.get('table') is not None and r['applied'] is not None
           and abs(r['applied'] - r['table']) > 0.002]
    print(f'{len(rows)} takes; hook added != table entry: {len(bad)}')
    for r in bad[:10]:
        print('   ', r['tag'], 'applied', round(r['applied'], 4), 'table', r['table'], 'ped', r['ped'])
    g = collections.defaultdict(set)
    for r in rows:
        g[r['iso']].add(r['gain'])
    print('sensor gain word by ISO:', {k: sorted(v) for k, v in sorted(g.items())})
    by = collections.defaultdict(list)
    for r in rows:
        if 'raw_err' in r:
            by[r['iso']].append(r)
    for iso in sorted(by):
        v = by[iso]
        print('ISO %5d n %3d  after |err| mean %.3f max %.3f   raw |err| mean %.3f max %.3f' % (
            iso, len(v), sum(abs(r['err']) for r in v) / len(v), max(abs(r['err']) for r in v),
            sum(abs(r['raw_err']) for r in v) / len(v), max(abs(r['raw_err']) for r in v)))
    if '--json' in sys.argv:
        pathlib.Path(sys.argv[sys.argv.index('--json') + 1]).write_text(json.dumps(rows, indent=1) + '\n')


if __name__ == '__main__':
    main()
