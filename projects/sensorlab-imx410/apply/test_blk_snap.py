#!/usr/bin/env python3
"""BLK-SNAP TEST build (-DAP_BLK_SNAP_TEST, build_slqs.py --blk-snap-test): the BlackLevel loop snapshot ring and its
host decoder (tools/live/blk_snap.py).  Offline: unicorn against the real firmware image, no camera.

    cd projects/sensorlab-imx410/apply
    python3 -B -m unittest test_blk_snap            # ~1 min
    python3 -B test_blk_snap.py --mutate            # every mutant must make a test fail

What is checked against the firmware's own code (the oracle tests): the decoder's black value equals what the real
FUN_c031a2a0 stores, with the real XC_ImageSensorIMX410::v35 behind it, for random inputs and the gain edges.
What is NOT: the init-pedestal branch table (hand vectors from the decompile only) and which ring entry reaches the
DNG tag.
"""
import os, pathlib, random, re, shutil, struct, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_argv = list(sys.argv)
import test_apply as T                                      # noqa: E402  (a mutant run: this directory's ap.c)
sys.argv[:] = _argv
LIVE = T.ROOT / 'projects/sensorlab-imx410/tools/live'
if not (HERE / 'blk_snap.py').exists():                     # a mutant run copies (and patches) the decoder next to us
    sys.path.insert(1, str(LIVE))
import blk_snap as D                                        # noqa: E402
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE          # noqa: E402
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP, UC_ARM_REG_PC, UC_ARM_REG_LR   # noqa: E402

DEF = ('AP_BLK_SNAP_TEST',)
BS = T.WORK + 0x300000
OBJ = 0xC3E09000
# the record layout, written out here on its own (not taken from ap.c / build_slqs.py / the decoder): word -> address
ADDR = {7: 0xC343B590,
        8: 0x300F0250, 9: 0x300F0270, 10: 0x300F0290, 11: 0x300F02B0,
        12: 0x300F02C0, 13: 0x300F02C4, 14: 0x300F02C8, 15: 0x300F02CC,
        16: 0x300F0318, 17: 0x300F031C,
        18: 0xC2F1E1E4, 19: 0xC2F1E1E8,
        20: 0xC343A6F8, 21: 0xC343A6D0, 22: 0xC343A6C8, 23: 0xC343A6D4,
        24: 0xC343A974, 25: 0xC343A978, 26: 0xC343A97C, 27: 0xC343A980,
        **{28 + i: 0xC343A78C + 0xC0 + 4 * i for i in range(10)},
        38: 0xC343A78C + 0x138,
        39: 0xC343B588 + 0x24,
        40: 0x300F0310, 41: 0x30100588, 42: 0x30100590}
NAMES = ('seq hook site_r0 bits_fw bits_out pick_bits rec14 cur_mode ob_a0 ob_a1 ob_a2 ob_a3 ob_b0 ob_b1 ob_b2 ob_b3 '
         'ped_reg0 ped_reg1 ped_target ped_cur avg_locked avg_at_lock ped_prev init_count flag0 flag1 flag2 flag3 '
         'black0 black1 black2 black3 black4 black5 black6 black7 black8 black9 black_idx sensor_gain crct_gain '
         'tg_frame tg_line pad0 pad1 pad2 pad3 pad4').split()
SAFE = [w for w in ADDR if w != 7]                          # 0xC343B590 is the mode the apply unit itself reads
SITES = ((0xC02CA1BC, 0x24, 0), (0xC02CA218, 0x08, 1))      # (the instruction before the hooked BL, desc field, hook)


def map_mmio(cam):
    for base in (0x30000000, 0x30100000):
        try:
            cam.mu.mem_map(base, 0x100000)
        except Exception:
            pass


def snap_cam(defines=DEF, attach=True):
    cam = T.Cam(defines=defines)
    map_mmio(cam)
    cam.init()
    if 'AP_BLK_SNAP_TEST' in defines:
        cam.mu.mem_write(BS, bytes(D.RING_BYTES + 64))
        if attach:
            assert cam.fn('ap_bs_attach', T.MEM, BS) == T.AP_OK
    return cam


