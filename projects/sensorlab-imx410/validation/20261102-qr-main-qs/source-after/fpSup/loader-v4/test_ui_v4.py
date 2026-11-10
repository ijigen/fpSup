#!/usr/bin/env python3
"""Loader v4's UI (fpsup_ui.c) under unicorn: the real core built with
ui=True, the real \\fpSup\\UI\\FPSUP.BIN (uishare/tab/build_fp4.py), real sups
(test_sup4.c, SUPMGR); the UI app is v3 test_ft6's fake (NBR loader, the
variable registry, subscriptions and the GUI's post queue are Python);
uishare's string layer and the FT_ page-id layer run for real.

    cd fpSup/loader-v4 && python3 -B -m unittest test_ui_v4
"""
import pathlib, struct, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent
TAB = HERE.parent / 'uishare' / 'tab'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TAB))
import test_ft6 as F6                                          # noqa: E402 (fake UI app)
import build_fp4 as FP4                                        # noqa: E402
import test_v4 as T                                            # noqa: E402
import build_v4 as B                                           # noqa: E402

UI_PATH = '\\fpSup\\UI\\' + B.UI_FILE
SM_PATH = '\\fpSup\\UI\\SUPMGR.BIN'
SCREENS = 0xC054DD38                     # fpsup_ui.c SCREENS: the screen manager getter
MGR = F6.FAKE + 0x7A00                   # a fake manager: vt at +0, vt+0x48 = SHOW
SHOW = F6.FAKE + 0x7C00
L_UI = 0x32
TOGGLE, JUMP, ACTION = 2, 1, 4
_cache = {}


def built():
    if not _cache:
        _cache['vbin'] = B.loader_bin(ui=True)[0]
        _cache['data'], _cache['info'] = FP4.home_file()
        _cache['smdata'], _ = FP4.supmgr_file()
        _cache['smgr'] = B.supmgr_sup()
    return _cache


class Cam(F6.Cam, T.Camera):
    """v3's fake UI app over the v4 test camera (heap at both aliases), and
    the screen manager's `gui scr set` (shown: the page names asked for)."""
    def __init__(self, files, dirs):
        super().__init__(files, dirs)
        self.shown = []
        self.machine_names = []
        self.mu.mem_write(SCREENS, struct.pack('<I', 0xE12FFF1E))
        self.mu.mem_write(SHOW, struct.pack('<I', 0xE12FFF1E))
        self.put(MGR, MGR + 0x100)
        self.put(MGR + 0x100 + 0x48, SHOW)

    def _hook(self, mu, addr, size, data):
        if addr == F6.NBR_LOAD and not bytes(mu.mem_read(self.r(T.T3.UC_ARM_REG_R1), 12)).startswith(F6.F.NBR.MAGIC):
            # each page pack brings its own machine: named after what the pack holds
            # (SupManager installs at its entry, before the fpSup page)
            n = len(self.machine_names)
            pack = bytes(mu.mem_read(self.r(T.T3.UC_ARM_REG_R1), self.r(T.T3.UC_ARM_REG_R2)))
            name = FP4.SUPMGR_MACHINE if FP4.SUPMGR_MACHINE.encode() in pack else FP4.HOME_MACHINE
            self.machine_names.append(name)
            m = F6.FAKE + 0x9000 + 0x40 * n
            mu.mem_write(F6.FAKE + 0x9800 + 0x20 * n, name.encode() + b'\0')
            self.put(m + 8, F6.FAKE + 0x9800 + 0x20 * n)
            self.new_machine = m
        if addr == SCREENS:
            return self._ret(MGR)
        if addr == SHOW:
            self.shown.append((self.r(T.T3.UC_ARM_REG_R0), self.cstr(self.r(T.T3.UC_ARM_REG_R1))))
            return self._ret(0)
        return super()._hook(mu, addr, size, data)


def boot(*sups, data=True, vbin=None, smdata=True):
    b = built()
    vbin = vbin or b['vbin']
    files = {'\\fpSup\\LOADER.BIN': vbin}
    ents = [('LOADER.BIN', 0x20, len(vbin)), ('UI', 0x10, 0)]
    if data:
        files[UI_PATH] = data if isinstance(data, bytes) else b['data']
    if smdata:
        files[SM_PATH] = b['smdata']
    for name, blob in sups:
        files['\\fpSup\\' + name] = blob
        ents.append((name, 0x20, len(blob)))
    cam = Cam(files, {'\\fpSup': ents})
    cam.boot()
    return cam


def ts(sup_id, rows):
    return B.test_sup(T.cfg(rows=rows), sup_id)


def ui_lines(cam):
    return [(a, b, t) for c, a, b, t in cam.loadlog() if c == L_UI]


def slot(cam, k):
    v = cam.vars
    return {g: v[FP4.slot_var(g, k)][1] for g in FP4.GROUPS}


def go_text(cam):
    """fpsup_home.c T_GO: the JUMP rows' request text, in the FPSUP.BIN the core read."""
    data = built()['data']
    texts_off, n_texts = struct.unpack_from('<2I', data, 4 * 11)            # fpui_file texts_off, n_texts
    assert n_texts == len(FP4.HOME_TEXTS) and FP4.HOME_TEXTS[-1] == FP4.GO_TEXT
    off = struct.unpack_from('<I', data, texts_off + 4 * (n_texts - 1))[0]
    heap = bytes(cam.mu.mem_read(T.HEAP, T.HEAP_SIZE))
    at = heap.find(data[:64])
    assert at >= 0
    return heap[at + off:at + off + len(FP4.GO_TEXT) + 1].split(b'\0')[0].decode()


