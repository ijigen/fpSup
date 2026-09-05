#!/usr/bin/env python3
"""Find which part of the pool probe wedged the camera, by bisecting it.

    ./mpool_stage.py 1     marker only -- is the vehicle sound?
    ./mpool_stage.py 2     + mpool_init
    ./mpool_stage.py 3     + mpool_alloc, including the one past the end
    ./mpool_stage.py 4     + mpool_free and its refusals

Each stage does everything the one below does and one thing more, and writes a
different marker word last.  Whichever stage stops answering is the one to look
at -- the previous attempt guessed three times and was wrong three times.
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'fp_usb_shell'))

import putfile as P                                            # noqa: E402
from armasm import assemble                                    # noqa: E402

CODE_AT, CAVE_HI = 0xC072ECF0, 0xC072EFA0
ARG_POOL, ARG_RESULT = 0xC072E0F0, 0xC072E0F4
POOL_PTR = 0xC3757A7C
MARKS = {1: 0xAAAA1111, 2: 0xAAAA2222, 3: 0xAAAA3333, 4: 0xAAAA4444}


def setw(addr, value, what):
    for _ in range(8):
        P.mem_set(addr, value)
        if (P.mem_get(addr) or [0])[0] == value:
            return
    raise SystemExit(f'could not write {what} at 0x{addr:08X}')


def main():
    stage = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    code = assemble(HERE / 'mpool_stage.S', (f'STAGE={stage}',))
    end = CODE_AT + len(code)
    if end > CAVE_HI:
        raise SystemExit(f'0x{CODE_AT:08X}..0x{end:08X} runs into the park stub')
    pool = P.mem_get(POOL_PTR)[0]
    if not pool or not 0x40000000 <= pool < 0x50000000:
        raise SystemExit(f'the pool pointer reads 0x{pool or 0:08X}')
    obj, res = pool + 0x40000, pool + 0x41000
    print(f'stage {stage}: {len(code)} bytes at 0x{CODE_AT:08X}..0x{end:08X}')
    print(f'  pool object 0x{obj:08X}   results 0x{res:08X}')

    P.put_slow(CODE_AT, code, f'stage {stage}')
    setw(ARG_POOL, obj, 'the pool address')
    setw(ARG_RESULT, res, 'the result address')
    P.put_slow(res, b'\0' * 64, 'results')

    orig = P.mem_get(P.ECHO_SLOT)
    if not orig or orig[0] != P.ECHO_ORIG:
        raise SystemExit(f'echo handler is {orig}, not free to borrow')
    setw(P.ECHO_SLOT, CODE_AT, 'the echo handler')
    fired = False
    try:
        P.sh('echo', retries=0)
        fired = True
    finally:
        for _ in range(8):
            P.mem_set(P.ECHO_SLOT, P.ECHO_ORIG)
            if (P.mem_get(P.ECHO_SLOT) or [0])[0] == P.ECHO_ORIG:
                print('  echo handler restored')
                break
        else:
            print('  !! the echo handler could not be restored -- reboot')
            print('     (it lives in RAM, so a power cycle clears it)')

    if not fired:
        return 1
    w = P.mem_get(res, 16)
    if w[15] is None:
        print('  results unreadable')
        return 1
    print(f'  marker  0x{w[15]:08X}   (stage {stage} wanted 0x{MARKS[stage]:08X})')
    if w[15] != MARKS[stage]:
        print('  the stage did not reach its end')
        return 1
    if stage >= 2:
        print(f'  pool size {w[0]}   free after init {w[1]}')
    if stage >= 3:
        print(f'  blocks ' + ' '.join(f'0x{x:08X}' if x else '(none)' for x in w[4:8]))
        print(f'  free after draining {w[2]}   high water {w[3]}')
        print(f'  alloc past the end {w[8]}   failures counted {w[9]}')
    if stage >= 4:
        print(f'  free a real block {w[10]}   the same one again {w[11]}')
        print(f'  free a foreign pointer {w[13]}   free at the end {w[14]}')
    print(f'  stage {stage} completed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
