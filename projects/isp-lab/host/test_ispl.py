#!/usr/bin/env python3
"""Offline tests for ispl.py against a fake camera memory.  python3 -B -m unittest test_ispl"""
import json, pathlib, struct, tempfile, types, unittest

import ispl
R = ispl.R

AT = 0x45001000                      # where the host reaches the sink (uncached alias)


class FakeApi:
    def __init__(self, recording=0):
        self.mem, self.calls, self.recording = {}, [], recording
        self.windows = [(0, 0, 0)] * 8
        cap = bytearray(R.CAP_BYTES)
        struct.pack_into('<II', cap, 0, R.CAP_MAGIC, R.CAP_VERSION)
        self.put(AT, bytes(cap))

    def put(self, a, b):
        for i, x in enumerate(b):
            self.mem[a + i] = x

    def get(self, a, n):
        return bytes(self.mem.get(a + i, 0) for i in range(n))

    def sh(self, line):
        self.calls.append(('sh', line))
        return f'is_recording -> {self.recording}'

    def mem_window(self, slot, base, n, perm):
        self.calls.append(('win', slot, base, n, perm))
        self.windows[slot] = (base, n, perm)

    def mem_write(self, a, data, label=''):
        self.calls.append(('w', a, bytes(data)))
        self.put(a, data)

    def mem_read(self, a, n, label=''):
        w = self.windows[7]
        assert w[2] & 1 and w[0] <= a and a + n <= w[0] + w[1], 'MEM1 read without a window'
        self.calls.append(('r', a, n))
        return self.get(a, n)


def heap_factory(cap=1 << 40, piece=1 << 40):
    """cap: total the allocator will give; piece: the largest single block."""
    nxt = [0xC6000000]
    freed, given = [], [0]

    def heap(op, size=0, desc=None):
        if op:
            freed.append(desc)
            return None
        if size > piece or given[0] + size > cap:
            return 0, [0, 0, 0, size]
        a = nxt[0]; nxt[0] += size; given[0] += size
        return a, [a, size, 0, 0]
    return heap, freed


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.patches = [('block_addr', lambda: 0x45000000), ('build', lambda: {'state_at': 0, 'cap_off': AT - 0x45000000}),
                        ('ALLOC_KEEP', self.tmp / 'alloc.json'), ('flush', lambda: None)]
        self.saved = [(k, getattr(ispl, k)) for k, _ in self.patches]
        for k, v in self.patches:
            setattr(ispl, k, v)

    def tearDown(self):
        for k, v in self.saved:
            setattr(ispl, k, v)


class Image(Base):
    def test_cap_image_roundtrip(self):
        body = ispl.cap_image('capture', [(0x46000000, 16 << 20)], keep_first=4, every_us=500_000,
                              log=(0x47000000, 65536), start_ms=1500, rec_ms=3000)
        self.assertEqual(len(body), R.HOST_END - 8, 'the host image must stop before the camera-only ur_*')
        cap = R.parse_cap(struct.pack('<II', R.CAP_MAGIC, R.CAP_VERSION) + body + bytes(R.CAP_BYTES - R.HOST_END))
        self.assertEqual((cap['mode'], cap['nchunk'], cap['chunks'][0]), (1, 1, (0x46000000, 16 << 20)))
        self.assertEqual((cap['keep_first'], cap['every_us'], cap['log_addr'], cap['log_max']),
                         (4, 500_000, 0x47000000, 65536))
        self.assertEqual((cap['ctl'], cap['start_ms'], cap['rec_ms'], cap['n_rec']), (0, 1500, 3000, 0))

    def test_load_log(self):
        self.assertEqual(ispl.parse_load_log('0A C504A080 00010000 ISPL.BIN\n'), 0xC504A080)
        self.assertEqual(ispl.parse_load_log('0A C504A080 00000000 ISPC.BIN\n', 'ISPC.BIN'), 0xC504A080)
        with self.assertRaises(SystemExit):
            ispl.parse_load_log('0A C504A080 00010000 IMXL.BIN\n')


