#!/usr/bin/env python3
"""Run the fixed-block pool once on the camera and read every answer.

The pool is the technique the audio writer posts its work with: a descriptor is
a queue slot, so "the pool is empty" is "the queue is full" with no bookkeeping
of our own.  What makes it usable during a recording is that it is not a heap
channel and not a kernel object -- just a free list guarded by masking
interrupts -- so nothing the recording path allocates can be short because of
it.  Holding 64 KiB of channel 10 is what froze the camera; this cannot.
"""
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'fp_usb_shell'))

import putfile as P                                            # noqa: E402
from armasm import assemble                                    # noqa: E402

CODE_AT = 0xC072ECF0
CAVE_HI = 0xC072EFA0
ARG_POOL, ARG_RESULT = 0xC072E0F0, 0xC072E0F4
POOL_PTR = 0xC3757A7C
POOL_OBJ_OFF, RESULT_OFF = 0x40000, 0x41000

EXPECT = [
    (1, 'free after init', 4),
    (2, 'free after draining it', 0),
    (3, 'high water mark', 4),
    (8, 'the allocation past the end', 0),
    (9, 'failed allocations counted', 1),
    (10, 'freeing a real block', 1),
    (11, 'freeing it a second time', 0),
    (13, 'freeing a pointer never ours', 0),
    (14, 'free after all that', 1),
    (15, 'the probe reached the end', 0x600D0000),
]


def main():
    code = assemble(HERE / 'mpool_probe.S')
    end = CODE_AT + len(code)
    if end > CAVE_HI:
        raise SystemExit(f'0x{CODE_AT:08X}..0x{end:08X} runs into the park stub')
    pool = P.mem_get(POOL_PTR)[0]
    if not pool or not 0x40000000 <= pool < 0x50000000:
        raise SystemExit(f'the pool pointer reads 0x{pool or 0:08X}')
    obj, res = pool + POOL_OBJ_OFF, pool + RESULT_OFF
    print(f'code 0x{CODE_AT:08X}..0x{end:08X} ({len(code)} bytes)')
    print(f'pool object 0x{obj:08X}   results 0x{res:08X}')

    P.put_slow(CODE_AT, code, 'mpool_probe')
    for addr, value, what in ((ARG_POOL, obj, 'the pool address'),
                              (ARG_RESULT, res, 'the result address')):
        for _ in range(8):
            P.mem_set(addr, value)
            if (P.mem_get(addr) or [0])[0] == value:
                break
        else:
            raise SystemExit(f'could not write {what}')
    P.put_slow(res, b'\0' * 64, 'results')

    orig = P.mem_get(P.ECHO_SLOT)
    if not orig or orig[0] != P.ECHO_ORIG:
        raise SystemExit(f'echo handler is {orig}, not free to borrow')
    for _ in range(8):
        P.mem_set(P.ECHO_SLOT, CODE_AT)
        if (P.mem_get(P.ECHO_SLOT) or [0])[0] == CODE_AT:
            break
    try:
        P.sh('echo', retries=0)
    finally:
        for _ in range(8):
            P.mem_set(P.ECHO_SLOT, P.ECHO_ORIG)
            if (P.mem_get(P.ECHO_SLOT) or [0])[0] == P.ECHO_ORIG:
                break
        else:
            raise SystemExit('LEFT THE ECHO HANDLER REDIRECTED -- reboot')

    w = P.mem_get(res, 16)
    print()
    print(f'  [0] pool size        {w[0]} bytes')
    print(f'  [4..7] blocks        ' + ' '.join(
        f'0x{x:08X}' if x else '(none)' for x in w[4:8]))
    bad = 0
    for i, what, want in EXPECT:
        got = w[i]
        ok = got == want
        bad += not ok
        print(f'  {"ok " if ok else "BAD"} [{i:2d}] {what:32s} {got}'
              + ('' if ok else f'   expected {want}'))
    stride = (w[5] - w[4]) if w[4] and w[5] else 0
    if stride:
        print(f'  block stride {stride} bytes (24 payload + 8 header)')
    print()
    print('every failure mode held' if not bad else f'{bad} checks failed')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
