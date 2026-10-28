#!/usr/bin/env python3
"""Offline checks for the shipped PreCap sup (loader v4, projects/precapture/precap.S).

    python3 -B -m unittest test_precap_sup -v

Reuses the P4 harness: the same firmware image, the same four sites, the same
faked camera state.  What is new is the *entry*: it claims through the service
table, builds four veneers from svc->cave_alloc, writes the four sites, and
installs the fpSup-page row.  So the entry is driven with a fake sl_svc, and the
hooks are then driven exactly as in the P4 tests.

Covered:
  - the entry claims all four sites with the stock words, EXCL;
  - it asks for 32 cave bytes and builds `ldr pc, [pc, #-4]` + stub veneers;
  - each site becomes `bl veneer` resolving to the matching stub;
  - a refused claim writes nothing and returns SL_RELEASE;
  - the row is registered with a TOGGLE, ON, and set() drives P_ON;
  - with the row OFF, S1 does not start pre-capture;
  - the state block is zeroed before the entry runs (the loader does that).
"""
import pathlib
import struct
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_precap_sup as B  # noqa: E402
import test_precap_p4 as P4  # noqa: E402

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE  # noqa: E402
from unicorn import arm_const as REG  # noqa: E402

SL_OK, SL_KEEP, SL_RELEASE = 0, 0, 1
SL_EXCL = 2
SL_ROW_TOGGLE = 2

STAGING, STACK, STOP = 0x42000000, 0x10000000, 0x10100000
BLOCK, CAVE, SVC, ROW = 0x43000000, 0xC0720000, 0x44000000, 0x44100000
SVC_FN = 0x47000000           # the fake service routines (ARM: mov pc, lr)
SVC_VERSION, SVC_CLAIM, SVC_CAVE, SVC_PUBLISH, SVC_PAGE_ADD = 0x00, 0x08, 0x14, 0x18, 0x40

SITE_A, SITE_B, SITE_D, SITE_S = (0xC038F0E8, 0xC038F174, 0xC02DC108, 0xC03817D4)
STOCK = {SITE_A: B.SITES['A'][1], SITE_B: B.SITES['B'][1],
         SITE_D: B.SITES['D'][1], SITE_S: B.SITES['S'][1]}


def u32(uc, address):
    return struct.unpack('<I', uc.mem_read(address, 4))[0]


def bl_target(site, word):
    offset = word & 0x00FFFFFF
    if offset & 0x00800000:
        offset -= 1 << 24
    return site + 8 + offset * 4


