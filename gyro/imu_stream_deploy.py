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
    # The accelerometer driver publishing a sample is the only real hardware
    # event this data has, so it is the only hook left that produces anything:
    # it drains the coprocessor's ring and then appends its own record, which is
    # what puts that record in the right place.
    'accel': (0xC072E100, 'accel_hook.S',       (),            0xC050D4C8, 0xE3A02000, 0),
    # Not hooks.  Called.
    'drain': (0xC072E300, 'gyro_drain.S',       (),            None,       None,       0),
    'space': (0xC072E900, 'stream_space.S',     (),            None,       None,       0),
    'start': (0xC072E4E0, 'rec_trigger.S',      (),            0xC03790B8, 0xE5DB25CE, 0),
    'stop':  (0xC072E620, 'rec_trigger.S',      ('REC_STOP',), 0xC038C45C, 0xE5D030E0, 0),
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
        if name in ('stream_claim', 'stream_commit', 'gyro_drain'):
            out[name] = value
    if not out:
        raise SystemExit(f'{src.name} exports nothing we can call')
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
STREAM_R0_HEAD = 0xC072E1E0
GYRO_RING_SPAN = 0x12C0
STREAM_R1_GC  = 0xC072E1D0
STREAM_R1_N   = 0xC072E1D4
STREAM_R0_GC  = 0xC072E1E8
STREAM_R0_N   = 0xC072E1EC
STREAM_GHEAD  = 0xC072E1F0
STREAM_PADBAD = 0xC072E1F4
STREAM_GCOUNT = 0xC072E1FC
STREAM_SIGFN  = 0xC072E1A8
STREAM_CLAIMFN  = 0xC072EC38
STREAM_COMMITFN = 0xC072EC3C
STREAM_DRAINFN  = 0xC072EC40
T_OPENFN, T_CLOSEFN = 0xC072EC30, 0xC072EC34
T_BUILD = 0xC072EC54
T_TEARDOWN = 0xC072EC58
BUF_N, BUF_BYTES = 8, 0x4000
B_DROPS, B_HANDED = 0xC072EBF0, 0xC072EBF4
POOL_PTR      = 0xC3757A7C

# GHEAD unarmed, everything else zero.
STATE_INIT = struct.pack('<20I', *([0] * 16 + [0xFFFFFFFF, 0, 0, 0]))

