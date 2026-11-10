"""The TEST card's launcher and hook shims, executed from the built bytes.

The card is built by build_card.py into a temporary directory. The real
loader and stage2 from its AutoRun and fpSup.BIN run in Unicorn against the
pinned firmware image (fp_usb_shell/test_loader_hook.Camera), which places
every section and journals every declared site. Then the lossless launcher --
the bytes that will be on the card -- runs from the staging buffer, and every
hook is entered through its veneer exactly as the firmware's branch would
enter it.

What this proves: allocation, copy, publication order, all-or-nothing arming,
branch encodings, the veneers, and that each shim reaches its C body and
returns to (or continues into) the firmware with the registers and stack the
firmware expects. What it does not: real scheduling, the codec, the SD path,
or anything the stubs stand in for. Emulated, not on the camera.
"""
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SHELL = HERE.parent / 'fp_usb_shell'
sys.path.insert(0, str(SHELL))
sys.argv[1:] = [] if __name__ == '__main__' else sys.argv[1:]
import test_loader_hook as T                     # noqa: E402

from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,  # noqa: E402
                               UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR,
                               UC_ARM_REG_R4, UC_ARM_REG_R6, UC_ARM_REG_R11,
                               UC_ARM_REG_CPSR)

SITES = {'rec': (0xC03A33C8, 0xEBFFFC1A), 'arrive': (0xC038BFF0, 0xE12FFF33),
         'stop': (0xC0398D88, 0xE92D49F0), 'flush': (0xC03A5490, 0xEB0BD652),
         'play': (0xC05C0EA4, 0xE595201C), 'clip': (0xC05BDDAC, 0xE58430A0),
         'end': (0xC05C2E90, 0xE92D4070), 'pool': (0xC05C2D10, 0xE92D44F0),
         'event': (0xC038BD08, 0xE594300C), 'discard': (0xC037DEF8, 0xEB000042)}
VENEER_AT = {'rec': 0, 'arrive': 8, 'stop': 16, 'flush': 24,      # the record at +32
             'play': 48, 'clip': 56, 'end': 64, 'pool': 72, 'event': 80, 'discard': 88}
CAVE_BYTES = 96
CAVE_BUMP, CAVE_ARENA, CAVE_END = 0xC072E060, 0xC072E064, 0xC072EFB4
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_card  # noqa: E402
CARD_BLOCK = build_card.BLOCK_BYTES     # the launcher's USER block, as built
CARD_OFFSETS = tuple(build_card.ENTRIES)
BLOCK = 0x45300000                    # where our allocation lands in emulation:
                                      # clear of the staging buffer the harness
                                      # hands the loader lower in the same heap
ORIGINAL = {'prepare': 0xC03A2438, 'enqueue': 0xC037DD50, 'flush': 0xC069ADE0,
            'stop_resume': 0xC0398D8C, 'tk_cre_tsk': 0xC0016A58, 'tk_sta_tsk': 0xC0016BC0,
            'end_resume': 0xC05C2E94, 'pool_resume': 0xC05C2D14,
            'event_resume': 0xC038BD0C, 'discard': 0xC037E008,
            'irq_off': 0xC000EC14, 'irq_restore': 0xC000EC24,
            'tag_add': 0xC00BA378}
# A clip's first frame, as fpl_play_clip opens it -- open refused. Installed
# only after boot: the loader reads fpSup.BIN through the same file API.
CLIP_FILE = {'clip_volume': 0xC069B930, 'clip_path': 0xC069B9B8, 'f_ctor': 0xC0365E90,
             'f_open': 0xC0365FB0, 'f_dtor': 0xC0365ED0}
TASK_ID = 0x5A
BULK = 0xC0B9E5D8                     # the file layer's bulk size (stock 64 MB; LOSS leaves it)


def build_card():
    out = pathlib.Path(tempfile.mkdtemp(prefix='fpl-card-emu-')) / 'card'
    subprocess.run([sys.executable, '-B', str(HERE / 'build_card.py'), '--out', str(out)],
                   check=True, capture_output=True, text=True, timeout=300)
    text = (out / 'AutoRun.txt').read_text()
    import re
    sets = [(int(a, 16), int(v, 16)) for a, v in
            re.findall(r'^mem set (0x[0-9A-Fa-f]+) (0x[0-9A-Fa-f]+)', text, re.M)]
    loader = {a: v for a, v in sets if T.CAVE_LOW <= a < T.CAVE_LOW + 0x200}
    global LAYOUT, C_ENTRIES
    import json
    LAYOUT = json.loads((out / 'layout.json').read_text())['fields']
    facts = json.loads((out / 'build.json').read_text())['blob']
    C_ENTRIES = {name: BLOCK + facts['c_base'] + (off & ~1)
                 for name, off in facts['entries'].items()}
    return loader, (out / 'fpSup.BIN').read_bytes(), (out / 'lossless.bin').read_bytes()


LAYOUT = {}
C_ENTRIES = {}


def card_symbols():
    from armasm import symbols
    return symbols(HERE / 'native' / 'card.S',
                   ['BLOB_LEN=4', 'BLOCK_BYTES=4', 'STATE_OFF=4'] +
                   [f'{k}=1' for k in CARD_OFFSETS])


