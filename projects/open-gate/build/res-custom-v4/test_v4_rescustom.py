"""res-custom as a Loader v4 sup (build_v4_rescustom.py), loaded by the real v4 core.

    cd projects/open-gate/build/res-custom-v4 && python3 -B -m unittest test_v4_rescustom

Every test of test_v3_rescustom runs again on the v4 build under the v4 core
(RESCUS.BIN, the record at 48): the data files, S byte for byte, the claims,
the hooks and shims, the pick / commit / live paths, the Quick Set records,
the virtual rates' menu, the record written back into its own file, power-off.
As in v3, S.UIA_FN is answered by the test (the image's RAM has no GUI): here
that is ogc_uia, the call into fpsup-ui's fpui_stock_apply.

Added for v4: the header, the display name and S's zeroed body; no string site
claimed; the block runs at the cached alias; the firmware's file object and
the .RCD read reach the firmware at the uncached alias with the D-cache cleaned
around them.

Emulated, not on the camera.
"""
import pathlib
import struct
import subprocess
import sys
import tempfile
import json
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'fpSup' / 'loader-v4'))

import test_v3_rescustom as V3R                           # noqa: E402
import build_v4 as B4                                     # noqa: E402
import test_v4 as T4                                      # noqa: E402
import names_v4                                           # noqa: E402

L, T = V3R.L, V3R.T
NAME = names_v4.file_name('RCUS')                         # RES-Custom_v0.1.5.BIN
LINE, ALIAS = 64, 0x80000000
STRING_SITES = (0xC05E5B58, 0xC05E61C8, 0xC05E61E0)
CODE_NAMES = {T4.CODES['LOADED']: 'LOADED', T4.CODES['RELEASED']: 'RELEASED',
              T4.CODES['REPAIRED']: 'REPAIRED', T4.CODES['CONFLICT']: 'CONFLICT'}
_BUILT = {}


def built4():
    if 'b' not in _BUILT:
        out = pathlib.Path(tempfile.mkdtemp(prefix='ogc4t-')) / 'o'
        r = subprocess.run([sys.executable, '-B', str(HERE / 'build_v4_rescustom.py'), '--out', str(out)],
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr[-4000:])
        meta = json.loads((out / 'build.json').read_text())['files']
        _BUILT['b'] = {n: ((out / n).read_bytes(), m['facts']) for n, m in meta.items()}
    return _BUILT['b']


def asize(block):
    return ((block + LINE - 1) & ~(LINE - 1)) + 2 * LINE       # sloader4.c load_one


class Cam4(V3R.Cam, T4.Camera):
    """test_v3_rescustom's camera on v4's: the core is the 64-aligned line in its
    allocation, run at the cached alias; S.UIA_FN (ogc_uia) is the stub."""
    def __init__(self, files, dirs, core_facts, **kw):
        files.setdefault('\\fpSup\\LOAD.LOG', b'')
        self.dcache_calls, self.io = 0, []
        super().__init__(files, dirs, core_facts, **kw)

    def _alloc(self, n, align=8):
        p = T4.Camera._alloc(self, n, align)
        if n == asize(self.cf['block']) and self.core_block is None:
            self.core_block = ((p + LINE - 1) & ~(LINE - 1)) + ALIAS
            uia = self.core_block + (self.cf['uia_apply_off'] & ~1)
            self.by_addr[uia] = 'UIA'
            self.pending.append((uia, struct.pack('<H', 0x4770)))      # bx lr (Thumb)
        return p

    def _hook(self, mu, addr, size, data):
        name = self.by_addr.get(addr)
        if name == 'DCACHE':
            self.dcache_calls += 1
            if self.io and self.io[-1][3] is None:
                self.io[-1][3] = self.dcache_calls
        if name in ('F_READ', 'F_WRITE'):
            # (call, file object, buffer, the first D-cache clean after it)
            self.io.append([name, self.r(V3R.UC_ARM_REG_R0), self.r(V3R.UC_ARM_REG_R1), None,
                            self.dcache_calls])
        return super()._hook(mu, addr, size, data)

    def log(self):
        return [(CODE_NAMES.get(c, c), a, b, t) for c, a, b, t in self.loadlog()]


