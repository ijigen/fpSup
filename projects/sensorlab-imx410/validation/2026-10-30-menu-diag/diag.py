"""First-MENU diagnostic, 2026-10-30. Reads only (mem get / callfn of sq_test getters / GUI time log).
Never during recording or playback.

  python3 -B diag.py state TAG          # LOAD.LOG-derived blocks + SensorLab ap + container + screen
  python3 -B diag.py menu TAG           # GUI log on, MENUON once (30 s reply timeout), poll 10 s, read state
  python3 -B diag.py op N TAG           # callfn sq_test(N) (21 = ap_init_rc, 22 = back to stock)
"""
import json, pathlib, re, sys, time, subprocess, fcntl
HERE = pathlib.Path(__file__).resolve().parent
SH = HERE.parents[3] / 'fpSup/fp_usb_shell'
sys.path.insert(0, str(SH))
import putfile, callfn
FPSH = str(SH / 'host/fpsh')

def fpsh(cmd, timeout=10):
    t = time.time()
    try:
        r = subprocess.run([FPSH, *cmd.split()], capture_output=True, text=True, timeout=timeout, cwd=SH)
        out = (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        out = '<host timeout>'
    return dict(cmd=cmd, t=round(t, 3), dt=round(time.time() - t, 3), out=out[:600])

def words(addr, n):
    v = putfile.mem_get(addr, n)
    return [None if x is None else int(x) for x in v]

def s32(x): return None if x is None else (x - (1 << 32) if x & 0x80000000 else x)

def blocks():
    log = (HERE / 'LOAD-current.LOG').read_text(errors='replace')
    b = {}
    for m in re.finditer(r'^0A ([0-9A-F]{8}) ([0-9A-F]{8}) (\S+\.BIN)', log, re.M):
        b[m[3]] = (int(m[1], 16), int(m[2], 16))
    return b

def find(b, prefix):
    for k, v in b.items():
        if k.startswith(prefix): return k, v[0], v[1]
    return None, None, None

AP_N1 = ['magic', 'abi', 'armed', 'svc', 'active', 'cur', 'picked', 'in_commit', 'owed', 'seq']
AP_N2 = ['result', 'detail', 'commits', 'refusals', 'lv_reloads', 'picks', 'lookups', 'canvases', 'recrates',
         'commit_us', 'standby_picks', 'carrier_sets', 'clk_ok', 'clk_open']

def sensorlab(b):
    name, blk, claims = find(b, 'SensorLab-IMX410_')
    d = dict(file=name, block=hex(blk) if blk else None, claims=claims)
    if not blk: return d
    if 'v0.5.0test' in name:
        apm = blk + 0x24050
        v = words(apm + 0x8F0, 10); d.update({n: (hex(x) if n in ('magic', 'svc') and x is not None else s32(x)) for n, x in zip(AP_N1, v)})
        v = words(apm + 0x9FC, 14); d.update({n: s32(x) for n, x in zip(AP_N2, v)})
        d['sq_test'] = hex(blk + 0x7111)
    else:
        d['note'] = 'layout for this version via sq_test(17) only'
    return d

# QSContainer v0.2.4 (qst.py, S = block + state_off 173888); v0.3.0 = +4 after the api (test_qs_page.LAYOUT)
QS24 = {'result': 4, 'phase': 8, 'freeze': 12, 'N': 32, 'lay_calls': 52, 'saves': 3224, 'writes': 3252,
        'write_fails': 3256, 'write_why': 3260, 'busy_skips': 3264,
        'qs_result': 11016, 'qs_ready': 11020, 'qs_reloads': 11036, 'hits': 11040, 'foreign': 11044,
        'sub_open': 11704, 'keys': 11740, 'opens': 11752, 'closes': 11756, 'posts': 11768,
        'menus': 11932, 'focus_cb': 11936, 'guid_sets': 11940, 'fresh': 11944, 'focus_id': 11952,
        'n_leave': 64732, 'fine_on': 64736, 'leaves': 64744, 'foot_pitch': 64752}
STATE_OFF = {'v0.2.4': 173888, 'v0.3.0': 176256}

def container(b):
    name, blk, claims = find(b, 'QSContainer_')
    d = dict(file=name, block=hex(blk) if blk else None, claims=claims)
    if not blk: return d
    ver = re.search(r'_(v[0-9.]+)\.BIN', name)[1]
    S = blk + STATE_OFF[ver]
    F = dict(QS24)
    if ver == 'v0.3.0':
        F = {k: (o + 4 if o >= 11016 else o) for k, o in F.items()}
        F.update(qs_active=64760, pending_fn=64764, pending_how=64768, standalone=64772)
    d['magic'] = hex(words(S, 1)[0] or 0)
    for k, o in F.items():
        d[k] = s32(words(S + o, 1)[0])
    return d

def screen():
    app = words(0xC37B7048, 1)[0]
    scr = words(app + 0x84C, 1)[0]
    nm = words(scr + 8, 1)[0] if scr else None
    name = ''
    if nm:
        raw = b''.join(int(w or 0).to_bytes(4, 'little') for w in words(nm, 8))
        name = raw.split(b'\0')[0].decode('latin1')
    return dict(app=hex(app or 0), screen=hex(scr or 0), name=name)

def state():
    b = blocks()
    return dict(t=time.time(), ping=fpsh('ping', 6)['out'], app_current=fpsh('status get app_current')['out'],
                screen=screen(), sensorlab=sensorlab(b), container=container(b))

GUILOG = re.compile(r'^\s*(\d+),\s*(-?\d+),\s*\d+,\w+,0x[0-9a-f]+,(\d+),(Gui:Update|Gui:Render)')

def guilog():
    out = putfile.sh('log out GUI', retries=0)
    return out

def main():
    lock = open('/tmp/fp-af-fusion.lock', 'a+'); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    act, tag = sys.argv[1], sys.argv[-1]
    rec = fpsh('status get is_recording')
    if 'is_recording -> 0' not in rec['out']: raise SystemExit('not idle: ' + rec['out'])
    res = dict(action=act, start=time.strftime('%H:%M:%S'))
    if act == 'state':
        res['state'] = state()
    elif act == 'op':
        b = blocks(); _, blk, _ = find(b, 'SensorLab-IMX410_')
        ok, val = callfn.call(blk + 0x7111, r0=int(sys.argv[2]), verbose=False)
        res['op'] = dict(n=int(sys.argv[2]), ok=ok, value=s32(val) if ok else None)
        res['state'] = state()
    elif act == 'menu':
        res['before'] = state()
        putfile.mem_set(0xC37B71E0, 1); res['log_act'] = putfile.sh('log act GUI', retries=0)
        res['log_before'] = guilog()[-3000:]
        k = fpsh('key MENUON', timeout=40); res['key'] = k
        print('key', k, flush=True)
        polls = []
        t0 = time.time()
        while time.time() - t0 < 10:
            p = fpsh('ping', 6)
            polls.append(dict(dt=round(time.time() - t0, 2), ping=p['out'][:60], rt=p['dt']))
            if 'pong' not in p['out']:
                polls.append(dict(note='ping failed; stop polling'))
                break
            polls.append(dict(dt=round(time.time() - t0, 2), app=fpsh('status get app_current')['out'][:40]))
            time.sleep(0.5)
        res['polls'] = polls
        print('polls', polls[-3:], flush=True)
        if 'pong' in polls[-1].get('ping', polls[-2].get('ping', '')) or 'app' in polls[-1]:
            res['log_after'] = guilog()
            putfile.mem_set(0xC37B71E0, 0); putfile.sh('log inact GUI', retries=0)
            res['after'] = state()
    (HERE / f'{tag}.json').write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1)[:4000])

if __name__ == '__main__':
    main()
