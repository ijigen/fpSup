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
import json
import struct
import subprocess
import sys
from pathlib import Path

# The rates the camera will record at. Without this the table is every mode the
# sensor has, which is seventy, and the whole point is that it fits in the pool
# beside the logger so the camera never has to be told which mode to expect.
MOVIE_FPS = (23.976, 24, 25, 29.97, 30, 50, 59.94, 60, 100, 119.88, 120)

HERE = Path(__file__).resolve().parent
SHELL = HERE.parent / 'fp_usb_shell'
sys.path.insert(0, str(SHELL))

from armasm import assemble                                    # noqa: E402
import putfile as P                                            # noqa: E402
from lens_profile import load_modes, build_profile           # noqa: E402

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

    if not mov_w:
        raise SystemExit('  the movie size did not read back; without it the '
                         'profiles would carry the wrong frame dimensions')
    # CinemaDNG frames come out sixteen wider and ten taller than the menu says.
    frame_w, frame_h = mov_w + 16, mov_h + 10

    # Finished profiles, not the numbers to build them from.
    #
    # Version 2 stored focal_px and the readout and left the camera to assemble
    # the JSON. That means formatting decimals in ARM, for a file whose text is
    # the same on every take with the same lens and mode -- nothing in a profile
    # is clip-specific. Storing the text instead moves every format decision
    # back to the host, where it can be changed without reloading the logger,
    # and leaves the camera a lookup and a copy.
    #
    # One blob per mode in the table rather than the few that look plausible:
    # a hundred kilobytes costs nothing on a card, and a mode missing from the
    # file is a take with no profile.
    profiles, blobs, offsets = [], [], []
    for m in sorted(load_modes(), key=lambda x: int(x['mode_id'])):
        if frame_w > m['readout_w'] or frame_h > m['readout_h']:
            continue            # that mode cannot have produced this frame
        if not any(abs(m['fps'] - f) < 0.2 for f in MOVIE_FPS):
            continue            # nor can it, at a rate the camera cannot record
        prof = build_profile(m, name, frame_w, frame_h, m['fps'], focal_tenths / 10)
        blobs.append((json.dumps(prof, indent=2, ensure_ascii=False) + '\n').encode())
        profiles.append(int(m['mode_id']))

    HEADER = 48
    body = HEADER + 12 * len(blobs)
    directory = b''
    for mode_id, blob_bytes in zip(profiles, blobs):
        directory += struct.pack('<III', mode_id, body, len(blob_bytes))
        body += len(blob_bytes)

    blob = struct.pack('<4sHHHHH32s2x', b'LDAT', 3, len(blobs), focal_tenths,
                       mov_w, mov_h, name.encode('ascii', 'replace')[:32])
    assert len(blob) == HEADER, len(blob)
    blob += directory + b''.join(blobs)
    # Padded to a fixed length, because opening with mode 7 does not truncate:
    # a shorter table written over a longer one leaves the old tail behind, and
    # the card then reports a size that is not the table's. The pad is zeros,
    # which the directory never points into.
    PADDED = 0x10000
    if len(blob) > PADDED:
        raise SystemExit(f'  the table is {len(blob)} bytes, past the {PADDED} '
                         f'the pool has room for; narrow the mode list')
    print(f'  profiles      {len(blobs)} modes for {frame_w}x{frame_h}, '
          f'{len(blob)} bytes in {PADDED}')
    blob += b'\0' * (PADDED - len(blob))
    if not blobs:
        raise SystemExit('  no mode in the table can produce that frame size')

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
