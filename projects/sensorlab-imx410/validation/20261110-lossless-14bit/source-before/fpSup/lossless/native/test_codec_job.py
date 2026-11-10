"""The firmware encoder C062F6F8, split at its wait.

Host tests compile codec_job.c with every firmware call substituted by
codec_job_fixture.c, which logs the calls. Three kinds of check:

  * ORDER. The submit and finish halves call the firmware functions in the
    order C062F6F8 calls them. That order is not typed in here from memory:
    FirmwareOrderTests reads it out of the pinned image and requires the
    module's sequence to be a subsequence of the encoder's own calls, and
    every Thumb/ARM address the module uses to be one the encoder calls.
  * BOUNDS. Nothing is started unless every length F_INIT decided fits the
    buffers we own, and the source the engine is told it may read fits the
    frame buffer the caller vouched for.
  * FAILURE. An engine error closes and fails; any other wait failure keeps
    the job held, because the engine's state is unknown.

No camera, USB or card.
"""
import ctypes as ct
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
IMAGE = ROOT / 'out/seg0_c0000000.bin'
IMAGE_SHA256 = 'aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622'
OK, INVALID, BUSY, UNSUPPORTED, NOT_READY, FAULT = range(6)
IDLE, RUNNING, DONE, FAILED = range(4)
(C_INIT, C_FLAG, C_CLR, C_TWAI, C_OPEN, C_SUBMIT, C_RESET, C_START,
 C_CLOSE, C_EOI, C_TILES, C_TOTAL) = range(1, 13)
SRC, DST, TBL = 0x10000000, 0x20000000, 0x30000000
E_TMOUT = 0xFFFFFFCE
(K_INIT, K_FLAG, K_OPEN, K_SUBMIT, K_START, K_CLOSE, K_TWAI, K_PATTERN, K_TOTAL,
 K_DSTLEN, K_TBLLEN, K_SRCCAP, K_DSTCAP, K_TBLCAP, K_ENDPOS, K_SRC) = range(16)
LOG_N, PHASE, TOTAL, PADDED, TILECOUNT, EOI_D, EOI_E, TILES_D, TILES_T, TILES_N, \
    TOTAL_T, TOTAL_N, OOB, BAND_TABLE, LAST_NATIVE = range(100, 115)
FHD = (1936, 1090, 0)
SUBMIT_ORDER = [C_INIT, C_FLAG, C_CLR, C_OPEN, C_SUBMIT, C_RESET, C_START]
FINISH_ORDER = [C_TWAI, C_CLR, C_EOI, C_TILES, C_TOTAL, C_CLOSE]


def build(directory, source=None, name='codec.dylib'):
    out = Path(directory) / name
    subprocess.run([shutil.which('clang') or 'clang', '-shared', '-fPIC', '-O2', '-std=c11',
                    '-Wall', '-Wextra', '-Werror', '-DFPL_CODEC_JOB_HOST_TEST',
                    '-I', str(HERE), str(source or HERE / 'codec_job.c'),
                    str(HERE / 'codec_job_fixture.c'), '-o', str(out)],
                   check=True, capture_output=True, text=True, timeout=60)
    lib = ct.CDLL(str(out))
    for fn, count, ret in (('reset', 3, True), ('set', 2, False), ('submit', 0, True),
                           ('poll', 0, True), ('wait', 1, True), ('get', 1, True), ('source_bytes', 3, True),
                           ('abort', 0, True), ('engine_open', 0, True),
                           ('release', 0, True), ('reused', 0, True), ('submit_reg', 1, True)):
        f = getattr(lib, 'fpl_fixture_' + fn)
        f.argtypes = [ct.c_uint32] * count
        f.restype = ct.c_uint32 if ret else None
    return lib


class CodecJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-codec-')
        cls.lib = build(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.assertEqual(self.lib.fpl_fixture_reset(*FHD), OK)

    def get(self, field):
        return self.lib.fpl_fixture_get(field)

    def set(self, knob, value):
        self.lib.fpl_fixture_set(knob, value)

    def calls(self):
        return [self.get(i) for i in range(self.get(LOG_N))]

    def request(self):
        return [self.get(200 + i) for i in range(12)]

    # ---- keep_open: one open a take, the set-up registers cleared (2026-10-15)
    K_KEEP, K_DIRTY = 18, 19

    def finish_one(self):
        self.assertEqual(self.lib.fpl_fixture_submit(), OK)
        self.assertEqual(self.lib.fpl_fixture_poll(), OK)

    def test_kept_open_later_jobs_clear_the_set_up_instead_of_reopening(self):
        self.set(self.K_KEEP, 1)
        self.finish_one()
        self.assertNotIn(C_CLOSE, self.calls(), 'a finished job closed a kept-open engine')
        for _ in range(2):
            self.set(self.K_DIRTY, 0x5A5A5A50)       # what C062FFF8 ORed in last time
            self.finish_one()
            regs = [self.lib.fpl_fixture_submit_reg(n) for n in range(19)]
            self.assertEqual(regs[:13] + regs[14:], [0] * 18, 'set-up not cleared before submit')
            self.assertEqual(regs[13] & 1, 1, '300D0074, the enable, was touched')
        self.assertEqual(self.calls().count(C_OPEN), 1)
        self.assertEqual(self.lib.fpl_fixture_reused(), 2)
        self.assertEqual(self.calls().count(C_RESET), 3, 'the soft reset before every start')
        self.assertEqual(self.lib.fpl_fixture_release(), OK)
        self.assertEqual(self.calls()[-1], C_CLOSE)
        self.assertEqual(self.lib.fpl_fixture_engine_open(), 0)
        self.assertEqual(self.lib.fpl_fixture_release(), OK)
        self.assertEqual(self.calls().count(C_CLOSE), 1)

    def test_release_never_closes_a_running_job(self):
        self.set(self.K_KEEP, 1)
        self.assertEqual(self.lib.fpl_fixture_submit(), OK)
        self.assertEqual(self.lib.fpl_fixture_release(), BUSY)
        self.assertNotIn(C_CLOSE, self.calls())

    def test_a_refusal_still_closes_and_the_next_job_reopens(self):
        self.set(self.K_KEEP, 1)
        self.set(K_PATTERN, 4)
        self.assertEqual(self.lib.fpl_fixture_submit(), OK)
        self.assertEqual(self.lib.fpl_fixture_poll(), UNSUPPORTED)
        self.assertEqual(self.lib.fpl_fixture_engine_open(), 0)
        self.set(K_PATTERN, 1)
        self.finish_one()
        self.assertEqual(self.calls().count(C_OPEN), 2)
        self.assertEqual(self.lib.fpl_fixture_reused(), 0)

    def test_without_keep_open_every_job_opens_and_closes_as_the_encoder(self):
        self.finish_one()
        self.finish_one()
        self.assertEqual((self.calls().count(C_OPEN), self.calls().count(C_CLOSE)), (2, 2))
        self.assertEqual(self.lib.fpl_fixture_engine_open(), 0)

    # ---- submit -------------------------------------------------------
    def test_submit_calls_the_firmware_steps_in_order_and_does_not_wait(self):
        self.assertEqual(self.lib.fpl_fixture_submit(), OK)
        self.assertEqual(self.calls(), SUBMIT_ORDER)
        self.assertEqual(self.get(PHASE), RUNNING)

    def test_init_gets_the_stock_arguments(self):
        self.lib.fpl_fixture_submit()
        self.assertEqual([self.get(220 + i) for i in range(9)],
                         [1936, 1090, 0, 512, 368, SRC, DST, TBL, 0])

    def test_the_request_is_the_encoders_own(self):
        self.lib.fpl_fixture_submit()
        band_table = TBL + ((160 * 4 + 0x3FF) & ~0x3FF)
        self.assertEqual(self.request(), [
            1936, 1090, 0, 512, 368,
            SRC, (1936 * 1090 * 12 // 8 + 0x3FF) & ~0x3FF,   # 3,166,208
            DST, 0x2000, band_table, 160 * 4, 0xC062FCB1])
        self.assertEqual(self.get(BAND_TABLE), band_table)
        self.assertEqual(self.get(TILECOUNT), 12)

    def test_a_forced_grid_reaches_init_and_the_request(self):
        self.set(17, 480 << 16 | 368)
        self.assertEqual(self.lib.fpl_fixture_submit(), OK)
        self.assertEqual([self.get(220 + i) for i in (3, 4)], [480, 368])
        self.assertEqual(self.request()[3:5], [480, 368])
        self.assertEqual(self.get(TILECOUNT), 5 * 3)
        self.assertEqual((self.get(117), self.get(118)), (480, 368))

    def test_a_wait_gives_the_engine_flag_its_ticks_and_finishes_as_a_poll_does(self):
        self.lib.fpl_fixture_submit()
        self.assertEqual(self.lib.fpl_fixture_wait(10), OK)    # 0xDEAD unless tmo == 10
        self.assertEqual(self.get(PHASE), DONE)
        self.lib.fpl_fixture_reset(*FHD)
        self.lib.fpl_fixture_submit()
        self.assertEqual(self.lib.fpl_fixture_wait(0), OK)     # 0: the one-tick poll

    def test_a_new_force_on_the_same_job_gets_a_new_grid(self):
        self.assertEqual(self.lib.fpl_fixture_submit(), OK)
        self.assertEqual(self.request()[3:5], [512, 368])
        self.set(6, 0); self.lib.fpl_fixture_poll()          # finish it
        self.set(17, 480 << 16 | 368)
        self.assertEqual(self.lib.fpl_fixture_submit(), OK)
        self.assertEqual(self.request()[3:5], [480, 368])

    def test_a_grid_the_engine_or_tiff_cannot_take_falls_back(self):
        # not a multiple of 32 / of 16 / too wide / too many tiles for FHD
        for force in (500 << 16 | 368, 512 << 16 | 360, 544 << 16 | 368, 64 << 16 | 16):
            with self.subTest(force=hex(force)):
                self.lib.fpl_fixture_reset(*FHD)
                self.set(17, force)
                self.assertEqual(self.lib.fpl_fixture_submit(), OK)
                self.assertEqual(self.request()[3:5], [512, 368])
                self.assertEqual(self.get(TILECOUNT), 12)

    def test_an_exact_multiple_height_is_not_sent_as_zero(self):
        """C062F6F8 would send height % (368 * rows) = 0 for 736 rows."""
        self.lib.fpl_fixture_reset(1536, 736, 0)
        self.assertEqual(self.lib.fpl_fixture_submit(), OK)
        self.assertEqual(self.request()[1], 736)

    def test_source_bytes_is_the_1_kib_rounded_packed_raster(self):
        for (w, h, f), bits in (((1936, 1090, 0), 12), ((3840, 2160, 3), 10),
                                ((6064, 4042, 1), 14), ((1024, 576, 2), 16)):
            with self.subTest(w=w, h=h, f=f):
                self.assertEqual(self.lib.fpl_fixture_source_bytes(w, h, f),
                                 (w * h * bits // 8 + 0x3FF) & ~0x3FF)

    def test_shapes_the_engine_or_one_band_cannot_take_are_refused(self):
        for w, h, f in ((1937, 1090, 0), (1936, 1091, 0), (0, 2, 0), (1936, 1090, 4),
                        (1936, 1090, 7), (0x4008, 1090, 0), (0x4000, 0x4000, 2)):
            with self.subTest(w=w, h=h, f=f):
                self.assertEqual(self.lib.fpl_fixture_source_bytes(w, h, f), 0)
                self.lib.fpl_fixture_reset(w, h, f)
                self.assertEqual(self.lib.fpl_fixture_submit(), UNSUPPORTED)
                self.assertEqual(self.calls(), [])

    def test_a_frame_buffer_shorter_than_the_told_length_is_never_started(self):
        told = (1936 * 1090 * 12 // 8 + 0x3FF) & ~0x3FF
        self.set(K_SRCCAP, told - 1)
        self.assertEqual(self.lib.fpl_fixture_submit(), NOT_READY)
        self.assertEqual(self.calls(), [])
        self.set(K_SRCCAP, told)
        self.assertEqual(self.lib.fpl_fixture_submit(), OK)

    def test_every_length_f_init_decided_is_checked_before_starting(self):
        for knob, value in ((K_DSTLEN, 8192 + 1024), (K_DSTLEN, 0), (K_DSTLEN, 0x2001),
                            (K_TBLLEN, 0), (K_TBLLEN, 12 * 4 - 4),
                            (K_TBLCAP, 1024 + 160 * 4 - 1)):
            with self.subTest(knob=knob, value=value):
                self.lib.fpl_fixture_reset(*FHD)
                self.set(knob, value)
                self.assertEqual(self.lib.fpl_fixture_submit(), NOT_READY)
                self.assertEqual(self.calls(), [C_INIT])   # init only: nothing started

    def test_unaligned_buffers_are_refused_before_init(self):
        self.set(K_SRC, SRC + 0x200)
        self.assertEqual(self.lib.fpl_fixture_submit(), INVALID)
        self.assertEqual(self.calls(), [])

    def test_a_failing_step_stops_there_and_closes_what_it_opened(self):
        cases = ((K_INIT, 0, [C_INIT]),
                 (K_FLAG, 0xFFFFFFFF, [C_INIT, C_FLAG]),
                 (K_OPEN, 1, [C_INIT, C_FLAG, C_CLR, C_OPEN]),
                 (K_SUBMIT, 1, [C_INIT, C_FLAG, C_CLR, C_OPEN, C_SUBMIT, C_CLOSE]),
                 (K_START, 1, SUBMIT_ORDER + [C_CLOSE]))
        for knob, value, order in cases:
            with self.subTest(knob=knob):
                self.lib.fpl_fixture_reset(*FHD)
                self.set(knob, value)
                self.assertEqual(self.lib.fpl_fixture_submit(), NOT_READY)
                self.assertEqual(self.calls(), order)
                self.assertEqual(self.get(PHASE), IDLE)

    def test_a_second_submit_while_running_is_busy(self):
        self.lib.fpl_fixture_submit()
        self.assertEqual(self.lib.fpl_fixture_submit(), BUSY)

    # ---- poll / finish ------------------------------------------------
    def start(self):
        self.assertEqual(self.lib.fpl_fixture_submit(), OK)
        return self.get(LOG_N)

    def test_not_yet_done_is_busy_and_touches_nothing(self):
        mark = self.start()
        self.set(K_TWAI, E_TMOUT)
        for _ in range(5):
            self.assertEqual(self.lib.fpl_fixture_poll(), BUSY)
        self.assertEqual(self.calls()[mark:], [C_TWAI] * 5)
        self.assertEqual(self.get(PHASE), RUNNING)

    def test_finish_calls_the_firmware_fixups_in_order(self):
        mark = self.start()
        self.set(K_ENDPOS, 0x0014_8008)
        self.assertEqual(self.lib.fpl_fixture_poll(), OK)
        self.assertEqual(self.calls()[mark:], FINISH_ORDER)
        band = self.get(BAND_TABLE)
        self.assertEqual((self.get(EOI_D), self.get(EOI_E)), (DST, 0x0014_8008))
        self.assertEqual((self.get(TILES_D), self.get(TILES_T), self.get(TILES_N)),
                         (DST, band, 12))
        self.assertEqual((self.get(TOTAL_T), self.get(TOTAL_N)), (band, 12))
        self.assertEqual(self.get(PHASE), DONE)

    def test_the_payload_is_zero_padded_to_1_kib_and_the_pad_joins_the_last_tile(self):
        self.start()
        self.set(K_TOTAL, 0x1234)
        self.assertEqual(self.lib.fpl_fixture_poll(), OK)
        pad = 0x1400 - 0x1234
        self.assertEqual((self.get(TOTAL), self.get(PADDED)), (0x1234, 0x1400))
        self.assertEqual([self.get(2000 + 0x1234 + i) for i in range(pad)], [0] * pad)
        self.assertEqual(self.get(2000 + 0x1234 - 1), 0xAB, 'payload itself was touched')
        self.assertEqual(self.get(2000 + 0x1400), 0xAB, 'wrote past the padded end')
        be = lambda v: int.from_bytes(v.to_bytes(4, 'little'), 'big')
        band = (self.get(BAND_TABLE) - TBL) // 4
        last = be(self.get(300 + band + 11))
        self.assertEqual(last, 100 + 11 + pad)
        # and the band table was copied into the engine's own table
        self.assertEqual([self.get(300 + i) for i in range(12)],
                         [self.get(300 + band + i) for i in range(12)])
        self.assertEqual(self.get(OOB), 0)

    def test_an_already_aligned_total_adds_no_pad(self):
        self.start()
        self.set(K_TOTAL, 0x1000)
        self.lib.fpl_fixture_poll()
        self.assertEqual(self.get(PADDED), 0x1000)

    def test_a_job_given_up_on_is_closed_and_its_registers_kept(self):
        self.assertEqual(self.lib.fpl_fixture_submit(), OK)
        self.lib.fpl_fixture_set(16, 4)                 # 300D0008, as read on the camera
        n = self.lib.fpl_fixture_get(LOG_N)
        self.assertEqual(self.lib.fpl_fixture_abort(), OK)
        self.assertEqual([self.lib.fpl_fixture_get(i) for i in range(n, self.lib.fpl_fixture_get(LOG_N))],
                         [C_CLR, C_CLOSE])
        self.assertEqual(self.lib.fpl_fixture_get(PHASE), IDLE)
        self.assertEqual(self.lib.fpl_fixture_get(115), 4)
        self.assertEqual(self.lib.fpl_fixture_submit(), OK, 'not usable again')

    def test_giving_up_on_an_idle_job_touches_nothing(self):
        n = self.lib.fpl_fixture_get(LOG_N)
        self.assertEqual(self.lib.fpl_fixture_abort(), OK)
        self.assertEqual(self.lib.fpl_fixture_get(LOG_N), n)

    def test_a_close_that_fails_when_giving_up_is_a_fault(self):
        self.assertEqual(self.lib.fpl_fixture_submit(), OK)
        self.lib.fpl_fixture_set(K_CLOSE, 1)
        self.assertEqual(self.lib.fpl_fixture_abort(), FAULT)
        self.assertEqual(self.lib.fpl_fixture_get(PHASE), FAILED)

    def test_the_engine_refusing_a_frame_closes_and_frees_the_job(self):
        """Output that would not fit one frame: the frame goes RAW, and the
        next frame may use the job again -- as the firmware reuses its own."""
        mark = self.start()
        self.set(K_PATTERN, 4 | 1)
        self.assertEqual(self.lib.fpl_fixture_poll(), UNSUPPORTED)
        self.assertEqual(self.calls()[mark:], [C_TWAI, C_CLR, C_CLOSE])
        self.assertEqual(self.get(PHASE), IDLE)
        self.assertNotIn(C_EOI, self.calls()[mark:])
        self.set(K_PATTERN, 1)
        self.assertEqual(self.lib.fpl_fixture_submit(), OK)

    def test_a_refusal_whose_close_fails_is_a_fault_and_stays_held(self):
        self.start()
        self.set(K_PATTERN, 4 | 1)
        self.set(K_CLOSE, 1)
        self.assertEqual(self.lib.fpl_fixture_poll(), FAULT)
        self.assertEqual(self.get(PHASE), FAILED)
        self.assertEqual(self.lib.fpl_fixture_submit(), FAULT, 'a failed job was reused')

    def test_any_other_wait_failure_keeps_everything_held(self):
        mark = self.start()
        self.set(K_TWAI, 0xFFFFFFEF)          # E_ID and friends: state unknown
        self.assertEqual(self.lib.fpl_fixture_poll(), FAULT)
        self.assertNotIn(C_CLOSE, self.calls()[mark:])
        self.assertEqual(self.get(PHASE), FAILED)

    def test_an_impossible_total_is_not_trusted(self):
        for total in (0, 0x2001):
            with self.subTest(total=total):
                self.lib.fpl_fixture_reset(*FHD)
                self.start()
                self.set(K_TOTAL, total)
                self.assertEqual(self.lib.fpl_fixture_poll(), FAULT)
                self.assertEqual(self.calls()[-1], C_CLOSE)
                self.assertEqual(self.get(OOB), 0)


class FirmwareOrderTests(unittest.TestCase):
    """The order above comes out of the image, not out of this file."""

    CORE, CORE_END = 0xC062F6F8, 0xC062FA40
    # what each fixture code stands for in the firmware
    TARGET = {C_FLAG: 0xC062F440, C_CLR: 0xC00169C8, C_OPEN: 0xC062FE70,
              C_SUBMIT: 0xC062FE98, C_RESET: 0xC062FE90, C_START: 0xC062FEB0,
              C_TWAI: 0xC0016C08, C_EOI: 0xC062F6C0, C_TILES: 0xC062FCF8,
              C_TOTAL: 0xC062F4E0, C_CLOSE: 0xC062FE80}

    @classmethod
    def setUpClass(cls):
        import capstone
        image = IMAGE.read_bytes()
        if hashlib.sha256(image).hexdigest() != IMAGE_SHA256:
            raise AssertionError('firmware image hash differs')
        md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        cls.calls = []
        base = cls.CORE - 0xC0000000
        for insn in md.disasm(image[base:base + cls.CORE_END - cls.CORE], cls.CORE):
            if insn.mnemonic in ('bl', 'blx') and insn.op_str.startswith('#'):
                cls.calls.append(int(insn.op_str[1:], 16))

    def subsequence(self, wanted):
        it = iter(self.calls)
        return all(any(target == w for target in it) for w in wanted)

    def test_submit_order_is_the_encoders_order(self):
        wanted = [self.TARGET[c] for c in SUBMIT_ORDER if c != C_INIT]
        self.assertTrue(self.subsequence(wanted), [hex(a) for a in self.calls])

    def test_finish_order_is_the_encoders_order_after_start(self):
        start = self.calls.index(self.TARGET[C_START])
        tail = self.calls[start + 1:]
        it = iter(tail)
        wanted = [self.TARGET[c] for c in FINISH_ORDER]
        self.assertTrue(all(any(t == w for t in it) for w in wanted),
                        [hex(a) for a in tail])

    def test_the_encoder_resets_before_every_start(self):
        """The step the old probes skipped."""
        starts = [i for i, a in enumerate(self.calls) if a == self.TARGET[C_START]]
        self.assertTrue(starts)
        for i in starts:
            self.assertEqual(self.calls[i - 1], self.TARGET[C_RESET])

    def test_every_firmware_address_in_the_module_is_one_the_encoder_calls(self):
        text = (HERE / 'codec_job.c').read_text()
        arm = text[text.index('#elif defined(__arm__)'):text.index('#else')]
        used = {int(m, 16) & ~1 for m in re.findall(r'\(fn\d\)(0x[0-9a-f]+)u', arm)}
        self.assertTrue(used)
        allowed = set(self.calls) | {0xC05A6890}          # F_INIT, the caller's step
        self.assertEqual(sorted(hex(a) for a in used - allowed), [])

    def test_the_callback_is_the_one_the_encoder_installs(self):
        text = (HERE / 'codec_job.c').read_text()
        self.assertIn('#define STOCK_CALLBACK 0xc062fcb1u', text)
        # C062F75C/C062F760: movw/movt r0, #0xfcb1 / #0xc062 -> str [sp, #0x68]
        import capstone
        image = IMAGE.read_bytes()
        md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        at = 0xC062F75C - 0xC0000000
        ops = [f'{i.mnemonic} {i.op_str}' for i in md.disasm(image[at:at + 8], 0xC062F75C)]
        self.assertEqual(ops, ['movw r0, #0xfcb1', 'movt r0, #0xc062'])


class MutationTests(unittest.TestCase):
    MUTATIONS = {
        'no soft reset before start': ('    native_reset();', '    (void)0;'),
        'waits instead of polling': ('#define WAIT_POLL      1u', '#define WAIT_POLL      100u'),
        'skips the EOI fix': ('    native_eoi(j->destination, j->end_position);', ''),
        'skips the tile fix': ('    native_tiles(j->destination, j->band_table, j->tiles);', ''),
        'forgets the pad in the last tile': (
            '    poke(last, bswap(bswap(peek(last)) + pad));',
            '    poke(last, bswap(bswap(peek(last))));'),
        'trusts the engine dst length': ('        engine[3] > in->destination_capacity ||', ''),
        'ignores the source capacity': (
            '    if (source_bytes > in->source_capacity) return refuse(j, FPL_NOT_READY);', ''),
        'closes on an unknown wait failure': (
            '    if (native != 0) return fail(j, native);',
            '    if (native != 0) { native_close(); return fail(j, native); }'),
        'does not close on the error bit': (
            '        if ((native = native_close()) != 0) return fail(j, native);\n'
            '        j->last_native = pattern;',
            '        j->last_native = pattern;'),
        'treats a refusal as a fault': (
            '        j->phase = FPL_CODEC_IDLE;\n        return FPL_UNSUPPORTED;',
            '        j->phase = FPL_CODEC_FAILED;\n        return FPL_FAULT;'),
        'sends the zero band height': ('    j->request[1] = in->height;',
                                       '    j->request[1] = in->height % (FPL_TILE_HEIGHT * '
                                       'ceil_div(in->height, FPL_TILE_HEIGHT));'),
        'gives up without closing': ('    if ((native = native_close()) != 0) return fail(j, native);\n    j->phase = FPL_CODEC_IDLE;\n    return FPL_OK;',
                                     '    (void)native;\n    j->phase = FPL_CODEC_IDLE;\n    return FPL_OK;'),
        'a wait polls one tick': ('                             ticks ? ticks : WAIT_POLL);',
                                  '                             ((void)ticks, WAIT_POLL));'),
        'ignores the forced grid': (
            '        fpl_tile_grid(in->width, in->height, in->tile_force, &j->grid[0], &j->grid[1]);',
            '        fpl_tile_grid(in->width, in->height, 0, &j->grid[0], &j->grid[1]);'),
        'keeps a grid made for another force': ('        j->grid_for[2] != in->tile_force) {', '        0) {'),
        'tells the engine the default tile': ('    j->request[3] = tw;', '    j->request[3] = FPL_TILE_WIDTH;'),
        'clears the flag on a timeout': (
            '    if (native == E_TMOUT) return FPL_BUSY;          /* still encoding */',
            '    if (native == E_TMOUT) { native_clr_flg(j->flag, 0); return FPL_BUSY; }'),
    }

    def test_every_mutation_is_caught(self):
        text = (HERE / 'codec_job.c').read_text()
        with tempfile.TemporaryDirectory(prefix='fpl-codec-mut-') as tmp:
            for index, (name, (old, new)) in enumerate(self.MUTATIONS.items()):
                with self.subTest(mutation=name):
                    self.assertEqual(text.count(old), 1, f'seam for {name!r}')
                    source = Path(tmp) / f'm{index}.c'
                    source.write_text(text.replace(old, new))
                    lib = build(tmp, source, f'm{index}.dylib')
                    result = unittest.TestResult()
                    for base in (CodecJobTests,):
                        class Against(base):
                            @classmethod
                            def setUpClass(cls):
                                cls.lib = lib

                            @classmethod
                            def tearDownClass(cls):
                                pass
                        unittest.defaultTestLoader.loadTestsFromTestCase(Against).run(result)
                    self.assertFalse(result.wasSuccessful(), f'{name} was not caught')

    def test_the_real_module_passes_the_same_harness(self):
        with tempfile.TemporaryDirectory(prefix='fpl-codec-real-') as tmp:
            lib = build(tmp)
            result = unittest.TestResult()
            for base in (CodecJobTests,):
                class Against(base):
                    @classmethod
                    def setUpClass(cls):
                        cls.lib = lib

                    @classmethod
                    def tearDownClass(cls):
                        pass
                unittest.defaultTestLoader.loadTestsFromTestCase(Against).run(result)
            self.assertTrue(result.wasSuccessful(), result.failures + result.errors)


class ArmCompileTests(unittest.TestCase):
    def test_it_builds_freestanding_for_the_camera(self):
        clang = shutil.which('clang') or 'clang'
        nm = shutil.which('llvm-nm') or shutil.which('nm') or 'nm'
        with tempfile.TemporaryDirectory(prefix='fpl-codec-arm-') as tmp:
            out = Path(tmp) / 'codec_job.o'
            subprocess.run([clang, '--target=armv7a-none-eabi', '-mcpu=cortex-a9', '-mthumb',
                            '-mfloat-abi=soft', '-mfpu=none', '-ffreestanding', '-fno-builtin',
                            '-nostdlib', '-O2', '-std=c11', '-Wall', '-Wextra', '-Werror', '-c',
                            '-I', str(HERE), str(HERE / 'codec_job.c'), '-o', str(out)],
                           check=True, capture_output=True, text=True, timeout=30)
            undefined = subprocess.run([nm, '-u', str(out)], capture_output=True,
                                       text=True).stdout
            for forbidden in ('memcpy', 'memset', '__aeabi', 'fpl_codec_test'):
                self.assertNotIn(forbidden, undefined, undefined)


if __name__ == '__main__':
    unittest.main()
