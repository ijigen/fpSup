#!/usr/bin/env python3
"""The QS probe's three stages on the real ARM bytes, offline.

The real v4 core (LOADER.BIN, built with the fpSup page) loads the real probe
BIN through the real AutoRun loader against the real firmware image
(out/MAIN_c0000000.bin); the UI app is the maintained fake (uishare/tab/
test_ft6.py: reader, variable posts).  Converter lookups run the firmware's own
FUN_c06c7bc0 / FUN_c06c7b28 / FUN_c06d0fa0 / FUN_c06ce6f0 and the stock
vtable functions; the save runs the firmware's FUN_c0088660 from its call site.

Python models (declared, not the firmware): the settings object getters
C0057AE8 / C0058340 (CINE or not), the slot read FUN_c0061b08 (it reads the
working image's set the CINE flag picks), the guard pair C0013090 / C00131E4,
memcpy C0014DAC and the checksum C00228D0, the file API (test_v3), F_SEEK.

    cd projects/sensorlab-imx410/qsprobe && python3 -B -m unittest test_qsprobe
    python3 -B test_qsprobe.py --mutate        # every mutant must fail a test
"""
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / 'fpSup/loader-v4')]
import build_qsprobe as Q                   # noqa: E402
import test_ui_v4 as U                      # noqa: E402

T = U.T                                     # test_v4
T3 = T.T3                                   # test_v3
F6 = U.F6
IMG = T3.IMAGE.read_bytes() if T3.IMAGE.exists() else b''

CONV, CONV_VT, VT_STOCK, GUARD = 0xC37B7724, 0xC37B7728, 0xC2DEAD7C, 0xC37B772C
UI_TO_INT, INT_TO_UI = 0xC06C7BC0, 0xC06C7B28
SAVE_SITE, SAVE_STOCK, REC_SITE, REC_STOCK = 0xC0088C60, 0xEBFFFE7E, 0xC053DBF8, 0xEBEC8FC2
STORE, IMG_A, IMG_B, SEL = 0xC31AE3B0, 0xC, 0x58D4, 0xB19C
ARR = (0x23E8, 0x2700)
F_SEEK, MEMCPY, CSUM, ASSERT = 0xC03661E0, 0xC0014DAC, 0xC00228D0, 0xC0011100
GUARD_ACQ, GUARD_REL, SETTINGS_GET, IS_CINE, QS_GET = 0xC0013090, 0xC00131E4, 0xC0057AE8, 0xC0058340, 0xC0061B08
SETTINGS = F6.FAKE + 0xA000
USERSET = F6.FAKE + 0xA100                 # FUN_c0088660's object: +0x48 -> {header, buffer}
FLASH = 0xC3E00000                         # the buffer FUN_c0088660 copies into (what the flush writes)
NAMES = ['MV_QSMENU_QS%d' % k for k in range(1, 9)]
STOCK_CINE = [struct.unpack_from('<2I', IMG, 0x2E431A4 + 8 * i) for i in range(51)] if IMG else []

_built = {}


def blob(stage, **kw):
    key = (stage, tuple(sorted(kw.items())))
    if key not in _built:
        _built[key] = Q.build(stage, **kw)
    return _built[key]


if T.Uc is not None:
    _ORIG_HOOK = T.Uc.hook_add

    def rom_hook(mu, kind, cb, *a, **kw):
        # the stubs are firmware addresses: no Python on every sup instruction
        if kind == T.UC_HOOK_CODE and not a and not kw:
            kw = dict(begin=0xC0000000, end=0xC3FFFFFF)
        return _ORIG_HOOK(mu, kind, cb, *a, **kw)