class CardCamera(T.Camera):
    """The shared harness, with our allocation given its own block and the
    firmware functions our shims continue into recorded and returned."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        assert T.HEAP <= BLOCK and BLOCK + CARD_BLOCK <= T.HEAP + T.HEAP_SIZE
        self.h_get = []
        self.originals = []
        self.launching = False        # only the launcher's own request is ours
        for name, at in ORIGINAL.items():
            self.by_addr[at] = 'ORIG_' + name
        self.returns = {'ORIG_prepare': 7, 'ORIG_enqueue': 1, 'ORIG_flush': 0,
                        'ORIG_tk_cre_tsk': TASK_ID, 'ORIG_tk_sta_tsk': 0,
                        'ORIG_clip_volume': 1, 'ORIG_clip_path': 0x45100000,
                        'ORIG_f_ctor': 0, 'ORIG_f_open': 0, 'ORIG_f_dtor': 0,
                        'ORIG_tag_add': 0}
        self.task_descriptors = []
        self.flush_result = (0, 0)
        self.irq_depth = 0
        self.observers = []
        self.observer_at = {C_ENTRIES[name]: name for name in (
            'fpl_card_rec', 'fpl_card_flush', 'fpl_card_written', 'fpl_card_event', 'fpl_card_discard')}

    def _hook(self, mu, addr, size, _):
        name = self.by_addr.get(addr)
        if addr in self.observer_at:
            assert self.r(UC_ARM_REG_SP) % 8 == 0, 'observer C entry stack is not 8-aligned'
            self.observers.append(self.observer_at[addr])
        if name in ('ORIG_irq_off', 'ORIG_irq_restore'):
            assert self.r(UC_ARM_REG_SP) % 8 == 0, 'observer native call stack is not 8-aligned'
            if name == 'ORIG_irq_off':
                assert self.irq_depth == 0, 'unexpected nested diagnostic critical section'
                self.irq_depth = 1
                return self._ret(0x13)
            assert self.irq_depth == 1 and self.r(UC_ARM_REG_R0) == 0x13
            self.irq_depth = 0
            return self._ret(0)
        if name == 'H_GET':
            self.h_get.append(tuple(self.r(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1,
                                                        UC_ARM_REG_R2, UC_ARM_REG_R3)))
        if name == 'H_ADDR' and self.launching and self.h_get and self.h_get[-1][2] == CARD_BLOCK:
            self.calls.append(name)
            return self._ret(BLOCK)
        if name and name.startswith('ORIG_'):
            self.calls.append(name)
            self.originals.append((name, tuple(self.r(r) for r in (
                UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)),
                self.r(UC_ARM_REG_SP), self.r(UC_ARM_REG_LR)))
            if name == 'ORIG_tk_cre_tsk':
                d = self.r(UC_ARM_REG_R0)
                self.task_descriptors.append(struct.unpack('<8I', bytes(mu.mem_read(d, 32))))
            if name in ('ORIG_stop_resume', 'ORIG_end_resume', 'ORIG_pool_resume',
                        'ORIG_event_resume'):
                mu.emu_stop()                 # mid-function: look, do not run on
                return
            if name == 'ORIG_flush':
                assert self.r(UC_ARM_REG_SP) % 8 == 0, 'native writer stack not aligned'
                mu.reg_write(UC_ARM_REG_R1, self.flush_result[1])
                mu.reg_write(UC_ARM_REG_CPSR, (self.r(UC_ARM_REG_CPSR) & 0x0FFFFFFF) |
                             0x60000000)
                return self._ret(self.flush_result[0])
            if name == 'ORIG_discard':
                return self._ret(0xCAFE)
            return self._ret(self.returns[name])
        return super()._hook(mu, addr, size, _)


class CardEmulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader, cls.bin, cls.blob = build_card()

    def boot(self, mutate_site=None):
        cam = CardCamera(self.loader, self.bin)
        cam.mu.mem_write(T.SITE, struct.pack('<I', 0xEB000000 | ((((T.CAVE_LOW + 4)
                         - T.SITE - 8) >> 2) & 0xFFFFFF)))
        cam.mu.mem_write(CAVE_BUMP, struct.pack('<I', CAVE_ARENA))
        cam.call(T.CAVE_LOW + 4, r0=0xC0BABDD8, r1=1, lr=T.AR_RET, sp=T.STACK - 0x1004)
        # AFTER stage2: it writes every declared site back to its stock word,
        # which is the journal's repair and would undo an earlier change.
        if mutate_site:
            cam.mu.mem_write(SITES[mutate_site][0], struct.pack('<I', 0xE1A00000))
        self.assertEqual(cam.calls.count('ENTRY'), 1, 'stage2 never reached the entry')
        # our section: destination zero, byte-identical to lossless.bin
        staging = cam.entry - struct.unpack_from('<I', self.bin, 8)[0]
        n = struct.unpack_from('<I', self.bin, 4)[0]
        offset, found = 16 + 8 * n, None
        for i in range(n):
            dest, length = struct.unpack_from('<II', self.bin, 16 + 8 * i)
            if dest == 0 and self.bin[offset:offset + length] == self.blob:
                found = staging + offset
            offset += length + (-length % 4)
        self.assertIsNotNone(found, 'the launcher is not a section of fpSup.BIN')
        cam.launcher = found
        return cam

    def launch(self, cam):
        cam.calls.clear()
        cam.h_get.clear()
        cam.launching = True
        try:
            r0, sp = cam.call(cam.launcher, r0=cam.launcher, sp=T.STACK - 0x1000)
        finally:
            cam.launching = False
        self.assertEqual(sp, T.STACK - 0x1000, 'the launcher left the stack moved')
        return r0

    def cave_block(self, cam):
        return cam.word(CAVE_BUMP) - CAVE_BYTES

    # ---- the launcher -------------------------------------------------
    def test_the_sites_are_journaled_by_stage2_before_the_entry(self):
        cam = self.boot()
        for name, (site, stock) in SITES.items():
            self.assertEqual(cam.word(site), stock, name)

    def test_it_allocates_its_own_user_block_copies_publishes_then_arms(self):
        cam = self.boot()
        self.assertEqual(self.launch(cam), 0)
        self.assertEqual(cam.h_get[-1][1:3], (0, CARD_BLOCK), 'not its own USER block')
        # identical but for the state/entry words the launcher resolves
        words = card_symbols()
        lo, hi = words['g_card'], words['stop_resume']
        # one word per entry the shims call, plus g_card; OFF_INIT and
        # OFF_OBSERVER are called once at load and have none
        resident_words = len(CARD_OFFSETS) - 1
        self.assertEqual(hi - lo, 4 * resident_words)
        resident = bytes(cam.mu.mem_read(BLOCK, len(self.blob)))
        self.assertEqual(resident[:lo], self.blob[:lo])
        self.assertEqual(resident[hi:], self.blob[hi:])
        self.assertEqual(self.blob[lo:hi], b'\0' * (hi - lo))
        filled = struct.unpack(f'<{resident_words}I', resident[lo:hi])
        self.assertTrue(all(filled), 'a resident word was left empty')
        calls = [c for c in cam.calls if c in ('H_GET', 'H_ADDR', 'DCACHE', 'ICACHE')]
        self.assertEqual(calls, ['H_GET', 'H_ADDR', 'DCACHE', 'ICACHE',
                                 'DCACHE', 'ICACHE', 'DCACHE', 'ICACHE'])

    def test_init_starts_the_codec_task_at_the_resident_task_shim(self):
        cam = self.boot()
        self.assertEqual(self.launch(cam), 0)
        words = card_symbols()
        self.assertEqual(len(cam.task_descriptors), 1)
        exinf, atr, entry, pri, stksz, n0, n1, tail = cam.task_descriptors[0]
        self.assertEqual((exinf, atr, pri, stksz, tail), (0, 0x41, 12, 0x2000, 0))
        self.assertEqual(struct.pack('<II', n0, n1), b'FPLCODE\0')
        self.assertEqual(entry, BLOCK + words['task_shim'], 'not the resident shim')
        starts = [o for o in cam.originals if o[0] == 'ORIG_tk_sta_tsk']
        self.assertEqual(starts[0][1][:2], (TASK_ID, 0))
        # the shim hands the task the card state and enters fpl_card_task
        resident = bytes(cam.mu.mem_read(BLOCK, len(self.blob)))
        g_card, w_task = struct.unpack_from('<I', resident, words['g_card'])[0], \
            struct.unpack_from('<I', resident, words['w_task'])[0]
        self.assertTrue(g_card and w_task)

    def test_every_site_branches_to_its_veneer_and_every_veneer_to_its_shim(self):
        cam = self.boot()
        self.launch(cam)
        cave = self.cave_block(cam)
        self.assertEqual(cave, CAVE_ARENA)
        for i, (name, (site, _)) in enumerate(SITES.items()):
            word = cam.word(site)
            op = 0xEA000000 if name in ('stop', 'end', 'pool', 'event') else 0xEB000000
            self.assertEqual(word & 0xFF000000, op, name)
            disp = word & 0xFFFFFF
            disp = disp - 0x1000000 if disp & 0x800000 else disp
            self.assertEqual(site + 8 + 4 * disp, cave + VENEER_AT[name], name)
            self.assertEqual(cam.word(cave + VENEER_AT[name]), 0xE51FF004, name)
            shim = cam.word(cave + VENEER_AT[name] + 4)
            self.assertTrue(BLOCK <= shim < BLOCK + len(self.blob), f'{name} shim {shim:#x}')
        self.assertEqual(cam.word(cave + 32), 0x43504C46)
        self.assertEqual(cam.word(cave + 40), BLOCK)
        state = cam.word(cave + 36)
        self.assertEqual(cam.word(state), 0x44524143, 'card state not initialised')

    def test_a_site_that_is_not_stock_arms_nothing(self):
        for which in SITES:
            with self.subTest(site=which):
                cam = self.boot(mutate_site=which)
                self.launch(cam)
                for name, (site, stock) in SITES.items():
                    expect = 0xE1A00000 if name == which else stock
                    self.assertEqual(cam.word(site), expect, f'{name} armed anyway')
                self.assertEqual(cam.word(CAVE_BUMP), CAVE_ARENA, 'cave taken anyway')

    def test_a_full_cave_arms_nothing(self):
        cam = self.boot()
        cam.mu.mem_write(CAVE_BUMP, struct.pack('<I', CAVE_END - 40))
        self.launch(cam)
        for name, (site, stock) in SITES.items():
            self.assertEqual(cam.word(site), stock, name)

    # ---- through the veneers ------------------------------------------
    def enter(self, cam, name, regs, lr=T.DONE, r4=0x44444444, stack_delta=0):
        site = SITES[name][0]
        word = cam.word(site)
        disp = word & 0xFFFFFF
        disp = disp - 0x1000000 if disp & 0x800000 else disp
        veneer = site + 8 + 4 * disp
        mu = cam.mu
        for reg, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), regs):
            mu.reg_write(reg, v)
        mu.reg_write(UC_ARM_REG_R4, r4)
        mu.reg_write(UC_ARM_REG_R11, 0xBBBBBBBB)
        mu.reg_write(UC_ARM_REG_SP, T.STACK - 0x2000 - stack_delta)
        mu.reg_write(UC_ARM_REG_LR, lr)
        cam.originals.clear()
        mu.emu_start(veneer, T.DONE, count=2_000_000)
        return cam.r(UC_ARM_REG_R0)

    def armed(self):
        cam = self.boot()
        self.launch(cam)
        return cam

    def field(self, cam, path):
        state = cam.word(self.cave_block(cam) + 36)
        return cam.word(state + LAYOUT[path])

    def mutate_instruction(self, cam, label, expected, replacement):
        at = BLOCK + card_symbols()[label]
        self.assertEqual(cam.word(at), expected, f'{label} mutation no longer targets its instruction')
        cam.mu.mem_write(at, struct.pack('<I', replacement))

    def test_rec_passes_any_other_request_to_the_original(self):
        for delta in (0, 4):
            with self.subTest(stack_delta=delta):
                cam = self.armed()
                request = T.STACK - 0x3000
                cam.mu.mem_write(request, struct.pack('<I', 1))
                self.assertEqual(self.enter(cam, 'rec', (0x1234, request), stack_delta=delta), 7)
                (name, regs, sp, lr), = cam.originals
                self.assertEqual((name, regs[:2]), ('ORIG_prepare', (0x1234, request)))
                self.assertEqual(sp % 8, 0)
                self.assertTrue(BLOCK <= lr < BLOCK + len(self.blob))
                self.assertEqual(cam.r(UC_ARM_REG_SP), T.STACK - 0x2000 - delta)
                self.assertEqual(cam.r(UC_ARM_REG_R4), 0x44444444)

    def test_rec_resets_diagnostics_when_lossless_is_off(self):
        cam = self.armed()
        state = cam.word(self.cave_block(cam) + 36)
        for path in ('take_frames', 'record_diag.writer_calls', 'record_diag.discard_count'):
            cam.mu.mem_write(state + LAYOUT[path], struct.pack('<I', 99))
        request = T.STACK - 0x3000
        cam.mu.mem_write(request, struct.pack('<I', 0x23))
        self.assertEqual(self.enter(cam, 'rec', (0x1234, request), stack_delta=4), 7)
        for path in ('take_frames', 'record_diag.writer_calls', 'record_diag.discard_count'):
            self.assertEqual(self.field(cam, path), 0, path)
        self.assertEqual(self.field(cam, 'rec_menu_off'), 1)
        self.assertEqual(cam.irq_depth, 0)

    def test_rec_never_touches_the_bulk_size(self):
        """2026-10-14 (user): the 64 MB bulk size is no longer LOSS's to set --
        the rec-core writer owns the file layer. REC leaves the word as found."""
        cam = self.armed()
        cam.mu.mem_write(BULK, struct.pack('<I', 0x00C00000))
        request = T.STACK - 0x3000
        cam.mu.mem_write(request, struct.pack('<I', 0x23))
        self.assertEqual(self.enter(cam, 'rec', (0x1234, request), stack_delta=4), 7)
        self.assertEqual(cam.word(BULK), 0x00C00000)

    def test_mutation_omitting_rec_alignment_is_caught(self):
        cam = self.armed()
        self.mutate_instruction(cam, 'rec_align', 0xE3CDD007, 0xE1A0D00D)
        request = T.STACK - 0x3000
        cam.mu.mem_write(request, struct.pack('<I', 1))
        with self.assertRaisesRegex(AssertionError, 'observer C entry stack is not 8-aligned'):
            self.enter(cam, 'rec', (0x1234, request), stack_delta=4)

    def test_arrive_calls_an_unknown_vtable_target_untouched(self):
        cam = self.armed()
        self.enter(cam, 'arrive', (0xC0DE, 5, 1, T.DONE))
        self.assertEqual(cam.originals, [])
        self.assertEqual((cam.r(UC_ARM_REG_R0), cam.r(UC_ARM_REG_R1)), (0xC0DE, 5))

    def test_arrive_without_a_take_is_the_original_enqueue(self):
        cam = self.armed()
        self.assertEqual(self.enter(cam, 'arrive', (0xC0DE, 5, 1, ORIGINAL['enqueue'])), 1)
        (name, regs, _sp, lr), = cam.originals
        self.assertEqual((name, regs[:3]), ('ORIG_enqueue', (0xC0DE, 5, 1)))
        self.assertEqual(lr, T.DONE)
        self.assertEqual(cam.r(UC_ARM_REG_R4), 0x44444444, 'r4 not preserved')
        self.assertEqual(cam.r(UC_ARM_REG_R11), 0xBBBBBBBB, 'r11 not preserved')
        self.assertEqual(self.field(cam, 'take_frames'), 1, 'OFF arrivals were not counted')

    def test_flush_keeps_every_argument_for_the_real_flush(self):
        cam = self.armed()
        writer = T.STACK - 0x3000
        cam.mu.mem_write(writer, b'\0' * 0x100)
        self.enter(cam, 'flush', (writer, 0x11, 0x22, 0x33))
        (name, regs, sp, lr), = cam.originals
        self.assertEqual(name, 'ORIG_flush')
        self.assertEqual(regs, (writer, 0x11, 0x22, 0x33))
        self.assertEqual(sp % 8, 0)
        self.assertTrue(BLOCK <= lr < BLOCK + len(self.blob))
        self.assertEqual(cam.r(UC_ARM_REG_SP), T.STACK - 0x2000)
        self.assertEqual(cam.r(UC_ARM_REG_R4), 0x44444444)

    def check_event(self, cam, stack_delta=0):
        message = T.STACK - 0x4000
        cam.mu.mem_write(message, b'\0' * 0x100)
        cam.mu.mem_write(message + 0x0C, struct.pack('<I', 5))
        cam.mu.mem_write(message + 0xE4, struct.pack('<II', 1, 7))
        cam.mu.reg_write(UC_ARM_REG_R6, 0)
        cam.mu.reg_write(UC_ARM_REG_CPSR, (cam.r(UC_ARM_REG_CPSR) & 0x0FFFFFFF) | 0xA0000000)
        self.enter(cam, 'event', (0xA0, 0xA1, 0xA2, 0xA3), r4=message,
                   stack_delta=stack_delta)
        (name, regs, sp, lr), = cam.originals
        self.assertEqual(name, 'ORIG_event_resume')
        self.assertEqual(regs, (0xA0, 0xA1, 0xA2, 5), 'displaced event load not replayed')
        self.assertEqual((sp, lr), (T.STACK - 0x2000 - stack_delta, T.DONE))
        self.assertEqual(cam.r(UC_ARM_REG_CPSR) & 0xF0000000, 0xA0000000)
        self.assertEqual(self.field(cam, 'record_diag.raw_errors'), 1)
        self.assertEqual(self.field(cam, 'record_diag.last_slot'), 7)
        self.assertEqual(self.field(cam, 'record_diag.last_missing'), 1)
        self.assertEqual(cam.irq_depth, 0)
        self.assertIn('fpl_card_event', cam.observers)

    def test_event_observation_preserves_displaced_load_flags_and_both_stack_alignments(self):
        for delta in (0, 4):
            with self.subTest(stack_delta=delta):
                self.check_event(self.armed(), delta)

    def check_discard(self, cam, stack_delta=0):
        frame = 0x45200000
        data = bytearray(0x1200)
        name = b'A001_001_000059.DNG\0'
        data[0x1030:0x1030 + len(name)] = name
        struct.pack_into('<II', data, 0x10FC, 7, 123)
        cam.mu.mem_write(frame, bytes(data))
        original_sp = T.STACK - 0x2000 - stack_delta
        cam.mu.mem_write(original_sp + 12, struct.pack('<I', 0xC038BF0C))
        result = self.enter(cam, 'discard', (0xC0DE, frame, 0x22, 0x33),
                            stack_delta=stack_delta)
        (called, regs, sp, lr), = cam.originals
        self.assertEqual((called, regs), ('ORIG_discard', (0xC0DE, frame, 0x22, 0x33)))
        self.assertEqual((result, sp, lr), (0xCAFE, original_sp, T.DONE))
        self.assertEqual(cam.r(UC_ARM_REG_SP), original_sp)
        self.assertEqual(self.field(cam, 'record_diag.discard_count'), 1)
        self.assertEqual(self.field(cam, 'record_diag.discard_raw'), 1,
                         'clear caller was read from the wrong stack frame')
        state = cam.word(self.cave_block(cam) + 36)
        row = state + LAYOUT['record_diag.drops']
        self.assertEqual(struct.unpack('<III', cam.mu.mem_read(row, 12)), (7, 123, 0xC038BF0C))
        self.assertEqual(bytes(cam.mu.mem_read(row + 12, 48)), bytes(data[0x1030:0x1060]))
        self.assertEqual(bytes(cam.mu.mem_read(frame, len(data))), bytes(data), 'observer changed frame')
        self.assertEqual(cam.irq_depth, 0)

    def test_discard_records_one_popped_frame_then_calls_original_once(self):
        for delta in (0, 4):
            with self.subTest(stack_delta=delta):
                self.check_discard(self.armed(), delta)

    def check_writer_result(self, cam, result, stack_delta=0):
        writer = T.STACK - 0x3000
        cam.mu.mem_write(writer, b'\0' * 0x100)
        cam.flush_result = result
        self.enter(cam, 'flush', (writer, 0x11, 0x22, 0x33), stack_delta=stack_delta)
        (name, regs, _sp, _lr), = cam.originals
        self.assertEqual((name, regs), ('ORIG_flush', (writer, 0x11, 0x22, 0x33)))
        self.assertEqual((cam.r(UC_ARM_REG_R0), cam.r(UC_ARM_REG_R1)), result)
        self.assertEqual(cam.r(UC_ARM_REG_SP), T.STACK - 0x2000 - stack_delta)
        self.assertEqual(cam.r(UC_ARM_REG_R4), 0x44444444)
        self.assertEqual(cam.r(UC_ARM_REG_R11), 0xBBBBBBBB)
        self.assertEqual(cam.r(UC_ARM_REG_CPSR) & 0xF0000000, 0x60000000)
        self.assertEqual(self.field(cam, 'record_diag.writer_calls'), 1)
        self.assertEqual(self.field(cam, 'record_diag.writer_low'), result[0])
        self.assertEqual(self.field(cam, 'record_diag.writer_high'), result[1],
                         'writer high return word was lost')
        self.assertEqual(self.field(cam, 'record_diag.writer_nonzero'), int(any(result)))
        self.assertEqual(self.field(cam, 'record_diag.writer_zero'), int(not any(result)))
        self.assertEqual(cam.irq_depth, 0)

    def test_writer_observes_full_return_and_restores_both_stack_alignments(self):
        for delta in (0, 4):
            for result in ((0, 0), (0, 1), (0x12345678, 0)):
                with self.subTest(stack_delta=delta, result=result):
                    self.check_writer_result(self.armed(), result, delta)

    def test_mutation_omitting_event_alignment_is_caught(self):
        cam = self.armed()
        self.mutate_instruction(cam, 'event_align', 0xE3CDD007, 0xE1A0D00D)
        with self.assertRaisesRegex(AssertionError, 'observer C entry stack is not 8-aligned'):
            self.check_event(cam, 4)

    def test_mutation_omitting_displaced_load_is_caught(self):
        cam = self.armed()
        self.mutate_instruction(cam, 'event_replay', 0xE594300C, 0xE1A00000)
        with self.assertRaisesRegex(AssertionError, 'displaced event load not replayed'):
            self.check_event(cam)

    def test_mutation_reading_shim_lr_instead_of_clear_caller_is_caught(self):
        cam = self.armed()
        self.mutate_instruction(cam, 'discard_caller', 0xE595202C, 0xE595201C)
        with self.assertRaisesRegex(AssertionError, 'clear caller was read from the wrong stack frame'):
            self.check_discard(cam)

    def test_mutation_discarding_writer_high_word_is_caught(self):
        cam = self.armed()
        self.mutate_instruction(cam, 'written_high', 0xE1A02001, 0xE3A02000)
        with self.assertRaisesRegex(AssertionError, 'writer high return word was lost'):
            self.check_writer_result(cam, (0, 1))

    def test_play_does_the_displaced_load_and_returns_through_lr(self):
        """The player's slot in r5, a stock frame (root on IFD0) in its
        buffer: the shim leaves the frame alone, loads r2 = slot+0x1c as the
        site did, keeps the callee-saved registers and returns through lr."""
        from unicorn.arm_const import UC_ARM_REG_R5, UC_ARM_REG_R2
        cam = self.armed()
        slot, buf = T.STACK - 0x3000, 0x45200000
        frame = b'II*\0' + struct.pack('<I', 8) + b'\x11' * 56
        cam.mu.mem_write(buf, frame)
        cam.mu.mem_map(buf + 0x40000000, 0x1000)       # the uncached alias the reads use
        cam.mu.mem_write(buf + 0x40000000, frame)
        cam.mu.mem_write(slot, b'\0' * 0x14 + struct.pack('<III', buf, 0x100000, len(frame)))
        cam.mu.reg_write(UC_ARM_REG_R5, slot)
        self.enter(cam, 'play', (0xA0, 0xA1, 0xA2, 0xA3))
        self.assertEqual(cam.r(UC_ARM_REG_R2), len(frame), 'displaced load not done')
        self.assertEqual(cam.r(UC_ARM_REG_R5), slot)
        self.assertEqual(cam.r(UC_ARM_REG_R4), 0x44444444)
        self.assertEqual(cam.r(UC_ARM_REG_SP), T.STACK - 0x2000)
        self.assertEqual(bytes(cam.mu.mem_read(buf, len(frame))), frame, 'a stock frame changed')

    def test_stop_runs_the_displaced_push_and_continues_into_the_original(self):
        cam = self.armed()
        self.enter(cam, 'stop', (1, 0x77, 0, 0))
        (name, regs, sp, _lr), = cam.originals
        self.assertEqual((name, regs[:2]), ('ORIG_stop_resume', (1, 0x77)))
        # exactly push {r4-r8, fp, lr}: seven words, lr on top
        self.assertEqual(sp, T.STACK - 0x2000 - 28)
        pushed = struct.unpack('<7I', cam.mu.mem_read(sp, 28))
        self.assertEqual(pushed[0], 0x44444444)            # r4
        self.assertEqual(pushed[5], 0xBBBBBBBB)            # fp
        self.assertEqual(pushed[6], T.DONE)                # the caller's lr


    def test_clip_stores_the_size_through_the_displaced_store(self):
        """r3 the first frame's size, r4 the player, r6 the clip: with the
        first frame unreadable the size is stored as the firmware had it."""
        from unicorn.arm_const import UC_ARM_REG_R6
        from unicorn.arm_const import UC_ARM_REG_R3
        cam = self.armed()
        for name, at in CLIP_FILE.items():
            cam.by_addr[at] = 'ORIG_' + name
        player = T.STACK - 0x3000
        cam.mu.mem_write(player, b'\0' * 0x100)
        cam.mu.reg_write(UC_ARM_REG_R6, 0xDE5C)
        self.enter(cam, 'clip', (0xA0, 0xA1, 0xA2, 0x334000), r4=player)
        self.assertIn('ORIG_f_open', cam.calls, 'the first frame was not asked for')
        self.assertEqual(cam.word(player + 0xA0), 0x334000, 'displaced store not done')
        self.assertEqual(cam.r(UC_ARM_REG_R3), 0x334000)
        self.assertEqual(cam.r(UC_ARM_REG_R4), player)
        self.assertEqual(cam.r(UC_ARM_REG_SP), T.STACK - 0x2000)

    def test_end_runs_the_displaced_push_and_continues_into_the_original(self):
        cam = self.armed()
        self.enter(cam, 'end', (0x55, 0, 0, 0))
        (name, regs, sp, _lr), = [o for o in cam.originals if o[0] == 'ORIG_end_resume']
        self.assertEqual(regs[0], 0x55)
        self.assertEqual(sp, T.STACK - 0x2000 - 16)          # push {r4, r5, r6, lr}
        pushed = struct.unpack('<4I', cam.mu.mem_read(sp, 16))
        self.assertEqual(pushed[0], 0x44444444)
        self.assertEqual(pushed[3], T.DONE)


    def test_pool_runs_the_displaced_push_and_continues_into_the_original(self):
        cam = self.armed()
        self.enter(cam, 'pool', (0x66, 0x77, 0, 0))
        (name, regs, sp, _lr), = [o for o in cam.originals if o[0] == 'ORIG_pool_resume']
        self.assertEqual(regs[:2], (0x66, 0x77))
        self.assertEqual(sp, T.STACK - 0x2000 - 24)          # push {r4-r7, sl, lr}
        pushed = struct.unpack('<6I', cam.mu.mem_read(sp, 24))
        self.assertEqual(pushed[0], 0x44444444)
        self.assertEqual(pushed[5], T.DONE)


    # ---- the header template's observer (header_tag.h) -------------------
    SUBJECT = 0xC31AC4EC
    TEMPLATE_PTR, TEMPLATE_LEN = 0xC358DBA8, 0xC358DBA4
    POOL, POOL_VT, EVENT, BUILDER, POOL_FN = (0xC3F00000, 0xC3F00100, 0xC3F00200,
                                              0xC3F00300, 0xC3F00400)
    TEMPLATE = 0xC3E00000

    @staticmethod
    def put(cam, at, value):
        cam.mu.mem_write(at, struct.pack('<I', value & 0xFFFFFFFF))

    @staticmethod
    def movw_movt(rd, value):
        lo, hi = value & 0xFFFF, value >> 16
        return [0xE3000000 | (lo >> 12) << 16 | rd << 12 | (lo & 0xFFF),
                0xE3400000 | (hi >> 12) << 16 | rd << 12 | (hi & 0xFFF)]

    def data_pool(self, cam, mode, flag=0):
        """A DataPool: vtable +0x40 returns the event {mode, 3, flag}, +0x2C
        the builder -- as FUN_c00559f0 leaves them for the observers."""
        code = (self.movw_movt(0, self.EVENT) + [0xE12FFF1E] +
                self.movw_movt(0, self.BUILDER) + [0xE12FFF1E])
        cam.mu.mem_write(self.POOL_FN, struct.pack(f'<{len(code)}I', *code))
        self.put(cam, self.POOL, self.POOL_VT)
        self.put(cam, self.POOL_VT + 0x40, self.POOL_FN)
        self.put(cam, self.POOL_VT + 0x2C, self.POOL_FN + 12)
        cam.mu.mem_write(self.EVENT, struct.pack('<3I', mode, 3, flag))

    def set_field(self, cam, path, value):
        state = cam.word(self.cave_block(cam) + 36)
        self.put(cam, state + LAYOUT[path], value)

    def notify(self, cam, mode, flag=0):
        """The Subject's notify loop calling our slot: vt+0xC(observer, pool),
        from a stack 4 off 8 as the firmware's may be."""
        self.data_pool(cam, mode, flag)
        obs = cam.word(self.SUBJECT + 4 * (self.field(cam, 'observer_slot') - 1))
        shim = cam.word(cam.word(obs) + 0xC)
        cam.originals.clear()
        sp = T.STACK - 0x2004
        for reg in range(4, 12):
            cam.mu.reg_write(getattr(__import__('unicorn.arm_const', fromlist=['x']),
                                     f'UC_ARM_REG_R{reg}'), 0x40404040 + reg)
        r0, sp_after = cam.call(shim, r0=obs, r1=self.POOL, sp=sp)
        self.assertEqual((r0, sp_after), (1, sp), 'observer must return 1 with the stack as given')
        for reg in range(4, 12):
            self.assertEqual(cam.r(getattr(__import__('unicorn.arm_const', fromlist=['x']),
                                           f'UC_ARM_REG_R{reg}')), 0x40404040 + reg)

    def template(self, cam):
        sys.path.insert(0, str(HERE / 'native'))
        import test_header_tag as H
        stock = H.STOCK.read_bytes()
        tmpl, head = H.make_template(stock)
        cam.mu.mem_write(self.TEMPLATE, bytes(tmpl))
        self.put(cam, self.TEMPLATE_PTR, self.TEMPLATE)
        self.put(cam, self.TEMPLATE_LEN, head)
        return tmpl, head, H

    def test_the_observer_is_put_on_the_subject_list_last(self):
        cam = self.armed()
        self.assertEqual(self.field(cam, 'observer_slot'), 1)
        obs = cam.word(self.SUBJECT)
        self.assertEqual(cam.word(cam.word(obs) + 0xC), BLOCK + card_symbols()['obs_shim'])
        self.assertEqual([cam.word(self.SUBJECT + 4 * n) for n in range(1, 9)], [0] * 8)
        # after every site is armed: the last call before the final cache flush
        self.assertEqual(cam.calls[-2:], ['DCACHE', 'ICACHE'])

    def test_a_full_subject_list_is_left_alone(self):
        cam = self.boot()
        taken = [0x1000 + n for n in range(9)]
        cam.mu.mem_write(self.SUBJECT, struct.pack('<9I', *taken))
        self.assertEqual(self.launch(cam), 0)
        self.assertEqual(list(struct.unpack('<9I', cam.mu.mem_read(self.SUBJECT, 36))), taken)
        self.assertEqual(self.field(cam, 'observer_slot'), 0)
        self.assertEqual(self.field(cam, 'observer_full'), 1)

    def test_an_admitted_take_gets_its_tag_and_its_ifd_and_nothing_per_frame(self):
        cam = self.armed()
        tmpl, head, H = self.template(cam)
        self.set_field(cam, 'tag_want', 1)
        self.set_field(cam, 'tag_bytes', H.TAG_BYTES)
        self.set_field(cam, 'hold.require_head', 0xFFFFFFFF)   # as REC leaves it
        # mode 0, the template build: the tag is added to the open builder
        self.notify(cam, 0)
        adds = [o for o in cam.originals if o[0] == 'ORIG_tag_add']
        self.assertEqual(len(adds), 1)
        (_, regs, sp, _), = adds
        self.assertEqual(regs, (self.BUILDER, 0, 0xFD4C, 7))
        count, value = struct.unpack('<II', cam.mu.mem_read(sp, 8))
        self.assertEqual(count, H.TAG_BYTES)
        self.assertEqual(bytes(cam.mu.mem_read(value, count)), bytes(count))
        self.assertEqual((self.field(cam, 'tag_added'), self.field(cam, 'tag_want'),
                          self.field(cam, 'tag_pending')), (1, 0, 1))
        # mode 2 after the serialization: the IFD goes into the template
        self.notify(cam, 2, 1)
        self.assertEqual(self.field(cam, 'tag_prepare_result'), 0)
        self.assertEqual((self.field(cam, 'tag_prepared'), self.field(cam, 'tag_head')),
                         (1, head))
        self.assertNotEqual(self.field(cam, 'tag_live'), 0)
        self.assertEqual(self.field(cam, 'hold.require_head'), head, 'frames still refused')
        live = bytes(cam.mu.mem_read(self.TEMPLATE, head))
        value_at = struct.unpack_from('<I', live, H.entry_at(live, 0x13400, 0xFD4C) + 8)[0]
        ifd_at = (value_at + 3) & ~3
        n, = struct.unpack_from('<H', live, ifd_at)
        root_n, = struct.unpack_from('<H', live, 0x13400)
        self.assertEqual(n, root_n - 3 + 4)
        self.assertEqual(live[:value_at], bytes(tmpl[:value_at]), 'wrote outside the tag')
        # mode 3, every frame: the values the firmware rewrites are shared,
        # so the per-frame notify writes nothing
        self.notify(cam, 3)
        self.assertEqual(bytes(cam.mu.mem_read(self.TEMPLATE, head)), live)
        self.assertEqual([o for o in cam.originals if o[0] == 'ORIG_tag_add'], [])

    def test_a_take_it_did_not_admit_is_not_touched(self):
        cam = self.armed()
        tmpl, head, _ = self.template(cam)
        for mode, flag in ((0, 0), (2, 1), (3, 0)):
            self.notify(cam, mode, flag)
        self.assertEqual([o for o in cam.originals if o[0] == 'ORIG_tag_add'], [])
        self.assertEqual(bytes(cam.mu.mem_read(self.TEMPLATE, head)), bytes(tmpl))
        self.assertEqual((self.field(cam, 'tag_mode0'), self.field(cam, 'tag_added'),
                          self.field(cam, 'tag_prepared'), self.field(cam, 'tag_live')),
                         (1, 0, 0, 0))

    def test_a_template_without_the_tag_leaves_the_take_raw(self):
        cam = self.armed()
        tmpl, head, H = self.template(cam)
        stock = H.STOCK.read_bytes()[:0x13400]
        cam.mu.mem_write(self.TEMPLATE, stock)
        self.put(cam, self.TEMPLATE_LEN, 0x13400)
        self.set_field(cam, 'tag_pending', 1)
        self.notify(cam, 2, 1)
        self.assertEqual(self.field(cam, 'tag_prepare_result'), 3)      # UNSUPPORTED
        self.assertEqual((self.field(cam, 'tag_prepared'), self.field(cam, 'tag_live')), (0, 0))
        self.assertEqual(bytes(cam.mu.mem_read(self.TEMPLATE, 0x13400)), stock)
        self.assertNotEqual(self.field(cam, 'hold.require_head'), 0x13400, 'frames would be held')

    def test_a_new_take_forgets_the_prepared_ifd(self):
        cam = self.armed()
        self.template(cam)
        self.set_field(cam, 'tag_pending', 1)
        self.notify(cam, 2, 1)
        self.assertNotEqual(self.field(cam, 'tag_live'), 0)
        request = T.STACK - 0x3000
        cam.mu.mem_write(request, struct.pack('<I', 0x23))
        self.enter(cam, 'rec', (0x1234, request), stack_delta=4)
        self.assertEqual(self.field(cam, 'tag_live'), 0)


