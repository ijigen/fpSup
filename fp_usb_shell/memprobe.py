#!/usr/bin/env python3
"""Prove a region of memory is actually yours.

    ./memprobe.py 0x44F6ADC0 0x100000        mark it
    ...record a clip...
    ./memprobe.py 0x44F6ADC0 0x100000 --check

Nothing of yours runs during this: no hook, no task, just markers. A region that
takes a write while the camera is idle can still belong to somebody who
reinitialises it the moment recording starts, and that is not something any
amount of reading the code will tell you.

It is how the worst bug of 2026-08-26 was found. `memmgr bufmem get 0 0x20000
0x40` had been returning 128 bytes -- the handler parses the alignment into the
size slot -- so the shell's capture buffer and a logger's two 16 KiB halves all
sat inside a 256 KiB buffer owned by something else. Writing 16 KiB into it
every 0.8 s tore the picture, or froze the camera, or did nothing, depending on
what the recorder had put there. Before the fix a recording left 0 of 29 markers
standing. After it, 29 of 29.
"""
import argparse, sys

from putfile import mem_set, mem_get, sh

STEP = 0x1000
MARK = 0xBEEF0000


def spots(base, size):
    return [(base + off, MARK | (off >> 12)) for off in range(0, size, STEP)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base', type=lambda s: int(s, 0))
    ap.add_argument('size', type=lambda s: int(s, 0))
    ap.add_argument('--check', action='store_true', help='read back instead of marking')
    ap.add_argument('--skip', type=lambda s: int(s, 0), default=0,
                    help='bytes to leave alone at the start, for regions in use')
    a = ap.parse_args()

    marks = [(x, v) for x, v in spots(a.base, a.size) if x >= a.base + a.skip]
    if not a.check:
        hook = mem_get(0xC00D0794)
        if hook and hook[0] != 0xFA046FD7:
            print(f'  WARNING 0xC00D0794 is 0x{hook[0]:08X}, not the original — '
                  'something of yours is running, and this test wants nothing to be')
        for addr, val in marks:
            mem_set(addr, val)
        bad = [a_ for a_, v in marks if (mem_get(a_)[0] or 0) != v]
        print(f'  marked  {len(marks) - len(bad)}/{len(marks)} took the write')
        print('  now record a clip, then run again with --check')
        return 1 if bad else 0

    bad = [(a_, v, mem_get(a_)[0]) for a_, v in marks if (mem_get(a_)[0] or 0) != v]
    print(f'  intact  {len(marks) - len(bad)}/{len(marks)}')
    for addr, want, got in bad[:12]:
        shown = f'0x{got:08X}' if got is not None else 'unreadable'
        print(f'    +0x{addr - a.base:06X}  wrote 0x{want:08X}  reads {shown}')
    if bad:
        print('  the region is not yours: something else owns it and rewrote it')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
