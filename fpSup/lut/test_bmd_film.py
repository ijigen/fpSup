"""Blackmagic Design / Blackmagic Design Film as an input model (2026-11-18), offline.

The model is what DaVinci Resolve does with a CinemaDNG from a camera that is not Blackmagic's, read from the
program (bmd_gen1/resolve_re/NOTES.md): the white-balanced sensor RGB with no colour matrix, and the
first-generation Film curve.  What these tests hold:

  host   the curve's formula at its published points and against Resolve's own table (when Resolve is installed);
         the "gamut" is the inverse of native/lvb.c lvb_xyz, so camera RGB -> XYZ -> Blackmagic is the identity
         and the reference render is cube(Film(camera RGB)); the other models' matrices and curves are the bytes
         they were before the asset grew a seventh curve; the retired Extended Video name reads as Film.
  ARM    supported() over every (colour, gamma) through the asset check; the running selection; the camera's
         own import gives build_sup.asset()'s bytes; a picked cube renders as the reference; a LUT.BIN saved
         with the retired Gamma 7 loads as Film.

         The conversion (conv.c) of a Blackmagic cube runs to its .JFT, its targets the direct formula's.

Not here: the camera, a comparison with an image exported by Resolve, how good the converted look is on the ISP
for real Blackmagic Film LUTs (one synthetic cube converts; no match threshold is set), the one-row Gamma list
on the real menu.
"""
import hashlib
import re
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

import build_sup as P
import color as C
import library as L
import test_import_native as IN
import test_library_native as LN
import test_sup_native as N
import test_sup_ui as U
from cinemadng import BLACKMAGIC_GAMMAS, COLOR_SPACES, COMMON_GAMMAS, GAMMAS, LEGACY_GAMMAS, Selection, catalogue
from cube import Cube
from monitor import Monitor
from test_lut import make_cube

HERE = Path(__file__).resolve().parent
RESOLVE_TABLE = Path('/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT/VFX IO/BMDFilm to Linear.cube')
BMD, FILM = 'blackmagic-design', 'blackmagic-film'
NATIVE = U.N.T4.Uc is not None and U.N.T3.IMAGE.exists()
# camera RGB (white-balanced, 18 % grey = .18): below black, the toe, grey, white, highlights, saturated colours
RGB = np.array([[-.01, .002, .004], [.0063, .0064, .02], [.18] * 3, [1.] * 3, [.3, .15, .05], [.05, .25, .4],
                [2.5, 1.2, .6], [4., 4., 4.], [.9, .01, .02], [.0, .7, .0]])
LOOK = lambda r, g, b: (r * g + .03 * b, .2 * r + .6 * g + .2 * b, b * b - .04 * r)   # noqa: E731  (not separable)


def film(x):
    """The formula as the task states it, written out apart from color.transfer (linear -> code)."""
    x = np.asarray(x, float)
    return np.where(x > 0.0063636, 0.4292962 * np.log10(7.2818453 * np.maximum(x, 0.0063636) + 0.2367946) + 0.3021497,
                    4.9676965 * x + 0.0353847)


def forged(asset, color, gamma):
    """`asset` with its colour / gamma fields changed and the checksum made right again."""
    a = bytearray(asset)
    struct.pack_into('<2I', a, 48, color, gamma)
    struct.pack_into('<I', a, 16, 0)
    struct.pack_into('<I', a, 16, P.fnv(a))
    return bytes(a)


