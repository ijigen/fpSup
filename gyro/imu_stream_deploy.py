#!/usr/bin/env python3
"""Put both IMU producers on the camera, writing one ordered stream.

    ./imu_stream_deploy.py            arm both hooks
    ./imu_stream_deploy.py --restore  put the firmware's instructions back
    ./imu_stream_deploy.py --dump     read the stream and report the interleave

The two hooks are separate test units that share a record shape and an index.
`--dump` is a `mem read`; it is never issued without being asked for.

Nothing here writes over live code by accident: the placement is checked against
the injection cave and against the stream's own span before a single word goes
out, because the last time a probe landed on something that was running it cost
four power cycles to work out why.
"""
import argparse
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'fp_usb_shell'))

import putfile as P                                            # noqa: E402
from armasm import assemble                                    # noqa: E402

import imu_stream as S                                         # noqa: E402

# The injection cave, from notes/: loader.S below, park stub above.
CAVE_LO, CAVE_HI = 0xC072E064, 0xC072EFA0

ACCEL_AT = 0xC072E100
GYRO_AT  = 0xC072EA00

# Must agree with imu_stream.inc.S; _check_header() proves they do.
STREAM_GHEAD  = 0xC072E1F0
STREAM_PADBAD = 0xC072E1F4
STREAM_INDEX  = 0xC072E1F8
STREAM_GCOUNT = 0xC072E1FC
STREAM_BASE   = 0xC072E200
STREAM_COUNT  = 256
STREAM_SPAN   = STREAM_COUNT * 8

# hook site -> the firmware's own word there
SITES = {
    'accel': (0xC050D498, 0xE1D410F0),      # ldrsh r1, [r4]
    'gyro':  (0xC00D0794, 0xFA046FD7),      # blx   0xC01EC6F8
}

TAG_GYRO, TAG_ACCEL = 0, 1


def _check_header():
    """The constants above are duplicated from the assembly; prove they match."""
    src = (HERE / 'imu_stream.inc.S').read_text()
    want = {'STREAM_GHEAD': STREAM_GHEAD, 'STREAM_PADBAD': STREAM_PADBAD,
            'STREAM_INDEX': STREAM_INDEX, 'STREAM_GCOUNT': STREAM_GCOUNT,
            'STREAM_BASE': STREAM_BASE,
            'STREAM_COUNT': STREAM_COUNT, 'TAG_GYRO': TAG_GYRO,
            'TAG_ACCEL': TAG_ACCEL}
    for name, value in want.items():
        m = re.search(rf'^\.equ\s+{name},\s*(\S+)', src, re.M)
        if not m:
            raise SystemExit(f'imu_stream.inc.S has no {name}')
        if int(m.group(1).rstrip(','), 0) != value:
            raise SystemExit(f'{name}: header says {m.group(1)}, this says {value:#x}')


def _place():
    """Assemble both and check nothing lands on anything else."""
    code = {'accel': assemble(HERE / 'accel_hook.S'),
            'gyro': assemble(HERE / 'gyro_stream_hook.S')}
    spans = [('accel_hook', ACCEL_AT, len(code['accel'])),
             ('gyro_stream_hook', GYRO_AT, len(code['gyro'])),
             ('stream words', STREAM_GHEAD, 16),
             ('stream', STREAM_BASE, STREAM_SPAN)]
    for name, at, n in spans:
        if at < CAVE_LO or at + n > CAVE_HI:
            raise SystemExit(f'{name}: 0x{at:08X}..0x{at+n:08X} leaves the cave '
                             f'0x{CAVE_LO:08X}..0x{CAVE_HI:08X}')
    for i, (an, aa, al) in enumerate(spans):
        for bn, ba, bl in spans[i + 1:]:
            if aa < ba + bl and ba < aa + al:
                raise SystemExit(f'{an} and {bn} overlap')
    for name, at, n in spans:
        print(f'  {name:18s} 0x{at:08X}..0x{at+n:08X}  {n} bytes')
    return code


def _put(addr, blob, label):
    P.put_slow(addr, blob, label)


def arm():
    _check_header()
    code = _place()

    for name, (site, orig) in SITES.items():
        got = P.mem_get(site)[0]
        if got is None:
            raise SystemExit(f'{name}: could not read 0x{site:08X}')
        if got != orig:
            raise SystemExit(f'{name}: 0x{site:08X} is 0x{got:08X}, not the '
                             f'firmware\'s 0x{orig:08X} -- something is already '
                             f'hooked there, refusing')

    _put(ACCEL_AT, code['accel'], 'accel_hook')
    _put(GYRO_AT, code['gyro'], 'gyro_stream_hook')

    # State before either hook can run: an unarmed head makes the gyro producer
    # take the firmware's current head on its first visit and drop the history.
    _put(STREAM_GHEAD, struct.pack('<4I', 0xFFFFFFFF, 0, 0, 0), 'stream words')
    _put(STREAM_BASE, b'\0' * STREAM_SPAN, 'stream')

    for name, (site, _orig) in SITES.items():
        at = ACCEL_AT if name == 'accel' else GYRO_AT
        word = 0xEB000000 | (((at - (site + 8)) >> 2) & 0xFFFFFF)
        print(f'arming {name}: 0x{site:08X} -> bl 0x{at:08X}  (0x{word:08X})')
        for _ in range(8):
            P.mem_set(site, word)
            if P.mem_get(site)[0] == word:
                break
        else:
            raise SystemExit(f'{name}: the branch would not take')
    print('both producers live')


