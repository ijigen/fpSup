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

CODE      = 0xC072F800          # the working template
CODE_END  = 0xC072FA00
BULK      = 0xC072FA00          # the bulk loader, resident alongside it
BULK_STATE = 0xC072F7F8         # its own two words, clear of the parameter block
DUMP      = 0xC072FB00          # the raw reader, in a slot of its own
DUMP_END  = 0xC072FC00          # memcpy_scratch starts here
DUMP_CAP  = 0x4000              # dumpraw's own ceiling; it truncates past this
                                # without saying so, and a short block leaves the
                                # host waiting for bytes that never come
DIRECT_CHUNK = 0x100000         # bytes per round trip on the direct path
# One megabyte measured fastest: 73 MB/s against 41 at two and 11 at three and a
# half. Not understood, so it is a measurement rather than a rule.
DUMP_CHUNK = DUMP_CAP - 4       # bytes per round trip, copying path
# Three thousand was chosen when the reply went out through printf and the rate
# went flat past that. Nothing about the raw path shares that ceiling: a chunk
# costs one command whatever its size, and a 31 MB file at three thousand bytes
# is eleven thousand of them. The round trip is four tenths of a millisecond and
# the misses are two hundred, so almost all of that time was the count, not the
# bytes. Four less than the buffer, because the address tag goes on the end and
# the capture buffer is exactly DUMP_CAP long.
# A run of this size used to stop answering somewhere between a hundred
# kilobytes and three megabytes, and only a cable replug brought it back. Two
# things fixed that: the worker never answers a raw request with nothing (the
# host's cancelled transfer was what took the USB device off the bus), and it
# waits three hundred milliseconds for a reply to be collected rather than fifty
# seconds (during which it was deaf to everything). A 31 MB DNG now comes off
# the card in one call, decodes, and is the picture that was taken.
READ_MAX = 64 * 1024 * 1024
READ_TIMEOUT = 200              # ms
# The median round trip is four tenths of a millisecond, so this is not a wait
# anyone pays: it is what a chunk is worth before giving up on it. Thirty looked
# generous by that measure and lost seven chunks in a hundred; two hundred loses
# one and a half, and a thousand loses exactly the same one and a half, so what
# is left is genuinely gone rather than slow. Being early costs more than being
# late here -- the camera has the block ready, and walking away from one it has
# prepared is what leaves the worker unable to answer anything again.
BULK_END  = 0xC072FB00
CHUNK     = 240                 # bytes per command; the line holds about 502 chars
P         = 0xC072F700          # parameter block
ECHO_SLOT = 0xC0BAC2F8          # command table entry 17, echo's handler pointer
ECHO_ORIG = 0xC03D99A0
POOL_PTR  = 0xC3757A7C          # where the AutoRun's pool address lands
POOL_OFF  = 0x10000             # the templates' own scratch, past shell and gyro
FOBJ_ROOM = 0x400

P_STATUS, P_OPENR, P_WRITER = 0x08, 0x0C, 0x10
P_DATA, P_LEN, P_FOBJ, P_MODE, P_PATH = 0x14, 0x18, 0x1C, 0x20, 0x24

STATUS = {0: 'never ran', 1: 'started but did not finish', 2: 'written',
          3: 'open returned 0', 4: 'write returned 0'}


def sh(line: str, retries: int = 3, raw: int = 0, timeout_ms: int = 0,
       want_hex: bool = False) -> str:
    """One command, one connection -- the daemon closes after each reply.

    Roughly one command in ten goes missing, in one direction or the other, so a
    reply that does not come back is retried rather than believed.  The daemon
    gives up after 200 ms, which is what makes retrying cheap.

    Not cheap enough, though, when the command itself answers in under two
    milliseconds: a reply lost every few dozen chunks then costs more than the
    entire rest of the read. `timeout_ms` says how long this particular command
    is worth waiting for. Leave it alone for anything that touches the card.
    """
    for attempt in range(retries + 1):
        s = socket.socket(socket.AF_UNIX)
        s.connect(SOCK)
        head = f'BULK {raw} '.encode() if raw else b'SHL '
        if timeout_ms:
            head = f'TMO {timeout_ms} '.encode() + head
        if want_hex:
            head = b'HEX ' + head
        s.sendall(head + line.encode() + b'\n')
        out = b''
        while True:
            b = s.recv(65536)
            if not b:
                break
            out += b
        s.close()
        text = out.decode(errors='replace')
        if not text.startswith('ERR'):
            if text.startswith('OKX '):
                # A raw block. The daemon hex-encodes it because a line-based
                # socket cannot carry arbitrary bytes; decode it back here so
                # there is one return type. Text replies survive the round trip
                # unchanged, which matters because any reply over 128 bytes now
                # comes this way -- including `mem get`.
                try:
                    return bytes.fromhex(text[4:].strip()).decode('latin-1')
                except ValueError:
                    return ''

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
                  f'  {(count-len(out))*el/max(len(out),1):.0f}s left ', end='', flush=True, file=sys.stderr)
    if count > READ_CHUNK * 16:
        print(f'\r  read   {count} words in {time.time()-t0:.1f}s'
              f' ({count*4/(time.time()-t0)/1024:.1f} KiB/s)          ', file=sys.stderr)
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
_stale = [0]        # blocks that answered a different address


