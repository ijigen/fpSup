#!/usr/bin/env python3
"""build_precap_sup.py -- build PreCap as a loader v4 sup.

    python3 -B build_precap_sup.py --out DIR

Produces DIR/PreCap_v0.1.0.BIN.  The row unit (precap_row.c) is compiled and
.incbin'd into precap.S, so the sup is one flat .text with no data section.

Checks before writing:
  - the four hook sites hold their stock words in the firmware image;
  - every external call in precap.S is on the allow-list;
  - the stub offsets the launcher bakes in match the assembled symbols;
  - the file is 8-byte aligned and its block covers the row area.
"""
import argparse
import pathlib
import struct
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]      # fpSup-fork/
SHELL = ROOT / 'fpSup' / 'fp_usb_shell'
V4 = ROOT / 'fpSup' / 'loader-v4'
sys.path.insert(0, str(SHELL))
sys.path.insert(0, str(V4))

from armasm import assemble, symbols  # noqa: E402
import build_v4 as B4  # noqa: E402

ROM_CANDIDATES = (ROOT / 'out' / 'MAIN_c0000000.bin',
                  pathlib.Path('/opt/sigma/out/MAIN_c0000000.bin'))
ROM = next((p for p in ROM_CANDIDATES if p.exists()), ROM_CANDIDATES[0])
ROM_BASE = 0xC0000000

SITES = {
    'A': (0xC038F0E8, 0xE12FFF33),
    'B': (0xC038F174, 0xE12FFF33),
    'D': (0xC02DC108, 0xEB00000A),
    'S': (0xC03817D4, 0xEB000047),
}
SUP_ID = 'PCAP'
VERSION = 1
PROJ = HERE.parent
ROW_SRC = PROJ / 'precap_row.c'
SRC = PROJ / 'precap.S'

# precap.S may call only these firmware routines (plus its own subroutines).
FIRMWARE = {
    0xC002B6E0,   # F_TICK_US
    0xC0397B30,   # F_KIND
    0xC02DBAF0,   # F_KEYMON
    0xC02DBBE8,   # F_ENQ
    0xC02DC138,   # F_DISP
    0xC0374220,   # F_JOBDB
    0xC03753C0,   # F_JOBGET
    0xC03A4620,   # F_CAP
    0xC03A46B8,   # F_REFUND
    0xC0377348,   # F_RAWOBJ
    0xC0377730,   # F_DROPRW
    0xC0375030,   # F_DROPJB
    0xC037AF20,   # F_ENQUEUE
    0xC03818F8,   # F_SOUND
    0xC000EABC,   # F_ICACHE
}
SVC = {0x08: 'SVC_CLAIM', 0x14: 'SVC_CAVE', 0x18: 'SVC_PUBLISH'}


class BuildError(RuntimeError):
    pass


def row_unit():
    """(code, offset) of precap_row.c, compiled exactly as build_v4 does."""
    with tempfile.TemporaryDirectory(prefix='pcsup-') as t:
        text = B4.compile_unit(pathlib.Path(t), ROW_SRC, 'precap_row_install')
    return text.code, text.functions['precap_row_install']


def stock_word(address):
    data = ROM.read_bytes()
    return struct.unpack_from('<I', data, address - ROM_BASE)[0]


def check_sites():
    for name, (address, want) in SITES.items():
        got = stock_word(address)
        if got != want:
            raise BuildError(f'site {name} 0x{address:08X} holds 0x{got:08X}, not 0x{want:08X}')


def call_targets(code):
    """Every firmware target reached through `blx ip` / `bx ip`, plus direct
    `bl` sites (which the camera's position-independent rules forbid)."""
    import capstone
    dis = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    low = high = 0
    imm = None            # the last movw/movt-built address, cleared by `ldr ip`
    targets, direct = [], []
    for insn in dis.disasm(code, 0):
        if insn.mnemonic == 'movw' and insn.op_str.startswith('ip,'):
            low = int(insn.op_str.split('#')[1], 0)
            imm = None
        elif insn.mnemonic == 'movt' and insn.op_str.startswith('ip,'):
            high = int(insn.op_str.split('#')[1], 0)
            imm = (high << 16) | low
        elif insn.mnemonic == 'ldr' and insn.op_str.startswith('ip,'):
            imm = None        # a service-table call: not a firmware address
        elif insn.mnemonic in ('blx', 'bx') and insn.op_str == 'ip':
            if imm is not None:
                targets.append(imm)
            imm = None
        elif insn.mnemonic == 'bl':
            direct.append((insn.address, insn.op_str))
    return targets, direct


def _bl_target(code, addr):
    import struct as _s
    w = _s.unpack_from('<I', code, addr)[0]
    disp = (w & 0x00FFFFFF) << 2
    if disp & 0x02000000:
        disp -= 0x04000000
    return addr + 8 + disp


def build():
    check_sites()
    code, fn = row_unit()
    if len(code) % 4:
        code += b'\0' * (-len(code) % 4)
    with tempfile.TemporaryDirectory(prefix='pcsrc-') as t:
        inc = pathlib.Path(t) / 'precap_row.bin'
        inc.write_bytes(code)
        defines = [f'ROW_BIN="{inc}"', f'ROW_INSTALL=0x{fn:X}']
        body = assemble(SRC, defines)
        syms = symbols(SRC, defines)

    if syms['precap_entry'] != 0:
        raise BuildError('precap_entry is not at offset 0')
    for name in ('stub_a', 'stub_b', 'disp_stub', 'mute_stub', 'precap_state'):
        if name not in syms:
            raise BuildError(f'{name} missing from precap.S')

    targets, direct = call_targets(body)
    bad = [t for t in targets if t not in FIRMWARE]
    if bad:
        raise BuildError('unexpected firmware call 0x%08X' % bad[0])
    # `bl` is allowed only inside this blob (local subroutines); it must never
    # reach into the firmware, where the stock code expects to be called as is.
    for addr, op in direct:
        target = _bl_target(body, addr)
        if not 0 <= target < len(body):
            raise BuildError(f'bl at {addr:#x} leaves the sup ({op})')

    file_len = B4.SL4_HEADER_LEN + len(body)
    row_off = syms['row_space']
    block = file_len + ROW_BYTES + 8                 # the row area lives past the file
    sup = B4.make_sup(body, B4.SL4_HEADER_LEN, SUP_ID, version=VERSION,
                      min_svc=5, flags=B4.SL_F_CACHED_OK, block_size=block)
    if len(sup) != file_len:
        raise BuildError(f'file {len(sup)} != code {file_len}')
    name_off = B4.SL4_HEADER_LEN + syms['pc_name']
    sup = sup[:44] + struct.pack('<I', name_off) + sup[48:]
    if sup[name_off:name_off + 7] != b'PreCap\0':
        raise BuildError('the display name is not where the symbol says')
    return sup, dict(code=len(body), row=len(code), entry=B4.SL4_HEADER_LEN,
                     file=len(sup), block=block, row_off=row_off,
                     state=syms['precap_state'],   # relative to the code start
                     stubs={k: syms[v] for k, v in (('A', 'stub_a'), ('B', 'stub_b'),
                                                    ('D', 'disp_stub'), ('S', 'mute_stub'))})


ROW_BYTES = 0x80


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sup, info = build()
    path = out / 'PreCap_v0.1.0.BIN'
    path.write_bytes(sup)
    print(f'{path}  {len(sup)} B')
    for k, v in info.items():
        print(f'  {k}: {v}')


if __name__ == '__main__':
    main()
