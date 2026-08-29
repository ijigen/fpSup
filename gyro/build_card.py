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
PARK_AT = 0xC072EFB4        # above the logger, below the shell's worker state
TABLE_LOAD_AT = 0xC072F800  # the shell's template slot: nothing uses it at boot,
                            # and the worker sits below it at 0xC072F050

if __name__ == '__main__':
    sys.exit(subprocess.call([
        sys.executable, str(SHELL),
        '--payload', str(HERE / 'logger.S'),
        '--entry', 'gyro_hook',
        '--also', f'0x{PARK_AT:08X}:{SHELL.parent / "templates" / "park.S"}',
        # The logger is nearly four kilobytes; spelled out as `mem set` it is a
        # fifty kilobyte AutoRun against the thirty-two everything pads to. In
        # the binary it costs nothing, and the builder arms the callback as the
        # binary's last section, after the code it branches to is in place.
        '--loader',
        # Above the loader, and the same address load.sh uses over USB: one
        # layout, so the card build and the development build cannot drift.
        '--payload-addr', '0xC072E064',
        # No --boot-call: the logger fetches \PGEN.BIN itself, on its writer
        # thread's first idle poll. That is ninety-one commands off the boot and
        # one fewer thing borrowing the shell's command table at start-up.
        '--out', str(HERE / 'autorun' / 'AutoRun.txt'),
    ] + sys.argv[1:]))
