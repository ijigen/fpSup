"""CinemaDNG menu boundaries and standard (not Resolve-matched) mathematics."""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cinemadng import COLOR_SPACES, Selection, gamma_choices
from color import D65, to_xyz_matrix, transfer, xyz_white
from cube import Cube
from fplut import main
from monitor import Monitor, presets
from test_lut import make_cube


class CinemaDngTests(unittest.TestCase):
    def test_observed_menu_and_dependent_gamma_lists(self):
        menu = presets()
        self.assertEqual([c['label'] for c in menu['color_spaces']],
                         ['ACES', 'Adobe RGB', 'Blackmagic Design', 'P3 D60',
                          'P3 D65', 'Rec.2020', 'Rec.709', 'sRGB'])
        self.assertEqual([g['label'] for g in menu['common_gammas']],
                         ['Adobe RGB', 'Gamma 2.4', 'Gamma 2.6', 'Linear', 'Rec.709', 'sRGB'])
        self.assertEqual([g['label'] for g in menu['blackmagic_gammas']],
                         ['Blackmagic Design Film', 'Blackmagic Design Extended Video'])
        self.assertFalse(menu['resolve_pixel_match_verified'])
        self.assertFalse(menu['menu_option_enabled_state_verified'])

    def test_proprietary_and_rec709_models_never_silently_substituted(self):
        for color, gamma in [('blackmagic-design', 'blackmagic-film'),
                             ('blackmagic-design', 'blackmagic-extended-video'),
                             ('aces', 'rec709')]:
            selection = Selection(color, gamma)
            self.assertFalse(selection.numerical_reference_available)
            with self.assertRaisesRegex(ValueError, 'not a substitute'):
                selection.encoding()
        for color, gamma in [('blackmagic-design', 'linear'), ('rec709', 'blackmagic-film')]:
            with self.assertRaisesRegex(ValueError, 'not in'):
                Selection(color, gamma)

    def test_adobe_published_matrix_and_transfer(self):
        # Adobe RGB (1998) spec sections 4.3.5.2/3: independent published data.
        np.testing.assert_allclose(to_xyz_matrix('adobe-rgb'),
            [[.57667, .18556, .18823], [.29734, .62736, .07529], [.02703, .07069, .99134]],
            atol=7e-6, rtol=0)
        self.assertAlmostEqual(float(transfer(.5, 'adobe-rgb', inverse=True)),
                               .5**2.19921875, places=15)
        self.assertAlmostEqual(float(transfer(.18, 'adobe-rgb')), .18**(1/2.19921875), places=15)
        self.assertAlmostEqual(float(transfer(.18, 'gamma26')), .18**(1/2.6), places=15)

    def test_standard_white_and_negative_hdr_roundtrips_for_all_available_pairs(self):
        linear = np.array([[-.01, .18, 16.], [4., -.002, .0001]])
        count = 0
        for color in COLOR_SPACES:
            for gamma in gamma_choices(color):
                selection = Selection(color, gamma)
                if not selection.numerical_reference_available:
                    continue
                with self.subTest(color=color, gamma=gamma):
                    space = selection.encoding()
                    np.testing.assert_allclose(space.from_xyz(xyz_white(D65)*.18),
                                               transfer(np.full(3, .18), space.curve), atol=2e-14)
                    encoded = transfer(linear, space.curve)
                    recovered = transfer(space.from_xyz(space.to_xyz(encoded)), space.curve, inverse=True)
                    np.testing.assert_allclose(recovered, linear, atol=3e-13)
                    self.assertFalse(space.display_input)
                    count += 1
        self.assertEqual(count, 35)

    def test_gamut_and_gamma_are_independent_and_white_choice_matters(self):
        cube = Cube.parse(make_cube())
        neutral = [[.18]*3]
        a, _ = Monitor(cube, 'rec2020', input_gamma='gamma26').evaluate(neutral, 'linear-709')
        b, _ = Monitor(cube, 'rec2020', input_gamma='linear').evaluate(neutral, 'linear-709')
        np.testing.assert_allclose(a, .18**(1/2.6), atol=2e-15)
        np.testing.assert_allclose(b, .18, atol=2e-15)
        # Same P3 primaries, different white points: chromatic samples differ.
        sample = [[.4, .15, .08]]
        a, _ = Monitor(cube, 'p3-d60', input_gamma='linear').evaluate(sample, 'linear-709')
        b, _ = Monitor(cube, 'p3-d65', input_gamma='linear').evaluate(sample, 'linear-709')
        self.assertGreater(float(np.abs(a-b).max()), .001)
        # ACES menu model is explicit AP0, never implicitly AP1/ACEScg or a DRT.
        self.assertEqual(Selection('aces', 'linear').encoding().gamut, 'aces-ap0')
        self.assertFalse(Selection('aces', 'linear').summary()['resolve_pixel_match_verified'])

    def test_no_hidden_input_display_clipping_for_sdr_gamut_labels(self):
        # Identity on an expanded domain exposes pre-LUT values outside 0..1.
        cube = Cube.parse(make_cube(fn=lambda r, g, b: (3*r-1, 3*g-1, 3*b-1),
                          headers='DOMAIN_MIN -1 -1 -1\nDOMAIN_MAX 2 2 2\n'))
        sample = np.array([[-.02, .18, 2.]])
        for color, gamma in [('rec709', 'linear'), ('srgb', 'gamma24')]:
            model = Monitor(cube, color, input_gamma=gamma)
            output, report = model.evaluate(sample, 'linear-709')
            expected = sample if gamma == 'linear' else np.sign(sample)*np.abs(sample)**(1/2.4)
            np.testing.assert_allclose(output, expected, atol=3e-15)
            self.assertEqual(report['input_linear_before_render']['outside_samples'], 1)
            self.assertEqual(report['lut_lookups']['cube_lookup']['outside_samples'], 0)


class CinemaDngCliTests(unittest.TestCase):
    def test_unavailable_pairs_fail_before_creating_assets(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            root = Path(directory)
            cube = root/'look.cube'
            cube.write_bytes(make_cube())
            for color, gamma in [('blackmagic-design', 'blackmagic-film'),
                                 ('blackmagic-design', 'blackmagic-extended-video'),
                                 ('p3-d65', 'rec709'), ('blackmagic-design', 'gamma24')]:
                output = root/'assets'
                with self.subTest(color=color, gamma=gamma), redirect_stderr(io.StringIO()):
                    self.assertEqual(main(['monitor-prepare', str(cube), str(output),
                                          '--input-space', color, '--input-gamma', gamma]), 2)
                    self.assertFalse(output.exists())

    def test_cli_requires_separate_gamma_and_rejects_cst_only_gamuts(self):
        for extra in [[], ['--input-gamma', 'linear']]:
            args = ['monitor-prepare', 'look.cube', 'out', '--input-space',
                    'rec709' if not extra else 'arri-logc3-ei800', *extra]
            with self.subTest(args=args), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(args)
                self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
