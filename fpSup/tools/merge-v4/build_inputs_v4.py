#!/usr/bin/env python3
"""Build the Loader v4 product snapshot the Merge v4 page reads.

    python3 -B tools/merge-v4/build_inputs_v4.py --out tools/merge-v4/inputs/v4-YYYYMMDD
    python3 -B tools/merge-v4/build_inputs_v4.py --out ... --only sensor-lab,qs-share   # some products only

Runs each product's own v4 builder (nothing is rebuilt by hand), copies the
outputs into a NEW directory and writes manifest.json in the format
build_catalogue_v4.input_products() checks (the same as merge-v3's snapshots):
every file's size and sha256, each product's sup and data files, and the
sha256 of every builder source.  Refuses to overwrite a snapshot.
"""
import argparse, datetime, hashlib, json, pathlib, shutil, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent.parent
ROOT = FPSUP.parent
sys.path.insert(0, str(FPSUP / 'loader-v4'))
import names_v4 as N                                     # noqa: E402  (file names, versions)

# product id -> (builder, its output relative to the builder's --out, extra args)
BUILDS = {
    'ports': ([FPSUP / 'loader-v4/ports.py'], 'fpSup'),
    'jose': ([FPSUP / 'loader-v4/ports_jose.py'], 'fpSup'),
    'loss': ([FPSUP / 'lossless/build_v4_lossless.py'], '.'),
    'flip': ([FPSUP / 'screenflip/build_v4_flip.py'], '.'),
    'rawv': ([ROOT / 'projects/rawview/build/build_v4_rawview.py'], '.'),
    'rescus': ([ROOT / 'projects/open-gate/build/res-custom-v4/build_v4_rescustom.py'], '.'),
    'slqs': ([ROOT / 'projects/sensorlab-imx410/qs/build_slqs.py'], 'fpSup'),
    'qsct': ([ROOT / 'projects/qs-container/build_qsct.py'], 'fpSup'),
    'dial': ([FPSUP / 'dialfix/build_dialfix.py'], 'fpSup'),
}
# product id -> (build, sup_id, data dir or None); the file is names_v4's
# <base>_v<version>.BIN (the user 2026-10-25)
PRODUCTS = {
    'res-custom': ('rescus', 'RCUS', 'RESCUS'),
    'lossless': ('loss', 'LOSS', None),
    'fcap': ('ports', 'FCAP', None),
    'unlocked-writer': ('ports', 'ULWR', None),
    'stopfx': ('ports', 'STFX', None),
    'gyro2': ('ports', 'GYR2', None),
    'raw-view': ('rawv', 'RAWV', None),
    'screenflip': ('flip', 'FLIP', None),
    'desqueeze': ('jose', 'DSQZ', None),
    'tap-to-zoom': ('jose', 'TAPZ', None),
    'usbshell': ('ports', 'SHEL', None),
    # 2026-11-07 (Bei): Sensor Lab-IMX410 and the QS container it needs, renamed QS-Share (sup_id QSCT)
    'sensor-lab': ('slqs', 'SL41', None),
    'qs-share': ('qsct', 'QSCT', None),
    # 2026-11-08 (Bei): Andy_hal9000's rear-wheel decoder v6 as a v4 sup
    'dial-fix': ('dial', 'DIAL', None),
}
SOURCES = [
    'fpSup/loader-v4/ports.py', 'fpSup/loader-v4/ports_jose.py', 'fpSup/loader-v4/build_v4.py',
    'fpSup/loader-v4/names_v4.py',
    'fpSup/fpsup-ui/fpui_stock.c', 'fpSup/fpsup-ui/fpsup_ui.c', 'fpSup/fpsup-ui/build_stock_section.py',
    'fpSup/lossless/build_v4_lossless.py', 'fpSup/lossless/native/menu_row4.c',
    'fpSup/screenflip/build_v4_flip.py', 'fpSup/screenflip/native/flip.c',
    'projects/rawview/build/build_v4_rawview.py', 'projects/rawview/build/build_v3_rawview.py',
    'projects/open-gate/build/res-custom-v4/build_v4_rescustom.py',
    'projects/open-gate/build/res-custom-v4/build_v3_rescustom.py',
    'projects/open-gate/build/res-custom-v4/ogc.c', 'projects/open-gate/build/res-custom-v4/ogc_files.c',
    'projects/sensorlab-imx410/qs/build_slqs.py', 'projects/sensorlab-imx410/qs/slqs.c', 'projects/sensorlab-imx410/qs/qrdec.c',
    'projects/sensorlab-imx410/core/core.c', 'projects/sensorlab-imx410/apply/ap.c', 'projects/sensorlab-imx410/apply/ap_calc.c',
    'projects/qs-container/build_qsct.py', 'projects/qs-container/qsct.c', 'projects/qs-container/qsc.h',
    'projects/qs-container/editor_data.py', 'projects/qs-container/editor_title.py', 'projects/qs-container/qs_page_data.py',
    'fpSup/dialfix/build_dialfix.py', 'fpSup/dialfix/dialfix.c', 'fpSup/dialfix/reference/v6/dial2_fast.S',
    'fpSup/dialfix/reference/v6/AutoRun.txt',
]
VALIDATION = ('fpSup/loader-v4/README.md "已上線 sup 的 v4 第一次上機(2026-10-24)": all eleven load, '
              'menus and saving checked on the camera; recording (ULWR, Gyro2, Lossless compression) not yet.')
