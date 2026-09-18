#!/usr/bin/env python3
"""fpSup-Gyro-HDMI timestamp channel -- encoder, decoder, and damage model.

Spec: projects/gyro-sup/notes/GYRO_HDMI_TIMESTAMP_SPEC.md

An 18-byte packet per frame, painted into the idle region of the HDMI raster as
32x32 luma blocks, one bit per block.  This file is the whole format: the
camera-side injector paints exactly what `encode()` lays out, and the host reads
frames back through `decode()`.

Written before the camera side deliberately.  The format has to survive 4:2:0
capture, limited/full range conversion and lossy recording, and none of that is
worth finding out on a camera -- `simulate()` applies all three here, offline,
in a second.  Run this file to see the round trip.
"""

import struct
import sys

MAGIC = 0x66705453                      # 'fpTS', big-endian in the packet
PACKET = 18                             # magic 4 + t_us 8 + seq 4 + crc 2
BITS = PACKET * 8                       # 144

BLOCK = 32                              # luma block edge, pixels
LO, HI = 16, 235                        # limited-range endpoints.  NOT 0/255:
                                        # a full<->limited conversion clamps
                                        # those, and then a bit is unreadable.
MID = (LO + HI) // 2

# The raster geometries the camera can output, and where RAW stops.  The idle
# fraction is HDMI_RAW_FORMAT.md 9.0(a): the 12-bit Bayer fills about 75.9% of
# a 2 B/px raster, so the tail is free.  UNVERIFIED on hardware -- see the spec
# section 9 item 1.  `first_row` is the parameter a measurement would correct.
RASTERS = {
    'UHD':  dict(w=3840, h=2160, first_row=1620),
    'DCI4K': dict(w=4096, h=2160, first_row=1620),
    'FHD':  dict(w=1920, h=1080, first_row=810),
}


