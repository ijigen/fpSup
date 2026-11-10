#!/usr/bin/env python3
"""Run a live checklist end to end, deterministically: no LLM between steps.

    python3 -B tools/live/run_checklist.py v1 --version 0.7.2test --out validation/<date>-v1-live3 [--from 7] [--only 3,4]
    python3 -B tools/live/run_checklist.py v1 --version 0.7.2test --list        # print the items and steps, touch nothing

A checklist is Python data (tools/live/checklists/<name>.py: items(version) -> [item]).  An item is
{id, title, steps: [step]}; a step is a dict with `do` and its arguments (see STEPS below) and optional `expect`.
Every step's actual result and the expectation verdict go to <out>/results.jsonl; <out>/summary.md is a one-page
summary (per item PASS / FAIL / MANUAL, the failed expectations, the screenshots to look at).

Built-in safety (not configurable from a checklist):
  - keys: only MENU OK UP DOWN LEFT RIGHT QS DISP Fn AEL and the dials; never S1 / S2 / MOV / PLAY / CAPTURE
    (recording only through `rec`, which runs fpSup/fp_usb_shell/rec_take.sh: nothing on USB while recording, 12 s
    after the stop; screenshots only through `shot`);
  - no playback steps at all (playback items are MANUAL: Bei, USB unplugged);
  - before any USB step after a recording: at least POST_REC_S since the stop;
  - every USB step is followed by a liveness ping; no pong for FREEZE_S -> FREEZE: stop at once, write the summary with
    the last action, no recovery.
"""
import argparse, importlib.util, json, pathlib, re, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
SL = HERE.parents[1]
ROOT = SL.parents[1]
SH = ROOT / 'fpSup/fp_usb_shell'
FPSH = str(SH / 'host/fpsh')
FREEZE_S = 5.0
POST_REC_S = 12.0
KEYS = {'MENU', 'OK', 'UP', 'DOWN', 'LEFT', 'RIGHT', 'QS', 'DISP', 'Fn', 'AEL', 'DIAL1', 'DIAL2'}
STRUCTS = {                                          # sq_test op -> field names of the struct it returns the address of
    17: ['bytes', 'abi', 'armed', 'active', 'cur', 'mode_id', 'pid', 'result', 'detail', 'commits', 'refusals',
         'lv_reloads', 'owed', 'picks', 'lookups', 'canvases', 'recrates', 'standby_picks', 'carrier', 'carrier_sets',
         'fast', 'commit_us', 'gated', 'blacks'],
    18: ['bytes', 'abi', 'valid', 'fmt', 'dcw', 'dch', 'rw', 'rh', 'key', 'hbin', 'vbin', 'hm', 'vmax', 'fps_n',
         'fps_d', 'kh', 'kv', 'km', 'standby'],
    27: ['ready', 'attempted', 'result', 'updates', 'picks', 'rejected', 'opened', 'go', 'count0', 'count1', 'count2',
         'cur0', 'cur1', 'cur2', 'sent0', 'sent1', 'sent2', 'sending', 'bank'],
}
EXTRA = {27: {'owed': 7484}}                         # slm_state.owed (appended)
CUR_MODE = 0xC343B590
QS_FOCUS = 0xC37B72A8 + 0xBC                         # AGENT_BRIEF "Navigate by UI log": the focused QS tile's id
APP_VARS = ('MENU_Level1', 'MENU_Level2', 'MENU_Level3')
QSC_FIELDS = ('sub_open', 'sub_tile', 'focus', 'fine_on')   # the container's state (qs-container test_qs_page.LAYOUT)


class Refused(Exception):
    pass


class Freeze(Exception):
    pass


