#!/usr/bin/env python3
"""Read the lens's distortion table off the camera and fit Gyroflow's coefficients.

    ./gyro/lens_dist_table.py                 -> the profile numbers for the mounted lens

This replaces lens_dist.py's 17-point Q15 scrape. The firmware keeps the real
thing: a table of five focus support points, each with four f64 radial
coefficients per colour plane -- the same numbers it writes into a DNG's
WarpRectilinear opcode. Interpolating it linearly reproduces a DNG's opcode to
nine decimal places, so nothing here is fitted to a picture.

Two things the DNG model carries that Gyroflow's does not:

  kr0 is not 1.  It is the lens's focus breathing -- the magnification change
  between infinity and the near limit, 1.2% on the 40 mm.  That is a focal
  length, not a distortion, so it multiplies camera_matrix and is divided out
  before the shape is fitted.  Leaving it in the fit costs a factor of forty in
  residual (1.43 px against 0.036) because the theta model's leading term is
  pinned at 1 and k1/k2 have to absorb the scale.

  The support axis is 2^24 / focus distance in mm, not the focus position the
  lens reports.  `lens getfpos` spans 5977..11116; the axis spans 0..55924.
  They have to be bridged through the distance in millimetres.
"""
import math, struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'fp_usb_shell'))
from putfile import read_bulk, sh                                    # noqa: E402
from lens_profile import fit_distortion                              # noqa: E402

AXIS = 0xC307CE2C          # 5 x u32, 2^24 / mm
TABLE = 0xC307D270         # 5 nodes x 3 planes x 4 doubles
FOCAL = 0xC307CDF0         # u32, tenths of a mm
PLANE_GREEN = 1
TERMS = 3
INF = 0x7FFFFFF


def read_table():
    axis = struct.unpack('<5I', read_bulk(AXIS, 20, 'axis  '))
    raw = read_bulk(TABLE, 480, 'coeffs')
    nodes = [[struct.unpack_from('<4d', raw, 32 * (3 * n + p)) for p in range(3)]
             for n in range(5)]
    return axis, nodes


def focus_axis():
    """Where the lens is now, on the table's axis."""
    pos = int(sh('lens getfpos').split()[-1])
    dist = int(sh(f'lens cnvfdist {pos}').split()[-1])
    return (0.0 if dist >= INF else 16777216.0 / dist), pos, dist


def interpolate(axis, nodes, a, plane=PLANE_GREEN):
    i = 0
    for j in range(4):
        if a >= axis[j]:
            i = j
    t = (a - axis[i]) / (axis[i + 1] - axis[i])
    t = min(max(t, 0.0), 1.0)
    lo, hi = nodes[i][plane], nodes[i + 1][plane]
    return [lo[k] + t * (hi[k] - lo[k]) for k in range(4)], i, t


def coefficients(kr, w, h, focal_px, terms=TERMS):
    """Gyroflow's distortion_coeffs, and the focal length that goes with them.

    kr0 rides on the focal length; the fit sees only the shape.
    """
    k0 = kr[0]

    def g(rho):
        r2 = rho * rho
        return (kr[0] + kr[1] * r2 + kr[2] * r2 * r2 + kr[3] * r2 ** 3) / k0

    table = [round(g(k / 16) * 32768) for k in range(17)]
    coeffs, rms, mx, limit = fit_distortion(table, w, h, focal_px, terms)
    return coeffs, focal_px * k0, rms, mx, limit


def main():
    if sh('version').startswith('ERR'):
        raise SystemExit('the camera is not answering')
    axis, nodes = read_table()
    if not any(any(c[1:]) for n in nodes for c in n):
        raise SystemExit('the mounted lens has no distortion data')
    focal_mm = struct.unpack('<I', read_bulk(FOCAL, 4, 'focal '))[0] / 10.0
    a, pos, dist = focus_axis()
    kr, i, t = interpolate(axis, nodes, a)

    w, h = 1936, 1090
    focal_px = w * focal_mm / 35.9
    coeffs, focal_out, rms, mx, limit = coefficients(kr, w, h, focal_px)

    print(f'# lens {focal_mm:.1f} mm, focus pos {pos} = {dist} mm, axis {a:.0f}')
    print(f'# support points ' + ', '.join(
        'inf' if v == 0 else f'{16777216 / v:.0f}mm' for v in axis))
    print(f'# node {i}->{i + 1}, t={t:.6f}')
    print(f'# kr = ' + ', '.join(f'{x:+.9f}' for x in kr))
    print(f'# breathing: focal x{kr[0]:.6f}  ->  {focal_out:.1f} px')
    print(f'# fit {TERMS} terms: RMS {rms:.3f} px, max {mx:.3f} px, limit {limit:.2f}')
    print('distortion_coeffs = [' + ', '.join(f'{x:.9f}' for x in coeffs) + ']')
    print(f'focal_px = {focal_out:.4f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
