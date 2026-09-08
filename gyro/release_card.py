#!/usr/bin/env python3
"""Package fpGyroSup Base for release.

    ./gyro/release_base.py v1

Builds the card from source, checks the sections the card is supposed to
carry are really in the binary, and writes the archive and its checksums.
Nothing is assembled by hand: v1.4 of the older line shipped once without its
two orientation sections because a rebuild silently dropped two arguments
somebody had been passing on the command line, and the only visible sign was a
VSHL.BIN that hashed differently.
"""
import argparse
import hashlib
import pathlib
import struct
import subprocess
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
BASE = HERE / 'release' / 'base'
FILES = ('AutoRun.txt', 'VSHL.BIN', 'README.txt')

# Every section the card must carry, and what it is.  A build that drops one
# still produces a perfectly valid AutoRun and a camera that does nothing.
EXPECT = {
    0xC072E064: 'gsup_entry, the cave trampoline',
    0xC072E200: 'the accelerometer hook',
    0xC072E300: 'the gyro drain',
    0xC072E4E0: 'the record start hook',
    0xC072E620: 'the record stop hook',
    0xC072EC60: 'the space provider',
    0x00044000: 'ring_task, in the pool',
    0xC072EC38: '-> stream_claim',
    0xC072EC3C: '-> stream_commit',
    0xC072EC40: '-> gyro_drain',
    0xC072EC44: '-> stream_flush',
}


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def check_sections(path):
    d = pathlib.Path(path).read_bytes()
    magic, n, entry, _ = struct.unpack_from('<4sIII', d, 0)
    if magic != b'VBIN':
        raise SystemExit(f'{path} is not a VSHL binary: {magic!r}')
    dests = {struct.unpack_from('<II', d, 16 + i * 8)[0] for i in range(n)}
    missing = [f'0x{a:08X} ({w})' for a, w in EXPECT.items() if a not in dests]
    if missing:
        raise SystemExit(f'{path} is missing:\n  ' + '\n  '.join(missing))
    if entry != 0xC072E064:
        raise SystemExit(f'{path} names entry 0x{entry:08X}, not gsup_entry')
    print(f'  sections: {n}, entry 0x{entry:08X}, all {len(EXPECT)} accounted for')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('version', help='e.g. v1')
    a = ap.parse_args()
    r = subprocess.run([sys.executable, str(HERE / 'build_base_card.py')],
                       capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit('build_base_card failed')
    print(r.stdout.rstrip().splitlines()[-1].strip())
    check_sections(BASE / 'VSHL.BIN')

    # Named like the rest of the family: this is an edition of fpGyroSup,
    # not a separate thing.
    name = f'fp-gyro-sup-base-{a.version}'
    zpath = HERE / 'release' / f'{name}.zip'
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in FILES:
            z.write(BASE / f, f'{name}/{f}')
    sums = HERE / 'release' / f'SHA256SUMS-base-{a.version}.txt'
    lines = [f'{sha(BASE / f)}  {f}' for f in FILES]
    lines.append(f'{sha(zpath)}  {zpath.name}')
    sums.write_text('\n'.join(lines) + '\n')

    print(f'  {zpath.name}  {zpath.stat().st_size} bytes')
    for l in lines:
        print('  ' + l)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
