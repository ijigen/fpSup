#!/usr/bin/env python3
"""List and export the XC graphics blocks in a decompressed SIGMA fp firmware.

The XC container is the camera's on-screen-display artwork: every menu label,
digit, icon and bar. Each block is one greyscale bitmap.

Usage:
    xc_decode.py list  IMAGE [--group H]
    xc_decode.py dump  IMAGE OUTDIR [--group H] [--index N]

IMAGE is a decompressed firmware image, for example FP__V203_dec.bin from
fw_unpack.py. Only raw blocks (version 0x0101, up to Ver 2.03) decode; Ver 3.00
and later pack the payload with a codec that is not decoded yet.

Blocks are written as PNG. No third-party modules are needed.
"""

import argparse
import os
import struct
import sys
import zlib

LOAD_ADDRESS = 0xC0000000
MAGIC = b'XC\0\0'
HEADER_SIZE = 0x20
RAW = 0x0101
PACKED = 0x0202


def find_container(data):
    """Return the file offset of the first XC block, or None."""
    off = data.find(MAGIC)
    while off != -1:
        if off % 4 == 0 and struct.unpack_from('<H', data, off + 0x0C)[0] == 0x0400:
            return off
        off = data.find(MAGIC, off + 1)
    return None


def read_blocks(data, start):
    """Walk the flat run of XC blocks from start. The container has no index."""
    blocks = []
    off = start
    while off + HEADER_SIZE <= len(data) and data[off:off + 4] == MAGIC:
        size, width, height = struct.unpack_from('<IHH', data, off + 4)
        version = struct.unpack_from('<H', data, off + 0x10)[0]
        blocks.append({
            'address': off + LOAD_ADDRESS,
            'width': width,
            'height': height,
            'version': version,
            'payload': data[off + HEADER_SIZE:off + HEADER_SIZE + size],
        })
        off += HEADER_SIZE + ((size + 3) & ~3)
    return blocks


def decode(payload, width, height):
    """Decode a raw payload into height rows of width 16-bit samples.

    Payload: u8 format (0x01), then records, then one trailer byte.
    Record:  u8 run, u8 count-1, then count little-endian u16 samples. After the
             samples the last sample repeats (run - 1) more times.
    The encoder stops as soon as the rest of the image is flat, so the tail is
    padded with the last sample. Rows run top to bottom, left to right.
    """
    if payload[0] != 1:
        raise ValueError('payload format 0x%02x is not supported' % payload[0])
    pixels = []
    off, end = 1, len(payload) - 1
    while off + 2 <= end:
        run, count = payload[off], payload[off + 1] + 1
        if off + 2 + 2 * count > end:
            break
        samples = list(struct.unpack_from('<%dH' % count, payload, off + 2))
        pixels += samples
        if run > 1:
            pixels += [samples[-1]] * (run - 1)
        off += 2 + 2 * count
    if not pixels:
        pixels = [0]
    pixels += [pixels[-1]] * (width * height - len(pixels))
    return [pixels[r * width:(r + 1) * width] for r in range(height)]


def write_png(path, rows):
    """Write 16-bit greyscale PNG."""
    height, width = len(rows), len(rows[0])
    raw = b''.join(b'\0' + struct.pack('>%dH' % width, *row) for row in rows)

    def chunk(tag, body):
        return (struct.pack('>I', len(body)) + tag + body
                + struct.pack('>I', zlib.crc32(tag + body) & 0xFFFFFFFF))

    header = struct.pack('>IIBBBBB', width, height, 16, 0, 0, 0, 0)
    with open(path, 'wb') as handle:
        handle.write(b'\x89PNG\r\n\x1a\n'
                     + chunk(b'IHDR', header)
                     + chunk(b'IDAT', zlib.compress(raw, 9))
                     + chunk(b'IEND', b''))


def load(path):
    with open(path, 'rb') as handle:
        data = handle.read()
    start = find_container(data)
    if start is None:
        sys.exit('no XC container found in %s' % path)
    return read_blocks(data, start)


def select(blocks, group, index):
    chosen = [b for b in blocks if group is None or b['height'] == group]
    if index is not None:
        chosen = chosen[index:index + 1]
    return chosen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('list', 'dump'))
    parser.add_argument('image')
    parser.add_argument('outdir', nargs='?')
    parser.add_argument('--group', type=int, help='keep only blocks of this height')
    parser.add_argument('--index', type=int, help='keep only the Nth block of the group')
    args = parser.parse_args()

    blocks = load(args.image)
    chosen = select(blocks, args.group, args.index)

    if args.command == 'list':
        packed = sum(1 for b in blocks if b['version'] == PACKED)
        print('%d blocks, %d packed' % (len(blocks), packed))
        for i, b in enumerate(chosen):
            print('%4d  %#010x  %4d x %-4d  %s'
                  % (i, b['address'], b['width'], b['height'],
                     'raw' if b['version'] == RAW else 'packed'))
        return

    if not args.outdir:
        sys.exit('dump needs an output directory')
    os.makedirs(args.outdir, exist_ok=True)
    written = skipped = 0
    for i, b in enumerate(chosen):
        if b['version'] != RAW or not b['width'] or not b['height']:
            skipped += 1
            continue
        try:
            rows = decode(b['payload'], b['width'], b['height'])
        except ValueError as error:
            print('%#010x: %s' % (b['address'], error), file=sys.stderr)
            skipped += 1
            continue
        name = '%03d_%08x_%dx%d.png' % (i, b['address'], b['width'], b['height'])
        write_png(os.path.join(args.outdir, name), rows)
        written += 1
    print('wrote %d, skipped %d' % (written, skipped))


if __name__ == '__main__':
    main()
