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
PAYLOAD_AT = 0xC072E064     # must match --payload-addr below
PHASE_AT = 0xC072F000       # release-only: debug shell state/worker begin here
F_WRITE_AT = 0xC03660E8
ORIENT_AT = 0xC072EF00      # the call-through that suppresses the DNG rotation
                            # tag while a clip is being written.  It only fits
                            # above logger_stream.S, which ends at 0xC072EEF8;
                            # the GYR logger runs to the park stub with nothing
                            # to spare, so this rides with --gcsv-stream only.
ORIENT_PATCH_AT = 0xC00C32C8
ORIENT_AT_ANCHOR = 0xC072EF40   # the frame-anchor payload is 64 bytes longer and
                                # runs past 0xC072EF00; only that build moves it,
                                # so the shipping VSHL stays byte for byte the one
                                # that was tested
TABLE_LOAD_AT = 0xC072F800  # the shell's template slot: nothing uses it at boot,
                            # and the worker sits below it at 0xC072F050

if __name__ == '__main__':
    forwarded = sys.argv[1:]
    phase_probe = '--phase-probe' in forwarded
    gcsv_stream = '--gcsv-stream' in forwarded
    backpressure_probe = '--backpressure-probe' in forwarded
    frame_anchor = '--frame-anchor' in forwarded
    if frame_anchor:
        forwarded = [arg for arg in forwarded if arg != '--frame-anchor']
        if not gcsv_stream:
            raise SystemExit('--frame-anchor is a GCSV-only streaming build')
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
    payload = HERE / ('logger_stream_anchor.S' if frame_anchor else
                      'logger_phase.S' if phase_probe else
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
    if gcsv_stream:
        # Portrait takes.  The stub goes in before the four-byte patch that
        # calls it, the same ordering the phase probe needs: the loader keeps
        # section order and only invalidates the instruction cache once every
        # section is in place.
        #
        # Spelled out here rather than passed on the command line, which is how
        # v1.4 shipped without it: the release was rebuilt from build_card.py
        # and the two --also arguments v1.3 had been given by hand were gone.
        # Where the stub goes is decided by how big the payload turned out, not
        # by a constant someone has to remember to move.  The logger has grown
        # past 0xC072EF00 twice now; the first time it took the orientation
        # call-through with it and the camera froze on the take's first frame.
        sys.path.insert(0, str(SHELL.parent))
        from armasm import assemble as _asm
        _end = PAYLOAD_AT + len(_asm(payload))
        at = (_end + 0xF) & ~0xF
        if at + 64 > PARK_AT:
            raise SystemExit(f'the payload ends at 0x{_end:08X}, leaving no room for '
                             f'orient_stub below the park stub at 0x{PARK_AT:08X}')

        # The patch is a bare `bl` word, so its target and the address the stub
        # is placed at have to agree -- and nothing used to make them.  Moving
        # the stub for the frame-anchor build left the word still branching to
        # 0xC072EF00, which by then was inside the logger: the DNG tag writer
        # calls it for every frame, so recording froze on the first one.
        # Generated from the same variable now, so they cannot disagree.
        disp = ((at - ORIENT_PATCH_AT - 8) >> 2) & 0xFFFFFF
        gen = HERE / '.orient_patch.S'
        gen.write_text('.syntax unified\n.arm\n.text\n'
                       f'/* generated: bl 0x{at:08X} over the call at '
                       f'0x{ORIENT_PATCH_AT:08X} */\n'
                       f'    .word   0x{0xEB000000 | disp:08X}\n')
        command += [
            '--also', f'0x{at:08X}:{HERE / "orient_stub.S"}',
            '--also', f'0x{ORIENT_PATCH_AT:08X}:{gen}',
        ]
    sys.exit(subprocess.call(command + forwarded))