class Cam(U.Cam):
    PAGE_ENTRIES = F6.FAKE + 0xC000

    def __init__(self, files, dirs, cine=True):
        with patch.object(T.Uc, 'hook_add', rom_hook):
            super().__init__(files, dirs)
        self.cine = cine
        self.created, self.asserts, self.copies = [], [], []
        for a, n in ((GUARD_ACQ, 'G_ACQ'), (GUARD_REL, 'G_REL'), (SETTINGS_GET, 'SET_GET'),
                     (IS_CINE, 'IS_CINE'), (QS_GET, 'QS_GET'), (F_SEEK, 'F_SEEK'), (MEMCPY, 'MEMCPY'),
                     (CSUM, 'CSUM'), (ASSERT, 'ASSERT')):
            self.by_addr[a] = n
        at, names = self.PAGE_ENTRIES, self.PAGE_ENTRIES + 44 * len(Q.PAGES)
        for i, page in enumerate(Q.PAGES):
            _a, off, _n = Q.O.resource_set(page)
            e = at + 44 * i
            self.mu.mem_write(e, bytes(44))
            self.mu.mem_write(names + 32 * i, page.encode() + b'\0')
            self.put(e + 4, names + 32 * i)
            self.put(e + 8, off)
        self.put(F6.READER + 0xA8, len(Q.PAGES))
        self.put(F6.READER + 0xAC, at)

    def _hook(self, mu, addr, size, data):
        name = self.by_addr.get(addr)
        r = [self.r(getattr(T3, 'UC_ARM_REG_R%d' % i)) for i in range(4)]
        if name == 'G_ACQ':
            return self._ret(0 if self.w(r[0]) & 1 else 1)
        if name == 'G_REL':
            self.put(r[0], 1)
            return self._ret(0)
        if name == 'SET_GET':
            return self._ret(SETTINGS)
        if name == 'IS_CINE':
            return self._ret(1 if self.cine else 0)
        if name == 'QS_GET':                         # model: the working image's CINE / STILL set
            assert r[0] == SETTINGS and r[1] < 8
            return self._ret(self.slot(1 if self.cine else 0, r[1]))
        if name == 'F_SEEK':
            self.fobj[r[0]][1] = r[1]
            return self._ret(1)
        if name == 'MEMCPY':
            self.copies.append((r[0], r[1], r[2]))
            mu.mem_write(r[0], bytes(mu.mem_read(r[1], r[2])))
            return self._ret(r[0])
        if name == 'CSUM':
            return self._ret(0x5A5A5A5A)
        if name == 'ASSERT':
            self.asserts.append(self.cstr(r[0]))
            raise AssertionError('firmware assert ' + self.asserts[-1])
        if name == 'F_OPEN' and r[2] == 7:          # overwrite in place, create if missing
            path = self.cstr(r[1])
            self.opened.append(path)
            if path not in self.written:
                if path not in self.files:
                    self.created.append(path)
                self.written[path] = self.files.get(path, b'')
            self.fobj[r[0]] = [path, 0]
            return self._ret(1)
        if name == 'F_READ' and self.fobj.get(r[0]) and self.fobj[r[0]][0] in self.written:
            path, pos = self.fobj[r[0]]
            got = self.written[path][pos:pos + r[2]]
            mu.mem_write(r[1], got)
            self.fobj[r[0]][1] += len(got)
            if r[3]:
                self.put(r[3], len(got))
            return self._ret(len(got))
        return super()._hook(mu, addr, size, data)

    # --- the settings image ---------------------------------------------------
    def image(self):
        return STORE + (IMG_B if self.mu.mem_read(STORE + SEL, 1)[0] else IMG_A)

    def slot(self, a, k):
        return self.w(self.image() + ARR[a] + 4 * k)

    def set_slot(self, a, k, v):
        self.put(self.image() + ARR[a] + 4 * k, v)

    # --- running firmware ------------------------------------------------------
    def run(self, pc, until, **regs):
        from unicorn import arm_const
        from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR
        self.mu.reg_write(UC_ARM_REG_SP, T3.STACK - 0x1000)
        self.mu.reg_write(UC_ARM_REG_LR, T3.DONE)
        for k, v in regs.items():
            self.mu.reg_write(getattr(arm_const, 'UC_ARM_REG_' + k.upper()), v & 0xFFFFFFFF)
        try:
            self.mu.emu_start(pc, until, count=5_000_000)
        finally:
            if self.error:
                raise self.error
        assert self.r(T3.UC_ARM_REG_PC) == until, hex(self.r(T3.UC_ARM_REG_PC))
        return self.r(T3.UC_ARM_REG_R0)

    def conv_built(self):
        return self.call(0xC058C4D0)[0]

    def to_int(self, ui):
        return self.call(UI_TO_INT, r0=CONV, r1=ui)[0]

    def to_ui(self, internal):
        return self.call(INT_TO_UI, r0=CONV, r1=internal)[0]

    def save(self):
        """v2's `bl FUN_c0088660(store, image)`: what lands in the flush buffer."""
        hdr, pair = F6.FAKE + 0xA200, F6.FAKE + 0xA280
        self.mu.mem_write(FLASH, bytes(0x4F00))
        self.put(USERSET + 0x48, pair)
        self.put(pair, hdr)
        self.put(pair + 4, FLASH)
        self.put(hdr + 8, 0xE)
        self.put(hdr + 0x10, 0x4F00)
        self.copies.clear()
        r0 = self.run(SAVE_SITE, SAVE_SITE + 4, r0=USERSET, r1=STORE + IMG_A, r4=STORE)
        assert self.copies == [(FLASH, STORE + IMG_A, 0x4F00)], self.copies
        return r0, bytes(self.mu.mem_read(FLASH, 0x4F00))

    def rec_read(self, k):
        """The RecommendedSetting getter's read of slot k (its call site)."""
        return self.run(REC_SITE, REC_SITE + 4, r0=SETTINGS, r1=k)

    def block_of(self, name):
        return T.blocks(self)[name]

    def st(self, name, stage):
        info = blob(stage)[1]
        return self.block_of(name) + info['state_off']

    def ours_line(self):
        return [t for c, a, b, t in self.loadlog()]


