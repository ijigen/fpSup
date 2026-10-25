#!/usr/bin/env python3
"""Cut a Loader v3 release: one product, one self-contained card folder.

    python3 tools/release_v3.py <product> <version>      e.g.  lossless 0.2.0test

writes releases/fpsup-<product>-v<version>/:

    AutoRun.txt            loads \\fpSup\\LOADER.BIN (build_v3.autorun)
    fpSup/LOADER.BIN       the 加載器, identical in every v3 release built from
    fpSup/UI/0..4.BIN      the same sloader -- so merging = copying fpSup/ together
    fpSup/NNNAME.BIN       this product's sup
    ABOUT.txt              carried from the product's newest release (or --about)
    README.txt             skeleton; the CHANGES / VERIFIED sections are TODO
    MANIFEST.txt           hashes, header fields, the git state the build came from
    build.json             the sup builder's own record (not for the card)

Design: projects/usb-shell-sup/notes/LOADER_V3.md.  The v3 sup builders are run
as they are (their non --card output is the bare NNNAME.BIN + build.json), so the
release carries exactly the bytes `build_v3_*.py --out` makes.

It refuses an existing folder (fp-release skill: rebuilding an old version in
place produces a different card under the same number).  No --force.
"""
import argparse, hashlib, json, pathlib, re, shutil, struct, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent
ROOT = FPSUP.parent
RELEASES = FPSUP / 'releases'
V3 = FPSUP / 'fp_usb_shell' / 'v3'
sys.path.insert(0, str(V3))

import build_v3 as B                                   # noqa: E402

NAME_RE = re.compile(r'^[0-9]{2}[A-Z0-9]{1,6}\.BIN$')  # 8.3, two-digit order prefix
VER_RE = re.compile(r'^\d+(?:\.\d+)*[a-z]*$')

# product -> (builder argv, file it makes, sup_id, title)
PRODUCTS = {
    'usbshell':   (None, '00SHELL.BIN', 'SHEL', 'USB shell'),
    'lossless':   ([FPSUP / 'lossless' / 'build_v3_lossless.py'], '10LOSS.BIN', 'LOSS',
                   'Lossless CinemaDNG'),
    'og3k':       ([ROOT / 'projects' / 'open-gate' / 'build' / 'build_v3_og.py', '--target', 'og3k'],
                   '30OG3K.BIN', 'OG3K', 'Open Gate 3K'),
    'og2k':       ([ROOT / 'projects' / 'open-gate' / 'build' / 'build_v3_og.py', '--target', 'og2k'],
                   '30OG2K.BIN', 'OG2K', 'Open Gate 2K'),
    'gyro2':      ([ROOT / 'projects' / 'gyro2-sup' / 'build.py'], '20GYR2.BIN', 'GYR2', 'Gyro2'),
    'screenflip': ([FPSUP / 'screenflip' / 'build_v3_flip.py'], '40FLIP.BIN', 'FLIP', 'Screen flip'),
    'rec-limit': ([FPSUP / 'rec-limit' / 'build_v3_reclimit.py'], '46RECLM.BIN', 'RCLM',
                  'Recording time limit'),
    'raw-view':   ([ROOT / 'projects' / 'rawview' / 'build' / 'build_v3_rawview.py'], '45RAWV.BIN',
                   'RAWV', 'RAW view'),
    # the OpenGate formats (2026-10-07): one core + one data file per format in \fpSup\RESCUS\
    'res-custom': ([ROOT / 'projects' / 'open-gate' / 'build' / 'res-custom' / 'build_v3_rescustom.py'],
                   '32RESCUS.BIN', 'RCUS', 'Open Gate formats (res-custom)'),
}
# products whose builder also writes a data folder that goes under \fpSup\ as it is
DATA_DIRS = {'res-custom': 'RESCUS'}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def header(data):
    if len(data) < B.SL_HEADER_LEN:
        raise SystemExit('sup shorter than its header')
    magic, hlen, flen, block, entry, sid, ver, svc = struct.unpack_from('<8I', data)
    return dict(magic=magic, header_len=hlen, file_len=flen, block_size=block, entry_off=entry,
                sup_id=struct.pack('<I', sid).rstrip(b'\0').decode('ascii', 'replace'),
                version=ver, min_svc=svc)


