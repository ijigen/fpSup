"""HpZoom as a Loader v3 sup, loaded by the real 加載器.

    cd fpSup/hpzoom && python3 -B -m unittest test_v3_hpzoom

The real loader.S (as the AutoRun spells it), the real LOADER.BIN and the
built 20HPZOOM.BIN run in Unicorn against the reference image; the firmware's
file, directory, allocator, power-off and task routines are Python
(fp_usb_shell/v3/test_v3.Camera).  The hook bodies are exercised by calling
the sites: the poster, the focus-mode getters and the queue push are stubs,
everything the hooks touch is real.

Emulated, not on the camera.  What this cannot tell: timing, and that the
zoom machine's shape (cap_machine -> [+4] -> id) still matches the firmware.
"""
import pathlib
import struct
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
V3 = HERE.parent / 'fp_usb_shell' / 'v3'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(V3))
sys.path.insert(0, str(V3.parent))

import test_v3 as T                                       # noqa: E402
import build_v3 as B                                      # noqa: E402
import build_v3_hpzoom as H                               # noqa: E402

from armasm import symbols                                # noqa: E402
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1,   # noqa: E402
                               UC_ARM_REG_R4, UC_ARM_REG_R5,
                               UC_ARM_REG_SP, UC_ARM_REG_LR)

POSTER, CS, POST, APPLY = H.SITES
VENEER_AT = {POSTER: 0, CS: 8, POST: 16, APPLY: 24}
REPLAY = {POSTER: 'poster_replay', CS: 'cs_replay', POST: 'post_replay',
          APPLY: 'apply_replay'}
NEXT = {POSTER: 'poster_next', CS: 'cs_next', POST: 'post_next',
        APPLY: 'apply_next'}
LOWER = 0xC0100000                  # a layer below's target: inside branch reach

F_POSTER, F_GETCTX, F_GETFM = 0xC02DBBE8, 0xC0057AE8, 0xC0059D18
AUTOMAG_CELL, PIC_STRUCT = 0xC31B3774, 0xC341399C
EVT_S1_DOWN, EVT_S2_DOWN, EVT_S2_UP, EVT_OK = 4, 6, 7, 0x1C

MACHINE, REF = 0xC3001000, 0xC3002000      # a fake zoom machine in mapped camera RAM


def branch(site, target, op=0xEB000000):
    return op | (((target - site - 8) >> 2) & 0xFFFFFF)


def target_of(site, word):
    d = word & 0xFFFFFF
    d -= 0x1000000 if d & 0x800000 else 0
    return site + 8 + 4 * d


class HpZoomCamera(T.Camera):
    """test_v3's camera, with the firmware routines the hooks reach."""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.posted = []
        self.focus_mode = 2                             # MF
        for at, name in ((F_POSTER, 'POSTER'), (F_GETCTX, 'GETCTX'), (F_GETFM, 'GETFM')):
            self.mu.mem_write(at, struct.pack('<I', 0xE12FFF1E))
            self.by_addr[at] = name

    def _hook(self, mu, addr, size, data):
        name = self.by_addr.get(addr)
        if name == 'POSTER':
            self.posted.append((self.r(UC_ARM_REG_R0), self.r(UC_ARM_REG_R1)))
            return self._ret(0)
        if name == 'GETCTX':
            return self._ret(0xC3001000)
        if name == 'GETFM':
            return self._ret(self.focus_mode)
        return super()._hook(mu, addr, size, data)


