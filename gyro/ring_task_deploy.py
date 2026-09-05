#!/usr/bin/env python3
"""Create the dedicated writer task, and prove it blocks and wakes.

    ./ring_task_deploy.py            place the code and create the task
    ./ring_task_deploy.py --signal   wake it N times and check it noticed
    ./ring_task_deploy.py --state    read the counters

The task is what the audio writer is and ours never was: priority 6, blocked on
tk_slp_tsk rather than polling, woken the instant there is work.  This step
proves only that -- it creates the task, blocks it, and counts wakes.  The ring
and the card write are separate units, because task creation is the piece with
a history of freezing the camera and it should not be entangled with anything
else when it is first run.

The creator runs ONCE, through the shell's borrowed echo handler.  Nothing about
it stays reachable afterwards.
"""
import argparse
import re
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'fp_usb_shell'))

import putfile as P                                            # noqa: E402
from armasm import assemble, _compile, _parse                  # noqa: E402

CODE_AT = 0xC072EA40            # after vd_hook, below the park stub
CAVE_HI = 0xC072EFA0

T_ID, T_CRE_RC, T_STA_RC = 0xC072E160, 0xC072E164, 0xC072E168
T_WAKES, T_SIGNALS, T_ENTRY = 0xC072E16C, 0xC072E170, 0xC072E174
T_RECV_RC, T_MBX_RC = 0xC072E178, 0xC072E17C
T_DESC, T_PKT, T_DOOR, T_MBX = 0xC072E080, 0xC072E0A0, 0xC072E0C0, 0xC072E0C4


def symbols(src):
    """Offsets of the global symbols inside the assembled blob."""
    elf, sections, by_name = _parse(_compile(src))
    _, symtab = by_name['.symtab']
    _, strtab = by_name['.strtab']
    out = {}
    for off in range(symtab[4], symtab[4] + symtab[5], 16):
        name_off, value, _size, info, _other, shndx = struct.unpack_from(
            '<IIIBBH', elf, off)
        # `.global` alone leaves the symbol STT_NOTYPE, so filter by name, not
        # by type -- an empty map here would place the task at zero.
        end = elf.index(b'\0', strtab[4] + name_off)
        name = elf[strtab[4] + name_off:end].decode()
        if name in ('writer_task', 'make_writer', 'writer_signal'):
            out[name] = value
    return out


def _check():
    """The addresses here are duplicated from the assembly; prove they match."""
    src = (HERE / 'ring_task.inc.S').read_text()
    want = {'T_ID': T_ID, 'T_CRE_RC': T_CRE_RC, 'T_STA_RC': T_STA_RC,
            'T_WAKES': T_WAKES, 'T_SIGNALS': T_SIGNALS, 'T_ENTRY': T_ENTRY,
            'T_RECV_RC': T_RECV_RC, 'T_MBX_RC': T_MBX_RC, 'T_DESC': T_DESC,
            'T_PKT': T_PKT, 'T_DOOR': T_DOOR, 'T_MBX': T_MBX, 'WRITER_PRI': 6}
    for name, value in want.items():
        m = re.search(rf'^\.equ\s+{name},\s*([^\s/@]+)', src, re.M)
        if not m:
            raise SystemExit(f'ring_task.inc.S has no {name}')
        if int(m.group(1).rstrip(','), 0) != value:
            raise SystemExit(f'{name}: header says {m.group(1)}, this says {value:#x}')

    # The syscall stubs, checked against the firmware rather than trusted.  Each
    # TK-OS stub keeps its service ID at stub+0x20; the notes recorded three of
    # these twelve bytes too high, which would have skipped the prologue.
    fw = Path('/Users/dido/Developer/SIGMAfp_re/out/MAIN_c0000000.bin')
    if fw.exists():
        blob = fw.read_bytes()
        for name, service in (('TK_CRE_TSK', 0x80010100), ('TK_STA_TSK', 0x80030200),
                              ('TK_DLY_TSK', 0x80460100), ('MBX_CREATE', 0x80260100),
                              ('MBX_SEND', 0x80280200), ('MBX_RECV', 0x80290300)):
            m = re.search(rf'^\.equ\s+{name},\s*(0x[0-9A-Fa-f]+)', src, re.M)
            if not m:
                raise SystemExit(f'ring_task.inc.S has no {name}')
            stub = int(m.group(1), 0)
            got = struct.unpack_from('<I', blob, stub + 0x20 - 0xC0000000)[0]
            if got != service:
                raise SystemExit(f'{name} 0x{stub:08X}: service at +0x20 is '
                                 f'0x{got:08X}, not 0x{service:08X}')
            first = struct.unpack_from('<I', blob, stub - 0xC0000000)[0]
            if first != 0xE92D0010:
                raise SystemExit(f'{name} 0x{stub:08X} does not start with push {{r4}}')


