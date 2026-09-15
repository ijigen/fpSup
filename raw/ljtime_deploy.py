#!/usr/bin/env python3
"""Time the lossless-JPEG engine across several frame sizes.

    ./ljtime_deploy.py                 print what it would send, send nothing
    ./ljtime_deploy.py --go            place the probe and arm it
    ./ljtime_deploy.py --read          read one result
    ./ljtime_deploy.py --restore       put the firmware's word back
    ./ljtime_deploy.py --fit a.csv     fit collected results

The question this answers: 169.7 Mpix/s was measured once, on one frame size,
with a cold call -- and `FUN_c062fee8` brings up power domain 5, the clock and
IRQ 0x29 *inside* encode, so that measurement includes a fixed cost a recording
loop pays once and a cold call pays every time. Fixed overhead and per-pixel
rate have never been separated, and the difference decides whether
alternate-frame compressed 6K is worth 33% or worth 2%.

    time = overhead + pixels / rate

Two points separate them; three or four make the fit trustworthy.

**Vary the size with the aspect ratio, not with a patch.** The camera's own
still aspect settings crop the sensor, so the engine sees a different pixel
count each time and nothing has to be modified:

    3:2    6064 x 4042   24.51 Mpix     <- the size already measured
    4:3    5389 x 4042   21.78
    16:9   6064 x 3411   20.69
    1:1    4042 x 4042   16.34
    21:9   6064 x 2599   15.76

That is a 1.55x spread, and the two hypotheses predict times 23% apart at the
small end, which a 1 microsecond counter resolves easily.

**The engine cannot be called cold** -- the power domain returns -99 and clock
domain 5 refuses, measured 2026-08-30. The still path already owns both, which
is why this times from inside it rather than trying to take them. That also
means: this does not disturb stills compression, unlike a cold call, which broke
it until a reboot.

Procedure once armed: set an aspect ratio, take one still, `--read`, repeat.
The call counter at +0x14 rises by one per still, so a stale slot cannot be
mistaken for a fresh result.
"""
import argparse
import csv
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
SHELL = HERE.parent / 'fp_usb_shell'
sys.path.insert(0, str(SHELL))

SITE = 0xC037E7AC          # the still path's `bl 0xC05A6920`
STOCK = 0xEB08A05B         # what that word holds
DEFAULT_SLOT = 0xC072E080  # ljtime.S's default -- inside the gyro logger's range
DEFAULT_ADDR = 0xC072F800  # the templates' routine area


def probe_words(addr, slot):
    from armasm import assemble, symbols
    src = HERE / 'ljtime.S'
    defs = (f'SLOT=0x{slot:08X}',)
    blob = assemble(src, defs)
    entry = addr + symbols(src, defs)['enc_timed']
    words = [int.from_bytes(blob[i:i + 4], 'little')
             for i in range(0, len(blob), 4)]
    disp = (entry - SITE - 8) >> 2
    return words, entry, 0xEB000000 | (disp & 0xFFFFFF)


def show(addr, slot):
    words, entry, bl = probe_words(addr, slot)
    print(f'  probe   {len(words) * 4} bytes at 0x{addr:08X}..0x{addr+len(words)*4:08X}, '
          f'entry 0x{entry:08X}')
    print(f'  results 0x{slot:08X}..0x{slot+36:08X}  '
          f't0/t1/result/w/h/count/bitdepth/tileW/tileH')
    print()
    print('  would send:')
    for i, w in enumerate(words):
        print(f'    mem set 0x{addr + i * 4:08X} 0x{w:08X}')
    print(f'    mem set 0x{SITE:08X} 0x{bl:08X}        <- last, and only after a read-back')
    print()
    print(f'  restore: mem set 0x{SITE:08X} 0x{STOCK:08X}')
    print()
    if addr <= 0xC072F8E8 and addr + len(words) * 4 > 0xC072F800:
        print('  NOTE this overlaps open gate\'s rowpatch at 0xC072F800-0xC072F8E8.')
        print('       Use --addr 0xC072E0A0 if an open-gate card is in the camera.')