class CoreV4Tests(V3R.CoreTests):
    NAME, HL = NAME, B4.SL4_HEADER_LEN

    @classmethod
    def setUpClass(cls):
        b = built4()
        cls._v3_built = V3R._BUILT.get('b')
        V3R._BUILT['b'] = b                     # the v3 suite's built() is this build now
        try:
            super().setUpClass()
        finally:
            cls._restore_v3()

    @classmethod
    def _restore_v3(cls):                       # the v3 suite keeps its own build
        if cls._v3_built is None:
            V3R._BUILT.pop('b', None)
        else:
            V3R._BUILT['b'] = cls._v3_built

    def boot(self, rcds='default', fmt=V3R.CINEMADNG, res=2, record=None, core_name=None,
             stale=None, order=None, extra=(), **kw):
        core_name = core_name or self.NAME
        core = self.core_with(record) if record else self.core
        rcds = self.rcds if rcds == 'default' else rcds
        cardfiles, dirs = V3R.rcd_card(core_name, core, rcds, order, extra)
        cardfiles['\\fpSup\\LOADER.BIN'] = B4.loader_bin()[0] if 'v' not in _BUILT else _BUILT['v']
        _BUILT['v'] = cardfiles['\\fpSup\\LOADER.BIN']
        dirs['\\fpSup'] = [(n, a, len(cardfiles['\\fpSup\\' + n]) if a == 0x20 else s)
                           for n, a, s in dirs['\\fpSup']]
        st = dict(stale or {})
        st.setdefault(V3R.OGSAVE, 0x5A5A5A5A)
        cam = Cam4(cardfiles, dirs, self.f, fmt=fmt, res=res, stale=st, **kw)
        cam.boot()
        self.assertIsNone(cam.error)
        self.assertEqual(cam.misaligned, [])
        self.assertEqual(cam.w(V3R.OGSAVE), 0x5A5A5A5A, 'OGSAVE untouched')
        cam.S = self.s_addr(cam, core_name)
        cam.core_path = '\\fpSup\\' + core_name
        return cam

    # ---- what v4 changed ----------------------------------------------------
    def test_v4_header_name_and_zeroed_state(self):
        h = struct.unpack_from('<12I', self.core)
        self.assertEqual((h[0], h[1], h[2], h[7], h[8]),
                         (B4.SL4_MAGIC, 48, len(self.core), 6, B4.SL_F_CACHED_OK))
        self.assertEqual(self.core[h[11]:h[11] + 11], b'RES-Custom\0')
        self.assertLess(h[11], self.f['img_off'])
        self.assertTrue(all(b == 0 for b in self.core[48:48 + L.CFG['BYTES']]))
        self.assertEqual(h[3], self.f['block'] + (-self.f['block'] % 64))

    def test_v4_claims_no_string_site(self):
        claimed = {int(c['address'], 16): c['kind'] for c in self.f['claims']}
        for a in STRING_SITES:
            self.assertNotIn(a, claimed)
        self.assertEqual(claimed.get(0xC05E5BEC), 3)       # the file-redirect site, SHARED_UI

    def test_v4_runs_at_the_cached_alias(self):
        cam = self.boot()
        self.assertEqual(self.outcome(cam, NAME), 'LOADED')
        at = T4.blocks(cam)[NAME]
        self.assertEqual(at, cam.core_block)
        self.assertTrue(at >= 0xC0000000 and at % 64 == 0, hex(at))
        self.assertTrue(at < cam.S < at + self.f['block'])
        self.assertEqual(self.S(cam, L.S['CFG']), at + 48)
        fo = self.S(cam, L.S['FOBJ'])
        self.assertEqual(fo, at + self.f['fobj_off'] - ALIAS)       # the file object: uncached
        self.assertTrue(at <= self.S(cam, L.S['DATA']) < at + self.f['block'])

    def test_v4_firmware_file_io_is_uncached_and_cache_maintained(self):
        cam = self.boot()
        mine = lambda a: cam.core_block - ALIAS <= a < cam.core_block - ALIAS + self.f['block']   # noqa: E731
        reads = [x for x in cam.io if x[0] == 'F_READ' and mine(x[1]) and mine(x[2])]   # not the loader's
        self.assertEqual(len(reads), 2, cam.io)                    # OG2K.RCD, OG3K.RCD
        for x in reads:
            name, fo, buf, after, before = x
            prev = cam.io[cam.io.index(x) - 1]
            self.assertGreater(before, prev[3] if prev[3] is not None else prev[4],
                               'cleaned again before this read')
            self.assertIsNotNone(after)                             # and after it
        self.live(cam, 4)
        cam.io, n = [], cam.dcache_calls
        self.save(cam)
        writes = [x for x in cam.io if x[0] == 'F_WRITE']
        self.assertEqual(len(writes), 1, cam.io)
        _, fo, buf, _, before = writes[0]
        self.assertTrue(mine(fo), hex(fo))
        self.assertEqual(buf, self.S(cam, L.S['CFG']) - ALIAS)       # the record, uncached
        self.assertGreater(before, n)                                # in RAM before the write



