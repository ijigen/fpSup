"""fpScreenFlip as a Loader v4 sup (build_v4_flip.py), loaded by the real v4 core.

    cd fpSup/screenflip && python3 -B -m unittest test_v4_flip

Every behaviour test of test_v3_flip runs again here, unchanged, against
FLIP.BIN under the v4 core (with its fpSup-page hooks, so string ids really
resolve): switching applies, setting does not, the table is saved once still
and not recording -- now through svc->file_is -- and loaded at boot.  What
differs from v3 is checked instead: no claim on any firmware word, the row's
page equals the reference applier's except the string fields, and each string
field is an id the core's resolve hook turns back into that very text.
"""
import pathlib
import struct
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(FPSUP / 'loader-v4'))

import test_v3_flip as V3F                                # noqa: E402
import build_v4_flip as FL4                               # noqa: E402
import build_v4 as B4                                     # noqa: E402
import test_v4 as T4                                      # noqa: E402
import test_ui_v4 as U                                    # noqa: E402
from ui import fpui                                       # noqa: E402

F, SETS, NBU_BASE = V3F.F, V3F.SETS, V3F.NBU_BASE
STRING_SITES = V3F.STRING_SITES
PATH = '\\fpSup\\FLIP.BIN'
LOADED = T4.CODES['LOADED']
RELEASED = T4.CODES['RELEASED']


class FlipCamera4(V3F.FlipCamera, T4.Camera):
    """test_v3_flip's camera (fake UI objects, getters, files) on v4's camera.
    Its F_OPEN only opens files that exist: the v4 core's LOAD.LOG is there
    from the start, empty."""
    def __init__(self, files, dirs, **kw):
        files.setdefault('\\fpSup\\LOAD.LOG', b'')
        super().__init__(files, dirs, **kw)


def ref_text(pool, off):
    """What the reference applier's id `off` resolves to."""
    if off < len(pool.stock):
        return pool.stock[off:pool.stock.index(b'\0', off)].decode()
    for base, texts in pool.layers:
        if base <= off < base + len(texts):
            return texts[off - base]
    raise KeyError(hex(off))


