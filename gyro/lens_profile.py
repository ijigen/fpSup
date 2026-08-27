#!/usr/bin/env python3
"""Generate a Gyroflow lens profile for a SIGMA fp clip.

Everything except the lens focal length comes out of the firmware's own IMX410 mode
tables (extracted by analyze_imx410_modes.py), so nothing here is measured by eye:

  clip resolution + frame rate  ->  sensor mode  ->  readout geometry, binning, timing
  geometry + binning            ->  how much of the sensor is actually imaged
  that + the lens focal length  ->  focal length in pixels
  mode timing                   ->  rolling-shutter readout time

The one number that cannot come from a table is the lens focal length in mm, since it
depends on the lens (and, for a zoom, on where it is set). Read it off the camera from
L-mount block 0x0d, or pass --focal-mm.

Why binning matters: the fp's 1080p CinemaDNG reads 3032x1708, which looks like a crop
until you notice the binning factor is 2 -- 3032 x 2 = 6064 covers the full sensor
width, so the field of view is not reduced at all. Fitting the focal length from optical
flow instead gave 2451 px and looked like a 0.88 crop; the oversampling is what made a
full-width readout resemble a cropped one.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLES = HERE / "analysis_imx410"

SENSOR_ACTIVE_W = 6000          # active pixels across the frame
SENSOR_ACTIVE_MM = 35.9         # full-frame width those pixels span
SENSOR_TOTAL_W = 6064           # including the 32 px margins each side

# Geometry record fields, named from comparing modes with known behaviour.
F_READOUT_W, F_READOUT_H = "field_0x04", "field_0x08"
F_BIN_H, F_BIN_V = "field_0x44", "field_0x48"


def load_modes():
    geom = {r["mode_id"]: r for r in csv.DictReader(open(TABLES / "imx410_mode_geometry.csv"))}
    modes = []
    for t in csv.DictReader(open(TABLES / "imx410_timing.csv")):
        g = geom.get(t["mode_id"])
        if not g:
            continue
        rw, rh = int(g[F_READOUT_W] or 0), int(g[F_READOUT_H] or 0)
        bh, bv = int(g[F_BIN_H] or 1) or 1, int(g[F_BIN_V] or 1) or 1
        if not rw or not rh:
            continue
        modes.append({
            "mode_id": t["mode_id"],
            "readout_w": rw, "readout_h": rh,
            "bin_h": bh, "bin_v": bv,
            "covered_w": rw * bh, "covered_h": rh * bv,
            "fps": float(t["exact_fps"] or 0),
            "readout_ms": float(t["active_readout_ms_est"] or 0),
            "bits": t["raw_bit_depth"],
        })
    return modes


def pick_mode(modes, out_w, out_h, fps, tol_fps=0.5):
    """Match on frame rate first, then on aspect -- the output is a scaled copy of the
    readout, so their aspects agree even though the pixel counts do not."""
    want = out_w / out_h
    cands = [m for m in modes if abs(m["fps"] - fps) <= tol_fps]
    if not cands:
        raise SystemExit(f"no mode near {fps:.3f} fps (table has "
                         f"{sorted({round(m['fps'],3) for m in modes})})")
    scored = sorted(cands, key=lambda m: abs(m["readout_w"] / m["readout_h"] - want))
    best = scored[0]
    if abs(best["readout_w"] / best["readout_h"] - want) > 0.02:
        raise SystemExit(f"no mode at {fps:.3f} fps has aspect {want:.3f}; "
                         f"closest is mode {best['mode_id']} at "
                         f"{best['readout_w']/best['readout_h']:.3f}")
    # Resolution and frame rate do not pin the mode down: several share a geometry and
    # differ only in line timing, which changes the readout time but not the focal
    # length. Return every match so the caller can say so rather than silently choosing.
    same = [m for m in scored
            if abs(m["readout_w"] / m["readout_h"] - want) <= 0.02
            and (m["readout_w"], m["readout_h"]) == (best["readout_w"], best["readout_h"])]
    return best, same


def dng_info(path):
    """Size, focal length and lens name, from the frame itself.

    The focal length used to have to be typed in, or read off the camera from
    L-mount block 0x0d. It is in every frame's EXIF -- the camera writes it --
    along with the lens's own name, so neither has to be supplied or guessed.

    EXIF hangs off the main IFD through tag 0x8769, so this follows that rather
    than reading only the first directory.
    """
    d = open(path, "rb").read(262144)
    bo = "<" if d[:2] == b"II" else ">"
    out = {}

    def walk(off, seen):
        if off <= 0 or off + 2 > len(d) or off in seen:
            return
        seen.add(off)
        n = struct.unpack_from(bo + "H", d, off)[0]
        for i in range(n):
            e = off + 2 + i * 12
            if e + 12 > len(d):
                return
            tag, typ, cnt = struct.unpack_from(bo + "HHI", d, e)
            raw = struct.unpack_from(bo + "I", d, e + 8)[0]
            if tag == 0x8769:                       # ExifIFD
                walk(raw, seen)
            elif tag == 0x0100:
                out["w"] = raw
            elif tag == 0x0101:
                out["h"] = raw
            elif tag == 0x920A and typ == 5 and raw + 8 <= len(d):
                num, den = struct.unpack_from(bo + "II", d, raw)
                if den:
                    out["focal_mm"] = num / den
            elif tag == 0xA434 and typ == 2:        # LensModel
                blob = d[raw:raw + cnt] if cnt > 4 else d[e + 8:e + 8 + cnt]
                out["lens"] = blob.split(b"\0")[0].decode("ascii", "replace").strip()

    walk(struct.unpack_from(bo + "I", d, 4)[0], set())
    return out


def dng_size(path):
    info = dng_info(path)
    return info.get("w"), info.get("h")


def fit_distortion(table, w, h, focal_px, terms):
    """Fit Gyroflow's coefficients to the lens's own support points.

    The firmware stores a 17-point radial map in Q15: for a corrected radius of
    k/16 of the corner distance, the source pixel sits at S[k]. Gyroflow wants
    r_d = f(theta + k1 theta^3 + k2 theta^5 + ...), so each point becomes one
    equation and the coefficients fall out of least squares.

    Two terms by default, not four. Four fit better inside the frame -- 0.42 px
    RMS against 0.74 -- and then turn over 1.4 corner-radii out and go negative,
    which is exactly where stabilisation samples. Three tenths of a pixel is not
    worth that.
    """
    rmax = math.hypot(w / 2, h / 2)
    pts = []
    for k in range(1, 17):
        theta = math.atan((k / 16) * rmax / focal_px)
        pts.append((theta, table[k] * k / 16 / 32768 * rmax / focal_px))

    A = [[t ** (3 + 2 * i) for i in range(terms)] for t, _ in pts]
    b = [y - t for t, y in pts]
    n = terms
    N = [[sum(A[r][i] * A[r][j] for r in range(len(A))) for j in range(n)] +
         [sum(A[r][i] * b[r] for r in range(len(A)))] for i in range(n)]
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(N[r][i]))
        N[i], N[piv] = N[piv], N[i]
        for r in range(n):
            if r != i and N[i][i]:
                g = N[r][i] / N[i][i]
                for c in range(i, n + 1):
                    N[r][c] -= g * N[i][c]
    coeffs = [N[i][n] / N[i][i] for i in range(n)] + [0.0] * (4 - n)

    def mapped(t):
        return t + sum(coeffs[i] * t ** (3 + 2 * i) for i in range(4))

    res = [abs(mapped(t) - y) * focal_px for t, y in pts]
    rms = math.sqrt(sum(r * r for r in res) / len(res))

    corner = math.atan(rmax / focal_px)
    prev, safe = -1.0, 0.0
    for m in [x / 20 for x in range(2, 61)]:
        v = mapped(corner * m)
        if v < prev:
            break
        prev, safe = v, m
    return coeffs, rms, max(res), safe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", nargs="?", help="a .DNG, or a CINEMA clip folder")
    ap.add_argument("--size", help="WxH, when the footage is not at hand")
    ap.add_argument("--fps", type=float,
                    help="only needed without --gyr: the clip records its sensor mode, "
                         "and the mode fixes the frame rate")
    ap.add_argument("--focal-mm", type=float,
                    help="overrides the focal length in the frame's EXIF")
    ap.add_argument("--gyr", type=Path,
                    help="a .GYR from the same take; it carries the sensor mode the "
                         "camera was actually in, which resolution and frame rate "
                         "cannot tell apart")
    ap.add_argument("--dist-table",
                    help="the lens's 17 Q15 support points, from gyro/lens_dist.py; "
                         "a comma-separated list or a file containing one")
    ap.add_argument("--dist-terms", type=int, default=2,
                    help="how many distortion coefficients to fit (default 2)")
    ap.add_argument("--lens", help="overrides the lens name in the frame's EXIF")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    if a.size:
        w, h = (int(x) for x in a.size.lower().split("x"))
    else:
        w, h = None, None
    path = a.clip
    if path and os.path.isdir(path):
        frames = sorted(glob.glob(os.path.join(path, "*.DNG")))
        if not frames:
            raise SystemExit(f"no .DNG in {path}")
        path = frames[0]
    info = dng_info(path) if path else {}
    if w is None:
        if not path:
            raise SystemExit("give a clip or --size WxH")
        w, h = info.get("w"), info.get("h")
    if not w or not h:
        raise SystemExit("could not read image size")

    focal_mm = a.focal_mm if a.focal_mm else info.get("focal_mm")
    if not focal_mm:
        raise SystemExit("no focal length: the frame carries none, so pass --focal-mm")
    lens_name = a.lens or info.get("lens") or "unknown lens"

    modes = load_modes()
    fps = a.fps
    if a.fps:
        mode, scored = pick_mode(modes, w, h, a.fps)
    elif a.gyr:
        mode, scored = None, []          # the capture decides, below
    else:
        raise SystemExit("give --fps, or --gyr so the mode can come from the clip")

    if a.gyr:
        # The clip knows. `FUN_c032c720()` returns the sensor mode enum and the
        # logger calls it at record start, so there is nothing left to infer --
        # 1080p29.97 12-bit matches four modes whose readouts run from 5.4 to
        # 10.6 ms, and the output geometry scales evenly from either geometry
        # family, so it cannot be worked out from the footage alone.
        head = a.gyr.read_bytes()[:64]
        if head[:4] != b"GFS6":
            raise SystemExit(f"{a.gyr} is not a GFS6 capture")
        recorded = struct.unpack_from("<I", head, 48)[0]
        by_id = {m["mode_id"]: m for m in modes}
        if str(recorded) not in by_id:
            raise SystemExit(f"{a.gyr} records mode {recorded}, which is not in the "
                             "extracted tables")
        chosen = by_id[str(recorded)]
        if mode is not None and chosen is not mode:
            print(f"clip says mode {recorded}; resolution and frame rate alone "
                  f"would have guessed {mode['mode_id']}")
        mode, scored = chosen, [chosen]
    if fps is None:
        fps = mode["fps"]          # the mode fixes it; nothing to infer

    table = None
    if a.dist_table:
        text = a.dist_table
        if Path(text).exists():
            text = "\n".join(l for l in Path(text).read_text().splitlines()
                              if not l.startswith("#"))
        table = [int(x) for x in text.replace("\n", ",").split(",") if x.strip()]
        if len(table) != 17:
            raise SystemExit(f"--dist-table needs 17 values, got {len(table)}")

    covered_mm = SENSOR_ACTIVE_MM * min(mode["covered_w"], SENSOR_ACTIVE_W) / SENSOR_ACTIVE_W
    focal_px = w * focal_mm / covered_mm
    fov = 2 * math.degrees(math.atan(w / 2 / focal_px))
    full_width = mode["covered_w"] >= SENSOR_TOTAL_W - 64

    print(f"clip          {w} x {h} @ {fps:.3f} fps")
    print(f"mode          {mode['mode_id']}  readout {mode['readout_w']}x{mode['readout_h']} "
          f"binning {mode['bin_h']}x{mode['bin_v']}  {mode['bits']}-bit")
    print(f"covers        {mode['covered_w']} sensor columns "
          f"({'full width' if full_width else f'crop, {covered_mm:.1f} mm'})")
    print(f"focal         {focal_mm} mm -> {focal_px:.0f} px   (FOV {fov:.1f} deg)"
          + ("" if a.focal_mm else "   [from the frame]"))
    print(f"readout       {mode['readout_ms']:.3f} ms")
    dist = [0.0, 0.0, 0.0, 0.0]
    if table:
        dist, rms, worst, safe = fit_distortion(table, w, h, focal_px, a.dist_terms)
        print(f"distortion    {a.dist_terms} terms, {rms:.3f} px rms / {worst:.3f} px worst")
        print(f"              monotonic to {safe:.1f}x the corner radius")
        if safe < 1.5:
            print("              WARNING that is barely past the frame; "
                  "stabilisation samples outside it")
    if a.gyr:
        print(f"source        {a.gyr.name} -- the mode is recorded, not inferred")
    if len(scored) > 1:
        spread = {round(m["readout_ms"], 3) for m in scored}
        print(f"\n  NOTE: {len(scored)} modes share this resolution and frame rate "
              f"({', '.join(m['mode_id'] for m in scored)}).")
        if len(spread) > 1:
            print(f"  They differ only in line timing, so the focal length is the same for all "
                  f"of them\n  but the readout time is not: {sorted(spread)} ms. "
                  f"{mode['readout_ms']:.3f} was used.")
            print(f"  Resolution and frame rate cannot tell them apart -- the camera would have "
                  f"to\n  record which mode it was in. Readout mostly matters on fast pans.")

    profile = {
        "name": f"SIGMA fp - {lens_name} - {w}x{h} @{fps:.2f} (mode {mode['mode_id']})",
        "note": (f"Generated from the firmware's IMX410 mode tables. Mode {mode['mode_id']}: "
                 f"readout {mode['readout_w']}x{mode['readout_h']}, binning "
                 f"{mode['bin_h']}x{mode['bin_v']}, so it covers {mode['covered_w']} sensor "
                 f"columns -- {'the full width' if full_width else f'a crop spanning {covered_mm:.1f} mm'}. "
                 f"Focal {focal_mm} mm therefore lands at {focal_px:.0f} px. Readout "
                 f"{mode['readout_ms']:.3f} ms is that mode's active readout. Distortion is left "
                 f"at zero: it was not measured, which is not the same as being zero."),
        "calibrated_by": "firmware IMX410 mode tables (SIGMAfp_re)",
        "camera_brand": "SIGMA", "camera_model": "fp", "lens_model": lens_name,
        "camera_setting": f"{w}x{h} @{fps:.2f} CinemaDNG",
        "calib_dimension": {"w": w, "h": h},
        "orig_dimension": {"w": w, "h": h},
        "output_dimension": {"w": w, "h": h},
        "identifier": f"sigma_fp_mode{mode['mode_id']}_{w}x{h}",
        "calibrator_version": "1.5.0",
        "compatible_settings": [],
        "frame_readout_time": round(mode["readout_ms"], 3),
        "frame_readout_direction": "TopToBottom",
        "input_horizontal_stretch": 1.0, "input_vertical_stretch": 1.0,
        "num_images": 0,
        "fisheye_params": {
            "RMS_error": 0.0,
            "camera_matrix": [[focal_px, 0.0, w / 2], [0.0, focal_px, h / 2], [0.0, 0.0, 1.0]],
            "distortion_coeffs": dist,
        },
        "sync_settings": {}, "official": False,
    }
    out = a.out or Path(f"SIGMA_fp_mode{mode['mode_id']}_{w}x{h}.json")
    out.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
