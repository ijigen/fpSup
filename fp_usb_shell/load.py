#!/usr/bin/env python3
"""Assemble a resident routine, write it into the cave, and arm its hook.

    ./load.py ../../codex/stage6_gyro_double_buffer_hook.S \
              --entry stage6_hook --hook 0xC00D0794

Unlike inject.py, which fires a routine once and puts the call site back, this
loads code that stays.  It is how the gyro logger is developed: assemble, load,
watch, change one thing, load again -- without burning a card per iteration.

Loading and arming are separate decisions.  A half-written image branched into
from a 2500 Hz interrupt is the kind of mistake that needs the battery pulled,
so nothing is armed until every word has been read back and matched.
"""
import argparse, pathlib, sys, time

from armasm import assemble, symbols
from putfile import put, mem_set, mem_get, sh

# Whether anything is resident in the cave, and how to park it, is the payload's
# business rather than this tool's -- pass --resident-task and --park-state to
# say so. Without them the loader simply refuses when a task is running.


def park_resident(task_name, state):
    """Ask a resident writer to step out of the cave, and wait for it.

    Returns the state address if something was parked, so the caller can point
    it at the new code afterwards.  If no task is running there is nothing to do.
    """
    listing = sh('tkos tsklist')
    if not any(task_name.upper() in l.upper() for l in listing.splitlines()):
        return None
    mem_set(state + 0x7C, 1)
    for _ in range(50):
        if (mem_get(state + 0x80)[0] or 0) == 1:
            print('  parked  the writer stepped out of the cave')
            return state
        time.sleep(0.1)
    raise SystemExit('the writer did not park — pull the battery before loading')


def refuse_if_resident():
    """Do not overwrite code a task is running from.

    Unhooking the callback stops new entries; it does nothing about a writer
    thread already created, which sits in a 5 ms loop inside the region about to
    be rewritten. It executes whatever lands there. `tkos task` offers chgpri and
    nothing else, so there is no way to stop one short of a power cycle.
    """
    listing = sh('tkos tsklist')
    live = [l.strip() for l in listing.splitlines()
            if '|' in l and l.split('|')[1].strip()
            and int(l.split('|')[2].strip() or '0', 16) >= CAVE_LOW]
    if live:
        raise SystemExit(
            'a task is still running out of the cave:\n  ' + '\n  '.join(live) +
            '\nPull the battery before loading. Overwriting the code underneath '
            'it is a freeze, and unhooking does not stop it.')

CAVE_LOW  = 0xC072DE64          # first byte the injection region owns
CAVE_HIGH = 0xC072F000          # the shell's own state starts here


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('source')
    ap.add_argument('--addr',  type=lambda s: int(s, 0), default=CAVE_LOW)
    ap.add_argument('--entry', default=None, help='symbol the hook should branch to')
    ap.add_argument('--hook',  type=lambda s: int(s, 0), default=None)
    ap.add_argument('--resident-task',
                    help='name of a task that runs from the cave and must be '
                         'parked before the code under it is replaced')
    ap.add_argument('--park-state', type=lambda s: int(s, 0),
                    help='address of the payload state block holding S_PARK '
                         '(+0x7C), S_PARKED (+0x80) and S_WRITER_PC (+0x84)')
    ap.add_argument('--park-resume', default=None,
                    help='symbol the parked task should resume at')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    src = pathlib.Path(a.source)
    code = assemble(src)
    end = a.addr + len(code)
    print(f'  source  {src.name}')
    print(f'  code    {len(code)} bytes, {len(code)//4} words, '
          f'0x{a.addr:08X}..0x{end:08X}')
    if a.addr < CAVE_LOW or end > CAVE_HIGH:
        raise SystemExit(f'0x{a.addr:08X}..0x{end:08X} leaves the injection region '
                         f'0x{CAVE_LOW:08X}..0x{CAVE_HIGH:08X}')
    print(f'  headroom {CAVE_HIGH - end} bytes to the shell worker')

    entry = a.addr
    if a.entry:
        sy = symbols(src)
        if a.entry not in sy:
            raise SystemExit(f'no symbol {a.entry!r} in {src.name}')
        entry = a.addr + sy[a.entry]
        print(f'  entry   {a.entry} at 0x{entry:08X}')

    if a.dry_run:
        return 0

    state = None
    if a.resident_task and a.park_state and a.park_resume:
        state = park_resident(a.resident_task, a.park_state)
    if state is None:
        refuse_if_resident()
    put(a.addr, code, 'load  ')          # writes, verifies, repairs
    if state is not None:
        resume = a.addr + symbols(src)[a.park_resume]
        mem_set(state + 0x84, resume)
        mem_set(state + 0x7C, 0)
        print(f'  resumed  0x{resume:08X}')

    if a.hook:
        orig = mem_get(a.hook)
        disp = (entry - a.hook - 8) >> 2
        if not -0x800000 <= disp < 0x800000:
            raise SystemExit('the hook site is out of branch range of the entry')
        # BL, not B. The site holds a BLX -- a call -- and the routine there
        # returns through lr. Branching without link leaves lr holding whatever
        # the caller had, so `pop {.., pc}` returns into the middle of the call
        # chain and the camera goes down on the first firing. Two freezes were
        # spent blaming the payload for this one word.
        word = 0xEB000000 | (disp & 0xFFFFFF)
        mem_set(a.hook, word)
        back = mem_get(a.hook)
        if not back or back[0] != word:
            raise SystemExit(f'the hook did not take: wrote {word:08X}, read {back}')
        print(f'  armed   0x{a.hook:08X} = 0x{word:08X} -> 0x{entry:08X} '
              f'(was 0x{orig[0]:08X})' if orig else '')
    else:
        print('  hook    not armed (pass --hook to arm)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
