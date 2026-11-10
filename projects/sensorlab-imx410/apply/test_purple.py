#!/usr/bin/env python3
"""0.0.3test PURPLE TEST build (-DAP_REC_DELAY_TEST -DAP_PURPLE_TEST): the first-frame toggles under unicorn against
the real firmware image (validation/20261108-purple-stock-diff/README.md).

    cd projects/sensorlab-imx410/apply
    SL_EMU_COUNT=1 python3 -B -m unittest test_purple      # ~6 min
    SL_EMU_COUNT=1 python3 -B test_purple.py --mutate      # every mutant must make a test fail

The whole REC start runs as the firmware's own code: SetImgMode_s through the image controller's message-1 code
(standby, then the record switch when the mode differs), then C0379180's BL (the TEST hook) into the real
FUN_c030cf98 -> ContSet_Adr1, up to BUFA1's start.  ap.c's hooks are live.  Stubs: mmio_diff.py's (logging, waits,
semaphores, the LV pipeline sizing); the sensor writer is recorded.
"""
import os, pathlib, re, shutil, struct, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_argv = list(sys.argv)
import test_apply as T                                      # noqa: E402  (a mutant run: this directory's ap.c)
VAL = T.ROOT / 'projects/sensorlab-imx410/validation/20261108-purple-stock-diff'
sys.path.insert(1, str(VAL))
import stock_diff as SD                                     # noqa: E402
sys.argv[:] = _argv
MD = SD.MD
RD_DEF = ('AP_RESYNC=0', 'AP_REC_DELAY_TEST')               # the product's AP_RESYNC (0)
PT_DEF = RD_DEF + ('AP_PURPLE_TEST',)
RD = T.WORK + 0x300000
HDR = 16                                                    # struct ap_rd header words in the purple build
RW = 16                                                     # record words
REC_KEYS = 'seq ms t0 t1 t2 rc line0 line2 arm_us arm_line ff pad bits sw sw_dt cur'.split()
TWIN, NOWIN, ROWS, RWZM, SBSTOCK = 1, 2, 4, 8, 16
WIN_REGS = (0x0003, 0x0022, 0x0023, 0x0024, 0x0025)
RWZM_OFFS = (0x00, 0x04, 0x24, 0x2C, 0x64, 0xD4, 0xDC, 0xE4)


def cam_for(args, bits=0, smode=0, defines=PT_DEF):
    """an MCam of the given build, the rd attached with bits / smode before the commit, the recipe committed"""
    cam = MD.MCam(defines=defines)
    T.ff_window(cam)
    assert cam.init() == T.AP_OK
    if 'AP_PURPLE_TEST' in defines:
        cam.mu.mem_write(RD, bytes(4 * (HDR + 16 * RW)))
        assert cam.fn('ap_rd_attach', T.MEM, RD) == T.AP_OK
        cam.put(RD + 32, bits)
        cam.put(RD + 36, smode)
    return SD.setup_cam(cam, T.recipe(*args)[0])


def stock_cam(key):
    cam = MD.MCam()
    T.ff_window(cam)
    assert cam.init() == T.AP_OK
    e = cam.call(T.PICKER, 0, T.TAB3, cam.key(key))
    _, cam.pid, cam.mode = struct.unpack('<3I', cam.mu.mem_read(e, 12))
    return SD.setup_cam(cam)


def hdr(cam):
    w = struct.unpack('<16I', cam.mu.mem_read(RD, 64))
    return dict(zip('magic ms ver n sleeps clamped rec_words nmax bits smode live refused commits sw_total p0 p1'.split(), w))


def rec(cam, i):
    return dict(zip(REC_KEYS, struct.unpack(f'<{RW}I', cam.mu.mem_read(RD + 4 * HDR + 4 * RW * i, 4 * RW))))


def sensor_final(sens):
    d = {}
    for p in ('standby', 'switch', 'contset'):
        for a, v in sens[p]:
            d[a] = v
    return d


DEFC_ADDR = 0x300F0D84                                      # the defect table's DMA address >> 2 (the slot's buffer)


def regs_of(b, addrs, defc=False):
    return {a: struct.unpack_from('<I', b, a - 0x30000000)[0] for a in addrs if defc or a != DEFC_ADDR}


def written(*phs):
    return {a & ~3 for ph in phs for p in ph.values() for _, _, a, *_r in p}


_cache = {}


def stock30():
    """stock UHD 29.97 12-bit (TAB3 'UHD30' = pid 171, mode 7): its REC start from standby mode 8"""
    if 'stock30' not in _cache:
        cam = stock_cam('UHD30')
        ph, regs, sens = SD.rec_seq(cam, 8)
        _cache['stock30'] = (cam, ph, regs, sens, SD.rows(cam, cam.mode), SD.canvas(cam, cam.pid)[0])
    return _cache['stock30']