ST = dict(magic=0, stage=4, result=8, csv_result=12, csv_op=16, key_patched=20)
# struct st (qsprobe.c), stage-3 counters: after vt[345] and tab[192]
_S3 = 84 + 4 * (345 + 192)
STF = {n: _S3 + 4 * i for i, n in enumerate(
    ['next_save', 'next_rec', 'veneer', 'saves', 'foreign', 'sanitized', 'rec_hits', 'restored', 'stale',
     'writes', 'write_fails', 'write_why', 'busy_skips'])}


def stword(cam, base, field):
    return cam.w(base + ST[field])


def boot(sups, cine=True, prepare=None, files=None):
    b = U.built()
    vbin = b['vbin']
    fs = {'\\fpSup\\LOADER.BIN': vbin, U.UI_PATH: b['data'], U.SM_PATH: b['smdata']}
    ents = [('LOADER.BIN', 0x20, len(vbin)), ('UI', 0x10, 0)]
    for name, data in sups:
        fs['\\fpSup\\' + name] = data
        ents.append((name, 0x20, len(data)))
    fs.update(files or {})
    cam = Cam(fs, {'\\fpSup': ents}, cine=cine)
    if prepare:
        prepare(cam)
    cam.boot()
    return cam


def name(stage):
    return Q.file_name(stage)


def redirect_table(cam):
    w = cam.w(0xC05E5BEC)
    hw1, hw2 = w & 0xFFFF, w >> 16
    s = (hw1 >> 10) & 1; j1 = (hw2 >> 13) & 1; j2 = (hw2 >> 11) & 1
    off = s << 24 | (1 ^ (j1 ^ s)) << 23 | (1 ^ (j2 ^ s)) << 22 | (hw1 & 0x3FF) << 12 | (hw2 & 0x7FF) << 1
    if s:
        off |= 0xFE000000
    entry = cam.w((0xC05E5BEC + 4 + off + 4) & 0xFFFFFFFF)
    _code, ent, tw = Q.O.handler()
    table = cam.w(entry - ent + tw)
    n = cam.w(table + 8)
    return {cam.w(table + 16 + 12 * i): (cam.w(table + 20 + 12 * i), cam.w(table + 24 + 12 * i)) for i in range(n)}


def cstr(cam, a):
    return bytes(cam.mu.mem_read(a, 64)).split(b'\0')[0].decode()


def page_word(cam, page, image_addr):
    """The BE float at a stock address, in the page copy the reader now points at."""
    a, off, _n = Q.O.resource_set(page)
    k = Q.PAGES.index(page)
    now = 0xC18C0460 + cam.w(Cam.PAGE_ENTRIES + 44 * k + 8)
    return struct.unpack('>f', bytes(cam.mu.mem_read(now + (image_addr - a), 4)))[0], now != a


