#!/usr/bin/env python3
"""Build raw-view as a Loader v4 sup: \\fpSup\\RAWV.BIN.

    python3 -B projects/rawview/build/build_v4_rawview.py --out /absolute/new/directory [--cols]

--cols: RAW-View 0.4.0test, a COL-Share client (fpSup/colshare/DESIGN.md P3; tests:
test_v4_cols_rawview.py).  Without it: 0.3.1 as shipped (the merge page still takes that one
until P5 makes COL-Share its dependency).

build_v3_rawview.build(v4=True): the 48-byte FSB4 header with the settings
record right after it (48), SL_F_CACHED_OK, the COLOR row through fpsup-ui's
section (fpui_stock.c: its strings are stock, so no string site and no
borrow), and rv_*.S V4=1 -- stub_sv asks svc->file_is before it writes into
this file, cleans the D-cache first, and uses the file object at the uncached
alias.  Tests: test_v4_rawview.py.
"""
import argparse, hashlib, json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import build_v3_rawview as V                             # noqa: E402
sys.path.insert(0, str(ROOT / 'fpSup' / 'loader-v4'))
import names_v4 as N                                     # noqa: E402

NAME = N.file_name('RAWV')                               # RAW-View_v0.3.0.BIN (names_v4)
DISPLAY = N.display('RAWV').encode() + b'\0'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--cols', action='store_true', help='RAW-View 0.4.0test: a COL-Share client')
    a = ap.parse_args()
    out = a.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f'{out} is not empty: this never overwrites a build')
    data, facts, _ = V.build(v4=True, name=DISPLAY, cols=a.cols)
    name = V.COLS_FILE if a.cols else NAME
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_bytes(data)
    sources = [pathlib.Path(__file__), HERE / 'build_v3_rawview.py', HERE / 'build_rawview.py',
               HERE / 'rv_launch.S', HERE / 'rv_resident.S',
               ROOT / 'fpSup' / 'fpsup-ui' / 'fpui_stock.c', ROOT / 'fpSup' / 'fpsup-ui' / 'build_stock_section.py']
    (out / 'build.json').write_text(json.dumps({
        'product': 'raw-view, Loader v4 sup' + (' (COL-Share client)' if a.cols else ''), 'file': name,
        'sup_id': V.SUP_ID, 'version': V.COLS_VERSION if a.cols else V.VERSION,
        'sha256': hashlib.sha256(data).hexdigest(), 'facts': facts,
        'sources': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sources}}, indent=1, ensure_ascii=False) + '\n')
    print(f'{name}  {len(data)} B  block {facts["block"]:#x}  claims {facts["claims"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
