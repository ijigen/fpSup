#!/usr/bin/env python3
"""native/conv.c (Stage B, projects/lut-sup/notes/STAGE_B_CONVERT_IN_MANAGER.md) on the real ARM build.

The firmware's task calls (tk_cre/sta/slp/wup) and the folder calls are Python; the worker's body runs as
ARM (one Gauss-Newton iteration per start: conv.iters = 1, the speed of the emulator).  The worker's
"done" is the app state LC_ConvEnd (UicGuiFunction::v1); the page answers with LC_Key = 90, delivered by
notify(), as the GUI would.

Checked: On converts first (no row until then), the guards while it runs, the file it writes against
jft.py's quantise / pack on the camera's own solution and inputs, the score, the COLOR row and the
tables from the new file, a write failure."""
import struct
import sys
import unittest
import unittest.mock

import numpy as np

import test_lvb_native as V
import test_library_native as LN
import test_sup_ui as U
import test_sup_native as NS

sys.path.insert(0, str(V.ROOT_DIR / 'projects/lut-sup/probes'))
import lv_fit as F                                          # noqa: E402
import lut_batch_eval as E                                  # noqa: E402
import joint_fit_eval as J                                  # noqa: E402

TK_CRE, TK_STA, TK_SLP, TK_WUP = 0xC0016A58, 0xC0016BC0, 0xC01F8D00, 0xC01F8ED4
FS_DISK, DIR_CTOR, DIR_MAKE, DIR_DTOR = 0xC0407E20, 0xC0366918, 0xC03669C0, 0xC0366940
GUI_FUNCTION, GUI_APPSTATE, GUI_OBJECT = 0xC054DD38, 0xC055D470, 0xC3786188
MS_CLOCK = 0xC002B920
CONV_MAGIC = 0x31564E43
JFT_BYTES = 64 + 12580                      # JFIT v5: + m1 (set 1), 20 bytes; v6: + the CKNEE block, 16
JFC_BYTES = 212                             # the chart block after it (Bei 11-07: lvb.c JFC_BYTES, jft.CHART_BYTES)
JFT_FILE = JFT_BYTES + JFC_BYTES
N, NF, NCHK = 1331 + 168, 148, 72          # lvb's 11^3 grid + jft.grey_samples (conv.c CONV_GREY); A: the untied + CKNEE 148
NHSV, NGREY = 144, 168
NX = N + NHSV                               # + the 144 HSV samples (conv.c CONV_NX, JFIT v2 / v3's refine)
NDX, NXW = 3357, 3060                       # jfit.c JF_NDX: the dense extras, the first NXW stock-look weighted
ND = NX + NDX                               # JFIT v5's dense set (conv.c CONV_ND): the untied refine's samples
# struct conv_work (conv.c), field offsets
_sizes = [('A', 8 * (NF * NF + NF)), ('xs', 12 * ND), ('want', 12 * ND), ('w', 4 * ND), ('bt', 4 * 3 * 2048),
          ('tone', 4 * 3 * 2048), ('chk', 4 * 3 * NCHK), ('chkw', 4 * 3 * NCHK), ('dE', 4 * NCHK), ('m0', 36),
          ('best', 592), ('jft', JFT_FILE), ('chki', 12 * NCHK), ('gx', 12 * NGREY), ('gw', 12 * NGREY),
          ('gy', 12 * NGREY), ('hx', 12 * NHSV), ('alt', 592), ('alt2', 592), ('cost', 12), ('amax', 2 * 3 * 2048),
          ('prod', 592), ('pw', 592), ('ucost', 12), ('untie', 4), ('knee', 4), ('res', 4 * (3 * N + 123)), ('res2', 4 * (3 * N + 123)),
          ('u', 4 * 27 * 2048), ('pre', 4 * 5 * N), ('J', 0)]
JP = 20                                     # struct jfit: n, xs, want, w, base_tone, then P[148] (ARM: 4-byte pointers)
OFF = {}
_at = 0
for _k, _s in _sizes:
    OFF[_k] = _at; _at += _s


class Camera(V.Camera):
    auto_jft = False

    def page_entries(self):
        super().page_entries()
        self.cv_tasks, self.cv_wakes, self.cv_dirs, self.cv_sleeps, self.jft_write_ok = [], [], [], 0, True
        self.cv_states, self.cv_ms, self.cv_clocks = [], 0, []
        self.stubs = {TK_CRE: 'CV_TK_CRE', TK_STA: 'CV_TK_STA', TK_SLP: 'CV_TK_SLP', TK_WUP: 'CV_TK_WUP',
                      FS_DISK: 'CV_FS_DISK', DIR_CTOR: 'CV_DIR_CTOR', DIR_MAKE: 'CV_DIR_MAKE', DIR_DTOR: 'CV_DIR_DTOR',
                      GUI_FUNCTION: 'CV_GUI_FN', GUI_APPSTATE: 'CV_GUI_STATE', MS_CLOCK: 'CV_MS'}

    def _hook(self, mu, addr, size, data):
        name = self.stubs.get(addr, '') if getattr(self, 'stubs_on', False) else ''
        r = lambda k: self.r(getattr(U.N.T3, f'UC_ARM_REG_R{k}')) if k < 3 else self.r(U.N.T4.UC_ARM_REG_R3)
        if name == 'CV_TK_CRE':
            d = r(0); self.cv_tasks.append(dict(exinf=self.w(d), attr=self.w(d + 4), entry=self.w(d + 8),
                                              pri=self.w(d + 12), stksz=self.w(d + 16)))
            return self._ret(7)
        if name == 'CV_TK_STA': return self._ret(0)
        if name == 'CV_TK_WUP': self.cv_wakes.append(r(0)); return self._ret(0)
        if name == 'CV_TK_SLP':                         # the first sleep returns (woken); the next ends the run
            self.cv_sleeps += 1
            if self.cv_sleeps > 1:
                mu.reg_write(U.N.T3.UC_ARM_REG_PC, U.N.T3.DONE); return True
            return self._ret(0)
        if name == 'CV_GUI_FN': return self._ret(GUI_OBJECT)
        if name == 'CV_MS':                                 # 50 ms a call: the hourglass turns every 7th
            self.cv_ms += 50
            frame = tuple(self.vars.get(f'LC_Clock{k}', (0, 0))[1] for k in range(3))
            if not self.cv_clocks or self.cv_clocks[-1] != frame: self.cv_clocks.append(frame)
            return self._ret(self.cv_ms)
        if name == 'CV_GUI_STATE':
            assert r(0) == GUI_OBJECT, 'v1 on the GUI function object'
            self.cv_states.append(self.cstr(r(1))); return self._ret(1)
        if name == 'CV_FS_DISK': return self._ret(1)
        if name in ('CV_DIR_CTOR', 'CV_DIR_DTOR'): return self._ret(0)
        if name == 'CV_DIR_MAKE': self.cv_dirs.append(self.cstr(r(1))); return self._ret(1)
        if addr == U.N.T3.F['F_OPEN'] and r(2) == 7 and self.cstr(r(1)).endswith('.JFT'):
            if not self.jft_write_ok: return self._ret(0)
            path = self.cstr(r(1)); self.written.setdefault(path, self.files.get(path, b'')); self.fobj[r(0)] = [path, 0]
            return self._ret(1)
        if addr == U.N.T3.F['F_WRITE'] and self.fobj.get(r(0)) and self.fobj[r(0)][0].endswith('.JFT'):
            path, pos = self.fobj[r(0)]; blob = bytes(mu.mem_read(r(1), r(2)))
            old = self.written[path]; self.written[path] = old[:pos] + blob + old[pos + r(2):]
            self.files[path] = self.written[path]; self.fobj[r(0)][1] += r(2)
            return self._ret(1)
        return super()._hook(mu, addr, size, data)

    def conv(self):
        _api, state = self.lut()
        blob = bytes(self.mu.mem_read(state, 4096))
        at = next(i for i in range(0, 4096, 4) if struct.unpack_from('<I', blob, i)[0] == CONV_MAGIC)
        w = struct.unpack_from('<24I', blob, at)
        keys = ('magic', 'state', 'index', 'base', 'pct', 'err', 'err_task', 'ticks', 'runs', 'done', 'last', 'iters',
                'tid', 'color', 'gamma', 'amount', 'matrix', 's0', 's1', 's2')
        return dict(zip(keys, w), at=state + at)

    def block(self):
        _api, state = self.lut()
        return state - struct.unpack_from('<I', self.files[LN.BIN], 48 + 4)[0]

    CONV_WORK = (100_000, 1_000_000)          # sizeof(struct conv_work) lies here; the asset is 4 MiB, the fit 60 KB

    def conv_area(self):
        """(address, bytes or None): struct conv_work (native/borrow.c) while it is borrowed (bytes None),
        else the snapshot the allocator model took when it came back."""
        lo, hi = self.CONV_WORK
        out = [q for q, n in NS.borrows(self)[2].items() if lo < n < hi]
        if out: return (out[0] + 63) & ~63, None
        q, _m, snap = next(x for x in reversed(self.borrow_freed) if lo < x[1] < hi)
        a = (q + 63) & ~63
        return a, snap[a - q:]

    def conv_mem(self):
        at, snap = self.conv_area()
        assert snap is None, 'the work area is returned'
        return at

    def floats(self, name, n):
        at, snap = self.conv_area()
        data = bytes(self.mu.mem_read(at + OFF[name], 4 * n)) if snap is None else snap[OFF[name]:OFF[name] + 4 * n]
        return np.frombuffer(data, '<f4').astype(float)

    def run_worker(self):
        t = self.cv_tasks[-1]
        entry = self.w(t['entry'] + 4)                     # the cave stub: ldr pc, [pc, #-4]; conv_task | 1
        self.cv_sleeps = 0
        mu = self.mu
        for reg, value in ((U.N.T3.UC_ARM_REG_SP, U.N.T3.STACK - 0x1004), (U.N.T3.UC_ARM_REG_R0, 0),
                           (U.N.T3.UC_ARM_REG_R1, t['exinf']), (U.N.T3.UC_ARM_REG_LR, U.N.T3.DONE)):
            mu.reg_write(reg, value & 0xffffffff)
        mu.emu_start(entry, U.N.T3.DONE, count=3_000_000_000)
        if self.error: raise self.error
        assert self.r(U.N.T3.UC_ARM_REG_PC) == U.N.T3.DONE, 'the worker did not come back to its sleep'