def fill(cam, rng):
    """distinct values in every word the hook reads (except the live mode); -> {word: value}"""
    exp = {}
    for w in SAFE:
        v = rng.getrandbits(32)
        cam.put(ADDR[w], v)
        exp[w] = v
    exp[7] = cam.w(ADDR[7])
    return exp


def hook_call(cam, site, field, plane=0):
    cam.put(OBJ + field, plane)
    cam.mu.reg_write(UC_ARM_REG_R0, OBJ)
    cam.mu.reg_write(UC_ARM_REG_SP, T.STACK - 0x2004)
    cam.mu.emu_start(site, site + 8, count=20000)
    if cam.error:
        raise cam.error
    return cam.r(UC_ARM_REG_R0)


def ring(cam):
    return bytes(cam.mu.mem_read(BS, D.RING_BYTES))


def words(cam, slot):
    return struct.unpack('<48I', cam.mu.mem_read(BS + 32 + 192 * slot, 192))


class HookTests(unittest.TestCase):
    def test_attach_writes_the_header_and_nothing_else(self):
        cam = snap_cam()
        self.assertEqual(struct.unpack('<8I', cam.mu.mem_read(BS, 32)), (0x504E5342, 1, 48, 32, 0, 0, 0, 0))
        self.assertEqual(bytes(cam.mu.mem_read(BS + 32, D.RING_BYTES - 32 + 64)), bytes(D.RING_BYTES - 32 + 64))

    def test_one_record_per_hook_call_with_every_word_from_its_address(self):
        cam = snap_cam()
        rng = random.Random(20261116)
        for k, (site, field, hook) in enumerate(SITES * 2):
            exp = fill(cam, rng)
            bits = hook_call(cam, site, field)
            w = words(cam, k)
            self.assertEqual(cam.w(BS + 16), k + 1, 'n')
            self.assertEqual((w[0], w[1], w[2], w[3], w[4]), (k + 1, hook, 0, 12, bits), 'seq, hook, r0, bits')
            self.assertEqual((w[5], w[6]), (0, 0xFFFFFFFF), 'no pick yet, no live slot')
            for i, a in ADDR.items():
                self.assertEqual(w[i], exp[i], f'word {i} ({NAMES[i]}) is not {a:#x}')
            self.assertEqual(w[43:], (0,) * 5)
        self.assertEqual(bytes(cam.mu.mem_read(BS + D.RING_BYTES, 64)), bytes(64), 'nothing past the ring')

    def test_the_plane_code_handed_down_is_recorded(self):
        cam = snap_cam()
        for k, plane in enumerate((0, 1, 2, 3)):
            hook_call(cam, SITES[0][0], SITES[0][1], plane)
            self.assertEqual(words(cam, k)[2], plane)

    def test_the_ring_wraps_and_the_decoder_orders_it(self):
        cam = snap_cam()
        rng = random.Random(7)
        marks = []
        for k in range(35):
            exp = fill(cam, rng)
            marks.append(exp[12])
            hook_call(cam, *SITES[k & 1][:2])
        self.assertEqual(cam.w(BS + 16), 35)
        self.assertEqual(bytes(cam.mu.mem_read(BS + D.RING_BYTES, 3 * 48 * 4)), bytes(3 * 48 * 4),
                         'records 33..35 wrapped into the ring, nothing written past it')
        self.assertEqual(words(cam, 2)[0], 35, 'record 35 is in slot 34 & 31')
        self.assertEqual(words(cam, 3)[0], 4, 'the oldest kept')
        hdr, recs = D.parse(ring(cam))
        self.assertEqual(hdr['n'], 35)
        self.assertEqual([r['seq'] for r in recs], list(range(4, 36)))
        self.assertEqual([r['ob_b0'] for r in recs], marks[3:])
        self.assertEqual([r['hook'] for r in recs], [(s - 1) & 1 for s in range(4, 36)])

    def test_true_14_is_recorded_as_12_from_the_firmware_and_14_answered(self):
        true14 = T.recipe(6048, 4040, 6048, 4040, '1x1', 14, fps=T.Fraction(15))
        cam = snap_cam()
        self.assertEqual(cam.apply(true14[0]), T.AP_OK)
        cam.call(T.PICKER, 0, T.TAB3, cam.key('UHD24'))
        cam.call(T.PICKER, 0, T.TAB3, cam.key('UHD23_98'))
        n0 = cam.w(BS + 16)
        self.assertEqual(hook_call(cam, *SITES[1][:2]), 14)
        w = words(cam, n0)
        self.assertEqual((w[3], w[4], w[5], w[6]), (12, 14, 12, 1), 'bits_fw 12, answered 14, TAB3, rec14')
        self.assertEqual(w[7], cam.w(0xC343B590))

    def test_not_attached_records_nothing_and_answers_the_same(self):
        cam = snap_cam(attach=False)
        fill(cam, random.Random(3))
        self.assertEqual([hook_call(cam, s, f) for s, f, _ in SITES], [12, 12])
        self.assertEqual(ring(cam), bytes(D.RING_BYTES))

    def test_the_hook_only_loads_and_stores_into_the_ring(self):
        """writes: the ring, the apply unit's own memory, the stack -- never a register or firmware state; and the
        firmware code that runs is the product build's (the hooked BL's own target), nothing more"""
        def run(defines):
            cam = snap_cam(defines)
            fill(cam, random.Random(11))
            wr, pcs = [], set()
            h1 = cam.mu.hook_add(UC_HOOK_MEM_WRITE, lambda uc, acc, a, sz, v, d: wr.append(a))
            h2 = cam.mu.hook_add(UC_HOOK_CODE, lambda uc, a, sz, d: pcs.add(a), begin=0xC0000000, end=0xC0FFFFFF)
            out = [hook_call(cam, s, f) for s, f, _ in SITES]
            cam.mu.hook_del(h1)
            cam.mu.hook_del(h2)
            return out, wr, pcs, cam
        out_p, wr_p, pcs_p, _ = run(())
        out_s, wr_s, pcs_s, cam = run(DEF)
        self.assertEqual(out_s, out_p)
        self.assertEqual(pcs_s, pcs_p, 'the same firmware instructions as the product build')
        extra = [a for a in wr_s if not (BS <= a < BS + D.RING_BYTES)]
        for a in extra:
            self.assertTrue(T.MEM <= a < T.MEM + 0x100000 or T.STACK - 0x40000 <= a < T.STACK or a == OBJ + 0x24
                            or a == OBJ + 8, f'write to {a:#x}')
        self.assertEqual(sorted(a for a in wr_p if not (T.STACK - 0x40000 <= a < T.STACK)),
                         sorted(a for a in extra if not (T.STACK - 0x40000 <= a < T.STACK)),
                         'outside the ring and the stack: the product build\'s writes')
        self.assertEqual(len([a for a in wr_s if BS + 32 <= a < BS + D.RING_BYTES]), 2 * 48, '48 stores a record')
        self.assertEqual(cam.calls and [c for c in cam.calls if c[0] == 'MISALIGNED'], [], 'stack alignment')


