"""Any .cube copied to \\fpSup\\LUT\\, imported on the camera (native/import.c), offline.

The ARM code lists the folder (the harness models the firmware's dir API, as
for the loader), parses the text with integers alone and must produce
build_sup.asset()'s bytes exactly (but its identity, which the camera derives
from the file's size and name, and the checksum over it).  No claim about the
camera's SD speed for a 65^3 cube, or dates in the identity (the model has none).
"""
import struct
import unittest

import numpy as np

import build_sup as P
import library as L
import test_library_native as LN
import test_sup_native as N
import test_sup_ui as U
from cube import Cube
from monitor import Monitor

FOLDER = '\\fpSup\\LUT\\'


class Camera(LN.Camera):                     # LN.Camera lists \\fpSup\\LUT\\ (LN.folder_entries)
    def lut_block(self):
        """The sup's block: its state minus cfg.state_off (LUT.BIN config, after the 48-byte header)."""
        _api, state = self.lut()
        return state - struct.unpack_from('<I', self.files[LN.BIN], 48 + 4)[0]

    def library(self):
        """The saved library (LUT.BIN as written, else as it was)."""
        data = self.written.get(LN.BIN, self.files[LN.BIN])
        off = struct.unpack_from('<I', data, 76)[0]
        count = struct.unpack_from('<I', data, off + 16)[0]
        out = []
        for i in range(count):
            p = off + 64 + L.RECORD * i
            name = data[p + 32:p + 96].split(b'\0')[0].decode()
            flags, color, gamma, amount = struct.unpack_from('<4I', data, p + 96)
            origin = struct.unpack_from('<I', data, p + 124)[0]
            layers = struct.unpack_from('<9I', data, p + 128)      # matrix, author x5, user x3 (library.layer_fields)
            cm = list(struct.unpack_from('<18i', data, p + 176))
            out.append(dict(name=name, flags=flags, color=color, gamma=gamma, amount=amount, origin=origin,
                            matrix=layers[0], author=layers[1:5], user=layers[5:9], cm=cm,
                            user_matrix=struct.unpack_from('<I', data, p + 160)[0]))
        return out


def cube_text(n=2, fn=lambda r, g, b: (r, g, b), head='', fmt='{:.6f}', eol='\n', bom=False):
    rows = []
    axis = np.linspace(0, 1, n)
    for b in axis:
        for g in axis:
            for r in axis:
                rows.append(' '.join(fmt.format(v) for v in fn(r, g, b)))
    text = head + f'LUT_3D_SIZE {n}{eol}' + eol.join(rows) + eol
    return (b'\xef\xbb\xbf' if bom else b'') + text.replace('\n', eol).encode()


AUTHOR = '# FPSUP_INPUT_COLOR_SPACE rec709\n# FPSUP_INPUT_GAMMA gamma24\n'


