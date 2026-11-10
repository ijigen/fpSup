"""v1 live checklist helper (2026-10-30). Read-mostly: callfn of sq_test ops + mem get. Never during rec/playback.

  python3 -B sl.py op N [a] TAG      sq_test(N, a) -> value
  python3 -B sl.py words N CNT TAG   sq_test(N) -> address, read CNT words
  python3 -B sl.py ap TAG            sq_test 17 decoded (struct ap_status)
  python3 -B sl.py menu TAG          sq_test 27 head (struct slm_state) + current rows' text
  python3 -B sl.py timing TAG        sq_test 29 (16) + 31 (12)
  python3 -B sl.py state TAG         screen + ap + menu
Options (anywhere): --version 0.7.1test  or  --build path/to/build-<ver>.json.
Default: the SensorLab BIN named in LOAD-current.LOG -> ../../qs/out/build-<ver>.json.  sq_test_off comes from
that json (it moves every build: 0x79DF in v0.7.0test, 0x7B61 in v0.7.1test); missing json/key = hard error.
Every result is appended to results.jsonl.
"""
import json, pathlib, re, sys, time, subprocess
HERE = pathlib.Path(__file__).resolve().parent
SH = HERE.parents[3] / 'fpSup/fp_usb_shell'
sys.path.insert(0, str(SH))
import putfile, callfn
FPSH = str(SH / 'host/fpsh')
QS_OUT = HERE.parents[1] / 'qs/out'
OPT = dict(version=None, build=None)              # set by take_opts(); rows.py uses the defaults
_cache = {}


def take_opts(argv):
    """strip --version V / --build P from argv (in place)"""
    for k in ('version', 'build'):
        f = '--' + k
        if f in argv:
            i = argv.index(f); OPT[k] = argv[i + 1]; del argv[i:i + 2]


def loaded_sl():
    """(block address, version) of the SensorLab BIN in LOAD-current.LOG (0A = loaded)"""
    log = (HERE / 'LOAD-current.LOG').read_bytes().decode('latin1')
    hits = re.findall(r'0A ([0-9A-F]{8}) [0-9A-F]{8} SensorLab-IMX410_v(\S+?)\.BIN', log)
    if OPT['version']: hits = [h for h in hits if h[1] == OPT['version']]
    if len(hits) != 1: raise SystemExit(f'LOAD-current.LOG: want exactly one loaded SensorLab BIN'
                                        f'{" v" + OPT["version"] if OPT["version"] else ""}, found {hits}')
    return int(hits[0][0], 16), hits[0][1]


def build_json():
    if 'build' not in _cache:
        ver = loaded_sl()[1]
        path = pathlib.Path(OPT['build']) if OPT['build'] else QS_OUT / f'build-{ver}.json'
        if not path.is_file(): raise SystemExit(f'build json missing: {path}')
        d = json.loads(path.read_text())
        if d.get('file') != f'SensorLab-IMX410_v{ver}.BIN':
            raise SystemExit(f'{path} is for {d.get("file")}, LOAD.LOG has v{ver}')
        if 'sq_test_off' not in d: raise SystemExit(f'{path}: no sq_test_off')
        _cache['build'] = d
    return _cache['build']


def sq_off(): return build_json()['sq_test_off']


def block(): return loaded_sl()[0]


def s32(x): return None if x is None else (x - (1 << 32) if x & 0x80000000 else x)


def words(addr, n):
    for _ in range(3):
        v = putfile.mem_get(addr, n)
        if None not in v: return [int(x) for x in v]
    return [None if x is None else int(x) for x in v]


def op(n, a=0, b=0):
    ok, val = callfn.call(block() + sq_off(), r0=n, r1=a, r2=b, verbose=False)
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
    d = {k: s32(x) for k, x in zip(MENU, v)}
    d['owed'] = words(a + 7484, 1)[0]                 # slm_state.owed (v0.7.1test, after summary[2][3][32])
    return d


SEL = ['bytes', 'abi', 'valid', 'fmt', 'dcw', 'dch', 'rw', 'rh', 'key', 'hbin', 'vbin', 'hm', 'vmax', 'fps_n', 'fps_d',
       'kh', 'kv', 'km', 'standby']


def sel():                                            # sq_test 18: struct ap_sel ap_last (apply/ap.h:29)
    a = op(18); v = words(a, len(SEL))
    return {k: s32(x) for k, x in zip(SEL, v)}


HOLDER, REGDESC, LK_REG = 0xC343B67C, 0xC0B5FDA4, 0xC0326DB8   # res-custom ogc_layout / test_v3_rescustom


def regs(mode):
    """the REG row the firmware reads for this mode id (lk_reg, hooked by ap for our virtual ids):
    word 0 = id, word 1+i = REG_ORDER[i]; 0x0003 -> i 1, 0x0022..0x0025 -> i 5..8"""
    ok, idx = callfn.call(LK_REG, r0=HOLDER, r1=mode, verbose=False)
    if not ok: raise SystemExit('lk_reg DID NOT RETURN')
    base = words(REGDESC, 1)[0]; row = (base + idx * 0x288) & 0xFFFFFFFF
    w = words(row, 10)
    return dict(mode=mode, idx=idx, row=hex(row), id=w[0], r0003=w[2], r0022=w[6], r0023=w[7], r0024=w[8], r0025=w[9],
                vstart=(w[6] & 0xFF) | (w[7] & 0xFF) << 8, vsize=(w[8] & 0xFF) | (w[9] & 0xFF) << 8)


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
    take_opts(sys.argv)
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
    elif act == 'sel':
        r['sel'] = sel()
    elif act == 'regs':                                # regs MODE|cur  (cur = W(0xC343B590))
        m = words(0xC343B590, 1)[0] if sys.argv[2] == 'cur' else int(sys.argv[2], 0)
        r['regs'] = regs(m)
    elif act == 'dc':                                  # the height investigation: ap + sel + the current mode's regs
        r['ap'] = ap(); r['sel'] = sel(); r['curmode'] = words(0xC343B590, 1)[0]
        r['regs'] = regs(r['curmode'])
        if r['ap'].get('mode_id'): r['regs_rec'] = regs(r['ap']['mode_id'])
    elif act == 'state':
        r.update(screen=screen(), ap=ap(), menu=menu())
    print(json.dumps(r))
    with open(HERE / 'results.jsonl', 'a') as f: f.write(json.dumps(r) + '\n')


if __name__ == '__main__':
    main()
