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

CODE      = 0xC072F600          # the templates' code region
CODE_END  = 0xC0730000
P         = 0xC072F500          # parameter block
ECHO_SLOT = 0xC0BAC2F8          # command table entry 17, echo's handler pointer
ECHO_ORIG = 0xC03D99A0
POOL_PTR  = 0xC3757A7C          # where the AutoRun's pool address lands
POOL_OFF  = 0x2000              # past the 4 KiB the shell's own frames use
FOBJ_ROOM = 0x400

P_STATUS, P_OPENR, P_WRITER = 0x08, 0x0C, 0x10
P_DATA, P_LEN, P_FOBJ, P_MODE, P_PATH = 0x14, 0x18, 0x1C, 0x20, 0x24

STATUS = {0: 'never ran', 1: 'started but did not finish', 2: 'written',
          3: 'open returned 0', 4: 'write returned 0'}


def sh(line: str) -> str:
    """One command, one connection -- the daemon closes after each reply."""
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
    # the daemon escapes newlines so a reply stays one line on the wire
    text = out.decode(errors='replace')
    if text.startswith('OK '):
        text = text[3:]
    return text.replace('\\n', '\n')


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
    which was enough.  So the address is derived instead: the pool the AutoRun
    already took, skipping the first 4 KiB, which is the frame buffer that every
    shell command overwrites.  The gyro logger wrote megabytes from +0x2000
    onward across many recordings, so the region is known to be ours.
    """
    got = mem_get(POOL_PTR)
    if not got or not 0x40000000 <= got[0] < 0x50000000:
        raise SystemExit(f'0x{POOL_PTR:08X} does not hold a pool address ({got})')
    return got[0] + POOL_OFF


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


def read_back(addr, count):
    """Read `count` words in 16-word requests."""
    out = []
    for base in range(0, count, 16):
        out += mem_get(addr + base * 4, min(16, count - base))
    return out


def put(addr, blob, label, passes=6):
    """Write, verify, rewrite what did not land, until nothing is left.

    `mem set` drops writes.  Measured over 200 words: 18 lost at full speed,
    none on the next run, 48 on the one after -- so it is not pacing, and no
    delay makes it safe.  Reads are reliable: three verifies of the same region
    named the same two words every time, so what is missing is genuinely not
    there rather than misread.

    Nothing downstream can tell a dropped word from a real one -- the two words
    lost out of this template's 78 turned `movt ip, #0xC044` into the `blx ip`
    that followed it, which would have called whatever address ip held.
    """
    w = list(struct.unpack(f'<{len(blob)//4}I', blob))
    t0 = time.time()
    for i, word in enumerate(w):
        mem_set(addr + i * 4, word)
        if i % 64 == 63:
            el = time.time() - t0
            print(f'\r  {label} {i+1}/{len(w)}  {(i+1)/el:.0f}/s  '
                  f'{(len(w)-i-1)*el/(i+1):.0f}s left ', end='', flush=True)

    repaired = 0
    for attempt in range(passes):
        got = read_back(addr, len(w))
        bad = [i for i in range(len(w)) if i >= len(got) or got[i] != w[i]]
        if not bad:
            dt = time.time() - t0
            note = f', {repaired} rewritten' if repaired else ''
            print(f'\r  {label} {len(w)} words verified in {dt:.1f}s{note}      ')
            return w
        repaired += len(bad)
        print(f'\r  {label} pass {attempt+1}: {len(bad)} did not land, rewriting  ',
              end='', flush=True)
        for i in bad:
            mem_set(addr + i * 4, w[i])
    raise SystemExit(f'{label}: still short after {passes} passes — nothing was run')


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
