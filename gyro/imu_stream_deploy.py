#!/usr/bin/env python3
"""Put the IMU producers on the camera, all writing one ordered stream.

    ./imu_stream_deploy.py             arm every hook
    ./imu_stream_deploy.py --restore   put the firmware's instructions back
    ./imu_stream_deploy.py --reset     clear the counters before a take
    ./imu_stream_deploy.py --take      read what one take measured (twelve words)
    ./imu_stream_deploy.py --dump      read the stream itself
    ./imu_stream_deploy.py --rate 600  count gyro against the host clock

Five producers, five hook sites, one 8-byte record shape:

    gyro   tag 0    0xC00D0794   the 20 ms GyroData callback, drains the ring
    accel  tag 1    0xC050D498   the MMA8452Q driver publishing a sample
    frame  tag 2    0xC0315C18   FrameExpos_s, one per exposure
    start  tag 3    0xC01FBA28   recording begins (movRec tears down monitor audio)
    stop   tag 4    0xC01FB880   recording ends (the REC state is left)

Nothing writes over live code by accident: placement is checked against the
injection cave and against every other span before a byte goes out, because the
last time a probe landed on something that was running it cost four power
cycles to work out why.  `--dump` and `--take` are `mem read`; they are never
issued without being asked for.
"""
import argparse
import re
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'fp_usb_shell'))

import putfile as P                                            # noqa: E402
from armasm import assemble                                    # noqa: E402

import imu_stream as S                                         # noqa: E402

# The injection cave, from notes/: loader.S below, park stub above.
CAVE_LO, CAVE_HI = 0xC072E064, 0xC072EFA0

# name -> (code address, source, defines, hook site, the firmware's own word)
PRODUCERS = {
    'accel': (0xC072E100, 'accel_hook.S',       (),           0xC050D498, 0xE1D410F0),
    'gyro':  (0xC072EA00, 'gyro_stream_hook.S', (),           0xC00D0794, 0xFA046FD7),
    'frame': (0xC072EB40, 'frame_hook.S',       (),           0xC0315C18, 0xE58D0080),
    'start': (0xC072EBD0, 'rec_trigger.S',      (),           0xC01FBA28, 0xE5940008),
    'stop':  (0xC072EC60, 'rec_trigger.S',      ('REC_STOP',), 0xC01FB880, 0xE1A00004),
}

# Must agree with imu_stream.inc.S; _check_header() proves they do.
STATE_AT      = 0xC072E1D0
STATE_WORDS   = 12
STREAM_R1_GC  = 0xC072E1D0
STREAM_R1_N   = 0xC072E1D4
STREAM_FCOUNT = 0xC072E1E0
STREAM_F0_GC  = 0xC072E1E4
STREAM_R0_GC  = 0xC072E1E8
STREAM_R0_N   = 0xC072E1EC
STREAM_GHEAD  = 0xC072E1F0
STREAM_PADBAD = 0xC072E1F4
STREAM_INDEX  = 0xC072E1F8
STREAM_GCOUNT = 0xC072E1FC
STREAM_BASE   = 0xC072E200
STREAM_COUNT  = 256
STREAM_SPAN   = STREAM_COUNT * 8

# GHEAD unarmed, everything else zero.
STATE_INIT = struct.pack('<12I', 0, 0, 0, 0, 0, 0, 0, 0, 0xFFFFFFFF, 0, 0, 0)

GYRO_PERIOD_US = 400.0


def _check_header():
    """These constants are duplicated from the assembly; prove they match."""
    src = (HERE / 'imu_stream.inc.S').read_text()
    want = {
        'STREAM_R1_GC': STREAM_R1_GC, 'STREAM_R1_N': STREAM_R1_N,
        'STREAM_FCOUNT': STREAM_FCOUNT, 'STREAM_F0_GC': STREAM_F0_GC,
        'STREAM_R0_GC': STREAM_R0_GC, 'STREAM_R0_N': STREAM_R0_N,
        'STREAM_GHEAD': STREAM_GHEAD, 'STREAM_PADBAD': STREAM_PADBAD,
        'STREAM_INDEX': STREAM_INDEX, 'STREAM_GCOUNT': STREAM_GCOUNT,
        'STREAM_BASE': STREAM_BASE, 'STREAM_COUNT': STREAM_COUNT,
        'TAG_GYRO': S.TAG_GYRO, 'TAG_ACCEL': S.TAG_ACCEL,
        'TAG_FRAME': S.TAG_FRAME, 'TAG_START': S.TAG_START, 'TAG_STOP': S.TAG_STOP,
    }
    for name, value in want.items():
        m = re.search(rf'^\.equ\s+{name},\s*([^\s/@]+)', src, re.M)
        if not m:
            raise SystemExit(f'imu_stream.inc.S has no {name}')
        if int(m.group(1).rstrip(','), 0) != value:
            raise SystemExit(f'{name}: header says {m.group(1)}, this says {value:#x}')
    if STATE_AT + STATE_WORDS * 4 != STREAM_BASE:
        raise SystemExit('the state words do not end where the stream begins')

    # Each hook must carry the site it is deployed to, and end by performing the
    # instruction it displaced.  A site that drifts between the two is how a
    # branch lands inside something that is running.
    for name, (_at, source, defines, site, orig) in PRODUCERS.items():
        text = (HERE / source).read_text()
        if 'REC_STOP' in [d for d in defines]:
            text = text.split('#ifdef REC_STOP')[1].split('#else')[0]
        elif '#ifdef REC_STOP' in text:
            text = text.split('#else')[1].split('#endif')[0]
        if f'{site:#010X}'.replace('0X', '0x') not in text.replace('0X', '0x'):
            if f'0x{site:08X}' not in text:
                raise SystemExit(f'{name}: {source} does not mention site 0x{site:08X}')
        if f'0x{orig:08X}' not in text:
            raise SystemExit(f'{name}: {source} does not mention its displaced '
                             f'word 0x{orig:08X}')


