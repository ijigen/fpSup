import base64
import struct
import unittest
import tempfile
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
import io
import zlib
import xml.etree.ElementTree as ET

import numpy as np

from cube import Cube
from dng import Dng, LUT_NS, RDF_NS, RGB_TABLES, XMP, rgb_tables, settings, xmp_packet, extract_xmp
from fplut import exclusive_write, main


def make_cube(n=2, fn=lambda r, g, b: (r, g, b), headers=''):
    rows = [f'{x:.12g} {y:.12g} {z:.12g}'
            for b in np.linspace(0, 1, n) for g in np.linspace(0, 1, n)
            for r in np.linspace(0, 1, n) for x, y, z in [fn(r, g, b)]]
    return (headers + f'LUT_3D_SIZE {n}\n' + '\n'.join(rows) + '\n').encode()


def fixture(bo='<', subifd=False):
    """Two strips, opaque MakerNote/EXIF pointer and unmodified calibration tags."""
    image = bytes(range(16))
    data = bytearray((b'II' if bo == '<' else b'MM') + struct.pack(bo + 'HI', 42, 8))
    def append_ifd(entries):
        at = len(data)
        data.extend(struct.pack(bo + 'H', len(entries)))
        for tag, kind, count, value in sorted(entries):
            data.extend(struct.pack(bo + 'HHI', tag, kind, count) + value)
        data.extend(struct.pack(bo + 'I', 0))
        return at
    raw_entries = [(256, 4, 1, struct.pack(bo + 'I', 4)),
                   (257, 4, 1, struct.pack(bo + 'I', 2)),
                   (273, 4, 2, b'\0' * 4), (279, 4, 2, b'\0' * 4)]
    root_entries = [(50706, 1, 4, bytes((1, 4, 0, 0))),
                    (50721, 10, 9, b'\0' * 4), (50722, 10, 9, b'\0' * 4),
                    (50728, 5, 3, b'\0' * 4), (34665, 4, 1, b'\0' * 4)]
    if subifd:
        root_entries.append((330, 4, 1, b'\0' * 4))
    else:
        root_entries.extend(raw_entries)
    root_at = append_ifd(root_entries)
    raw_at = append_ifd(raw_entries) if subifd else root_at
    exif_at = append_ifd([(37500, 7, 12, b'\0' * 4)])
    def patch_ifd(ifd_at, tag, pointer):
        count = struct.unpack_from(bo + 'H', data, ifd_at)[0]
        for i in range(count):
            at = ifd_at + 2 + 12 * i
            if struct.unpack_from(bo + 'H', data, at)[0] == tag:
                struct.pack_into(bo + 'I', data, at + 8, pointer)
                return
        raise AssertionError(tag)
    for tag, payload in [(50721, bytes(range(72))), (50722, bytes(reversed(range(72)))),
                         (50728, bytes(range(24)))]:
        patch_ifd(root_at, tag, len(data))
        data.extend(payload)
    patch_ifd(root_at, 34665, exif_at)
    patch_ifd(exif_at, 37500, len(data))
    data.extend(b'opaque-note!')  # 12 bytes; relative/vendor offsets are never rewritten.
    if subifd:
        patch_ifd(root_at, 330, raw_at)
    patch_ifd(raw_at, 273, len(data))
    start = len(data) + 16
    data.extend(struct.pack(bo + 'II', start, start + 8))
    patch_ifd(raw_at, 279, len(data))
    data.extend(struct.pack(bo + 'II', 8, 8))
    data.extend(image)
    return bytes(data)


