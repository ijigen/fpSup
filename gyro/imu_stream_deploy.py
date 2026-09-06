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
    vd     tag 5    0xC0125480   the sensor Vd frame IRQ, the exposure itself

FrameExpos_s (0xC0315C18) was tried first and removed: it fired zero times in
liveview and zero times through a recording, so it is not on the exposure path.
The Vd interrupt is.
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

# name -> (code address, source, defines, hook site, firmware's word, thumb?)
PRODUCERS = {
    # 0xC072E100 is where this hook has always been, and the default build
    # must stay there: the whole cave is inside the release logger's 3860
    # bytes, so moving a hook moves which of the logger's bytes we overwrite.
    # Putting it at 0xC072E900 gave a four second freeze with a LENS ERROR,
    # which is what overwriting something live looks like.  Only the
    # ACC_MEASURE build, which is 260 bytes and cannot fit under T_BYTES at
    # 0xC072E180, moves -- and when it does, it moves on its own.
    'accel': (0xC072E100, 'accel_hook.S',       (),            0xC050D498, 0xE1D410F0, 0),
    # Not a hook: the space provider the producers call.  It is the only thing
    # in the cave that knows the ring is a row of buffers.
    'space': (0xC072E900, 'stream_space.S',      (),            None,       None,       0),
    'gyro':  (0xC072E300, 'gyro_stream_hook.S', (),            0xC00D0794, 0xFA046FD7, 0),
    'start': (0xC072E4E0, 'rec_trigger.S',      (),            0xC01FBA28, 0xE5940008, 0),
    'stop':  (0xC072E620, 'rec_trigger.S',      ('REC_STOP',), 0xC01FB880, 0xE1A00004, 0),
    'vd':    (0xC072E710, 'vd_hook.S',          (),            0xC0125480, 0x341DF2CC, 1),
}


def _symbols(src):
    """Offsets of the global symbols in a blob, so the callers can be pointed
    at them: the space provider lives in the cave but the hooks that call it are
    separate blobs, so a branch cannot reach it by assembly alone."""
    from armasm import _compile, _parse
    elf, _sections, by_name = _parse(_compile(src))
    _, symtab = by_name['.symtab']
    _, strtab = by_name['.strtab']
    out = {}
    for off in range(symtab[4], symtab[4] + symtab[5], 16):
        name_off, value, _size, _info, _other, _shndx = struct.unpack_from(
            '<IIIBBH', elf, off)
        end = elf.index(b'\0', strtab[4] + name_off)
        name = elf[strtab[4] + name_off:end].decode()
        if name in ('stream_claim', 'stream_commit'):
            out[name] = value
    if len(out) != 2:
        raise SystemExit(f'stream_space.S is missing {out}')
    return out


def branch_word(site, target, thumb):
    """The word to write over the hook site.

    ARM sites take a plain bl.  The Vd handler is Thumb, so it takes a Thumb
    BLX -- two halfwords with the immediate split across them and J1/J2 derived
    from the sign.  Encoding that wrong gives a branch into the middle of
    something rather than a fault, so the test suite decodes the firmware's own
    bl at 0xC0125494 (which the decompilation names FUN_c0128e50) to fix the bit
    layout, then round-trips this.
    """
    if not thumb:
        return 0xEB000000 | (((target - (site + 8)) >> 2) & 0xFFFFFF)
    if target & 3:
        raise SystemExit(f'a Thumb BLX target must be 4-byte aligned: {target:#x}')
    off = target - ((site + 4) & ~3)
    if not -(1 << 24) <= off < (1 << 24) or off & 3:
        raise SystemExit(f'Thumb BLX offset {off:#x} out of range')
    s_ = (off >> 24) & 1
    i1, i2 = (off >> 23) & 1, (off >> 22) & 1
    j1, j2 = (~i1 & 1) ^ s_, (~i2 & 1) ^ s_
    hw1 = 0xF000 | (s_ << 10) | ((off >> 12) & 0x3FF)
    hw2 = 0xC000 | (j1 << 13) | (j2 << 11) | (((off >> 2) & 0x3FF) << 1)
    return hw1 | (hw2 << 16)

