#!/usr/bin/env python3
"""Extract the SIGMA fp colour-mode look tables from a decompressed firmware.

Each colour mode is three pieces of data:

  1. a 3x3 colour matrix, Q9 fixed point (512 = 1.0)
  2. a 24-bin hue table: for each 15-degree bin, a hue rotation in degrees,
     a saturation multiplier and a value multiplier
  3. a shared 128-point tone curve (only Standard and OFF carry one)

Usage:
    colormode_extract.py report IMAGE          human-readable dump
    colormode_extract.py json   IMAGE [FILE]   machine-readable dump

IMAGE is a decompressed firmware image, for example MAIN_dec.bin or
FP__V203_dec.bin from fw_unpack.py.

The tables are found by signature, so this works on Ver 1.02 through Ver 5.02.
"""

import argparse
import json
import struct
import sys

LOAD_ADDRESS = 0xC0000000

# Signatures. Each one is the first bytes of the Standard entry of its table.
# They are byte-identical in every firmware from Ver 1.02 to Ver 5.02.
SIG_LOOK = bytes.fromhex('0ad7b340c3e5d13f0000803f0ad7b340c3e5d13f0000803f'
                         '0000344123e9b63f')
SIG_MATRIX = struct.pack('<10h', 452, 118, -58, 646, 0, -134, 537, 0, -25, 0)
SIG_TONE = bytes.fromhex('0000000000000000feff493c06009a3b0180ca3cfeff4b3c'
                         '00c0173d0100da3c')

LOOK_STRIDE = 580      # u32 mode id + 24 bins * 2 variants * 3 floats
MATRIX_STRIDE = 24     # u32 mode id + 9 int16 + 1 pad
TONE_STRIDE = 1028     # u32 mode id + 128 (x, y) float pairs
BINS = 24
BIN_DEGREES = 360 // BINS

# Mode ids per firmware. The internal enum gained values over time and every
# id above the insertion point moved up by one, so the numbers differ per
# version. Derived by matching record contents between consecutive versions.
MODE_NAMES = {
    14: {0: 'Standard', 1: 'Monochrome', 3: 'Vivid', 5: 'Neutral',
         6: 'Portrait', 7: 'Landscape', 8: 'Cinematic', 9: 'TealAndOrange',
         10: 'SunsetRed', 11: 'ForestGreen', 12: 'FOVClassicBlue',
         13: 'FOVClassicYellow', 22: 'unmapped-A', 23: 'unmapped-B'},
    15: {0: 'Standard', 1: 'Monochrome', 3: 'Vivid', 5: 'Neutral',
         6: 'Portrait', 7: 'Landscape', 8: 'Cinematic', 9: 'TealAndOrange',
         10: 'SunsetRed', 11: 'ForestGreen', 12: 'FOVClassicBlue',
         13: 'FOVClassicYellow', 22: 'unmapped-A', 23: 'OFF',
         24: 'unmapped-B'},
    16: {0: 'Standard', 1: 'Monochrome', 3: 'Vivid', 5: 'Neutral',
         6: 'Portrait', 7: 'Landscape', 8: 'Cinematic', 9: 'TealAndOrange',
         10: 'SunsetRed', 11: 'ForestGreen', 12: 'PowderBlue',
         13: 'FOVClassicBlue', 14: 'FOVClassicYellow'},
    17: {0: 'Standard', 1: 'Monochrome', 3: 'Vivid', 5: 'Neutral',
         6: 'Portrait', 7: 'Landscape', 8: 'Cinematic', 9: 'WarmGold',
         10: 'TealAndOrange', 11: 'SunsetRed', 12: 'ForestGreen',
         13: 'PowderBlue', 14: 'FOVClassicBlue', 15: 'FOVClassicYellow',
         35: 'unmapped-A', 36: 'OFF', 37: 'unmapped-B'},
}
# Ver 3.00 and Ver 4.00 share the 16-entry map above but number the three
# high ids differently.
HIGH_IDS = {16: {33: 'unmapped-A', 34: 'OFF', 35: 'unmapped-B'}}
HIGH_IDS_V400 = {34: 'unmapped-A', 35: 'OFF', 36: 'unmapped-B'}


def find(data, sig, what):
    at = data.find(sig)
    if at < 0:
        sys.exit('cannot find the %s table in this image' % what)
    if data.find(sig, at + 1) >= 0 and what != 'matrix':
        sys.exit('the %s signature is not unique in this image' % what)
    return at


def walk(data, start, stride, limit=200, valid=None):
    """Read (mode_id, record_bytes) until the record stops being plausible."""
    out, off = [], start
    while len(out) < limit and off + stride <= len(data):
        mode = struct.unpack_from('<I', data, off)[0]
        body = data[off + 4:off + stride]
        if mode > 0x40 or (valid and not valid(body)):
            break
        out.append((mode, body))
        off += stride
    return out


def looks_like_look(body):
    f = struct.unpack('<%df' % (BINS * 6), body[:BINS * 24])
    for i in range(BINS):
        hue, sat, val = f[6 * i], f[6 * i + 1], f[6 * i + 2]
        if not (-90 <= hue <= 90 and 0 <= sat <= 8 and 0.05 <= val <= 8):
            return False
    return True


