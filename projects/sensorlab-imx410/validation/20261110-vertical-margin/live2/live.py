#!/usr/bin/env python3
"""Live driver for the PURPLE TEST build (2026-11-10).

    python3 -B live.py BLOCK status
    python3 -B live.py BLOCK set BITS [SMODE]       # write bits/smode, recommit (sq_test 30 1 / 0), check live/refused
    python3 -B live.py BLOCK takes N LABEL          # N takes of 1 s via rec_take.sh, ring record per take -> takes.jsonl
    python3 -B live.py BLOCK payload                # the current selection's QR fields

BLOCK = the SensorLab line of LOAD.LOG.  Offsets come from out-purple-live/build-<ver>.json only.
"""
import json, pathlib, struct, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path[:0] = [str(ROOT / 'fpSup/fp_usb_shell'), str(HERE.parents[1] / '20261108-purple-stock-diff'),
                str(ROOT / 'projects/sensorlab-imx410/qs')]
from callfn import call            # noqa: E402
import putfile as pf               # noqa: E402
import ring                        # noqa: E402

INFO = json.load(open(next((HERE / 'out-purple-live').glob('build-*.json'))))
BLOCK = int(sys.argv[1], 16)
RD = INFO['rec_delay']; PU = INFO['purple']
SQ = BLOCK + INFO['sq_test_off']


def op(n, a=0, b=0):
    r = call(SQ, r0=n, r1=a, r2=b)
    return r[1] if isinstance(r, tuple) else r


def dump():
    n = 0x440 // 4
    words = pf.mem_get(BLOCK + RD['base_off'], n)
    return struct.pack(f'<{n}I', *words)


def head():
    return ring.decode(INFO, dump())


def setw(addr, v):
    for _ in range(3):
        pf.mem_set(addr, v)
        if pf.mem_get(addr, 1)[0] == v:
            return
    raise SystemExit(f'mem set {addr:#x} failed')


def cmd_status():
    h, recs = head()
    print(json.dumps(h))
    for r in recs[-3:]:
        print({k: r[k] for k in ('seq', 'toggles', 'smode', 'ff', 'sw_n', 'sw_from', 'sw_to', 'cur', 'switched_at_rec', 'arm_t1')})
    for k in (46, 17):
        a = op(k)
        print(k, pf.mem_get(a, 24))


def cmd_set(bits, smode=0):
    setw(BLOCK + PU['bits_off'], bits)
    setw(BLOCK + PU['smode_off'], smode)
    op(30, 1)
    op(30, 0)
    live, refused = pf.mem_get(BLOCK + PU['live_off'], 2)
    print('bits', bits, 'smode', smode, '-> live', live, 'refused', refused)
    if live != bits or refused:
        raise SystemExit('not live')


def cmd_takes(n, label):
    out = HERE / 'takes.jsonl'
    for i in range(n):
        before = head()[0]['n']
        r = subprocess.run(['/bin/zsh', str(ROOT / 'fpSup/fp_usb_shell/rec_take.sh'), '1'], capture_output=True, text=True)
        h, recs = head()
        if h['n'] != before + 1:
            raise SystemExit(f'no new REC start ({before} -> {h["n"]}): {r.stdout} {r.stderr}')
        rec = recs[-1]
        rec['label'] = label
        with open(out, 'a') as f:
            f.write(json.dumps(rec) + '\n')
        print(i + 1, '/', n, label, 'toggles', rec['toggles'], 'smode', rec['smode'], 'ff', rec['ff'],
              'sw', (rec['sw_n'], rec['sw_from'], rec['sw_to']), 'cur', rec['cur'], 'at_rec', rec['switched_at_rec'],
              flush=True)


def cmd_payload():
    import test_slqs as T
    a = op(13)
    s = bytes(b for w in pf.mem_get(a, 10) for b in w.to_bytes(4, 'little')).split(b'\0')[0].decode()
    d, ok = T.qr_unpack(s)
    print(s, ok, {k: d[k] for k in ('dcw', 'dch', 'rw', 'rh', 'fps', 'vmax', 'hmax', 'ad', 'mh', 'mv', 'key', 'visw', 'vish')})


if __name__ == '__main__':
    c = sys.argv[2]
    if c == 'status':
        cmd_status()
    elif c == 'set':
        cmd_set(int(sys.argv[3]), int(sys.argv[4]) if len(sys.argv) > 4 else 0)
    elif c == 'takes':
        cmd_takes(int(sys.argv[3]), sys.argv[4])
    elif c == 'payload':
        cmd_payload()
