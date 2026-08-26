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


def dng_size(path):
    d = open(path, "rb").read(65536)
    bo = "<" if d[:2] == b"II" else ">"
    off = struct.unpack_from(bo + "I", d, 4)[0]
    n = struct.unpack_from(bo + "H", d, off)[0]
    w = h = None
    for i in range(n):
        tag, typ, cnt, val = struct.unpack_from(bo + "HHII", d, off + 2 + i * 12)
        if tag == 0x0100:
            w = val
        elif tag == 0x0101:
            h = val
    return w, h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", nargs="?", help="a .DNG, or a CINEMA clip folder")
    ap.add_argument("--size", help="WxH, when the footage is not at hand")
    ap.add_argument("--fps", type=float, required=True)
    ap.add_argument("--focal-mm", type=float, required=True,
                    help="lens focal length; L-mount block 0x0d reports it in tenths of a mm")
    ap.add_argument("--gyr", type=Path,
                    help="a .GYR from the same take; it carries the sensor mode the "
                         "camera was actually in, which resolution and frame rate "
                         "cannot tell apart")
    ap.add_argument("--lens", default="unknown lens")
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
    if w is None:
        if not path:
            raise SystemExit("give a clip or --size WxH")
        w, h = dng_size(path)
    if not w or not h:
        raise SystemExit("could not read image size")

    modes = load_modes()
    mode, scored = pick_mode(modes, w, h, a.fps)

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
        if chosen is not mode:
            print(f"clip says mode {recorded}; resolution and frame rate alone "
                  f"would have guessed {mode['mode_id']}")
        mode, scored = chosen, [chosen]

    covered_mm = SENSOR_ACTIVE_MM * min(mode["covered_w"], SENSOR_ACTIVE_W) / SENSOR_ACTIVE_W
    focal_px = w * a.focal_mm / covered_mm
    fov = 2 * math.degrees(math.atan(w / 2 / focal_px))
    full_width = mode["covered_w"] >= SENSOR_TOTAL_W - 64

    print(f"clip          {w} x {h} @ {a.fps:.3f} fps")
    print(f"mode          {mode['mode_id']}  readout {mode['readout_w']}x{mode['readout_h']} "
          f"binning {mode['bin_h']}x{mode['bin_v']}  {mode['bits']}-bit")
    print(f"covers        {mode['covered_w']} sensor columns "
          f"({'full width' if full_width else f'crop, {covered_mm:.1f} mm'})")
    print(f"focal         {a.focal_mm} mm -> {focal_px:.0f} px   (FOV {fov:.1f} deg)")
    print(f"readout       {mode['readout_ms']:.3f} ms")
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
        "name": f"SIGMA fp - {a.lens} - {w}x{h} @{a.fps:.2f} (mode {mode['mode_id']})",
        "note": (f"Generated from the firmware's IMX410 mode tables. Mode {mode['mode_id']}: "
                 f"readout {mode['readout_w']}x{mode['readout_h']}, binning "
                 f"{mode['bin_h']}x{mode['bin_v']}, so it covers {mode['covered_w']} sensor "
                 f"columns -- {'the full width' if full_width else f'a crop spanning {covered_mm:.1f} mm'}. "
                 f"Focal {a.focal_mm} mm therefore lands at {focal_px:.0f} px. Readout "
                 f"{mode['readout_ms']:.3f} ms is that mode's active readout. Distortion is left "
                 f"at zero: it was not measured, which is not the same as being zero."),
        "calibrated_by": "firmware IMX410 mode tables (SIGMAfp_re)",
        "camera_brand": "SIGMA", "camera_model": "fp", "lens_model": a.lens,
        "camera_setting": f"{w}x{h} @{a.fps:.2f} CinemaDNG",
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
            "distortion_coeffs": [0.0, 0.0, 0.0, 0.0],
        },
        "sync_settings": {}, "official": False,
    }
    out = a.out or Path(f"SIGMA_fp_mode{mode['mode_id']}_{w}x{h}.json")
    out.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
