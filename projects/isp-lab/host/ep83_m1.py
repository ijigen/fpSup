#!/usr/bin/env python3
"""Push engine milestone 1: do bytes the camera arms on EP 0x83 reach the host?

Writes a known pattern into putfile's staging area, runs sup/ep83send.S once
through the borrowed echo slot, and has the running fpshd (3.2.0's
`EP83 <bytes> <shellline>`) read exactly that many bytes from EP 0x83, then the
echo's own reply on EP82.  Pass = the bytes match and the sender says the TRB
completed.  Standby only; refuses while recording.

    ep83_m1.py OUT_DIR [--bytes 16384] [--wait-ms 1000]
"""
import argparse, datetime as dt, hashlib, json, pathlib, random, socket, struct, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SHELL = ROOT / 'fpSup' / 'fp_usb_shell'
SRC = HERE.parent / 'sup' / 'ep83send.S'
sys.path.insert(0, str(SHELL))

CODE_CLAIM, PARM_CLAIM = ('ispl.ep83.code', 320), ('ispl.ep83.parm', 64)
CTX, PHYS = 3, 7                                  # EP 0x83 (memory push-endpoint-is-ep83)
DONE = 0xD09E0083
F_DCACHE = 0xC000E91C
OUT_FIELDS = ('start_rc', 'wait_rc', 'trb_ctrl', 'trb_size', 'ended', 'done')


def pattern(n, seed=0x83):
    return random.Random(seed).randbytes(n)


def ep83_exchange(n, line, timeout=10):
    """fpshd: EP83 <n> <line> -> (header line, payload bytes, rest)."""
    with socket.socket(socket.AF_UNIX) as c:
        c.settimeout(timeout)
        c.connect('/tmp/fpshd.sock')
        c.sendall(f'EP83 {n} {line}\n'.encode())
        buf = b''
        while b'\n' not in buf:
            d = c.recv(4096)
            if not d:
                break
            buf += d
        head, _, rest = buf.partition(b'\n')
        head = head.decode('latin1')
        if not head.startswith('OK83'):
            return head, b'', rest
        while len(rest) < n:
            d = c.recv(n - len(rest))
            if not d:
                break
            rest += d
        return head, rest[:n], rest[n:]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=pathlib.Path)
    ap.add_argument('--bytes', type=int, default=16384)
    ap.add_argument('--wait-ms', type=int, default=1000)
    a = ap.parse_args()
    if not 1 <= a.bytes <= 65536:
        raise SystemExit('3.2.0 EP83 takes at most 64 KiB')
    import putfile as p, cave, callfn
    from armasm import assemble
    if not p.sh('status get is_recording').strip().endswith('0'):
        raise SystemExit('recording: no USB during recording')

    parm = cave.claim(*PARM_CLAIM)
    code_at = cave.claim(*CODE_CLAIM)
    code = assemble(SRC, [f'P=0x{parm:08X}'])
    if len(code) > CODE_CLAIM[1]:
        raise SystemExit(f'ep83send is {len(code)} B')
    n = (len(code) + 3) // 4
    cur = p.mem_get(code_at, n)
    if None in cur or struct.pack(f'<{n}I', *cur) != code + bytes(-len(code) % 4):
        p.put(code_at, code, 'ep83  ')
        ok, _ = callfn.call(F_DCACHE, verbose=False)      # new bytes: clean D / invalidate I first
        if not ok:
            raise SystemExit('cache flush did not return')

    buf = p.staging_area()
    p.check_fits(buf, a.bytes, 'ep83 payload')
    data = pattern(a.bytes)
    p.put(buf, data + bytes(-len(data) % 4), 'payld ', fast=True)

    # TRBs carry DMA addresses = CPU (uncached alias) - 0x40000000: the firmware arms its own
    # TRBs as `[0xC3025744] - 0x40000000` (blk_c01.c ~135322), and 0xC31E3264[ctx] = 0xC31E3238[ctx] + 0x40000000
    want = {0x00: buf - 0x40000000, 0x04: a.bytes, 0x08: CTX, 0x0C: PHYS, 0x10: a.wait_ms}
    for _ in range(8):
        for off, v in want.items():
            p.mem_set(parm + off, v)
        for off in range(0x14, 0x2C, 4):
            p.mem_set(parm + off, 0)
        got = p.mem_get(parm, 11)
        if got[:5] == [want[o] for o in sorted(want)] and got[5:] == [0] * 6:
            break
    else:
        raise SystemExit(f'parameters did not stick: {got}')

    slot = p.mem_get(p.ECHO_SLOT)[0]
    if slot != p.ECHO_ORIG:
        raise SystemExit(f'echo handler is {slot:#x}, not free to borrow')
    p.set_echo_handler(code_at)
    try:
        head, payload, rest = ep83_exchange(a.bytes, 'echo')
    finally:
        p.set_echo_handler(p.ECHO_ORIG)
    res = dict(zip(OUT_FIELDS, p.mem_get(parm + 0x14, 6)))

    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'payload.bin').write_bytes(payload)
    match = payload == data
    rep = {'date_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'bytes': a.bytes, 'src': buf,
           'code_at': code_at, 'parm': parm, 'daemon': head, 'tail': rest.decode('latin1', 'replace'),
           'got': len(payload), 'match': match, 'sender': res,
           'first_diff': next((i for i, (x, y) in enumerate(zip(payload, data)) if x != y), None),
           'sha_sent': hashlib.sha256(data).hexdigest(), 'sha_got': hashlib.sha256(payload).hexdigest(),
           'tool_sha256': hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
           'sender_sha256': hashlib.sha256(SRC.read_bytes()).hexdigest()}
    (a.out / 'result.json').write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: rep[k] for k in ('daemon', 'got', 'match', 'sender', 'first_diff')}))
    return 0 if match and res['done'] == DONE and res['start_rc'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
