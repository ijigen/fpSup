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
PHASE_AT = 0xC072F000       # release-only: debug shell state/worker begin here
F_WRITE_AT = 0xC03660E8
TABLE_LOAD_AT = 0xC072F800  # the shell's template slot: nothing uses it at boot,
                            # and the worker sits below it at 0xC072F050

if __name__ == '__main__':
    forwarded = sys.argv[1:]
    phase_probe = '--phase-probe' in forwarded
    gcsv_stream = '--gcsv-stream' in forwarded
    backpressure_probe = '--backpressure-probe' in forwarded
    if phase_probe:
        forwarded = [arg for arg in forwarded if arg != '--phase-probe']
        if '--no-shell' not in forwarded:
            raise SystemExit('--phase-probe is release-only: C072F000 is the '
                             'debug shell state/worker region')
    if gcsv_stream:
        forwarded = [arg for arg in forwarded if arg != '--gcsv-stream']
    if backpressure_probe:
        forwarded = [arg for arg in forwarded
                     if arg != '--backpressure-probe']
        if not gcsv_stream:
            raise SystemExit('--backpressure-probe requires --gcsv-stream')
    if phase_probe and gcsv_stream:
        raise SystemExit('--phase-probe and --gcsv-stream are separate A/B builds')
    payload = HERE / ('logger_phase.S' if phase_probe else
                      'logger_stream_probe.S' if backpressure_probe else
                      'logger_stream.S' if gcsv_stream else 'logger.S')
    command = [
        sys.executable, str(SHELL),
        '--payload', str(payload),
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
    ]
    if phase_probe:
        # Place the trampoline before the four-byte firmware patch.  The VSHL
        # loader preserves section order and invalidates the instruction cache
        # after all of them are present, so F_WRITE can never branch into a
        # half-copied probe.
        command += [
            '--also', f'0x{PHASE_AT:08X}:{HERE / "phase_probe.S"}',
            '--also', f'0x{F_WRITE_AT:08X}:{HERE / "phase_fwrite_patch.S"}',
        ]
    else:
        # A soft power cycle may preserve a previous diagnostic patch.  Every
        # ordinary image restores the firmware prologue before it can reuse
        # C072F000 for the USB-shell state or another payload.
        command += [
            '--also', f'0x{F_WRITE_AT:08X}:{HERE / "phase_fwrite_restore.S"}',
        ]
    sys.exit(subprocess.call(command + forwarded))