def check_sup(name, data, sup_id):
    h = header(data)
    bad = []
    if h['magic'] != B.SL_MAGIC:
        bad.append(f'magic 0x{h["magic"]:08X}, not FSB1')
    if h['file_len'] != len(data):
        bad.append(f'file_len {h["file_len"]} but the file is {len(data)} B')
    if h['block_size'] < h['file_len']:
        bad.append('block_size < file_len')
    if not 0 < (h['entry_off'] & ~1) < h['file_len']:
        bad.append(f'entry_off 0x{h["entry_off"]:X} outside the file')
    if h['sup_id'] != sup_id:
        bad.append(f'sup_id {h["sup_id"]!r}, expected {sup_id!r}')
    if h['min_svc'] > B.SL_SVC_VERSION:
        bad.append(f'needs services v{h["min_svc"]}, LOADER.BIN gives v{B.SL_SVC_VERSION}')
    if not NAME_RE.match(name):
        bad.append(f'{name}: not an 8.3 NNNAME.BIN')
    if bad:
        raise SystemExit(f'{name}: ' + '; '.join(bad))
    return h


def build_sup(product, tmp):
    argv, name, sup_id, _ = PRODUCTS[product]
    if argv is None:                                    # the shell: no builder script of its own
        return B.shell_sup(burst15=True), name, None, {}   # burst15+NOPTP, no EP83: the bytes on cards/20261006-mem1 and screenflip v3d
    out = tmp / 'sup'
    r = subprocess.run([sys.executable, '-B', *map(str, argv), '--out', str(out)],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        raise SystemExit(f'{argv[0].name} failed:\n{r.stdout}{r.stderr}')
    data = (out / name).read_bytes()
    bj = out / 'build.json'
    extra = {}
    sub = DATA_DIRS.get(product)
    if sub:
        if not (out / sub).is_dir():
            raise SystemExit(f'{argv[0].name} wrote no {sub}/')
        for f in sorted((out / sub).iterdir()):
            if not re.match(r'^[A-Z0-9]{1,8}\.[A-Z0-9]{1,3}$', f.name):
                raise SystemExit(f'{sub}/{f.name}: not an 8.3 name')
            extra[f'{sub}/{f.name}'] = f.read_bytes()
    return data, name, json.loads(bj.read_text()) if bj.exists() else None, extra


def git_state():
    def g(*a):
        return subprocess.run(['git', '-C', str(FPSUP), *a], capture_output=True,
                              text=True).stdout.strip()
    return g('rev-parse', 'HEAD'), [l[3:] for l in g('status', '--porcelain').splitlines()]


def newest_about(product):
    pat = re.compile(rf'^fpsup-{re.escape(product)}-v(\d+(?:\.\d+)*)([a-z]*)$')
    best = None
    for d in RELEASES.iterdir():
        m = pat.match(d.name)
        if m and (d / 'ABOUT.txt').exists():
            q = m[2]                            # releases/README.md: none > letters > test
            key = (tuple(int(x) for x in m[1].split('.')), 0 if q == 'test' else 2 if not q else 1, q)
            if best is None or key > best[0]:
                best = (key, d)
    return best[1] if best else None


README = """================================================================
 {title}  fpsup-{product}-v{version}
 SIGMA fp Ver.5.02 only -- Loader v3 card
================================================================

WHAT IT IS

  TODO (carry from the previous release's README, plain words)

HOW TO USE

  Copy AutoRun.txt and the fpSup folder to the root of the SD card and
  start the camera.  To combine with other fpSup products released for
  Loader v3, copy their fpSup folders over this one: every product
  carries the same LOADER.BIN and UI frames, and its own {name}.

  Upgrading from an older (single fpSup.BIN) card: delete the old
  fpSup.BIN from the card root.  A card from before Loader v3 cannot be
  mixed with this one.

{changes}

WHAT HAS BEEN VERIFIED

  TODO -- only on THIS release's own files (MANIFEST.txt hashes).
  Not yet written to a card or tested on the camera.
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('product', choices=sorted(PRODUCTS))
    ap.add_argument('version', help='e.g. 0.2.0test (no leading v)')
    ap.add_argument('--about', type=pathlib.Path, help='ABOUT.txt for a first release')
    a = ap.parse_args()
    if not VER_RE.match(a.version):
        raise SystemExit(f'{a.version}: not <num>.<num>[qualifier]')
    dest = RELEASES / f'fpsup-{a.product}-v{a.version}'
    if dest.exists():
        raise SystemExit(f'{dest.name} exists: a release is never rebuilt in place')
    prev = newest_about(a.product)
    about = a.about or (prev / 'ABOUT.txt' if prev else None)
    if about is None:
        raise SystemExit(f'no earlier {a.product} release to take ABOUT.txt from: pass --about')

    _, name, sup_id, title = PRODUCTS[a.product]
    with tempfile.TemporaryDirectory(prefix='relv3-') as t:
        data, name, bj, extra = build_sup(a.product, pathlib.Path(t))
    h = check_sup(name, data, sup_id)
    vbin, linfo = B.loader_bin()
    frames = B.splash_frames()
    head, dirty = git_state()

    stage = RELEASES / f'.{dest.name}.tmp'
    if stage.exists():
        shutil.rmtree(stage)
    d = stage / B.SL_DIR
    (d / 'UI').mkdir(parents=True)
    (stage / 'AutoRun.txt').write_bytes(B.autorun(stage))
    (d / B.SL_SELF).write_bytes(vbin)
    for i, px in enumerate(frames):
        (d / 'UI' / f'{i}.BIN').write_bytes(px)
    (d / name).write_bytes(data)
    for rel, b in extra.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(b)
    if B.loader_words((stage / 'AutoRun.txt').read_bytes()) == {}:
        raise SystemExit('AutoRun.txt carries no loader words')
    shutil.copy(about, stage / 'ABOUT.txt')
    (stage / 'README.txt').write_text(README.format(
        title=title, product=a.product, version=a.version, name=name,
        changes=(f'WHAT CHANGED SINCE {prev.name}\n\n'
                 '  - Moved to Loader v3: one file per product in \\fpSup\\.\n  - TODO'
                 if prev else 'WHAT CHANGED\n\n  - First release.')), encoding='utf-8')

    files = sorted(p for p in stage.rglob('*') if p.is_file() and p.suffix.upper() != '.TXT'
                   or p.name == 'AutoRun.txt')
    lines = [f'SIGMA fp -- {title} (v{a.version}), Loader v3 card',
             'firmware: SIGMA fp Ver.5.02 only', '']
    for p in files:
        b = p.read_bytes()
        lines.append(f'{str(p.relative_to(stage)):22} {len(b):>9,}B  sha256={sha(b)}')
    lines += ['', f'{name} header: ' + ', '.join(
        f'{k}={v:#x}' if isinstance(v, int) and k not in ('version', 'min_svc') else f'{k}={v}'
        for k, v in h.items()),
        f'LOADER.BIN gives services v{B.SL_SVC_VERSION}',
        '', f'Built by fpSup/tools/release_v3.py {a.product} {a.version}',
        f'fpSup HEAD {head}' + (f', {len(dirty)} uncommitted paths at build time' if dirty else ''),
        'Not yet written to a card or tested on the camera.']
    (stage / 'MANIFEST.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    if bj:
        (stage / 'build.json').write_text(json.dumps(bj, indent=1, ensure_ascii=False) + '\n')
    stage.rename(dest)
    print(f'{dest.relative_to(FPSUP)}: {name} {len(data):,} B, block {h["block_size"]:,} B, '
          f'min_svc {h["min_svc"]}' + (f'  (tree dirty: {len(dirty)} paths)' if dirty else ''))


if __name__ == '__main__':
    main()