class FilmCurveTests(unittest.TestCase):
    def test_the_published_points(self):
        for x, y in ((0., .03539), (.18, .38356), (1., .67827), (5.766130431, 1.)):
            with self.subTest(x=x):                       # the points are given to five places
                self.assertAlmostEqual(float(C.transfer(x, 'bmd-film')), y, delta=6e-6)

    def test_the_formula_both_ways_and_the_toe_line_below_black(self):
        x = np.r_[np.linspace(-128, 0, 257), np.geomspace(1e-6, 128, 2000), .0063636, .0063637]
        y = C.transfer(x, 'bmd-film')
        np.testing.assert_allclose(y, film(x), atol=1e-12, rtol=0)
        self.assertAlmostEqual(float(C.transfer(-.01, 'bmd-film')), 4.9676965 * -.01 + .0353847, delta=1e-12)
        # the two branches meet within 1.1e-4 at the cut (the fit's own step), so the round trip is that good there
        np.testing.assert_allclose(C.transfer(y, 'bmd-film', inverse=True), x, atol=3e-5, rtol=2e-9)
        # the stated formula is not continuous at the cut: the log branch starts 1.05e-4 (0.11 of a 10-bit code) below
        # where the line ends, so the curve steps down there once and rises everywhere else
        step = float(C.transfer(.0063636, 'bmd-film') - C.transfer(np.nextafter(.0063636, 1), 'bmd-film'))
        self.assertTrue(1.0e-4 < step < 1.1e-4, step)
        d = np.diff(C.transfer(np.sort(x), 'bmd-film'))
        self.assertEqual(int((d < 0).sum()), 1); self.assertGreater(d.min(), -1.1e-4)

    @unittest.skipUnless(RESOLVE_TABLE.exists(), 'DaVinci Resolve is not installed here; skipped is unverified')
    def test_against_resolves_own_table(self):
        rows = [line.split() for line in RESOLVE_TABLE.read_text().splitlines()
                if re.fullmatch(r'\s*-?[\d.]+(e[+-]?\d+)?(\s+-?[\d.]+(e[+-]?\d+)?){2}\s*', line, re.I)]
        linear = np.array(rows, float)[:, 0]
        self.assertEqual(len(linear), 4096)
        self.assertAlmostEqual(linear[0], -.0071215555, delta=1e-9)
        self.assertAlmostEqual(linear[-1], 5.766130431, delta=1e-8)
        code = np.arange(4096) / 4095.
        self.assertLess(np.abs(C.transfer(linear, 'bmd-film') - code).max() * 1023, .11)   # the fit: 0.10 of a 10-bit code


class SensorGamutTests(unittest.TestCase):
    def test_the_matrix_is_lvb_xyz_and_its_inverse_makes_the_identity(self):
        text = (HERE / 'native/lvb.c').read_text()
        body = text[text.index('static void lvb_xyz('):]
        rows = re.findall(r'out\[\d\] = \(i32\)\(\((-?\d+) \* r ([+-]) (\d+) \* g ([+-]) (\d+) \* b\) >> 20\);', body)[:3]
        sign = lambda s, v: int(v) * (-1 if s == '-' else 1)   # noqa: E731
        self.assertEqual(tuple((int(a), sign(s1, b), sign(s2, c)) for a, s1, b, s2, c in rows), C.FP_SENSOR_XYZ_Q20)
        np.testing.assert_array_equal(C.to_xyz_matrix('fp-sensor'), np.array(C.FP_SENSOR_XYZ_Q20) / 2. ** 20)
        np.testing.assert_allclose(C.from_xyz_matrix('fp-sensor') @ C.FP_SENSOR_XYZ, np.eye(3), atol=1e-14)
        # as the asset holds it (Q20): camera RGB -> XYZ -> Blackmagic within 1.5e-6 of the identity
        asset = P.asset(P.identity())
        stored = np.frombuffer(asset, '<i4', 9, P.HEADER + 9 * 4 * list(COLOR_SPACES).index(BMD)).reshape(3, 3) / P.Q
        self.assertLess(np.abs(stored @ C.FP_SENSOR_XYZ - np.eye(3)).max(), 1.5e-6)

    def test_the_reference_render_is_the_film_curve_on_camera_rgb_then_the_cube(self):
        cube = Cube.parse(make_cube(n=5, fn=LOOK))
        got, _ = Monitor(cube, BMD, input_gamma=FILM).evaluate_xyz(RGB @ C.FP_SENSOR_XYZ.T)
        # float throughout: only the matrix inverse's rounding (1e-14 of the value) times the curve's and the
        # cube's slopes is left
        np.testing.assert_allclose(got, cube.apply(film(RGB)), atol=1e-11, rtol=0)


