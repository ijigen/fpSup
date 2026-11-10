"""fpScreenFlip as a Loader v3 sup, loaded by the real 加載器.

    cd fpSup/screenflip && python3 -B -m unittest test_v3_flip

The real loader.S (as the AutoRun spells it), the real LOADER.BIN and the
built 40FLIP.BIN run in Unicorn against the reference image; the firmware's
file, directory, allocator, task and power-off routines are Python
(fp_usb_shell/v3/test_v3.Camera), and so are the UI registry, the display-mode
getters and the GUI queue (this file). The native UI objects ui_apply looks
for are laid out as read from the camera (fp-native-ui §8a), so the row IS
installed here and compared with the reference applier.

Proven here: claims before anything (and RELEASE with nothing written when
the panel is someone else's); the row and its variable; setting a value does
not touch the panel; switching INTO a custom (DISP, STILL/CINE, shooting
style) applies that custom's value, LCD off applies nothing; the edited custom
is shown in the row; the table is saved into this sup's own file only after
it held still and not while recording, read back, and loaded at the next boot.
Not proven: the real UI, the real getters' values, the panel, timing.
"""
import pathlib
import struct
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent
V3 = FPSUP / 'fp_usb_shell' / 'v3'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(V3))
sys.path.insert(0, str(V3.parent))
sys.path.insert(0, str(FPSUP / 'uishare'))
sys.path.insert(0, str(HERE / 'menu'))

import test_v3 as T                                       # noqa: E402
import build_v3 as B                                      # noqa: E402
import build_v3_flip as FL                                # noqa: E402
import build_flip_page as F                               # noqa: E402
from ui import fpui                                       # noqa: E402
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE   # noqa: E402

GUI_OBJECT, UI_AREA = 0xC37B7048, 0xC3A00000
NBU_BASE = 0xC18C0460
LOOKUP, REGISTER, SUBSCRIBE, RELAYOUT = 0xC05DB418, 0xC05DB308, 0xC0560FB0, 0xC02E4420
QUEUE, SETTINGS, MODE, CINEMA, STYLE = 0xC0593F30, 0xC0057AE8, 0xC0061BA8, 0xC0058340, 0xC0061A68
F_SEEK = 0xC03661E0
LAYER, TOUCH, TOUCH_VT_AT, TOUCH_VT = 0x30190044, 0xC3760E44, 0xC3760E48, 0xC0CBE37C
EDITING, STATUS, REC_AREA = 0xC37628A4, 0xC00178D8, UI_AREA + 0xA000
SETTINGS_OBJ = 0xC31AC530
DESC = UI_AREA + 0x8000
WANT = {0: 0x000000, 1: 0x333000, 2: 0x001000, 3: 0x332000}
SETS = ['MainB2', 'Y2_5_1']
PATH = '\\fpSup\\40FLIP.BIN'
OTHER = 0x00000ABC                        # other layers' bits: must survive
CHECKED = [LOOKUP, REGISTER, SUBSCRIBE, RELAYOUT, QUEUE, SETTINGS, MODE, CINEMA, STYLE,
           STATUS, 0xC0016A58, 0xC0016BC0, 0xC03705D8, 0xC0365E90, 0xC0365FB0, F_SEEK, 0xC03660E8,
           0xC0366060, 0xC0366020, 0xC0365ED0]
CHECKED_SET = set(CHECKED)
STRING_SITES = (0xC05E5B58, 0xC05E61C8, 0xC05E61E0)


