#!/usr/bin/env python3
"""fpSup-Merge v4: build the merge page for Loader v4 cards.

    python3 -B tools/merge-v4/build_catalogue_v4.py       writes tools/merge-v4/index.html

A Loader v4 card (fpSup/loader-v4/README.md):

    AutoRun.txt + fpSup/LOADER.BIN   the boot pair, one of four (Instant / Fast)
    fpSup/UI/0..4.BIN                the splash
    fpSup/SUPMGR.BIN, fpSup/UI/FPSUP.BIN, fpSup/UI/SUPMGR.BIN
                                     the fpSup page and SupManager -- on every
                                     card: Lossless's switch and Res-Custom's
                                     file page live on the fpSup page (user
                                     2026-10-24: with the page off some sups
                                     cannot be used)
    fpSup/NAME.BIN                   one per product (FSB4), loaded in name order

Every product comes from one manifest-checked snapshot that
build_inputs_v4.py makes with the products' own v4 builders.  v3 releases are
not read for products; they stay the version history.  The boot pairs are
built here from fpSup/loader-v4/build_v4.py.  The v3 page (tools/merge-v3)
is not changed by this one.
"""
import argparse, base64, hashlib, json, pathlib, re, struct, sys

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent.parent
RELEASES = FPSUP / 'releases'
TEMPLATE = HERE / 'template.html'
GUIDE = FPSUP / 'guide'
OUT = HERE / 'index.html'
INPUTS = [HERE / 'inputs' / 'v4-20261027']
sys.path.insert(0, str(FPSUP / 'fp_usb_shell'))
from v3 import build_v3 as V3
sys.path.insert(0, str(FPSUP / 'loader-v4'))
import build_v4 as B4
import names_v4 as N        # display / file names and versions (the user 2026-10-25)
from release_history import attach_history

SPLASH = [f'fpSup/UI/{i}.BIN' for i in range(5)]
MANAGER = ['fpSup/SUPMGR.BIN', 'fpSup/UI/FPSUP.BIN', 'fpSup/UI/SUPMGR.BIN']