@unittest.skipIf(T.Uc is None or not IMG, 'needs unicorn and out/MAIN_c0000000.bin; skipped = unverified')
class Stage1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cam = boot([(name(1), blob(1)[0])])
        cls.base = cls.cam.st(name(1), 1)

    def test_installed_and_logged(self):
        c = self.cam
        self.assertEqual(stword(c, self.base, 'magic'), 0x4E555251)
        self.assertEqual((stword(c, self.base, 'result'), stword(c, self.base, 'csv_result')), (0, 0))
        self.assertEqual(stword(c, self.base, 'key_patched'), 16)          # 4 rows x 4 CSVs
        self.assertTrue(any(t.startswith('QSP 1 00000000') for t in c.ours_line()), c.ours_line())

    def test_every_cine_csv_has_four_rows_with_private_labels(self):
        c = self.cam
        table = redirect_table(c)
        for i, (nm, addr, size) in enumerate(Q.CSVS):
            copy, n = table[addr]
            data = bytes(c.mu.mem_read(copy, n))
            stock = Q.stock_csv(i)
            self.assertEqual(data[:len(stock)], stock, nm)                  # stock rows untouched
            self.assertTrue(data.endswith(b'\r\n'), nm)
            head, rows = Q.csv_records(data)
            self.assertEqual(len(rows), 36, nm)
            new = rows[32:]
            self.assertEqual([r[0] for r in new], ['33', '34', '35', '36'])
            self.assertEqual([r[1] for r in new], ['49', '50', '51', '52'])
            self.assertEqual([r[2] for r in new], Q.ICONS)
            for k, r in enumerate(new):
                sid = int(r[3])
                self.assertTrue(0x40000000 <= sid < 0x80000000, r)
                got = c.call(0xC05E5B58, r0=F6.READER, r1=sid, thumb=True)[0]   # the core's resolve hook
                self.assertEqual(got, sid + 0x80000000)
                self.assertEqual(cstr(c, got), Q.LABELS[k])
                self.assertEqual(c.call(0xC05E61C8, r0=F6.READER, r1=got, thumb=True)[0], 1)   # borrowed

    def test_list_maximum_is_raised_by_four_in_both_editor_pages(self):
        for page in Q.PAGES:
            v, copied = page_word(self.cam, page, Q.visible_max(page))
            self.assertTrue(copied, page)
            self.assertEqual(v, 35.0, page)

    def test_converter_untouched_and_ui49_stores_internal_0(self):
        c = self.cam
        self.assertEqual(c.conv_built(), CONV)
        self.assertEqual(c.w(CONV_VT), VT_STOCK)
        self.assertEqual([c.to_int(u) for u in (49, 50, 51, 52)], [0, 0, 0, 0])   # the research's §3.1
        self.assertEqual(c.to_int(20), 21)                                     # stock still converts
        self.assertEqual([c.to_ui(i) for i in (54, 55, 56, 57)], [0, 0, 0, 0])   # unknown internal -> UI 0

    def test_stock_keys_build_has_no_private_strings(self):
        c = boot([(name(1), blob(1, stock_keys=True)[0])])
        copy, n = redirect_table(c)[Q.CSVS[0][1]]
        _h, rows = Q.csv_records(bytes(c.mu.mem_read(copy, n)))
        self.assertEqual([r[3] for r in rows[32:]], Q.STOCK_KEYS)


