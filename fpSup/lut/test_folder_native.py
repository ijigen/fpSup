"""The list is the folder (Bei 2026-11-06): only the .cube files in \\fpSup\\LUT\\ show,
offline, on the actual ARM code (native/import.c imp_scan, library4.c).

- a cube whose file went shows nowhere (manager, COLOR list, the API's indices);
  its record stays in LUT.BIN, hidden, and its settings come back with the file;
- a full catalog reuses a hidden record before giving up on a new file;
- an older card's built-in / computer-prepared records (origin 0) are gone;
- the scan passes over sub-folders (an older card's SOURCES\\, JFIT\\, DATA\\) and
  other files; the sup's own files are under \\fpSup\\LUTDATA\\;
- a library build_sup is given reaches the camera as it keeps it (same identity:
  no write at boot).

The dir API is test_v3's model (no dates, so library.camera_identity's zero dates
are the camera's here); SD behaviour and a real card's FAT are not covered.
"""
import struct
import tempfile
import unittest
from pathlib import Path

import build_sup as P
import library as L
import test_clist_native as CN
import test_import_native as IN
import test_library_native as LN
import test_sup_ui as U
from test_import_native import AUTHOR, cube_text

FOLDER = LN.FOLDER
BIN = LN.BIN


class Camera(CN.Camera):
    library = IN.Camera.library                 # the saved catalog: every record, hidden ones too

    def rows(self):
        """The manager's cubes, every page."""
        self.open_color()
        page = self.vars['LC_PageText'][1].strip()
        total = int(page.split('/')[1]) if '/' in page else 1
        names = set()
        for _ in range(total):
            names |= set(self.current_rows())
            self.press(11)
        return names


