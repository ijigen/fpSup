"""LExpo as a Loader v3 sup, loaded by the real 加載器.

    cd fpSup/lexpo && python3 -B -m unittest test_v3_lexpo

The real loader.S (as the AutoRun spells it), the real LOADER.BIN and the
built 30LEXPO.BIN run in Unicorn against the reference image; the firmware's
file, directory, allocator, power-off and task routines are Python
(fp_usb_shell/v3/test_v3.Camera).  The controller accessor and the
rebuild/event wrapper the one-shot LV hook calls are stubs; the claim,
journal, layering and arming paths are real.

Emulated, not on the camera.  What this cannot tell: that the widget
actually re-reads the list on the "B1_1_2_Speed" event -- that is the
on-camera test reported in projects/lexpo-sup.md.
"""
import pathlib
import struct
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
V3 = HERE.parent / 'fp_usb_shell' / 'v3'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(V3))
sys.path.insert(0, str(V3.parent))

import test_v3 as T                                       # noqa: E402
import build_v3_lexpo as L                                # noqa: E402

from armasm import symbols                                # noqa: E402
from unicorn.arm_const import (UC_ARM_REG_SP, UC_ARM_REG_LR,   # noqa: E402
                               UC_ARM_REG_R0, UC_ARM_REG_R1)

SITE, STOCK, PATCHED = L.SITE, L.STOCK, L.PATCHED
OTHER_WORD = 0xE309C6F0   # a rival sup's value at the same site (any non-stock)

SITE_LV, STOCK_LV = 0xC02BAD0C, 0xE24DD064     # the one-shot hook's site
F_CTRL, F_WRAP = 0xC049D448, 0xC049D6D0        # accessor + rebuild wrapper
CTRL = 0xC3766ADC                              # the controller singleton
LOWER = 0xC0100000    # a layer below's target: inside branch reach


def branch(site, target):
    return 0xEB000000 | (((target - site - 8) >> 2) & 0xFFFFFF)


class LExpoCamera(T.Camera):
    """test_v3's camera, with the controller accessor and the rebuild/event
    wrapper stubbed: the one-shot hook must call the wrapper exactly once,
    with (controller, mode 1), after the patch word is in."""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.wraps = []
        for at, name in ((F_CTRL, 'CTRL'), (F_WRAP, 'WRAP')):
            self.mu.mem_write(at, struct.pack('<I', 0xE12FFF1E))
            self.by_addr[at] = name

    def _hook(self, mu, addr, size, data):
        name = self.by_addr.get(addr)
        if name == 'CTRL':
            return self._ret(CTRL)
        if name == 'WRAP':
            self.wraps.append((self.r(UC_ARM_REG_R0), self.r(UC_ARM_REG_R1),
                               self.w(SITE)))
            return self._ret(0)
        return super()._hook(mu, addr, size, data)