# product -> page metadata. Development Res tools are separate manifest-checked
# snapshots; frozen releases are never rewritten to add virtual RCD support.
#
# category: the page's sections, in CATEGORIES order.
# excl: pairs whose claims collide.  Symmetric (checked below).  The page still
#   lets both onto the card -- the one not chosen goes on as fpSup/NAME.OFF,
#   which the loader (it lists *.BIN only) skips; renaming .OFF <-> .BIN
#   switches which one runs (user 2026-10-07).
# summary: the tile's one line -- what it does, never how to use it or its
#   caveats (user 2026-10-07); those live on the guide page behind the link.
# author / credits: shown on the tile and written into the card's README.
#   author is left empty for the site's own sups (user 2026-10-07: they are
#   mine, no need to say so); set it only for a sup someone else wrote.
#   credits are people whose work the sup builds on, not its authors.  Keep
#   them in step with the guide page's "Thank you" box (test checks it).
CATEGORIES = ['format', 'focus', 'motion', 'monitor', 'development']
# the page shows sups in this order (user 2026-10-07); the card's load order is
# still the file names'
ORDER = ['res-custom', 'res-lab', 'lossless', 'fcap', 'unlocked-writer', 'stopfx', 'split-record', 'hdrx', 'af', 'gyro2', 'raw-view', 'screenflip', 'desqueeze', 'tap-to-zoom', 'lut', 'usbshell']
AUTHOR = ''
PRODUCTS = {
    # og3k / og2k: not this round (user 2026-10-07) -- the OG line ships as
    # res-custom.  Their v3 drafts in releases/ are not to be offered.
    # res-custom carries data files in fpSup/RESCUS/ (one .RCD per format); the
    # user picks which go on the card.  Its excl names products not on this page
    # (old OG cards, Jose's 31FMT, res-lab): kept so the list is complete when
    # one of them is added.  Preliminary -- sigmafp-re-70, 2026-10-07.
    'res-custom': dict(name=N.display('RCUS'), sup_id='RCUS',
                       summary=dict(en='Custom recording resolutions in one sup: open gate OG2K, OG3K, OG3.5K, OG4K and S16.',
                                    zh='多種自訂錄影解析度合一:Open Gate OG2K、OG3K、OG3.5K、OG4K 與 S16。'), category='format', file=N.file_name('RCUS'),
                       excl=['og3k', 'og2k', 'formats'],
                       data=dict(dir='RESCUS', ext='.RCD',
                                 names={'OG35K': 'OG3.5K'},
                                 # per-format author shown on its chip (user 2026-10-13)
                                 authors={k: 'Jose Hurtado' for k in ('OG35K', 'OG4K', 'S16')},
                                 # chip order on the page (user 2026-10-13); others after, by name
                                 order=['OG2K', 'OG3K', 'OG35K', 'OG4K', 'S16']),
                       author=AUTHOR, credits=['Jose Hurtado'],
                       pending=True),
    'res-lab': dict(name='RES-Lab', sup_id='RLAB', category='format', file='50RES-Lab v0.1.0test.BIN',
                    excl=[], requires=['res-custom'], needs_manager=True, pending=True, stage='dev',  # user 2026-10-13: in development, not selectable
                    summary=dict(en='Adjust the sensor readout, crop and recording size with a live diagram, and save custom formats.',
                                 zh='搭配示意圖調整感光元件讀取方式、裁切與錄影尺寸，並可保存自訂格式。'),
                    author=AUTHOR, credits=[]),
    # links: ticking this tile also ticks those (user 2026-10-15: Lossless
    # ticks FCAP -- without it a compressed take stops at ~94 frames, the
    # stock batch waiting for 128 files -- but FCAP can still be unticked;
    # unlike requires, which RES-Lab uses for Res-Custom and which holds).
    'lossless':   dict(name=N.display('LOSS'), sup_id='LOSS', file=N.file_name('LOSS'),
                       summary=dict(en="Record smaller CinemaDNG files with lossless compression, preserving image quality.",
                                    zh='錄製容量更小、畫質不變的無損壓縮 CinemaDNG。'), category='format', excl=[],
                       links=['fcap'], author=AUTHOR, credits=['CorNy']),
    # projects/rec-core/fcap: the stock writer sends a batch of files at 64 MiB
    # or 128 files; FCAP makes it 40 files, so small (compressed) frames never
    # fill the 96-slot descriptor pool. Full-size RAW batches still close at
    # 64 MiB first and are unchanged.
    'fcap':       dict(name=N.display('FCAP'), sup_id='FCAP', file=N.file_name('FCAP'),
                       summary=dict(en='Writes small frames to the card sooner, so long compressed or small-format takes do not stop early. Needed by Lossless.',
                                    zh='讓小幀更早寫入記憶卡，壓縮或小尺寸格式的長錄影不會提早停止。Lossless 需要它。'),
                       category='format', excl=[], author=AUTHOR, credits=[]),
    # projects/rec-core/writer: the stock batch write, sent by our own task
    # without the FS lock (SD and SSD alike).  No links: whether Lossless
    # should tick it is the user's call (lossless-sup, 2026-10-15).
    'unlocked-writer': dict(name=N.display('ULWR'), sup_id='ULWR', file=N.file_name('ULWR'),
                       summary=dict(en='Writes recordings to the SD card or SSD without holding the file-system lock, so the camera keeps working while the card is written. SD card: on by itself (Video Speed Class and CMD20 are detected). SSD: works only with Write Mode turned on.',
                                    zh='寫卡時不握檔案系統鎖，寫入 SD 卡或 SSD 的同時，相機照常處理後續畫格。SD 卡自動生效(自動辨識 Video Speed Class 與 CMD20);SSD 要開啟 Write Mode 才會生效。'),
                       category='format', excl=[], author=AUTHOR, credits=[]),
    'stopfx':     dict(name=N.display('STFX'), sup_id='STFX', file=N.file_name('STFX'),
                       summary=dict(en='Helps the camera clear pending frames after an abnormal recording stop. Use alone or with Lossless.',
                                    zh='幫助相機在異常停錄後清理暫存影格，可單獨或搭配 Lossless 使用。'),
                       category='format', excl=[], author='Ruari', credits=[]),
    'raw-view':   dict(name=N.display('RAWV'), sup_id='RAWV', file=N.file_name('RAWV'),
                       summary=dict(en='The screen shows the RAW about to be recorded: what clips on screen clips in the DNG.',
                                    zh='螢幕顯示即將錄下的 RAW:畫面上過曝的地方，錄下來就是過曝。'), category='monitor', excl=[], author=AUTHOR, credits=['Ole Berek', 'Luka']),
    'screenflip': dict(name=N.display('FLIP'), sup_id='FLIP', file=N.file_name('FLIP'),
                       summary=dict(en='Flip the rear screen 180°, mirror it, or both.',
                                    zh='背螢幕翻轉 180°、左右鏡像，或兩者。'), category='monitor', excl=[], author=AUTHOR, credits=[]),
    # Jose Hurtado's original Loader v3 releases, kept byte-for-byte.
    'desqueeze': dict(name=N.display('DSQZ'), sup_id='DSQZ', file=N.file_name('DSQZ'), category='monitor', excl=[],
                      summary=dict(en='Anamorphic preview at 1.33x, 1.6x or 2.0x, with scaled frame guides and an amber indicator. Recorded files are unchanged.',
                                   zh='變形鏡頭預覽以 1.33x、1.6x 或 2.0x 還原比例，構圖線跟著縮放並顯示琥珀色標記；錄下的檔案不變。'),
                      author='Jose Hurtado', credits=[]),
    'tap-to-zoom': dict(name=N.display('TAPZ'), sup_id='TAPZ', file=N.file_name('TAPZ'), category='monitor', excl=[],
                        summary=dict(en='Tap the LCD to zoom around that point; dials select 2x, 4x or 8x and the next tap restores the full frame. Works while recording.',
                                     zh='輕觸 LCD，以該點為中心放大；轉盤可選 2x、4x 或 8x，再點一次還原全畫面。錄影中也可使用。'),
                        author='Jose Hurtado', credits=[]),
    'gyro2':      dict(name=N.display('GYR2'), sup_id='GYR2',
                       summary=dict(en='Gyro data inside every CinemaDNG frame; stabilise in DaVinci Resolve with the Gyroflow plugin (fpSup build).',
                                    zh='把陀螺儀資料寫進每一格 CinemaDNG,用 Gyroflow 的 DaVinci Resolve 插件(fpSup 版)防震。'), category='motion', excl=[], file=N.file_name('GYR2'),
                       author=AUTHOR, credits=[],
                       pending=True),
    # In development (user 2026-10-07: show what is coming).  stage='dev' tiles
    # are greyed and say so; they have no release and cannot be ticked.
    'split-record': dict(name='Split Record', category='format', excl=[], stage='dev', pending=True,
                       summary=dict(en='Records CinemaDNG to the SD card and an SSD at once, splitting the frames between them.',
                                    zh='CinemaDNG 同時寫進 SD 卡與 SSD,把畫格分流到兩邊。'),
                       author=AUTHOR, credits=[]),
    'hdrx':       dict(name='HDRx', category='format', excl=[], stage='dev', pending=True,
                       summary=dict(en='Records alternating normal and short exposures, merged in post for a wider dynamic range.',
                                    zh='交替錄下正常與短曝光的畫格，後製合成更寬的動態範圍。'),
                       author=AUTHOR, credits=[]),
    # projects/fp-af-assist; stage 'long' = long-term development
    'af':         dict(name='AF Optimisation', category='focus', excl=[], stage='long', pending=True,
                       summary=dict(en='Better in-camera continuous autofocus while recording in CINE.',
                                    zh='改善 CINE 錄影時的機內連續自動對焦。'),
                       author=AUTHOR, credits=[]),
    'lut':        dict(name='LUT', category='monitor', excl=[], stage='dev', pending=True,
                       summary=dict(en='Load a .cube LUT and see its look simulated on the screen; recorded files are unchanged.',
                                    zh='讀取 .cube LUT,在螢幕上模擬還原調色後的樣子;錄下的檔案不變。'),
                       author=AUTHOR, credits=[]),
    'usbshell':   dict(name=N.display('SHEL'), sup_id='SHEL', file=N.file_name('SHEL'),
                       summary=dict(en='A development tool: commands and memory access to the camera over USB.',
                                    zh='開發工具：透過 USB 對相機下指令、讀寫記憶體。'), category='development', excl=[], author=AUTHOR, credits=[]),
}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def embedded(files):
    return [dict(path=rel, size=len(b), sha256=sha(b), data=base64.b64encode(b).decode())
            for rel, b in files.items()]


