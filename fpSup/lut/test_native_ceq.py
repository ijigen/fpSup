"""Actual Thumb-2 firmware packing emulation; not ISP silicon emulation."""
import hashlib
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

import native_ceq
from native_ceq import CEQResource

from unicorn import (Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE,
                     UC_PROT_READ, UC_PROT_EXEC)
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                               UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
                               UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
                               UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9,
                               UC_ARM_REG_R10, UC_ARM_REG_R11)

ROOT = Path(__file__).resolve().parents[2]
ROM = ROOT / 'out/MAIN_c0000000.bin'
EXPAND, EXPAND_END = 0xC01084D8, 0xC01089A8
ROUTE, ROUTE_END = 0xC0108C98, 0xC0109768
INPUT, PARAMS, STACK, DONE = 0x45000000, 0x45001000, 0x46000000, 0x47000000
CALLEE_SAVED = (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)


def firmware_tables(resource, context=0):
    rom = ROM.read_bytes()
    emulator = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    emulator.mem_map(0xC0000000, 0x3000000)
    emulator.mem_write(0xC0000000, rom)
    emulator.mem_protect(0xC0000000, 0x3000000, UC_PROT_READ | UC_PROT_EXEC)
    for base, size in ((INPUT, 0x3000), (STACK, 0x4000),
                       (0x30210000, 0x10000), (0x30240000, 0x10000)):
        emulator.mem_map(base, size)
    emulator.mem_write(INPUT, resource.to_bytes())
    emulator.mem_protect(INPUT, 0x1000, UC_PROT_READ)
    allowed = []
    visited = [0]
    def guard(uc, address, size, _):
        if address == DONE:
            uc.emu_stop()
        elif any(low <= address < high for low, high in allowed):
            visited[0] += 1
        else:
            raise RuntimeError(f'unreviewed ROM execution at {address:08X}')
    emulator.hook_add(UC_HOOK_CODE, guard)
    def call(address, end, args):
        allowed[:] = [(address, end)]
        values = [0x24680000 + i for i in range(8)]
        for register, value in zip(CALLEE_SAVED, values):
            emulator.reg_write(register, value)
        for register, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2), args):
            emulator.reg_write(register, value)
        sp = STACK + 0x3FF0
        emulator.reg_write(UC_ARM_REG_SP, sp)
        emulator.reg_write(UC_ARM_REG_LR, DONE)
        emulator.emu_start(address | 1, DONE, count=10000)
        if emulator.reg_read(UC_ARM_REG_PC) != DONE:
            raise RuntimeError('firmware did not return within instruction bound')
        if emulator.reg_read(UC_ARM_REG_SP) != sp:
            raise RuntimeError('firmware stack restoration mismatch')
        if [emulator.reg_read(r) for r in CALLEE_SAVED] != values:
            raise RuntimeError('firmware callee-saved register mismatch')
    call(EXPAND, EXPAND_END, (1, INPUT, PARAMS))
    call(ROUTE, ROUTE_END, (PARAMS, context, 0))
    result = {}
    for key, (address, count) in native_ceq.TABLES.items():
        result[key] = list(struct.unpack('<' + 'I' * count,
                          emulator.mem_read(address + 0x30000 * context, count * 4)))
    return result, {'rom_sha256': hashlib.sha256(rom).hexdigest(),
                    'instructions': visited[0], 'hardware_pixels_emulated': False}


class CEQTests(unittest.TestCase):
    def test_exact_layout_matches_real_arm_for_both_contexts(self):
        resource = CEQResource(tuple(tuple((i * 2891 + plane * 8191) & 65535
                                          for i in range(24)) for plane in range(6)))
        for context in (0, 1):
            actual, evidence = firmware_tables(resource, context)
            expected = {key: v['words'] for key, v in resource.shadow_tables(context).items()}
            self.assertEqual(actual, expected)
            self.assertGreater(evidence['instructions'], 0)
            self.assertEqual(CEQResource.from_shadow_tables(actual), resource)

    def test_encoding_scaling_mutation_is_detected(self):
        resource = CEQResource(tuple(tuple(range(1, 25)) for _ in range(6)))
        actual, _ = firmware_tables(resource)
        with patch.object(native_ceq, 'PLANE_B_SHIFT', 0):
            bad = {key: v['words'] for key, v in resource.shadow_tables().items()}
        with self.assertRaises(AssertionError):
            self.assertEqual(actual, bad)

    def test_source_byte_roundtrip_and_input_rejections(self):
        data = struct.pack('<144H', *range(144))
        self.assertEqual(CEQResource.from_bytes(data).to_bytes(), data)
        for bad in (data[:-2], data + b'\0\0'):
            with self.assertRaises(ValueError): CEQResource.from_bytes(bad)
        with self.assertRaises(ValueError): CEQResource([[0] * 24] * 5)
        with self.assertRaises(ValueError): CEQResource([[0.1] * 24] * 6)
        with self.assertRaises(ValueError): CEQResource([[-1] * 24] * 6)
        with self.assertRaises(ValueError): CEQResource([[65536] * 24] * 6)

    def test_shadow_decode_refuses_to_round_unrepresentable_values(self):
        resource = CEQResource([[0] * 24] * 6)
        tables = {key: v['words'] for key, v in resource.shadow_tables().items()}
        tables['ORG'][16] = 1
        with self.assertRaisesRegex(ValueError, 'losslessly'):
            CEQResource.from_shadow_tables(tables)

    def test_native_trial_snapshots_encode_exactly(self):
        import json
        report = ROOT / 'projects/lut-sup/validation/20261009-native-controls-trial-01/report.json'
        self.assertTrue(report.is_file(), 'actual camera evidence required')
        data = json.loads(report.read_text())
        count = 0
        refused = []
        for group in data['groups']:
            for condition in group['conditions']:
                for sample in condition['changed']:
                    for context in (0, 1):
                        try:
                            resource = CEQResource.from_snapshot(sample['regions'], context)
                        except ValueError as error:
                            refused.append((group['name'], condition['label'], context, str(error)))
                            continue
                        self.assertEqual(CEQResource.from_bytes(resource.to_bytes()), resource)
                        actual, _ = firmware_tables(resource, context)
                        expected = {k: v['words'] for k, v in resource.shadow_tables(context).items()}
                        self.assertEqual(actual, expected)
                        count += 1
        # A sequential read contains one non-u16 transient word. Never round or
        # silently truncate that observation into a deployable resource.
        self.assertEqual(count, 83)
        self.assertEqual(refused, [('Standard', 'saturation_high', 0,
                                   'CEQ source values must be exact u16 integers')])


if __name__ == '__main__':
    unittest.main()