VALIDATION_OF = {
    'res-custom': ("projects/open-gate/build/res-custom-v4/test_v4_rescustom.py: 85 tests pass (2026-11-12). Change from 0.1.5: the files page is built with manage_page.row_visible (a watcher under the page root shows / hides each row) and ogc_files.c sends Visible=1 before a row's words, Visible=0 after them; reported and fixed independently by Ruari (2026-11-11). On the camera 2026-11-12 under Loader v4 (LOAD.LOG 0A), 16 format files = 4 pages, the last with one row: paged to 4 and back to 3, 2, 1, every row shown (screenshots). The five .RCD files are 0.1.5's bytes. Not checked: recording, switching a format on / off, the selection across power-off."),
    'sensor-lab': ('projects/sensorlab-imx410/validation/20261105-cpux2-removed: v0.7.39test offline full suite and '
                   'on the camera 2026-11-05 (boot apply, QS and RECIPE display, CPU x2 settings -> ISP HBIN 1); '
                   '0.0.1test = the same body, only the header display name changed (2026-11-07, offline).'),
    'qs-share': ('projects/qs-container v0.3.8 (API 8): offline suites, on the camera with SensorLab v0.7.39test '
                 '2026-11-05; 0.0.1test = the v0.3.8 code with the header display name fixed to "QS-Share" '
                 '(state/DMA offsets 64 B lower); not yet on the camera under this name.'),
    'screenflip': ("fpSup/screenflip/test_v4_flip.py + test_v3_flip.py (the task is created with stksz 0x2000; v3's 40FLIP.BIN keeps 0x1000 and its bytes). On the camera 2026-11-11, loaded under Loader v4: 19 value changes from the TOOLS row (19 saves, 0 failed, file = table each time), 25 STILL/CINE switches (25 applies; 0x30190044 = 0x00333000 at 180, 0 at Off), no freeze; DISP switching checked by hand by Bei. Not checked: a non-Off value across a restart; the old 0x1000 stack's depth was never measured."),
    'dial-fix': ('fpSup/dialfix/test_dialfix.py: 9 unicorn tests (his v6 words = his AutoRun = clang of his .S; '
                 'sup copy and his in-place code reached through the stock edge handlers agree over 600 random steps; '
                 'one click per detent, clockwise +1; the edge register is the one his installer writes) and 12 mutations '
                 'caught (2026-11-10). 0.2.1test on the camera 2026-11-10: loads (LOAD.LOG 0A), the three vtable '
                 'slots and 0x301502E4 read back as expected, one step per click by hand (Bei). 0.2.0test wrote the '
                 'wrong register address and froze on load; it was never offered.'),
}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--only', default='', help='comma-separated product ids (default: all)')
    a = ap.parse_args()
    only = [x for x in a.only.split(',') if x]
    if any(x not in PRODUCTS for x in only):
        raise SystemExit(f'--only: unknown product in {only}; known: {", ".join(PRODUCTS)}')
    chosen = {k: v for k, v in PRODUCTS.items() if not only or k in only}
    builds = {k: v for k, v in BUILDS.items() if any(b == k for b, _s, _d in chosen.values())}
    out = a.out.resolve()
    if out.exists():
        raise SystemExit(f'{out} exists: a snapshot is never overwritten')
    files, products = {}, {}
    with tempfile.TemporaryDirectory(prefix='mergev4-') as t:
        t = pathlib.Path(t)
        for key, (cmd, sub) in builds.items():
            r = subprocess.run([sys.executable, '-B', *map(str, cmd), '--out', str(t / key)],
                               capture_output=True, text=True, cwd=FPSUP)
            if r.returncode:
                raise SystemExit(f'{key}: builder failed\n{r.stderr[-3000:]}')
        out.mkdir(parents=True)
        for pid, (build, sid, data) in chosen.items():
            name = N.file_name(sid)
            src = t / build / BUILDS[build][1]
            b = (src / name).read_bytes()
            (out / name).write_bytes(b)
            files[name] = dict(size=len(b), sha256=sha(b))
            entry = dict(file=name, version=N.version(sid), name=N.display(sid),
                         release=f'fpsup-{pid}-v{N.version(sid)}',
                         build_label=dict(en='Loader v4 test build', zh='Loader v4 測試版'))
            if data:
                (out / data).mkdir()
                entry['data_files'] = []
                for f in sorted((src / data).iterdir()):
                    rel = f'{data}/{f.name}'
                    (out / rel).write_bytes(f.read_bytes())
                    files[rel] = dict(size=f.stat().st_size, sha256=sha(f.read_bytes()))
                    entry['data_files'].append(rel)
            products[pid] = entry
    meta = dict(date=f'{datetime.date.today():%Y-%m-%d}',
                source_sha256={s: sha((ROOT / s).read_bytes()) for s in SOURCES},
                files=files, products=products, loader='v4',
                validation=' '.join(VALIDATION_OF[k] for k in chosen if k in VALIDATION_OF)
                if all(k in VALIDATION_OF for k in chosen) else VALIDATION)
    (out / 'manifest.json').write_text(json.dumps(meta, indent=1, ensure_ascii=False) + '\n')
    for name, f in files.items():
        print(f'{name:28s} {f["size"]:8,d} B  {f["sha256"][:12]}')


if __name__ == '__main__':
    main()
