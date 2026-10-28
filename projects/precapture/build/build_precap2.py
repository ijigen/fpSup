#!/usr/bin/env python3
"""build_precap2.py -- build the pre-capture P2 card (AutoRun.txt + fpSup.BIN).

    python3 build_precap2.py --out DIR      dev card, USB shell kept (--no-ep-patches)
    python3 build_precap2.py --out DIR --no-shell

P2 makes a half-press start the stock high-speed burst.  Three sites:
  A = C038F0E8, B = C038F174  the HIGHCONT `blx r3` hand-offs (count frames, as
                              P1, and send S2 OFF once a burst passes 10 s);
  D = C02DC108                the KeyMon thread's only `bl FUN_c02dc138` (key
                              dispatch): on S1 ON, when FUN_c0397b30(3) == 9,
                              dispatch S2 ON right after it; on S1 OFF while
                              pre-capturing, dispatch S2 OFF first.
Only stock key codes are used.  Same rules as P1: the shared build_autorun.py
--loader path, one --boot-bin (destination 0), each site declared as a
four-byte section holding the firmware's own word.  Offline; writes no card.
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
SITES = [
    (0xC038F0E8, ORIG_BLX_R3, 'HIGHCONT RAW event -> Yuv enqueue (main)'),
    (0xC038F174, ORIG_BLX_R3, 'HIGHCONT RAW event -> Yuv enqueue (sub-frame)'),
    (0xC02DC108, ORIG_BL_DISP, 'KeyMon thread -> key dispatch FUN_c02dc138'),
]
LAUNCH_CALLS = p1.LAUNCH_CALLS
RESIDENT_CALLS = {
    0xC002B6E0,   # F_TICK_US
    0xC0397B30,   # F_KIND   shot-kind selector, read-only
    0xC02DBAF0,   # F_KEYMON KeyMon singleton getter
    0xC02DBBE8,   # F_ENQ    post a key code to the KeyMon queue
    0xC02DC138,   # F_DISP   the stock key dispatch site D calls
}
CAVE_ARENA, CAVE_ARENA_END = p1.CAVE_ARENA, p1.CAVE_ARENA_END
ALLOC = p1.ALLOC
MAXLEN = p1.MAXLEN
BANNER = 'fpSup-DEV-PreCap2!'
VENEERS = len(SITES)
P_RING, RING_N = 0x40, 64


def hook_sites():
    """Each run-time site as a four-byte section holding the firmware's word."""
    out = []
    for site, expect, why in SITES:
        word = p1.stock_word(site)
        if struct.unpack('<I', word)[0] != expect:
            raise SystemExit(f'0x{site:08X} does not hold 0x{expect:08X} in {p1.rom_path()}')
        out.append((site, word, f'hook site {why}'))
    return out


def build_blob():
    resident_src = HERE / 'pc2_resident.S'
    resident = assemble(resident_src)
    resident += b'\0' * (-len(resident) % 4)
    syms = symbols(resident_src)
    if syms['params'] != 0:
        raise SystemExit('params must be the first thing in pc2_resident.S')
    if syms['ring'] != P_RING or syms['stub_a'] < P_RING + RING_N * 16:
        raise SystemExit(f'pc2_resident.S ring at {syms["ring"]:#x}, expected {P_RING:#x} '
                         f'with {RING_N} entries before the code')
    if len(resident) + 8 > ALLOC:
        raise SystemExit(f'resident {len(resident)} bytes does not fit ALLOC {ALLOC:#x}')
    p1.check_calls(resident[syms['stub_a']:], RESIDENT_CALLS, 'resident')

    defines = [f'RES_LEN=0x{len(resident):X}',
               f'STUB_A=0x{syms["stub_a"]:X}',
               f'STUB_B=0x{syms["stub_b"]:X}',
               f'STUB_D=0x{syms["disp_stub"]:X}']
    launch_src = HERE / 'pc2_launch.S'
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
            'stub_a': syms['stub_a'], 'stub_b': syms['stub_b'], 'disp_stub': syms['disp_stub']}
    return blob, info


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=pathlib.Path, required=True)
    parser.add_argument('--no-shell', action='store_true',
                        help='leave the USB shell out (the P2 counters cannot be read then)')
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
