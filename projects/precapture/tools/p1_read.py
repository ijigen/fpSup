#!/usr/bin/env python3
"""p1_read.py -- read the pre-capture P1 observer's counters over the USB shell.

    python3 p1_read.py read                 header + every ring entry in use
    python3 p1_read.py read --save FILE     also write the raw words to FILE

Read-only: it issues `mem get` and nothing else, one attempt per command, and
stops at the first reply that is missing a word or is not a dump.  It finds
the observer from the hook site itself (site -> bl -> veneer -> stub_a), so it
depends on no address that changes per boot.

Without `read` it prints this text and never connects.
"""
import argparse
import pathlib
import re
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / 'fpSup' / 'fp_usb_shell'))
sys.path.insert(0, str(HERE.parent / 'build'))

SITE_A, SITE_B = 0xC038F0E8, 0xC038F174
ORIG_BLX_R3 = 0xE12FFF33
VENEER_LDR = 0xE51FF004
MAGIC, LAYOUT, RING_N = 0x31504350, 1, 64
HEADER_WORDS = 8
WORDS_PER_COMMAND = 32
DUMP_LINE = re.compile(r'A:0x([0-9A-Fa-f]+),\s*D:0x([0-9A-Fa-f]+)')


class ReadStopped(Exception):
    pass


def read_words(sh, address, count):
    words = []
    for start in range(0, count, WORDS_PER_COMMAND):
        chunk = min(WORDS_PER_COMMAND, count - start)
        base = address + start * 4
        reply = sh(f'mem get 0x{base:08X},,0x{chunk * 4:X}', retries=0)
        seen = {int(a, 16): int(d, 16) for a, d in DUMP_LINE.findall(reply)}
        missing = [base + i * 4 for i in range(chunk) if base + i * 4 not in seen]
        if missing:
            raise ReadStopped(f'mem get 0x{base:08X}: no word for 0x{missing[0]:08X}; '
                              f'reply was {reply.strip()[:120]!r}')
        words += [seen[base + i * 4] for i in range(chunk)]
    return words


def bl_target(site, word):
    if word >> 24 != 0xEB:
        return None
    offset = word & 0x00FFFFFF
    if offset & 0x00800000:
        offset -= 1 << 24
    return site + 8 + offset * 4


def stub_offsets():
    from armasm import symbols
    found = symbols(HERE.parent / 'build' / 'pc_resident.S')
    return found['stub_a'], found['stub_b']


def locate(sh):
    stub_a_off, stub_b_off = stub_offsets()
    site_a, site_b = read_words(sh, SITE_A, 1)[0], read_words(sh, SITE_B, 1)[0]
    if site_a == ORIG_BLX_R3 and site_b == ORIG_BLX_R3:
        raise ReadStopped('both sites still hold the stock `blx r3`: the observer is not installed')
    veneers = [bl_target(SITE_A, site_a), bl_target(SITE_B, site_b)]
    if None in veneers:
        raise ReadStopped(f'site words 0x{site_a:08X} / 0x{site_b:08X} are not both bl')
    stubs = []
    for veneer in veneers:
        ldr, target = read_words(sh, veneer, 2)
        if ldr != VENEER_LDR:
            raise ReadStopped(f'veneer 0x{veneer:08X} holds 0x{ldr:08X}, not ldr pc')
        stubs.append(target)
    params = stubs[0] - stub_a_off
    if stubs[1] - params != stub_b_off:
        raise ReadStopped('the two veneers do not point into the same resident')
    return params, veneers


def report(params, header, ring_rows):
    _, _, count_a, count_b, first_us, last_us, seq, _ = header
    print(f'observer at 0x{params:08X}')
    print(f'  frames  main {count_a}  sub {count_b}  total seq {seq}')
    if seq:
        span = (last_us - first_us) & 0xFFFFFFFF
        print(f'  first {first_us} us  last {last_us} us  span {span / 1000:.1f} ms')
        if seq > 1:
            print(f'  average {span / 1000 / (seq - 1):.1f} ms between frames'
                  f'  ({(seq - 1) * 1e6 / span:.2f} fps)' if span else '')
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
            raise ReadStopped(f'0x{params:08X} does not hold a layout-1 PCP1 block: '
                              + ' '.join(f'{w:08X}' for w in header))
        seq = header[6]
        used = min(seq, RING_N)
        ring = read_words(sh, params + 0x20, used * 4) if used else []
    except ReadStopped as stopped:
        print(f'stopped: {stopped}', file=sys.stderr)
        return 1
    rows = [struct.unpack('<4I', struct.pack('<4I', *ring[i * 4:i * 4 + 4])) for i in range(used)]
    first_index = seq - used
    ordered = [(first_index + k, rows[(first_index + k) % RING_N]) for k in range(used)]
    report(params, header, ordered)
    if args.save:
        args.save.write_text(' '.join(f'{w:08X}' for w in [params, *veneers, *header, *ring]) + '\n')
        print(f'  saved {args.save}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
