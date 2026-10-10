#!/usr/bin/env python3
"""Render a SIGMA fp DNG through the camera's own colour modes.

This is the reference implementation of the pipeline that `docs/COLOR_MODES.md`
decodes. It is a worked example rather than a converter: it is short, it does no
sharpening or noise reduction, and it is meant to be read beside the document.

The chain, in the camera's order:

    raw -> linear ProPhoto        the DNG's own ColorMatrix2 and AsShotNeutral
        -> FRONT                  one measured 3x3, the only fitted-shaped thing
        -> mode matrix            MakerNote tag 292
        -> tone curve, per channel MakerNote tag 301, then an sRGB encode
        -> YC matrix              MakerNote tag 297, into the mode's chroma plane
        -> rotate and scale       MakerNote tag 299, 24 bins from 285 degrees
        -> back through Rec.601   which is what reads the Y, Cb, Cr a JPEG stores

**Almost everything comes out of the DNG itself.** Every fp DNG carries the
pipeline state its ISP ran on, as floats in the Sigma MakerNote, so this script
needs no firmware image for fourteen of the fifteen modes. The exception is Warm
Gold, which the camera does not export; pass `--firmware` to render it.

Usage:

    render_dng.py shot.DNG                      Standard, to shot_Standard.png
    render_dng.py shot.DNG --mode Vivid
    render_dng.py shot.DNG --mode all           every mode the file carries
    render_dng.py shot.DNG --list               what this DNG carries, then exit
    render_dng.py shot.DNG --mode WarmGold --firmware MAIN_dec.bin

Needs `rawpy`, `numpy` and `Pillow`.

## The one measured constant, and what it is tied to

`FRONT` is the transform from this script's linear decode to the camera's own
linear front end. It is measured, not tuned to a score: OFF's exported matrix is
the exact identity, so a render of OFF is the front end alone, and one least
squares of the OFF JPEG against the decode of the same frame fixes it on 709,631
pixels with a 2.31 percent residual. Because that fit never sees any mode's
matrix, every other mode is a prediction.

It is tied to **this exact decode**. Change the demosaic, the output space or the
white-balance handling and `FRONT` is wrong, because it is a bridge between two
pipelines rather than a property of the camera. The `rawpy` arguments in
`decode_prophoto` are pinned for that reason and should not be edited without
re-measuring `FRONT`.

It was measured on one body. `ColorMatrix1` and `ColorMatrix2` are identical in
the two DNGs this project has, which suggests they are per-model rather than
per-body, so `FRONT` should carry across fp bodies. That is untested.

## What this does not do

No exposure fudge. The scores quoted in `docs/COLOR_MODES.md` allowed the
brightness to vary by about a quarter stop per mode when matching the camera's
JPEG, to absorb decode differences. This script applies `FRONT` as measured and
nothing else, so a render may sit a little darker or lighter than the camera's
own JPEG of the same frame. That is honest rather than matched.

Warm Gold is knowingly wrong, at about 8 dE against the camera where every other
mode is under 2.9. The camera exports sixteen records and Warm Gold is not among
them, so its matrix is derived from the firmware table by a composition that is
exact only for modes which keep white neutral -- and Warm Gold shifts it by
0.188. See "Unread data" in `docs/COLOR_MODES.md`.
"""
import argparse
import struct
import sys

import numpy as np

# ---------------------------------------------------------------- constants --

#: ProPhoto linear -> camera linear. See the module docstring for provenance.
#: Row sums near 0.62 carry the exposure, so there is no separate trim.
FRONT = np.array([
    [0.826628, -0.048768, -0.155484],
    [-0.052120, 0.643991, 0.032050],
    [-0.106242, 0.218943, 0.510454],
])

XYZ_D50_TO_PROPHOTO = np.array([[1.3459433, -0.2556075, -0.0511118],
                                [-0.5445989, 1.5081673, 0.0205351],
                                [0.0, 0.0, 1.2118128]])
BRADFORD = np.array([[0.8951, 0.2664, -0.1614],
                     [-0.7502, 1.7135, 0.0367],
                     [0.0389, -0.0685, 1.0296]])
D50 = np.array([0.9642, 1.0000, 0.8249])

