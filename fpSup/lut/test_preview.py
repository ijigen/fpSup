import unittest
import numpy as np
from preview import YUYVFrame


class PreviewTests(unittest.TestCase):
    def test_independent_byte_order_stride_and_tail_guards(self):
        data = bytes([10, 50, 20, 70, 30, 60, 40, 80, 255, 255,
                      90, 110, 100, 120, 130, 140, 150, 160, 255, 255])
        frame = YUYVFrame.unpack(data, 4, 2, row_stride=10)
        np.testing.assert_array_equal(frame.y, [[10, 20, 30, 40], [90, 100, 130, 150]])
        np.testing.assert_array_equal(frame.cr, [[50, 60], [110, 140]])     # Y0 Cr Y1 Cb (YVYU)
        np.testing.assert_array_equal(frame.cb, [[70, 80], [120, 160]])
        self.assertFalse(frame.y.flags.writeable)
        for bad in (data[:-1], data + b'\0'):
            with self.assertRaises(ValueError): YUYVFrame.unpack(bad, 4, 2, 10)
        with self.assertRaises(ValueError): YUYVFrame.unpack(data, 3, 2)

    def test_neutral_limited_black_white_are_exact_for_both_matrices(self):
        frame = YUYVFrame.unpack(bytes([16, 128, 235, 128]), 2, 1)
        for matrix in ('601', '709'):
            np.testing.assert_allclose(frame.rgb(matrix, 'limited'), [[[0, 0, 0], [1, 1, 1]]])

    def test_full_neutral_and_unclamped_extremes(self):
        frame = YUYVFrame.unpack(bytes([0, 128, 255, 128]), 2, 1)
        np.testing.assert_allclose(frame.rgb('601', 'full'), [[[0, 0, 0], [1, 1, 1]]])
        extreme = YUYVFrame.unpack(bytes([0, 255, 255, 255]), 2, 1).rgb('709', 'full')
        self.assertLess(float(extreme.min()), 0)
        self.assertGreater(float(extreme.max()), 1)

    def test_orange_is_orange(self):          # the LCD shows an orange cat; Cb low, Cr high in Y Cr Y Cb order
        rgb = YUYVFrame.unpack(bytes([150, 170, 150, 90]), 2, 1).rgb('709', 'full')[0, 0]
        self.assertGreater(rgb[0], rgb[2] + 0.2)

    def test_chroma_channels_and_matrix_choice_are_distinct(self):
        frame = YUYVFrame.unpack(bytes([100, 160, 110, 192]), 2, 1)
        a, b = frame.rgb('601', 'full'), frame.rgb('709', 'full')
        self.assertGreater(a[0, 0, 0], 100 / 255)
        self.assertGreater(a[0, 0, 2], 100 / 255)
        np.testing.assert_allclose(a[0, 1] - a[0, 0], [10 / 255] * 3)
        self.assertGreater(float(np.max(np.abs(a - b))), 0.01)
        with self.assertRaises(ValueError): frame.rgb('auto', 'full')
        with self.assertRaises(ValueError): frame.rgb('601', 'auto')


if __name__ == '__main__': unittest.main()
