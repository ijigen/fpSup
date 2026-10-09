#!/usr/bin/env python3
"""Build HpZoom as a Loader v3 sup: \\fpSup\\20HPZOOM.BIN.

    python3 -B hpzoom/build_v3_hpzoom.py --out /absolute/new/directory [--card]

HpZoom reverses the stock magnification behaviour for manual lenses: in MF
mode with Auto Magnification OFF, a half-press of the shutter (S1) magnifies
and releasing S1 unmagnifies, and the live view is B&W while magnified.  See
projects/hpzoom-sup.md and hpzoom_sup.S's header.

--out DIR writes DIR/20HPZOOM.BIN and build.json.  --no-bw builds
20HPZOOMNB.BIN instead: the same half-press magnification without the
B&W-while-magnified (its own sup id, so the two are never both loaded).
--card makes DIR a whole v3 card instead (AutoRun.txt, fpSup/LOADER.BIN,
fpSup/UI/, fpSup/00SHELL.BIN and the sup, MANIFEST.sha256).  It never writes
a camera card.
"""
import argparse
import hashlib
import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent
V3 = FPSUP / 'fp_usb_shell' / 'v3'
sys.path.insert(0, str(V3))
sys.path.insert(0, str(V3.parent))

import build_v3 as B                                     # noqa: E402
from armasm import assemble, symbols                     # noqa: E402

SRC = HERE / 'hpzoom_sup.S'
NAME, NAME_NB = '20HPZOOM.BIN', '20HPZOMNB.BIN'
SUP_ID, SUP_ID_NB = 'HPZM', 'HPZN'
VERSION = 1

# The four hook sites and their stock words, checked against the reference
# image at build time (the claims table the sup carries says the same).
SITES = {0xC02DBBF0: 0xE1A04000,      # poster +4:          mov r4, r0
         0xC04819DC: 0xE1A04000,      # change_state +4:    mov r4, r0
         0xC02DBC10: 0xE28DD004,      # poster +40:         add sp, sp, #4
         0xC02BAD0C: 0xE24DD064}      # live-view applier +4: sub sp, sp, #0x64


def sup_file(no_bw=False):
    """(sup bytes, symbols).  The claims table as assembled is checked against
    the reference image, the way build_v3_lossless.check_claims does."""
    defines = ['NO_BW=1'] if no_bw else []
    blob = assemble(SRC, defines)
    syms = symbols(SRC, defines)
    n, = struct.unpack_from('<I', blob, syms['claims'])
    want = 3 if no_bw else 4
    if n != want:
        raise B.BuildError(f'claims table has {n} rows, expected {want}')
    for i in range(n):
        addr, stock, kind = struct.unpack_from('<3I', blob, syms['claims'] + 4 + 12 * i)
        if addr not in SITES or SITES[addr] != stock:
            raise B.BuildError(f'0x{addr:08X}: not a known site/stock pair')
        if B.stock(addr, 4) != struct.pack('<I', stock):
            raise B.BuildError(f'0x{addr:08X}: stock 0x{stock:08X} is not the image')
        if kind != 1:
            raise B.BuildError(f'0x{addr:08X}: kind {kind}, every site is CHAIN')
    return B.make_sup(blob, B.SL_HEADER_LEN, SUP_ID_NB if no_bw else SUP_ID,
                      VERSION, min_svc=1), syms


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--no-bw', action='store_true',
                    help='half-press magnification without B&W-while-magnified')
    ap.add_argument('--card', action='store_true',
                    help='a whole v3 card: loader, AutoRun, frames, shell and the sup')
    a = ap.parse_args()
    out = a.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f'{out} is not empty: this never overwrites a build or a card')
    out.mkdir(parents=True, exist_ok=True)
    data, syms = sup_file(no_bw=a.no_bw)
    name = NAME_NB if a.no_bw else NAME
    if a.card:
        vbin, _ = B.loader_bin()
        d = out / B.SL_DIR
        (d / 'UI').mkdir(parents=True)
        (d / B.SL_SELF).write_bytes(vbin)
        (out / 'AutoRun.txt').write_bytes(B.autorun(out))
        for i, px in enumerate(B.splash_frames()):
            (d / 'UI' / f'{i}.BIN').write_bytes(px)
        (d / '00SHELL.BIN').write_bytes(B.shell_sup())
        (d / name).write_bytes(data)
        files = sorted(p for p in out.rglob('*') if p.is_file() and p.name != 'MANIFEST.sha256')
        (out / 'MANIFEST.sha256').write_text(''.join(
            f'{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.relative_to(out)}\n'
            for p in files))
    else:
        (out / name).write_bytes(data)
    (out / 'build.json').write_text(json.dumps({
        'product': 'HpZoom, Loader v3 sup', 'file': name,
        'sup_id': SUP_ID_NB if a.no_bw else SUP_ID, 'version': VERSION,
        'no_bw': a.no_bw, 'card': a.card, 'bytes': len(data),
        'symbols': {k: syms[k] for k in ('entry', 'claims', 'poster_hook', 'cs_hook',
                                         'post_hook', 'cap_machine', 'pre_zoom')
                    if k in syms} | ({'apply_hook': syms['apply_hook'],
                                      'bw_state': syms['bw_state']} if not a.no_bw else {}),
        'sha256': hashlib.sha256(data).hexdigest(),
        'sources': {str(p.relative_to(FPSUP)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (pathlib.Path(__file__), SRC)},
        'written_to_card': False, 'camera_tested': False}, indent=1) + '\n')
    print(f'built {name} ({len(data)} bytes) into {out}')


if __name__ == '__main__':
    main()
