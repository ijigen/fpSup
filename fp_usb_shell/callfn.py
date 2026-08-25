#!/usr/bin/env python3
"""Call one function on the camera and report what it returned.

    ./callfn.py 0xC072E380 --r10 0x4502C680

Bringing up resident code a routine at a time.  A logger that hooks a 2500 Hz
callback gets one chance to be right; calling its pieces from a shell command
first costs nothing when they are wrong.
"""
import argparse, sys

from armasm import assemble
from putfile import sh, mem_set, mem_get, put, CODE, CODE_END, P, ECHO_SLOT, ECHO_ORIG, HERE

P_FN, P_R0, P_R1, P_R2, P_R3, P_R10, P_RET, P_DONE = (
    0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C)
DONE = 0xD09E0000

_loaded = [False]


def call(fn, r0=0, r1=0, r2=0, r3=0, r10=0, verbose=True):
    """Run `fn` once.  Returns (returned_ok, value)."""
    if not _loaded[0]:
        code = assemble(HERE / 'templates' / 'callfn.S')
        if CODE + len(code) > CODE_END:
            raise SystemExit('callfn does not fit')
        put(CODE, code, 'callfn')
        _loaded[0] = True

    for off, val in ((P_FN, fn), (P_R0, r0), (P_R1, r1), (P_R2, r2),
                     (P_R3, r3), (P_R10, r10), (P_RET, 0), (P_DONE, 0)):
        mem_set(P + off, val & 0xFFFFFFFF)

    mem_set(ECHO_SLOT, CODE)
    try:
        sh('echo', retries=0)
    finally:
        mem_set(ECHO_SLOT, ECHO_ORIG)

    st = mem_get(P + P_RET, 2)
    ret, done = (st + [None, None])[:2]
    ok = done == DONE
    if verbose:
        where = f'0x{fn:08X}'
        print(f'  call {where}  ->  ' +
              (f'0x{ret:08X} ({ret})' if ok else 'DID NOT RETURN'))
    return ok, ret


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('fn', type=lambda s: int(s, 0))
    for r in ('r0', 'r1', 'r2', 'r3', 'r10'):
        ap.add_argument(f'--{r}', type=lambda s: int(s, 0), default=0)
    a = ap.parse_args()
    ok, _ = call(a.fn, a.r0, a.r1, a.r2, a.r3, a.r10)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