# ---------------------------------------------------------------------------------------------------- the camera
class Camera:
    """the real shell (fpsh, putfile.mem_get, callfn.call, getfile.py, rec_take.sh).  Tests replace it."""

    def __init__(self):
        sys.path.insert(0, str(SH))
        import putfile, callfn                      # noqa: E401
        self.putfile, self.callfn = putfile, callfn

    def sh(self, *a, timeout=20):
        try:
            r = subprocess.run([FPSH, *a], capture_output=True, text=True, timeout=timeout, cwd=SH)
            return r.returncode, (r.stdout + r.stderr).strip()
        except subprocess.TimeoutExpired:
            return -1, 'host timeout'

    def ping(self):
        return self.sh('ping', timeout=3)[0] == 0

    def recording(self):
        return 'is_recording -> 0' not in self.sh('status', 'get', 'is_recording', timeout=10)[1]

    def key(self, name, n=1):
        if name.startswith('DIAL'):
            return self.sh('key', f'CMD{name} {n}')[0]
        return self.sh('key', name + 'ON')[0]

    def mem(self, addr, n):
        for _ in range(3):
            v = self.putfile.mem_get(addr, n)
            if None not in v:
                return [int(x) for x in v]
        raise Refused(f'mem get {addr:#x} x{n} incomplete')

    def call(self, addr, r0=0, r1=0, r2=0):
        ok, val = self.callfn.call(addr, r0=r0, r1=r1, r2=r2, verbose=False)
        if not ok:
            raise Freeze(f'call {addr:#x}({r0}, {r1}, {r2}) DID NOT RETURN')
        return val & 0xFFFFFFFF

    def screen(self):
        sys.path.insert(0, str(SH))
        import ui_drive
        app = ui_drive.mem1(ui_drive.APP_PTR)
        scr = ui_drive.mem1(app + ui_drive.APP_SCREEN) if app else None
        ptr = ui_drive.mem1(scr + ui_drive.SCREEN_NAME) if scr else None
        return ui_drive.cstr(ptr) if ptr else '?'

    def app_vars(self, names):
        sys.path.insert(0, str(SH))
        import ui_drive
        return ui_drive.app_vars(list(names))

    def getfile(self, remote, local, size=None):
        def run(sz):
            r = subprocess.run([sys.executable, '-B', 'getfile.py', remote, str(local), '--size', str(sz)],
                               capture_output=True, text=True, cwd=SH, timeout=300)
            return r.stdout + r.stderr
        out = run(size or 64 << 20)
        m = re.search(r'file length is (\d+)', out)
        if m and not size:
            run(int(m.group(1)))
        return pathlib.Path(local).is_file() and pathlib.Path(local).stat().st_size > 0

    def shot(self, n, local):
        self.sh('key', 'CAPTUREON'); self.sh('key', 'CAPTUREOFF')
        for _ in range(10):
            time.sleep(1.5)
            if self.getfile(f'\\DCIM\\100SIGMA\\SS__{n:04d}.JPG', local):
                return True
        return False

    def rec_take(self, seconds):
        subprocess.run(['zsh', str(SH / 'rec_take.sh'), str(seconds)], capture_output=True, timeout=seconds + 60)

    def latest_clip(self):
        _, out = self.sh('dir', '\\CINEMA')
        names = sorted(set(re.findall(r'A\d{3}_\d{3}', out)))
        return names[-1] if names else None

    def sleep(self, s):
        time.sleep(s)

    def now(self):
        return time.time()


# ---------------------------------------------------------------------------------------------------- expectations
def get(d, path):
    for p in path.split('.'):
        if not isinstance(d, dict) or p not in d:
            return None
        d = d[p]
    return d


def check(want, got, saved):
    """want: a literal (==), or {eq|ne|gt|ge|lt|le|in: v}, or {ref: 'name.field', add: k[, cmp: ...]}"""
    if not isinstance(want, dict):
        return got == want
    if 'ref' in want:
        base = get(saved, want['ref'])
        if base is None or got is None:
            return False
        want = {want.get('cmp', 'eq'): base + want.get('add', 0)}
    (op, v), = want.items()
    if got is None:
        return False
    ops = {'eq': lambda: got == v, 'ne': lambda: got != v, 'gt': lambda: got > v, 'ge': lambda: got >= v,
           'lt': lambda: got < v, 'le': lambda: got <= v, 'in': lambda: got in v,
           'startswith': lambda: str(got).startswith(str(v)), 'contains': lambda: str(v) in str(got)}
    try:
        return ops[op]()
    except TypeError:
        return False