# Must agree with imu_stream.inc.S; _check_header() proves they do.
STATE_AT      = 0xC072E1B0
STATE_WORDS   = 20
STREAM_VSUM   = 0xC072E1B0
STREAM_VNF    = 0xC072E1B4
STREAM_VSHORT = 0xC072E1B8
STREAM_VOMAX  = 0xC072E1BC
STREAM_V0_GC  = 0xC072E1C0
STREAM_VCOUNT = 0xC072E1C4
STREAM_V1_N   = 0xC072E1C8
STREAM_VPREV  = 0xC072E1CC
STREAM_VMIN   = 0xC072E1D8
STREAM_VMAX   = 0xC072E1DC
STREAM_R0_HEAD = 0xC072E1E0
STREAM_V0_HEAD = 0xC072E1E4
GYRO_RING_SPAN = 0x12C0
STREAM_R1_GC  = 0xC072E1D0
STREAM_R1_N   = 0xC072E1D4
STREAM_R0_GC  = 0xC072E1E8
STREAM_R0_N   = 0xC072E1EC
STREAM_GHEAD  = 0xC072E1F0
STREAM_PADBAD = 0xC072E1F4
STREAM_INDEX  = 0xC072E1F8
STREAM_GCOUNT = 0xC072E1FC
STREAM_RING   = 0xC072E1A0
STREAM_TAIL   = 0xC072E1A4
STREAM_SIGFN  = 0xC072E1A8
STREAM_DONE     = 0xC072EA6C
STREAM_CLAIMFN  = 0xC072EA70
STREAM_COMMITFN = 0xC072EA74
STREAM_BASE   = 0xC072E200
POOL_PTR      = 0xC3757A7C
RING_POOL_OFF = 0x20000
RING_RECORDS  = 16384
RING_BYTES    = 16384 * 8
STREAM_COUNT  = 32
STREAM_SPAN   = STREAM_COUNT * 8

# GHEAD unarmed, everything else zero.
STATE_INIT = struct.pack('<20I', *([0] * 16 + [0xFFFFFFFF, 0, 0, 0]))

ACC_CODE_AT   = 0xC072E900   # only the measuring build needs the room
ACC_STATE     = 0xC072E8C0
ACC_WORDS     = 5
ACC_DANGER    = 500
# GHEAD unarmed, then max/count/sum/over.
ACC_INIT = struct.pack('<5I', 0xFFFFFFFF, 0, 0, 0, 0)

GYRO_PERIOD_US = 400.0


