#!/usr/bin/env python3
"""Read the lens distortion support points out of the camera.

    ./gyro/lens_dist.py                 -> 17 raw values, ready for lens_profile.py

The firmware carries only the interpolation engine; the coefficients live in the
lens and are downloaded at boot. What lands in RAM is a 17-point radial table in
Q15, already interpolated for the current focus distance and focal length, so it
has to be read with the lens mounted and roughly where it was shot.

Two tables sit next to each other -- the pair the correction uses. One reads as
all 32768, which is Q15 for 1.0: the identity, i.e. no correction. The other
carries the lens. This prints whichever is not the identity.
"""
import struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'fp_usb_shell'))
from putfile import read_bulk, sh                                    # noqa: E402

TABLES = 0xC2F2D876          # the pair, as DistConverter reaches them
SPAN = 0x60


def main():
    if sh('version').startswith('ERR'):
        raise SystemExit('the camera is not answering')
    raw = read_bulk(TABLES, SPAN, 'lens  ')
    words = struct.unpack(f'<{SPAN // 2}H', raw)
    best, best_dev = None, 0.0
    for start in range(0, len(words) - 17):
        t = words[start:start + 17]
        if t[0] == 0 or any(v == 0 for v in t[1:]):
            continue
        s = [t[k] * k / 16 / 32768 for k in range(17)]
        if any(s[k] > s[k + 1] + 1e-9 for k in range(16)):
            continue
        dev = max(abs(s[k] - k / 16) for k in range(17))
        # A real table stays within a few percent of the identity. Without this
        # the search happily picks a window that has run off the end of the
        # table into whatever follows, and reports 90% distortion.
        if dev > 0.05:
            continue
        if dev > best_dev:
            best, best_dev = t, dev
    if best is None or best_dev < 1e-6:
        raise SystemExit(
            'only the identity table is loaded -- either no lens is mounted, or '
            'the camera has no correction data for it')
    print(f'# max deviation {best_dev * 100:.3f}% of the corner radius')
    print(','.join(str(v) for v in best))
    return 0


if __name__ == '__main__':
    sys.exit(main())
