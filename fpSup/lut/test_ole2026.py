"""Independent properties and failure boundaries of the experimental recipe."""
import unittest

import numpy as np

from cinemadng import Selection
from color import D65, transfer, xyz_white
from cube import Cube
from ole2026 import (GEN1_WHITE, MeasuredMatrices, chain, cube_bytes, description,
                     factorized_monitor, input_to_film5,
                     linear_matrix, monitor, native_xyz, node01, node03, q, q_matrix)


class Ole2026Tests(unittest.TestCase):
    def test_native_white_and_cat_flags_are_not_silently_normalized(self):
        np.testing.assert_allclose(native_xyz('bmd-gen1-legacy') @ np.ones(3),
                                   xyz_white(GEN1_WHITE), atol=3e-16)
        adapted = linear_matrix('bmd-gen1-legacy', '709', cat=True)
        np.testing.assert_allclose(adapted @ np.ones(3), np.ones(3), atol=1e-15)
        self.assertGreater(np.max(np.abs(q_matrix() @ np.ones(3)-1)), .005)
        self.assertGreater(np.max(np.abs(linear_matrix('bmwg5', 'dwg', cat=False)-
                                        linear_matrix('bmwg5', 'dwg', cat=True))), 1e-5)

    def test_gen1_rounded_native_xyz_extraction_is_an_independent_anchor(self):
        # Existing Resolve binary extraction, rounded to six decimals in matrices.txt.
        np.testing.assert_allclose(native_xyz('bmd-gen1-legacy'),
            [[.639292, .157828, .151621], [.174407, .951008, -.125415],
             [-.116740, -.551789, 1.745690]], atol=8e-6, rtol=0)

    def test_q_is_not_matrix_on_encoded_values_and_has_exposure_dependence(self):
        sample = np.array([[.5, .3, .2], [.25, .4, .33]])
        self.assertGreater(np.max(np.abs(q(sample)-sample @ q_matrix().T)), .03)
        scene = np.array([[.22, .18, .12]])
        before = node01(scene)
        after = transfer(q(before), 'film5', inverse=True)
        doubled = transfer(q(node01(scene*4)), 'film5', inverse=True)/4
        self.assertGreater(np.max(np.abs(after-doubled)), .0005)

    def test_bypass_equals_independent_combined_linear_matrix_even_with_hdr(self):
        sample = np.array([[-.01, .18, 16.], [4., -.002, .001], [.18]*3, [-.1]*3])
        # Algebraically cancel the BWG basis, retaining the Node01 white adaptation.
        from color import adaptation
        expected = (sample @ native_xyz('p3d60').T @
                    adaptation((.32168, .33767), (.312717, .3290312)).T @
                    np.linalg.inv(native_xyz('dwg')).T)
        actual = transfer(chain(sample, correction=False), 'intermediate', inverse=True)
        np.testing.assert_allclose(actual, expected, atol=2e-13, rtol=1e-13)
        self.assertLess(actual.min(), 0)
        self.assertGreater(actual.max(), 1)

    def test_dwg_rewrite_preserves_recipe_including_no_cat(self):
        sample = np.array([[.24, .16, .13], [.01, .3, .7], [4., .18, .002]])
        film5 = node01(sample)
        dwg = node03(film5)
        np.testing.assert_allclose(input_to_film5(dwg, 'dwg-intermediate'), film5, atol=2e-14)
        for correction in (False, True):
            np.testing.assert_allclose(monitor(film5, 'bwg-film5', correction=correction),
                monitor(dwg, 'dwg-intermediate', correction=correction), atol=3e-13)

    def test_monitor_is_fixed_709_gamma24_and_cube_orders_red_fastest(self):
        # Reverse independently from linear Rec.709 to the exported input basis.
        reference = np.array([[.18]*3, [0., .4, 1.], [2., -.01, .1]])
        film5 = transfer(reference @ linear_matrix('709', 'bmwg5', cat=False).T, 'film5')
        np.testing.assert_allclose(monitor(film5, 'bwg-film5', correction=False),
                                   np.clip(reference, 0, 1)**(1/2.4), atol=5e-15)
        for correction in (False, True):
            cube = Cube.parse(cube_bytes(7, 'bwg-film5', correction=correction))
            anchors = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 1]])
            np.testing.assert_allclose(cube.apply(anchors),
                monitor(anchors, 'bwg-film5', correction=correction), atol=5e-10)

    def test_candidate_cannot_enable_pending_raw_models_or_linear_cube_export(self):
        self.assertFalse(description()['resolve_pixel_match_verified'])
        self.assertFalse(description()['raw_menu_registration'])
        self.assertFalse(Selection('blackmagic-design', 'blackmagic-film').numerical_reference_available)
        for size in (1, 66, True, 3.5):
            with self.assertRaises(ValueError): cube_bytes(size, 'bwg-film5', correction=True)
        for bad in ('p3-linear', None, 'bmd-raw-film'):
            with self.assertRaises(ValueError): cube_bytes(3, bad, correction=True)
        for bad in ([[np.nan, 0, 0]], [[np.inf, 0, 0]], [1, 2], []):
            with self.assertRaises(ValueError): q(bad)

    def test_explicit_measured_matrices_control_every_stage_and_are_immutable(self):
        matrices = MeasuredMatrices(*(np.eye(3) for _ in range(4)))
        scene = np.array([[.03, .18, 4.], [-.01, .001, .5]])
        for correction in (False, True):
            np.testing.assert_allclose(chain(scene, correction=correction, matrices=matrices),
                                       transfer(scene, 'intermediate'), atol=3e-15)
            film5 = transfer(scene, 'film5')
            np.testing.assert_allclose(monitor(film5, 'bwg-film5', correction=correction,
                                               matrices=matrices),
                                       np.clip(scene, 0, 1)**(1/2.4), atol=3e-15)
        with self.assertRaises(ValueError): matrices.bwg_to_dwg[0, 0] = 2
        for bad in (np.zeros((3, 3)), np.eye(2), np.full((3, 3), np.nan)):
            with self.assertRaises(ValueError): MeasuredMatrices(bad, np.eye(3), np.eye(3), np.eye(3))

    def test_factorized_curves_and_matrices_preserve_the_monitor_result(self):
        values=np.random.default_rng(6611).uniform(-.02,1.1,(2048,3))
        for matrices in (None,MeasuredMatrices(*(np.eye(3) for _ in range(4)))):
            for correction in (False,True):
                np.testing.assert_allclose(factorized_monitor(values,correction=correction,matrices=matrices),
                    monitor(values,'bwg-film5',correction=correction,matrices=matrices),atol=3e-13)


if __name__ == '__main__':
    unittest.main()
