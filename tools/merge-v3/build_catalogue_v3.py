#!/usr/bin/env python3
"""fpSup-Merge v3: build the merge page for Loader v3 cards.

    python3 tools/merge-v3/build_catalogue_v3.py          writes tools/merge-v3/index.html

A Loader v3 card is a folder, not one BIN (projects/usb-shell-sup/notes/LOADER_V3.md):

    AutoRun.txt          identical in every v3 release
    fpSup/LOADER.BIN     identical in every v3 release
    fpSup/UI/0..4.BIN    identical in every v3 release
    fpSup/NNNAME.BIN     one per product; the loader loads them in name order

so merging is copying the products' fpSup/ folders together.  Nothing is
relocated or patched, and a sup whose claims collide with an earlier one
releases itself at boot without writing a firmware word.  The page still
refuses the pairs that would only ever end that way (EXCL below).

This builder reads the newest frozen v3 release of every product in PRODUCTS,
checks each file against its MANIFEST.txt, refuses if the shared files differ
between the releases it picked, and embeds the bytes in template.html.  The
page re-hashes every file of the zip against these hashes before it offers
the download.  The old fpSup.BIN page (tools/card-composer) is left alone.
"""
import argparse, base64, datetime, hashlib, json, pathlib, re, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent.parent
RELEASES = FPSUP / 'releases'
TEMPLATE = HERE / 'template.html'
GUIDE = FPSUP / 'guide'
OUT = HERE / 'index.html'
# The site's fpSup-Merge address is tools/card-composer/ (user 2026-10-08): the same
# page is written there too; the older page lives in tools/card-composer/legacy/.
SITE_COPY = HERE.parent / 'card-composer' / 'index.html'

SHARED = ['AutoRun.txt', 'fpSup/LOADER.BIN'] + [f'fpSup/UI/{i}.BIN' for i in range(5)]
SUP_RE = re.compile(r'^[0-9]{2}[A-Z0-9]{1,6}\.BIN$')

