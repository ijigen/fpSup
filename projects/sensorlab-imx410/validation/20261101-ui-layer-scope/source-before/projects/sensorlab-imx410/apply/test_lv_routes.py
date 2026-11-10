#!/usr/bin/env python3
"""Exercise W v4's real classifier/ratio call sites before the native fitter.

The fragment C0306DB0..DB8 executes both actual BL instructions. Only the
surrounding display-manager selection is omitted; classifier, ratio lookup,
SensorLab veneers and rectangle arithmetic all execute their real ARM bytes.
The 8:5 live-slot pair is an emulator-only fixture, independent of recipe math.
No camera, USB, card or shared build artifacts are used.
"""
import struct
import unittest

from unicorn import UC_HOOK_CODE
from unicorn import arm_const as reg

import test_apply as T
from test_lv_fit import fit_native, continuous_rectangle


W_CLASSIFY, W_RATIO_DONE = 0xC0306DB0, 0xC0306DB8
CLASSIFY, CLASSIFY_END = 0xC02DB140, 0xC02DB1D8
PAIR = (8, 5)
FIT_WORK = T.WORK + 0x3F0000
INPUT = FIT_WORK + 0x100


def prepared(*, active):
    cam = T.Cam()
    if cam.init() != T.AP_OK:
        raise AssertionError('SensorLab apply hooks did not install')
    owned = None
    if active:
        if cam.apply(T.recipe(*T.V1_ARGS)[0]) != T.AP_OK:
            raise AssertionError('SensorLab live slot did not activate')
        owned = cam.call(T.RATIO, 9)
        if not T.MEM <= owned < T.MEM + T.AP_MEM:
            raise AssertionError('H_RATIO did not return a sup-owned pair')
        cam.mu.mem_write(owned, struct.pack('<2I', *PAIR))
    cam.mu.mem_write(INPUT, struct.pack('<2I', *PAIR))
    cam.mu.reg_write(reg.UC_ARM_REG_C1_C0_2, 0xF00000)
    cam.mu.reg_write(reg.UC_ARM_REG_FPEXC, 0x40000000)
    cam.mu.reg_write(reg.UC_ARM_REG_FPSCR, 0)
    return cam, owned


def w_pair(cam):
    """Execute W v4's classifier BL followed by its native ratio getter BL.

    r0 is the W parameter's input pair (param1 + 0x14 in the full v4 method).
    Every visited ROM address is bounded to these two callees or the two BLs;
    product code is bounded to its image, owned veneers and allocated cave.
    """
    mu = cam.mu
    entered = []
    callee_saved = {getattr(reg, f'UC_ARM_REG_R{n}'): 0x55550000 + n
                    for n in range(4, 12)}
    initial_sp = T.STACK - 0x1000
    before = bytes(mu.mem_read(INPUT, 8))
    ranges = ((W_CLASSIFY, W_RATIO_DONE), (CLASSIFY, CLASSIFY_END),
              (T.RATIO, 0xC02DAFFC),
              (T.BLOB, T.BLOB + len(cam.img)),
              (T.MEM, T.MEM + (len(cam.claims) - 1) * 88),
              (T.CAVE_ARENA, cam.w(T.CAVE_BUMP)))

    def guard(uc, address, size, _data):
        if address == CLASSIFY:
            entered.append(uc.reg_read(reg.UC_ARM_REG_R0))
        if not any(lo <= address and address + size <= hi for lo, hi in ranges):
            raise AssertionError(f'unapproved W v4 fragment execution at {address:#x}')

    handle = mu.hook_add(UC_HOOK_CODE, guard)
    try:
        # Earlier init/oracle calls may have translated these blocks before
        # this strict observer existed. Re-translate with the observer active.
        for lo, hi in ranges:
            mu.ctl_remove_cache(lo, hi)
        for number, value in callee_saved.items():
            mu.reg_write(number, value)
        mu.reg_write(reg.UC_ARM_REG_SP, initial_sp)
        mu.reg_write(reg.UC_ARM_REG_R0, INPUT)
        mu.reg_write(reg.UC_ARM_REG_LR, T.DONE)
        mu.emu_start(W_CLASSIFY, W_RATIO_DONE, count=500000)
    finally:
        mu.hook_del(handle)
    if cam.error:
        raise cam.error
    if mu.reg_read(reg.UC_ARM_REG_PC) != W_RATIO_DONE:
        raise AssertionError('W v4 classifier/ratio fragment did not finish')
    if mu.reg_read(reg.UC_ARM_REG_SP) != initial_sp:
        raise AssertionError('W v4 classifier/ratio fragment damaged SP')
    for number, value in callee_saved.items():
        if mu.reg_read(number) != value:
            raise AssertionError(f'W v4 classifier/ratio damaged register {number}')
    if bytes(mu.mem_read(INPUT, 8)) != before:
        raise AssertionError('W v4 classifier/ratio changed its input pair')
    return mu.reg_read(reg.UC_ARM_REG_R0), entered


def native_pair(cam):
    """Call the original classifier and the real stock enum-to-pair getter."""
    enum = cam.call(CLASSIFY, INPUT)
    return enum, cam.call(T.RATIO, enum)


class Wv4Routes(unittest.TestCase):
    def test_live_route_keeps_the_owned_pair_before_the_complete_fit(self):
        cam, owned = prepared(active=True)
        ptr, entered = w_pair(cam)
        self.assertEqual(ptr, owned, 'W v4 must bypass its quantizing classifier for a custom live slot')
        self.assertEqual(entered, [], 'the custom live route must not run the stock classifier')
        self.assertEqual(fit_native(cam.mu, cam.call, ptr, work=FIT_WORK),
                         continuous_rectangle(PAIR))

    def test_fit_hook_alone_cannot_repair_the_w_v4_route(self):
        # Remove only H_ASP3 in emulator memory before this code first executes.
        # H_FIT remains installed: a successful direct fit is insufficient if
        # the W route already replaced the aspect with a stock enum.
        cam, owned = prepared(active=True)
        cam.put(W_CLASSIFY, T.iw(W_CLASSIFY))
        enum, expected = native_pair(cam)
        self.assertNotEqual(enum, 9)
        ptr, entered = w_pair(cam)
        self.assertEqual((ptr, entered), (expected, [INPUT]))
        self.assertNotEqual(ptr, owned)
        self.assertNotEqual(fit_native(cam.mu, cam.call, ptr, work=FIT_WORK),
                            continuous_rectangle(PAIR))

    def test_inactive_route_preserves_the_native_classifier_and_pair(self):
        cam, _owned = prepared(active=False)
        enum, expected = native_pair(cam)
        self.assertNotEqual(enum, 9)
        ptr, entered = w_pair(cam)
        self.assertEqual((ptr, entered), (expected, [INPUT]))

    def test_playback_routes_preserve_the_native_classifier_and_pair(self):
        for field in ('active', 'pbc'):
            with self.subTest(playback=field):
                cam, owned = prepared(active=True)
                pb = cam.fn('ap_pb_info', T.MEM) & 0xFFFFFFFF
                # Existing stable ap_pb word layout, also used by test_apply.
                offset = 8 * 4 if field == 'active' else T.PB_V1_AT + 8
                cam.put(pb + offset, 1)
                enum, expected = native_pair(cam)
                self.assertNotEqual(enum, 9)
                ptr, entered = w_pair(cam)
                self.assertEqual((ptr, entered), (expected, [INPUT]))
                self.assertNotEqual(ptr, owned)


if __name__ == '__main__':
    unittest.main(verbosity=2)