AE = {0x0005, 0x0006, 0x00D1}                               # SHS (AE) and the per-mode-set D1 toggle: not geometry


class PurpleTests(unittest.TestCase):
    def test_product_and_rec_delay_builds_are_untouched(self):
        """every AP_PURPLE_TEST block stripped (and #else kept) gives the same ARM image for the product and the
        REC-delay builds: the flag adds nothing elsewhere"""
        src = (HERE / 'ap.c').read_text()
        out, st = [], []                                     # st: (purple?, the enclosing keep)
        keep = True
        for line in src.splitlines(keepends=True):
            d = line.strip()
            if d.startswith('#if'):
                p = d.startswith('#ifdef AP_PURPLE_TEST')
                st.append((p, keep))
                if p:
                    keep = False
                    continue
            elif d.startswith('#else') and st and st[-1][0]:
                keep = st[-1][1]
                continue
            elif d.startswith('#endif') and st:
                p, outer = st.pop()
                if p:
                    keep = outer
                    continue
                if outer:
                    out.append(line)
                continue
            if keep:
                out.append(line)
        stripped = ''.join(out)
        self.assertNotIn('PT_', stripped)
        self.assertNotIn('AP_PURPLE_TEST', stripped)
        t = pathlib.Path(tempfile.mkdtemp(prefix='slpt-strip-'))
        try:
            for f in ('ap.c', 'ap_calc.c', 'ap.h', 'pb_glyph.h', 'pb_glyph.py', 'build_apply.py', 'pb_page.h'):
                if (HERE / f).exists():
                    shutil.copy(HERE / f, t / f)
            (t / 'ap.c').write_text(stripped)
            import build_apply as BA
            for d in ((), ('AP_REC_DELAY_TEST',)):
                a, _ = BA.arm(HERE, out_dir=pathlib.Path(tempfile.mkdtemp()), defines=d)
                b, _ = BA.arm(t, out_dir=pathlib.Path(tempfile.mkdtemp()), defines=d)
                self.assertEqual(a, b, d)
        finally:
            shutil.rmtree(t, ignore_errors=True)
        _, funcs = BA.arm(HERE, out_dir=pathlib.Path(tempfile.mkdtemp()), defines=PT_DEF)
        self.assertIn('ap_pt_latch', funcs)

    def test_bits_zero_is_the_rec_delay_build(self):
        """the purple build with no toggle: the same rows, canvas, REC-start writes and sensor writes as the REC-delay
        build (and the ring records the switch: standby 8 -> ours, one call into ours)"""
        a = cam_for(SD.UHD30)
        b = cam_for(SD.UHD30, defines=RD_DEF)
        self.assertEqual(SD.rows(a, a.mode), SD.rows(b, b.mode))
        self.assertEqual(SD.canvas(a, a.pid), SD.canvas(b, b.pid))
        self.assertEqual(SD.entry(a, T.TABS, 'MOV'), SD.entry(b, T.TABS, 'MOV'))
        pa, ra, sa = SD.rec_seq(a, 8, via_site=True)
        b.mu.mem_write(RD, bytes(4 * (8 + 16 * 12)))
        self.assertEqual(b.fn('ap_rd_attach', T.MEM, RD), T.AP_OK)
        pb, rb, sb = SD.rec_seq(b, 8, via_site=True)
        ws = written(pa, pb)
        self.assertEqual(regs_of(ra, ws), regs_of(rb, ws))
        self.assertEqual(sensor_final(sa), sensor_final(sb))
        h, q = hdr(a), rec(a, 0)
        self.assertEqual((h['magic'], h['ver'], h['rec_words'], h['n'], h['live'], h['refused'], h['commits']),
                         (0x594C4452, 2, 16, 1, 0, 0, 1))
        self.assertEqual(q['bits'], 0)
        self.assertEqual((q['sw'] & 0xFF, q['sw'] >> 8 & 0xFF, q['sw'] >> 16 & 0xFF, q['sw'] >> 24), (2, 8, a.mode, 1),
                         'standby 8 then the switch into ours: 2 calls, the last 8 -> ours')
        self.assertEqual(q['cur'], a.mode)

    def test_twin_standby_switches_at_rec_start(self):
        """bit 0: the MOV answer is id + 2; every lookup answers the twin with the slot's rows; a standby on the twin
        makes the REC start run SetImgMode_s into ours (without it, a standby already in ours skips it)"""
        cam = cam_for(SD.UHD30, bits=TWIN)
        self.assertEqual(SD.entry(cam, T.TABS, 'MOV')[2], cam.mode + 2)
        self.assertEqual(SD.rows(cam, cam.mode + 2), SD.rows(cam, cam.mode))
        self.assertEqual(SD.entry(cam, T.TAB3, 'UHD30')[2], cam.mode, 'the record entry is ours')
        ph, regs, sens = SD.rec_seq(cam, cam.mode + 2, via_site=True)
        self.assertTrue(cam.switched)
        q = rec(cam, 0)
        self.assertEqual((q['bits'] & 0xFF, q['sw'] & 0xFF, q['sw'] >> 8 & 0xFF, q['sw'] >> 16 & 0xFF, q['sw'] >> 24),
                         (TWIN, 2, cam.mode + 2, cam.mode, 1))
        self.assertEqual(sum(1 for a, v in sens['switch'] if a == 0x0011), 2, '0011 0 -> 1: the sensor restarted')
        src = T.WORK + 0xF800                                 # a second REC start, no switch in between
        cam.run(SD.bl_target(SD.REC_SITE, cam.w(SD.REC_SITE)), 0x11, src, 0x33)
        q2 = rec(cam, 1)
        self.assertEqual((q2['seq'], q2['sw'] & 0xFF, q2['sw'] >> 24, q2['cur']), (2, 0, 0, cam.mode), 'counts restart per take')
        ref = cam_for(SD.UHD30)
        ph2, regs2, sens2 = SD.rec_seq(ref, ref.mode, via_site=True)
        self.assertFalse(ref.switched, 'standby in ours: no switch at REC start')
        self.assertEqual(rec(ref, 0)['sw'] & 0xFF, 1)
        self.assertEqual(rec(ref, 0)['sw'] >> 24, 1)
        ws = written(ph, ph2) - {0x30100060}                  # TG control: emulated RAM after a first set from 0 (README 2.4)
        self.assertEqual(regs_of(regs, ws), regs_of(regs2, ws), 'the same register image at BUFA1 start')

    def test_stock_standby(self):
        cam = cam_for(SD.UHD30, bits=SBSTOCK)
        self.assertEqual(SD.entry(cam, T.TABS, 'MOV'), [1, 5, 8])
        self.assertEqual(SD.entry(cam, T.TAB3, 'UHD30')[1:], [cam.pid, cam.mode])
        both = cam_for(SD.UHD30, bits=SBSTOCK | TWIN)
        self.assertEqual(SD.entry(both, T.TABS, 'MOV'), [1, 5, 8])
        self.assertEqual((hdr(both)['live'], hdr(both)['refused']), (SBSTOCK, TWIN))

    def test_nowin_turns_the_sensor_window_off_and_nothing_else(self):
        cam = cam_for(SD.UHD30, bits=NOWIN)
        ref = cam_for(SD.UHD30)
        _, _, sens = SD.rec_seq(cam, 8)
        _, _, sref = SD.rec_seq(ref, 8)
        sc, sr = sensor_final(sens), sensor_final(sref)
        s30 = sensor_final(stock30()[3])
        for a in WIN_REGS:
            self.assertEqual(sc[a], s30[a], hex(a))
            self.assertNotEqual(sr[a], s30[a], hex(a))
        self.assertEqual({a: v for a, v in sc.items() if a not in WIN_REGS and a not in AE},
                         {a: v for a, v in sr.items() if a not in WIN_REGS and a not in AE})
        self.assertEqual({a: v for a, v in sc.items() if a not in AE}, {a: v for a, v in s30.items() if a not in AE},
                         'UHD 29.97 12b 1x1: the sensor table is then stock mode 7 exactly')
        self.assertEqual(SD.rows(cam, cam.mode)['TIM'], SD.rows(ref, ref.mode)['TIM'], 'RX / TG unchanged')
        self.assertEqual(hdr(cam)['live'], NOWIN)

    def test_rows_are_the_stock_modes(self):
        s = stock30()
        cam = cam_for(SD.UHD30, bits=ROWS, smode=7)
        self.assertEqual(hdr(cam)['live'], ROWS)
        r = SD.rows(cam, cam.mode)
        for k in ('TIM', 'META', 'R28', 'R38', 'R14', 'R68', 'REG', 'R10'):
            self.assertEqual(r[k], s[4][k], k)
        c = SD.canvas(cam, cam.pid)[0]
        self.assertEqual((c[0xF4 // 4], c[0xF8 // 4]), (s[5][0xF4 // 4], s[5][0xF8 // 4]), 'META on the canvas')
        ph, regs, sens = SD.rec_seq(cam, 8, via_site=True)
        sc, s30 = sensor_final(sens), sensor_final(s[3])
        self.assertEqual({a: v for a, v in sc.items() if a not in AE}, {a: v for a, v in s30.items() if a not in AE})
        ws = written(ph, s[1])
        a, b = regs_of(regs, ws), regs_of(s[2], ws)
        for reg in (0x30100004, 0x3010000C, 0x30100020, 0x30100024, 0x300F021C, 0x300F0224):
            self.assertEqual(a[reg], b[reg], hex(reg))
        self.assertEqual(rec(cam, 0)['bits'], ROWS | 7 << 8)

    def test_rows_refusals(self):
        for args, smode in ((SD.UHD30, 8), (SD.UHD30, 123), (SD.UHD30, 0), (T.FF_12V2, 7)):
            cam = cam_for(args, bits=ROWS, smode=smode)
            self.assertEqual((hdr(cam)['live'], hdr(cam)['refused']), (0, ROWS), (args, smode))
        ok = cam_for(SD.UHD25, bits=ROWS, smode=123)
        self.assertEqual(hdr(ok)['live'], ROWS, 'UHD 25p sweep recipe: stock mode 123 has its frame time')

    def test_rwzm_is_the_stock_raster(self):
        s = stock30()
        cam = cam_for(SD.UHD30, bits=RWZM)
        c = SD.canvas(cam, cam.pid)[0]
        ref = SD.canvas(cam_for(SD.UHD30), cam.pid)[0]
        for o in RWZM_OFFS:
            self.assertEqual(c[o // 4], s[5][o // 4], hex(o))
        self.assertEqual([(4 * i, v) for i, v in enumerate(c) if 4 * i not in RWZM_OFFS],
                         [(4 * i, v) for i, v in enumerate(ref) if 4 * i not in RWZM_OFFS])
        sb = SD.canvas(cam, cam.pid + 2)[0]
        self.assertEqual(sb, SD.canvas(cam_for(SD.UHD30), cam.pid + 2)[0], 'standby canvas untouched')
        ph, regs, _ = SD.rec_seq(cam, 8)
        ws = written(ph, s[1])
        a, b = regs_of(regs, ws), regs_of(s[2], ws)
        for reg in (0x30182210, 0x30182214, 0x30182218, 0x300F0908, 0x300F090C):
            self.assertEqual(a[reg], b[reg], hex(reg))
        ff = struct.unpack('<6I', cam.mu.mem_read(T.MEM + cam.fn('ap_sizes_t', 19), 24))
        self.assertEqual(ff[0], 1, 'armed')
        self.assertEqual((ff[2], ff[3]), (3856 * 12 // 8, 2170), 'the sentinel: the stock raster row')

    def test_rows_and_rwzm_is_stock_at_bufa1_start(self):
        s = stock30()
        cam = cam_for(SD.UHD30, bits=ROWS | RWZM, smode=7)
        ph, regs, sens = SD.rec_seq(cam, 8)
        ws = written(ph, s[1])
        a, b = regs_of(regs, ws, defc=True), regs_of(s[2], ws, defc=True)
        diff = {hex(r): (hex(a[r]), hex(b[r])) for r in ws if a[r] != b[r]}
        self.assertEqual(diff, {}, 'every register written in the REC start as stock UHD 29.97')

    def test_non_uhd_recipes_refuse_the_geometry_toggles(self):
        cam = cam_for(T.FF_12V2, bits=TWIN | NOWIN | RWZM | ROWS, smode=7)
        self.assertEqual((hdr(cam)['live'], hdr(cam)['refused']), (TWIN, NOWIN | RWZM | ROWS))
        self.assertEqual(SD.entry(cam, T.TABS, 'MOV')[2], cam.mode + 2)

    def test_toggles_change_only_at_a_commit(self):
        cam = cam_for(SD.UHD30)
        cam.put(RD + 32, TWIN | SBSTOCK)
        self.assertEqual(SD.entry(cam, T.TABS, 'MOV')[2], cam.mode, 'not before a commit')
        sel = T.recipe(*SD.UHD30)[0]
        self.assertEqual(cam.apply(sel, valid=0), T.AP_OK)    # sq_test 30 1 / 30 0: stock, then ours again
        self.assertEqual(cam.apply(sel), T.AP_OK)
        st = cam.status()
        self.assertEqual(SD.entry(cam, T.TABS, 'MOV'), [1, 5, 8])
        self.assertEqual(hdr(cam)['commits'], 2)
        self.assertNotEqual(st['mode_id'], cam.mode, 'the other slot')


MUTANTS = [
    ('ap.c', '&& A->slot[i].id + AP_PT_TWIN == id) return &A->slot[i];', '&& A->slot[i].id == id + 99u) return &A->slot[i];', 'test_twin_standby_switches_at_rec_start'),
    ('ap.c', '    if (s->pt & PT_TWIN) s->sentry[2] = id + AP_PT_TWIN;', '', 'test_twin_standby_switches_at_rec_start'),
    ('ap.c', '            && !(s->pt & PT_SBSTOCK)', '            && 1', 'test_stock_standby'),
    ('ap.c', '    if ((pt & PT_TWIN) && (pt & PT_SBSTOCK)) pt &= ~PT_TWIN;', '', 'test_stock_standby'),
    ('ap.c', '        else for (u32 i = 0; i < sizeof AP_PT_WIN; i++) AP_W(row + 4u * AP_PT_WIN[i]) = 0;',
     '        else for (u32 i = 1; i < sizeof AP_PT_WIN; i++) AP_W(row + 4u * AP_PT_WIN[i]) = 0;', 'test_nowin_turns_the_sensor_window_off_and_nothing_else'),
    ('ap.c', '        if (s->pt & PT_ROWS) { f[1] = s->smode; A->lookups++; return 0; }', '', 'test_rows_are_the_stock_modes'),
    ('ap.c', '            if (s->pt & PT_ROWS) { AP_W(c + 0xF4u) = s->meta[0]; AP_W(c + 0xF8u) = s->meta[1]; }', '', 'test_rows_are_the_stock_modes'),
    ('ap.c', '        if (!tim || !meta || !reg || !b || d * 100u > b) pt &= ~PT_ROWS;', '        if (!tim || !meta || !reg) pt &= ~PT_ROWS;', 'test_rows_refusals'),
    ('ap.c', '(1u << 0) | (1u << 1) | (1u << 9) | (1u << 11) | (1u << 25)', '(1u << 0) | (1u << 1) | (1u << 9) | (1u << 11)', 'test_rwzm_is_the_stock_raster'),
    ('ap.c', '        else { s->rec_w = bw; s->rec_h = bh; }', '        else { }', 'test_rwzm_is_the_stock_raster'),
    ('ap.c', "    if ((pt & (PT_ROWS | PT_RWZM | PT_NOWIN)) && (o->rec_w != 3840u || o->rec_h != 2160u))", "    if (0)", 'test_non_uhd_recipes_refuse_the_geometry_toggles'),
    ('ap.c', '        if (s && f[1] == s->id) A->pt_ours++;', '        A->pt_ours++;', 'test_twin_standby_switches_at_rec_start'),
    ('ap.c', '            A->pt_sw = 0; A->pt_ours = 0;', '            A->pt_ours = 0;', 'test_twin_standby_switches_at_rec_start'),
    ('ap.c', '        if (s->pt & PT_ROWS) return 0;                               /* the stock R68 row', '        if (0) return 0;                               /* the stock R68 row', 'test_rows_and_rwzm_is_stock_at_bufa1_start'),
]


def mutate():
    bad = []
    only = [int(a.split('=')[1]) for a in sys.argv if a.startswith('--only=')]
    for i, (fname, old, new, test) in enumerate(MUTANTS):
        if only and i not in only:
            continue
        t = pathlib.Path(tempfile.mkdtemp(prefix='slpt-mut-'))
        for f in ('ap.c', 'ap_calc.c', 'ap.h', 'pb_glyph.h', 'pb_glyph.py', 'pb_page.h', 'build_apply.py', 'test_apply.py',
                  'test_purple.py'):
            if (HERE / f).exists():
                shutil.copy(HERE / f, t / f)
        src = (t / fname).read_text()
        if src.count(old) != 1:
            bad.append((i, 'mutant text not found once'))
            print(f'mutant {i:2d} text not found once')
            continue
        (t / fname).write_text(src.replace(old, new))
        env = dict(os.environ, SL_ROOT=str(T.ROOT))
        r = subprocess.run([sys.executable, '-B', '-m', 'unittest', f'test_purple.PurpleTests.{test}'], cwd=t,
                           capture_output=True, text=True, env=env)
        ok = r.returncode != 0
        print(f'mutant {i:2d} {test[:50]:50s} {"caught" if ok else "SURVIVED"}')
        if not ok:
            bad.append((i, new[:60]))
        shutil.rmtree(t, ignore_errors=True)
    print('all caught' if not bad else f'survived: {bad}')
    return not bad


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        sys.exit(0 if mutate() else 1)
    unittest.main()
