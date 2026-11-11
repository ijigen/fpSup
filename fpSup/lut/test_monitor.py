"""Published colour anchors, monitoring semantics and real ARRI LUT integration."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

import numpy as np
from PIL import Image

from color import (REFERENCE_SPACES, D65, from_xyz_matrix, source_to_xyz,
                   to_xyz_matrix, transfer, xyz_white)
from cube import Cube
from fplut import main
from monitor import Monitor, OUTPUT, baseline_xyz, png_bytes, prepare
from test_lut import make_cube


ROOT = Path(__file__).resolve().parents[2]
ARRI = ROOT / 'projects/lut-sup/assets/arri/official-20261009/ARRI_LogC3-to-Gamma24_Rec709_D65-Classic_33.cube'


class ColourTests(unittest.TestCase):
    def test_published_grey_and_black_code_values(self):
        # Reference values from the manufacturer documents; not round trips.
        for curve, black, grey in [('logc3-ei800', .092809, 400/1023),
                                   ('logc4', 95/1023, .2783958365482653),
                                   ('slog3', 95/1023, 420/1023),
                                   ('vlog', .125, 433/1023),
                                   ('film5', .0924657534246575, .3835616438356165),
                                   ('intermediate', 0., .336043)]:
            with self.subTest(curve=curve):
                self.assertAlmostEqual(float(transfer(0., curve)), black, places=7)
                # V-Log's published integer code 433 is rounded.
                self.assertLess(abs(float(transfer(.18, curve))-grey), .5/1023 if curve == 'vlog' else 5e-7)

    def test_published_gen5_hdr_and_negative_intermediate(self):
        np.testing.assert_allclose(transfer([1., 10., 40., 100.], 'film5'),
            [.5304896249573048, .7302219538415439, .8506949973834717, .9303398518999735], atol=2e-15)
        self.assertAlmostEqual(float(transfer(-.01, 'intermediate')), -.1044426855, places=10)
        self.assertGreater(float(transfer(100., 'logc3-ei800')), 1.)

    def test_negative_and_hdr_values_survive_colour_roundtrip(self):
        values = np.array([[-.001, .18, 16.], [4., -.002, 1.], [0., 0., 0.]])
        for space in REFERENCE_SPACES.values():
            with self.subTest(space=space.id):
                # Conversion alone does not perform the monitor's display render.
                encoded = transfer(values, space.curve)
                recovered = space.from_xyz(space.to_xyz(encoded))
                np.testing.assert_allclose(transfer(recovered, space.curve, inverse=True), values, atol=2e-11)

    def test_matrices_against_published_xyz_values(self):
        expected = {
            'awg3': [[.638008, .214704, .097744], [.291954, .823841, -.115795], [.002798, -.067034, 1.153294]],
            'vgamut': [[.679644, .152211, .118600], [.260686, .774894, -.035580], [-.009310, -.004612, 1.102980]],
            'dwg': [[.70062239, .14877482, .10105872], [.27411851, .87363190, -.14775041], [-.09896291, -.13789533, 1.32591599]],
        }
        for gamut, matrix in expected.items():
            with self.subTest(gamut=gamut):
                np.testing.assert_allclose(to_xyz_matrix(gamut), matrix, atol=6e-7, rtol=0)

    def test_white_adaptation_p3_and_bmd_to_common_d65(self):
        for gamut in ('709', 'p3d60', 'bmwg5', 'awg4'):
            np.testing.assert_allclose(to_xyz_matrix(gamut) @ np.ones(3), xyz_white(D65), atol=5e-15)
            np.testing.assert_allclose(from_xyz_matrix(gamut) @ xyz_white(D65), 1, atol=5e-15)


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.constant = Cube.parse(make_cube(fn=lambda r, g, b: (.2, .4, .8)))

    def test_no_second_display_transform_and_output_not_clipped(self):
        cube = Cube.parse(make_cube(fn=lambda r, g, b: (-.2, .4, 1.3)))
        output, report = Monitor(cube, 'arri-logc3-ei800').evaluate([[.18]*3, [16.]*3], 'linear-709')
        np.testing.assert_allclose(output, [[-.2, .4, 1.3]]*2, atol=1e-15)
        self.assertEqual(report['output_before_display_clip']['outside_samples'], 2)

    def test_strength_is_mixed_in_709_and_zero_is_baseline(self):
        scene = np.array([[.18, .18, .18], [-.1, 4., .02]])
        baseline = np.clip(scene, 0, 1)**(1/2.4)
        for preset in REFERENCE_SPACES:
            with self.subTest(preset=preset):
                zero, report = Monitor(self.constant, preset, 0).evaluate(scene, 'linear-709')
                np.testing.assert_allclose(zero, baseline, atol=1e-14)
                self.assertFalse(report['lut_evaluated'])
                half, _ = Monitor(self.constant, preset, .5).evaluate(scene, 'linear-709')
                np.testing.assert_allclose(half, .5*baseline+.5*np.array([.2, .4, .8]), atol=1e-14)

    def test_scene_exposure_is_upstream_of_encoding(self):
        identity = Cube.parse(make_cube())
        a, _ = Monitor(identity, 'arri-logc3-ei800', exposure_ev=1).evaluate([[.09]*3], 'linear-709')
        np.testing.assert_allclose(a, 400/1023, atol=2e-8)

    def test_lookup_clipping_report_includes_post_shaper(self):
        source = b'LUT_1D_SIZE 2\nLUT_3D_SIZE 2\n0 0 0\n2 2 2\n'
        source += make_cube().split(b'\n', 1)[1]
        model = Monitor(Cube.parse(source), 'linear-709')
        _, report = model.evaluate([[.75]*3, [2.]*3], 'linear-709')
        self.assertEqual(report['lut_lookups']['shaper_lookup']['outside_samples'], 1)
        self.assertEqual(report['lut_lookups']['cube_lookup']['outside_samples'], 2)

    def test_png_has_srgb_encoding_and_profile(self):
        # A 709/Gamma2.4 code of 0.5 has linear light .5**2.4, not .214041.
        image = Image.open(io.BytesIO(png_bytes(np.full((2, 3, 3), .5))))
        self.assertIn('icc_profile', image.info)
        expected = round((1.055*(.5**2.4)**(1/2.4)-.055)*255)
        np.testing.assert_array_equal(np.asarray(image), expected)

    def test_bad_parameters_and_source_are_rejected(self):
        for kwargs in [dict(input_space='unknown'), dict(input_space='srgb', strength=2),
                       dict(input_space='srgb', exposure_ev=float('nan'))]:
            with self.assertRaises(ValueError):
                Monitor(self.constant, **kwargs)
        with self.assertRaises(ValueError):
            Monitor(self.constant, 'srgb').evaluate([[.1]*3], 'camera-native-unknown')

    def test_saved_settings_do_not_mutate_transfer_constants(self):
        model = Monitor(self.constant, 'arri-logc3-ei800')
        config = model.settings()
        config['transfer_parameters']['logc3_ei800']['a'] = 0
        self.assertEqual(model.settings()['transfer_parameters']['logc3_ei800']['a'], 5.555556)

    def test_composite_retains_exact_source_and_float32_nodes(self):
        model = Monitor(self.constant, 'p3-d65', input_gamma='gamma26')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'prepared'
            config = prepare(model, root, 17)
            self.assertEqual((root/'source.cube').read_bytes(), self.constant.source)
            self.assertEqual(config['output']['space'], OUTPUT)
            self.assertEqual(config['cinemadng']['color_space'], 'p3-d65')
            self.assertEqual(config['cinemadng']['gamma'], 'gamma26')
            self.assertFalse(config['cinemadng']['resolve_pixel_match_verified'])
            self.assertEqual(config['compiled']['input_space'], 'cdng:p3-d65/gamma26')
            self.assertFalse(config['on_camera_ready'])
            self.assertEqual((root/'monitor.f32le').stat().st_size, 17**3*3*4)
            composite = Cube.read(root/'monitor.cube')
            samples = np.random.default_rng(3).uniform(-.01, 1, (30, 3))
            np.testing.assert_allclose(composite.apply(samples), [.2, .4, .8]*np.ones((30, 3)), atol=1e-12)
            self.assertLess(config['compiled']['error']['max_channel'], 2e-8)
            for name, info in config['assets'].items():
                self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(), info['sha256'])

    @unittest.skipUnless(ARRI.exists(), 'official ARRI fixture is in the full research tree')
    def test_real_arri_lut_grey_against_independent_diagonal_interpolation(self):
        cube = Cube.read(ARRI)
        self.assertEqual(cube.sha256, '29212a71808ab22f2819b904b3730fa4231b5841d883e43ec17610096dc38879')
        # Neutral tetrahedral interpolation follows the diagonal; use ARRI's
        # published grey code, rather than reusing our LogC3 encoder here.
        expected = [np.interp(400/1023, np.linspace(0, 1, 33),
                             [cube.table3d[i, i, i, c] for i in range(33)]) for c in range(3)]
        output, report = Monitor(cube, 'arri-logc3-ei800').evaluate([[.18]*3], 'linear-709')
        np.testing.assert_allclose(output[0], expected, atol=5e-8)
        self.assertEqual(report['lut_lookups']['cube_lookup']['outside_samples'], 0)

    @unittest.skipUnless(ARRI.exists(), 'official ARRI fixture is in the full research tree')
    def test_arri_composite_keeps_native_input_domain_and_hdr_exposure_upstream(self):
        model = Monitor(Cube.read(ARRI), 'arri-logc3-ei800', exposure_ev=2)
        composite, packed, error = model.compile(33)
        self.assertEqual(composite.range3d, model.cube.range3d)
        self.assertLess(error['max_channel'], 1e-6)
        # Matching source grid preserves the original 3D LUT, despite the
        # runtime exposure setting; exposure is applied BEFORE LogC3 encoding.
        np.testing.assert_array_equal(composite.table3d, model.cube.table3d)


class MonitoringCliTests(unittest.TestCase):
    def test_fixed_output_catalogue_and_float_render(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            root = Path(directory)
            cube = root/'look.cube'
            cube.write_bytes(make_cube(fn=lambda r, g, b: (-.1, .5, 1.1)))
            source = root/'linear.npy'
            np.save(source, np.full((2, 3, 3), .18))
            output = root/'709.npy'
            args = ['monitor-render', str(cube), str(source), str(output),
                    '--input-space', 'aces', '--input-gamma', 'linear', '--source-space', 'linear-709']
            self.assertEqual(main(args), 0)
            np.testing.assert_allclose(np.load(output), np.broadcast_to([-.1, .5, 1.1], (2, 3, 3)))
            metadata = json.loads((root/'709.npy.json').read_text())
            self.assertEqual(metadata['output']['space'], OUTPUT)
            original = output.read_bytes()
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 2)
            self.assertEqual(output.read_bytes(), original)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                self.assertEqual(main(['monitor-presets']), 0)
            self.assertEqual(len(json.loads(buffer.getvalue())['color_spaces']), 8)

    def test_preview_uses_input_conversion_and_preserves_existing_sidecar(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            root = Path(directory)
            cube, image, output = root/'look.cube', root/'in.png', root/'out.png'
            cube.write_bytes(make_cube(fn=lambda r, g, b: (.2, .4, .8)))
            Image.new('RGB', (4, 3), (128, 128, 128)).save(image)
            args = ['monitor-preview', str(cube), str(image), str(output),
                    '--input-space', 'rec2020', '--input-gamma', 'adobe-rgb']
            sidecar = root/'out.png.json'
            sidecar.write_bytes(b'keep')
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 2)
            self.assertFalse(output.exists())
            self.assertEqual(sidecar.read_bytes(), b'keep')
            sidecar.unlink()
            self.assertEqual(main(args), 0)
            with Image.open(output) as result:
                self.assertEqual(result.size, (4, 3))
                self.assertIn('icc_profile', result.info)


if __name__ == '__main__':
    unittest.main()