#: Rec.601, which is what a JPEG's Y, Cb and Cr are read as.
REC601 = np.array([[0.299, 0.587, 0.114],
                   [-0.168736, -0.331264, 0.5],
                   [0.5, -0.418688, -0.081312]])
REC601_INV = np.linalg.inv(REC601)

#: Bin 0 of the 24-bin hue table, in degrees of atan2(Cr, Cb). Confirmed five
#: ways; it is a sharp minimum, with 280 and 290 both clearly worse.
BIN_ZERO_DEG = 285.0

#: The order the preloader at 0xC02C57C0 writes every sixteen-record tag in.
#: Warm Gold (id 9) is absent and OFF (36) appears twice.
EXPORT_ORDER = [35, 1, 0, 3, 5, 6, 7, 14, 11, 12, 15, 8, 10, 36, 13, 36]

#: Menu name -> internal mode id.
MODES = {'Standard': 0, 'Monochrome': 1, 'Vivid': 3, 'Neutral': 5,
         'Portrait': 6, 'Landscape': 7, 'Cinematic': 8, 'WarmGold': 9,
         'TealAndOrange': 10, 'SunsetRed': 11, 'ForestGreen': 12,
         'PowderBlue': 13, 'FOVClassicBlue': 14, 'FOVClassicYellow': 15,
         'OFF': 36}

#: Gamma group per mode id, from the map at 0xC0B3D670. Only needed with
#: --firmware, which in practice means only for Warm Gold.
GAMMA_GROUP = {0: 5, 3: 16, 7: 16, 8: 16, 10: 16, 11: 16, 12: 16, 14: 16,
               15: 16, 5: 27, 6: 38, 13: 49, 9: 433, 1: 71, 36: 82}

GAMMA_BANK = 0xC096CF34
HUE_TABLE = 0xC0B400AC
MATRIX_TABLE = 0xC0B3A340


# ------------------------------------------------------------- MakerNote IO --

def _tiff_base(d):
    """Where the TIFF header starts. A DNG begins with one; a JPEG wraps it."""
    if d[:2] in (b'II', b'MM'):
        return 0
    i = 2
    while i + 4 <= len(d) and d[i] == 0xFF:
        m = d[i + 1]
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        n = struct.unpack_from('>H', d, i + 2)[0]
        if m == 0xE1 and d[i + 4:i + 10] == b'Exif\0\0':
            return i + 10
        if m == 0xDA:
            break
        i += 2 + n
    raise SystemExit('not a TIFF, DNG or JPEG: no TIFF header found')


_TYPESZ = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
_TYPEFMT = {1: 'B', 3: 'H', 4: 'I', 6: 'b', 8: 'h', 9: 'i', 11: 'f', 12: 'd'}


def _entries(d, off, bo):
    n = struct.unpack_from(bo + 'H', d, off)[0]
    for i in range(n):
        e = off + 2 + i * 12
        tag, typ, cnt = struct.unpack_from(bo + 'HHI', d, e)
        yield tag, typ, cnt, e + 8


def _value(d, bo, typ, cnt, poff, base):
    size = _TYPESZ.get(typ, 1) * cnt
    off = poff if size <= 4 else base + struct.unpack_from(bo + 'I', d, poff)[0]
    if typ in (2, 7):
        return d[off:off + size]
    if typ in (5, 10):                                  # RATIONAL, SRATIONAL
        f = 'II' if typ == 5 else 'ii'
        # a zero denominator is legal in the wild and means "undefined"; some
        # Sigma MakerNote rationals use it for unset fields
        return np.array([a / b if b else 0.0 for a, b in
                         (struct.unpack_from(bo + f, d, off + 8 * i) for i in range(cnt))])
    fmt = _TYPEFMT.get(typ)
    if fmt is None:
        return d[off:off + size]
    return np.array(struct.unpack_from(bo + str(cnt) + fmt, d, off))


