#!/usr/bin/env python3
"""The QS container (stage 1) on the real ARM bytes, offline.

The real v4 core (LOADER.BIN with the fpSup page) loads the real
QSContainer_v0.1.0.BIN and the real QSTest client through the real AutoRun
loader, against the real firmware image (out/MAIN_c0000000.bin).  Real
firmware code that runs: the converter (FUN_c058c4d0, FUN_c06c7bc0 /
FUN_c06c7b28 / FUN_c06d0fa0 / FUN_c06ce6f0, the stock vtable functions),
FUN_c0088660 from the save's call site, the core's string resolve hook, the
uishare file-redirect handler (installed by fpui_stock), the call sites of the
four hooks.

Python models (declared, not the firmware): the UI app (uishare/tab/test_ft6:
reader, page entries, variable posts), the settings getters C0057AE8 /
C0058340 / FUN_c0061b08, FUN_c05666a0 (the QS state object), the headphone
setter FUN_c0062bb0 (counted), the body of FUN_c05d90f0 after its first
instruction (returns 0x77), the guard pair, memcpy, checksum, the file API.

The editor's GUI page build (objects, events, animations) cannot be run
offline (research/ui/tools/nbu_probe stops before element construction), so the
freeze regression is a data check of the page copy the camera code made:
re-derived from its bytes, every tile's event range, interval and the three
clips are evaluated at each new id's frame with the playback model in
editor_data.Prop (hold / linear), and the same model on the stock page shows
the failure (name 'xxxx', list row 90).

    cd projects/qs-container && python3 -B -m unittest test_qsct
    python3 -B test_qsct.py --mutate        # every mutant must fail a test
"""
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(HERE / 'testclient'), str(ROOT / 'fpSup/loader-v4')]
import build_qsct as Q                      # noqa: E402
import build_qstest as QT                   # noqa: E402
import editor_data as E                     # noqa: E402
import test_ui_v4 as U                      # noqa: E402

import testcache as TC                     # noqa: E402  (test-only caches; README "Testing")

T = U.T
T3 = T.T3
F6 = U.F6
T3.IMAGE = TC.image_once(T3.IMAGE)          # every camera boot reads the image: once per process
T.V3.autorun = TC.memo(T.V3.autorun)        # every camera boot spawns build_autorun.py: once per process
_U_BUILT = getattr(U.built, '_tc_orig', U.built)


def _u_built():
    """the v4 core, FPSUP.BIN and SUPMGR (test_ui_v4.built), from the test cache"""
    if not U._cache:
        U._cache.update(TC.cached('ui_v4', _U_BUILT))
    return U._cache


_u_built._tc_orig = _U_BUILT
U.built = _u_built
IMG = T3.IMAGE.read_bytes() if T3.IMAGE.exists() else b''

CONV, CONV_VT, VT_STOCK = 0xC37B7724, 0xC37B7728, 0xC2DEAD7C
UI_TO_INT, INT_TO_UI = 0xC06C7BC0, 0xC06C7B28
SAVE_SITE, SAVE_STOCK, REC_SITE, REC_STOCK = 0xC0088C60, 0xEBFFFE7E, 0xC053DBF8, 0xEBEC8FC2
HP_SITE, HP_STOCK, HP_SET = 0xC0582AE8, 0xEBEB8030, 0xC0062BB0
LAY_SITE, LAY_STOCK, LAY_BODY = 0xC05D90F0, 0x4CF0E92D, 0xC05D90F4
FV_SITE = 0xC05E5BEC
QS_STATE = 0xC05666A0
STORE, IMG_A, SEL = 0xC31AE3B0, 0xC, 0xB19C
ARR = (0x23E8, 0x2700)
F_SEEK, MEMCPY, CSUM, ASSERT = 0xC03661E0, 0xC0014DAC, 0xC00228D0, 0xC0011100
GUARD_ACQ, GUARD_REL, SETTINGS_GET, IS_CINE, QS_GET = 0xC0013090, 0xC00131E4, 0xC0057AE8, 0xC0058340, 0xC0061B08
SETTINGS = F6.FAKE + 0xA000
USERSET = F6.FAKE + 0xA100
QSOBJ = F6.FAKE + 0xB000                  # FUN_c05666a0's object; +0xBC = the focused tile's internal id
LAYOUT = F6.FAKE + 0xB400
FLASH = 0xC3E00000
REC_PARSE, REC_PARSE_STOCK, REC_BODY = 0xC05E6400, 0x4FF0E92D, 0xC05E6404
RCACHE, RCACHE_V2, RCACHE_V3 = 0xC37B7254, 0xC05663E8, 0xC0566498
QSLAY, QSTREE, QSCTX = F6.FAKE + 0xD000, F6.FAKE + 0xD100, F6.FAKE + 0xD200
PAGES = E.PAGES + ['QS_CINE']
NBU = 0xC18C0460
RESOLVE = 0xC05E5B58
# v0.2.1: the hint's value (QS state +0x44 -> vt +0x74) and its setter (FUN_c054dd38 -> vt +0x2C)
GUID_SITE, GUID_STOCK, APPVARS = 0xC0582DB4, 0xEBFFF155, 0xC054DD38
GVT, GUID_GET, AVOBJ, AVVT, GUID_SETV = (F6.FAKE + o for o in (0xB800, 0xB900, 0xB980, 0xB9C0, 0xBA00))
NAMES = ['MV_QSMENU_QS%d' % k for k in range(1, 9)]
STOCK_CINE = [struct.unpack_from('<2I', IMG, 0x2E431A4 + 8 * i) for i in range(51)] if IMG else []
CNAME, TNAME = Q.file_name(), QT.file_name()
CPATH = '\\fpSup\\' + CNAME
REC_WORDS = Q.REC_WORDS

_built = {}


def cblob():
    if 'c' not in _built:
        _built['c'] = TC.cached('qsct', Q.build, key=TC.file_key(Q.SOURCE))
    return _built['c']


def tblob(**kw):
    key = repr(sorted(kw.items()))
    if key not in _built:
        _built[key] = QT.build(**kw)
    return _built[key]


if T.Uc is not None:
    _ORIG_HOOK = T.Uc.hook_add

    def rom_hook(mu, kind, cb, *a, **kw):
        if kind == T.UC_HOOK_CODE and not a and not kw:
            kw = dict(begin=0xC0000000, end=0xC3FFFFFF)
        return _ORIG_HOOK(mu, kind, cb, *a, **kw)


