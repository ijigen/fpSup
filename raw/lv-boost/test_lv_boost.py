"""Offline tests against downloaded fp 5.02 machine code; no camera access."""
from pathlib import Path
import math
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'raw/lv-boost/build'), str(ROOT / 'fp_usb_shell')]
import build_lv_boost as B
import fl_tables as F
import test_loader_hook as T
from unicorn import UC_HOOK_MEM_WRITE, UC_HOOK_CODE
from unicorn.arm_const import *

T.IMAGE = ROOT / 'out/MAIN_c0000000.bin'
STAGING, RES = T.HEAP + 0x100000, T.HEAP + 0x3200
STACK = T.STACK - 0x1000
TONE, KEY, APP = 0xC02D2E50, 0xC2F19D44, 0xC3033A44
FLAG, VAR = RES + 4, RES + 0x1A4
ORIGINAL = 0xC09C3F34
SAVE, MAGIC = 0xC307544C, 0x4C560100


class Rig:
    def __init__(self, blob, corrupt=None, task_result=7, preference=0):
        self.cam = T.Camera({}, b'')
        self.mu = self.cam.mu
        self.mu.mem_write(B.SEG1_BASE, B.SEG1.read_bytes())
        if corrupt is not None:
            self.put(corrupt, 0xE320F000)
        self.put(0xC3033A54, 1)  # Stable STILL live-view readback.
        self.put(0xC072E060, 0xC072E100)
        self.put(SAVE, preference)
        self.mu.mem_write(STAGING, blob)
        self.writes = set()
        self.mu.hook_add(UC_HOOK_MEM_WRITE, self.record_write)
        self.task = None
        self.task_started = False
        def task_api(mu, addr, size, data):
            if addr not in (0xC0016A58, 0xC0016BC0):
                return
            assert mu.reg_read(UC_ARM_REG_SP) % 8 == 0
            if addr == 0xC0016A58:
                self.task = struct.unpack('<8I', mu.mem_read(mu.reg_read(UC_ARM_REG_R0), 32))
                self.cam._ret(task_result)
            else:
                assert mu.reg_read(UC_ARM_REG_R0) == task_result
                assert mu.reg_read(UC_ARM_REG_R1) == 0
                self.task_started = True
                self.cam._ret(0)
        self.mu.hook_add(UC_HOOK_CODE, task_api)
        self.cam.call(STAGING, sp=STACK)
        self.conv = T.HEAP + 0x30000
        self.put(self.conv + 4, 0xC2DEAE98 - 0x11C)
        # Native UI publishing is the only stub used by menu adjustments.
        self.mu.mem_write(0xC0593F30, struct.pack('<I', 0xE12FFF1E))

    def record_write(self, mu, access, addr, size, value, data):
        if 0xC0000000 <= addr < 0xC3000000:
            self.writes.update(range(addr & ~3, addr + size, 4))

    def put(self, addr, value):
        self.mu.mem_write(addr, struct.pack('<I', value))

    def step(self, site, **regs):
        self.mu.reg_write(UC_ARM_REG_SP, STACK)
        self.mu.reg_write(UC_ARM_REG_LR, T.DONE)
        for name, value in regs.items():
            self.mu.reg_write(globals()['UC_ARM_REG_' + name.upper()], value)
        self.mu.emu_start(site, site + 4, count=100000)
        assert self.mu.reg_read(UC_ARM_REG_PC) == site + 4
        assert self.mu.reg_read(UC_ARM_REG_SP) == STACK

    def select(self, row):
        self.step(0xC0568950, r0=self.conv, r1=row)
        value = self.mu.reg_read(UC_ARM_REG_R0)
        self.step(0xC0075CF4, r4=0xC31ACDC4, sl=0xC, r6=value)

    def gain(self, state=0):
        helper = T.HEAP + 0x31000
        self.put(helper + 12, state)
        self.step(0xC0313244, r5=helper, r6=936)
        return self.mu.reg_read(UC_ARM_REG_R2)

    def tone(self, context=0, color=0x24, channels=0, source=ORIGINAL):
        lookup = T.HEAP + 0x32000
        self.put(lookup + 4, source)
        cpsr = 0xA8000013
        self.step(TONE, r0=lookup, r2=channels, r3=0x12345678,
                  ip=0x87654321, r5=context, r11=color, cpsr=cpsr)
        for reg, expected in [(UC_ARM_REG_R0, lookup), (UC_ARM_REG_R2, channels),
                              (UC_ARM_REG_R3, 0x12345678), (UC_ARM_REG_IP, 0x87654321)]:
            assert self.mu.reg_read(reg) == expected
        assert self.mu.reg_read(UC_ARM_REG_CPSR) & 0xF8000000 == cpsr & 0xF8000000
        return self.mu.reg_read(UC_ARM_REG_R1)


