"""Execute the emitted ARM core, including failure and warm recovery paths.

Unicorn runs local synthetic RAM plus the pinned firmware image. There is no
camera transport. Tests deliberately fail if the emulator is unavailable.
"""
from __future__ import annotations

import importlib.util
import pathlib
import struct
import sys
import unittest

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import *

import core_build as core

sys.path.insert(0, str(core.ROOT / "projects" / "open-gate" / "build"))
import og4k_plan
import sizesim

CODE = 0x10000000
STACK = 0x11000000
STATE = 0x12000000
CANVAS = STATE + 0x1000
CONTEXT = STATE + 0x2000
STOP = CODE + 0xFF0


def packed(values):
    return struct.pack(f"<{len(values)}I", *values)


def canvas(profile):
    row = sizesim.w32(sizesim.MAP + profile * 4)
    return [sizesim.w32(base + row * 4) for base in sizesim.COL]


class Machine:
    def __init__(self, blob, symbols, image):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.uc.mem_map(core.BASE, (len(image) + 4095) & ~4095)
        self.uc.mem_write(core.BASE, image)
        self.uc.mem_map(CODE, 0x1000)
        self.uc.mem_write(CODE, blob)
        self.uc.mem_map(STACK, 0x4000)
        self.uc.mem_map(STATE, 0x3000)
        self.symbols = symbols
        self.writes = []
        self.inject = None
        self.pending = None
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self._write)
        self.uc.hook_add(UC_HOOK_CODE, self._instruction)

    def _write(self, uc, access, address, size, value, data):
        self.writes.append((address, size, value))
        if self.inject:
            replacement = self.inject(address, value, self.word(address))
            if replacement is not None:
                self.pending = (address, replacement)

    def _instruction(self, uc, address, size, data):
        if self.pending:
            target, value = self.pending
            self.put(target, [value])
            self.pending = None

    def put(self, address, values):
        self.uc.mem_write(address, packed(values))

    def words(self, address, count):
        return tuple(struct.unpack(f"<{count}I", self.uc.mem_read(address, count * 4)))

    def word(self, address):
        return self.words(address, 1)[0]

    def call(self, name, r0, r1, masks=0):
        self.writes = []
        self.uc.reg_write(UC_ARM_REG_CPSR, 0x13 | masks)
        self.uc.reg_write(UC_ARM_REG_SP, STACK + 0x3FF0)
        self.uc.reg_write(UC_ARM_REG_LR, STOP)
        self.uc.reg_write(UC_ARM_REG_R0, r0)
        self.uc.reg_write(UC_ARM_REG_R1, r1)
        saved = (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                 UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)
        for index, reg in enumerate(saved):
            self.uc.reg_write(reg, 0xABCD0000 + index)
        self.uc.emu_start(CODE + self.symbols[name], STOP, count=20000)
        assert self.uc.reg_read(UC_ARM_REG_PC) == STOP, "core did not return"
        assert self.uc.reg_read(UC_ARM_REG_SP) == STACK + 0x3FF0
        assert self.uc.reg_read(UC_ARM_REG_CPSR) & 0xC0 == masks
        for index, reg in enumerate(saved):
            assert self.uc.reg_read(reg) == 0xABCD0000 + index
        return self.uc.reg_read(UC_ARM_REG_R0)


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob, cls.symbols = core.build()
        cls.image = core.load_firmware()
        cls.frontend = core.table(cls.blob, cls.symbols, "frontend", 10, 3)

    def setUp(self):
        self.m = Machine(self.blob, self.symbols, self.image)

    def reset(self):
        for address, stock, _ in self.frontend:
            self.m.put(address, [stock])
        self.m.put(STATE, [core.MAGIC, 0, 0, 0])

    def assert_frontend(self, column):
        for row in self.frontend:
            self.assertEqual(self.m.word(row[0]), row[column])

    def test_tables_match_independently_derived_firmware_plan(self):
        self.assertEqual(self.frontend, tuple((p.address, p.expected, p.replacement)
                                            for p in og4k_plan.derive_frontend_patches(self.image)))
        self.assertEqual(core.table(self.blob, self.symbols, "record_request", 1, 9)[0],
                         core.RECORD_REQUEST)
        self.assertEqual(core.table(self.blob, self.symbols, "playback_frame", 1, 10)[0],
                         core.PLAYBACK_FRAME)
        row = sizesim.w32(sizesim.MAP + 429 * 4)
        for off, stock, new in core.table(self.blob, self.symbols, "record_pairs", 8, 3):
            address = sizesim.COL[off // 4] + row * 4
            self.assertIn((address, stock, new),
                          [(p.address, p.expected, p.replacement) for p in og4k_plan.OUTPUT_PATCHES])

    def test_cold_init_repeated_on_off_and_irq_masks(self):
        self.m.put(STATE, [0xAAAAAAAA] * 4)
        self.assertEqual(self.m.call("transition", STATE, 2), 0)
        self.assertEqual(self.m.words(STATE, 4), (core.MAGIC, 0, 0, 0))
        for masks in (0, 0x40, 0x80, 0xC0):
            for action in (1, 1, 0, 0):
                self.assertEqual(self.m.call("transition", STATE, action, masks), 0)
                self.assert_frontend(2 if action else 1)
                self.assertEqual(self.m.words(STATE, 4), (core.MAGIC, action, 0, 0))

    def test_all_1024_known_partial_warm_boot_states_restore(self):
        for mask in range(1 << 10):
            for i, row in enumerate(self.frontend):
                self.m.put(row[0], [row[2] if mask & (1 << i) else row[1]])
            self.m.put(STATE, [0xDEADBEEF, 1, 7, 1])
            self.assertEqual(self.m.call("transition", STATE, 2), 0, mask)
            self.assert_frontend(1)
            self.assertEqual(self.m.words(STATE, 4), (core.MAGIC, 0, 0, 0))

    def test_unknown_word_and_foreign_timing_refuse_without_frontend_writes(self):
        for address, stock, _ in self.frontend:
            self.reset()
            self.m.put(address, [stock ^ 0x80000000])
            self.assertEqual(self.m.call("transition", STATE, 2), 2)
            self.assertFalse(any(core.BASE <= a < core.BASE + len(self.image)
                                 for a, _, _ in self.m.writes))
        for address in (0xC0B59D04, 0xC0B59D08):
            self.reset()
            original = self.m.word(address)
            self.m.put(address, [original ^ 1])
            self.assertEqual(self.m.call("transition", STATE, 1), 3)
            self.assert_frontend(1)
            self.m.put(address, [original])

    def test_each_dropped_frontend_write_rolls_back(self):
        for address, _, _ in self.frontend:
            self.reset()
            dropped = []
            def inject(target, value, old):
                if target == address and not dropped:
                    dropped.append(True)
                    return old
            self.m.inject = inject
            self.assertEqual(self.m.call("transition", STATE, 1), 4, hex(address))
            self.assert_frontend(1)
            self.assertEqual(self.m.words(STATE, 4), (core.MAGIC, 0, 4, 0))
        self.m.inject = None

    def test_rollback_failure_never_publishes_enabled(self):
        self.reset()
        target = self.frontend[0][0]
        self.m.inject = lambda address, value, old: 0xDEADBEEF if address == target else None
        self.assertEqual(self.m.call("transition", STATE, 1), 5)
        self.assertEqual(self.m.words(STATE, 4), (0, 0, 5, 0))
        self.assertEqual(self.m.call("transition", STATE, 1), 1)

    def test_refused_request_never_changes_unowned_or_busy_state(self):
        self.reset()
        self.assertEqual(self.m.call("transition", STATE, 1), 0)
        for state, action in (((core.MAGIC, 1, 0, 0), 3),
                              ((core.MAGIC, 1, 0, 1), 0),
                              ((0xBAD00000, 1, 0, 0), 0)):
            self.m.put(STATE, state)
            self.assertEqual(self.m.call("transition", STATE, action), 1)
            self.assertEqual(self.m.words(STATE, 4), state)
            self.assert_frontend(2)

    def test_failed_off_rollback_preserves_enabled_and_can_retry(self):
        self.reset()
        self.assertEqual(self.m.call("transition", STATE, 1), 0)
        target = self.frontend[4][0]
        dropped = []
        def inject(address, value, old):
            if address == target and not dropped:
                dropped.append(True)
                return old
        self.m.inject = inject
        self.assertEqual(self.m.call("transition", STATE, 0), 4)
        self.assert_frontend(2)
        self.assertEqual(self.m.words(STATE, 4), (core.MAGIC, 1, 4, 0))
        self.m.inject = None
        self.assertEqual(self.m.call("transition", STATE, 0), 0)
        self.assert_frontend(1)

    def test_transition_write_scope_and_publication_order(self):
        self.reset()
        self.assertEqual(self.m.call("transition", STATE, 1), 0)
        addresses = {row[0] for row in self.frontend}
        for address, size, _ in self.m.writes:
            self.assertTrue(address in addresses or STATE <= address < STATE + 16
                            or STACK <= address < STACK + 0x4000, hex(address))
        publish = [i for i, (address, _, value) in enumerate(self.m.writes)
                   if address == STATE + 4 and value == 1]
        data = [i for i, (address, _, _) in enumerate(self.m.writes) if address in addresses]
        self.assertEqual(len(publish), 1)
        self.assertGreater(publish[0], max(data))

    def test_record_canvas_changes_only_eight_raw_fields(self):
        before = canvas(429)
        self.m.put(CANVAS, before)
        self.m.put(CONTEXT, core.RECORD_REQUEST)
        self.assertEqual(self.m.call("record_canvas", CANVAS, CONTEXT), 1)
        after = list(self.m.words(CANVAS, 65))
        expected = list(before)
        for off, _, new in core.table(self.blob, self.symbols, "record_pairs", 8, 3):
            expected[off // 4] = new
        self.assertEqual(after, expected)
        for off in (0x0C, 0x10, 0xD8, 0xE0, 0xF4, 0xF8):
            self.assertEqual(after[off // 4], before[off // 4])
        self.assertEqual(bytes(self.m.uc.mem_read(core.BASE, len(self.image))), self.image)

    def test_record_rejects_each_unsupported_setting_and_bad_donor_before_write(self):
        before = canvas(429)
        for index in range(9):
            request = list(core.RECORD_REQUEST)
            request[index] ^= 1
            self.m.put(CANVAS, before)
            self.m.put(CONTEXT, request)
            self.assertEqual(self.m.call("record_canvas", CANVAS, CONTEXT), 0)
            self.assertEqual(self.m.words(CANVAS, 65), tuple(before))
        self.m.put(CONTEXT, core.RECORD_REQUEST)
        fields = [p[0] for p in core.table(self.blob, self.symbols, "record_pairs", 8, 3)]
        for off in fields + [0x80, 0x84, 0x3C]:
            changed = list(before)
            changed[off // 4] ^= 1
            self.m.put(CANVAS, changed)
            self.assertEqual(self.m.call("record_canvas", CANVAS, CONTEXT), 2)
            self.assertEqual(self.m.words(CANVAS, 65), tuple(changed))

    def test_playback_matches_file_geometry_independent_of_selection(self):
        for profile in (71,):
            before = canvas(profile)
            self.m.put(CANVAS, before)
            self.m.put(CONTEXT, core.PLAYBACK_FRAME)
            self.m.put(STATE, [0, 0, 0, 0])
            self.assertEqual(self.m.call("playback_canvas", CANVAS, CONTEXT), 1)
            expected = list(before)
            for off, new in core.table(self.blob, self.symbols, "playback_pairs", 13, 2):
                expected[off // 4] = new
            self.assertEqual(self.m.words(CANVAS, 65), tuple(expected))

    def test_playback_rejects_compressed_wrong_bitdepth_crop_and_strip(self):
        before = canvas(71)
        for index in range(10):
            frame = list(core.PLAYBACK_FRAME)
            frame[index] ^= 1
            self.m.put(CANVAS, before)
            self.m.put(CONTEXT, frame)
            self.assertEqual(self.m.call("playback_canvas", CANVAS, CONTEXT), 0)
            self.assertEqual(self.m.words(CANVAS, 65), tuple(before))
        for profile in (43, 51, 53, 73, 83, 429):
            before = canvas(profile)
            self.m.put(CANVAS, before)
            self.m.put(CONTEXT, core.PLAYBACK_FRAME)
            self.assertEqual(self.m.call("playback_canvas", CANVAS, CONTEXT), 2)
            self.assertEqual(self.m.words(CANVAS, 65), tuple(before))


if __name__ == "__main__":
    unittest.main()
