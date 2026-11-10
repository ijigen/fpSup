#!/usr/bin/env python3
"""DC-height probe: ap status, ap_sel and the sensor REG row the firmware reads, as ONE json line.

    python3 -B dc_probe.py --load-log RUN/LOAD-current.LOG [--version 0.7.1test | --build out/build-X.json]
                           [--mode cur|rec|N] [--tag TAG] [--out RUN/results.jsonl]

Reads (callfn + mem get only; never during recording or playback -- it refuses unless is_recording -> 0):
  sq_test 17 -> struct ap_status (24 words), sq_test 18 -> struct ap_sel ap_last (19 words);
  W(0xC343B590) = the current sensor mode id;
  firmware lk_reg 0xC0326DB8(HOLDER 0xC343B67C, mode) -> index into the REGDESC table (*0xC0B5FDA4, 0x288-byte rows;
  for our virtual ids the hooked lk_reg returns an index whose row wraps (mod 2^32) into the SensorLab block);
  row word 0 = id, word 1+i = REG_ORDER[i]: 0x0003 -> w2, 0x0022..0x0025 -> w6..w9 -> vstart / vsize.
--mode: both (default) = cur and rec (rec only if ap.mode_id != 0); cur = W(0xC343B590); rec = ap.mode_id; or an id.

The sensorlab block address comes from the LOAD.LOG copy (line `0A <block> <claims> SensorLab-IMX410_v<ver>.BIN`);
sq_test_off comes from qs/out/build-<ver>.json (it moves every build) -- a missing json or key is a hard error.
Copied from validation/2026-10-30-v1-live2/sl.py (`dc`, `ap`, `sel`, `regs`); that script keeps working on its own.
"""
import argparse, json, pathlib, re, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]                                      # SIGMAfp_re
SH = ROOT / 'fpSup/fp_usb_shell'
FPSH = str(SH / 'host/fpsh')
QS_OUT = HERE.parents[1] / 'qs/out'

AP = ['bytes', 'abi', 'armed', 'active', 'cur', 'mode_id', 'pid', 'result', 'detail', 'commits', 'refusals',
      'lv_reloads', 'owed', 'picks', 'lookups', 'canvases', 'recrates', 'standby_picks', 'carrier', 'carrier_sets',
      'fast', 'commit_us', 'gated', 'blacks']                 # sq_test 17, struct ap_status (v0.7.1test, 96 B)
SEL = ['bytes', 'abi', 'valid', 'fmt', 'dcw', 'dch', 'rw', 'rh', 'key', 'hbin', 'vbin', 'hm', 'vmax', 'fps_n', 'fps_d',
       'kh', 'kv', 'km', 'standby']                          # sq_test 18, struct ap_sel (apply/ap.h:29, 76 B)
CURMODE = 0xC343B590
HOLDER, REGDESC, LK_REG = 0xC343B67C, 0xC0B5FDA4, 0xC0326DB8
ROW_BYTES, ROW_WORDS = 0x288, 10


# ---- pure (unit-tested offline) --------------------------------------------
def parse_load_log(text, version=None):
    """-> (block, version) of the single loaded SensorLab BIN; SystemExit otherwise"""
    hits = re.findall(r'0A ([0-9A-F]{8}) [0-9A-F]{8} SensorLab-IMX410_v(\S+?)\.BIN', text)
    if version: hits = [h for h in hits if h[1] == version]
    if len(hits) != 1:
        raise SystemExit(f'LOAD.LOG: want exactly one loaded SensorLab BIN{" v" + version if version else ""}, found {hits}')
    return int(hits[0][0], 16), hits[0][1]


def load_build(version, build=None, qs_out=QS_OUT):
    path = pathlib.Path(build) if build else pathlib.Path(qs_out) / f'build-{version}.json'
    if not path.is_file(): raise SystemExit(f'build json missing: {path}')
    d = json.loads(path.read_text())
    if d.get('file') != f'SensorLab-IMX410_v{version}.BIN':
        raise SystemExit(f'{path} is for {d.get("file")}, LOAD.LOG has v{version}')
    if not isinstance(d.get('sq_test_off'), int): raise SystemExit(f'{path}: no integer sq_test_off')
    return d


