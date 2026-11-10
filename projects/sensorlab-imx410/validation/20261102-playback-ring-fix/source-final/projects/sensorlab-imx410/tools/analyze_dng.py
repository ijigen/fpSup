#!/usr/bin/env python3
"""Inspect a local DNG or a byte-zero prefix; never contacts a camera.

JSON includes each IFD, the selected CFA raster, and exact decoded coverage.
Only complete, byte-aligned TIFF rows are decoded. Packed samples are MSB first,
independently of TIFF metadata byte order. A complete raster is not proof that
the original file, recording, or clip is complete.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

import numpy as np


TAGS = {
    254: 'NewSubfileType', 256: 'ImageWidth', 257: 'ImageLength',
    258: 'BitsPerSample', 259: 'Compression', 262: 'PhotometricInterpretation',
    266: 'FillOrder', 271: 'Make', 272: 'Model', 273: 'StripOffsets',
    274: 'Orientation', 277: 'SamplesPerPixel', 278: 'RowsPerStrip',
    279: 'StripByteCounts', 284: 'PlanarConfiguration', 322: 'TileWidth',
    323: 'TileLength', 324: 'TileOffsets', 325: 'TileByteCounts', 330: 'SubIFDs',
    33421: 'CFARepeatPatternDim', 33422: 'CFAPattern',
    33434: 'ExposureTime', 33437: 'FNumber', 34665: 'ExifIFD',
    34855: 'ISOSpeedRatings', 37386: 'FocalLength',
    50706: 'DNGVersion', 50710: 'CFAPlaneColor', 50711: 'CFALayout',
    50713: 'BlackLevelRepeatDim', 50714: 'BlackLevel',
    50715: 'BlackLevelDeltaH', 50716: 'BlackLevelDeltaV', 50717: 'WhiteLevel',
    50718: 'DefaultScale', 50719: 'DefaultCropOrigin', 50720: 'DefaultCropSize',
    50721: 'ColorMatrix1', 50722: 'ColorMatrix2', 50728: 'AsShotNeutral',
    50829: 'ActiveArea', 50830: 'MaskedAreas', 51044: 'FrameRate',
}
TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2,
             9: 4, 10: 8, 11: 4, 12: 8, 13: 4}
TYPE_FMT = {1: 'B', 3: 'H', 4: 'I', 6: 'b', 7: 'B', 8: 'h',
            9: 'i', 11: 'f', 12: 'd', 13: 'I'}


class Tiff:
    """Bounded classic TIFF reader, including partially captured directories."""

    def __init__(self, data):
        self.data, self.ifds, self.warnings, self.seen = data, [], [], set()
        if len(data) < 8 or data[:2] not in (b'II', b'MM'):
            raise ValueError('Need a classic TIFF/DNG header starting at file byte zero')
        self.endian = '<' if data[:2] == b'II' else '>'
        if self.u('H', 2) != 42:
            raise ValueError('Only classic TIFF (magic 42), not BigTIFF, is supported')
        self.read_ifd(self.u('I', 4), 'IFD0')

    def u(self, fmt, offset):
        return struct.unpack_from(self.endian + fmt, self.data, offset)[0]

    def read_ifd(self, offset, name):
        if not offset:
            return
        if offset in self.seen:
            self.warnings.append(f'{name}: repeated/cyclic IFD offset {offset}; not followed')
            return
        if len(self.ifds) >= 64:
            self.warnings.append('IFD traversal limit (64) reached')
            return
        self.seen.add(offset)
        node = {'name': name, 'offset': offset, 'complete': False, 'tags': {}}
        self.ifds.append(node)
        if offset + 2 > len(self.data):
            node['missing'] = 'IFD entry count outside captured bytes'
            return
        count = self.u('H', offset)
        node['entry_count'] = count
        end = offset + 2 + count * 12
        node['directory_required_end'] = end + 4
        available = min(count, max(0, (len(self.data) - offset - 2) // 12))
        node['entries_available'] = available
        for i in range(available):
            entry = offset + 2 + i * 12
            tag, typ, n = struct.unpack_from(self.endian + 'HHI', self.data, entry)
            if tag not in TAGS:
                continue
            item = {'id': tag, 'type': typ, 'count': n}
            node['tags'][TAGS[tag]] = item
            if typ not in TYPE_SIZE:
                item['status'] = 'unsupported_type'
                continue
            size = TYPE_SIZE[typ] * n
            start = entry + 8 if size <= 4 else self.u('I', entry + 8)
            item.update(offset=start, byte_count=size, required_end=start + size)
            if start + size > len(self.data):
                item['status'] = 'outside_capture'
                continue
            # Protect against adversarial counts, even in a very large local file.
            if n > 1_000_000:
                item['status'] = 'count_limit'
                continue
            raw = self.data[start:start + size]
            item['status'] = 'ok'
            if typ == 2:
                item['value'] = raw.rstrip(b'\0').decode('utf-8', errors='replace')
            elif typ in (5, 10):
                fmt = 'II' if typ == 5 else 'ii'
                pairs = [list(p) for p in struct.iter_unpack(self.endian + fmt, raw)]
                item['rationals'] = pairs
                item['value'] = [a / b if b else None for a, b in pairs]
            else:
                values = list(struct.unpack(self.endian + str(n) + TYPE_FMT[typ], raw))
                item['value'] = [v if not isinstance(v, float) or math.isfinite(v) else None
                                 for v in values]
        node['complete'] = end + 4 <= len(self.data)
        if node['complete']:
            node['next_ifd'] = self.u('I', end)
        for tag, label in (('SubIFDs', 'SubIFD'), ('ExifIFD', 'Exif')):
            for i, child in enumerate(value(node, tag) or []):
                if isinstance(child, int):
                    self.read_ifd(child, f'{name}/{label}[{i}]')
        if node.get('next_ifd'):
            self.read_ifd(node['next_ifd'], f'{name}/Next')


def value(ifd, tag, default=None):
    item = ifd.get('tags', {}).get(tag, {})
    return item.get('value', default) if item.get('status') == 'ok' else default


def first(ifd, tag, default=None):
    v = value(ifd, tag)
    return v[0] if isinstance(v, list) and v else default


def choose_raster(ifds):
    candidates = [i for i in ifds if first(i, 'ImageWidth', 0) > 0
                  and first(i, 'ImageLength', 0) > 0 and '/Exif[' not in i['name']]
    # Prefer the CFA image even if a larger JPEG preview is present.
    return max(candidates, key=lambda i: (first(i, 'PhotometricInterpretation') == 32803,
                                         first(i, 'ImageWidth') * first(i, 'ImageLength')),
               default=None)


def unpack_msb_rows(raw, width, bits, rows):
    """TIFF rows are independently byte aligned; unused low bits are not pixels."""
    row_bytes = (width * bits + 7) // 8
    b = np.frombuffer(raw, dtype=np.uint8).reshape(rows, row_bytes)
    group_pixels, group_bytes = (2, 3) if bits == 12 else (4, 7)
    groups = (width + group_pixels - 1) // group_pixels
    padded_bytes = groups * group_bytes
    if padded_bytes != row_bytes:
        b = np.pad(b, ((0, 0), (0, padded_bytes - row_bytes)))
    b = b.reshape(rows, groups, group_bytes).astype(np.uint16)
    out = np.empty((rows, groups, group_pixels), dtype=np.uint16)
    if bits == 12:
        out[:, :, 0] = (b[:, :, 0] << 4) | (b[:, :, 1] >> 4)
        out[:, :, 1] = ((b[:, :, 1] & 15) << 8) | b[:, :, 2]
    else:
        out[:, :, 0] = (b[:, :, 0] << 6) | (b[:, :, 1] >> 2)
        out[:, :, 1] = ((b[:, :, 1] & 3) << 12) | (b[:, :, 2] << 4) | (b[:, :, 3] >> 4)
        out[:, :, 2] = ((b[:, :, 3] & 15) << 10) | (b[:, :, 4] << 2) | (b[:, :, 5] >> 6)
        out[:, :, 3] = ((b[:, :, 5] & 63) << 8) | b[:, :, 6]
    return out.reshape(rows, groups * group_pixels)[:, :width]


def stats(arrays):
    count = sum(a.size for a in arrays)
    if not count:
        return {'pixel_count': 0, 'mean': None, 'min': None, 'max': None,
                'low2_histogram': [0, 0, 0, 0]}
    hist = sum((np.bincount((a.ravel() & 3), minlength=4) for a in arrays), np.zeros(4, dtype=np.int64))
    return {'pixel_count': int(count), 'mean': sum(int(a.sum(dtype=np.uint64)) for a in arrays) / count,
            'min': min(int(a.min()) for a in arrays), 'max': max(int(a.max()) for a in arrays),
            'low2_histogram': [int(x) for x in hist],
            'low2_fraction': [int(x) / count for x in hist]}


def region_stats(blocks, rect, width, height, label):
    top, left, bottom, right = rect
    if not (0 <= top <= bottom <= height and 0 <= left <= right <= width):
        return {'label': label, 'rect': rect, 'error': 'rectangle outside raster'}
    selected = []
    for y, a in blocks:
        lo, hi = max(top, y), min(bottom, y + len(a))
        if hi > lo and right > left:
            selected.append(a[lo - y:hi - y, left:right])
    result = {'label': label, 'rect': rect, 'expected_pixel_count': (bottom - top) * (right - left),
              **stats(selected)}
    result['region_complete'] = result['pixel_count'] == result['expected_pixel_count']
    return result


def decode_pixels(data, raw, rows_summary=8, ob_rects=()):
    w, h = first(raw, 'ImageWidth'), first(raw, 'ImageLength')
    bits, compression = value(raw, 'BitsPerSample'), first(raw, 'Compression')
    report = {'status': 'metadata_only', 'pixel_data_complete': False,
              'scope': 'Selected raster only; no claim of whole-file or clip completeness'}
    blocks = []
    if compression != 1:
        report['reason'] = f'Compression {compression} is not uncompressed (1)'
        return report, blocks
    if not bits or len(set(bits)) != 1 or bits[0] not in (12, 14):
        report['reason'] = 'Only packed 12/14-bit pixels are decoded'
        return report, blocks
    if first(raw, 'SamplesPerPixel', 1) != 1 or first(raw, 'FillOrder', 1) != 1:
        report['reason'] = 'Only one sample per pixel and MSB-first FillOrder 1 are supported'
        return report, blocks
    offsets, counts = value(raw, 'StripOffsets'), value(raw, 'StripByteCounts')
    if not offsets or not counts or len(offsets) != len(counts):
        report['reason'] = 'Complete matching StripOffsets/StripByteCounts required; tiles unsupported'
        return report, blocks
    if any(not isinstance(x, int) or x < 0 for x in offsets + counts):
        report['reason'] = 'Strip offsets/counts must be nonnegative integers'
        return report, blocks
    rps = min(first(raw, 'RowsPerStrip', h), h)
    if not isinstance(rps, int) or rps <= 0 or not isinstance(w, int) or not isinstance(h, int):
        report['reason'] = 'Invalid raster or RowsPerStrip'
        return report, blocks
    nstrips = (h + rps - 1) // rps
    if len(offsets) != nstrips:
        report['reason'] = f'Expected {nstrips} strips from geometry, found {len(offsets)}'
        return report, blocks
    bits = bits[0]
    row_bytes = (w * bits + 7) // 8
    report.update(status='decoded', packing='MSB-first, independently byte-aligned TIFF rows',
                  row_bytes=row_bytes, expected_rows=h, expected_pixel_count=w * h,
                  rows_per_strip=rps, strips=[], row_ranges=[], first_rows=[])
    for i, (off, declared) in enumerate(zip(offsets, counts)):
        y, wanted_rows = i * rps, min(rps, h - i * rps)
        expected_bytes = wanted_rows * row_bytes
        available = min(declared, max(0, len(data) - off))
        pixel_bytes = min(available, expected_bytes)
        full_rows = pixel_bytes // row_bytes
        strip = {'index': i, 'offset': off, 'declared_bytes': declared,
                 'available_bytes': available, 'declared_bytes_missing': declared - available,
                 'expected_raster_bytes': expected_bytes,
                 'declared_surplus_bytes': max(0, declared - expected_bytes),
                 'declared_raster_shortfall': max(0, expected_bytes - declared),
                 'first_row': y, 'expected_rows': wanted_rows, 'decoded_rows': full_rows,
                 'partial_next_row_bytes': pixel_bytes % row_bytes}
        report['strips'].append(strip)
        if full_rows:
            report['row_ranges'].append([y, y + full_rows])  # half-open raster coordinates
        for start in range(0, full_rows, 256):
            n = min(256, full_rows - start)
            a = unpack_msb_rows(data[off + start * row_bytes:off + (start + n) * row_bytes], w, bits, n)
            blocks.append((y + start, a))
            for j in range(min(n, max(0, rows_summary - len(report['first_rows'])))):
                report['first_rows'].append({'row': y + start + j, **stats([a[j]])})
    report.update(stats([a for _, a in blocks]))
    report['decoded_rows'] = sum(len(a) for _, a in blocks)
    report['pixel_data_complete'] = report['decoded_rows'] == h
    report['declared_strip_bytes_complete'] = all(s['declared_bytes_missing'] == 0 for s in report['strips'])
    report['pixel_fraction'] = report['pixel_count'] / (w * h)
    report['partial_row_pixels_decoded'] = 0
    raster_end = max(s['offset'] + s['expected_raster_bytes'] for s in report['strips'])
    declared_end = max(s['offset'] + s['declared_bytes'] for s in report['strips'])
    report['capture_requirements'] = {
        'raster_required_prefix_bytes': raster_end,
        'additional_prefix_bytes_for_raster': max(0, raster_end - len(data)),
        'declared_strips_required_prefix_bytes': declared_end,
        'additional_prefix_bytes_for_declared_strips': max(0, declared_end - len(data)),
        'declared_counts_cover_raster': all(s['declared_raster_shortfall'] == 0 for s in report['strips']),
        'note': 'Prefix sizes are from file byte zero; a too-small declared byte count is not fixed by a longer capture',
    }
    for s in report['strips']:
        if s['decoded_rows'] < s['expected_rows']:
            next_end = s['offset'] + (s['decoded_rows'] + 1) * row_bytes
            report['capture_requirements'].update(
                next_missing_raster_row=s['first_row'] + s['decoded_rows'],
                next_complete_row_required_prefix_bytes=next_end,
                additional_prefix_bytes_for_next_row=max(0, next_end - len(data)))
            break
    regions = []
    masked = value(raw, 'MaskedAreas') or []
    if len(masked) % 4:
        report['masked_area_error'] = 'MaskedAreas count is not a multiple of four'
    else:
        for i in range(0, len(masked), 4):
            regions.append(region_stats(blocks, masked[i:i + 4], w, h, f'MaskedAreas[{i // 4}]'))
    for i, rect in enumerate(ob_rects):
        regions.append(region_stats(blocks, list(rect), w, h, f'user-specified OB[{i}]'))
    report['optical_black_regions'] = regions
    report['optical_black_note'] = ('Only MaskedAreas or explicitly supplied rectangles are called OB; '
                                    'crop margins alone do not identify optical black')
    active = value(raw, 'ActiveArea')
    if active and len(active) == 4:
        report['active_area_stats'] = region_stats(blocks, active, w, h, 'ActiveArea')
    report['edge_diagnostics'] = [
        region_stats(blocks, [0, 0, h, min(16, w)], w, h, 'left 16 columns; not assumed OB'),
        region_stats(blocks, [0, max(0, w - 16), h, w], w, h, 'right 16 columns; not assumed OB'),
    ]
    return report, blocks


def make_preview(blocks, raw, metadata, target):
    """Sensor-RGB diagnostic: RGGB 2x2 mean greens, metadata black/white/WB."""
    from PIL import Image
    if value(raw, 'CFARepeatPatternDim') != [2, 2] or value(raw, 'CFAPattern') != [0, 1, 1, 2]:
        raise ValueError('Preview requires declared RGGB 2x2 CFA (0,1,1,2)')
    if value(raw, 'CFAPlaneColor', [0, 1, 2]) != [0, 1, 2] or first(raw, 'CFALayout', 1) != 1:
        raise ValueError('Preview requires rectangular RGB CFA planes')
    black = metadata.get('black_level')
    repeat = metadata.get('black_level_repeat_dim') or [1, 1]
    white, neutral = metadata.get('white_level'), metadata.get('as_shot_neutral')
    if not black or not white or not neutral or len(neutral) != 3:
        raise ValueError('Preview requires BlackLevel, WhiteLevel and AsShotNeutral metadata')
    if any(x is None or x <= 0 for x in neutral) or len(white) != 1:
        raise ValueError('Preview requires finite positive WB and scalar WhiteLevel')
    if value(raw, 'BlackLevelDeltaH') or value(raw, 'BlackLevelDeltaV'):
        raise ValueError('Preview with BlackLevelDeltaH/V is not implemented')
    if repeat == [1, 1] and len(black) == 1:
        black = np.full((2, 2), black[0], dtype=np.float32)
    elif repeat == [2, 2] and len(black) == 4:
        black = np.array(black, dtype=np.float32).reshape(2, 2)
    else:
        raise ValueError('Preview supports scalar or 2x2 BlackLevel only')
    if np.any(~np.isfinite(black)) or np.any(white[0] <= black):
        raise ValueError('Invalid BlackLevel/WhiteLevel')
    # Stop at the first missing row. Never synthesize missing pixels or join gaps.
    prefix, end = [], 0
    for y, a in blocks:
        if y != end:
            break
        prefix.append(a)
        end += len(a)
    if end < 2:
        raise ValueError('Preview requires at least two contiguous rows from raster row zero')
    a = np.concatenate(prefix).astype(np.float32)
    hh, ww = len(a) // 2, a.shape[1] // 2
    # BlackLevelRepeatDim is relative to ActiveArea, not necessarily raster (0,0).
    active = metadata.get('active_area') or [0, 0, len(a), a.shape[1]]
    planes = []
    for dy, dx in ((0, 0), (0, 1), (1, 0), (1, 1)):
        bl = black[(dy - active[0]) % 2, (dx - active[1]) % 2]
        planes.append(np.maximum(a[dy:hh * 2:2, dx:ww * 2:2] - bl, 0) / (white[0] - bl))
    rgb = np.stack((planes[0], (planes[1] + planes[2]) / 2, planes[3]), axis=-1)
    wb = np.asarray(neutral[1] / np.asarray(neutral), dtype=np.float32)
    rgb *= wb
    # A declared display transform, not a claim to camera-matched color science.
    peak = float(np.percentile(rgb, 99.5))
    exposure = 0.9 / peak if peak > 0 else 1.0
    pixels = np.uint8(np.clip(rgb * exposure, 0, 1) ** (1 / 2.2) * 255 + 0.5)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels).save(target)
    return {'path': str(target.resolve()), 'width': ww, 'height': hh,
            'source_row_range': [0, hh * 2], 'source_column_range': [0, ww * 2],
            'partial_raster': hh * 2 != first(raw, 'ImageLength'),
            'white_balance_gains': wb.tolist(), 'exposure_gain': exposure, 'gamma': 2.2,
            'method': 'RGGB 2x2 sensor RGB; mean greens; metadata black/white/WB; p99.5 to 0.9',
            'limitations': 'Diagnostic color only: no ColorMatrix transform, crop, DefaultScale or orientation applied'}


def analyze(data, source=None, source_size=None, rows_summary=8, ob_rects=(), preview=None):
    t = Tiff(data)
    raw = choose_raster(t.ifds)
    report = {'schema': 'sensorlab-dng-analysis-v1', 'source': source,
              'input': {'captured_bytes': len(data), 'local_source_bytes': source_size,
                        'read_is_local_file_prefix': source_size is not None and len(data) < source_size,
                        'sha256_of_captured_bytes': hashlib.sha256(data).hexdigest(),
                        'original_file_completeness': 'not inferred from local file length'},
              'tiff_byte_order': 'little' if t.endian == '<' else 'big',
              'ifds': t.ifds, 'warnings': t.warnings, 'selected_ifd': raw['name'] if raw else None}
    required = max([8] + [i.get('directory_required_end', i['offset'] + 2) for i in t.ifds]
                   + [tag['required_end'] for i in t.ifds for tag in i['tags'].values()
                      if 'required_end' in tag])
    report['input']['known_metadata_required_prefix_bytes'] = required
    report['input']['additional_prefix_bytes_for_known_metadata'] = max(0, required - len(data))
    if not raw:
        report['pixels'] = {'status': 'metadata_only', 'reason': 'No captured raster dimensions',
                            'pixel_data_complete': False}
        return report
    root = t.ifds[0]
    def meta(tag):
        # Raw-specific geometry is never borrowed from a thumbnail.
        own = value(raw, tag)
        return own if own is not None else value(root, tag)
    fields = {'raster': [first(raw, 'ImageWidth'), first(raw, 'ImageLength')],
              'bits_per_sample': value(raw, 'BitsPerSample'),
              'compression': first(raw, 'Compression'),
              'photometric_interpretation': first(raw, 'PhotometricInterpretation'),
              'active_area': value(raw, 'ActiveArea'),
              'default_crop_origin': value(raw, 'DefaultCropOrigin'),
              'default_crop_size': value(raw, 'DefaultCropSize'),
              'default_scale': value(raw, 'DefaultScale'),
              'black_level': value(raw, 'BlackLevel'),
              'black_level_repeat_dim': value(raw, 'BlackLevelRepeatDim'),
              'white_level': value(raw, 'WhiteLevel'),
              'as_shot_neutral': meta('AsShotNeutral'),
              'frame_rate': meta('FrameRate'),
              'strip_offsets': value(raw, 'StripOffsets'),
              'strip_byte_counts': value(raw, 'StripByteCounts'),
              'rows_per_strip': value(raw, 'RowsPerStrip'),
              'masked_areas': value(raw, 'MaskedAreas'),
              'cfa_repeat_dim': value(raw, 'CFARepeatPatternDim'),
              'cfa_pattern': value(raw, 'CFAPattern')}
    report['metadata'] = fields
    exif = {}
    for ifd in t.ifds:
        for tag in ('ExposureTime', 'FNumber', 'ISOSpeedRatings', 'FocalLength'):
            v = value(ifd, tag)
            if v is not None:
                exif[tag] = v
    report['exif'] = exif
    report['pixels'], blocks = decode_pixels(data, raw, rows_summary, ob_rects)
    if preview:
        try:
            report['preview'] = make_preview(blocks, raw, fields, preview)
        except (ValueError, ImportError) as exc:
            report['preview'] = {'error': str(exc)}
    return report


def rectangle(text):
    try:
        rect = tuple(int(x, 0) for x in text.split(','))
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Use top,left,bottom,right integers') from exc
    if len(rect) != 4:
        raise argparse.ArgumentTypeError('Use top,left,bottom,right integers')
    return rect


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input', type=Path, help='Local DNG or capture starting at its byte zero')
    ap.add_argument('--limit-bytes', type=lambda x: int(x, 0), default=0,
                    help='Read at most this many bytes (e.g. 2097152); default entire local file')
    ap.add_argument('--out', type=Path, help='Write JSON here instead of stdout')
    ap.add_argument('--rows-summary', type=int, default=8)
    ap.add_argument('--ob-rect', type=rectangle, action='append', default=[],
                    help='Explicit optical-black rectangle top,left,bottom,right; repeatable')
    ap.add_argument('--preview', type=Path, help='Optional metadata-driven RGGB half-resolution PNG')
    args = ap.parse_args(argv)
    if args.limit_bytes < 0 or args.rows_summary < 0:
        ap.error('Limits must be nonnegative')
    try:
        with args.input.open('rb') as f:
            data = f.read(args.limit_bytes or -1)
        report = analyze(data, str(args.input.resolve()), args.input.stat().st_size,
                         args.rows_summary, args.ob_rect, args.preview)
        output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(output)
        else:
            print(output, end='')
        return 0
    except (OSError, ValueError, struct.error) as exc:
        print(f'analyze_dng: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