def _place():
    """Assemble everything and check nothing lands on anything else."""
    code = {n: assemble(HERE / src, d) for n, (_a, src, d, _s, _o) in PRODUCERS.items()}
    spans = [(n, PRODUCERS[n][0], len(c)) for n, c in code.items()]
    spans += [('state words', STATE_AT, STATE_WORDS * 4),
              ('stream', STREAM_BASE, STREAM_SPAN)]
    for name, at, n in spans:
        if at < CAVE_LO or at + n > CAVE_HI:
            raise SystemExit(f'{name}: 0x{at:08X}..0x{at+n:08X} leaves the cave '
                             f'0x{CAVE_LO:08X}..0x{CAVE_HI:08X}')
    for i, (an, aa, al) in enumerate(spans):
        for bn, ba, bl in spans[i + 1:]:
            if aa < ba + bl and ba < aa + al:
                raise SystemExit(f'{an} and {bn} overlap')
    for name, at, n in sorted(spans, key=lambda s: s[1]):
        print(f'  {name:14s} 0x{at:08X}..0x{at+n:08X}  {n} bytes')
    return code


def arm():
    _check_header()
    code = _place()

    for name, (_at, _src, _d, site, orig) in PRODUCERS.items():
        got = P.mem_get(site)[0]
        if got is None:
            raise SystemExit(f'{name}: could not read 0x{site:08X}')
        if got != orig:
            raise SystemExit(f'{name}: 0x{site:08X} is 0x{got:08X}, not the '
                             f"firmware's 0x{orig:08X} -- something is already "
                             f'hooked there, refusing')

    for name, blob in code.items():
        P.put_slow(PRODUCERS[name][0], blob, name)
    P.put_slow(STATE_AT, STATE_INIT, 'state words')
    P.put_slow(STREAM_BASE, b'\0' * STREAM_SPAN, 'stream')

    for name, (at, _src, _d, site, _orig) in PRODUCERS.items():
        word = 0xEB000000 | (((at - (site + 8)) >> 2) & 0xFFFFFF)
        print(f'arming {name:6s} 0x{site:08X} -> bl 0x{at:08X}  (0x{word:08X})')
        for _ in range(8):
            P.mem_set(site, word)
            if P.mem_get(site)[0] == word:
                break
        else:
            raise SystemExit(f'{name}: the branch would not take')
    print(f'{len(PRODUCERS)} producers live')


def restore():
    for name, (_at, _src, _d, site, orig) in PRODUCERS.items():
        for _ in range(8):
            P.mem_set(site, orig)
            if P.mem_get(site)[0] == orig:
                print(f'{name:6s} 0x{site:08X} back to 0x{orig:08X}')
                break
        else:
            raise SystemExit(f'{name}: could not restore 0x{site:08X}')


def reset():
    """Clear the counters between takes without rewriting a byte of code.

    Arming re-writes the hooks, and rewriting live code is what killed the
    camera four times.  A take needs only the counters cleared: each latch fires
    again on its next first event, and the gyro producer re-anchors on the
    firmware's current head.
    """
    P.put_slow(STATE_AT, STATE_INIT, 'state words')
    # Not the stream.  It is a ring that overwrites itself in a hundred
    # milliseconds, so zeroing two kilobytes buys nothing -- and `mem set` drops
    # enough of five hundred writes that the retry pass fails outright.
    print('counters cleared -- the next start, and the next frame, are take zero')


def _ms(samples):
    return samples * GYRO_PERIOD_US / 1000.0


