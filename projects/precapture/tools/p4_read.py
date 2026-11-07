#!/usr/bin/env python3
"""p4_read.py -- read the pre-capture P4 resident over the USB shell.

    python3 p4_read.py read
    python3 p4_read.py read --save FILE

Read-only: `mem get` only, one attempt per command.  Without `read` it prints
this text and never connects.
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from p1_read import ReadStopped, bl_target, read_words  # noqa: E402

SITES = {'A': 0xC038F0E8, 'B': 0xC038F174, 'D': 0xC02DC108, 'S': 0xC03817D4}
STOCK = {'A': 0xE12FFF33, 'B': 0xE12FFF33, 'D': 0xEB00000A, 'S': 0xEB000047}
STUB_NAME = {'A': 'stub_a', 'B': 'stub_b', 'D': 'disp_stub', 'S': 'mute_stub'}
VENEER_LDR = 0xE51FF004
MAGIC, LAYOUT, KEEP_N = 0x34504350, 4, 4
HEADER_WORDS = 28
P_KEEP = 0x70
FIELDS = ('magic', 'layout', 'count_a', 'count_b', 'first_us', 'last_us', 'seq', 'ring_n',
          'pre', 't0', 'tmo', 'inj', 's1c', 'tmof', 'disp', 'gate',
          'held', 'dropped', 'evicted', 'committed', 'abandoned',
          'origin', 'lock', 'head', 'n', 'muted', 'played', 'pad')


def stub_offsets():
    from armasm import symbols
    found = symbols(HERE.parent / 'build' / 'pc4_resident.S')
    return {site: found[name] for site, name in STUB_NAME.items()}


def locate(sh):
    offsets = stub_offsets()
    words = {name: read_words(sh, address, 1)[0] for name, address in SITES.items()}
    if all(words[name] == STOCK[name] for name in SITES):
        raise ReadStopped('all four sites still hold their stock words: P4 is not installed')
    veneers, residents = {}, set()
    for name, address in SITES.items():
        veneer = bl_target(address, words[name])
        if veneer is None or words[name] == STOCK[name]:
            raise ReadStopped(f'site {name} holds 0x{words[name]:08X}, not a bl into the cave')
        ldr, target = read_words(sh, veneer, 2)
        if ldr != VENEER_LDR:
            raise ReadStopped(f'veneer 0x{veneer:08X} holds 0x{ldr:08X}, not ldr pc')
        veneers[name] = veneer
        residents.add(target - offsets[name])
    if len(residents) != 1:
        raise ReadStopped('the four veneers do not point into the same resident')
    return residents.pop(), veneers


def report(params, header, slots):
    h = dict(zip(FIELDS, header))
    print(f'P4 resident at 0x{params:08X}')
    print(f'  shutter sound  muted {h["muted"]}  played {h["played"]}')
    print(f'  pre-capturing {h["pre"]}  held {h["held"]}  dropped {h["dropped"]}'
          f'  evicted {h["evicted"]}  committed {h["committed"]}  abandoned {h["abandoned"]}')
    print(f'  S2 injected {h["inj"]}  S1-release {h["s1c"]}  timeouts {h["tmof"]}'
          f'  keys {h["disp"]}  gate 0x{h["gate"]:X}')
    print(f'  frames seen  main {h["count_a"]}  sub {h["count_b"]}  seq {h["seq"]}'
          f'  ring n {h["n"]} head {h["head"]}')
    for i, (stamp, job, yuv, site) in enumerate(slots):
        print(f'  keep[{i}]  {stamp} us  job {job}  yuv 0x{yuv:08X}  site {site}')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', nargs='?', choices=['read'])
    parser.add_argument('--save', type=pathlib.Path)
    args = parser.parse_args()
    if args.action != 'read':
        parser.print_help()
        return 0

    from putfile import sh
    try:
        params, veneers = locate(sh)
        header = read_words(sh, params, HEADER_WORDS)
        if header[0] != MAGIC or header[1] != LAYOUT or header[7] != KEEP_N:
            raise ReadStopped(f'0x{params:08X} is not a layout-4 PCP4 block: '
                              + ' '.join(f'{w:08X}' for w in header[:8]))
        n = min(header[24], KEEP_N)
        head = header[23]
        raw = read_words(sh, params + P_KEEP, KEEP_N * 4) if n else []
        slots = []
        for i in range(n):
            off = ((head + i) & 3) * 4
            slots.append(tuple(raw[off:off + 4]))
    except ReadStopped as stopped:
        print(f'stopped: {stopped}', file=sys.stderr)
        return 1
    report(params, header, slots)
    if args.save:
        args.save.write_text(' '.join(f'{w:08X}' for w in [params, *veneers.values(), *header]) + '\n')
        print(f'  saved {args.save}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