class Harness:
    """The entry plus the four hooks, on the real firmware image."""

    def __init__(self, refuse=None, svc_version=7, no_page_add=False):
        self.sup, self.info = B.build()
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        rom = B.ROM.read_bytes()
        self.uc.mem_map(0xC0000000, 0x04000000)
        self.uc.mem_write(0xC0000000, rom[:0x04000000])
        for address, size in ((STAGING, 0x10000), (STACK, 0x10000), (STOP, 0x1000),
                              (BLOCK, 0x10000), (SVC, 0x1000),
                              (ROW, 0x1000), (SVC_FN, 0x1000),
                              (P4.JOBS, 0x40000), (P4.HEAP, 0x10000)):
            self.uc.mem_map(address, size)
        # the block: the header, the code, then zeros (as the loader gives it)
        self.uc.mem_write(BLOCK, self.sup)
        # the four sites hold their stock words
        for site, word in STOCK.items():
            self.uc.mem_write(site, struct.pack('<I', word))
        self.refuse = refuse
        self.claims, self.cave_calls, self.publishes, self.pages = [], [], [], []
        self.rows = []
        self.cave_next = CAVE
        self._build_svc(svc_version, no_page_add)
        self.tick, self.tick_step, self.kind = 1000, 200_000, 9   # one frame per 167 ms slot
        fake = ((0xC001D740, self._h_get), (0xC001D7F0, self._h_addr),
                (0xC000E91C, lambda: None), (0xC000EABC, lambda: None),
                (0xC002B6E0, self._h_tick), (0xC0397B30, lambda: self.kind),
                (0xC02DBAF0, lambda: 0xC3425684), (0xC02DBBE8, lambda: None),
                (0xC02DC138, lambda: None))
        for address, handler in fake:
            self.uc.hook_add(UC_HOOK_CODE, self._make(address, handler),
                             begin=address, end=address)
        self.writes = []
        for site in STOCK:
            self.uc.hook_add(UC_HOOK_MEM_WRITE, self._write, begin=site, end=site + 3)

    # --- the fake service table -------------------------------------------
    def _build_svc(self, version, no_page_add):
        for off in range(0, 0x68, 4):
            self.uc.mem_write(SVC + off, struct.pack('<I', 0))
        self.uc.mem_write(SVC + SVC_VERSION, struct.pack('<I', version))
        for index, (offset, handler) in enumerate(
                ((SVC_CLAIM, self._claim), (SVC_CAVE, self._cave), (SVC_PUBLISH, self._publish))):
            at = SVC_FN + index * 4
            self.uc.mem_write(at, struct.pack('<I', 0xE1A0F00E))   # mov pc, lr
            self.uc.mem_write(SVC + offset, struct.pack('<I', at))
            self.uc.hook_add(UC_HOOK_CODE, self._make(at, handler), begin=at, end=at)
        if not no_page_add:
            at = SVC_FN + 0x0c
            self.uc.mem_write(at, struct.pack('<I', 0xE1A0F00E))
            self.uc.mem_write(SVC + SVC_PAGE_ADD, struct.pack('<I', at))
            self.uc.hook_add(UC_HOOK_CODE, self._make(at, self._page_add), begin=at, end=at)

    def _make(self, address, handler):
        def hook(uc, _addr, _size, _user):
            result = handler()
            uc.reg_write(REG.UC_ARM_REG_R0, 0 if result is None else result)
            uc.reg_write(REG.UC_ARM_REG_PC, uc.reg_read(REG.UC_ARM_REG_LR))
        return hook

    def _claim(self):
        uc = self.uc
        svc, addr, length = (uc.reg_read(getattr(REG, f'UC_ARM_REG_R{i}')) for i in range(3))
        stock_ptr = uc.reg_read(REG.UC_ARM_REG_R3)
        kind = u32(uc, uc.reg_read(REG.UC_ARM_REG_SP))
        stock = struct.unpack('<I', uc.mem_read(stock_ptr, 4))[0]
        self.claims.append((svc, addr, length, stock, kind))
        if self.refuse is not None and addr == self.refuse:
            return -1
        return SL_OK

    def _cave(self):
        uc = self.uc
        want = uc.reg_read(REG.UC_ARM_REG_R1) & 0xFFFFFFFF
        self.cave_calls.append(want)
        out = self.cave_next
        self.cave_next += want + 8
        return out

    def _publish(self):
        self.publishes.append(1)

    def _page_add(self):
        uc = self.uc
        row_ptr = uc.reg_read(REG.UC_ARM_REG_R1)
        self.pages.append(row_ptr)
        kind = struct.unpack('<H', uc.mem_read(row_ptr, 2))[0]
        n = struct.unpack('<H', uc.mem_read(row_ptr + 2, 2))[0]
        title = u32(uc, row_ptr + 4)
        get = u32(uc, row_ptr + 12)
        set_ = u32(uc, row_ptr + 16)
        choices = u32(uc, row_ptr + 20)
        self.rows.append(dict(kind=kind, n=n, title=title, get=get, set=set_, choices=choices))
        return 0

    def _write(self, _uc, _access, address, size, value, _user):
        self.writes.append((address, size, value))

    def _h_get(self):
        size = self.uc.reg_read(REG.UC_ARM_REG_R0)
        self.uc.mem_write(self.uc.reg_read(REG.UC_ARM_REG_SP), struct.pack('<I', P4.HEAP))
        return P4.HEAP

    def _h_addr(self):
        return u32(self.uc, self.uc.reg_read(REG.UC_ARM_REG_R0))

    def _h_tick(self):
        self.tick += self.tick_step
        return self.tick & 0xFFFFFFFF

    # --- driving ----------------------------------------------------------
    def run_entry(self):
        self.uc.reg_write(REG.UC_ARM_REG_R0, BLOCK)
        self.uc.reg_write(REG.UC_ARM_REG_R1, SVC)
        self.uc.reg_write(REG.UC_ARM_REG_R2, 0)
        self.uc.reg_write(REG.UC_ARM_REG_SP, STACK + 0x8000)
        self.uc.reg_write(REG.UC_ARM_REG_LR, STOP)
        self.uc.emu_start(BLOCK + self.info['entry'], STOP, count=500_000)
        return self.uc.reg_read(REG.UC_ARM_REG_R0)

    def field(self, offset):
        return u32(self.uc, BLOCK + self.info['state'] + offset)

    def set_field(self, offset, value):
        self.uc.mem_write(BLOCK + offset, struct.pack('<I', value))

    def call_row_set(self, on):
        """Drive the row's set() through the service table's callback."""
        cb = self.rows[0]['set']
        if not cb:
            raise AssertionError('the row has no set()')
        arg = u32(self.uc, self.pages[0] + 28)
        self.uc.reg_write(REG.UC_ARM_REG_R0, arg)
        self.uc.reg_write(REG.UC_ARM_REG_R1, 1 if on else 0)
        self.uc.reg_write(REG.UC_ARM_REG_LR, STOP)
        self.uc.emu_start(cb, STOP, count=20_000)
        return self.uc.reg_read(REG.UC_ARM_REG_R0)

    def call_row_get(self):
        cb = self.rows[0]['get']
        arg = u32(self.uc, self.pages[0] + 28)
        self.uc.reg_write(REG.UC_ARM_REG_R0, arg)
        self.uc.reg_write(REG.UC_ARM_REG_LR, STOP)
        self.uc.emu_start(cb, STOP, count=20_000)
        return self.uc.reg_read(REG.UC_ARM_REG_R0)


