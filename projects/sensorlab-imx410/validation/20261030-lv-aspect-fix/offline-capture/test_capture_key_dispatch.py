#!/usr/bin/env python3
"""Bounded ROM proof: CAPTUREON -> GUI 0x18 -> RecMgr screenshot 0x18.

No USB, camera, product source/build or hardware. The real seg1 overlay is
required: MAIN alone contains compressed data at C2F2xxxx. Native strcmp,
table lookup, key translation, GUI packet construction, table initializer,
current-screen dispatch, capture handler, virtual RecMgr bridge and screenshot
request constructor execute unchanged ROM instructions. Explicit stubs isolate
runtime eligibility, GUI pre-notification, logging, locks, queue handoff and
singleton ownership. This does not run the complete EventMessageMgr worker or
prove current camera state, GUI lifetime, hardware capture, stride or LCD.

Run with /usr/bin/python3 -B <this file> [--json output.json]. On hosts where
the sandbox prohibits Unicorn's JIT, run this same offline command with normal
approval. Missing Unicorn/ROM is an error, not a skip/pass.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import unittest

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn import arm_const as R

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
ROM, SEG1 = 0xC0000000, 0xC2EF6E00
WORK, STACK, STOP = 0x10000000, 0x10010000, 0x10030000
OBSERVER, GUI, SCREEN, MANAGER = (WORK+x for x in (0x100, 0x200, 0x300, 0x400))
RECMGR, CAMERA, CAPSTATE, EVENT = (WORK+x for x in (0x500, 0x600, 0x700, 0x800))
KEYTABLE, GUITABLE = 0xC2F205C0, 0xC2F23848
VTABLES = {'standby': 0xC0CD7960, 'qs': 0xC0CD1234}
NOTIFIER, KEYQUEUE, KEYHANDLE = (WORK+x for x in (0xC00, 0xD00, 0xE00))
NATIVE = (
    (0xC0013E2C, 0xC0013EFC, 'strcmp'),
    (0xC01F575C, 0xC01F578C, 'strncmp'),
    (0xC0015058, 0xC0015108, 'memset'),
    (0xC03F5730, 0xC03F578C, 'shell-key-lookup'),
    (0xC03F5DC0, 0xC03F6038, 'shell-key-command'),
    (0xC02DBBE8, 0xC02DBC18, 'physical-key-submit'),
    (0xC02DBFF0, 0xC02DC030, 'physical-key-queue-send'),
    (0xC02DC138, 0xC02DC1A0, 'physical-key-observer-dispatch'),
    (0xC0515960, 0xC0515A00, 'DeviceOperationObserver-v1'),
    (0xC0515A28, 0xC0515A60, 'physical-key-press'),
    (0xC0515AB0, 0xC0515AE8, 'physical-key-release'),
    (0xC0516950, 0xC0516A34, 'GUI-key-packet'),
    (0xC05166E8, 0xC0516780, 'GUI-queue-packet'),
    (0xC05123D8, 0xC0512738, 'GUI-callback-initializer'),
    (0xC0510EB8, 0xC0511000, 'current-screen-dispatch'),
    (0xC05114E0, 0xC0511504, 'GUI-18-wrapper'),
    (0xC0451478, 0xC04514AC, 'CommonEventHandler-v25'),
    (0xC04B6B00, 0xC04B6B44, 'capture-request'),
    (0xC0371428, 0xC0371468, 'RecMgr-virtual-screenshot'),
    (0xC0372688, 0xC03726E8, 'RecMgr-screenshot-constructor'),
    (0xC0446608, 0xC044661C, 'GUI-after-key-noop'),
)
ALL_RESULTS = []


def w(mu, address, *values):
    mu.mem_write(address, struct.pack('<'+'I'*len(values), *values))


def words(mu, address, count=1):
    return struct.unpack('<'+'I'*count, mu.mem_read(address, 4*count))


class KeyDispatch:
    def __init__(self):
        self.mu = mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        main = (ROOT/'out/MAIN_c0000000.bin').read_bytes()
        seg1 = (ROOT/'out/seg1_c2ef6e00.bin').read_bytes()
        mu.mem_map(ROM, 0x03000000)
        mu.mem_write(ROM, main[:0x03000000])
        mu.mem_write(SEG1, seg1)
        mu.mem_map(WORK, 0x1000)
        mu.mem_map(STACK, 0x10000)
        mu.mem_map(STOP, 0x1000)
        self.executed = set()
        self.stub_calls = []
        self.gui_packets = []
        self.physical_keys = []
        self.requests = []
        self.eligible = 1
        self.capture_state = 0
        self.reached = False
        w(mu, OBSERVER, 0xC0CFD550, GUI)
        w(mu, NOTIFIER, OBSERVER, 0, 0, 0, 0, 0, 0)
        w(mu, NOTIFIER+0x24, KEYQUEUE)
        w(mu, KEYQUEUE+4, KEYHANDLE)
        w(mu, RECMGR, 0xC0B9928C, CAMERA)
        w(mu, MANAGER+4, WORK+0x900)
        self.stubs = {
            0xC0513660: ('GUI-singleton', GUI),
            0xC02DBAF0: ('physical-key-notifier-singleton', NOTIFIER),
            0xC0513BE8: ('GUI-filter-inactive', 0),
            0xC0512978: ('key-policy-singleton', WORK+0xA00),
            0xC0512A70: ('key-coalescing-inactive', 0),
            0xC0019DC0: ('logger-singleton', 0),
            0xC001A048: ('log', 0),
            0xC001A0D8: ('log-dispatch', 0),
            0xC001CCE0: ('interrupt-lock', 0),
            0xC001CD18: ('interrupt-unlock', 0),
            0xC036D758: ('GUI-worker-notify', 1),
            0xC05149A0: ('GUI-screen-id', 1),
            0xC0514968: ('GUI-mode-id', 0),
            0xC0513D40: ('no-screen-observer', 0),
            0xC04820F0: ('standby-before-key-notify', 0),
            0xC0471570: ('QS-before-key-notify', 0),
            0xC04B67E0: ('capture-state-singleton', CAPSTATE),
            0xC0370CF8: ('RecMgr-singleton', RECMGR),
            0xC02ECC68: ('capture-display-singleton', 0),
            0xC02ECCC0: ('capture-display-mode', 0),
        }
        mu.hook_add(UC_HOOK_CODE, self.code)
        mu.hook_add(UC_HOOK_MEM_WRITE, self.write)

    def ret(self, value):
        self.mu.reg_write(R.UC_ARM_REG_R0, value)
        self.mu.reg_write(R.UC_ARM_REG_PC, self.mu.reg_read(R.UC_ARM_REG_LR))

    def code(self, mu, address, size, _):
        if address == STOP:
            self.reached = True
            return mu.emu_stop()
        args = tuple(mu.reg_read(r) for r in (R.UC_ARM_REG_R0, R.UC_ARM_REG_R1,
                                             R.UC_ARM_REG_R2, R.UC_ARM_REG_R3))
        if address == 0xC01F8D24:
            assert (args[0], args[2], args[3]) == (KEYHANDLE, 4, 3000)
            self.physical_keys.append(words(mu, args[1])[0])
            self.stub_calls.append(('physical-key-RTOS-queue-handoff', address, args))
            return self.ret(0)
        if address == 0xC05162F8:
            assert args[0] == GUI+4
            self.gui_packets.append(bytes(mu.mem_read(args[1], 0x2C)))
            self.stub_calls.append(('GUI-queue-handoff', address, args))
            return self.ret(1)
        if address == 0xC03A0798:
            assert args[0] == CAMERA
            self.requests.append(bytes(mu.mem_read(args[1], 0xBC)))
            self.stub_calls.append(('CameraFunction-queue-handoff', address, args))
            return self.ret(1)
        if address in (0xC04B6818, 0xC04B6A28):
            value = self.eligible if address == 0xC04B6818 else self.capture_state
            self.stub_calls.append(('capture-eligibility' if address == 0xC04B6818
                                    else 'capture-state', address, args))
            return self.ret(value)
        if address in self.stubs:
            name, value = self.stubs[address]
            self.stub_calls.append((name, address, args))
            return self.ret(value)
        for lo, hi, name in NATIVE:
            if lo <= address and address+size <= hi:
                self.executed.add(name)
                return
        raise AssertionError(f'unapproved native execution {address:#010x}')

    def write(self, mu, access, address, size, value, _):
        if ((WORK <= address and address+size <= WORK+0x1000) or
                (STACK <= address and address+size <= STACK+0x10000)):
            return
        # Only the real boot callback initializer may populate this table.
        if (GUITABLE+4 <= address < GUITABLE+0x238 and size == 4 and
                (address-GUITABLE) % 8 == 4 and
                0xC05123D8 <= mu.reg_read(R.UC_ARM_REG_PC) < 0xC0512738):
            return
        raise AssertionError(f'unapproved native write {address:#010x}, size={size}')

    def call(self, address, *args):
        mu = self.mu
        self.reached = False
        for r, value in zip((R.UC_ARM_REG_R0, R.UC_ARM_REG_R1,
                             R.UC_ARM_REG_R2, R.UC_ARM_REG_R3), args):
            mu.reg_write(r, value)
        mu.reg_write(R.UC_ARM_REG_SP, STACK+0xFFF0)
        mu.reg_write(R.UC_ARM_REG_LR, STOP)
        saved = {r: 0xA4000000+i for i, r in enumerate(
            (R.UC_ARM_REG_R4, R.UC_ARM_REG_R5, R.UC_ARM_REG_R6, R.UC_ARM_REG_R7,
             R.UC_ARM_REG_R8, R.UC_ARM_REG_R9, R.UC_ARM_REG_R10, R.UC_ARM_REG_R11))}
        for r, value in saved.items():
            mu.reg_write(r, value)
        mu.emu_start(address, 0, count=200000)
        assert self.reached, 'native function did not return within instruction bound'
        assert mu.reg_read(R.UC_ARM_REG_SP) == STACK+0xFFF0, 'native stack damaged'
        assert all(mu.reg_read(r) == value for r, value in saved.items()), 'saved register damaged'
        return mu.reg_read(R.UC_ARM_REG_R0)

    def physical(self, key):
        self.call(0xC02DC138, NOTIFIER, key)
        return self.gui_packets[-1]

    def dispatch(self, packet, screen='standby'):
        w(self.mu, SCREEN+8, VTABLES[screen])
        self.mu.mem_write(EVENT, packet)
        self.call(0xC0510EB8, MANAGER, SCREEN, EVENT)

    def evidence(self, label):
        ALL_RESULTS.append({'case': label, 'native': sorted(self.executed),
                            'stubs': sorted(set(x[0] for x in self.stub_calls)),
                            'submitted_physical_keys': self.physical_keys,
                            'gui_packets': [p.hex() for p in self.gui_packets],
                            'screenshot_requests': [p.hex() for p in self.requests]})


class CaptureKeyTests(unittest.TestCase):
    def test_shell_key_command_submits_capture_on_and_off(self):
        c = KeyDispatch()
        for name, key in (('CAPTUREON', 0x3B), ('CAPTUREOFF', 0x3C)):
            c.mu.mem_write(WORK, name.encode()+b'\0')
            w(c.mu, WORK+0xB00, WORK)
            c.call(0xC03F5DC0, WORK+0xF00, 1, WORK+0xB00)
            self.assertEqual(c.physical_keys[-1], key)
        c.evidence('shell-key-command-RTOS-handoff')

    def test_real_lookup_uses_seg1_key_names(self):
        c = KeyDispatch()
        for name, entry, key in (('CAPTUREON', 0xC2F207D0, 0x3B),
                                 ('CAPTUREOFF', 0xC2F207DC, 0x3C)):
            c.mu.mem_write(WORK, name.encode()+b'\0')
            self.assertEqual(c.call(0xC03F5730, WORK), entry)
            self.assertEqual(words(c.mu, entry+4)[0], key)
        c.mu.mem_write(WORK, b'NOT_A_CAMERA_KEY\0')
        self.assertEqual(c.call(0xC03F5730, WORK), 0)
        c.evidence('real-key-lookup')

    def test_native_physical_press_release_build_gui_18(self):
        c = KeyDispatch()
        for key, pressed in ((0x3B, 1), (0x3C, 0)):
            packet = c.physical(key)
            self.assertEqual(packet, struct.pack('<I', 0x18)+bytes([pressed])+bytes(39))
        self.assertEqual(words(c.mu, 0xC2F23F54, 5),
                         (0x3B, 0x18, 0, 0xFFFFFFFF, 0xC0515A28))
        c.evidence('physical-key-to-GUI-packet')

    def test_initializer_and_screen_virtuals_are_stock_capture_handler(self):
        c = KeyDispatch()
        self.assertEqual(words(c.mu, 0xC2F23904)[0], 0)
        c.call(0xC05123D8)
        self.assertEqual(words(c.mu, 0xC2F23900, 2), (0x18, 0xC05114E0))
        for vptr in VTABLES.values():
            self.assertEqual(words(c.mu, vptr+0x6C)[0], 0xC0451478)
        self.assertEqual(words(c.mu, 0xC0B9928C+0x7C)[0], 0xC0372688)
        c.evidence('real-GUI-callback-initializer')

    def test_screenshot_event_name_and_CameraFunction_handler_are_exact(self):
        c = KeyDispatch()
        self.assertEqual(words(c.mu, 0xC0B9E1B4, 4),
                         (0x18, 0, 0xFFFFFFFF, 0xC03A1F78))
        self.assertEqual(words(c.mu, 0xC0B9E1C4, 4),
                         (0x19, 0, 0xFFFFFFFF, 0xC03A1FE0))
        pointer = words(c.mu, 0xC2F1FA78+0x18*4)[0]
        self.assertEqual(pointer, 0xC0B9FD5A)
        self.assertEqual(bytes(c.mu.mem_read(pointer, 20)), b'INTR_REC_SCREENSHOT\0')
        c.evidence('exact-event-name-and-handler-table')

    def test_press_routes_stock_standby_and_QS_to_screenshot_request(self):
        for screen in VTABLES:
            for state in (0, 1):
                with self.subTest(screen=screen, state=state):
                    c = KeyDispatch()
                    c.capture_state = state
                    c.call(0xC05123D8)
                    c.dispatch(c.physical(0x3B), screen)
                    request = bytearray(0xBC)
                    struct.pack_into('<I', request, 0, 0x18)
                    request[4] = 1
                    request[0x10:0x12] = bytes([state ^ 1, 1])
                    self.assertEqual(c.requests, [bytes(request)])
                    self.assertEqual(c.mu.mem_read(CAPSTATE, 1), bytes([state]))
                    c.evidence(f'{screen}-press-capture-state-{state}')

    def test_release_or_ineligible_press_does_not_request_capture(self):
        for physical, eligible in ((0x3C, 1), (0x3B, 0)):
            with self.subTest(physical=physical, eligible=eligible):
                c = KeyDispatch()
                c.eligible = eligible
                c.call(0xC05123D8)
                c.dispatch(c.physical(physical))
                self.assertEqual(c.requests, [])
                c.evidence(f'no-request-{physical:02x}-eligibility-{eligible}')

    def test_unknown_native_code_fails_closed(self):
        c = KeyDispatch()
        with self.assertRaisesRegex(AssertionError, 'unapproved native execution'):
            c.call(0xC03726E8)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(CaptureKeyTests))
    report = {'ok': result.wasSuccessful(), 'tests': result.testsRun,
              'failures': len(result.failures), 'errors': len(result.errors),
              'rom': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in (ROOT/'out/MAIN_c0000000.bin', ROOT/'out/seg1_c2ef6e00.bin')},
              'limits': ['Runtime state/eligibility/singleton ownership are declared fixtures.',
                         'Queue append, notify, locks, logging and screen pre-hook are stubs.',
                         'No full GUI worker scheduling or post-C03A0798 handler execution.',
                         'No camera, USB, LCD, JPEG source/stride or hardware capture proof.'],
              'cases': ALL_RESULTS}
    if args.json:
        args.json.write_text(json.dumps(report, indent=2)+'\n')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
