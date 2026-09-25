#!/usr/bin/env python3
"""Offline four-box splash regressions; never opens a camera or card.

Build checks cover the emitted scripts and assets. ARM execution uses Unicorn
with firmware calls stubbed: it checks our control flow and ABI, not actual LCD
presentation, cache hardware, file I/O, or native firmware timing.
"""
import importlib.util
import os
import pathlib
import re
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
DRAW = 0xC0528700
DRAW_ORIG, DRAW_PAUSE = 0xE92D4BF0, 0xE12FFF1E
ECHO_SLOT, ECHO_ORIG = 0xC0BAC2F8, 0xC03D99A0
DCACHE, ICACHE = 0xC000E91C, 0xC000EABC
FINISH, LOADER, STORE_BOOT = 0xC072F080, 0xC072DE64, 0xC072F700
OSDFILE, SLEEP, TICK = 0xC03E4270, 0xC03705D8, 0xC002B6E0
AR_TABLE, AR_LINEFN, AR_POP = 0xC2F20FC0, 0xC03DA7A8, 0xC0420D90
FILE_CLOSE = 0xC0366020
MEM_SET = re.compile(r"^mem set (0x[0-9a-f]+) (0x[0-9a-f]+)$", re.I)
EMULATOR_REASON = 'Unicorn is not installed; generated ARM execution is unverified'
HAS_UNICORN = False
if importlib.util.find_spec('unicorn') is not None:
    # On macOS, a sandbox may permit import but kill Unicorn's first JIT memory
    # mapping with SIGILL. Probe in a child so that ordinary build checks run.
    probe = subprocess.run([sys.executable, '-B', '-c',
        'import unicorn; u=unicorn.Uc(unicorn.UC_ARCH_ARM,unicorn.UC_MODE_ARM); '
        'u.mem_map(4096,4096); u.mem_write(4096,bytes.fromhex("0000a0e1")); '
        'u.emu_start(4096,4100,count=1)'], capture_output=True, timeout=10)
    HAS_UNICORN = probe.returncode == 0
    EMULATOR_REASON = (f'Unicorn host probe exited {probe.returncode}; sandbox/JIT may '
                       'prevent execution; generated ARM is unverified in this run')


def commands(text):
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def writes(lines):
    for index, line in enumerate(lines):
        match = MEM_SET.match(line)
        if match:
            yield index, int(match[1], 16), int(match[2], 16)


def echo_targets(lines):
    target = ECHO_ORIG
    for index, line in enumerate(lines):
        match = MEM_SET.match(line)
        if match and int(match[1], 16) == ECHO_SLOT:
            target = int(match[2], 16)
        elif line == 'echo':
            yield index, target


def sections(blob):
    magic, count, entry, length = struct.unpack_from('<4sIII', blob)
    if magic != b'VBIN':
        raise AssertionError('builder output is not VBIN')
    cursor = 16 + 8 * count
    result = []
    for index in range(count):
        address, size = struct.unpack_from('<II', blob, 16 + index * 8)
        result.append((address, blob[cursor:cursor + size], cursor))
        cursor += (size + 3) & ~3
    if cursor != 16 + 8 * count + length:
        raise AssertionError('VBIN body length does not match section table')
    return result, entry


