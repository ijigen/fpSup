#!/usr/bin/env python3
"""Per-take driver for 0.0.6test binning checks (2026-11-10).
    python3 -B takes.py LABEL N    -> N takes of 1 s (rec_until), fetch frames 1-2 of each, DNG shift check -> takes.jsonl
No USB while recording (rec_until only sends the stop pulse); 12 s wait after each stop."""
import json, pathlib, subprocess, sys, time
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[4]
SHELL = ROOT / 'fpSup/fp_usb_shell'
sys.path.insert(0, str(SHELL))
from putfile import sh  # noqa: E402

def clips():
    return sorted(l.split()[-1] for l in sh(r'dir \CINEMA').splitlines() if 'A001_' in l)

def frames(clip):
    out = {}
    for l in sh(rf'dir \CINEMA\{clip}').splitlines():
        p = l.split()
        if p and p[-1].endswith('.DNG'):
            out[p[-1]] = int(p[-2])
    return out

label, n = sys.argv[1], int(sys.argv[2])
dst = HERE / 'dng'; dst.mkdir(exist_ok=True)
for i in range(n):
    before = clips()
    r = subprocess.run([sys.executable, '-B', str(ROOT / 'fpSup/lossless/rec_until.py'), '1'], capture_output=True, text=True)
    time.sleep(12)
    after = clips()
    new = [c for c in after if c not in before]
    if not new:
        raise SystemExit(f'no new clip: {r.stdout} {r.stderr}')
    clip = new[-1]
    fr = frames(clip)
    names = sorted(fr)[:2]
    paths = []
    for nm in names:
        p = dst / nm
        subprocess.run([sys.executable, '-B', str(SHELL / 'getfile.py'), rf'\CINEMA\{clip}\{nm}', str(p), '--size', str(fr[nm])],
                       capture_output=True, text=True, cwd=SHELL)
        paths.append(str(p))
    s = subprocess.run([sys.executable, str(HERE / 'shift.py'), *paths], capture_output=True, text=True).stdout.strip()
    rec = dict(label=label, clip=clip, n_frames=len(fr), shift=json.loads(s) if s else None)
    with open(HERE / 'takes.jsonl', 'a') as f:
        f.write(json.dumps(rec) + '\n')
    print(i + 1, '/', n, rec, flush=True)
