#!/usr/bin/env python3
"""Does memory from the firmware's allocator survive a recording?

    ./heap_survives.py          allocate and mark
    ...record a clip...
    ./heap_survives.py --check

Two attempts at writing the gcsv during a take froze the camera, and both wrote
into a buffer the allocator handed out. That buffer was only ever checked while
the camera was idle -- it took the writes and gave them back -- which is exactly
the evidence memprobe's own docstring calls worthless:

    a region that takes a write while the camera is idle can still belong to
    somebody who reinitialises it the moment recording starts

The pool got the full test the same night: mark, record, check, 224 of 224
standing. What the allocator hands out never did. This is that test.

It matters beyond the gcsv. The plan is to move the shell's buffers off the
hand-carved pool and onto this allocator; if what it returns is not safe during
a recording, that plan needs rethinking rather than implementing.
"""
import subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHELL = HERE.parent / 'fp_usb_shell'
sys.path.insert(0, str(SHELL))

from armasm import assemble                                    # noqa: E402
import putfile as P                                            # noqa: E402

SIZE = 0x10000
KEEP = HERE / '.heap_probe_addr'


def allocate() -> int:
    P.put(P.CODE, assemble(SHELL / 'templates' / 'heapalloc.S'), 'heap  ')
    orig = P.mem_get(P.ECHO_SLOT)
    if not orig or orig[0] not in (P.ECHO_ORIG, P.CODE):
        raise SystemExit(f'echo handler is {orig}, not free to borrow')
    try:
        P.mem_set(P.ECHO_SLOT, P.CODE)
        for off, val in ((0x00, 0), (0x04, 10), (0x08, SIZE)):
            P.mem_set(P.P + off, val)
        P.sh('echo', retries=2)
        got = P.mem_get(P.P + 0x0C)
    finally:
        for _ in range(10):
            P.mem_set(P.ECHO_SLOT, P.ECHO_ORIG)
            if (P.mem_get(P.ECHO_SLOT) or [0])[0] == P.ECHO_ORIG:
                break
    if not got or not got[0]:
        raise SystemExit('the allocator refused')
    return got[0]


def main() -> int:
    check = '--check' in sys.argv
    if check:
        if not KEEP.exists():
            raise SystemExit('nothing marked: run without --check first')
        addr = int(KEEP.read_text().strip(), 0)
        print(f'  checking 0x{addr:08X}')
    else:
        addr = allocate()
        KEEP.write_text(hex(addr))
        print(f'  allocated 0x{addr:08X}, {SIZE // 1024} KiB')
    args = [sys.executable, str(SHELL / 'memprobe.py'), hex(addr), hex(SIZE)]
    if check:
        args.append('--check')
    return subprocess.call(args, cwd=SHELL)


if __name__ == '__main__':
    sys.exit(main())
