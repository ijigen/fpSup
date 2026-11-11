"""What the camera needs to take any .cube copied to \\fpSup\\LUT\\ (user
2026-10-28: on-camera import, no computer step) -- native/import.c uses it:

- the part of every prepared asset that does not depend on the cube (the
  input-space matrices and the Gamma curves, build_sup.asset()'s first
  HEADER..one_off bytes): the camera writes the header and appends the cube's
  own 1D / 3D rows, parsed on the camera;
- a glyph atlas for the COLOR list's label tiles: ASCII 0x20..0x7E at three
  cap heights (the stock tile's 23 px, then smaller for long names), each
  glyph an 8-bit coverage bitmap; the camera lays a label out and packs it as
  an XCI whose LZ4 block holds literals only -- a valid compressed block every
  LZ4 decoder reads, so no "uncompressed block" flag is needed.

label_tile() / xci_literal() are the camera's algorithm in Python (the tests
compare its bytes with the ARM code's).
"""
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / 'projects/open-gate/build'), str(ROOT / 'projects/rawview/tools')]

MAGIC = 0x31504D49                     # "IMP1": native/import.c struct imp_section
W, H = 86, 74                          # a COLOR tile (set_common_1)
BASELINE, CENTER_X, MARGIN = 47, 42, 3
CAPS = (23, 19, 15)                    # px; the largest whose label fits W - 2*MARGIN
FIRST, LAST = 0x20, 0x7E
MAX_LABEL = 8
ATLAS_H = 32                           # rows per glyph cell (baseline at row BASE_ROW)
BASE_ROW = 26
FONT = '/System/Library/Fonts/Supplemental/Arial Narrow.ttf'
XCI_HEADER = 0x33


def glyph(ch, cap, ss=8, lo=0.05, hi=0.6):
    """One glyph's coverage (ATLAS_H rows, its own width) and advance, in the
    stock tile's style (rv_icon.render: Arial Narrow, tight edge)."""
    from PIL import Image, ImageDraw, ImageFont
    size = None
    for s in range(60, 6, -1):                         # the size whose 'H' is `cap` px tall
        f = ImageFont.truetype(FONT, s * ss)
        box = f.getbbox('H')
        if (box[3] - box[1]) / ss <= cap + 0.5:
            size = s; break
    f = ImageFont.truetype(FONT, size * ss)
    adv = int(round(f.getlength(ch) / ss))
    big = Image.new('L', ((adv + 4) * ss, ATLAS_H * ss), 0)
    asc = f.getbbox('H')[3]                             # baseline in the big image
    ImageDraw.Draw(big).text((2 * ss, BASE_ROW * ss - asc), ch, font=f, fill=255)
    sm = np.array(big.resize((adv + 4, ATLAS_H), Image.LANCZOS)).astype(float) / 255
    sm = np.clip((sm - lo) / (hi - lo), 0, 1)
    return (sm * 255 + 0.5).astype(np.uint8), adv


def atlas():
    """{cap: [(width, advance, bitmap)]} for FIRST..LAST."""
    out = {}
    for cap in CAPS:
        out[cap] = []
        for c in range(FIRST, LAST + 1):
            g, adv = glyph(chr(c), cap)
            out[cap].append((g.shape[1], adv, g))
    return out


def label_text(name):
    stem = name[:-5] if name.lower().endswith('.cube') else name
    t = ''.join(c if FIRST <= ord(c) <= LAST else '?' for c in stem[:MAX_LABEL])
    return t or '?'


