#!/usr/bin/env python3
"""build_precap.py -- build the pre-capture P1 card (AutoRun.txt + fpSup.BIN).

    python3 build_precap.py --out DIR      dev card, USB shell kept (--no-ep-patches)
    python3 build_precap.py --out DIR --no-shell

P1 only observes: the two HIGHCONT hand-off sites (C038F0E8 / C038F174, both
`blx r3` into XC_StillCreateYuv's enqueue) count each frame and stamp it with
the microsecond clock, then tail-call the original.  Nothing the camera does
changes.

Per SUP_BUILD_RULES: the shared build_autorun.py --loader path, one --boot-bin
(destination 0), and each run-time site declared as a four-byte section holding
the firmware's own word, so stage2 journals it and the loader writes it back
at power-off.  Building is offline; it writes no card and touches no camera.
"""
import argparse
import hashlib
import pathlib
import struct
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
SHELL = REPO / 'fpSup' / 'fp_usb_shell'
sys.path.insert(0, str(SHELL))
from armasm import assemble, symbols  # noqa: E402

ROM_CANDIDATES = (REPO / 'out' / 'MAIN_c0000000.bin',
                  pathlib.Path('/opt/sigma/out/MAIN_c0000000.bin'))
ROM_BASE = 0xC0000000
ORIG_BLX_R3 = 0xE12FFF33
SITES = [
    (0xC038F0E8, 'HIGHCONT RAW event -> Yuv enqueue (main)'),
    (0xC038F174, 'HIGHCONT RAW event -> Yuv enqueue (sub-frame)'),
]
LAUNCH_CALLS = {0xC001D740, 0xC001D7F0, 0xC000E91C, 0xC000EABC}
RESIDENT_CALLS = {0xC002B6E0}
CAVE_ARENA, CAVE_ARENA_END = 0xC072E064, 0xC072EFB4
ALLOC = 0x1000
MAXLEN = 0xF000
BANNER = 'fpSup-DEV-PreCap1!'


def rom_path():
    for path in ROM_CANDIDATES:
        if path.exists():
            return path
    raise SystemExit('firmware image MAIN_c0000000.bin not found in: '
                     + ', '.join(str(p) for p in ROM_CANDIDATES))


def stock_word(address):
    data = rom_path().read_bytes()
    return data[address - ROM_BASE:address - ROM_BASE + 4]


def hook_sites():
    """Each run-time site as a four-byte section holding the firmware's word."""
    out = []
    for site, why in SITES:
        word = stock_word(site)
        if struct.unpack('<I', word)[0] != ORIG_BLX_R3:
            raise SystemExit(f'0x{site:08X} is not `blx r3` in {rom_path()}')
        out.append((site, word, f'hook site {why}'))
    return out


def blx_targets(code):
    """Every `blx ip` target formed by a preceding movw/movt ip pair."""
    import capstone
    disassembler = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    low = high = None
    targets, direct = [], []
    for insn in disassembler.disasm(code, 0):
        if insn.mnemonic == 'movw' and insn.op_str.startswith('ip,'):
            low = int(insn.op_str.split('#')[1], 0)
        elif insn.mnemonic == 'movt' and insn.op_str.startswith('ip,'):
            high = int(insn.op_str.split('#')[1], 0)
        elif insn.mnemonic == 'blx' and insn.op_str == 'ip':
            targets.append((high << 16) | low)
        elif insn.mnemonic == 'bl':
            direct.append(insn.address)
    return targets, direct


def check_calls(code, allowed, what):
    targets, direct = blx_targets(code)
    if direct:
        raise SystemExit(f'{what} has a direct bl at {direct[0]:#x}')
    for target in targets:
        if target not in allowed:
            raise SystemExit(f'{what} calls 0x{target:08X}, not an allowed routine')


def build_blob():
    resident_src = HERE / 'pc_resident.S'
    resident = assemble(resident_src)
    resident += b'\0' * (-len(resident) % 4)
    resident_syms = symbols(resident_src)
    if resident_syms['params'] != 0:
        raise SystemExit('params must be the first thing in pc_resident.S')
    if len(resident) + 8 > ALLOC:
        raise SystemExit(f'resident {len(resident)} bytes does not fit ALLOC {ALLOC:#x}')
    check_calls(resident[resident_syms['stub_a']:], RESIDENT_CALLS, 'resident')

    defines = [f'RES_LEN=0x{len(resident):X}',
               f'STUB_A=0x{resident_syms["stub_a"]:X}',
               f'STUB_B=0x{resident_syms["stub_b"]:X}']
    launch_src = HERE / 'pc_launch.S'
    launch = assemble(launch_src, defines)
    launch_syms = symbols(launch_src, defines)
    if launch_syms['blob'] != len(launch):
        raise SystemExit(f'launcher blob label at {launch_syms["blob"]:#x} '
                         f'but code is {len(launch):#x} bytes')
    check_calls(launch, LAUNCH_CALLS, 'launcher')

    for site, _ in SITES:
        for veneer in (CAVE_ARENA, CAVE_ARENA_END - 16):
            if not -(1 << 25) <= veneer - site - 8 < (1 << 25):
                raise SystemExit(f'cave is out of bl range from 0x{site:08X}')

    blob = launch + resident
    if len(blob) > MAXLEN:
        raise SystemExit(f'blob {len(blob)} bytes exceeds MAXLEN {MAXLEN:#x}')
    info = {'launch': len(launch), 'resident': len(resident),
            'stub_a': resident_syms['stub_a'], 'stub_b': resident_syms['stub_b']}
    return blob, info


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=pathlib.Path, required=True)
    parser.add_argument('--no-shell', action='store_true',
                        help='leave the USB shell out (the P1 counters cannot be read then)')
    parser.add_argument('--banner', default=BANNER)
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise SystemExit(f'{args.out} is not empty; refusing to overwrite')

    blob, info = build_blob()
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = pathlib.Path(tmp_name)
        blob_file = tmp / 'precap.bin'
        blob_file.write_bytes(blob)
        cmd = [sys.executable, str(SHELL / 'build_autorun.py'), '--loader',
               '--banner', args.banner, '--boot-bin', f'{blob_file}:0',
               '--out', str(args.out / 'AutoRun.txt')]
        cmd.append('--no-shell' if args.no_shell else '--no-ep-patches')
        # build_autorun marks the four-box splash "hardware untested"; P1 keeps
        # the text banner so the card carries no display code it has not run.
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
