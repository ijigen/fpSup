#!/usr/bin/env python3
"""Which products obey the cave rule, asked of the cards themselves.

    ./tools/cave_audit.py                 every released product
    ./tools/cave_audit.py path/to/card    one card directory

The rule is that no product names a cave address at build time: it asks the
allocator at boot and keeps only what the firmware has to branch to. Sources are
held to it by test_safety.ArenaTests, and a release card is held to it by
release_card.check_sections -- but neither can answer "is what people are
running today obeying it", because a released archive is immutable and a merged
card is built from released archives rather than from the tree.

So this reads the cards. A card writes the cave two ways and this counts both:
`mem set` lines in AutoRun.txt, and VBIN section destinations in fpSup.BIN.

Three regions, and only one of them is a finding:

    the loader's own block   0xC072DE64..0xC072E064   every card writes it; it
                             is the loader, and it cannot ask for space because
                             it is what goes and asks
    THE ARENA                0xC072E064..0xC072EFB4   a byte here is a claim the
                             allocator will hand to somebody else
    above the arena          0xC072EFB4..             the park stub and the USB
                             worker's rendezvous words, which the resident
                             worker carries and so cannot be allocated

Written on 2026-09-23, when the answer was: og3k and og2k clean, usbshell's 96
bytes are its ABI, and the shipped gyro still holds 1,736 bytes of arena in
seven sections -- with the fix in the tree and not yet released.
"""
import pathlib
import re
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
RELEASES = HERE.parent / 'releases'
CAVE_LO, CAVE_HI = 0xC072D000, 0xC0730000
ARENA_LO, ARENA_HI = 0xC072E064, 0xC072EFB4
LOADER_LO = 0xC072DE64


def writes(card):
    """Every (how, address, length) this card puts in the cave."""
    out = []
    autorun = card / 'AutoRun.txt'
    if autorun.exists():
        for m in re.finditer(r'^mem set\s+(0x[0-9A-Fa-f]+)',
                             autorun.read_text(errors='replace'), re.M):
            at = int(m.group(1), 16)
            if CAVE_LO <= at < CAVE_HI:
                out.append(('mem set', at, 4))
    payload = card / 'fpSup.BIN'
    if payload.exists():
        raw = payload.read_bytes()
        if raw[:4] == b'VBIN':
            _, count, _, _ = struct.unpack_from('<4sIII', raw)
            off = 16
            for _ in range(count):
                dest, length = struct.unpack_from('<II', raw, off)
                off += 8
                if CAVE_LO <= dest < CAVE_HI:
                    out.append(('section', dest, length))
    return out


def merge(spans):
    """Adjacent writes of the same kind read as one region."""
    out, cur = [], None
    for kind, at, n in sorted(spans, key=lambda s: s[1]):
        if cur and cur[0] == kind and at == cur[1] + cur[2]:
            cur = (kind, cur[1], cur[2] + n)
        else:
            if cur:
                out.append(cur)
            cur = (kind, at, n)
    if cur:
        out.append(cur)
    return out


def zone(at):
    if at < ARENA_LO:
        return 'the loader block' if at >= LOADER_LO else 'below the loader'
    return 'THE ARENA' if at < ARENA_HI else 'above the arena'


def report(card):
    regions = merge(writes(card))
    arena = sum(n for _, at, n in regions if zone(at) == 'THE ARENA')
    total = sum(n for _, _, n in regions)
    verdict = f'{arena} bytes of arena' if arena else 'clean'
    print(f'\n{card.name}   {total} bytes of cave, {verdict}')
    for kind, at, n in regions:
        mark = ' <<<' if zone(at) == 'THE ARENA' else ''
        print(f'   {kind:<8} 0x{at:08X}..0x{at + n:08X}  {n:5d}  {zone(at)}{mark}')
    return arena


def main():
    if len(sys.argv) > 1:
        return 1 if report(pathlib.Path(sys.argv[1])) else 0
    if not RELEASES.is_dir():
        raise SystemExit(f'{RELEASES} is not there')
    products = sorted({d.name.split('-v')[0] for d in RELEASES.glob('fpsup-*-v*')})
    bad = []
    for product in products:
        cards = sorted(RELEASES.glob(f'{product}-v*'))
        if not cards:
            continue
        if report(cards[-1]):
            bad.append(cards[-1].name)
    print()
    if bad:
        print('these hold arena the allocator will hand to somebody else:')
        for name in bad:
            print(f'  {name}')
        print('a card already published cannot be fixed -- the next release can')
        return 1
    print('every released product obeys the rule')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
