#!/usr/bin/env python3
"""Assemble a resident routine, write it into the cave, and arm its hook.

    ./load.py ../../codex/stage6_gyro_double_buffer_hook.S \
              --addr 0xC072DE64 --entry stage6_hook --hook 0xC00D0794

Unlike inject.py, which fires a routine once and puts the call site back, this
loads code that stays.  It is how the gyro logger is developed: assemble, load,
watch, change one thing, load again -- without burning a card per iteration.

Every step is separate and every step is checked.  In particular the loader
proves the write path reaches the target address before it writes 434 words
there: the v1 worker silently refused writes below 0xC072F100 and read back the
old value, which is the kind of failure that makes everything downstream look
fine while being built on nothing.
"""
import argparse, pathlib, re, subprocess, sys, time

from armasm import assemble, symbols, words

HERE = pathlib.Path(__file__).resolve().parent
FPSH = HERE / 'host' / 'fpsh'

CAVE_LOW  = 0xC072DE64          # first byte the injection region owns
CAVE_HIGH = 0xC072F000          # the shell's own state starts here


def sh(*cmd) -> str:
    r = subprocess.run([str(FPSH), *cmd], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"fpsh {' '.join(cmd)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def mem_set(addr: int, value: int) -> None:
    sh(f'mem set 0x{addr:08X} 0x{value:08X}')


def mem_get(addr, count):
    """Read `count` words.  The shell answers one line per word:

        get : A:0xc072f000, D:0x4C485356

    Parsed exactly rather than by scraping hex tokens, so a reply that is not a
    dump -- an error, an echo -- yields nothing instead of plausible numbers.
    """
    out = sh(f'mem get 0x{addr:08X},,0x{count * 4:X}')
    seen = {int(a, 16): int(d, 16) for a, d in
            re.findall(r'A:0x([0-9A-Fa-f]+),\s*D:0x([0-9A-Fa-f]+)', out)}
    return [seen[addr + i * 4] for i in range(count) if addr + i * 4 in seen]


def prove(addr: int) -> None:
    """Write a marker, read it back, restore.  Refuse to continue if it lies."""
    original = mem_get(addr, 1)
    marker = 0xC0DEC0DE
    mem_set(addr, marker)
    got = mem_get(addr, 1)
    if not got:
        raise SystemExit(f'0x{addr:08X}: mem get returned nothing parseable — try --probe')
    if got[0] != marker:
        raise SystemExit(
            f'0x{addr:08X}: wrote {marker:08X}, read back {got[0]:08X}.\n'
            'The write did not reach the target.  Nothing has been loaded.')
    if original:
        mem_set(addr, original[0])
    print(f'  proof   0x{addr:08X} accepts writes and reads back what was written')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('source')
    ap.add_argument('--addr',  type=lambda s: int(s, 0), default=CAVE_LOW)
    ap.add_argument('--entry', default=None, help='symbol the hook should branch to')
    ap.add_argument('--hook',  type=lambda s: int(s, 0), default=None)
    ap.add_argument('--probe', action='store_true', help='dump one raw mem get and stop')
    ap.add_argument('--no-verify', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    if a.probe:
        print(sh(f'mem get 0x{a.addr:08X},,0x20'))
        return 0

    src = pathlib.Path(a.source)
    code = assemble(src)
    w = words(code)
    end = a.addr + len(code)
    print(f'  source  {src.name}')
    print(f'  code    {len(code)} bytes, {len(w)} words, '
          f'0x{a.addr:08X}..0x{end:08X}')

    if a.addr < CAVE_LOW or end > CAVE_HIGH:
        raise SystemExit(f'0x{a.addr:08X}..0x{end:08X} leaves the injection region '
                         f'0x{CAVE_LOW:08X}..0x{CAVE_HIGH:08X}')
    print(f'  headroom {CAVE_HIGH - end} bytes to the shell worker')

    entry = a.addr
    if a.entry:
        sy = symbols(src)
        if a.entry not in sy:
            raise SystemExit(f'no symbol {a.entry!r} in {src.name}')
        entry = a.addr + sy[a.entry]
        print(f'  entry   {a.entry} at 0x{entry:08X}')

    if a.dry_run:
        return 0

    prove(a.addr)

    t0 = time.time()
    for i, word in enumerate(w):
        mem_set(a.addr + i * 4, word)
        if i % 64 == 63:
            print(f'\r  write   {i + 1}/{len(w)}', end='', flush=True)
    print(f'\r  write   {len(w)}/{len(w)} words in {time.time() - t0:.1f}s')

    if not a.no_verify:
        bad = 0
        for base in range(0, len(w), 16):
            got = mem_get(a.addr + base * 4, min(16, len(w) - base))
            for i, want in enumerate(w[base:base + 16]):
                if i >= len(got) or got[i] != want:
                    bad += 1
                    if bad <= 4:
                        have = f'{got[i]:08X}' if i < len(got) else '--------'
                        print(f'  MISMATCH 0x{a.addr + (base + i) * 4:08X} '
                              f'want {want:08X} got {have}')
        if bad:
            raise SystemExit(f'{bad} words did not verify — hook NOT armed')
        print(f'  verify  {len(w)} words match')

    if a.hook:
        # a24-bit ARM branch: b <entry> placed at the hook site
        disp = (entry - a.hook - 8) >> 2
        if not -0x800000 <= disp < 0x800000:
            raise SystemExit('hook site is out of branch range of the entry')
        mem_set(a.hook, 0xEA000000 | (disp & 0xFFFFFF))
        print(f'  armed   0x{a.hook:08X} -> 0x{entry:08X}')
    else:
        print('  hook    not armed (pass --hook to arm)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