DIRECT = 0xC072FC00             # dumpdirect, past dumpraw's slot
_direct_loaded = False


def ensure_direct():
    global _direct_loaded
    if not _direct_loaded:
        code = assemble(HERE / 'templates' / 'dumpdirect.S')
        put_slow(DIRECT, code, 'direct')
        _direct_loaded = True


def ensure_dump():
    global _dump_loaded
    if not _dump_loaded:
        code = assemble(HERE / 'templates' / 'dumpraw.S')
        if DUMP + len(code) > DUMP_END:
            raise SystemExit(f'dumpraw is {len(code)} bytes and would run into '
                             f'the scratch at 0x{DUMP_END:08X}')
        put_slow(DUMP, code, 'dump  ')
        _dump_loaded = True


def read_direct(addr, nbytes, label='direct'):
    """Read without copying: the worker points its TRB at `addr` itself.

    dumpraw stages everything through the shell's 16 KiB capture buffer, so a
    31 MB file came back in 1995 round trips and sixteen seconds. The card was
    never the slow part -- it reads that file into memory in 0.17 s, at
    183 MB/s -- it was a staging buffer we were copying through for no reason.
    A TRB carries a 24-bit length, so one transfer can be sixteen megabytes.

    Same file, whole thing, 0.42 s.

    `addr` must be somewhere the controller can reach as CPU-0x40000000: the
    pool, or what the firmware's allocator returns, which is where files land.
    The firmware's own image at 0xC0000000 is mapped some other way -- use
    read_bulk for that.

    No address tag either, so a stale reply cannot be told from a real one. That
    mattered when there were two thousand of them; at thirty-two it is a
    different bet, and one worth knowing you are making.
    """
    ensure_direct()
    orig = mem_get(ECHO_SLOT)
    if not orig or orig[0] not in (ECHO_ORIG, DIRECT):
        raise SystemExit(f'echo handler is {orig}, not free to borrow')
    out = bytearray()
    t0 = time.time()
    mem_set(ECHO_SLOT, DIRECT)
    try:
        while len(out) < nbytes:
            n = min(DIRECT_CHUNK, nbytes - len(out))
            for attempt in range(6):
                r = sh(f'echo {addr + len(out):X} {n:X}', retries=0, raw=n,
                       timeout_ms=4000)
                if len(r) >= n and not r.startswith('ERR'):
                    out += r[:n].encode('latin-1')
                    break
            else:
                raise SystemExit(f'{label}: no reply for {n} bytes at '
                                 f'0x{addr + len(out):08X}')
            el = time.time() - t0
            print(f'\r  {label} {len(out)}/{nbytes} B  {len(out)/el/1024/1024:.1f} MB/s ',
                  end='', flush=True, file=sys.stderr)
    finally:
        for _ in range(8):
            mem_set(ECHO_SLOT, ECHO_ORIG)
            if (mem_get(ECHO_SLOT) or [0])[0] == ECHO_ORIG:
                break
        else:
            print('  WARNING echo handler still borrowed')
    dt = time.time() - t0
    print(f'\r  {label} {nbytes} bytes in {dt:.2f}s '
          f'({nbytes/dt/1024/1024:.1f} MB/s)      ', file=sys.stderr)
    return bytes(out)


