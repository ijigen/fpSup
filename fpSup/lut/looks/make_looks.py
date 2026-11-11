#!/usr/bin/env python3
"""The .cube files the merge page offers with LUT (Bei 2026-11-12: only our two log
conversions until the licences are sorted out; the Spectral Film LUT copies are not offered).

    python3 -B fpSup/lut/looks/make_looks.py            # writes fpSup/lut/looks/*.cube
    python3 -B fpSup/lut/looks/make_looks.py --check    # the files here = a fresh build

Sources are the repo root's fp_p3d60_*.cube (projects/lut-sup/probes/chain_rebuild.py
and the Spectral Film LUT batch; input P3-D60 linear).  Each copy gets the author
lines the camera reads (native/import.c imp_author: the first 4 KiB) so it
converts without the user setting the input, and, for Spectral Film LUT, the
MIT notice in full (projects/lut-sup/notes/FREE_LUT_CANDIDATES.md #1).  The
table itself is copied byte for byte.  Card names are <= 8 characters: the
COLOR tile shows the first 8 (import_ui.label_text).
"""
import argparse, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
AUTHOR = b'# FPSUP_INPUT_COLOR_SPACE p3-d60\n# FPSUP_INPUT_GAMMA linear\n'
OURS = (b'# fpSup LUT (https://github.com/ijigen/fpSup): SIGMA fp P3-D60 linear -> %s.\n'
        b'# Colour calibration: Luka (Midnite), SigmaFP_OFF_to_Chart_v0.3.dctl (daylight/tungsten at 4300 K).\n'
        b'# Validation reference: Ole Berek. Log/gamut: published ARRI / Leica formulas. No vendor look data.\n')
MIT = b"""# Spectral Film LUT
# MIT License
#
# Copyright (c) 2026 Jan Lohse
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# https://github.com/JanLohse/spectral_film_lut
# Modified for the SIGMA fp by fpSup: input P3-D60 linear, output Rec.709 gamma 2.4, 65^3.
"""
# card name -> (source, notice)
LOOKS = {
    # Bei 2026-11-12: hidden until Luka (Midnite) and Ole Berek agree -- the calibration step is Luka's
    # 'LogC3': ('fp_p3d60_ARRI LogC3.cube', OURS % b'ARRI Wide Gamut 3 / LogC3'),
    # 'L-Log': ('fp_p3d60_Leica L-Log.cube', OURS % b'Leica L-Gamut / L-Log'),
    # Spectral Film LUT (MIT) -- not offered for now (Bei 2026-11-12); build() still handles them:
    # 'Portra': ('fp_p3d60_SFL Portra 400.cube', MIT), '250D': ('fp_p3d60_SFL Vision3 250D 2383.cube', MIT),
    # 'Velvia50': ('fp_p3d60_SFL Velvia 50.cube', MIT), 'TriX400': ('fp_p3d60_SFL Tri-X 400.cube', MIT),
}


def build(name):
    src, notice = LOOKS[name]
    raw = (ROOT / src).read_bytes()
    lines = raw.split(b'\n')
    title = [l for l in lines[:1] if l.startswith(b'TITLE')]
    rest = lines[len(title):]
    if src.startswith('fp_p3d60_SFL'):        # its own two-line credit is replaced by the full notice
        rest = [l for l in rest if not (l.startswith(b'# Spectral Film LUT') or l.startswith(b'# Modified for SIGMA fp'))]
    out = b'\n'.join(title) + (b'\n' if title else b'') + AUTHOR + notice + b'\n'.join(rest)
    assert out.find(b'FPSUP_INPUT_GAMMA') < 4096 and len(out) < 0x1000000
    assert raw.split(b'LUT_3D_SIZE', 1)[1] == out.split(b'LUT_3D_SIZE', 1)[1]     # the table is untouched
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    bad = 0
    for name in LOOKS:
        b, p = build(name), HERE / f'{name}.cube'
        if a.check:
            ok = p.exists() and p.read_bytes() == b; bad += not ok
            print(f'{name:9s} {"ok" if ok else "DIFFERS"}')
        else:
            p.write_bytes(b); print(f'{p.name:14s} {len(b):9,d} B')
    return bad


if __name__ == '__main__':
    sys.exit(main())
