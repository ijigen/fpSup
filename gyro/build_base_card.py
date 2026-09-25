#!/usr/bin/env python3
"""Build the gyro_sup_base card: the stream, and nothing else.

    ./gyro/build_base_card.py            -> gyro/release/base/{AutoRun.txt,VSHL.BIN}

WHAT THIS IS

The base is the foundation the rest gets built on: every take writes its own
\\GYRO\\A001_037.GYR beside the clip, sixty-four bytes of header and then
nothing but interleaved gyro and accelerometer records, straight from the
buffers the producers filled.  No gcsv on the camera, no lens profile, no
portrait patch, no USB shell.  Those are separate questions and they were what
made the old logger four kilobytes with nothing to spare.

HOW IT GETS THERE

    \\AutoRun.txt   about ninety commands: the loader, spelled out
    \\fpSup.BIN     everything else, as sections

The loader reads fpSup.BIN into the camera's DMA pool and branches to stage2,
which places every section and then branches to the file's entry.  Sections
whose destination is below 0x40000000 are OFFSETS into that pool -- the pool's
address is decided at boot, so a build cannot name it, but it can name an
offset.  That is how four kilobytes of writer gets somewhere the two-kilobyte
cave could never hold it.

The entry is gsup_launch, which runs where the file lands and which reads
the routine table at the top of the blob and calls gsup_boot in the pool.
gsup_boot does exactly what the two deploy scripts do over USB: wire every
pointer word, build the job free list, take the eight buffers from the
allocator -- and only then arm the three hooks.  If the allocator refuses, it
arms nothing and the camera is an ordinary camera.  A card that half-works is
worse than one that does not.

THE LAYOUT IS THE DEVELOPMENT ONE

Every cave address here comes from imu_stream_deploy.py's own table, and the
blob is patched by ring_task_deploy.py's own function.  Two builds, one layout:
the release cannot drift from the thing that was tested over USB.
"""
import argparse
import pathlib
import shutil
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SHELL = HERE.parent / 'fp_usb_shell'
sys.path.insert(0, str(SHELL))
sys.path.insert(0, str(HERE))

from armasm import assemble, symbols                            # noqa: E402
import imu_stream_deploy as S                                   # noqa: E402
import ring_task_deploy as R                                    # noqa: E402

ENTRY_AT = 0xC072E064      # the bottom of the cave, above the loader
PARK_AT = 0xC072EFB4       # the shell's park stub; nothing of ours may reach it
F_WRITE_AT = 0xC03660E8    # a previous session's diagnostic patch, restored
OUT = HERE / 'release' / 'base'


READMES = {}

READMES['base'] = """fpGyroSup Base {version} -- SIGMA fp firmware Ver.5.02 only

Put AutoRun.txt and fpSup.BIN in the root of the SD card the camera boots
from, and make sure there is a folder called

    GYRO

in the root of EVERY volume you record to -- the SD card and, if you record
to one, the USB SSD as well.  The camera writes the log beside the clip, on
the same disk, and it will not create the folder for you: making a directory
writes to the file system, and the only two moments it could do that are
while a take is starting (which froze the camera) or at boot, when it can
only guess which disk you will actually use.  One empty folder, once, is the
honest price.

Then record.  Each take writes

    \\GYRO\\A001_037.GYR    beside    \\CINEMA\\A001_037

64 bytes of header and then nothing but 8-byte records, gyro and
accelerometer interleaved in the order they happened.  Convert with

    ./gyro/gyr7.py A001_037.GYR --gcsv A001_037.gcsv

If a take produces no .GYR, the folder is missing on that volume.  Nothing
else is wrong and nothing else needs doing.  Formatting a card removes it,
so put it back after you format.

This card carries the stream and nothing else: no gcsv on the camera, no
lens profile, no USB shell.  If you would rather the camera wrote the .gcsv and
the .json for you and left no .GYR at all, that is the main fpGyroSup release,
in the same folder.

    https://ijigen.github.io/fpSup/gyro/web/     convert in a browser
    ./gyro/gyr7.py                               convert on the command line
"""

