#!/usr/bin/env python3
"""Write a local file onto the camera's card, over the shell.

    ./putfile.py hello.txt '\\TEST.TXT'
    ./putfile.py autorun/AutoRun.txt '\\AutoRun.txt'

Which is how the AutoRun gets updated without taking the card out: the file the
shell was started from is just a file, and the shell can replace it.

Most of this is native commands.  `mem set` stages the bytes, `mem get` checks
them, `dir` confirms the result.  Only the write itself is code, because nothing
in the shell writes arbitrary content to a path -- that is templates/putfile.S,
run by borrowing the `echo` command's handler.

Roughly 20 words a second over USB, so a 14 KB AutoRun takes a few minutes.
"""
import argparse, pathlib, re, socket, struct, sys, time

from armasm import assemble

HERE = pathlib.Path(__file__).resolve().parent
SOCK = '/tmp/fpshd.sock'

CODE      = 0xC072F600          # the working template
CODE_END  = 0xC072F900
BULK      = 0xC072F900          # the bulk loader, resident alongside it
BULK_STATE = 0xC072F5F8         # its own two words, clear of the parameter block
DUMP      = 0xC072FA00          # the dense reader, in a slot of its own
DUMP_CHUNK = 3000               # bytes per round trip; 135 KiB/s, flat past 3000
DUMP_TEXT  = 0xF8000            # pool offset for the hex, 32 KiB from the end
BULK_END  = 0xC072FA00
CHUNK     = 240                 # bytes per command; the line holds about 502 chars
P         = 0xC072F500          # parameter block
ECHO_SLOT = 0xC0BAC2F8          # command table entry 17, echo's handler pointer
ECHO_ORIG = 0xC03D99A0
POOL_PTR  = 0xC3757A7C          # where the AutoRun's pool address lands
POOL_OFF  = 0x10000             # the templates' own scratch, past shell and gyro
FOBJ_ROOM = 0x400

P_STATUS, P_OPENR, P_WRITER = 0x08, 0x0C, 0x10
P_DATA, P_LEN, P_FOBJ, P_MODE, P_PATH = 0x14, 0x18, 0x1C, 0x20, 0x24

STATUS = {0: 'never ran', 1: 'started but did not finish', 2: 'written',
          3: 'open returned 0', 4: 'write returned 0'}


def sh(line: str, retries: int = 3) -> str:
    """One command, one connection -- the daemon closes after each reply.

    Roughly one command in ten goes missing, in one direction or the other, so a
    reply that does not come back is retried rather than believed.  The daemon
    gives up after 200 ms, which is what makes retrying cheap.
    """
    for attempt in range(retries + 1):
        s = socket.socket(socket.AF_UNIX)
        s.connect(SOCK)
        s.sendall(b'SHL ' + line.encode() + b'\n')
        out = b''
        while True:
            b = s.recv(65536)
            if not b:
                break
            out += b
        s.close()
        text = out.decode(errors='replace')
        if not text.startswith('ERR'):
            if text.startswith('OK '):
                text = text[3:]
            # the daemon escapes newlines so a reply stays one line on the wire
            return text.replace('\\n', '\n')
    return text


def mem_set(addr, value):
    sh(f'mem set 0x{addr:08X} 0x{value:08X}')


def mem_get(addr, count=1, tries=4):
    """Read `count` words, retrying while any of them is missing.

    The shell answers one line per word: `get : A:0xc072f000, D:0x4C485356`.
    Parsed exactly rather than by scraping hex, so a reply that is not a dump --
    an error, an echo of the command -- yields nothing instead of numbers that
    look real.

    Whole commands go missing sometimes, in both directions, so a reply with a
    word absent is retried rather than believed.  Words already seen are kept:
    what comes back is consistent, it is the round trip that is not.
    """
    seen = {}
    for _ in range(tries):
        out = sh(f'mem get 0x{addr:08X},,0x{count * 4:X}')
        for a, d in re.findall(r'A:0x([0-9A-Fa-f]+),\s*D:0x([0-9A-Fa-f]+)', out):
            seen[int(a, 16)] = int(d, 16)
        if all(addr + i * 4 in seen for i in range(count)):
            break
    return [seen.get(addr + i * 4) for i in range(count)]


