#!/usr/bin/env python3
"""Read the mounted lens, and leave the camera everything it needs on the card.

    ./gyro/lensdat.py                 -> \\LENS.DAT

Run it once after loading the logger, and again after changing lenses. Then the
camera can write a Gyroflow profile for every take without a host, because the
one slow part is already done.

Reading a block off the L-mount bus takes about seven hundred milliseconds --
the firmware's accessor holds a mutex the camera wants back for its own periodic
polling -- which is fine here, with nothing recording, and is why this is not
done at the moment a take starts or stops.

What lands on the card:

    "LDAT" 2 <focal_tenths> <name[32]> <movie_w> <movie_h> <mode count>
    then per mode:  <mode_id> <focal_px x 1000> <readout_us>

The movie size is what the menu is set to when this runs, recorded so a profile
built from stale data can be spotted rather than believed. The camera answers
`setting get cam_movie_imagesize.h` once `setting readcam` has loaded the store
-- before that it says 0, which looks like an answer.

The per-mode numbers are worked out here, from the firmware's own IMX410 tables,
so the camera has nothing to compute but the lookup. Only primes are supported:
a zoom's focal length changes while shooting, and Gyroflow has no way to follow
it either.
"""
import argparse
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHELL = HERE.parent / 'fp_usb_shell'
sys.path.insert(0, str(SHELL))

from armasm import assemble                                    # noqa: E402
import putfile as P                                            # noqa: E402
from lens_profile import load_modes                            # noqa: E402

BLOCK_FOCAL, BLOCK_NAME = 0x0D, 0x2D
SENSOR_ACTIVE_W, SENSOR_ACTIVE_MM = 6000, 35.9


def read_block(bid, dst):
    P.mem_set(P.ECHO_SLOT, P.CODE)
    P.mem_set(P.P + 0x00, bid)
    P.mem_set(P.P + 0x04, dst)
    P.sh('echo', retries=2)
    ok = P.mem_get(P.P + 0x08)
    ln = P.mem_get(P.P + 0x0C)
    P.mem_set(P.ECHO_SLOT, P.ECHO_ORIG)
    if not ok or not ok[0] or not ln or not ln[0]:
        raise SystemExit(f'  block 0x{bid:02X} did not read')
    return P.read_bulk(dst, ln[0], '')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', help=r'card path (default \LENS.DAT)',
                    default=r'\LENS.DAT')
    ap.add_argument('--local', type=Path, help='also keep a copy here')
    a = ap.parse_args()

    if P.sh('version', retries=3).startswith('ERR'):
        raise SystemExit('the camera is not answering')

    P.put(P.CODE, assemble(SHELL / 'templates' / 'lensblock.S'), 'lens  ')
    dst = P.staging_area()
    orig = P.mem_get(P.ECHO_SLOT)
    if not orig or orig[0] not in (P.ECHO_ORIG, P.CODE):
        raise SystemExit(f'echo handler is {orig}, not free to borrow')
    try:
        # Big-endian. The L-mount protocol is, and reading 0x0190 the other way
        # round gives a 3686.5 mm lens -- which is wrong in a way that looks like
        # data rather than like an error.
        focal_tenths = struct.unpack('>H', read_block(BLOCK_FOCAL, dst))[0]
        name = read_block(BLOCK_NAME, dst).split(b'\0')[0].decode('ascii', 'replace').strip()
    finally:
        for _ in range(10):
            P.mem_set(P.ECHO_SLOT, P.ECHO_ORIG)
            if (P.mem_get(P.ECHO_SLOT) or [0])[0] == P.ECHO_ORIG:
                break
        else:
            print('  WARNING echo handler still borrowed')

    # The recording format, so the file says what it was built against. Only
    # readable after `setting readcam`: the parameter store is empty until then
    # and reports zero, which is indistinguishable from a real answer.
    P.sh('setting readcam', retries=3)
    def setting(name):
        r = P.sh(f'setting get {name}', retries=3)
        tail = r.strip().split('->')[-1].strip()
        return int(tail) if tail.isdigit() else 0
    mov_w, mov_h = setting('cam_movie_imagesize.h'), setting('cam_movie_imagesize.v')

    if not 10 <= focal_tenths <= 20000:
        raise SystemExit(f'  focal length reads {focal_tenths} tenths of a mm; '
                         'that is not a lens')
    print(f'  lens          {name}')
    print(f'  focal         {focal_tenths / 10} mm')
    if mov_w:
        # The frames come out sixteen wider and ten taller than the menu says --
        # CinemaDNG's margin. 1920x1080 -> 1936x1090, 3840x2160 -> 3856x2170.
        print(f'  movie size    {mov_w} x {mov_h}  (frames are {mov_w + 16} x {mov_h + 10})')
    else:
        print('  movie size    unknown; the profile cannot be checked against it')

    rows = []
    for m in load_modes():
        cw = min(m['covered_w'], SENSOR_ACTIVE_W)
        covered_mm = SENSOR_ACTIVE_MM * cw / SENSOR_ACTIVE_W
        # focal_px is per output width, and the output width is not in the mode
        # table -- it is whatever the clip is. Store the ratio instead, scaled:
        # focal_px = out_w * (focal_mm / covered_mm), so keep focal_mm/covered_mm
        # x 1e6 and let the camera multiply by its own width.
        ratio = (focal_tenths / 10) / covered_mm
        rows.append((int(m['mode_id']), round(ratio * 1e6),
                     round(m['readout_ms'] * 1000)))
    rows.sort()

    blob = struct.pack('<4sHH32sHHH', b'LDAT', 2, focal_tenths,
                       name.encode('ascii', 'replace')[:32], mov_w, mov_h, len(rows))
    blob += b''.join(struct.pack('<III', *r) for r in rows)
    print(f'  modes         {len(rows)} rows, {len(blob)} bytes')

    tmp = Path(a.local) if a.local else HERE / '.lens.dat'
    tmp.write_bytes(blob)
    r = subprocess.run([sys.executable, str(SHELL / 'putfile.py'),
                        str(tmp), a.out], capture_output=True, text=True)
    if 'written' not in r.stdout:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f'  could not write {a.out}')
    print(f'  wrote         {a.out}')
    if not a.local:
        tmp.unlink()
    return 0


if __name__ == '__main__':
    sys.exit(main())