@unittest.skipIf(U.N.T4.Uc is None or not U.N.T3.IMAGE.exists(), 'requires Unicorn and firmware; skipped is unverified')
class FolderNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.root = Path(cls.temp.name)
        P.build(cls.root / 'card', card=True, debug=True, collection=L.blank())
        cls.files = U.runtime_files(cls.root / 'card'); cls.ar = cls.files['\\AutoRun.txt']

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def cam(self, files, cubes=None):
        files = dict(files)
        files.update({FOLDER + n: d for n, d in (cubes or {}).items()})
        return Camera(files, self.ar)

    @staticmethod
    def saved(c):
        files = dict(c.files); files.update(c.written)
        return files

    def test_a_removed_cube_is_nowhere_and_its_settings_come_back_with_it(self):
        look = AUTHOR.encode() + cube_text(3, lambda r, g, b: (r * .9, g, b))
        other = AUTHOR.encode() + cube_text(2)
        c = self.cam(self.files, {'Look.cube': look, 'Other.cube': other})
        c.open_color(); c.edit('Look.cube'); c.choose('Color space', 4); c.choose('Gamma', 2); c.press(70)
        c.choose('Look.cube', 1); c.choose('Other.cube', 1)
        self.assertEqual(c.invoke(8, 0), 0)                          # Look monitored
        self.assertEqual(c.clist()['n'], 2)
        # the file goes while the camera runs: the manager's next open drops it, the active one is Off
        c.files.pop(FOLDER + 'Look.cube'); c.page_entries()
        self.assertEqual(c.rows(), {'Other.cube'})
        self.assertEqual(c.clist()['n'], 1)
        self.assertNotEqual(c.status()['asset'], 0)
        self.assertNotEqual(c.invoke(8, 1), 0)                       # no index past the folder's cubes
        # ... and after a boot: nothing of it anywhere, its record kept (hidden)
        gone = self.saved(c)
        again = Camera(gone, self.ar)
        self.assertEqual(again.rows(), {'Other.cube'})
        self.assertEqual(again.clist()['n'], 1)
        self.assertNotEqual(again.invoke(8, 1), 0)
        rec = {e['name']: e for e in again.library()}
        self.assertEqual(set(rec), {'Look.cube', 'Other.cube'})
        self.assertEqual(rec['Look.cube']['origin'], L.ORIGIN_CAMERA | L.ORIGIN_GONE)
        self.assertEqual((rec['Look.cube']['color'], rec['Look.cube']['gamma'], rec['Look.cube']['flags']), (4, 2, 15))
        self.assertEqual(rec['Other.cube']['origin'], L.ORIGIN_CAMERA)
        # the same file back: its settings with it (on, P3 D65 / Gamma 2.6); the monitored one stays Off
        back = dict(self.saved(again)); back[FOLDER + 'Look.cube'] = look
        third = Camera(back, self.ar)
        self.assertEqual(third.rows(), {'Look.cube', 'Other.cube'})
        rec = {e['name']: e for e in third.library()}
        self.assertEqual((rec['Look.cube']['origin'], rec['Look.cube']['color'], rec['Look.cube']['gamma'],
                          rec['Look.cube']['flags']), (L.ORIGIN_CAMERA, 4, 2, 15))
        self.assertEqual(rec['Look.cube']['user'][:3], (L.SPACE_SET | L.GAMMA_SET, 4, 2))
        self.assertEqual(third.clist()['n'], 2)
        third.edit('Look.cube')
        self.assertEqual((third.find_row('Color space')[1]['A'], third.find_row('Gamma')[1]['A']), ('P3 D65', 'Gamma 2.6'))
        self.assertEqual(third.cube_writes, 0)

    def test_a_full_catalog_reuses_a_gone_entry_first(self):
        cubes = {f'Look{i:02}.cube': AUTHOR.encode() + cube_text(2) for i in range(L.MAX_LUTS)}
        c = self.cam(self.files, cubes)
        self.assertEqual(len(c.library()), L.MAX_LUTS)
        files = self.saved(c); files.pop(FOLDER + 'Look05.cube')
        files[FOLDER + 'New.cube'] = AUTHOR.encode() + cube_text(2)
        again = Camera(files, self.ar)
        names = [e['name'] for e in again.library()]
        self.assertEqual(len(names), L.MAX_LUTS)
        self.assertIn('New.cube', names); self.assertNotIn('Look05.cube', names)
        self.assertEqual(again.rows(), set(cubes) - {'Look05.cube'} | {'New.cube'})
        # full of present files: a new one waits (nothing present is pushed out)
        more = self.saved(again); more[FOLDER + 'Newer.cube'] = AUTHOR.encode() + cube_text(2)
        third = Camera(more, self.ar)
        self.assertEqual(sorted(e['name'] for e in third.library()), sorted(names))

    def older_card(self):
        """LUT.BIN as an older build saved it: two built-in demo records prepared on a computer (origin 0, one
        active) and one cube the camera found; the folder with that cube and the older layout's files."""
        demo = self.root / 'demo'; demo.mkdir(exist_ok=True)
        paths = []
        for name in ('Demo_709.cube', 'Demo_P3.cube', 'Mine.cube'):
            p = demo / name; p.write_bytes(AUTHOR.encode() + f'TITLE "{name}"\n'.encode() + cube_text(2)); paths.append(p)
        doc = L.import_cubes(L.blank(), paths)
        for name in ('Demo_709.cube', 'Demo_P3.cube', 'Mine.cube'):
            doc = L.configure(doc, name, enabled=True)
        doc = L.configure(doc, 'Demo_P3.cube', active=True)
        blob = bytearray(P.build_sup(collection=doc)[0])
        off = struct.unpack_from('<I', blob, 76)[0]
        for i in (0, 1):                                    # the demos as library.binary wrote them until 11-06
            p = off + L.HEADER + L.RECORD * i
            blob[p:p + 32] = bytes.fromhex(doc['luts'][i]['id'])
            struct.pack_into('<4I', blob, p + 112, 600, 0x1234, 0, 0)
        struct.pack_into('<I', blob, off + 24, L.checksum(blob[off:off + L.HEADER + 3 * L.RECORD]))
        files = {k: v for k, v in self.files.items() if not k.startswith(FOLDER)}
        files[BIN] = bytes(blob)
        files[FOLDER + 'Mine.cube'] = paths[2].read_bytes()
        for n, d in {'SOURCES\\' + doc['luts'][0]['id'] + '.cube': paths[0].read_bytes(),
                     'DATA\\' + doc['luts'][0]['id'][:16] + '.LUT': b'\0' * 300,
                     'JFIT\\' + L.record_identity(doc['luts'][2])[:8].hex() + '.JFT': b'\0' * 64,
                     'ACTIVE.LUT': b'\0' * 300, 'source.cube.bak': b'x', 'settings.json': b'{}', 'menu.json': b'{}'}.items():
            files[FOLDER + n] = d
        return files

    def test_an_older_cards_built_in_luts_are_gone(self):
        files = self.older_card()
        c = Camera(files, self.ar)
        self.assertEqual(c.rows(), {'Mine.cube'})
        self.assertNotEqual(c.status()['asset'], 0)                  # the active demo: Off
        self.assertNotEqual(c.invoke(8, 1), 0)
        self.assertEqual(c.cube_writes, 0)
        self.assertFalse([p for p in c.written if p.startswith(FOLDER)])   # nothing written in the user's folder
        self.assertFalse([p for p in c.opened if '\\JFIT\\' in p or '\\SOURCES\\' in p or '\\DATA\\' in p])
        c.choose('Mine.cube', 0)                                      # any save: the catalog without them
        lib = c.library()
        self.assertEqual([(e['name'], e['origin']) for e in lib], [('Mine.cube', L.ORIGIN_CAMERA)])
        data = c.written[BIN]; off = struct.unpack_from('<I', data, 76)[0]
        self.assertEqual(struct.unpack_from('<2I', data, off + 16), (1, L.NONE))
        self.assertEqual(struct.unpack_from('<I', data, off + 24)[0], L.checksum(data[off:off + L.HEADER + L.RECORD]))
        again = Camera(self.saved(c), self.ar)
        self.assertEqual(again.rows(), {'Mine.cube'})

    def test_the_scan_passes_over_sub_folders_and_other_files(self):
        c = self.cam(self.files, {'Look.cube': AUTHOR.encode() + cube_text(2),
                                  'SOURCES\\0123.cube': AUTHOR.encode() + cube_text(2),
                                  'JFIT\\0123456789abcdef.JFT': b'\0' * 64,
                                  'Folder.cube\\inner.txt': b'a folder named like a cube',
                                  'notes.txt': b'x', 'settings.json': b'{}', 'LOOK.CUBE.txt': b'x'})
        self.assertEqual(sorted(n for n, a, _s in c.dirs[FOLDER[:-1]] if a & 0x10), ['Folder.cube', 'JFIT', 'SOURCES'])
        self.assertEqual([e['name'] for e in c.library()], ['Look.cube'])
        self.assertEqual(c.rows(), {'Look.cube'})

    def test_a_library_reaches_the_camera_as_it_keeps_it(self):
        """build_sup --library: the cubes in the folder and records keyed as the camera keys them -- the first
        boot finds every one by name, with its settings (here no write at all: the model has no dates)."""
        src = self.root / 'lib'; src.mkdir(exist_ok=True)
        a = src / 'Alpha.cube'; a.write_bytes(AUTHOR.encode() + cube_text(2))
        b = src / 'Beta.cube'; b.write_bytes(cube_text(3))
        doc = L.import_cubes(L.blank(), [a, b])
        doc = L.configure(doc, 'Beta.cube', input_space='p3-d65', input_gamma='gamma26', strength_percent=50, enabled=True)
        files = LN.with_library(self.files, doc)
        self.assertEqual(sorted(p for p in files if p.startswith(FOLDER)), [FOLDER + 'Alpha.cube', FOLDER + 'Beta.cube'])
        c = Camera(files, self.ar)
        self.assertNotIn(BIN, c.written)                              # nothing to change
        lib = c.library()
        self.assertEqual([(e['name'], e['origin']) for e in lib], [('Alpha.cube', 1), ('Beta.cube', 1)])
        self.assertEqual((lib[1]['color'], lib[1]['gamma'], lib[1]['amount'], lib[1]['flags']), (4, 2, 50, 15))
        blob = c.files[BIN]; off = struct.unpack_from('<I', blob, 76)[0]
        for i, e in enumerate(doc['luts']):
            p = off + L.HEADER + L.RECORD * i
            self.assertEqual(blob[p:p + 32], L.record_identity(e))
        self.assertEqual(c.rows(), {'Alpha.cube', 'Beta.cube'})