@unittest.skipIf(T.Uc is None or not T.IMAGE.exists(), 'needs unicorn and the image')
class HpZoomV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sup, cls.sym = H.sup_file()
        cls.sup_nb, _ = H.sup_file(no_bw=True)
        cls.img = T.IMAGE.read_bytes()

    def boot(self, *inner, sup=None, stale=None):
        files, dirs = T.card(*inner, ('20HPZOOM.BIN', sup or self.sup))
        cam = HpZoomCamera(files, dirs, stale=stale)
        r0, sp = cam.boot()
        self.assertEqual(sp, T.STACK - 0x1004)
        self.assertEqual(cam.misaligned, [])
        return cam

    def outcome(self, cam, name='20HPZOOM.BIN'):
        return {t: c for c, _, _, t in cam.log() if c in ('LOADED', 'RELEASED')}.get(name)

    def block(self, cam):
        return next(a for c, a, _, t in cam.log() if c == 'LOADED' and t == '20HPZOOM.BIN')

    def blob(self, cam):
        return self.block(cam) + B.SL_HEADER_LEN            # hpzoom_sup.S `entry`

    def word(self, cam, label):
        return cam.w(self.blob(cam) + self.sym[label])

    def call_site(self, cam, site, until=None, regs={}):
        mu = cam.mu
        for reg, v in regs.items():
            mu.reg_write(reg, v)
        mu.reg_write(UC_ARM_REG_SP, T.STACK - 0x2000)
        mu.reg_write(UC_ARM_REG_LR, T.DONE)
        mu.emu_start(site, until or site + 4, count=2_000_000)
        self.assertIsNone(cam.error)

    def stock(self, a):
        return T.word(self.img, a)

    def other(self, sid, *rows):
        """A sup loaded before hpzoom: rows (address, kind, new word or 0)."""
        return T.test_sup(sid, [(a, self.stock(a), k, new) for a, k, new in rows])

    # ---- loaded ---------------------------------------------------------
    def test_loads_claims_all_four_sites_chain_then_arms(self):
        cam = self.boot()
        self.assertEqual(self.outcome(cam), 'LOADED')
        self.assertEqual(sorted(a for a, n, _ in cam.journal()), sorted(H.SITES))
        for a, n, data in cam.journal():
            self.assertEqual((n, data), (4, struct.pack('<I', H.SITES[a])), hex(a))
        st = cam.state()
        claims = [struct.unpack('<IIBBBB', cam.mu.mem_read(st + T.O_CLAIMS + 12 * i, 12))
                  for i in range(cam.w(st + T.O_NCLAIMS))]
        kinds = {a: k for a, n, k, _, res, _ in claims if not res}
        self.assertEqual(kinds, {a: 1 for a in H.SITES})            # all CHAIN
        cave = cam.w(T.cave.CAVE_BUMP) - 32                          # CAVE_BYTES
        self.assertEqual(cave, (T.cave.CAVE_ARENA + 7) & ~7)         # 8-aligned
        blob = self.blob(cam)
        for site, off in VENEER_AT.items():
            word = cam.w(site)
            self.assertEqual(word & 0xFF000000, 0xEB000000, hex(site))   # bl
            self.assertEqual(target_of(site, word), cave + off, hex(site))
            self.assertEqual(cam.w(cave + off), 0xE51FF004)
            body = cam.w(cave + off + 4)
            self.assertTrue(blob <= body < blob + len(self.sup) - B.SL_HEADER_LEN,
                            f'{site:#x} body {body:#x}')

    def test_power_off_puts_every_site_back(self):
        cam = self.boot()
        cam.power_off()
        for a, stock in H.SITES.items():
            self.assertEqual(cam.w(a), stock, hex(a))

    def test_a_patch_left_by_last_boot_is_repaired_then_armed(self):
        stale = {POSTER: 0xEB0DEAD0, APPLY: 0xEB0DEAD0}
        cam = self.boot(stale=stale)
        self.assertEqual(self.outcome(cam), 'LOADED')
        repaired = {a for c, a, _, t in cam.log() if c == 'REPAIRED'}
        self.assertEqual(repaired, set(stale))
        cam.power_off()
        for a in stale:
            self.assertEqual(cam.w(a), H.SITES[a])

    def test_the_no_bw_build_claims_three_sites_and_skips_the_applier(self):
        files, dirs = T.card(('20HPZOMNB.BIN', self.sup_nb))
        cam = HpZoomCamera(files, dirs)
        cam.boot()
        self.assertEqual({t: c for c, _, _, t in cam.log()
                          if c in ('LOADED', 'RELEASED')}, {'20HPZOMNB.BIN': 'LOADED'})
        self.assertEqual(sorted(a for a, n, _ in cam.journal()),
                         sorted([POSTER, CS, POST]))
        self.assertEqual(cam.w(APPLY), H.SITES[APPLY])              # left stock

    # ---- released: nothing written ---------------------------------------
    def test_an_exclusive_hold_on_a_site_releases(self):
        o = self.other('OTHR', (POST, 2, 0))
        cam = self.boot(('05OTHER.BIN', o))
        self.assertEqual(self.outcome(cam), 'RELEASED')
        self.assertEqual(cam.w(T.cave.CAVE_BUMP), T.cave.CAVE_ARENA, 'cave taken')
        for a, stock in H.SITES.items():
            if a != POST:
                self.assertEqual(cam.w(a), stock, f'{a:#x} written')

    def test_a_full_cave_releases(self):
        import armasm
        n = T.cave.CAVE_ARENA_END - T.cave.CAVE_ARENA - 16
        src = pathlib.Path(tempfile.mkdtemp(prefix='hog-')) / 'hog.S'
        src.write_text(f'''.syntax unified
.arm
.text
entry:
    push {{r4, lr}}
    mov r0, r1
    movw r1, #:lower16:{n}
    movt r1, #:upper16:{n}
    ldr ip, [r0, #20]
    blx ip
    mov r0, #0
    pop {{r4, pc}}
''')
        hog = B.make_sup(armasm.assemble(src), B.SL_HEADER_LEN, 'HOGG')
        cam = self.boot(('05HOG.BIN', hog))
        self.assertEqual(self.outcome(cam, '05HOG.BIN'), 'LOADED')
        self.assertEqual(self.outcome(cam), 'RELEASED')
        for a, stock in H.SITES.items():
            self.assertEqual(cam.w(a), stock, hex(a))

    # ---- the layers below -------------------------------------------------
    def test_insertion_sites_end_in_the_layer_below(self):
        for site in REPLAY:
            with self.subTest(site=hex(site)):
                o = self.other('OTHR', (site, 1, branch(site, LOWER)))
                cam = self.boot(('05OTHER.BIN', o))
                self.assertEqual(self.outcome(cam), 'LOADED')
                blob = self.blob(cam)
                self.assertEqual(cam.w(blob + self.sym[NEXT[site]]), LOWER)
                at = blob + self.sym[REPLAY[site]]
                self.assertEqual(cam.w(at) & 0xFFFFF000, 0xE59FF000)   # ldr pc, [pc, #]
                self.assertEqual(at + 8 + (cam.w(at) & 0xFFF), blob + self.sym[NEXT[site]])

    def test_stock_insertion_sites_keep_their_replay(self):
        cam = self.boot()
        for site in REPLAY:
            at = B.SL_HEADER_LEN + self.sym[REPLAY[site]]
            want = struct.unpack_from('<I', self.sup, at)[0]
            self.assertEqual(self.word(cam, REPLAY[site]), want, hex(site))

    def test_a_layer_below_runs_after_ours(self):
        o = self.other('OTHR', (POSTER, 1, branch(POSTER, LOWER)))
        cam = self.boot(('05OTHER.BIN', o))
        self.call_site(cam, POSTER, until=LOWER, regs={UC_ARM_REG_R0: 0x1111,
                                                       UC_ARM_REG_R1: EVT_S1_DOWN})
        self.assertEqual(self.word(cam, 'pre_zoom'), 0xFFFFFFFF)    # ours ran first

    # ---- the feature ------------------------------------------------------
    def s1_down(self, cam, singleton=0x1111):
        """poster (records pre_zoom), then post (maybe queues OK)."""
        self.call_site(cam, POSTER, regs={UC_ARM_REG_R0: singleton,
                                          UC_ARM_REG_R1: EVT_S1_DOWN})
        self.call_site(cam, POST, regs={UC_ARM_REG_R4: singleton, UC_ARM_REG_R5: EVT_S1_DOWN})

    def test_s1_in_mf_posts_the_magnify_toggle(self):
        cam = self.boot()
        self.s1_down(cam)
        self.assertEqual(cam.posted, [(0x1111, EVT_OK)])

    def test_s1_in_af_posts_nothing(self):
        cam = self.boot()
        cam.focus_mode = 0                                        # an AF mode
        self.s1_down(cam)
        self.assertEqual(cam.posted, [])

    def test_s1_with_auto_magnify_on_posts_nothing(self):
        cam = self.boot()
        cam.put(AUTOMAG_CELL, 1)
        self.s1_down(cam)
        self.assertEqual(cam.posted, [])

    def test_s1_while_already_magnified_posts_nothing(self):
        """pre_zoom == MfZoom: the stock S1-cancels-magnify does the work."""
        cam = self.boot()
        cam.put(MACHINE + 4, REF)
        cam.put(REF, 4)
        self.call_site(cam, CS, regs={UC_ARM_REG_R0: MACHINE})
        self.assertEqual(self.word(cam, 'cap_machine'), MACHINE)
        self.s1_down(cam)
        self.assertEqual(cam.posted, [])
        self.assertEqual(self.word(cam, 'pre_zoom'), 4)

    # ---- B&W while magnified ----------------------------------------------
    def magnify(self, cam):
        cam.put(MACHINE + 4, REF)
        cam.put(REF, 4)
        self.call_site(cam, CS, regs={UC_ARM_REG_R0: MACHINE})

    def gray_seen(self, cam):
        return (cam.w(PIC_STRUCT + 0x40), cam.w(PIC_STRUCT + 0x1e0),
                cam.mu.mem_read(PIC_STRUCT + 0xb0, 1)[0],
                cam.mu.mem_read(PIC_STRUCT + 0x104, 1)[0])

    def test_applier_grays_both_live_records_while_magnified(self):
        cam = self.boot()
        self.magnify(cam)
        self.call_site(cam, APPLY)
        self.assertEqual(self.gray_seen(cam), (1, 1, 0, 1))

    def test_applier_writes_nothing_when_not_magnified_and_clears_the_inhibit(self):
        cam = self.boot()
        cam.put(MACHINE + 4, REF)
        cam.put(REF, 1)                                            # Normal
        self.call_site(cam, CS, regs={UC_ARM_REG_R0: MACHINE})
        blob = self.blob(cam)
        cam.put(blob + self.sym['bw_state'], 2)
        self.call_site(cam, APPLY)
        self.assertEqual(self.gray_seen(cam), (0, 0, 0, 0))        # untouched
        self.assertEqual(cam.w(blob + self.sym['bw_state']), 0)    # re-armed

    def test_s2_down_colours_the_records_and_inhibits_the_assert(self):
        cam = self.boot()
        self.magnify(cam)
        blob = self.blob(cam)
        cam.put(PIC_STRUCT + 0x40, 1)                              # gray standing
        self.call_site(cam, POSTER, regs={UC_ARM_REG_R0: 0x1111, UC_ARM_REG_R1: EVT_S2_DOWN})
        self.assertEqual(cam.w(blob + self.sym['bw_state']), 2)
        self.assertEqual(cam.w(PIC_STRUCT + 0x40), 0)              # colour pattern
        self.assertEqual(cam.mu.mem_read(PIC_STRUCT + 0x12c, 1)[0], 1)
        self.call_site(cam, APPLY)                                 # inhibited
        self.assertEqual(cam.w(PIC_STRUCT + 0x40), 0)
        self.call_site(cam, POSTER, regs={UC_ARM_REG_R0: 0x1111, UC_ARM_REG_R1: EVT_S2_UP})
        self.assertEqual(cam.w(blob + self.sym['bw_state']), 0)    # re-armed


if __name__ == '__main__':
    unittest.main()
