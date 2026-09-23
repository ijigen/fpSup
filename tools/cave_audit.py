#!/usr/bin/env python3
"""Which products obey the cave rule, asked of the cards themselves.

    ./tools/cave_audit.py                 every released product
    ./tools/cave_audit.py path/to/card    one card directory
    ./tools/cave_audit.py --sources       who claims what, and who collides

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


# ---------------------------------------------------------------- the sources
# The card audit above answers "is what people are running obeying the rule".
# This answers the other half, which ROADMAP G1 states as "no undeclared fixed
# scratch/code ownership": who in the tree still writes an address down, and
# where two of them wrote the same one.
#
# A collision here is not hypothetical. 0xC072F700 is the host's old parameter
# block, the fast-start bootstrap's word, and the state word of four lossless
# probes; the two that run together find out by hanging. The answer is not to
# arrange them by hand again -- it is cave.claim, which asks the camera's own
# bump pointer and cannot hand the same bytes to two callers.
SKIP_PARTS = ('release', 'history', '.git', 'node_modules', 'jdk',
              '_retired_2026-09-19')
# The map's own landmarks. Several files name each of these and give it a
# different local name -- CAVE_LOW, CAVE_BASE, LOADER_LO are one address and
# one meaning -- so a name mismatch here is inconsistent spelling, not two
# owners. Every other address that two files name IS two owners until somebody
# shows otherwise.
LANDMARKS = {
    0xC072DE64: 'the loader base',
    0xC072E060: 'the bump pointer',
    0xC072E064: 'the arena base',
    0xC072EFB4: 'the arena end / park stub',
}
# The resident worker's rendezvous block, which cannot be allocated: the worker
# was built with these addresses in it, so the host has to use the same ones.
# fp_usb_shell/cave.py names them once as ABI; the files here reached them
# before that existed and spell them differently -- STATE, A_WORKER, CAVE_HIGH
# are one word, and so are CAPLEN and CAP_LEN.
ABI_BLOCK = (0xC072F000, 0xC072F100)
ABI_SINGLES = {0xC072F6D8: 'the allocator descriptor',
               0xC072F6F4: 'the load-start stamp',
               0xC072F6F8: 'the load-done stamp'}


def _landmark(at):
    if at in LANDMARKS:
        return LANDMARKS[at]
    if ABI_BLOCK[0] <= at < ABI_BLOCK[1]:
        return "the worker's ABI"
    return ABI_SINGLES.get(at)


# These two declare the map rather than claim a piece of it.
MAP_FILES = ('cave.py', 'cave_audit.py')


def _skip(p):
    return p.name in MAP_FILES or any(part in p.parts for part in SKIP_PARTS)


def sources(root):
    """{address: {file: [names]}} for every cave address the tree writes down.

    A `#ifndef`-guarded .equ is a standalone default the caller overrides, so
    it is not a claim and is not counted.
    """
    import ast
    import collections
    out = collections.defaultdict(lambda: collections.defaultdict(list))
    for f in sorted(root.rglob('*.py')):
        if _skip(f):
            continue
        try:
            tree = ast.parse(f.read_text())
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target])
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            for t in targets:
                if isinstance(t, ast.Tuple):
                    names += [e.id for e in t.elts if isinstance(e, ast.Name)]
            vals = ([node.value] if not isinstance(node.value, ast.Tuple)
                    else list(node.value.elts))
            for i, v in enumerate(vals):
                if (isinstance(v, ast.Constant) and isinstance(v.value, int)
                        and CAVE_LO <= v.value < CAVE_HI):
                    nm = names[i] if i < len(names) else (names[0] if names else '?')
                    out[v.value][str(f)].append(nm)
    for f in sorted(root.rglob('*.S')):
        if _skip(f):
            continue
        text = f.read_text()
        for m in re.finditer(
                r'^\.equ\s+([A-Z][A-Z_0-9]*),\s*(0xC072[0-9A-Fa-f]{4})',
                text, re.M):
            at = int(m.group(2), 16)
            if not CAVE_LO <= at < CAVE_HI:
                continue
            if re.search(rf'#ifndef\s+{m.group(1)}\s*\n\s*$',
                         text[:m.start()][-140:]):
                continue
            out[at][str(f)].append(m.group(1))
    return out


def report_sources(root):
    """Two kinds of sharing, and only one of them is a bug.

    Four files declare CAVE_BUMP at 0xC072E060 and mean the same word: that is
    a mirror, and _check_agrees is what keeps mirrors honest. Eight files claim
    0xC072F700 and mean eight different things: that is a collision, and the
    two that run together find out by hanging. The difference is whether the
    names agree, so that is what this splits on.
    """
    found = sources(root)
    shared = {at: who for at, who in found.items() if len(who) > 1}
    collide, mirror = {}, 0
    spelling = 0
    for at, who in shared.items():
        names = {n for ns in who.values() for n in ns}
        if len(names) == 1:
            mirror += 1
        elif _landmark(at):
            spelling += 1
        else:
            collide[at] = who
    files = sorted({f for who in found.values() for f in who})
    print(f'{len(files)} files write a cave address down, '
          f'{len(found)} addresses.')
    print(f'{mirror} are mirrors -- one name, several files, same meaning.')
    print(f'{spelling} are landmarks spelled several ways -- the map\'s own '
          f'edges and the worker\'s ABI, which cannot be allocated.')
    print(f'{len(collide)} are COLLISIONS -- one address, different things.\n')
    for at in sorted(collide):
        print(f'  0x{at:08X}  {zone(at)}')
        for f in sorted(collide[at]):
            rel = pathlib.Path(f).relative_to(root)
            print(f'      {", ".join(collide[at][f]):<24} {rel}')
        print()
    if collide:
        print('Owners of one address agree only by hand, and find out by '
              'hanging.\ncave.claim asks the camera for a block instead -- '
              'see fp_usb_shell/cave.py.')
    return 1 if collide else 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--sources':
        return report_sources(HERE.parent)
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