@unittest.skipIf(U.N.T4.Uc is None or not U.N.T3.IMAGE.exists(), 'requires Unicorn and firmware; skipped is unverified')
class CardLayoutTests(unittest.TestCase):
    def test_the_card_has_only_cubes_in_the_users_folder(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / 'Look.cube'; src.write_bytes(AUTHOR.encode() + cube_text(2))
            doc = L.import_cubes(L.blank(), [src])
            P.build(root / 'lib', card=True, collection=doc, info_path=root / 'lib.json')
            P.build(root / 'empty', card=True, collection=L.blank())
            for card, cubes in (('lib', ['Look.cube']), ('empty', [])):
                with self.subTest(card=card):
                    lut = root / card / 'fpSup/LUT'
                    self.assertEqual(sorted(p.name for p in lut.rglob('*')) if lut.exists() else [], cubes)
                    self.assertFalse((root / card / 'fpSup/LUTDATA').exists())   # made on the camera (conv.c), when needed
                    self.assertEqual(list((root / card).rglob('*.json')), [])
            self.assertIn('files', __import__('json').loads((root / 'lib.json').read_text()))
            with self.assertRaises(ValueError):                          # the record does not go on the card
                P.build(root / 'x', card=True, collection=L.blank(), info_path=root / 'x' / 'info.json')
            self.assertFalse((root / 'x').exists())


if __name__ == '__main__':
    unittest.main()
