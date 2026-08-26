#!/usr/bin/env python3
"""Read a file off the camera's card, over the shell.

    ./getfile.py '\\AutoRun.txt' out.txt

The other half of putfile.py, and what makes writing a file safe: a write can be
read back and compared before anything acts on it.  The AutoRun only runs at
boot, so a bad write costs nothing as long as it is caught before the next one.
"""
import argparse, pathlib, struct, sys, time

from armasm import assemble
from putfile import (sh, mem_set, mem_get, staging_area, put, read_bulk, read_direct, check_fits,
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
    ap.add_argument('--buf', type=lambda s: int(s, 0), default=None)
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

    # Ask the firmware for the buffer rather than carving one out of the
    # megabyte grabbed at boot. That pool has to hold the gyro logger, the
    # capture buffer and this at once, so a file could not exceed what had been
    # reserved for every purpose together -- and two users of it colliding
    # showed up as damage somewhere unrelated. The camera's own code asks for
    # ten megabytes to put a photo on screen; the allocator has been measured
    # good to thirty-two.
    #
    # Slack on the end, the way the firmware does it: it never asks how big a
    # file is, it asks for more than it can be and reads the count back. A read
    # that returns exactly what was asked for is the one to distrust.
    words = (size + 3) // 4
    fobj = staging_area()                # small, and wanted before the call
    heap = a.buf is None
    buf = 0 if heap else a.buf
    ask = size + 0x1000 if heap else size
    print(f'  buffer  {"from the firmware" if heap else f"0x{buf:08X}"}'
          f', file object 0x{fobj:08X}')
    check_fits(fobj, 0x400, 'file object')

    # Poison every 4 KiB rather than the whole buffer.  Filling 247 KB with a
    # pattern took longer than reading the file twice over, and one marker per
    # page catches the case it is there for -- a read that did not happen.
    # Poisoning catches a read that never happened. It needs the address
    # beforehand, which a heap buffer does not have -- there the count the
    # firmware reports does the same job, and is checked below.
    marks = [] if heap else list(range(0, words, 1024)) + [words - 1]
    for i in marks:
        mem_set(buf + i * 4, POISON)

    path = a.remote.encode() + b'\0'
    for off, val in ((P_ACTUAL, 0), (P_STATUS, 0), (P_OPENR, 0), (P_READR, 0),
                     (P_BUF, buf), (P_LEN, ask), (P_FOBJ, fobj), (P_MODE, a.mode)):
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
    if heap:
        got = mem_get(P + P_BUF)
        if not got or not got[0]:
            raise SystemExit('  the allocator refused; nothing was read')
        buf = got[0]
        print(f'  buffer  0x{buf:08X} ({ask} bytes asked for)')
    st = mem_get(P, 5)
    status = st[P_STATUS // 4]
    print(f'  status  {status} — {STATUS.get(status, "unknown")}')
    print(f'  open    {st[P_OPENR//4]}   read {st[P_READR//4]}   '
          f'actual {st[P_ACTUAL//4]} of {size}')
    if status != 2:
        return 1

    actual = st[P_ACTUAL // 4]
    if heap and actual >= ask:
        raise SystemExit(f'  read filled the whole buffer ({actual}); the file '
                         f'is longer than it was thought to be')
    # The buffer came from the firmware's allocator, which the controller can
    # reach directly -- so there is no reason to copy it through a 16 KiB
    # staging buffer sixteen kilobytes at a time.
    data = (read_direct(buf, size) if heap else read_bulk(buf, size, 'fetch '))
    if heap:
        from callfn import call
        call(0xC001D7A0, r0=P + 0xE0, r1=2, verbose=False)   # free
        print('  buffer  handed back')
    left = sum(1 for i in marks if i * 4 + 4 <= len(data)
               and struct.unpack_from('<I', data, i * 4)[0] == POISON)
    if left:
        print(f'  WARNING {left} of {len(marks)} markers survived — that much was not read')

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