def shown(s):
    """What a slot's value column shows: a TOGGLE's stock Off / On object (its
    text variable blank), or the text."""
    if s['Tog']:
        assert s['A'] == ' ' and s['TOff'] + s['TOn'] == 1, s
        return 'On' if s['TOn'] else 'Off'
    assert not (s['TOff'] or s['TOn']), s
    return s['A']


@unittest.skipIf(T.Uc is None or not T.T3.IMAGE.exists(), 'needs unicorn and the image')
class HomePageTests(unittest.TestCase):
    def test_installs_after_the_sups(self):
        cam = boot(('A.BIN', ts('AAAA', [(TOGGLE, 'Flip')])))
        # the hooks before any sup, the fpSup page after them all
        self.assertEqual(ui_lines(cam), [(0, 0, 'LOADER.BIN'), (0x100, 1, 'LOADER.BIN')])
        log = [(c, a) for c, a, *_ in cam.loadlog()]
        loaded = log.index(next(e for e in log if e[0] == T.CODES['LOADED']))
        self.assertLess(log.index((L_UI, 0)), loaded)
        self.assertLess(loaded, log.index((L_UI, 0x100)))
        self.assertEqual(set(cam.vars), {n for _t, n, _v in FP4.home_file_vars()})
        self.assertEqual(cam.page_id('FT_Y6'), 21)
        subs = {n for _o, n, _f in cam.subs}
        self.assertEqual(subs, {'FT_Key', 'FT_Focus', 'FT_Go'} | {f'FT_Choice{k}' for k in range(6)})
        self.assertEqual(cam.machines()[0], FP4.HOME_MACHINE)

    def test_first_values_show_the_rows(self):
        cam = boot(('A.BIN', ts('AAAA', [(TOGGLE, 'Flip'), (JUMP, 'Gyro page')])),
                   ('SUPMGR.BIN', B.supmgr_sup()))
        s0, s1, s2, s3 = (slot(cam, k) for k in (0, 1, 2, 3))
        self.assertEqual((s0['N'], s0['Lock'], s0['Jump'], s0['Visible']), ('SupManager', 0, 1, 1))
        self.assertEqual((s1['N'], shown(s1), s1['Lock'], s1['Max'], s1['Default'], s1['PopH']),
                         ('Flip', 'Off', 0, 1, 0, 162))
        # the popup's Off / On are the page's stock texts (FT_Tog), its text variables blank
        self.assertEqual((s1['Ia'], s1['Ib'], s1['Ic'], s1['Tog']), (' ', ' ', ' ', 1))
        self.assertEqual((s2['N'], s2['Lock'], s2['Jump']), ('Gyro page', 0, 1))   # a locked row's keys die
        self.assertEqual((s3['N'], s3['Visible'], s3['Lock']), (' ', 0, 1))
        # three rows: no paging -- no title row, no tabs; focus on the stock tab bar
        # (user 2026-10-24: arriving from the next tab keeps switching pages), lit
        self.assertEqual(cam.vars['FT_PageText'][1], ' ')
        self.assertEqual(cam.vars['FT_Title'][1], 0)
        self.assertEqual([cam.vars[f'FT_TabVisible{k}'][1] for k in range(1, 8)], [0] * 7)
        self.assertNotEqual(cam.vars['FT_Row0'][1], 0)
        self.assertEqual(cam.vars['FT_Focus'][1], 55)
        self.assertEqual(cam.vars['FT_HeadOn'][1], 1)

    def test_six_rows_do_not_page(self):
        cam = boot(('A.BIN', ts('AAAA', [(JUMP, f'R{i}') for i in range(6)])))
        self.assertEqual([slot(cam, k)['N'] for k in range(6)], [f'R{i}' for i in range(6)])
        self.assertEqual(cam.vars['FT_Title'][1], 0)
        cam.press(11)                                           # Right on a hidden title: nothing
        self.assertEqual(slot(cam, 0)['N'], 'R0')
        self.assertEqual(cam.vars['FT_PageText'][1], ' ')

    def test_paging_on_the_title(self):
        rows = [(JUMP, f'R{i}') for i in range(7)]
        cam = boot(('A.BIN', ts('AAAA', rows[:6])), ('B.BIN', ts('BBBB', rows[6:])))
        self.assertEqual(cam.vars['FT_Title'][1], 1)
        self.assertEqual(cam.vars['FT_Focus'][1], 55)                   # the tab bar, paged or not
        self.assertEqual(cam.vars['FT_PageText'][1], '1 / 2')
        self.assertEqual([slot(cam, k)['N'] for k in range(6)], [' ', 'R0', 'R1', 'R2', 'R3', 'R4'])
        self.assertEqual(slot(cam, 0)['Visible'], 0)            # slot 0 under the title row: hidden
        self.assertEqual([cam.vars[f'FT_TabVisible{k}'][1] for k in range(1, 4)], [1, 1, 0])
        self.assertEqual([cam.vars[f'FT_TabWidth{k}'][1] for k in (1, 2)], [512, 512])
        cam.press(11)
        self.assertEqual(cam.vars['FT_PageText'][1], '2 / 2')
        self.assertEqual((slot(cam, 0)['N'], slot(cam, 0)['Visible']), (' ', 0))   # not R4 again
        self.assertEqual([slot(cam, k)['N'] for k in range(1, 6)], ['R5', 'R6', ' ', ' ', ' '])
        self.assertEqual([slot(cam, k)['Visible'] for k in range(1, 6)], [1, 1, 0, 0, 0])
        self.assertEqual([cam.vars[f'FT_TabActive{k}'][1] for k in (1, 2)], [0, 1])
        cam.press(11)                                           # the last page stays
        self.assertEqual(cam.vars['FT_PageText'][1], '2 / 2')
        cam.press(10)
        self.assertEqual(slot(cam, 1)['N'], 'R0')
        self.assertEqual(cam.vars['FT_Key'][1], 0)

    def test_paging_repaints_lock_and_popup(self):
        rows = [(JUMP, f'R{i}') for i in range(5)] + [(TOGGLE, 'Z toggle')]
        cam = boot(('A.BIN', ts('AAAA', rows)), ('B.BIN', ts('BBBB', [(JUMP, 'ZZ')])))
        self.assertEqual((slot(cam, 1)['Lock'], slot(cam, 1)['Max']), (0, 0))
        cam.press(11)
        s = slot(cam, 1)
        self.assertEqual((s['N'], s['Lock'], s['Jump'], s['Max'], shown(s)), ('Z toggle', 0, 0, 1, 'Off'))
        self.assertEqual((slot(cam, 2)['N'], slot(cam, 2)['Jump'], slot(cam, 2)['Lock']), ('ZZ', 1, 0))
        self.assertEqual(slot(cam, 3)['Lock'], 1)                # empty: locked

    def test_repaint_includes_slot_0(self):
        cam = boot(('A.BIN', ts('AAAA', [(TOGGLE, 'Flip')])))
        cam.put(T.blocks(cam)['A.BIN'] + T.O_TOGGLED, 1)
        cam.press(11)                                           # one page: repaint in place
        self.assertEqual(shown(slot(cam, 0)), 'On')

    def test_out_of_range_value_shows_the_first_choice(self):
        cam = boot(('A.BIN', ts('AAAA', [(TOGGLE, 'Flip')])))
        cam.put(T.blocks(cam)['A.BIN'] + T.O_TOGGLED, 7)        # get() answers 7
        cam.press(11)                                           # one page: repaint in place
        cam.notify('FT_Choice0', 255)
        cam.press(10)
        self.assertEqual((shown(slot(cam, 0)), slot(cam, 0)['Default']), ('Off', 0))

    def test_toggle_choice_sets_the_value(self):
        cam = boot(('A.BIN', ts('AAAA', [(TOGGLE, 'Flip')])))
        base = T.blocks(cam)['A.BIN']
        cam.notify('FT_Choice0', 1)
        self.assertEqual(cam.w(base + T.O_TOGGLED), 1)
        self.assertEqual(shown(slot(cam, 0)), 'On')
        self.assertEqual(slot(cam, 0)['Default'], 1)
        self.assertEqual(cam.posts[-1], ('FT_Choice0', 255))     # ready for the next choice
        cam.notify('FT_Choice0', 5)                             # out of range: no set
        self.assertEqual(cam.w(base + T.O_TOGGLED), 1)

    def test_jump_and_action_rows_open(self):
        cam = boot(('A.BIN', ts('AAAA', [(JUMP, 'a page'), (ACTION, 'b run'), (TOGGLE, 'c flip')])))
        base = T.blocks(cam)['A.BIN']
        cam.press(41); cam.press(42); cam.press(43); cam.press(44)   # slots 0..3 (40 + slot + 1)
        self.assertEqual([cam.w(base + T.O_OPENED + 4 * i) for i in range(2)], [1, 1])
        self.assertEqual(cam.w(base + T.O_TOGGLED + 8), 0)      # a TOGGLE does not open

    def test_jump_on_a_later_page(self):
        cam = boot(('A.BIN', ts('AAAA', [(TOGGLE, f'T{i}') for i in range(6)])),
                   ('B.BIN', ts('BBBB', [(JUMP, 'page')])))
        base = T.blocks(cam)['B.BIN']
        cam.press(42)                                           # page 1, slot 1 = T0: nothing
        cam.press(11)
        cam.press(43)                                           # page 2, slot 2 = row 6 = B's
        self.assertEqual(cam.w(base + T.O_OPENED), 1)

    def test_page_refresh_repaints_the_slot(self):
        cam = boot(('A.BIN', ts('AAAA', [(TOGGLE, 'Flip')])))
        cam.put(T.blocks(cam)['A.BIN'] + T.O_TOGGLED, 1)        # the sup changed it itself
        cam.callsvc('page_refresh', 0)
        self.assertEqual(shown(slot(cam, 0)), 'On')
        paged = boot(('A.BIN', ts('AAAA', [(TOGGLE, f'T{i}') for i in range(6)])),
                     ('B.BIN', ts('BBBB', [(TOGGLE, 'T6')])))
        paged.put(T.blocks(paged)['A.BIN'] + T.O_TOGGLED + 4, 1)
        paged.callsvc('page_refresh', 1)                        # row 1 = page 1, slot 2
        self.assertEqual(shown(slot(paged, 2)), 'On')
        paged.put(T.blocks(paged)['B.BIN'] + T.O_TOGGLED, 1)
        paged.callsvc('page_refresh', 6)                        # page 2: not on screen
        self.assertEqual(shown(slot(paged, 1)), 'Off')

    def test_footer_follows_focus_and_popup(self):
        cam = boot(('A.BIN', ts('AAAA', [(TOGGLE, 'Flip')])))
        ok = lambda: cam.vars['FT_OK'][1]
        cam.press(31); self.assertEqual(ok(), FP4.HOME_TEXTS[1])   # no title row: no page hint
        cam.press(21); self.assertEqual(ok(), FP4.HOME_TEXTS[2])
        cam.press(20); self.assertEqual(ok(), FP4.HOME_TEXTS[1])
        paged = boot(('A.BIN', ts('AAAA', [(TOGGLE, f'T{i}') for i in range(6)])),
                     ('B.BIN', ts('BBBB', [(TOGGLE, 'T6')])))
        ok = lambda: paged.vars['FT_OK'][1]
        paged.press(31); self.assertEqual(ok(), FP4.HOME_TEXTS[3])
        paged.press(30); self.assertEqual(ok(), FP4.HOME_TEXTS[1])

    def test_no_data_file_no_ui_and_sups_unaffected(self):
        cam = boot(('A.BIN', ts('AAAA', [(TOGGLE, 'Flip')])), data=False)
        self.assertEqual(ui_lines(cam), [(0, 0, 'LOADER.BIN'), (1, 0, 'LOADER.BIN')])
        self.assertEqual(cam.vars, {})
        self.assertIn('A.BIN', T.blocks(cam))
        # the hooks stay: they serve any sup's pages, not only this one
        self.assertNotEqual(cam.w(F6.SITE), struct.unpack('<I', T.T3.IMAGE.read_bytes()[F6.SITE - 0xC0000000:][:4])[0])

    def test_power_off_restores_the_sites(self):
        cam = boot(('A.BIN', ts('AAAA', [(TOGGLE, 'Flip')])))
        img = T.T3.IMAGE.read_bytes()
        sites = [0xC056461C, 0xC05E5B58, 0xC05E61C8, 0xC05E61E0]
        stock = [struct.unpack_from('<I', img, a - 0xC0000000)[0] for a in sites]
        self.assertNotEqual(cam.w(sites[0]), stock[0])
        cam.power_off()
        self.assertEqual([cam.w(a) for a in sites], stock)

    def test_a_v3_uishare_sup_is_refused_on_the_string_sites(self):
        # v3 uishare claims the string sites SHARED_UI; under v4 they are the
        # core's alone, so such a sup must not load half-working
        img = T.T3.IMAGE.read_bytes()
        for site in (0xC05E5B58, 0xC05E61C8, 0xC05E61E0):
            stock = struct.unpack_from('<I', img, site - 0xC0000000)[0]
            cam = boot(('A.BIN', B.test_sup(T.cfg(claims=[(site, stock, 3, 0)], rows=[(TOGGLE, 'Flip')]), 'AAAA')))
            log = cam.loadlog()
            self.assertIn('A.BIN', [t for c, _, _, t in log if c == T.CODES['RELEASED']], hex(site))
            self.assertIn(site, [a for c, a, _, _ in log if c == T.CODES['CONFLICT']])

    def strings_cam(self):
        cam = boot(('A.BIN', ts('AAAA', [(TOGGLE, 'Flip')])), ('SUPMGR.BIN', built()['smgr']))
        pool = F6.FAKE + 0x7480                                 # a reader of a 16-byte stock pool
        cam.mu.mem_write(pool, b'stock-0\0stock-8\0')
        cam.put(F6.FAKE + 0x7400 + 0x10, 16)
        cam.put(F6.FAKE + 0x7400 + 0x14, pool)
        return cam, F6.FAKE + 0x7400, pool

    def site(self, cam, at, reader, r1):
        r0, _ = cam.call(at, r0=reader, r1=r1, thumb=True)
        return r0

    def loaded(self, cam, data):
        """Where `data` (an FT4 file as built) was read: its header is unchanged."""
        heap = bytes(cam.mu.mem_read(T.HEAP, T.HEAP_SIZE))
        at = heap.find(data[:64])
        self.assertGreaterEqual(at, 0)
        return T.HEAP + T.ALIAS + at                            # the cached alias it runs at

    def check_ids(self, cam, reader, data, names):
        hdr = struct.unpack_from('<17I', data)                  # fpsup-ui struct fpui_file
        pack_off, strs_off, n_refs, refs_off = hdr[1], hdr[3], hdr[5], hdr[6]
        base = self.loaded(cam, data)
        for j in (0, 1, n_refs // 2, n_refs - 1):
            off, k = struct.unpack_from('<II', data, refs_off + 8 * j)
            sid = struct.unpack('>I', bytes(cam.mu.mem_read(base + pack_off + off, 4)))[0]
            # the id is the string's own address, at the uncached alias: no table
            self.assertEqual(sid + 0x80000000, base + struct.unpack_from('<I', data, strs_off + 4 * k)[0])
            self.assertTrue(0x40000000 <= sid < 0x80000000, hex(sid))
            got = self.site(cam, 0xC05E5B58, reader, sid)
            self.assertEqual(got, sid + 0x80000000)                     # the cached alias
            self.assertEqual(cam.cstr(got), names[k])

    def test_private_strings_resolve_to_themselves(self):
        cam, reader, pool = self.strings_cam()
        self.check_ids(cam, reader, built()['data'], built()['info']['strings'])
        sm, info = FP4.supmgr_file()
        self.check_ids(cam, reader, sm, info['strings'])                    # a sup's pack: the same rule

    def test_stock_lookups_keep_the_firmware_rule(self):
        cam, reader, pool = self.strings_cam()
        self.assertEqual(self.site(cam, 0xC05E5B58, reader, 8), pool + 8)
        self.assertEqual(self.site(cam, 0xC05E5B58, reader, 16), 0)            # past the pool
        self.assertEqual(self.site(cam, 0xC05E5B58, reader, 0xFFFFFFFF), 0)
        self.assertEqual(self.site(cam, 0xC05E5B58, reader, 0x3FFFFFFF), 0)    # below the id range: stock's 0
        self.assertEqual(self.site(cam, 0xC05E5B58, reader, 0x80000000), 0)    # above it, too
        self.assertEqual(self.site(cam, 0xC05E5B58, reader, 0x90000000), 0)
        self.assertEqual(self.site(cam, 0xC05E61C8, reader, pool), 1)           # the pool's first byte
        self.assertEqual(self.site(cam, 0xC05E61C8, reader, pool + 3), 1)
        self.assertEqual(self.site(cam, 0xC05E61C8, reader, pool + 16), 0)
        self.assertEqual(self.site(cam, 0xC05E61C8, reader, pool - 1), 0)
        self.assertEqual(self.site(cam, 0xC05E61E0, reader, pool + 3), 13)

    def test_our_pointers_are_borrowed(self):
        cam, reader, pool = self.strings_cam()
        data = built()['data']
        base = self.loaded(cam, data)
        p = base + struct.unpack_from('<I', data, struct.unpack_from('<17I', data)[3])[0]   # string 0
        self.assertEqual(self.site(cam, 0xC05E61C8, reader, p), 1)              # owns: never freed
        rest = self.site(cam, 0xC05E61E0, reader, p)
        self.assertGreater(rest, len(cam.cstr(p)))                               # realloc copies inside
        self.assertGreaterEqual(p, T.HEAP + T.ALIAS)                            # the cached alias

    def test_owns_and_remain_keep_the_registers(self):
        # the firmware's contract for these leaves: r0, r2 and the flags change,
        # nothing else -- C runs inside them on a stack of its own alignment
        cam, reader, pool = self.strings_cam()
        p = self.loaded(cam, built()['data']) + 100
        from unicorn.arm_const import UC_ARM_REG_R3, UC_ARM_REG_R12, UC_ARM_REG_R4
        for site, want in ((0xC05E61C8, 1), (0xC05E61E0, None)):
            for sp in (T.T3.STACK - 0x1004, T.T3.STACK - 0x1008):   # 4 and 0 mod 8
                cam.mu.reg_write(UC_ARM_REG_R3, 0x33333333)
                cam.mu.reg_write(UC_ARM_REG_R12, 0x12121212)
                cam.mu.reg_write(UC_ARM_REG_R4, 0x44444444)
                r0, sp_after = cam.call(site, r0=reader, r1=p, sp=sp, thumb=True)
                self.assertEqual(sp_after, sp)
                self.assertEqual([cam.r(r) for r in (UC_ARM_REG_R3, UC_ARM_REG_R12, UC_ARM_REG_R4)],
                                 [0x33333333, 0x12121212, 0x44444444])
                self.assertEqual(cam.r(T.T3.UC_ARM_REG_R1), p)
                if want is not None:
                    self.assertEqual(r0, want)
                else:
                    self.assertGreater(r0, 0)

    def test_supmanager_hides_the_core_pseudo_sup(self):
        cam = boot(('A.BIN', ts('AAAA', [])))
        names = []
        for i in range(8):
            out = T.T3.STACK - 0x3000
            if cam.callsvc('sups_list', i, out) != 0:
                break
            names.append((cam.cstr(cam.w(out)), cam.w(out + 8)))
        self.assertIn(('LOADER.BIN', 0x34495546), names)        # listed with its id; SupManager skips it



def sm(cam, part, k):
    return cam.vars[f'SM_{part}{k}'][1]


@unittest.skipIf(T.Uc is None or not T.T3.IMAGE.exists(), 'needs unicorn and the image')
class SupManagerPageTests(unittest.TestCase):
    def boot_sm(self, *sups):
        return boot(('A.BIN', ts('AAAA', [])), ('SUPMGR.BIN', built()['smgr']), *sups)

    def test_pack_installed_and_ready(self):
        cam = self.boot_sm()
        self.assertEqual(ui_lines(cam), [(0, 0, 'LOADER.BIN'), (0x100, 1, 'LOADER.BIN')])
        self.assertEqual({n for n in cam.vars if n.startswith('SM_')}, {n for _t, n, _v in FP4.supmgr_vars()})
        subs = {n for _o, n, _f in cam.subs}
        self.assertTrue({'SM_Key', 'SM_Focus'} | {f'SM_Choice{k}' for k in range(6)} <= subs)
        self.assertEqual(cam.machines()[:2], [FP4.HOME_MACHINE, FP4.SUPMGR_MACHINE])   # the last in, first
        self.assertEqual(cam.page_id('FT_LIST'), 21)

    def test_list_without_the_core(self):
        cam = self.boot_sm(('B.BIN', ts('BBBB', [])))
        cam.press(41)                           # opening it lists again: at its entry, later sups were not loaded yet
        names = [sm(cam, 'N', k) or sm(cam, 'G', k) for k in range(6)]
        # three: no paging -- slots 0..5, no title row, no tabs
        self.assertEqual([sm(cam, 'N', k) for k in range(4)], ['A.BIN', 'B.BIN', 'SupManager', ' '])
        self.assertEqual([sm(cam, 'Lock', k) for k in range(4)], [0, 0, 1, 1])
        self.assertEqual([sm(cam, 'Visible', k) for k in range(4)], [1, 1, 1, 0])
        self.assertNotIn('LOADER.BIN', names)
        self.assertEqual(cam.vars['SM_Title'][1], 0)
        self.assertEqual([cam.vars[f'SM_TabVisible{k}'][1] for k in range(1, 8)], [0] * 7)

    def test_six_sups_do_not_page(self):
        cam = self.boot_sm(*[(f'{c}.BIN', ts(c * 4, [])) for c in 'BCDE'])
        cam.press(41)
        self.assertEqual(cam.vars['SM_Title'][1], 0)
        self.assertEqual([sm(cam, 'N', k) or sm(cam, 'G', k) for k in range(6)],
                         ['A.BIN', 'B.BIN', 'C.BIN', 'D.BIN', 'E.BIN', 'SupManager'])

    def test_the_file_names_version_in_brackets(self):
        """The user 2026-10-25: the version rides on the file name; SupManager
        shows it after the display name, as RES-Custom's "OG3K (3008x2000)"."""
        gyro = B.test_sup(T.cfg(rows=[]), T.sid('GYRO'), name='Gyro2')
        cam = self.boot_sm(('Gyro2_v0.1.0.BIN', gyro), ('Gyro2_v0.2.0test.BIN', gyro),
                           ('Flip.BIN', B.test_sup(T.cfg(rows=[]), T.sid('FLIP'), name='ScreenFlip')))
        cam.press(41)
        names = [sm(cam, 'N', k) for k in range(6)]
        grey = [sm(cam, 'G', k) for k in range(6)]
        self.assertIn('Gyro2 (0.2.0test)', names)               # the newer loaded
        self.assertIn('Gyro2_v0.1.0.BIN', grey)                 # the older: a duplicate sup_id, not loaded
        self.assertIn('ScreenFlip', names)                      # no "_v": the name alone
        self.assertIn('A.BIN', names)                           # no header name: the file name, no brackets

    def test_seven_sups_page(self):
        cam = self.boot_sm(*[(f'{c}.BIN', ts(c * 4, [])) for c in 'BCDEF'])
        cam.press(41)
        self.assertEqual(cam.vars['SM_Title'][1], 1)
        self.assertEqual(cam.vars['SM_PageText'][1], '1 / 2')
        self.assertEqual([sm(cam, 'N', k) for k in range(6)], [' ', 'A.BIN', 'B.BIN', 'C.BIN', 'D.BIN', 'E.BIN'])
        self.assertEqual(sm(cam, 'Visible', 0), 0)
        self.assertEqual([cam.vars[f'SM_TabWidth{k}'][1] for k in (1, 2)], [512, 512])
        cam.notify('SM_Key', 11)
        self.assertEqual([sm(cam, 'N', k) or sm(cam, 'G', k) for k in range(3)], [' ', 'F.BIN', 'SupManager'])
        self.assertEqual(sm(cam, 'Visible', 0), 0)
        cam.notify('SM_Choice1', 1)                             # page 2, slot 1 = F.BIN: Disable
        self.assertEqual(cam.callsvc('disabled_get', T.sid('FFFF')), 1)

    def test_row_opens_the_page_with_its_focus(self):
        cam = self.boot_sm()
        self.assertEqual(slot(cam, 0)['N'], 'SupManager')
        self.assertEqual(go_text(cam), '')                      # nothing named before a press
        cam.press(41)                                           # slot 0's Right
        # the firmware's own transition: the row's request names the page; no screen set
        self.assertEqual((cam.shown, go_text(cam)), ([], 'FT_LIST'))
        self.assertEqual(cam.vars['FT_Go'][1], 1)                 # posted after open(): the change event
        cam.notify('FT_Go', 0)                                  # the opened page entered: nothing named
        self.assertEqual(go_text(cam), '')
        cam.press(41)
        self.assertEqual((go_text(cam), cam.vars['FT_Go'][1]), ('FT_LIST', 2))
        self.assertNotEqual(cam.vars['SM_Row0'][1], 0)
        self.assertEqual(cam.vars['SM_Focus'][1], cam.vars['SM_Row0'][1])   # unpaged: slot 0
        paged = self.boot_sm(*[(f'{c}.BIN', ts(c * 4, [])) for c in 'BCDEF'])
        paged.notify('SM_Focus', 33333)
        paged.press(41)
        self.assertEqual(paged.vars['SM_Focus'][1], FP4.HEADER_FOCUS)       # paged: the title row

    def test_ui_go_only_inside_a_rows_open(self):
        cam = self.boot_sm()
        name = cam._alloc(64)
        cam.mu.mem_write(name, b'FT_LIST\0')
        self.assertNotEqual(cam.callsvc('ui_go', name), 0)           # no press: nothing to name
        self.assertEqual(go_text(cam), '')
        cam.press(41)
        long = cam._alloc(64)
        cam.mu.mem_write(long, b'X' * len(FP4.GO_TEXT) + b'\0')     # SL_GO_MAX bytes: refused
        self.assertNotEqual(cam.callsvc('ui_go', long), 0)
        self.assertEqual(go_text(cam), 'FT_LIST')

    def test_header_lights_on_the_tab_bar(self):
        cam = self.boot_sm()
        for name, head in (('FT_Focus', 'FT_HeadOn'), ('SM_Focus', 'SM_HeadOn')):
            cam.notify(name, 55)
            self.assertEqual(cam.vars[head][1], 1)
            cam.notify(name, FP4.HEADER_FOCUS)
            self.assertEqual(cam.vars[head][1], 0)

    def test_moving_the_cursor_posts_nothing_unchanged(self):
        """Each post is another GUI update pass (the user, 2026-10-24: the cursor
        lagged on both pages): a focus move within the rows posts nothing."""
        cam = self.boot_sm(*[(f'{c}.BIN', ts(c * 4, [])) for c in 'BCDEF'])
        for name in ('FT_Focus', 'SM_Focus'):
            cam.notify(name, 33333)                             # first: header off, hint
            n = len(cam.posts)
            for focus in (33334, 33335, 33336, 33333):
                cam.notify(name, focus)
            self.assertEqual(cam.posts[n:], [], name)
            cam.notify(name, 55)                                # the tab bar: header on
            self.assertEqual([p for p in cam.posts[n:] if p[0].endswith('HeadOn')], [(name[:2] + '_HeadOn', 1)])

    def test_disable_writes_the_list(self):
        cam = self.boot_sm()
        cam.notify('SM_Choice0', 1)                             # A.BIN: Disable
        self.assertEqual(cam.callsvc('disabled_get', T.sid('AAAA')), 1)
        self.assertEqual(sm(cam, 'R', 0), 'Unload on restart')
        self.assertEqual(sm(cam, 'Default', 0), 1)
        self.assertIn('\\fpSup\\LOADER.BIN', cam.written)
        cam.notify('SM_Choice0', 0)                             # Enable again
        self.assertEqual(cam.callsvc('disabled_get', T.sid('AAAA')), 0)
        self.assertEqual(sm(cam, 'R', 0), ' ')
        cam.notify('SM_Choice1', 1)                             # SupManager itself: locked
        self.assertEqual(cam.callsvc('disabled_get', T.sid('SMGR')), 0)

    def test_the_right_column_is_the_stock_on_off(self):
        """On when the sup loads next boot, Off when it is disabled (the page's
        localized stock texts, user 2026-10-24); an empty slot shows neither."""
        cam = self.boot_sm()
        self.assertEqual((sm(cam, 'TOn', 0), sm(cam, 'TOff', 0)), (1, 0))
        cam.notify('SM_Choice0', 1)                             # A.BIN: Disable
        self.assertEqual((sm(cam, 'TOn', 0), sm(cam, 'TOff', 0)), (0, 1))
        self.assertEqual(sm(cam, 'R', 0), 'Unload on restart')  # kept
        self.assertEqual((sm(cam, 'TOn', 5), sm(cam, 'TOff', 5)), (0, 0))
        # the red note and the grey name are drawn only when they say something
        self.assertEqual((sm(cam, 'RShow', 0), sm(cam, 'GShow', 0), sm(cam, 'RShow', 2), sm(cam, 'GShow', 2)), (1, 0, 0, 0))
        cam.notify('SM_Choice0', 0)
        self.assertEqual(sm(cam, 'RShow', 0), 0)

    def test_file_read_and_borrow(self):
        cam = self.boot_sm()
        buf, path = F6.FAKE + 0x7600, F6.FAKE + 0x7580
        cam.mu.mem_write(path, SM_PATH.encode() + b'\0')
        self.assertEqual(cam.callsvc('file_read', path, buf, 68), 68)
        self.assertEqual(bytes(cam.mu.mem_read(buf, 4)), b'FT4S')
        cam.mu.mem_write(path, b'\\fpSup\\NONE.BIN\0')
        self.assertEqual(cam.callsvc('file_read', path, buf, 68) & 0xFFFFFFFF, 0xFFFFFFFB)   # SL_IO
        self.assertEqual(cam.callsvc('borrow', 0, 0x100) & 0xFFFFFFFF, 0xFFFFFFFD)        # SL_BADARG
        self.assertEqual(cam.callsvc('borrow', 0x100, 0x100) & 0xFFFFFFFF, 0xFFFFFFFD)
        lo = T.HEAP + T.ALIAS + 0x1000
        reader = F6.FAKE + 0x7400
        cam.put(reader + 0x10, 16); cam.put(reader + 0x14, F6.FAKE + 0x7480)
        own = lambda p: cam.call(0xC05E61C8, r0=reader, r1=p, thumb=True)[0]
        self.assertEqual(own(lo + 8), 0)
        self.assertEqual(cam.callsvc('borrow', lo, lo + 0x40), 0)
        self.assertEqual((own(lo + 8), own(lo + 0x40)), (1, 0))

    def test_supmanager_holds_no_firmware_address(self):
        import re
        src = (T.HERE / 'supmgr.c').read_text()
        self.assertEqual(re.findall(r'0x[cC][0-9a-fA-F]{7}', src), [])
        self.assertNotIn('vars_off', src)

    def test_without_its_data_the_row_stays_and_does_nothing(self):
        cam = boot(('A.BIN', ts('AAAA', [])), ('SUPMGR.BIN', built()['smgr']), smdata=False)
        self.assertEqual(ui_lines(cam), [(0, 0, 'LOADER.BIN'), (0x100, 1, 'LOADER.BIN')])
        self.assertEqual(sm(cam, 'N', 0) if 'SM_N0' in cam.vars else None, None)   # no page of its own
        cam.press(41)
        self.assertEqual(cam.shown, [])


_probe = {}
PROBE = {name: 0x30555046 + (i << 24) for i, name in enumerate(('text', 'first', 'set', 'watch', 'install', 'read'))}


@unittest.skipIf(T.Uc is None or not T.T3.IMAGE.exists(), 'needs unicorn and the image')
class FpuiLibraryTests(unittest.TestCase):
    """fpSup/fpsup-ui as a third party's sup would use it (test_fpui_probe.c)."""
    def setUp(self):
        if 'probe' not in _probe:
            _probe['probe'] = B.c_sup(HERE / 'test_fpui_probe.c', 'FPUP', name='fpui probe')
        self.cam = boot(('FPUP.BIN', _probe['probe']), ('SUPMGR.BIN', built()['smgr']))
        heap = bytes(self.cam.mu.mem_read(T.HEAP, T.HEAP_SIZE))
        self.sm, _ = FP4.supmgr_file()
        self.ui = T.HEAP + T.ALIAS + heap.find(self.sm[:64])
        self.names = [n for _t, n, _v in FP4.supmgr_vars()]

    def fn(self, name, *args):
        f = self.cam.callsvc('find', PROBE[name])
        self.assertTrue(f, name)
        return self.cam.call(f & ~1, *args, thumb=bool(f & 1))[0]

    def test_by_number(self):
        cam = self.cam
        self.assertEqual(cam.cstr(self.fn('text', self.ui, 1)), FP4.SUPMGR_TEXTS[1])
        self.assertEqual(self.fn('first', self.ui, self.names.index('SM_Title')), 1)
        self.fn('set', self.ui, self.names.index('SM_Title'), 7)
        self.assertEqual(cam.posts[-1], ('SM_Title', 7))

    def test_a_wrong_file_or_number_does_nothing(self):
        cam = self.cam
        n = len(cam.posts)
        for bad in (0, self.ui + 4, T.HEAP + T.ALIAS):
            self.assertEqual(self.fn('text', bad, 1), 0)
            self.fn('set', bad, 1, 5)
        self.assertEqual(self.fn('text', self.ui, len(FP4.SUPMGR_TEXTS)), 0)
        self.assertEqual(self.fn('first', self.ui, len(self.names)), 0)
        # one past the end reads the word after the table: make it non-zero, so
        # "does nothing" is told from "read what is there"
        vars_off = struct.unpack_from('<17I', self.sm)[8]
        past = self.ui + vars_off + 12 * len(self.names) + 8
        cam.put(past, 0x5A5A5A5A)
        self.assertEqual(self.fn('first', self.ui, len(self.names)), 0)
        self.fn('set', self.ui, len(self.names), 5)
        self.assertEqual(len(cam.posts), n)
        self.assertEqual(self.fn('watch', self.ui, len(self.names), 0x1000), 0xFFFFFFFD)   # SL_BADARG
        self.assertEqual(self.fn('watch', self.ui, 0, 0), 0xFFFFFFFD)

    def test_read(self):
        cam = self.cam
        path = F6.FAKE + 0x7580
        cam.mu.mem_write(path, SM_PATH.encode() + b'\0')
        at = self.fn('read', cam.svc(), path)
        self.assertGreaterEqual(at, T.HEAP + T.ALIAS)                          # the cached alias
        self.assertEqual(at & 63, 0)                                             # its own lines
        self.assertEqual(bytes(cam.mu.mem_read(at, len(self.sm))), self.sm)
        cam.mu.mem_write(path, b'\\fpSup\\NONE.BIN\0')
        self.assertEqual(self.fn('read', cam.svc(), path), 0)

    def test_install_refuses_a_bad_file(self):
        cam = self.cam
        at = T.HEAP + T.HEAP_SIZE - 0x40000                                     # free test memory
        hdr = list(struct.unpack_from('<17I', self.sm))
        bad_ref = bytearray(self.sm)
        n_str, refs_off = hdr[4], hdr[6]
        struct.pack_into('<I', bad_ref, refs_off + 4, n_str)                    # a string past the table
        cam.mu.mem_write(at, bytes(bad_ref))
        self.assertEqual(self.fn('install', cam.svc(), at + T.ALIAS), 8)
        cam.mu.mem_write(at, self.sm)
        self.assertEqual(self.fn('install', cam.svc(), at), 2)                 # the uncached alias: no ids
        cam.mu.mem_write(at, b'XXXX')
        self.assertEqual(self.fn('install', cam.svc(), at + T.ALIAS), 1)


if __name__ == '__main__':
    unittest.main()