def read_tags(path):
    """(MakerNote tags, DNG IFD0 tags) for a DNG or a JPEG.

    The Sigma MakerNote is Exif tag 37500. Its header is `SIGMA\\0\\0\\0` then a
    two-byte version, the IFD count sits at offset 10 and the entries start at
    12. **Value offsets are relative to the TIFF base, not to the MakerNote.**
    Getting that wrong yields plausible-looking garbage rather than an error.
    """
    d = open(path, 'rb').read()
    try:
        base = _tiff_base(d)
    except SystemExit as e:
        raise SystemExit(f'{path}: {e}')
    bo = '<' if d[base:base + 2] == b'II' else '>'
    ifd0 = base + struct.unpack_from(bo + 'I', d, base + 4)[0]

    dng, exif = {}, None
    for tag, typ, cnt, poff in _entries(d, ifd0, bo):
        if tag == 34665:
            exif = base + int(np.atleast_1d(_value(d, bo, typ, cnt, poff, base))[0])
        elif tag in (0xC621, 0xC622, 0xC628):           # ColorMatrix1/2, AsShotNeutral
            dng[tag] = _value(d, bo, typ, cnt, poff, base)
    if exif is None:
        raise SystemExit(f'{path}: no ExifIFD')

    mkn = None
    for tag, typ, cnt, poff in _entries(d, exif, bo):
        if tag == 37500:
            mkn = base + struct.unpack_from(bo + 'I', d, poff)[0]
    if mkn is None:
        raise SystemExit(f'{path}: no MakerNote')
    if d[mkn:mkn + 5] != b'SIGMA':
        raise SystemExit(f'{path}: MakerNote is not SIGMA ({d[mkn:mkn + 8]!r})')

    tags = {}
    for tag, typ, cnt, poff in _entries(d, mkn + 10, bo):
        tags[tag] = _value(d, bo, typ, cnt, poff, base)
    return tags, dng


def exported_state(tags):
    """{mode id: (matrix, yc, hue, curve)} for every mode the file carries.

    Tag 292 is sixteen 3x3 mode matrices, 297 sixteen YC matrices, 299 the hue
    tables as 16 x 24 bins x 2 variants x (degrees, saturation, value), and 301
    sixteen 128-point tone curves as (x, y) pairs. Records are identified by
    their position in EXPORT_ORDER, which the firmware hardcodes.
    """
    need = (292, 297, 299, 301)
    missing = [t for t in need if t not in tags]
    if missing:
        raise SystemExit('this file carries no exported pipeline state (missing tags '
                         f'{missing}).\nOnly DNGs carry it; JPEGs never do.')
    mat = np.asarray(tags[292], float).reshape(16, 3, 3)
    yc = np.asarray(tags[297], float).reshape(16, 3, 3)
    hue = np.asarray(tags[299], float).reshape(16, 24, 2, 3)
    curve = np.asarray(tags[301], float).reshape(16, 128, 2)
    out = {}
    for i, mid in enumerate(EXPORT_ORDER):
        out.setdefault(mid, (mat[i], yc[i], hue[i], curve[i]))
    return out


# ----------------------------------------------------------- firmware fallback --

def firmware_state(path, mid):
    """(matrix, yc, hue, curve) for a mode the camera does not export.

    In practice this is Warm Gold alone. The matrix is derived from the table at
    0xC0B3A340 by the composition rule, which is **known to be wrong for this
    mode**: it row-normalises, and that discards Warm Gold's channel gain of
    1.188, 1.000, 0.846 -- the red lift its name promises. The YC matrix falls
    back to the class default at descriptor entry 31.
    """
    img = open(path, 'rb').read()

    def rec(base, stride, want, n=40):
        for k in range(n):
            o = base - 0xC0000000 + k * stride
            if o + stride > len(img):
                break
            if struct.unpack_from('<I', img, o)[0] == want:
                return o
        return None

    def rows(h):
        return np.array([[h[0], h[1], h[2]], [h[4], h[3], h[5]], [h[7], h[8], h[6]]], float)

    def loader(o):
        h = struct.unpack_from('<9h', img, o + 4)
        return rows(h) / (h[0] + h[1] + h[2])

    o_mode, o_off = rec(MATRIX_TABLE, 24, mid), rec(MATRIX_TABLE, 24, 36)
    if o_mode is None or o_off is None:
        raise SystemExit(f'firmware: no matrix record for mode id {mid}')
    m = np.linalg.inv(loader(o_off)) @ loader(o_mode)
    m = m / m.sum(1, keepdims=True)

    o_hue = rec(HUE_TABLE, 580, mid, n=17)
    if o_hue is None:
        raise SystemExit(f'firmware: no hue record for mode id {mid}')
    hue = np.array(struct.unpack_from('<144f', img, o_hue + 4)).reshape(24, 2, 3)

    grp = GAMMA_GROUP[mid]
    o_g = GAMMA_BANK + (grp + 5) * 0x1000 - 0xC0000000
    if o_g + 4096 > len(img):
        raise SystemExit(f'firmware: gamma group {grp} is past the end of the image')
    bank = np.array(struct.unpack_from('<2048H', img, o_g), float) / 8190.0

    # the bank is srgb_encode(tone_curve), so undo the encode to get the curve
    x = np.arange(128) / 128.0
    x[-1] = 1.0
    y = np.interp(x * WHITE, np.arange(2048), bank)
    curve = np.stack([x, _srgb_decode(y)], -1)

    # descriptor entry 31, the YC class default keyed 100
    yc = np.array([[0.298828, 0.586670, 0.114502],
                   [-0.011719, -0.488281, 0.500000],
                   [0.500000, -0.390625, -0.109375]])
    return m, yc, hue, curve


