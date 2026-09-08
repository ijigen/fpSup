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
    \\VSHL.BIN      everything else, as sections

The loader reads VSHL.BIN into the camera's DMA pool and branches to stage2,
which places every section and then branches to the file's entry.  Sections
whose destination is below 0x40000000 are OFFSETS into that pool -- the pool's
address is decided at boot, so a build cannot name it, but it can name an
offset.  That is how four kilobytes of writer gets somewhere the two-kilobyte
cave could never hold it.

The entry is gsup_entry, fifty-six bytes at the bottom of the cave, which reads
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
import struct
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

Put AutoRun.txt and VSHL.BIN in the root of the SD card the camera boots
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

Put AutoRun.txt and VSHL.BIN in the root of the SD card the camera boots
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


EDITIONS = {
    'base': 'ring_task.S',
    'gcsv': 'gcsv_task.S',
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
    for name, (at, src, defines, _site, _orig, _thumb) in S.PRODUCERS.items():
        # The mode hook belongs to the editions that write their own log: it
        # is what makes a take's frames landscape upright, and Base's readers
        # get the orientation out of the .GYR header instead.  Placing it
        # unarmed would only be sixty bytes of cave nobody branches to.
        if name == 'mode' and edition == 'base':
            continue
        blob = assemble(HERE / src, defines)
        out.append((at, blob, name))

    # The producers reach each other through words only a build can fill in:
    # they are separate blobs and a branch cannot resolve across them.
    space_syms = symbols(HERE / 'stream_space.S', ())
    space_at = S.PRODUCERS['space'][0]
    drain_at = S.PRODUCERS['drain'][0]
    for word, addr, why in (
            (S.STREAM_CLAIMFN, space_at + space_syms['stream_claim'], 'stream_claim'),
            (S.STREAM_COMMITFN, space_at + space_syms['stream_commit'], 'stream_commit'),
            (S.STREAM_FLUSHFN, space_at + space_syms['stream_flush'], 'stream_flush'),
            (S.STREAM_DRAINFN,
             drain_at + symbols(HERE / 'gyro_drain.S', ())['gyro_drain'], 'gyro_drain')):
        out.append((word, struct.pack('<I', addr), f'-> {why}'))

    # The writer, in the pool, by offset.  Patched with its own routine table:
    # the same function the USB deploy uses, so the two blobs are the same bytes.
    src = EDITIONS[edition]
    code = assemble(HERE / src, ())
    code = R.patch_offsets(code, symbols(HERE / src, ()))
    out.append((R.CODE_POOL_OFF, code, f'{src[:-2]} (pool)'))

    out.append((ENTRY_AT, assemble(HERE / 'gsup_entry.S', ()), 'gsup_entry'))
    return out


def check(secs):
    """Nothing overlaps, and nothing in the cave reaches the park stub."""
    spans = [(a, a + len(b), w) for a, b, w in secs]
    for i, (alo, ahi, aw) in enumerate(spans):
        for blo, bhi, bw in spans[i + 1:]:
            if alo < bhi and blo < ahi:
                raise SystemExit(f'{aw} and {bw} overlap')
    for lo, hi, w in spans:
        if lo < 0x40000000:
            continue                    # pool-relative
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
    ap.add_argument('--debug', action='store_true',
                    help='keep the USB shell in, so the camera can be asked '
                         'what happened; never for a release')
    ap.add_argument('--version', default='dev',
                    help='what to call it in README.txt; release_card.py '
                         'passes the real one')
    a = ap.parse_args()
    out = a.out or (HERE / 'release' / a.edition)
    secs = sections(a.edition)
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
    banner = f'fpSup-{BANNER[a.edition]}-{a.version}!'
    cmd = [sys.executable, str(SHELL / 'build_autorun.py'),
           '--loader', '--banner', banner] + (
               [] if a.debug else ['--no-shell']) + [
           '--vshl-entry', f'0x{ENTRY_AT:08X}',
           # A soft power cycle can leave a previous session's diagnostic patch
           # in the F_WRITE prologue.  Every ordinary image puts it back.
           '--also', f'0x{F_WRITE_AT:08X}:{HERE / "phase_fwrite_restore.S"}',
           '--also', f'0x{PARK_AT:08X}:{SHELL / "templates" / "park.S"}',
           '--out', str(out / 'AutoRun.txt')]
    for at, blob, why in secs:
        f = tmp / f'{at:08x}.bin'
        f.write_bytes(blob)
        cmd += ['--also-bin', f'0x{at:08X}:{f}']
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
    vshl = out / 'VSHL.BIN'
    autorun = out / 'AutoRun.txt'
    print(f'\n  {autorun}  {len(autorun.read_text().splitlines())} commands')
    print(f'  {vshl}  {vshl.stat().st_size} bytes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
