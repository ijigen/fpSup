#!/usr/bin/env python3
"""Measure the sensor's readout time from the footage itself.

    ./rolling_shutter.py A001_018            -- pulls frames off the card
    ./rolling_shutter.py --dir frames/       -- uses DNGs already fetched

Why this exists: the sensor mode a take ran in cannot be read reliably at record
start.  `FUN_c032c720` returns the mode the imager is switching *to*, and
sampling it the instant the record flag goes up races the switch -- A001_016 and
A001_017, shot back to back on the same settings, recorded 8 and 106.  Their
readouts are 6.160 ms and 10.556 ms, which is the whole answer for a rolling
shutter, so guessing between them is not an option.

The measurement needs neither the mode, the focal length, nor the gyro:

    a frame-to-frame shift    d      = omega * T_frame   * focal_px
    the skew within a frame   s      = omega * T_readout * focal_px
    so                        T_readout = T_frame * s / d

Both unknowns divide out.  What it does need is a straight edge that is straight
for a known reason, so the take holds still first -- that baseline slope carries
any roll in how the camera is held -- and then pans.  The gyro is a cross-check
here, not an input.
"""
import argparse, struct, subprocess, sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SHELL = HERE.parent / 'fp_usb_shell'


def read_ifd(data, offset, bo):
    n = struct.unpack_from(bo + 'H', data, offset)[0]
    tags = {}
    for i in range(n):
        o = offset + 2 + i * 12
        tag, typ, cnt = struct.unpack_from(bo + 'HHI', data, o)
        tags[tag] = (typ, cnt, data[o + 8:o + 12])
    return tags


def tag_int(data, bo, tags, tag, default=None):
    if tag not in tags:
        return default
    typ, cnt, pl = tags[tag]
    if cnt == 1:
        return struct.unpack_from(bo + ('H' if typ == 3 else 'I'), pl)[0]
    off = struct.unpack_from(bo + 'I', pl)[0]
    fmt = 'H' if typ == 3 else 'I'
    return struct.unpack_from(bo + fmt, data, off)[0]


