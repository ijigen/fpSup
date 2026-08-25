#!/usr/bin/env python3
"""Read a file off the camera's card, over the shell.

    ./getfile.py '\\AutoRun.txt' out.txt

The other half of putfile.py, and what makes writing a file safe: a write can be
read back and compared before anything acts on it.  The AutoRun only runs at
boot, so a bad write costs nothing as long as it is caught before the next one.
"""
import argparse, pathlib, struct, sys, time

from armasm import assemble
from putfile import (sh, mem_set, mem_get, staging_area, put, read_back,
                     CODE, CODE_END, P, ECHO_SLOT, ECHO_ORIG, HERE)

P_ACTUAL, P_STATUS, P_OPENR, P_READR = 0x04, 0x08, 0x0C, 0x10
P_BUF, P_LEN, P_FOBJ, P_MODE, P_PATH = 0x14, 0x18, 0x1C, 0x20, 0x24

STATUS = {0: 'never ran', 1: 'started but did not finish', 2: 'read',
          3: 'open returned 0', 4: 'read returned 0'}

POISON = 0xDEADBEEF


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('remote', help=r'camera path, e.g. \AutoRun.txt')
    ap.add_argument('local', nargs='?', help='where to save it; omit to only print')
    ap.add_argument('--size', type=lambda s: int(s, 0), default=None,
                    help='bytes to read; default comes from dir')
    ap.add_argument('--mode', type=lambda s: int(s, 0), default=1)
    a = ap.parse_args()

    name = a.remote.lstrip('\\').split('\\')[-1]
    size = a.size
    if size is None:
        for line in sh('dir').splitlines():
            parts = line.split()
            if parts and parts[-1].lower() == name.lower() and len(parts) >= 4:
                try:
                    size = int(parts[-2])
                except ValueError:
                    pass
                break
        if size is None:
            raise SystemExit(f'{name} is not in dir, and no --size was given')
    print(f'  remote  {a.remote}  {size} bytes, mode 0x{a.mode:X}')

    words = (size + 3) // 4
    buf = staging_area()
    fobj = buf + words * 4 + 4
    print(f'  buffer  0x{buf:08X}, file object 0x{fobj:08X}')

    # poison first, so what comes back is known to have been read, not left over
    put(buf, struct.pack(f'<{words}I', *([POISON] * words)), 'poison')

    path = a.remote.encode() + b'\0'
    for off, val in ((P_ACTUAL, 0), (P_STATUS, 0), (P_OPENR, 0), (P_READR, 0),
                     (P_BUF, buf), (P_LEN, size), (P_FOBJ, fobj), (P_MODE, a.mode)):
        mem_set(P + off, val)
    pw = path + b'\0' * (-len(path) % 4)
    for i, w in enumerate(struct.unpack(f'<{len(pw)//4}I', pw)):
        mem_set(P + P_PATH + i * 4, w)

    code = assemble(HERE / 'templates' / 'getfile.S')
    if CODE + len(code) > CODE_END:
        raise SystemExit('template does not fit')
    put(CODE, code, 'code  ')

    mem_set(ECHO_SLOT, CODE)
    try:
        reply = sh('echo')
    finally:
        mem_set(ECHO_SLOT, ECHO_ORIG)
        back = mem_get(ECHO_SLOT)
        if not back or back[0] != ECHO_ORIG:
            print(f'  WARNING echo handler did not restore: {back}')

    print(f'  reply   {reply.strip()}')
    st = mem_get(P, 5)
    status = st[P_STATUS // 4]
    print(f'  status  {status} — {STATUS.get(status, "unknown")}')
    print(f'  open    {st[P_OPENR//4]}   read {st[P_READR//4]}   '
          f'actual {st[P_ACTUAL//4]} of {size}')
    if status != 2:
        return 1

    t0 = time.time()
    got = read_back(buf, words)
    if any(v is None for v in got):
        raise SystemExit('some words could not be read back')
    data = struct.pack(f'<{words}I', *got)[:size]
    print(f'  fetched {len(data)} bytes in {time.time()-t0:.1f}s')
    if data.count(struct.pack('<I', POISON)) :
        n = data.count(struct.pack('<I', POISON))
        print(f'  WARNING {n} words still hold the poison — that much was not read')

    if a.local:
        pathlib.Path(a.local).write_bytes(data)
        print(f'  saved   {a.local}')
    else:
        print('  ---')
        sys.stdout.write(data.decode('latin1'))
        print('  ---')
    return 0


if __name__ == '__main__':
    sys.exit(main())