class FlipCamera(T.Camera):
    def __init__(self, files, dirs, touch_vt=TOUCH_VT, **kw):
        super().__init__(files, dirs, **kw)
        mu = self.mu
        mu.mem_map(LAYER & ~0xFFF, 0x1000)
        # test_v3 makes every stubbed routine `bx lr` (unicorn sometimes runs
        # the real routine despite a hook's PC write). The sup checks their
        # first words: a data read of one sees the stock word, put there just
        # for that read and taken away before the next instruction.
        for a in CHECKED:
            mu.mem_write(a, struct.pack('<I', 0xE12FFF1E))
        self.lent = False
        self.image_writes = set()
        mu.hook_add(UC_HOOK_MEM_WRITE, self._image_write, begin=0xC0000000, end=0xC2FFFFFF)
        mu.hook_add(UC_HOOK_MEM_READ, self._lend, begin=min(CHECKED), end=max(CHECKED) + 3)
        for at, name in ((LOOKUP, 'LOOKUP'), (REGISTER, 'REGISTER'), (SUBSCRIBE, 'SUBSCRIBE'),
                         (RELAYOUT, 'RELAYOUT'), (QUEUE, 'QUEUE'), (SETTINGS, 'SETTINGS'),
                         (MODE, 'MODE'), (CINEMA, 'CINEMA'), (STYLE, 'STYLE'), (F_SEEK, 'F_SEEK'),
                         (STATUS, 'STATUS')):
            self.by_addr[at] = name
        self.mode, self.cine, self.style = 0, 0, 0
        self.lookups, self.regs, self.subs, self.queued, self.relayouts = [], [], [], [], 0
        self.vars = {}
        w = self.put
        app, screens, screen, reader, entries, names, registry = (
            UI_AREA + o for o in (0, 0x1000, 0x2000, 0x3000, 0x4000, 0x6000, 0x7000))
        w(GUI_OBJECT, app); w(app + 0x80, 1); w(app + 0x8C, screens); w(screens, screen)
        w(screen + 0x24, reader); w(app + 0x888, registry)
        w(reader + 0x10, 176152); w(reader + 0x14, 0xC18C0474); w(reader + 0x24, NBU_BASE)
        w(reader + 0xA8, len(SETS)); w(reader + 0xAC, entries)
        offsets = {'MainB2': 0x76FF04, 'Y2_5_1': F.ENTRY_OFFSET}
        for i, name in enumerate(SETS):
            mu.mem_write(names + 0x40 * i, name.encode() + b'\0')
            w(entries + 44 * i + 4, names + 0x40 * i)
            w(entries + 44 * i + 8, offsets[name])
        self.entries, self.reader = entries, reader
        w(LAYER, OTHER)
        w(TOUCH_VT_AT, touch_vt)
        w(TOUCH, 0)
        w(EDITING, 0xFFFF)                               # the page never opened
        self.recording = 0

    def _image_write(self, mu, access, addr, size, value, data):
        if not 0xC072D000 <= addr < 0xC0735000:          # the cave is the loader's
            self.image_writes.add(addr & ~3)

    def _lend(self, mu, access, addr, size, value, data):
        if addr in CHECKED_SET:
            mu.mem_write(addr, self.img[addr - 0xC0000000:addr - 0xC0000000 + 4])
            self.lent = True

    @property
    def recording(self):
        return self.mu.mem_read(REC_AREA + 0x84, 1)[0]

    @recording.setter
    def recording(self, v):
        self.mu.mem_write(REC_AREA + 0x84, bytes([v]))

    def _hook(self, mu, addr, size, data):
        if self.lent:
            for a in CHECKED:
                mu.mem_write(a, struct.pack('<I', 0xE12FFF1E))
            self.lent = False
        name = self.by_addr.get(addr)
        r = [self.r(x) for x in (T.UC_ARM_REG_R0, T.UC_ARM_REG_R1, T.UC_ARM_REG_R2)]
        if name == 'LOOKUP':
            n = self.cstr(r[1])
            self.lookups.append(n)
            self.put(r[2], self.vars.get(n, 0))
            return self._ret(0)
        if name == 'REGISTER':
            t, p, v = struct.unpack('<3I', mu.mem_read(r[2], 12))
            self.regs.append((r[0], r[1], t, p, v))
            d = DESC + 16 * len(self.vars)
            mu.mem_write(d, struct.pack('<3I', t, p, v))
            self.vars[self.cstr(p)] = d
            return self._ret(0)
        if name == 'SUBSCRIBE':
            self.subs.append(tuple(r))
            return self._ret(0)
        if name == 'RELAYOUT':
            self.relayouts += 1
            return self._ret(0)
        if name == 'QUEUE':
            self.queued.append((self.cstr(r[1]), r[2]))
            return self._ret(0)
        if name == 'SETTINGS':
            return self._ret(SETTINGS_OBJ)
        if name == 'STATUS':                             # is_recording at +0x18 +0x84
            return self._ret(REC_AREA - 0x18)
        if name in ('MODE', 'CINEMA', 'STYLE'):
            assert r[0] == SETTINGS_OBJ, hex(r[0])
            return self._ret({'MODE': self.mode, 'CINEMA': self.cine, 'STYLE': self.style}[name])
        # files: one byte string per path, written in place
        if name == 'F_OPEN':
            path = self.cstr(r[1])
            self.opened.append(path)
            ok = path in self.files
            self.fobj[r[0]] = [path, 0] if ok else None
            return self._ret(1 if ok else 0)
        if name == 'F_SEEK':
            self.fobj[r[0]][1] = r[1]
            return self._ret(1)
        if name == 'F_WRITE':
            path, pos = self.fobj[r[0]]
            new = bytes(mu.mem_read(r[1], r[2]))
            old = self.files[path]
            self.files[path] = old[:pos] + new + old[pos + len(new):]
            self.written[path] = self.files[path]
            self.fobj[r[0]][1] += r[2]
            return self._ret(1)
        return super()._hook(mu, addr, size, data)