ACC_CODE_AT   = 0xC072ECC0   # only the measuring build needs the room;
                             # 0xC072E900 is the space provider now
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
        'GYRO_RING_SPAN': GYRO_RING_SPAN,
        'STREAM_R1_GC': STREAM_R1_GC, 'STREAM_R1_N': STREAM_R1_N,
        'STREAM_R0_GC': STREAM_R0_GC, 'STREAM_R0_N': STREAM_R0_N,
        'STREAM_GHEAD': STREAM_GHEAD, 'STREAM_PADBAD': STREAM_PADBAD, 'STREAM_GCOUNT': STREAM_GCOUNT,
        'ACC_STATE': ACC_STATE, 'ACC_WORDS': ACC_WORDS,
        'ACC_DANGER': ACC_DANGER,
        'STREAM_SIGFN': STREAM_SIGFN,
        'TAG_GYRO': S.TAG_GYRO, 'TAG_ACCEL': S.TAG_ACCEL,
    }
    for name, value in want.items():
        m = re.search(rf'^\.equ\s+{name},\s*([^\s/@]+)', src, re.M)
        if not m:
            raise SystemExit(f'imu_stream.inc.S has no {name}')
        if int(m.group(1).rstrip(','), 0) != value:
            raise SystemExit(f'{name}: header says {m.group(1)}, this says {value:#x}')

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
    code_spans = list(spans)      # words may sit in data, never in code
    spans += [('state words', STATE_AT, STATE_WORDS * 4),
              ('accel state', ACC_STATE, ACC_WORDS * 4),
              # ring_task_deploy owns these, but only this script knows
              # where the hooks land -- so the overlap check lives here.
              ('writer counters', 0xC072E8E0, 5 * 4),
              # the blocks are the allocator's; only their bookkeeping is here
              ('block state', 0xC072EBA0, (2 * BUF_N + 7) * 4),
              # the writer's own words and the four call-throughs.  These
              # used to sit under the space provider, and W_VT sat on top of
              # T_POS: putting them in the map is what stops that happening.
              ('writer words', 0xC072EC00, 0x5C)]
    for name, at, n in spans:
        if at < CAVE_LO or at + n > CAVE_HI:
            raise SystemExit(f'{name}: 0x{at:08X}..0x{at+n:08X} leaves the cave '
                             f'0x{CAVE_LO:08X}..0x{CAVE_HI:08X}')
    for i, (an, aa, al) in enumerate(spans):
        for bn, ba, bl in spans[i + 1:]:
            if aa < ba + bl and ba < aa + al:
                raise SystemExit(f'{an} and {bn} overlap')
    # Every .equ in the cave, against every blob.  This is the check that was
    # missing: T_JSEQ, T_JOBSLOT and T_WANT had been sitting INSIDE the
    # accelerometer hook's code, so writing T_WANT at record start overwrote an
    # instruction and the kernel wrote received messages into another one.  The
    # map only listed what the deployer places; the words are declared in the
    # headers, so nothing compared the two.
    caves = {}
    for hdr in ('imu_stream.inc.S', 'ring_task.inc.S'):
        text = (HERE / hdr).read_text()
        for m in re.finditer(r'^\.equ\s+([A-Z_0-9]+),\s*(0xC072E[0-9A-Fa-f]{3})',
                             text, re.M):
            caves[m.group(1)] = int(m.group(2), 16)
    sized = {'T_DESC': 32, 'T_PKT': 32, 'W_VT': 16, 'B_PTR': 32, 'B_BUSY': 32}
    hit = []
    for wname, wa in sorted(caves.items(), key=lambda kv: kv[1]):
        wn = sized.get(wname, 4)
        for bn, ba, bl in code_spans:
            if wa < ba + bl and ba < wa + wn:
                hit.append(f'{wname} 0x{wa:08X}+{wn} is inside {bn} '
                           f'0x{ba:08X}..0x{ba + bl:08X}')
    if hit:
        raise SystemExit('state words land on code:\n  ' + '\n  '.join(hit))

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

    # The real ring lives in the pool, whose address is only known now.  Memory
    # from the firmware's allocator freezes the camera when held across a
    # recording start; the pool does not, and pool+0x20000 is inside the 896 KB
    # that survived 224 of 224 markers.
    # The ring is the allocator's now, asked for at record start and given back
    # at stop, the way DspAudioDevice::v5 asks for its two blocks.  Nothing is
    # resolved here any more: take_open fills this word in and take_close clears
    # it, so between takes there is no buffer standing around at all.
    print(f'buffers: {BUF_N} x {BUF_BYTES // 1024} KiB from the allocator at '
          f'record start = {BUF_N * BUF_BYTES / 8 / 2500:.1f} s')

    # The producers call these; only the deployer knows where they landed.
    syms = _symbols(HERE / 'stream_space.S')
    base = PRODUCERS['space'][0]
    _setw(STREAM_CLAIMFN, base + syms['stream_claim'], 'stream_claim')
    _setw(STREAM_COMMITFN, base + syms['stream_commit'], 'stream_commit')
    syms = _symbols(HERE / 'gyro_drain.S')
    _setw(STREAM_DRAINFN, PRODUCERS['drain'][0] + syms['gyro_drain'], 'gyro_drain')

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
    # The block bookkeeping too, so a stage that never builds a take still
    # reads cleanly.  B_CUR must be -1, not 0: zero means "block zero is mine",
    # and on a fresh boot block zero has no allocation behind it.
    # B_PTR is NOT cleared: it holds the allocator's pointers and they are
    # held for the session.  Clearing it once leaked 128 KiB and made take_open
    # decline every take.  Only the busy flags and the fill state reset.
    P.put_slow(0xC072EBC0, struct.pack('<%dI' % BUF_N, *([0] * BUF_N))
               + struct.pack('<6i', -1, 0, 0, 0, 0, 0), 'block state')

    # NOT the call-throughs.  Clearing counters must not undo --stage: this
    # block was here by accident and it turned every stage back on, so a run
    # that looked like stage 1 was really stages 1, 3 and 4 together.
    # Not the stream.  It is a ring that overwrites itself in a hundred
    # milliseconds, so zeroing two kilobytes buys nothing -- and `mem set` drops
    # enough of five hundred writes that the retry pass fails outright.
    print('counters cleared -- the next start, and the next frame, are take zero')


def _ms(samples):
    return samples * GYRO_PERIOD_US / 1000.0


STAGES = {
    0: 'nothing armed',
    1: 'the accelerometer hook, entered and left',
    2: '+ the take is built and torn down',
    3: '+ the space provider: blocks fill, nothing is posted',
    4: '+ the gyro drain',
    5: '+ posting and writing',
}