class Cam(U.Cam):
    PAGE_ENTRIES = F6.FAKE + 0xC000

    def __init__(self, files, dirs, cine=True):
        with patch.object(T.Uc, 'hook_add', rom_hook):
            super().__init__(files, dirs)
        self.cine = cine
        self.created, self.copies, self.hp_sets, self.lay_bodies = [], [], [], 0
        for a, n in ((GUARD_ACQ, 'G_ACQ'), (GUARD_REL, 'G_REL'), (SETTINGS_GET, 'SET_GET'),
                     (IS_CINE, 'IS_CINE'), (QS_GET, 'QS_GET'), (F_SEEK, 'F_SEEK'), (MEMCPY, 'MEMCPY'),
                     (CSUM, 'CSUM'), (ASSERT, 'ASSERT'), (HP_SET, 'HP_SET'), (QS_STATE, 'QS_STATE')):
            self.by_addr[a] = n
            if a in (HP_SET, QS_STATE):
                self.mu.mem_write(a, struct.pack('<I', 0xE12FFF1E))
        # FUN_c05d90f0 past its first instruction: movs r0, #0x77; pop.w {r4-r7, r10, r11, pc}
        self.mu.mem_write(LAY_BODY, bytes.fromhex('7720') + bytes.fromhex('bde8f08c'))
        self.by_addr[LAY_BODY] = 'LAY_BODY'
        at, names = self.PAGE_ENTRIES, self.PAGE_ENTRIES + 44 * len(PAGES)
        for i, page in enumerate(PAGES):
            _a, off, _n = E.O.resource_set(page)
            e = at + 44 * i
            self.mu.mem_write(e, bytes(44))
            self.mu.mem_write(names + 32 * i, page.encode() + b'\0')
            self.put(e + 4, names + 32 * i)
            self.put(e + 8, off)
        self.put(F6.READER + 0xA8, len(PAGES))
        self.put(F6.READER + 0xAC, at)
        self.mu.mem_write(QSOBJ, bytes(0x100))
        # the QS state's hint copy and the app variable object (declared models)
        self.guid_cur, self.guid_sets = 1, []
        for a, n in ((GUID_GET, 'GUID_GET'), (APPVARS, 'APPVARS'), (GUID_SETV, 'GUID_SETV')):
            self.mu.mem_write(a, struct.pack('<I', 0xE12FFF1E))
            self.by_addr[a] = n
        self.mu.mem_write(GVT, bytes(0x80))
        self.put(QSOBJ + 0x44, GVT)
        self.put(GVT + 0x74, GUID_GET)
        self.mu.mem_write(AVVT, bytes(0x40))
        self.put(AVOBJ, AVVT)
        self.put(AVVT + 0x2C, GUID_SETV)
        # FUN_c05e6400 past its first instruction: the record is taken (Python),
        # then movs r0, #1; pop.w {r4-r11, pc}
        self.mu.mem_write(REC_BODY, bytes.fromhex('0120') + bytes.fromhex('bde8f08f'))
        self.by_addr[REC_BODY] = 'REC_BODY'
        self.parsed = []
        # the resource cache holds a parsed QS layout L (one reference)
        for a in (RCACHE_V2, RCACHE_V3):
            self.mu.mem_write(a, struct.pack('<I', 0xE12FFF1E))
        self.by_addr[RCACHE_V2], self.by_addr[RCACHE_V3] = 'RC_V2', 'RC_V3'
        self.rcache_calls = []
        self.mu.mem_write(RCACHE, bytes(0x40))
        self.mu.mem_write(QSLAY, bytes(0x40))
        self.mu.mem_write(QSTREE, bytes(0x40))
        self.mu.mem_write(QSCTX, bytes(0x900))
        self.put(RCACHE + 4, QSLAY)
        self.put(QSLAY + 0xC, QSTREE)
        self.put(QSLAY + 4, QSCTX)
        self.put(QSTREE + 0xC, 1)

    def _hook(self, mu, addr, size, data):
        name = self.by_addr.get(addr)
        r = [self.r(getattr(T3, 'UC_ARM_REG_R%d' % i)) for i in range(4)]
        if name == 'LAY_BODY':
            self.lay_bodies += 1
            return
        if name == 'REC_BODY':
            base, pos = self.w(r[0] + 0x24), self.w(r[0] + 4)
            a = (base + pos) & 0xFFFFFFFF
            n = struct.unpack('>I', bytes(mu.mem_read(a + 4, 4)))[0]
            self.parsed.append((base, pos, bytes(mu.mem_read(a, n))))
            self.put(r[0] + 4, pos + n)                       # the parser moves past it
            return
        if name in ('RC_V2', 'RC_V3'):
            self.rcache_calls.append((name, r[0]))
            if name == 'RC_V3' and r[0] == RCACHE:
                self.put(RCACHE + 4, 0)
            return self._ret(0)
        if name == 'G_ACQ':
            return self._ret(0 if self.w(r[0]) & 1 else 1)
        if name == 'G_REL':
            self.put(r[0], 1)
            return self._ret(0)
        if name == 'SET_GET':
            return self._ret(SETTINGS)
        if name == 'IS_CINE':
            return self._ret(1 if self.cine else 0)
        if name == 'QS_GET':
            assert r[0] == SETTINGS and r[1] < 8
            return self._ret(self.slot(1 if self.cine else 0, r[1]))
        if name == 'QS_STATE':
            return self._ret(QSOBJ)
        if addr == 0xC0593FE0:                                # POST_STR: texts longer than ft6's 256
            name, value = self.cstr(r[1]), self.cstr(r[2], 2048)
            self.posts.append((name, value))
            if name in self.vars:
                self.vars[name] = (self.vars[name][0], value)
            return self._ret(0)
        if name == 'GUID_GET':
            assert r[0] == QSOBJ + 0x3C
            return self._ret(self.guid_cur)
        if name == 'APPVARS':
            return self._ret(AVOBJ)
        if name == 'GUID_SETV':
            assert r[0] == AVOBJ
            self.guid_sets.append((self.cstr(r[1]), r[2]))
            self.guid_cur = r[2]
            return self._ret(0)
        if name == 'HP_SET':
            self.hp_sets.append((r[0], r[1], r[2]))
            return self._ret(0)
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
            raise AssertionError('firmware assert ' + self.cstr(r[0]))
        if name == 'F_OPEN' and r[2] == 7:
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

    # --- settings -----------------------------------------------------------
    def image(self):
        return STORE + (0x58D4 if self.mu.mem_read(STORE + SEL, 1)[0] else IMG_A)

    def slot(self, a, k):
        return self.w(self.image() + ARR[a] + 4 * k)

    def set_slot(self, a, k, v):
        self.put(self.image() + ARR[a] + 4 * k, v)

    def call(self, pc, r0=0, r1=0, r2=0, lr=T3.DONE, sp=T3.STACK - 0x1004, thumb=False):
        """test_v3.Camera.call, its 20 M instruction cap as a wall-clock cap (testcache.emu_start)"""
        mu = self.mu
        mu.reg_write(T3.UC_ARM_REG_SP, sp)
        for reg, v in ((T3.UC_ARM_REG_R0, r0), (T3.UC_ARM_REG_R1, r1), (T3.UC_ARM_REG_R2, r2)):
            mu.reg_write(reg, v & 0xFFFFFFFF)
        mu.reg_write(T3.UC_ARM_REG_LR, lr)
        try:
            TC.emu_start(mu, pc | (1 if thumb else 0), T3.DONE, 20_000_000)
        finally:
            if self.error:
                raise self.error
        return self.r(T3.UC_ARM_REG_R0), self.r(T3.UC_ARM_REG_SP)

    def run(self, pc, until, **regs):
        from unicorn import arm_const
        from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR
        self.mu.reg_write(UC_ARM_REG_SP, T3.STACK - 0x1000)
        self.mu.reg_write(UC_ARM_REG_LR, T3.DONE)
        for k, v in regs.items():
            self.mu.reg_write(getattr(arm_const, 'UC_ARM_REG_' + k.upper()), v & 0xFFFFFFFF)
        try:
            TC.emu_start(self.mu, pc, until, 50_000_000)
        finally:
            if self.error:
                raise self.error
        assert self.r(T3.UC_ARM_REG_PC) == until, hex(self.r(T3.UC_ARM_REG_PC))
        return self.r(T3.UC_ARM_REG_R0)

    def to_int(self, ui):
        return self.call(UI_TO_INT, r0=CONV, r1=ui)[0]

    def to_ui(self, internal):
        return self.call(INT_TO_UI, r0=CONV, r1=internal)[0]

    def layout(self):
        """A screen change: FUN_c05d90f0(layout) entered at its first word."""
        r0, sp = self.call(LAY_SITE, r0=LAYOUT, thumb=True, sp=T3.STACK - 0x1004)
        assert sp == T3.STACK - 0x1004 and r0 == 0x77, (hex(r0), hex(sp))
        return r0

    def save(self):
        hdr, pair = F6.FAKE + 0xA200, F6.FAKE + 0xA280
        self.mu.mem_write(FLASH, bytes(0x4F00))
        self.put(USERSET + 0x48, pair)
        self.put(pair, hdr)
        self.put(pair + 4, FLASH)
        self.put(hdr + 8, 0xE)
        self.put(hdr + 0x10, 0x4F00)
        self.copies.clear()
        self.run(SAVE_SITE, SAVE_SITE + 4, r0=USERSET, r1=STORE + IMG_A, r4=STORE)
        assert self.copies == [(FLASH, STORE + IMG_A, 0x4F00)], self.copies
        return bytes(self.mu.mem_read(FLASH, 0x4F00))

    def rec_read(self, k):
        return self.run(REC_SITE, REC_SITE + 4, r0=SETTINGS, r1=k)

    def hp(self, focused, volume=7):
        """The QS GUI's headphone callback at its setter call, the QS tile `focused`."""
        self.put(QSOBJ + 0xBC, focused)
        self.hp_sets.clear()
        self.run(HP_SITE, HP_SITE + 4, r0=SETTINGS, r1=volume, r2=1)
        return list(self.hp_sets)

    def guid(self, internal):
        """FUN_c0582da0 at its `bl FUN_c057f310(id)`: the QS GUI's QS_QSMode callback, +0xBC written."""
        self.put(QSOBJ + 0xBC, internal)
        self.run(GUID_SITE, GUID_SITE + 4, r0=internal)

    def block_of(self, name):
        return T.blocks(self)[name]

    def st(self):
        return self.block_of(CNAME) + cblob()[1]['state_off']

    def page_copy(self, i):
        """(address, bytes, FSPG header words) the runtime entry of page i now points at."""
        off = self.w(self.PAGE_ENTRIES + 44 * i + 8)
        a = 0xC18C0460 + off
        h = (a & ~3) - 128
        hdr = struct.unpack('<9I', bytes(self.mu.mem_read(h, 36)))
        return a, bytes(self.mu.mem_read(a, hdr[3])), hdr, off

    def csv(self, stock_addr):
        w = self.w(FV_SITE)
        hw1, hw2 = w & 0xFFFF, w >> 16
        s = (hw1 >> 10) & 1; j1 = (hw2 >> 13) & 1; j2 = (hw2 >> 11) & 1
        off = s << 24 | (1 ^ (j1 ^ s)) << 23 | (1 ^ (j2 ^ s)) << 22 | (hw1 & 0x3FF) << 12 | (hw2 & 0x7FF) << 1
        if s:
            off |= 0xFE000000
        entry = self.w((FV_SITE + 4 + off + 4) & 0xFFFFFFFF)
        _code, ent, tw = E.O.handler()
        table = self.w(entry - ent + tw)
        for i in range(self.w(table + 8)):
            if self.w(table + 16 + 12 * i) == stock_addr:
                return bytes(self.mu.mem_read(self.w(table + 20 + 12 * i), self.w(table + 24 + 12 * i)))
        return None