# product -> page metadata.  Only listed products appear: res-lab is left out
# (single-card, user 2026-10-07: not in this round).
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
ORDER = ['res-custom', 'lossless', 'split-record', 'hdrx', 'af', 'gyro2', 'raw-view', 'screenflip', 'lut', 'usbshell']
AUTHOR = ''
PRODUCTS = {
    # og3k / og2k: not this round (user 2026-10-07) -- the OG line ships as
    # res-custom.  Their v3 drafts in releases/ are not to be offered.
    # res-custom carries data files in fpSup/RESCUS/ (one .RCD per format); the
    # user picks which go on the card.  Its excl names products not on this page
    # (old OG cards, Jose's 31FMT, res-lab): kept so the list is complete when
    # one of them is added.  Preliminary -- sigmafp-re-70, 2026-10-07.
    'res-custom': dict(name='Res-Custom',
                       summary=dict(en='Custom recording resolutions in one sup: open gate OG2K, OG3K, OG3.5K, OG4K and S16.',
                                    zh='多種自訂錄影解析度合一:Open Gate OG2K、OG3K、OG3.5K、OG4K 與 S16。'), category='format', file='32RESCUS.BIN',
                       excl=['og3k', 'og2k', 'formats', 'res-lab'],
                       data=dict(dir='RESCUS', ext='.RCD',
                                 names={'OG35K': 'OG3.5K'}),
                       author=AUTHOR, credits=['Vitaly Li (the first open gate on the fp)',
                                               'Jose Hurtado (the S16, OG3.5K and OG4K formats, used with his permission; the one-core, row-per-format design, the greyed-out options and the video clamp)'],
                       pending=True),
    'lossless':   dict(name='Lossless',
                       summary=dict(en="Lossless-compressed CinemaDNG, by the camera's own hardware codec.",
                                    zh='用相機內建的硬體編碼器錄無損壓縮 CinemaDNG。'), category='format', excl=[], author=AUTHOR, credits=['CorNy (found that a mixed clip needs its first frame uncompressed)']),
    'raw-view':   dict(name='RAW-View',
                       summary=dict(en='The screen shows the RAW about to be recorded: what clips on screen clips in the DNG.',
                                    zh='螢幕顯示即將錄下的 RAW:畫面上過曝的地方，錄下來就是過曝。'), category='monitor', excl=[], author=AUTHOR, credits=['Ole Berek (display curves from his SIGMA fp Rec709 LUT & Operations Guide)',
                                'Luka (found and derived the CinemaDNG colour-tag fix at Saturation +0.2)']),
    'screenflip': dict(name='ScreenFlip',
                       summary=dict(en='Flip the rear screen 180°, mirror it, or both.',
                                    zh='背螢幕翻轉 180°、左右鏡像，或兩者。'), category='monitor', excl=[], author=AUTHOR, credits=[]),
    'gyro2':      dict(name='Gyro2',
                       summary=dict(en='Gyro data inside every CinemaDNG frame; stabilise in DaVinci Resolve with the Gyroflow plugin (fpSup build).',
                                    zh='把陀螺儀資料寫進每一格 CinemaDNG,用 Gyroflow 的 DaVinci Resolve 插件(fpSup 版)防震。'), category='motion', excl=[], file='20GYR2.BIN',
                       author=AUTHOR, credits=['Gyroflow (the stabilisation, and the Resolve plugin it is built on)'],
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
    'usbshell':   dict(name='Shell',
                       summary=dict(en='A development tool: commands and memory access to the camera over USB.',
                                    zh='開發工具：透過 USB 對相機下指令、讀寫記憶體。'), category='development', excl=[], author=AUTHOR, credits=[]),
}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def version_key(q):
    """Same ordering as card-composer: numbers as numbers, then plain >
    one-letter revision > word suffix."""
    nums = tuple(int(n) for n in re.findall(r'\d+', q))
    tail = re.sub(r'^[\d.]*', '', q)
    return (nums, 2 if not tail else (1 if len(tail) == 1 else 0), tail)


def version_of(d):
    return re.split(r'-v(?=\d)', d.name, maxsplit=1)[1]


def latest_v3(product):
    """Newest fpsup-<product>-v*/ that is a v3 card (has fpSup/LOADER.BIN).
    Drafts (_draft-*) never match the glob."""
    found = [(version_key(version_of(d)), d) for d in RELEASES.glob(f'fpsup-{product}-v*')
             if d.is_dir() and (d / 'fpSup' / 'LOADER.BIN').is_file()]
    return max(found)[1] if found else None


def manifest(d):
    """{path: sha256} from MANIFEST.txt."""
    out = {}
    for line in (d / 'MANIFEST.txt').read_text(encoding='utf-8').splitlines():
        m = re.match(r'^(\S+)\s+[\d,]+B\s+sha256=([0-9a-f]{64})$', line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def updated(d, sup):
    """The release's date, YYYY-MM-DD: the last commit touching its folder,
    or -- while it is not committed yet -- the sup file's mtime.  (A fresh
    checkout resets mtimes, so the commit date wins whenever there is one.)"""
    try:
        out = subprocess.run(['git', 'log', '-1', '--format=%cs', '--', '.'], cwd=d,
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ''
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', out):
        return out
    return datetime.date.fromtimestamp((d / 'fpSup' / sup).stat().st_mtime).isoformat()


def label(spec, rel):
    stem = pathlib.PurePosixPath(rel).stem
    return spec['data'].get('names', {}).get(stem, stem)


def guide(key):
    """The tile's details are the site's illustrated guide page, nothing else
    (user 2026-10-07: no README text on the page).  '' when it has none yet."""
    return f'../../guide/{key}.html' if (GUIDE / f'{key}.html').exists() else ''


def load(product, d, spec):
    """(sup name, {path: bytes}, [data file paths]).  A product's data files
    live in fpSup/<dir>/ and are optional per file."""
    sups = [p for p in (d / 'fpSup').iterdir() if p.is_file() and SUP_RE.match(p.name)]
    if len(sups) != 1:
        raise SystemExit(f'{d.name}: expected one NNNAME.BIN in fpSup/, found {[p.name for p in sups]}')
    sup = sups[0]
    man = manifest(d)
    files = {}
    for rel in SHARED + [f'fpSup/{sup.name}']:
        b = (d / rel).read_bytes()
        if man.get(rel) != sha(b):
            raise SystemExit(f'{d.name}/{rel}: sha256 does not match MANIFEST.txt')
        files[rel] = b
    if files[f'fpSup/{sup.name}'][:4] != b'FSB1':
        raise SystemExit(f'{d.name}/{sup.name}: not an FSB1 sup')
    data = []
    if spec.get('data'):
        sub = d / 'fpSup' / spec['data']['dir']
        for f in sorted(sub.glob('*' + spec['data']['ext'])) if sub.is_dir() else []:
            rel = str(f.relative_to(d))
            b = f.read_bytes()
            if man.get(rel) != sha(b):
                raise SystemExit(f'{d.name}/{rel}: sha256 does not match MANIFEST.txt')
            files[rel] = b
            data.append(rel)
        if not data:
            raise SystemExit(f'{d.name}: no {spec["data"]["ext"]} in fpSup/{spec["data"]["dir"]}/')
    extra = sorted(str(p.relative_to(d)) for p in (d / 'fpSup').rglob('*')
                   if p.is_file() and str(p.relative_to(d)) not in files)
    if extra:
        raise SystemExit(f'{d.name}: files in fpSup/ this page would drop: {extra}')
    return sup.name, files, data


def main():
    global RELEASES, OUT
    ap = argparse.ArgumentParser()
    ap.add_argument('--releases', type=pathlib.Path, help='read releases from here (tests)')
    ap.add_argument('--out', type=pathlib.Path)
    a = ap.parse_args()
    RELEASES = a.releases or RELEASES
    OUT = a.out or OUT
    for k, spec in PRODUCTS.items():
        if k not in ORDER:
            raise SystemExit(f'{k}: not in ORDER')
        if not (spec.get('summary', {}).get('en') and spec['summary'].get('zh')):
            raise SystemExit(f'{k}: needs summary en + zh')
        for o in spec['excl']:
            if o in PRODUCTS and k not in PRODUCTS[o]['excl']:
                raise SystemExit(f'excl not symmetric: {k} -> {o}')

    products, shared, skipped, pending = [], None, [], []
    for key, spec in PRODUCTS.items():
        d = latest_v3(key)
        if d is None:
            skipped.append(key)
            # shown greyed out, not selectable: the user wants to see what is coming
            if spec.get('pending'):
                pending.append(dict(id=key, name=spec['name'], category=spec['category'],
                                    file=spec.get('file', ''), author=spec['author'],
                                    credits=list(spec['credits']), about=spec['summary'],
                                    stage=spec.get('stage', 'unreleased'),
                                    guide=guide(key)))
            continue
        sup, files, data = load(key, d, spec)
        common = {rel: files[rel] for rel in SHARED}
        if shared is None:
            shared, shared_from = common, d.name
        else:
            diff = [rel for rel in SHARED if sha(common[rel]) != sha(shared[rel])]
            if diff:
                raise SystemExit(f'{d.name} and {shared_from} differ in {diff}: '
                                 'rebuild the older release on the current loader first')
        b = files[f'fpSup/{sup}']
        if spec['category'] not in CATEGORIES:
            raise SystemExit(f'{key}: category {spec["category"]!r} not in CATEGORIES')
        products.append(dict(id=key, name=spec['name'], category=spec['category'],
                             excl=list(spec['excl']), author=spec['author'],
                             credits=list(spec['credits']), release=d.name,
                             version=version_of(d), date=updated(d, sup),
                             file=sup, size=len(b), sha256=sha(b),
                             about=spec['summary'], data=base64.b64encode(b).decode(),
                             guide=guide(key),
                             data_files=[dict(path=rel, label=label(spec, rel), size=len(files[rel]),
                                              sha256=sha(files[rel]),
                                              data=base64.b64encode(files[rel]).decode())
                                         for rel in data]))
    if not products:
        raise SystemExit('no v3 release found')

    # Simplified Chinese = the Traditional text through the site's own character
    # table (assets/lang.js), so there is still only one Chinese text to keep.
    lj = (FPSUP / 'assets' / 'lang.js').read_text(encoding='utf-8')
    body = lj[lj.index('var MAP = {'):lj.index('};', lj.index('var MAP = {'))]
    t2s = dict(re.findall(r'"(.)":"(.)"', body))
    if len(t2s) < 500:
        raise SystemExit(f'assets/lang.js: only {len(t2s)} characters in MAP')
    cat = dict(categories=CATEGORIES, t2s=t2s, shared=[dict(path=rel, size=len(shared[rel]), sha256=sha(shared[rel]),
                            data=base64.b64encode(shared[rel]).decode()) for rel in SHARED],
               products=sorted(products, key=lambda p: p['file']),
               pending=sorted(pending, key=lambda p: p['file']),
               order=ORDER)
    page = TEMPLATE.read_text(encoding='utf-8')
    if page.count('@@CATALOGUE@@') != 1:
        raise SystemExit('template.html must hold @@CATALOGUE@@ exactly once')
    # </script> cannot occur in base64 or in the ABOUT text we embed, but guard anyway.
    blob = json.dumps(cat, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    OUT.write_text(page.replace('@@CATALOGUE@@', blob), encoding='utf-8')
    if not a.out:
        SITE_COPY.write_text(page.replace('@@CATALOGUE@@', blob), encoding='utf-8')

    print(f'wrote {OUT} ({OUT.stat().st_size:,} B)')
    for p in cat['products']:
        print(f"  {p['file']:<12} {p['release']:<36} {p['size']:>7,} B  {p['sha256'][:12]}")
    noguide = [p['id'] for p in cat['products'] + cat['pending'] if not p['guide']]
    if noguide:
        print('  no guide page (fpSup/guide/<id>.html) yet:', ', '.join(noguide))
    if skipped:
        print('  no v3 release yet:', ', '.join(skipped))
    print(f"  shared files from {shared_from}: " + ' '.join(sha(shared[r])[:8] for r in SHARED))


if __name__ == '__main__':
    main()
