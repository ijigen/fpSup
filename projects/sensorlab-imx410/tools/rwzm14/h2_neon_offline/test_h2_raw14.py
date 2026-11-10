#!/usr/bin/env python3
"""Execute assembled ARMv7 bytes, not a host replacement, under Unicorn.

No ROM image, camera interaction, installation, or benchmark is involved.
"""
import hashlib
import itertools
import json
import pathlib
import random
import struct
import sys

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn import arm_const as A

HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / 'fpSup' / 'fp_usb_shell'))
from armasm import assemble

CODE = 0x10000000
STOP = 0x10010000
SRC = 0x20000000
DST = 0x30000000
SP = 0x40001000
REGION = 0x20000
GUARD = 64
SEED = 0x141402
RNG = random.Random(SEED)


def reference(samples):
    return [((samples[i] + samples[i + 2] + 1) >> 1)
            for group in range(0, len(samples), 4)
            for i in (group, group + 1)]


class Rig:
    def __init__(self, code):
        self.mu = m = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        m.ctl_set_cpu_model(A.UC_CPU_ARM_CORTEX_A7)
        for base, size in ((CODE, 0x20000), (SRC, REGION),
                           (DST, REGION), (SP - 0x1000, 0x2000)):
            m.mem_map(base, size)
        m.mem_write(CODE, code)
        m.reg_write(A.UC_ARM_REG_C1_C0_2, 0x00f00000)
        m.reg_write(A.UC_ARM_REG_FPEXC, 0x40000000)
        self.code_end = CODE + len(code)
        self.count = 0
        self.reads = []
        self.writes = []
        m.hook_add(UC_HOOK_CODE, self.on_code)
        m.hook_add(UC_HOOK_MEM_READ, self.on_read)
        m.hook_add(UC_HOOK_MEM_WRITE, self.on_write)

    def on_code(self, mu, addr, size, _):
        assert CODE <= addr < self.code_end, ('execution escaped', hex(addr))
        self.count += 1

    def on_read(self, mu, access, addr, size, value, _):
        self.reads.append((addr, size))

    def on_write(self, mu, access, addr, size, value, _):
        self.writes.append((addr, size))

    def call(self, samples, width=None, src_align=0, dst_align=0):
        width = len(samples) if width is None else width
        src_bytes = struct.pack('<%dH' % len(samples), *samples)
        src_base = SRC + GUARD + src_align
        dst_base = DST + GUARD + dst_align
        dst_len = max(width, 0)  # width/2 output samples * 2 bytes
        src_whole = b'\xa5' * (GUARD + src_align) + src_bytes + b'\x5a' * GUARD
        dst_whole = b'\xcc' * (GUARD + dst_align + dst_len + GUARD)
        m = self.mu
        m.mem_write(SRC, src_whole)
        m.mem_write(DST, dst_whole)
        m.reg_write(A.UC_ARM_REG_R0, dst_base)
        m.reg_write(A.UC_ARM_REG_R1, src_base)
        m.reg_write(A.UC_ARM_REG_R2, width)
        saved = {}
        for r in range(4, 12):
            reg = A.UC_ARM_REG_R4 + r - 4
            saved[reg] = RNG.getrandbits(32)
        saved[A.UC_ARM_REG_SP] = SP
        saved[A.UC_ARM_REG_LR] = STOP
        for d in range(4, 32):
            saved[A.UC_ARM_REG_D0 + d] = RNG.getrandbits(64)
        saved[A.UC_ARM_REG_FPSCR] = 0
        for reg, val in saved.items():
            m.reg_write(reg, val)
        self.count, self.reads, self.writes = 0, [], []
        m.emu_start(CODE, STOP, count=100000)
        assert m.reg_read(A.UC_ARM_REG_PC) == STOP, 'did not return'
        for reg, val in saved.items():
            assert m.reg_read(reg) == val, ('register clobber', reg)
        assert bytes(m.mem_read(SRC, len(src_whole))) == src_whole, 'source modified'
        actual = bytes(m.mem_read(DST, len(dst_whole)))
        if width % 16:
            assert m.reg_read(A.UC_ARM_REG_R0) == 0xffffffff
            assert actual == dst_whole, 'invalid width wrote output'
            assert not self.reads and not self.writes
            assert self.count == 4
        else:
            assert m.reg_read(A.UC_ARM_REG_R0) == 0
            out = reference(samples)
            assert all(0 <= x <= 16383 for x in out), 'RAW14 range loss'
            expected = (b'\xcc' * (GUARD + dst_align)
                        + struct.pack('<%dH' % len(out), *out) + b'\xcc' * GUARD)
            assert actual == expected, 'output/guard mismatch'
            assert self.count == 6 + 5 * (width // 16)
            assert sum(size for addr, size in self.reads) == width * 2
            assert sum(size for addr, size in self.writes) == width
            for addr, size in self.reads:
                assert src_base <= addr and addr + size <= src_base + len(src_bytes)
            for addr, size in self.writes:
                assert dst_base <= addr and addr + size <= dst_base + dst_len
        return self.count


def main():
    code = assemble(HERE / 'h2_raw14.S')
    (HERE / 'h2_raw14.bin').write_bytes(code)
    insns = list(Cs(CS_ARCH_ARM, CS_MODE_ARM).disasm(code, CODE))
    disasm = '\n'.join(f'{i.address:08x}  {i.bytes.hex():8}  {i.mnemonic} {i.op_str}'
                       for i in insns)
    (HERE / 'h2_raw14.disassembly.txt').write_text(disasm + '\n')
    assert len(insns) == 13
    assert [i.mnemonic for i in insns[4:9]] == [
        'vld2.32', 'vrhadd.u16', 'vst1.16', 'subs', 'bne']
    # The exact compiled sequence is checked, not merely the source text.
    assert insns[4].op_str == '{d0, d1, d2, d3}, [r1]!'
    assert insns[5].op_str == 'q0, q0, q1'
    assert insns[6].op_str == '{d0, d1}, [r0]!'
    rig = Rig(code)
    counts = {}
    cases = 0
    edge = [0, 1, 2, 3, 7, 8, 15, 255, 256, 4095, 4096, 8191, 8192, 16382, 16383]
    for a, b in itertools.product(edge, repeat=2):
        # Exercise even and odd sums with unrelated adjacent CFA channels.
        rig.call([a, 16383-b, b, 16383-a] * 4)
        cases += 1
    for width in (0, 16, 32, 48, 80, 608, 3840, 6000, 6016):
        counts[str(width)] = rig.call([RNG.randrange(16384) for _ in range(width)])
        cases += 1
    for _ in range(256):
        width = RNG.randrange(0, 65) * 16
        rig.call([RNG.randrange(16384) for _ in range(width)],
                 src_align=RNG.choice((0, 2, 4, 6)),
                 dst_align=RNG.choice((0, 2, 4, 6)))
        cases += 1
    for width in (1, 2, 4, 8, 15, 17, 31, 33):
        rig.call([1234] * width)
        cases += 1
    # Distinct row/channel levels prove the pair mapping for all four CFA phases.
    # This intentionally calls once per row: no image-stride wrapper is claimed.
    cfas = ('RGGB', 'GRBG', 'GBRG', 'BGGR')
    channel = {'R': 1000, 'G': 8000, 'B': 15000}
    for cfa in cfas:
        for row in range(7):
            width = 80
            samples = [channel[cfa[(row % 2) * 2 + (x % 2)]] + row * 20 + x // 2
                       for x in range(width)]
            rig.call(samples)
            cases += 1
    # Bounded mutation: unrounded average must fail for odd sums.
    mutant_path = HERE / 'h2_raw14_mutant.S'
    mutant_path.write_text((HERE / 'h2_raw14.S').read_text().replace('vrhadd.u16', 'vhadd.u16'))
    mutation_caught = False
    try:
        Rig(assemble(mutant_path)).call([0, 0, 1, 1] * 4)
    except AssertionError as exc:
        assert str(exc) == 'output/guard mismatch', str(exc)
        mutation_caught = True
    assert mutation_caught
    result = {
        'status': 'PASS', 'cases': cases, 'cfa_phases': list(cfas),
        'seed': SEED, 'raw_binary_bytes': len(code),
        'sha256': hashlib.sha256(code).hexdigest(),
        'loop_instructions_per_16_input_samples': 5,
        'vector_instructions_per_16_input_samples': 3,
        'per_nonzero_valid_row_instruction_formula': '6 + 5 * (width / 16)',
        'instruction_counts_by_input_width': counts,
        'memory_read_bytes_per_16_input_samples': 32,
        'memory_write_bytes_per_16_input_samples': 16,
        'only_neon_registers_used': 'd0-d3 / q0-q1',
        'preservation': 'r4-r11, sp, lr, d4-d31, FPSCR verified',
        'unrounded_average_mutation_detected': mutation_caught,
        'limitations': [
            'offline ARM execution only; no real device throughput measurements',
            'right-justified u16 RAW14 only, not packed RAW14',
            'input width multiple of 16; nonmultiples return -1 without memory access',
            'disjoint, 2-byte-aligned buffers; no image-stride wrapper',
            'input samples must be in 0..16383; no mask or format conversion',
            'CFA phase and sensor vertical mode must be established by caller',
            'no hook, DMA, cache-coherency, scheduling, or recorder integration',
        ],
    }
    (HERE / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