def s32(x): return None if x is None else (x - (1 << 32) if x & 0x80000000 else x)


def decode(names, words): return {k: s32(x) for k, x in zip(names, words)}


def row_addr(base, idx): return (base + idx * ROW_BYTES) & 0xFFFFFFFF


def decode_row(mode, idx, row, w):
    """w = the row's first 10 words"""
    return dict(mode=mode, idx=idx, row=hex(row), id=w[0], r0003=w[2], r0022=w[6], r0023=w[7], r0024=w[8],
                r0025=w[9], vstart=(w[6] & 0xFF) | (w[7] & 0xFF) << 8, vsize=(w[8] & 0xFF) | (w[9] & 0xFF) << 8)


# ---- camera (callfn + mem get) ---------------------------------------------
class Cam:
    def __init__(self, block, sq_off):
        sys.path.insert(0, str(SH))
        import putfile, callfn                              # camera modules: only when actually probing
        self.putfile, self.callfn, self.fn = putfile, callfn, block + sq_off

    def words(self, addr, n):
        for _ in range(3):                                  # mem get drops replies: retry
            v = self.putfile.mem_get(addr, n)
            if None not in v: return [int(x) for x in v]
        raise SystemExit(f'mem get {addr:#x}+{n}: incomplete after 3 tries: {v}')

    def op(self, n):
        ok, val = self.callfn.call(self.fn, r0=n, r1=0, r2=0, verbose=False)
        if not ok: raise SystemExit(f'sq_test({n}) DID NOT RETURN')
        return val & 0xFFFFFFFF

    def struct(self, n, names):
        a = self.op(n)
        if not a: raise SystemExit(f'sq_test({n}) returned 0')
        return decode(names, self.words(a, len(names)))

    def regs(self, mode):
        ok, idx = self.callfn.call(LK_REG, r0=HOLDER, r1=mode, verbose=False)
        if not ok: raise SystemExit('lk_reg DID NOT RETURN')
        idx &= 0xFFFFFFFF
        row = row_addr(self.words(REGDESC, 1)[0], idx)
        return decode_row(mode, idx, row, self.words(row, ROW_WORDS))


def idle():
    r = subprocess.run([FPSH, 'status', 'get', 'is_recording'], capture_output=True, text=True, timeout=10).stdout
    if 'is_recording -> 0' not in r: raise SystemExit('not idle (recording/unknown), refusing: ' + r.strip()[:120])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--load-log', required=True, help='LOAD.LOG copy read at the start of this run')
    p.add_argument('--version', help='SensorLab version, e.g. 0.7.1test (default: the one in LOAD.LOG)')
    p.add_argument('--build', help='explicit build-<ver>.json (default: qs/out/build-<ver>.json)')
    p.add_argument('--mode', default='both', help='cur | rec | both | <id>')
    p.add_argument('--tag', default='')
    p.add_argument('--out', help='append the line to this results.jsonl')
    a = p.parse_args(argv)
    block, ver = parse_load_log(pathlib.Path(a.load_log).read_bytes().decode('latin1'), a.version)
    b = load_build(ver, a.build)
    idle()
    cam = Cam(block, b['sq_test_off'])
    r = dict(tag=a.tag, act='dc_probe', t=time.strftime('%H:%M:%S'), version=ver, block=hex(block),
             sq_test_off=hex(b['sq_test_off']))
    r['ap'] = cam.struct(17, AP)
    r['sel'] = cam.struct(18, SEL)
    r['curmode'] = cam.words(CURMODE, 1)[0]
    if a.mode in ('cur', 'both'): r['regs'] = cam.regs(r['curmode'])
    if a.mode in ('rec', 'both') and r['ap'].get('mode_id'): r['regs_rec'] = cam.regs(r['ap']['mode_id'])
    if a.mode not in ('cur', 'rec', 'both'): r['regs'] = cam.regs(int(a.mode, 0))
    line = json.dumps(r)
    print(line)
    if a.out:
        with open(a.out, 'a') as f: f.write(line + '\n')


if __name__ == '__main__':
    main()