class ArmHarness:
    """Runs only generated ARM, intercepting every expected firmware call."""
    STAGING, STACK, STOP, CTX = 0x42000000, 0x10000000, 0x10100000, 0xC2000000

    def __init__(self):
        from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
        from unicorn import arm_const as reg
        self.reg = reg
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.uc.mem_map(0xC0000000, 0x04000000)
        self.uc.mem_map(self.STAGING, 0x20000)
        self.uc.mem_map(self.STACK, 0x10000)
        self.uc.mem_map(self.STOP, 0x1000)
        self.events = []
        self.callbacks = {}
        self.write_callback = None
        self.reached_stop = False
        self.initial_sp = self.STACK + 0xFFF0
        self.initial_saved = {getattr(reg, f'UC_ARM_REG_R{n}'): 0x55550000 + n
                              for n in range(4, 12)}
        for number, value in self.initial_saved.items():
            self.uc.reg_write(number, value)
        self.uc.reg_write(reg.UC_ARM_REG_SP, self.initial_sp)
        self.uc.reg_write(reg.UC_ARM_REG_LR, self.STOP)
        self.uc.hook_add(UC_HOOK_CODE, self._code)
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self._write)

    def u32(self, address):
        return struct.unpack('<I', self.uc.mem_read(address, 4))[0]

    def put32(self, address, value):
        self.uc.mem_write(address, struct.pack('<I', value))

    def cstring(self, address):
        raw = bytearray()
        for offset in range(512):
            byte = self.uc.mem_read(address + offset, 1)[0]
            if not byte:
                return raw.decode('ascii')
            raw.append(byte)
        raise AssertionError('unterminated native-handler argument')

    def _code(self, uc, address, size, _data):
        if address == self.STOP:
            self.reached_stop = True
            uc.emu_stop()
            return
        callback = self.callbacks.get(address)
        if callback is None:
            if not (self.STAGING <= address < self.STAGING + 0x20000 or
                    LOADER <= address < LOADER + 0x200):
                raise AssertionError(f'unmocked firmware execution {address:#x}')
            return
        if uc.reg_read(self.reg.UC_ARM_REG_SP) % 8:
            raise AssertionError(f'unaligned stack at firmware call {address:#x}')
        args = [uc.reg_read(getattr(self.reg, f'UC_ARM_REG_R{n}')) for n in range(4)]
        lr = uc.reg_read(self.reg.UC_ARM_REG_LR)
        result = callback(args)
        # A firmware callee is entitled to destroy caller-saved registers.
        for n in (0, 1, 2, 3, 12):
            uc.reg_write(getattr(self.reg, f'UC_ARM_REG_R{n}'), 0xBAD00000 + n)
        uc.reg_write(self.reg.UC_ARM_REG_R0, 0 if result is None else result)
        uc.reg_write(self.reg.UC_ARM_REG_PC, lr)

    def _write(self, uc, access, address, size, value, _data):
        if self.write_callback:
            self.write_callback(address, size, value)

    def execute(self, address, r0, argc=0):
        self.uc.reg_write(self.reg.UC_ARM_REG_R0, r0)
        self.uc.reg_write(self.reg.UC_ARM_REG_R1, argc)
        self.uc.reg_write(self.reg.UC_ARM_REG_R2, 0)
        self.uc.emu_start(address, self.STOP + 4, count=100000)
        if not self.reached_stop:
            raise AssertionError('generated code did not return within instruction budget: '
                                 f'pc={self.uc.reg_read(self.reg.UC_ARM_REG_PC):#x}, '
                                 f'lr={self.uc.reg_read(self.reg.UC_ARM_REG_LR):#x}, '
                                 f'events={self.events}')
        if self.uc.reg_read(self.reg.UC_ARM_REG_SP) != self.initial_sp:
            raise AssertionError('generated code did not restore SP')
        for number, value in self.initial_saved.items():
            if self.uc.reg_read(number) != value:
                raise AssertionError(f'generated code damaged callee-saved register {number}')


class SplashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import boot_splash
        cls.width, cls.height = boot_splash.WIDTH, boot_splash.HEIGHT
        cls.frame_bytes = boot_splash.FRAME_BYTES
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpsup-splash-offline-')
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = pathlib.Path(cls.tmp.name)
        cls.cards = {}
        cls.legacy = {}
        modes = {'ordinary': ['--no-shell'], 'debug': [],
                 'fast': ['--no-shell', '--store-boot']}
        for mode, flags in modes.items():
            cls.cards[mode] = [cls.build(f'{mode}-{rev}', flags, rev, True)
                               for rev in range(2)]
            cls.legacy[mode] = cls.build(f'legacy-{mode}', flags, 0, False)

    @classmethod
    def build(cls, name, flags, revision, splash):
        out = cls.root / name
        out.mkdir()
        payload = out / 'payload.bin'
        payload.write_bytes(struct.pack('<I', 0x12345678 + revision) * (revision + 1))
        env = {key: value for key, value in os.environ.items()
               if not key.startswith('FPSUP_')}
        result = subprocess.run(
            [sys.executable, '-B', str(HERE / 'build_autorun.py'), '--loader',
             '--out', str(out / 'AutoRun.txt'), '--also-bin', f'0xC0731000:{payload}',
             *flags, *(['--four-box-bar'] if splash else [])],
            env=env, capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return {'path': out, 'auto': (out / 'AutoRun.txt').read_bytes(),
                'bin': (out / 'fpSup.BIN').read_bytes(),
                'ui': [(out / 'FPSUPUI' / f'{n}.BIN').read_bytes()
                       for n in range(5)] if splash else None,
                'lines': commands((out / 'AutoRun.txt').read_text())}

    def test_asset_four_independent_fills_and_brand_colors(self):
        import boot_splash
        blob = boot_splash.asset()
        self.assertLessEqual(self.width, 1024)
        self.assertLessEqual(self.height, 64)
        self.assertEqual(self.frame_bytes, self.width * self.height * 2)
        self.assertEqual(len(blob), self.frame_bytes * 5)
        pixels = self.width * self.height
        frames = [struct.unpack(f'<{pixels}H', blob[n * self.frame_bytes:(n + 1) * self.frame_bytes])
                  for n in range(5)]
        self.assertTrue(all(pixel == 0 for frame in frames for pixel in frame[:self.width]),
                        'background must be transparent, with no black strip')
        for frame in frames:
            visible = [(i % self.width, i // self.width)
                       for i, pixel in enumerate(frame) if pixel >> 12]
            xs, ys = zip(*visible)
            self.assertEqual((min(xs), min(ys), max(xs), max(ys)),
                             (16, 10, 161, 37),
                             'artwork must be left aligned at its existing height')
        self.assertTrue(any(0 < pixel >> 12 < 15 for pixel in frames[0]),
                        'logo must retain its antialiased alpha edge')
        self.assertFalse(any(pixel >> 12 and pixel & 0xFFF == 0
                             for frame in frames for pixel in frame),
                         'artwork must not contain an opaque black background')
        colors = set(frames[0])
        self.assertIn(0xFFFF, colors, 'fp white is missing')
        self.assertIn(0xFD35, colors, 'reference Sup pink is missing')
        prior_right = -1
        dimensions = []
        for before, after in zip(frames, frames[1:]):
            changed = [index for index, pair in enumerate(zip(before, after))
                       if pair[0] != pair[1]]
            self.assertTrue(changed, 'each of the four completion steps must fill a box')
            xs, ys = [n % self.width for n in changed], [n // self.width for n in changed]
            self.assertTrue(all(after[y * self.width + x] == 0xFFFF
                                for y in range(min(ys), max(ys) + 1)
                                for x in range(min(xs), max(xs) + 1)),
                            'a completed square must be solid white, including its old border')
            self.assertGreater(min(xs), prior_right, 'progress must move left to right')
            prior_right = max(xs)
            dimensions.append((max(xs) - min(xs), min(ys), max(ys)))
        self.assertEqual(len(set(dimensions)), 1, 'all four boxes must have equal geometry')
        self.assertEqual(dimensions[0], (11, 18, 29),
                         'all 12x12 pixels must fill, covering the gray outline')
        for pair in self.cards.values():
            self.assertEqual(pair[0]['ui'], boot_splash.frames())

    def test_first_frame_replaces_full_top_row_and_keeps_progress_files_small(self):
        import boot_splash
        narrow = boot_splash.asset()[:self.frame_bytes]
        for pair in self.cards.values():
            frames = pair[0]['ui']
            self.assertEqual(len(frames[0]), 1024 * 56 * 2)
            for y in range(56):
                row = frames[0][y * 2048:(y + 1) * 2048]
                self.assertEqual(row[:self.width * 2],
                                 narrow[y * self.width * 2:(y + 1) * self.width * 2])
                self.assertEqual(row[self.width * 2:], bytes((1024 - self.width) * 2),
                                 'the time/STBY/file-name area must be erased to transparent')
            for frame in frames[1:]:
                self.assertEqual(len(frame), self.frame_bytes,
                                 'later updates must retain the small read size')

    def test_payload_only_updates_keep_autorun_and_art_identical(self):
        for mode, pair in self.cards.items():
            with self.subTest(mode=mode):
                self.assertEqual(pair[0]['auto'], pair[1]['auto'])
                self.assertEqual(pair[0]['ui'], pair[1]['ui'])
                self.assertNotEqual(pair[0]['bin'], pair[1]['bin'])

    def test_four_states_each_seed_all_three_buffers(self):
        for mode, pair in self.cards.items():
            with self.subTest(mode=mode):
                frames = []
                for line in pair[0]['lines']:
                    if line.startswith('display osdfile '):
                        args = line.split()[2:]
                        self.assertEqual(len(args), 6)
                        match = re.fullmatch(r'\\FPSUPUI\\([0-4])\.BIN', args[0], re.I)
                        self.assertIsNotNone(match)
                        width = 1024 if int(match[1]) == 0 else self.width
                        self.assertEqual([int(value, 0) for value in args[1:5]],
                                         [0, 0, width, self.height])
                        self.assertEqual((pair[0]['path'] / 'FPSUPUI' /
                                          f'{match[1]}.BIN').stat().st_size,
                                         width * self.height * 2)
                        offset = int(args[5], 0)
                        self.assertEqual(offset, 0, 'each update must read only its one-frame file')
                        frames.append(int(match[1]))
                self.assertEqual(frames, [0] * 3 + [1] * 3 + [2] * 3 + [3] * 3)
                self.assertFalse(any(line.startswith('display text ') for line in pair[0]['lines']))
                self.assertLess(len([line for line in pair[0]['lines'] if line.startswith('display ')]),
                                len([line for line in self.legacy[mode]['lines']
                                     if line.startswith('display ')]))

    def test_pause_precedes_published_first_frame_and_tail_restores_without_bin(self):
        for mode, pair in self.cards.items():
            with self.subTest(mode=mode):
                lines = pair[0]['lines']
                pauses = [index for index, address, value in writes(lines)
                          if (address, value) == (DRAW, DRAW_PAUSE)]
                restores = [index for index, address, value in writes(lines)
                            if (address, value) == (DRAW, DRAW_ORIG)]
                first_frame = next(i for i, line in enumerate(lines)
                                   if line.startswith('display osdfile '))
                self.assertEqual(len(pauses), 1)
                self.assertTrue(restores, 'missing BIN must still reach an AutoRun restoration')
                self.assertLess(pauses[0], first_frame)
                other_display = [line for line in lines
                                 if line.startswith('display ')
                                 and not line.startswith('display osdfile ')]
                self.assertEqual(other_display, [],
                                 'whole-layer clear/present would erase the retained lower UI')
                self.assertLessEqual(self.width, 176)
                self.assertLessEqual(self.height, 56,
                                     'splash writes must stay above the lower native UI')
                before = [target for index, target in echo_targets(lines)
                          if pauses[0] < index < first_frame]
                self.assertEqual(before, [DCACHE, ICACHE])
                after = [target for index, target in echo_targets(lines)
                         if index > restores[-1]]
                self.assertEqual(after, [DCACHE, ICACHE])
                slot_writes = [value for _, address, value in writes(lines) if address == ECHO_SLOT]
                self.assertEqual(slot_writes[-1], ECHO_ORIG)
                self.assertGreater(restores[-1], first_frame)

    def test_opt_in_loader_fits_fast_store_and_legacy_mode_stays_available(self):
        for mode, pair in self.cards.items():
            with self.subTest(mode=mode):
                def loader_words(card):
                    return [(address, value) for _, address, value in writes(card['lines'])
                            if LOADER <= address < LOADER + 0x200]
                self.assertTrue(loader_words(pair[0]))
                self.assertEqual(loader_words(pair[0]), loader_words(pair[1]))
                self.assertEqual(loader_words(pair[0]), loader_words(self.legacy[mode]))
                self.assertLessEqual(len(loader_words(pair[0])) * 4, 468)
                self.assertFalse((self.legacy[mode]['path'] / 'FPSUPUI').exists())
                self.assertFalse(any(address == DRAW for _, address, _ in writes(self.legacy[mode]['lines'])))
                # Splash is transient stage2 code, with no extra resident
                # sections or changes to Fast's original abort handler.
                def resident(card):
                    return [(address, body) for address, body, _ in sections(card['bin'])[0]
                            if address != 0]
                self.assertEqual(resident(pair[0]), resident(self.legacy[mode]))

    @unittest.skipUnless(HAS_UNICORN, EMULATOR_REASON)
    def test_loader_failures_return_to_unconditional_ui_restoration(self):
        for failure in ('allocation', 'missing-bin', 'invalid-bin'):
            with self.subTest(failure=failure):
                card = self.cards['ordinary'][0]
                harness = ArmHarness()
                for _, address, value in writes(card['lines']):
                    if LOADER <= address < LOADER + 0x200:
                        harness.put32(address, value)
                harness.put32(ECHO_SLOT, LOADER)
                harness.put32(DRAW, DRAW_PAUSE)

                def called(name, result=0):
                    def callback(args):
                        harness.events.append(name)
                        return result
                    return callback

                harness.callbacks.update({
                    0xC001D740: called('allocate'),
                    0xC001D7F0: called('address', 0 if failure == 'allocation' else harness.STAGING),
                    0xC001D7A0: called('free'),
                    0xC0444658: called('media-manager', 0xC2030000),
                    0xC0444698: called('volume', 1),
                    0xC0365E90: called('file-construct'),
                    0xC0365FB0: called('file-open', 1 if failure == 'invalid-bin' else 0),
                    0xC0366060: called('file-read'),
                    0xC0366020: called('file-close'),
                    0xC0365ED0: called('file-destruct'),
                })
                harness.execute(LOADER, harness.CTX)
                self.assertEqual(harness.u32(ECHO_SLOT), LOADER)
                self.assertEqual(harness.u32(DRAW), DRAW_PAUSE)
                self.assertEqual(harness.events.count('free'), failure != 'allocation')
                self.assertEqual(harness.events.count('file-close'), failure == 'invalid-bin')
                self.assertEqual(harness.events.count('file-destruct'), failure != 'allocation')
                # Replay only the unconditional tail, with echo target lookup.
                # No completion helper exists on these paths.
                tail_at = next(index for index, address, value in writes(card['lines'])
                               if (address, value) == (DRAW, DRAW_ORIG))
                cache_calls = []
                for line in card['lines'][tail_at:]:
                    match = MEM_SET.match(line)
                    if match:
                        harness.put32(int(match[1], 16), int(match[2], 16))
                    elif line == 'echo':
                        cache_calls.append(harness.u32(ECHO_SLOT))
                self.assertEqual(cache_calls, [DCACHE, ICACHE])
                self.assertEqual(harness.u32(DRAW), DRAW_ORIG)
                self.assertEqual(harness.u32(ECHO_SLOT), ECHO_ORIG)

    @unittest.skipUnless(HAS_UNICORN, EMULATOR_REASON)
    def test_stage2_finishes_after_both_passes_and_returns_with_ui_restored(self):
        for mode in self.cards:
            for ui_ok in (True, False):
                with self.subTest(mode=mode, ui_file_ok=ui_ok):
                    self.check_stage2(mode, ui_ok, DRAW_PAUSE)

    @unittest.skipUnless(HAS_UNICORN, EMULATOR_REASON)
    def test_native_finish_does_not_overwrite_a_foreign_draw_hook(self):
        # This is specifically the native helper's ownership guard. AutoRun's
        # unconditional failure tail assumes the ordinary firmware draw site.
        self.check_stage2('ordinary', False, 0xEA012345)

    def check_stage2(self, mode, ui_ok, initial_draw):
        blob = self.cards[mode][0]['bin']
        secs, entry = sections(blob)
        harness = ArmHarness()
        harness.uc.mem_write(harness.STAGING, blob)
        harness.put32(DRAW, initial_draw)
        harness.put32(ECHO_SLOT, ECHO_ORIG)
        # stage2 runs inside the AutoRun's `echo`, so the interpreter is
        # registered; stage2 arms the abort only when it finds that entry.
        harness.put32(AR_TABLE + 0x21C, 1)
        harness.put32(AR_TABLE + 36 + 4, AR_LINEFN)
        # Every loader card journals the words it changes and registers the
        # power-off restore before placing anything (LOADER_V2.md): a block
        # from the allocator, its routine published, then both lists.
        journal_block = harness.STAGING + 0x18000
        assert len(blob) <= 0x18000
        harness.callbacks.update({
            0xC001CF78: lambda args: harness.events.append('heap') or 0x1234,
            0xC001D038: lambda args: harness.events.append('get') or journal_block,
            0xC0023A98: lambda args: 0xC2F00000,
            0xC0024118: lambda args: harness.events.append(f'poff-{args[2]}') or 1,
        })
        expected = ['heap', 'get', 'dcache', 'icache', 'poff-0', 'poff-1']
        expected += ['dcache', 'icache']
        if entry:
            entry_address = entry if entry >= 0x40000000 else harness.STAGING + entry
            def payload(args):
                self.assertEqual(args[0], entry_address)
                self.assertEqual(harness.u32(ECHO_SLOT), ECHO_ORIG)
                harness.events.append('entry')
            harness.callbacks[entry_address] = payload
            expected.append('entry')
        expected += ['dcache', 'icache']
        if mode == 'fast':
            expected.append('armed')
        expected.append('tick')

        def draw(args):
            self.assertEqual(harness.events[:len(expected)], expected)
            self.assertEqual(args[1], 6)
            self.assertTrue(harness.STACK <= args[0] < harness.STACK + 0x10000,
                            'native handler requires its local printf context')
            no_output = harness.u32(args[0])
            self.assertTrue(harness.STAGING <= no_output < harness.STAGING + len(blob))
            self.assertEqual(bytes(harness.uc.mem_read(no_output, 8)),
                             bytes.fromhex('0000a0e31eff2fe1'))
            argv = [harness.cstring(harness.u32(args[2] + 4 * n)) for n in range(6)]
            self.assertEqual(argv, [r'\FPSUPUI\4.BIN', '0', '0',
                                    str(self.width), str(self.height), '0'])
            self.assertEqual(harness.u32(0xC0731000), 0x12345678,
                             'payload placement must precede completion')
            self.assertEqual(harness.u32(0xC072F6F8), 123456,
                             'load timestamp must precede the display hold')
            harness.events.append('draw')
            return 1 if ui_ok else 0

        def hold(args):
            self.assertEqual(args[0], 2000)
            self.assertEqual(harness.events, expected + ['draw'] * 3)
            self.assertEqual(harness.u32(DRAW), initial_draw)
            harness.events.append('hold')

        def tick(args):
            harness.events.append('tick')
            return 123456

        def on_write(address, size, value):
            if address == DRAW:
                self.assertEqual(initial_draw, DRAW_PAUSE)
                self.assertEqual((size, value), (4, DRAW_ORIG))
                self.assertEqual(harness.events, expected + ['draw'] * 3 + ['hold'])
                harness.events.append('restore')
            elif address == ECHO_SLOT:
                self.assertEqual(mode, 'fast')
                self.assertEqual((size, value), (4, FINISH))
                abort = next(body for dest, body, _ in secs if dest == FINISH)
                self.assertEqual(bytes(harness.uc.mem_read(FINISH, len(abort))), abort)
                self.assertEqual(harness.events, expected[:-2])
                harness.events.append('armed')

        def unexpected_teardown(args):
            self.fail('stage2 completion must return; only the later Fast echo may abort')

        def draw_manager(args):
            self.assertEqual(harness.u32(DRAW), DRAW_ORIG)
            self.assertEqual(harness.events[-3:], ['restore', 'dcache', 'icache'])
            harness.events.append('draw-manager')
            return 0xC3782FC8

        def clear_native(args):
            self.assertEqual(args[0], 0xC3782FC8)
            self.assertIn(args[1], (0, 1))
            self.assertEqual(args[2], 1)
            harness.events.append(f'clear-{args[1]}')

        def request_native_redraw(args):
            self.assertEqual(args[0], 0xC3782FC8)
            self.assertEqual(harness.events[-2:], ['clear-0', 'clear-1'])
            request_address = args[1]
            self.assertTrue(harness.STAGING <= request_address <=
                            harness.STAGING + len(blob) - 12,
                            'native request must remain valid inside staging until consumed')
            request = bytes(harness.uc.mem_read(request_address, 12))
            flags, priority, observer = struct.unpack('<III', request)
            # Clear/pending alone leaves clean widgets in incremental mode and
            # can therefore present an empty UI. Native C0529610 copies byte 1
            # into event bit 0x10; C0529538 then copies that bit into draw-context
            # byte 1. UicDrawHandler C06D1948 requires it to select mode 2 when
            # its own dirty flag is clear. Assert this semantic dependency, not
            # merely the address of the scheduling function.
            self.assertEqual(request[0], 1, 'all native groups must be scheduled')
            self.assertEqual(request[1], 1, 'clean widgets require forced full redraw')
            self.assertEqual(request[2:4], b'\0\0')
            self.assertEqual(flags, 0x101)
            self.assertEqual(priority, 0xFFFFFFFF, 'restoration must not change task priority')
            self.assertEqual(observer, 0, 'no callback may outlive the staging buffer')
            harness.events.append('redraw')

        def wake_without_invalidation(args):
            self.fail('clear + wake does not invalidate clean UI widgets; '
                      'restoration requires the native full-redraw request')

        harness.callbacks.update({OSDFILE: draw, SLEEP: hold, TICK: tick,
                                  FILE_CLOSE: unexpected_teardown, AR_POP: unexpected_teardown,
                                  0xC05278F8: draw_manager, 0xC0527DD8: clear_native,
                                  0xC0527E68: request_native_redraw,
                                  0xC0527E40: wake_without_invalidation})
        for address, name in ((DCACHE, 'dcache'), (ICACHE, 'icache')):
            harness.callbacks[address] = lambda args, name=name: harness.events.append(name)
        harness.write_callback = on_write
        harness.execute(harness.STAGING + secs[0][2], harness.STAGING)
        expected += ['draw'] * 3 + ['hold']
        if initial_draw == DRAW_PAUSE:
            expected += ['restore', 'dcache', 'icache']
            expected += ['draw-manager', 'clear-0', 'clear-1', 'redraw']
            self.assertEqual(harness.u32(DRAW), DRAW_ORIG)
        else:
            self.assertEqual(harness.u32(DRAW), initial_draw)
        self.assertEqual(harness.events, expected)
        self.assertEqual(harness.u32(ECHO_SLOT), FINISH if mode == 'fast' else ECHO_ORIG)


if __name__ == '__main__':
    unittest.main(verbosity=2)
