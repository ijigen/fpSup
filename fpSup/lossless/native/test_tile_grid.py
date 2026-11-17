#!/usr/bin/env python3
"""tile_grid.h: the grid every lossless frame is compressed with.

The C is compiled for the host and compared with a Python statement of the
rule over many frame shapes; the shapes the camera records have their answer
written out; mutations of the header must each fail a test. And the default
must stay inside the engine's and TIFF's limits for every shape it can see.
"""
import ctypes as ct
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
TILE_MAX = 160
TILE_PIXELS = 32250
WRAPPER = r'''
#include "tile_grid.h"
uint32_t grid(uint32_t w, uint32_t h, uint32_t force) {
    uint32_t tw = 0, th = 0;
    fpl_tile_grid(w, h, force, &tw, &th);
    return tw << 16 | th;
}
'''


def build(directory, header=None):
    d = Path(directory)
    (d / 'tile_grid.h').write_text(header or (HERE / 'tile_grid.h').read_text())
    (d / 'w.c').write_text(WRAPPER)
    # tile_grid.h includes "../control.h": the real one, one level up from the copy
    (d.parent / 'control.h').write_text((HERE.parent / 'control.h').read_text())
    out = d / 'g.dylib'
    subprocess.run([shutil.which('clang') or 'clang', '-shared', '-fPIC', '-O2', '-std=c11',
                    '-Wall', '-Wextra', '-Werror', '-I', str(d), str(d / 'w.c'), '-o', str(out)],
                   check=True, capture_output=True, text=True, timeout=60)
    lib = ct.CDLL(str(out))
    lib.grid.argtypes = [ct.c_uint32] * 3
    lib.grid.restype = ct.c_uint32
    return lib


def reference(w, h):
    best = None
    for tw in range(32, 513, 32):
        if w == 2 * tw:                      # LibRaw misplaces the rows of exactly two tiles across
            continue
        for th in range(16, 513, 16):
            kx, ky = math.ceil(w / tw), math.ceil(h / th)
            if kx * ky > TILE_MAX:
                continue
            key = (kx * tw * ky * th + kx * ky * TILE_PIXELS, kx * ky)
            if best is None or key < best[0]:
                best = (key, tw, th)
    return (best[1], best[2]) if best else (512, 368)


SHAPES = [(3024, 2010), (3840, 2160), (1936, 1090), (2016, 1340), (6064, 4042),
          (1920, 1080), (4096, 2160), (3008, 2000), (520, 368), (1536, 736), (8, 2)]


class GridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-grid-')
        root = Path(cls.tmp.name) / 'a'
        root.mkdir()
        cls.lib = build(root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def grid(self, w, h, force=0):
        v = self.lib.grid(w, h, force)
        return v >> 16, v & 0xFFFF

    def test_the_shapes_the_camera_records(self):
        # the measured cost model's choices (2026-10-07)
        self.assertEqual(self.grid(3024, 2010), (512, 512))     # OG3K: 24 tiles
        self.assertEqual(self.grid(3840, 2160), (480, 432))     # UHD: exact, 40 tiles
        self.assertEqual(self.grid(1936, 1090), (512, 368))     # FHD: as before

    def test_never_exactly_two_tiles_across(self):
        # SQ 1024x1024 took 512x512 and LibRaw read it with every other row misplaced (2026-11-17)
        self.assertEqual(self.grid(1024, 1024), reference(1024, 1024))
        self.assertNotEqual(self.grid(1024, 1024)[0], 512)
        for w in range(64, 1025, 64):
            for h in (64, 678, 1024, 2010):
                with self.subTest(w=w, h=h):
                    self.assertNotEqual(2 * self.grid(w, h)[0], w)
        self.assertEqual(self.grid(1024, 1024, 512 << 16 | 512), (512, 512), 'a force is still a force')

    def test_the_c_is_the_rule(self):
        shapes = SHAPES + [(w, h) for w in range(8, 6200, 296) for h in range(2, 4100, 214)]
        for w, h in shapes:
            with self.subTest(w=w, h=h):
                self.assertEqual(self.grid(w, h), reference(w, h))

    def test_every_default_is_a_legal_tile(self):
        for w, h in SHAPES + [(w, h) for w in range(8, 0x4001, 1016) for h in range(2, 0x4001, 1022)]:
            tw, th = self.grid(w, h)
            with self.subTest(w=w, h=h, grid=(tw, th)):
                if math.ceil(w / 512) * math.ceil(h / 512) > TILE_MAX:
                    self.assertEqual((tw, th), (512, 368))       # nothing fits: refused later
                    continue
                self.assertTrue(32 <= tw <= 512 and tw % 32 == 0)
                self.assertTrue(16 <= th <= 512 and th % 16 == 0)
                self.assertLessEqual(math.ceil(w / tw) * math.ceil(h / th), TILE_MAX)

    def test_a_legal_force_wins_and_an_illegal_one_does_not(self):
        self.assertEqual(self.grid(3024, 2010, 256 << 16 | 400), (256, 400))
        for force in (500 << 16 | 400, 512 << 16 | 360, 544 << 16 | 400, 512 << 16 | 528,
                      32 << 16 | 16):
            with self.subTest(force=hex(force)):
                self.assertEqual(self.grid(3024, 2010, force), (512, 512))


class MutationTests(unittest.TestCase):
    MUTATIONS = {
        'tiles cost nothing': ('tiles * FPL_TILE_PIXELS;', '0;'),
        'heights not a multiple of 16': ('h += 16u', 'h += 2u'),
        'force not checked': ('if (force && fpl_tile_legal(width, height, fw, fh))', 'if (force)'),
        'too many tiles allowed': ('if (tiles > FPL_TILE_MAX) continue;', ''),
        'two tiles across allowed': ('        if (width == 2u * w) continue;\n', ''),
        'no search': ('    for (uint32_t w = 32u; w <= 512u; w += 32u) {',
                      '    for (uint32_t w = 32u; w < 32u; w += 32u) {'),
    }

    def test_every_mutation_is_caught(self):
        text = (HERE / 'tile_grid.h').read_text()
        with tempfile.TemporaryDirectory(prefix='fpl-grid-mut-') as tmp:
            for i, (name, (old, new)) in enumerate(self.MUTATIONS.items()):
                with self.subTest(mutation=name):
                    self.assertEqual(text.count(old), 1, f'seam for {name!r}')
                    root = Path(tmp) / f'm{i}'
                    root.mkdir()
                    lib = build(root, text.replace(old, new))

                    class Against(GridTests):
                        @classmethod
                        def setUpClass(cls):
                            cls.lib = lib

                        @classmethod
                        def tearDownClass(cls):
                            pass
                    result = unittest.TestResult()
                    unittest.defaultTestLoader.loadTestsFromTestCase(Against).run(result)
                    self.assertFalse(result.wasSuccessful(), f'{name} was not caught')


if __name__ == '__main__':
    unittest.main()