# ---- the real fpsup-ui (fpui_stock.c, fpsup_ui.c) against test_ui_v4's fake GUI ----
import test_ui_v4 as U                                   # noqa: E402
F6 = U.F6
B25_OFF = 0x19C130                                       # B2_5's runtime page offset (stock)
UI_RAM = F6.FAKE + 0xA000                                # our screen entry names
DESC_V4 = 0xC3F70000                                     # V3R.DESC sits on F6's fake app


class UiCam(V3R.Cam, U.Cam):
    """test_v3_rescustom's camera (descriptor, firmware stubs) over test_ui_v4's
    (the v4 core's fake GUI: variables, subscriptions, NBR loads, `gui scr set`),
    with B2_5 in the reader's runtime entries.  Nothing stubs S.UIA_FN: the
    core's menu blocks go through fpui_stock_apply for real."""
    def __init__(self, files, dirs, core_facts):
        files.setdefault('\\fpSup\\LOAD.LOG', b'')
        old, V3R.DESC = V3R.DESC, DESC_V4
        try:
            super().__init__(files, dirs, core_facts)
        finally:
            V3R.DESC = old
        names, entries = UI_RAM, UI_RAM + 0x100
        self.mu.mem_write(names, b'B2_5\0')
        self.put(entries + 4, names)
        self.put(entries + 8, B25_OFF)
        self.put(F6.READER + 0xA8, 1)
        self.put(F6.READER + 0xAC, entries)
        self.b25_entry = entries
        self.packs = []

    def _alloc(self, n, align=8):
        p = T4.Camera._alloc(self, n, align)
        if n == asize(self.cf['block']) and self.core_block is None:
            self.core_block = ((p + LINE - 1) & ~(LINE - 1)) + ALIAS
        return p

    def _hook(self, mu, addr, size, data):
        if addr == F6.NBR_LOAD:
            self.packs.append(bytes(mu.mem_read(self.r(V3R.UC_ARM_REG_R1), self.r(V3R.UC_ARM_REG_R2))))
        return super()._hook(mu, addr, size, data)


