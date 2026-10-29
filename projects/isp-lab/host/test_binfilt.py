"""binfilt.S under unicorn: the selector fix-up and the two kernels, against ogc_binfilt.c's rules; mutants."""
import pathlib, struct, sys, unittest
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / 'fpSup' / 'fp_usb_shell'))
import armasm                                                        # noqa: E402

SRC = HERE / 'asm' / 'binfilt.S'
BASE, DATA, STACK, STOP = 0x45000000, 0x46000000, 0x47000000, 0x48000000
POP_BX = struct.pack('<2I', 0xE8BD00F0, 0xE12FFF1E)                  # pop {r4-r7}; bx lr  (the selector's tail)


def cfg_of(bh, bv, kh, kv, mode):
    return 0x800 | (0x200 if bh == 3 else 0) | (0x400 if bv == 3 else 0) | (mode << 8) | kh | (kv << 4)



class BinFilt(unittest.TestCase):
    src = SRC

    def _path(self, cfg, inb=(3, 1), mux=4, h24=3):
        code = bytearray(armasm.assemble(self.src))
        sym = armasm.symbols(self.src)
        struct.pack_into('<I', code, sym['cfg'], cfg)
        u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for a in (BASE, DATA, STACK, STOP, 0xC0325000):
            u.mem_map(a, 0x10000)
        u.mem_write(BASE, bytes(code))
        u.mem_write(0xC0325230, POP_BX)
        inp, out = DATA, DATA + 0x100
        u.mem_write(inp + 0x10, struct.pack('<2I', *inb))
        u.mem_write(out + 8, struct.pack('<I', mux))
        u.mem_write(out + 0x24, struct.pack('<I', h24))
        u.mem_write(out + 0x48, struct.pack('<I', 7))
        u.reg_write(UC_ARM_REG_R0, 0x1234)
        u.reg_write(UC_ARM_REG_R1, inp)
        u.reg_write(UC_ARM_REG_R2, out)
        u.reg_write(UC_ARM_REG_SP, STACK + 0x8000)
        u.reg_write(UC_ARM_REG_LR, STOP)
        u.emu_start(BASE + sym['path'], STOP, count=2000)
        rd = lambda a: struct.unpack('<I', u.mem_read(a, 4))[0]
        return rd(out + 0x24), rd(out + 0x48), u.reg_read(UC_ARM_REG_R0), u.reg_read(UC_ARM_REG_SP)

    def test_branch_c_second_horizontal_third_removed(self):
        self.assertEqual(self._path(cfg_of(3, 1, 1, 0, 1)), (1, 1, 0x1234, STACK + 0x8000))

    def test_not_c_or_not_ours_untouched(self):
        self.assertEqual(self._path(cfg_of(3, 1, 1, 0, 0), mux=3)[:2], (3, 0))   # not C: mode only
        self.assertEqual(self._path(cfg_of(3, 1, 1, 0, 1), inb=(1, 1))[:2], (3, 7))  # another path's bins
        self.assertEqual(self._path(0)[:2], (3, 7))                                  # no recipe
        self.assertEqual(self._path(cfg_of(1, 1, 0, 0, 1))[:2], (3, 7))            # recipe without a bin

    def _kernel(self, entry, cfg):
        code = bytearray(armasm.assemble(self.src))
        sym = armasm.symbols(self.src)
        struct.pack_into('<I', code, sym['cfg'], cfg)
        u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for a in (BASE, STACK, STOP, 0xC032D000):
            u.mem_map(a, 0x10000)
        u.mem_write(BASE, bytes(code))
        for a in (0xC032DDF0, 0xC032DE70):
            u.mem_write(a, struct.pack('<I', 0xE12FFF1E))
        sp = STACK + 0x8000
        u.mem_write(sp, bytes(range(4)) + bytes(0x7C))
        u.reg_write(UC_ARM_REG_SP, sp)
        u.reg_write(UC_ARM_REG_LR, STOP)
        u.emu_start(BASE + sym[entry], STOP, count=2000)
        rec = bytes(u.mem_read(sp + 8, 0x30))            # the record: r1 = the caller's sp + 8
        return rec, u.reg_read(UC_ARM_REG_R0), u.reg_read(UC_ARM_REG_R1) - sp, u.reg_read(UC_ARM_REG_SP) - sp

    def test_kernels_as_ogc(self):
        for entry, r0 in (('k1', 2), ('k2', 3)):
            for kh in range(6):
                for kv in range(6):
                    rec, a0, a1, dsp = self._kernel(entry, cfg_of(3, 3, kh, kv, 0))
                    s = (21, 16, 11, 8, 4, 0)[kh]
                    self.assertEqual(rec[0x29:0x2C], bytes((s, 64 - 2 * s, s)))
                    for i in range(4):
                        self.assertEqual(rec[0x1C + 3 * i:0x1F + 3 * i], bytes((s, 64 - 2 * s, s)))
                    v = (1365, 1024, 683, 512, 256, 0)[kv]
                    for i in range(3):
                        self.assertEqual(struct.unpack_from('<3H', rec, 8 + 6 * i), (v, 4096 - 2 * v, v))
                    self.assertEqual((a0, a1, dsp), (r0, 8, 0))             # the replayed ldrb / add, sp intact

    def test_kernel_axes_independent_and_off(self):
        rec, *_ = self._kernel('k1', cfg_of(3, 1, 0, 0, 0))
        self.assertEqual(rec[8:26], bytes(18))                              # V untouched
        rec, *_ = self._kernel('k1', 0)
        self.assertEqual(rec, bytes(0x30))


MUTANTS = {
    'branch C fix missing': ('    moveq   ip, #1\n    streq   ip, [r2, #0x24]\n', ''),
    'wrong H kernel table': ('htab:       .byte 21, 16', 'htab:       .byte 20, 16'),
    'V middle not 4096-2s': ('    rsb     r2, r0, #4096\n    sub     r2, r2, r0\n', '    rsb     r2, r0, #4096\n'),
    'k2 replays k1 byte': ('    ldrb    r0, [sp, #3]', '    ldrb    r0, [sp, #2]'),
    'ignores the in bins': ('    cmp     ip, r5\n    bne     9f\n    tst     r4, #0x400', '    tst     r4, #0x400'),
}


class Mutation(unittest.TestCase):
    def test_every_mutant_is_caught(self):
        import io, tempfile
        src = SRC.read_text()
        for name, (old, new) in MUTANTS.items():
            self.assertEqual(src.count(old), 1, name)
            with tempfile.TemporaryDirectory() as t:
                p = pathlib.Path(t) / 'm.S'
                p.write_text(src.replace(old, new))
                cls = type('M', (BinFilt,), {'src': p})
                suite = unittest.TestLoader().loadTestsFromTestCase(cls)
                r = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
                self.assertFalse(r.wasSuccessful(), f'mutant survived: {name}')


if __name__ == '__main__':
    unittest.main()
