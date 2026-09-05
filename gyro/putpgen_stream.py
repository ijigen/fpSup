#!/usr/bin/env python3
"""Hot-swap the pool's profile generator for a freshly built one.

putprofile.py predates the lifecycle rework: it assembles profilegen.S with no
defines and points S_JSON_FN at pg_build.  The card's own loader places the
whole PGEN.BIN -- header, profile half, gcsv half -- and points S_JSON_FN and
S_GCSV_FN at the two entries the header carries.  This does the same thing, so
what runs after it is what a burnt card would run.

The pointers go to zero first.  The logger's idle poll calls through them every
few milliseconds, and writing fifty kilobytes underneath a live pointer is what
killed the camera four times over.
"""
import argparse
import sys
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'fp_usb_shell'))

import putfile as P                                            # noqa: E402
import build_pgen                                              # noqa: E402

POOL_PTR, O_STATE = 0xC3757A7C, 0x6000
PG_CODE, PG_MAX, PG_TEXT = 0x71000, 0x10000, 0xF8800
S_JSON_FN, S_GCSV_FN = 0xF0, 0xF8
F_CACHE = 0xC000E91C


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


def setw(addr, v, what):
    v &= 0xFFFFFFFF
    for _ in range(10):
        P.mem_set(addr, v)
        if (P.mem_get(addr) or [None])[0] == v:
            return
    raise SystemExit(f'could not write {what} at {addr:#x}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plain', action='store_true',
                    help='build without GCSV-only streaming')
    ap.add_argument('--gcsv-2500', action='store_true',
                    help='measuring build: every native sample on its own row')
    a = ap.parse_args()

    if P.sh('version', retries=3).startswith('ERR'):
        raise SystemExit('the camera is not answering')
    pool = (P.mem_get(POOL_PTR) or [0])[0]
    if not pool:
        raise SystemExit('the pool pointer reads zero; the AutoRun has not run')
    r10 = pool + O_STATE
    base = r10 + PG_CODE

    blob = build_pgen.build(native_lifecycle=True, gcsv_stream=not a.plain,
                            gcsv_2500=a.gcsv_2500)[0]
    if a.gcsv_2500:
        print('  2500 Hz measuring build -- reboot to get the shipping one back')
    magic, prof_off, gcsv_off, length = struct.unpack_from('<4sIII', blob, 0)
    if magic != b'PGEN':
        raise SystemExit('the build did not produce a PGEN blob')
    if len(blob) > PG_MAX or PG_CODE + len(blob) > PG_TEXT:
        raise SystemExit(f'{len(blob)} bytes does not fit the pool window')

    was_json = (P.mem_get(r10 + S_JSON_FN) or [0])[0]
    was_gcsv = (P.mem_get(r10 + S_GCSV_FN) or [0])[0]
    print(f'pool {pool:#x}  code {base:#x}  {len(blob)} bytes')
    print(f'resident: json {was_json:#x}  gcsv {was_gcsv:#x}')

    setw(r10 + S_JSON_FN, 0, 'S_JSON_FN')
    setw(r10 + S_GCSV_FN, 0, 'S_GCSV_FN')
    print('pointers cleared -- the logger will not call in while we write')
    try:
        P.put(base, blob, 'pgen  ')
        echo_into(F_CACHE, 'the cache maintenance routine')
    except BaseException:
        print('WRITE FAILED -- the pointers are left at zero, which is safe; '
              'the camera writes no profile until this is run again')
        raise
    setw(r10 + S_JSON_FN, base + 16 + prof_off, 'S_JSON_FN')
    setw(r10 + S_GCSV_FN, base + 16 + gcsv_off, 'S_GCSV_FN')
    print(f'now:      json {base + 16 + prof_off:#x}  gcsv {base + 16 + gcsv_off:#x}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
