#!/usr/bin/env python3
"""Reboot the camera and wait for the shell to answer again.

    ./bootmeasure.py "what this card is" [times]

The number worth quoting is not the one this prints.  The camera stamps its own
microsecond clock when the load finishes -- read it afterwards with

    ./host/fpsh mem get 0xC072F6F4,,8

and with `--profile` builds the first of those two words is the moment the
loader got control, so the pair says how much of the boot was the AutoRun and
how much was everything before it.  Those numbers carry no host in them; three
runs spread 35-142 ms.  What this script measures instead is "power-on until
the worker answers", which also carries USB enumeration and the polling
interval -- measured 165-627 ms of spread, and about 580 ms high.

So this is the thing that presses the button, not the thing that holds the
stopwatch.  It is here because the loop around it is fiddly: the camera
re-enumerates, the daemon has to be restarted against the new device, and a
daemon started too early attaches to nothing.

TWO THINGS THAT ARE EASY TO GET WRONG.

Rebooting with the cable attached works, but only with the host's PTP stack out
of the way.  While the descriptor still says class 06/01/01 -- which it does
until our patch lands, and it lands late -- macOS's `ptpcamerad` claims
interface 0 and the shell is unreachable even though the card ran perfectly.
Run a watchdog for the session and tell the user their camera imports are off:

    while :; do pkill -9 ptpcamerad 2>/dev/null; sleep 0.1; done

And `reboot` reloads the firmware image, so the cave and every firmware word we
patched come back stock -- measured by planting 0xDEADBEEF in the cave and
finding zero afterwards.  Whether the power switch does the same is NOT known;
do not assume it from this.
"""
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
FPSH = str(HERE / 'host' / 'fpsh')
FPSHD = str(HERE / 'fpshd')


def sh(*args, timeout=20):
    try:
        return subprocess.run([FPSH, *args], capture_output=True, text=True,
                              timeout=timeout, cwd=HERE).stdout.strip()
    except Exception:
        return ''


def one():
    before = sh('time', 'tickm')
    print(f'  tickm before the reboot: {before or "?"}', flush=True)
    subprocess.Popen([FPSH, 'reboot'], cwd=HERE,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    time.sleep(1.0)
    subprocess.run(['pkill', '-9', '-f', 'fpshd'], capture_output=True)
    time.sleep(0.3)

    for _ in range(200):
        daemon = subprocess.Popen([FPSHD], cwd=HERE, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        time.sleep(0.30)
        if 'pong' in sh('ping', timeout=6):
            tick = sh('time', 'tickm')
            print(f'  first pong: tickm {tick}   (host wall clock '
                  f'{time.time() - t0:.1f}s)', flush=True)
            return tick
        daemon.kill()
        time.sleep(0.12)
    print('  no answer in ninety seconds', flush=True)
    return None


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else 'run'
    times = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    print(f'== {label} ==', flush=True)
    got = []
    for i in range(times):
        print(f'-- {i + 1}/{times}', flush=True)
        answer = one()
        if answer:
            got.append(int(''.join(c for c in answer if c.isdigit())))
        time.sleep(1.5)
    if got:
        print(f'== {label}: {got}  median {sorted(got)[len(got) // 2]} ms  '
              f'spread {max(got) - min(got)} ms', flush=True)
    print('   now read the camera\'s own stamps: '
          'host/fpsh mem get 0xC072F6F4,,8', flush=True)


main()
