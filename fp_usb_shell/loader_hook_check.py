#!/usr/bin/env python3
"""Read the loader hook's state off the camera (a --loader-hook-mark card).

    ./loader_hook_check.py            # after any boot

Prints whether 0xC03DA420 points at the loader, what the power-off routine has
recorded (runs, when), and walks the journal of the load that is live now,
comparing every saved word with out/MAIN_c0000000.bin -- the journal must hold
the STOCK words, or power-off would put back something else.
"""
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from putfile import mem_get                                   # noqa: E402

IMAGE = HERE.parents[1] / 'out' / 'MAIN_c0000000.bin'
CAVE_LOW, SITE, SITE_ORIG = 0xC072DE64, 0xC03DA420, 0xEB0000CC
MARK = 0xC072E040
HOOK_BL = 0xEB000000 | ((((CAVE_LOW + 4) - SITE - 8) >> 2) & 0xFFFFFF)


def read(addr, nwords):
    """mem_get in 64-word pieces, retried: a long read loses replies, and a
    missing word read as a mismatch once (2026-09-25, a 933-word og3k entry)."""
    out = []
    for k in range(0, nwords, 64):
        c = min(64, nwords - k)
        for _ in range(5):
            w = mem_get(addr + 4 * k, c)
            if w and len(w) == c and None not in w:
                break
        else:
            sys.exit(f'read failed at 0x{addr + 4 * k:08X}')
        out += w
    return tuple(out)


def main():
    site, = mem_get(SITE)
    plus4, = mem_get(CAVE_LOW + 4)
    runs, when, block, drawn = mem_get(MARK, 4)
    print(f'0xC03DA420 = 0x{site:08X}  ' + ('armed -> loader+4' if site == HOOK_BL
          else 'stock' if site == SITE_ORIG else '?? unknown'))
    print(f'loader+4   = 0x{plus4:08X}  ' + ('hook entry' if plus4 >> 24 == 0xEA
          else 'NOT a hook entry (old loader)'))
    print(f'power-off routine: runs={runs} last at {when / 1e6:.3f} s (camera clock of that boot)')
    print(f'banner     : ' + (f'drawn, calls returned at {drawn / 1e6:.3f} s' if drawn
                              else 'not drawn this boot'))
    if not 0x40000000 <= block < 0xC0000000:
        print(f'block      = 0x{block:08X}  (no journal this boot)')
        return
    vt, routine, jptr = mem_get(block, 3)
    print(f'block      = 0x{block:08X}  vtbl ok={vt == block - 8}  routine ok={routine == block + 12}')
    stock = IMAGE.read_bytes() if IMAGE.exists() else None
    j, n_ok, n_bad, entries = jptr, 0, 0, 0
    while True:
        addr, size = mem_get(j, 2)
        if addr == 0:
            break
        words = read(j + 8, size // 4)
        entries += 1
        if stock is not None:
            want = struct.unpack_from(f'<{size // 4}I', stock, addr - 0xC0000000)
            ok = tuple(words) == want
            n_ok += ok
            n_bad += not ok
            now = read(addr, size // 4)
            print(f'  0x{addr:08X} +{size:<4} saved==stock {ok}   live {"patched" if tuple(now) != want else "STOCK?"}')
        j += 8 + size
        if entries > 512:
            sys.exit('journal does not terminate')
    print(f'journal: {entries} entries, {n_ok} match the image, {n_bad} do not')


if __name__ == '__main__':
    main()