def place():
    _check()
    code = assemble(HERE / 'ring_task.S')
    syms = symbols(HERE / 'ring_task.S')
    end = CODE_AT + len(code)
    if end > CAVE_HI:
        raise SystemExit(f'0x{CODE_AT:08X}..0x{end:08X} runs into the park stub')
    missing = {'writer_task', 'make_writer', 'writer_signal'} - set(syms)
    if missing:
        raise SystemExit(f'the blob has no {sorted(missing)}')
    print(f'  ring_task     0x{CODE_AT:08X}..0x{end:08X}  {len(code)} bytes')
    for n, o in sorted(syms.items(), key=lambda kv: kv[1]):
        print(f'    {n:16s} 0x{CODE_AT + o:08X}')
    return code, {n: CODE_AT + o for n, o in syms.items()}


def _setw(addr, value, what):
    for _ in range(8):
        P.mem_set(addr, value)
        if (P.mem_get(addr) or [0])[0] == value:
            return
    raise SystemExit(f'could not write {what} at 0x{addr:08X}')


def echo_into(addr, label):
    """Run a routine once by borrowing the shell's echo handler."""
    orig = P.mem_get(P.ECHO_SLOT)
    if not orig or orig[0] != P.ECHO_ORIG:
        raise SystemExit(f'echo handler is {orig}, not free to borrow')
    _setw(P.ECHO_SLOT, addr, f'the echo handler -> {label}')
    try:
        P.sh('echo', retries=0)
    finally:
        for _ in range(8):
            P.mem_set(P.ECHO_SLOT, P.ECHO_ORIG)
            if (P.mem_get(P.ECHO_SLOT) or [0])[0] == P.ECHO_ORIG:
                return
        raise SystemExit('LEFT THE ECHO HANDLER REDIRECTED -- reboot the camera')


def create():
    code, at = place()
    have = P.mem_get(T_ID)[0]
    if have and 0 < have < 0x1000:
        raise SystemExit(f'a task id {have} is already recorded; creating a second '
                         f'one would leak the first (tk_ext_tsk is not isolated)')
    P.put_slow(CODE_AT, code, 'ring_task')
    _setw(T_ENTRY, at['writer_task'], 'the task entry')
    _setw(T_ID, 0, 'the id slot')
    print(f'creating: priority 6, entry 0x{at["writer_task"]:08X}')
    echo_into(at['make_writer'], 'make_writer')
    state()


def signal(times, at=None):
    if at is None:
        _code, at = place()
    before = P.mem_get(T_WAKES)[0]
    for _ in range(times):
        echo_into(at['writer_signal'], 'writer_signal')
    time.sleep(0.5)
    after = P.mem_get(T_WAKES)[0]
    print(f'signalled {times}x   wakes {before} -> {after}')
    if after == before:
        print('  the task did not wake: it is not running, or the id is wrong')
    elif after - before == times:
        print('  every signal was taken -- blocking and waking, no wakeups lost')
    else:
        print(f'  {after - before} of {times} landed')


def state():
    mbx, door = P.mem_get(T_MBX)[0], P.mem_get(T_DOOR)[0]
    print(f'  T_MBX      {mbx}   T_DOOR {door}')
    w = P.mem_get(T_ID, 8)
    names = ('T_ID', 'T_CRE_RC', 'T_STA_RC', 'T_WAKES', 'T_SIGNALS', 'T_ENTRY',
             'T_RECV_RC', 'T_MBX_RC')
    for n, v in zip(names, w):
        print(f'  {n:10s} {v if v is not None else "(unread)"}'
              + (f'   0x{v:08X}' if v is not None else ''))
    if w[1] is not None and w[1] <= 0:
        print(f'  tk_cre_tsk returned {w[1]} -- E_PAR is -17 (priority must be '
              f'1..32, stack at least 0x100)')
    if w[2] == 0 and w[0] and w[0] > 0:
        print('  created and started')


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--state', action='store_true')
    g.add_argument('--signal', type=int, metavar='N')
    g.add_argument('--place-only', action='store_true')
    a = ap.parse_args()
    if a.state:
        state()
    elif a.signal:
        signal(a.signal)
    elif a.place_only:
        place()
    else:
        create()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