class LVBoost(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob, cls.info = B.build_blob(True)

    def setUp(self):
        self.r = Rig(self.blob)

    def test_install_tables_and_journal_coverage(self):
        r = self.r
        from read_diagnostics import resident
        self.assertEqual(resident([r.cam.word(0xC06C07CC), r.cam.word(0xC06C07D0)]), RES)
        with self.assertRaises(ValueError):
            resident([0, 0])
        self.assertEqual(bytes(r.mu.mem_read(T.HEAP, 12288)), F.blob())
        self.assertEqual(r.cam.word(FLAG), 0)
        self.assertEqual(r.cam.word(0xC06C07D8), 0xE3A02011)
        sites = {a for a, _, _ in B.hook_sites(True)}
        self.assertTrue(r.writes <= sites | set(range(0xC072E060, 0xC072EFB4, 4)),
                        [hex(a) for a in r.writes - sites if not 0xC072E060 <= a < 0xC072EFB4])
        for a in [0xC032F728, 0xC2F1A0D4, B.rv_color.ROOT_P08,
                  *(a for a, _, _ in B.rv_dngcm.SITES)]:
            self.assertNotIn(a, r.writes)
            self.assertEqual(bytes(r.mu.mem_read(a, 4)), B.stock_word(a))
        self.assertEqual(r.cam.calls, ['H_GET', 'H_ADDR', 'DCACHE', 'ICACHE', 'DCACHE', 'ICACHE'])

    def test_menu_select_lift_adjust_and_return_to_off(self):
        r = self.r
        r.put(APP, 2)
        self.assertEqual(r.tone(), ORIGINAL)
        r.select(16)
        self.assertEqual(r.cam.word(FLAG), 1)
        self.assertEqual(r.gain(), 0)
        self.assertEqual(r.tone(), T.HEAP)
        r.step(0xC0595908, r7=0xC)
        self.assertEqual(r.mu.reg_read(UC_ARM_REG_R0), 1)
        r.step(0xC0568A3C, r1=2)
        self.assertEqual(r.cam.word(VAR), 1)
        r.put(KEY, 0x24)
        r.gain()
        self.assertEqual(r.cam.word(KEY), 0xFFFFFFFF)
        self.assertEqual(r.tone(), T.HEAP + 4096)
        r.step(0xC05957B0, r7=0xC)
        self.assertEqual(r.mu.reg_read(UC_ARM_REG_R0), 2)
        r.step(0xC0568A3C, r1=3)
        self.assertEqual(r.cam.word(VAR), 2)
        self.assertEqual(r.tone(), T.HEAP + 8192)
        r.step(0xC0568A3C, r1=4)
        self.assertEqual(r.cam.word(VAR), 2)
        r.step(0xC0568A3C, r1=0)
        self.assertEqual(r.cam.word(VAR), 0)
        r.select(15)
        r.gain()
        self.assertEqual(r.tone(), ORIGINAL)

    def test_unexpected_firmware_word_prevents_installation(self):
        r = Rig(self.blob, corrupt=TONE)
        self.assertEqual(r.cam.calls, [])
        self.assertEqual(r.writes, set())
        self.assertEqual(r.cam.word(0xC06C07D8), 0xE3A02010)

    def test_native_tone_lookup_and_diagnostics(self):
        # Execute the stock dispatch and LUT-index lookup, not a fabricated
        # register frame at our hook. Runtime parameter semantics still need
        # camera evidence; this checks the real firmware path for those inputs.
        r = self.r
        r.put(0xC3414470, 0xC2F1A064)
        param = T.HEAP + 0x36000
        r.put(param + 0x30, 0x24)
        r.put(APP, 2)
        r.select(16)
        for variant in range(3):
            r.step(0xC0568A3C, r1=variant + 1)
            for reg, value in [(UC_ARM_REG_R0, 0xC3414470),
                    (UC_ARM_REG_R1, 0xC097110C), (UC_ARM_REG_R2, param),
                    (UC_ARM_REG_SP, STACK), (UC_ARM_REG_LR, T.DONE)]:
                r.mu.reg_write(reg, value)
            r.mu.emu_start(0xC02D29E0, TONE + 4, count=100000)
            self.assertEqual(r.mu.reg_read(UC_ARM_REG_PC), TONE + 4)
            self.assertEqual(r.mu.reg_read(UC_ARM_REG_R1), T.HEAP + variant * 4096)
            self.assertEqual(r.cam.word(RES + 0x34), ORIGINAL)
            self.assertEqual(r.cam.word(RES + 0x44), variant + 1)

    def test_restricted_menu_navigation(self):
        B.write_csv_inc(True)
        import re
        text = (B.HERE / 'fl_csv.inc').read_text().split('csv2:')[1].split('.align')[0]
        rows = bytes(int(x, 16) for x in re.findall(r'0x([0-9A-F]{2})', text)).splitlines()
        self.assertEqual(rows[1], b'1,set_color_01,0,16,1,0')
        self.assertEqual(rows[15], b'15,set_color_11,0,12,16,14')
        self.assertEqual(rows[17], b'17,set_flash_1,0,14,0,16')
        self.assertEqual(rows[14].split(b',')[2], b'1')
        self.assertEqual(rows[16].split(b',')[2], b'1')

    def test_passthrough_capture_cine_playback_and_other_color(self):
        r = self.r
        r.select(16)
        r.put(APP, 2)
        for state in range(10):
            self.assertEqual(r.gain(state), state)
        for context, color, channels, source in [(1, 0x24, 0, ORIGINAL),
                (0, 0, 0, ORIGINAL), (0, 0x24, 3, ORIGINAL), (0, 0x24, 0, 0xC09C0000)]:
            self.assertEqual(r.tone(context, color, channels, source), source)
        for app in [0, 1, 3, 4, 0xFFFFFFFF]:
            r.put(APP, app)
            r.gain()
            self.assertEqual(r.tone(), ORIGINAL)
        r.put(APP, 2)
        r.put(VAR, 3)  # Invalid private setting must not address a fourth table.
        self.assertEqual(r.tone(), ORIGINAL)

    def test_usb_control_still_cine_transition(self):
        r = self.r
        r.select(16)
        r.put(APP, 5)
        r.put(0xC3033A54, 2)  # Camera readback: CINE over USB.
        r.gain()
        self.assertEqual(r.tone(), ORIGINAL)
        r.put(KEY, 0x24)
        r.put(0xC3033A54, 1)  # Stable STILL, verified with SetRecMode=0.
        r.gain()
        self.assertEqual(r.cam.word(KEY), 0xFFFFFFFF)
        self.assertEqual(r.tone(), T.HEAP)
        self.assertEqual(r.cam.word(RES + 0x4C), 1)
        r.put(KEY, 0x24)
        r.put(0xC3033A54, 2)
        r.gain()
        self.assertEqual(r.cam.word(KEY), 0xFFFFFFFF)
        self.assertEqual(r.tone(), ORIGINAL)
        for app in (2, 5):
            for attribute in (0, 1, 2):
                r.put(APP, app)
                r.put(0xC3033A54, attribute)
                self.assertEqual(r.tone(), T.HEAP if attribute == 1 else ORIGINAL)
        for app in (0, 1, 3, 4):
            r.put(APP, app)
            r.put(0xC3033A54, 1)
            self.assertEqual(r.tone(), ORIGINAL)
        r.put(VAR, 0)
        r.select(0)
        self.assertEqual(r.cam.word(FLAG), 0)
        self.assertEqual(r.tone(), ORIGINAL)

    def test_exposure_math_and_curve_shape(self):
        def decode(y):
            return y / 12.92 if y <= 0.04045 else ((y + 0.055) / 1.055) ** 2.4
        for stops in (1, 2, 3):
            t = F.table(stops)
            self.assertEqual(len(t), 2048)
            self.assertEqual(t[0], 0)
            self.assertTrue(all(0 <= a <= b <= 8190 for a, b in zip(t, t[1:])))
            self.assertAlmostEqual(decode(F.display(0.18 / 2 ** stops, stops)), 0.18)
            for i in (1, 8, 32, 64, 128):
                x = i / 1918
                if x * 2 ** stops <= 0.75:
                    self.assertLess(abs(math.log2(decode(t[i] / 8190) / x) - stops), 0.005)
            self.assertGreater(F.display(2, stops), F.display(1, stops))
            self.assertLess(F.display(2, stops), 1)
        self.assertTrue(all(a <= b for a, b in zip(F.table(2), F.table(3))))
        for x, stops in [(float('nan'), 2), (-1, 2), (0.1, 4)]:
            with self.assertRaises(ValueError):
                F.display(x, stops)

    def test_complete_loader_entry_and_poweroff_restore(self):
        # Run the actual payload entry, not Camera's default ENTRY shortcut.
        class Card(T.Camera):
            allocations = 0

            def _hook(self, mu, addr, size, data):
                if addr == self.entry:
                    self.entry = None
                if addr == T.F['H_ADDR']:
                    result = T.HEAP + self.allocations * 0x100000
                    self.allocations += 1
                    return self._ret(result)
                return super()._hook(mu, addr, size, data)

        with tempfile.TemporaryDirectory() as td:
            blob = Path(td) / 'lv-boost.bin'
            blob.write_bytes(self.blob)
            args = ['--no-shell', '--boot-bin', str(blob) + ':0']
            for a, word, _ in B.hook_sites(True):
                f = Path(td) / f'{a:x}.bin'
                f.write_bytes(word)
                args += ['--also-bin', f'{a:#x}:{f}']
            loader, binary = T.build(args, hook=True)
            cam = Card(loader, binary)
            cam.mu.mem_write(B.SEG1_BASE, B.SEG1.read_bytes())
            cam.call(T.CAVE_LOW, sp=STACK)
            self.assertEqual(cam.allocations, 2)
            self.assertEqual(cam.word(0xC06C07D8), 0xE3A02011)
            self.assertNotEqual(cam.word(TONE), 0xE5901004)
            self.assertEqual(len(cam.registered), 2)
            obj = cam.registered[0][0]
            for _ in range(2):
                cam.call(cam.word(obj + 4), r0=obj, r1=4)
            for a, word, _ in B.hook_sites(True):
                self.assertEqual(bytes(cam.mu.mem_read(a, 4)), word, hex(a))
            # Simulate retained RAM after the power-off callback. The loader
            # hook must reinstall our menu/preview hooks without AutoRun.
            cam.call(T.CAVE_LOW + 4, r0=0xC0BABDD8, r1=1,
                     lr=T.AR_RET, sp=T.STACK - 0x1004)
            self.assertIsNone(cam.ar_started)
            self.assertEqual(cam.allocations, 4)
            self.assertEqual(cam.word(0xC06C07D8), 0xE3A02011)
            self.assertNotEqual(cam.word(TONE), 0xE5901004)


class Startup(unittest.TestCase):
    default_level = 2

    @classmethod
    def setUpClass(cls):
        cls.blob, cls.info = B.build_blob(True, cls.default_level)

    def run_startup(self, states, cancel_at=None, task_result=7, refuse_color=False,
                    preference=0, expected_level=2):
        r = Rig(self.blob, task_result=task_result, preference=preference)
        self.assertEqual(r.cam.word(SAVE), preference)
        # Native restore callbacks before the task must not overwrite saved data.
        r.step(0xC0075CF4, r4=0xC31ACDC4, sl=12, r6=0)
        self.assertEqual(r.cam.word(SAVE), preference)
        self.assertEqual(r.task[:2], (0, 0x41))
        self.assertTrue(RES <= r.task[2] < RES + self.info['resident'])
        self.assertEqual(r.task[3:5], (28, 0x2000))
        self.assertEqual(r.cam.word(RES + 0x54), task_result & 0xFFFFFFFF)
        self.assertEqual(r.task_started, task_result > 0)
        if task_result <= 0:
            return r, []
        ticks, changes, native_color = [0], [], [0]
        saved = {}

        # Mock the native settings facade/API; execute our real setter hook.
        # This proves request timing/arguments and private menu state, not
        # firmware notification timing or thread safety on the physical camera.
        def firmware(mu, addr, size, data):
            if addr not in (0xC01F89C4, 0xC0057AE8, 0xC005C958, 0xC005C990, 0xC0075CF8):
                return
            if addr == 0xC0075CF8 and saved:
                for reg, value in saved.items():
                    mu.reg_write(reg, value)
                saved.clear()
                return r.cam._ret(0)
            self.assertEqual(mu.reg_read(UC_ARM_REG_SP) % 8, 0)
            if addr == 0xC01F89C4:
                delay = mu.reg_read(UC_ARM_REG_R0)
                if delay == 60000:
                    mu.emu_stop()
                    return
                self.assertEqual(delay, 100)
                ticks[0] += 1
                self.assertLessEqual(ticks[0], len(states), 'startup never finished')
                app, attribute = states[ticks[0] - 1]
                r.put(APP, app)
                r.put(0xC3033A54, attribute)
                if ticks[0] == cancel_at:
                    r.put(RES + 0x50, 2)
                return r.cam._ret(0)
            if addr == 0xC0057AE8:
                return r.cam._ret(r.conv)
            if addr == 0xC005C990:
                return r.cam._ret(native_color[0])
            if addr == 0xC005C958:
                self.assertEqual(mu.reg_read(UC_ARM_REG_R0), r.conv)
                self.assertEqual(mu.reg_read(UC_ARM_REG_R1), 12)
                self.assertEqual(mu.reg_read(UC_ARM_REG_R2), 1)
                self.assertEqual(r.cam.word(VAR), expected_level - 1)
                self.assertEqual(r.cam.word(RES + 0x94), 17)
                changes.append(ticks[0])
                if refuse_color:
                    return r.cam._ret(0)
                for reg in (UC_ARM_REG_R4, UC_ARM_REG_R6, UC_ARM_REG_SL, UC_ARM_REG_LR):
                    saved[reg] = mu.reg_read(reg)
                mu.reg_write(UC_ARM_REG_R4, 0xC31ACDC4)
                mu.reg_write(UC_ARM_REG_R6, 12)
                mu.reg_write(UC_ARM_REG_SL, native_color[0])
                native_color[0] = 12
                mu.reg_write(UC_ARM_REG_PC, 0xC0075CF4)
        handle = r.mu.hook_add(UC_HOOK_CODE, firmware)
        r.mu.reg_write(UC_ARM_REG_SP, STACK)
        r.mu.emu_start(r.task[2], T.DONE, count=200000)
        self.assertEqual(r.mu.reg_read(UC_ARM_REG_SP), STACK)
        r.mu.hook_del(handle)
        # Subsequent Rig.step stops at CF8; discard the larger setter block
        # translated while the API mock was returning through that address.
        r.mu.ctl_remove_cache(0xC0075CF4, 0xC0075D34)
        return r, changes

    def test_stable_still_selects_default_once_and_user_can_disable(self):
        r, changes = self.run_startup([(2, 1)] * 10)
        self.assertEqual(changes, [10])
        self.assertEqual(r.cam.word(RES + 0x50), 1)
        self.assertEqual(r.cam.word(FLAG), 1)
        self.assertEqual(r.cam.word(RES + 0x98 + 15 * 8 + 4), 16)
        self.assertEqual(r.tone(), T.HEAP + (self.default_level - 1) * 4096)
        r.select(15)
        self.assertEqual(r.cam.word(FLAG), 0)
        self.assertEqual(r.tone(), ORIGINAL)

    def test_saved_levels_disable_and_reenable_across_reboots(self):
        for level in (1, 2, 3):
            with self.subTest(level=level):
                r, _ = self.run_startup([(2, 1)] * 10)
                r.step(0xC0568A3C, r1=level)
                saved = r.cam.word(SAVE)
                self.assertEqual(saved, MAGIC | 4 | (level - 1))
                reboot, changes = self.run_startup([(2, 1)] * 10,
                    preference=saved, expected_level=level)
                self.assertEqual(changes, [10])
                self.assertEqual(reboot.tone(), T.HEAP + (level - 1) * 4096)
                for row in (0, 15):  # native preset and native OFF
                    reboot.select(row)
                    saved = reboot.cam.word(SAVE)
                    self.assertEqual(saved, MAGIC | (level - 1))
                    disabled, changes = self.run_startup([(2, 1)], preference=saved)
                    self.assertEqual(changes, [])
                    self.assertEqual(disabled.cam.word(RES + 0x50), 5)
                    self.assertEqual(disabled.cam.word(VAR), level - 1)
                    self.assertEqual(disabled.cam.word(FLAG), 0)
                    disabled.select(16)
                    self.assertEqual(disabled.cam.word(SAVE), MAGIC | 4 | (level - 1))
                # Non-menu native preset changes also disable after startup.
                reboot.select(16)
                reboot.step(0xC0075CF4, r4=0xC31ACDC4, sl=12, r6=1)
                self.assertEqual(reboot.cam.word(SAVE), MAGIC | (level - 1))

    def test_invalid_preferences_fall_back_and_failed_restore_keeps_saved_word(self):
        for invalid in (0, 0xFFFFFFFF, MAGIC | 3, MAGIC | 7, MAGIC ^ 0x100):
            r, changes = self.run_startup([(2, 1)] * 10, preference=invalid)
            self.assertEqual(changes, [10])
            self.assertEqual(r.cam.word(SAVE), MAGIC | 5)
        r, _ = self.run_startup([(2, 1)] * 10, preference=MAGIC | 6,
                                expected_level=3, refuse_color=True)
        self.assertEqual(r.cam.word(SAVE), MAGIC | 6)
        # A choice before the startup worker runs wins and saves the loaded level.
        r = Rig(self.blob, preference=MAGIC | 6)
        r.select(0)
        self.assertEqual(r.cam.word(SAVE), MAGIC | 2)
        self.assertEqual(r.cam.word(RES + 0x50), 2)

    def test_preference_write_is_one_word_outside_other_settings(self):
        r, _ = self.run_startup([(2, 1)] * 10)
        start, length = 0xC307523C, 0x410
        before = bytes(r.mu.mem_read(start, length))
        writes = []
        handle = r.mu.hook_add(UC_HOOK_MEM_WRITE,
            lambda mu, access, addr, size, value, data: writes.append((addr, size)),
            begin=start, end=start + length - 1)
        r.step(0xC0568A3C, r1=1)
        r.select(0)
        r.mu.hook_del(handle)
        self.assertEqual(writes, [(SAVE, 4), (SAVE, 4)])
        after = bytes(r.mu.mem_read(start, length))
        self.assertEqual(before[:0x210], after[:0x210])
        self.assertEqual(before[0x214:], after[0x214:])
        self.assertNotIn(SAVE, {a for a, _, _ in B.hook_sites(True)})

    def test_cine_playback_and_transitions_do_not_trigger_default(self):
        states = [(2, 2)] * 20 + [(3, 1)] * 10 + [(2, 1)] * 9 + [(2, 0)] + [(5, 1)] * 10
        r, changes = self.run_startup(states)
        self.assertEqual(changes, [len(states)])
        self.assertEqual(r.cam.word(RES + 0x50), 1)

    def test_manual_choice_and_creation_failure_keep_native_color(self):
        r, changes = self.run_startup([(2, 1)] * 5, cancel_at=5)
        self.assertEqual(changes, [])
        self.assertEqual(r.cam.word(FLAG), 0)
        r, changes = self.run_startup([], task_result=-1)
        self.assertEqual(changes, [])
        self.assertEqual(r.cam.word(FLAG), 0)
        r.select(0)
        self.assertEqual(r.cam.word(RES + 0x50), 2)

    def test_failed_native_selection_is_reported_without_retry(self):
        r, changes = self.run_startup([(2, 1)] * 10, refuse_color=True)
        self.assertEqual(changes, [10])
        self.assertEqual(r.cam.word(RES + 0x50), 4)
        self.assertEqual(r.cam.word(RES + 0x94), 0)


if __name__ == '__main__':
    unittest.main()