class BuildTests(unittest.TestCase):
    def test_every_blk_snap_line_is_behind_the_flag(self):
        """the product (and the two older TEST builds) with every AP_BLK_SNAP_TEST block removed give the same ARM
        image, and the product image has no ap_bs symbol"""
        src = (HERE / 'ap.c').read_text()
        out, depth, skip = [], 0, None
        for line in src.splitlines(keepends=True):
            d = line.strip()
            if d.startswith('#if'):
                depth += 1
                if skip is None and d == '#ifdef AP_BLK_SNAP_TEST':
                    skip = depth
                    continue
            elif d.startswith('#endif'):
                depth -= 1
                if skip is not None and depth == skip - 1:
                    skip = None
                    continue
            if skip is None:
                out.append(line)
        stripped = ''.join(out)
        for word in ('ap_bs', 'AP_BS_', 'AP_BLK_SNAP_TEST'):
            self.assertNotIn(word, stripped)
        t = pathlib.Path(tempfile.mkdtemp(prefix='slbs-strip-'))
        try:
            for f in ('ap.c', 'ap_calc.c', 'ap.h', 'pb_glyph.h', 'pb_glyph.py', 'build_apply.py', 'pb_page.h'):
                if (HERE / f).exists():
                    shutil.copy(HERE / f, t / f)
            (t / 'ap.c').write_text(stripped)
            import build_apply as BA
            for d in ((), ('AP_REC_DELAY_TEST',), ('AP_REC_DELAY_TEST', 'AP_PURPLE_TEST')):
                a, fa = BA.arm(HERE, out_dir=pathlib.Path(tempfile.mkdtemp()), defines=d)
                b, _ = BA.arm(t, out_dir=pathlib.Path(tempfile.mkdtemp()), defines=d)
                self.assertEqual(a, b, d)
                self.assertFalse([f for f in fa if 'ap_bs' in f], d)
        finally:
            shutil.rmtree(t, ignore_errors=True)
        _, funcs = BA.arm(HERE, out_dir=pathlib.Path(tempfile.mkdtemp()), defines=DEF)
        self.assertIn('ap_bs_attach', funcs)

    def test_the_build_json_layout_is_the_decoders_and_the_tests(self):
        txt = (T.ROOT / 'projects/sensorlab-imx410/qs/build_slqs.py').read_text()
        ns = {}
        m = re.search(r'^BLK_SNAP_DEFINE = .*?^assert len\(BLK_SNAP_FIELDS\).*?$', txt, re.S | re.M)
        self.assertTrue(m)
        exec(m.group(0), ns)                                 # the constants only: no build is run
        self.assertEqual(ns['BLK_SNAP_FIELDS'], NAMES)
        self.assertEqual(D.FIELDS, NAMES)
        self.assertEqual({i: int(a, 16) for i, a in enumerate(ns['BLK_SNAP_ADDRS']) if a}, ADDR)
        self.assertGreaterEqual(ns['BLK_SNAP_RESERVE'], D.RING_BYTES)
        self.assertEqual(D.RING_BYTES, 32 + 32 * 48 * 4)