READMES['gcsv'] = """fpGyroSup {version} -- SIGMA fp firmware Ver.5.02 only

Put AutoRun.txt and fpSup.BIN in the root of the SD card the camera boots
from, and record CinemaDNG.  Nothing else: no folder to make, no file to
convert, no step after the take.

Each take writes both of the files Gyroflow wants, inside the clip's own
folder, while it is being recorded:

    \\CINEMA\\A001_037\\A001_037.gcsv    the IMU log
    \\CINEMA\\A001_037\\A001_037.json    the lens profile

Load the frames and both files into Gyroflow and run its synchronisation as
usual.  There is nothing to convert, but the offset still has to be found:
CinemaDNG carries no timecode, and the log starts about half a second after
the first frame -- measured between 470 and 570 ms, and different every take --
so it is not a number you can fill in once and reuse.

The log is every sample the gyro produced -- 2499.466 Hz, nothing averaged and
nothing dropped -- with each accelerometer reading placed on the row of the
sample it followed.  The profile carries the lens's own distortion, read out
of the camera's calibration data for whatever is mounted, so it is the same
curve the camera puts in a DNG's WarpRectilinear opcode.

Portrait takes need nothing done to them.  In CINE the camera records every
frame landscape upright, so Gyroflow reads a portrait take exactly as it
reads a landscape one: load the frames and the two sidecars, sync, stabilise,
and turn the picture at the end of the edit.  Leave horizon lock off.
Photographs are untouched and still rotate by themselves.

CinemaDNG only.  A MOV take gets no sidecars: MOV records through a different
path this build does not hook.  Use fpGyroSup Base for MOV -- it writes a .GYR
beside any take -- or v1.1 of this line.

This card carries no USB shell.  Nothing is flashed: take the two files off
the card, or pull the battery, and the camera is exactly as it was.
"""


# One source, two products.  Base used to be its own file and that is exactly
# how it went stale: the 2026-09-19 profile-size fix landed in gcsv and base
# kept writing the menu's size, because nobody edits a file that is not in
# front of them.  A define cannot be forgotten the way a second file can.
#
# What the define changes is spelled out at the top of gcsv_task.S: where the
# log goes (base writes to the volume root -- no folder for anyone to forget
# to make), what goes in it (base writes the records untouched), and the
# header (twenty bytes, only what is needed to read them).  The .json is the
# same file in the same format either way.
EDITIONS = {
    'base': ('gcsv_task.S', ('FPGYRO_EDITION_BASE=1',)),
    'gcsv': ('gcsv_task.S', ()),
}
BANNER = {'base': 'Base', 'gcsv': 'Gyro'}


def sections(edition='base'):
    """Every section, with where it goes and why.

    The cave addresses are read out of imu_stream_deploy's PRODUCERS rather
    than repeated here, because a second copy of an address is a second chance
    to be wrong -- which is how a four-byte patch once branched into the middle
    of the logger.
    """
    out = []
    # The hook stubs are NOT sections any more either.
    #
    # They were 536 bytes of cave -- 152, 196, 124 and 64 -- and every one of
    # them was there for the same reason: the firmware reaches a hook with `bl`,
    # which carries 32 MB, and a body in the pool is two gigabytes away.  But
    # that argument only covers the LANDING POINT.  The bodies are sections of
    # the writer's blob now and gsup_boot writes an eight-byte veneer at each of
    # the four cave addresses, so the same four addresses still receive the
    # firmware's branch and the cave keeps 32 bytes instead of 536.
    #
    # Which leaves this card placing nothing in the cave at all.  Everything it
    # needs there -- veneers, call-through words, state -- is written at boot by
    # its own entry, after the allocator has said yes.  A card that cannot get
    # its memory now leaves the cave exactly as it found it.

    # The four call-through words are NOT sections any more.
    #
    # They were, while the code they name sat at a fixed cave address a build
    # could compute.  The space provider and the drain are in the writer's blob
    # now -- 1,108 bytes out of a payload window that is 3,920 -- so where they
    # land is not known until the pool is, and gsup_boot fills the words in from
    # the routine table, before it arms a single hook.  See writer_core.inc.S.

    # The writer is NOT here any more.  It used to be a section whose
    # destination was a pool offset, which meant somebody had to have published
    # a pool before it could be placed -- and nobody does that any more except
    # the payload that wants one.  It travels inside launch() instead, appended
    # to the code that asks for the pool and copies it in.  See gsup_launch.S.
    return out


def launch(edition):
    """The logger's bootstrap with the edition's writer appended to it.

    One destination-zero section: stage2 leaves it where the file landed and
    runs it, and it drives its own order from there -- ask the allocator, copy
    the writer to pool + 0x44000, make it runnable, call it.  The same shape the
    USB shell's worker has used since it left the cave.

    The writer is patched with its own routine table first: the same function
    the USB deploy uses, so the two blobs are the same bytes.
    """
    src, defines = EDITIONS[edition]
    code = assemble(HERE / src, defines)
    code = R.patch_offsets(code, symbols(HERE / src, defines))
    code += b'\x00' * (-len(code) % 4)
    boot = assemble(HERE / 'gsup_launch.S', [f'BLOB_LEN=0x{len(code):X}'])
    at = symbols(HERE / 'gsup_launch.S', [f'BLOB_LEN=0x{len(code):X}'])
    if len(boot) != at['blob']:
        raise SystemExit('gsup_launch.S has bytes after `blob`; the writer must '
                         'be the tail of the section, not the middle of it')
    return boot + code, len(code)