class MenuAndAssetTests(unittest.TestCase):
    def test_film_is_the_one_blackmagic_gamma_and_extended_video_is_gone(self):
        self.assertEqual(BLACKMAGIC_GAMMAS, (FILM,))
        self.assertNotIn('blackmagic-extended-video', GAMMAS)
        self.assertEqual(LEGACY_GAMMAS, {'blackmagic-extended-video': FILM})
        self.assertTrue(Selection(BMD, FILM).numerical_reference_available)
        self.assertEqual((Selection(BMD, FILM).encoding().gamut, Selection(BMD, FILM).encoding().curve), ('fp-sensor', 'bmd-film'))
        for color in COLOR_SPACES:
            for gamma in GAMMAS:
                with self.subTest(color=color, gamma=gamma):
                    if (color == BMD) == (gamma == FILM):
                        Selection(color, gamma)
                    else:
                        self.assertRaises(ValueError, Selection, color, gamma)
        menu = catalogue()
        self.assertEqual(menu['pending_models'], ['Resolve CinemaDNG Rec.709 gamma'])
        self.assertEqual([g['id'] for g in menu['blackmagic_gammas']], [FILM])
        words = P.strings()
        self.assertEqual(len(words), 125)                                  # native/lut4.c sup_entry: the indices stay
        self.assertEqual((words[20], words[21], words[91], words[92]),
                         ('Blackmagic Design Film', '', FILM, 'blackmagic-extended-video'))

    def test_the_asset_has_a_seventh_curve_and_the_other_models_are_the_bytes_they_were(self):
        a = P.asset(P.identity())
        curves = P.HEADER + 8 * 9 * 4
        self.assertEqual((P.CURVES, struct.unpack_from('<I', a, 44)[0]), (7, curves + 7 * 2 * P.CURVE_N * 4))
        # 0.1.1test's asset (six curves), the same cube: sha-256 of its seven matrices other than Blackmagic's and
        # of its six curves -- taken from that version's build_sup.asset() before this change
        matrices = b''.join(a[P.HEADER + 36 * i:P.HEADER + 36 * (i + 1)] for i in range(8) if i != 2)
        self.assertEqual(hashlib.sha256(matrices).hexdigest(), OLD_MATRICES)
        self.assertEqual(hashlib.sha256(a[curves:curves + 6 * 2 * P.CURVE_N * 4]).hexdigest(), OLD_CURVES)
        six = np.frombuffer(a, '<i4', 6 * 2 * P.CURVE_N, curves).reshape(6, 2, -1)
        self.assertFalse((six[:, 0, 0] + six[:, 1, 0]).any())            # odd about black: lut4.c curve() at 0 gives 0, as before
        grid = np.r_[[(1 << e) * (1 + np.arange(256) / 256) / P.Q for e in range(27)]].reshape(-1)
        grid = np.r_[grid, 128.]
        seventh = np.frombuffer(a, '<i4', 2 * P.CURVE_N, curves + 6 * 2 * P.CURVE_N * 4).reshape(2, -1)
        np.testing.assert_array_equal(seventh[0], np.rint(film(grid) * P.Q))
        np.testing.assert_array_equal(seventh[1], np.rint(film(-grid) * P.Q))
        self.assertLessEqual(abs((int(seventh[0, 0]) + int(seventh[1, 0])) // 2 - film(0.) * P.Q), 1)   # curve() at black: Film's toe
        b = P.asset(P.identity(), BMD, FILM)
        self.assertEqual(struct.unpack_from('<2I', b, 48), (2, 6))
        self.assertEqual(a[P.HEADER:], b[P.HEADER:])                       # the tables do not depend on the selection

    def test_a_saved_extended_video_reads_as_film_on_the_host(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'Old.cube'
            path.write_bytes(b'# FPSUP_INPUT_COLOR_SPACE blackmagic-design\n# FPSUP_INPUT_GAMMA blackmagic-extended-video\n' + make_cube(2))
            self.assertEqual(L.author_settings(Cube.read(path))['input_gamma'], FILM)
            doc = L.import_cubes(L.blank(), [path])
            entry = doc['luts'][0]
            entry['author'] = {}
            entry['overrides'] = dict(input_space=BMD, input_gamma='blackmagic-extended-video')   # an older library.json
            value = L.resolved(entry)
            self.assertEqual((value['input_gamma'], value['configured'], value['model_available']), (FILM, True, True))
            layers, _ = L.layer_fields(entry)
            self.assertEqual(layers[6], L.GAMMAS_ALL.index(FILM))
            self.assertEqual(struct.unpack_from('<4I', L.binary(doc), L.HEADER + 96)[1:3], (2, 0))


OLD_MATRICES = '2234cb90e2f84325e42216d67c2dfd628a434d03f3dfdb0a0564539c969b1da0'
OLD_CURVES = 'f24a841524d8cbda37f21f23feef79e42e82b020478c48cb93a0779f96f96960'


@unittest.skipUnless(NATIVE, 'requires Unicorn and firmware image; skipped is unverified')
class NativeModelTests(unittest.TestCase):
    """The reference build (one prepared asset, no library): supported() and the running selection."""
    @classmethod
    def setUpClass(cls):
        cls.sup, cls.facts = P.build_sup(N.MUTANT_SOURCE or P.SOURCE)
        cls.boot = P.B.boot_card(slim=True)
        cls.cube = Cube.parse(make_cube(n=5, fn=LOOK))

    def cam(self, asset):
        return N.Camera(self.sup, asset, boot=self.boot)

    def test_supported_takes_blackmagic_with_film_alone(self):
        base = P.asset(P.identity())
        for color in range(9):
            for gamma in range(9):
                want = color < 8 and (gamma == 6 if color == 2 else gamma < 6 and gamma != 4)
                with self.subTest(color=color, gamma=gamma):
                    c = self.cam(forged(base, color, gamma))
                    self.assertEqual(c.status()['asset'], 0 if want else -11)
                    if want:                                   # the running gamma: within the colour's own list
                        self.assertEqual((c.status()['color'], c.status()['gamma'], c.status()['model']),
                                         (color, 0 if color == 2 else gamma, 0))
        c = self.cam(base)                                     # an asset right but for its last byte: refused (the check checks)
        self.assertEqual(self.cam(base[:-1] + bytes([base[-1] ^ 1])).status()['asset'], -11)
        self.assertEqual(c.status()['asset'], 0)

    def test_the_running_selection_is_film_or_refused(self):
        c = self.cam(P.asset(P.identity()))
        self.assertEqual(c.invoke(3, 2, 0), 0)
        self.assertEqual((c.status()['color'], c.status()['gamma'], c.status()['model']), (2, 0, 0))
        self.assertEqual(c.invoke(3, 2, 1), -3)                # there is no second Blackmagic Gamma
        for color in range(8):
            if color != 2:
                self.assertEqual(c.invoke(3, color, 6), -3)    # ... and Film is no other colour's
        self.assertEqual(c.invoke(3, 6, 4), -12)               # Rec.709's Gamma: still no model

    def test_the_arm_render_is_the_film_curve_on_camera_rgb_then_the_cube(self):
        c = self.cam(P.asset(self.cube, BMD, FILM))
        self.assertEqual((c.status()['asset'], c.status()['color'], c.status()['gamma']), (0, 2, 0))
        rc, actual = c.render(RGB @ C.FP_SENSOR_XYZ.T)
        self.assertEqual(rc, 0)
        # 4e-5 as the other models' test (Q20 samples, matrix, curve table, nodes); the net matrix's own part
        # is under 1.5e-6 of the value (SensorGamutTests)
        np.testing.assert_allclose(actual, self.cube.apply(film(RGB)), atol=4e-5, rtol=0)
        self.assertEqual(c.invoke(3, 6, 1), 0)                 # another model on the same asset: as before
        expected, _ = Monitor(self.cube, 'rec709', input_gamma='gamma24').evaluate_xyz(RGB @ C.FP_SENSOR_XYZ.T)
        rc, actual = c.render(RGB @ C.FP_SENSOR_XYZ.T)
        self.assertEqual(rc, 0); np.testing.assert_allclose(actual, expected, atol=4e-5, rtol=0)


BMD_AUTHOR = '# FPSUP_INPUT_COLOR_SPACE blackmagic-design\n# FPSUP_INPUT_GAMMA blackmagic-film\n'


@unittest.skipUnless(NATIVE, 'requires Unicorn and firmware; skipped is unverified')
class NativeImportTests(IN.ImportNativeTests):
    """A Blackmagic cube copied to the card: the camera's own asset, its render, and an older LUT.BIN."""
    def test_the_camera_builds_the_hosts_exact_asset_for_blackmagic_film(self):
        it = iter(np.random.default_rng(11).uniform(-.25, 1.25, (9 ** 3, 3)))
        files = {'Film9.cube': BMD_AUTHOR.encode() + IN.cube_text(9, lambda r, g, b: next(it), fmt='{:.9f}'),
                 'Old.cube': BMD_AUTHOR.replace('blackmagic-film', 'blackmagic-extended-video').encode() + IN.cube_text(3),
                 'Plain.cube': IN.AUTHOR.encode() + IN.cube_text(3)}
        c = self.cam(files)
        lib = c.library()
        self.assertEqual({e['name']: (e['color'], e['gamma'], e['author'][2]) for e in lib},
                         {'Film9.cube': (2, 0, 6), 'Old.cube': (2, 0, 6), 'Plain.cube': (6, 1, 1)})   # the retired name: Film
        c.open_color()
        for i, e in enumerate(lib):
            with self.subTest(e['name']):
                c.choose(e['name'], 1)
                model = (BMD, FILM) if e['color'] == 2 else ('rec709', 'gamma24')
                host = self.host_asset(files[e['name']], *model)
                self.assertEqual(struct.unpack_from('<2I', host, 48), (2, 6) if e['color'] == 2 else (6, 1))
                self.same_asset(self.camera_asset(c, i), host)
                c.choose(e['name'], 0)

    def test_a_picked_blackmagic_cube_renders_as_the_reference(self):
        data = BMD_AUTHOR.encode() + IN.cube_text(5, LOOK)
        c = self.cam({'Look.cube': data})
        self.on(c, 'Look.cube')
        self.assertEqual(c.invoke(8, 0), 0)
        self.assertEqual((c.status()['color'], c.status()['gamma'], c.status()['model']), (2, 0, 0))
        rc, actual = c.render(RGB @ C.FP_SENSOR_XYZ.T)
        self.assertEqual(rc, 0)
        np.testing.assert_allclose(actual, Cube.parse(data).apply(film(RGB)), atol=4e-5, rtol=0)

    def test_the_settings_page_lists_film_alone(self):
        c = self.cam({'Plain.cube': IN.cube_text(2)})
        c.open_color(); c.edit('Plain.cube'); c.choose('Color space', 2)
        self.assertEqual((c.vars['LC_GammaX'][1], c.vars['LC_GammaM'][1]), (1, 0))
        self.assertEqual(c.find_row('Gamma')[1]['A'], 'Setup required')       # as before: the Gamma is the user's to pick
        c.choose('Gamma', 0)
        self.assertEqual(c.find_row('Gamma')[1]['A'], 'Blackmagic Design Film')
        rows = c.csv_models['LC_GAMMA_BMD'].decode('utf-8-sig').split('\r\n')[1:-1]
        self.assertEqual([r.split(',')[1] for r in rows], ['Blackmagic Design Film'])
        c.press(70)
        e = c.library()[0]
        self.assertEqual((e['color'], e['gamma'], e['user'][:3]), (2, 0, (L.SPACE_SET | L.GAMMA_SET, 2, 6)))

    def test_a_library_saved_with_extended_video_loads_as_film(self):
        """LUT.BIN from before 2026-11-18: the user's Gamma 7, the effective one 1 within Blackmagic's list."""
        c = self.cam({'Plain.cube': IN.cube_text(2), 'Other.cube': IN.AUTHOR.encode() + IN.cube_text(3)})
        c.open_color(); c.edit('Plain.cube'); c.choose('Color space', 2); c.choose('Gamma', 0); c.press(70)
        c.choose('Plain.cube', 1); c.choose('Other.cube', 1)
        files = {p: b for p, b in dict(c.files, **c.written).items() if p not in getattr(c, 'synth', ())}
        data = bytearray(files[LN.BIN])
        off = struct.unpack_from('<I', data, 76)[0]
        count = struct.unpack_from('<I', data, off + 16)[0]
        i = next(k for k in range(count) if data[off + 64 + L.RECORD * k + 32:].startswith(b'Plain.cube\0'))
        p = off + 64 + L.RECORD * i
        self.assertEqual(struct.unpack_from('<2I', data, p + 100), (2, 0))
        self.assertEqual(struct.unpack_from('<I', data, p + 128 + 28)[0], 6)
        struct.pack_into('<I', data, p + 104, 1)                   # gamma: the second of Blackmagic's two
        struct.pack_into('<I', data, p + 128 + 28, 7)              # user_gamma: Extended Video
        struct.pack_into('<I', data, off + 24, L.checksum(data[off:off + 64 + L.RECORD * count]))
        files[LN.BIN] = bytes(data)
        again = IN.Camera(files, self.ar)
        again.open_color()
        self.assertEqual(set(again.current_rows()), {'Plain.cube', 'Other.cube'})   # not a refused library
        self.assertEqual(again.find_row('Plain.cube')[1]['TOn'], 1)                 # still enabled
        j = next(k for k, e in enumerate(again.library()) if e['name'] == 'Plain.cube')
        self.assertEqual(again.invoke(8, j), 0)                                      # and it can be picked
        self.assertEqual((again.status()['color'], again.status()['gamma'], again.status()['model']), (2, 0, 0))
        e = again.library()[j]                                                       # the pick saved LUT.BIN
        self.assertEqual((e['color'], e['gamma'], e['user'][:3]), (2, 0, (L.SPACE_SET | L.GAMMA_SET, 2, 6)))
        again.edit('Plain.cube')
        self.assertEqual(again.find_row('Gamma')[1]['A'], 'Blackmagic Design Film')


@unittest.skipUnless(NATIVE, 'requires Unicorn and firmware; skipped is unverified')
class NativeConversionTests(unittest.TestCase):
    """The user's report was "cannot convert": the conversion itself, for a Blackmagic Design / Film cube."""
    @classmethod
    def setUpClass(cls):
        import test_conv_native as CV
        cls.CV = CV
        cls.base = type('Base', (CV.ConvNativeTests,), {})
        cls.base.setUpClass()
        hard = lambda r, g, b: (r * (0.7 + 0.3 * g), g * (0.9 + 0.1 * b) + 0.05 * r * b, b * (0.5 + 0.5 * r))   # noqa: E731
        cls.path = cls.base.root / 'lvb' / 'F.cube'
        cls.path.write_bytes(BMD_AUTHOR.encode() + make_cube(9, fn=hard))
        cls.doc = L.configure(L.import_cubes(cls.base.ldoc, [cls.path]), 'F.cube', enabled=True)
        cls.files = LN.with_library(cls.base.files, cls.doc)

    @classmethod
    def tearDownClass(cls): cls.base.tearDownClass()

    def test_a_blackmagic_cube_converts_and_its_targets_are_the_direct_formula(self):
        CV = self.CV
        c = CV.Camera(self.files, self.base.ar)
        c.stubs_on = True
        st = c.conv(); c.put(st['at'] + 4 * 11, 1)                       # conv.iters = 1, as test_conv_native
        i = [e['filename'] for e in self.doc['luts']].index('F.cube'); e = self.doc['luts'][i]
        c.manager()
        row = c.find_row('F.cube')[1]
        self.assertEqual((row['A'].strip(), row['TOn'], row['TOff']), ('', 0, 1))   # set up, not converted: plain Off
        c.choose('F.cube', 1)
        st = c.conv()
        self.assertEqual((st['state'], st['index'], st['err']), (1, i, 0))          # it starts (it was refused before)
        c.run_worker()
        st = c.conv()
        self.assertEqual((st['state'], st['pct'], st['err']), (2, 100, 0))
        c.notify('LC_Key', 90)
        st = c.conv()
        self.assertEqual((st['state'], st['done'], st['last']), (0, 1, 0))
        import jft
        key = L.record_identity(e)
        data = c.files['\\' + jft.path_for(key.hex()).replace('/', '\\')]
        u = jft.unpack(data)                                                # magic, size, fnv
        self.assertEqual(u['key'], (key[:8], 2, 0, 100, 1))                 # Blackmagic Design, its Gamma 0 (Film)
        self.assertEqual(c.clist()['n'], 1)                                 # its COLOR row is there
        # what it fitted to: the cube on the Film curve of the camera's own samples -- no matrix in between
        cube = Cube.read(self.path)
        for name, n in (('want', CV.N), ('chkw', CV.NCHK)):
            xs = c.floats('xs' if name == 'want' else 'chk', 3 * n).reshape(-1, 3)
            host = CV.F.lab709(np.clip(cube.apply(film(xs)), 0, 1))
            d = np.linalg.norm(c.floats(name, 3 * n).reshape(-1, 3) - host, axis=1)
            self.assertLess(d.mean(), .05, name); self.assertLess(d.max(), .5, name)   # dE, as test_conv_native's bound
        self.assertEqual(c.invoke(8, i), 0)                                 # and it can be picked
        self.assertEqual((c.status()['color'], c.status()['gamma'], c.status()['model']), (2, 0, 0))


# the parent's own tests run in test_import_native; here only the ones above
for _name in [n for n in dir(IN.ImportNativeTests) if n.startswith('test_')]:
    setattr(NativeImportTests, _name, None)


if __name__ == '__main__':
    unittest.main()
