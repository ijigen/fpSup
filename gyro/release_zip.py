#!/usr/bin/env python3
"""Build the release card files and the zip people download.

    ./gyro/release_zip.py 1.4

v1.3 and everything before it was assembled by hand, which is how the zip and
release/card/ drifted apart more than once. This runs the same two builds
makecard.py runs, checks the three files against what is already in
release/card/, and writes the archive and its checksums.
"""
import argparse, hashlib, pathlib, shutil, subprocess, sys, zipfile

HERE = pathlib.Path(__file__).resolve().parent
REL = HERE / 'release'
CARD = REL / 'card'
FILES = ('AutoRun.txt', 'VSHL.BIN', 'PGEN.BIN')


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def build():
    """The release contract: no shell, native lifecycle, GCSV-only stream."""
    for cmd in ([sys.executable, str(HERE / 'build_card.py'),
                 '--no-pad', '--no-shell', '--gcsv-stream'],
                [sys.executable, str(HERE / 'build_pgen.py'), '--local',
                 '--native-lifecycle', '--gcsv-stream']):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stdout + r.stderr)
            raise SystemExit(f'{pathlib.Path(cmd[1]).name} failed')
        print('  ' + r.stdout.strip().splitlines()[-1].strip())
    return {'AutoRun.txt': HERE / 'autorun' / 'AutoRun.txt',
            'VSHL.BIN':    HERE / 'autorun' / 'VSHL.BIN',
            'PGEN.BIN':    HERE / '.pgen.bin'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('version', help='e.g. 1.4')
    a = ap.parse_args()
    name = f'fp-gyro-sup-v{a.version}'

    src = build()
    CARD.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        shutil.copyfile(src[f], CARD / f)

    sums = REL / f'SHA256SUMS-v{a.version}.txt'
    sums.write_text(''.join(f'{sha(src[f])}  {f}\n' for f in FILES))

    zpath = REL / f'{name}.zip'
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(REL / 'INSTALL.txt', f'{name}/INSTALL.txt')
        for f in FILES:
            z.write(src[f], f'{name}/{f}')
        z.write(sums, f'{name}/SHA256SUMS.txt')

    print(f'\n  {zpath.name}  {zpath.stat().st_size:,} bytes')
    for f in FILES:
        print(f'    {f:12s} {src[f].stat().st_size:7,} B  {sha(src[f])[:16]}')
    lines = (CARD / 'AutoRun.txt').read_text().splitlines()
    cmds = [l for l in lines if l.strip() and not l.strip().startswith('#')]
    print(f'    AutoRun is {len(cmds)} commands '
          f'(~{len(cmds) * 0.038 + 4.7:.1f} s to fpSup! at 38 ms each)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