# struct st (qsct.c) field offsets
ST_N = 32
ST_FIELDS = ['magic', 'result', 'phase', 'freeze']
FN_BYTES = 36


def stw(cam, off):
    return cam.w(cam.st() + off)


def st_word(cam, name):
    return stw(cam, 4 * ST_FIELDS.index(name))


# counters after the converter block: struct st layout
_AFTER_FN = 56 + FN_BYTES * 16
_CONV = _AFTER_FN + 4 * 8 + 4 * ((8 + 0x55C) // 4) + 4 * 2 * 96
_HOOKS = _CONV + 4 * 5
_REC = _HOOKS + 4 * (16 * 4 + 16 + 2)
_LAST = _REC
_CNT = _LAST + 4 * 16
COUNTERS = {n: _CNT + 4 * i for i, n in enumerate(
    ['saves', 'sanitized', 'rec_hits', 'hp_blocks', 'restored', 'stale', 'orphans',
     'writes', 'write_fails', 'write_why', 'busy_skips', 'emitted'])}


def counter(cam, name):
    return stw(cam, COUNTERS[name])


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


def std(client=True, cfile=None, **kw):
    sups = [(CNAME, cfile or cblob()[0])]
    if client:
        sups.append((TNAME, tblob()))
    return boot(sups, **kw)


def ready(**kw):
    c = std(**kw)
    c.layout()
    return c


def cstr(cam, a):
    return bytes(cam.mu.mem_read(a, 64)).split(b'\0')[0].decode()


def csv_records(data):
    import csv
    import io
    rows = list(csv.reader(io.StringIO(data.decode('utf-8-sig'), newline='')))
    return rows[0], rows[1:]


def copy_tiles(page_bytes):
    """editor_data's tile finder on the bytes the camera made."""
    recs = E.records(page_bytes)
    objs = E.objects(page_bytes, recs)
    menu = next(i for i, (n, _p) in objs.items() if n == 'Menu01')
    icon_name = E.pool_offset('Icon01_CINE')
    out = []
    for k in range(1, 9):
        tile = E.children(objs, menu, f'QS{k}C')
        cine = E.children(objs, E.children(objs, tile, 'Icon01'), 'Icon01_CINE')
        index, string = E.children(objs, cine, 'index'), E.children(objs, cine, 'string')
        var = E.pool_offset(f'MV_QSMENU_QS{k}')
        ev = [o for o, tag, s in recs if tag == E.T_EVENT and E.be(page_bytes, o + 24) == cine
              and E.be(page_bytes, o + 36) == var and page_bytes[o + 44] == 0x23]
        gr = [o for o, tag, s in recs if tag == E.T_GROUP and E.be(page_bytes, o + 24) == cine
              and E.be(page_bytes, o + 20) == icon_name]
        assert len(ev) == 1 and len(gr) == 1
        out.append(dict(upper=struct.unpack_from('>f', page_bytes, ev[0] + 45)[0],
                        end=E.be(page_bytes, gr[0] + 36),
                        icon=E.clip_of(page_bytes, recs, cine, 2), row=E.clip_of(page_bytes, recs, index, 3),
                        text=E.clip_of(page_bytes, recs, string, 2),
                        default_text=None))
    return recs, objs, out


def page_build_state(tile, ui):
    """What tile `tile` holds after its page is built with MV_QSMENU_QSn = ui:
    the event fires only inside its range; otherwise the static first values
    stay (drawText 'xxxx', index.position_x 90.0) -- QS_EDITOR_ID_PATHS.md §1.1."""
    if ui > tile['upper']:
        return {'fired': False, 'text': 'xxxx', 'row': 90.0}
    t = Fraction(ui * 100, 3)
    t = min(t, tile['end'])
    return {'fired': True, 'text': tile['text'].prop('text', 0).value_at(t),
            'row': tile['row'].prop('position', 0).value_at(t),
            'image': tile['icon'].prop('image').value_at(t),
            'rect': tile['icon'].prop('rect', 2).value_at(t),
            'size': tile['icon'].prop('size', 0).value_at(t),
            'pos': tile['icon'].prop('position', 0).value_at(t)}


def f32(w):
    return struct.unpack('<f', struct.pack('<I', w))[0]


SKIP = unittest.skipIf(T.Uc is None or not IMG, 'needs unicorn and out/MAIN_c0000000.bin; skipped = unverified')


@SKIP
class Registration(unittest.TestCase):
    def test_entry_installs_and_journals_every_site(self):
        c = std()
        self.assertEqual(st_word(c, 'magic'), 0x4E555251)
        self.assertEqual(st_word(c, 'result'), 0)
        self.assertEqual(st_word(c, 'phase'), 0)                     # not collected yet
        j = {a: d for a, n, d in c.journal()}
        for site, stock in ((SAVE_SITE, SAVE_STOCK), (REC_SITE, REC_STOCK), (HP_SITE, HP_STOCK),
                            (LAY_SITE, LAY_STOCK), (CONV_VT, VT_STOCK)):
            self.assertEqual(j[site], struct.pack('<I', stock), hex(site))
        self.assertNotEqual(c.w(LAY_SITE), LAY_STOCK)
        c.power_off()
        for site, stock in ((SAVE_SITE, SAVE_STOCK), (REC_SITE, REC_STOCK), (HP_SITE, HP_STOCK),
                            (LAY_SITE, LAY_STOCK), (CONV_VT, VT_STOCK)):
            self.assertEqual(c.w(site), stock, hex(site))

    def test_nothing_new_before_collection(self):
        c = std()
        self.assertEqual(c.to_int(49), 0)                            # no pairs yet: 49 is unknown
        self.assertEqual(c.to_int(20), 21)
        self.assertIsNone(c.csv(E.CSVS[0][1]))                         # the handler is in, our rows are not
        self.assertEqual(c.w(Cam.PAGE_ENTRIES + 8), E.O.resource_set('Y2_3C')[1])

    def test_first_layout_load_collects_the_client(self):
        c = ready()
        self.assertEqual(st_word(c, 'phase'), 2)
        self.assertEqual(st_word(c, 'freeze'), 0)
        self.assertEqual(stw(c, ST_N), 2)
        self.assertEqual(c.lay_bodies, 1)                            # the stock layout load still ran
        self.assertEqual([c.to_int(u) for u in (49, 50, 51)], [54, 55, 0])
        self.assertEqual([c.to_ui(i) for i in (54, 55, 56)], [49, 50, 0])
        for internal, ui in STOCK_CINE:
            self.assertEqual(c.to_int(ui), next(i for i, u in STOCK_CINE if u == ui))
        c.layout()                                                   # once only
        self.assertEqual(c.lay_bodies, 2)
        self.assertEqual(stw(c, ST_N), 2)

    def test_load_order_does_not_matter(self):
        early = QT.build(sup_id='QSTA')                              # 'AAQSTest' loads before the container
        c = boot([('AAQSTest_v0.1.0.BIN', early), (CNAME, cblob()[0])])
        c.layout()
        a = [c.csv(E.CSVS[0][1])]
        d = ready()
        b = [d.csv(E.CSVS[0][1])]
        self.assertEqual(stw(c, ST_N), 2)
        self.assertEqual(a, b)

    def test_two_clients_in_load_order(self):
        other = QT.build(funcs=[('X', 'Other X', 'menu_wb')], sup_id='QSTB')
        c = boot([(CNAME, cblob()[0]), (TNAME, tblob()), ('ZOther_v0.1.0.BIN', other)])
        c.layout()
        _h, rows = csv_records(c.csv(E.CSVS[0][1]))
        self.assertEqual([r[1:4] for r in rows[32:]], [['49', 'menu_crop', 'QS Test A'],
                                                       ['50', 'menu_lock', 'QS Test B'],
                                                       ['51', 'menu_wb', 'Other X']])

    def test_bad_functions_are_refused_one_by_one(self):
        bad = QT.build(funcs=[('A', '1234', 'menu_crop'), ('B', 'Comma,No', 'menu_crop'),
                              ('C', 'Good', 'menu_nope'), ('C', 'Dup', 'menu_crop'), ('', 'NoName', None)])
        c = boot([(CNAME, cblob()[0]), (TNAME, bad)])
        c.layout()
        self.assertEqual(stw(c, ST_N), 1)
        _h, rows = csv_records(c.csv(E.CSVS[0][1]))
        self.assertEqual([r[1:4] for r in rows[32:]], [['49', 'menu_crop', 'Good']])   # unknown icon: default
        self.assertEqual(stw(c, 44), 4)                              # st.bad

    def test_seventeen_functions_take_sixteen(self):
        many = QT.build(funcs=[(f'F{i}', f'Fn {i}', 'menu_crop') for i in range(16)])
        more = QT.build(funcs=[('Z', 'Extra', 'menu_crop')], sup_id='QSTZ')
        c = boot([(CNAME, cblob()[0]), (TNAME, many), ('ZMore_v0.1.0.BIN', more)])
        c.layout()
        self.assertEqual(stw(c, ST_N), 16)
        self.assertEqual(stw(c, 40), 1)                              # st.full
        self.assertEqual(c.to_int(64), 69)
        self.assertEqual(c.to_int(65), 70)                           # the QS page's first sub-item tile
        self.assertEqual(c.to_int(73), 0)

    def test_a_page_that_is_not_the_stock_bytes_is_not_edited(self):
        """The edit list carries the stock word at each place it changes: a page
        that differs (another firmware, someone's in-place edit) gets nothing,
        and then no function is offered at all."""
        _a, off, _n = E.O.resource_set('Y2_3C')
        pos = next(e[0] for e in E.page_edits('Y2_3C') if e[1] == E.K_SET_END)
        addr = _a + pos + 3                                          # 1600 -> 1600 ^ 0x40

        def poke(cam):
            v = cam.mu.mem_read(addr, 1)[0]
            cam.mu.mem_write(addr, bytes([v ^ 0x40]))
        c = std(prepare=poke)
        c.layout()
        self.assertEqual(st_word(c, 'freeze'), 3)
        self.assertEqual(stw(c, ST_N), 0)
        self.assertEqual(c.w(Cam.PAGE_ENTRIES + 8), off)
        self.assertEqual(c.to_int(49), 0)
        self.assertIsNone(c.csv(E.CSVS[0][1]))

    def test_zqs_on_the_card_stands_the_container_down(self):
        zqs = QT.build(funcs=[('T', 'Touch', None)], sup_id='QSN1')
        c = boot([(CNAME, cblob()[0]), (TNAME, tblob()), ('ZQS.BIN', zqs)])
        c.layout()
        self.assertEqual((st_word(c, 'phase'), st_word(c, 'freeze')), (3, 1))
        self.assertEqual(c.to_int(49), 0)
        self.assertEqual(c.w(Cam.PAGE_ENTRIES + 8), E.O.resource_set('Y2_3C')[1])
        _h, rows = csv_records(c.csv(E.CSVS[0][1]) or E.O.at(IMG, E.CSVS[0][1], E.CSVS[0][2]))
        self.assertEqual(len(rows), 32)

    def test_api_answers_the_ids(self):
        c = ready()
        api = c.callsvc('find', Q.B._id('QSCT') if hasattr(Q.B, '_id') else 0x54435351)
        self.assertEqual(c.w(api), 0x31415351)
        fn = c.w(api + 8)
        name = F6.FAKE + 0xB800
        c.mu.mem_write(name, b'B\0')
        self.assertEqual(c.call(fn & ~1, r0=api, r1=Q.B._id('QSTS'), r2=name, thumb=bool(fn & 1))[0], 50)
        c.mu.mem_write(name, b'Q\0')
        self.assertEqual(c.call(fn & ~1, r0=api, r1=Q.B._id('QSTS'), r2=name, thumb=bool(fn & 1))[0], 0xFFFFFFFF)


@SKIP
class CsvRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cam = ready()

    def test_every_cine_list_gets_our_rows_after_the_stock_ones(self):
        for name, addr, size in E.CSVS:
            data = self.cam.csv(addr)
            stock = E.O.at(IMG, addr, size)
            self.assertEqual(data[:len(stock)], stock, name)
            self.assertTrue(data.endswith(b'\r\n'), name)
            head, rows = csv_records(data)
            self.assertEqual(len(rows), 34, name)
            self.assertEqual(rows[32:], [['33', '49', 'menu_crop', 'QS Test A', 'S'],
                                         ['34', '50', 'menu_lock', 'QS Test B', 'S']])

    def test_the_label_is_literal_text_not_an_id(self):
        _h, rows = csv_records(self.cam.csv(E.CSVS[0][1]))
        self.assertFalse(rows[32][3].isdigit())


@SKIP
class EditorPages(unittest.TestCase):
    """E2-E5 and the freeze regression: a data check of the camera's page copies."""
    @classmethod
    def setUpClass(cls):
        cls.cam = ready()
        icons = ['menu_crop', 'menu_wb', 'menu_lock', 'menu_iso', 'menu_cine_fps', 'menu_headPhone']
        many = QT.build(funcs=[(f'F{i}', f'Fn {i}', icons[i % len(icons)]) for i in range(16)])
        cls.full = boot([(CNAME, cblob()[0]), (TNAME, many)])
        cls.full.layout()

    def labels(self, cam):
        """(string id, text) of each function's label copy: its uncached address."""
        base = cam.st() + 56
        return [(base + FN_BYTES * i + 16 - 0x80000000, cstr(cam, base + FN_BYTES * i + 16))
                for i in range(stw(cam, ST_N))]

    def check_page(self, cam, p):
        n = stw(cam, ST_N)
        a, data, hdr, off = cam.page_copy(p)
        self.assertNotEqual(off, E.O.resource_set(E.PAGES[p])[1])
        self.assertEqual(hdr[0], 0x47505346)                         # FSPG: uishare's convention copy
        _sa, _soff, stock = E.page_bytes(E.PAGES[p])
        self.assertEqual(hdr[4], len(stock))
        recs, _objs, ts = copy_tiles(data)
        srecs, _sobjs, sts = copy_tiles(stock)
        self.assertEqual([t for _o, t, _s in recs], [t for _o, t, _s in srecs])   # same records, in order
        self.assertEqual(recs[-1][1], 0xFFFFFFFF)
        _h, rows = csv_records(cam.csv(E.CSVS[E.PAGE_CSV[E.PAGES[p]]][1]))
        labels = self.labels(cam)
        icons = E.icon_table()
        for k, (tl, st) in enumerate(zip(ts, sts)):
            self.assertEqual(tl['upper'], 48.0 + n)
            self.assertEqual(tl['end'], E.t_of(48 + n))
            for i in range(n):
                ui = 49 + i
                got = page_build_state(tl, ui)
                row = next(j for j, r in enumerate(rows) if r[1] == str(ui))
                self.assertTrue(got['fired'], (k, ui))
                self.assertEqual(got['row'], float(row), (k, ui))
                self.assertEqual(got['text'], labels[i][0], (k, ui))
                self.assertEqual(cstr(cam, cam.call(RESOLVE, r0=F6.READER, r1=got['text'], thumb=True)[0]),
                                 rows[row][3])
                look = icons[rows[row][2]]
                self.assertEqual((got['image'], got['rect'], got['size'], got['pos']),
                                 (look[0], f32(look[1]), f32(look[2]), f32(look[3])), (k, ui))
            for ui in range(49):                                     # every stock id as before
                want = page_build_state(st, ui)
                self.assertEqual(page_build_state(tl, ui), want, (k, ui))
        return data, hdr, stock

    def test_both_pages_initialise_every_new_id(self):
        for p in range(2):
            self.check_page(self.cam, p)

    def test_sixteen_functions_incl_the_twin_overwrites(self):
        for p in range(2):
            self.check_page(self.full, p)

    def test_the_freeze_precondition_is_gone(self):
        """Slot 2 holding UI 49, the editor re-entered: on the stock page the tile
        keeps 'xxxx' and list row 90 (OK then focuses a list item that does not
        exist, camera 2026-10-28); on our copy it is our label and row 32."""
        _sa, _soff, stock = E.page_bytes('Y2_3C')
        _r, _o, sts = copy_tiles(stock)
        self.assertEqual(page_build_state(sts[1], 49), {'fired': False, 'text': 'xxxx', 'row': 90.0})
        _a, data, _hdr, _off = self.cam.page_copy(0)
        _r, _o, ts = copy_tiles(data)
        got = page_build_state(ts[1], 49)
        self.assertTrue(got['fired'])
        self.assertEqual(cstr(self.cam, self.cam.call(RESOLVE, r0=F6.READER, r1=got['text'], thumb=True)[0]),
                         'QS Test A')
        self.assertEqual(got['row'], 32.0)
        self.assertLess(got['row'], len(csv_records(self.cam.csv(E.CSVS[0][1]))[1]))

    def test_visible_maximum_and_total_count(self):
        for cam, n in ((self.cam, 2), (self.full, 16)):
            for p, page in enumerate(E.PAGES):
                _a, data, hdr, _off = cam.page_copy(p)
                vm = E.visible_max(page)
                ins = sum(nn for q, nn in self.deltas(cam, hdr) if q <= vm)
                self.assertEqual(struct.unpack_from('>f', data, vm + ins)[0], 31.0 + n)
                for (pos, _old), want in zip(E.total_digits(page), divmod(32 + n, 10)):
                    ins = sum(nn for q, nn in self.deltas(cam, hdr) if q <= pos)
                    self.assertEqual(E.pool_str(E.be(data, pos + ins)), f'font_menu_S_{want}')

    def deltas(self, cam, hdr):
        return [struct.unpack('<2I', bytes(cam.mu.mem_read(hdr[8] + 8 * i, 8))) for i in range(hdr[6])]

    def test_the_delta_table_maps_every_stock_byte(self):
        """uishare's FSPG rule: removing the inserted bytes gives the stock page
        back except at the words we edit -- so another sup's stock coordinates
        still land where they should."""
        for cam in (self.cam, self.full):
            for p, page in enumerate(E.PAGES):
                _a, data, hdr, _off = cam.page_copy(p)
                _sa, _soff, stock = E.page_bytes(page)
                back = bytearray()
                ds = sorted(self.deltas(cam, hdr))
                shift, prev = 0, 0
                for q, n in ds:
                    back += data[prev + shift:q + shift]
                    prev = q
                    shift += n
                back += data[prev + shift:]
                self.assertEqual(len(back), len(stock))
                edited = set()
                for pos, kind, _sel, fi, _a2, _b in E.page_edits(page):
                    if kind != E.K_INS:
                        edited.update(range(pos, pos + 4))
                diff = [i for i in range(len(stock)) if back[i] != stock[i] and i not in edited]
                self.assertEqual(diff, [])


@SKIP
class SaveSwap(unittest.TestCase):
    def flash_ids(self, flash):
        return [struct.unpack_from('<I', flash, ARR[a] + 4 * k)[0] for a in (0, 1) for k in range(8)]

    def record(self, c):
        data = c.written[CPATH]
        off = cblob()[1]['rec_off']
        return struct.unpack_from(f'<{REC_WORDS}I', data, off)

    def pick(self, c, k, ui):
        """The editor puts UI `ui` into CINE slot k: its conversion, then the setter."""
        internal = c.to_int(ui)
        c.set_slot(1, k, internal)
        return internal

    def test_flash_gets_the_slots_previous_stock_function(self):
        c = ready()
        c.set_slot(1, 1, 12)
        self.assertEqual(self.pick(c, 1, 49), 54)
        flash = c.save()
        ids = self.flash_ids(flash)
        self.assertEqual(ids[9], 12)                                 # not 0: what the slot held before
        self.assertFalse([v for v in ids if v >= 54])
        self.assertEqual(c.slot(1, 1), 54)                           # RAM put back
        rec = self.record(c)
        self.assertEqual(rec[0], 0x31435351)
        e = rec[2 + 5 * 9:2 + 5 * 10]
        self.assertEqual(e[0], Q.B._id('QSTS'))
        self.assertEqual(struct.pack('<3I', *e[1:4]).rstrip(b'\0'), b'A')
        self.assertEqual(e[4], 12)
        self.assertNotIn(CPATH, c.created)
        new = c.written[CPATH]
        self.assertEqual(new[:cblob()[1]['rec_off']], cblob()[0][:cblob()[1]['rec_off']])

    def test_every_id_from_54_is_cleaned_not_only_ours(self):
        c = ready()
        c.set_slot(1, 3, 70); c.set_slot(0, 2, 55)                  # nobody's / ours in the STILL set
        flash = c.save()
        ids = self.flash_ids(flash)
        self.assertFalse([v for v in ids if v >= 54], ids)
        self.assertEqual(ids[8 + 3], Q.DEFAULTS[8 + 3])              # no history: the stock default
        self.assertEqual(c.slot(1, 3), 70)

    def next_boot(self, c, flash, client=True, prepare=None, card=None):
        new_bin = card if card is not None else c.written[CPATH]

        def from_flash(cam):
            cam.mu.mem_write(STORE + IMG_A, flash)
            cam.mu.mem_write(STORE + SEL, b'\0')
            if prepare:
                prepare(cam)
        d = std(client=client, cfile=new_bin, prepare=from_flash)
        d.layout()
        return d

    def test_restored_next_boot_and_reposted(self):
        c = ready()
        c.set_slot(1, 1, 12); self.pick(c, 1, 50)
        c.set_slot(1, 6, 9); self.pick(c, 6, 49)
        d = self.next_boot(c, c.save())
        self.assertEqual((d.slot(1, 1), d.slot(1, 6)), (55, 54))
        posts = [(n, v) for n, v in d.posts if n.startswith('MV_QSMENU_QS')]
        self.assertIn(('MV_QSMENU_QS2', 50), posts)
        self.assertIn(('MV_QSMENU_QS7', 49), posts)
        self.assertEqual(counter(d, 'restored'), 2)

    def test_client_away_shows_the_placeholder_and_comes_back(self):
        c = ready()
        c.set_slot(1, 1, 12); self.pick(c, 1, 49)
        flash = c.save()
        card = c.written[CPATH]
        d = self.next_boot(c, flash, client=False)                   # SupManager disabled QSTest
        self.assertEqual(d.slot(1, 1), 12)
        self.assertEqual(counter(d, 'orphans'), 1)
        flash2 = d.save()                                            # the orphan survives a save
        self.assertEqual(self.flash_ids(flash2)[9], 12)
        self.assertEqual(d.written.get(CPATH, card), card)           # record unchanged, not rewritten
        e = self.next_boot(d, flash2, client=True, card=card)
        self.assertEqual(e.slot(1, 1), 54)                           # back automatically
        self.assertEqual(counter(e, 'restored'), 1)

    def test_a_slot_changed_while_away_is_not_overwritten(self):
        c = ready()
        c.set_slot(1, 1, 12); self.pick(c, 1, 49)
        flash = c.save()
        d = self.next_boot(c, flash, prepare=lambda cam: cam.put(STORE + IMG_A + ARR[1] + 4, 25))
        self.assertEqual(d.slot(1, 1), 25)
        self.assertEqual(counter(d, 'stale'), 1)
        self.assertEqual([n for n, v in d.posts if n.startswith('MV_QSMENU')], [])

    def test_a_damaged_record_restores_nothing(self):
        c = ready()
        c.set_slot(1, 1, 12); self.pick(c, 1, 49)
        flash = c.save()
        bad = bytearray(c.written[CPATH])
        ro = cblob()[1]['rec_off']
        e9 = bad[ro + 8 + 20 * 9:ro + 8 + 20 * 10]                  # slot CINE 2's entry ...
        e12 = bytearray(e9)
        struct.pack_into('<I', e12, 16, struct.unpack_from('<I', flash, ARR[1] + 16)[0])
        bad[ro + 8 + 20 * 12:ro + 8 + 20 * 13] = e12                 # ... copied to CINE 5 (its flash value): only the sum tells
        c.written[CPATH] = bytes(bad)
        d = self.next_boot(c, flash)
        self.assertEqual((d.slot(1, 1), d.slot(1, 4)), (12, struct.unpack_from('<I', flash, ARR[1] + 16)[0]))
        self.assertEqual(counter(d, 'restored'), 0)

    def test_record_written_only_when_it_changes(self):
        c = ready()
        c.set_slot(1, 2, 3); self.pick(c, 2, 49)
        c.save(); c.save()
        self.assertEqual(counter(c, 'writes'), 1)
        c.set_slot(1, 2, 21)
        c.save()
        self.assertEqual(counter(c, 'writes'), 2)
        self.assertEqual(self.record(c)[2 + 5 * 10], 0)

    def test_never_creates_or_writes_a_file_that_is_not_ours(self):
        c = ready()
        c.files[CPATH] = b'FSB4 something else entirely'.ljust(128, b'\0')
        c.set_slot(1, 2, 3); self.pick(c, 2, 49)
        flash = c.save()
        self.assertNotIn(CPATH, c.written)
        self.assertNotIn(CPATH, c.created)
        self.assertEqual(self.flash_ids(flash)[10], 3)
        del c.files[CPATH]
        c.save()
        self.assertNotIn(CPATH, c.created)

    def test_recording_defers_the_record_not_the_swap(self):
        c = ready()
        c.put(0xC35A952C, 1)
        c.set_slot(1, 2, 3); self.pick(c, 2, 49)
        flash = c.save()
        self.assertEqual(self.flash_ids(flash)[10], 3)
        self.assertNotIn(CPATH, c.written)
        self.assertEqual(counter(c, 'busy_skips'), 1)

    def test_no_record_written_before_collection(self):
        c = std()
        c.set_slot(1, 2, 3)
        c.save()
        self.assertNotIn(CPATH, c.written)

    def test_recommended_setting_reader_sees_the_placeholder(self):
        c = ready()
        c.set_slot(1, 4, 23); self.pick(c, 4, 50)
        c.set_slot(1, 5, 9)
        self.assertEqual(c.rec_read(4), 23)
        self.assertEqual(c.rec_read(5), 9)

    def test_only_one_call_site_feeds_the_flash_buffer(self):
        callers, readers = [], []
        for off in range(0, 0xB00000, 4):
            w = struct.unpack_from('<I', IMG, off)[0]
            if (w & 0x0E000000) == 0x0A000000 and (w >> 28) != 0xF:
                imm = w & 0xFFFFFF
                t = 0xC0000000 + off + 8 + ((imm - (1 << 24) if imm & 0x800000 else imm) << 2)
                if t == 0xC0088660:
                    callers.append(0xC0000000 + off)
                if t == 0xC0061B08 and 0xC053D000 <= 0xC0000000 + off < 0xC053F000:
                    readers.append(0xC0000000 + off)
        self.assertEqual(callers, [SAVE_SITE])
        self.assertEqual(readers, [REC_SITE])


@SKIP
class Headphone(unittest.TestCase):
    def test_dial_on_our_tile_does_not_set_the_volume(self):
        c = ready()
        self.assertEqual(c.hp(54), [])
        self.assertEqual(counter(c, 'hp_blocks'), 1)
        self.assertEqual(c.hp(53), [(SETTINGS, 7, 1)])               # the stock headphone tile
        self.assertEqual(c.hp(25), [(SETTINGS, 7, 1)])
        self.assertEqual(c.hp(56), [(SETTINGS, 7, 1)])               # not issued this boot

    def test_before_collection_the_setter_always_runs(self):
        c = std()
        self.assertEqual(c.hp(54), [(SETTINGS, 7, 1)])

    def test_the_callback_is_only_the_quick_set_guis(self):
        """FUN_c0582ab0 is built (movw/movt) only in UicGuiMenuQs v25 (subscribe,
        C05806B8..) and v26 (unsubscribe, C0580D48..); no literal holds it.  So the
        site runs only while the Quick Set GUI is up, where +0xBC is current."""
        self.assertEqual(IMG.find(struct.pack('<I', 0xC0582AB0)), -1)
        hits = []
        for off in range(0, 0xB00000, 4):
            w = struct.unpack_from('<I', IMG, off)[0]
            if w >> 28 == 0xE and w & 0x0FF00000 == 0x03000000 and ((w >> 4) & 0xF000 | w & 0xFFF) == 0x2AB0:
                rd = (w >> 12) & 0xF
                for k in range(1, 8):
                    m = struct.unpack_from('<I', IMG, off + 4 * k)[0]
                    if m >> 28 == 0xE and m & 0x0FF00000 == 0x03400000 and (m >> 12) & 0xF == rd:
                        if ((m >> 4) & 0xF000 | m & 0xFFF) == 0xC058:
                            hits.append(0xC0000000 + off)
                        break
        self.assertEqual(len(hits), 2, [hex(h) for h in hits])
        self.assertTrue(0xC05806B8 <= hits[0] < 0xC0580D48 <= hits[1] < 0xC0581400, [hex(h) for h in hits])
        self.assertEqual(struct.unpack_from('<I', IMG, HP_SITE - 0xC0000000)[0], HP_STOCK)


# ---- mutations: each must make at least one test fail ----------------------------
MUTANTS = [
    ('table not extended', 'qsct.c', 's->tab_n = n + s->n + extra(s);', 's->tab_n = n + extra(s);'),
    ('pairs swapped', 'qsct.c', 's->tab[2u * (n + j)] = INT_BASE + j;', 's->tab[2u * (n + j)] = UI_BASE + j;'),
    ('no collection at the layout load', 'qsct.c', 'if (s->phase == PH_ENTRY && !W(SL_SVC_AT)) qc_freeze(s);', ''),
    ('collected but the layout load not passed on', 'qsct.c', 'u32 r = ((fn1)s->next_lay)(layout);', 'u32 r = 0x77;'),
    ('stale table after collection', 'qsct.c', '&& s->tab_for == s->n && s->tab_extra == extra(s))', ')'),
    ('ZQS ignored', 'qsct.c', 'if (qc_zqs(s)) { s->freeze = F_ZQS; s->phase = PH_DOWN; return; }', ''),
    ('label checks skipped', 'qsct.c', '!(q->flags & QSC_F_CINE) || !label_ok(q->label) ||', '!(q->flags & QSC_F_CINE) ||'),
    ('no limit', 'qsct.c', 'if (s->offered == QSC_MAX) { s->full++; continue; }', 'if (s->offered == 64u) { s->full++; continue; }'),
    ('rows without a CRLF', 'qsct.c', "B8(p + n++) = '\\r'; B8(p + n++) = '\\n';", "B8(p + n++) = '\\n';"),
    ('csv rows not committed', 'qsct.c', '    if (n) qc_csv_commit(&rw);\n', '\n'),
    ('pages not switched', 'qsct.c', '    W(e + ENTRY_OFFSET) = out - NBU_BASE;\n', '\n'),
    ('inserted key at the wrong time', 'qsct.c', 'wr_be(out + o + 2u, c->t_of[x->fi]);', 'wr_be(out + o + 2u, c->t_of[x->fi] + 1u);'),
    ('list row off by one', 'qsct.c', 'fst_int_to_f32((int32_t)s->editor_row[csv][fi], &v);', 'fst_int_to_f32((int32_t)(s->editor_row[csv][fi] + 1u), &v);'),
    ('count/size not adjusted', 'qsct.c', 'wr_be(q, v + x->b * popcount(x->a & mask));', 'wr_be(q, v);'),
    ('delta table not merged', 'qsct.c', 'if (last_pos == x->pos) W(deltas + 8u * (nd - 1u) + 4u) += 10u;', 'if (0) {}'),
    ('guard ignored', 'qsct.c', 'if (x->kind != K_ADJ && v != x->a) return 5;', ''),
    ('save does not sanitise', 'qsct.c', 'W(image + arr(i)) = ph[i];', '(void)0;'),
    ('save does not put RAM back', 'qsct.c', '{ W(image + arr(i)) = was[i]; s->sanitized++; }', '{ s->sanitized++; }'),
    ('placeholder is the stock default', 'qsct.c', 'if (ours(s, v) && !foreign_id(s->last[i])) return s->last[i];', ''),
    ('only our ids cleaned', 'qsct.c', 'if (mine && foreign_id(was[i])) {', 'if (mine && ours(s, was[i])) {'),
    ('no snapshot before the setter', 'qsct.c', 'if (s->phase == PH_READY) qc_snapshot(s);', ''),
    ('record never written', 'qsct.c', 'u32 why = qc_write(s, rec);', 'u32 why = 0;'),
    ('orphans dropped', 'qsct.c', '                used |= 1u << i;\n            }\n        }\n    }', '            }\n        }\n    }'),
    ('restore ignores the placeholder check', 'qsct.c', 'if (v != s->rec_ph[i]) { s->stale++;', 'if (0) { s->stale++;'),
    ('record checksum not checked', 'qsct.c', ' || tmp[REC_SUM] != fnv_words(tmp, REC_SUM)) return;', ') return;'),
    ('file_is skipped', 'qsct.c', 'if (svc->file_is(svc, s->path, s->block, SL4_HEADER_LEN) != SL_OK) return 2;', ''),
    ('recording not deferred', 'qsct.c', 'if (busy()) { s->busy_skips++; return; }', ''),
    # equivalent, not listed: 'record written before collection' (before it the record
    # is not loaded and nothing is ours, so the computed record equals the empty one)
    ('QR reader not mapped', 'qsct.c', 'if (!foreign_id(v)) return v;\n    s->rec_hits++;', 'return v;\n    s->rec_hits++;'),
    ('headphone guard off', 'qsct.c', '{ s->hp_blocks++; return 0; }', '{ s->hp_blocks++; }'),
    ('no re-post after restore', 'qsct.c', '((fn3)POST_INT)(0, QS_NAME0 + 0x10u * k, qc_slot_ui(s, k));', '(void)k;'),
    ('builder: no total digits', 'env', 'QSCT_MUTATE', 'nodigits'),
    ('builder: no interval end', 'env', 'QSCT_MUTATE', 'noend'),
    ('builder: no range / Visible maximum', 'env', 'QSCT_MUTATE', 'norange'),
    ('builder: twin keys keep their flag', 'env', 'QSCT_MUTATE', 'stepflag'),
]


def mutate():
    src = (HERE / 'qsct.c').read_text()
    survived = []
    only = [a for a in sys.argv[1:] if a != '--mutate' and not a.startswith('--part=')]
    part = [a for a in sys.argv[1:] if a.startswith('--part=')]      # k/n: mutant i runs when i % n == k
    k_part, n_part = (int(x) for x in part[0][7:].split('/')) if part else (0, 1)
    for i_m, (label, where, old, new) in enumerate(MUTANTS):
        if (only and not any(o in label for o in only)) or i_m % n_part != k_part:
            continue
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        if env.get('SL_TESTCACHE', '1') != '0':
            env['SL_TESTCACHE'] = 'ro'              # a mutant's build is a one-off: read the cache, never write it
        with tempfile.TemporaryDirectory(prefix='qsct-mut-') as t:
            env['PYTHONPYCACHEPREFIX'] = t              # an empty bytecode cache: no stale .pyc
            if where == 'qsct.c':
                if src.count(old) != 1:
                    print(f'  BAD MUTANT (pattern x{src.count(old)}): {label}')
                    survived.append(label)
                    continue
                p = pathlib.Path(t) / 'qsct.c'
                p.write_text(src.replace(old, new))
                env['QSCT_SRC'] = str(p)
            else:
                env[old] = new
            r = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-q', *(['-f'] if os.environ.get('SL_MUT_FAILFAST') else []), 'test_qsct'], cwd=HERE,
                               env=env, capture_output=True, text=True)
        failed = r.returncode != 0 and ('FAILED' in r.stderr or 'Error' in r.stderr)
        print(f'  {"caught " if failed else "SURVIVED"}  {label}', flush=True)
        if not failed:
            survived.append(label)
    n = len([m for i_m, m in enumerate(MUTANTS) if i_m % n_part == k_part])
    print(f'{n - len(survived)}/{n} mutants caught' if not only else f'{len(survived)} survived')
    return 1 if survived else 0


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        sys.exit(mutate())
    unittest.main()