def boot_options():
    """The splash, the fpSup page / SupManager files, and the four boot pairs
    (Instant x Fast) from fpSup/loader-v4/build_v4.py -- the same switches the
    card built for the 2026-10-24 camera test used (splash, slim, the pages)."""
    splash = dict(zip(SPLASH, V3.splash_frames()))
    variants = {}
    for instant in (False, True):
        for fast in (False, True):
            ar, loader, info = B4.boot_card(splash=True, instant=instant, fast=fast, slim=True, ui=True)
            variants[f'm1i{int(instant)}f{int(fast)}'] = dict(info=dict(info, manager=True),
                                                             files=embedded({'AutoRun.txt': ar, 'fpSup/LOADER.BIN': loader}))
    pages = B4.ui_files()
    manager = {'fpSup/SUPMGR.BIN': B4.supmgr_sup(), 'fpSup/UI/FPSUP.BIN': pages['FPSUP.BIN'],
               'fpSup/UI/SUPMGR.BIN': pages['SUPMGR.BIN']}
    if sorted(pages) != ['FPSUP.BIN', 'SUPMGR.BIN']:
        raise SystemExit(f'unexpected fpSup page files: {sorted(pages)}')
    default = variants['m1i1f0']['files']
    sources = [FPSUP / 'loader-v4' / p for p in
               ['build_v4.py', 'sloader4.c', 'sloader4.h', 'sloader4_entry.S', 'fpsup_home.c', 'supmgr.c']]
    sources += [FPSUP / 'fp_usb_shell' / p for p in
                ['build_autorun.py', 'asm/loader.S', 'asm/stage2.S', 'asm/store_boot.S', 'asm/store_boot_slim.S',
                 'asm/abort.S', 'asm/splash_finish.S', 'asm/lhook_stub.S']]
    sources += list((FPSUP / 'uishare/tab').glob('*.py')) + list((FPSUP / 'fpsup-ui').glob('*.c'))
    return default + embedded(splash), dict(default=dict(instant=True, fast=False, manager=True), variants=variants,
                                            manager_files=embedded(manager),
                                            sources={str(p.relative_to(FPSUP)): sha(p.read_bytes()) for p in sources})