# ------------------------------------------------------------------- the chain --

#: Where the camera's curve reaches white. The bank's own full scale is entry
#: 2047, and 1919 is 15/16 of it: resampling at 1919 puts linear 1.0 at the
#: camera's white and leaves the last 1/16 as headroom. Read that way OFF's
#: curve is a plain sRGB encode to 0.0007; read across 0..2047 it is 0.028 away,
#: because it is then srgb(16/15 x). FRONT carries the same units.
WHITE = 1919.0


def _srgb_encode(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def _srgb_decode(y):
    y = np.clip(y, 0.0, 1.0)
    return np.where(y <= 0.04045, y / 12.92, ((y + 0.055) / 1.055) ** 2.4)


def _adapt(white_xyz):
    """Bradford adaptation from an as-shot white onto D50."""
    s, d = BRADFORD @ white_xyz, BRADFORD @ D50
    return np.linalg.inv(BRADFORD) @ np.diag(d / s) @ BRADFORD


def decode_prophoto(path, dng, half_size=False):
    """The DNG to linear ProPhoto RGB, by the route FRONT was measured against.

    rawpy is asked for camera-native RGB with the camera white balance applied
    and no tone curve. The DNG spec route then takes it to XYZ: undo the white
    balance with AsShotNeutral, apply the inverse ColorMatrix, and adapt the
    as-shot white onto D50 so neutral stays neutral.

    Do not change these arguments without re-measuring FRONT.
    """
    import rawpy
    with rawpy.imread(path) as r:
        rgb = r.postprocess(output_color=rawpy.ColorSpace.raw, no_auto_bright=True,
                            gamma=(1, 1), output_bps=16, use_camera_wb=True,
                            half_size=half_size)
    cam = rgb.astype(np.float32) / 65535.0
    if 0xC622 not in dng or 0xC628 not in dng:
        raise SystemExit('DNG is missing ColorMatrix2 or AsShotNeutral')
    cm = np.asarray(dng[0xC622], float).reshape(3, 3)
    asn = np.asarray(dng[0xC628], float)
    m = np.linalg.inv(cm) @ np.diag(asn)
    white = m @ np.ones(3)
    cam2xyz = _adapt(white / white[1]) @ m
    return cam @ (XYZ_D50_TO_PROPHOTO @ cam2xyz).T.astype(np.float32)


def develop(pp, state):
    """Linear ProPhoto to display-referred sRGB, through one mode."""
    matrix, yc, hue, curve = state

    lin = np.clip(pp @ FRONT.T.astype(np.float32), 0, None)
    lin = np.clip(lin @ matrix.T.astype(np.float32), 0, 1)

    # The tone curve, per channel, then the sRGB encode the bank folds in.
    # Tag 301's x axis runs 0..1 over the bank's *own* full scale of 2047, while
    # `lin` runs 0..1 over the camera's white at 1919, so the two differ by
    # 1919/2047 = 15/16. Drop this factor and every render comes out about
    # 0.016 too dark, uniformly.
    x = np.clip(lin * np.float32(WHITE / 2047.0), 0, 1)
    enc = _srgb_encode(np.interp(x, curve[:, 0], curve[:, 1])).astype(np.float32)

    # into this mode's chroma plane
    v = enc @ yc.T.astype(np.float32)
    y, cb, cr = v[..., 0], v[..., 1], v[..., 2]

    # the equaliser: rotate and scale by 15-degree bin, blended with the neighbour
    rot = hue[:, 0, 0].astype(np.float32)        # variant 0: degrees
    gain = hue[:, 0, 1].astype(np.float32)       # variant 0: absolute saturation
    ang = (np.degrees(np.arctan2(cr, cb)) % 360.0 - BIN_ZERO_DEG) % 360.0
    q = ang / 15.0
    lo = np.floor(q).astype(np.int32) % 24
    hi = (lo + 1) % 24
    fr = (q - np.floor(q)).astype(np.float32)
    r = np.radians(rot[lo] + (rot[hi] - rot[lo]) * fr)
    g = gain[lo] + (gain[hi] - gain[lo]) * fr
    c, s = np.cos(r), np.sin(r)
    cb2 = g * (cb * c - cr * s)
    cr2 = g * (cb * s + cr * c)

    # out through Rec.601, which is how a JPEG's Y, Cb and Cr are read
    out = np.stack([y, cb2, cr2], -1) @ REC601_INV.T.astype(np.float32)
    return np.clip(out, 0, 1)


# --------------------------------------------------------------------- driver --

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Render a SIGMA fp DNG through the camera's own colour modes.",
        epilog='See docs/COLOR_MODES.md for where every number comes from.')
    ap.add_argument('dng', help='a DNG written by a SIGMA fp')
    ap.add_argument('--mode', default='Standard',
                    help='mode name, or "all". Default: Standard')
    ap.add_argument('--out', help='output PNG. Default: <dng stem>_<mode>.png')
    ap.add_argument('--firmware', help='decompressed firmware, needed only for WarmGold')
    ap.add_argument('--half', action='store_true', help='half-size decode, 4x faster')
    ap.add_argument('--list', action='store_true',
                    help='report what this file carries, then exit')
    a = ap.parse_args(argv)

    tags, dng = read_tags(a.dng)
    shot = tags.get(61, b'?').split(b'\0')[0].decode(errors='replace')
    state = exported_state(tags)
    have = {n: i for n, i in MODES.items() if i in state}

    if a.list:
        print(f'{a.dng}\n  shot in mode: {shot}')
        print(f'  exported modes ({len(have)}): {", ".join(sorted(have))}')
        absent = sorted(set(MODES) - set(have))
        print(f'  not exported: {", ".join(absent) or "none"}'
              + ('   (pass --firmware to render)' if absent else ''))
        return 0

    if a.mode == 'all':
        wanted = [n for n in MODES if n in have or a.firmware]
    elif a.mode in MODES:
        wanted = [a.mode]
    else:
        ap.error(f'unknown mode {a.mode!r}. Known: {", ".join(MODES)}, or "all"')

    # Resolve every mode's tables before decoding, so a missing --firmware is
    # reported in a moment rather than after a full decode.
    jobs, skipped = [], []
    for name in wanted:
        mid = MODES[name]
        if mid in state:
            jobs.append((name, state[mid], False))
        elif a.firmware:
            jobs.append((name, firmware_state(a.firmware, mid), True))
        else:
            skipped.append(name)
    for name in skipped:
        print(f'{name}: not exported by this file, and no --firmware given. Skipped.')
    if not jobs:
        return 1

    from PIL import Image
    pp = decode_prophoto(a.dng, dng, half_size=a.half)
    print(f'decoded {a.dng}: {pp.shape[1]}x{pp.shape[0]}, shot in {shot}')

    stem = a.dng.rsplit('.', 1)[0]
    for name, st, derived in jobs:
        out = develop(pp, st)
        path = a.out if (a.out and len(jobs) == 1) else f'{stem}_{name}.png'
        Image.fromarray((out * 255.0 + 0.5).astype(np.uint8)).save(path)
        note = '   (derived, known wrong -- see the docstring)' if derived else ''
        print(f'  {name:18s} -> {path}{note}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