# ---------------------------------------------------------------------------------------------------- the runner
class Runner:
    def __init__(self, cam, out, version, build=None):
        self.cam, self.out, self.version = cam, pathlib.Path(out), version
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / 'shots').mkdir(exist_ok=True)
        (self.out / 'dng').mkdir(exist_ok=True)
        path = pathlib.Path(build) if build else SL / 'qs/out' / f'build-{version}.json'
        if not path.is_file():
            raise SystemExit(f'build json missing: {path}')
        self.build = json.loads(path.read_text())
        if self.build.get('file') != f'SensorLab-IMX410_v{version}.BIN' or 'sq_test_off' not in self.build:
            raise SystemExit(f'{path}: not the build of v{version} or no sq_test_off')
        self.block = None
        self.qsc = None                              # (block, state_off, {field: offset}) of the loaded container
        self.saved = {}
        self.rec_stop = None
        self.last = 'start'
        self.flagged = []
        self.item = None
        self.ask = lambda prompt: sys.stdin.isatty() and input(prompt) is not None

    # -- safety
    def usb(self, what):
        """every USB action goes through here first"""
        if self.rec_stop is not None and self.cam.now() - self.rec_stop < POST_REC_S:
            raise Refused(f'{what}: only {self.cam.now() - self.rec_stop:.1f} s after the recording stopped')
        self.last = what

    def alive(self):
        t0 = self.cam.now()
        while True:
            if self.cam.ping():
                return True
            if self.cam.now() - t0 > FREEZE_S:
                raise Freeze(f'no pong for {FREEZE_S:.0f} s after: {self.last}')
            self.cam.sleep(0.3)

    def sq(self, op, a=0, b=0):
        if self.block is None:
            raise Refused('the SensorLab block is unknown: run a `loadlog` step first')
        return self.cam.call(self.block + self.build['sq_test_off'], op, a, b)

    # -- steps: each returns a result dict
    def s_note(self, st):
        return {}

    def s_manual(self, st):
        return {'manual': st.get('text', '')}

    def s_pause(self, st):
        """a hand step inside an item: wait for Enter (no terminal -> refused, the item stops)"""
        if not self.ask(f'item {self.item}: {st.get("text", "")} -- Enter when done: '):
            raise Refused('pause needs a terminal (or --yes)')
        return {'paused': st.get('text', '')}

    def s_wait(self, st):
        self.cam.sleep(st['s'])
        return {}

    def s_loadlog(self, st):
        self.usb('getfile LOAD.LOG')
        local = self.out / 'LOAD.LOG'
        self.cam.getfile('\\fpSup\\LOAD.LOG', local, None)
        log = local.read_bytes().decode('latin1') if local.is_file() else ''
        hits = re.findall(r'0A ([0-9A-F]{8}) ([0-9A-F]{8}) SensorLab-IMX410_v(\S+?)\.BIN', log)
        mine = [h for h in hits if h[2] == self.version]
        if len(mine) == 1:
            self.block = int(mine[0][0], 16)
        # the container: QS-Share_v<ver>.BIN from 0.0.1test (2026-11-07), QSContainer_v<ver>.BIN before
        qsc = re.findall(r'0A ([0-9A-F]{8}) [0-9A-F]{8} (QS-Share|QSContainer)_v(\S+?)\.BIN', log)
        if len(qsc) == 1:
            self.qsc = qsc_layout(int(qsc[0][0], 16), qsc[0][2])
        qsc = [f'{base}_v{v}.BIN' for _, base, v in qsc]
        return {'sl': [h[2] for h in hits], 'sl_claims': mine[0][1] if mine else None, 'qsc': qsc,
                'block': hex(self.block) if self.block else None, 'sltp': 'SLTP' in log}

    def s_keys(self, st):
        """keys: ['MENU', 'DOWN:2', 'DIAL1:+1', 'wait1']"""
        sent = []
        for k in st['keys']:
            if k.startswith('wait'):
                self.cam.sleep(float(k[4:] or 1)); continue
            name, _, n = k.partition(':')
            if name not in KEYS:
                raise Refused(f'key {name} is not allowed from a checklist')
            reps, step = (1, int(n or 1)) if name.startswith('DIAL') else (int(n or 1), 1)
            for _ in range(reps):
                self.usb(f'key {k}')
                self.cam.key(name, step)
                self.cam.sleep(st.get('gap', 0.4))
            sent.append(k)
            self.alive()
        return {'sent': sent}

    def s_pingkey(self, st):
        """one key inside a 100 ms ping loop; a reply timeout alone is not a freeze, FREEZE_S without pong is"""
        lines, worst, t0, last_ok = [], 0.0, self.cam.now(), self.cam.now()

        def loop(until):
            nonlocal worst, last_ok
            while self.cam.now() - t0 < until:
                ok = self.cam.ping()
                t = self.cam.now()
                if ok:
                    worst = max(worst, t - last_ok); last_ok = t
                elif t - last_ok > FREEZE_S:
                    raise Freeze(f'no pong for {FREEZE_S:.0f} s after key {st["key"]}')
                lines.append(f'{t - t0:7.2f} ping {int(ok)}')
                self.cam.sleep(0.1)
        if st['key'] not in KEYS:
            raise Refused(f'key {st["key"]} is not allowed')
        self.usb(f'pingkey {st["key"]}')
        loop(st.get('before', 1.0))
        rc = self.cam.key(st['key'])
        lines.append(f'{self.cam.now() - t0:7.2f} key {st["key"]} rc={rc}')
        loop(st.get('before', 1.0) + st.get('after', 8.0))
        (self.out / f'{st.get("save", "pingkey")}-pingloop.txt').write_text('\n'.join(lines) + '\n')
        n_ok = sum(1 for x in lines if x.endswith(' 1'))
        return {'pongs': n_ok, 'pings': sum(1 for x in lines if ' ping ' in x), 'max_gap': round(worst, 2)}

    def ui(self, want=None):
        """the UI log (no screenshot): screen, the page focus variables, the QS focus, the container's sub-QS state.
        want: only these keys (a step's `at`), None = everything"""
        self.usb('ui read')
        keys = set(want or ['screen', *APP_VARS, 'qs_focus', *QSC_FIELDS])
        r = {}
        if 'screen' in keys:
            r['screen'] = self.cam.screen()
        names = [k for k in APP_VARS if k in keys] + [k for k in keys if k.startswith(('SL_', 'SLM_', 'QS_'))]
        if names:
            r.update(self.cam.app_vars(names))
        if 'qs_focus' in keys:
            r['qs_focus'] = self.cam.mem(QS_FOCUS, 1)[0]
        if self.qsc and keys & set(QSC_FIELDS):
            base, off, lay = self.qsc
            for k in QSC_FIELDS:
                if k in keys:
                    v = self.cam.mem(base + off + lay[k], 1)[0]
                    r[k] = v - (1 << 32) if v >> 31 else v
        return r

    def at(self, st, res):
        """a step's expected position: `at` = {screen: 'B2_5', MENU_Level2: 4254, sub_open: 1, qs_focus: 70}"""
        if st.get('at'):
            res['at'] = self.ui(st['at'])
            for k, w in st['at'].items():
                st.setdefault('expect', {}).setdefault('at.' + k, w)
        return res

    def s_where(self, st):
        return self.ui(st.get('at'))

    def s_to_lv(self, st):
        """MENU until the screen is a live view (at most 4)"""
        for _ in range(4):
            self.usb('where')
            s = self.cam.screen()
            if s.startswith('LV'):
                return {'screen': s}
            self.usb('key MENU'); self.cam.key('MENU'); self.cam.sleep(1.0); self.alive()
        return {'screen': self.cam.screen()}

    def s_nav(self, st):
        """keys chosen by the screen now: {'by': {'MainB1': [...], 'MainB2': [...]}}"""
        self.usb('where')
        s = self.cam.screen()
        keys = st['by'].get(s)
        if keys is None:
            return {'screen': s, 'nav': None}
        r = self.s_keys({'keys': keys, 'gap': st.get('gap', 0.4)})
        self.usb('where')
        return {'from': s, 'sent': r['sent'], 'screen': self.cam.screen()}

    def s_sq(self, st):
        self.usb(f'sq_test {st["op"]}')
        v = self.sq(st['op'], st.get('a', 0), st.get('b', 0))
        r = {'value': v - (1 << 32) if v & 0x80000000 else v}
        if st.get('words'):
            r['words'] = self.cam.mem(v, st['words']) if v else None
        if st['op'] in STRUCTS and st.get('decode', True):
            names = STRUCTS[st['op']]
            w = self.cam.mem(v, len(names))
            r.update({k: x - (1 << 32) if x & 0x80000000 else x for k, x in zip(names, w)})
            for k, off in EXTRA.get(st['op'], {}).items():
                r[k] = self.cam.mem(v + off, 1)[0]
        return r

    def s_mem(self, st):
        self.usb(f'mem {st["addr"]:#x}')
        w = self.cam.mem(st['addr'], st.get('n', 1))
        return {'words': w, 'value': w[0]}

    def s_curmode(self, st):
        self.usb('mem curmode')
        return {'value': self.cam.mem(CUR_MODE, 1)[0]}

    def s_shot(self, st):
        n = st.get('n', getattr(self, 'next_shot', None))
        if n is None:
            raise Refused('the next screenshot number is unknown: pass --shot N')
        self.next_shot = n + 1
        self.usb(f'shot {n}')
        local = self.out / 'shots' / f'SS{n}-{st.get("tag", "shot")}.jpg'
        ok = self.cam.shot(n, local)
        if st.get('look'):
            self.flagged.append(str(local))
        return {'n': n, 'file': str(local), 'ok': ok}

    def s_rec(self, st):
        self.usb('recording check')
        if self.cam.recording():
            raise Refused('already recording')
        self.last = f'rec_take {st.get("s", 3)} s'
        self.cam.rec_take(st.get('s', 3))             # rec_take.sh: MOV pulse, sleep, MOV pulse, 12 s, ping
        self.rec_stop = self.cam.now() - POST_REC_S    # rec_take already waited POST_REC_S after the stop
        self.alive()
        self.usb('recording check')
        return {'recording_after': self.cam.recording()}

    def s_dng(self, st):
        """fetch frame `frame` of the newest clip, the bit check and a colour preview"""
        self.usb('dir CINEMA')
        clip = self.cam.latest_clip()
        if not clip:
            return {'clip': None}
        name = f'{clip}_{st.get("frame", 3):06d}.DNG'
        local = self.out / 'dng' / f'{st.get("tag", "dng")}_{name}'
        self.usb(f'getfile {name}')
        if not self.cam.getfile(f'\\CINEMA\\{clip}\\{name}', local, None):
            return {'clip': clip, 'file': None}
        r = {'clip': clip, 'file': str(local), **dng_check(local, local.with_suffix('.png'))}
        self.flagged.append(str(local.with_suffix('.png')))
        return r

    STEPS = {'note': s_note, 'manual': s_manual, 'pause': s_pause, 'wait': s_wait, 'loadlog': s_loadlog, 'keys': s_keys,
             'pingkey': s_pingkey, 'where': s_where, 'to_lv': s_to_lv, 'nav': s_nav, 'sq': s_sq, 'mem': s_mem,
             'curmode': s_curmode, 'shot': s_shot, 'rec': s_rec, 'dng': s_dng}

    # -- items
    def run(self, items, first=None, only=None):
        rows, log = [], open(self.out / 'results.jsonl', 'a')
        status = 'done'
        try:
            for it in items:
                if (first is not None and it['id'] < first) or (only and it['id'] not in only):
                    continue
                verdict, fails = 'PASS', []
                self.item = it['id']
                for i, st in enumerate(it['steps']):
                    rec = dict(item=it['id'], step=i, do=st['do'], t=time.strftime('%H:%M:%S'))
                    try:
                        res = self.STEPS[st['do']](self, st)
                        if st['do'] in ('keys', 'pingkey', 'nav', 'to_lv'):
                            res = self.at(st, res)
                    except Refused as e:
                        res = {'refused': str(e)}
                        fails.append(f'step {i} {st["do"]}: refused: {e}'); verdict = 'FAIL'
                    rec['got'] = res
                    if st['do'] == 'manual':
                        verdict = 'MANUAL' if verdict == 'PASS' else verdict
                    if st.get('save'):
                        self.saved[st['save']] = res
                    bad = {k: (w, get(res, k)) for k, w in st.get('expect', {}).items()
                           if not check(w, get(res, k), self.saved)}
                    if bad:
                        rec['bad'] = {k: {'want': w, 'got': g} for k, (w, g) in bad.items()}
                        fails += [f'step {i} {st["do"]}: {k} = {g!r}, want {w!r}' for k, (w, g) in bad.items()]
                        verdict = 'FAIL'
                    log.write(json.dumps(rec, default=str) + '\n'); log.flush()
                    if 'refused' in res or (bad and st.get('stop_on_fail', True)):
                        break
                rows.append((it, verdict, fails))
                if verdict == 'FAIL' and it.get('stop_run', False):
                    status = f'stopped after item {it["id"]}'
                    break
        except Freeze as e:
            status = f'FREEZE: {e}'
            log.write(json.dumps(dict(freeze=str(e), last=self.last, t=time.strftime('%H:%M:%S'))) + '\n')
            rows.append((it, 'FREEZE', [str(e)]))
        log.close()
        self.summary(rows, status)
        return status, rows

    def summary(self, rows, status):
        L = [f'# Checklist run, SensorLab v{self.version} — {time.strftime("%Y-%m-%d %H:%M")}', '',
             f'**Status: {status}**' + (f' (last action: `{self.last}`; no recovery done — stop, report)' if
                                        status.startswith('FREEZE') else ''), '',
             '| # | item | verdict | notes |', '|---|---|---|---|']
        for it, v, fails in rows:
            L.append(f'| {it["id"]} | {it["title"]} | {v} | {"; ".join(fails)[:300]} |')
        manual = [it for it, v, _ in rows if v == 'MANUAL']
        if manual:
            L += ['', 'Manual (not run by the script): ' + ', '.join(f'{it["id"]} {it["title"]}' for it in manual)]
        if self.flagged:
            L += ['', 'Look at:'] + [f'- {p}' for p in self.flagged]
        L += ['', f'Details: {self.out / "results.jsonl"}']
        (self.out / 'summary.md').write_text('\n'.join(L) + '\n')


