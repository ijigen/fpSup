#!/usr/bin/env python3
"""Build a card that boots the shell and the gyro logger together.

    ./gyro/build_card.py            -> gyro/autorun/AutoRun.txt

The shell's builder knows how to place a payload in the cave and arm it; it does
not know or care that this one is a gyro logger.  Everything specific lives here.

For development, use load.sh instead: it swaps the logger over USB in about a
second, and does not need a reboot.
"""
import pathlib, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
SHELL = HERE.parent / 'fp_usb_shell' / 'build_autorun.py'
PARK_AT = 0xC072EF00        # above the logger, below the shell's worker state

if __name__ == '__main__':
    sys.exit(subprocess.call([
        sys.executable, str(SHELL),
        '--payload', str(HERE / 'logger.S'),
        '--entry', 'gyro_hook',
        '--also', f'0x{PARK_AT:08X}:{SHELL.parent / "templates" / "park.S"}',
        '--out', str(HERE / 'autorun' / 'AutoRun.txt'),
    ] + sys.argv[1:]))