def take():
    """What one take measured.  Twelve words, no stream dump."""
    w = P.mem_get(STATE_AT, STATE_WORDS)
    if any(x is None for x in w):
        raise SystemExit('the state words did not read back whole')
    r1_gc, r1_n = w[0], w[1]
    fcount, f0_gc, r0_gc, r0_n = w[4], w[5], w[6], w[7]
    _ghead, padbad, index, gcount = w[8], w[9], w[10], w[11]

    print(f'records {index}   gyro {gcount}   bad pads {padbad}')
    print(f'starts {r0_n}   stops {r1_n}   frames {fcount}')
    print()

    if not r0_n:
        print('recording never began -- 0xC01FBA28 (movRec) did not fire.')
    if not fcount:
        print('no frame marker fired -- 0xC0315C18 is not on the exposure path,')
        print('  or nothing was exposed since the counters were cleared.')

    if r0_n and r1_n:
        d = r1_gc - r0_gc
        print(f'take: gyro {r0_gc} -> {r1_gc} = {d} samples = {_ms(d)/1000:.2f} s')
        print()

    if r0_n and fcount:
        d = f0_gc - r0_gc
        print(f'gyro sample at record start  {a0_gc}')
        print(f'gyro sample at first frame   {f0_gc}')
        print(f'  -> the first exposure is {d:+d} samples = {_ms(d):+.1f} ms '
              f'from the recorder committing to start')
        print('     (positive: the exposure is later, which is the direction our')
        print("      polled flag has always been early in)")
        print()

    if fcount >= 2:
        frames = fcount - 1
        samples = gcount - f0_gc
        per = samples / frames
        print(f'{samples} gyro over {frames} frames = {per:.4f} per frame')
        print("  if the clip is        the gyro rate in the camera's own clock is")
        for label, fps in (('29.97 fps', 30000 / 1001), ('59.94 fps', 60000 / 1001),
                           ('25 fps', 25.0), ('24 fps', 24.0)):
            hz = per * fps
            print(f'  {label:12s}          {hz:9.3f} Hz  ({hz / 2500 - 1:+.4%} of 2500)')




def dump(count):
    take()
    print()
    words = P.read_back(STREAM_BASE, STREAM_COUNT * 2)
    if any(w is None for w in words):
        raise SystemExit('the stream did not read back whole')
    recs = S.records(struct.pack(f'<{len(words)}I', *words))

    index = P.mem_get(STREAM_INDEX)[0]
    live = min(index, STREAM_COUNT)
    first = index % STREAM_COUNT
    order = ([(first + i) % STREAM_COUNT for i in range(live)]
             if index > STREAM_COUNT else list(range(live)))
    seq = [recs[i] for i in order]

    info = S.summary(seq)
    print(f"{live} records: {info['gyro']} gyro, {info['accel']} accel, "
          f"{info['frame']} frame, {info['start']} start, {info['stop']} stop"
          + (f", unknown tags {info['unknown']}" if info['unknown'] else ''))
    if info['per_accel']:
        print(f"one accel every {info['per_accel']:.0f} gyro "
              f"(2500 Hz against a measured 47.2 Hz is about 53)")
    gaps, per_frame = S.frame_spacing(seq)
    if per_frame:
        print(f"{per_frame:.2f} gyro per frame in the ring; spacings {gaps}")
    print(f"{info['duration_us'] / 1000:.1f} ms of gyro in the stream")
    for t, g, a, mark in S.rows(seq)[:count]:
        extra = f'   accel {a[0]:6d} {a[1]:6d} {a[2]:6d}' if a else ''
        m = f'   <- {mark[0].upper()} {mark[1]}' if mark else ''
        print(f'  {t:8.0f} us  {g[0]:7d} {g[1]:7d} {g[2]:7d}{extra}{m}')


def rate(total, step):
    """Count gyro records against a long baseline and fit a rate.

    A count is exact; the host's clock is not, so the uncertainty is entirely in
    the timestamps and the fit's residuals are what says how much of it there
    is.  A rate quoted without an error bar is how the notes ended up with two
    that disagree.  Note this measures the gyro against the HOST -- for the ratio
    that actually matters, against the camera's own frame clock, use --take.
    """
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
            print(f'  {dt:7.1f} s   {dn:9d} records   {dn / dt:9.3f} Hz')
        if time.time() >= t_end:
            break
        time.sleep(max(0.0, step - (time.time() - b)))

    if len(samples) < 3:
        raise SystemExit('too few samples to fit')
    n = len(samples)
    t0, c0 = samples[0][0], samples[0][1]
    xs = [t - t0 for t, _, _ in samples]
    ys = [float(c - c0) for _, c, _ in samples]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    icpt = my - slope * mx
    resid = [y - (slope * x + icpt) for x, y in zip(xs, ys)]
    se = (sum(r * r for r in resid) / (n - 2) / sxx) ** 0.5
    print()
    print(f'{n} samples over {xs[-1]:.1f} s')
    print(f'rate  {slope:.3f} +/- {se:.3f} Hz   ({slope / 2500 - 1:+.4%} of 2500)')


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--restore', action='store_true')
    g.add_argument('--reset', action='store_true')
    g.add_argument('--take', action='store_true')
    g.add_argument('--dump', action='store_true')
    g.add_argument('--rate', type=float, metavar='SECONDS')
    ap.add_argument('--rows', type=int, default=24)
    ap.add_argument('--step', type=float, default=30.0)
    a = ap.parse_args()
    if a.restore:
        restore()
    elif a.reset:
        reset()
    elif a.take:
        take()
    elif a.dump:
        dump(a.rows)
    elif a.rate:
        rate(a.rate, a.step)
    else:
        arm()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