@unittest.skipIf(T.Uc is None or not T.IMAGE.exists(), 'needs unicorn and the image')
class LExpoV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sup = L.sup_file()
        cls.sym = symbols(HERE.parent / 'lexpo' / 'lexpo_inner.S')

    def boot(self, *inner, stale=None):
        files, dirs = T.card(*inner, ('30LEXPO.BIN', self.sup))
        cam = LExpoCamera(files, dirs, stale=stale)
        r0, sp = cam.boot()
        self.assertEqual(sp, T.STACK - 0x1004)
        self.assertEqual(cam.misaligned, [])
        return cam

    def outcome(self, cam, name='30LEXPO.BIN'):
        return {t: c for c, _, _, t in cam.log() if c in ('LOADED', 'RELEASED')}.get(name)

    def fire_lv(self, cam, until=None):
        """Run the LV applier site: site -> veneer -> hook -> replay -> site+4."""
        mu = cam.mu
        mu.reg_write(UC_ARM_REG_SP, T.STACK - 0x2000)
        mu.reg_write(UC_ARM_REG_LR, T.DONE)
        mu.emu_start(SITE_LV, until or SITE_LV + 4, count=2_000_000)
        self.assertIsNone(cam.error)

    # ---- the patch --------------------------------------------------------
    def test_loads_and_patches_the_word(self):
        cam = self.boot()
        self.assertEqual(self.outcome(cam), 'LOADED')
        self.assertEqual(cam.w(SITE), PATCHED)
        self.assertEqual(cam.journal(), [(SITE, 4, struct.pack('<I', STOCK)),
                                         (SITE_LV, 4, struct.pack('<I', STOCK_LV))])

    def test_power_off_restores_both_words(self):
        cam = self.boot()
        self.fire_lv(cam)
        cam.power_off()
        self.assertEqual(cam.w(SITE), STOCK)
        self.assertEqual(cam.w(SITE_LV), STOCK_LV)

    def test_a_patch_left_by_last_boot_is_repaired_then_reapplied(self):
        """Battery pulled before the power-off write-back: the camera comes up
        with our word still in place, not stock."""
        cam = self.boot(stale={SITE: PATCHED})
        self.assertEqual(self.outcome(cam), 'LOADED')
        repaired = {a for c, a, _, t in cam.log() if c == 'REPAIRED'}
        self.assertEqual(repaired, {SITE})
        self.assertEqual(cam.w(SITE), PATCHED)
        cam.power_off()
        self.assertEqual(cam.w(SITE), STOCK)

    def test_an_exclusive_hold_on_the_site_releases_us(self):
        o = T.test_sup('OTHR', [(SITE, STOCK, 2, OTHER_WORD)])
        cam = self.boot(('05OTHER.BIN', o))
        self.assertEqual(self.outcome(cam, '05OTHER.BIN'), 'LOADED')
        self.assertEqual(self.outcome(cam), 'RELEASED')
        self.assertEqual(cam.w(SITE), OTHER_WORD)          # theirs, untouched
        self.assertEqual(cam.w(SITE_LV), STOCK_LV)         # hook never armed
        self.assertEqual(cam.wraps, [])

    def test_a_foreign_word_at_the_site_is_repaired_and_taken(self):
        """A word that is not stock and not this boot's: by design the loader
        treats it as a patch a missed power-off left behind (only sups patch,
        every patch is claimed and journaled) -- repaired to stock, then ours."""
        cam = self.boot(stale={SITE: OTHER_WORD})
        self.assertEqual(self.outcome(cam), 'LOADED')
        repaired = {a for c, a, _, t in cam.log() if c == 'REPAIRED'}
        self.assertEqual(repaired, {SITE})
        self.assertEqual(cam.w(SITE), PATCHED)
        cam.power_off()
        self.assertEqual(cam.w(SITE), STOCK)

    # ---- the one-shot LV hook ----------------------------------------------
    def test_first_lv_frame_calls_the_wrapper_once_after_the_patch(self):
        cam = self.boot()
        self.fire_lv(cam)
        self.assertEqual(cam.wraps, [(CTRL, 1, PATCHED)])
        self.fire_lv(cam)
        self.assertEqual(cam.wraps, [(CTRL, 1, PATCHED)])    # one-shot

    def test_hook_replays_the_displaced_instruction(self):
        """The applier's frame must still shrink by 0x64: after the hook
        returns to site+4 the SP is entry-SP minus 0x64."""
        cam = self.boot()
        mu = cam.mu
        mu.reg_write(UC_ARM_REG_SP, T.STACK - 0x2000)
        mu.reg_write(UC_ARM_REG_LR, T.DONE)
        mu.emu_start(SITE_LV, SITE_LV + 4, count=2_000_000)
        self.assertIsNone(cam.error)
        self.assertEqual(mu.reg_read(UC_ARM_REG_SP), T.STACK - 0x2000 - 0x64)

    def test_a_layer_below_runs_after_ours(self):
        """HpZoom chains the same site: with a layer below, our replay jumps
        to it instead of replaying stock."""
        o = T.test_sup('OTHR', [(SITE_LV, STOCK_LV, 1, branch(SITE_LV, LOWER))])
        cam = self.boot(('05OTHER.BIN', o))
        self.assertEqual(self.outcome(cam), 'LOADED')
        self.fire_lv(cam, until=LOWER)                       # reached the layer
        self.assertEqual(len(cam.wraps), 1)                  # ours ran first


if __name__ == '__main__':
    unittest.main()
