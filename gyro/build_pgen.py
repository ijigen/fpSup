#!/usr/bin/env python3
"""Wrap the profile generator as \\PGEN.BIN for the camera to load at boot.

    ./gyro/build_pgen.py            -> writes it to the card over USB

    "PGEN" | u32 post-process entry | u32 gcsv entry | u32 length | the code

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


def build(native_lifecycle=False, recovery=False, gcsv_stream=False,
          backpressure_probe=False):
    """Both pool routines in one file, with the entry points in the header.

        "PGEN" | u32 post-process entry | u32 gcsv entry | u32 length | the code

    They are laid end to end and neither calls the other, so concatenating two
    position-independent blobs is all it takes. The loader never has to know
    anything about either of them.
    """
    if recovery and not native_lifecycle:
        raise ValueError('recovery requires native_lifecycle')
    if recovery and gcsv_stream:
        raise ValueError('GCSV-only streaming has no GYR recovery source')
    if backpressure_probe and not gcsv_stream:
        raise ValueError('backpressure probe requires GCSV-only streaming')
    defines = []
    if native_lifecycle:
        defines.append('FPGYRO_NATIVE_LIFECYCLE')
    if recovery:
        defines.append('FPGYRO_RECOVERY')
    if gcsv_stream:
        defines.append('FPGYRO_GCSV_STREAM')
    if backpressure_probe:
        defines.append('FPGYRO_BACKPRESSURE_PROBE')
    defines = tuple(defines)
    prof = assemble(HERE / 'profilegen.S', defines)
    prof += b'\0' * (-len(prof) % 4)
    gcsv = assemble(HERE / 'gcsvgen.S', defines)
    # The first entry owns the post-process queue and calls pg_build itself.
    # Keeping the scheduler in PGEN leaves the fixed injection cave to the
    # recording and close path, where every instruction has to fit below the
    # shell's state/parking stub.
    a = symbols(HERE / 'profilegen.S', defines)['pg_post_process']
    b = len(prof) + symbols(HERE / 'gcsvgen.S', defines)['gcsv_build']
    code = prof + gcsv
    return struct.pack('<4sIII', b'PGEN', a, b, len(code)) + code, (a, b), len(code)


if __name__ == '__main__':
    native = '--native-lifecycle' in sys.argv
    recovery = '--recovery' in sys.argv
    gcsv_stream = '--gcsv-stream' in sys.argv
    backpressure_probe = '--backpressure-probe' in sys.argv
    blob, (a, b), n = build(native_lifecycle=native, recovery=recovery,
                             gcsv_stream=gcsv_stream,
                             backpressure_probe=backpressure_probe)
    local = HERE / '.pgen.bin'
    local.write_bytes(blob)
    print(f'  pool code     {n} bytes: post +0x{a:X}, gcsv +0x{b:X}, '
          f'{len(blob)} on the card' + (' [native lifecycle]' if native else '')
          + (' [GCSV-only stream]' if gcsv_stream else '')
          + (' [backpressure probe]' if backpressure_probe else '')
          + (' [recovery]' if recovery else ' [no recovery]' if native else ''))
    if '--local' not in sys.argv:
        r = subprocess.run([sys.executable, str(SHELL / 'putfile.py'),
                            str(local), r'\PGEN.BIN'], capture_output=True, text=True)
        sys.stdout.write('\n'.join(l for l in (r.stdout + r.stderr).splitlines()
                                   if 'written' in l or 'dir' in l or 'ERR' in l))
        print()
