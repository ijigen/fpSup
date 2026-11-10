"""Screenshot when `dir \\DCIM\\100SIGMA` is truncated (ui_drive.shot cannot see new files):
press CAPTURE, then probe SS__<n>.JPG upward from the last known number and fetch it.

    python3 -B shot.py TAG          -> validation/.../shots/<time>-TAG-SS<n>.jpg
"""
import pathlib, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
SHELL = HERE.parents[3] / 'fpSup' / 'fp_usb_shell'
sys.path.insert(0, str(SHELL))
from putfile import sh  # noqa: E402

STATE = HERE / 'shots' / 'last.txt'


def fetch(n, dst, size=900000):
    if dst.exists():
        dst.unlink()
    subprocess.run([sys.executable, '-B', 'getfile.py', f'\\DCIM\\100SIGMA\\SS__{n:04d}.JPG', str(dst),
                    '--size', str(size), '--partial'], cwd=SHELL, capture_output=True)
    return dst.exists() and dst.stat().st_size > 0


def capture(last, probe):
    sh('key CAPTUREON', retries=0)
    sh('key CAPTUREOFF', retries=0)
    for _ in range(20):
        time.sleep(0.5)
        if fetch(last + 1, probe, 64):
            return last + 1
    raise SystemExit(f'SS__{last + 1:04d} did not appear')


def main():
    """Two captures, the second kept: the first can still show the previous screen (2026-11-03 SS3058-3062)."""
    tag = sys.argv[1] if len(sys.argv) > 1 else 'shot'
    out = HERE / 'shots'
    out.mkdir(exist_ok=True)
    last = int(STATE.read_text()) if STATE.exists() else 3056
    probe = out / '.probe'
    last = capture(last, probe)
    time.sleep(1.0)
    n = capture(last, probe)
    time.sleep(1.0)                                   # let the file finish growing
    dst = out / f'{time.strftime("%H%M%S")}-{tag}-SS{n:04d}.jpg'
    if not fetch(n, dst):
        raise SystemExit('fetch failed')
    STATE.write_text(str(n))
    print(dst)


if __name__ == '__main__':
    main()