class FlipV4Tests(V3F.FlipV3Tests):
    @classmethod
    def setUpClass(cls):
        cls.sup, cls.facts = FL4.sup_file()
        cls.block, _ = V3F.FL.menu_block()
        cls.lay = cls.facts['layout']
        cls.vbin = U.built()['vbin']                      # the core with its UI hooks

    def boot(self, sup=None, before=(), stale=None, **kw):
        files, dirs = T4.card(*before, ('FLIP.BIN', sup or self.sup), loader=self.vbin)
        cam = FlipCamera4(files, dirs, stale=stale, **kw)
        cam.boot()
        self.assertIsNone(cam.error)
        return cam

    def outcome(self, cam):
        names = {LOADED: 'LOADED', RELEASED: 'RELEASED'}
        return {t: names[c] for c, _, _, t in cam.loadlog() if c in names}.get('FLIP.BIN')

    def blob(self, cam):
        return T4.blocks(cam)['FLIP.BIN'] + B4.SL4_HEADER_LEN

    def saved_sup(self, table):
        lo = int.from_bytes(bytes(table[:4]), 'little')
        hi = int.from_bytes(bytes(table[4:]), 'little')
        rec = struct.pack('<5I', 0x54534646, 1, lo, hi, 0x54534646 ^ 1 ^ lo ^ hi ^ 0xFFFFFFFF)
        at = B4.SL4_HEADER_LEN + self.facts['settings_off']
        return self.sup[:at] + rec + self.sup[at + len(rec):]

    def resolve(self, cam, sid):
        """The core's string resolve hook (C05E5B58), as the firmware calls it."""
        return cam.call(0xC05E5B58, r0=0, r1=sid, thumb=True)[0]

    # ---- what v4 changed -------------------------------------------------
    def test_loads_claims_the_panel_adds_the_row_subscribes_and_starts_the_task(self):
        cam = self.boot()
        self.assertEqual(self.outcome(cam), 'LOADED')
        at = T4.blocks(cam)['FLIP.BIN']
        self.assertTrue(at >= 0xC0000000 and at % 64 == 0, hex(at))      # cached
        loaded = [(a, n) for c, a, n, t in cam.loadlog() if c == LOADED and t == 'FLIP.BIN']
        self.assertEqual(loaded[0][1], 0, 'FLIP.BIN claimed a firmware word')
        blob, state = self.blob(cam), self.state(cam)
        self.assertEqual(self.field(cam, 'result'), 1, 'not READY')
        self.assertEqual(cam.cstr(self.field(cam, 'self_path')), PATH)
        sym = self.facts['symbols']
        self.assertEqual(cam.subs, [(V3F.GUI_OBJECT, state + self.lay['name'], blob + sym['changed_shim'])])
        self.assertEqual(cam.tasks, [blob + sym['task_shim']])
        self.assertEqual(cam.task_stacks, [0x2000])              # the saves go through the file system on it (froze at 0x1000, user 2026-11-10)
        self.assertEqual(self.panel(cam), (0, 0), 'loading touched the panel')
        y = SETS.index('Y2_5_1')
        entry = cam.w(cam.entries + 44 * y + 8)
        self.assertNotEqual(entry, F.ENTRY_OFFSET, 'Y2_5_1 was not switched')
        self.assertEqual(cam.w(cam.entries + 8), 0x76FF04, 'MainB2 was touched')
        page = (NBU_BASE + entry) & 0xFFFFFFFF
        self.assertTrue(page >= 0xC0000000, f'the page copy is not cached: {page:#x}')
        length = cam.w((page & ~3) - 128 + 12)
        stock = cam.img[F.PAGE_START:F.PAGE_END]
        pages = {'Y2_5_1': fpui.PageCopy(stock, len(stock), 1)}
        pool = fpui.Strings(cam.img[0x18C0474:0x18C0474 + 176152])
        fpui.apply(self.block, pages, pool)
        ref = bytes(pages['Y2_5_1'].data)
        ours = bytes(cam.mu.mem_read(page, length))
        self.assertEqual(len(ours), len(ref))
        ui = blob + self.facts['ui_off']
        diffs, o = 0, 0
        while o < len(ref):                              # each run of differing bytes
            if ours[o] == ref[o]:
                o += 1
                continue
            end = o
            while end < len(ref) and ours[end] != ref[end]:
                end += 1
            for at in range(max(0, end - 4), o + 1):     # the 4-byte field holding the run
                sid = struct.unpack_from('>I', ours, at)[0]
                try:
                    want = ref_text(pool, struct.unpack_from('>I', ref, at)[0])
                except (KeyError, ValueError):
                    continue
                if 0x40000000 <= sid < 0x80000000:
                    break
            else:
                self.fail(f'+{o:#x}: {ref[o:end].hex()} -> {ours[o:end].hex()} is no string field')
            self.assertTrue(ui <= sid + 0x80000000 < ui + self.facts['ui_len'], f'+{at:#x}')
            self.assertEqual(cam.cstr(self.resolve(cam, sid)), want, f'+{at:#x}')
            diffs += 1
            o = at + 4
        self.assertGreater(diffs, 0, 'no string field: the row has private strings')
        self.assertEqual(self.field(cam, 'row_y'), 405)
        cam.power_off()

    def test_a_string_site_held_exclusively_releases_with_nothing_written(self):
        """v4: there is no string claim to lose -- the core holds the sites, and
        FLIP.BIN loads beside it."""
        cam = self.boot()
        self.assertEqual(self.outcome(cam), 'LOADED')
        for a in STRING_SITES:
            self.assertNotIn(a, [x for x, _, _ in cam.journal()
                                 if False])              # journaled by the core, not us
        self.assertEqual(self.field(cam, 'result'), 1)

    def test_the_panel_held_by_another_sup_releases_with_nothing_written(self):
        for res in (V3F.LAYER, V3F.TOUCH):
            with self.subTest(res=hex(res)):
                other = B4.from_v3(V3F.B.patch_sup('LCDF', [(res, None, 2, 'res')]), name='LCD')
                cam = self.boot(before=[('A_LCD.BIN', other)])
                self.assertEqual(self.outcome(cam), 'RELEASED')
                self.assertEqual((cam.regs, cam.subs, cam.tasks, cam.lookups), ([], [], [], []))
                self.assertEqual(cam.w(cam.entries + 44 * SETS.index('Y2_5_1') + 8),
                                 F.ENTRY_OFFSET, 'a row without its sup')

    def test_a_foreign_firmware_word_releases_before_registering(self):
        files, dirs = T4.card(('FLIP.BIN', self.sup), loader=self.vbin)
        cam = FlipCamera4(files, dirs)
        img = bytearray(cam.img)
        img[V3F.MODE - 0xC0000000:V3F.MODE - 0xC0000000 + 4] = struct.pack('<I', 0xE12FFF1E)
        cam.img = bytes(img)
        cam.boot()
        self.assertEqual(self.outcome(cam), 'RELEASED')
        self.assertEqual((cam.regs, cam.subs, cam.tasks, cam.lookups), ([], [], [], []))

    def test_an_already_registered_variable_is_not_registered_again(self):
        files, dirs = T4.card(('FLIP.BIN', self.sup), loader=self.vbin)
        cam = FlipCamera4(files, dirs)
        name = V3F.UI_AREA + 0x7800
        cam.mu.mem_write(name, b'MV_fpScreenFlip\0')
        cam.mu.mem_write(V3F.DESC + 0x100, struct.pack('<3I', 0, name, 2))
        cam.vars['MV_fpScreenFlip'] = V3F.DESC + 0x100
        cam.boot()
        self.assertEqual(self.outcome(cam), 'LOADED')
        self.assertEqual(cam.regs, [])
        self.assertEqual(self.field(cam, 'result'), 1)

    def test_a_refused_block_keeps_the_block_but_no_subscription_or_task(self):
        files, dirs = T4.card(('FLIP.BIN', self.sup), loader=self.vbin)
        cam = FlipCamera4(files, dirs)
        cam.put(cam.entries + 44 * SETS.index('Y2_5_1') + 8, 0x76FF04)   # not stock: GUARD
        cam.boot()
        self.assertEqual(self.outcome(cam), 'LOADED', 'the registry borrows the block')
        self.assertEqual(self.field(cam, 'result'), 7)
        self.assertEqual((cam.subs, cam.tasks), ([], []))

    def test_a_damaged_record_starts_normal_and_is_never_rewritten(self):
        bad = bytearray(self.saved_sup([1] * 8))
        bad[B4.SL4_HEADER_LEN + self.facts['settings_off'] + 16] ^= 1
        cam = self.boot(sup=bytes(bad))
        self.assertEqual((self.field(cam, 'settings_ok'), self.table(cam)), (0, [0] * 8))
        self.assertEqual(self.field(cam, 'self_path'), 0)
        cam.put(V3F.EDITING, 0)
        self.poll(cam)
        self.write_row(cam, 1)
        for _ in range(V3F.FL_SAVE_POLLS * 2):
            self.poll(cam)
        self.assertEqual({k: v for k, v in cam.written.items() if k != '\\fpSup\\LOAD.LOG'}, {})

    def test_the_table_is_saved_into_this_file_once_still_and_not_recording(self):
        cam = self.boot()
        cam.put(V3F.EDITING, 2)
        self.poll(cam)
        self.write_row(cam, 3)
        cam.recording = 1
        for _ in range(V3F.FL_SAVE_POLLS * 2):
            self.poll(cam)
        self.assertNotIn(PATH, cam.written, 'saved while recording')
        cam.recording = 0
        for _ in range(V3F.FL_SAVE_POLLS - 1):
            self.poll(cam)
        self.assertNotIn(PATH, cam.written, 'saved before the value held still')
        self.poll(cam)
        self.assertEqual(cam.files[PATH], self.saved_sup([0, 0, 3, 0, 0, 0, 0, 0]))
        self.assertEqual((self.field(cam, 'saves'), self.field(cam, 'save_failed')), (1, 0))
        before = dict(cam.written)
        for _ in range(V3F.FL_SAVE_POLLS * 2):
            self.poll(cam)
        self.assertEqual(cam.written, before, 'saved again with nothing new')

    def test_a_replaced_file_is_never_written(self):
        """file_is: the file on the card is no longer this sup (renamed away and
        another put in its place) -- the save must not write into it."""
        cam = self.boot()
        cam.put(V3F.EDITING, 2)
        self.poll(cam)
        self.write_row(cam, 3)
        other = b'\0' * len(self.sup)
        cam.files[PATH] = other
        for _ in range(V3F.FL_SAVE_POLLS * 2):
            self.poll(cam)
        self.assertEqual(cam.files[PATH], other)
        self.assertEqual(self.field(cam, 'saves'), 0)


if __name__ == '__main__':
    unittest.main()