def read_bulk(addr, nbytes, label='read  '):
    """Read memory through dumpraw.S rather than `mem get`.

    `mem get` answers thirty-four characters for every four bytes, which is
    26 KiB/s. Printing bare hex instead reached 135. Neither was the link: the
    firmware's printf costs about a microsecond a character, and hex pays it
    twice over by doubling the volume first. dumpraw.S skips printf entirely --
    it puts the bytes in the reply buffer and sets the length itself -- so what
    crosses USB is the data.

    That got a 3000-byte block down to 0.27 ms, and then this function spent ten
    more setting up the next one: three parameter words, written one shell
    command at a time, one of which dumpraw never read. The address rides on the
    command line now, so a chunk is one command and there is nothing to set up
    and nothing remembered between calls.
    """
    ensure_dump()
    orig = mem_get(ECHO_SLOT)
    if not orig or orig[0] not in (ECHO_ORIG, DUMP):
        raise SystemExit(f'echo handler is {orig}, not free to borrow')
    chunk = min(DUMP_CHUNK, DUMP_CAP)
    if nbytes > READ_MAX:
        raise SystemExit(f'{label}: {nbytes} bytes in one go is past the '
                         f'{READ_MAX // 1024 // 1024} MiB this has been shown to '
                         f'survive. Read it in pieces.')
    out = bytearray()
    t0 = time.time()
    mem_set(ECHO_SLOT, DUMP)
    try:
        while len(out) < nbytes:
            n = min(chunk, nbytes - len(out))
            want = addr + len(out)
            for attempt in range(12):
                # The raw path needs a worker that understands it. Fall back to
                # the header-framed one so the tool works against either.
                # The raw path. The framed one carries a header saying how
                # many bytes really follow, which sounded like the answer to a
                # worker that sometimes sends none at all -- and it is, for that
                # one symptom. It was measured: still dies, at a third of the
                # speed. Whatever loses the link is not the reply format.
                # Ask for four more than wanted: dumpraw puts the address it
                # read from on the end. A raw block is otherwise anonymous, and
                # a reply abandoned by one read and collected by the next looks
                # exactly like the right answer -- five blocks in forty-two came
                # back belonging to somewhere else, all of them plausible.
                reply = sh(f'echo {want:X} {n:X}', retries=0, raw=n + 4,
                           timeout_ms=READ_TIMEOUT)
                if len(reply) >= n + 4 and not reply.startswith('ERR'):
                    blk = reply[:n + 4].encode('latin-1')
                    if int.from_bytes(blk[n:n + 4], 'little') == want:
                        out += blk[:n]
                        break
                    _stale[0] += 1
            else:
                raise SystemExit(f'{label}: no reply for {n} bytes at '
                                 f'0x{want:08X}')
            el = time.time() - t0
            print(f'\r  {label} {len(out)}/{nbytes} B  {len(out)/el/1024:.0f} KiB/s ',
                  end='', flush=True, file=sys.stderr)
    finally:
        # Put it back, and check.  A single write is not enough: the transport
        # drops commands, and an unrestored handler means the next `echo`
        # anywhere runs whatever is in the cave.
        for _ in range(8):
            mem_set(ECHO_SLOT, ECHO_ORIG)
            if (mem_get(ECHO_SLOT) or [0])[0] == ECHO_ORIG:
                break
        else:
            print(f'  WARNING echo handler still borrowed — restore it before '
                  f'anything else uses `echo`')
    dt = time.time() - t0
    print(f'\r  {label} {nbytes} bytes in {dt:.1f}s ({nbytes/dt/1024:.0f} KiB/s)      ', file=sys.stderr)
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
                  end='', flush=True, file=sys.stderr)
    finally:
        mem_set(ECHO_SLOT, ECHO_ORIG)

    repaired = 0
    for attempt in range(passes):
        # read_bulk, not read_back: the same bytes at a hundred times the rate.
        # `mem get` answers thirty-four characters for every four bytes and gets
        # 22 KiB/s, which used to be half the cost of loading anything. dumpraw
        # is loaded by put_slow, which still verifies the slow way -- it has to,
        # since it is what puts dumpraw there.
        got = list(struct.unpack(f'<{len(w)}I', read_bulk(addr, len(w) * 4,
                                                          'verify')))
        bad = [i for i in range(len(w)) if i >= len(got) or got[i] != w[i]]
        if not bad:
            dt = time.time() - t0
            note = f', {repaired} repaired' if repaired else ''
            print(f'\r  {label} {len(blob)} bytes in {dt:.1f}s '
                  f'({len(blob)/dt/1024:.1f} KiB/s){note}          ', file=sys.stderr)
            return w
        repaired += len(bad)
        print(f'\r  {label} pass {attempt+1}: {len(bad)} words missing, repairing ',
              end='', flush=True, file=sys.stderr)
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
