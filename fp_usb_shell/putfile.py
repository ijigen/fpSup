#!/usr/bin/env python3
"""Write a local file onto the camera's card, over the shell.

    ./putfile.py autorun/AutoRun.txt '\\AutoRun.txt'

Which is how the AutoRun gets updated without taking the card out: the file the
shell was started from is just a file, and the shell can replace it.

Most of this is native shell commands.  `memmgr bufmem get` hands out a buffer,
`mem set` fills it, `dir` shows the result.  Only the write itself is code --
nothing in the shell writes arbitrary content to a path -- and that is the
putfile template, fired once through the borrowed call site.

Nothing is left behind: the template restores the call site itself, and the task
it starts exits as soon as the file is closed.
"""
import argparse, pathlib, re, struct, subprocess, sys, time

from armasm import assemble, symbols, words

HERE = pathlib.Path(__file__).resolve().parent
FPSH = HERE / 'host' / 'fpsh'

P         = 0xC072F500          # parameter block, shared with the one-shot map
CODE      = 0xC072F600
CODE_END  = 0xC0730000
HOOK_SITE = 0xC00D0794
FOBJ_ROOM = 0x400               # scratch the file object needs after the data

P_DONE, P_RESULT, P_STATUS, P_OPENR, P_WRITER = 0x00, 0x04, 0x08, 0x0C, 0x10
P_DATA, P_LEN, P_FOBJ, P_MODE, P_PATH         = 0x14, 0x18, 0x1C, 0x20, 0x24

STATUS = {0: 'not started', 1: 'running', 2: 'written',
          3: 'open returned 0', 4: 'write returned 0', 5: 'write was short'}


def sh(*cmd) -> str:
    r = subprocess.run([str(FPSH), *cmd], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"fpsh {' '.join(cmd)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def mem_set(addr, value):
    sh('shl', f'mem set 0x{addr:08X} 0x{value:08X}')


def mem_get(addr, count):
    out = sh('shl', f'mem get 0x{addr:08X},,0x{count * 4:X}')
    vals = []
    for line in out.splitlines():
        toks = re.findall(r'\b[0-9A-Fa-f]{8}\b', line)
        if toks and int(toks[0], 16) in range(addr - 4, addr + count * 4 + 4):
            toks = toks[1:]
        vals += [int(t, 16) for t in toks]
    return vals


def alloc(size):
    """Ask the shell for a buffer.  Returns the address it reports."""
    out = sh('shl', f'memmgr bufmem get 0 0x{size:X} 0x40')
    cands = [int(t, 16) for t in re.findall(r'\b[0-9A-Fa-f]{8}\b', out)
             if 0x40000000 <= int(t, 16) < 0x50000000]
    if not cands:
        raise SystemExit(f'could not find a buffer address in:\n{out}')
    return cands[0]


def put_words(addr, blob, label):
    w = list(struct.unpack(f'<{len(blob)//4}I', blob))
    t0 = time.time()
    for i, word in enumerate(w):
        mem_set(addr + i * 4, word)
        if i % 128 == 127:
            rate = (i + 1) / (time.time() - t0)
            print(f'\r  {label} {i+1}/{len(w)} words  {rate:.0f}/s', end='', flush=True)
    dt = time.time() - t0
    print(f'\r  {label} {len(w)}/{len(w)} words in {dt:.1f}s'
          f'  ({len(blob)/dt/1024:.1f} KiB/s)')
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('local')
    ap.add_argument('remote', help=r'camera path, e.g. \AutoRun.txt')
    ap.add_argument('--mode', type=lambda s: int(s, 0), default=7,
                    help='7 truncates or creates (default); 0x402 fails if it exists')
    ap.add_argument('--buf', type=lambda s: int(s, 0), default=None,
                    help='skip memmgr and stage into this address')
    ap.add_argument('--timeout', type=float, default=30.0)
    ap.add_argument('--no-verify', action='store_true')
    a = ap.parse_args()

    data = pathlib.Path(a.local).read_bytes()
    padded = data + b'\0' * (-len(data) % 4)
    path = a.remote.encode() + b'\0'
    if len(path) > 0xD8:
        raise SystemExit('path does not fit the parameter block')

    print(f'  local   {a.local}  {len(data)} bytes')
    print(f'  remote  {a.remote}  mode 0x{a.mode:X}')

    buf = a.buf if a.buf else alloc(len(padded) + FOBJ_ROOM)
    fobj = buf + len(padded)
    print(f'  buffer  0x{buf:08X}, file object at 0x{fobj:08X}')

    # prove the buffer before trusting it -- a write that does not land reads
    # back as the old value, and every byte after that would be a guess
    mem_set(buf, 0xC0DEC0DE)
    got = mem_get(buf, 1)
    if not got or got[0] != 0xC0DEC0DE:
        raise SystemExit(f'0x{buf:08X} did not take a test write ({got})')

    put_words(buf, padded, 'stage ')

    code = assemble(HERE / 'templates' / 'putfile.S')
    if CODE + len(code) > CODE_END:
        raise SystemExit('template does not fit the code region')

    # parameter block first, then the code, then arm -- never the other way
    sh('shl', f'mem set 0x{P + P_DONE:08X} 0x00000000')
    for off, val in ((P_STATUS, 0), (P_OPENR, 0), (P_WRITER, 0),
                     (P_DATA, buf), (P_LEN, len(data)), (P_FOBJ, fobj),
                     (P_MODE, a.mode)):
        mem_set(P + off, val)
    pw = path + b'\0' * (-len(path) % 4)
    for i, word in enumerate(struct.unpack(f'<{len(pw)//4}I', pw)):
        mem_set(P + P_PATH + i * 4, word)

    put_words(CODE, code, 'code  ')

    entry = CODE + symbols(HERE / 'templates' / 'putfile.S')['entry']
    disp = (entry - HOOK_SITE - 8) >> 2
    mem_set(HOOK_SITE, 0xEA000000 | (disp & 0xFFFFFF))
    print(f'  armed   0x{HOOK_SITE:08X} -> 0x{entry:08X}')

    deadline = time.time() + a.timeout
    status = 0
    while time.time() < deadline:
        s = mem_get(P + P_STATUS, 1)
        status = s[0] if s else 0
        if status >= 2:
            break
        time.sleep(0.2)

    openr, writer = (mem_get(P + P_OPENR, 2) + [0, 0])[:2]
    print(f'  status  {status} — {STATUS.get(status, "unknown")}')
    print(f'  open    0x{openr:08X}     write  {writer} bytes')
    if status != 2:
        return 1

    if not a.no_verify:
        listing = sh('shl', 'dir')
        name = a.remote.lstrip('\\').split('\\')[-1]
        for line in listing.splitlines():
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
