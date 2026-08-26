#!/usr/bin/env python3
"""Give the logger its gcsv text buffer, from the host.

The camera does not ask for this itself. The first attempt had the writer thread
call the firmware allocator at the moment a recording started, and the camera
froze: that thread holds locks the rest of the camera waits on, and the
allocator had only ever been exercised from a borrowed shell command with the
camera idle. Verified in one context is not verified in another -- which is the
same mistake that cost two card-reader trips earlier the same night.

So the allocation happens here, in the context that was actually tested, while
nothing is recording. The logger reads the address out of its state block and
uses it; a zero there simply means no gcsv, and the .GYR records as always.

Nothing frees it. It is one buffer for the session, reused by every take, and
handing it back would be another allocator call in a context nobody has tested.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'fp_usb_shell'))

from armasm import assemble                                    # noqa: E402
import putfile as P                                            # noqa: E402

O_STATE, S_TXT_BUF = 0x6000, 0x90
TXT_SIZE = 0x10000
HEAP_TYPE = 10


def main() -> int:
    pool = P.mem_get(P.POOL_PTR)
    if not pool:
        raise SystemExit('no pool pointer: is the shell up?')
    state = pool[0] + O_STATE

    have = P.mem_get(state + S_TXT_BUF)
    if have and have[0]:
        print(f'  the logger already has one at 0x{have[0]:08X}')
        return 0

    P.put(P.CODE, assemble(HERE.parent / 'fp_usb_shell' / 'templates' / 'heapalloc.S'),
          'heap  ')
    orig = P.mem_get(P.ECHO_SLOT)
    if not orig or orig[0] not in (P.ECHO_ORIG, P.CODE):
        raise SystemExit(f'echo handler is {orig}, not free to borrow')
    try:
        P.mem_set(P.ECHO_SLOT, P.CODE)
        for off, val in ((0x00, 0), (0x04, HEAP_TYPE), (0x08, TXT_SIZE)):
            P.mem_set(P.P + off, val)
        print(' ', P.sh('echo', retries=2).strip())
        got = P.mem_get(P.P + 0x0C)
    finally:
        for _ in range(10):
            P.mem_set(P.ECHO_SLOT, P.ECHO_ORIG)
            if (P.mem_get(P.ECHO_SLOT) or [0])[0] == P.ECHO_ORIG:
                break
        else:
            print('  WARNING echo handler still borrowed')

    if not got or not got[0]:
        raise SystemExit('  the allocator refused; the logger will skip the gcsv')
    addr = got[0]

    # Prove it before handing it over: a buffer that is not ours is worse than
    # none, because the logger would write a take's worth of text into it.
    P.mem_set(addr, 0xC0DE0001)
    P.mem_set(addr + TXT_SIZE - 4, 0xC0DE0002)
    head, tail = P.mem_get(addr), P.mem_get(addr + TXT_SIZE - 4)
    if not (head and tail and head[0] == 0xC0DE0001 and tail[0] == 0xC0DE0002):
        raise SystemExit(f'  0x{addr:08X} did not hold the markers; not using it')

    for _ in range(8):
        P.mem_set(state + S_TXT_BUF, addr)
        back = P.mem_get(state + S_TXT_BUF)
        if back and back[0] == addr:
            break
    else:
        raise SystemExit('  could not write the address into the state block')
    print(f'  text buffer 0x{addr:08X}, {TXT_SIZE // 1024} KiB, head and tail verified')
    return 0


if __name__ == '__main__':
    sys.exit(main())
