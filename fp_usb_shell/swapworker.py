#!/usr/bin/env python3
"""Replace the running worker without a power cycle.

    ./swapworker.py

Every change to worker.S used to cost a reboot: the code is placed at boot, and
the task asking for the change is running inside the code being replaced. Eight
reboots in one evening, for eight one-line edits.

loader.S is already the piece that does this correctly -- it reads VSHL.BIN,
places what the file says, and branches to the entry named in it -- and it lives
at the bottom of the cave, well clear of what it writes. So the swap is not a
new mechanism: it is the boot path, asked for a second time, by a worker that
hands its task over rather than trying to overwrite itself.

    write VSHL.BIN to the card
    tell the worker where to go
    the worker branches into the loader on its next round
    the loader re-reads the file and becomes the new worker

The endpoints are unattended while the file is read, so the first command after
is expected to be slow, and is retried.
"""
import struct, sys, time
from pathlib import Path

from armasm import assemble, symbols
from putfile import sh, mem_set, mem_get, read_bulk, HERE

SWAP_MAGIC, SWAP_ADDR = 0xC072F044, 0xC072F048
SWAP_WORD = 0x50415753          # "SWAP"
CAVE_LOW, LOAD = 0xC072DE64, 0xC072F050


def main():
    worker = assemble(HERE / 'camera' / 'worker.S')
    binpath = HERE / 'autorun' / 'VSHL.BIN'
    if not binpath.exists():
        raise SystemExit('build it first: python3 build_autorun.py --loader')

    live = read_bulk(LOAD, len(worker), 'before')
    if live == worker:
        print('  the worker in memory is already this one; nothing to swap')
        return 0

    where = CAVE_LOW + symbols(HERE / 'templates' / 'loader.S')['load']
    print(f'  loader load at 0x{where:08X}')

    # Address first, magic second. The worker checks the magic and only then
    # reads the address, so a half-written pair never sends it anywhere.
    mem_set(SWAP_ADDR, where)
    got = mem_get(SWAP_ADDR)
    if not got or got[0] != where:
        raise SystemExit(f'  address did not take: {got}')
    mem_set(SWAP_MAGIC, SWAP_WORD)

    for attempt in range(20):
        time.sleep(0.5)
        try:
            live = read_bulk(LOAD, len(worker), 'after ')
        except SystemExit:
            continue
        if live == worker:
            print(f'  swapped, byte for byte, after {(attempt + 1) * 0.5:.1f}s')
            print('  shell :', sh('version', retries=3).split('\n')[0].strip())
            return 0
        same = sum(1 for a, b in zip(live, worker) if a == b)
        print(f'  {same}/{len(worker)} bytes match so far')
    raise SystemExit('  the worker never became the new one')


if __name__ == '__main__':
    sys.exit(main())
