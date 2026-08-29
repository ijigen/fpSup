#!/usr/bin/env python3
"""Wrap the profile generator as \\PGEN.BIN for the camera to load at boot.

    ./gyro/build_pgen.py            -> writes it to the card over USB

    "PGEN" | u32 entry offset | u32 length | the code

The generator lives in the pool, whose address is only known at run time, so it
cannot be a section of VSHL.BIN like the logger is.  It goes on the card as a
file instead and pgenload.S reads it in at boot -- the same shape the lens table
already uses.  The header carries the entry offset so the loader never has to
know anything about the code it is placing.
"""
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHELL = HERE.parent / 'fp_usb_shell'
sys.path.insert(0, str(SHELL))

from armasm import assemble, symbols                           # noqa: E402


def build():
    """Both pool routines in one file, with the entry points in the header.

        "PGEN" | u32 profile entry | u32 gcsv entry | u32 length | the code

    They are laid end to end and neither calls the other, so concatenating two
    position-independent blobs is all it takes. The loader never has to know
    anything about either of them.
    """
    prof = assemble(HERE / 'profilegen.S')
    prof += b'\0' * (-len(prof) % 4)
    gcsv = assemble(HERE / 'gcsvgen.S')
    a = symbols(HERE / 'profilegen.S')['pg_build']
    b = len(prof) + symbols(HERE / 'gcsvgen.S')['gcsv_build']
    code = prof + gcsv
    return struct.pack('<4sIII', b'PGEN', a, b, len(code)) + code, (a, b), len(code)


if __name__ == '__main__':
    blob, (a, b), n = build()
    local = HERE / '.pgen.bin'
    local.write_bytes(blob)
    print(f'  pool code     {n} bytes: profile +0x{a:X}, gcsv +0x{b:X}, '
          f'{len(blob)} on the card')
    if '--local' not in sys.argv:
        r = subprocess.run([sys.executable, str(SHELL / 'putfile.py'),
                            str(local), r'\PGEN.BIN'], capture_output=True, text=True)
        sys.stdout.write('\n'.join(l for l in (r.stdout + r.stderr).splitlines()
                                   if 'written' in l or 'dir' in l or 'ERR' in l))
        print()
