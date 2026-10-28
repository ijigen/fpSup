#!/usr/bin/env python3
"""build_precap4.py -- build the pre-capture P4 card (AutoRun.txt + fpSup.BIN).

    python3 build_precap4.py --out DIR

P4 is P3 plus shutter mute: a fourth hook at the SRec task's shutter-sound
call (C03817D4, bl FUN_c03818f8) skips the sound while pre-capturing and
tail-calls it otherwise.  Offline; writes no card.
"""
import argparse
import hashlib
import pathlib
import struct
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_precap as p1  # noqa: E402
from armasm import assemble, symbols  # noqa: E402

ORIG_BLX_R3 = 0xE12FFF33
ORIG_BL_DISP = 0xEB00000A
ORIG_BL_SOUND = 0xEB000047
SITES = [
    (0xC038F0E8, ORIG_BLX_R3, 'HIGHCONT RAW event -> Yuv enqueue (main)'),
    (0xC038F174, ORIG_BLX_R3, 'HIGHCONT RAW event -> Yuv enqueue (sub-frame)'),
    (0xC02DC108, ORIG_BL_DISP, 'KeyMon thread -> key dispatch FUN_c02dc138'),
    (0xC03817D4, ORIG_BL_SOUND, 'SRec task -> shutter sound FUN_c03818f8'),
]
F_SOUND = 0xC03818F8
LAUNCH_CALLS = p1.LAUNCH_CALLS
RESIDENT_CALLS = {
    0xC002B6E0, 0xC0397B30, 0xC02DBAF0, 0xC02DBBE8, 0xC02DC138,
    0xC0374220, 0xC03753C0, 0xC03A4620, 0xC03A46B8,
    0xC0377348, 0xC0377730, 0xC0375030, 0xC037AF20,
    F_SOUND,
}
CAVE_ARENA, CAVE_ARENA_END = p1.CAVE_ARENA, p1.CAVE_ARENA_END
ALLOC = p1.ALLOC
MAXLEN = p1.MAXLEN
BANNER = 'fpSup-DEV-PreCap4!'
VENEERS = len(SITES)
P_KEEP, KEEP_N = 0x70, 4


def check_resident_calls(code):
    """Like p1.check_calls, but a `bl` whose target stays inside this blob is a
    local subroutine (drop / keep / lock), not a firmware call.  `bx ip` is a
    tail call and goes through the same allow-list as `blx ip`."""
    import capstone
    disassembler = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    low = high = None
    for insn in disassembler.disasm(code, 0):
        if insn.mnemonic == 'movw' and insn.op_str.startswith('ip,'):
            low = int(insn.op_str.split('#')[1], 0)
        elif insn.mnemonic == 'movt' and insn.op_str.startswith('ip,'):
            high = int(insn.op_str.split('#')[1], 0)
        elif insn.mnemonic in ('blx', 'bx') and insn.op_str == 'ip':
            target = (high << 16) | low
            if target not in RESIDENT_CALLS:
                raise SystemExit(f'resident calls 0x{target:08X}, not an allowed routine')
        elif insn.mnemonic == 'bl':
            target = int(insn.op_str.split('#')[1], 0)
            if not 0 <= target < len(code):
                raise SystemExit(f'resident has a bl out of the blob at {insn.address:#x}')


def hook_sites():
    out = []
    for site, expect, why in SITES:
        word = p1.stock_word(site)
        if struct.unpack('<I', word)[0] != expect:
            raise SystemExit(f'0x{site:08X} does not hold 0x{expect:08X} in {p1.rom_path()}')
        out.append((site, word, f'hook site {why}'))
    return out


def build_blob():
    resident_src = HERE / 'pc4_resident.S'
    resident = assemble(resident_src)
    resident += b'\0' * (-len(resident) % 4)
    syms = symbols(resident_src)
    if syms['params'] != 0:
        raise SystemExit('params must be the first thing in pc4_resident.S')
    if syms['keep'] != P_KEEP or syms['stub_a'] < P_KEEP + KEEP_N * 16:
        raise SystemExit(f'pc4_resident.S keep at {syms["keep"]:#x}, expected {P_KEEP:#x} '
                         f'with {KEEP_N} entries before the code')
    if len(resident) + 8 > ALLOC:
        raise SystemExit(f'resident {len(resident)} bytes does not fit ALLOC {ALLOC:#x}')
    check_resident_calls(resident[syms['stub_a']:])

    defines = [f'RES_LEN=0x{len(resident):X}',
               f'STUB_A=0x{syms["stub_a"]:X}',
               f'STUB_B=0x{syms["stub_b"]:X}',
               f'STUB_D=0x{syms["disp_stub"]:X}',
               f'STUB_S=0x{syms["mute_stub"]:X}']
    launch_src = HERE / 'pc4_launch.S'
    launch = assemble(launch_src, defines)
    launch_syms = symbols(launch_src, defines)
    if launch_syms['blob'] != len(launch):
        raise SystemExit(f'launcher blob label at {launch_syms["blob"]:#x} '
                         f'but code is {len(launch):#x} bytes')
    p1.check_calls(launch, LAUNCH_CALLS, 'launcher')

    for site, _, _ in SITES:
        for veneer in (CAVE_ARENA, CAVE_ARENA_END - 8 * VENEERS):
            if not -(1 << 25) <= veneer - site - 8 < (1 << 25):
                raise SystemExit(f'cave is out of bl range from 0x{site:08X}')

    blob = launch + resident
    if len(blob) > MAXLEN:
        raise SystemExit(f'blob {len(blob)} bytes exceeds MAXLEN {MAXLEN:#x}')
    info = {'launch': len(launch), 'resident': len(resident),
            'stub_a': syms['stub_a'], 'stub_b': syms['stub_b'], 'disp_stub': syms['disp_stub'],
            'mute_stub': syms['mute_stub']}
    return blob, info


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=pathlib.Path, required=True)
    parser.add_argument('--no-shell', action='store_true')
    parser.add_argument('--banner', default=BANNER)
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise SystemExit(f'{args.out} is not empty; refusing to overwrite')

    blob, info = build_blob()
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = pathlib.Path(tmp_name)
        blob_file = tmp / 'precap.bin'
        blob_file.write_bytes(blob)
        cmd = [sys.executable, str(p1.SHELL / 'build_autorun.py'), '--loader',
               '--banner', args.banner, '--boot-bin', f'{blob_file}:0',
               '--out', str(args.out / 'AutoRun.txt')]
        cmd.append('--no-shell' if args.no_shell else '--no-ep-patches')
        cmd.append('--no-four-box-bar')
        for site, word, _ in hook_sites():
            site_file = tmp / f'site_{site:08x}.bin'
            site_file.write_bytes(word)
            cmd += ['--also-bin', f'0x{site:08X}:{site_file}']
        args.out.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(cmd, capture_output=True, text=True)
        sys.stdout.write(result.stdout)
        if result.returncode:
            sys.stderr.write(result.stderr)
            raise SystemExit('build_autorun failed')
    (args.out / 'precap.bin').write_bytes(blob)
    print(f'\n  precap blob {len(blob)} bytes  '
          + '  '.join(f'{key} {value}' for key, value in info.items()))
    for name in ('AutoRun.txt', 'fpSup.BIN', 'precap.bin'):
        data = (args.out / name).read_bytes()
        print(f'  {name:12s} {len(data):6d} bytes  sha256 {hashlib.sha256(data).hexdigest()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
