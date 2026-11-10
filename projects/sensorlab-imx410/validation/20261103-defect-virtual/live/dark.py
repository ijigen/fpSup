"""Dark take for the DEFC check (lens capped): IMXB substitution SHS 4 + 30 dB (3965), record N s, download frames 1-3.

    python3 -B dark.py TAG [--secs 2] [--pre CMD --post CMD]
Same method as imx410-lab DEFECT_CORRECTION (captures/defectrec2).  USB during the take = the two REC pulses only.
"""
import argparse, json, pathlib, subprocess, sys
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[4]
SHELL = ROOT / 'fpSup' / 'fp_usb_shell'
LAB = ROOT / 'projects' / 'imx410-lab'
sys.path.insert(0, str(SHELL)); sys.path.insert(0, str(LAB))
import bufa_probe as B  # noqa: E402
from putfile import sh  # noqa: E402

SUBS = [(0x0005, 4), (0x0006, 0), (0x003D, 3965 & 0xFF), (0x003E, 3965 >> 8), (0x003F, 3965 & 0xFF), (0x0040, 3965 >> 8)]


def listing(path):
    return [(p[-1], p[-2]) for p in (l.split() for l in sh(f'dir {path}', timeout_ms=20000).splitlines()) if len(p) >= 4]


def alive(step):
    import putfile as pf
    v = pf.mem_get(0xC343B590)[0]
    print(f'alive {step}: imager mode {v}', flush=True)
    if v is None:
        raise SystemExit(f'shell dead after {step}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tag'); ap.add_argument('--secs', default='2')
    ap.add_argument('--pre', action='append', default=[]); ap.add_argument('--post', action='append', default=[])
    a = ap.parse_args()
    out = HERE / a.tag
    clips = lambda: sorted(n for n, s in listing(r'\CINEMA') if s == '<DIR>' and n.startswith('A0'))
    before = set(clips())
    st = B.bus_state()
    B.bus_subs(st, SUBS)
    try:
        cmd = [sys.executable, '-B', 'bufa_probe.py', 'rec', str(out), '--secs', a.secs]
        for p in a.pre: cmd += ['--pre', p]
        for p in a.post: cmd += ['--post', p]
        r = subprocess.run(cmd, cwd=LAB, capture_output=True, text=True)
        print((r.stdout + r.stderr).strip()[-400:])
    finally:
        B.bus_subs(st, [])
    alive('rec + subs off')
    new = sorted(set(clips()) - before)
    if not new:
        raise SystemExit('no new clip')
    clip = new[-1]
    files = {n: int(s) for n, s in listing('\\CINEMA\\' + clip) if s.isdigit()}
    dngs = sorted(n for n in files if n.endswith('.DNG'))
    for n in dngs[:3]:
        subprocess.run([sys.executable, '-B', 'getfile.py', f'\\CINEMA\\{clip}\\{n}', str(out / n), '--size', str(files[n])],
                       cwd=SHELL, capture_output=True, check=True)
        alive(n)
    (out / 'clip.json').write_text(json.dumps(dict(clip=clip, frames=len(dngs), got=dngs[:3])))
    print(json.dumps(dict(tag=a.tag, clip=clip, frames=len(dngs))))


if __name__ == '__main__':
    main()
