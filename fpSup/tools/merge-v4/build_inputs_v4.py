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
    'rawv': ([ROOT / 'projects/rawview/build/build_v4_rawview.py', '--cols'], '.'),   # 0.4.0test: a COL-Share client
    'rescus': ([ROOT / 'projects/open-gate/build/res-custom-v4/build_v4_rescustom.py'], '.'),
    'slqs': ([ROOT / 'projects/sensorlab-imx410/qs/build_slqs.py'], 'fpSup'),
    'qsct': ([ROOT / 'projects/qs-container/build_qsct.py'], 'fpSup'),
    'dial': ([FPSUP / 'dialfix/build_dialfix.py'], 'fpSup'),
    'lut': ([FPSUP / 'lut/build_v4_lut.py'], 'fpSup'),
    'cols': ([FPSUP / 'colshare/build_colshare.py'], '.'),
}
# builders whose --out is the file itself, not a folder (build_colshare.py)
OUT_IS_FILE = {'cols': 'COLS'}
# product id -> files beside the sup it always needs (not a choice), relative to the builder's output
SUPPORT = {'lut': ['UI/COLOR.BIN']}
# product id -> (build, sup_id, data dir or None); the file is names_v4's
# <base>_v<version>.BIN (the user 2026-10-25)
PRODUCTS = {
    'res-custom': ('rescus', 'RCUS', 'RESCUS'),
    'lossless': ("fpSup/lossless tests 2026-11-18: test_play_decode 60, test_codec_job 48, test_frame_hold 234, test_tile_grid 6, test_rec_workspace 17, test_rec_hook 14, test_v4_lossless 10, test_card_emulation 35 in the full tree. 0.3.11test = 0.3.7test + in-camera playback in one engine job a frame with the next file read meanwhile; recording code unchanged. These bytes (sha256 180a5f55...) on Bei's camera 2026-11-18, SD, on a card with Sensor Lab 0.0.10test and the other sups Bei carries (COL-Share, Desqueeze, Dial Fix, EarlyFlush, Gyro2, LUT, QS-Share, RAW-View, ScreenFlip, Stop-FX, StorageTest, TapToZoom, UnlockWriter, USB shell): 57 / 61 compressed frames a clip decoded the new way, none refused, every player buffer put back, an uncompressed clip untouched, a take after each playback fine; the picture looked at by Bei. Recording as accepted for 0.3.7test (80 lit and 80 dark takes, projects/sensorlab-imx410/validation/20261117-lossless-stale/LOG.md); four takes recorded with these bytes decode with no repeats. Not checked: the full recording acceptance with these bytes, bright scenes, SSD, long clips, HDMI, clips above UHD size (not viewable in the camera, as before) (validation/20261118-lossless-play/LOG.md)."),
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
    # 2026-11-12 (Bei): LUT, the COL-Share it needs (the COLOR list's rows; RAW-View 0.4 needs it too), and its looks
    'lut': ('lut', 'LUT4', 'LUT'),
    'col-share': ('cols', 'COLS', None),
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
    'fpSup/lut/build_v4_lut.py', 'fpSup/lut/build_sup.py', 'fpSup/lut/checker_q20.bin', 'fpSup/lut/looks/make_looks.py',
    'fpSup/lut/native/lut4.c', 'fpSup/lut/native/lvb.c', 'fpSup/lut/native/jfit.c', 'fpSup/lut/native/conv.c',
    'fpSup/lut/native/import.c', 'fpSup/lut/native/cols.c', 'fpSup/lut/color_ui.py',
    'fpSup/colshare/build_colshare.py', 'fpSup/colshare/colshare.c', 'fpSup/colshare/colshare_ui.py',
]
VALIDATION = ('fpSup/loader-v4/README.md "已上線 sup 的 v4 第一次上機(2026-10-24)": all eleven load, '
              'menus and saving checked on the camera; recording (ULWR, Gyro2, Lossless compression) not yet.')
