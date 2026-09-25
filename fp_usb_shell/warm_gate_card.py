#!/usr/bin/env python3
"""Warm-boot gate, minimal test card (2026-09-25).  NOT a product.

    ./warm_gate_card.py build --out DIR     # AutoRun.txt + fpSup.BIN for the card
    ./warm_gate_card.py check               # over the shell, after a boot

The card is an ordinary --loader USB-shell card whose AutoRun, after the shell
is up, also writes templates/gate.S into the loader's own 0x200 block and points
the firmware's one AutoRun call (0xC03DA420) at it.  Nothing happens on that
boot.  The power switch is a warm restart and keeps both, so on the NEXT boot the
gate runs before the AutoRun: it restores 0xC03DA420 first, calls the loader that
is still in the cave, and skips the AutoRun if stage2 ran.

Expected, powering off with the switch each time:

    boot 1  progress bar, banner, then "GATE-ARMED"      (slow path, installs)
    boot 2  no bar, no banner; shell answers              (gate loaded the BIN)
    boot 3  like boot 2, and every warm boot after it
            (--one-shot: like boot 1, the gate disarmed itself)

`check` tells the three cases apart: gate never ran / ran and loaded / ran and
fell back to the AutoRun.  See projects/usb-shell-sup/notes/WARM_BOOT_GATE.md.
"""
import argparse, pathlib, re, struct, subprocess, sys

from armasm import assemble

HERE = pathlib.Path(__file__).resolve().parent

CAVE_LOW   = 0xC072DE64
LOADER_END = CAVE_LOW + 0x200
CAVE_BUMP  = 0xC072E060
GATE_AT    = 0xC072DFA0      # in the loader's block, above the loader (which
                             # grew to 0xC072DFA0 with the loader hook entry)
MARK       = 0xC072E050      # 4 words, up to CAVE_BUMP
LOAD_DONE  = 0xC072F6F8      # stage2's LOAD_DONE_US
SITE       = 0xC03DA420
SITE_ORIG  = 0xEB0000CC
ECHO_SLOT, ECHO_ORIG = 0xC0BAC2F8, 0xC03D99A0
DCACHE, ICACHE = 0xC000E91C, 0xC000EABC
PAD_TO = 32768


def gate_code(one_shot=False):
    code = assemble(HERE / 'templates' / 'gate.S',
                    [f'LOADER=0x{CAVE_LOW:08X}', f'LOAD_DONE=0x{LOAD_DONE:08X}',
                     f'MARK=0x{MARK:08X}'] + (['ONE_SHOT=1'] if one_shot else []))
    if GATE_AT + len(code) > MARK:
        sys.exit(f'gate is {len(code)} bytes, runs into MARK')
    words = struct.unpack(f'<{len(code) // 4}I', code)
    # immediates only: no ldr/str pc-relative, no literal pool
    for i, w in enumerate(words):
        if (w & 0x0E000000) in (0x04000000, 0x06000000) and ((w >> 16) & 0xF) == 15:
            sys.exit(f'gate word {i} reads pc-relative: 0x{w:08X}')
    return words


def bl(frm, to):
    return 0xEB000000 | (((to - frm - 8) >> 2) & 0xFFFFFF)


def build(out: pathlib.Path, banner: str, one_shot=False):
    out.mkdir(parents=True, exist_ok=True)
    ar = out / 'AutoRun.txt'
    subprocess.run([sys.executable, '-B', str(HERE / 'build_autorun.py'), '--loader',
                    '--out', str(ar), '--banner', banner], check=True)
    text = ar.read_text()

    # The loader has to end below the gate.
    lw = [int(a, 16) for a in re.findall(r'^mem set (0x[0-9A-Fa-f]+) ', text, re.M)
          if CAVE_LOW <= int(a, 16) < LOADER_END]
    if not lw or max(lw) + 4 > GATE_AT:
        sys.exit(f'loader reaches 0x{max(lw) + 4:08X}, gate is at 0x{GATE_AT:08X}')
    for a in (GATE_AT, MARK, CAVE_BUMP, SITE):
        if re.search(rf'^mem set 0x{a:08X} ', text, re.M | re.I):
            sys.exit(f'base AutoRun already writes 0x{a:08X}')

    words = gate_code(one_shot)
    body = text.split('# pad --', 1)[0].rstrip('\n') + '\n'
    L = ['', '# ===== warm-boot gate test: install (runs after the shell is up) =====']
    for i in range(4):
        L.append(f'mem set 0x{MARK + 4 * i:08X} 0x00000000')
    for i, w in enumerate(words):              # twice: a dropped word here would be
        L += [f'mem set 0x{GATE_AT + 4 * i:08X} 0x{w:08X}'] * 2   # executed next boot
    for f in (DCACHE, ICACHE):
        L += [f'mem set 0x{ECHO_SLOT:08X} 0x{f:08X}', 'echo']
    L += [f'mem set 0x{ECHO_SLOT:08X} 0x{ECHO_ORIG:08X}'] * 3
    # the site last, once the gate is in memory
    L += [f'mem set 0x{SITE:08X} 0x{bl(SITE, GATE_AT):08X}'] * 2
    L += [f'mem set 0x{ECHO_SLOT:08X} 0x{DCACHE:08X}', 'echo']
    L += [f'mem set 0x{ECHO_SLOT:08X} 0x{ECHO_ORIG:08X}'] * 3
    L += ['display text GATE-ARMED', 'display osd 1'] * 3
    text = body + '\n'.join(L) + '\n'

    filler = '# pad -- see PAD_TO: mode 7 overwrites but does not truncate\n'
    while len(text) + len(filler) <= PAD_TO:
        text += filler
    text += '#' * max(0, PAD_TO - len(text) - 1) + '\n'
    ar.write_text(text)
    print(f'gate   : {len(words) * 4} bytes at 0x{GATE_AT:08X}, marks at 0x{MARK:08X}')
    print(f'site   : 0x{SITE:08X} 0x{SITE_ORIG:08X} -> 0x{bl(SITE, GATE_AT):08X}')
    print(f'card   : copy {ar} and {out / "fpSup.BIN"} to the card root')


def check():
    sys.path.insert(0, str(HERE))
    from putfile import mem_get
    site = mem_get(SITE)[0]
    m = mem_get(MARK, 4)
    done = mem_get(LOAD_DONE)[0]
    g = mem_get(GATE_AT, len(gate_code()))
    print(f'site 0x{SITE:08X} = 0x{site:08X}  '
          + ('(stock)' if site == SITE_ORIG else
             '(armed)' if site == bl(SITE, GATE_AT) else '(??)'))
    print(f'gate words intact: {list(g) == list(gate_code())}')
    print(f'runs={m[0]}  entry={m[1] / 1e6:.3f}s  after_load={m[2] / 1e6:.3f}s  '
          f'result={ {0: "never ran", 1: "LOADED, AutoRun skipped", 2: "fell back to AutoRun"}.get(m[3], m[3]) }')
    print(f'LOAD_DONE_US = {done / 1e6:.3f}s')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    b = sp.add_parser('build')
    b.add_argument('--out', type=pathlib.Path, required=True)
    b.add_argument('--banner', default='fpSup-GT2!')
    b.add_argument('--one-shot', action='store_true',
                   help='the first version: the gate disarms itself when it runs')
    sp.add_parser('check')
    a = ap.parse_args()
    build(a.out, a.banner, a.one_shot) if a.cmd == 'build' else check()
