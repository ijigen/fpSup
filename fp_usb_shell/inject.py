#!/usr/bin/env python3
"""Assemble a one-shot routine, write it to the camera, and let it fire once.

    ./inject.py templates/oneshot.S [--addr 0xC072F800] [--dry-run]

Writes the code with `mem set` through the shell, clears the scratch word, arms
the borrowed call site, then polls until the routine reports 'DONE'.  Nothing
here lives on the camera permanently: the routine restores the call site itself.
"""
import argparse, pathlib, subprocess, sys, time

from armasm import assemble, words

HERE = pathlib.Path(__file__).resolve().parent
FPSH = HERE / 'host' / 'fpsh'

HOOK_SITE = 0xC00D0794
HOOK_ORIG = 0xFA046FD7
SCRATCH   = 0xC072F700


def sh(*cmd) -> str:
    r = subprocess.run([str(FPSH), *cmd], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"fpsh {' '.join(cmd)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('source', help='e.g. templates/oneshot.S')
    ap.add_argument('--addr', type=lambda s: int(s, 0), default=0xC072F800)
    ap.add_argument('--timeout', type=float, default=10.0)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    code = assemble(HERE / a.source if not pathlib.Path(a.source).exists() else a.source)
    w = words(code)
    end = a.addr + len(code)
    if end > 0xC0730000:
        raise SystemExit(f'routine overruns the injection area: 0x{end:08X}')
    print(f'{a.source}: {len(code)} bytes at 0x{a.addr:08X}..0x{end:08X}')

    branch = 0xEB000000 | (((a.addr - (HOOK_SITE + 8)) >> 2) & 0xFFFFFF)
    if a.dry_run:
        for i, x in enumerate(w):
            print(f'mem set 0x{a.addr + i*4:08X} 0x{x:08X}')
        print(f'mem set 0x{SCRATCH:08X} 0x00000000')
        print(f'mem set 0x{HOOK_SITE:08X} 0x{branch:08X}')
        return 0

    for i, x in enumerate(w):
        sh('mem', 'set', f'0x{a.addr + i*4:08X}', f'0x{x:08X}')
    sh('mem', 'set', f'0x{SCRATCH:08X}', '0x00000000')
    print(f'arming 0x{HOOK_SITE:08X} -> 0x{a.addr:08X}')
    sh('mem', 'set', f'0x{HOOK_SITE:08X}', f'0x{branch:08X}')

    deadline = time.time() + a.timeout
    while time.time() < deadline:
        out = sh('mem', 'get', f'0x{SCRATCH:08X},,0x8')
        if 'D:0x454E4F44' in out:
            print(out.strip())
            print('fired; the call site restored itself')
            return 0
        time.sleep(0.2)

    print('timed out waiting for the routine to run', file=sys.stderr)
    print(sh('mem', 'get', f'0x{HOOK_SITE:08X},,0x4').strip(), file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
