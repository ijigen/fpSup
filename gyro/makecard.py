#!/usr/bin/env python3
"""Build and install a card, one command.

    ./gyro/makecard.py release     the shipping card: no USB shell
    ./gyro/makecard.py debug       the same, plus the shell to look inside with
    ./gyro/makecard.py release --to /Volumes/SOMETHING

Finds the mounted card, builds everything from source, copies the three files,
makes the folder the .GYR files go in, checks every byte back, and ejects.

The two builds differ in one thing: whether the USB shell is there. Release
leaves out its worker, its endpoint patches and its state block -- a hundred and
fifty commands against two hundred and twenty, and one less resident task -- and
with it goes any way of looking inside a camera that misbehaves. Keep the debug
card; it is the only instrument there is.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = ('AutoRun.txt', 'VSHL.BIN', 'PGEN.BIN')


def find_card(explicit):
    if explicit:
        p = Path(explicit)
        if not p.is_dir():
            raise SystemExit(f'{p} is not there')
        return p
    # Skip the boot disk and the hidden mounts macOS keeps there -- /Volumes
    # holds .timemachine and friends, and picking one of those up gets as far as
    # trying to write to it.
    vols = [p for p in Path('/Volumes').iterdir()
            if p.is_dir() and not p.name.startswith('.')
            and p.name != 'Macintosh HD' and os.access(p, os.W_OK)]
    if not vols:
        raise SystemExit('no card mounted -- put it in the reader, or pass --to')
    if len(vols) > 1:
        raise SystemExit('more than one volume mounted; say which with --to:\n  ' +
                         '\n  '.join(str(v) for v in vols))
    return vols[0]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('build', choices=('release', 'debug'))
    ap.add_argument('--to', help='the card, if it is not the only volume mounted')
    ap.add_argument('--keep-mounted', action='store_true')
    ap.add_argument('--recovery', action='store_true',
                    help='also enable the experimental boot recovery scan')
    ap.add_argument('--phase-probe', action='store_true',
                    help='release-only RAM trace of CDNG/GYR write phase')
    a = ap.parse_args()

    if a.phase_probe and a.build != 'release':
        raise SystemExit('--phase-probe is release-only (the debug shell owns '
                         'the probe address)')

    card = find_card(a.to)
    print(f'  card          {card}')

    cmd = [sys.executable, str(HERE / 'build_card.py'), '--no-pad']
    if a.build == 'release':
        cmd.append('--no-shell')
    if a.phase_probe:
        cmd.append('--phase-probe')
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit('  the card build failed')
    for line in r.stdout.splitlines():
        if line.startswith(('worker', 'payload', 'clean')):
            print('  ' + line)

    # Native lifecycle is the shipping v1.1 contract.  The logger consumes its
    # clip identity, volume and finalize publication, so there is no meaningful
    # legacy card combination to expose here.
    pgen_cmd = [sys.executable, str(HERE / 'build_pgen.py'), '--local',
                '--native-lifecycle']
    if a.recovery:
        pgen_cmd.append('--recovery')
    r = subprocess.run(pgen_cmd,
                       capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit('  the pool build failed')
    print('  ' + r.stdout.strip().splitlines()[-1].strip())

    src = {'AutoRun.txt': HERE / 'autorun' / 'AutoRun.txt',
           'VSHL.BIN': HERE / 'autorun' / 'VSHL.BIN',
           'PGEN.BIN': HERE / '.pgen.bin'}
    # Remove before writing, which is why --no-pad above is safe.
    #
    # The camera's own file writes overwrite but do not truncate, so a shorter
    # AutoRun written over a longer one leaves the tail of the old one behind
    # and the camera runs it: the previous worker written over the loader that
    # had already been hooked. Padding every build to thirty-two kilobytes was
    # the answer when the only way onto the card was through the camera. From
    # here the file can simply go first -- and the camera stops parsing four
    # hundred lines of filler on every boot.
    for name in FILES:
        target = card / name
        if target.exists():
            target.unlink()
    for name in FILES:
        shutil.copyfile(src[name], card / name)

    # The .GYR files go here. It has to exist before the first take: the logger
    # opens the file the instant recording starts and cannot make a folder.
    (card / 'GYRO').mkdir(exist_ok=True)

    # AppleDouble files the Mac leaves behind. The camera ignores them; they are
    # just noise on a card someone will look at.
    for junk in card.rglob('._*'):
        junk.unlink()
    subprocess.run(['sync'])

    bad = [n for n in FILES if sha(src[n]) != sha(card / n)]
    if bad:
        raise SystemExit(f'  copied but did not verify: {", ".join(bad)}')
    lines = (card / 'AutoRun.txt').read_text().count('\n')
    print(f'  installed     {", ".join(FILES)}, all verified')
    print(f'  AutoRun       {(card / "AutoRun.txt").stat().st_size:,} bytes, '
          f'{lines} lines, unpadded')
    print(f'  GYRO/         {"ready" if (card / "GYRO").is_dir() else "MISSING"}')

    if not a.keep_mounted:
        subprocess.run(['diskutil', 'eject', str(card)],
                       capture_output=True, text=True)
        print('  ejected       put it in the camera and power on')
    return 0


if __name__ == '__main__':
    sys.exit(main())