def rec(**kw):
    r = dict.fromkeys(NAMES, 0)
    r.update(kw)
    return r


def ring_bytes(records, n=None):
    n = len(records) if n is None else n
    buf = bytearray(D.RING_BYTES)
    struct.pack_into('<8I', buf, 0, 0x504E5342, 1, 48, 32, n, 0, 0, 0)
    for k, r in enumerate(records):
        k0 = n - len(records) + k
        struct.pack_into('<48I', buf, 32 + 192 * (k0 & 31), *[r[f] & 0xFFFFFFFF for f in NAMES])
    return bytes(buf)


class DecoderTests(unittest.TestCase):
    def test_hand_vectors(self):
        """worked by hand from FUN_c031a2a0 / v35 (DN12 x 1024)"""
        r = rec(avg_at_lock=262400, ob_b0=262144, ob_a0=262656, ped_target=0x3FD, ped_prev=0x400, sensor_gain=0x600)
        self.assertEqual(D.v35(r), 512 - 128)
        self.assertEqual(D.black_x1024(r), 262144 - 256 + 0 + 384)              # -3 / 4 truncates to 0
        r = rec(avg_at_lock=262144, ob_b0=262400, ob_a0=262400, ped_target=0x3FB, ped_prev=0x400, sensor_gain=0x400)
        self.assertEqual(D.v35(r), 0)
        self.assertEqual(D.black_x1024(r), 262144 + 256 - 1024)                 # -5 / 4 = -1 -> one DN12 down
        r = rec(avg_at_lock=1000, ob_b0=1000, ob_a0=900, ped_target=0x407, ped_prev=0x400, sensor_gain=0x800)
        self.assertEqual(D.black_x1024(r), 262144 + 1024 - 100 - 128)           # +7 / 4 = +1; the gain's upper edge
        self.assertEqual([D.trunc_div4(v) for v in (-8, -7, -5, -4, -3, -1, 0, 1, 3, 4, 7)],
                         [-2, -1, -1, -1, 0, 0, 0, 0, 0, 1, 1])

    def test_init_pedestal_branches(self):
        """FUN_c0313ec0's init path (param_1 != 0): the two tables, by the flags"""
        for mod, a, b in ((0, 0, -2), (1, -3, -1), (2, -2, 0), (3, -1, -3)):
            ob = (1016 + mod) << 8 | 0x37
            self.assertEqual(D.init_pedestal(rec(ob_b0=ob)), 0x400 + a, mod)
            self.assertEqual(D.init_pedestal(rec(ob_b0=ob, flag0=1, flag1=1)), 0x400 + b, mod)
            self.assertEqual(D.init_pedestal(rec(ob_b0=ob, flag0=0x100, flag2=1)), 0x400 + b, mod)
            self.assertEqual(D.init_pedestal(rec(ob_b0=ob, flag0=1, flag1=2)), 0x400 + a, 'byte0 set but +4 != 1')
            self.assertEqual(D.init_pedestal(rec(ob_b0=ob, flag0=0, flag1=1, flag2=1)), 0x400 + a, 'bytes clear')

    def test_parse_orders_wraps_and_refuses(self):
        rs = [rec(seq=i + 1, ob_b0=1000 + i) for i in range(40)]
        hdr, out = D.parse(ring_bytes(rs[8:], n=40))
        self.assertEqual((hdr['n'], [r['seq'] for r in out]), (40, list(range(9, 41))))
        hdr, out = D.parse(ring_bytes(rs[:5]))
        self.assertEqual([r['ob_b0'] for r in out], [1000, 1001, 1002, 1003, 1004])
        self.assertEqual(D.parse(ring_bytes([]))[1], [])
        bad = bytearray(ring_bytes(rs[:5]))
        struct.pack_into('<I', bad, 32 + 192 * 2, 9)
        with self.assertRaises(D.BadRing):
            D.parse(bytes(bad))
        with self.assertRaises(D.BadRing):
            D.parse(bytes(D.RING_BYTES))
        with self.assertRaises(D.BadRing):
            D.parse(ring_bytes(rs[:5])[:-4])
        bad = bytearray(ring_bytes(rs[:5]))
        struct.pack_into('<I', bad, 8, 47)
        with self.assertRaises(D.BadRing):
            D.parse(bytes(bad))

    def test_table_compares_with_the_dng_tag(self):
        r = rec(seq=1, hook=1, bits_out=14, bits_fw=12, rec14=1, avg_at_lock=262144, ob_b0=262144, ob_a0=262144,
                ped_target=0x400, ped_prev=0x400, black_idx=3, black2=262144 - 512)
        rows, text = D.table([r], dng_black=[1023.0, 1025.0], bits=14)
        self.assertEqual((rows[0]['pred'], rows[0]['fw'], rows[0]['hook'], rows[0]['rec14']), (256.0, 255.5, 'BLK', 1))
        self.assertIn('pred as a tag 1024.000', text)
        self.assertIn('tag - pred +0.000', text)
        self.assertIn('tag - fw +2.000', text)
        self.assertEqual(D.fw_newest(rec(black_idx=0, black9=77)), 77)
        self.assertEqual((D.tag_of(256.0, 12), D.tag_of(256.0, 10), D.tag_of(256.0, 8)), (256.0, 64.0, 16.0))

    def test_read_refuses_while_recording_and_reads_the_whole_ring(self):
        class Cam:
            def __init__(s, rec_):
                s.rec_, s.asked = rec_, []
            def recording(s):
                return s.rec_
            def call(s, a, r0=0, r1=0, r2=0):
                s.asked.append(('call', a, r0))
                return 0x48400000
            def mem(s, a, n):
                s.asked.append(('mem', a, n))
                return [(a - 0x48400000) // 4 + i for i in range(n)]
        t = pathlib.Path(tempfile.mkdtemp(prefix='slbs-read-'))
        try:
            (t / 'b.json').write_text('{"blk_snap": {}, "sq_test_off": 4660}')
            (t / 'p.json').write_text('{"sq_test_off": 4660}')
            c = Cam(True)
            with self.assertRaises(SystemExit):
                D.read_camera(t / 'b.json', block=0x46000000, cam=c)
            self.assertEqual(c.asked, [], 'recording: nothing is sent')
            with self.assertRaises(SystemExit):
                D.read_camera(t / 'p.json', block=0x46000000, cam=Cam(False))
            c = Cam(False)
            b = D.read_camera(t / 'b.json', block=0x46000000, cam=c)
            self.assertEqual(c.asked[0], ('call', 0x46000000 + 4660, 50))
            self.assertEqual(struct.unpack(f'<{D.RING_BYTES // 4}I', b), tuple(range(D.RING_BYTES // 4)))
        finally:
            shutil.rmtree(t, ignore_errors=True)


class OracleTests(unittest.TestCase):
    """the decoder against the firmware's own FUN_c031a2a0 (+ the real v35 through the IMX410 vtable)"""
    FAKE = T.WORK + 0x280000                                 # stands for the image sensor object (FUN_c0322e48(0))
    CL = T.WORK + 0x290000                                   # stands for the clamp object (0xC343A78C)

    @classmethod
    def setUpClass(cls):
        cam = T.Cam()
        map_mmio(cam)
        cam.mu.mem_write(0xC0322E48, struct.pack('<I', 0xE12FFF1E))      # bx lr; r0 set by the hook below
        cam.mu.hook_add(UC_HOOK_CODE, lambda uc, a, sz, d: uc.reg_write(UC_ARM_REG_R0, cls.FAKE),
                        begin=0xC0322E48, end=0xC0322E48)
        cam.put(cls.FAKE + 0xD0, 0xC0B5FCC0)                             # the IMX410 vtable; + 0x94 = v35 (C0324910)
        cls.cam = cam

    def fw(self, r):
        cam = self.cam
        for name, a in (('ob_a0', 0x300F0250), ('ob_b0', 0x300F02C0)):
            cam.put(a, r[name])
        for a in (0x300F0270, 0x300F0290, 0x300F02B0, 0x300F02C4, 0x300F02C8, 0x300F02CC):
            cam.put(a, 0x5A5A5A5A)                                       # the other channels must not matter
        cam.put(self.FAKE + 0x24, r['sensor_gain'])
        cam.put(self.CL + 0x138, r['black_idx'])
        for i in range(10):
            cam.put(self.CL + 0xC0 + 4 * i, 0)
        cam.call(0xC031A2A0, self.CL, r['avg_at_lock'], r['ped_target'], r['ped_prev'])
        slot = 9 if r['black_idx'] == 0 else r['black_idx'] - 1
        vals = [cam.w(self.CL + 0xC0 + 4 * i) for i in range(10)]
        self.assertEqual([i for i, v in enumerate(vals) if v], [slot] if vals[slot] else [])
        return D.s32(vals[slot])

    def test_the_vtable_slot_is_v35(self):
        self.assertEqual(self.cam.w(0xC0B5FCC0 + 0x94), 0xC0324910)

    def test_random_inputs(self):
        rng = random.Random(1116)
        for _ in range(300):
            base = rng.randrange(200 << 10, 300 << 10)
            r = rec(avg_at_lock=base + rng.randrange(-4096, 4096), ob_b0=base + rng.randrange(-4096, 4096),
                    ob_a0=base + rng.randrange(-8192, 8192), ped_target=rng.randrange(0x100, 0x701),
                    ped_prev=rng.randrange(0x100, 0x701), sensor_gain=rng.choice((0x400, 0x4FF, 0x600, 0x7FF, 0x1000)),
                    black_idx=rng.randrange(0, 10))
            self.assertEqual(self.fw(r), D.black_x1024(r), r)

    def test_gain_edges_and_small_pedestal_steps(self):
        for g, sub in ((0x500, 0), (0x501, 0x80), (0x800, 0x80), (0x801, 0), (0, 0), (0xFFFFFFFF, 0)):
            r = rec(avg_at_lock=262144, ob_b0=262144, ob_a0=262144, ped_target=0x400, ped_prev=0x400, sensor_gain=g,
                    black_idx=1)
            self.assertEqual(self.fw(r), 262144 - sub, hex(g))
            self.assertEqual(D.black_x1024(r), 262144 - sub, hex(g))
        for dp in range(-9, 10):
            r = rec(avg_at_lock=262144, ob_b0=262144, ob_a0=262144, ped_target=0x400 + dp, ped_prev=0x400,
                    sensor_gain=0x400, black_idx=5)
            self.assertEqual(self.fw(r), D.black_x1024(r), dp)
            self.assertEqual(self.fw(r), 262144 + 1024 * int(dp / 4), dp)

    def test_fw_newest_is_the_slot_the_firmware_wrote(self):
        for idx in range(10):
            r = rec(avg_at_lock=262144, ob_b0=262000, ob_a0=262100, ped_target=0x400, ped_prev=0x400,
                    sensor_gain=0x400, black_idx=idx)
            v = self.fw(r)
            got = rec(black_idx=idx, **{f'black{i}': self.cam.w(self.CL + 0xC0 + 4 * i) for i in range(10)})
            self.assertEqual(D.fw_newest(got), v, idx)


# (file, old, new, the test that must fail)
MUTANTS = [
    ('ap.c', '    w[16] = AP_W(0x300F0318u); w[17] = AP_W(0x300F031Cu);\n', '    w[16] = AP_W(0x300F0318u);\n',
     'HookTests.test_one_record_per_hook_call_with_every_word_from_its_address'),            # a word not recorded
    ('ap.c', 'w[12] = AP_W(0x300F02C0u); w[13] = AP_W(0x300F02C4u);', 'w[12] = AP_W(0x300F02C4u); w[13] = AP_W(0x300F02C0u);',
     'HookTests.test_one_record_per_hook_call_with_every_word_from_its_address'),            # two words swapped
    ('ap.c', '    w[39] = AP_W(0xC343B5ACu);', '    w[39] = AP_W(0xC2F1E678u);',
     'HookTests.test_one_record_per_hook_call_with_every_word_from_its_address'),            # the wrong object
    ('ap.c', '    B->n = n + 1u;                                                   /* last',
     '    B->n = n;                                                        /* last',
     'HookTests.test_the_ring_wraps_and_the_decoder_orders_it'),                             # the count stands still
    ('ap.c', '    w[0] = n + 1u;\n', '    w[0] = 1u;\n',
     'HookTests.test_the_ring_wraps_and_the_decoder_orders_it'),                             # seq does not advance
    ('ap.c', '    volatile u32 *w = B->r[n & (AP_BS_N - 1u)].w;', '    volatile u32 *w = B->r[n & (AP_BS_N * 2u - 1u)].w;',
     'HookTests.test_the_ring_wraps_and_the_decoder_orders_it'),                             # runs past the ring
    ('ap.c', '    if (!B || B->magic != AP_BS_MAGIC) return;                       /* not attached */\n',
     '    if (!B) B = (struct ap_bs *)(uintptr_t)0x48400000u;\n',
     'HookTests.test_not_attached_records_nothing_and_answers_the_same'),                    # writes when not attached
    ('ap.c', '#ifdef AP_BLK_SNAP_TEST\n        u32 bs_down = r;\n#endif\n', '        u32 bs_down = r;\n',
     'BuildTests.test_every_blk_snap_line_is_behind_the_flag'),                              # leaks into the product
    ('ap.c', '        ap_bs_snap(A, id, bs_r0, bs_down, r, s);', '        ap_bs_snap(A, id, bs_r0, r, r, s);',
     'HookTests.test_true_14_is_recorded_as_12_from_the_firmware_and_14_answered'),
    ('ap.c', '        ap_bs_snap(A, id, bs_r0, bs_down, r, s);', '        ap_bs_snap(A, id, bs_r0, bs_down, r, s); r = bs_down;',
     'HookTests.test_true_14_is_recorded_as_12_from_the_firmware_and_14_answered'),          # the TEST build changes the answer
    ('ap.c', '    w[40] = AP_W(0x300F0310u); w[41]', '    AP_W(0x300F0318u) = w[16]; w[40] = AP_W(0x300F0310u); w[41]',
     'HookTests.test_the_hook_only_loads_and_stores_into_the_ring'),                         # a register write
    ('blk_snap.py', "    return (0x40000 - s32(r['avg_at_lock'] - r['ob_b0'])", "    return (0x40000 + s32(r['avg_at_lock'] - r['ob_b0'])",
     'OracleTests.test_random_inputs'),                                                      # the sign reversed
    ('blk_snap.py', "    v = s32(r['ob_a0'] - r['ob_b0'])", "    v = s32(r['ob_b0'] - r['ob_a0'])", 'DecoderTests.test_hand_vectors'),
    ('blk_snap.py', "    return -((-v) >> 2) if v < 0 else v >> 2", "    return v >> 2", 'DecoderTests.test_hand_vectors'),
    ('blk_snap.py', "    if 0x500 < r['sensor_gain'] <= 0x800:", "    if 0x500 <= r['sensor_gain'] < 0x800:",
     'OracleTests.test_gain_edges_and_small_pedestal_steps'),
    ('blk_snap.py', "        if r['seq'] != k + 1:", "        if False:", 'DecoderTests.test_parse_orders_wraps_and_refuses'),
    ('blk_snap.py', "    for k in range(max(0, n - NMAX), n):", "    for k in range(0, min(n, NMAX)):",
     'DecoderTests.test_parse_orders_wraps_and_refuses'),
    ('blk_snap.py', "ADJ = {'A': {1: -3, 2: -2, 3: -1, 0: 0}, 'B': {1: -1, 2: 0, 3: -3, 0: -2}}",
     "ADJ = {'B': {1: -3, 2: -2, 3: -1, 0: 0}, 'A': {1: -1, 2: 0, 3: -3, 0: -2}}", 'DecoderTests.test_init_pedestal_branches'),
    ('blk_snap.py', "    if cam.recording():\n        raise SystemExit('recording: nothing is sent')\n", "",
     'DecoderTests.test_read_refuses_while_recording_and_reads_the_whole_ring'),
]


def mutate():
    bad = []
    only = [int(a.split('=')[1]) for a in sys.argv if a.startswith('--only=')]
    for i, (fname, old, new, test) in enumerate(MUTANTS):
        if only and i not in only:
            continue
        t = pathlib.Path(tempfile.mkdtemp(prefix='slbs-mut-'))
        for f in ('ap.c', 'ap_calc.c', 'ap.h', 'pb_glyph.h', 'pb_glyph.py', 'pb_page.h', 'build_apply.py', 'test_apply.py',
                  'test_blk_snap.py'):
            if (HERE / f).exists():
                shutil.copy(HERE / f, t / f)
        shutil.copy(LIVE / 'blk_snap.py', t / 'blk_snap.py')
        src = (t / fname).read_text()
        if src.count(old) != 1:
            bad.append((i, 'mutant text not found once'))
            print(f'mutant {i:2d} text not found once')
            shutil.rmtree(t, ignore_errors=True)
            continue
        (t / fname).write_text(src.replace(old, new))
        cache = tempfile.mkdtemp(prefix='slbs-pyc-')         # a fresh bytecode cache: never a stale module
        env = dict(os.environ, SL_ROOT=str(T.ROOT), PYTHONPYCACHEPREFIX=cache)
        r = subprocess.run([sys.executable, '-B', '-m', 'unittest', f'test_blk_snap.{test}'], cwd=t,
                           capture_output=True, text=True, env=env)
        ran = re.search(r'Ran (\d+) test', r.stderr)
        ok = r.returncode != 0
        why = 'caught' if ok else 'SURVIVED'
        if ok and not (ran and int(ran.group(1)) >= 1):
            why = 'caught (did not get to a test: build / import error)'
        print(f'mutant {i:2d} {test[:66]:66s} {why}')
        if not ok:
            bad.append((i, new[:60]))
        shutil.rmtree(t, ignore_errors=True)
        shutil.rmtree(cache, ignore_errors=True)
    print('all caught' if not bad else f'survived: {bad}')
    return not bad


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        sys.exit(0 if mutate() else 1)
    unittest.main()
