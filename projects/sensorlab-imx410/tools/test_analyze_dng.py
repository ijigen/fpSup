"""Offline tests; fixture bytes are generated independently of the decoder."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

SPEC = importlib.util.spec_from_file_location('analyze_dng', Path(__file__).with_name('analyze_dng.py'))
dng = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dng)


def pack_rows(rows, bits):
    out = bytearray()
    for row in rows:
        text = ''.join(format(int(v), f'0{bits}b') for v in row)
        text += '0' * (-len(text) % 8)
        out.extend(int(text[i:i + 8], 2) for i in range(0, len(text), 8))
    return bytes(out)


class Builder:
    def __init__(self, endian='<'):
        self.endian, self.data, self.cursor = endian, bytearray(1024), 1024
        self.write(0, (b'II' if endian == '<' else b'MM') + struct.pack(endian + 'HI', 42, 8))

    def write(self, off, data):
        self.data.extend(b'\0' * max(0, off + len(data) - len(self.data)))
        self.data[off:off + len(data)] = data

    def ifd(self, offset, tags, next_ifd=0):
        self.write(offset, struct.pack(self.endian + 'H', len(tags)))
        for i, (tag, (typ, values)) in enumerate(sorted(tags.items())):
            if typ in (5, 10):
                raw = b''.join(struct.pack(self.endian + ('II' if typ == 5 else 'ii'), *p) for p in values)
            else:
                raw = struct.pack(self.endian + str(len(values)) + dng.TYPE_FMT[typ], *values)
            inline = raw.ljust(4, b'\0') if len(raw) <= 4 else struct.pack(self.endian + 'I', self.cursor)
            if len(raw) > 4:
                self.write(self.cursor, raw)
                self.cursor += len(raw)
            self.write(offset + 2 + i * 12, struct.pack(self.endian + 'HHI', tag, typ, len(values)) + inline)
        self.write(offset + 2 + 12 * len(tags), struct.pack(self.endian + 'I', next_ifd))


def fixture(bits=14, width=7, height=6, endian='<', subifd=False, strips=1,
            masked=False, wb=True, compression=1, short_count=0, cycle=False):
    px = (np.arange(width * height, dtype=np.uint16).reshape(height, width) + 1001) % (1 << bits)
    b = Builder(endian)
    rps = (height + strips - 1) // strips
    offsets, counts = [], []
    for i in range(strips):
        payload = pack_rows(px[i * rps:min(height, (i + 1) * rps)], bits)
        off = 2048 + 4096 * i
        b.write(off, payload)
        offsets.append(off)
        counts.append(len(payload) - short_count)
    tags = {256: (4, [width]), 257: (4, [height]), 258: (3, [bits]), 259: (3, [compression]),
            262: (3, [32803]), 273: (4, offsets), 277: (3, [1]), 278: (4, [rps]),
            279: (4, counts), 33421: (3, [2, 2]), 33422: (1, [0, 1, 1, 2]),
            50713: (3, [2, 2]), 50714: (5, [(10, 1), (20, 1), (30, 1), (40, 1)]),
            50717: (4, [(1 << bits) - 1]), 50718: (5, [(3, 2), (1, 1)]),
            50719: (4, [1, 2]), 50720: (4, [width - 2, height - 2]),
            50829: (4, [0, 0, height, width]), 51044: (10, [(30000, 1001)])}
    if masked:
        tags[50830] = (4, [0, 0, height, 1])
    if wb:
        tags[50728] = (5, [(1, 2), (1, 1), (2, 3)])
    if subifd:
        b.ifd(8, {256: (4, [160]), 257: (4, [120]), 259: (3, [7]), 262: (3, [2]),
                  330: (4, [512]), 34665: (4, [900]), 50728: tags.pop(50728)})
        b.ifd(512, tags)
        b.ifd(900, {33434: (5, [(1, 125)]), 34855: (3, [640])})
    else:
        b.ifd(8, tags, 8 if cycle else 0)
    return bytes(b.data), px


class AnalyzeDngTests(unittest.TestCase):
    def test_all_low_bits_and_non_group_aligned_rows(self):
        for bits in (12, 14):
            for width in (1, 2, 3, 4, 5, 7, 8, 16):
                px = np.array([[0, 1, 2, 3, (1 << bits) - 1, 1001, 1002, 1003] * 2,
                               [(1 << bits) - 1] * 16], dtype=np.uint16)[:, :width]
                got = dng.unpack_msb_rows(pack_rows(px, bits), width, bits, 2)
                np.testing.assert_array_equal(got, px)

    def test_subifd_exif_and_big_endian(self):
        for endian in ('<', '>'):
            data, px = fixture(endian=endian, subifd=True)
            r = dng.analyze(data)
            self.assertEqual(r['selected_ifd'], 'IFD0/SubIFD[0]')
            self.assertEqual(r['metadata']['raster'], [7, 6])
            self.assertEqual(r['metadata']['default_scale'], [1.5, 1])
            self.assertEqual(r['metadata']['as_shot_neutral'], [0.5, 1, 2 / 3])
            self.assertEqual(r['exif']['ISOSpeedRatings'], [640])
            self.assertEqual(r['exif']['ExposureTime'], [1 / 125])
            self.assertEqual(r['metadata']['frame_rate'], [30000 / 1001])
            self.assertEqual(r['pixels']['low2_histogram'], np.bincount(px.ravel() & 3, minlength=4).tolist())

    def test_prefix_counts_and_next_needed_byte(self):
        data, px = fixture(bits=12, width=5, height=6, masked=True)
        rb = 8
        cut = 2048 + 3 * rb + 2
        r = dng.analyze(data[:cut], source_size=len(data))
        p = r['pixels']
        self.assertFalse(p['pixel_data_complete'])
        self.assertEqual(p['decoded_rows'], 3)
        self.assertEqual(p['pixel_count'], 15)
        self.assertEqual(p['strips'][0]['partial_next_row_bytes'], 2)
        self.assertEqual(p['capture_requirements']['raster_required_prefix_bytes'], 2048 + 6 * rb)
        self.assertEqual(p['capture_requirements']['additional_prefix_bytes_for_next_row'], 6)
        self.assertEqual(p['capture_requirements']['next_missing_raster_row'], 3)
        self.assertEqual(p['optical_black_regions'][0]['pixel_count'], 3)
        self.assertFalse(p['optical_black_regions'][0]['region_complete'])
        self.assertEqual(p['mean'], float(px[:3].mean()))

    def test_multistrip_gap_and_final_partial(self):
        data, px = fixture(width=7, height=6, strips=2)
        r = dng.analyze(data[:-4])['pixels']
        self.assertEqual(r['row_ranges'], [[0, 3], [3, 5]])
        self.assertEqual(r['decoded_rows'], 5)
        self.assertEqual(r['mean'], float(px[:5].mean()))
        self.assertFalse(r['declared_strip_bytes_complete'])
        self.assertTrue(dng.analyze(data)['pixels']['pixel_data_complete'])

    def test_declared_shortfall_not_fixed_by_more_bytes(self):
        data, _ = fixture(short_count=1)
        r = dng.analyze(data)['pixels']
        self.assertFalse(r['pixel_data_complete'])
        self.assertFalse(r['capture_requirements']['declared_counts_cover_raster'])
        self.assertEqual(r['capture_requirements']['additional_prefix_bytes_for_raster'], 0)
        self.assertEqual(r['strips'][0]['declared_raster_shortfall'], 1)

    def test_truncated_tag_and_ifd_and_cycle(self):
        data, _ = fixture(cycle=True)
        r = dng.analyze(data[:1030])
        self.assertTrue(r['warnings'])
        self.assertEqual(r['ifds'][0]['tags']['BlackLevel']['status'], 'outside_capture')
        self.assertGreater(r['input']['additional_prefix_bytes_for_known_metadata'], 0)
        r = dng.analyze(data[:35])
        self.assertFalse(r['ifds'][0]['complete'])
        self.assertGreater(r['input']['additional_prefix_bytes_for_known_metadata'], 0)
        for bad in (b'II*', b'not a TIFF header', b'II+\0\x08\0\0\0'):
            with self.assertRaises(ValueError):
                dng.analyze(bad)

    def test_compressed_only_metadata(self):
        data, _ = fixture(compression=7)
        r = dng.analyze(data)
        self.assertEqual(r['pixels']['status'], 'metadata_only')
        self.assertNotIn('pixel_count', r['pixels'])
        self.assertFalse(r['pixels']['pixel_data_complete'])

    def test_preview_metadata_driven_and_partial(self):
        with tempfile.TemporaryDirectory() as td:
            data, _ = fixture(width=8, height=6)
            p = Path(td) / 'preview.png'
            r = dng.analyze(data[:2048 + 14 * 3], preview=p)
            self.assertTrue(p.exists())
            self.assertEqual((r['preview']['width'], r['preview']['height']), (4, 1))
            self.assertTrue(r['preview']['partial_raster'])
            self.assertEqual(r['preview']['white_balance_gains'], [2, 1, 1.5])
            data, _ = fixture(wb=False)
            r = dng.analyze(data, preview=Path(td) / 'must-not-exist.png')
            self.assertIn('requires BlackLevel', r['preview']['error'])
            self.assertFalse((Path(td) / 'must-not-exist.png').exists())

    def test_cli_local_file_limit_and_output(self):
        with tempfile.TemporaryDirectory() as td:
            data, _ = fixture()
            source, report = Path(td) / 'x.dng', Path(td) / 'report.json'
            source.write_bytes(data)
            self.assertEqual(dng.main([str(source), '--limit-bytes', '2090', '--out', str(report)]), 0)
            import json
            r = json.loads(report.read_text())
            self.assertEqual(r['input']['captured_bytes'], 2090)
            self.assertTrue(r['input']['read_is_local_file_prefix'])
            self.assertFalse(r['pixels']['pixel_data_complete'])


if __name__ == '__main__':
    unittest.main()
