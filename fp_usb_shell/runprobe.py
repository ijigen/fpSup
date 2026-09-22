#!/usr/bin/env python3
"""Run a candidate routine once on a live camera, without going near the boot path.

    ./runprobe.py probe.S 0xC072FE00 0xC072F6EC

Writes the assembled routine into the cave at the given address, verifies every
word by reading it back, points the shell's `echo` handler at it, runs `echo`
once, puts the handler back, and then answers the two questions that matter:
did it come back, and is the shell still alive.

WHY THIS EXISTS.  A change to the loader cannot be tried by putting it on a
card.  The loader runs before anything of ours exists, so if it hangs there is
no shell left to replace it with and the SD card has to come out of the slot and
go into a Mac.  That happened twice in one afternoon on 2026-09-22, both times
for an ARM calling-convention mistake in seven instructions -- a `bl` above the
push that saves lr, and then `sp` carried across a call in a caller-saved
register.  Either would have been caught here in ten seconds.

So: a change to the loader, or to anything the loader calls, is proven here
first.  The cost of being wrong is one failed `echo`.

The probe is an ordinary shell handler: it is entered as (ctx, argc, argv), its
return value is ignored, and it must return.  PROBE_BASE is passed to the
assembler so a `CALL`-style macro can work out its own branch offsets, exactly
as loader.S does.

    .macro CALL target
    9:  .word 0xEB000000 + ((((\\target) - (PROBE_BASE + (9b - _pstart))) - 8) >> 2 & 0xFFFFFF)
    .endm

Pick an address in the cave that nothing owns.  Above the host file tools'
scratch (0xC072F700..0xC072FC84) and below the cave's top is usually free; read
it first and make sure it is zero.  The output word is somewhere the probe
writes a recognisable value, so that "it ran" is distinguishable from "it never
started".
"""
import pathlib
import struct
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from armasm import assemble                                    # noqa: E402

FPSH = str(HERE / 'host' / 'fpsh')
ECHO_SLOT, ECHO_ORIG = 0xC0BAC2F8, 0xC03D99A0


def sh(*args, timeout=25):
    return subprocess.run([FPSH, *args], capture_output=True, text=True,
                          timeout=timeout, cwd=HERE).stdout.strip()


def get(addr):
    for token in sh('mem', 'get', f'0x{addr:08X},,4').replace(',', ' ').split():
        if token.startswith('D:0x'):
            return int(token[2:], 16)
    return None


def setw(addr, value, tries=8):
    """`mem set` drops commands silently, so a write is not a write until it
    reads back.  Eight tries, because one retry is not enough and a loop that
    never gives up hides a wedged shell."""
    for _ in range(tries):
        sh('mem', 'set', f'0x{addr:08X}', f'0x{value:08X}')
        if get(addr) == value:
            return True
    return False


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__.strip().splitlines()[2].strip())
    src = pathlib.Path(sys.argv[1])
    at, out = int(sys.argv[2], 0), int(sys.argv[3], 0)

    code = assemble(src, [f'PROBE_BASE=0x{at:08X}'])
    words = struct.unpack(f'<{len(code) // 4}I', code)
    print(f'{src.name}: {len(code)} bytes -> 0x{at:08X}')

    for i, word in enumerate(words):
        if not setw(at + i * 4, word):
            raise SystemExit(f'  0x{at + i * 4:08X} will not hold its word')
    print(f'  {len(words)} words written and read back identical')

    if not setw(out, 0):
        raise SystemExit(f'  0x{out:08X} will not clear')
    if get(ECHO_SLOT) != ECHO_ORIG:
        raise SystemExit(f'  the echo handler is 0x{get(ECHO_SLOT) or 0:08X}, '
                         f'not the firmware\'s -- something else is borrowing it')

    print('  borrowing echo, one call ...')
    try:
        if not setw(ECHO_SLOT, at):
            raise SystemExit('  the handler slot will not take the address')
        sh('echo')
    finally:
        # Whatever happened, the slot goes back.  A handler left pointing at a
        # probe is a camera that runs it again on the next `echo` from anything.
        for _ in range(10):
            sh('mem', 'set', f'0x{ECHO_SLOT:08X}', f'0x{ECHO_ORIG:08X}')
            if get(ECHO_SLOT) == ECHO_ORIG:
                break
        else:
            print('  *** THE ECHO HANDLER IS STILL REDIRECTED -- reboot ***')

    alive = 'pong' in sh('ping')
    value = get(out)
    print(f'\n  shell alive: {alive}')
    print(f'  the probe wrote: 0x{value:08X}' if value else '  the probe wrote nothing')
    if not (alive and value):
        raise SystemExit('  so this code is not safe to put on a card')
    print('  it was called, it came back, and it did not damage its caller')


main()