def read_dng(path):
    """The raw CFA plane as uint16, plus its width and height.

    Only what the fp writes: one uncompressed strip, 12 or 16 bits, no tiles.
    Anything else raises rather than guessing, because a silently wrong unpack
    would still produce a plausible-looking edge.
    """
    d = Path(path).read_bytes()
    bo = '<' if d[:2] == b'II' else '>'
    tags = read_ifd(d, struct.unpack_from(bo + 'I', d, 4)[0], bo)
    if 0x014A in tags:                       # SubIFDs -- the fp puts raw there
        typ, cnt, pl = tags[0x014A]
        sub = struct.unpack_from(bo + 'I', pl)[0]
        if cnt > 1:
            sub = struct.unpack_from(bo + 'I', d, sub)[0]
        tags = read_ifd(d, sub, bo)
    w = tag_int(d, bo, tags, 0x0100)
    h = tag_int(d, bo, tags, 0x0101)
    bits = tag_int(d, bo, tags, 0x0102, 16)
    comp = tag_int(d, bo, tags, 0x0103, 1)
    if comp != 1:
        raise SystemExit(f'{path}: compression {comp}, only uncompressed is handled')
    off = tag_int(d, bo, tags, 0x0111)
    cnt = tag_int(d, bo, tags, 0x0117)
    buf = d[off:off + cnt]
    if bits == 16:
        plane = np.frombuffer(buf, dtype=('<u2' if bo == '<' else '>u2')).astype(np.uint16)
    elif bits == 12:
        # Two pixels per three bytes, high bits first -- the TIFF packing, which
        # is big-endian within the pair whatever the file's byte order says.
        b = np.frombuffer(buf[:(len(buf) // 3) * 3], dtype=np.uint8).reshape(-1, 3).astype(np.uint16)
        plane = np.empty(b.shape[0] * 2, dtype=np.uint16)
        plane[0::2] = (b[:, 0] << 4) | (b[:, 1] >> 4)
        plane[1::2] = ((b[:, 1] & 0x0F) << 8) | b[:, 2]
    else:
        raise SystemExit(f'{path}: {bits} bits per sample is not handled')
    if plane.size < w * h:
        raise SystemExit(f'{path}: strip holds {plane.size} samples, expected {w*h}')
    return plane[:w * h].reshape(h, w).astype(np.float32), w, h


def green(plane):
    """One of the two green sites, so the profile is not modulated by the CFA.

    Half resolution in both axes; every x measured on it is doubled to get back
    to sensor columns, and the skew is reported in full-frame pixels.
    """
    return plane[0::2, 1::2]


def column_profile(g):
    return g.mean(axis=0)


def shift_between(a, b, limit=200):
    """Horizontal shift from profile a to profile b, to a fraction of a pixel."""
    a = a - a.mean()
    b = b - b.mean()
    n = len(a)
    lags = np.arange(-limit, limit + 1)
    scores = np.empty(len(lags), dtype=np.float64)
    for i, k in enumerate(lags):
        if k >= 0:
            scores[i] = np.dot(a[k:], b[:n - k]) if n - k > 0 else -np.inf
        else:
            scores[i] = np.dot(a[:n + k], b[-k:])
    j = int(np.argmax(scores))
    if 0 < j < len(lags) - 1:
        y0, y1, y2 = scores[j - 1], scores[j] , scores[j + 1]
        denom = y0 - 2 * y1 + y2
        sub = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
    else:
        sub = 0.0
    return lags[j] + sub


def band_shifts(g, bands=8, limit=60):
    """Where each horizontal band sits relative to the frame's own middle.

    Matching a band against the middle of the *same* frame would be comparing
    different scenery, so this is not that: each band is matched against the same
    band of the reference frame by the caller.  Here it just splits.
    """
    h = g.shape[0]
    edges = np.linspace(0, h, bands + 1).astype(int)
    return [(0.5 * (edges[i] + edges[i + 1]), column_profile(g[edges[i]:edges[i + 1]]))
            for i in range(bands)]


def skew_of(g_ref, g, bands=8, limit=120):
    """Per-band shift of `g` against `g_ref`, fitted to a line in y.

    The slope is the extra displacement a row picks up per row of readout: with
    a still reference it is the rolling-shutter skew, in half-resolution pixels
    per half-resolution row, which is the same number in full-frame units.
    """
    ref = band_shifts(g_ref, bands)
    cur = band_shifts(g, bands)
    ys, ds = [], []
    for (y, pr), (_, pc) in zip(ref, cur):
        ys.append(y)
        ds.append(shift_between(pr, pc, limit))
    ys = np.array(ys); ds = np.array(ds)
    slope, intercept = np.polyfit(ys, ds, 1)
    resid = ds - (slope * ys + intercept)
    return slope, ds.mean(), float(np.abs(resid).max())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('clip', nargs='?', help='e.g. A001_018; omit with --dir')
    ap.add_argument('--dir', type=Path, help='directory of already-fetched DNGs')
    ap.add_argument('--fps', type=float, default=29.97)
    ap.add_argument('--bands', type=int, default=8)
    a = ap.parse_args()

    if a.dir:
        frames = sorted(a.dir.glob('*.DNG')) + sorted(a.dir.glob('*.dng'))
    else:
        raise SystemExit('fetching from the card is not wired up yet; use --dir')
    if len(frames) < 4:
        raise SystemExit(f'need several frames, found {len(frames)}')

    print(f'  {len(frames)} frames, assuming {a.fps} fps')
    planes = []
    for f in frames:
        p, w, h = read_dng(f)
        planes.append(green(p))
    prof = [column_profile(g) for g in planes]

    # How far the camera swung between each pair, from the imagery alone.
    steps = [shift_between(prof[i], prof[i + 1], limit=250) for i in range(len(planes) - 1)]
    steps = np.array(steps)
    still = np.abs(steps) < 0.5
    print(f'  frame-to-frame shift  min {steps.min():+.2f}  max {steps.max():+.2f} px'
          f'   ({still.sum()} of {len(steps)} frames essentially still)')

    if not still.any():
        raise SystemExit('  no still stretch in this take: the baseline slope of the '
                         'edge is unknown, so the skew cannot be separated from how '
                         'the camera is held. Re-shoot with a few seconds held still '
                         'before the pan.')

    ref = int(np.flatnonzero(still)[len(np.flatnonzero(still)) // 2])
    print(f'  baseline from frame {ref} ({frames[ref].name})')

    # A frame can only be matched against the baseline while it still overlaps
    # it.  Twenty pixels a frame walks the whole scene out of view in a couple of
    # seconds, and a correlation against scenery that is no longer there returns
    # a confident wrong answer rather than an error, so the window is explicit.
    cum = np.concatenate([[0.0], np.cumsum(steps)]) - np.concatenate([[0.0], np.cumsum(steps)])[ref]
    span = planes[ref].shape[1]
    rows = []
    for i, g in enumerate(planes):
        d = steps[min(i, len(steps) - 1)]
        if abs(d) < 2 or abs(cum[i]) > 0.30 * span:
            continue
        slope, mean_shift, resid = skew_of(planes[ref], g, a.bands,
                                           limit=int(abs(cum[i])) + 40)
        # slope is px per half-res row; the skew across the whole readout is
        # slope * (number of half-res rows), which is the plane's height.
        skew = slope * planes[ref].shape[0]
        rows.append((i, d, skew, skew / d, resid))

    if not rows:
        raise SystemExit('  the pan never got above 2 px/frame; nothing to measure')

    ratios = np.array([r[3] for r in rows])
    keep = np.abs(ratios - np.median(ratios)) < 3 * (np.std(ratios) + 1e-9)
    t_frame_ms = 1000.0 / a.fps
    readout = t_frame_ms * ratios[keep]
    print(f'  usable frames         {keep.sum()} of {len(rows)} '
          f'(of {len(planes)} in the take; the rest are still or panned out of overlap)')
    print(f'  skew / step           {np.median(ratios[keep]):.3f} of a frame period')
    print(f'  readout time          {np.median(readout):.3f} ms '
          f'(spread {readout.min():.2f}..{readout.max():.2f})')
    print()
    print('  candidates: mode 8 = 6.160 ms, mode 106 = 10.556 ms, mode 111 = 7.828 ms')
    return 0


if __name__ == '__main__':
    sys.exit(main())