def input_products(directory):
    """Read exact development snapshots; require every recorded file hash.
    They are selectable builds, not a published version or a release rewrite.
    """
    if directory is None:
        return []
    meta = json.loads((directory / 'manifest.json').read_text())
    verified = {}
    for rel, expected in meta['files'].items():
        if pathlib.PurePosixPath(rel).is_absolute() or '..' in pathlib.PurePosixPath(rel).parts:
            raise SystemExit('invalid snapshot path: ' + rel)
        b = (directory / rel).read_bytes()
        if len(b) != expected['size'] or sha(b) != expected['sha256']:
            raise SystemExit('snapshot does not match manifest: ' + rel)
        verified[rel] = b
    def sup_file(rel, expected_sid):
        b = verified[rel]
        magic, hlen, flen, block, entry, sid, version, service = struct.unpack_from('<8I', b)
        if (magic != B4.SL4_MAGIC or hlen != B4.SL4_HEADER_LEN or flen != len(b) or block < flen or
                not hlen <= (entry & ~1) < flen or sid.to_bytes(4, 'little') != expected_sid.encode() or
                service > B4.SL4_LOADER_SVC):
            raise SystemExit('invalid snapshot sup: ' + rel)
        return dict(size=len(b), sha256=sha(b), data=base64.b64encode(b).decode()), version
    out = []
    for key, entry in meta['products'].items():
        spec = PRODUCTS[key]
        payload, version = sup_file(entry['file'], spec['sup_id'])
        filename = pathlib.PurePosixPath(entry['file'])
        # the snapshot's name and version (names_v4, 2026-10-25) when it carries them
        name = entry.get('name') or (filename.stem.lstrip('0123456789') if key == 'res-lab' else spec['name'])
        p = dict(id=key, name=name, category=spec['category'], file=filename.name, sup_id=spec['sup_id'],
                 excl=list(spec['excl']), requires=spec.get('requires', []), links=spec.get('links', []), needs_manager=spec.get('needs_manager', False),
                 author=spec['author'], credits=spec['credits'], release=entry.get('release', f'fpsup-{key}-dev-r{version}'),
                 version=entry.get('version', str(version)),
                 build_label=entry.get('build_label', dict(en='Development build', zh='開發版')), date=meta['date'], about=spec['summary'], guide=guide(key),
                 provenance=dict(manifest=str(directory.relative_to(HERE) / 'manifest.json') if directory.is_relative_to(HERE) else str(directory / 'manifest.json'),
                                 source_sha256=meta['source_sha256']), data_files=[], support_files=[], **payload)
        for rel in entry.get('data_files', []):
            b = verified[rel]
            target = 'fpSup/RESCUS/' + pathlib.PurePosixPath(rel).name
            p['data_files'].append(dict(label=label(spec, target), author=data_author(spec, target), **embedded({target:b})[0]))
        for rel in entry.get('support_files', []):
            target = 'fpSup/RESCUS/' + pathlib.PurePosixPath(rel).name
            p['support_files'] += embedded({target:verified[rel]})
        p['data_files'].sort(key=lambda d: data_rank(spec, d['path']))
        if entry.get('virtual'):
            p['virtual'], _ = sup_file(entry['virtual'], 'RCUS')
        out.append(p)
    return out


def label(spec, rel):
    stem = pathlib.PurePosixPath(rel).stem
    return spec['data'].get('names', {}).get(stem, stem)