@unittest.skipIf(U.N.T4.Uc is None or not U.N.T3.IMAGE.exists(), 'requires Unicorn and firmware; skipped is unverified')
class ImportNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        from pathlib import Path
        cls.temp = tempfile.TemporaryDirectory(); cls.root = Path(cls.temp.name)
        cls.info = P.build(cls.root / 'card', card=True, debug=True, collection=L.blank())
        cls.files = U.runtime_files(cls.root / 'card'); cls.ar = cls.files['\\AutoRun.txt']

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def cam(self, cubes):
        files = dict(self.files)
        files.update({FOLDER + n: d for n, d in cubes.items()})
        return Camera(files, self.ar)

    def host_asset(self, data, color='rec709', gamma='gamma24', strength=100):
        return P.asset(Cube.parse(data), color, gamma, strength)

    def on(self, c, *names):
        c.open_color()
        for n in names:
            c.choose(n, 1)

    def camera_asset(self, c, index):
        before = len(getattr(c, 'borrow_log', []))
        self.assertEqual(c.invoke(8, index), 0, 'pick')
        # the pick parses the cube into a borrowed area (native/borrow.c) and returns it: the asset
        # is the snapshot the allocator model took as it came back (cfg asset_off is 0 now)
        self.assertEqual(struct.unpack_from('<I', c.files[LN.BIN], 48 + 12)[0], 0)
        got = [q for k, q, n in c.borrow_log[before:] if k == 'get' and n >= P.CAPACITY]
        self.assertIn(len(got), (1, 2))                             # the pick's load (+ the row's fit: 11-10, a set is made at its pick)
        out = N.borrows(c)[2]
        self.assertTrue(all(25984 <= m < 32768 for m in out.values()), out)   # nothing kept but the shown row's ISP set
        snap = next(b for q, m, b in reversed(c.borrow_freed) if q == got[0])
        a = ((got[0] + 63) & ~63) - got[0]                          # borrow.c: the first whole line
        total = struct.unpack_from('<I', snap, a + 12)[0]
        return snap[a:a + total]

    def same_asset(self, cam, host):
        def strip(b):
            b = bytearray(b); b[16:20] = bytes(4); b[136:168] = bytes(32); return bytes(b)
        self.assertEqual(len(cam), len(host))
        if strip(cam) != strip(host):
            diff = next(i for i in range(len(cam)) if strip(cam)[i] != strip(host)[i])
            self.fail(f'asset differs at {diff}: cam {cam[diff - 4:diff + 8].hex()} host {host[diff - 4:diff + 8].hex()}')

    def test_copied_cubes_become_entries_and_author_comments_preset_them(self):
        c = self.cam({'Look_A.cube': (AUTHOR + 'TITLE "A"\n').encode() + cube_text(), 'Plain.cube': cube_text(),
                      '._Look_A.cube': b'\0' * 4096, 'notes.txt': b'x'})
        lib = c.library()
        self.assertEqual([e['name'] for e in lib], ['Look_A.cube', 'Plain.cube'])
        self.assertEqual([(e['origin'], e['flags'], e['color'], e['gamma']) for e in lib],
                         [(1, 14, 6, 1), (1, 8, 6, 0)])
        c.open_color()
        self.assertEqual(c.find_row('Plain.cube')[1]['A'], 'Setup required')
        self.assertEqual(c.find_row('Look_A.cube')[1]['A'], ' ')

    def test_the_camera_parses_a_cube_into_the_hosts_exact_asset(self):
        rng = np.random.default_rng(7)
        table = rng.uniform(-0.25, 1.25, (17 ** 3, 3))
        it = iter(table)
        cases = {
            'Rand17.cube': (AUTHOR, cube_text(17, lambda r, g, b: next(it), fmt='{:.9f}')),
            'Crlf.cube': (AUTHOR, cube_text(5, lambda r, g, b: (r * .9, g ** 2, 1 - b), eol='\r\n', bom=True)),
            'Expo.cube': (AUTHOR, cube_text(3, lambda r, g, b: (r, g, b), fmt='{:.3e}')),
            'Domain.cube': (AUTHOR + 'DOMAIN_MIN -0.1 0 0\nDOMAIN_MAX 1.5 2 1\n', cube_text(3)),
        }
        shaper = (AUTHOR + 'TITLE "has # inside"\nLUT_1D_SIZE 4\nLUT_3D_SIZE 2\n'
                  'LUT_1D_INPUT_RANGE -0.25 1.75\nLUT_3D_INPUT_RANGE 0 1\n')
        shaper += ''.join(f'{v:.5f} {v * v:.5f} {1 - v:.5f}\n' for v in np.linspace(0, 1, 4))
        files = {n: (h.encode() + body) for n, (h, body) in cases.items()}
        files['Crlf.cube'] = b'\xef\xbb\xbf' + AUTHOR.replace('\n', '\r\n').encode() + \
            cube_text(5, lambda r, g, b: (r * .9, g ** 2, 1 - b), eol='\r\n')     # BOM first, CRLF lines
        files['Shaper.cube'] = shaper.encode() + b'\n'.join(cube_text(2).split(b'\n')[1:])
        c = self.cam(files)
        c.open_color()
        for i, e in enumerate(c.library()):              # one on at a time: the cap is 4
            with self.subTest(e['name']):
                c.choose(e['name'], 1)
                self.same_asset(self.camera_asset(c, i), self.host_asset(files[e['name']]))
                c.choose(e['name'], 0)

    def test_a_picked_cube_renders_as_the_reference(self):
        data = (AUTHOR).encode() + cube_text(5, lambda r, g, b: (r * .8 + .1, g, b ** .5))
        c = self.cam({'Look.cube': data})
        self.on(c, 'Look.cube')
        self.assertEqual(c.invoke(8, 0), 0)
        xyz = np.array([[.1, .2, .3], [.18, .18, .18], [.5, .4, .2]])
        rc, actual = c.render(xyz)
        expected, _ = Monitor(Cube.parse(data), 'rec709', input_gamma='gamma24').evaluate_xyz(xyz)
        self.assertEqual(rc, 0); np.testing.assert_allclose(actual, expected, atol=4e-5, rtol=0)

    def test_a_malformed_cube_is_refused_and_a_removed_one_is_gone(self):
        good = AUTHOR.encode() + cube_text(2)
        bad = AUTHOR.encode() + cube_text(2)[:-12]            # a row short
        c = LN.without_jft(lambda: self.cam({'Good.cube': good, 'Bad.cube': bad}), 'Bad.cube')   # malformed: never converted
        self.on(c, 'Good.cube', 'Bad.cube')
        names = [e['name'] for e in c.library()]
        self.assertNotEqual(c.invoke(8, names.index('Bad.cube')), 0)
        self.assertEqual(c.invoke(8, names.index('Good.cube')), 0)
        files = dict(c.files); files.update(c.written)
        files.pop(FOLDER + 'Good.cube')
        again = Camera(files, self.ar)
        lib = again.library()
        gone = next(e for e in lib if e['name'] == 'Good.cube')
        self.assertEqual(gone['origin'] & 2, 2)
        self.assertNotEqual(again.invoke(8, names.index('Good.cube')), 0)

    def test_a_cube_copied_while_running_appears_when_the_manager_opens(self):
        c = self.cam({'First.cube': AUTHOR.encode() + cube_text(2)})
        c.files[FOLDER + 'Second.cube'] = AUTHOR.encode() + cube_text(3)
        c.page_entries()                               # the card's folder now
        c.open_color()
        self.assertEqual(set(c.current_rows()), {'First.cube', 'Second.cube'})
        self.assertEqual([e['name'] for e in c.library()], ['First.cube', 'Second.cube'])
        self.assertEqual(c.misaligned, [])                       # the dir API from the row's open

    def test_a_camera_written_library_loads_on_the_next_boot_whatever_the_stack_held(self):
        # 2026-11-03 camera: the dir scan's name buffer is stack; bytes left after
        # the NUL went into the entry, and the next boot refused the whole
        # library (name[63] != 0) -- no claims, "No LUT files".  Unicorn's stack
        # starts zeroed, so dirty it the way the camera's is.
        c = self.cam({'First.cube': AUTHOR.encode() + cube_text(2)})
        T3 = U.N.T3
        c.mu.mem_write(T3.STACK - 0x10000, b'\xc3' * 0x10000)
        c.files[FOLDER + 'Demo_709.cube'] = AUTHOR.encode() + cube_text(2)
        c.page_entries(); c.open_color()
        data = c.written[LN.BIN]
        off = struct.unpack_from('<I', data, 76)[0]
        for i in range(struct.unpack_from('<I', data, off + 16)[0]):
            name = data[off + 64 + L.RECORD * i + 32:off + 64 + L.RECORD * i + 96]
            self.assertEqual(name[name.index(b'\0'):], bytes(64 - name.index(b'\0')), name)
        files = dict(c.files); files.update(c.written)
        again = Camera(files, self.ar)
        again.open_color()
        self.assertEqual(set(again.current_rows()), {'First.cube', 'Demo_709.cube'})

    def test_author_color_matrix_layer_is_the_hosts(self):
        """user 2026-11-03: a LUT names the DNG matrix it was made on; custom ones in its comments."""
        m1 = '# FPSUP_COLOR_MATRIX1 0.6 -0.1 -0.05 -0.4 1.2 0.2 -0.1 0.2 0.55\n'
        m2 = '# FPSUP_COLOR_MATRIX2 .5 -6.25e-2 -0.05 -0.4 1.25E0 0.2 -0.1 +0.2 0.123456789\n'
        cases = {'Both.cube': 'TITLE "x"\n# FPSUP_COLOR_MATRIX custom\n' + m1 + m2,
                 'One.cube': AUTHOR + m2.replace('\n', '\r\n'),
                 'OneA.cube': AUTHOR + m1,
                 'Off.cube': AUTHOR + '# FPSUP_COLOR_MATRIX off\n',
                 'Bad.cube': AUTHOR + '# FPSUP_COLOR_MATRIX custom\n# FPSUP_COLOR_MATRIX1 1 0 0 0 1 0 0 0\n',
                 'Huge.cube': AUTHOR + '# FPSUP_COLOR_MATRIX1 17 0 0 0 1 0 0 0 1\n'}
        files = {n: h.encode() + cube_text(2) for n, h in cases.items()}
        lib = {e['name']: e for e in self.cam(files).library()}
        for name in ('Both.cube', 'One.cube', 'OneA.cube', 'Off.cube'):
            with self.subTest(name):
                author = L.author_settings(Cube.parse(files[name]))
                doc = dict(author=author, overrides={})
                e = lib[name]; layers, cm = L.layer_fields(doc)
                self.assertEqual(e['author'], layers[:4])
                self.assertEqual(e['cm'], cm[0] + cm[1])
                self.assertEqual(e['matrix'], L.MATRICES.index(L.resolved(doc)['color_matrix']))
                self.assertEqual(e['flags'] & L.MATRIX_SET, L.MATRIX_SET)
        for name in ('One.cube', 'OneA.cube'):                  # one illuminant fills both
            self.assertEqual(lib[name]['cm'][:9], lib[name]['cm'][9:])
        for name in ('Bad.cube', 'Huge.cube'):                  # host refuses them; the camera shows Setup required
            with self.subTest(name):
                self.assertEqual(lib[name]['flags'] & L.MATRIX_SET, 0)
                self.assertEqual(lib[name]['author'][0] & L.AUTH_CUSTOM, 0)

    def test_user_choice_is_kept_apart_from_the_author_and_survives_an_author_edit(self):
        c = self.cam({'Look.cube': AUTHOR.encode() + cube_text(2)})
        c.open_color(); c.edit('Look.cube'); c.choose('Color space', 4); c.choose('Gamma', 2); c.press(70)
        e = c.library()[0]
        self.assertEqual(e['author'], (L.SPACE_SET | L.GAMMA_SET, 6, 1, 0))          # the designer's, untouched
        self.assertEqual(e['user'][:3], (L.SPACE_SET | L.GAMMA_SET, 4, 2))
        self.assertEqual((e['color'], e['gamma']), (4, 2))
        self.assertEqual(c.cube_writes, 0)
        # the author edits the file: the author layer follows, the user's choice still wins
        c.files[FOLDER + 'Look.cube'] = (AUTHOR.replace('rec709', 'srgb').replace('gamma24', 'gamma26') +
                                         '# FPSUP_COLOR_MATRIX off\n').encode() + cube_text(2)
        c.page_entries(); c.open_color()
        e = c.library()[0]
        self.assertEqual(e['author'], (L.READY, 7, 2, 1))
        self.assertEqual((e['color'], e['gamma'], e['matrix']), (4, 2, 1))
        # choosing the author's own value clears that override
        c.edit('Look.cube'); c.choose('Gamma', 2); c.choose('Color space', 7); c.press(70)
        e = c.library()[0]
        self.assertEqual(e['user'][0], 0)
        self.assertEqual((e['color'], e['gamma']), (7, 2))
        files = dict(c.files); files.update(c.written)
        again = Camera(files, self.ar).library()[0]
        self.assertEqual((again['author'], again['user'][0], again['color']), (e['author'], 0, 7))

    def test_settings_of_a_copied_cube_are_saved_in_lut_bin_and_kept(self):
        c = self.cam({'Plain.cube': cube_text(2)})
        c.open_color(); c.edit('Plain.cube'); c.choose('Color space', 4); c.choose('Gamma', 2); c.press(70)
        c.choose('Plain.cube', 1)
        self.assertEqual(c.cube_writes, 0)                       # the user's file is not touched
        e = c.library()[0]
        self.assertEqual((e['color'], e['gamma'], e['flags']), (4, 2, 15))
        files = dict(c.files); files.update(c.written)
        again = Camera(files, self.ar)
        self.assertEqual([(x['name'], x['flags']) for x in again.library()], [('Plain.cube', 15)])
        self.assertEqual(c.misaligned, [])                       # callbacks realign before the firmware's file calls


if __name__ == '__main__':
    unittest.main()
