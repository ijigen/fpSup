#!/usr/bin/env python3
"""Put the profile generator in the pool and point the logger at it.

    ./gyro/putprofile.py

Run after load.sh -- which does it for you.

The generator is gyro/profilegen.S.  It reads the lens off the mount, looks the
sensor mode up in the firmware's own timing and geometry tables, works out the
rolling shutter and the focal length, formats the text and writes the file.
Nothing about the profile is computed here: this only carries the code across
and tells the logger where it landed.

It lives in the pool because the injection cave is under four kilobytes and
full.  Code runs from the pool once the data cache has been cleaned.
"""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHELL = HERE.parent / 'fp_usb_shell'
sys.path.insert(0, str(SHELL))

from armasm import assemble, symbols                           # noqa: E402
import putfile as P                                            # noqa: E402
import callfn                                                  # noqa: E402

POOL_PTR = 0xC3757A7C
O_STATE = 0x6000
F_CACHE = 0xC000E91C            # CP15 maintenance; without it the CPU can fetch
                                # instructions the write has not reached yet


def equs(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r'\s*\.equ\s+(\w+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)', line)
        if m:
            out[m.group(1)] = int(m.group(2), 0)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()

    gen, log = equs(HERE / 'profilegen.S'), equs(HERE / 'logger.S')
    code = assemble(HERE / 'profilegen.S')
    sym = symbols(HERE / 'profilegen.S')

    # Keep code in the audited unused middle of the one-megabyte pool.  O_READ
    # ends at r10+0x6B000; this leaves a 24 KiB guard before the code and ample
    # space before PG_TEXT near the top of the pool.
    PG_CODE = 0x71000
    PG_MAX = 0x10000
    if len(code) > PG_MAX:
        raise SystemExit(f'the generator is {len(code)} bytes; limit is '
                         f'{PG_MAX} bytes')
    if PG_CODE + len(code) > gen['PG_TEXT']:
        raise SystemExit(f'the generator is {len(code)} bytes and would run into '
                         f'its own text buffer at {gen["PG_TEXT"]:#x}')
    if gen['PG_LENS'] + 0x100 > 0xFA000:
        raise SystemExit('the lens scratch runs past the end of the pool')

    if P.sh('version', retries=3).startswith('ERR'):
        raise SystemExit('the camera is not answering')
    pool = P.mem_get(POOL_PTR)
    if not pool or not pool[0]:
        raise SystemExit('the pool pointer reads zero; the AutoRun has not run')
    r10 = pool[0] + O_STATE
    base = r10 + PG_CODE
    entry = base + sym['pg_build']

    # Clear the pointer first. If the write below fails, the logger finds zero
    # and writes no profile, rather than branching into half-placed code.
    P.mem_set(r10 + log['S_JSON_FN'], 0)
    P.put(base, code, 'pgen  ')
    callfn.call(F_CACHE, verbose=False)
    for _ in range(10):
        P.mem_set(r10 + log['S_JSON_FN'], entry)
        if (P.mem_get(r10 + log['S_JSON_FN']) or [0])[0] == entry:
            break
    else:
        raise SystemExit('could not write the generator address')
    if not a.quiet:
        print(f'  generator     {len(code)} bytes at 0x{base:08X}, '
              f'entry 0x{entry:08X}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