@unittest.skipIf(T.Uc is None or not IMG, 'needs unicorn and out/MAIN_c0000000.bin; skipped = unverified')
class Stage2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cam = boot([(name(2), blob(2)[0])])
        cls.base = cls.cam.st(name(2), 2)

    def test_vtable_is_a_copy_with_only_the_cine_slot_changed(self):
        c = self.cam
        vt = c.w(CONV_VT)
        self.assertNotEqual(vt, VT_STOCK)
        self.assertEqual(vt & 0xF0000000, 0xC0000000)                          # the cached alias
        mine = bytes(c.mu.mem_read(vt - 8, 8 + 0x55C))
        stock = IMG[VT_STOCK - 8 - 0xC0000000:VT_STOCK + 0x55C - 0xC0000000]
        diff = [i for i in range(0, len(stock), 4) if mine[i:i + 4] != stock[i:i + 4]]
        self.assertEqual(diff, [8 + 0x344])

    def test_ui_to_internal_both_ways_through_the_firmware(self):
        c = self.cam
        self.assertEqual([c.to_int(u) for u in (49, 50, 51, 52)], [54, 55, 56, 57])
        self.assertEqual([c.to_ui(i) for i in (54, 55, 56, 57)], [49, 50, 51, 52])
        for internal, ui in STOCK_CINE:                                       # every stock pair still holds
            self.assertEqual(c.to_int(ui), next(i for i, u in STOCK_CINE if u == ui))
            self.assertEqual(c.to_ui(internal), next(u for i, u in STOCK_CINE if i == internal))

    def test_unknown_ids_still_map_to_0(self):
        c = self.cam
        self.assertEqual([c.to_int(u) for u in (53, 60, 0xFFFF)], [0, 0, 0])
        self.assertEqual([c.to_ui(i) for i in (58, 99)], [0, 0])

    def test_still_table_is_not_extended(self):
        c = self.cam
        c.cine = False
        try:
            self.assertEqual(c.to_int(49), 0)
            self.assertEqual(c.to_int(4), 9)
        finally:
            c.cine = True

    def test_power_off_puts_the_stock_vtable_back(self):
        c = boot([(name(2), blob(2)[0])])
        self.assertIn((CONV_VT, 4, struct.pack('<I', VT_STOCK)), c.journal())
        c.power_off()
        self.assertEqual(c.w(CONV_VT), VT_STOCK)

    def test_a_stale_pointer_from_the_last_boot_is_repaired_first(self):
        def stale(cam):
            cam.put(CONV, 0x44); cam.put(CONV_VT, 0xC5DEAD00); cam.put(GUARD, 1)
        c = boot([(name(2), blob(2)[0])], prepare=stale)
        base = c.st(name(2), 2)
        self.assertEqual(c.w(base + 56), VT_STOCK)                             # prev_vt: chained on stock
        self.assertEqual(c.to_int(49), 54)

    def test_chains_onto_a_previous_layer(self):
        alpha = Q.build(2, ids=(58, 53, 1), sup_id='SLQA', name='alpha')[0]
        c = boot([('SLQSAlpha_v0.1.0.BIN', alpha), (name(2), blob(2)[0])])
        a_vt = c.block_of('SLQSAlpha_v0.1.0.BIN')
        base = c.st(name(2), 2)
        prev = c.w(base + 56)
        self.assertNotEqual(prev, VT_STOCK)
        self.assertTrue(a_vt < prev < a_vt + 0x4000, (hex(a_vt), hex(prev)))   # alpha's copy
        self.assertEqual(c.to_int(53), 58)                                     # alpha's pair
        self.assertEqual(c.to_ui(58), 53)
        self.assertEqual([c.to_int(u) for u in (49, 52)], [54, 57])            # ours on top
        self.assertEqual(c.to_int(20), 21)
        c.power_off()
        self.assertEqual(c.w(CONV_VT), VT_STOCK)

    def test_a_layer_with_our_ids_makes_us_stand_down(self):
        clash = Q.build(2, ids=(54, 49, 1), sup_id='SLQA', name='clash')[0]
        c = boot([('SLQSAlpha_v0.1.0.BIN', clash), (name(2), blob(2)[0])])
        released = [t for code, a, b, t in c.loadlog() if code == T.CODES['RELEASED']]
        self.assertTrue(any(name(2) in t for t in released), c.loadlog())
        self.assertTrue(any(t.startswith('QSP 2 00030000') for t in c.ours_line()), c.ours_line())
        a_vt = c.block_of('SLQSAlpha_v0.1.0.BIN')
        self.assertTrue(a_vt < c.w(CONV_VT) < a_vt + 0x4000)                   # alpha's, not ours
        self.assertEqual(c.to_int(50), 0)

    def test_stage_2_alone_would_put_our_id_in_flash(self):
        """The negative control: why stage 2 must not be powered off holding our id."""
        c = boot([(name(2), blob(2)[0])])
        c.set_slot(1, 2, 55)
        _r, flash = c.save()
        self.assertEqual(struct.unpack_from('<I', flash, ARR[1] + 8)[0], 55)