def stage(n):
    """Turn the flow on one step at a time, by pointer rather than by rebuild.

    Every step is one word.  A stage that freezes has narrowed the trouble to
    the one thing the step before it did not do, and the camera never has to be
    reflashed or rebooted to move between them.
    """
    if n == 0:
        restore()
        return

    import ring_task_deploy as R
    _code, at = R.place()               # assembles and resolves; writes nothing
    want = {
        T_OPENFN:        at['take_open']   if n >= 2 else 0,
        T_CLOSEFN:       at['take_close']  if n >= 2 else 0,
        STREAM_CLAIMFN:  None              if n >= 3 else 0,
        STREAM_COMMITFN: None              if n >= 3 else 0,
        STREAM_DRAINFN:  None              if n >= 4 else 0,
        STREAM_SIGFN:    at['writer_post'] if n >= 5 else 0,
    }
    syms = _symbols(HERE / 'stream_space.S')
    base = PRODUCERS['space'][0]
    real = {STREAM_CLAIMFN: base + syms['stream_claim'],
            STREAM_COMMITFN: base + syms['stream_commit'],
            STREAM_DRAINFN: PRODUCERS['drain'][0]
                            + _symbols(HERE / 'gyro_drain.S')['gyro_drain']}
    names = {T_OPENFN: 'take_open', T_CLOSEFN: 'take_close',
             STREAM_CLAIMFN: 'stream_claim', STREAM_COMMITFN: 'stream_commit',
             STREAM_DRAINFN: 'gyro_drain', STREAM_SIGFN: 'writer_post'}
    _setw(T_BUILD, 5, 'how far take_open builds')
    _setw(T_TEARDOWN, 5, 'how far take_close tears down')
    print(f'stage {n}: {STAGES[n]}')
    for addr, v in want.items():
        v = real[addr] if v is None else v
        _setw(addr, v, names[addr])
        print(f'  {names[addr]:14s} ' + (f'0x{v:08X}' if v else '(off)'))


def take():
    """What one take measured.

    The frame census went with the Vd hook: it could not put a record in the
    stream without lying about where it belonged, and everything else it
    measured -- the frame period, the rate, the doubled-interrupt count -- was
    finished work.  What is left is what the take itself says.
    """
    w = P.mem_get(STATE_AT, STATE_WORDS)
    if any(x is None for x in w):
        raise SystemExit('the state words did not read back whole')
    r1_gc, r1_n = w[8], w[9]
    r0_head, r0_gc, r0_n = w[12], w[14], w[15]
    padbad, gcount = w[17], w[19]
    handed, drops = P.mem_get(B_HANDED)[0], P.mem_get(B_DROPS)[0]
    print(f'gyro {gcount}   bad pads {padbad}')
    print(f'blocks {handed} handed to the writer   {drops} dropped'
          + ('   <- the writer did not keep up' if drops else ''))
    print(f'starts {r0_n}   stops {r1_n}')
    print()

    if not r0_n:
        print('recording never began -- 0xC01FBA28 (movRec) did not fire.')
        return
    if r0_n and r1_n:
        d = r1_gc - r0_gc
        print(f'take: gyro {r0_gc} -> {r1_gc} = {d} samples = {_ms(d)/1000:.2f} s')
        print(f'ring head at record start {r0_head} (+{r0_head//8} samples)')


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
    g.add_argument('--stage', type=int, choices=range(6),
                   help='turn the flow on one step at a time')
    g.add_argument('--teardown', type=int, choices=range(6),
                   help='how much of take_close to run: 0 nothing, 1 stop job, '
                        '2 +join, 3 +close, 4 +destroy thread, 5 +delete mailbox')
    g.add_argument('--build', type=int, choices=range(6),
                   help='how much of take_open to run: 1 blocks, 2 +file, '
                        '3 +mailbox, 4 +thread, 5 +attached')
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
    elif a.stage is not None:
        stage(a.stage)
    elif a.teardown is not None:
        _setw(T_TEARDOWN, a.teardown, 'how far take_close tears down')
        print(f'take_close will run {a.teardown} of 5 steps')
    elif a.build is not None:
        _setw(T_BUILD, a.build, 'how far take_open builds')
        print(f'take_open will build {a.build} of 5 steps')
    elif a.accel:
        accel_interval()
    elif a.rate:
        rate(a.rate, a.step)
    else:
        arm(set(a.only.split(',')) if a.only else None, a.measure_accel)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