class CubeTests(unittest.TestCase):
    def test_red_fast_and_all_six_tetrahedra(self):
        cube = Cube.parse(make_cube(fn=lambda r, g, b: (b, r, g)))
        points = np.array([[.1, .4, .7], [.1, .7, .4], [.4, .1, .7],
                           [.4, .7, .1], [.7, .1, .4], [.7, .4, .1],
                           [0, 0, 0], [1, 1, 1], [1, 0, 0]])
        np.testing.assert_allclose(cube.apply(points), points[:, [2, 0, 1]], atol=1e-14)

    def test_tetrahedral_reference_differs_from_trilinear(self):
        # Only the white corner contributes. Tetrahedral weight is min(r,g,b).
        cube = Cube.parse(make_cube(fn=lambda r, g, b: (r*g*b,) * 3))
        points = np.array([[.2, .5, .8], [.8, .2, .5], [.5, .8, .2]])
        np.testing.assert_allclose(cube.apply(points), .2, atol=1e-14)

    def test_domain_per_channel_and_lookup_clamp(self):
        cube = Cube.parse(make_cube(headers='DOMAIN_MIN -1 0 2\nDOMAIN_MAX 1 2 4\n'))
        np.testing.assert_allclose(cube.apply([[0, 1, 3], [10, -1, 1]]), [[.5]*3, [1, 0, 0]])
        np.testing.assert_array_equal(cube.apply([[10, -1, 1]], 0), [[10, -1, 1]])

    def test_shaper_and_combined_resolve_ranges(self):
        source = b'LUT_1D_SIZE 2\nLUT_3D_SIZE 2\nLUT_1D_INPUT_RANGE 0 2\nLUT_3D_INPUT_RANGE 0 1\n0 0 0\n1 1 1\n'
        source += make_cube(fn=lambda r, g, b: (b, r, g)).split(b'\n', 1)[1]
        cube = Cube.parse(source)
        np.testing.assert_allclose(cube.apply([.2, .6, 1.4]), [.7, .1, .3])
        one = Cube.parse(b'LUT_1D_SIZE 2\n0 0 .1\n1 .8 1\n')
        np.testing.assert_allclose(one.apply([.5, .5, .5]), [.5, .4, .55])

    def test_comments_title_strength_and_nodes(self):
        source = make_cube(3, headers='TITLE "Look # 一" # comment\n')
        cube = Cube.parse(b'\xef\xbb\xbf' + source)
        self.assertEqual(cube.title, 'Look # 一')
        np.testing.assert_allclose(cube.apply(np.random.default_rng(2).random((7, 5, 3))),
                                   np.random.default_rng(2).random((7, 5, 3)))
        swap = Cube.parse(make_cube(fn=lambda r, g, b: (b, r, g)))
        np.testing.assert_allclose(swap.apply([.1, .3, .9], .5), [.5, .2, .6])

    def test_invalid_input_is_rejected(self):
        cases = [b'LUT_3D_SIZE 2\n0 0 0', b'LUT_3D_SIZE 1\n',
                 b'LUT_3D_SIZE 2\nDOMAIN_MIN nan 0 0\n',
                 b'LUT_3D_SIZE 2\nFOO_BAR 1 2\n',
                 b'LUT_3D_SIZE 2\nLUT_3D_SIZE 2\n',
                 make_cube(headers='DOMAIN_MAX 0 1 1\n'),
                 make_cube(headers='DOMAIN_MIN -1e308 0 0\nDOMAIN_MAX 1e308 1 1\n'),
                 make_cube(headers='DOMAIN_MIN 0 0 0\nLUT_3D_INPUT_RANGE 0 1\n'),
                 make_cube().replace(b'0 0 0\n', b'nan 0 0\n', 1),
                 make_cube() + b'0 0 0\n']
        for source in cases:
            with self.subTest(source=source[:70]), self.assertRaises(ValueError):
                Cube.parse(source)


