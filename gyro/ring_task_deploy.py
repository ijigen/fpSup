#!/usr/bin/env python3
"""Create the dedicated writer task, and prove it blocks and wakes.

    ./ring_task_deploy.py --place    write the code, create nothing
    ./ring_task_deploy.py            create the task (file still closed)
    ./ring_task_deploy.py --open     open the file -- the writer drains at once
    ./ring_task_deploy.py --close    drain what is left and close

ORDER MATTERS.  Open last, and only when something is there to use the file.
Opening it and then doing six minutes of other work froze the camera: a file
object nobody is writing to is the \LENS.DAT failure the logger warns about --
"could not be opened again by anything until the camera was power cycled, with
the card light on".
    ./ring_task_deploy.py --signal   wake it N times and check it noticed
    ./ring_task_deploy.py --state    read the counters

The task is what the audio writer is and ours never was: priority 6, blocked on
tk_slp_tsk rather than polling, woken the instant there is work.  This step
proves only that -- it creates the task, blocks it, and counts wakes.  The ring
and the card write are separate units, because task creation is the piece with
a history of freezing the camera and it should not be entangled with anything
else when it is first run.

The creator runs ONCE, through the shell's borrowed echo handler.  Nothing about
it stays reachable afterwards.
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
from armasm import assemble, _compile, _parse                  # noqa: E402

# The task lives in the POOL, not the injection cave.  The cave is a hard 3900
# bytes and the producers already take most of it; the task is reached by
# absolute address -- tk_cre_tsk's entry, and an indirect blx from the gyro
# producer -- so it does not need to be inside a firmware bl's range the way
# the hooks do.  Code runs from the pool once the caches have been maintained.
CODE_POOL_OFF = 0x44000
JPOOL_POOL_OFF = 0x43000
FOBJ_POOL_OFF = 0x42000
F_CACHE = 0xC000E91C            # what makes freshly written pool code runnable
POOL_PTR = 0xC3757A7C
JOB_COUNT = 32
JOB_SIZE = 24

T_ID, T_CRE_RC, T_STA_RC = 0xC072E0D0, 0xC072E0D4, 0xC072E0D8
T_WAKES, T_SIGNALS, T_ENTRY = 0xC072E0DC, 0xC072E0E0, 0xC072E0E4
T_RECV_RC, T_MBX_RC = 0xC072E0E8, 0xC072E0EC
T_DESC, T_PKT, T_DOOR, T_MBX = 0xC072E080, 0xC072E0A0, 0xC072E0C0, 0xC072E0C4
T_DRAINED, T_MAXSPAN = 0xC072E0C8, 0xC072E0CC
T_FOBJ, T_FOPEN = 0xC072E0F8, 0xC072E0FC
T_WANT = 0xC072E194
T_STAGE = 0xC072E198
T_STOPSENT = 0xC072E15C
T_JSEQ = 0xC072E160
T_JOBSLOT = 0xC072E164
STREAM_JPOOL = 0xC072E19C
STREAM_POSTED = 0xC072E1AC
STREAM_INDEX, STREAM_TAIL = 0xC072E1F8, 0xC072E1A4
T_OPENFN, T_CLOSEFN = 0xC072EA64, 0xC072EA68
W_THREAD, W_BODYOBJ, W_JOINRC = 0xC072EA10, 0xC072EA14, 0xC072EA18
W_VT, W_VT_SLOT = 0xC072EA30, 0x0C
W_OPENS, W_CLOSES, W_STAGE = 0xC072EA24, 0xC072EA28, 0xC072EA2C
T_BYTES, T_WRITES = 0xC072E8E0, 0xC072E8E4
T_WRC, T_LOST, T_WRAPS = 0xC072E8E8, 0xC072E8EC, 0xC072E8F0
STREAM_SIGFN = 0xC072E1A8


def symbols(src, defines=()):
    """Offsets of the global symbols inside the assembled blob."""
    elf, sections, by_name = _parse(_compile(src, defines))
    _, symtab = by_name['.symtab']
    _, strtab = by_name['.strtab']
    out = {}
    for off in range(symtab[4], symtab[4] + symtab[5], 16):
        name_off, value, _size, info, _other, shndx = struct.unpack_from(
            '<IIIBBH', elf, off)
        # `.global` alone leaves the symbol STT_NOTYPE, so filter by name, not
        # by type -- an empty map here would place the task at zero.
        end = elf.index(b'\0', strtab[4] + name_off)
        name = elf[strtab[4] + name_off:end].decode()
        if name in ('writer_body', 'make_writer',
                    'writer_openfile', 'writer_closefile',
                    'writer_selftest', 'writer_post', 'mpool_init_jobs',
                    'take_open', 'take_close'):
            out[name] = value
    return out


def _check():
    """The addresses here are duplicated from the assembly; prove they match."""
    src = (HERE / 'ring_task.inc.S').read_text()
    want = {'T_ID': T_ID, 'T_CRE_RC': T_CRE_RC, 'T_STA_RC': T_STA_RC,
            'T_WAKES': T_WAKES, 'T_SIGNALS': T_SIGNALS, 'T_ENTRY': T_ENTRY,
            'T_RECV_RC': T_RECV_RC, 'T_MBX_RC': T_MBX_RC, 'T_DESC': T_DESC,
            'T_PKT': T_PKT, 'T_DOOR': T_DOOR, 'T_MBX': T_MBX,
            'T_DRAINED': T_DRAINED, 'T_MAXSPAN': T_MAXSPAN,
            'T_FOBJ': T_FOBJ, 'T_FOPEN': T_FOPEN, 'T_WANT': T_WANT, 'T_STAGE': T_STAGE,
            'T_OPENFN': T_OPENFN, 'T_CLOSEFN': T_CLOSEFN,
            'W_THREAD': W_THREAD, 'W_BODYOBJ': W_BODYOBJ, 'W_VT': W_VT,
            'W_OPENS': W_OPENS, 'W_CLOSES': W_CLOSES,
            'XT_CREATE': 0xC036E108, 'XT_ATTACH': 0xC036E1B8,
            'XT_JOIN': 0xC036E1F8, 'XT_DESTROY': 0xC036E168,
            'W_STAGE': W_STAGE,
            'T_BYTES': T_BYTES,
            'T_WRITES': T_WRITES, 'T_WRC': T_WRC, 'T_LOST': T_LOST,
            'T_WRAPS': T_WRAPS, 'WRITER_PRI': 6}
    for name, value in want.items():
        m = re.search(rf'^\.equ\s+{name},\s*([^\s/@]+)', src, re.M)
        if not m:
            raise SystemExit(f'ring_task.inc.S has no {name}')
        if int(m.group(1).rstrip(','), 0) != value:
            raise SystemExit(f'{name}: header says {m.group(1)}, this says {value:#x}')

    # The syscall stubs, checked against the firmware rather than trusted.  Each
    # TK-OS stub keeps its service ID at stub+0x20; the notes recorded three of
    # these twelve bytes too high, which would have skipped the prologue.
    fw = Path('/Users/dido/Developer/SIGMAfp_re/out/MAIN_c0000000.bin')
    if fw.exists():
        blob = fw.read_bytes()
        for name, service in (('TK_CRE_TSK', 0x80010100), ('TK_STA_TSK', 0x80030200),
                              ('TK_DLY_TSK', 0x80460100), ('MBX_CREATE', 0x80260100),
                              ('MBX_SEND', 0x80280200), ('MBX_RECV', 0x80290300)):
            m = re.search(rf'^\.equ\s+{name},\s*(0x[0-9A-Fa-f]+)', src, re.M)
            if not m:
                raise SystemExit(f'ring_task.inc.S has no {name}')
            stub = int(m.group(1), 0)
            got = struct.unpack_from('<I', blob, stub + 0x20 - 0xC0000000)[0]
            if got != service:
                raise SystemExit(f'{name} 0x{stub:08X}: service at +0x20 is '
                                 f'0x{got:08X}, not 0x{service:08X}')
            first = struct.unpack_from('<I', blob, stub - 0xC0000000)[0]
            if first != 0xE92D0010:
                raise SystemExit(f'{name} 0x{stub:08X} does not start with push {{r4}}')


def pool_base():
    seen = [P.mem_get(POOL_PTR)[0] for _ in range(3)]
    if len(set(seen)) != 1:
        raise SystemExit('the pool pointer read back differently three times: '
                         + ', '.join(f'0x{v:08X}' if v else str(v) for v in seen))
    pool = seen[0]
    if not pool or not 0x40000000 <= pool < 0x50000000:
        raise SystemExit(f'the pool pointer reads 0x{pool or 0:08X}')
    return pool


DRY_RUN = False   # set by --dry-run: everything except the card


def place():
    _check()
    defines = ('DRY_RUN',) if DRY_RUN else ()
    code = assemble(HERE / 'ring_task.S', defines)
    syms = symbols(HERE / 'ring_task.S', defines)
    pool = pool_base()
    global CODE_AT
    CODE_AT = pool + CODE_POOL_OFF
    end = CODE_AT + len(code)
    # The regions this deployer owns, against the ring the stream deployer set.
    import imu_stream_deploy as D
    ring_lo = pool + D.RING_POOL_OFF
    ring_hi = ring_lo + D.RING_BYTES
    jlo = pool + JPOOL_POOL_OFF
    jhi = jlo + JOB_COUNT * (JOB_SIZE + 8) + 0x14
    flo = pool + FOBJ_POOL_OFF
    for name, lo, hi in (('code', CODE_AT, end), ('job pool', jlo, jhi),
                         ('file object', flo, flo + 0x1000)):
        if lo < ring_hi and ring_lo < hi:
            raise SystemExit(f'{name} 0x{lo:08X}..0x{hi:08X} overlaps the ring')
        if not (pool + 0x20000 <= lo and hi <= pool + 0x100000):
            raise SystemExit(f'{name} 0x{lo:08X}..0x{hi:08X} leaves the free pool')
    missing = {'writer_body', 'take_open', 'take_close'} - set(syms)
    if missing:
        raise SystemExit(f'the blob has no {sorted(missing)}')
    print(f'  ring_task     0x{CODE_AT:08X}..0x{end:08X}  {len(code)} bytes (pool)'
          + ('   DRY RUN: no open, no write, no close' if DRY_RUN else ''))
    print(f'  job pool      0x{jlo:08X}..0x{jhi:08X}  {JOB_COUNT} jobs')
    for n, o in sorted(syms.items(), key=lambda kv: kv[1]):
        print(f'    {n:16s} 0x{CODE_AT + o:08X}')
    return code, {n: CODE_AT + o for n, o in syms.items()}


def _setw(addr, value, what):
    for _ in range(8):
        P.mem_set(addr, value)
        if (P.mem_get(addr) or [0])[0] == value:
            return
    raise SystemExit(f'could not write {what} at 0x{addr:08X}')


def echo_into(addr, label):
    """Run a routine once by borrowing the shell's echo handler."""
    orig = P.mem_get(P.ECHO_SLOT)
    if not orig or orig[0] != P.ECHO_ORIG:
        raise SystemExit(f'echo handler is {orig}, not free to borrow')
    _setw(P.ECHO_SLOT, addr, f'the echo handler -> {label}')
    try:
        P.sh('echo', retries=0)
    finally:
        for _ in range(8):
            P.mem_set(P.ECHO_SLOT, P.ECHO_ORIG)
            if (P.mem_get(P.ECHO_SLOT) or [0])[0] == P.ECHO_ORIG:
                return
        raise SystemExit('LEFT THE ECHO HANDLER REDIRECTED -- reboot the camera')