def crc16(data):
    """CRC-16/CCITT-FALSE.  Small, and a bad frame has to be *detected*, not
    corrected -- a wrong timestamp silently shifts every sample after it."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def pack(t_us, seq):
    body = struct.pack('>IQI', MAGIC, t_us & 0xFFFFFFFFFFFFFFFF, seq & 0xFFFFFFFF)
    return body + struct.pack('>H', crc16(body))


def unpack(raw):
    """-> (t_us, seq) or None if the packet does not check out."""
    if len(raw) != PACKET:
        return None
    body, (crc,) = raw[:16], struct.unpack('>H', raw[16:])
    magic, t_us, seq = struct.unpack('>IQI', body)
    if magic != MAGIC or crc != crc16(body):
        return None
    return t_us, seq


def grid(raster):
    """Columns and rows of blocks available in the idle region."""
    r = RASTERS[raster]
    return r['w'] // BLOCK, (r['h'] - r['first_row']) // BLOCK


def capacity(raster):
    cols, rows = grid(raster)
    return cols * rows


def repeats(raster):
    """How many times each bit fits.  Whatever is left over is unused rather
    than partially filled: a half-written repeat would be counted by the
    majority vote as if it were a real reading."""
    return max(1, capacity(raster) // BITS)


def encode(t_us, seq, raster='UHD'):
    """-> (plan, packet).  plan is a list of (col, row, level), which is exactly
    what the camera-side injector walks.  Block order is row-major within the
    idle region, bit 0 = MSB of byte 0."""
    raw = pack(t_us, seq)
    bits = [(raw[i // 8] >> (7 - i % 8)) & 1 for i in range(BITS)]
    cols, rows = grid(raster)
    n = repeats(raster)
    plan = []
    for cell in range(BITS * n):
        # INTERLEAVED, not contiguous.  The first draft put a bit's repeats next
        # to each other, and one smudged row of blocks then wiped every copy of
        # a few bits -- unrecoverable, where the same damage spread across all
        # bits costs each of them one vote out of thirteen.  Interleaving is the
        # difference between surviving a scratch and not.
        bit = bits[cell % BITS]
        plan.append((cell % cols, cell // cols, HI if bit else LO))
    return plan, raw


def render(t_us, seq, raster='UHD'):
    """A full-frame luma plane with the packet painted in.  Only used by the
    tests and by anyone eyeballing the layout; the camera never builds one."""
    try:
        import numpy as np
    except ImportError:
        sys.exit('render() needs numpy; encode()/decode() do not')
    r = RASTERS[raster]
    y = np.zeros((r['h'], r['w']), dtype=np.uint8)
    plan, _ = encode(t_us, seq, raster)
    for col, row, level in plan:
        y0 = r['first_row'] + row * BLOCK
        y[y0:y0 + BLOCK, col * BLOCK:(col + 1) * BLOCK] = level
    return y


def decode(y, raster='UHD'):
    """-> (t_us, seq) or None.  `y` is a captured luma plane at raster size.

    Each block is read from its middle half only.  Block edges are where a
    lossy codec puts its error and where a resampler mixes neighbours, and the
    centre is the one part no filter kernel of reasonable size can reach.
    """
    try:
        import numpy as np
    except ImportError:
        sys.exit('decode() needs numpy')
    r = RASTERS[raster]
    if y.shape != (r['h'], r['w']):
        return None
    cols, _rows = grid(raster)
    n = repeats(raster)
    q = BLOCK // 4
    votes = []
    for cell in range(BITS * n):
        col, row = cell % cols, cell // cols
        y0 = r['first_row'] + row * BLOCK
        x0 = col * BLOCK
        patch = y[y0 + q:y0 + BLOCK - q, x0 + q:x0 + BLOCK - q]
        votes.append(1 if float(patch.mean()) > MID else 0)
    bits = []
    for i in range(BITS):
        window = votes[i::BITS][:n]     # matches the interleave in encode()
        bits.append(1 if sum(window) * 2 > len(window) else 0)
    raw = bytearray(PACKET)
    for i, b in enumerate(bits):
        if b:
            raw[i // 8] |= 1 << (7 - i % 8)
    return unpack(bytes(raw))


def simulate(y, chroma420=True, limited_to_full=True, blur=True, noise=0):
    """What the capture chain does to the luma plane on the way back.

    Every stage here is a real thing the spec says we have to survive, not a
    guess: 4:2:0 from the AVerMedia (all 15 of its formats), range conversion
    from any chain that thinks it is carrying video, and block-transform loss
    from BRAW or ProRes RAW.
    """
    import numpy as np
    out = y.astype(np.float32)
    if chroma420:
        pass                            # 4:2:0 leaves luma alone.  That is the
                                        # entire reason the data is in luma.
    if limited_to_full:
        out = (out - 16.0) * (255.0 / 219.0)
        out = np.clip(out, 0, 255)
    if blur:
        k = np.array([1, 2, 1], dtype=np.float32) / 4.0
        for axis in (0, 1):
            out = np.apply_along_axis(lambda m: np.convolve(m, k, mode='same'), axis, out)
    if noise:
        rng = np.random.default_rng(0)
        out = out + rng.normal(0, noise, out.shape)
    return np.clip(out, 0, 255).astype(np.uint8)


def _selftest():
    import numpy as np
    print(f'packet {PACKET} B = {BITS} bits, block {BLOCK}x{BLOCK}, levels {LO}/{HI}\n')
    print(f'{"raster":<8}{"cells":>8}{"repeats":>9}{"spare":>8}')
    for name in RASTERS:
        c, n = capacity(name), repeats(name)
        print(f'{name:<8}{c:8}{n:9}{c - BITS * n:8}')
    print()

    t_us, seq = 0x0000_01F4_2C3D_5E70, 12345
    ok = True
    for name in RASTERS:
        y = render(t_us, seq, name)
        for label, kw in (
                ('clean',            dict(blur=False, limited_to_full=False)),
                ('limited->full',    dict(blur=False)),
                ('+ blur',           dict()),
                ('+ blur + noise 8', dict(noise=8)),
                ('+ blur + noise 24', dict(noise=24))):
            got = decode(simulate(y, **kw), name)
            good = got == (t_us, seq)
            ok &= good
            print(f'  {name:<7}{label:<20}{"OK" if good else "FAIL " + str(got)}')
        print()

    # A frame that is nothing but the black the camera clears the raster to must
    # not decode: a dropped or mistimed capture has to read as absent, never as
    # timestamp zero.
    blank = np.zeros((RASTERS['UHD']['h'], RASTERS['UHD']['w']), dtype=np.uint8)
    rejected = decode(blank, 'UHD') is None
    ok &= rejected
    print(f'  blank frame rejected: {"OK" if rejected else "FAIL"}')
    print('\n' + ('all good' if ok else 'SOMETHING FAILED'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(_selftest())