# ---- the Lossless RAW row, composed by ui_apply in the ARM build -------------
GUI_OBJECT = 0xC37B7048
UI_AREA = 0xC3A00000                  # app, screens, reader, entries, names: unused BSS
APP, SCREENS, SCREEN, READER, ENTRIES, NAMES, REGISTRY, DESCS = (
    UI_AREA + o for o in (0x0, 0x1000, 0x2000, 0x3000, 0x4000, 0x6000, 0x8000, 0x9000))
UIA_HEAP, UIA_HEAP_SIZE = 0x46000000, 0x01000000
SCREEN_NAMES = ['MainB1', 'MainB2', 'MainY4']
ENTRY_OFFSETS = [0x74D796, 0x76FF04, 0x889C60]
REG_LOOKUP, REG_ADD = 0xC05DB418, 0xC05DB308          # Thumb, entered with bit 0 clear


class MenuCamera(CardCamera):
    """The card camera plus the native UI objects the row installer expects
    (laid out as read from the camera, fp-native-ui §8a), a sequential file,
    a real allocator for the UI copies, and the variable registry."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        mu = self.mu
        mu.mem_map(UIA_HEAP, UIA_HEAP_SIZE)
        self.uia_next = UIA_HEAP
        self.file_pos = 0
        self.vars = {}
        self.ui_ready = False

    def setup_ui(self):
        mu, w = self.mu, lambda a, v: self.mu.mem_write(a, struct.pack('<I', v))
        w(GUI_OBJECT, APP)
        w(APP + 0x80, len(SCREEN_NAMES)); w(APP + 0x8C, SCREENS); w(APP + 0x888, REGISTRY - 0x60)
        for i, (name, off) in enumerate(zip(SCREEN_NAMES, ENTRY_OFFSETS)):
            s, n = SCREEN + 0x40 * i, NAMES + 0x40 * i
            mu.mem_write(n, name.encode() + b'\0')
            w(SCREENS + 4 * i, s); w(s + 4, APP); w(s + 8, n); w(s + 0x24, READER)
            w(ENTRIES + 44 * i + 4, n); w(ENTRIES + 44 * i + 8, off)
        w(READER + 0x10, 176152); w(READER + 0x14, 0xC18C0474); w(READER + 0x24, 0xC18C0460)
        w(READER + 0xA8, len(SCREEN_NAMES)); w(READER + 0xAC, ENTRIES)
        self.by_addr[REG_LOOKUP] = 'REG_LOOKUP'
        self.by_addr[REG_ADD] = 'REG_ADD'
        self.ui_ready = True

    def _hook(self, mu, addr, size, _):
        name = self.by_addr.get(addr)
        if self.ui_ready and name in ('REG_LOOKUP', 'REG_ADD', 'F_OPEN', 'F_READ', 'H_ADDR'):
            r = [self.r(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]
            self.calls.append(name)
            if name == 'REG_LOOKUP':
                d = self.vars.get(self.cstr(r[1]), 0)
                mu.mem_write(r[2], struct.pack('<I', d))
                return self._ret(0)
            if name == 'REG_ADD':
                kind, nameptr, value = struct.unpack('<3I', mu.mem_read(r[2], 12))
                d = DESCS + 32 * len(self.vars)
                mu.mem_write(d, struct.pack('<3I', kind, nameptr, value))
                self.vars[self.cstr(nameptr)] = d
                return self._ret(0)
            if name == 'F_OPEN':
                self.file_pos = 0
                return self._ret(1)
            if name == 'F_READ':                 # (obj, buf, len, &actual) -> 1
                data = self.bin[self.file_pos:self.file_pos + r[2]]
                mu.mem_write(r[1], data)
                self.file_pos += len(data)
                mu.mem_write(r[3], struct.pack('<I', len(data)))
                return self._ret(1)
            if name == 'H_ADDR':
                size_ = self.h_get[-1][2] if self.h_get else 0
                if self.launching and size_ == CARD_BLOCK:
                    return self._ret(BLOCK)
                got = self.uia_next
                self.uia_next = (self.uia_next + size_ + 0xFFF) & ~0xFFF
                assert self.uia_next <= UIA_HEAP + UIA_HEAP_SIZE, 'emulated heap exhausted'
                return self._ret(got)
        return super()._hook(mu, addr, size, _)


class MenuEmulationTests(unittest.TestCase):
    """The row installer and ui_apply as the camera runs them: the card's own
    launcher bytes, Thumb, against the stock NBU in the pinned image."""

    @classmethod
    def setUpClass(cls):
        cls.loader, cls.bin, cls.blob = build_card()
        sys.path.insert(0, str(HERE / 'menu'))
        sys.path.insert(0, str(HERE.parent / 'uishare'))
        import build_fpui
        from ui import fpui
        cls.fpui = fpui
        cls.block, _, (cls.stock_page, cls.pool_stock, _) = build_fpui.build()

    def boot_with_ui(self):
        case = CardEmulationTests()
        case.loader, case.bin, case.blob = self.loader, self.bin, self.blob
        global CardCamera
        saved, CardCamera = CardCamera, MenuCamera
        try:
            cam = case.boot()
        finally:
            CardCamera = saved
        cam.setup_ui()
        case.launch(cam)
        return cam

    def field(self, cam, path):
        state = cam.word(cam.word(CAVE_BUMP) - CAVE_BYTES + 36)
        return cam.word(state + LAYOUT[path])

    def test_the_row_is_installed_and_mainb2_is_the_reference_page(self):
        cam = self.boot_with_ui()
        self.assertEqual(self.field(cam, 'menu.result'), 1, 'menu not installed')
        self.assertEqual(self.field(cam, 'menu.registered'), 3)
        off = cam.word(ENTRIES + 44 * 1 + 8)
        self.assertNotEqual(off, 0x76FF04, 'MainB2 not switched')
        page_at = (0xC18C0460 + off) & 0xFFFFFFFF
        hdr = struct.unpack('<32I', bytes(cam.mu.mem_read((page_at & ~3) - 128, 128)))
        self.assertEqual(hdr[0], 0x47505346)
        page = bytes(cam.mu.mem_read(page_at, hdr[3]))
        pages = {'MainB2': self.fpui.PageCopy(self.stock_page, len(self.stock_page), 1)}
        pool = self.fpui.Strings(self.pool_stock)
        self.fpui.apply(self.block, pages, pool)
        self.assertEqual(page, bytes(pages['MainB2'].data))
        # private strings in the row's own string layer; the pool untouched
        # (uishare/NESTED_HOOKS.md), and the firmware's resolver finds them
        from ui import chain
        self.assertEqual((cam.word(READER + 0x14), cam.word(READER + 0x10)), (0xC18C0474, 176152))
        self.assertEqual(chain.layers(cam.word), pool.layers)
        for base, texts in pool.layers:
            for i, text in enumerate(texts):
                r0, _ = cam.call(0xC05E5B58 | 1, r0=READER, r1=base + i, sp=T.STACK - 0x1000)
                self.assertEqual(cam.cstr(r0), text)
        self.assertEqual(set(cam.vars), {'MV_fpLossless', 'SUB_MV_fpLossless', 'EXCL_fpLossless'})
        # the firmware image itself is untouched: MainB2's stock bytes
        self.assertEqual(bytes(cam.mu.mem_read(0xC2030364, len(self.stock_page))), self.stock_page)


if __name__ == '__main__':
    unittest.main()
