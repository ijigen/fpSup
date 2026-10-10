#!/usr/bin/env python3
"""Build LExpo as a Loader v3 sup: \\fpSup\\30LEXPO.BIN.

    python3 -B lexpo/build_v3_lexpo.py --out /absolute/new/directory [--card]

LExpo widens the manual shutter-speed range past 30 s: in M and S modes the
dial natively offers 40" to 500" (the firmware's own ladder, strings and
playback formatting included).  See projects/lexpo-sup.md.

The whole mod is one word.  The shutter-speed property's read-back refresh
(0xC009FEF0) validates the cell against a computed slow bound; in stills
modes that bound is the fallback default loaded at 0xC007F324, a
`movw ip, #0x96f4` addressing the {30,1} entry of the ROM defaults table.
The entry at 0xC07396FC is {500,1} -- the ladder top.  Patching the movw
immediate to #0x96fc widens the bound; the picker list (bounded by the same
getter) then offers 40"…500".  A one-shot live-view hook (lexpo_inner.S)
runs the camera's own picker refresh (rebuild + list-changed event) on the
first LV frame: the picker's boot-time build predates the sup, and the dial
widget caches the list count at creation, so a load-time rebuild alone
leaves the dial capped until the mode is re-selected.

--out DIR writes DIR/30LEXPO.BIN and build.json.  --card makes DIR a whole
v3 card instead (AutoRun.txt, fpSup/LOADER.BIN, fpSup/UI/, fpSup/00SHELL.BIN
and the sup, MANIFEST.sha256).  It never writes a camera card.
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

NAME = '30LEXPO.BIN'
SUP_ID, VERSION = 'LXPO', 1

SITE = 0xC007F324
STOCK = 0xE309C6F4       # movw ip, #0x96f4  ->  {30,1}  at 0xC07396F4
PATCHED = 0xE309C6FC     # movw ip, #0x96fc  ->  {500,1} at 0xC07396FC


def sup_file():
    """The sup bytes.  EXCL: a data patch cannot layer, and a conflict must
    refuse cleanly rather than overwrite another sup's word.  The inner entry
    (lexpo_inner.S) runs after the write and force-rebuilds the stills
    shutter-speed list: the picker's boot-time build predates the sup."""
    if B.stock(SITE, 4) != struct.pack('<I', STOCK):
        raise B.BuildError(f'0x{SITE:08X}: image word is not the stock '
                           f'0x{STOCK:08X} (wrong firmware?)')
    inner = assemble(HERE / 'lexpo_inner.S')
    entry = symbols(HERE / 'lexpo_inner.S')['inner_entry']
    return B.patch_sup(SUP_ID, [(SITE, struct.pack('<I', PATCHED), 2)],
                       inner, entry, version=VERSION)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--card', action='store_true',
                    help='a whole v3 card: loader, AutoRun, frames, shell and the sup')
    a = ap.parse_args()
    out = a.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f'{out} is not empty: this never overwrites a build or a card')
    out.mkdir(parents=True, exist_ok=True)
    data = sup_file()
    if a.card:
        vbin, _ = B.loader_bin()
        d = out / B.SL_DIR
        (d / 'UI').mkdir(parents=True)
        (d / B.SL_SELF).write_bytes(vbin)
        (out / 'AutoRun.txt').write_bytes(B.autorun(out))
        for i, px in enumerate(B.splash_frames()):
            (d / 'UI' / f'{i}.BIN').write_bytes(px)
        (d / '00SHELL.BIN').write_bytes(B.shell_sup())
        (d / NAME).write_bytes(data)
        files = sorted(p for p in out.rglob('*') if p.is_file() and p.name != 'MANIFEST.sha256')
        (out / 'MANIFEST.sha256').write_text(''.join(
            f'{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.relative_to(out)}\n'
            for p in files))
    else:
        (out / NAME).write_bytes(data)
    (out / 'build.json').write_text(json.dumps({
        'product': 'LExpo, Loader v3 sup', 'file': NAME,
        'sup_id': SUP_ID, 'version': VERSION, 'card': a.card, 'bytes': len(data),
        'patch': {'address': SITE, 'stock': STOCK, 'patched': PATCHED},
        'sha256': hashlib.sha256(data).hexdigest(),
        'sources': {str(p.relative_to(FPSUP)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (pathlib.Path(__file__),)},
        'written_to_card': False, 'camera_tested': False}, indent=1) + '\n')
    print(f'built {NAME} ({len(data)} bytes) into {out}')


if __name__ == '__main__':
    main()