class Entry(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.ret = self.h.run_entry()

    def test_returns_keep(self):
        self.assertEqual(self.ret, SL_KEEP,
                         'SL_KEEP, not SL_RELEASE: the fpSup page points into the block')

    def test_claims_the_four_sites_excl_with_stock_words(self):
        got = {(addr, length, stock, kind) for _, addr, length, stock, kind in self.h.claims}
        self.assertEqual(got, {(site, 4, word, SL_EXCL) for site, word in STOCK.items()})

    def test_asks_for_four_eight_byte_veneers(self):
        self.assertEqual(self.h.cave_calls, [0x20])

    def test_each_site_routes_through_a_veneer_to_its_stub(self):
        stubs = self.h.info['stubs']
        for index, (site, key) in enumerate(((SITE_A, 'A'), (SITE_B, 'B'),
                                             (SITE_D, 'D'), (SITE_S, 'S'))):
            word = u32(self.h.uc, site)
            self.assertEqual(word >> 24, 0xEB, f'{key}: not a bl')
            veneer = bl_target(site, word)
            self.assertEqual(veneer, CAVE + index * 8, f'{key}: wrong veneer')
            self.assertEqual(u32(self.h.uc, veneer), 0xE51FF004, f'{key}: not ldr pc')
            self.assertEqual(u32(self.h.uc, veneer + 4),
                             BLOCK + self.h.info['entry'] + stubs[key],
                             f'{key}: veneer does not reach its stub')

    def test_publishes_once_the_sites_are_armed(self):
        self.assertEqual(len(self.h.publishes), 1)

    def test_the_row_is_a_toggle_that_starts_on(self):
        self.assertEqual(len(self.h.rows), 1)
        row = self.h.rows[0]
        self.assertEqual(row['kind'], SL_ROW_TOGGLE)
        self.assertEqual(row['n'], 2)
        self.assertEqual(bytes(self.h.uc.mem_read(row['title'], 8)), b'PreCap\0\0')
        self.assertEqual(self.h.field(0x9C), 1)      # P_ON, ON at boot

    def test_the_switch_drives_the_state_word(self):
        self.assertEqual(self.h.call_row_get(), 1)
        self.assertEqual(self.h.call_row_set(0), 0)
        self.assertEqual(self.h.field(0x9C), 0)
        self.assertEqual(self.h.call_row_get(), 0)
        self.assertEqual(self.h.call_row_set(1), 0)
        self.assertEqual(self.h.field(0x9C), 1)


class Refusals(unittest.TestCase):
    def test_a_refused_claim_writes_nothing_and_releases(self):
        h = Harness(refuse=SITE_D)
        self.assertEqual(h.run_entry(), SL_RELEASE)
        self.assertEqual(h.writes, [], 'a refused entry must not touch a site')
        self.assertEqual(h.pages, [])

    def test_an_old_service_table_releases(self):
        h = Harness(svc_version=4)
        self.assertEqual(h.run_entry(), SL_RELEASE)
        self.assertEqual(h.writes, [])

    def test_no_page_add_still_takes_the_hooks(self):
        h = Harness(no_page_add=True)
        self.assertEqual(h.run_entry(), SL_KEEP)
        self.assertEqual(h.pages, [])
        for site in STOCK:
            self.assertNotEqual(u32(h.uc, site), STOCK[site])


class Switch(unittest.TestCase):
    P_INJ, P_PRE = 0x5C, 0x50

    def _press_s1(self, h):
        """Drive the key hook at C02DC108 with key code 4 (S1 ON).

        The hook returns to C02DC10C, which is the middle of the firmware's key
        loop -- so stop as soon as the site is re-entered instead of letting the
        stock loop run on.
        """
        h.uc.reg_write(REG.UC_ARM_REG_R0, 0xC3425684)      # KEYMON
        h.uc.reg_write(REG.UC_ARM_REG_R1, 4)               # S1 ON
        h.uc.reg_write(REG.UC_ARM_REG_SP, STACK + 0x6000)
        h.uc.reg_write(REG.UC_ARM_REG_LR, SITE_D + 4)
        h.uc.emu_start(SITE_D, SITE_D + 4, count=80_000)

    def test_off_means_s1_does_nothing(self):
        h = Harness()
        h.run_entry()
        h.call_row_set(0)
        before = h.field(self.P_INJ)
        self._press_s1(h)
        self.assertEqual(h.field(self.P_INJ), before,
                         'S1 with the switch OFF must not inject S2')
        self.assertEqual(h.field(self.P_PRE), 0, 'pre-capture must stay down')


class Behaviour(unittest.TestCase):
    """The hooks, driven through the sup's own veneers, on the P4 assertions."""

    P = dict(pre=0x50, t0=0x54, tmo=0x58, inj=0x5C, s1c=0x60, tmof=0x64,
             gate=0x6C, held=0x70, dropped=0x74, evicted=0x78, committed=0x7C,
             abandoned=0x80, head=0x8C, n=0x90, muted=0x94, played=0x98,
             on=0x9C, keep=0x00)

    def setUp(self):
        self.h = Harness()
        self.h.run_entry()
        self.uc = self.h.uc
        j = self.uc
        for job_id in range(32):
            addr = P4.job_addr(job_id)
            j.mem_write(P4.JOBDB + 4 + job_id * 4, struct.pack('<I', addr))
            j.mem_write(addr + 0xFFC, struct.pack('<I', 0x1000 + job_id))
            j.mem_write(addr + 0x10FC, struct.pack('<I', job_id))
        for address in (P4.F_JOBDB, P4.F_JOBGET, P4.F_CAP, P4.F_REFUND,
                        P4.F_RAWOBJ, P4.F_DROPRW, P4.F_DROPJB, P4.F_ENQUEUE,
                        P4.F_SOUND):
            self.uc.hook_add(UC_HOOK_CODE, self._make4(address),
                             begin=address, end=address)
        self.refunds, self.raw_drops, self.job_drops, self.enqueued = [], [], [], []
        self.sounds = []
        for address in (P4.F_ENQUEUE,):
            self.uc.hook_add(UC_HOOK_CODE, self._make4(address), begin=address, end=address)

    def _ret(self, value):
        self._pending = value
        return value

    def _make4(self, address):
        def hook(uc, _addr, _size, _user):
            self._pending = None
            handler = {
                P4.F_JOBDB: lambda: self._ret(P4.JOBDB),
                P4.F_JOBGET: lambda: self._ret(
                    P4.job_addr(uc.reg_read(REG.UC_ARM_REG_R1))
                    if uc.reg_read(REG.UC_ARM_REG_R1) < 32 else 0),
                P4.F_CAP: lambda: self._ret(P4.CAP),
                P4.F_REFUND: lambda: self.refunds.append(1) and None,
                P4.F_RAWOBJ: lambda: self._ret(P4.RAWOBJ),
                P4.F_DROPRW: lambda: self._ret(self.raw_drops.append(1) or 1),
                P4.F_DROPJB: lambda: self._ret(
                    self.job_drops.append(uc.reg_read(REG.UC_ARM_REG_R1)) or 1),
                P4.F_ENQUEUE: lambda: self._ret(
                    self.enqueued.append((uc.reg_read(REG.UC_ARM_REG_R0),
                                          uc.reg_read(REG.UC_ARM_REG_R1))) or 1),
                P4.F_SOUND: lambda: self.sounds.append(1) and None,
            }[address]()
            if self._pending is not None:
                uc.reg_write(REG.UC_ARM_REG_R0, self._pending & 0xFFFFFFFF)
            uc.reg_write(REG.UC_ARM_REG_PC, uc.reg_read(REG.UC_ARM_REG_LR))
        return hook

    def press(self, code):
        h, uc = self.h, self.uc
        uc.reg_write(REG.UC_ARM_REG_R0, 0xC3425684)
        uc.reg_write(REG.UC_ARM_REG_R1, code)
        uc.reg_write(REG.UC_ARM_REG_SP, STACK + 0x6000)
        uc.reg_write(REG.UC_ARM_REG_LR, SITE_D + 4)
        uc.emu_start(SITE_D, SITE_D + 4, count=80_000)

    def frame(self, site=SITE_B, job=1):
        """Enter the site as the HIGHCONT task does.

        The stock site tail-calls the original enqueue through r3, so "did the
        frame reach YUV" is "did r3 run", which the sentinel STOP marks.
        """
        uc = self.uc
        uc.reg_write(REG.UC_ARM_REG_R0, P4.YUV)
        uc.reg_write(REG.UC_ARM_REG_R1, job)
        uc.reg_write(REG.UC_ARM_REG_R2, 1)
        uc.reg_write(REG.UC_ARM_REG_R3, STOP)
        uc.reg_write(REG.UC_ARM_REG_SP, STACK + 0x4000)
        uc.reg_write(REG.UC_ARM_REG_LR, site + 4)
        # A held frame returns to site+4 (the stock site's next instruction); a
        # released one tail-calls the original enqueue through r3 (= STOP).
        uc.emu_start(site, site + 4, count=80_000)
        return uc.reg_read(REG.UC_ARM_REG_PC) == STOP

    def sound(self):
        uc = self.uc
        before = len(self.sounds)
        uc.reg_write(REG.UC_ARM_REG_R0, P4.SREC)
        uc.reg_write(REG.UC_ARM_REG_R1, 1000)
        uc.reg_write(REG.UC_ARM_REG_SP, STACK + 0x2000)
        uc.reg_write(REG.UC_ARM_REG_LR, SITE_S + 4)
        uc.emu_start(SITE_S, SITE_S + 4, count=20_000)
        return len(self.sounds) > before

    def test_s1_takes_four_frames_and_s2_commits_them(self):
        self.press(4)                                # S1 ON
        self.assertEqual(self.h.field(self.P['inj']), 1)
        self.assertEqual(self.h.field(self.P['pre']), 1)
        for _ in range(4):
            self.assertFalse(self.frame(), 'a held frame must not reach YUV')
        self.assertEqual(self.h.field(self.P['n']), 4)
        self.press(6)                                # S2 ON
        self.assertEqual(self.h.field(self.P['committed']), 4)
        self.assertEqual(self.h.field(self.P['pre']), 0)
        # enqueue_raw re-enters itself once per call (the second time with the
        # task id in r0), so count how often the frame itself was handed over.
        handed = [yuv for yuv, _job in self.enqueued if yuv == P4.YUV]
        self.assertEqual(len(handed), 4, 'four frames handed to the firmware')

    def test_letting_go_of_s1_drops_the_ring(self):
        self.press(4)
        for _ in range(4):
            self.frame()
        self.press(5)                                # S1 OFF
        self.assertEqual(self.h.field(self.P['committed']), 0)
        self.assertEqual(self.h.field(self.P['abandoned']), 4)
        self.assertEqual(len(self.enqueued), 0, 'nothing reaches the firmware')
        self.assertEqual(self.h.field(self.P['pre']), 0)

    def test_a_single_shot_kind_never_engages(self):
        self.h.kind = 3                              # not the high-speed mode
        self.press(4)
        self.assertEqual(self.h.field(self.P['pre']), 0)
        self.assertEqual(self.h.field(self.P['gate']) & 0x100, 0x100)

    def test_shutter_is_muted_while_pre_capturing(self):
        self.assertTrue(self.sound())
        self.press(4)
        self.assertFalse(self.sound())
        self.press(5)
        self.assertTrue(self.sound())
        self.assertEqual(self.h.field(self.P['muted']), 1)
        self.assertEqual(self.h.field(self.P['played']), 2)

    def test_frames_pass_straight_through_when_idle(self):
        self.assertTrue(self.frame(), 'no pre-capture: the frame must reach YUV')
        self.assertEqual(self.h.field(self.P['held']), 0)


if __name__ == '__main__':
    unittest.main()
