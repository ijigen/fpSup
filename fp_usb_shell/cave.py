#!/usr/bin/env python3
"""Where a host tool's code and scratch go in the cave -- asked for, not chosen.

    from cave import claim, ABI
    at = claim('putfile.code', 512)     # same address all boot; new one after a reboot

WHY THIS EXISTS.  Twenty-five host-side constants named cave addresses by hand:
putfile picked 0xC072F800 for its template and 0xC072FA00 for its bulk loader,
the probes picked 0xC072F740, the one-shot bootstrap and four different probes
all picked 0xC072F700, and nothing anywhere compared them.  The products stopped
doing this on 2026-09-22 -- a release card names no cave address at all -- and
the reason applies here unchanged: an address written into a tool is held
whether the tool runs or not, so every new tool has to be arranged around every
old one by hand, and two that overlap are found by a freeze.

The camera already has an allocator.  stage2 resets CAVE_BUMP to the bottom of
the arena every boot and gsup_boot takes its veneers from it; this hands the
host the same word.  Nothing new is placed in the cave to make it work.

WHY A NAME AND NOT JUST A BUMP.  Host scratch is not all transient.  putfile
writes its bulk loader once and calls it for the rest of the session -- that is
why it is fast -- so a tool invoked again needs the SAME address, not a fresh
one, or every call would leak a block and re-upload the loader.  So a claim is
by name, and the register of who has what lives here on the host, because the
host is the only thing that reads it.  The camera holds one number: the bump.

A boot is identified by LOAD_DONE_US, the microsecond stamp stage2 writes when
the load finishes.  It is already there, it is different every boot, and it goes
back to zero-then-something on a reboot -- which is exactly when the arena is
reset and every claim has to be re-issued.

WHAT THIS DOES NOT COVER.  The worker's own words (ABI below) are a rendezvous:
the resident worker was built with those addresses in it and the host has to use
the same ones.  They cannot be allocated, and they are not the problem -- there
are eight of them, they are declared here once, and the worker and this file are
built from the same tree.
"""
import fcntl
import json
import os
import pathlib
import re
import subprocess
import time

HERE = pathlib.Path(__file__).resolve().parent
FPSH = str(HERE / 'host' / 'fpsh')

# ---------------------------------------------------------------- the arena
# Duplicated from build_autorun.py, which is where the cave map is decided.
# _check_agrees() proves they match, the same way every other constant that
# lives in two places is checked.
CAVE_BUMP = 0xC072E060
CAVE_ARENA = 0xC072E064
CAVE_ARENA_END = 0xC072EFB4
LOAD_DONE_US = 0xC072F6F8

# ------------------------------------------------------------------ the ABI
# The resident worker's rendezvous words.  Fixed because the worker carries
# them; declared here so six files stop spelling them out.
ABI = {
    'pool_ptr':  0xC072F050,   # the pool the worker was given
    'pool_size': 0xC072F054,
    'code_ptr':  0xC072F058,   # where the worker put its own code
    'abort':     0xC072F080,   # the AutoRun abort flag
    'pool_desc': 0xC072F6D8,   # the loader's allocator descriptor, 16 bytes
    'load_start_us': 0xC072F6F4,
    'load_done_us':  LOAD_DONE_US,
    'park_stub': 0xC072EFB4,
}

REGISTER = pathlib.Path(
    os.environ.get('FPSUP_CAVE_REGISTER',
                   pathlib.Path.home() / '.cache' / 'fpsup' / 'cave.json'))


class CaveError(RuntimeError):
    pass


def _sh(*args, timeout=25):
    return subprocess.run([FPSH, *args], capture_output=True, text=True,
                          timeout=timeout, cwd=HERE).stdout


def _get(addr, tries=5):
    """One word, read until it answers.

    `mem get` drops commands -- not often, but often enough that a single read
    is a coin toss on a busy camera.  boot_id() read LOAD_DONE_US once and
    raised 'this camera did not boot from a loader card' when the answer went
    missing, which took putfile down with it in the middle of a deploy and left
    the card holding two files from different builds.  A dropped read is not an
    answer, so it is not treated as one.
    """
    for _ in range(tries):
        m = re.search(r'D:0x([0-9A-Fa-f]+)', _sh('mem', 'get', f'0x{addr:08X},,4'))
        if m:
            return int(m.group(1), 16)
    return None


def _set(addr, value, tries=8):
    """`mem set` drops commands silently, so a write is not a write until it
    reads back.  This is the same loop every tool here already carries."""
    for _ in range(tries):
        _sh('mem', 'set', f'0x{addr:08X}', f'0x{value:08X}')
        if _get(addr) == value:
            return True
    return False


def boot_id():
    """Which boot this is, as the camera measures it."""
    v = _get(LOAD_DONE_US)
    if not v:
        raise CaveError(
            'LOAD_DONE_US reads zero: this camera did not boot from a card '
            'whose loader stamps it.  Without a boot identity a claim cannot '
            'be told from a stale one.')
    return v


