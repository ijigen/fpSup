#!/usr/bin/env python3
"""ISPL under unicorn (fork of projects/imx410-lab/sup/test_card.py, sha256
2a7b7dfa...): IMXL's tests unchanged in substance, plus the keep policy, the
block log and the control task (KeepTests, LogTests, ControlTests), and (layout 10) the non-blocking
start with the LV burst across it (BurstTests).

IMXL under unicorn: the real loader v4 loads build.py's IMXL.BIN into the real
firmware image, then takes run through the firmware's own code as in
rec-core/writer/test_card.py (C063F220 set-up, C063F048 extents, the SD
driver's arena routines, C063F310 stop), with only C01EB790, C03A55D0,
C0644B68 and the TK-OS calls in Python.  The writer task is the real
wr_service, run whenever stock blocks on our flag and between frames.

What is new against ULWR is the sink:
  - sd       : unchanged ULWR behaviour (every byte on the disk where it belongs)
  - capture  : nothing reaches the device; the lent chunks hold records that
               rebuild exactly the disk ULWR would have written; every cookie
               once, in order, status 0
  - full     : a sink that runs out stores only whole records, writes nothing
               past its chunks, and still completes every frame
  - discard  : nothing stored, nothing written, every frame completed
  - frames given at the cached alias are read through the uncached one
  - lent memory outside the uncached alias is refused

    python3 -B -m unittest test_card
"""
import ctypes, pathlib, random, struct, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SHELL = ROOT / 'fpSup' / 'fp_usb_shell'
sys.path[:0] = [str(HERE), str(SHELL.parent / 'loader-v4'), str(SHELL / 'v3'), str(SHELL)]
import test_v4 as V4                                         # noqa: E402
import test_v3 as V3                                         # noqa: E402
import build as IB                                           # noqa: E402
import ispl_records as R                                     # noqa: E402
from unicorn import UC_PROT_ALL                              # noqa: E402
from unicorn.arm_const import *                              # noqa: E402,F403

VOL = 0xC37D50D4                       # SD: 0xC37D066C + 1 * 0x4A68
DEV_ID = 1
SS, SPC, HEAP_LBA = 512, 256, 0x8000
CLUSTER = SS * SPC
PAD = 0x4FF00000                       # stock's zero buffer (uncached)
DATA = 0x50000000                      # frame bytes (uncached alias)
DATA_SIZE = 0x4000000
CACHED = 0x80000000                    # DATA + this: the cached alias, holding STALE bytes
CAP = 0x48000000                       # memory lent to the sink (uncached alias)
CAP_SIZE = 0x2000000
GUARD = 0xA5
TBL, BOUNCE = 0x43818EC8, 0x4381AECC
DRV = 0xC3816E80
MAXDESC = 0xC2F2E750
STUBS = {'VOL_LOOKUP': 0xC0644B68, 'DEV_WRITE': 0xC01EB790, 'STOCK_CB': 0xC03A55D0,
         'FLG_CREATE': 0xC00169EC, 'FLG_SET': 0xC0016B9C, 'FLG_WAIT': 0xC0016C08,
         'REC_STATE': 0xC03A52D0, 'LOG_A': 0xC0019DC0, 'LOG_B': 0xC001A048,
         'SHELL_EXEC': 0xC03D9C20, 'PUSH': 0x438F0000,     # PUSH: the engine stand-in (another sup's)
         'START_XFER': 0xC01E6B80, 'END_XFER': 0xC01E6D48}
THUMB_STUBS = {'VOL_LOOKUP', 'DEV_WRITE', 'START_XFER', 'END_XFER'}
PX_DMA_TBL, PX_CPU_TBL, PX_DEAF = 0xC31E3238, 0xC31E3264, 0xC31E38FC
PX_DEPCMD = 0x2100C87C                 # DWC3 DEPCMD, phys 7
SD = dict(acq=0xC065F021, add=0xC065F061, ckpt=0xC065EFE1, rb=0xC065F001, rel=0xC065F269)
SLOT = dict(cb=0x4834, acq=0x4838, add=0x483C, ckpt=0x4840, rb=0x4844, rel=0x4848)
DONE = V3.DONE
REGS = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5,
        UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
        UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_CPSR]
_BUILDS = {}


class Cam(V4.Camera):
    """v4's camera (heap at both aliases) plus the frame/pad/ADMA/lent memory and
    the stubs above.  DATA's cached alias is a separate buffer full of 0xEE: a
    read through it instead of the uncached alias sees stale bytes."""

    def __init__(self, files, dirs, seed=0, fail_write=None):
        super().__init__(files, dirs)
        mu = self.mu
        mu.mem_map(0x43800000, 0x100000)
        mu.mem_map(PAD, 0x100000)
        mu.mem_map(DATA, DATA_SIZE)
        self._stale = ctypes.create_string_buffer(b'\xEE' * DATA_SIZE, DATA_SIZE)
        mu.mem_map_ptr(DATA + CACHED, DATA_SIZE, UC_PROT_ALL, self._stale)
        mu.mem_map(CAP, CAP_SIZE)
        mu.mem_map(0x30180000, 0x10000)                       # display DMA channel registers
        mu.mem_map(0x30100000, 0x1000)                        # receiver registers (v8: frame counter 0x30100588)
        mu.mem_map(0x2100C000, 0x1000)                        # DWC3 device registers
        mu.mem_write(CAP, bytes([GUARD]) * CAP_SIZE)
        for k, a in STUBS.items():
            self.by_addr[a] = k
            mu.mem_write(a, b'\x70\x47' if k in THUMB_STUBS else struct.pack('<I', 0xE12FFF1E))
        self.rnd = random.Random(seed)
        self.fail_write = fail_write
        self.disk, self.writes, self.cookies, self.shell = {}, 0, [], []
        self.switch = self.on_cookie = self.on_shell = None
        self.pushes, self.push_ret = [], 0
        self.xfers, self.ends, self.start_rc, self.complete = [], [], 0, True
        self.last_chain = None

    def _hook(self, mu, addr, size, _):
        name = self.by_addr.get(addr)
        if name not in STUBS:
            return super()._hook(mu, addr, size, _)
        r0, r1, r2, r3 = (self.r(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3))
        self.calls.append(name)
        if name == 'VOL_LOOKUP':
            return self._ret(VOL if r0 == DEV_ID else 0)
        if name == 'FLG_CREATE':
            return self._ret(5)
        if name == 'FLG_SET':
            return self._ret(0)
        if name == 'FLG_WAIT':
            tmo = struct.unpack('<i', struct.pack('<I', self.w(self.r(UC_ARM_REG_SP))))[0]
            if tmo == -1:
                raise AssertionError('the writer task body ran inside the emulation')
            self.switch = [self.r(r) for r in REGS]          # stock blocks: run the writer
            mu.emu_stop()
            return
        if name == 'STOCK_CB':
            self.cookies.append((r0, r1))
            if self.on_cookie: self.on_cookie(r0, r1)
            return self._ret(0)
        if name == 'SHELL_EXEC':
            assert r0 == 0xC3756904, 'not the console context'
            line = self.cstr(r1)
            self.shell.append((line, self.now))
            if self.on_shell: self.on_shell(line)
            return self._ret(0)
        if name == 'START_XFER':
            return self._ret(self.start_xfer(r0))
        if name == 'END_XFER':
            self.ends.append(r0)
            return self._ret(0)
        if name == 'PUSH':
            f = struct.unpack('<19I', self.mu.mem_read(r0, 76))
            self.pushes.append(dict(zip(('mode', 'source', 'frame_no', 'w', 'h', 'fmt', 'stride', 'flags',
                                         'aux0', 'aux1', 'nseg'), f[:11]), segs=list(zip(f[11::2], f[12::2]))))
            return self._ret(self.push_ret)
        if name in ('REC_STATE', 'LOG_A', 'LOG_B'):
            return self._ret(0)
        if name == 'DEV_WRITE':
            return self._ret(self.dev_write(r0, r1, r2, r3, self.w(self.r(UC_ARM_REG_SP))))

    def start_xfer(self, phys):
        """The controller, as far as the engine can tell: walk the chain from the
        DMA table entry StartTransfer would hand it and gather the bytes."""
        ctx = phys >> 1
        dma = self.w(PX_DMA_TBL + 4 * ctx)
        assert dma % 16 == 0, f'TRB chain at DMA {dma:#x}: DWC3 needs 16-aligned TRBs (10-27 live failure)'
        assert self.w(PX_CPU_TBL + 4 * ctx) == dma + 0x40000000, 'tables disagree'
        if self.start_rc:
            self.xfers.append({'phys': phys, 'refused': True})
            return self.start_rc & 0xFFFFFFFF
        trbs, at = [], dma + 0x40000000
        for _ in range(80):
            lo, hi, size, ctrl = struct.unpack('<4I', self.mu.mem_read(at, 16))
            trbs.append((lo, hi, size, ctrl, at))
            if ctrl & 2:
                break
            assert ctrl & 4, f'TRB {len(trbs)} neither chained nor last: {ctrl:#x}'
            at += 16
        data = b''.join(bytes(self.mu.mem_read(lo + 0x40000000, size)) for lo, _, size, _, _ in trbs)
        self.xfers.append({'phys': phys, 'trbs': [t[:4] for t in trbs], 'data': data})
        self.last_chain = trbs
        self.put(0x2100C80C + 0x10 * phys, 0x10006)             # DEPCMD reads back StartTransfer, resource 1
        if self.complete:
            self.finish()
        return 0

    def finish(self):
        lo, hi, size, ctrl, at = self.last_chain[-1]
        self.mu.mem_write(at + 12, struct.pack('<I', ctrl & ~1))

    def dev_write(self, dev, lo, hi, n, buf):
        assert dev == 0xE, dev
        assert buf == self.w(DRV + 4) and self.w(DRV) == 1, 'not the held arena'
        data = bytearray()
        for i in range(self.w(DRV + 8)):
            w0, phys = struct.unpack('<II', self.mu.mem_read(TBL + 8 * i, 8))
            ln = (w0 >> 16) | (((w0 >> 6) & 0x3FF) << 16) or self.w(MAXDESC)
            data += self.mu.mem_read(phys + 0x40000000, ln)
        assert len(data) == n * SS
        k = self.writes; self.writes += 1
        if k == self.fail_write:
            return 0
        self.disk[(lo | hi << 32) * SS] = bytes(data)
        return 1

    def run(self, pc, r0=0, r1=0, thumb=True, lr=DONE):
        out = self.call(pc, r0=r0, r1=r1, thumb=thumb, lr=lr)
        while self.switch:
            regs, self.switch = self.switch, None
            self.service()
            for r, v in zip(REGS, regs): self.mu.reg_write(r, v)
            self.mu.reg_write(UC_ARM_REG_R0, 0)
            self.mu.reg_write(UC_ARM_REG_PC, regs[REGS.index(UC_ARM_REG_LR)])
            try:
                self.mu.emu_start(regs[REGS.index(UC_ARM_REG_LR)], DONE, count=20_000_000)
            finally:
                if self.error: raise self.error
            out = (self.r(UC_ARM_REG_R0), self.r(UC_ARM_REG_SP))
        return out[0]

    def service(self):
        self.call(self.entry['wr_service'], r0=self.state_addr, thumb=True, sp=V3.STACK - 0x9004)


