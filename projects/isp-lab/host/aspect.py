#!/usr/bin/env python3
"""Picture distortion: the LV's content aspect against the DNG's physical aspect (case.py checks it).

DNG physical aspect = (w x Zh x Sh) / (h x Zv x Sv): record pixels back to sensor pixels (RWZM per axis, CRCT vbin,
sensor merge).  LV content aspect = the non-black bounding box of the frame x the buffer's pixel aspect (a 1620x1080
buffer on the 3:2 LCD is not square-pixel); PIXEL_ASPECT is calibrated on stock takes.
"""
import numpy as np

BLACK = 10                              # Y below this is a bar
PIXEL_ASPECT = {}                       # (w, h) -> display width / height per buffer pixel; filled by calibrate()


def content_box(y):
    """(x0, y0, x1, y1) of the non-black area of a luma plane."""
    cols = np.where(y.mean(axis=0) > BLACK)[0]
    rows = np.where(y.mean(axis=1) > BLACK)[0]
    if not len(cols) or not len(rows):
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def lv_aspect(raw, w, h):
    y = np.frombuffer(raw, np.uint8)[:w * h * 2][0::2].reshape(h, w).astype(float)
    b = content_box(y)
    if not b:
        return None
    return (b[2] - b[0]) / (b[3] - b[1]) * PIXEL_ASPECT.get((w, h), 1.0), b


def dng_aspect(want):
    """want = applied.json's want: rec, zoom (1023 = 1:1), bin, scale."""
    zh, zv = (max(z, 1024) for z in want['zoom'])
    sh, sv = want['scale']
    hb, vb = want['bin']
    return want['rec'][0] * zh * sh * hb / (want['rec'][1] * zv * sv * vb)
