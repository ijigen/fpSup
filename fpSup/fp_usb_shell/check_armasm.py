#!/usr/bin/env python3
"""What fpSup/fp_usb_shell/armasm.py actually accepts, checked by assembling.

    python3 -B check_armasm.py

Three findings, each pinned by an encoding here:

1. `ldr reg, =constant` works, `ldr reg, =label` does not.  clang emits no
   relocation for the constant form — it inlines `mov`/`movw`/`movt` or fills a
   pool word itself — so nothing here has to touch it.  The label form leaves an
   R_ARM_ABS32 (type 2) the module refuses, so it fails loudly, not silently.
2. `movw reg, #imm` is encoded correctly, including with the canonical imm16
   split (the top nibble in bits 19:16, the low twelve bits in bits 11:0), which
   reads as a wrong immediate until you decode it.  Earlier attempts appeared to
   fail because a wrong offset or a pool value was mistaken for a bad immediate.
3. What is genuinely missing: a bare `.word` holding a symbol is an R_ARM_ABS32
   this module has no case for.  Since every constant it does support is an
   inline immediate or a filled pool word, this is not hit by ordinary templates
   — but a data table of addresses inside .text cannot be built.
"""
import struct
import subprocess
import sys
import tempfile
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from armasm import assemble  # noqa: E402

CFLAGS = ['clang', '-target', 'armv7-none-eabi', '-c']


def asm(src):
    with tempfile.TemporaryDirectory() as t:
        path = pathlib.Path(t) / 'a.S'
        path.write_text('.syntax unified\n.arm\n.text\n.globl f\nf:\n' + src)
        return assemble(path)


def words(code):
    return list(struct.unpack(f'<{len(code) // 4}I', code))


def check_ldr_constant_is_inlined():
    """`ldr r1, =0x12345` becomes a pool load the assembler fills itself."""
    w = words(asm('    ldr r1, =0x12345\n    bx lr\n'))
    assert w[0] == 0xE59F1000, f'{w[0]:08X}: not a pc-relative ldr'
    assert w[2] == 0x00012345, f'{w[2]:08X}: the pool was not filled'


def check_ldr_label_is_refused_loudly():
    """`ldr r1, =label` leaves R_ARM_ABS32, which raises instead of shipping 0."""
    try:
        asm('    ldr r1, =tail\n    bx lr\ntail:\n    bx lr\n')
    except SystemExit as e:
        assert 'unsupported relocation 2' in str(e), e
        return
    raise AssertionError('ldr reg, =label assembled silently')


def _mov16(rd, imm16, top):
    """The canonical halfword move: imm4 in bits 19:16, imm12 in bits 11:0."""
    return (0xE3400000 if top else 0xE3000000) | (rd << 12) \
        | (((imm16 >> 12) & 0xF) << 16) | (imm16 & 0xFFF)


def check_movw_and_movt_immediates():
    for rd, imm in ((1, 0x17D4), (2, 0x8000), (3, 0x0FFF), (5, 0xFFFF), (6, 0x0000)):
        for top in (False, True):
            mnem = 'movt' if top else 'movw'
            want = _mov16(rd, imm, top)
            got = words(asm(f'    {mnem} r{rd}, #{imm:#x}\n    bx lr\n'))[0]
            assert got == want, f'{mnem} r{rd}, #{imm:#x}: {got:08X} != {want:08X}'


def check_manual_literal_pool():
    """A hand-written `.word` pool is the supported way to hold an address."""
    w = words(asm('    ldr r1, k32\n    ldr r2, kaddr\n    bx lr\n'
                  '    .align 2\nk32:\n    .word 0x20\nkaddr:\n    .word 0xC03817D4\n'))
    assert w[:3] == [0xE59F1004, 0xE59F2004, 0xE12FFF1E], [f'{x:08X}' for x in w[:3]]
    assert w[3] == 0x20 and w[4] == 0xC03817D4


def check_symbol_word_is_the_gap():
    """Pinning the gap: `.word <symbol>` is the one thing that cannot be built."""
    with tempfile.TemporaryDirectory() as t:
        src = pathlib.Path(t) / 'a.S'
        src.write_text('.syntax unified\n.arm\n.text\nf:\n    .word tail\ntail:\n    bx lr\n')
        obj = pathlib.Path(t) / 'a.o'
        subprocess.run(CFLAGS + [str(src), '-o', str(obj)], check=True)
        relocs = subprocess.run(['readelf', '-r', str(obj)], capture_output=True, text=True).stdout
    assert 'R_ARM_ABS32' in relocs, relocs
    try:
        asm('    .word tail\ntail:\n    bx lr\n')
    except SystemExit as e:
        assert 'unsupported relocation 2' in str(e), e
        return
    raise AssertionError('.word <symbol> assembled silently')


def main():
    checks = [check_ldr_constant_is_inlined, check_ldr_label_is_refused_loudly,
              check_movw_and_movt_immediates, check_manual_literal_pool,
              check_symbol_word_is_the_gap]
    for c in checks:
        c()
        print(f'ok  {c.__name__}')
    print(f'\n{len(checks)} checks')


if __name__ == '__main__':
    main()