def _load():
    try:
        return json.loads(REGISTER.read_text())
    except Exception:
        return {}


def _save(reg):
    REGISTER.parent.mkdir(parents=True, exist_ok=True)
    REGISTER.write_text(json.dumps(reg, indent=1, sort_keys=True))


def _bump(n):
    """Take n bytes off the camera's own bump pointer.

    No free list and no lock on the camera side -- the same allocator the
    products use, with the same contract: a boot's worth of allocations, reset
    by the next boot.  The lock that matters is on the host, because two host
    processes doing read-modify-write on one word is a collision this is
    supposed to be ending, not causing.
    """
    n = (n + 7) & ~7                      # 8-aligned: an interrupt may use it
    at = _get(CAVE_BUMP)
    if at is None:
        raise CaveError('the bump pointer did not read back')
    if not CAVE_ARENA <= at <= CAVE_ARENA_END:
        raise CaveError(
            f'the bump pointer reads 0x{at:08X}, which is outside the arena '
            f'0x{CAVE_ARENA:08X}..0x{CAVE_ARENA_END:08X}.\n'
            f'  stage2 sets it every boot, so this camera did not boot from a '
            f'loader card.  A fallback card puts its worker at 0xC072E800, '
            f'inside the arena, so handing out space here would overwrite it.')
    if at + n > CAVE_ARENA_END:
        raise CaveError(
            f'{n} bytes do not fit: the bump is at 0x{at:08X} and the arena '
            f'ends at 0x{CAVE_ARENA_END:08X} ({CAVE_ARENA_END - at} left)')
    if not _set(CAVE_BUMP, at + n):
        raise CaveError('the bump pointer would not take its new value')
    return at


def claim(name, size):
    """The address this tool's block is at, allocating it if this boot has not.

    The same name gives the same address for as long as the camera stays up,
    and a different one after a reboot.  Growing a claim re-allocates: the old
    block is lost until the next boot, which is what a bump allocator does and
    is why sizes here are the size of the thing, not a guess.
    """
    REGISTER.parent.mkdir(parents=True, exist_ok=True)
    lock = REGISTER.with_suffix('.lock')
    with open(lock, 'w') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        boot = boot_id()
        reg = _load()
        if reg.get('boot') != boot:
            reg = {'boot': boot, 'at': time.strftime('%Y-%m-%d %H:%M:%S'),
                   'claims': {}}
        have = reg['claims'].get(name)
        if have and have[1] >= size:
            return have[0]
        at = _bump(size)
        reg['claims'][name] = [at, size]
        _save(reg)
        return at


def claims():
    """What this boot has handed out, for a tool that wants to print a map."""
    reg = _load()
    try:
        live = boot_id()
    except CaveError:
        return {}
    if reg.get('boot') != live:
        return {}
    return dict(reg.get('claims', {}))


def _check_agrees():
    """The four arena constants are build_autorun.py's; prove they match.

    build_autorun reads argv at module scope, so it cannot be imported -- the
    values are read out of the source, following one name to the next the way
    test_imu_stream does.
    """
    src = (HERE / 'build_autorun.py').read_text()

    def const(nm, depth=0):
        if depth > 4:
            raise CaveError(f'{nm}: too many hops in build_autorun.py')
        m = re.search(rf'^{nm}\s*=\s*([^#\n]+)', src, re.M)
        if not m:
            raise CaveError(f'build_autorun.py has no {nm}')
        expr = m.group(1).strip()
        mm = re.fullmatch(r'(\w+)(?:\s*\+\s*(0x[0-9A-Fa-f]+|\d+))?', expr)
        if mm and not mm.group(1).startswith('0'):
            return const(mm.group(1), depth + 1) + (
                int(mm.group(2), 0) if mm.group(2) else 0)
        return int(expr, 0)

    for nm, here in (('CAVE_BUMP', CAVE_BUMP), ('CAVE_ARENA', CAVE_ARENA),
                     ('CAVE_ARENA_END', CAVE_ARENA_END),
                     ('LOAD_DONE_US', LOAD_DONE_US)):
        there = const(nm)
        if there != here:
            raise CaveError(f'{nm}: build_autorun.py says 0x{there:08X}, '
                            f'cave.py says 0x{here:08X}')


if __name__ == '__main__':
    _check_agrees()
    print('the map agrees with build_autorun.py')
    at = _get(CAVE_BUMP)
    print(f'arena  0x{CAVE_ARENA:08X}..0x{CAVE_ARENA_END:08X}  '
          f'{CAVE_ARENA_END - CAVE_ARENA} bytes')
    print(f'bump   0x{(at or 0):08X}   '
          f'{CAVE_ARENA_END - at if at else 0} free')
    got = claims()
    if not got:
        print('no claims this boot')
    for nm, (a, n) in sorted(got.items(), key=lambda kv: kv[1][0]):
        print(f'  0x{a:08X}  {n:5d}  {nm}')
