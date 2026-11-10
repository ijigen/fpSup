#!/usr/bin/env python3
"""Build fpLossless as a Loader v4 sup: \\fpSup\\LOSS.BIN.

    python3 -B lossless/build_v4_lossless.py --out /absolute/new/directory

The v3 sup (build_v3_lossless.py) with three changes (the user 2026-10-22):
  - the 48-byte FSB4 header, SL_F_CACHED_OK: the core runs it at the cached
    alias, so card.S's own switch to it does nothing;
  - the Lossless-CDNG switch is a TOGGLE row on the fpSup page
    (native/menu_row4.c, svc->page_add) instead of a row composed onto the
    stock CINE page through uishare: no FPUI block, no ui_pool/ui_apply, no
    claim on the three string sites (the v4 core's);
  - the saved ON/OFF record sits at 48 + `settings`, and is written only
    while svc->file_is says the file is still this sup.
Everything recording does is the same code as v3.
"""
import argparse, hashlib, json, pathlib, struct, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent
ROOT = FPSUP.parent
LOADER_V4 = FPSUP / 'loader-v4'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(LOADER_V4))

import build_v3_lossless as L3                           # noqa: E402
import build_card as C                                   # noqa: E402
import build_v4 as B4                                    # noqa: E402
import names_v4 as N                                     # noqa: E402

NAME = N.file_name('LOSS')                               # Lossless_v0.3.0.BIN (names_v4)
SUP_ID = L3.SUP_ID
VERSION = 1
DISPLAY = N.display('LOSS')
V3_ONLY = ('uishare/ui_pool.c', 'uishare/ui_apply.c', 'native/menu_page.c')


def sup_file(tmp):
    """(LOSS.BIN bytes, facts)."""
    units, cflags = list(C.UNITS), list(C.CFLAGS)
    try:
        C.UNITS[:] = [u for u in units if u not in V3_ONLY]
        C.UNITS.insert(C.UNITS.index('native/card.c'), 'native/menu_row4.c')
        C.CFLAGS += ['-DFPL_V4', '-I', str(LOADER_V4)]
        # the display name rides where v3 put the row's FPUI block: after
        # the text, before the state (the C never reads FPL_MENU_OFF under V4)
        blob, facts = L3.build_blob(tmp, DISPLAY.encode().ljust(12, b'\0'), v4=True)
    finally:
        C.UNITS[:], C.CFLAGS[:] = units, cflags
    data = bytearray(B4.make_sup(blob, B4.SL4_HEADER_LEN, SUP_ID, version=VERSION,
                                 block_size=B4.SL4_HEADER_LEN + facts['block_bytes'],
                                 min_svc=5, flags=B4.SL_F_CACHED_OK))
    struct.pack_into('<I', data, 44, B4.SL4_HEADER_LEN + facts['menu_off'])      # name_off
    data = bytes(data)
    return data, facts


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', type=pathlib.Path, required=True)
    a = ap.parse_args()
    out = a.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f'{out} is not empty: this never overwrites a build')
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fpl-v4-') as t:
        data, facts = sup_file(pathlib.Path(t))
    (out / NAME).write_bytes(data)
    sources = [pathlib.Path(__file__), HERE / 'build_v3_lossless.py', HERE / 'build_card.py',
               HERE / 'native' / 'card.S', HERE / 'native' / 'menu_row4.c', HERE / 'native' / 'menu_row4.h',
               LOADER_V4 / 'sloader4.h'] + \
              [HERE / u for u in C.UNITS if u not in V3_ONLY]
    (out / 'build.json').write_text(json.dumps({
        'product': 'fpLossless, Loader v4 sup', 'file': NAME, 'sup_id': SUP_ID, 'version': VERSION,
        'blob': {k: v for k, v in facts.items() if k != 'layout'},
        'sha256': hashlib.sha256(data).hexdigest(),
        'sources': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(set(sources))},
        'written_to_card': False, 'camera_tested': False}, indent=1) + '\n')
    print(f'{NAME}: {len(data)} B, block {B4.SL4_HEADER_LEN + facts["block_bytes"]} B, '
          f'sha256 {hashlib.sha256(data).hexdigest()[:16]}')


if __name__ == '__main__':
    main()