class Converted(Camera):
    auto_jft = True                                        # every cube's file on the card before the boot


class ConvertedOld(Converted):
    """every cube's file there, but made by an older fit (header +40 = `jfit`): stale since v3 (2026-11-07)"""
    jfit = 2

    def synth_jft(self, path):
        super().synth_jft(path)
        if path in self.files:
            b = bytearray(self.files[path]); struct.pack_into('<I', b, 40, self.jfit); self.files[path] = bytes(b)


@unittest.skipIf(U.N.T4.Uc is None or not U.N.T3.IMAGE.exists(), 'needs Unicorn and firmware image; skip is unverified')
class ConvNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        V.LvbNativeTests.setUpClass.__func__(cls)
        # + H: luma x hue (what the joint fit is for) on another input than the boot's rec709 / gamma24
        import library as L
        import build_sup as P0
        from test_lut import make_cube
        from cinemadng import COLOR_SPACES, COMMON_GAMMAS
        hard = lambda r, g, b: (r * (0.7 + 0.3 * g), g * (0.9 + 0.1 * b) + 0.05 * r * b, b * (0.5 + 0.5 * r))
        h = cls.root / 'lvb' / 'H.cube'
        h.write_bytes(b'# FPSUP_INPUT_COLOR_SPACE srgb\n# FPSUP_INPUT_GAMMA gamma26\n' + make_cube(9, fn=hard))
        cls.ldoc = L.configure(L.import_cubes(cls.ldoc, [h]), 'H.cube', enabled=True)
        cls.lfiles = LN.with_library(cls.files, cls.ldoc)      # the folder: these cubes alone
        cls.cubes = dict(cls.cubes, **{'H.cube': h})
        cls.H_KEY = (list(COLOR_SPACES).index('srgb'), COMMON_GAMMAS.index('gamma26'))
        import jft
        import build_sup as P
        cls.jft = jft
        _blob, facts = P.build_sup(collection=cls.ldoc)
        cls.repack_off = facts['entries']['lut4_conv_repack']
        cls.choose_off = facts['entries']['lut4_conv_choose']
        cls.jft_off = OFF['best'] + 592                                 # struct conv_mem: ... best, jft

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def cam(self, files=None):
        c = Camera(files or self.lfiles, self.ar)
        c.stubs_on = True                                  # after the boot: the loader calls some of these itself
        st = c.conv(); c.put(st['at'] + 4 * 11, 1)        # conv.iters = 1
        return c

    def entry(self, name='M.cube'):
        i = [e['filename'] for e in self.ldoc['luts']].index(name)
        return i, self.ldoc['luts'][i]

    def start(self, c, name='M.cube'):
        c.manager()
        c.choose(name, 1)

    def test_on_converts_first_and_the_row_comes_after(self):
        c = self.cam()
        i, e = self.entry('H.cube')
        self.assertEqual(c.clist()['n'], 0)                          # enabled in the build, not converted: no row
        c.manager()
        k, row = c.find_row('H.cube')
        self.assertEqual((row['A'].strip(), row['TOn'], row['TOff']), ('', 0, 1))   # not converted: plain Off (user 11-05)
        c.choose('H.cube', 0)                                         # Off: no conversion for that
        self.assertEqual(c.cv_tasks, [])
        c.choose('H.cube', 1)
        st = c.conv()
        self.assertEqual((st['state'], st['index'], st['err']), (1, i, 0))
        self.assertEqual(len(c.cv_tasks), 1)
        self.assertEqual((c.cv_tasks[0]['pri'], c.cv_tasks[0]['stksz'], c.cv_tasks[0]['attr']), (29, 0x4000, 0x41))
        self.assertEqual(c.cv_wakes, [7])
        self.assertEqual(c.w(c.cv_tasks[0]['entry']), 0xE51FF004)       # ARM: ldr pc, [pc, #-4]
        self.assertEqual(c.vars['LC_OK'][1], 'Converting 0%')
        self.assertEqual((c.cv_states, c.vars['LC_Busy'][1], c.vars['LC_Clock0'][1]), (['LC_ConvStart'], 1, 1))
        self.assertEqual(c.clist()['n'], 0)                          # nothing until the file is there
        c.run_worker()
        st = c.conv()
        self.assertEqual((st['state'], st['runs'], st['pct']), (2, 1, 100))
        self.assertEqual(c.cv_states, ['LC_ConvStart', 'LC_ConvEnd'])   # focus on the overlay; the worker's done
        self.assertEqual(c.vars['LC_Busy'][1], 1)                     # the overlay stays until the finish
        turns = [f for f in c.cv_clocks if sum(f) == 1]
        self.assertGreater(len(turns), 3)                             # the hourglass turned while it fitted
        self.assertTrue(all(a != b for a, b in zip(turns, turns[1:])))
        self.assertEqual({f.index(1) for f in turns}, {0, 1, 2})
        self.assertNotEqual(c.vars.get('LC_Key', (0, 0))[1], 90)       # not its own LC_Key post (never reached the watch)
        self.assertGreaterEqual(st['ticks'], 1)
        c.notify('LC_Key', 90)
        st = c.conv()
        self.assertEqual((st['state'], st['done'], st['last']), (0, 1, 0))
        self.assertEqual([c.vars[n][1] for n in ('LC_Busy', 'LC_Clock0', 'LC_Clock1', 'LC_Clock2')], [0, 0, 0, 0])
        self.assertEqual(c.cv_dirs, ['\\fpSup\\LUTDATA'])                 # the sup's folder, not the user's LUT\\
        key = LN.L.record_identity(e)
        path = '\\' + self.jft.path_for(key.hex()).replace('/', '\\')
        self.assertTrue(path.startswith('\\fpSup\\LUTDATA\\'))
        data = c.files[path]
        self.assertEqual(len(data), JFT_FILE)                          # + the chart block (Bei 11-07)
        u = self.jft.unpack(data)                                     # magic, size, fnv
        self.assertEqual(u['key'], (key[:8], *self.H_KEY, 100, 1))   # no author matrix: off (11-05)
        self.assertEqual(c.clist()['n'], 1)                           # the row, now
        pct = self.jft.match_percent(u['stats'][0])
        self.assertNotEqual(pct, self.jft.match_percent(u['stats'][1]))   # a cube hard enough to tell mean from p95
        self.assertEqual(c.vars['LC_OK'][1], f'{pct}% match')
        k, row = c.find_row('H.cube')
        self.assertEqual(c.vars[f'LC_V{k}'][1], f'{pct}%')
        self.assertEqual(row['A'].strip(), '')
        self.assertEqual(V.JftNativeTests.lvb_extra(self, c)['jfts'], 0)   # 11-10: a row's set is made at its pick
        self.assertEqual(c.invoke(8, self.entry('H.cube')[0]), 0)        # picked (the COLOR list's close: api.pick)
        self.assertEqual(V.JftNativeTests.lvb_extra(self, c)['jfts'], 1)   # lvb_refresh read the new file
        self.check_file_against_host(c, u)
        c.edit('H.cube')                                              # AEL: the title carries the match (user 11-05)
        self.assertEqual(c.vars['LC_PageTitle'][1], f'H.cube  {pct}% match')
        self.assertEqual((c.vars['LC_MatrixV'][1], c.vars['LC_MatrixT'][1]), (1, 'OFF'))   # no author matrix: Off (camera, 11-05)

    def test_enabled_but_not_converted_shows_off_and_on_converts(self):
        """user 11-05: an enabled cube without its .JFT shows Off (header counts it out); On converts it straight away."""
        c = self.cam()
        i, _e = self.entry('H.cube')
        c.manager()
        k, row = c.find_row('H.cube')
        self.assertEqual((row['TOn'], row['TOff'], row['A'].strip()), (0, 1, ''))
        self.assertTrue(c.vars['LC_Header'][1].startswith('LUT (0/'))
        c.choose('H.cube', 1)
        self.assertEqual((c.conv()['state'], c.conv()['index']), (1, i))

    def check_file_against_host(self, c, u):
        """jft.quantise / pack and the score on the camera's own inputs and solution."""
        P = c.floats('best', 148)
        bt = c.floats('bt', 3 * 2048).reshape(3, 2048)
        hw = self.jft.quantise(P, bt)
        got = u['hw']
        self.assertEqual(got['shift'], hw['shift']); self.assertEqual(got['m2'], hw['m2']); self.assertEqual(got['m1'], hw['m1'])
        self.assertLessEqual(int(np.abs(np.asarray(got['tone'], int) - hw['tone']).max()), 1)
        self.assertLessEqual(max(abs(a - b) for a, b in zip(got['ycmat'], hw['ycmat'])), 1)
        for a, b in zip(sum(got['ceq'], []), sum(hw['ceq'], [])):
            self.assertLessEqual(min(abs(a - b), 65536 - abs(a - b)), 1)
        self.assertEqual(got['ygam'], hw['ygam'])
        self.assertEqual(got['knee'] is None, hw['knee'] is None)             # JFIT v6: the CKNEE's codes (VFP float vs
        if hw['knee']:                                                        # the host's: a half may round apart)
            self.assertLessEqual(max(abs(a - b) for a, b in zip(got['knee'], hw['knee'])), 1)
        # inputs: lvb's samples, the ColorChecker set
        samples = np.r_[E.lvb_samples(), self.jft.grey_samples()]                # the grid, then the grey axis
        self.assertLess(np.abs(c.floats('xs', 3 * N).reshape(-1, 3) - samples).max(), 1e-5)
        chk = c.floats('chk', 3 * NCHK).reshape(-1, 3)
        self.assertLess(np.abs(chk - E.sample_sets()['色卡']).max(), 1e-5)
        # the targets: the cube as the host renders it (lv_fit.make_target)
        from cube import Cube
        target = F.make_target(Cube.read(self.cubes['H.cube']), space='srgb', gamma='gamma26')
        host_w = np.sqrt((1 - 2.5 * F.saturation(np.clip(target(samples, 0), 0, 1)) / 8) ** 8)
        self.assertLess(np.abs(c.floats('w', N)[-168:] - host_w[-168:]).max(), 0.02)   # the greys' weights as lvb's
        for name, xs, n in (('want', samples, N), ('chkw', chk, NCHK)):
            host = F.lab709(np.clip(target(xs, 100), 0, 1))
            d = np.linalg.norm(c.floats(name, 3 * n).reshape(-1, 3) - host, axis=1)
            self.assertLess(d.mean(), 0.05, name); self.assertLess(d.max(), 0.5, name)
        # JFIT v5's dense extras (after the NX): jf_dense_samples, the cube's render, the stock-look weight / 1
        xd, nw = self.jft.dense_samples()
        self.assertEqual(nw, NXW)
        self.assertLess(np.abs(c.floats('xs', 3 * ND).reshape(-1, 3)[NX:] - xd).max(), 1e-6)
        d = np.linalg.norm(c.floats('want', 3 * ND).reshape(-1, 3)[NX:] - F.lab709(np.clip(target(xd, 100), 0, 1)), axis=1)
        self.assertLess(d.mean(), 0.05); self.assertLess(d.max(), 0.5)
        wd = c.floats('w', ND)[NX:]
        self.assertTrue((wd[NXW:] == 1).all())
        self.assertLess(np.abs(wd[:NXW] - np.sqrt((1 - 2.5 * F.saturation(np.clip(target(xd[:NXW], 0), 0, 1)) / 8) ** 8)).max(), 0.02)
        # the score: the chain on the checker vs the camera's own target Lab
        lab = F.lab709(self.jft.chain(chk, P, bt * F.TONE_MAX, split=True))
        dE = np.linalg.norm(lab - c.floats('chkw', 3 * NCHK).reshape(-1, 3), axis=1)
        want = (dE.mean(), np.percentile(dE, 95), dE.max())
        for a, b in zip(u['stats'], want):
            self.assertAlmostEqual(a, b, delta=0.006)          # x 100, rounded

    @staticmethod
    def rgba(rgb):
        q = np.round(np.clip(np.asarray(rgb, float), 0, 1) * 255).astype(int)
        return [int(r) << 24 | int(g) << 16 | int(b) << 8 | 0xFF for r, g, b in q]

    @staticmethod
    def channels(v):
        return np.array([v >> 24 & 255, v >> 16 & 255, v >> 8 & 255])

    def test_the_chart_shows_target_and_fit_and_stays_after_the_finish(self):
        """Bei 11-07: the ColorChecker while it converts -- each patch's top the cube's colour (the target), its
        bottom the fit's, updated as it fits, the match shown; the result left up when done (until a key)."""
        c = self.cam()
        before = len(c.posts)
        self.start(c, 'H.cube')
        names = [f'LC_P{k:02d}' for k in range(48)]
        self.assertEqual(c.vars['LC_Chart'][1], 1)
        self.assertEqual(c.vars['LC_Bar'][1], 0)
        # tops: the cube's render of the 0 EV checker (C->chki, Q20), as 0xRRGGBBAA; bottoms: not yet
        _a, snap = c.conv_area()
        raw = bytes(c.mu.mem_read(c.conv_mem() + OFF['chki'], 72 * 12))
        chki = np.frombuffer(raw, '<i4').reshape(72, 3) / float(1 << 20)
        tops = self.rgba(chki[24:48])
        self.assertEqual([c.vars[names[2 * p]][1] for p in range(24)], tops)
        self.assertEqual({c.vars[names[2 * p + 1]][1] for p in range(24)}, {0x222222FF})
        # the cube's colours, as the host renders them (lv_fit.make_target, 100 %)
        from cube import Cube
        target = F.make_target(Cube.read(self.cubes['H.cube']), space='srgb', gamma='gamma26')
        host = self.rgba(np.clip(target(E.sample_sets()['色卡'][24:48], 100), 0, 1))
        self.assertLessEqual(max(np.abs(self.channels(a) - self.channels(b)).max() for a, b in zip(tops, host)), 2)
        c.run_worker()
        posts = c.posts[before:]
        bottoms = [v for n, v in posts if n in names[1::2] and v != 0x222222FF]
        self.assertGreaterEqual(len(bottoms), 24)                      # the fit's colours, posted as it went
        matches = [v for n, v in posts if n == 'LC_Match']
        ticks = c.conv()['ticks']
        self.assertGreaterEqual(ticks, 1)
        self.assertEqual(len(matches), 1 + 3 + ticks + 1)            # open, each v1 start and the seed, every step, the result
        bars = [v for n, v in posts if n == 'LC_Bar']
        self.assertEqual(bars[-1], 640)
        self.assertEqual(bars, sorted(bars))
        # the result: the chain on the best solution, against the host twin (joint_fit_eval.chain)
        P = c.floats('best', 148)
        bt = c.floats('bt', 3 * 2048).reshape(3, 2048)
        chk = c.floats('chk', 3 * NCHK).reshape(-1, 3)
        want = self.rgba(self.jft.chain(chk[24:48], P, bt * F.TONE_MAX, split=True))
        got = [c.vars[names[2 * p + 1]][1] for p in range(24)]
        self.assertLessEqual(max(np.abs(self.channels(a) - self.channels(b)).max() for a, b in zip(got, want)), 1)
        self.assertEqual([c.vars[names[2 * p]][1] for p in range(24)], tops)   # the targets stay
        c.notify('LC_Key', 90)                                          # the finish: the box goes, the chart stays
        u = self.jft.unpack(c.files[next(p for p in c.files if p.endswith('.JFT') and p.startswith('\\fpSup\\LUTDATA\\'))])
        pct = self.jft.match_percent(u['stats'][0])
        self.assertEqual(c.vars['LC_Match'][1], f'Match {pct}%')
        self.assertEqual((c.vars['LC_Busy'][1], c.vars['LC_Chart'][1]), (0, 1))
        c.press(31)                                                     # the next key takes it down
        self.assertEqual(c.vars['LC_Chart'][1], 0)

    def test_extreme_solutions_quantise_as_jft_py(self):
        """conv_pack on synthetic solutions (a matrix beyond Q9: shift 1 / 2; hue moves; big gains; a YGAM bend)
        against jft.quantise -- what one emulated iteration cannot reach."""
        c = self.cam()
        self.start(c); c.run_worker()                              # the work area is held until conv_finish
        base = c.floats('best', 148)
        bt = c.floats('bt', 3 * 2048).reshape(3, 2048)
        rng = np.random.default_rng(3)
        repack = c.block() + self.repack_off
        _api, state = c.lut()
        for scale in (1.0, 1.6, 3.2):
            P = base.copy()
            P[:9] = (np.eye(3) * 1.1 + rng.normal(0, 0.3, (3, 3))).ravel() * scale
            P[9:18] = P[:9] + rng.normal(0, 0.15, 9) * scale                 # JFIT v5: set 1 its own
            P[18:45] = rng.normal(0, 0.03, 27)
            P[51:75] = rng.uniform(-40, 40, 24); P[75:99] = rng.uniform(0.3, 2.5, 24); P[99:123] = rng.uniform(0.5, 1.8, 24)
            P[123:140] = np.sort(rng.uniform(0, 1, 17))
            P[140:148] = np.ravel([[rng.uniform(0, 0.52), rng.uniform(0, 1.7)] for _ in range(4)]) if scale != 1.6 else self.jft.knee_off(P)[140:]   # JFIT v6
            c.mu.mem_write(c.conv_mem() + OFF['best'], P.astype('<f4').tobytes())
            rc, _ = c.call(repack & ~1, r0=state, thumb=True)
            data = bytes(c.mu.mem_read(c.conv_mem() + self.jft_off, JFT_BYTES))
            P32 = P.astype(np.float32).astype(float)
            try:
                hw = self.jft.quantise(P32, bt)
            except ValueError:
                self.assertNotEqual(rc, 0, scale); continue
            self.assertEqual(rc, 0, scale)
            got = self.jft.unpack(data)['hw']
            self.assertEqual(got['shift'], hw['shift'], scale); self.assertEqual(got['m2'], hw['m2'], scale)
            self.assertEqual(got['m1'], hw['m1'], scale); self.assertNotEqual(got['m1'], got['m2'])
            self.assertLessEqual(int(np.abs(np.asarray(got['tone'], int) - hw['tone']).max()), 1, scale)
            for a, b in zip(sum(got['ceq'], []), sum(hw['ceq'], [])):
                self.assertLessEqual(min(abs(a - b), 65536 - abs(a - b)), 1, scale)
            self.assertEqual(got['ygam'], hw['ygam'], scale)
            self.assertLessEqual(max(abs(a - b) for a, b in zip(got['ycmat'], hw['ycmat'])), 1)
            self.assertEqual(got['knee'] is None, hw['knee'] is None, scale)
            if hw['knee']:
                self.assertLessEqual(max(abs(a - b) for a, b in zip(got['knee'], hw['knee'])), 1, scale)
            # dh uniform +-40: out of order before the clamp; both sides pack it in order (jf_hue_safe / jft.hue_safe)
            self.assertFalse(min(15 + np.roll(P32[51:75], -1) - P32[51:75]) >= self.jft.HUE_GAP, scale)
            self.assertTrue(self.jft.hue_in_order(got['ceq'][2]), (scale, self.jft.hue_steps(got['ceq'][2])))
            chk = c.floats('chk', 3 * NCHK).reshape(-1, 3)
            dE = np.linalg.norm(F.lab709(self.jft.chain(chk, P32, bt * F.TONE_MAX, split=True)) -
                                c.floats('chkw', 3 * NCHK).reshape(-1, 3), axis=1)
            for a, b in zip(self.jft.unpack(data)['stats'], (dE.mean(), np.percentile(dE, 95), dE.max())):
                self.assertAlmostEqual(a, b, delta=0.006)
            seen = getattr(self, '_shifts', set()); seen.add(hw['shift']); self._shifts = seen
        self.assertTrue({1, 2} & self._shifts, self._shifts)            # the shift path was exercised
        c.notify('LC_Key', 90)
        self.assertEqual(NS.borrows(c)[2], {})

    def test_one_at_a_time_and_nothing_moves_meanwhile(self):
        c = self.cam()
        self.start(c, 'M.cube')
        before = c.saved_files().get(LN.BIN)
        c.choose(self.other(), 1)
        self.assertEqual(c.conv()['index'], self.entry()[0])          # still M's
        self.assertEqual(len(c.cv_wakes), 1)
        self.assertEqual(c.saved_files().get(LN.BIN), before)         # no library write
        c.choose(self.other(), 0)                                     # nor an Off
        self.assertEqual(c.saved_files().get(LN.BIN), before)
        k, _ = c.find_row('M.cube'); c.ael(k)
        self.assertFalse(c.in_settings())                             # the settings wait
        self.assertEqual(c.vars['LC_OK'][1], 'Converting 0%')

    def other(self):
        return next(e['filename'] for e in self.ldoc['luts'] if e['filename'] != 'M.cube')

    def test_a_write_failure_turns_nothing_on(self):
        c = self.cam()
        self.start(c)
        c.run_worker()
        c.jft_write_ok = False
        c.notify('LC_Key', 90)
        st = c.conv()
        self.assertEqual((st['state'], st['last']), (0, 6))           # CVE_WRITE
        self.assertEqual(c.clist()['n'], 0)
        self.assertEqual(c.vars['LC_OK'][1], 'Convert failed')

    # ---- native/borrow.c (2026-11-07): the conversion's memory is borrowed for it, then returned
    def kept(self, c):
        """The block's long-lived parts (lvb's region, the ISP roots, conv's resident state)."""
        conv_off = struct.unpack_from('<I', c.files[LN.BIN], 48 + 48)[0]
        return V.LvbNativeTests.kept(self, c) + [(c.block() + conv_off, 0x400)]

    def test_a_conversion_borrows_its_work_area_and_returns_everything(self):
        c = self.cam()
        g0, f0, out = NS.borrows(c)
        self.assertEqual((g0, out), (f0, {}))
        self.start(c, 'H.cube')
        g, f, out = NS.borrows(c)
        self.assertEqual((g - g0, f - f0), (3, 2))                     # asset + samples back already; the work kept
        (q, n), = out.items()
        self.assertTrue(c.CONV_WORK[0] < n < c.CONV_WORK[1], n)
        self.assertEqual(NS.dangling(c, self.kept(c)), [])
        c.run_worker()
        self.assertEqual(NS.borrows(c)[2], out)                         # the worker's until the finish
        c.notify('LC_Key', 90)
        g, f, out = NS.borrows(c)
        self.assertEqual((g, out), (f, {}))
        self.assertEqual((c.conv()['last'], c.clist()['n']), (0, 1))
        self.assertEqual(NS.dangling(c, self.kept(c)), [])              # no lvb set / clist record / root into it

    def test_every_conversion_failure_returns_its_areas(self):
        """write failure, a cube that will not load, the allocator saying no, recording: "Convert failed",
        nothing on, nothing kept borrowed (and nothing asked for at all while recording)."""
        for case in ('write', 'cube', 'memory', 'recording'):
            with self.subTest(case):
                c = self.cam()
                c.manager()
                g0 = NS.borrows(c)[0]
                if case == 'cube': c.files.pop(LN.FOLDER + 'H.cube')
                if case == 'memory': c.borrow_fail = lambda n: c.CONV_WORK[0] < n < c.CONV_WORK[1]
                if case == 'recording': NS.recording(c)
                c.choose('H.cube', 1)
                if case == 'write':
                    c.run_worker(); c.jft_write_ok = False; c.notify('LC_Key', 90)
                    self.assertEqual(c.conv()['last'], 6)                # CVE_WRITE
                else:
                    self.assertEqual(c.conv()['state'], 0)
                    self.assertEqual(c.conv()['err'], 3 if case == 'cube' else 8)   # CVE_FIT / CVE_MEMORY
                    self.assertEqual(c.cv_wakes, [])
                if case == 'recording': NS.recording(c, False)
                self.assertEqual(c.vars['LC_OK'][1], 'Convert failed')
                g, f, out = NS.borrows(c)
                self.assertEqual((g, out), (f, {}))
                if case == 'recording': self.assertEqual(g, g0)
                self.assertEqual(c.clist()['n'], 0)
                self.assertEqual(NS.dangling(c, self.kept(c)), [])

    # ---- JFIT v3 (Bei 2026-11-07): "xlm10+144" -- jf_fit 2 x 20 on the ordinary samples, then jf_fit_direct 10 from
    # the cheaper on + the 144 HSV, as jft.convert (jft.route)
    def host_route(self, c):
        """the camera's own inputs (after a run), through the host's route at conv.iters 1"""
        xs = c.floats('xs', 3 * NX).reshape(-1, 3); want = c.floats('want', 3 * NX).reshape(-1, 3)
        w = c.floats('w', NX); bt = c.floats('bt', 3 * 2048).reshape(3, 2048); m0 = c.floats('m0', 9).reshape(3, 3)
        starts = [np.r_[M0.ravel(), M0.ravel(), np.zeros(27), E.POST_ID] for M0 in (np.eye(3), m0)]
        return (xs, want, w, bt), starts, self.jft.route(xs, want, w, bt, starts, N, 1)

    def test_the_fit_is_jft_convert_s_route(self):
        """the 144 HSV samples after the grid and the greys (weight 1, the cube's target); from the camera's own
        inputs the host's route (jf_fit 1 step from each start on the first N samples, the cheaper refined by
        jf_fit_direct 1 step on all NX) gives the camera's refined solution, seed and other start and their costs;
        the whole host conversion (jft.convert) runs the same route."""
        c = self.cam()
        self.start(c, 'H.cube'); c.run_worker()
        (xs, want, w, bt), starts, (cands, costs) = self.host_route(c)
        hsv = self.jft.hsv_samples()
        self.assertEqual(hsv.shape, (NHSV, 3))
        self.assertLess(np.abs(xs[N:] - hsv).max(), 1e-6)                    # the floats jft fits (ARM VFP vs host: 1 ulp)
        self.assertTrue((w[N:] == 1).all())
        from cube import Cube
        target = F.make_target(Cube.read(self.cubes['H.cube']), space='srgb', gamma='gamma26')
        d = np.linalg.norm(want[N:] - F.lab709(target(hsv, 100)), axis=1)
        self.assertLess(d.mean(), 0.05); self.assertLess(d.max(), 0.5)
        self.assertEqual(c.conv()['ticks'], 4)                                # one step per v1 start, the refine's, the untied's
        P, _hw = self.jft.choose(cands, bt)
        self.assertIs(P, cands[0])                                            # the refined one packs (H)
        # (JFIT v5: conv_untie keeps the v4 result in prod; best is the kept one)
        best, alt, alt2, cost = c.floats('prod', 140), c.floats('alt', 140), c.floats('alt2', 140), c.floats('cost', 3)
        # the v1 stage: the host's seed and other start are the camera's (ARM VFP vs host: a few ulp per sum)
        for got, ref in ((alt, cands[1]), (alt2, cands[2])):
            self.assertLess(np.abs(got - ref).max(), 2e-3)
        for got, ref in zip(cost[1:], costs[1:]):
            self.assertAlmostEqual(got / ref, 1, delta=1e-3)
        self.assertLess(cost[1], cost[2])                                     # alt is the cheaper: the seed
        # the refine: from the camera's own seed, the host's jf_fit_direct on all NX is the camera's best (one LM
        # step amplifies the v1 stage's ulps: 0.04 in a CEQ hue from the host's own seed, so the seed is shared here)
        Pr, cr = self.jft.native_direct(xs, want, w, bt, alt, 1)
        self.assertLess(np.abs(best - Pr).max(), 2e-3)
        self.assertAlmostEqual(cost[0] / cr, 1, delta=1e-3)
        self.assertLess(np.abs(best - cands[0]).max(), 0.1)                   # and near the host's whole route
        self.assertAlmostEqual(cost[0] / costs[0], 1, delta=1e-2)
        self.assertFalse(np.allclose(best, alt))                              # the refine moved it
        # JFIT v5, the untied refine: from the camera's own v4 result (prod) on its own dense set (ND), the host's
        # jf_fit_untied (1 step) is the camera's untied solution (J.P; best when kept); the choice by the packed cost
        X = c.floats('xs', 3 * ND).reshape(-1, 3); WANT = c.floats('want', 3 * ND).reshape(-1, 3); W = c.floats('w', ND)
        Pu, cu = self.jft.native_untied(X, WANT, W, bt, best, 1)
        Pu[51:75] = self.jft.hue_safe(Pu[51:75])
        at, _snap = c.conv_area()
        Pcam = np.frombuffer(bytes(c.mu.mem_read(at + OFF['J'] + JP, 592)), '<f4').astype(float)
        print(f'\n  untied step: camera vs host |dP| {np.abs(Pcam - Pu).max():.1e}, |M1 - M2| {np.abs(Pcam[9:18] - Pcam[:9]).max():.3f}')
        self.assertLess(np.abs(Pcam - Pu).max(), 2e-3)
        self.assertGreater(np.abs(Pcam[9:18] - Pcam[:9]).max(), 1e-3)         # set 1 moved off set 2
        ucost = c.floats('ucost', 3); untie, knee = struct.unpack('<2I', bytes(c.mu.mem_read(at + OFF['untie'], 8)))
        hw4 = self.jft.quantise(best, bt)
        c0 = self.jft.packed_cost(self.jft.payload(hw4), X, WANT, W)
        self.assertAlmostEqual(ucost[0] / c0, 1, delta=1e-4)                 # the v4 one's packed cost, as the host's
        # JFIT v6: ucost[1] the refine's tables with the CKNEE off, ucost[2] with it; the knee only when cheapest
        self.assertEqual(knee, 1 if ucost[2] < ucost[0] and ucost[2] < ucost[1] else 0)
        self.assertEqual(untie, 1 if knee or ucost[1] < ucost[0] else 0)
        self.assertEqual((untie, knee), (1, 1))                               # H: the untied one with its knee, kept
        self.assertTrue(self.jft.knee_on(Pu)); self.assertTrue(self.jft.knee_on(Pcam))
        self.assertTrue((c.floats('best', 148).astype(np.float32) == Pcam.astype(np.float32)).all())
        self.assertAlmostEqual(ucost[2] / self.jft.packed_cost(self.jft.payload(self.jft.quantise(Pcam, bt)), X, WANT, W), 1, delta=1e-4)
        self.assertAlmostEqual(ucost[1] / self.jft.packed_cost(self.jft.payload(self.jft.quantise(self.jft.knee_off(Pcam), bt)), X, WANT, W), 1, delta=1e-4)
        c.notify('LC_Key', 90)
        u = self.jft.unpack(c.files[next(p for p in c.files if p.endswith('.JFT') and p.startswith('\\fpSup\\LUTDATA\\'))])
        self.assertEqual(u['jfit_version'], self.jft.JFIT_VERSION)
        self.assertEqual(self.jft.JFIT_VERSION, 7)
        self.assertNotEqual(u['hw']['m1'], u['hw']['m2'])                     # the file carries set 1 apart
        self.assertEqual(u['hw']['knee'], self.jft.knee_codes(Pcam))          # ... and the CKNEE (JFIT v6)
        # jft.convert runs the same route: jf_fit on the first N (these samples and weights), the identity then lvb's
        # start, CONV_ITERS each; then jf_fit_direct from the cheaper of the two on all NX, CONV_DIRECT_ITERS
        # (its lvb start is the host's E.fit_lvb, not the camera's lvb_fit: the solutions themselves differ)
        calls, rf, rd, ru = [], self.jft.native_fit, self.jft.native_direct, self.jft.native_untied

        def spy_fit(xs_, want_, w_, bt_, P0, iters=10):
            out = rf(xs_, want_, w_, bt_, P0, iters); calls.append(('fit', np.asarray(xs_), np.asarray(w_), np.asarray(P0), iters, out))
            return out

        def spy_direct(xs_, want_, w_, bt_, P0, iters=None):
            out = rd(xs_, want_, w_, bt_, P0, iters); calls.append(('direct', np.asarray(xs_), np.asarray(w_), np.asarray(P0), iters, out))
            return out
        def spy_untied(xs_, want_, w_, bt_, P0, iters=None, **kw):
            self.assertEqual(kw, dict(knee=True))                             # JFIT v6: the CKNEE free
            out = ru(xs_, want_, w_, bt_, P0, iters, **kw); calls.append(('untied', np.asarray(xs_), np.asarray(w_), np.asarray(P0), iters, out))
            return out
        with unittest.mock.patch.object(self.jft, 'native_fit', spy_fit), \
                unittest.mock.patch.object(self.jft, 'native_direct', spy_direct), \
                unittest.mock.patch.object(self.jft, 'native_untied', spy_untied):
            _data, stats = self.jft.convert(self.cubes['H.cube'], *self.H_KEY, 100)
        self.assertEqual([k[0] for k in calls], ['fit', 'fit', 'direct', 'untied'])
        _kind, hx, hw_, P0, iters, _out = calls[3]                            # the untied refine: from the v4 result, on
        self.assertEqual(iters, self.jft.CONV_UNTIE_ITERS)                    # the conversion's samples + the dense extras
        self.assertEqual(len(hx), ND); self.assertLess(np.abs(hx - X).max(), 1e-5)
        self.assertLess(np.abs(hw_ - W).max(), 0.02)
        self.assertTrue((P0[9:18] == P0[:9]).all())
        for k, (_kind, hx, hw_, P0, iters, _out) in enumerate(calls[:2]):
            self.assertEqual(iters, self.jft.CONV_ITERS)
            self.assertEqual(len(hx), N); self.assertLess(np.abs(hx - xs[:N]).max(), 1e-5)
            self.assertLess(np.abs(hw_ - w[:N]).max(), 0.02)
            if not k: self.assertEqual(P0[:18].tolist(), np.r_[np.eye(3).ravel(), np.eye(3).ravel()].tolist())
        _kind, hx, hw_, P0, iters, (Pr, _c) = calls[2]
        self.assertEqual(iters, self.jft.CONV_DIRECT_ITERS)
        self.assertLess(np.abs(hx - xs).max(), 1e-5)
        self.assertTrue((hw_[N:] == 1).all()); self.assertLess(np.abs(hw_[:N] - w[:N]).max(), 0.02)
        seed = min(calls[:2], key=lambda k: k[5][1])[5][0]
        self.assertTrue((P0 == seed).all())                                   # from the cheaper v1 solution
        self.assertEqual((self.jft.CONV_ITERS, self.jft.CONV_DIRECT_ITERS, self.jft.CONV_UNTIE_ITERS), (20, 10, 40))
        # the camera's own counts when conv.iters is 0 (20 + 20 + 10 emulated steps are too slow to run here)
        import re
        src = (V.ROOT_DIR / 'fpSup/lut/native/conv.c').read_text()
        self.assertEqual(int(re.search(r'#define CONV_ITERS\s+(\d+)u', src).group(1)), self.jft.CONV_ITERS)
        self.assertEqual(int(re.search(r'#define CONV_DIRECT_ITERS\s+(\d+)u', src).group(1)), self.jft.CONV_DIRECT_ITERS)
        self.assertEqual(int(re.search(r'#define CONV_UNTIE_ITERS\s+(\d+)u', src).group(1)), self.jft.CONV_UNTIE_ITERS)
        self.assertIn('J->iters = s->conv.iters ? s->conv.iters : CONV_UNTIE_ITERS;', src)
        self.assertIn('jf_fit_untied(J, C->amax, J->iters, 1);', src)
        self.assertIn('if (!rc) rc = conv_untie(s, C);', src)
        self.assertIn('J->iters = s->conv.iters ? s->conv.iters : CONV_ITERS;', src)
        self.assertIn('J->iters = s->conv.iters ? s->conv.iters : CONV_DIRECT_ITERS;', src)
        self.assertIn('C->cost[0] = jf_fit_direct(J, C->amax, J->iters);', src)
        self.assertIn('J->w_mono = JF_W_MONO;', src)                     # the hue-order hinge, as jfit_host.c (11-10)
        self.assertEqual(self.jft.unpack(_data)['jfit_version'], 7)

    def test_the_seed_is_the_cheaper_v1_start(self):
        """jft.seed_order as conv_compute: the cheaper first, a tie keeps the identity's, a NaN goes last"""
        a, b = ('I', 1.0), ('L', 2.0)
        self.assertEqual(self.jft.seed_order([a, b]), [a, b])
        self.assertEqual(self.jft.seed_order([b, a]), [a, b])
        self.assertEqual(self.jft.seed_order([('I', 1.0), ('L', 1.0)])[0][0], 'I')
        self.assertEqual(self.jft.seed_order([('I', float('nan')), b])[0], b)
        self.assertEqual(self.jft.seed_order([b, ('L', float('nan'))])[0], b)

    def test_progress_and_the_chart_through_both_stages(self):
        """the bar only grows over the v1 starts and the refine (Bei: monotonic), each stage's steps reach it; the
        chart's fits are posted in both stages, and each match posted is the chain on the P it shows (J->tone its)."""
        c = self.cam()
        before = len(c.posts)
        self.start(c, 'H.cube'); c.run_worker()
        posts = c.posts[before:]
        bars = [v for n, v in posts if n == 'LC_Bar']
        texts = [v for n, v in posts if n == 'LC_OK' and isinstance(v, str) and v.startswith('Converting')]
        pcts = [int(t[len('Converting '):-1]) for t in texts]
        self.assertEqual(pcts, sorted(pcts)); self.assertEqual(bars, sorted(bars))
        # conv.iters 1: each stage ends on its own share -- 24, 43, 47, 99 (conv.c CONV_SPAN_*; JFIT v5's untied 47 .. 99)
        self.assertEqual([p for p in pcts if p], [24, 43, 47, 99])
        self.assertEqual(bars[-1], 640)
        # the chart: open, then 3 stage starts + 4 steps + the result; the fits between change in every stage
        idx = [k for k, (n, _v) in enumerate(posts) if n == 'LC_Match']
        self.assertEqual(len(idx), 1 + 3 + 4 + 1)
        ticks = [k for k, (n, v) in enumerate(posts) if n == 'LC_OK' and isinstance(v, str) and v.startswith('Converting ') and v != 'Converting 0%']
        self.assertEqual(len(ticks), 4)
        self.assertGreater(ticks[2], idx[5])                                   # the refine's tick after the seed's chart
        fits = lambda lo, hi: [v for n, v in posts[lo:hi] if n in [f'LC_P{k:02d}' for k in range(1, 48, 2)]]
        self.assertTrue(fits(idx[1], idx[3]))                                  # posted during the v1 stage
        self.assertTrue(fits(idx[4], idx[7]))                                  # and during the refines
        # the last step's chart (the untied refine's tick) is the chain (split) on its P: every half posted by then
        # equals the chain on best when best is the untied one (H: kept)
        (xs, want, w, bt), _starts, (cands, _costs) = self.host_route(c)
        chk = c.floats('chk', 3 * NCHK).reshape(-1, 3)
        shown = {}
        for n, v in posts[:idx[8]]:
            if n.startswith('LC_P'): shown[n] = v
        want_ = self.rgba(self.jft.chain(chk[24:48], c.floats('best', 148), bt * F.TONE_MAX, split=True))
        got = [shown[f'LC_P{2 * p + 1:02d}'] for p in range(24)]
        self.assertLessEqual(max(np.abs(self.channels(a) - self.channels(b)).max() for a, b in zip(got, want_)), 1)
        c.notify('LC_Key', 90)

    def test_the_candidates_are_packed_in_order_the_first_that_packs(self):
        """refined, then the v1 seed, then the other v1 start: the first that quantises is packed and left in best
        (a YCMAT overflow of one must not fail the conversion: FITTER_OPTIMIZATION, conv_choose); costs follow."""
        c = self.cam()
        self.start(c); c.run_worker()
        good = c.floats('best', 148).astype(np.float32)
        bt = c.floats('bt', 3 * 2048).reshape(3, 2048)
        bad = good.copy(); bad[45] = -0.1                                     # YCMAT Y of R < 0: does not pack
        g = [good.copy() for _ in range(3)]
        for k in range(3): g[k][123 + 8] = good[123 + 8] - 0.01 * k           # three that pack, told apart (a YGAM knot)
        _api, state = c.lut()
        at = c.conv_mem()

        def run(b, a, a2, costs=(3.0, 1.0, 2.0)):
            c.mu.mem_write(at + OFF['best'], b.astype('<f4').tobytes())
            c.mu.mem_write(at + OFF['alt'], a.astype('<f4').tobytes())
            c.mu.mem_write(at + OFF['alt2'], a2.astype('<f4').tobytes())
            c.mu.mem_write(at + OFF['cost'], np.array(costs, '<f4').tobytes())
            rc, _ = c.call((c.block() + self.choose_off) & ~1, r0=state, thumb=True)
            return rc, c.floats('best', 148), c.floats('cost', 3), bytes(c.mu.mem_read(at + self.jft_off, JFT_BYTES))
        for cands, k in (((g[0], g[1], g[2]), 0), ((bad, g[1], g[2]), 1), ((bad, bad, g[2]), 2), ((g[0], bad, g[2]), 0),
                         ((bad, g[1], bad), 1)):
            rc, got, cost, data = run(*cands)
            self.assertEqual(rc, 0, k)
            self.assertTrue((got.astype(np.float32) == g[k]).all(), k)             # not the cheaper: the order
            self.assertEqual(cost[0], (3.0, 1.0, 2.0)[k])                          # its cost with it
            want = self.jft.quantise(g[k].astype(float), bt)
            hw = self.jft.unpack(data)['hw']
            self.assertEqual((hw['m2'], hw['ygam']), (want['m2'], want['ygam']))
            self.assertLessEqual(max(abs(x - y) for x, y in zip(hw['ycmat'], want['ycmat'])), 1)
            P, _hw = self.jft.choose([x.astype(float) for x in cands], bt)        # the host twin
            self.assertTrue((P == g[k].astype(float)).all(), k)
        self.assertNotEqual(self.jft.quantise(g[0].astype(float), bt)['ygam'], self.jft.quantise(g[2].astype(float), bt)['ygam'])
        rc, *_ = run(bad, bad, bad)
        self.assertEqual(rc, 5)                                               # none: CVE_YCMAT, Convert failed
        with self.assertRaises(ValueError):
            self.jft.choose([bad.astype(float)] * 3, bt)
        c.notify('LC_Key', 90)
        self.assertEqual(NS.borrows(c)[2], {})

    def test_an_older_jfit_file_is_converted_again(self):
        """JFIT_VERSION 7 (11-11, the CKNEE slope / 16): a v1 .. v6 file (+40 = 1 .. 6) is stale -- no score, On converts;
        a v7 one turns on as is."""
        for old in (1, 2, 3, 4, 5, 6):
            with self.subTest(old):
                c = type('Old', (ConvertedOld,), dict(jfit=old))(self.lfiles, self.ar); c.stubs_on = True
                self.assertEqual(c.clist()['n'], 0)                           # not shown on: no row until converted
                c.manager(); c.choose(self.other(), 0); c.choose(self.other(), 1)
                self.assertEqual(len(c.cv_tasks), 1)
                self.assertEqual(c.conv()['state'], 1)

    def test_a_converted_cube_turns_on_without_converting(self):
        c = Converted(self.lfiles, self.ar); c.stubs_on = True
        c.manager(); c.choose(self.other(), 0); c.choose(self.other(), 1)
        self.assertEqual(c.cv_tasks, [])
        self.assertEqual(c.conv()['state'], 0)


    # ---- the settings page's "Color chart" row (Bei 2026-11-07): the chart kept in the .JFT, shown again
    CVV = dict(shown=0, busy=1, read=2, head=3, block=4)            # conv.c CVV_*
    KEEP_VIEW = 868                                                 # struct conv_keep: view_rc, view_n

    def view(self, c):
        conv_off = struct.unpack_from('<I', c.files[LN.BIN], 48 + 48)[0]
        return struct.unpack_from('<2I', bytes(c.mu.mem_read(c.block() + conv_off + self.KEEP_VIEW, 8)))

    def jft_path(self, name):
        _i, e = self.entry(name)
        return '\\' + self.jft.path_for(LN.L.record_identity(e).hex()).replace('/', '\\')

    @staticmethod
    def put_file(c, path, data):
        """the card's file now (the harness reads a file written this run from c.written)"""
        c.files[path] = data
        if path in c.written: c.written[path] = data

    def converted(self, name='H.cube'):
        """A camera that converted `name`, finished, the chart closed: (camera, the file, its chart as shown)."""
        c = self.cam()
        self.start(c, name); c.run_worker()
        P = c.floats('best', 148); bt = c.floats('bt', 3 * 2048).reshape(3, 2048); chk = c.floats('chk', 3 * NCHK).reshape(-1, 3)
        c.notify('LC_Key', 90)
        shown = [c.vars[f'LC_P{k:02d}'][1] for k in range(48)], c.vars['LC_Match'][1]
        c.press(31)                                                     # the next key: the chart down
        self.assertEqual(c.vars['LC_Chart'][1], 0)
        return c, c.files[self.jft_path(name)], shown, (P, bt, chk)

    def test_the_file_carries_the_chart_the_overlay_left(self):
        """the 24 targets, 24 fits and the match of the 0 EV checker, exactly the values conv.c posted last."""
        c, data, (patches, match), (P, bt, chk) = self.converted()
        self.assertEqual(len(data), JFT_FILE)
        u = self.jft.unpack(data)
        self.assertEqual(u['chart']['patches'], patches)                # what the overlay showed at the end
        self.assertEqual(f"Match {u['chart']['match']}%", match)
        self.assertEqual(u['chart']['match'], self.jft.match_percent(u['stats'][0]))
        self.assertNotIn(0x222222FF, patches)                          # every half posted
        # the host twin of the block: the same bytes from the same values, and the fits as joint_fit_eval.chain
        self.assertEqual(data[JFT_BYTES:], self.jft.chart_block(data[:JFT_BYTES], u['chart']))
        want = self.rgba(self.jft.chain(chk[24:48], P, bt * F.TONE_MAX, split=True))
        self.assertLessEqual(max(np.abs(self.channels(a) - self.channels(b)).max()
                                 for a, b in zip(patches[1::2], want)), 1)
        self.assertEqual(self.jft.rgba([[0.5, 1.2, -1]]), [0x80FF00FF])  # conv_rgba: half up, clamped
        # a damaged block is refused by the host reader; the core alone is a v2 file
        bad = bytearray(data); bad[JFT_BYTES + 20] ^= 1
        with self.assertRaises(ValueError): self.jft.unpack(bytes(bad))
        self.assertIsNone(self.jft.unpack(data[:JFT_BYTES])['chart'])
        self.assertEqual(self.jft.unpack(data[:JFT_BYTES])['hw']['ygam'], u['hw']['ygam'])

    def test_the_host_conversion_writes_the_block_too(self):
        data, stats = self.jft.convert(self.cubes['H.cube'], *self.H_KEY, 100)
        u = self.jft.unpack(data)
        self.assertEqual(len(data), JFT_FILE)
        self.assertEqual(u['chart']['match'], self.jft.match_percent(stats[0]))
        from cube import Cube
        target = F.make_target(Cube.read(self.cubes['H.cube']), space='srgb', gamma='gamma26')
        self.assertEqual(u['chart']['patches'][0::2], self.jft.rgba(target(E.sample_sets()['色卡'][24:48], 100)))

    def test_the_row_shows_the_chart_from_the_file_alone(self):
        """OK on "Color chart": the 48 halves and the match from the file's block (here rewritten, so they can only
        come from it), the chart up, nothing borrowed; any key takes it down, MENU too without leaving."""
        c, data, _shown, _ = self.converted()
        u = self.jft.unpack(data)
        mine = dict(match=42, patches=[(0x01020300 + 0x10000 * k) | 0xFF for k in range(48)])
        self.put_file(c, self.jft_path('H.cube'), data[:JFT_BYTES] + self.jft.chart_block(data[:JFT_BYTES], mine))
        c.edit('H.cube')
        self.assertTrue(c.in_settings())
        self.assertEqual((c.vars['LC_Chart'][1], c.vars['LC_ChartT'][1].strip()), (0, ''))
        g0, f0, out0 = NS.borrows(c)
        before = len(c.posts)
        c.press(81)                                                     # OK on the row (settings_y51.CHART_KEY)
        self.assertEqual(self.view(c), (self.CVV['shown'], 1))
        self.assertEqual([c.vars[f'LC_P{k:02d}'][1] for k in range(48)], mine['patches'])
        self.assertEqual((c.vars['LC_Match'][1], c.vars['LC_Chart'][1]), ('Match 42%', 1))
        self.assertEqual(c.vars['LC_ChartT'][1].strip(), '')
        self.assertEqual(NS.borrows(c), (g0 + 1, f0 + 1, out0))         # no asset, no work area: the .JFT buffer, back at once (11-10)
        self.assertNotIn('LC_Bar', [n for n, _v in c.posts[before:]])
        c.press(81)                                                     # the row again: down
        self.assertEqual(c.vars['LC_Chart'][1], 0)
        c.press(81); self.assertEqual(c.vars['LC_Chart'][1], 1)
        c.notify('LC_Focus', c.vars['LC_Focus'][1] + 1)                 # Up / Down: down
        self.assertEqual(c.vars['LC_Chart'][1], 0)
        c.press(81); self.assertEqual(c.vars['LC_Chart'][1], 1)
        seq = c.vars['LC_Back'][1]
        c.notify('LC_Key', 70)                                          # MENU: down, and the page stays
        self.assertEqual(c.vars['LC_Chart'][1], 0)
        self.assertEqual((c.vars['LC_Back'][1], c.back_text()), (seq, ''))
        c.notify('LC_Key', 70)                                          # MENU again: back to the manager
        self.assertEqual(c.back_text(), 'Return')
        self.assertNotEqual(c.vars['LC_Back'][1], seq)
        self.assertEqual(self.view(c)[1], 3)
        self.assertEqual(u['key'][0], LN.L.record_identity(self.entry('H.cube')[1])[:8])

    def test_a_v2_file_without_the_block_still_loads_and_the_row_asks_for_a_conversion(self):
        """a file converted before 11-07 (the core alone): the cube on, its tables from the file as before; the
        chart row says "Convert again" and shows nothing."""
        c, data, _shown, _ = self.converted()
        path = self.jft_path('H.cube')
        old = Camera(dict(self.lfiles, **{path: data[:JFT_BYTES]}), self.ar); old.stubs_on = True
        self.assertEqual(old.clist()['n'], 1)                           # on, no conversion asked for
        self.assertEqual(old.invoke(8, self.entry('H.cube')[0]), 0)      # picked (11-10: its set is made then)
        self.assertEqual(V.JftNativeTests.lvb_extra(self, old)['jfts'], 1)   # lvb_jft read it: the ISP tables
        old.edit('H.cube')
        pct = self.jft.match_percent(self.jft.unpack(data)['stats'][0])
        self.assertEqual(old.vars['LC_PageTitle'][1], f'H.cube  {pct}% match')
        g0 = NS.borrows(old)
        old.press(81)
        self.assertEqual(self.view(old)[0], self.CVV['block'])
        self.assertEqual((old.vars['LC_Chart'][1], old.vars['LC_ChartT'][1]), (0, 'Convert again'))
        self.assertEqual(NS.borrows(old), (g0[0] + 1, g0[1] + 1, g0[2]))   # the .JFT buffer only, back at once (11-10)
        self.assertEqual(old.cv_tasks, [])
        # no file at all (or a stranger's): the same words
        old.files.pop(path); old.written.pop(path, None); old.press(81)
        self.assertEqual((self.view(old)[0], old.vars['LC_ChartT'][1]), (self.CVV['read'], 'Convert again'))
        bad = bytearray(data); bad[JFT_BYTES + 100] ^= 1; self.put_file(old, path, bytes(bad)); old.press(81)
        self.assertEqual((self.view(old)[0], old.vars['LC_Chart'][1]), (self.CVV['block'], 0))
        bad = bytearray(data); struct.pack_into('<I', bad, 24, (self.H_KEY[0] + 1) % 8)   # another colour space's file
        self.put_file(old, path, bytes(bad)); old.press(81)
        self.assertEqual((self.view(old)[0], old.vars['LC_Chart'][1]), (self.CVV['head'], 0))
        self.put_file(old, path, data); old.press(81)                   # the new file: the chart
        self.assertEqual((self.view(old)[0], old.vars['LC_Chart'][1]), (self.CVV['shown'], 1))

    def test_a_converted_cube_is_picked_without_opening_it(self):
        """2026-11-10 (Bei: switching COLOR then MENU was slow): with its .JFT there, a pick (and the boot's load of the
        active entry) selects from the record alone -- the 65^3 .cube is neither opened nor parsed; the tables come
        from the file.  Without one the cube is still checked (test_library_native: a damaged cube; test_import_native:
        a malformed one; test_lvb_native: a refused borrow)."""
        _c, data, _shown, _ = self.converted()
        i = self.entry('H.cube')[0]
        c = Camera(dict(self.lfiles, **{self.jft_path('H.cube'): data}), self.ar); c.stubs_on = True
        self.assertNotEqual(c.status()['color'], self.H_KEY[0])            # not H's input before the pick
        n = len(c.opened)
        self.assertEqual(c.invoke(8, i), 0)
        self.assertNotIn(LN.FOLDER + 'H.cube', c.opened[n:])                # not opened
        self.assertIn(self.jft_path('H.cube'), c.opened[n:])               # its file instead
        st = c.status()
        self.assertEqual((st['color'], st['gamma'], st['asset'], st['last']), (*self.H_KEY, 0, 0))
        self.assertEqual(V.JftNativeTests.lvb_extra(self, c)['jfts'], 1)   # the ISP tables from the file
        again = Camera(c.saved_files(), self.ar)                           # the boot loads the active one the same way
        self.assertNotIn(LN.FOLDER + 'H.cube', again.opened)
        self.assertEqual((again.status()['color'], again.status()['gamma']), self.H_KEY)

    def test_the_row_is_refused_while_recording(self):
        c, data, _shown, _ = self.converted()
        c.edit('H.cube')
        g0 = NS.borrows(c)
        opens = len(getattr(c, 'opened', []))
        NS.recording(c)
        c.press(81)
        self.assertEqual(self.view(c)[0], self.CVV['busy'])
        self.assertEqual((c.vars['LC_Chart'][1], c.vars['LC_ChartT'][1]), (0, 'Recording busy'))
        self.assertEqual(NS.borrows(c), g0)
        NS.recording(c, False)
        c.press(81)
        self.assertEqual((self.view(c)[0], c.vars['LC_Chart'][1], c.vars['LC_ChartT'][1].strip()), (0, 1, ''))


if __name__ == '__main__':
    unittest.main()