def build_sup(defines=(), ctl_only=False):
    key = (tuple(defines), ctl_only)
    if key not in _BUILDS:
        _BUILDS[key] = IB.build(defines, ctl_only=ctl_only)
    return _BUILDS[key]


class Take:
    def __init__(self, seed=0, frames=120, fail_write=None, sizes=None, defines=(), cached_frames=False,
                 ctl_only=False):
        self.sup, self.info = build_sup(defines, ctl_only) if ctl_only else build_sup(defines)
        fname = 'ISPC.BIN' if ctl_only else 'ISPL.BIN'
        cam = self.cam = Cam(*V4.card((fname, self.sup)), seed, fail_write)
        cam.boot()
        blocks = V4.blocks(cam)
        assert fname in blocks, cam.loadlog()
        block = blocks[fname]
        cached = block + 0x80000000 if 0x40000000 <= block < 0x80000000 else block
        inner = cached + self.info['inner_at']
        cam.state_addr = cached + self.info['state_at']
        cam.entry = {k: inner + self.info['c_base'] + v for k, v in self.info['entries'].items()}
        self.block, self.cap_at = block, cam.state_addr + self.info['cap_off']
        self.rnd = random.Random(seed)
        self.frames, self.sizes = frames, sizes or [1_095_168 // 8, 60_000, 300_001, 2_048, 700_000]
        self.cached_frames = cached_frames
        self.pieces = {}; self.next_cl = 0x40; self.addr = DATA; self.expect = {}

    # ---- the sink, as the host tool sets it
    def cap(self):
        return R.parse_cap(bytes(self.cam.mu.mem_read(self.cap_at, R.CAP_BYTES)))

    def arm(self, mode, chunks=(), keep_first=1 << 30, every_us=0, log=(0, 0)):
        c = self.cam
        for o in range(R.O_HOST, R.HOST_END, 4): c.put(self.cap_at + o, 0)      # as ispl.cap_image
        c.put(self.cap_at + R.OFF['keep_first'], keep_first)
        c.put(self.cap_at + R.OFF['every_us'], every_us)
        c.put(self.cap_at + R.OFF['log_addr'], log[0]); c.put(self.cap_at + R.OFF['log_max'], log[1])
        for i in range(R.MAX_CHUNK):
            a, n = chunks[i] if i < len(chunks) else (0, 0)
            c.put(self.cap_at + R.O_CHUNK + 8 * i, a); c.put(self.cap_at + R.O_CHUNK + 8 * i + 4, n)
        c.put(self.cap_at + 12, len(chunks))
        c.put(self.cap_at + 8, R.MODES[mode])

    def stream(self, chunks):
        return b''.join(bytes(self.cam.mu.mem_read(a, n)) for a, n in chunks)

    # ---- the take (rec-core/writer/test_card.py)
    def rd(self, off): return self.cam.w(VOL + off)
    def wr(self, off, v): self.cam.put(VOL + off, v)

    def mount(self):
        c = self.cam
        for a in range(VOL, VOL + 0x4A68, 4): c.put(a, 0)
        c.put(VOL + 0x0, 0xE); c.put(VOL + 0x1460, SS); c.put(VOL + 0x146C, SPC); c.put(VOL + 0x1458, HEAP_LBA)
        for k, a in SD.items(): c.put(VOL + SLOT[k], a)
        for o in range(0, 0x30, 4): c.put(DRV + o, 0)
        c.put(DRV + 4, TBL); c.put(DRV + 0x10, BOUNCE)
        c.put(MAXDESC, 0x10000)

    def start(self):
        p = V3.HEAP + 0x700000
        for i, v in enumerate((0x04000000, PAD, 0x40000, 0xC03A55D0)): self.cam.put(p + 4 * i, v)
        return self.cam.run(0xC063F220, r0=DEV_ID, r1=p)

    def call_slot(self, slot, *args):
        a = self.rd(SLOT[slot])
        return self.cam.run(a & ~1, *args, thumb=bool(a & 1), lr=DONE)

    def send(self, lr=DONE):
        self.cam.run(0xC063F140, r0=VOL, lr=lr)

    def extent(self, f, pieces):
        size = sum(n for _, n in pieces); ncl = -(-size // CLUSTER)
        cl = self.next_cl + (self.rnd.randint(1, 3) if self.rnd.random() < 0.05 else 0)
        self.next_cl = cl + ncl
        p = ((cl - 2) * SPC + HEAP_LBA) * SS
        for a, n in pieces: self.expect[a] = p; p += n
        if self.rd(0x4A58) and cl != self.rd(0x4A54) + self.rd(0x4A58) // CLUSTER:
            self.send()
        if not self.rd(0x484C):
            raise AssertionError('the take degraded to direct writes')
        lst = V3.HEAP + 0x710000
        alias = CACHED if self.cached_frames else 0
        for i, (a, n) in enumerate(pieces): self.cam.put(lst + 8 * i, a + alias); self.cam.put(lst + 8 * i + 4, n)
        st = V3.HEAP + 0x720000
        for i, v in enumerate((VOL, lst, 0, 0, PAD, 0x40000, CLUSTER, cl, 0, size, 0, 0)):
            self.cam.put(st + 4 * i, v)
        r = self.cam.run(0xC063F048, r0=st)
        assert r == 0, f'C063F048 -> {r:#x}'
        if not self.rd(0x4A58): self.wr(0x4A54, cl)
        self.wr(0x4A58, self.rd(0x4A58) + ncl * CLUSTER)
        if self.rd(0x4A58) >= self.rd(0x4828): self.send()

    def frame(self, f):
        rnd = self.rnd
        size = rnd.choice(self.sizes)
        pieces, left = [], size
        while left:
            n = min(left, rnd.choice([3, 4096, 70_001, 1 << 20]))
            a = self.addr + rnd.choice([0, 0, 1, 2])
            self.cam.mu.mem_write(a, rnd.randbytes(n))
            self.addr = (a + n + 0x40) & ~0x3
            pieces.append((a, n))
            left -= n
        self.pieces[f] = pieces
        cut = rnd.randint(1, len(pieces)) if len(pieces) > 1 and rnd.random() < 0.2 else len(pieces)
        for part in (pieces[:cut], pieces[cut:]):
            if part: self.extent(f, part)
        if self.rd(0x4850) == 0x80: self.send()
        if self.rd(0x4A58) == 0:
            self.call_slot('cb', f + 1, 0)
        else:
            n = self.rd(0x4850); self.wr(0x4854 + 4 * n, f + 1); self.wr(0x4850, n + 1)

    def in_image(self, image, a, n):
        p = self.expect[a]
        for off, data in image.items():
            if off <= p and p + n <= off + len(data):
                return data[p - off:p - off + n] == bytes(self.cam.mu.mem_read(a, n))
        return False

    def run(self, writer_bias=0.5):
        c = self.cam
        self.mount()
        assert self.start() == 1
        for f in range(self.frames):
            self.frame(f)
            if self.rnd.random() < writer_bias: c.service()
        assert c.run(0xC063F310, r0=DEV_ID, r1=0) == 1
        return self


CHUNKS = [(CAP, 0x7FFFF3), (CAP + 0x900000, 0x500001), (CAP + 0x1000000, 0xFFFFFC)]   # odd sizes: records span
SMALL = [2_048, 60_000, 130_001]      # capture takes: unicorn copies every word through a code hook


class SinkTests(unittest.TestCase):
    def assert_completed(self, t):
        c = t.cam
        self.assertEqual([f for f, _ in c.cookies], list(range(1, t.frames + 1)))
        self.assertTrue(all(s == 0 for _, s in c.cookies))
        for k, a in SD.items():
            self.assertEqual(t.rd(SLOT[k]), a, f'{k} not stock after the stop')
        self.assertEqual(c.w(DRV), 0, 'driver table held after the take')

    def guards_intact(self, t, chunks):
        mem = bytes(t.cam.mu.mem_read(CAP, CAP_SIZE))
        inside = bytearray(CAP_SIZE)
        for a, n in chunks: inside[a - CAP:a - CAP + n] = b'\1' * n
        bad = [i for i in range(0, CAP_SIZE, 997) if not inside[i] and mem[i] != GUARD]
        self.assertEqual(bad[:4], [], 'the sink wrote outside the lent chunks')

    def test_loads_as_v4_and_restores_at_power_off(self):
        t = Take()
        c = t.cam
        for site in (0xC063F140, 0xC063F220):
            self.assertEqual(c.w(site), 0xF000F8DF)
            self.assertTrue(0xC5000000 <= c.w(site + 4) < 0xC5800000, hex(c.w(site + 4)))
        self.assertEqual(c.w(0xC03A549C), 0xE51FF004)
        cap = t.cap()
        self.assertEqual((cap['magic'], cap['version'], cap['mode']), (R.CAP_MAGIC, R.CAP_VERSION, 0))
        self.assertEqual(t.info['cap_bytes'], R.CAP_BYTES)
        c.power_off()
        for a, h in IB.SITES.items():
            self.assertEqual(bytes(c.mu.mem_read(a, 8)).hex(), h)

    def test_sd_mode_is_ulwr(self):
        for seed in range(2):
            t = Take(seed).run()
            self.assert_completed(t)
            for f, pieces in t.pieces.items():
                for a, n in pieces:
                    self.assertTrue(t.in_image(t.cam.disk, a, n), f'frame {f} not on disk')
            self.assertGreater(t.cam.writes, 3)
            self.assertEqual(t.cap()['n_rec'], 0)

    def test_capture_rebuilds_the_disk_and_writes_nothing(self):
        for seed in range(3):
            t = Take(seed, frames=80, sizes=SMALL); t.arm('capture', CHUNKS); t.run()
            self.assert_completed(t)
            self.assertEqual(t.cam.writes, 0, 'capture reached the card')
            cap = t.cap()
            recs = list(R.records(t.stream(CHUNKS), cap['used']))
            self.assertEqual(len(recs), cap['n_rec']); self.assertEqual(cap['n_full'], 0)
            self.assertEqual([r['seq'] for r in recs], sorted(r['seq'] for r in recs))
            self.assertEqual(sum(r['ncookie'] for r in recs) <= t.frames, True)
            img = R.disk_image(recs, HEAP_LBA, SPC)
            for f, pieces in t.pieces.items():
                for a, n in pieces:
                    self.assertTrue(t.in_image(img, a, n), f'seed {seed} frame {f} piece {a:#x} not captured')
            self.guards_intact(t, CHUNKS)

    def test_frames_at_the_cached_alias_are_read_uncached(self):
        t = Take(2, frames=30, sizes=SMALL, cached_frames=True); t.arm('capture', CHUNKS); t.run()
        recs = list(R.records(t.stream(CHUNKS), t.cap()['used']))
        img = R.disk_image(recs, HEAP_LBA, SPC)
        for f, pieces in t.pieces.items():
            for a, n in pieces:
                self.assertTrue(t.in_image(img, a, n), f'frame {f}: stale (cached) bytes captured')

    def test_full_sink_keeps_whole_records_and_the_take_going(self):
        small = [(CAP, 0x9FFFF1), (CAP + 0xC00000, 0x3FFFF)]
        t = Take(1, frames=120, sizes=SMALL); t.arm('capture', small); t.run()
        self.assert_completed(t)
        self.assertEqual(t.cam.writes, 0)
        cap = t.cap()
        self.assertGreater(cap['n_full'], 0)
        recs = list(R.records(t.stream(small), cap['used']))
        self.assertEqual(len(recs), cap['n_rec'])
        self.assertGreater(len(recs), 0)
        self.guards_intact(t, small)

    def test_discard_stores_and_writes_nothing(self):
        t = Take(3, frames=60); t.arm('discard', CHUNKS); t.run()
        self.assert_completed(t)
        cap = t.cap()
        self.assertEqual((t.cam.writes, cap['n_rec'], cap['used']), (0, 0, 0))
        self.assertGreater(cap['n_discard'], 0)
        self.guards_intact(t, [])

    def test_lent_memory_must_be_the_uncached_alias(self):
        # big enough for every record: refused for its address, not its size
        # (IMXL's 1 MiB chunk was refused only because nothing fit in it)
        bad = [(0xC5000000, 0x10000000)]          # the heap's cached alias: code lives up there
        t = Take(0, frames=20); t.arm('capture', bad); t.run()
        self.assert_completed(t)
        cap = t.cap()
        self.assertEqual((cap['n_rec'], cap['used']), (0, 0))
        self.assertGreater(cap['n_full'], 0)


LOG_AT = CAP + 0x1F00000                # inside CAP, past every CHUNKS entry


class KeepTests(unittest.TestCase):
    def kept(self, t, chunks=CHUNKS):
        cap = t.cap()
        return cap, list(R.records(t.stream(chunks), cap['used']))

    def test_first_k_then_nothing(self):
        t = Take(4, frames=80, sizes=SMALL); t.arm('capture', CHUNKS, keep_first=2, every_us=0); t.run()
        SinkTests.assert_completed(self, t)
        cap, recs = self.kept(t)
        self.assertEqual(len(recs), 2)
        self.assertGreater(cap['n_skip'], 0)
        self.assertEqual(t.cam.writes, 0, 'a skipped block reached the card')
        # the kept ones are the first two the writer took
        self.assertEqual([r['seq'] for r in recs], sorted(r['seq'] for r in recs)[:2])

    def test_every_interval(self):
        t = Take(5, frames=80, sizes=SMALL); t.arm('capture', CHUNKS, keep_first=1, every_us=5_000); t.run()
        # (the stub clock moves 1 ms per tick call, a few calls per block)
        SinkTests.assert_completed(self, t)
        cap, recs = self.kept(t)
        self.assertGreater(cap['n_skip'], 0)
        self.assertGreater(len(recs), 1)
        gaps = [b['t_us'] - a['t_us'] for a, b in zip(recs, recs[1:])]
        self.assertTrue(all(g >= 5_000 for g in gaps), gaps)

    def test_full_sink_still_skips(self):
        # a full sink must not degrade to "keep everything": the copy never runs again
        small = [(CAP, 0x9FFFF1)]
        t = Take(1, frames=120, sizes=SMALL); t.arm('capture', small, keep_first=3, every_us=0); t.run()
        cap = t.cap()
        self.assertLessEqual(cap['n_rec'] + cap['n_full'], 3)
        self.assertGreater(cap['n_skip'], 0)


class LogTests(unittest.TestCase):
    def test_a_line_per_block(self):
        t = Take(6, frames=60, sizes=SMALL); t.arm('capture', CHUNKS, keep_first=2, log=(LOG_AT, 4096)); t.run()
        cap = t.cap()
        lines = R.log_lines(bytes(t.cam.mu.mem_read(LOG_AT, 16 * cap['log_n'])), cap['log_n'])
        self.assertEqual(cap['log_n'], cap['n_rec'] + cap['n_skip'] + cap['n_full'])
        self.assertEqual([l['seq'] for l in lines], sorted(l['seq'] for l in lines))
        self.assertTrue(all(l['bytes'] > 0 and l['ncookie'] >= 0 for l in lines))
        self.assertEqual([l['t_us'] for l in lines], sorted(l['t_us'] for l in lines))

    def test_log_is_bounded(self):
        t = Take(6, frames=60); t.arm('discard', CHUNKS, log=(LOG_AT, 1)); t.run()
        self.assertEqual(t.cap()['log_n'], 1)
        self.assertEqual(set(bytes(t.cam.mu.mem_read(LOG_AT + 16, 4096))), {GUARD}, 'log ran past log_max')

    def test_log_refuses_the_cached_alias(self):
        t = Take(6, frames=20); t.arm('discard', CHUNKS, log=(0xC5000000, 64)); t.run()
        self.assertEqual(t.cap()['log_n'], 0)


RECSTATE = 0xC3757F30
START = ['recstate ena', 'recstate init', 'key MOVON']          # layout 10: +6 polled per step, no movrecstwai
STOP = ['key MOVON', 'recstate movsavewai']


class ControlTests(unittest.TestCase):
    def setup(self, start_ms=100, rec_ms=1000, starts=True, saves_on=2, ctl_only=False):
        """starts: the first MOVON sets recstate +6.  saves_on: the n-th MOVON
        sets +7 (None: never)."""
        t = Take(0, frames=1, ctl_only=ctl_only)
        t.arm('discard')
        c = t.cam
        c.mu.mem_write(RECSTATE, bytes(8))
        presses = [0]

        def on_shell(line):
            if line == 'recstate init':
                c.mu.mem_write(RECSTATE + 5, bytes(3))
            if line == 'key MOVON':
                presses[0] += 1
                if presses[0] == 1 and starts:
                    c.mu.mem_write(RECSTATE + 6, b'\1')
                if presses[0] == saves_on:
                    c.mu.mem_write(RECSTATE + 7, b'\1')
        c.on_shell = on_shell
        c.put(t.cap_at + R.OFF['start_ms'], start_ms); c.put(t.cap_at + R.OFF['rec_ms'], rec_ms)
        c.put(t.cap_at + R.OFF['ctl'], R.CTL['armed'])          # last, as the host does
        return t

    def step(self, t, now):
        t.cam.now = now
        t.cam.call(t.cam.entry['ix_ctl_step'], r0=t.cam.state_addr, thumb=True, sp=V3.STACK - 0x9004)
        return t.cap()

    def lines(self, t):
        return [l for l, _ in t.cam.shell]

    def test_frame_clock(self):
        """v8: the receiver counter (0x30100588 & 0x7FF) during the take -> fc_frames over fc_t_first..fc_t_last.
        One step sees two frames (gap 2) and the counter wraps past 0x7FF; the upper bits are not the counter."""
        t = self.setup(start_ms=100, rec_ms=60_000)
        now = 5_000_000
        self.step(t, now)
        while self.step(t, now)['ctl'] != R.CTL['rec']:
            now += 50_000
        v, seen = 0x7E0, []
        for i in range(40):
            now += 20_000
            v = (v + (2 if i == 20 else 1)) & 0x7FF
            t.cam.put(0x30100588, 0x5A000 | v)
            seen.append((now, v))
            cap = self.step(t, now)
        (t1, v1), (tn, vn) = seen[1], seen[-1]               # seen[0] is the first sample, seen[1] the first edge
        self.assertEqual(cap['fc_frames'], (vn - v1) & 0x7FF)
        self.assertEqual((cap['fc_t_last'] | 1) - (cap['fc_t_first'] | 1), tn - t1)    # the stub clock runs ahead by a fixed 1 ms
        self.assertEqual((cap['fc_gap_max'], cap['fc_steps']), (2, 40))

    def test_the_firmware_script_on_time(self):
        t = self.setup(start_ms=100, rec_ms=1000)
        base = 5_000_000
        self.assertEqual(self.step(t, base)['ctl'], R.CTL['armed'])        # t_arm stamped
        self.assertEqual(self.step(t, base + 50_000)['ctl'], R.CTL['armed'])
        self.assertEqual(t.cam.shell, [])
        cap = self.step(t, base + 120_000)
        self.assertEqual(cap['ctl'], R.CTL['starting'])
        self.assertEqual(self.lines(t), START)
        cap = self.step(t, base + 140_000)                            # the next step sees +6
        self.assertEqual(cap['ctl'], R.CTL['rec'])
        self.assertEqual(self.lines(t), START)
        self.assertNotIn('key MOVOFF', self.lines(t))                 # the firmware's script never sends it
        self.assertEqual(self.step(t, base + 700_000)['ctl'], R.CTL['rec'])
        cap = self.step(t, base + 1_200_000)
        self.assertEqual(cap['ctl'], R.CTL['done'])
        self.assertEqual(self.lines(t), START + STOP + ['recstate disa'])
        self.assertEqual((cap['n_press'], cap['rs_started'], cap['rs_saved']), (2, 1, 1))
        self.assertGreaterEqual(cap['t_stop'] - cap['t_rec'], 1_000_000)
        self.step(t, base + 9_000_000)
        self.assertEqual(len(t.cam.shell), len(START + STOP) + 1, 'ran again after done')

    def test_no_start_no_second_press(self):
        t = self.setup(starts=False, saves_on=None)
        self.step(t, 1_000_000); cap = self.step(t, 2_000_000)
        self.assertEqual(cap['ctl'], R.CTL['starting'])
        for now in range(4_000_000, 61_900_001, 2_000_000):            # movrecstwai's 60 s from the MOVON
            self.assertEqual(self.step(t, now)['ctl'], R.CTL['starting'], now)
        self.assertEqual(self.lines(t), START)
        cap = self.step(t, 62_100_000)
        self.assertEqual(cap['ctl'], R.CTL['fail_start'])
        self.assertEqual(self.lines(t), START + ['recstate disa'])
        for now in (65_000_000, 160_000_000):
            self.step(t, now)
        self.assertEqual(self.lines(t), START + ['recstate disa'])
        self.assertEqual(self.lines(t).count('key MOVON'), 1, 'pressed REC on a camera that never started')

    def test_a_cancel_cannot_abandon_a_pressed_start(self):
        t = self.setup(start_ms=100, rec_ms=1000, starts=False)
        self.step(t, 1_000_000); self.step(t, 1_200_000)                # MOVON: starting
        t.cam.put(t.cap_at + R.OFF['ctl'], R.CTL['idle'])               # a host write over ctl meanwhile
        self.assertEqual(self.step(t, 1_400_000)['ctl'], R.CTL['starting'])
        t.cam.mu.mem_write(RECSTATE + 6, b'\1')
        self.assertEqual(self.step(t, 1_600_000)['ctl'], R.CTL['rec'])
        cap = self.step(t, 2_700_000)
        self.assertEqual(cap['ctl'], R.CTL['done'], 'the take that started was left running')
        self.assertEqual(self.lines(t), START + STOP + ['recstate disa'])

    def test_missing_save_ack_does_not_press_again(self):
        t = self.setup(saves_on=3)
        self.step(t, 1_000_000); self.step(t, 2_000_000); self.step(t, 2_020_000); cap = self.step(t, 9_000_000)
        self.assertEqual(cap['ctl'], R.CTL['fail_stop'])
        self.assertEqual(self.lines(t), START + STOP + ['recstate disa'])
        self.assertEqual(cap['n_press'], 2, 'uncertain stop must not start another take')

    def test_stop_failure_is_terminal(self):
        t = self.setup(saves_on=None)
        self.step(t, 1_000_000); self.step(t, 2_000_000); self.step(t, 2_020_000); cap = self.step(t, 9_000_000)
        self.assertEqual(cap['ctl'], R.CTL['fail_stop'])
        self.assertEqual(self.lines(t), START + STOP + ['recstate disa'])
        self.assertEqual(cap['ctl_line'], 6)
        self.step(t, 90_000_000)
        self.assertEqual(self.lines(t), START + STOP + ['recstate disa'])

    def test_cancel_before_start(self):
        t = self.setup(start_ms=100)
        self.step(t, 1_000_000)
        t.cam.put(t.cap_at + R.OFF['ctl'], R.CTL['idle'])
        self.step(t, 9_000_000)
        self.assertEqual(t.cam.shell, [])

    def test_idle_presses_nothing(self):
        t = Take(0, frames=1)
        for now in (1_000_000, 50_000_000):
            self.step(t, now)
        self.assertEqual(t.cam.shell, [])

    def test_tick_wraps(self):
        t = self.setup(start_ms=100, rec_ms=1000)
        base = 0xFFFFFFFF - 50_000
        self.step(t, base)
        self.step(t, (base + 150_000) & 0xFFFFFFFF)
        self.step(t, (base + 170_000) & 0xFFFFFFFF)
        self.assertEqual(t.cap()['ctl'], R.CTL['rec'])


LV_DESC, LV_CHSEL = 0xC30255B4, 0xC31DF8D8
LV_REG = {0: 0x301832E8, 3: 0x301835E8}                # [LV_CHSEL] -> channel 2 / 5's slot register
LV_W, LV_H, LV_N = 1620, 911, 4
LV_SLOT = [0x4B000000 + i * 0x300000 for i in range(LV_N)]


class LvTests(unittest.TestCase):
    """The LV sampler (PUSH_CALLERS §1): the last slot the display DMA finished
    (register byte1), every lv_every_us, handed to the engine in mode 0; nothing waits."""
    def setup(self, every_us=250_000, lag=0, chsel=0, reg=0x20102, n=LV_N, w=LV_W, push=True, lv_max=0):
        t = Take(0, frames=1)
        t.arm('discard')
        c = t.cam
        desc = [0] * 32
        desc[3], desc[4], desc[8] = w, LV_H, n
        for i, a in enumerate(LV_SLOT):
            desc[9 + i] = (a - 0x40000000) // 4
        c.mu.mem_write(LV_DESC, struct.pack('<32I', *desc))
        c.put(LV_CHSEL, chsel)
        c.put(LV_REG.get(chsel, 0x301837E8), reg)
        for k, v in (('lv_every_us', every_us), ('lv_lag', lag), ('lv_max', lv_max),
                     ('lv_push', STUBS['PUSH'] if push else 0)):
            c.put(t.cap_at + R.OFF[k], v)
        c.mu.mem_write(RECSTATE, bytes(8))
        c.put(t.cap_at + R.OFF['start_ms'], 1_000_000)        # armed, REC far away: the sampler runs, nobody presses
        c.put(t.cap_at + R.OFF['ctl'], R.CTL['armed'])
        return t

    step = ControlTests.step

    def test_pushes_the_slot_before_the_current_one(self):
        t = self.setup(reg=0x20102)              # writing 2, finished 1, on screen 2 (measured 10-24)
        cap = self.step(t, 1_000_000)
        self.assertEqual(len(t.cam.pushes), 1)
        p = t.cam.pushes[0]
        self.assertEqual((p['mode'], p['source'], p['fmt'], p['w'], p['h'], p['stride'], p['nseg']),
                         (0, 1, 1, LV_W, LV_H, 2 * LV_W, 1))
        self.assertEqual(p['segs'][0], (LV_SLOT[1], 2 * LV_W * LV_H))
        self.assertEqual((p['frame_no'], p['aux0'], p['aux1'], p['flags']), (1, 0x20102, 2, 0))
        self.assertEqual((cap['lv_n_sent'], cap['lv_last_addr']), (1, LV_SLOT[1]))

    def test_slot_zero_wraps_to_the_last(self):
        t = self.setup(reg=0x10000, lag=2)        # finished 0, one older = 3
        self.step(t, 1_000_000)
        self.assertEqual(t.cam.pushes[0]['segs'][0][0], LV_SLOT[3])

    def test_hdmi_channel_and_its_wider_mask(self):
        t = self.setup(chsel=3, reg=0x20101)               # channel 5's register: finished 1
        self.step(t, 1_000_000)
        p = t.cam.pushes[0]
        self.assertEqual((p['aux1'], p['segs'][0][0]), (5, LV_SLOT[1]))

    def test_lag(self):
        t = self.setup(reg=0x30203, lag=2)        # finished 2, one older = 1
        self.step(t, 1_000_000)
        self.assertEqual(t.cam.pushes[0]['segs'][0][0], LV_SLOT[1])

    def test_interval_and_the_cap(self):
        t = self.setup(every_us=250_000, lv_max=3)
        for now in range(1_000_000, 3_000_000, 20_000):     # the task's 20 ms steps for 2 s
            self.step(t, now)
        self.assertEqual(len(t.cam.pushes), 3)
        t = self.setup(every_us=250_000)
        for now in range(1_000_000, 3_000_000, 20_000):
            self.step(t, now)
        self.assertEqual(len(t.cam.pushes), 8)

    def test_busy_engine_is_counted_not_waited(self):
        t = self.setup(every_us=20_000)
        t.cam.push_ret = 1
        for now in (1_000_000, 1_020_000):
            cap = self.step(t, now)
        self.assertEqual((cap['lv_n_sent'], cap['lv_n_skip'], cap['lv_n_err']), (0, 2, 0))
        t.cam.push_ret = 7
        cap = self.step(t, 1_040_000)
        self.assertEqual(cap['lv_n_err'], 1)

    def test_off_without_an_engine(self):
        t = self.setup(push=False)
        for now in (1_000_000, 5_000_000):
            self.step(t, now)
        self.assertEqual(t.cam.pushes, [])

    def test_bad_descriptor_pushes_nothing(self):
        for kw in (dict(n=0), dict(n=9), dict(w=0), dict(w=8000), dict(lag=5), dict(reg=0x50400)):
            t = self.setup(**kw)
            cap = self.step(t, 1_000_000)
            self.assertEqual(t.cam.pushes, [], kw)
            self.assertEqual(cap['lv_n_bad'], 1, kw)

    def test_a_finished_take_samples_nothing(self):
        t = self.setup()
        t.cam.put(t.cap_at + R.OFF['ctl'], R.CTL['done'])
        before = t.cap()['lv_t_last']
        for now in (1_000_000, 2_000_000):
            self.step(t, now)
        self.assertEqual((t.cam.pushes, t.cap()['lv_t_last']), ([], before),
                         'the sampler wrote the cap after the take: the host arm races it')

    def test_recording_flag(self):
        t = self.setup()
        t.cam.put(t.cap_at + R.OFF['rec_ms'], 3_000_000)   # 50 min; x1000 still fits u32
        t.cam.put(t.cap_at + R.OFF['t_rec'], 1)
        t.cam.put(t.cap_at + R.OFF['ctl'], R.CTL['rec'])
        self.step(t, 1_000_000)
        self.assertEqual(t.cam.pushes[0]['flags'] & 1, 1)
        self.assertEqual(t.cam.shell, [], 'the sampler pressed something')


WT_ADDRS = [0xC30255C0, 0xC30255C4, 0xC3025640, 0xC3025644, 0xC30256C0, 0xC30256C4, 0xC31E10F8, 0xC31E10FC,
            0xC31DF594, 0xC31DF598, 0xC31DF59C, 0xC31DF5A0, 0xC31DF744, 0xC31DF748, 0xC31DF74C, 0xC31DF750]   # IX_WT_ADDRS


def ring_reg(done):
    """The slot register with `done` the last slot finished (byte1), done + 1 being written and on screen."""
    nxt = (done + 1) % LV_N
    return (nxt << 16) | (done << 8) | nxt


class BurstTests(unittest.TestCase):
    """Layout 10: the start no longer blocks in movrecstwai (LV goes on while recstate +6 is pending), and with
    lv_burst_ms every newly finished ring slot is pushed from our MOVON until lv_burst_ms after the start was
    seen, each with a bu entry holding the display watch at that moment."""
    step = ControlTests.step
    STEP = 20_000

    def setup(self, burst_ms=300, every_us=250_000, lv_max=0):
        t = LvTests.setup(self, every_us=every_us, lv_max=lv_max)
        c = t.cam
        c.put(t.cap_at + R.OFF['lv_burst_ms'], burst_ms)
        c.put(t.cap_at + R.OFF['start_ms'], 100)
        c.put(t.cap_at + R.OFF['rec_ms'], 1000)
        presses = [0]

        def on_shell(line):                    # +6 comes later, from run(); the second MOVON saves
            if line == 'recstate init':
                c.mu.mem_write(RECSTATE + 5, bytes(3))
            if line == 'key MOVON':
                presses[0] += 1
                if presses[0] == 2:
                    c.mu.mem_write(RECSTATE + 7, b'\1')
        c.on_shell = on_shell
        return t

    def run_take(self, t, start_after_us=600_000, frames=lambda i: i * 3 // 4, busy=lambda i: False,
                 t0=1_000_000, steps=150):
        """20 ms control steps; the display finishes frames(i) frames by step i (so the slot is frames(i) % 4);
        recstate +6 is set start_after_us after the step that pressed MOVON; busy(i): the engine skips at step i.
        -> [{now (the sup's tick), ctl_before, ctl, slot, reg, wt, ret, pushes}]"""
        c = t.cam
        log, ctl, movon = [], R.CTL['armed'], None
        for i in range(steps):
            now = t0 + i * self.STEP
            slot = frames(i) % LV_N
            reg = ring_reg(slot)
            c.put(LV_REG[0], reg)
            wt = [LV_W, LV_H] + [0x5A000000 | (i << 8) | k for k in range(2, 16)]   # 0, 1 are the LV descriptor's w/h
            for a, v in zip(WT_ADDRS, wt):
                c.put(a, v)
            if movon is not None and now - movon >= start_after_us:
                c.mu.mem_write(RECSTATE + 6, b'\1')
            c.push_ret = 1 if busy(i) else 0
            n0 = len(c.pushes)
            cap = self.step(t, now)
            if movon is None and 'key MOVON' in ControlTests.lines(self, t):
                movon = now
            log.append(dict(now=now + 1000, ctl_before=ctl, ctl=cap['ctl'], slot=slot, reg=reg, wt=wt,
                            ret=c.push_ret, pushes=c.pushes[n0:]))
            ctl = cap['ctl']
        return log, t.cap()

    def expect(self, log, cap, burst_us, every_us=250_000):
        """What the sampler must do, step by step: (now, slot, burst)."""
        out, last_slot, last_t = [], None, 0
        for e in log:
            cb, now = e['ctl_before'], e['now']
            if cb not in (R.CTL['armed'], R.CTL['starting'], R.CTL['rec']):
                continue
            burst = burst_us and (cb == R.CTL['starting'] or
                                  (cb == R.CTL['rec'] and now - cap['t_rec'] < burst_us))
            if burst:
                if e['slot'] == last_slot:
                    continue
                out.append((now, e['slot'], True))
                last_t = now
                if not e['ret']:
                    last_slot = e['slot']
            elif not last_t or now - last_t >= every_us:
                out.append((now, e['slot'], False))
                last_t = now
        return out

    @staticmethod
    def got(log):
        return [(e['now'], p['frame_no'], bool(p['flags'] & 8)) for e in log for p in e['pushes']]

    def test_lv_flows_while_the_start_is_pending(self):
        t = self.setup(burst_ms=0)
        log, cap = self.run_take(t)
        starting = [e for e in log if e['ctl_before'] == R.CTL['starting']]
        self.assertGreaterEqual(len(starting), 29, 'the control task blocked in the start')
        pending = [p for e in starting for p in e['pushes']]
        self.assertGreaterEqual(len(pending), 2, 'no LV between MOVON and the start')
        self.assertTrue(all(p['flags'] & 16 and not p['flags'] & 1 for p in pending))
        self.assertEqual(cap['ctl'], R.CTL['done'])
        self.assertEqual([l for l, _ in t.cam.shell], START + STOP + ['recstate disa'])
        self.assertGreaterEqual(cap['t_rec'] - cap['t_movon'], 600_000)
        self.assertLess(cap['t_rec'] - cap['t_movon'], 600_000 + 2 * self.STEP)

    def test_burst_off_is_the_cadence(self):
        t = self.setup(burst_ms=0)
        log, cap = self.run_take(t)
        self.assertEqual(self.got(log), self.expect(log, cap, 0))
        for e in log:
            for p in e['pushes']:
                self.assertEqual((p['aux0'], p['aux1'], p['flags'] & 8), (e['reg'], 2, 0))
        self.assertEqual((cap['bu_sent'], cap['bu_n'], cap['bursts']), (0, 0, []))

    def test_every_new_slot_once_with_its_watch(self):
        t = self.setup(burst_ms=300)
        log, cap = self.run_take(t)
        want = self.expect(log, cap, 300_000)
        self.assertEqual(self.got(log), want)
        bursts = [(e, p) for e in log for p in e['pushes'] if p['flags'] & 8]
        self.assertGreater(len(bursts), 25)
        for k, (e, p) in enumerate(bursts):
            self.assertEqual((p['frame_no'], p['segs'][0][0]), (e['slot'], LV_SLOT[e['slot']]))
            self.assertEqual((p['aux0'], p['aux1']), (e['now'], k), 'tick / bu index not in the header')
            self.assertEqual(bool(p['flags'] & 16), e['ctl_before'] == R.CTL['starting'])
            self.assertEqual(bool(p['flags'] & 1), e['ctl_before'] == R.CTL['rec'])
        slots = [e['slot'] for e, _ in bursts]
        self.assertTrue(all(a != b for a, b in zip(slots, slots[1:])), 'a slot pushed twice in a row')
        self.assertEqual((cap['bu_sent'], cap['bu_n'], cap['bu_skip']), (len(bursts), len(bursts), 0))
        for b, (e, p) in zip(cap['bursts'], bursts):
            self.assertEqual((b['tick_us'], b['slot'], b['flags'], b['reg']), (e['now'], e['slot'], p['flags'], e['reg']))
            self.assertEqual(list(b['wt'].values()), e['wt'], 'the watch is not the one at the push')

    def test_window_ends_lv_burst_ms_after_the_start(self):
        t = self.setup(burst_ms=300)
        log, cap = self.run_take(t)
        bursts = [e['now'] - cap['t_rec'] for e in log for p in e['pushes'] if p['flags'] & 8]
        self.assertLess(max(bursts), 300_000)
        self.assertGreaterEqual(max(bursts), 300_000 - 3 * self.STEP, 'the window closed early')
        after = [e['now'] for e in log for p in e['pushes'] if not p['flags'] & 8 and e['now'] > cap['t_rec']]
        self.assertTrue(after, 'the cadence did not come back after the window')
        self.assertTrue(all(b - a >= 250_000 for a, b in zip(after, after[1:])))
        self.assertGreaterEqual(min(after) - cap['t_rec'], 300_000)

    def test_a_busy_engine_retries_the_slot_and_counts(self):
        t = self.setup(burst_ms=300)
        log, cap = self.run_take(t, busy=lambda i: i % 3 == 0)
        self.assertEqual(self.got(log), self.expect(log, cap, 300_000))
        sent = [(e['slot'], p['aux1']) for e in log for p in e['pushes'] if p['flags'] & 8 and not e['ret']]
        skipped = [p for e in log for p in e['pushes'] if p['flags'] & 8 and e['ret']]
        self.assertGreater(len(skipped), 3)
        self.assertEqual((cap['bu_sent'], cap['bu_skip']), (len(sent), len(skipped)))
        self.assertEqual([k for _, k in sent], list(range(len(sent))), 'a skip used up a bu index')

    def test_entries_stop_at_the_array_pushes_go_on_and_lv_max_caps(self):
        t = self.setup(burst_ms=3000)
        log, cap = self.run_take(t, frames=lambda i: i, steps=200)
        self.assertGreater(cap['bu_sent'], R.BU_N)
        self.assertEqual((cap['bu_n'], len(cap['bursts'])), (R.BU_N, R.BU_N))
        t = self.setup(burst_ms=3000, lv_max=10)
        log, cap = self.run_take(t, frames=lambda i: i)
        self.assertEqual((len(self.got(log)), cap['lv_n_sent']), (10, 10))


class PushEngineTests(unittest.TestCase):
    """ix_push.c: header + chain built in the sup's state, ctx 3's tables taken and
    given back, EP 0x83 started; mode 0 skips while busy; the bytes parse as FPP1."""
    Q = CAP + 0x1000000                    # where the tests put an ix_push_req (lent memory, uncached)
    SRC = CAP + 0x1100000

    def setUp(self):
        sys.path.insert(0, str(HERE.parent / 'host'))
        import push_rx
        self.rx = push_rx
        self.t = Take(0, frames=1)
        c = self.t.cam
        c.put(PX_DMA_TBL + 12, 0x0BAD0000); c.put(PX_CPU_TBL + 12, 0x4BAD0000)
        c.put(PX_DEAF, 0)

    def req(self, mode=0, source=1, segs=((SRC, 4096),), w=1620, h=911, fmt=1, frame_no=7, flags=1):
        c = self.t.cam
        words = [mode, source, frame_no, w, h, fmt, w * 2, flags, 0x11, 0x22, len(segs)]
        for i in range(4):
            a, n = segs[i] if i < len(segs) else (0, 0)
            words += [a, n]
        c.mu.mem_write(self.Q, struct.pack(f'<{len(words)}I', *words))

    def push(self, timeout_ms=0, **kw):
        self.req(**kw)
        c = self.t.cam
        r = c.call(c.entry['ix_push'], r0=c.state_addr, r1=self.Q, r2=timeout_ms, thumb=True, sp=V3.STACK - 0x9004)
        return r[0] if isinstance(r, tuple) else r

    def test_one_image_parses_and_matches(self):
        c = self.t.cam
        payload = bytes(random.Random(1).randbytes(4096))
        c.mu.mem_write(self.SRC, payload)
        self.assertEqual(self.push(), 0)
        x = c.xfers[-1]
        self.assertEqual(x['phys'], 7)
        got = []
        sp = self.rx.Splitter(lambda h, p: got.append((h, p)))
        sp.feed(x['data'])
        self.assertEqual(len(got), 1, sp.stats())
        h, p = got[0]
        self.assertTrue(h['crc'])
        self.assertEqual((h['source'], h['seq'], h['w'], h['h'], h['fmt'], h['frame_no'], h['flags'], h['aux']),
                         ('lv', 0, 1620, 911, 'yuyv8', 7, 1, [0x11, 0x22]))
        self.assertEqual(p, payload)
        self.assertEqual(x['trbs'][0][2], 256)
        self.assertEqual(x['trbs'][-1][3], 0x813)
        self.assertTrue(all(t[0] < 0x40000000 for t in x['trbs']), 'TRBs must carry DMA addresses')

    def test_big_segment_is_cut_into_trbs(self):
        c = self.t.cam
        n = 0xFFFC00 + 5000                                    # one TRB max + a bit
        self.assertEqual(self.push(segs=((CAP, n),)), 0)
        sizes = [t[2] for t in c.xfers[-1]['trbs']]
        self.assertEqual(sizes, [256, 0xFFFC00, 5000])
        self.assertTrue(all(t[3] == 0x15 for t in c.xfers[-1]['trbs'][:-1]))

    def test_a_reconfigured_endpoint_drops_the_chain_instead_of_skipping_forever(self):
        c = self.t.cam
        c.complete = False
        self.assertEqual(self.push(), 0)
        self.assertEqual(self.push(), 1)                        # still the controller's: skipped
        c.put(PX_DEPCMD, 0x50002)                               # the host reopened: XferConfig (10-27 live)
        self.assertEqual(self.push(), 0, 'a lost chain still blocked the engine')
        self.assertEqual(len([x for x in c.xfers if not x.get('refused')]), 2)
        self.assertEqual(self.push(), 1)                        # the new chain is in flight again

    def test_mode0_skips_while_busy_and_leaves_a_seq_gap(self):
        c = self.t.cam
        c.complete = False
        self.assertEqual(self.push(), 0)
        self.assertEqual(self.push(), 1)                       # still owned by the controller
        self.assertEqual(len(c.xfers), 1)
        c.finish()
        self.assertEqual(self.push(), 0)
        seqs = []
        for x in c.xfers:
            sp = self.rx.Splitter(lambda h, p: seqs.append(h['seq'])); sp.feed(x['data'])
        self.assertEqual(seqs, [0, 2])                         # the skip shows as a gap
        hdr = self.rx.parse_header(c.xfers[-1]['data'][:256])
        self.assertEqual(hdr['n_skip'], 1)

    def test_mode1_timeout_leaves_the_transfer_armed(self):
        c = self.t.cam
        c.complete = False
        self.assertEqual(self.push(mode=1, timeout_ms=5), 3)   # started but NOT completed
        self.assertEqual(c.ends, [], 'EndTransfer on a timeout killed EP83 live (report-take-01/02)')
        self.assertEqual(self.push(mode=0), 1)                 # still armed: skipped, nothing stacked
        c.complete = True
        c.finish()                                              # the host read it
        self.assertEqual(self.push(mode=1, timeout_ms=5), 0)
        hdr = self.rx.parse_header(c.xfers[-1]['data'][:256])
        self.assertEqual((hdr['seq'], hdr['n_skip']), (2, 2))

    def test_refused_start_counts_deaf(self):
        c = self.t.cam
        c.start_rc, = struct.unpack('<I', struct.pack('<i', -2))
        c.put(PX_DEAF, 1)
        self.assertEqual(self.push(), 4)
        self.push()
        c.start_rc = 0; c.put(PX_DEAF, 0)
        self.assertEqual(self.push(), 0)
        hdr = self.rx.parse_header(c.xfers[-1]['data'][:256])
        self.assertEqual((hdr['seq'], hdr['n_skip']), (2, 2))

    def test_bad_requests_send_nothing(self):
        c = self.t.cam
        for segs in ((), ((0x30000000, 16),), ((CAP, 0),), ((0x7FFFFF00, 0x200),)):
            self.assertEqual(self.push(segs=segs), 2, segs)
        self.assertEqual(c.xfers, [])

    def test_release_restores_the_tables(self):
        c = self.t.cam
        self.push()
        self.assertNotEqual(c.w(PX_DMA_TBL + 12), 0x0BAD0000)
        c.call(c.entry['ix_push_release'], r0=c.state_addr, thumb=True, sp=V3.STACK - 0x9004)
        self.assertEqual((c.w(PX_DMA_TBL + 12), c.w(PX_CPU_TBL + 12)), (0x0BAD0000, 0x4BAD0000))

    def test_lv_sampler_uses_the_engine(self):
        t = LvTests.setup(self, push=False)
        c = t.cam
        c.put(PX_DMA_TBL + 12, 0); c.put(PX_CPU_TBL + 12, 0x40000000); c.put(PX_DEAF, 0)
        c.put(t.cap_at + R.OFF['lv_push'], 1)
        c.mu.mem_map(LV_SLOT[0], 0x1000000)                    # the display ring, for the bytes
        LvTests.step(self, t, 1_000_000)
        self.assertEqual(len(c.xfers), 1)
        hdr = self.rx.parse_header(c.xfers[0]['data'][:256])
        self.assertEqual((hdr['source'], hdr['w'], hdr['h'], hdr['total']), ('lv', LV_W, LV_H, 2 * LV_W * LV_H))
        self.assertEqual(t.cap()['lv_n_sent'], 1)


def make_dng(w, h, dt, payload):
    """Little-endian DNG: IFD0 with width/length/DateTime/one strip (what cd_parse reads)."""
    n = 6
    ifd = 8
    dt_at = ifd + 2 + 12 * n + 4
    data_at = dt_at + 20
    tags = [(256, 4, 1, w), (257, 4, 1, h), (258, 3, 1, 12), (273, 4, 1, data_at),
            (279, 4, 1, len(payload)), (306, 2, 20, dt_at)]
    b = b'II*\0' + struct.pack('<I', ifd) + struct.pack('<H', n)
    for tg in tags:
        b += struct.pack('<HHII', *tg)
    return b + b'\0\0\0\0' + dt.encode() + b'\0' + payload


class CdngTests(unittest.TestCase):
    """ix_cdng.c: the RAW arena after a take -> the newest take's DNGs, pushed as
    FPP1 source 4 / fmt 5 through the engine, nothing else."""
    LO, HI = 0x53B00900, 0x54AFFF00
    NEW, OLD = '2026:10:25 07:43:07', '2026:10:24 03:06:21'

    def setUp(self):
        sys.path.insert(0, str(HERE.parent / 'host'))
        import push_rx
        self.rx = push_rx
        self.t = Take(0, frames=1)
        c = self.t.cam
        c.mu.mem_map(0x54000000, 0x01000000)                    # DATA already covers up to 0x54000000
        obj = 0xC3073C3C
        c.put(0xC30739DC + 40, obj)
        c.put(obj + 0xC, self.LO)
        c.mu.mem_write(self.LO, struct.pack('<4I', 0xDEADBEEF, 0x40, 0, self.HI))
        c.mu.mem_write(self.HI, struct.pack('<4I', 0xDEADBEEF, 0x40, self.LO, 0))
        c.put(PX_DMA_TBL + 12, 0); c.put(PX_CPU_TBL + 12, 0x40000000); c.put(PX_DEAF, 0)
        rnd = random.Random(5)
        self.new = [(0x53B18400 + k * 0x31A400, make_dng(1936, 1090, self.NEW, rnd.randbytes(20000 + k))) for k in range(3)]
        self.old = [(0x54200000 + k * 0x8C7800, make_dng(3024, 2010, self.OLD, rnd.randbytes(30000))) for k in range(2)]
        for a, b in self.new + self.old:
            c.mu.mem_write(a, b)
        c.mu.mem_write(0x54600000, b'II*\0' + struct.pack('<I', 8) + bytes(64))   # a header with no IFD
        c.mu.mem_write(0x54700200, self.new[0][1])                                  # not 0x400-aligned

    def run_cd(self, cd_max=0):
        c = self.t.cam
        c.put(self.t.cap_at + R.OFF['cd_max'], cd_max)
        c.call(c.entry['ix_cdng_run'], r0=c.state_addr, thumb=True, sp=V3.STACK - 0x9004)
        return self.t.cap()

    def images(self):
        got = []
        for x in self.t.cam.xfers:
            sp = self.rx.Splitter(lambda h, p: got.append((h, p))); sp.feed(x['data'])
        return got

    def test_pushes_only_the_newest_take_whole(self):
        cap = self.run_cd()
        self.assertEqual((cap['cd_state'], cap['cd_found'], cap['cd_newest_n'], cap['cd_sent']), (1, 5, 3, 3))
        self.assertEqual((cap['cd_lo'], cap['cd_hi']), (self.LO, self.HI + 0x40))
        got = self.images()
        self.assertEqual([p for _, p in got], [b for _, b in self.new])
        for (h, _), (a, _) in zip(got, self.new):
            self.assertEqual((h['source'], h['fmt'], h['w'], h['h'], h['aux'][0]), ('cdng', 'dng', 1936, 1090, a))
        self.assertEqual([h['seq'] for h, _ in got], [0, 1, 2])
        self.assertEqual(self.t.cam.w(PX_CPU_TBL + 12), 0x40000000, 'tables not given back')

    def test_cap_on_count(self):
        cap = self.run_cd(cd_max=2)
        self.assertEqual((cap['cd_newest_n'], cap['cd_sent']), (3, 2))
        self.assertEqual(len(self.images()), 2)

    def test_no_arena_pushes_nothing(self):
        self.t.cam.put(0xC30739DC + 40, 0)
        cap = self.run_cd()
        self.assertEqual(cap['cd_state'], 2)
        self.assertEqual(self.t.cam.xfers, [])

    def test_uncompleted_transfers_are_not_counted_as_delivered_dngs(self):
        self.t.cam.complete = False
        cap = self.run_cd()
        self.assertEqual(cap['cd_state'], 1)
        self.assertEqual((cap['cd_sent'], cap['cd_skip']), (0, 3))
        self.assertEqual(self.t.cam.ends, [])                  # never end a transfer the host may still read

    def test_triggers(self):
        c, t = self.t.cam, self.t
        c.put(t.cap_at + R.OFF['cd_go'], 1)
        LvTests.step(self, t, 1_000_000)
        self.assertEqual((t.cap()['cd_go'], t.cap()['cd_sent']), (0, 3))
        c.xfers.clear()
        for k in ('cd_state', 'cd_sent'):
            c.put(t.cap_at + R.OFF[k], 0)
        c.put(t.cap_at + R.OFF['ctl'], R.CTL['done'])
        c.put(t.cap_at + R.OFF['t_stop'], 2_000_001)
        c.put(t.cap_at + R.OFF['cd_after_ms'], 10_000)
        LvTests.step(self, t, 11_000_000)
        self.assertEqual(c.xfers, [], 'ran before cd_after_ms')
        LvTests.step(self, t, 12_100_000)
        self.assertEqual(len(self.images()), 3)
        LvTests.step(self, t, 20_000_000)
        self.assertEqual(len(self.images()), 3, 'ran twice for one take')


class ReportTests(unittest.TestCase):
    """Reports (FPP1 source 5): a snapshot of ix_cap at every control event, and a heartbeat; the host
    parses them with the same parse_cap it uses on a shell read."""
    def setUp(self):
        sys.path.insert(0, str(HERE.parent / 'host'))
        import push_rx
        self.rx = push_rx

    def run_take(self, rp_on=1, every_us=0):
        t = ControlTests.setup(self, start_ms=100, rec_ms=1000)
        c = t.cam
        c.put(PX_DMA_TBL + 12, 0); c.put(PX_CPU_TBL + 12, 0x40000000); c.put(PX_DEAF, 0)
        c.put(t.cap_at + R.OFF['rp_on'], rp_on); c.put(t.cap_at + R.OFF['rp_every_us'], every_us)
        for now in range(1_000_000, 3_000_000, 20_000):
            ControlTests.step(self, t, now)
        reps = []
        for x in c.xfers:
            sp = self.rx.Splitter(lambda h, p: reps.append((h, R.parse_cap(p))))
            sp.feed(x['data'])
        return t, reps

    def test_one_report_per_event_with_the_matching_state(self):
        t, reps = self.run_take()
        evs = [(h['frame_no'], c['ctl']) for h, c in reps]
        self.assertEqual(evs, [(1, R.CTL['armed']), (2, R.CTL['rec']), (3, R.CTL['done'])])
        h, last = reps[-1]
        self.assertEqual((h['source'], h['fmt'], h['w'], last['magic'], last['version']),
                         ('report', 'report', R.CAP_VERSION, R.CAP_MAGIC, R.CAP_VERSION))
        self.assertEqual((last['n_press'], last['rs_started'], last['rs_saved']), (2, 1, 1))
        self.assertEqual(t.cap()['rp_n_sent'], 3)

    def test_heartbeat_interval(self):
        t, reps = self.run_take(rp_on=0, every_us=500_000)
        beats = [h for h, _ in reps if h['frame_no'] == 7]
        self.assertEqual(len(beats), 4)                     # 2 s of steps, one per 0.5 s
        self.assertTrue(all(b['frame_no'] == 7 for b, _ in reps))

    def test_off_pushes_nothing(self):
        t, reps = self.run_take(rp_on=0, every_us=0)
        self.assertEqual(reps, [])


class CheckpointTests(unittest.TestCase):
    """The control task's own checkpoints before REC: standby -> half-press AF -> magnify -> settle (layout 6)."""
    def take(self, standby=200, focus=500, mag=400, steps=(1_000_000, 4_000_000)):
        t = ControlTests.setup(self, start_ms=0, rec_ms=1000)
        c = t.cam
        for k, v in (('cp_standby_ms', standby), ('cp_focus_ms', focus), ('cp_mag_ms', mag)):
            c.put(t.cap_at + R.OFF[k], v)
        for now in range(steps[0], steps[1], 20_000):
            ControlTests.step(self, t, now)
        return t

    def test_phases_in_order_and_on_time(self):
        t = self.take()
        keys = [(l, now) for l, now in t.cam.shell if l.startswith('key')]
        self.assertEqual([l for l, _ in keys][:6], ['key S1ON', 'key S1OFF', 'key OKON', 'key OKOFF', 'key OKON', 'key OKOFF'])
        tm = {}
        for l, now in keys[:6]:
            tm.setdefault(l, []).append(now)
        arm = 1_000_000
        self.assertGreaterEqual(tm['key S1ON'][0] - arm, 200_000)
        self.assertGreaterEqual(tm['key S1OFF'][0] - tm['key S1ON'][0], 500_000)
        self.assertGreaterEqual(tm['key OKON'][1] - tm['key OKON'][0], 400_000)
        first_rec = next(now for l, now in t.cam.shell if l == 'recstate ena')
        self.assertGreaterEqual(first_rec - tm['key OKON'][1], 600_000)
        self.assertEqual(t.cap()['ctl'], R.CTL['done'])

    def test_no_checkpoints_is_the_old_take(self):
        t = self.take(0, 0, 0)
        self.assertFalse(any(l.startswith('key S1') or l.startswith('key OK') for l, _ in t.cam.shell))
        self.assertEqual(t.cap()['ctl'], R.CTL['done'])

    def test_lv_carries_the_phase_flags(self):
        t = LvTests.setup(self, push=False)
        c = t.cam
        c.put(PX_DMA_TBL + 12, 0); c.put(PX_CPU_TBL + 12, 0x40000000); c.put(PX_DEAF, 0)
        c.mu.mem_map(LV_SLOT[0], 0x1000000)
        c.put(t.cap_at + R.OFF['lv_push'], 1)
        sys.path.insert(0, str(HERE.parent / 'host'))
        import push_rx
        flags = []
        for phase, now in ((1, 1_000_000), (2, 2_000_000), (4, 3_000_000)):
            c.put(t.cap_at + R.OFF['cp_phase'], phase)
            LvTests.step(self, t, now)
            h = push_rx.parse_header(c.xfers[-1]['data'][:256])
            flags.append(h['flags'] & 6)
        self.assertEqual(flags, [2, 4, 0])


class CtlOnlyTests(unittest.TestCase):
    """ISPC.BIN: the control task alone (RESEARCH_PLAN §7 step 1)."""
    def test_loads_without_touching_the_writer(self):
        t = Take(0, frames=1, ctl_only=True)
        c = t.cam
        for a, h in IB.SITES.items():
            self.assertEqual(bytes(c.mu.mem_read(a, 8)).hex(), h, f'0x{a:08X} hooked by the control-only build')
        self.assertEqual(t.cap()['magic'], R.CAP_MAGIC)
        c.power_off()

    def test_runs_the_firmware_script(self):
        t = ControlTests.setup(self, ctl_only=True)
        ControlTests.step(self, t, 1_000_000); ControlTests.step(self, t, 2_000_000)
        ControlTests.step(self, t, 2_020_000)
        cap = ControlTests.step(self, t, 9_000_000)
        self.assertEqual(cap['ctl'], R.CTL['done'])
        self.assertEqual([l for l, _ in t.cam.shell], START + STOP + ['recstate disa'])


USBFIX_AT, USBFIX_WORD = 0xC0032808, 0xE3A03B01


class UsbReconnectTests(unittest.TestCase):
    """Once after boot, with the dev shell's USBFIX in place: "usb off", 700 ms, "usb on" -- so the host
    enumerates EP83 as bulk 1024 again and nobody replugs the cable at night."""
    def step(self, t, now):
        return ControlTests.step(self, t, now)

    def lines(self, t):
        return [l for l, _ in t.cam.shell]

    def test_off_then_on_once_when_usbfix_is_in(self):
        t = Take(0, frames=1)
        t.cam.put(USBFIX_AT, USBFIX_WORD)
        self.step(t, 1_000_000)                                       # first step: the clock starts
        self.step(t, 3_900_000)
        self.assertEqual(self.lines(t), [], 'reconnected before every sup had loaded')
        cap = self.step(t, 4_100_000)
        self.assertEqual((self.lines(t), cap['ur_state']), (['usb off'], 1))
        self.step(t, 4_500_000)
        self.assertEqual(self.lines(t), ['usb off'])
        cap = self.step(t, 4_900_000)
        self.assertEqual((self.lines(t), cap['ur_state']), (['usb off', 'usb on'], 2))
        for now in (9_000_000, 90_000_000):
            self.step(t, now)
        self.assertEqual(self.lines(t), ['usb off', 'usb on'], 'reconnected twice')

    def test_a_host_arm_after_the_reconnect_does_not_reconnect_again(self):
        t = Take(0, frames=1)
        t.cam.put(USBFIX_AT, USBFIX_WORD)
        for now in (1_000_000, 4_100_000, 4_900_000):
            self.step(t, now)
        t.arm('discard')                                               # the host's arm/disarm image
        for now in (9_000_000, 20_000_000):
            self.step(t, now)
        self.assertEqual(self.lines(t), ['usb off', 'usb on'])

    def test_release_shell_never_reconnects(self):
        t = Take(0, frames=1)                                          # stock word at 0xC0032808
        for now in (1_000_000, 5_000_000, 32_000_000, 90_000_000):
            cap = self.step(t, now)
        self.assertEqual((self.lines(t), cap['ur_state']), ([], 3))

    def test_waits_while_a_take_is_armed(self):
        t = ControlTests.setup(self, start_ms=60_000)
        t.cam.put(USBFIX_AT, USBFIX_WORD)
        for now in (1_000_000, 5_000_000, 9_000_000):
            self.step(t, now)
        self.assertNotIn('usb off', self.lines(t))


class MutationTests(unittest.TestCase):
    """Each mutant must make a SinkTests check fail."""
    def failing(self, define, test, cls=None):
        global _BUILDS
        saved = build_sup
        try:
            globals()['build_sup'] = lambda defines=(): saved(tuple(defines) + (define,))
            with open('/dev/null', 'w') as null:
                r = unittest.TextTestRunner(stream=null).run((cls or SinkTests)(test))
            return not r.wasSuccessful()
        finally:
            globals()['build_sup'] = saved

    def test_always_sd_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_ALWAYS_SD', 'test_capture_rebuilds_the_disk_and_writes_nothing'))

    def test_no_uncache_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_NO_UNCACHE', 'test_frames_at_the_cached_alias_are_read_uncached'))

    def test_no_room_check_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_NO_ROOM', 'test_full_sink_keeps_whole_records_and_the_take_going'))

    def test_address_wrap_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_WRAP', 'test_lent_memory_must_be_the_uncached_alias'))

    def test_keep_all_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_KEEP_ALL', 'test_first_k_then_nothing', KeepTests))

    def test_no_stop_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_NO_STOP', 'test_the_firmware_script_on_time', ControlTests))

    def test_no_start_check_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_NO_START_CHECK', 'test_no_start_no_second_press', ControlTests))

    def test_end_on_timeout_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_END_ON_TIMEOUT', 'test_mode1_timeout_leaves_the_transfer_armed', PushEngineTests))

    def test_no_s1off_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_NO_S1OFF', 'test_phases_in_order_and_on_time', CheckpointTests))

    def test_no_crc_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_NO_CRC', 'test_one_image_parses_and_matches', PushEngineTests))

    def test_cd_all_takes_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_CD_ALL', 'test_pushes_only_the_newest_take_whole', CdngTests))

    def test_no_stop_report_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_NO_STOP_REPORT', 'test_one_report_per_event_with_the_matching_state', ReportTests))

    def test_lv_after_the_take_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_LV_ALWAYS', 'test_a_finished_take_samples_nothing', LvTests))

    def test_no_lost_check_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_NO_LOST_CHECK',
                                     'test_a_reconfigured_endpoint_drops_the_chain_instead_of_skipping_forever',
                                     PushEngineTests))

    def test_ur_without_the_fix_check_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_UR_NO_FIX_CHECK', 'test_release_shell_never_reconnects', UsbReconnectTests))

    def test_start_blocking_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_START_BLOCKS', 'test_lv_flows_while_the_start_is_pending', BurstTests))

    def test_start_without_timeout_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_START_NO_TIMEOUT', 'test_no_start_no_second_press', ControlTests))

    def test_cancel_during_the_start_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_CANCEL_STARTING', 'test_a_cancel_cannot_abandon_a_pressed_start', ControlTests))

    def test_burst_without_dedupe_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_BU_NO_DEDUPE', 'test_every_new_slot_once_with_its_watch', BurstTests))

    def test_burst_without_end_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_BU_NO_END', 'test_window_ends_lv_burst_ms_after_the_start', BurstTests))

    def test_burst_header_without_tick_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_BU_AUX', 'test_every_new_slot_once_with_its_watch', BurstTests))

    def test_burst_without_watch_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_BU_NO_WT', 'test_every_new_slot_once_with_its_watch', BurstTests))

    def test_burst_when_off_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_BU_ALWAYS', 'test_burst_off_is_the_cadence', BurstTests))

    def test_lv_current_slot_is_caught(self):
        self.assertTrue(self.failing('IX_MUTANT_LV_CURRENT', 'test_pushes_the_slot_before_the_current_one', LvTests))


if __name__ == '__main__':
    unittest.main()