def restore():
    for name, (site, orig) in SITES.items():
        for _ in range(8):
            P.mem_set(site, orig)
            if P.mem_get(site)[0] == orig:
                print(f'{name}: 0x{site:08X} back to 0x{orig:08X}')
                break
        else:
            raise SystemExit(f'{name}: could not restore 0x{site:08X}')


def dump(count):
    ghead, padbad, index, gcount = P.mem_get(STREAM_GHEAD, 4)
    print(f'gyro head 0x{ghead:08X}   index {index}   gyro {gcount}   '
          f'bad pads {padbad}')
    if padbad:
        print('  ^ the gyro ring put something in the pad halfword: the tag is '
              'not free after all, and the format has to move')
    if not index:
        print('nothing has been written')
        return

    words = P.read_back(STREAM_BASE, STREAM_COUNT * 2)
    if any(w is None for w in words):
        raise SystemExit('the stream did not read back whole')
    blob = struct.pack(f'<{len(words)}I', *words)
    recs = S.records(blob)

    # The index is monotonic, so the next slot to be written is also the oldest
    # record still standing.
    live = min(index, STREAM_COUNT)
    first = index % STREAM_COUNT
    order = [(first + i) % STREAM_COUNT for i in range(live)] if index > STREAM_COUNT \
        else list(range(live))
    seq = [recs[i] for i in order]

    info = S.summary(seq)
    print(f"{live} records: {info['gyro']} gyro, {info['accel']} accel"
          + (f", unknown tags {info['unknown']}" if info['unknown'] else ''))
    if info['per_accel']:
        print(f"one accel every {info['per_accel']:.0f} gyro "
              f"(2500 Hz against a measured 47.2 Hz is about 53)")
    print(f"{info['duration_us'] / 1000:.1f} ms of gyro in the stream")

    for (t, g, a), slot in zip(S.rows(seq), order):
        if count <= 0:
            break
        count -= 1
        extra = f'   accel {a[0]:6d} {a[1]:6d} {a[2]:6d}' if a else ''
        print(f'  [{slot:3d}] {t:8.0f} us  {g[0]:7d} {g[1]:7d} {g[2]:7d}{extra}')


def rate(total, step):
    """Count gyro records against a long baseline and fit a rate.

    A count is exact; the clock is not.  So the uncertainty is entirely in the
    host's timestamps, and the fit's residuals are what says how much of it
    there is -- rather than a single pair of reads and a number with no error
    bar, which is how the notes ended up with two rates that disagree.
    """
    import time

    samples = []
    t_end = time.time() + total
    while True:
        a = time.time()
        got = P.mem_get(STREAM_GCOUNT)[0]
        b = time.time()
        if got is None:
            raise SystemExit('the counter did not read back')
        samples.append(((a + b) / 2, got, (b - a) / 2))
        if len(samples) > 1:
            dt = samples[-1][0] - samples[0][0]
            dn = samples[-1][1] - samples[0][1]
            print(f'  {dt:7.1f} s   {dn:9d} records   {dn / dt:9.3f} Hz'
                  f'   (+/- {samples[-1][2] * 1000:.0f} ms on this read)')
        if time.time() >= t_end:
            break
        time.sleep(max(0.0, step - (time.time() - b)))

    if len(samples) < 3:
        raise SystemExit('too few samples to fit')

    n = len(samples)
    t0 = samples[0][0]
    xs = [t - t0 for t, _, _ in samples]
    ys = [float(c - samples[0][1]) for _, c, _ in samples]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    icpt = my - slope * mx
    resid = [y - (slope * x + icpt) for x, y in zip(xs, ys)]
    se = (sum(r * r for r in resid) / (n - 2) / sxx) ** 0.5 if n > 2 else 0.0

    print()
    print(f'{n} samples over {xs[-1]:.1f} s')
    print(f'rate  {slope:.3f} +/- {se:.3f} Hz   ({slope / 2500 - 1:+.4%} of 2500)')
    worst = max(abs(r) for r in resid)
    print(f'worst residual {worst:.0f} records = {worst / slope * 1000:.0f} ms of clock')
    for label, hz in (('2500.00 exact', 2500.0), ('2500.50 (+0.02%)', 2500.5),
                      ('2501.85 (+0.074%)', 2501.85)):
        drift = (slope / hz - 1) * 180 * 1000
        print(f'  against {label:20s} 3 min would drift {drift:+7.1f} ms'
              f'  ({drift / 33.367:+.1f} frames at 29.97)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--restore', action='store_true')
    ap.add_argument('--dump', action='store_true')
    ap.add_argument('--rows', type=int, default=24)
    ap.add_argument('--rate', type=float, metavar='SECONDS',
                    help='count gyro records for this long and fit a rate')
    ap.add_argument('--step', type=float, default=30.0)
    a = ap.parse_args()
    if a.rate:
        rate(a.rate, a.step)
    elif a.restore:
        restore()
    elif a.dump:
        dump(a.rows)
    else:
        arm()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