@unittest.skipIf(T.Uc is None or not T.IMAGE.exists(), 'needs unicorn and the image')
class FlipV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sup, cls.facts = FL.sup_file()
        cls.block, _ = FL.menu_block()
        cls.lay = cls.facts['layout']

    # ---- plumbing --------------------------------------------------------
    def boot(self, sup=None, before=(), stale=None, **kw):
        files, dirs = T.card(*before, ('40FLIP.BIN', sup or self.sup))
        cam = FlipCamera(files, dirs, stale=stale, **kw)
        _, sp = cam.boot()
        self.assertEqual(sp, T.STACK - 0x1004)
        self.assertEqual(cam.misaligned, [])
        return cam

    def outcome(self, cam):
        return {t: c for c, _, _, t in cam.log() if c in ('LOADED', 'RELEASED')}.get('40FLIP.BIN')

    def blob(self, cam):
        return next(a for c, a, _, t in cam.log() if c == 'LOADED' and t == '40FLIP.BIN') + \
            B.SL_HEADER_LEN

    def state(self, cam):
        return self.blob(cam) + self.facts['state_off']

    def field(self, cam, name, n=4):
        at = self.state(cam) + self.lay[name]
        return cam.w(at) if n == 4 else bytes(cam.mu.mem_read(at, n))

    def table(self, cam):
        return list(self.field(cam, 'table', 8))

    def poll(self, cam):
        fn = self.blob(cam) + self.facts['c_base'] + self.facts['functions']['fpf_poll']
        _, sp = cam.call(fn & ~1, r0=self.state(cam), sp=T.STACK - 0x1000, thumb=True)
        self.assertEqual(sp, T.STACK - 0x1000)

    def write_row(self, cam, value):
        """The UI writes MV_fpScreenFlip: the subscribed shim runs."""
        desc = UI_AREA + 0x9000
        cam.mu.mem_write(desc, struct.pack('<3I', 0, self.state(cam) + self.lay['name'], value))
        r0, sp = cam.call(cam.subs[0][2], r0=desc, r1=0, sp=T.STACK - 0x1000)
        self.assertEqual((r0, sp), (0, T.STACK - 0x1000))

    def panel(self, cam):
        return cam.w(LAYER) & ~OTHER, cam.w(TOUCH)

    def saved_sup(self, table):
        """This sup as the task would have left it on the card."""
        lo = int.from_bytes(bytes(table[:4]), 'little')
        hi = int.from_bytes(bytes(table[4:]), 'little')
        rec = struct.pack('<5I', 0x54534646, 1, lo, hi, 0x54534646 ^ 1 ^ lo ^ hi ^ 0xFFFFFFFF)
        at = B.SL_HEADER_LEN + self.facts['settings_off']
        return self.sup[:at] + rec + self.sup[at + len(rec):]

    # ---- load --------------------------------------------------------------
    def test_loads_claims_the_panel_adds_the_row_subscribes_and_starts_the_task(self):
        cam = self.boot()
        self.assertEqual(self.outcome(cam), 'LOADED')
        strings = {a: T.word(cam.img, a) for a in STRING_SITES}
        self.assertEqual(cam.journal(), [(a, 4, struct.pack('<I', strings[a]))
                                         for a in sorted(STRING_SITES)])
        st = cam.state()
        claims = [struct.unpack('<IIBBBB', cam.mu.mem_read(st + T.O_CLAIMS + 12 * i, 12))
                  for i in range(cam.w(st + T.O_NCLAIMS))]
        self.assertEqual(sorted((a, k, res) for a, _, k, _, res, _ in claims),
                         sorted([(LAYER, 2, 1), (TOUCH, 2, 1)] +
                                [(a, 3, 0) for a in STRING_SITES]))
        # every firmware-image word that changed is one of ours, claimed
        for a in STRING_SITES:
            self.assertNotEqual(cam.w(a), strings[a], f'{a:#x}: the row hung no layer')
        self.assertEqual(sorted(cam.image_writes), sorted(STRING_SITES),
                         'a firmware word outside the claims was written')
        cam.power_off()
        for a in STRING_SITES:
            self.assertEqual(cam.w(a), strings[a], f'{a:#x} not put back at power-off')
        blob, state = self.blob(cam), self.state(cam)
        self.assertEqual(self.field(cam, 'magic'), 0x50494C46)
        self.assertEqual(self.field(cam, 'result'), 1, 'not READY')
        self.assertEqual(cam.cstr(state + self.lay['name']), 'MV_fpScreenFlip')
        self.assertEqual(cam.cstr(self.field(cam, 'self_path')), PATH)
        self.assertEqual(self.field(cam, 'settings_ok'), 1)
        self.assertEqual(cam.regs, [(UI_AREA, 1, 0, state + self.lay['name'], 0)])
        sym = self.facts['symbols']
        self.assertEqual(cam.subs, [(GUI_OBJECT, state + self.lay['name'], blob + sym['changed_shim'])])
        self.assertEqual(cam.tasks, [blob + sym['task_shim']])
        self.assertEqual(cam.task_stacks, [0x1000])              # v3's bytes as released
        self.assertEqual(cam.w(blob + sym['g_state']), state)
        self.assertEqual(self.panel(cam), (0, 0), 'loading touched the panel')
        # the row: Y2_5_1 switched to the reference applier's page
        y = SETS.index('Y2_5_1')
        entry = cam.w(cam.entries + 44 * y + 8)
        self.assertNotEqual(entry, F.ENTRY_OFFSET, 'Y2_5_1 was not switched')
        self.assertEqual(cam.w(cam.entries + 8), 0x76FF04, 'MainB2 was touched')
        page = (NBU_BASE + entry) & 0xFFFFFFFF
        length = cam.w((page & ~3) - 128 + 12)
        stock = cam.img[F.PAGE_START:F.PAGE_END]
        pages = {'Y2_5_1': fpui.PageCopy(stock, len(stock), 1)}
        pool = fpui.Strings(cam.img[0x18C0474:0x18C0474 + 176152])
        fpui.apply(self.block, pages, pool)
        self.assertEqual(bytes(cam.mu.mem_read(page, length)), bytes(pages['Y2_5_1'].data))
        self.assertEqual(self.field(cam, 'row_y'), 405)

    def test_the_panel_held_by_another_sup_releases_with_nothing_written(self):
        for res in (LAYER, TOUCH):
            with self.subTest(res=hex(res)):
                other = B.patch_sup('LCDF', [(res, None, 2, 'res')])
                cam = self.boot(before=[('20LCD.BIN', other)])
                self.assertEqual(self.outcome(cam), 'RELEASED')
                self.assertEqual((cam.regs, cam.subs, cam.tasks, cam.lookups), ([], [], [], []))
                self.assertEqual(cam.w(cam.entries + 44 * SETS.index('Y2_5_1') + 8),
                                 F.ENTRY_OFFSET, 'a row without its sup')

    def test_a_string_site_held_exclusively_releases_with_nothing_written(self):
        other = B.patch_sup('STRX', [(STRING_SITES[1], struct.pack('<I', 0xE1A00000), 2, 'claim')])
        cam = self.boot(before=[('20STR.BIN', other)])
        self.assertEqual(self.outcome(cam), 'RELEASED')
        self.assertEqual((cam.regs, cam.subs, cam.tasks, cam.lookups), ([], [], [], []))
        for a in STRING_SITES:
            self.assertEqual(cam.w(a), T.word(cam.img, a))

    def test_a_foreign_firmware_word_releases_before_registering(self):
        files, dirs = T.card(('40FLIP.BIN', self.sup))
        cam = FlipCamera(files, dirs)
        img = bytearray(cam.img)                         # MODE is not the 5.02 routine
        img[MODE - 0xC0000000:MODE - 0xC0000000 + 4] = struct.pack('<I', 0xE12FFF1E)
        cam.img = bytes(img)
        cam.boot()
        self.assertEqual(self.outcome(cam), 'RELEASED')
        self.assertEqual((cam.regs, cam.subs, cam.tasks, cam.lookups), ([], [], [], []))

    def test_an_already_registered_variable_is_not_registered_again(self):
        files, dirs = T.card(('40FLIP.BIN', self.sup))
        cam = FlipCamera(files, dirs)
        name = UI_AREA + 0x7800
        cam.mu.mem_write(name, b'MV_fpScreenFlip\0')
        cam.mu.mem_write(DESC + 0x100, struct.pack('<3I', 0, name, 2))
        cam.vars['MV_fpScreenFlip'] = DESC + 0x100
        cam.boot()
        self.assertEqual(self.outcome(cam), 'LOADED')
        self.assertEqual(cam.regs, [])
        self.assertEqual(self.field(cam, 'result'), 1)

    def test_a_refused_block_keeps_the_block_but_no_subscription_or_task(self):
        files, dirs = T.card(('40FLIP.BIN', self.sup))
        cam = FlipCamera(files, dirs)
        cam.put(cam.entries + 44 * SETS.index('Y2_5_1') + 8, 0x76FF04)   # not stock: GUARD
        cam.boot()
        self.assertEqual(self.outcome(cam), 'LOADED', 'the registry borrows the block')
        self.assertEqual(self.field(cam, 'result'), 7)
        self.assertEqual((cam.subs, cam.tasks), ([], []))

    # ---- the behaviour ---------------------------------------------------
    def test_setting_a_value_does_not_flip_switching_into_that_mode_does(self):
        cam = self.boot()
        self.poll(cam)                                   # boot: Custom 1 (0), all normal
        self.assertEqual((self.panel(cam), cam.relayouts), ((0, 0), 0))
        cam.put(EDITING, 1)                              # the user opens Custom 2
        self.poll(cam)
        self.assertEqual(cam.queued, [('MV_fpScreenFlip', 0)])
        self.write_row(cam, 1)                           # ... and sets 180
        self.assertEqual(self.table(cam), [0, 1, 0, 0, 0, 0, 0, 0])
        for _ in range(3):
            self.poll(cam)
        self.assertEqual((self.panel(cam), cam.relayouts), ((0, 0), 0), 'set must not flip')
        cam.mode = 1                                     # DISP: into Custom 2
        self.poll(cam)
        self.assertEqual((self.panel(cam), cam.relayouts), ((WANT[1], 1), 1))
        self.poll(cam)
        self.assertEqual(cam.relayouts, 1, 'applied again without a switch')
        cam.mode = 4                                     # LCD off: nothing to flip
        self.poll(cam)
        self.assertEqual((self.panel(cam), cam.relayouts), ((WANT[1], 1), 1))
        cam.mode = 2                                     # DISP: Custom 3 is normal
        self.poll(cam)
        self.assertEqual((self.panel(cam), cam.relayouts), ((0, 0), 2))
        cam.mode = 1
        self.poll(cam)
        self.assertEqual(self.panel(cam), (WANT[1], 1))
        self.assertEqual(self.field(cam, 'switches'), 5)

    def test_each_set_has_its_own_customs(self):
        cam = self.boot()
        cam.put(EDITING, 0)
        self.poll(cam)
        self.write_row(cam, 2)                           # STILL Custom 1: mirror
        cam.cine = 1
        self.poll(cam)                                   # CINE Custom 1 now edited/live
        self.assertEqual(cam.queued[-1], ('MV_fpScreenFlip', 0))
        self.assertEqual(self.panel(cam), (0, 0))
        self.write_row(cam, 3)                           # CINE Custom 1: 180 + mirror
        self.assertEqual(self.table(cam), [2, 0, 0, 0, 3, 0, 0, 0])
        self.assertEqual(self.panel(cam), (0, 0))
        cam.cine = 0                                     # back to STILL: a switch
        self.poll(cam)
        self.assertEqual(self.panel(cam), (WANT[2], 0))
        self.assertEqual(cam.queued[-1], ('MV_fpScreenFlip', 2))
        cam.cine = 1
        self.poll(cam)
        self.assertEqual(self.panel(cam), (WANT[3], 1))
        cam.style = 1                                    # CINE body, STILL style: STILL set
        self.poll(cam)
        self.assertEqual(self.panel(cam), (WANT[2], 0))

    def test_an_unknown_touch_object_refuses_a_turned_ui(self):
        cam = self.boot(touch_vt=0x12345678)
        cam.put(EDITING, 1)
        self.poll(cam)
        self.write_row(cam, 3)
        cam.mode = 1
        self.poll(cam)
        self.assertEqual(self.panel(cam), (0, 0))
        self.assertEqual(self.field(cam, 'refused'), 1)

    def test_values_out_of_range_and_unedited_writes_are_ignored(self):
        cam = self.boot()
        self.write_row(cam, 2)                           # the page never opened: no slot
        cam.put(EDITING, 4)                              # the LCD-off slot
        self.poll(cam)
        self.write_row(cam, 2)
        cam.put(EDITING, 0)
        self.poll(cam)
        self.write_row(cam, 9)
        self.assertEqual(self.table(cam), [0] * 8)

    # ---- this sup's file -------------------------------------------------
    def test_the_table_is_saved_into_this_file_once_still_and_not_recording(self):
        cam = self.boot()
        cam.put(EDITING, 2)
        self.poll(cam)
        self.write_row(cam, 3)
        cam.recording = 1
        for _ in range(FL_SAVE_POLLS * 2):
            self.poll(cam)
        self.assertNotIn(PATH, cam.written, 'saved while recording')
        cam.recording = 0
        for _ in range(FL_SAVE_POLLS - 1):
            self.poll(cam)
        self.assertNotIn(PATH, cam.written, 'saved before the value held still')
        self.poll(cam)
        self.assertEqual(cam.files[PATH], self.saved_sup([0, 0, 3, 0, 0, 0, 0, 0]))
        self.assertEqual((self.field(cam, 'saves'), self.field(cam, 'save_failed')), (1, 0))
        before = dict(cam.written)
        for _ in range(FL_SAVE_POLLS * 2):
            self.poll(cam)
        self.assertEqual(cam.written, before, 'saved again with nothing new')

    def test_a_saved_table_is_loaded_and_the_boot_mode_applied(self):
        cam = self.boot(sup=self.saved_sup([0, 0, 1, 0, 0, 0, 0, 0]))
        self.assertEqual(self.table(cam), [0, 0, 1, 0, 0, 0, 0, 0])
        cam.mode = 2                                     # the camera booted in Custom 3
        self.poll(cam)
        self.assertEqual(self.panel(cam), (WANT[1], 1))

    def test_a_damaged_record_starts_normal_and_is_never_rewritten(self):
        bad = bytearray(self.saved_sup([1] * 8))
        bad[B.SL_HEADER_LEN + self.facts['settings_off'] + 16] ^= 1     # the check
        cam = self.boot(sup=bytes(bad))
        self.assertEqual((self.field(cam, 'settings_ok'), self.table(cam)), (0, [0] * 8))
        self.assertEqual(self.field(cam, 'self_path'), 0)
        cam.put(EDITING, 0)
        self.poll(cam)
        self.write_row(cam, 1)
        for _ in range(FL_SAVE_POLLS * 2):
            self.poll(cam)
        self.assertEqual(cam.written, {})


FL_SAVE_POLLS = 20                                       # flip.h FPF_SAVE_POLLS


if __name__ == '__main__':
    unittest.main()
