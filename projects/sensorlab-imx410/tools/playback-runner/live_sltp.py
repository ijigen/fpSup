#!/usr/bin/env python3
"""SLTP v1 arm/status helper. Import and argument parsing are offline.

Only an operator who has visually confirmed CINE live-view idle may run it.
Arm sends one final sequence write, never retries it, then holds the shared
host lock silently for 30 seconds. No polling, readback, window revoke or USB
cleanup follows that write, including an uncertain acknowledgement.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import pathlib
import re
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SHELL = ROOT / 'fpSup/fp_usb_shell'
LOCK = pathlib.Path('/tmp/fp-af-fusion.lock')
PINNED_SHA256 = 'c1bc654a825128a7f50ca2ce41e21ab4b49e43b7b3b3e0ac4ae9cae79bcb6d45'
STATE_BYTES, WINDOW_SLOT, QUIET_SECONDS = 176, 6, 30
sys.path.insert(0, str(HERE))
from decode_sltp import parse


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def local_build(path):
    info = json.loads(path.read_text())
    required = dict(file='SLTP.BIN', bytes=1640, sha256=PINNED_SHA256,
                    state_off=1664, block_size=1920, state_bytes=176,
                    mutable_file_offsets=[1612])
    for key, expected in required.items():
        if info.get(key) != expected:
            raise RuntimeError('unsupported SLTP build metadata: ' + key)
    blob = (path.parent / 'fpSup' / info['file']).read_bytes()
    if len(blob) != info['bytes'] or digest(blob) != PINNED_SHA256:
        raise RuntimeError('local SLTP artifact differs from the pinned v1 build')
    return info, blob


def loaded_block(log):
    matches = re.findall(r'^0A ([0-9a-fA-F]{8}) [0-9a-fA-F]{8} SLTP\.BIN\s*$', log, re.M)
    if len(matches) != 1:
        raise RuntimeError('current LOAD.LOG must contain exactly one loaded SLTP.BIN')
    block = int(matches[0], 16)
    if block & 63 or not 0xC4000000 <= block <= 0xFFFFFFFF - 1920:
        raise RuntimeError('invalid cached SLTP resident block')
    return block


def idle_gate(api):
    replies = {}
    for command, expected in (('status get is_recording', 'is_recording -> 0'),
                              ('status get app_current', 'app_current -> 2')):
        answer = api.sh(command, retries=0).strip()
        replies[command] = answer
        if answer != expected:
            raise RuntimeError('native idle gate failed: ' + command + ': ' + answer)
    return replies


def read_current_log(out):
    """Existing getfile owns its scratch/echo handling; called only before arm."""
    path = pathlib.Path(out).resolve() / 'LOAD.LOG'
    result = subprocess.run([sys.executable, '-B', str(SHELL / 'getfile.py'),
                             r'\fpSup\LOAD.LOG', str(path), '--size', '0x2000'],
                            cwd=SHELL, capture_output=True, text=True, check=False)
    (out / 'load-log-read.txt').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError('current LOAD.LOG read failed; no request armed')
    return path.read_text('ascii', errors='strict')


@contextlib.contextmanager
def host_lease(path=LOCK):
    with open(path, 'a+') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def resident_state(api, block, info, local):
    """Read-only MEM1 window: fully revoked before any sequence can be armed."""
    base = block - 0x80000000
    caps = api.mem_caps(refresh=True)
    if not caps or len(caps['windows']) <= WINDOW_SLOT or caps['windows'][WINDOW_SLOT][2]:
        raise RuntimeError('MEM1 read window 6 is unavailable or already owned')
    api.mem_window(WINDOW_SLOT, base, info['block_size'], 1)
    try:
        remote = bytearray(api.mem_read(base, info['bytes'], sync=True, label='sltp code'))
        if len(remote) != info['bytes']:
            raise RuntimeError('short resident code read')
        pointer = struct.unpack_from('<I', remote, 1612)[0]
        if pointer != block + info['state_off']:
            raise RuntimeError('resident context pointer does not identify this block state')
        remote[1612:1616] = local[1612:1616]
        if remote != local:
            raise RuntimeError('running SLTP differs from the exact pinned build')
        raw = api.mem_read(base + info['state_off'], STATE_BYTES, sync=True, label='sltp state')
        return parse(raw), raw
    finally:
        api.mem_window(WINDOW_SLOT, base, info['block_size'], 0)


def ready_state(state):
    if not 0 < state['task_id'] < 0x80000000 or state['task_rc'] != 0:
        raise RuntimeError('SLTP task did not initialize successfully')
    if state['phase'] not in (0, 8, 9):
        raise RuntimeError('SLTP is active or failed; no arm allowed')
    if state['req_seq'] != state['seen_seq']:
        raise RuntimeError('SLTP still has an unconsumed request')
    if state['phase'] == 0 and any(state[k] for k in ('req_seq', 'seen_seq', 'active_seq', 'done_seq')):
        raise RuntimeError('inconsistent initial SLTP state')
    if state['phase'] == 8 and not state['sequence_completed']:
        raise RuntimeError('inconsistent completed SLTP state')
    if state['phase'] == 9 and (state['error'] not in (1, 2, 3) or state['reject_seq'] != state['seen_seq']):
        raise RuntimeError('SLTP rejection is not a safely consumed inactive request')
    seq = max(state[k] for k in ('req_seq', 'seen_seq', 'active_seq', 'done_seq', 'reject_seq')) + 1
    if not 0 < seq <= 0x7FFFFFFF:
        raise RuntimeError('SLTP sequence exhausted; no wrap/replay supported')
    return seq


def native_state(api, at):
    # Cached CPU reads/writes avoid DMA's minimum 1 KiB write window, which
    # would exceed SLTP's 256-byte private state reserve. No retry is used.
    reply = api.sh(f'mem get 0x{at:08X},,0x{STATE_BYTES:X}', retries=0)
    pairs = re.findall(r'A:0x([0-9A-Fa-f]+),\s*D:0x([0-9A-Fa-f]+)', reply)
    words = {int(a, 16): int(v, 16) for a, v in pairs}
    if len(pairs) != STATE_BYTES // 4 or len(words) != STATE_BYTES // 4 or any(at + 4*i not in words for i in range(44)):
        raise RuntimeError('incomplete/ambiguous cached SLTP readback')
    raw = struct.pack('<44I', *(words[at + 4*i] for i in range(44)))
    return parse(raw), raw


def save(out, name, obj):
    (out / name).write_text(json.dumps(obj, indent=2) + '\n')


def run(api, command, mode, info, local, out, *, get_log=read_current_log, sleep=time.sleep):
    """Caller holds host_lease and has checked the operator confirmation flag."""
    evidence = dict(started_utc=utc(), command=command, build_sha256=info['sha256'],
                    human_confirmed_liveview_idle=True, physical_exit_verified=False)
    evidence['idle_before'] = idle_gate(api)
    log = get_log(out)  # always fetch this boot, never accept a caller's stale block address
    block = loaded_block(log)
    evidence.update(block=f'0x{block:08X}', load_log_sha256=digest(log.encode('ascii')))
    state, raw = resident_state(api, block, info, local)
    (out / 'before-state.bin').write_bytes(raw)
    evidence['before'] = state
    save(out, 'before.json', evidence)
    if command == 'status':
        save(out, 'status.json', state)
        return dict(command='status', state=state, no_request_sent=True)
    if command != 'arm' or mode not in (1, 2):
        raise ValueError('arm supports only fixed scene 1 or 2')
    seq = ready_state(state)
    at = block + info['state_off']
    reply = api.sh(f'mem set 0x{at + 8:08X} 0x{mode:08X}', retries=0)
    if reply.lstrip().startswith('ERR'):
        raise RuntimeError('mode write failed; sequence was not committed')
    check, check_raw = native_state(api, at)
    if check['req_mode'] != mode or ready_state(check) != seq:
        raise RuntimeError('mode readback or inactive sequence changed; no commit')
    evidence['idle_at_commit'] = idle_gate(api)
    evidence.update(mode=mode, seq=seq, state_address=f'0x{at:08X}', commit_attempted_utc=utc(),
                    commit_outcome='unknown until a separately requested status read',
                    quiet_seconds=QUIET_SECONDS)
    # Persist intent before the one non-retried commit. From the next call on,
    # all paths (including missing ack/exception) perform only local work.
    save(out, 'arm.json', evidence)
    try:
        reply = api.sh(f'mem set 0x{at + 12:08X} 0x{seq:08X}', retries=0, timeout_ms=1000)
        evidence['commit_reply'] = reply
        evidence['ack_error'] = reply.lstrip().startswith('ERR')
        if evidence['ack_error']:
            raise RuntimeError('sequence commit acknowledgement is uncertain; do not retry')
    except BaseException as exc:
        evidence['commit_exception'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        try:
            save(out, 'arm.json', evidence)
        finally:
            sleep(QUIET_SECONDS)  # local only; held flock does not prove physical exit
    return evidence


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=('arm', 'status'))
    ap.add_argument('--scene', choices=('thumbnail', 'play'))
    ap.add_argument('--build', type=pathlib.Path, default=HERE / 'out-v1/build.json')
    ap.add_argument('--out', type=pathlib.Path, required=True, help='new evidence directory; existing paths refused')
    ap.add_argument('--confirm-cine-idle', action='store_true', help='arm: visually confirmed CINE live view idle now')
    ap.add_argument('--confirm-returned-liveview', action='store_true', help='status: visually confirmed return to idle live view and exit settling finished')
    args = ap.parse_args()
    if args.command == 'arm' and (not args.confirm_cine_idle or not args.scene):
        ap.error('arm requires --scene and --confirm-cine-idle before any USB access')
    if args.command == 'status' and (not args.confirm_returned_liveview or args.scene):
        ap.error('status requires --confirm-returned-liveview and no --scene before any USB access')
    info, local = local_build(args.build)
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    # Neither the transport nor card reader is touched by import/help.
    sys.path.insert(0, str(SHELL))
    import putfile
    with host_lease():
        result = run(putfile, args.command, {'thumbnail': 1, 'play': 2}.get(args.scene), info, local, args.out)
    print(json.dumps(result, indent=2))
    if args.command == 'arm':
        print('No USB was sent after sequence commit. Confirm idle live view and completed exit settling before a separate status command.')


if __name__ == '__main__':
    main()
