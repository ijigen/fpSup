#!/usr/bin/env python3
"""Everything Gyroflow needs for one take, off the camera in one command.

    ./gyro/fetchclip.py A001_009 -o ~/takes

    A001_009.gcsv    the gyro log, built by the camera itself
    A001_009.GYR     the raw capture it came from
    A001_009.json    the lens profile

The camera writes the .gcsv when a take stops, so the conversion is already done;
this fetches it and builds the profile to go with it. The profile needs the
sensor mode (in the .GYR), the frame size and focal length (in the frame's EXIF,
where the camera puts them) and the lens distortion table (in RAM, if the camera
has data for the mounted lens) -- so nothing has to be typed in or measured.

The .gcsv is verified against the host decoder before it is handed over. They have
matched byte for byte on every take so far, and the day they do not is the day to
find out, not to trust the camera's arithmetic silently.
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHELL = HERE.parent / 'fp_usb_shell'
sys.path.insert(0, str(SHELL))

import putfile as P                                            # noqa: E402
from decode import read_capture as decode_capture               # noqa: E402


def card_files(clip):
    """What the card holds for this clip: name -> size."""
    out = {}
    for line in P.sh('dir', retries=3).splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[-1].upper().startswith(clip.upper()):
            try:
                out[parts[-1]] = int(parts[-2])
            except ValueError:
                pass
    return out


def first_frame(clip):
    listing = P.sh(f'dir \\CINEMA\\{clip}', retries=3)
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[-1].upper().endswith('.DNG'):
            return parts[-1], int(parts[-2])
    return None, 0


def fetch(remote, size, dest):
    r = subprocess.run([sys.executable, str(SHELL / 'getfile.py'), remote,
                        str(dest), '--size', str(size)],
                       capture_output=True, text=True)
    if not dest.exists() or dest.stat().st_size != size:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f'  could not fetch {remote}')
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('clip', help='e.g. A001_009')
    # Somewhere that survives: the job's scratch directory does not, and a
    # profile is only useful next to the clip it belongs to.
    ap.add_argument('-o', '--out', type=Path,
                    default=HERE.parent.parent / 'out' / 'gyroflow')
    ap.add_argument('--keep-frame', action='store_true',
                    help='keep the DNG frame the profile was read from')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    clip = a.clip.upper()

    if P.sh('version', retries=3).startswith('ERR'):
        raise SystemExit('the camera is not answering')

    have = card_files(clip)
    # The camera writes .gcsv now; older cards carry .CSV from before the
    # rename, and there is no reason a clip shot last week should stop working.
    gyr_name = f'{clip}.GYR'
    csv_name = f'{clip}.gcsv'
    if csv_name not in have and f'{clip}.CSV' in have:
        csv_name = f'{clip}.CSV'
    if gyr_name not in have:
        raise SystemExit(f'no {gyr_name} on the card')

    gyr = fetch(f'\\\\{gyr_name}', have[gyr_name], a.out / gyr_name)
    print(f'  {gyr_name:16s} {have[gyr_name]:>9,} bytes')

    csv = None
    if csv_name in have and have[csv_name] > 0:
        csv = fetch(f'\\\\{csv_name}', have[csv_name], a.out / csv_name)
        print(f'  {csv_name:16s} {have[csv_name]:>9,} bytes')
    else:
        print(f'  {csv_name:16s} not on the card; building it here instead')

    # The camera's arithmetic, checked against ours.
    ref = a.out / f'{clip}.host.csv'
    subprocess.run([sys.executable, str(HERE / 'decode.py'), str(gyr),
                    '--gcsv', str(ref)], capture_output=True, text=True, check=True)
    if csv:
        def body(p):
            lines = p.read_text(errors='replace').splitlines()
            i = next((k for k, l in enumerate(lines) if l.startswith('t,gx')), 0)
            return lines[i:]
        same = body(csv) == body(ref)
        print(f'  camera vs host   {len(body(csv)):,} lines, '
              + ('identical' if same else '*** THEY DIFFER ***'))
        ref.unlink()
        if not same:
            raise SystemExit('  the camera and the decoder disagree; keeping both')
    else:
        ref.rename(a.out / csv_name)
        print(f'  {csv_name:16s} written from the .GYR')

    # What the clip itself says its frame rate is, against what the mode says.
    #
    # SPP_metadata.xmp carries the clip's total size in kilobytes, and every
    # frame is the same size, so the count follows -- and with the capture's
    # duration, so does the rate. A001_014 works out at 939 frames over 31.5 s,
    # near thirty, while its recorded mode is 60. One of the two is wrong and
    # the profile would carry the wrong one without saying so.
    #
    # The gyro starts before the video and ends after it, so this always reads a
    # little low; only a disagreement worth a factor is worth reporting.
    def implied_fps():
        try:
            meta = a.out / '_meta.xmp'
            r = P.sh(f'dir \\CINEMA\\{clip}', retries=3)
            msize = fsize = 0
            for line in r.splitlines():
                parts = line.split()
                if len(parts) >= 4 and parts[-1].upper().endswith('.XMP'):
                    msize = int(parts[-2])
                if len(parts) >= 4 and parts[-1].upper().endswith('.DNG') and not fsize:
                    fsize = int(parts[-2])
            if not (msize and fsize):
                return None
            fetch(f'\\CINEMA\\{clip}\\SPP_metadata.xmp', msize, meta)
            import re
            total = int(re.search(r'TotalSize>(\d+)', meta.read_text()).group(1))
            meta.unlink()
            cap = decode_capture(gyr)
            secs = sum(len(b.samples) for b in cap.blocks) * cap.period_us / 1e6
            return (total * 1024 / fsize) / secs if secs else None
        except Exception:
            return None

    frame_name, frame_size = first_frame(clip)
    if not frame_name:
        raise SystemExit(f'  no frames in \\CINEMA\\{clip}: cannot build a profile')
    frame = fetch(f'\\CINEMA\\{clip}\\{frame_name}', frame_size,
                  a.out / ('_frame.DNG' if not a.keep_frame else frame_name))

    # The distortion table only exists for lenses the camera has data for. A
    # LUMIX S 40/F2 has none -- the identity table is all that is loaded -- and
    # a profile without distortion is honest about that, where a fabricated one
    # would not be.
    dist = subprocess.run([sys.executable, str(HERE / 'lens_dist.py')],
                          capture_output=True, text=True)
    table = None
    for line in dist.stdout.splitlines():
        if line and not line.startswith('#'):
            table = line.strip()
    print('  distortion       ' + ('read from the lens' if table
                                   else 'none for this lens; left at zero'))

    prof = a.out / f'{clip}.json'
    cmd = [sys.executable, str(HERE / 'lens_profile.py'), str(frame),
           '--gyr', str(gyr), '--out', str(prof)]
    if table:
        cmd += ['--dist-table', table]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not prof.exists():
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit('  could not build the profile')
    for line in r.stdout.splitlines():
        if line.startswith(('clip', 'mode', 'focal', 'readout')):
            print('  ' + line)
    got = implied_fps()
    if got:
        import json as _json
        claimed = _json.loads(prof.read_text())['name'].split('@')[-1].split()[0]
        try:
            claimed = float(claimed)
        except ValueError:
            claimed = 0.0
        # The sensor may run faster than the clip and the recorder keep every
        # nth frame -- FHD 29.97 is shot with the sensor held at MONIT1_60, so
        # the mode reads 60 against a 30 fps clip and both are right. The
        # rolling shutter is per sensor frame either way, which is what the
        # profile carries. Only a ratio that is not a small whole number means
        # something is actually wrong.
        ratio = claimed / got if got else 0
        if claimed and not any(abs(ratio - k) < 0.25 for k in (1, 2, 3, 4)):
            print(f'  *** the clip works out at {got:.1f} fps against the mode\'s '
                  f'{claimed:.2f} -- not a whole multiple, so one of them is wrong. '
                  f'The profile carries the mode\'s rolling shutter. ***')
        elif claimed and abs(ratio - 1) > 0.25:
            print(f'  sensor        {claimed:.0f} fps for a {got:.0f} fps clip '
                  f'(every {round(ratio)}{"nd" if round(ratio)==2 else "rd" if round(ratio)==3 else "th"} '
                  f'frame kept); the readout time is per sensor frame')
    if not a.keep_frame:
        frame.unlink()
    print(f'\n  {a.out}/')
    for f in sorted(a.out.glob(f'{clip}.*')):
        print(f'    {f.name:20s} {f.stat().st_size:>9,}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
