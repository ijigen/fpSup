#!/usr/bin/env python3
"""Package an edition of fpGyroSup for release.

    ./gyro/release_card.py gcsv v1.10a
    ./gyro/release_card.py base v1

Builds the card from source, checks the sections the card is supposed to
carry are really in the binary, and writes the archive and its checksums.
Nothing is assembled by hand: v1.4 of the older line shipped once without its
two orientation sections because a rebuild silently dropped two arguments
somebody had been passing on the command line, and the only visible sign was a
payload container that hashed differently.
"""
import argparse
import hashlib
import pathlib
import struct
import subprocess
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
FILES = ('AutoRun.txt', 'fpSup.BIN', 'README.txt')

# Every section the card must carry, and what it is.  A build that drops one
# still produces a perfectly valid AutoRun and a camera that does nothing.
# Nothing is left.  The hook stubs were the last cave sections a gyro card
# carried, and they moved into the blob on 2026-09-22: the firmware still
# branches to the same four addresses, but what waits there is an eight-byte
# veneer gsup_boot writes at boot, not a section a build placed.  A card that
# dropped a hook now fails the routine-table check below instead.
SHARED = {}
# The gyro drain, the space provider and the four words that point at them used
# to be listed here as cave sections.  They are in the writer's blob now
# (2026-09-22), so a card that dropped them would still pass a destination
# check -- what proves they are aboard is the routine table, below: a zero
# there is exactly the "built but dropped" failure this list exists to catch,
# and it is checked for every routine the blob must carry, not just these.
#
# gyro_drain, stream_claim, stream_commit and stream_flush are NOT here.  They
# had slots while the cave held a pointer to each; hook and body share a blob
# now and the branch is an ordinary `bl`, so a build that dropped one does not
# ship a zero -- it fails to assemble.  Listing them here only made this check
# look for table entries that no longer exist.
BLOB_ROUTINES = ('accel_hook', 'rec_start', 'rec_stop',
                 'writer_body', 'take_open', 'take_close', 'writer_post',
                 'mpool_init_jobs', 'blocks_open', 'gsup_boot')