def _check_header():
    """These constants are duplicated from the assembly; prove they match."""
    src = (HERE / 'imu_stream.inc.S').read_text()
    want = {
        'STREAM_VSUM': STREAM_VSUM, 'STREAM_VNF': STREAM_VNF,
        'STREAM_VSHORT': STREAM_VSHORT, 'STREAM_VOMAX': STREAM_VOMAX, 'STREAM_V0_GC': STREAM_V0_GC, 'STREAM_VCOUNT': STREAM_VCOUNT,
        'STREAM_V1_N': STREAM_V1_N, 'STREAM_VPREV': STREAM_VPREV,
        'STREAM_VMIN': STREAM_VMIN, 'STREAM_VMAX': STREAM_VMAX,
        'STREAM_R0_HEAD': STREAM_R0_HEAD, 'STREAM_V0_HEAD': STREAM_V0_HEAD,
        'GYRO_RING_SPAN': GYRO_RING_SPAN,
        'STREAM_R1_GC': STREAM_R1_GC, 'STREAM_R1_N': STREAM_R1_N,
        'TAG_VD': S.TAG_VD,
        'STREAM_R0_GC': STREAM_R0_GC, 'STREAM_R0_N': STREAM_R0_N,
        'STREAM_GHEAD': STREAM_GHEAD, 'STREAM_PADBAD': STREAM_PADBAD,
        'STREAM_INDEX': STREAM_INDEX, 'STREAM_GCOUNT': STREAM_GCOUNT,
        'ACC_STATE': ACC_STATE, 'ACC_WORDS': ACC_WORDS,
        'ACC_DANGER': ACC_DANGER,
        'STREAM_RING': STREAM_RING, 'STREAM_TAIL': STREAM_TAIL,
        'STREAM_SIGFN': STREAM_SIGFN, 'RING_RECORDS': RING_RECORDS,
        'RING_POOL_OFF': RING_POOL_OFF,
        'STREAM_BASE': STREAM_BASE, 'STREAM_COUNT': STREAM_COUNT,
        'TAG_GYRO': S.TAG_GYRO, 'TAG_ACCEL': S.TAG_ACCEL,
        'TAG_START': S.TAG_START, 'TAG_STOP': S.TAG_STOP,
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
    for name, (_at, source, defines, site, orig, _t) in PRODUCERS.items():
        if site is None:
            continue                    # not a hook: placed code the hooks call
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


def _place(measure_accel=False):
    """Assemble everything and check nothing lands on anything else."""
    global PRODUCERS
    if measure_accel:
        a = PRODUCERS['accel']
        PRODUCERS = dict(PRODUCERS, accel=(ACC_CODE_AT,) + a[1:])

    def defines(name, d):
        # Off by default, and deliberately so: it is the only difference
        # between this build and the one the layered bisection is walking,
        # and a bisect with two variables in it is not a bisect.
        return d + ('ACC_MEASURE',) if (name == 'accel' and measure_accel) else d
    code = {n: assemble(HERE / src, defines(n, d))
            for n, (_a, src, d, _s, _o, _t) in PRODUCERS.items()}
    spans = [(n, PRODUCERS[n][0], len(c)) for n, c in code.items()]
    spans += [('state words', STATE_AT, STATE_WORDS * 4),
              ('accel state', ACC_STATE, ACC_WORDS * 4),
              # ring_task_deploy owns these, but only this script knows
              # where the hooks land -- so the overlap check lives here.
              ('writer counters', 0xC072E8E0, 5 * 4),
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


def _setw(addr, value, what):
    for _ in range(8):
        P.mem_set(addr, value)
        if (P.mem_get(addr) or [0])[0] == value:
            return
    raise SystemExit(f'could not write {what} at 0x{addr:08X}')


def resolve_ring():
    """Where the ring goes -- and prove it before 20 KB/s starts landing there.

    A range check is not enough.  The pool pointer came back as two different
    values in one boot with no reboot between them, and the second was inside
    the plausible range: a garbled read passes `0x4xxxxxxx` as easily as a real
    one.  Arming the producers on a wrong base points five hooks at whatever
    happens to live there, at two and a half thousand records a second, and the
    camera does not survive it.

    So: agree three times, then write a marker at each end of the span and read
    it back.  That proves the address is real, writable, and that the whole ring
    fits -- which the pointer alone never did.
    """
    seen = [P.mem_get(POOL_PTR)[0] for _ in range(3)]
    if len(set(seen)) != 1:
        print(f'the pool pointer read back differently three times: '
              + ', '.join(f'0x{v:08X}' if v else str(v) for v in seen))
        return None
    pool = seen[0]
    if not pool or not 0x40000000 <= pool < 0x50000000:
        print(f'the pool pointer reads 0x{pool or 0:08X}')
        return None
    ring = pool + RING_POOL_OFF
    for addr, mark in ((ring, 0x5AA5C33C), (ring + RING_BYTES - 4, 0xC33C5AA5)):
        for _ in range(6):
            P.mem_set(addr, mark)
            if (P.mem_get(addr) or [0])[0] == mark:
                break
        else:
            print(f'0x{addr:08X} would not hold a marker; the ring is not there')
            return None
    print(f'pool 0x{pool:08X}, ring proved writable at both ends')
    return ring


def arm(only=None, measure_accel=False):
    """Arm the producers.  `only` names a subset -- the record triggers sit
    INSIDE the firmware's audio teardown and rebuild, so being able to leave
    them out is how one tells whether they are what broke the audio."""
    _check_header()
    code = _place(measure_accel)

    for name, (_at, _src, _d, site, orig, _t) in PRODUCERS.items():
        if site is None:
            continue
        got = P.mem_get(site)[0]
        if got is None:
            raise SystemExit(f'{name}: could not read 0x{site:08X}')
        if got != orig:
            raise SystemExit(f'{name}: 0x{site:08X} is 0x{got:08X}, not the '
                             f"firmware's 0x{orig:08X} -- something is already "
                             f'hooked there, refusing')

    for name, blob in code.items():
        if only and name not in only:
            continue
        P.put_slow(PRODUCERS[name][0], blob, name)
    P.put_slow(STATE_AT, STATE_INIT, 'state words')
    if measure_accel:
        P.put_slow(ACC_STATE, ACC_INIT, 'accel interval counters')
    P.put_slow(STREAM_BASE, b'\0' * STREAM_SPAN, 'stream')

    # The real ring lives in the pool, whose address is only known now.  Memory
    # from the firmware's allocator freezes the camera when held across a
    # recording start; the pool does not, and pool+0x20000 is inside the 896 KB
    # that survived 224 of 224 markers.
    ring = resolve_ring()
    if ring:
        _setw(STREAM_RING, ring, 'the ring base')
        print(f'ring: 0x{ring:08X}, {RING_RECORDS} records = '
              f'{RING_RECORDS * 8 // 1024} KiB = {RING_RECORDS / 2500:.1f} s')
    else:
        _setw(STREAM_RING, 0, 'the ring base')
        print(f'staying on the {STREAM_COUNT}-record bench ring in the cave')
    _setw(STREAM_TAIL, 0, 'the ring tail')
    _setw(STREAM_DONE, 0, 'the committed count')

    # The producers call these; only the deployer knows where they landed.
    syms = _symbols(HERE / 'stream_space.S')
    base = PRODUCERS['space'][0]
    _setw(STREAM_CLAIMFN, base + syms['stream_claim'], 'stream_claim')
    _setw(STREAM_COMMITFN, base + syms['stream_commit'], 'stream_commit')

    for name, (at, _src, _d, site, _orig, thumb) in PRODUCERS.items():
        if site is None:
            continue                    # nothing to arm: it is called, not hooked
        if only and name not in only:
            print(f'skipping {name}')
            continue
        word = branch_word(site, at, thumb)
        kind = 'blx' if thumb else 'bl '
        print(f'arming {name:6s} 0x{site:08X} -> {kind} 0x{at:08X}  (0x{word:08X})')
        for _ in range(8):
            P.mem_set(site, word)
            if P.mem_get(site)[0] == word:
                break
        else:
            raise SystemExit(f'{name}: the branch would not take')
    print(f'{len(PRODUCERS)} producers live')


def restore():
    for name, (_at, _src, _d, site, orig, _t) in PRODUCERS.items():
        if site is None:
            continue
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
    P.put_slow(ACC_STATE, ACC_INIT, 'accel interval counters')
    # The tail sits outside the block because it is configuration-adjacent, but
    # it MUST be cleared with the index: a zeroed head against a stale tail
    # underflows and rings the doorbell without pause.
    _setw(STREAM_TAIL, 0, 'the ring tail')
    _setw(STREAM_DONE, 0, 'the committed count')

    # The producers call these; only the deployer knows where they landed.
    syms = _symbols(HERE / 'stream_space.S')
    base = PRODUCERS['space'][0]
    _setw(STREAM_CLAIMFN, base + syms['stream_claim'], 'stream_claim')
    _setw(STREAM_COMMITFN, base + syms['stream_commit'], 'stream_commit')
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
    vsum, vnf, vshort, vomax = w[0], w[1], w[2], w[3]
    v0_gc, vcount, v1_n = w[4], w[5], w[6]
    vmin, vmax = w[10], w[11]
    r1_gc, r1_n = w[8], w[9]
    r0_head, v0_head, r0_gc, r0_n = w[12], w[13], w[14], w[15]
    _ghead, padbad, index, gcount = w[16], w[17], w[18], w[19]

    ring, tail = P.mem_get(STREAM_RING)[0], P.mem_get(STREAM_TAIL)[0]
    where = f'pool 0x{ring:08X}' if ring else 'the bench ring'
    print(f'records {index}   gyro {gcount}   bad pads {padbad}')
    print(f'ring {where}   tail {tail}   waiting {index - tail} records')
    print(f'starts {r0_n}   stops {r1_n}   Vd now {vcount}, in the take {v1_n}')
    print()

    if not r0_n:
        print('recording never began -- 0xC01FBA28 (movRec) did not fire.')
    if not vcount:
        print('no Vd fired -- 0xC0125480 is not the frame interrupt, or the')
        print('  Thumb BLX did not take.  Vd free-runs in liveview, so a live')
        print('  hook shows a count even with the camera idle.')

    if r0_n and r1_n:
        d = r1_gc - r0_gc
        print(f'take: gyro {r0_gc} -> {r1_gc} = {d} samples = {_ms(d)/1000:.2f} s')
        print()

    if r0_n and vcount:
        # The ring head wraps every 240 ms; the gap we are measuring is a small
        # fraction of that, so the modulo is the whole correction needed.
        d = ((v0_head - r0_head) % GYRO_RING_SPAN) // 8
        print(f'ring head at record start   {r0_head} (+{r0_head//8} samples)')
        print(f'ring head at first exposure {v0_head} (+{v0_head//8} samples)')
        print(f'  -> the first frame is read out {d} samples = {_ms(d):.1f} ms '
              f'after the recorder commits')
        print(f'     (400 us resolution: this comes from the ring the coprocessor')
        print(f'      writes, not from our 20 ms batch counter)')
        print()
        if vnf:
            mean = vsum / vnf
            print(f'gaps between exposures: {v1_n - 1} total, '
                  f'{vnf} long enough to be a frame, {vshort} too short')
            print(f'  min {vmin}  max {vmax}')
            print(f'  mean {mean:.4f} gyro samples per frame  '
                  f'({vsum} samples over {vnf} gaps)')
            if vshort:
                print(f'  the {vshort} short ones are doubled interrupts, longest {vomax}')
                if vomax:
                    print(f'    the longest was {vomax}, so a doubled interrupt does '
                          f'not always land')
                    print('    exactly on top of the previous one.  That costs nothing:'
                          ' a gap split')
                    print('    into two short halves drops out of both the sum and the'
                          ' count, so')
                    print('    the mean of what remains is untouched.  The threshold'
                          ' could only')
                    print('    bias anything by letting a HALF gap in as if it were a'
                          ' whole one --')
                    print('    which the minimum below rules out.')
            # If every long gap was one of two adjacent integers, the counts of
            # each follow from the sum, and nothing is being assumed.
            if vmax == vmin + 1:
                n_hi = vsum - vmin * vnf
                n_lo = vnf - n_hi
                if 0 <= n_hi <= vnf:
                    print(f'  every long gap was {vmin} or {vmax}: '
                          f'{n_lo} x {vmin} + {n_hi} x {vmax}')
                    print(f'    nothing between {vmin} and the threshold got in, so no'
                          f' half gap was')
                    print('    counted as a whole one.  The mean is exact, not a fit.')
            elif vmax == vmin:
                print(f'  every long gap was exactly {vmin}')
            else:
                print(f'  long gaps ran from {vmin} to {vmax} -- more than two values,'
                      f' so the cadence was not steady')
            print()
            print('  if the clip is        the gyro rate in the sensor\'s own clock')
            for label, fps in (('29.97 fps', 30000 / 1001), ('30.00 fps', 30.0),
                               ('25 fps', 25.0), ('24 fps', 24.0)):
                hz = mean * fps
                print(f'  {label:12s}          {hz:9.3f} Hz   ({hz / 2500 - 1:+.4%})')
            print()
            print('  or, taking the gyro as exactly 2500 Hz, the frame rate is')
            print(f'    {2500 / mean:.5f} fps   (29.97 is {30000/1001:.5f})')
        print()


def accel_interval():
    """Can the accelerometer hook carry the drain on its own?

    One number decides it: the largest gap, in gyro samples, between two
    accelerometer visits.  The firmware ring holds 600, and a lap is silent --
    head-minus-cursor reads the same as a wrap -- so the answer has to come with
    margin, not just "it did not happen this time".
    """
    w = P.mem_get(ACC_STATE, ACC_WORDS)
    if any(x is None for x in w):
        raise SystemExit('the accel counters did not read back whole')
    ghead, mx, n, total, over = w
    if not n:
        print('the accelerometer hook has not fired twice yet.')
        print('  ghead 0x%08X -- if that is 0xFFFFFFFF the hook never ran at '
              'all.' % ghead)
        return
    mean = total / n
    print(f'accelerometer visits {n}   ring head now +{ghead} bytes')
    print(f'gap between visits, in gyro samples:')
    print(f'  mean {mean:.2f} = {_ms(mean):.2f} ms  -> {1000.0 / _ms(mean):.2f} Hz')
    print(f'  max  {mx} = {_ms(mx):.1f} ms')
    print(f'  gaps at or past {ACC_DANGER} records ({_ms(ACC_DANGER):.0f} ms): {over}')
    print()
    print(f'the firmware ring holds {GYRO_RING_SPAN // 8} records = '
          f'{_ms(GYRO_RING_SPAN // 8):.0f} ms')
    if mx:
        print(f'worst gap used {100.0 * mx / (GYRO_RING_SPAN // 8):.1f}% of it, '
              f'margin {GYRO_RING_SPAN // 8 - mx} records')
    print()
    if over or mx >= GYRO_RING_SPAN // 8:
        print('NO.  Dropping the 20 ms hook would lose samples, silently.')
    elif mx > (GYRO_RING_SPAN // 8) // 2:
        print('NOT YET.  The worst gap is past half the ring; that is not margin,')
        print('  it is luck.  Keep the 20 ms hook.')
    else:
        print('So far so good -- but this is a maximum, and a maximum only means')
        print('  something over a long run that included whatever the camera does')
        print('  worst (record start, card flush, menu, playback).  Run it long.')


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
    g.add_argument('--accel', action='store_true',
                   help='the accelerometer hook interval, in gyro samples')
    g.add_argument('--rate', type=float, metavar='SECONDS')
    ap.add_argument('--rows', type=int, default=24)
    ap.add_argument('--step', type=float, default=30.0)
    ap.add_argument('--only', help='comma-separated producers to arm')
    ap.add_argument('--measure-accel', action='store_true',
                    help='build the accel hook with its interval counters')
    a = ap.parse_args()
    if a.restore:
        restore()
    elif a.reset:
        reset()
    elif a.take:
        take()
    elif a.dump:
        dump(a.rows)
    elif a.accel:
        accel_interval()
    elif a.rate:
        rate(a.rate, a.step)
    else:
        arm(set(a.only.split(',')) if a.only else None, a.measure_accel)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