class DngTests(unittest.TestCase):
    def setUp(self):
        self.cube = Cube.parse(make_cube(fn=lambda r, g, b: (b, r, g)))
        self.config = settings(self.cube, 'My look', 'srgb', 'srgb')

    def test_embedded_cube_is_exact_and_pixels_tags_preserved(self):
        for bo in ('<', '>'):
            for subifd in (False, True):
                with self.subTest(bo=bo, subifd=subifd):
                    original = Dng(fixture(bo, subifd))
                    output = original.embed(self.cube, self.config)
                    result = Dng(output)
                    self.assertEqual(output[:4], original.data[:4])
                    self.assertEqual(output[8:len(original.data)], original.data[8:])
                    self.assertEqual(result.image_ranges, original.image_ranges)
                    self.assertEqual(result.image_digest(), original.image_digest())
                    for tag in original.root:
                        self.assertEqual(result.root[tag], original.root[tag])
                    self.assertEqual(result.extract()[0].source, self.cube.source)
                    self.assertNotIn(RGB_TABLES, result.root)

    def test_rgbtables_reorders_channels_and_respects_endian(self):
        for bo in ('<', '>'):
            table = rgb_tables(self.cube, self.config, bo, 2)
            self.assertEqual(struct.unpack_from(bo + 'IIH5B', table), (1, 0, 0, 2, 2, 1, 0, 1))
            data = np.frombuffer(table[15:], dtype=bo+'f4').reshape(2, 2, 2, 3)
            # DNG red outer, blue inner: index (0,0,1) is BLUE, mapped to RED.
            np.testing.assert_array_equal(data[0, 0, 1], [1, 0, 0])
            np.testing.assert_array_equal(data[1, 0, 0], [0, 1, 0])
            original = Dng(fixture(bo))
            result = Dng(original.embed(self.cube, self.config, True, 2))
            self.assertEqual(result.root[RGB_TABLES].data, table)
            self.assertEqual(result.root[50706].data, bytes((1, 6, 0, 0)))
            self.assertEqual(result.image_digest(), original.image_digest())
            self.assertLess(result.extract()[1]['rgbtables_resampling_error']['max'], 1e-7)

    def test_resampling_reports_loss_and_keeps_original(self):
        cube = Cube.parse(make_cube(33, fn=lambda r, g, b: (r*r, g, b)))
        result = Dng(Dng(fixture()).embed(cube, settings(cube, 'curve', 'srgb', 'srgb'), True))
        recovered, config = result.extract()
        self.assertEqual(recovered.source, cube.source)
        self.assertGreater(config['rgbtables_resampling_error']['max'], 1e-5)
        self.assertEqual(config['rgbtables_divisions'], 32)

    def test_reembedding_keeps_other_xmp_and_exact_source(self):
        packet = f'<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="{RDF_NS}" xmlns:t="urn:test"><rdf:RDF><rdf:Description t:Copyright="保留"/></rdf:RDF></x:xmpmeta>'.encode()
        one = xmp_packet(packet, self.cube, self.config)
        two = xmp_packet(one, self.cube, self.config)
        root = ET.fromstring(two)
        self.assertEqual(len(root.findall(f'.//{{{LUT_NS}}}Settings')), 1)
        self.assertEqual(root.find(f'.//{{{RDF_NS}}}Description').get('{urn:test}Copyright'), '保留')
        self.assertEqual(extract_xmp(two)[0].source, self.cube.source)

    def test_no_silent_color_space_or_overrange_conversion(self):
        for conf in (settings(self.cube, 'a', 'v-log', 'srgb'),
                     settings(self.cube, 'a', 'srgb', '709-gamma22')):
            with self.assertRaises(ValueError):
                rgb_tables(self.cube, conf)
            Dng(fixture()).embed(self.cube, conf)  # Full source can still be archived.
        over = Cube.parse(make_cube(fn=lambda r, g, b: (r + .1, g, b)))
        conf = settings(over, 'over', 'srgb', 'srgb')
        with self.assertRaises(ValueError):
            rgb_tables(over, conf)
        self.assertEqual(Dng(Dng(fixture()).embed(over, conf)).extract()[0].source, over.source)

    def test_existing_render_table_is_not_overwritten(self):
        old = Dng(Dng(fixture()).embed(self.cube, self.config, True, 2))
        with self.assertRaises(ValueError):
            old.embed(self.cube, self.config)

    def test_bad_tiff_and_tampered_cube_are_rejected(self):
        for source in (b'garbage', b'II'+struct.pack('<HI', 43, 8), fixture()[:-1]):
            with self.assertRaises(ValueError):
                Dng(source)
        packet = xmp_packet(None, self.cube, self.config)
        root = ET.fromstring(packet)
        root.find(f'.//{{{LUT_NS}}}CubeZlibBase64').text = base64.b64encode(b'invalid').decode()
        with self.assertRaises(zlib.error):
            extract_xmp(ET.tostring(root))

    def test_corrupt_settings_are_rejected(self):
        import json
        packet = xmp_packet(None, self.cube, self.config)
        for config in ([], None, dict(self.config, strength='1'),
                       dict(self.config, strength=2), dict(self.config, cube={}),
                       dict(self.config, interpolation='trilinear')):
            root = ET.fromstring(packet)
            root.find(f'.//{{{LUT_NS}}}Settings').text = json.dumps(config)
            with self.subTest(config=config), self.assertRaises(ValueError):
                extract_xmp(ET.tostring(root))


class CliTests(unittest.TestCase):
    def test_float32_overflow_rejected_before_creating_assets(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            root = Path(directory)
            source = root / 'large.cube'
            source.write_bytes(make_cube(fn=lambda r, g, b: (1e100, g, b)))
            output = root / 'assets'
            self.assertEqual(main(['prepare', str(source), str(output),
                                   '--input-space', 'srgb', '--output-space', 'srgb']), 2)
            self.assertFalse(output.exists())

    def test_existing_outputs_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'out.dng'
            path.write_bytes(b'keep')
            with self.assertRaises(FileExistsError):
                exclusive_write(path, b'new')
            self.assertEqual(path.read_bytes(), b'keep')

    def test_prepare_embed_extract_cli(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            root = Path(directory)
            source = root / 'look.cube'
            source.write_bytes(make_cube())
            dng = root / 'source.dng'
            dng.write_bytes(fixture())
            options = ['--input-space', 'srgb', '--output-space', 'srgb']
            self.assertEqual(main(['prepare', str(source), str(root / 'assets')] + options), 0)
            self.assertEqual((root / 'assets/source.cube').read_bytes(), source.read_bytes())
            self.assertEqual(main(['embed', str(source), str(dng), str(root / 'out.dng')] + options), 0)
            self.assertEqual(main(['extract', str(root / 'out.dng'), str(root / 'recovered.cube')]), 0)
            self.assertEqual((root / 'recovered.cube').read_bytes(), source.read_bytes())


if __name__ == '__main__':
    unittest.main()