def deploy(addr, slot):
    from putfile import mem_set, mem_get
    words, entry, bl = probe_words(addr, slot)
    for i, w in enumerate(words):
        a = addr + i * 4
        for _ in range(8):
            mem_set(a, w)
            got = mem_get(a)
            if got and got[0] == w:
                break
        else:
            raise SystemExit(f'  0x{a:08X} would not take 0x{w:08X}')
    print(f'  placed  {len(words) * 4} bytes, every word read back')
    # arm last: a half-written probe reached through the still path is a fault
    for _ in range(8):
        mem_set(SITE, bl)
        got = mem_get(SITE)
        if got and got[0] == bl:
            break
    else:
        raise SystemExit('  the site would not take the branch -- NOT armed')
    print(f'  armed   0x{SITE:08X} = 0x{bl:08X} -> 0x{entry:08X}')
    print('  take a still, then --read')


BITS = {0: 12, 1: 14, 2: 16, 3: 10}


def read(slot, csv_path=None):
    from putfile import mem_get
    w = mem_get(slot, 9)
    if not w:
        raise SystemExit('  no answer')
    t0, t1, res, width, height, n, bd, tw, th = w
    us = (t1 - t0) & 0xFFFFFFFF
    px = width * height
    # the engine pads edge tiles to full size and codes them, so this is the
    # pixel count the hardware actually worked on
    apx = (-(-width // tw) * tw) * (-(-height // th) * th) if tw and th else px
    print(f'  call #{n}  {width}x{height} = {px / 1e6:.2f} Mpix  result={res}  '
          f'{BITS.get(bd, "?")}-bit  tile {tw}x{th}')
    print(f'  tile-aligned {apx / 1e6:.2f} Mpix  (+{100 * (apx - px) / px:.2f}%)')
    print(f'  {us} us  ->  {apx / us:.1f} Mpix/s on coded samples '
          f'({px / us:.1f} on real pixels)')
    if csv_path:
        import os
        new = not os.path.exists(csv_path)
        with open(csv_path, 'a') as f:
            if new:
                f.write('call,width,height,tilew,tileh,pixels,aligned,us,result\n')
            f.write(f'{n},{width},{height},{tw},{th},{px},{apx},{us},{res}\n')
        print(f'  appended to {csv_path}')
    return apx, us


def restore():
    from putfile import mem_set, mem_get
    for _ in range(8):
        mem_set(SITE, STOCK)
        got = mem_get(SITE)
        if got and got[0] == STOCK:
            print(f'  restored 0x{SITE:08X} = 0x{STOCK:08X}')
            return
    raise SystemExit('  did NOT restore -- do not leave it like this')


def fit(path):
    rows = [(int(r.get('aligned') or r['pixels']), int(r['us']))
            for r in csv.DictReader(open(path))]
    rows = sorted(set(rows))
    if len(rows) < 2:
        raise SystemExit('  need at least two sizes')
    n = len(rows)
    sx = sum(p for p, _ in rows); sy = sum(u for _, u in rows)
    sxx = sum(p * p for p, _ in rows); sxy = sum(p * u for p, u in rows)
    slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)     # us per pixel
    inter = (sy - slope * sx) / n                          # us fixed
    rate = 1.0 / slope   # slope is us/pixel, so 1/slope is pixels/us = Mpix/s
    print(f'  {n} points')
    for p, u in rows:
        print(f'    {p / 1e6:6.2f} Mpix   {u:8d} us   ({p / u:6.1f} Mpix/s effective)')
    print()
    print(f'  fixed overhead   {inter / 1000:8.1f} ms')
    print(f'  sustained rate   {rate:8.1f} Mpix/s')
    print()
    fps = 30000 / 1001
    print(f'  at 29.97, alternate-frame compression allows '
          f'{rate / (0.5 * fps):.2f} Mpix')
    print(f'  break-even is 167 Mpix/s; below it the design gains nothing')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--addr', type=lambda s: int(s, 0), default=DEFAULT_ADDR)
    ap.add_argument('--slot', type=lambda s: int(s, 0), default=DEFAULT_SLOT)
    ap.add_argument('--csv', metavar='CSV', help='--read appends a row here')
    ap.add_argument('--go', action='store_true')
    ap.add_argument('--read', action='store_true')
    ap.add_argument('--restore', action='store_true')
    ap.add_argument('--fit', metavar='CSV')
    a = ap.parse_args()
    if a.fit:
        fit(a.fit)
    elif a.read:
        read(a.slot, a.csv)
    elif a.restore:
        restore()
    elif a.go:
        deploy(a.addr, a.slot)
    else:
        show(a.addr, a.slot)
        print('  nothing was sent. --go to place it.')


if __name__ == '__main__':
    main()