EXPECT = {'base': SHARED, 'gcsv': SHARED}
# Per edition, because the mode hook belongs to the one that writes its own log
# -- it is what makes a take land the right way up, and it goes missing quietly:
# without it the card still boots, still logs, still writes both sidecars, and a
# portrait take comes out rotated.
EDITION_ROUTINES = {'base': (), 'gcsv': ('mode_hook',)}
# What the archive is called.  Base is an edition of fpGyroSup, not a separate
# product, so it is named like the rest of the family.
STEM = {'base': 'fp-gyro-sup-base', 'gcsv': 'fp-gyro-sup'}
SUMS = {'base': 'base-', 'gcsv': ''}


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def check_sections(path, edition):
    d = pathlib.Path(path).read_bytes()
    magic, n, entry, _ = struct.unpack_from('<4sIII', d, 0)
    if magic != b'VBIN':
        raise SystemExit(f'{path} is not a VBIN container: {magic!r}')
    dests = {struct.unpack_from('<II', d, 16 + i * 8)[0] for i in range(n)}
    want = EXPECT[edition]
    missing = [f'0x{a:08X} ({w})' for a, w in want.items() if a not in dests]
    if missing:
        raise SystemExit(f'{path} is missing:\n  ' + '\n  '.join(missing))

    # The writer used to be checked by address -- a section at pool + 0x44000 --
    # and the entry by address too, gsup_entry in the cave at 0xC072E064.
    # Neither exists now.  The writer travels appended to the bootstrap that
    # asks for the pool and copies it in, as one destination-zero section, so
    # what is checked is that the card carries it and that the header really
    # points into it: a release whose entry misses the launcher boots, places
    # every section, and logs nothing.
    #
    # Destination zero means "run where the file landed".  The FIRST such
    # section is the loader's own second half -- loader.S branches to the end of
    # the table -- and a release card carries exactly one more, the launcher.
    # A debug card carries the shell's worker and a trampoline as well, which is
    # why this is a release check and not a general one.
    off, runs = 16 + n * 8, []
    for i in range(n):
        dest, ln = struct.unpack_from('<II', d, 16 + i * 8)
        if dest == 0:
            runs.append((off, ln))
        off += ln + (-ln % 4)
    if len(runs) != 2:
        raise SystemExit(f'{path} has {len(runs)} run-in-place sections, not '
                         f'two (stage2 and the launcher)')
    lo, ln = runs[1]
    # A release must not carry a fast start.  --store-boot exists on the card
    # builder because a DEV card packaged by --dev-card --fast needs it, and a
    # flag that exists gets passed: the abort routine at 0xC072F080 is what a
    # fast card places and nothing else does, so it is what this looks for.
    #
    # The rule is not aesthetic.  A fast card writes its loader into
    # XC_CommonSaveData, which survives a battery pull -- the one thing on these
    # cards that outlives deleting AutoRun.txt, and not something to hand
    # someone without them choosing it.  They choose it on the composer page.
    if 0xC072F080 in dests:
        raise SystemExit(f'{path} carries the abort routine, so it was built '
                         f'with --store-boot: a release must not start fast. '
                         f'Fast start is packaging, and the person installing '
                         f'the card chooses it on the composer page.')
    if not lo <= entry < lo + ln:
        raise SystemExit(f'{path} names entry 0x{entry:08X}, which is not '
                         f'inside the launcher at 0x{lo:X}..0x{lo + ln:X}')
    # What the launcher is carrying.  The cave list above can only see the
    # hooks now; everything else the card needs is inside this one section, and
    # the routine table at the top of the blob is what says so -- a zero there
    # means the builder did not find the symbol, which is what "shipped without
    # its sections" looks like since they moved into the pool.
    import sys as _sys
    _sys.path.insert(0, str(HERE))
    _sys.path.insert(0, str(HERE.parent / 'fp_usb_shell'))
    from armasm import symbols                                   # noqa: E402
    import ring_task_deploy as R                                 # noqa: E402
    # `blob` is the launcher's tail and BLOB_LEN is an immediate, so the offset
    # does not depend on what was appended -- the label is where it is.
    blob_off = symbols(HERE / 'gsup_launch.S', ['BLOB_LEN=0x0'])['blob']
    table = d[lo + blob_off: lo + blob_off + len(R.GSUP_ROUTINES) * 4]
    got = dict(zip(R.GSUP_ROUTINES, struct.unpack(f'<{len(table)//4}I', table)))
    want_routines = BLOB_ROUTINES + EDITION_ROUTINES[edition]
    # A name here that the table does not have reads as "missing from the
    # card", which is how the four `bl`-reached routines turned a good build
    # into a failed release check.  Say which it really is.
    unknown = [r for r in want_routines if r not in got]
    if unknown:
        raise SystemExit(f'{path}: the routine table has no slot for '
                         + ', '.join(unknown)
                         + ' -- BLOB_ROUTINES has drifted from GSUP_ROUTINES')
    missing = [r for r in want_routines if not got[r]]
    if missing:
        raise SystemExit(f'{path}: the blob\'s routine table has no '
                         + ', '.join(missing))
    print(f'  sections: {n}, entry 0x{entry:08X} in the {ln}-byte launcher, '
          + (f'all {len(want)} cave destinations accounted for' if want else
             'no cave destinations: nothing is placed at a build-time address'))
    print(f'  blob: {len(want_routines)} routines resolved, '
          f'gsup_boot at +0x{got["gsup_boot"]:X}, '
          f'accel_hook at +0x{got["accel_hook"]:X}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('edition', choices=sorted(EXPECT))
    ap.add_argument('version', help='e.g. v1.10a')
    ap.add_argument('--force', action='store_true',
                    help='overwrite an archive that already exists')
    a = ap.parse_args()
    out = HERE / 'release' / a.edition
    r = subprocess.run([sys.executable, str(HERE / 'build_base_card.py'),
                        '--edition', a.edition, '--version', a.version,
                        '--out', str(out)],
                       capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit('build_base_card failed')
    print(r.stdout.rstrip().splitlines()[-1].strip())
    check_sections(out / 'fpSup.BIN', a.edition)

    name = f'{STEM[a.edition]}-{a.version}'
    zpath = HERE / 'release' / f'{name}.zip'
    # A released version is what somebody downloaded; it does not get to change
    # under the same name.  This is not hypothetical -- release/<edition>/ is a
    # build directory and drifts from the archive as the shared core moves, so
    # rebuilding an old version here produces a DIFFERENT card with the same
    # version number on it.
    if zpath.exists() and not a.force:
        raise SystemExit(f'{zpath.name} already exists.  Give it a new version, '
                         f'or pass --force if you are certain nobody has it.')
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in FILES:
            z.write(out / f, f'{name}/{f}')
    sums = HERE / 'release' / f'SHA256SUMS-{SUMS[a.edition]}{a.version}.txt'
    lines = [f'{sha(out / f)}  {f}' for f in FILES]
    lines.append(f'{sha(zpath)}  {zpath.name}')
    sums.write_text('\n'.join(lines) + '\n')

    print(f'  {zpath.name}  {zpath.stat().st_size} bytes')
    for l in lines:
        print('  ' + l)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