@unittest.skipIf(T.Uc is None or not T.IMAGE.exists(), 'needs unicorn and the image')
class UiV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        b = built4()
        cls.core, cls.f = b[NAME]
        cls.rcds = {n.split('/')[1]: d for n, (d, _) in b.items()
                    if n.startswith('RESCUS/') and n.split('/')[1] in ('OG2K.RCD', 'OG3K.RCD')}

    def boot(self, rcds=None, record=None):
        u = U.built()
        core = self.core[:48] + record + self.core[48 + len(record):] if record else self.core
        files, dirs = V3R.rcd_card(NAME, core, self.rcds if rcds is None else rcds)
        files['\\fpSup\\LOADER.BIN'] = u['vbin']
        files[U.UI_PATH] = u['data']
        dirs['\\fpSup'] = [(n, a, len(files['\\fpSup\\' + n]) if a == 0x20 else sz)
                           for n, a, sz in dirs['\\fpSup']] + [('UI', 0x10, 0)]
        cam = UiCam(files, dirs, self.f)
        cam.boot()
        self.assertIsNone(cam.error)
        self.assertEqual(cam.misaligned, [])
        return cam

    def S(self, cam):
        return cam.core_block + self.f['img_off'] + (L.S_COORD - L.LAYOUT0)

    def log(self, cam):
        return [(CODE_NAMES.get(c, c), a, b, t) for c, a, b, t in cam.loadlog()]

    def test_loads_with_the_real_appliers(self):
        cam = self.boot()
        log = self.log(cam)
        self.assertIn(('LOADED', cam.core_block), [(c, a) for c, a, _, t in log if t == NAME], log)
        S = self.S(cam)
        self.assertEqual(cam.w(S + L.S['UI_OK']), 0b11, 'both rows went in')
        self.assertEqual(cam.w(S + L.S['BIT_UI']), 1)
        self.assertEqual(cam.w(S + L.S['VR_WHY']), 1, 'the virtual rates went in')

    def test_b2_5_is_our_cached_copy_and_the_row_texts_resolve(self):
        cam = self.boot()
        S = self.S(cam)
        page = (0xC18C0460 + cam.w(cam.b25_entry + 8)) & 0xFFFFFFFF   # NBU base + the entry's offset
        # the last row's copy (each applier copies what is there): FSPG, at the cached alias
        self.assertGreaterEqual(page, T4.HEAP + ALIAS, hex(page))
        self.assertEqual(cam.w((page & ~3) - 128), 0x47505346)
        self.assertEqual(cam.w((page & ~3) - 128 + 16), 0x1CD6B)       # B2_5's stock length
        for r, label in enumerate(('OG2K', 'OG3K')):
            row = S + cam.w(S + L.S['ROWS']) + L.ROW['SIZE'] * r
            self.assertEqual(cam.w(row + L.ROW['ON']), 1)
            self.assertGreaterEqual(cam.w(row + L.ROW['MROW']), 2)
            for i, suffix in enumerate(('QS', 'SET', 'FONT')):
                sid = cam.w(row + L.ROW['QSID'] + 4 * i)
                self.assertTrue(0x40000000 <= sid < 0x80000000, hex(sid))
                got, _ = cam.call(0xC05E5B58, r0=0, r1=sid, thumb=True)   # the core resolves it
                self.assertEqual(cam.cstr(got), f'{label}_{suffix}')
                own, _ = cam.call(0xC05E61C8, r0=F6.READER, r1=got, thumb=True)
                self.assertEqual(own, 1, 'borrowed: the firmware never frees it')

    def test_the_resolution_list_has_our_rows(self):
        cam = self.boot()
        w = cam.w(0xC05E5BEC)
        self.assertNotEqual(w, struct.unpack_from('<I', cam.img, 0x5E5BEC)[0])   # hooked
        texts = ''
        # the shared file-redirect table (FSFV): RES_CSV's copy
        heap = bytes(cam.mu.mem_read(T.HEAP, T.HEAP_SIZE))
        at = heap.find(struct.pack('<2I', 0x56465346, 1))          # "FSFV", version 1
        self.assertGreaterEqual(at, 0)
        table = T.HEAP + at
        for i in range(cam.w(table + 8)):
            stock, copy, size = (cam.w(table + 16 + 12 * i + 4 * k) for k in range(3))
            if stock == 0xC0F8E7EC:
                texts = bytes(cam.mu.mem_read(copy, size)).decode()
        self.assertIn('OG2K 2000x1334', texts)
        self.assertIn('OG3K 3008x2000', texts)

    def test_the_file_list_is_a_jump_row_and_its_page(self):
        cam = self.boot()
        rc = {n for n in cam.vars if n.startswith('RC_')}
        import rc_files_page as RF
        self.assertEqual(rc, {n for _t, n, _v in RF.v4_vars()})            # v4 SupManager's, RC_
        subs = {n for _o, n, _f in cam.subs}
        self.assertTrue({'RC_Key', 'RC_Focus'} | {f'RC_Choice{k}' for k in range(6)} <= subs)
        self.assertTrue(any(RF.V4_MACHINE.encode() in p for p in cam.packs))   # its pack went in
        slots = [U.slot(cam, k) for k in range(6)]
        k = next(i for i, s in enumerate(slots) if s['N'] == 'RES-Custom')
        self.assertEqual(slots[k]['Jump'], 1)
        cam.press(41 + k)
        # the firmware's transition (fpui_open): the fpSup page's request names the page
        self.assertEqual((cam.shown, U.go_text(cam), cam.vars['FT_Go'][1]), ([], RF.V4_PAGE, 1))
        # two files: no paging -- slots 0.., no title row, no tabs, focus on slot 0
        v = lambda n: cam.vars[n][1]                                       # noqa: E731
        # the right column is the page's stock On / Off (user 2026-10-24), no Enabled
        self.assertEqual((v('RC_N0'), v('RC_E0'), v('RC_TOn0'), v('RC_N1'), v('RC_TOn1'), v('RC_TOff1')),
                         ('OG2K (2000x1334)', ' ', 1, 'OG3K (3008x2000)', 1, 0))   # the resolution-list names
        self.assertEqual([v(f'RC_Visible{k}') for k in range(4)], [1, 1, 0, 0])
        self.assertEqual([v(f'RC_Lock{k}') for k in range(3)], [0, 0, 1])
        self.assertEqual(v('RC_Title'), 0)
        self.assertEqual([v(f'RC_TabVisible{k}') for k in range(1, 8)], [0] * 7)
        self.assertNotEqual(v('RC_Row0'), 0)
        self.assertEqual(v('RC_Focus'), v('RC_Row0'))
        self.assertEqual(v('RC_Header'), 'RES-CUSTOM (2/6)')
        self.assertEqual(v('RC_PageText'), ' ')
        self.assertEqual(cam.page_id(RF.V4_PAGE), 21)

    def test_disabling_a_file_writes_the_record_at_48(self):
        cam = self.boot()
        slots = [U.slot(cam, k) for k in range(6)]
        k = next(i for i, s in enumerate(slots) if s['N'] == 'RES-Custom')
        cam.press(41 + k)
        cam.notify('RC_Choice1', 1)                              # slot 1 = OG3K.RCD: Disable
        rec = cam.written['\\fpSup\\' + NAME][48:48 + L.CFG['BYTES']]
        self.assertEqual(struct.unpack_from('<I', rec, L.CFG['MAGIC'])[0], L.CFG_MAGIC)
        self.assertEqual(struct.unpack_from('<I', rec, L.CFG['NEN'])[0], 1)
        self.assertEqual(rec[L.CFG['EN']:L.CFG['EN'] + 4], b'OG2K')
        self.assertEqual(cam.written['\\fpSup\\' + NAME][:48], self.core[:48])
        # loaded this boot, off next: SupManager's note on the row (user 2026-10-24), no footer note
        self.assertEqual((cam.vars['RC_G1'][1], cam.vars['RC_R1'][1], cam.vars['RC_TOff1'][1], cam.vars['RC_TOn1'][1]),
                         ('OG3K (3008x2000)', 'Unload on restart', 1, 0))
        self.assertEqual(cam.vars['RC_Header'][1], 'RES-CUSTOM (1/6)')
        self.assertNotIn('Restart', cam.vars['RC_OK'][1])
        self.assertEqual(cam.vars['RC_RightFooter'][1], ' ')
        self.assertEqual(cam.vars['RC_Version'][1], ' ')                # no 5/6 bottom right: the title has it
        self.assertEqual((cam.vars['RC_RShow1'][1], cam.vars['RC_GShow1'][1], cam.vars['RC_RShow0'][1]), (1, 1, 0))
        cam.notify('RC_Choice1', 0)                              # back on: nothing owed
        self.assertEqual((cam.vars['RC_R1'][1], cam.vars['RC_TOn1'][1]), (' ', 1))


    def test_every_file_disabled_keeps_only_the_row(self):
        rec = V3R.CoreTests.record(self, '', 0, enable=('VRC000',))   # the explicit empty list
        cam = self.boot(record=rec)
        self.assertIn(NAME, T4.blocks(cam))                     # kept: the list must stay reachable
        self.assertEqual(cam.w(0xC043CCF8), struct.unpack_from('<I', cam.img, 0x43CCF8)[0],
                         'no format: the picker is stock')
        slots = [U.slot(cam, k) for k in range(6)]
        k = next(i for i, s in enumerate(slots) if s['N'] == 'RES-Custom')
        cam.press(41 + k)
        self.assertEqual((cam.shown, U.go_text(cam)), ([], 'FT_RCFILES'))
        self.assertEqual((cam.vars['RC_G0'][1], cam.vars['RC_R0'][1], cam.vars['RC_TOff0'][1]), ('OG2K (2000x1334)', ' ', 1))
        self.assertEqual(cam.vars['RC_Header'][1], 'RES-CUSTOM (0/6)')
        cam.notify('RC_Choice0', 0)                              # not loaded this boot, on next
        self.assertEqual((cam.vars['RC_R0'][1], cam.vars['RC_TOn0'][1]), ('Load on restart', 1))


    def test_seven_files_page(self):
        img = T.IMAGE.read_bytes()
        stock = {struct.unpack_from('<I', img, 0xB59500 + 0x20 * i)[0] for i in range(70)}
        src = self.rcds['OG2K.RCD']
        d = V3R.rcd.decode(src, img, stock)
        off, ln = d['pack']
        many = {}
        for i in range(8):                       # eight files: 1 + 7 = two pages
            d.update(label=f'F{i}', row_text=f'F{i} 2000x1334')
            many[f'F{i}.RCD'] = V3R.rcd.encode(d, src[off:off + ln])
        cam = self.boot(rcds=many)
        slots = [U.slot(cam, k) for k in range(6)]
        k = next(i for i, s in enumerate(slots) if s['N'] == 'RES-Custom')
        cam.press(41 + k)
        v = lambda n: cam.vars[n][1]                                       # noqa: E731
        self.assertEqual(cam.w(self.S(cam) + L.S['NAVAIL']), 8)
        self.assertEqual(v('RC_Title'), 1)
        self.assertEqual(v('RC_PageText'), '1 / 2')
        self.assertEqual(v('RC_Visible0'), 0)
        self.assertEqual(v('RC_Focus'), 3451)                              # paged: the title row
        self.assertEqual([v(f'RC_TabWidth{k}') for k in (1, 2)], [512, 512])
        self.assertEqual([v(f'RC_N{k}') for k in range(1, 6)], [f'F{i} (2000x1334)' for i in range(5)])
        cam.notify('RC_Key', 11)
        self.assertEqual(v('RC_PageText'), '2 / 2')
        # the first six are enabled (no list yet), F6 / F7 grey
        self.assertEqual([(v(f'RC_N{k}'), v(f'RC_G{k}')) for k in range(1, 4)],
                         [('F5 (2000x1334)', ' '), (' ', 'F6 (2000x1334)'), (' ', 'F7 (2000x1334)')])
        self.assertEqual([(v(f'RC_TOn{k}'), v(f'RC_TOff{k}')) for k in range(1, 4)], [(1, 0), (0, 1), (0, 1)])
        self.assertEqual([v(f'RC_Lock{k}') for k in range(1, 6)], [0, 0, 0, 1, 1])

    def test_moving_the_cursor_posts_nothing_unchanged(self):
        """Each post is another GUI update pass (user 2026-10-24: the cursor lagged
        on the v4 pages): a focus move within the rows posts nothing."""
        cam = self.boot()
        slots = [U.slot(cam, k) for k in range(6)]
        cam.press(41 + next(i for i, s in enumerate(slots) if s['N'] == 'RES-Custom'))
        cam.notify('RC_Focus', 33333)
        n = len(cam.posts)
        for focus in (33334, 33335, 33333):
            cam.notify('RC_Focus', focus)
        self.assertEqual(cam.posts[n:], [])
        cam.notify('RC_Focus', 55)
        self.assertIn(('RC_HeadOn', 1), cam.posts[n:])



if __name__ == '__main__':
    unittest.main()
