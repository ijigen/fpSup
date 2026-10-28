#!/usr/bin/env python3
"""p2_read.py -- read the pre-capture P2 resident's state over the USB shell.

    python3 p2_read.py read                 header + every frame-ring entry in use
    python3 p2_read.py read --save FILE     also write the raw words to FILE

Read-only: it issues `mem get` and nothing else, one attempt per command, and
stops at the first reply that is missing a word or is not a dump.  It finds
the resident from the hook sites themselves (site -> bl -> veneer -> stub), so
it depends on no address that changes per boot, and checks that all three
sites lead into the same resident.

Without `read` it prints this text and never connects.
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from p1_read import ReadStopped, bl_target, read_words  # noqa: E402

SITES = {'A': 0xC038F0E8, 'B': 0xC038F174, 'D': 0xC02DC108}
STOCK = {'A': 0xE12FFF33, 'B': 0xE12FFF33, 'D': 0xEB00000A}
STUB_NAME = {'A': 'stub_a', 'B': 'stub_b', 'D': 'disp_stub'}
VENEER_LDR = 0xE51FF004
MAGIC, LAYOUT, RING_N = 0x32504350, 2, 64
HEADER_WORDS = 16
P_RING = 0x40
FIELDS = ('magic', 'layout', 'count_a', 'count_b', 'first_us', 'last_us', 'seq', 'ring_n',
          'pre', 't0', 'tmo', 'inj', 's1c', 'tmof', 'disp', 'gate')
SINGLETONS = ('FUN_c03a9970', 'FUN_c0206e98', 'FUN_c0387e40', 'FUN_c00213b8', 'FUN_c0022da8')


def stub_offsets():
    from armasm import symbols
    found = symbols(HERE.parent / 'build' / 'pc2_resident.S')
    return {site: found[name] for site, name in STUB_NAME.items()}


def locate(sh):
    offsets = stub_offsets()
    words = {name: read_words(sh, address, 1)[0] for name, address in SITES.items()}
    if all(words[name] == STOCK[name] for name in SITES):
        raise ReadStopped('all three sites still hold their stock words: P2 is not installed')
    veneers, residents = {}, set()
    for name, address in SITES.items():
        veneer = bl_target(address, words[name])
        if veneer is None or words[name] == STOCK[name]:
            raise ReadStopped(f'site {name} 0x{address:08X} holds 0x{words[name]:08X}, '
                              'not a bl into the cave')
        ldr, target = read_words(sh, veneer, 2)
        if ldr != VENEER_LDR:
            raise ReadStopped(f'veneer 0x{veneer:08X} holds 0x{ldr:08X}, not ldr pc')
        veneers[name] = veneer
        residents.add(target - offsets[name])
    if len(residents) != 1:
        raise ReadStopped('the three veneers do not point into the same resident')
    return residents.pop(), veneers


def describe_gate(gate):
    if gate == 0:
        return 'no half-press seen yet'
    if gate == 1:
        return 'injected S2 ON (high-speed continuous)'
    if gate >> 8 == 1:
        return f'not injected: shot kind {gate & 0xFF} is not 9 (high-speed continuous)'
    if gate >> 8 == 2 and 1 <= gate & 0xFF <= len(SINGLETONS):
        return f'not injected: {SINGLETONS[(gate & 0xFF) - 1]} singleton not built yet'
    if gate == 0x300:
        return 'not injected: settings stack (0xC3075670) not in a valid state'
    return f'unknown gate value 0x{gate:X}'


def report(params, header, ring_rows):
    h = dict(zip(FIELDS, header))
    print(f'P2 resident at 0x{params:08X}')
    print(f'  pre-capturing {h["pre"]}  last half-press: {describe_gate(h["gate"])}')
    print(f'  S2 injected {h["inj"]}  S1-release endings {h["s1c"]}  timeouts {h["tmof"]}'
          f'  (timeout sent for current {h["tmo"]})  keys through hook {h["disp"]}')
    if h['inj']:
        print(f'  last injection at {h["t0"]} us')
    print(f'  frames  main {h["count_a"]}  sub {h["count_b"]}  total seq {h["seq"]}')
    seq = h['seq']
    if seq:
        span = (h['last_us'] - h['first_us']) & 0xFFFFFFFF
        print(f'  first {h["first_us"]} us  last {h["last_us"]} us  span {span / 1000:.1f} ms')
        if seq > 1 and span:
            print(f'  average {span / 1000 / (seq - 1):.1f} ms between frames'
                  f'  ({(seq - 1) * 1e6 / span:.2f} fps)')
    previous = None
    for index, (stamp, job, yuv, site) in ring_rows:
        delta = '' if previous is None else f'{((stamp - previous) & 0xFFFFFFFF) / 1000:8.1f} ms'
        print(f'  #{index:<5d} {stamp:>11d} us {delta:>11s}  job 0x{job:08X}'
              f'  yuv 0x{yuv:08X}  site {"AB"[site] if site in (0, 1) else site}')
        previous = stamp


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
        if header[0] != MAGIC or header[1] != LAYOUT or header[7] != RING_N:
            raise ReadStopped(f'0x{params:08X} does not hold a layout-2 PCP2 block: '
                              + ' '.join(f'{w:08X}' for w in header))
        seq = header[6]
        used = min(seq, RING_N)
        ring = read_words(sh, params + P_RING, used * 4) if used else []
    except ReadStopped as stopped:
        print(f'stopped: {stopped}', file=sys.stderr)
        return 1
    rows = [tuple(ring[i * 4:i * 4 + 4]) for i in range(used)]
    first_index = seq - used
    ordered = [(first_index + k, rows[(first_index + k) % RING_N]) for k in range(used)]
    report(params, header, ordered)
    if args.save:
        args.save.write_text(' '.join(f'{w:08X}' for w in
                                      [params, *veneers.values(), *header, *ring]) + '\n')
        print(f'  saved {args.save}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