def staging_area():
    """Where to stage the bytes.

    Not `memmgr bufmem get`.  That works from the AutoRun, at boot, but issued
    live through the shell it wedged the endpoint and froze the camera -- once,
    which was enough.  So the address is derived from the pool the AutoRun
    already took.

    The offset is the whole point.  +0x2000 was the obvious spot until the shell
    put its own capture buffer there, at which point staging a file meant writing
    into the memory that carries every reply, and the region-is-free check caught
    it on the first command.  The map now is: +0x0000 the shell's frames,
    +0x2000 its capture buffer, +0x6000 the gyro logger, +0x10000 here.
    """
    got = mem_get(POOL_PTR)
    if not got or not 0x40000000 <= got[0] < 0x50000000:
        raise SystemExit(f'0x{POOL_PTR:08X} does not hold a pool address ({got})')
    return got[0] + POOL_OFF


POOL_SIZE = 1048576             # must match the AutoRun's `memmgr bufmem get`


def pool_end():
    """One past the end of what the AutoRun asked for.

    Not read from `memmgr bufchk`. The memmgr commands are not safe to issue
    live -- `bufmem get` wedged the endpoint and froze the camera earlier today,
    and putting `bufchk` on the path every transfer takes did it again. The size
    is a constant here and in build_autorun.py, and the two have to agree; the
    check below is a guard against a stale one, not a discovery.
    """
    return mem_get(POOL_PTR)[0] + POOL_SIZE


def check_fits(addr, length, what):
    """Refuse rather than overflow.

    Staging 247 KB into the 64 KiB that was left ran off the end of the
    allocation into memory somebody else kept rewriting, so the verify could
    never converge and six passes of retries took six minutes -- reported as
    slowness, not as the out-of-bounds write it was.
    """
    end = pool_end()
    if addr + length > end:
        raise SystemExit(
            f'{what}: 0x{addr:08X}+{length} runs {addr + length - end} bytes past '
            f'the allocation end 0x{end:08X}.\n'
            "Raise the size in build_autorun.py's `memmgr bufmem get` and "
            'POOL_SIZE here, or move less at once.')