def place_code():
    """Write the code and set every word, but create nothing and open nothing.

    Separating this from create() is what makes the failure bisectable: the
    file open and the first card write can then be tried one at a time, which
    is how the pool probe's wedge was found after three wrong guesses.
    """
    code, at = place()
    # P.put rather than P.put_slow: a word per command took five minutes for
    # this blob, and a long window is a long window with the card mounted and
    # a file object possibly open.  put() sends about 240 bytes a round trip
    # and repairs whatever did not land, one word at a time.
    P.put(CODE_AT, code, 'ring_task')
    # Freshly written code in the pool is still only data to the caches.
    echo_into(F_CACHE, 'the cache maintenance routine')
    # The pool worker calls slot +0xC of the object it is handed.  That slot
    # is the only interface it has, and only we know where the body landed.
    _setw(W_VT + W_VT_SLOT, at['writer_body'], 'the body, in the vtable slot')
    _setw(T_ENTRY, at['writer_body'], 'the body, for reading back')
    # The record hooks live in the cave and these live in the pool, so the
    # hooks reach them through a word only the deployer can fill in.
    _setw(T_OPENFN, at['take_open'], 'what the record start calls')
    _setw(T_CLOSEFN, at['take_close'], 'what the record stop calls')
    _setw(STREAM_SIGFN, at['writer_post'], 'what the producer calls')
    pool = pool_base()
    _setw(T_FOBJ, pool + FOBJ_POOL_OFF, 'the file object')
    _setw(STREAM_JPOOL, pool + JPOOL_POOL_OFF, 'the job pool')
    _setw(STREAM_POSTED, 0, 'the posted mark')
    for a in (T_STOPSENT, T_JSEQ, T_JOBSLOT):
        _setw(a, 0, 'a job word')
    # Build the free list before anything can take a descriptor from it.
    echo_into(at['mpool_init_jobs'], 'mpool_init_jobs')
    free = P.mem_get(pool + JPOOL_POOL_OFF + 4)[0]
    print(f'job pool at 0x{pool + JPOOL_POOL_OFF:08X}: {free} free')
    if free != JOB_COUNT:
        raise SystemExit(f'the job pool says {free} free, not {JOB_COUNT}')
    _setw(T_FOPEN, 0, 'the open flag')
    _setw(T_WANT, 0, 'the wanted state')
    _setw(T_STAGE, 0, 'the close stage')
    for a in (T_BYTES, T_WRITES, T_WRC, T_LOST, T_WRAPS):
        _setw(a, 0, 'a write counter')
    # A fresh name each time.  Mode 7 does not truncate here, so reusing one
    # name layers every session's writes over each other and the file stops
    # being a single stream -- which cost one whole verification pass.
    import time as _t
    # `adr` has to resolve at assembly time, so the label cannot be global;
    # find the string in the blob instead.  It is a fixed literal, so this is
    # exact rather than a guess.
    marker = b'\\GYRO\\RINGTEST.BIN\0'
    off = code.find(marker)
    if off < 0:
        raise SystemExit('the path literal is not in the blob')
    name = f'\\GYRO\\RT{int(_t.time()) % 100000:05d}.BIN'
    blob = name.encode() + b'\0'
    blob += b'\0' * (-len(blob) % 4)
    if len(blob) > len(marker) + 12:
        raise SystemExit('the new name does not fit the reserved space')
    P.put_slow(CODE_AT + off, blob, 'the path')
    print(f'placed; file object 0x{pool + FOBJ_POOL_OFF:08X}, writing to {name}')
    return at


