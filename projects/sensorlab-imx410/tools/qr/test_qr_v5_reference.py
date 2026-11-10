"""Tests for the bounded pristine-matrix verifier; no ARM or image libraries."""
import json
import pathlib
import unittest

import qr_v5_reference as Q

FIXTURE = json.loads((pathlib.Path(__file__).with_name('v5_fixture.json')).read_text())


def matrix():
    return [[int(v) for v in row] for row in FIXTURE['dark_rows']]


def image(m, scale=1, border=4):
    width = (37 + border * 2) * scale
    rows = [[255] * width for _ in range(border * scale)]
    for row in m:
        expanded = [255] * (border * scale) + [0 if v else 255 for v in row for _ in range(scale)] + [255] * (border * scale)
        rows.extend([expanded[:] for _ in range(scale)])
    rows.extend([[255] * width for _ in range(border * scale)])
    return rows


class Reference(unittest.TestCase):
    def test_layout_and_fixture(self):
        self.assertEqual(len(Q.function_modules()), 290)
        self.assertEqual(len(list(Q.data_coordinates())), 1079)
        payload, mask = Q.decode_modules(matrix())
        self.assertEqual(payload.decode(), FIXTURE['url'])
        self.assertEqual(mask, FIXTURE['mask'])

    def test_every_mask(self):
        original = FIXTURE['mask']
        for target in range(8):
            m = matrix()
            for x, y in Q.data_coordinates():
                m[y][x] ^= Q.mask_at(original, x, y) ^ Q.mask_at(target, x, y)
            for coords in (Q.FORMAT_A, Q.FORMAT_B):
                for bit, (x, y) in enumerate(coords):
                    m[y][x] = (Q.FORMAT_L[target] >> bit) & 1
            self.assertEqual(Q.decode_modules(m), (FIXTURE['url'].encode(), target))

    def test_corrupted_patterns_formats_data_and_remainder_rejected(self):
        coords = list(Q.data_coordinates())
        for x, y in ((0, 0), (30, 30), (6, 12), Q.FORMAT_A[0], Q.FORMAT_B[0], coords[0], coords[-1]):
            m = matrix()
            m[y][x] ^= 1
            with self.subTest(x=x, y=y), self.assertRaises(ValueError):
                Q.decode_modules(m)

    def test_integer_scale_and_uniform_pixels(self):
        for scale in (1, 5, 6):
            for border in (0, 2, 4):
                self.assertEqual(Q.decode_pristine_image(image(matrix(), scale, border)), FIXTURE['url'])
        bad = image(matrix(), 5, 2)
        bad[11][11] ^= 255
        with self.assertRaisesRegex(ValueError, 'nonuniform'):
            Q.decode_pristine_image(bad)
        bad[11][11] = 127
        with self.assertRaisesRegex(ValueError, 'pristine'):
            Q.decode_pristine_image(bad)


if __name__ == '__main__':
    unittest.main()