def label_tile(name, at=None):
    """The tile: the label in the largest cap that fits, centred on CENTER_X,
    glyph boxes laid at their advances (2 px left padding each), coverage
    summed and clipped -- import.c imp_tile."""
    at = at or atlas()
    text = label_text(name)
    for cap in CAPS:
        glyphs = [at[cap][ord(c) - FIRST] for c in text]
        width = sum(adv for _w, adv, _g in glyphs)
        if width <= W - 2 * MARGIN or cap == CAPS[-1]:
            break
    tile = np.zeros((H, W), np.uint16)
    x = CENTER_X - width // 2
    top = BASELINE - BASE_ROW
    for w, adv, g in glyphs:
        x0 = x - 2
        for r in range(ATLAS_H):
            y = top + r
            if not 0 <= y < H:
                continue
            for c in range(w):
                xx = x0 + c
                if 0 <= xx < W:
                    tile[y, xx] = min(255, tile[y, xx] + int(g[r, c]))
        x += adv
    return tile.astype(np.uint8)


def xci_literal(tile):
    """An XCI whose LZ4 block is one literal-only sequence (import.c imp_xci)."""
    raw = ((tile.astype(np.uint16) << 8) | tile.astype(np.uint16)).astype('<u2').tobytes()
    n = len(raw)
    blk = bytearray([0xF0])
    rest = n - 15
    while rest >= 255:
        blk.append(255); rest -= 255
    blk.append(rest)
    blk += raw
    out = bytearray(XCI_HEADER)
    out[0:4] = b'XC\x00\x00'
    struct.pack_into('<I', out, 0x04, len(blk) + 23)
    struct.pack_into('<HH', out, 0x08, W, H)
    struct.pack_into('<I', out, 0x0C, 0x00000400)
    struct.pack_into('<H', out, 0x10, 0x0202)
    out[0x20:0x24] = b'\x04\x22\x4d\x18'
    out[0x24] = 0x88; out[0x25] = 0x10
    struct.pack_into('<I', out, 0x26, len(blk) + 19)
    struct.pack_into('<I', out, 0x2F, len(blk))
    return bytes(out) + bytes(blk) + b'\x00\x00\x00\x00'


ICON_BYTES = len(xci_literal(np.zeros((H, W), np.uint8)))


def atlas_blob(at=None):
    """Per cap: 95 x {u8 width, u8 advance, u16 0, u32 offset} then the bitmaps (ATLAS_H rows each)."""
    at = at or atlas()
    out = bytearray()
    for cap in CAPS:
        table = bytearray()
        data = bytearray()
        base = len(out) + 8 * (LAST - FIRST + 1)
        for w, adv, g in at[cap]:
            table += struct.pack('<BBHI', w, adv, 0, base + len(data))
            data += g.tobytes()
        out += table + data
        out += bytes(-len(out) % 4)
    return bytes(out)


def constants():
    """build_sup.asset()'s cube-independent payload: matrices, then curves."""
    import build_sup as B
    from cube import Cube
    one = Cube.parse(b'LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n')
    a = B.asset(one)
    three_off = struct.unpack_from('<I', a, 44)[0]
    return a[B.HEADER:three_off]


ICON_SLOT = (ICON_BYTES + 4 + 7) & ~7      # native/import.c imp_icon_slot: {u32 length, XCI}
FOLDER = '\\fpSup\\LUT'


def section(base):
    """struct imp_section and its data at block offset `base`."""
    head = 4 * 14
    at = atlas()
    blob = atlas_blob(at)
    tables, off = [], 0
    for cap in CAPS:                        # atlas_blob's per-cap layout: table, bitmaps, pad
        tables.append(off)
        n = 8 * (LAST - FIRST + 1) + sum(g.size for _w, _a, g in at[cap])
        off += n + (-(off + n) % 4)
    data = bytearray()

    def place(b, align=4):
        data.extend(bytes(-(head + len(data)) % align))
        p = base + head + len(data)
        data.extend(b)
        return p
    const = constants()
    const_off = place(const)
    atlas_off = place(blob)
    folder_off = place(FOLDER.encode() + b'\0')
    out = struct.pack('<14I', MAGIC, const_off, len(const), atlas_off, len(CAPS), *tables,
                      ICON_BYTES, ICON_SLOT, folder_off, *CAPS)
    assert len(out) == head
    return out + bytes(data)