VALIDATION_OF = {
    'res-custom': ("projects/open-gate/build/res-custom-v4/test_v4_rescustom.py: 78 tests, 76 pass, 2 skipped where the private raw-profiles.json is absent (both pass where it is present) (2026-11-15). 0.1.7 is 0.1.5's source with the files-page paging fix (Visible=1 before a row's words, Visible=0 after them) and without 0.1.6's reload-and-return flow, after which a white screen was reported when switching formats; plus the shared fpsup-ui change (a page pack load waits for the GUI to be idle, then translates). On the camera 2026-11-14/15 under Loader v4 (Bei): no white screen when switching resolution; booting with an SSD attached no longer shows 1474. The five .RCD files are 0.1.5's bytes. Not checked: that the white screen came from the reload flow (inferred from its absence), recording."),
    # 2026-11-12: filled in after the merge-page card's own camera check (README "LUT on the merge page")
    'lut': ('fpSup/lut tests: test_library_native (with the new submenu_width test), test_sup_ui, test_sup_native, colshare/test_colshare OK in the full tree (2026-11-15; test_jfit / test_lvb_native / test_conv_native need the private lv_fit and run only there). 0.1.1test = 0.1.0test + the settings page posts the stock submenu_width = 583 (its popups kept the last stock popup\'s width, 227 after the fpSup page\'s On / Off: labels squeezed) + the shared fpsup-ui change. On Bei\'s camera 2026-11-15 these bytes (with the card\'s own catalogue spliced in): no 1474 at power-on with an SSD. Not checked: the popup width on the camera. Upgrading from 0.1.0test starts with an empty catalogue (the settings live in the versioned BIN).'),
    'col-share': ('fpSup/colshare test_colshare + test_capacity 12 OK; on the camera with LUT 2026-11-11/12 (the names_v4 '
                  'RAW-View probe list was 0.3.1-based then); this file on Bei\'s camera 2026-11-12 with LUT 0.1.0test and RAW-View '
                  '0.4.0test: Bei\'s check passed.'),
    'raw-view': ('projects/rawview/build test_v4_cols_rawview; 0.4.0test was on the camera 2026-11-10 with the 4-row '
                 'COL-Share; with this COL-Share and LUT 0.1.0test on Bei\'s camera 2026-11-12: Bei\'s check passed.'),
    'sensor-lab': ("projects/sensorlab-imx410 offline tiers 2026-11-17. 0.0.10test = 0.0.8test + the video clamp on for every recipe (0.0.9test, never published) + the live-view frame-rate text whole after MENU. These bytes (sha256 e249e93b..., with the card's settings record spliced in) on Bei's camera 2026-11-17/18: 80 lens-capped takes (40 recipes x ISO 100 / 3200, SD) twice, frame-to-frame black deviation <= 0.011 DN12, black - tag <= 0.27 DN12 (validation/20261117-clamp-all, 20261117-lossless-stale/dark037.log). Not checked: SSD, long takes, the frame-rate text by eye on every recipe."),
    'lossless': ("fpSup/lossless tests 2026-11-18: test_codec_job 48, test_frame_hold 234, test_tile_grid 6, test_rec_workspace 17, test_rec_hook 14, test_v4_lossless 10. These bytes (sha256 0464758b...) on Bei's camera 2026-11-18, SD, with Sensor Lab 0.0.10test: 80 lit takes and 80 lens-capped takes (40 recipes x ISO 100 / 3200): every fetched clip decodes, no repeated frames; rasters under 2 MiB 40 of 40 compressed; late-data recipes uncompressed by design; one lit take gave no clip once (not reproduced); 6048-wide 12-bit fast keeps 1-2 frames on SD (projects/sensorlab-imx410/validation/20261117-lossless-stale/LOG.md). Not checked: compressed = uncompressed bit for bit, SSD, long takes, playback in the camera, stock (non Sensor Lab) modes in this run."),
    'qs-share': ("projects/qs-container tests: 134 run, 133 pass, 1 skipped (2026-11-15). Change from 0.0.2test: the shared fpsup-ui only (a page pack load waits for the GUI to be idle, then marks the language stale and translates). On the camera 2026-11-15 (Bei) with this code under the 0.0.2test file name: booting with an SSD attached no longer shows 1474. Not on the camera under the 0.0.3test name."),
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
            dest = t / key / N.file_name(OUT_IS_FILE[key]) if key in OUT_IS_FILE else t / key
            r = subprocess.run([sys.executable, '-B', *map(str, cmd), '--out', str(dest)],
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
            for rel in SUPPORT.get(pid, []):
                (out / rel).parent.mkdir(parents=True, exist_ok=True)
                b = (src / rel).read_bytes()
                (out / rel).write_bytes(b)
                files[rel] = dict(size=len(b), sha256=sha(b))
                entry.setdefault('support_files', []).append(rel)
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
