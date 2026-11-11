#!/usr/bin/env python3
"""LUT for the merge page (Bei 2026-11-12): the product files, nothing else.

    python3 -B fpSup/lut/build_v4_lut.py --out DIR

DIR/fpSup/ gets
  LUT_v<version>.BIN   names_v4 'LUT4'; an empty library (every .cube in \\fpSup\\LUT\\
                       is added on the camera, native/import.c)
  UI/COLOR.BIN         LUT's own manager / settings page (color_ui.py)
  LUT/*.cube           the offered looks (looks/make_looks.py; each carries its input
                       as author lines, so it converts with nothing set)
COL-Share (which owns the COLOR rows) is its own product on the page; the boot
files are the page's.  build.json beside fpSup/ is the build record.
"""
import argparse, hashlib, json, pathlib, shutil, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent
sys.path[:0] = [str(HERE), str(FPSUP / 'loader-v4'), str(HERE / 'looks')]
import names_v4 as N                    # noqa: E402
import build_sup as BS                  # noqa: E402
import make_looks as L                  # noqa: E402

SUP_ID = 'LUT4'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', type=pathlib.Path, required=True)
    a = ap.parse_args()
    out = a.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f'{out} is not empty: this never overwrites a build')
    for name in L.LOOKS:                                   # the committed looks are what make_looks makes
        if (L.HERE / f'{name}.cube').read_bytes() != L.build(name):
            raise SystemExit(f'looks/{name}.cube differs from make_looks.py: rebuild it')
    with tempfile.TemporaryDirectory(prefix='lut4-') as t:
        lib = pathlib.Path(t) / 'library.json'
        lib.write_text(json.dumps(dict(schema='fpsup-lut-library-1', active=None, luts=[])))
        import library
        info = BS.build(pathlib.Path(t) / 'card', collection=library.read(lib), ui=True, colshare=False,
                        product=(BS.SUP_FILE, BS.SUP_NAME, BS.SUP_VERSION))
        out.mkdir(parents=True, exist_ok=True)
        shutil.copytree(pathlib.Path(t) / 'card' / 'fpSup', out / 'fpSup', dirs_exist_ok=True)
    (out / 'fpSup' / 'LUT').mkdir(exist_ok=True)
    for name in L.LOOKS:
        shutil.copyfile(L.HERE / f'{name}.cube', out / 'fpSup' / 'LUT' / f'{name}.cube')
    files = sorted(p for p in (out / 'fpSup').rglob('*') if p.is_file())
    record = dict(product='lut, Loader v4 sup', sup_id=SUP_ID, version=N.version(SUP_ID), file=N.file_name(SUP_ID),
                  files={str(p.relative_to(out)): dict(size=p.stat().st_size,
                                                        sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files},
                  facts={k: info[k] for k in ('file_bytes', 'block_bytes', 'code_bytes')},
                  sources=info['source_hashes'])
    (out / 'build.json').write_text(json.dumps(record, indent=1, ensure_ascii=False) + '\n')
    for p in files:
        print(f'{str(p.relative_to(out)):34s} {p.stat().st_size:10,d} B')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