@unittest.skipIf(T.Uc is None or not IMG, 'needs unicorn and out/MAIN_c0000000.bin; skipped = unverified')
class Stage3(unittest.TestCase):
    def cam(self, **kw):
        return boot([(name(3), blob(3)[0])], **kw)

    def flash_ids(self, flash):
        return [struct.unpack_from('<I', flash, ARR[a] + 4 * k)[0] for a in (0, 1) for k in range(8)]

    def record(self, c):
        data = c.written['\\fpSup\\' + name(3)]
        off = blob(3)[1]['rec_off']
        return struct.unpack_from('<20I', data, off)

    def test_hooks_installed_and_journalled(self):
        c = self.cam()
        self.assertEqual(c.w(SAVE_SITE) >> 24, 0xEB)
        self.assertEqual(c.w(REC_SITE) >> 24, 0xEB)
        j = {a: d for a, n, d in c.journal()}
        self.assertEqual(j[SAVE_SITE], struct.pack('<I', SAVE_STOCK))
        self.assertEqual(j[REC_SITE], struct.pack('<I', REC_STOCK))
        c.power_off()
        self.assertEqual((c.w(SAVE_SITE), c.w(REC_SITE), c.w(CONV_VT)), (SAVE_STOCK, REC_STOCK, VT_STOCK))

    def test_save_never_serialises_our_ids_and_ram_keeps_them(self):
        c = self.cam()
        c.set_slot(1, 0, 54); c.set_slot(1, 3, 57); c.set_slot(0, 5, 55); c.set_slot(1, 7, 25)
        _r, flash = c.save()
        ids = self.flash_ids(flash)
        self.assertFalse(set(ids) & {54, 55, 56, 57}, ids)
        self.assertEqual(ids[8], 0); self.assertEqual(ids[11], 0); self.assertEqual(ids[5], 0)
        self.assertEqual(ids[15], 25)                                          # a stock id is left alone
        ram = bytes(c.mu.mem_read(STORE + IMG_A, 0x4F00))
        changed = [i for i in range(0, 0x4F00, 4) if ram[i:i + 4] != flash[i:i + 4]]
        self.assertEqual(changed, [ARR[0] + 20, ARR[1], ARR[1] + 12])          # only our three words
        self.assertEqual((c.slot(1, 0), c.slot(1, 3), c.slot(0, 5)), (54, 57, 55))   # RAM put back

    def test_record_written_to_own_bin_and_restored_next_boot(self):
        c = self.cam()
        c.set_slot(1, 1, 56); c.set_slot(1, 6, 54)
        _r, flash = c.save()
        rec = self.record(c)
        self.assertEqual(rec[0], 0x31525351)
        self.assertEqual(rec[2 + 9], 56); self.assertEqual(rec[2 + 14], 54)
        self.assertNotIn('\\fpSup\\' + name(3), c.created)
        new_bin = c.written['\\fpSup\\' + name(3)]
        self.assertEqual(new_bin[:blob(3)[1]['rec_off']], blob(3)[0][:blob(3)[1]['rec_off']])

        def from_flash(cam):                                  # next boot: settings as the flush left them
            cam.mu.mem_write(STORE + IMG_A, flash)
            cam.mu.mem_write(STORE + SEL, b'\0')
        c2 = boot([(name(3), new_bin)], prepare=from_flash)
        self.assertEqual((c2.slot(1, 1), c2.slot(1, 6)), (56, 54))
        posts = [(n, v) for n, v in c2.posts if n.startswith('MV_QSMENU_QS')]
        self.assertIn(('MV_QSMENU_QS2', 51), posts)
        self.assertIn(('MV_QSMENU_QS7', 49), posts)
        self.assertEqual(len(posts), 8)
        self.assertIn('QSP 3 00000000 C2DEAD7C 00020010', c2.ours_line())

    def test_a_slot_changed_while_we_were_away_is_not_overwritten(self):
        c = self.cam()
        c.set_slot(1, 1, 56)
        _r, flash = c.save()
        new_bin = c.written['\\fpSup\\' + name(3)]

        def changed(cam):
            cam.mu.mem_write(STORE + IMG_A, flash)
            cam.put(STORE + IMG_A + ARR[1] + 4, 25)          # user picked WB with the sup off
        c2 = boot([(name(3), new_bin)], prepare=changed)
        self.assertEqual(c2.slot(1, 1), 25)
        self.assertEqual([n for n, v in c2.posts if n.startswith('MV_QSMENU')], [])

    def test_a_damaged_record_restores_nothing(self):
        c = self.cam()
        c.set_slot(1, 1, 56)
        _r, flash = c.save()
        bad = bytearray(c.written['\\fpSup\\' + name(3)])
        bad[blob(3)[1]['rec_off'] + 8 + 4 * 9] = 57          # still one of our ids: only the sum tells
        c2 = boot([(name(3), bytes(bad))], prepare=lambda cam: cam.mu.mem_write(STORE + IMG_A, flash))
        self.assertEqual(c2.slot(1, 1), 0)

    def test_record_rewritten_only_when_it_changes(self):
        c = self.cam()
        c.set_slot(1, 2, 55)
        c.save(); c.save()
        base = c.st(name(3), 3)
        writes = c.w(base + STF['writes'])
        self.assertEqual(writes, 1)
        c.set_slot(1, 2, 21)                                  # gone: the record says so next save
        c.save()
        self.assertEqual(self.record(c)[2 + 10], 0)

    def test_never_creates_or_writes_a_file_that_is_not_ours(self):
        c = self.cam()
        c.files['\\fpSup\\' + name(3)] = b'FSB4 something else entirely'.ljust(128, b'\0')
        c.set_slot(1, 2, 55)
        _r, flash = c.save()
        self.assertNotIn('\\fpSup\\' + name(3), c.written)
        self.assertNotIn('\\fpSup\\' + name(3), c.created)
        self.assertEqual(self.flash_ids(flash)[10], 0)        # flash still clean

    def test_a_renamed_or_deleted_bin_is_never_recreated(self):
        c = self.cam()
        del c.files['\\fpSup\\' + name(3)]                 # SupManager renamed it / user deleted it
        c.set_slot(1, 2, 55)
        _r, flash = c.save()
        self.assertNotIn('\\fpSup\\' + name(3), c.created)
        self.assertNotIn('\\fpSup\\' + name(3), c.written)
        self.assertEqual(self.flash_ids(flash)[10], 0)
        self.assertEqual(c.w(c.st(name(3), 3) + STF['write_why']), 2)

    def test_recording_defers_the_record_but_not_the_swap(self):
        c = self.cam()
        c.put(0xC35A952C, 1)                                  # MOV_ACTIVE
        c.set_slot(1, 2, 55)
        _r, flash = c.save()
        self.assertEqual(self.flash_ids(flash)[10], 0)
        self.assertNotIn('\\fpSup\\' + name(3), c.written)

    def test_recommended_setting_reader_sees_the_placeholder(self):
        c = self.cam()
        c.set_slot(1, 4, 57); c.set_slot(1, 5, 9)
        self.assertEqual(c.rec_read(4), 0)
        self.assertEqual(c.rec_read(5), 9)

    def test_the_converter_is_installed_too(self):
        c = self.cam()
        self.assertEqual([c.to_int(u) for u in (49, 52)], [54, 57])
        self.assertEqual(c.to_ui(56), 51)

    def test_two_save_layers_chain(self):
        alpha = Q.build(3, ids=(58, 53, 1), sup_id='SLQA', name='alpha')[0]
        c = boot([('SLQSAlpha_v0.1.0.BIN', alpha), (name(3), blob(3)[0])])
        c.set_slot(1, 0, 58); c.set_slot(1, 1, 54)
        _r, flash = c.save()
        self.assertEqual(self.flash_ids(flash)[8:10], [0, 0])
        self.assertEqual((c.slot(1, 0), c.slot(1, 1)), (58, 54))
        self.assertEqual(c.rec_read(0), 0)
        self.assertEqual(c.to_int(53), 58)
        self.assertEqual(c.to_int(49), 54)

    def test_only_one_call_site_feeds_the_flash_buffer(self):
        """Static: FUN_c0088660 (the copy into the settings flush buffer) has one
        caller in the image, the site we hook; FUN_c053db98's slot read is the
        only RecommendedSetting read of QS slots.  A firmware with another
        writer would fail here first."""
        import struct as S
        callers, readers = [], []
        for off in range(0, 0xB00000, 4):
            w = S.unpack_from('<I', IMG, off)[0]
            if (w & 0x0E000000) == 0x0A000000 and (w >> 28) != 0xF:
                imm = w & 0xFFFFFF
                t = 0xC0000000 + off + 8 + ((imm - (1 << 24) if imm & 0x800000 else imm) << 2)
                if t == 0xC0088660:
                    callers.append(0xC0000000 + off)
                if t == 0xC0061B08 and 0xC053D000 <= 0xC0000000 + off < 0xC053F000:
                    readers.append(0xC0000000 + off)
        self.assertEqual(callers, [SAVE_SITE])
        self.assertEqual(IMG.count(S.pack('<I', 0xC0088660)), 0)
        self.assertEqual(readers, [REC_SITE])


