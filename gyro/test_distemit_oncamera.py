#!/usr/bin/env python3
"""Call pg_dist_prepare and pg_dist_emit on the camera and read the text back.

The last stretch the unit tests cannot reach: formatting a double as JSON.
Loads the real generator, points it at a scratch state block so nothing the
card is using is touched, and prints what would land inside distortion_coeffs.
"""
import sys, struct, math
sys.path.insert(0, '../fp_usb_shell')
from armasm import assemble, symbols
import putfile as P

POOL_PTR, O_STATE, F_CACHE, S_JSON_FN = 0xC3757A7C, 0x6000, 0xC000E91C, 0xF0
PARM = 0xC072F740
# pg_build gets this from pg_dist_focal; this probe calls pg_dist_prepare
# directly, so hand it the same measured value the block holds.
W, H, FOCAL_MM = 1936, 1090, 39.4


def echo_into(addr, label):
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
    defs = ('FPGYRO_NATIVE_LIFECYCLE', 'FPGYRO_GCSV_STREAM')
    gen = assemble('profilegen.S', defs)
    gsym = symbols('profilegen.S', defs)
    trampoline = assemble('distemit_probe.S')
    tsym = symbols('distemit_probe.S')

    pool = (P.mem_get(POOL_PTR) or [0])[0]
    if not pool:
        raise SystemExit('the pool pointer reads zero')
    r10_real = pool + O_STATE
    gen_at = pool + O_STATE + 0x7A000          # not 0x71000: the card's own
    tramp_at = pool + O_STATE + 0x7D000        # generator is resident there
    text = pool + O_STATE + 0x7E000            # PG_TEXT for our fake r10
    r10 = text - gsym_pg_text(gsym)            # so PG_TEXT lands on `text`

    resident = (P.mem_get(r10_real + S_JSON_FN) or [0])[0]
    lo, hi = gen_at, tramp_at + len(trampoline)
    if resident and lo <= resident < hi:
        raise SystemExit(f'the resident generator entry {resident:#x} is inside '
                         f'{lo:#x}..{hi:#x}')
    print(f'resident generator entry {resident:#x} -- clear of us')
    print(f'generator {len(gen)} B at {gen_at:#x}, text at {text:#x}')

    P.put(gen_at, gen, 'pgen  ')
    P.put(tramp_at, trampoline, 'tramp ')
    echo_into(F_CACHE, 'the cache maintenance routine')

    focal_milli = round(W * FOCAL_MM / 35.9 * 1000)
    setw(0, W); setw(4, H); setw(8, focal_milli)
    setw(12, text); setw(16, r10)
    setw(20, gen_at + gsym['pg_dist_prepare'])
    setw(28, gen_at + gsym['pg_dist_emit'])
    setw(24, 0); setw(32, 0); setw(36, 0)

    echo_into(tramp_at + tsym['_start'], 'the emitter')

    if (P.mem_get(PARM + 36) or [0])[0] != 0xD09E0000:
        raise SystemExit('the probe did not complete')
    focal_after = (P.mem_get(PARM + 24) or [0])[0]
    end = (P.mem_get(PARM + 32) or [0])[0]
    n = end - text
    print(f'\nfocal_px x1000: {focal_milli} -> {focal_after} '
          f'(breathing x{focal_after / focal_milli:.6f})')
    if not 0 < n < 512:
        raise SystemExit(f'the text is {n} bytes, which is not credible')
    words = []
    for off in range(0, (n + 63) // 64 * 64, 64):
        w = P.mem_get(text + off, 16)
        if not w:
            raise SystemExit('could not read the text back')
        words += w
    raw = struct.pack(f'<{len(words)}I', *words)[:n]
    print(f'text ({n} bytes): {raw.decode("ascii", "replace")}')


def gsym_pg_text(gsym):
    # PG_TEXT is an .equ, not a symbol; read it out of the source.
    import re, pathlib
    for line in pathlib.Path('profilegen.S').read_text().splitlines():
        m = re.match(r'\s*\.equ\s+PG_TEXT\s*,\s*(0x[0-9A-Fa-f]+)', line)
        if m:
            return int(m.group(1), 0)
    raise SystemExit('PG_TEXT not found')


if __name__ == '__main__':
    main()