def _verify_placed(code, at):
    """Refuse to jump into the pool unless our code is actually there.

    place() assembles and prints a full map without writing a byte -- it reads
    exactly like a successful placement, and running create() straight after a
    reboot therefore branches the shell's echo handler into whatever the pool
    held before.  That is a battery pull, and it cost one.  Two reads turn it
    into a sentence.
    """
    want = struct.unpack_from('<4I', code, 0)
    got = tuple(P.mem_get(CODE_AT, 4) or ())
    entry_off = at['make_writer'] - CODE_AT
    want2 = struct.unpack_from('<4I', code, entry_off)
    got2 = tuple(P.mem_get(at['make_writer'], 4) or ())
    if got == want and got2 == want2:
        return
    raise SystemExit(
        'the pool does not hold this blob -- run --place first.\n'
        f'  0x{CODE_AT:08X} reads ' + ' '.join(f'{w:08X}' for w in got) + '\n'
        f'  expected           ' + ' '.join(f'{w:08X}' for w in want) + '\n'
        '  place() only assembles and prints; place_code() is what writes.')


def create():
    """There is nothing left for this to do.

    The task used to be made once, at deploy time, and live for the session.
    It is now built by take_open at record start and destroyed by take_close at
    record stop, the way XC_AudioRecorder::Start and ::Stop build and destroy
    AudF_W -- which is the whole point of the rewrite.  --place is the entire
    deployment.
    """
    raise SystemExit('the take builds its own task now; --place is all there is')