# ---- mutations: each must make at least one test fail -------------------------
MUTANTS = [
    ('table not extended', 'qsprobe.c', 's->tab_n = n + s->n;', 's->tab_n = n;'),
    ('pairs swapped', 'qsprobe.c', 's->tab[2u * (n + j)] = s->ibase + j;', 's->tab[2u * (n + j)] = s->ubase + j;'),
    ('chain on stock, not the layer below', 'qsprobe.c', 'u32 prev = W(CONV_VT);', 'u32 prev = VT_STOCK;'),
    ('no collision check', 'qsprobe.c', 'if (ours_int(s, a) || ours_ui(s, b)) { s->collide++; return 0; }', ''),
    ('vtable word not claimed', 'qsprobe.c',
     'if (svc->claim(svc, CONV_VT, 4, &(u32){VT_STOCK}, SL_CHAIN) != SL_OK) return qp_fail(s, R_CLAIM_VT);', ''),
    ('save does not sanitise', 'qsprobe.c', 'W(a) = s->ph; mask |= 1u << i;', 'mask |= 0;'),
    ('save does not put RAM back', 'qsprobe.c', '{ W(image + arr(i)) = old[i]; s->sanitized++; }', '{ s->sanitized++; }'),
    ('only the first set sanitised', 'qsprobe.c', 'return (i < 8u ? QS_ARR0 : QS_ARR1) + 4u * (i & 7u);',
     'return QS_ARR0 + 4u * (i & 7u);'),
    ('record never written', 'qsprobe.c', 'u32 why = qp_write(s, slots);', 'u32 why = 0;'),
    ('restore ignores the placeholder check', 'qsprobe.c', 'if (W(img + arr(i)) == s->ph)', 'if (1)'),
    ('record checksum not checked', 'qsprobe.c', ' || r[REC_SUM] != rec_sum(tmp)) return;', ') return;'),
    ('file_is skipped', 'qsprobe.c',
     'if (svc->file_is(svc, s->path, s->block, SL4_HEADER_LEN) != SL_OK) return 2;', ''),
    ('recording not deferred', 'qsprobe.c', 'if (busy()) { s->busy_skips++; return; }', ''),
    ('recommended reader not mapped', 'qsprobe.c', 'if (ours_int(s, v)) { s->rec_hits++; return s->ph; }', ''),
    ('save hook not armed', 'qsprobe.c', 'W(SAVE_SITE) = bl_to(SAVE_SITE, v);', ''),
    ('no re-post after restore', 'qsprobe.c', '((fn3)POST_INT)(0, QS_NAME0 + 0x10u * k, ui);', '(void)ui;'),
    ('keys not patched', 'qsprobe.c', 's->key_patched = qp_keys(s);', 's->key_patched = 16;'),
    ('builder: no list maximum', 'env', 'QSPROBE_MUTATE', 'nomax'),
    ('builder: no key placeholder', 'env', 'QSPROBE_MUTATE', 'nokey'),
]


def mutate():
    src = (HERE / 'qsprobe.c').read_text()
    survived = []
    for label, where, old, new in MUTANTS:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        env.pop('PYTHONPYCACHEPREFIX', None)
        with tempfile.TemporaryDirectory(prefix='qsp-mut-') as t:
            if where == 'qsprobe.c':
                if src.count(old) != 1:
                    print(f'  BAD MUTANT (pattern x{src.count(old)}): {label}')
                    survived.append(label)
                    continue
                p = pathlib.Path(t) / 'qsprobe.c'
                p.write_text(src.replace(old, new))
                env['QSPROBE_SRC'] = str(p)
            else:
                env[old] = new
            r = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-q', 'test_qsprobe'], cwd=HERE,
                               env=env, capture_output=True, text=True)
        failed = r.returncode != 0 and ('FAILED' in r.stderr or 'Error' in r.stderr)
        print(f'  {"caught " if failed else "SURVIVED"}  {label}')
        if not failed:
            survived.append(label)
    print(f'{len(MUTANTS) - len(survived)}/{len(MUTANTS)} mutants caught')
    return 1 if survived else 0


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        sys.exit(mutate())
    unittest.main()
