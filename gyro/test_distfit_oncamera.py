#!/usr/bin/env python3
"""Read the lens's distortion table and fit it, on the camera.

What killed the camera four times was not the transfer size, callfn, or the
daemon -- all three were wrong guesses.  It was the address: putprofile puts
the generator at pool+0x77000, the card boots with it already resident there,
and writing over it lands half-finished while the logger's idle poll calls
straight in.  This runs at pool+0x80000 and refuses to start if the logger's
generator pointer falls anywhere inside what it is about to write.

No callfn either: the cache maintenance routine takes no arguments, so the
echo handler can point straight at it, and the results fit in `mem get`.
"""
import sys, struct, math, time
sys.path.insert(0, '../fp_usb_shell')
from armasm import assemble, symbols
import putfile as P

POOL_PTR, O_STATE, F_CACHE = 0xC3757A7C, 0x6000, 0xC000E91C
PARM = 0xC072F740
W, H, FOCAL_MM = 1936, 1090, 40.0


def echo_into(addr, label):
    """Run the routine at addr once, by lending it the echo command."""
    orig = P.mem_get(P.ECHO_SLOT)
    if not orig or orig[0] != P.ECHO_ORIG:
        raise SystemExit(f'echo handler is {orig}, not free to borrow')
    for _ in range(8):
        P.mem_set(P.ECHO_SLOT, addr)
        if (P.mem_get(P.ECHO_SLOT) or [0])[0] == addr:
            break
    else:
        raise SystemExit(f'could not point the echo handler at {label}')
    try:
        P.sh('echo', retries=0)
    finally:
        for _ in range(8):
            P.mem_set(P.ECHO_SLOT, P.ECHO_ORIG)
            if (P.mem_get(P.ECHO_SLOT) or [0])[0] == P.ECHO_ORIG:
                return
        raise SystemExit('LEFT THE ECHO HANDLER REDIRECTED -- reboot the camera')


def setw(off, v):
    v &= 0xFFFFFFFF
    for _ in range(8):
        P.mem_set(PARM + off, v)
        if (P.mem_get(PARM + off) or [None])[0] == v:
            return
    raise SystemExit(f'could not write PARM+{off}')


def main():
    if P.sh('version', retries=3).startswith('ERR'):
        raise SystemExit('the camera is not answering')
    code = assemble('distfit_probe.S')
    sym = symbols('distfit_probe.S')
    pool = (P.mem_get(POOL_PTR) or [0])[0]
    if not pool:
        raise SystemExit('the pool pointer reads zero')
    # NOT 0x71000: that is where the card's own PGEN is already resident, and
    # overwriting it while the logger's idle poll calls into it kills the
    # camera mid-transfer.  0x7A000 upward is clear and was proven harmless.
    r10 = pool + O_STATE
    base = pool + O_STATE + 0x7A000
    scratch = pool + O_STATE + 0x7C000
    print(f'probe {len(code)} B at {base:#x}, scratch {scratch:#x}')

    # The card boots with its own PGEN resident in this pool and the logger
    # holding a pointer into it.  Writing over that is what killed the camera
    # four times: the transfer lands half-finished and the idle poll calls
    # straight into it.  Refuse rather than find out again.
    resident = (P.mem_get(r10 + 0xf0) or [0])[0]
    if resident and base <= resident < scratch + 4096:
        raise SystemExit(f'the resident generator entry is {resident:#x}, '
                         f'inside the {base:#x}..{scratch + 4096:#x} we would write')
    print(f'resident generator entry {resident:#x} -- clear of us')

    P.put(base, code, 'probe ')
    echo_into(F_CACHE, 'the cache maintenance routine')

    focal_px = W * FOCAL_MM / 35.9
    s = math.hypot(W / 2, H / 2) / focal_px
    setw(16, scratch)
    setw(20, scratch + 32)
    setw(24, 0); setw(28, 0); setw(40, 0)
    setw(44, 400); setw(48, 0)          # what the mount reports, in tenths
    lo, hi = struct.unpack('<II', struct.pack('<d', s))
    setw(32, lo); setw(36, hi)

    echo_into(base + sym['_start'], 'the probe')

    if (P.mem_get(PARM + 40) or [0])[0] != 0xD09E0000:
        raise SystemExit('the probe did not complete')
    measured = (P.mem_get(PARM + 48) or [0])[0]
    print(f'pg_dist_focal: mount says 40.0 mm, camera uses {measured / 10:.1f} mm')
    print('pg_dist_kr  returned', (P.mem_get(PARM + 24) or ['?'])[0])
    print('pg_dist_fit returned', (P.mem_get(PARM + 28) or ['?'])[0])

    words = []
    for off in range(0, 152, 64):
        w = P.mem_get(scratch + off, 16)
        if not w:
            raise SystemExit('could not read the result back')
        words += w
    raw = struct.pack(f'<{len(words)}I', *words)
    kr = struct.unpack_from('<4d', raw, 0)
    fit = struct.unpack_from('<3d', raw, 32)
    mat = struct.unpack_from('<9d', raw, 56)
    rhs = struct.unpack_from('<3d', raw, 56 + 72)
    print('\nkr  from the camera:', ', '.join(f'{x:+.9f}' for x in kr))
    print('fit from the camera:', ', '.join(f'{x:+.9f}' for x in fit))
    print('matrix rows:')
    for r in range(3):
        print('   ' + ', '.join(f'{mat[3*r+c]:+.12e}' for c in range(3)))
    print('rhs:  ' + ', '.join(f'{x:+.12e}' for x in rhs))

    # Compare against the same arithmetic done here.  The assembly's own bugs
    # have all been in addressing and register setup, which no unit test on the
    # host can see; this is the only place the two can disagree.
    sys.path.insert(0, '.')
    from test_distfit import asm_fit
    want = asm_fit(kr, s)
    print('\nexpected   :', ', '.join(f'{x:+.9f}' for x in want))
    worst = max(abs(a - b) for a, b in zip(fit, want))
    print(f'worst difference {worst:.3e}',
          '-- MATCH' if worst < 1e-9 else '-- MISMATCH')
    return kr, fit, mat, rhs


if __name__ == '__main__':
    main()
