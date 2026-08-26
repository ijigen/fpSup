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


def park_resident(task_name, state, stub_src, stub_addr):
    """Ask a resident writer to step out of the cave, and wait for it.

    Returns the state address if something was parked, so the caller can point
    it at the new code afterwards.  If no task is running there is nothing to do.
    """
    listing = sh('tkos tsklist')
    if not any(task_name.upper() in l.upper() for l in listing.splitlines()):
        return None
    # Place the stub here rather than expecting it from a card script: the shell's
    # AutoRun carries the shell and nothing else, and what a payload needs to be
    # swappable is the payload's business.
    put(stub_addr, assemble(stub_src), 'park  ')
    mem_set(stub_addr + symbols(stub_src)['park_state'], state)
    mem_set(state, 1)                       # PARK
    for _ in range(50):
        if (mem_get(state + 4)[0] or 0) == 1:   # PARKED
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
    # `tkos tsklist` prints id|name|task|stat|pri|stksz|wait|wid, with the entry
    # address in the third column. Anything running from the cave is running from
    # code this loader is about to replace.
    live = []
    for line in sh('tkos tsklist').splitlines():
        cols = line.split('|')
        if len(cols) < 3:
            continue
        try:
            entry = int(cols[2].strip(), 16)
        except ValueError:
            continue
        if CAVE_LOW <= entry < CAVE_HIGH:
            live.append(line.strip())
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
                    help='address of the three words the parking protocol uses: '
                         'PARK, PARKED and RESUME, in that order')
    ap.add_argument('--park-stub', type=pathlib.Path, default=None,
                    help='source of the stub to park in, placed by this tool')
    ap.add_argument('--park-stub-addr', type=lambda s: int(s, 0), default=0xC072EF00)
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
    if a.resident_task and a.park_state and a.park_resume and a.park_stub:
        state = park_resident(a.resident_task, a.park_state,
                              a.park_stub, a.park_stub_addr)
    if state is None:
        refuse_if_resident()
    put(a.addr, code, 'load  ')          # writes, verifies, repairs
    if state is not None:
        resume = a.addr + symbols(src)[a.park_resume]
        mem_set(state + 8, resume)              # RESUME
        mem_set(state, 0)                       # PARK
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
