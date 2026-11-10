#!/usr/bin/env python3
"""Timestamped 100 ms ping loop around one key (the first-MENU probe, v1 live checklist item 2).

    python3 -B pingloop.py --key MENU --before 2 --after 15 --out 04-pingloop.txt

Pings every 100 ms for --before s, sends the key ONCE (its reply may time out: that alone is NOT a block -- live-v1's
rc=-7 was a single key reply under fpshd's short timeout), keeps pinging for --after s, and writes one line per ping:
t (s from start), rc, reply.  A block = pings stop answering and do not come back; a ~2 s silence that recovers is a
GUI / LV rebuild.  Never during recording or playback."""
import argparse, subprocess, time

FPSH = '/Users/dido/Developer.localized/SIGMAfp_re/fpSup/fp_usb_shell/host/fpsh'


def sh(*a, timeout=3):
    try:
        r = subprocess.run([FPSH, *a], capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip().replace('\n', ' ')[:80]
    except subprocess.TimeoutExpired:
        return -1, 'host timeout'


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--key', default='MENU')
    ap.add_argument('--before', type=float, default=2)
    ap.add_argument('--after', type=float, default=15)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    t0, lines = time.time(), []
    def loop(until):
        while time.time() - t0 < until:
            s = time.time(); rc, out = sh('ping')
            lines.append(f'{s - t0:7.2f} ping rc={rc} {out}')
            time.sleep(max(0, 0.1 - (time.time() - s)))
    loop(a.before)
    s = time.time(); rc, out = sh('key', a.key + 'ON', timeout=20)
    lines.append(f'{s - t0:7.2f} key {a.key}ON rc={rc} {out} ({time.time() - s:.2f} s)')
    loop(a.before + a.after)
    open(a.out, 'w').write('\n'.join(lines) + '\n')
    gaps = [float(l.split()[0]) for l in lines if ' ping rc=0' in l]
    worst = max((b - x for x, b in zip(gaps, gaps[1:])), default=0)
    print(f'{len(lines)} lines -> {a.out}; longest gap between answered pings {worst:.2f} s')


if __name__ == '__main__':
    main()