def signal(times, at=None):
    if at is None:
        _code, at = place()
        _verify_placed(_code, at)
    before = P.mem_get(T_WAKES)[0]
    for _ in range(times):
        echo_into(at['writer_signal'], 'writer_signal')
    time.sleep(0.5)
    after = P.mem_get(T_WAKES)[0]
    print(f'signalled {times}x   wakes {before} -> {after}')
    if after == before:
        print('  the task did not wake: it is not running, or the id is wrong')
    elif after - before == times:
        print('  every signal was taken -- blocking and waking, no wakeups lost')
    else:
        print(f'  {after - before} of {times} landed')


def state():
    mbx, door = P.mem_get(T_MBX)[0], P.mem_get(T_DOOR)[0]
    drained, maxspan = P.mem_get(T_DRAINED)[0], P.mem_get(T_MAXSPAN)[0]
    fopen, wr, by = (P.mem_get(T_FOPEN)[0], P.mem_get(T_WRITES)[0],
                     P.mem_get(T_BYTES)[0])
    lost, wraps, wrc = (P.mem_get(T_LOST)[0], P.mem_get(T_WRAPS)[0],
                        P.mem_get(T_WRC)[0])
    want = P.mem_get(T_WANT)[0]
    st = P.mem_get(T_STAGE)[0]
    where = {0x21: 'entered close', 0x22: 'about to drain', 0x23: 'drained, about to close',
             0x24: 'closed, about to destroy', 0x25: 'destroyed, all the way'}.get(st)
    print(f'  T_MBX      {mbx}   T_DOOR {door}   wanted {want}   file open {fopen}')
    if st:
        print(f'  close got to 0x{st:X}' + (f' -- {where}' if where else ''))
    jseq, sent = P.mem_get(T_JSEQ)[0], P.mem_get(T_STOPSENT)[0]
    jfree = P.mem_get((pool_base() + JPOOL_POOL_OFF) + 4)[0]
    jfail = P.mem_get((pool_base() + JPOOL_POOL_OFF) + 0x10)[0]
    print(f'  writes     {wr}   bytes {by}   last result {wrc}')
    print(f'  jobs       {jseq} posted   stop sent {sent}   '
          f'pool {jfree}/{JOB_COUNT} free   refused {jfail}')
    print(f'  wraps      {wraps}   LOST {lost}'
          + ('   <- the ring is too shallow' if lost else ''))
    print(f'  drained    {drained} records   most ever waiting {maxspan}')

    # The take's own lifecycle, the part that now mirrors AudF_W.
    opens, closes = P.mem_get(W_OPENS)[0], P.mem_get(W_CLOSES)[0]
    wst, thr = P.mem_get(W_STAGE)[0], P.mem_get(W_THREAD)[0]
    stage = {0x01: 'take_open entered', 0x02: 'the file is open',
             0x03: 'flag made, about to make the thread',
             0x04: 'thread made, about to attach',
             0x05: 'built, the writer is running',
             0x11: 'take_close entered', 0x12: 'the stop job is posted',
             0x13: 'joined -- the body returned',
             0x14: 'the file is closed', 0x15: 'the task is gone',
             0x16: 'torn down, all the way'}.get(wst)
    print(f'  takes      {opens} built   {closes} torn down   '
          f'thread 0x{(thr or 0):08X}')
    print(f'  last stage 0x{(wst or 0):02X}' + (f' -- {stage}' if stage else ''))
    w = P.mem_get(T_ID, 8)
    names = ('T_ID', 'T_CRE_RC', 'T_STA_RC', 'T_WAKES', 'T_SIGNALS', 'T_ENTRY',
             'T_RECV_RC', 'T_MBX_RC')
    for n, v in zip(names, w):
        print(f'  {n:10s} {v if v is not None else "(unread)"}'
              + (f'   0x{v:08X}' if v is not None else ''))
    if w[1] is not None and w[1] <= 0:
        print(f'  tk_cre_tsk returned {w[1]} -- E_PAR is -17 (priority must be '
              f'1..32, stack at least 0x100)')
    if w[2] == 0 and w[0] and w[0] > 0:
        print('  created and started')


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--state', action='store_true')
    g.add_argument('--signal', type=int, metavar='N')
    g.add_argument('--place-only', action='store_true')
    g.add_argument('--place', action='store_true',
                   help='write the code and the words, create nothing')
    g.add_argument('--holdopen', action='store_true',
                   help='open the file and hold it, with nothing writing')
    g.add_argument('--dropfile', action='store_true',
                   help='close it directly, without the task')
    g.add_argument('--selftest', action='store_true',
                   help='open, write from the ring, close -- all in this context')
    g.add_argument('--open', action='store_true', help='open the file')
    g.add_argument('--close', action='store_true', help='drain and close it')
    ap.add_argument('--dry-run', action='store_true',
                    help='build the writer with the card calls stubbed out')
    a = ap.parse_args()
    global DRY_RUN
    DRY_RUN = a.dry_run
    if a.state:
        state()
    elif a.signal:
        signal(a.signal)
    elif a.place_only:
        place()
    elif a.place:
        place_code()
    elif a.holdopen:
        # Open with no task in existence, so nothing drains and nothing writes.
        # This separates HOLDING a file across the camera's stop sequence from
        # WRITING during it -- the two have been tangled together in every run
        # so far, and the last freeze reached neither the stop hook nor the
        # close, so the writing may have had nothing to do with it.
        at = place_code()
        echo_into(at['writer_openfile'], 'writer_openfile')
        print(f'file open: {P.mem_get(T_FOPEN)[0]}   (no task exists; nothing '
              f'will write to it)')
    elif a.dropfile:
        # place(), not place_code(): the action modes must NOT reset the state
        # words.  place_code() zeroes T_FOPEN, and a close that sees a zero
        # flag skips the destroy -- leaving a constructed file object behind,
        # which is the \LENS.DAT trap the logger warns about and which then
        # makes every later open fail.
        _code, at = place()
        _verify_placed(_code, at)
        echo_into(at['writer_closefile'], 'writer_closefile')
        print(f'file open: {P.mem_get(T_FOPEN)[0]}   stage '
              f'0x{(P.mem_get(T_STAGE)[0] or 0):X}')
    elif a.selftest:
        # place(), not place_code(): the action modes must NOT reset the state
        # words.  place_code() zeroes T_FOPEN, and a close that sees a zero
        # flag skips the destroy -- leaving a constructed file object behind,
        # which is the \LENS.DAT trap the logger warns about and which then
        # makes every later open fail.
        _code, at = place()
        _verify_placed(_code, at)
        echo_into(at['writer_selftest'], 'writer_selftest')
        w = P.mem_get(T_WRC)[0]
        stage = {0x11: 'entered', 0x12: 'the open FAILED', 0x13: 'opened, about to write',
                 0x14: 'the ring base is zero', 0x15: 'the write returned',
                 0x16: 'closed, all the way through'}.get(w, f'0x{w:X}' if w else 'nothing')
        print(f'got as far as: {stage}')
        if w and w >= 0x15:
            print(f'  F_WRITE returned {P.mem_get(T_BYTES)[0]}')
        state()
    elif a.open:
        # The same way a recording asks: latch where the take starts, then say
        # it wants a file.  The writer opens it on its next wake, so this
        # exercises the path the record hook uses rather than a second one.
        head = P.mem_get(STREAM_INDEX)[0]
        _setw(STREAM_POSTED, head, 'the posted mark')
        _setw(T_STOPSENT, 0, 'the stop flag')
        _setw(T_WANT, 1, 'the wanted state')
        print(f'asked for a file, take starts at record {head}')
        time.sleep(1.0)
        state()
    elif a.close:
        _setw(T_WANT, 0, 'the wanted state')
        print('asked for it to be closed; the producer posts a stop job')
        time.sleep(2.0)
        state()
    else:
        place_code()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
