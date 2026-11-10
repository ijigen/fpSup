"""Repeat: bus-logged take (bufa_probe rec) -> download frames 1-2 of the newest clip -> frame-1 row shift.

    python3 -B takes.py START COUNT [--secs 2]
USB during a take carries only the two REC key pulses (Bei 2026-11-03: sending stop is fine).
"""
import argparse, json, pathlib, re, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SHELL = ROOT / 'fpSup' / 'fp_usb_shell'
LAB = ROOT / 'projects' / 'imx410-lab'
VENV = ROOT / 'projects' / 'cdng-image' / '.venv' / 'bin' / 'python'
sys.path.insert(0, str(SHELL))
from putfile import sh  # noqa: E402

SHIFT = r'''
import sys, json, numpy as np, tifffile
a, b = (tifffile.imread(p)[200:-200, 200:-200].astype(np.float32) for p in sys.argv[1:3])
H, W = a.shape; r = {}
for dy in range(-3, 4):
    for dx in range(-2, 3):
        A = a[max(dy,0):H+min(dy,0), max(dx,0):W+min(dx,0)]; B = b[max(-dy,0):H-max(dy,0), max(-dx,0):W-max(dx,0)]
        r[(dy, dx)] = float(np.abs(A - B).mean())
k = min(r, key=r.get)
print(json.dumps(dict(dy=k[0], dx=k[1], err=round(r[k], 2), err00=round(r[(0, 0)], 2), shape=list(a.shape))))
'''


def listing(path):
    rows = []
    for line in sh(f'dir {path}', timeout_ms=20000).splitlines():
        p = line.split()
        if len(p) >= 4:
            rows.append((p[-1], p[-2]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('start', type=int)
    ap.add_argument('count', type=int)
    ap.add_argument('--secs', type=float, default=2.0)
    a = ap.parse_args()
    clip_dirs = lambda: sorted(n for n, s in listing(r'\CINEMA') if s == '<DIR>' and n.startswith('A001_'))
    for i in range(a.start, a.start + a.count):
        out = HERE / 'bus' / f't{i:02d}'
        before = set(clip_dirs())
        if not (out / 'mode_now.txt').exists():           # a take already recorded here is only analysed
            r = subprocess.run([sys.executable, '-B', 'bufa_probe.py', 'rec', str(out), '--secs', str(a.secs)],
                               cwd=LAB, capture_output=True, text=True)
            tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
            new = sorted(set(clip_dirs()) - before)
            if r.returncode or not new or not (out / 'mode_now.txt').exists():
                print(json.dumps(dict(take=i, error='take failed', rc=r.returncode, new=new, tail=tail)), flush=True)
                continue
            clip = new[-1]
        else:
            tail = ['already recorded']
            clip = json.loads((out / 'clip.json').read_text())['clip'] if (out / 'clip.json').exists() else \
                sorted(before)[-1]
        (out / 'clip.json').write_text(json.dumps(dict(clip=clip)))
        files = {n: int(s) for n, s in listing('\\CINEMA\\' + clip) if s.isdigit()}
        dngs = sorted(n for n in files if n.endswith('.DNG'))
        got = []
        for n in dngs[:2]:
            dst = out / n
            subprocess.run([sys.executable, '-B', 'getfile.py', f'\\CINEMA\\{clip}\\{n}', str(dst),
                            '--size', str(files[n])], cwd=SHELL, capture_output=True, check=True)
            got.append(str(dst))
        s = json.loads(subprocess.run([str(VENV), '-c', SHIFT, *got], capture_output=True, text=True,
                                      check=True).stdout)
        rec = dict(take=i, clip=clip, frames=len(dngs), bus=tail, purple=s['dy'] % 2 == 1, **s)
        (out / 'result.json').write_text(json.dumps(rec, indent=1))
        print(json.dumps(rec), flush=True)


if __name__ == '__main__':
    main()
