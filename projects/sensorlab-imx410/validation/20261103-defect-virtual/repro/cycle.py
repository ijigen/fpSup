"""Freeze repro: N x (sq_test 22 = stock commit, sq_test 19 = push the QS selection = a recipe commit + defect build),
standby only, the shell probed after each.  The block address comes from this boot's LOAD.LOG (it moves between boots).

    python3 -B cycle.py N [--build-json default-build/build-*.json]
"""
import argparse, glob, json, pathlib, re, subprocess, sys, time
HERE = pathlib.Path(__file__).resolve().parent
SHELL = HERE.parents[4] / 'fpSup' / 'fp_usb_shell'
sys.path.insert(0, str(SHELL))
import putfile as pf  # noqa: E402
from callfn import call  # noqa: E402

NAMES = ("bytes abi armed active cur mode_id pid result detail commits refusals lv_reloads owed picks lookups canvases "
         "recrates standby_picks carrier carrier_sets fast commit_us gated blacks defc defc_builds defc_skips defc_loads "
         "defc_last").split()


def base_of(ver):
    log = HERE / 'LOAD.LOG'
    subprocess.run([sys.executable, '-B', 'getfile.py', r'\fpSup\LOAD.LOG', str(log), '--size', '0x2000', '--partial'],
                   cwd=SHELL, capture_output=True)
    m = re.search(r'^0A ([0-9A-F]{8}) [0-9A-F]{8} SensorLab-IMX410_v' + re.escape(ver) + r'\.BIN',
                  log.read_bytes().replace(b'\0', b'').decode('ascii', 'replace'), re.M)
    if not m:
        raise SystemExit(f'SensorLab {ver} not loaded')
    return int(m.group(1), 16)


def st(sq):
    ok, a = call(sq, r0=17)
    w = pf.mem_get(a, len(NAMES))
    return {k: (v if v is None or v < 0x80000000 else v - (1 << 32)) for k, v in zip(NAMES, w)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('n', type=int); ap.add_argument('--ver', default='0.7.25test')
    ap.add_argument('--sq-off', type=int, required=True)
    a = ap.parse_args()
    sq = base_of(a.ver) + a.sq_off
    print(f'sq_test at 0x{sq:08X}', flush=True)
    if 'app_current -> 2' not in pf.sh('status get app_current'):
        raise SystemExit('not in CINE')
    if 'is_recording -> 0' not in pf.sh('status get is_recording'):
        raise SystemExit('recording')
    s0 = st(sq); print('start', {k: s0[k] for k in ('active', 'mode_id', 'commits', 'defc_builds', 'result')}, flush=True)
    for i in range(a.n):
        call(sq, r0=22); time.sleep(0.5)
        call(sq, r0=19); time.sleep(0.5)
        s = st(sq)
        if s['commits'] is None:
            raise SystemExit(f'cycle {i}: shell dead')
        print(i, {k: s[k] for k in ('active', 'mode_id', 'commits', 'result', 'defc_builds', 'defc_last', 'commit_us')},
              flush=True)


if __name__ == '__main__':
    main()
