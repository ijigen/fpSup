import unittest
import numpy as np
from cube import Cube
from residual import ResidualAffine, ResidualGrid, collision_floor, error_metrics


class ResidualTests(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(90210)

    def test_tetrahedral_nodes_agree_with_full_cube_reference(self):
        size = 5
        table = self.rng.uniform(-0.03, 0.03, (size, size, size, 3))
        model = ResidualGrid(table, ((0, 0, 0), (1, 1, 1)))
        axis = np.linspace(0, 1, size)
        b, g, r = np.meshgrid(axis, axis, axis, indexing='ij')
        full = np.stack((r, g, b), axis=-1) + model.table
        text = 'LUT_3D_SIZE 5\n' + '\n'.join(' '.join(map(str, row)) for row in full.reshape(-1, 3))
        cube = Cube.parse(text.encode())
        inputs = np.vstack((self.rng.random((2000, 3)), [[0, 0, 0], [1, 1, 1], [0.5, 0.5, 0.5]]))
        np.testing.assert_allclose(model.apply(inputs), cube.apply(inputs), atol=1e-12)

    def test_fit_reduces_cross_channel_error_on_independent_samples(self):
        train = self.rng.random((3000, 3))
        target = train + np.column_stack((0.015 * train[:, 1], -0.02 * train[:, 2], 0.01 * train[:, 0]))
        model, report = ResidualGrid.fit(train, target, size=5, smoothness=1e-8)
        test = self.rng.random((1700, 3))
        expected = test + np.column_stack((0.015 * test[:, 1], -0.02 * test[:, 2], 0.01 * test[:, 0]))
        before = error_metrics(test, expected)['rgb_rmse']
        after = error_metrics(model.apply(test), expected)['rgb_rmse']
        self.assertLess(after, before / 100)
        self.assertTrue(report['held_out_validation_required'])
        self.assertFalse(report['camera_runtime_verified'])

    def test_affine_candidate_is_small_and_calibrates_cross_channel_pairs(self):
        train = self.rng.random((500, 3))
        matrix = self.rng.uniform(-0.01, 0.01, (3, 3))
        offset = np.array([0.01, -0.01, 0.005])
        model, report = ResidualAffine.fit(train, train + train @ matrix + offset)
        test = self.rng.random((600, 3))
        np.testing.assert_allclose(model.apply(test), test + test @ matrix + offset, atol=1e-8)
        self.assertEqual(report['float32_coefficient_bytes'], 48)
        with self.assertRaisesRegex(ValueError, 'rank-deficient'):
            ResidualAffine.fit(np.ones((10, 3)), np.ones((10, 3)))

    def test_clipped_output_collision_has_nonzero_recovery_floor(self):
        native = np.array([[0.5, 0.5, 0.5]] * 2)
        target = np.array([[0.1, 0.2, 0.3], [0.3, 0.2, 0.3]])
        floor = collision_floor(native, target)
        self.assertAlmostEqual(floor['rgb_rmse_lower_bound'], 0.1 / np.sqrt(3))
        self.assertEqual(floor['conflicting_output_groups'], 1)
        self.assertEqual(collision_floor(native, native)['rgb_rmse_lower_bound'], 0)

    def test_no_implicit_domain_or_output_clamp(self):
        model = ResidualGrid(np.full((5, 5, 5, 3), 0.2), ((0, 0, 0), (1, 1, 1)))
        self.assertGreater(model.apply([[1, 1, 1]])[0, 0], 1)
        for inputs in ([[1.01, 0, 0]], [[-0.001, 0, 0]]):
            with self.assertRaisesRegex(ValueError, 'implicit clamp'): model.apply(inputs)
            with self.assertRaisesRegex(ValueError, 'implicit clamp'): ResidualGrid.fit(inputs, inputs)

    def test_solver_bound_failure_is_explicit(self):
        train = self.rng.random((300, 3))
        target = train + 0.02 * np.sin(train[:, ::-1] * 8)
        with self.assertRaisesRegex(RuntimeError, 'did not converge'):
            ResidualGrid.fit(train, target, max_iterations=1)

    def test_table_budgets_and_invalid_inputs(self):
        for size, budget in ((5, 1500), (9, 8748), (17, 58956)):
            model = ResidualGrid(np.zeros((size, size, size, 3)), ((-1, -1, -1), (2, 2, 2)))
            self.assertEqual(model.summary()['float32_table_bytes'], budget)
        with self.assertRaises(ValueError): ResidualGrid.fit([[np.nan, 0, 0]], [[0, 0, 0]])
        with self.assertRaises(ValueError): ResidualGrid.fit([[0, 0, 0]], [[0, 0, 0]], size=33)
        with self.assertRaises(ValueError): collision_floor([], [])


if __name__ == '__main__': unittest.main()
