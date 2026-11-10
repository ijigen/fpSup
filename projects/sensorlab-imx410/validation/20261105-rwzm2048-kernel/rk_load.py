"""Load the isp-lab night1 CinemaDNG frames (uncompressed, single strip, 12-bit MSB-first, RGGB).

Frames come from `isp-lab/host/evidence_jxl.py unpack validation/RUN DEST push/`.
Default DEST root is the scratch dir below; override with env RWZM2_DIR.
"""
import os, struct, pathlib
import numpy as np

ROOT = pathlib.Path(os.environ.get(
    'RWZM2_DIR',
    '/private/tmp/claude-501/-Users-dido-Developer-localized-SIGMAfp-re/'
    'f4853b0e-658e-4c2b-be92-c46407ba9b43/scratchpad/rwzm2'))
CASES = {
    'z1024': (24, 25, 26),        # zoom 1023x1023 = stock 1:1, 3024x1708
    'z2048x1024': (15, 16, 17),   # zoom 2048 H, 1023 V, 1504x1708
    'z2048': (12, 13, 14),        # zoom 2048x2048, 1504x854
}
PLANES = {'R': (0, 0), 'G1': (0, 1), 'G2': (1, 0), 'B': (1, 1)}  # CFAPattern 00 01 01 02 = RGGB


def tags(b):
    o = struct.unpack_from('<I', b, 4)[0]
    n = struct.unpack_from('<H', b, o)[0]
    t = {}
    for i in range(n):
        tag, typ, cnt, val = struct.unpack_from('<HHII', b, o + 2 + 12 * i)
        t[tag] = (typ, cnt, val)
    return t


def load_dng(path):
    b = pathlib.Path(path).read_bytes()
    t = tags(b)
    w, h, bits = t[256][2], t[257][2], t[258][2] & 0xFFFF
    off, ln = t[273][2], t[279][2]
    assert bits == 12 and t[259][2] & 0xFFFF == 1
    num, den = struct.unpack_from('<II', b, t[50714][2])  # BlackLevel (4 equal rationals)
    black = num / den
    rb = w * 3 // 2  # strip may carry a few pad bytes at the end (z2048x1024: +12)
    raw = np.frombuffer(b, np.uint8, h * rb, off).reshape(h, rb).astype(np.uint16)
    a, bb, c = raw[:, 0::3], raw[:, 1::3], raw[:, 2::3]
    img = np.empty((h, w), np.uint16)
    img[:, 0::2] = (a << 4) | (bb >> 4)
    img[:, 1::2] = ((bb & 0xF) << 8) | c
    return img.astype(np.float64) - black, black


def frames(case):
    return np.stack([load_dng(ROOT / case / 'push' / f'cdng_{n:06d}.bin')[0] for n in CASES[case]])


def plane(img, name):
    dy, dx = PLANES[name]
    return img[..., dy::2, dx::2]