def prove(addr, length):
    """Write a pattern across the region, read it back, then read it again.

    The second read is the point: memory that takes a write but belongs to
    something else reads back correctly and is overwritten a moment later.
    """
    spots = [addr, (addr + length // 2) & ~3, (addr + length - 4) & ~3]
    for i, a in enumerate(spots):
        mem_set(a, 0xC0DE0000 | i)
    for wait in (0, 1.0):
        time.sleep(wait)
        for i, a in enumerate(spots):
            got = mem_get(a)
            if not got or got[0] != (0xC0DE0000 | i):
                raise SystemExit(f'0x{a:08X} reads {got} — staging area is not free')


READ_CHUNK = 128                # words per request


def read_back(addr, count):
    """Read `count` words, in requests as large as the reply will carry.

    Throughput flattens at about 44 KiB/s from 48 words up, and the reply for 64
    is well inside the daemon's 8 KiB buffer, so there is nothing to gain by
    going wider and something to lose if a reply is ever truncated.
    """
    out = []
    t0 = time.time()
    for base in range(0, count, READ_CHUNK):
        out += mem_get(addr + base * 4, min(READ_CHUNK, count - base))
        if base and (base // READ_CHUNK) % 16 == 0:
            el = time.time() - t0
            print(f'\r  read   {len(out)}/{count} words  {len(out)*4/el/1024:.1f} KiB/s'
                  f'  {(count-len(out))*el/max(len(out),1):.0f}s left ', end='', flush=True)
    if count > READ_CHUNK * 16:
        print(f'\r  read   {count} words in {time.time()-t0:.1f}s'
              f' ({count*4/(time.time()-t0)/1024:.1f} KiB/s)          ')
    return out


def put_slow(addr, blob, label, passes=6):
    """One word per command.  Used for the bulk loader itself, and for repairs."""
    w = list(struct.unpack(f'<{len(blob)//4}I', blob))
    for i, word in enumerate(w):
        mem_set(addr + i * 4, word)
    for _ in range(passes):
        got = read_back(addr, len(w))
        bad = [i for i in range(len(w)) if got[i] != w[i]]
        if not bad:
            return w
        for i in bad:
            mem_set(addr + i * 4, w[i])
    raise SystemExit(f'{label}: still short after {passes} passes')


_bulk_loaded = False
_dump_loaded = False


def ensure_dump():
    global _dump_loaded
    if not _dump_loaded:
        put_slow(DUMP, assemble(HERE / 'templates' / 'dump.S'), 'dump  ')
        _dump_loaded = True


def read_bulk(addr, nbytes, label='read  '):
    """Read memory through dump.S rather than `mem get`.

    `mem get` answers thirty-four characters for every four bytes and needs a
    round trip every 128 words, which is 26 KiB/s on a SuperSpeed link -- the
    text is the limit, not the wire. Bare hex at 3000 bytes a trip measures
    135 KiB/s.
    """
    ensure_dump()
    text = mem_get(POOL_PTR)[0] + DUMP_TEXT
    orig = mem_get(ECHO_SLOT)
    if not orig or orig[0] not in (ECHO_ORIG, DUMP):
        raise SystemExit(f'echo handler is {orig}, not free to borrow')
    out = bytearray()
    t0 = time.time()
    mem_set(ECHO_SLOT, DUMP)
    try:
        while len(out) < nbytes:
            n = min(DUMP_CHUNK, nbytes - len(out))
            for off, val in ((0x00, addr + len(out)), (0x04, n), (0x08, text)):
                mem_set(P + off, val)
            for _ in range(4):
                reply = sh('echo', retries=0)
                digits = ''.join(c for c in reply if c in '0123456789ABCDEF')
                if len(digits) >= n * 2:
                    out += bytes.fromhex(digits[:n * 2])
                    break
            else:
                raise SystemExit(f'{label}: no reply for {n} bytes at '
                                 f'0x{addr + len(out):08X}')
            el = time.time() - t0
            print(f'\r  {label} {len(out)}/{nbytes} B  {len(out)/el/1024:.0f} KiB/s ',
                  end='', flush=True)
    finally:
        mem_set(ECHO_SLOT, ECHO_ORIG)
    dt = time.time() - t0
    print(f'\r  {label} {nbytes} bytes in {dt:.1f}s ({nbytes/dt/1024:.0f} KiB/s)      ')
    return bytes(out)


def ensure_bulk():
    """Put the bulk loader on the camera, once per run."""
    global _bulk_loaded
    if _bulk_loaded:
        return
    code = assemble(HERE / 'templates' / 'bulkload.S')
    if BULK + len(code) > BULK_END:
        raise SystemExit('bulkload does not fit its region')
    put_slow(BULK, code, 'bulk  ')
    _bulk_loaded = True


def put(addr, blob, label, passes=6):
    """Write, verify, rewrite what did not land, until nothing is left.

    Bytes travel in the command line, about 240 at a time, because `mem set`
    moves four per round trip and that put 14 KB of AutoRun at 448 seconds --
    against 22 to read the same file back, `mem get` answering sixteen words at
    once.  The transport was never the problem.

    Verification stays, and matters more here, not less: `mem set` drops writes
    and whole commands go missing, so a chunk that never arrives leaves a 240
    byte hole.  Repairs go one word at a time, which is exact.
    """
    if len(blob) <= 256:
        return put_slow(addr, blob, label, passes)

    ensure_bulk()
    w = list(struct.unpack(f'<{len(blob)//4}I', blob))
    t0 = time.time()

    orig = mem_get(ECHO_SLOT)
    if not orig or orig[0] not in (ECHO_ORIG, BULK):
        raise SystemExit(f'echo handler is {orig}, not free to borrow')
    mem_set(ECHO_SLOT, BULK)
    try:
        mem_set(BULK_STATE, addr)        # destination, advanced by the loader
        mem_set(BULK_STATE + 4, 0)       # bytes taken
        sent = 0
        while sent < len(blob):
            piece = blob[sent:sent + CHUNK]
            sh('echo ' + piece.hex())
            sent += len(piece)
            el = time.time() - t0
            print(f'\r  {label} {sent}/{len(blob)} B  {sent/el/1024:.1f} KiB/s ',
                  end='', flush=True)
    finally:
        mem_set(ECHO_SLOT, ECHO_ORIG)

    repaired = 0
    for attempt in range(passes):
        got = read_back(addr, len(w))
        bad = [i for i in range(len(w)) if i >= len(got) or got[i] != w[i]]
        if not bad:
            dt = time.time() - t0
            note = f', {repaired} repaired' if repaired else ''
            print(f'\r  {label} {len(blob)} bytes in {dt:.1f}s '
                  f'({len(blob)/dt/1024:.1f} KiB/s){note}          ')
            return w
        repaired += len(bad)
        print(f'\r  {label} pass {attempt+1}: {len(bad)} words missing, repairing ',
              end='', flush=True)
        for i in bad:
            mem_set(addr + i * 4, w[i])
    raise SystemExit(f'{label}: still short after {passes} passes')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('local')
    ap.add_argument('remote', help=r'camera path, e.g. \TEST.TXT')
    ap.add_argument('--mode', type=lambda s: int(s, 0), default=7,
                    help='7 truncates or creates (default); 0x402 fails if it exists')
    ap.add_argument('--buf', type=lambda s: int(s, 0), default=None)
    a = ap.parse_args()

    data = pathlib.Path(a.local).read_bytes()
    padded = data + b'\0' * (-len(data) % 4)
    path = a.remote.encode() + b'\0'
    if len(path) > 0xD0:
        raise SystemExit('path does not fit the parameter block')

    print(f'  local   {a.local}  {len(data)} bytes')
    print(f'  remote  {a.remote}  mode 0x{a.mode:X}')

    slot = mem_get(ECHO_SLOT)
    if not slot:
        raise SystemExit('could not read the echo handler slot')
    if slot[0] != ECHO_ORIG and slot[0] != CODE:
        raise SystemExit(f'echo handler is 0x{slot[0]:08X}, expected 0x{ECHO_ORIG:08X} '
                         '— something else has borrowed it')

    buf = a.buf or staging_area()
    fobj = buf + len(padded)
    print(f'  buffer  0x{buf:08X}, file object 0x{fobj:08X}')
    check_fits(buf, len(padded) + FOBJ_ROOM, 'staging')
    prove(buf, len(padded) + FOBJ_ROOM)
    print('  proof   region takes writes and still holds them a second later')

    put(buf, padded, 'stage ')

    for off, val in ((P_STATUS, 0), (P_OPENR, 0), (P_WRITER, 0), (P_DATA, buf),
                     (P_LEN, len(data)), (P_FOBJ, fobj), (P_MODE, a.mode)):
        mem_set(P + off, val)
    pw = path + b'\0' * (-len(path) % 4)
    for i, word in enumerate(struct.unpack(f'<{len(pw)//4}I', pw)):
        mem_set(P + P_PATH + i * 4, word)

    code = assemble(HERE / 'templates' / 'putfile.S')
    if CODE + len(code) > CODE_END:
        raise SystemExit('template does not fit the code region')
    put(CODE, code, 'code  ')

    mem_set(ECHO_SLOT, CODE)
    try:
        reply = sh('echo')
    finally:
        mem_set(ECHO_SLOT, ECHO_ORIG)
        back = mem_get(ECHO_SLOT)
        if not back or back[0] != ECHO_ORIG:
            print(f'  WARNING echo handler did not restore: {back}')
        else:
            print(f'  restored echo -> 0x{ECHO_ORIG:08X}')

    print(f'  reply   {reply.strip()}')
    st = mem_get(P + P_STATUS, 3)
    status = st[0] if st else 0
    print(f'  status  {status} — {STATUS.get(status, "unknown")}')
    if len(st) >= 3:
        print(f'  open    {st[1]}     write  {st[2]}   (both are flags, not counts)')
    if status != 2:
        return 1

    name = a.remote.lstrip('\\').split('\\')[-1]
    for line in sh('dir').splitlines():
        if name.lower() in line.lower():
            print(f'  dir     {line.strip()}')
            if str(len(data)) not in line:
                print(f'  WARNING directory size does not read {len(data)}')
            break
    else:
        print(f'  WARNING {name} did not appear in dir')
    return 0


if __name__ == '__main__':
    sys.exit(main())