class Take(Base):
    def run_take(self, api, mb=32):
        heap, freed = heap_factory()
        slept = []

        def sleep(s):
            slept.append((s, len(api.calls)))
        a = types.SimpleNamespace(mb=mb, keep_first=4, every_ms=500, start_ms=1500, rec_ms=3000, focus=True, focus_ms=1500)
        ispl.cmd_take(a, api, heap, sleep)
        return slept, freed

    def test_order_and_silence(self):
        api = FakeApi()
        slept, _ = self.run_take(api)
        writes = [c for c in api.calls if c[0] == 'w']
        # the LV sampler off first, then body with mode sd, then the mode word, then ctl armed: the last write
        self.assertEqual((writes[0][1], writes[0][2]), (AT + R.OFF['lv_push'], struct.pack('<I', 0)))
        writes = writes[1:]
        self.assertEqual(struct.unpack_from('<I', writes[0][2])[0], R.MODES['sd'])
        self.assertEqual((writes[1][1], writes[1][2]), (AT + 8, struct.pack('<I', R.MODES['capture'])))
        self.assertEqual((writes[2][1], writes[2][2]), (AT + R.OFF['ctl'], struct.pack('<I', R.CTL['armed'])))
        # silent from the ctl write to the end of the sleep: only the window close in between
        (_, _), (secs, at_call) = slept                          # the AF wait, then the silence
        self.assertGreaterEqual(secs, 1.5 + 3 + 10)
        sh = [c[1] for c in api.calls if c[0] == 'sh']
        self.assertEqual(sh[1:3], ['key S1ON', 'key S1OFF'], 'no half-press AF before the arm')
        self.assertNotIn('key S2ON', sh)
        i = api.calls.index(writes[2])
        self.assertEqual([c[0] for c in api.calls[i + 1:at_call]], ['win'])
        self.assertEqual(api.windows[ispl.WIN_SLOT], (AT, R.CAP_BYTES, 0))
        cap = R.parse_cap(api.get(AT, R.CAP_BYTES))
        self.assertEqual(cap['nchunk'], 32 // 4)                 # 32 MiB of records in 4 MiB pieces, the log apart
        self.assertTrue(all(a < 0xC0000000 for a, _ in cap['chunks'][:8]), 'lent at the cached alias')
        self.assertTrue(0x40000000 <= cap['log_addr'] < 0xC0000000)
        self.assertEqual(cap['log_max'], ispl.LOG_BYTES // 16)

    def test_cache_flushed_around_every_write(self):
        api = FakeApi()
        orig = api.mem_write
        ispl.flush = lambda: api.calls.append(('flush',))
        self.run_take(api)
        seq = [c[0] for c in api.calls if c[0] in ('w', 'flush')]
        i = seq.index('w')
        self.assertEqual(seq[i - 1], 'flush', 'no flush before the first write')
        self.assertTrue(all(seq[k + 1] == 'flush' for k, x in enumerate(seq) if x == 'w'),
                        'a write not followed by a flush: the sup may never see it')

    def test_sink_at_the_uncached_alias(self):
        self.assertEqual(ispl.cap_addr(0xC4FB90C0, {'state_at': 0x10, 'cap_off': 0x20}), 0x44FB90F0)
        self.assertEqual(ispl.cap_addr(0x44FB90C0, {'state_at': 0x10, 'cap_off': 0x20}), 0x44FB90F0)

    def test_halves_pieces_when_refused(self):
        # 10-23 on camera: 16 MiB refused, 4 MiB given, 8 MiB in all
        heap, freed = heap_factory(cap=8 << 20, piece=1 << 20)
        held = []
        ispl.lend(ispl.LOG_BYTES, heap, held, 1)
        ispl.lend(64 << 20, heap, held, 33)
        self.assertEqual(held[0][2], ispl.LOG_BYTES)
        self.assertEqual(sum(n for *_, n in held), 8 << 20)
        self.assertTrue(all(n <= 1 << 20 for *_, n in held))

    def test_ctl_only_lends_nothing(self):
        api = FakeApi()
        saved = (ispl.SUP_FILE, ispl.BUILD_JSON)
        ispl.SUP_FILE = 'ISPC.BIN'
        try:
            def heap(*a):
                raise AssertionError('the control-only take must not touch the allocator')
            a = types.SimpleNamespace(mb=32, keep_first=4, every_ms=500, start_ms=3000, rec_ms=2000,
                                      focus=True, focus_ms=1500)
            ispl.cmd_take(a, api, heap, lambda s: None)
        finally:
            ispl.SUP_FILE, ispl.BUILD_JSON = saved
        cap = R.parse_cap(api.get(AT, R.CAP_BYTES))
        self.assertEqual((cap['mode'], cap['nchunk'], cap['ctl'], cap['start_ms'], cap['rec_ms']),
                         (R.MODES['sd'], 0, R.CTL['armed'], 3000, 2000))
        self.assertFalse(ispl.ALLOC_KEEP.exists())

    def test_discard_take_lends_nothing_and_arms_the_discard_sink(self):
        api = FakeApi()
        def heap(*a):
            raise AssertionError('a discard take must not touch the allocator')
        a = types.SimpleNamespace(mb=32, keep_first=4, every_ms=500, start_ms=3000, rec_ms=2000,
                                  focus=False, focus_ms=0, discard=True)
        ispl.cmd_take(a, api, heap, lambda s: None)
        cap = R.parse_cap(api.get(AT, R.CAP_BYTES))
        self.assertEqual((cap['mode'], cap['nchunk'], cap['ctl'], cap['log_max']),
                         (R.MODES['discard'], 0, R.CTL['armed'], 0))
        self.assertFalse(ispl.ALLOC_KEEP.exists())

    def test_discard_take_can_arm_the_lv_sampler_before_the_ctl_word(self):
        api = FakeApi()
        a = types.SimpleNamespace(start_ms=3000, rec_ms=2000, focus=False, discard=True, lv_every_ms=250, lv_max=20)
        ispl.cmd_take(a, api, None, lambda s: None)
        cap = R.parse_cap(api.get(AT, R.CAP_BYTES))
        self.assertEqual((cap['lv_push'], cap['lv_every_us'], cap['lv_max'], cap['ctl']), (1, 250000, 20, R.CTL['armed']))

    def test_discard_take_can_arm_the_lv_burst(self):
        api = FakeApi()
        a = types.SimpleNamespace(start_ms=3000, rec_ms=2000, focus=False, discard=True, lv_burst_ms=1500, lv_max=120)
        ispl.cmd_take(a, api, None, lambda s: None)
        cap = R.parse_cap(api.get(AT, R.CAP_BYTES))
        self.assertEqual((cap['lv_push'], cap['lv_every_us'], cap['lv_burst_ms'], cap['lv_max'], cap['ctl']),
                         (1, 0, 1500, 120, R.CTL['armed']))
        self.assertLess(R.OFF['lv_burst_ms'], R.HOST_END, 'lv_burst_ms must be inside the arm image')

    def test_discard_take_can_ask_for_cdng_after_the_stop(self):
        api = FakeApi()
        a = types.SimpleNamespace(start_ms=3000, rec_ms=2000, focus=False, discard=True, cd_after_ms=2000, cd_max=5)
        ispl.cmd_take(a, api, None, lambda s: None)
        cap = R.parse_cap(api.get(AT, R.CAP_BYTES))
        self.assertEqual((cap['cd_after_ms'], cap['cd_max'], cap['cd_state'], cap['lv_push']), (2000, 5, 0, 0))

    def test_reports_replace_the_shell_read(self):
        import push_rx, tempfile, pathlib
        api = FakeApi()
        out = pathlib.Path(tempfile.mkdtemp())
        a = types.SimpleNamespace(start_ms=3000, rec_ms=2000, focus=False, discard=True, report=True,
                                  heartbeat_ms=1000, listen=str(out))
        cap = bytearray(api.get(AT, R.CAP_BYTES))
        struct.pack_into('<I', cap, R.OFF['ctl'], R.CTL['done']); struct.pack_into('<I', cap, R.OFF['n_press'], 2)
        def fake_listen(path, *args, **kw):
            sink = push_rx.file_sink(path)
            for seq, ev in enumerate((1, 2, 3)):
                h = push_rx.parse_header(push_rx.make_header(5, seq, [len(cap)], t_us=1000 * seq, frame_no=ev, fmt=6))
                sink(h, bytes(cap))
            return {'reason': 'idle'}, None, {}
        saved_listen, saved_read = push_rx.listen, ispl.read_cap
        push_rx.listen = fake_listen
        reads = []
        ispl.read_cap = lambda api, at: reads.append(at) or R.parse_cap(api.get(at, R.CAP_BYTES))
        try:
            ispl.cmd_take(a, api, None, lambda s: None)
        finally:
            push_rx.listen, ispl.read_cap = saved_listen, saved_read
        armed = R.parse_cap(api.get(AT, R.CAP_BYTES))
        self.assertEqual((armed['rp_on'], armed['rp_every_us']), (1, 1_000_000))
        self.assertEqual(reads[1:], [], 'the summary read the sink over the shell although reports came')
        self.assertEqual([e for _, e, _ in ispl.reports(out)], ['armed', 'rec', 'stopped'])

    def test_ctl_only_does_not_free_an_old_sink_allocation(self):
        ispl.ALLOC_KEEP.write_text('old sink allocation: do not free after a reboot')
        saved = ispl.SUP_FILE
        ispl.SUP_FILE = 'ISPC.BIN'
        try:
            a = types.SimpleNamespace(start_ms=3000, rec_ms=2000, focus=False)
            def no_heap(*args):
                raise AssertionError('ISPC touched the old sink allocation')
            ispl.cmd_take(a, FakeApi(), no_heap, lambda s: None)
        finally:
            ispl.SUP_FILE = saved
        self.assertEqual(ispl.ALLOC_KEEP.read_text(), 'old sink allocation: do not free after a reboot')

    def test_refuses_while_recording(self):
        api = FakeApi(recording=1)
        with self.assertRaises(SystemExit):
            self.run_take(api)
        self.assertFalse([c for c in api.calls if c[0] == 'w'])

    def test_refuses_twice(self):
        api = FakeApi()
        self.run_take(api)
        with self.assertRaises(SystemExit):
            self.run_take(api)

    def test_gives_back_when_the_write_fails(self):
        api = FakeApi()
        api.mem_write = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('usb'))
        heap, freed = heap_factory()
        a = types.SimpleNamespace(mb=32, keep_first=4, every_ms=500, start_ms=1500, rec_ms=3000, focus=True, focus_ms=1500)
        with self.assertRaises(RuntimeError):
            ispl.cmd_take(a, api, heap, lambda s: None)
        self.assertEqual(len(freed), 1 + 32 // 4)              # the log + every 4 MiB record piece
        self.assertFalse(ispl.ALLOC_KEEP.exists())


def record(seq, cl, data):
    data = bytes(data)
    head = R.REC.pack(R.REC_MAGIC, seq, cl, len(data), 1, 1000 * seq, 10, 1)
    return head + data + b'\0' * (-len(data) % 4)


class Pull(Base):
    def test_records_log_and_dngs(self):
        api = FakeApi()
        cl = 4096
        f0 = b'II*\0' + b'a' * (cl - 4) + b'b' * cl         # a two-cluster file
        f1 = b'II*\0' + b'c' * (cl - 4)
        stream = record(1, 10, f0) + record(3, 30, f1)
        chunk, log_at = 0x46000000, 0x47000000
        api.put(chunk, stream)
        log = b''.join(R.LOG.pack(s, 1000 * s, 2, 8 << 20) for s in (1, 2, 3))
        api.put(log_at, log)
        cap = bytearray(api.get(AT, R.CAP_BYTES))
        struct.pack_into('<II', cap, R.O_CHUNK, chunk, 1 << 20)
        struct.pack_into('<I', cap, 12, 1)
        for k, v in (('used', len(stream)), ('n_rec', 2), ('n_skip', 1), ('log_addr', log_at),
                     ('log_max', 100), ('log_n', 3)):
            struct.pack_into('<I', cap, R.OFF[k], v)
        api.put(AT, cap)
        ispl.cmd_pull(types.SimpleNamespace(out=str(self.tmp / 'out')), api)
        frames = sorted((self.tmp / 'out' / 'frames').iterdir())
        self.assertEqual([f.read_bytes() for f in frames], [f0, f1])
        meta = json.loads((self.tmp / 'out' / 'cap.json').read_text())
        self.assertEqual(meta['log_check'], {'blocks': 3, 'frames': 6, 'seq_gaps': [], 'accounted': True,
                                             'log_full': False})
        self.assertEqual(api.windows[ispl.WIN_SLOT][2], 0, 'a read window left open')

    def test_seq_gap_is_reported(self):
        log = [{'seq': s, 't_us': 0, 'ncookie': 1, 'bytes': 1} for s in (1, 2, 4)]
        cap = {'n_rec': 3, 'n_skip': 0, 'n_full': 0, 'n_discard': 0, 'n_sd': 0, 'log_n': 3, 'log_max': 9}
        self.assertEqual(ispl.check_log(log, cap)['seq_gaps'], [2])


class OwnCallfnBlock(unittest.TestCase):
    """The shared callfn now owns its block; ISP Lab must not redirect it."""
    def test_flush_reuses_the_shared_callfn_block(self):
        import sys
        shared = 0xC072E980
        ran = []
        fake_callfn = types.SimpleNamespace(CODE=shared, CODE_END=shared + 160, _own_code=False)
        fake_callfn.call = lambda fn, **k: (ran.append((fn, fake_callfn.CODE)), (True, 0))[1]
        def no_extra_claim(*args):
            raise AssertionError('ISP Lab claimed another callfn block')
        fake_cave = types.SimpleNamespace(claim=no_extra_claim)
        saved = {m: sys.modules.get(m) for m in ('callfn', 'cave')}
        sys.modules.update(callfn=fake_callfn, cave=fake_cave)
        try:
            ispl.flush(); ispl.flush()
        finally:
            for m, v in saved.items():
                if v is None:
                    sys.modules.pop(m, None)
                else:
                    sys.modules[m] = v
        self.assertEqual(ran, [(ispl.F_DCACHE, shared)] * 2)
        self.assertEqual(fake_callfn.CODE_END - fake_callfn.CODE, 160)


if __name__ == '__main__':
    unittest.main()