def qsc_layout(block, version):
    """the container's state block and field offsets (its build json + its tests' struct layout)"""
    qc = ROOT / 'projects/qs-container'
    b = qc / 'out' / f'build-{version}.json'
    if not b.is_file():
        raise SystemExit(f'container build json missing: {b}')
    code = ('import sys, json; sys.argv = ["x"]; import test_qs_page as T; '
            f'print(json.dumps({{k: T.LAYOUT[k] for k in {list(QSC_FIELDS)!r}}}))')
    r = subprocess.run([sys.executable, '-B', '-c', code], cwd=qc, capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise SystemExit('container layout: ' + r.stderr[-500:])
    return block, json.loads(b.read_text())['state_off'], json.loads(r.stdout.strip().splitlines()[-1])


def dng_check(path, preview):
    """the bit check (dngcheck.py): metadata, mod-4 histogram, darks; a colour preview PNG"""
    sys.path.insert(0, str(SL / 'tools'))
    import numpy as np
    import analyze_dng as A
    data = pathlib.Path(path).read_bytes()
    rep = A.analyze(data, source=str(path), source_size=len(data), preview=str(preview))
    md = rep['metadata']
    _, blocks = A.decode_pixels(data, A.choose_raster(A.Tiff(data).ifds), 0, ())
    a = np.concatenate([b for _, b in blocks]).astype(np.int64)
    m4 = np.bincount((a & 3).ravel(), minlength=4) / a.size
    return {'bytes': len(data), 'raster': md.get('raster'), 'bits': (md.get('bits_per_sample') or [None])[0],
            'black': (md.get('black_level') or [None])[0], 'white': md.get('white_level'),
            'crop': md.get('default_crop_size'), 'fps': md.get('frame_rate'),
            'mod4': [round(float(x), 3) for x in m4], 'p01': float(np.percentile(a, 0.1)), 'preview': str(preview)}


def load_checklist(name):
    p = HERE / 'checklists' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(f'checklist_{name}', p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('checklist')
    ap.add_argument('--version', required=True)
    ap.add_argument('--build')
    ap.add_argument('--out')
    ap.add_argument('--from', dest='first', type=int)
    ap.add_argument('--only', default='')
    ap.add_argument('--shot', type=int, default=None, help='the next screenshot number on the card')
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args(argv)
    m = load_checklist(a.checklist)
    items = m.items(a.version)
    if a.list:
        for it in items:
            print(f'{it["id"]:3d} {it["title"]}: ' + ', '.join(s['do'] for s in it['steps']))
        return 0
    if not a.out:
        raise SystemExit('--out is required')
    r = Runner(Camera(), a.out, a.version, a.build)
    if a.shot is not None:
        r.next_shot = a.shot
    only = {int(x) for x in a.only.split(',') if x}
    status, _ = r.run(items, a.first, only)
    print((r.out / 'summary.md').read_text())
    return 0 if status == 'done' else 2


if __name__ == '__main__':
    sys.exit(main())
