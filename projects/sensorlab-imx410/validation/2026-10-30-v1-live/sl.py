"""v1 live checklist helper (2026-10-30). Read-mostly: callfn of sq_test ops + mem get. Never during rec/playback.

  python3 -B sl.py op N [a] TAG      sq_test(N, a) -> value
  python3 -B sl.py words N CNT TAG   sq_test(N) -> address, read CNT words
  python3 -B sl.py ap TAG            sq_test 17 decoded (struct ap_status)
  python3 -B sl.py menu TAG          sq_test 27 head (struct slm_state) + current rows' text
  python3 -B sl.py timing TAG        sq_test 29 (16) + 31 (12)
  python3 -B sl.py state TAG         screen + ap + menu
Every result is appended to results.jsonl.
"""
import json, pathlib, re, sys, time, subprocess
HERE = pathlib.Path(__file__).resolve().parent
SH = HERE.parents[3] / 'fpSup/fp_usb_shell'
sys.path.insert(0, str(SH))
import putfile, callfn
FPSH = str(SH / 'host/fpsh')
SQ_OFF = 0x79DF


def block():
    log = (HERE / 'LOAD-current.LOG').read_bytes().decode('latin1')
    m = re.search(r'0A ([0-9A-F]{8}) [0-9A-F]{8} SensorLab-IMX410_v0\.7\.0test\.BIN', log)
    return int(m[1], 16)


def s32(x): return None if x is None else (x - (1 << 32) if x & 0x80000000 else x)


def words(addr, n):
    for _ in range(3):
        v = putfile.mem_get(addr, n)
        if None not in v: return [int(x) for x in v]
    return [None if x is None else int(x) for x in v]


def op(n, a=0, b=0):
    ok, val = callfn.call(block() + SQ_OFF, r0=n, r1=a, r2=b, verbose=False)
    if not ok: raise SystemExit(f'sq_test({n}) DID NOT RETURN')
    return val & 0xFFFFFFFF


AP = ['bytes', 'abi', 'armed', 'active', 'cur', 'mode_id', 'pid', 'result', 'detail', 'commits', 'refusals',
      'lv_reloads', 'owed', 'picks', 'lookups', 'canvases', 'recrates', 'standby_picks', 'carrier', 'carrier_sets',
      'fast', 'commit_us', 'gated', 'blacks']
MENU = ['ready', 'attempted', 'result', 'updates', 'picks', 'rejected', 'opened', 'go',
        'count0', 'count1', 'count2', 'cur0', 'cur1', 'cur2', 'sent0', 'sent1', 'sent2', 'sending', 'bank']


def ap():
    a = op(17); v = words(a, len(AP))
    return {k: s32(x) for k, x in zip(AP, v)}


def menu():
    a = op(27); v = words(a, len(MENU))
    return {k: s32(x) for k, x in zip(MENU, v)}


def screen():
    app = words(0xC37B7048, 1)[0]
    scr = words(app + 0x84C, 1)[0]
    nm = words(scr + 8, 1)[0] if scr else None
    name = ''
    if nm:
        raw = b''.join(int(w or 0).to_bytes(4, 'little') for w in words(nm, 8))
        name = raw.split(b'\0')[0].decode('latin1')
    return name


def main():
    act, tag = sys.argv[1], sys.argv[-1]
    rec = subprocess.run([FPSH, 'status', 'get', 'is_recording'], capture_output=True, text=True, timeout=10).stdout
    if 'is_recording -> 0' not in rec: raise SystemExit('not idle: ' + rec)
    r = dict(tag=tag, act=act, t=time.strftime('%H:%M:%S'))
    if act == 'op':
        a = int(sys.argv[3], 0) if len(sys.argv) > 4 else 0
        v = op(int(sys.argv[2]), a); r.update(n=int(sys.argv[2]), a=a, value=s32(v), hex=hex(v))
    elif act == 'words':
        a = op(int(sys.argv[2])); r.update(n=int(sys.argv[2]), addr=hex(a), words=words(a, int(sys.argv[3])) if a else None)
    elif act == 'ap':
        r['ap'] = ap()
    elif act == 'menu':
        r['menu'] = menu()
    elif act == 'timing':
        a = op(29); r['t29'] = words(a, 16)
        b = op(31); r['t31'] = words(b, 12) if b else None
    elif act == 'state':
        r.update(screen=screen(), ap=ap(), menu=menu())
    print(json.dumps(r))
    with open(HERE / 'results.jsonl', 'a') as f: f.write(json.dumps(r) + '\n')


if __name__ == '__main__':
    main()