def looks_like_matrix(body):
    v = struct.unpack('<10h', body[:20])
    if v[9] != 0:
        return False
    return all(-2048 <= x <= 2048 for x in v[:9])


def looks_like_tone(body):
    f = struct.unpack('<256f', body[:1024])
    if f[0] != 0.0 or f[1] != 0.0 or abs(f[254] - 1.0) > 1e-6:
        return False
    return all(0.0 <= x <= 1.001 for x in f)


def name_map(count, matrix_ids):
    names = dict(MODE_NAMES.get(count, {}))
    if count == 16:
        names.update(HIGH_IDS_V400 if 35 in matrix_ids else HIGH_IDS[16])
    return names


def read(path):
    with open(path, 'rb') as handle:
        data = handle.read()

    look_start = find(data, SIG_LOOK, 'look') - 4
    looks = walk(data, look_start, LOOK_STRIDE, valid=looks_like_look)

    matrix_start = find(data, SIG_MATRIX, 'matrix') - 4
    # Two tables carry the Standard matrix. Take the one whose first id is 0.
    if struct.unpack_from('<I', data, matrix_start)[0] != 0:
        matrix_start = data.find(SIG_MATRIX, matrix_start + 4) - 4
    matrices = walk(data, matrix_start, MATRIX_STRIDE, valid=looks_like_matrix)

    tone_start = find(data, SIG_TONE, 'tone') - 4
    tones = walk(data, tone_start, TONE_STRIDE, limit=4, valid=looks_like_tone)

    names = name_map(len(looks), [m for m, _ in matrices])
    modes = {}
    for mode, body in looks:
        flat = struct.unpack('<%df' % (BINS * 6), body[:BINS * 24])
        modes.setdefault(mode, {})['hue_table'] = [
            {'hue_deg': round(flat[6 * i], 4),
             'sat': round(flat[6 * i + 1], 6),
             'val_a': round(flat[6 * i + 2], 6),
             'val_b': round(flat[6 * i + 5], 6)} for i in range(BINS)]
    for mode, body in matrices:
        # Several parallel matrix tables follow each other, and the later ones
        # repeat the same ids with identity rows. Keep the first one seen.
        if 'matrix' in modes.get(mode, {}):
            continue
        v = struct.unpack('<10h', body[:20])
        # Each row stores its own channel first, then the other two in RGB
        # order: R row is (RR, RG, RB), G row is (GG, GR, GB), B is (BB, BR, BG).
        modes.setdefault(mode, {})['matrix'] = [
            [v[0] / 512, v[1] / 512, v[2] / 512],
            [v[4] / 512, v[3] / 512, v[5] / 512],
            [v[7] / 512, v[8] / 512, v[6] / 512]]
    for mode, body in tones:
        f = struct.unpack('<256f', body[:1024])
        modes.setdefault(mode, {})['tone_curve'] = [
            [round(f[2 * i], 6), round(f[2 * i + 1], 6)] for i in range(128)]

    for mode in modes:
        modes[mode]['id'] = mode
        modes[mode]['name'] = names.get(mode, 'id-%d' % mode)
    return {'look_table': hex(look_start + LOAD_ADDRESS),
            'matrix_table': hex(matrix_start + LOAD_ADDRESS),
            'tone_table': hex(tone_start + LOAD_ADDRESS),
            'modes': [modes[m] for m in sorted(modes)]}


def report(db):
    print('look table   %s' % db['look_table'])
    print('matrix table %s' % db['matrix_table'])
    print('tone table   %s' % db['tone_table'])
    for m in db['modes']:
        print('\n=== id %-3d %s' % (m['id'], m['name']))
        if 'matrix' in m:
            gains = [sum(r) for r in m['matrix']]
            for label, row in zip('RGB', m['matrix']):
                print('   %s\' = %+.4f R %+.4f G %+.4f B'
                      % (label, row[0], row[1], row[2]))
            print('   channel gains  R %.3f  G %.3f  B %.3f' % tuple(gains))
        if 'hue_table' in m:
            print('   bin(deg): '
                  + ' '.join('%6d' % (i * BIN_DEGREES) for i in range(BINS)))
            for key, fmt in (('hue_deg', '%+6.2f'), ('sat', '%6.3f'),
                             ('val_b', '%6.3f')):
                print('   %-8s: ' % key
                      + ' '.join(fmt % b[key] for b in m['hue_table']))
        if 'tone_curve' in m:
            pts = m['tone_curve']
            print('   tone curve: '
                  + ' '.join('%.3f->%.3f' % (x, y) for x, y in pts[::16]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('report', 'json'))
    parser.add_argument('image')
    parser.add_argument('out', nargs='?')
    args = parser.parse_args()
    db = read(args.image)
    if args.command == 'report':
        report(db)
    elif args.out:
        with open(args.out, 'w') as handle:
            json.dump(db, handle, indent=1)
        print('wrote %s' % args.out)
    else:
        json.dump(db, sys.stdout, indent=1)


if __name__ == '__main__':
    main()