def hook_sites():
    """Each hook site as a four-byte section holding the firmware's own word.

    gsup_boot arms these at run time, which stage2 cannot see.  Declared here,
    stage2 journals each site before the entry runs -- and writing a site's own
    word back is a no-op on a stock image and a repair on one a missed power-off
    left patched.  The loader's power-off callback then writes them back with
    everything else, which is why gsup_boot has no disarm of its own any more
    (2026-09-25, LOADER_V2.md).  One list: imu_stream_deploy.PRODUCERS."""
    import struct
    import imu_stream_deploy as D
    return [(site, struct.pack('<I', orig), f'hook site {name}')
            for name, (_src, _defs, site, orig, _t) in sorted(D.PRODUCERS.items(),
                                                              key=lambda kv: kv[1][2])]


def check(secs):
    """Nothing overlaps, nothing in the cave reaches the park stub, and nothing
    in the pool lands on the loader while it is still reading."""
    spans = [(a, a + len(b), w) for a, b, w in secs]
    for i, (alo, ahi, aw) in enumerate(spans):
        for blo, bhi, bw in spans[i + 1:]:
            if alo < bhi and blo < ahi:
                raise SystemExit(f'{aw} and {bw} overlap')
    for lo, hi, w in spans:
        if lo < 0x40000000:             # pool-relative: an offset, not an address
            raise SystemExit(
                f'{w} wants to be placed at pool+0x{lo:X}, and nothing publishes '
                f'a pool before sections are placed.  The AutoRun used to ask for '
                f'one with `memmgr bufmem get`; it does not any more, and the only '
                f'pool on the card is the one a payload asks the allocator for in '
                f'its own entry -- which runs after this would have been placed. '
                f'Put the blob inside that entry instead, the way launch() does: '
                f'one destination-zero section that copies itself in. '
                f'(This check used to compare pool offsets against the window the '
                f'loader staged the file in; that window is inside a buffer the '
                f'loader now allocates for itself and hands back, so the two were '
                f'not the same address space and the comparison meant nothing.)')
        if not (0xC072D000 <= lo < 0xC0730000):
            continue                    # a patch in the firmware, not the cave
        if lo < ENTRY_AT:
            raise SystemExit(f'{w} at 0x{lo:08X} is inside the loader')
        if hi > PARK_AT:
            raise SystemExit(f'{w} runs to 0x{hi:08X}, past the park stub '
                             f'at 0x{PARK_AT:08X}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path, default=None)
    ap.add_argument('--edition', choices=sorted(EDITIONS), default='base')
    ap.add_argument('--store-boot', action='store_true',
                    help='keep the loader in the camera\'s settings block, so '
                         'every boot after the first is twenty-six commands. '
                         'A packaging choice, not a product one: the four '
                         'pieces of a fast start -- the bootstrap, the stage2 '
                         'that writes flash, the abort, and the magic -- have '
                         'to come from ONE build, because the magic is a hash '
                         'of the loader that same AutoRun spells out. This is '
                         'that build. Release cards do not pass it; a merged '
                         'card gets fast start from whoever packages it, the '
                         'composer page or --dev-card --fast.')
    ap.add_argument('--debug', action='store_true',
                    help='keep the USB shell in, so the camera can be asked '
                         'what happened; never for a release')
    ap.add_argument('--version', default='dev',
                    help='what to call it in README.txt; release_card.py '
                         'passes the real one')
    ap.add_argument('--also-bin', action='append', default=[],
                    metavar='0xADDR:FILE',
                    help='an extra section to place alongside the edition\'s '
                         'own, spelled as build_autorun.py spells it.  OG3K '
                         'passes its canvas and hook writes this way.  They go '
                         'through check() with everything else, so an extra '
                         'section that overlaps the logger or lands in the '
                         'loader\'s read window fails the build rather than '
                         'the camera.')
    ap.add_argument('--vshl-entry', type=lambda s: int(s, 0), default=None,
                    help='optional absolute entry for the extra sections; '
                         'called after the USB worker and gyro launcher')
    ap.add_argument('--loader-hook', action='store_true',
                    help='instant boot (dev cards; releases leave it to the '
                         'merge page)')
    ap.add_argument('--loader-hook-mark', default=None, metavar='ADDR',
                    help='debug: passed to build_autorun.py (see there)')
    ap.add_argument('--four-box-bar', action='store_true',
                    help='passed to build_autorun.py')
    ap.add_argument('--banner', default=None,
                    help='override the screen banner; a merged card is not '
                         'the edition on its own and should not claim to be')
    a = ap.parse_args()
    out = a.out or (HERE / 'release' / a.edition)
    secs = sections(a.edition)
    # sections() no longer ends with an entry section -- the entry is the
    # destination-zero blob launch() makes -- so extras simply go on the end.
    extra = []
    for spec in a.also_bin:
        at, _, path = spec.partition(':')
        if not _:
            raise SystemExit(f'--also-bin wants 0xADDR:FILE, got {spec!r}')
        f = pathlib.Path(path)
        extra.append((int(at, 0), f.read_bytes(), f'extra {f.name}'))
    secs = secs + hook_sites() + extra
    check(secs)

    tmp = pathlib.Path(tempfile.mkdtemp())
    # Padded, not --no-pad.  The shipping cards are written by a Mac, which
    # truncates; this one is written over USB by putfile, and build_autorun's
    # own filler line says why that matters -- "mode 7 overwrites but does not
    # truncate".  A shorter file would leave the tail of the last AutoRun on
    # the card, and the tail of the last AutoRun is the USB shell's worker.
    # The release card carries no USB shell, which is also why a fault that only
    # happens on a card cannot be looked at: there is nothing to ask.  --debug
    # builds the same code with the shell in, so the state words can be read
    # after a failure instead of guessed at.
    # What the screen reads when the load is done.  It names the edition and
    # the version because the two cards are indistinguishable once they are in
    # the camera, and "which build is in there" has been guessed at more than
    # once.
    banner = a.banner or f'fpSup-{BANNER[a.edition]}-{a.version}!'
    # The power-off restore is every loader card's now (build_autorun always
    # adds it; hook_sites above is what puts these hooks in it).  --loader-hook
    # only adds the instant path, which the merge page's Fast Start 2 owns.
    cmd = [sys.executable, str(SHELL / 'build_autorun.py'),
           '--loader', '--banner', banner] + (
               ['--loader-hook'] if a.loader_hook else []) + (
               ['--loader-hook-mark', a.loader_hook_mark]
               if a.loader_hook_mark else []) + (
               ['--four-box-bar'] if a.four_box_bar else []) + (
               ['--store-boot'] if a.store_boot else []) + (
               ['--no-ep-patches'] if a.debug else ['--no-shell']) + [
           # A soft power cycle can leave a previous session's diagnostic patch
           # in the F_WRITE prologue.  Every ordinary image puts it back.
           '--also', f'0x{F_WRITE_AT:08X}:{HERE / "phase_fwrite_restore.S"}',
           '--also', f'0x{PARK_AT:08X}:{SHELL / "templates" / "park.S"}',
           '--out', str(out / 'AutoRun.txt')]
    for at, blob, why in secs:
        f = tmp / f'{at:08x}.bin'
        f.write_bytes(blob)
        cmd += ['--also-bin', f'0x{at:08X}:{f}']
    # The bootstrap and the writer, as one run-in-place section whose entry is
    # its first byte.  build_autorun puts it in the file and names it in the
    # header -- or, on a card that also carries the shell, in the trampoline
    # that calls both.
    boot_blob, writer_len = launch(a.edition)
    bf = tmp / 'gsup_launch.bin'
    bf.write_bytes(boot_blob)
    cmd += ['--boot-bin', f'{bf}:0']
    if a.vshl_entry:
        # build_autorun already orders worker, boot-bin, then this entry.
        cmd += ['--vshl-entry', f'0x{a.vshl_entry:08X}']
    out.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode:
        sys.stderr.write(r.stderr)
        raise SystemExit('build_autorun failed')
    shutil.rmtree(tmp, ignore_errors=True)

    print()
    for at, blob, why in sorted(secs):
        where = ('pool + 0x%05X' % at) if at < 0x40000000 else '0x%08X' % at
        print(f'  {where:>16s}  {len(blob):5d}  {why}')
    (out / 'README.txt').write_text(
        READMES[a.edition].format(version=a.version))
    vshl = out / 'fpSup.BIN'
    autorun = out / 'AutoRun.txt'
    print(f'\n  {autorun}  {len(autorun.read_text().splitlines())} commands')
    print(f'  {vshl}  {vshl.stat().st_size} bytes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