def data_rank(spec, rel):
    order, stem = spec['data'].get('order', []), pathlib.PurePosixPath(rel).stem
    return (order.index(stem) if stem in order else len(order), rel)


def data_author(spec, rel):
    return spec['data'].get('authors', {}).get(pathlib.PurePosixPath(rel).stem, '')


def guide(key):
    """The tile's details are the site's illustrated guide page, nothing else
    (user 2026-10-07: no README text on the page).  '' when it has none yet."""
    return f'../../guide/{key}.html' if (GUIDE / f'{key}.html').exists() else ''


def main():
    global RELEASES, OUT
    ap = argparse.ArgumentParser()
    ap.add_argument('--releases', type=pathlib.Path, help='version history from here (tests)')
    ap.add_argument('--out', type=pathlib.Path)
    ap.add_argument('--inputs', type=pathlib.Path, action='append', help='manifest-checked snapshot (repeat for separate products)')
    a = ap.parse_args()
    RELEASES = a.releases or RELEASES
    OUT = a.out or OUT
    inputs = a.inputs if a.inputs is not None else INPUTS
    for k, spec in PRODUCTS.items():
        if k not in ORDER:
            raise SystemExit(f'{k}: not in ORDER')
        if not (spec.get('summary', {}).get('en') and spec['summary'].get('zh')):
            raise SystemExit(f'{k}: needs summary en + zh')
        for o in spec['excl']:
            if o in PRODUCTS and k not in PRODUCTS[o]['excl']:
                raise SystemExit(f'excl not symmetric: {k} -> {o}')

    snapshots = [p for directory in inputs for p in input_products(directory)
                 if PRODUCTS[p['id']].get('stage') not in ('dev', 'long')]
    if len({p['id'] for p in snapshots}) != len(snapshots):
        raise SystemExit('duplicate product in input snapshots')
    if not snapshots:
        raise SystemExit('no v4 product found')
    for p in snapshots:
        if p['category'] not in CATEGORIES:
            raise SystemExit(f"{p['id']}: category {p['category']!r} not in CATEGORIES")
        p['loader'] = 'v4'
    products = snapshots
    have = {p['id'] for p in products}
    skipped = [k for k in PRODUCTS if k not in have]
    # shown greyed out, not selectable: the user wants to see what is coming
    pending = [dict(id=k, name=spec['name'], category=spec['category'], file=spec.get('file', ''),
                    author=spec['author'], credits=list(spec['credits']), about=spec['summary'],
                    stage=spec.get('stage', 'unreleased'), guide=guide(k))
               for k, spec in PRODUCTS.items() if k not in have and spec.get('pending')]

    # Simplified Chinese = the Traditional text through the site's own character
    # table (assets/lang.js), so there is still only one Chinese text to keep.
    lj = (FPSUP / 'assets' / 'lang.js').read_text(encoding='utf-8')
    body = lj[lj.index('var MAP = {'):lj.index('};', lj.index('var MAP = {'))]
    t2s = dict(re.findall(r'"(.)":"(.)"', body))
    if len(t2s) < 500:
        raise SystemExit(f'assets/lang.js: only {len(t2s)} characters in MAP')
    boot_shared, boot = boot_options()
    cat = dict(categories=CATEGORIES, t2s=t2s, shared=boot_shared, boot=boot,
               products=sorted(products, key=lambda p: p['file']),
               pending=sorted(pending, key=lambda p: p['file']),
               order=ORDER, loader_svc=B4.SL4_LOADER_SVC)
    attach_history(cat, RELEASES)
    page = TEMPLATE.read_text(encoding='utf-8')
    if page.count('@@CATALOGUE@@') != 1:
        raise SystemExit('template.html must hold @@CATALOGUE@@ exactly once')
    # </script> cannot occur in base64 or in the ABOUT text we embed, but guard anyway.
    blob = json.dumps(cat, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    OUT.write_text(page.replace('@@CATALOGUE@@', blob), encoding='utf-8')

    print(f'wrote {OUT} ({OUT.stat().st_size:,} B)')
    for p in cat['products']:
        print(f"  {p['file']:<12} {p['release']:<36} {p['size']:>7,} B  {p['sha256'][:12]}")
    noguide = [p['id'] for p in cat['products'] + cat['pending'] if not p['guide']]
    if noguide:
        print('  no guide page (fpSup/guide/<id>.html) yet:', ', '.join(noguide))
    if skipped:
        print('  not in the v4 snapshot:', ', '.join(skipped))
    print('  boot pairs: ' + ' '.join(f"{k}={v['files'][1]['sha256'][:8]}" for k, v in boot['variants'].items()))


if __name__ == '__main__':
    main()
