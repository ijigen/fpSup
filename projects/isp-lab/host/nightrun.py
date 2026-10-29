#!/usr/bin/env python3
"""Unattended ISP custom runs: one case after another, nobody at the camera (notes/IMX410_LAB_SPEC.md §2).

    nightrun.py TAG EXP [EXP ...]        e.g.  nightrun.py night1 E0 z1536 z2048 z3072 z6144

Per case, in validation/<date>-<TAG>-<EXP>/:
    isp_custom apply EXP  ->  applied.json
    ispl.py take --discard  (the control task does standby / half-press AF / magnify / REC itself and pushes
                             LV, reports and CDNG over EP83; LISTEN83 only receives)   ->  push/, take.log
    isp_custom restore    ->  case.py  ->  archive_validation.py pack
and a line in validation/<date>-<TAG>.jsonl.  A case that fails is recorded and the next one runs; a take that does
not stop, a failed disarm / restore, or a shell that stops answering ends the batch with no further USB (10-28: two
automatic poffs lost the camera) -- a person checks the camera, then reruns (cases with a case.json are skipped).  ISPL reconnects USB once after every boot (ix_wr.c ix_ur_step), so EP83 comes back as bulk
1024 without a replug.  At the end the page is rebuilt (site/build_page.py).
"""
import argparse, datetime as dt, json, pathlib, shutil, subprocess, sys, time
import cardclean

HERE = pathlib.Path(__file__).resolve().parent
LAB = HERE.parent
ROOT = LAB.parents[1]
SHELL = ROOT / 'fpSup' / 'fp_usb_shell'
VAL = LAB / 'validation'
PY = [sys.executable, '-B']
import os
TAKE = ['--discard', '--start-ms', '0', '--rec-ms', os.environ.get('NR_REC_MS', '1000'), '--cp-standby-ms', '1000',
        '--cp-focus-ms', '1000', '--cp-mag-ms', '1000', '--lv-every-ms', '250', '--lv-max', '60', '--cd-after-ms', '1000',
        '--cd-max', os.environ.get('NR_CD_MAX', '3'), '--report']
if int(os.environ.get('NR_BURST_MS', '0')):        # v8.1: every new LV around the REC start (lv_burst_ms)
    TAKE += ['--lv-burst-ms', os.environ['NR_BURST_MS']]
    TAKE[TAKE.index('--lv-max') + 1] = os.environ.get('NR_LV_MAX', '200')      # NR_*: a probe wants a longer take / more DNGs
CLEAN_EVERY = 5                   # cases per card clean (each clean waits out late frames once)


def run(cmd, cwd, out=None, timeout=300):
    """(rc, text); rc None on a timeout."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        txt = (e.stdout or b'').decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
        if out: out.write_text(txt + '\n[timeout]\n')
        return None, txt
    txt = p.stdout + p.stderr
    if out: out.write_text(txt)
    return p.returncode, txt


def ep83_ok():
    rc, txt = run([str(SHELL / 'lsdesc')], SHELL, timeout=20)
    return rc == 0 and any('EP 0x83 IN  Bulk' in l and 'wMaxPacketSize=1024' in l for l in txt.splitlines())


def shell_ok():
    rc, txt = run(PY + ['-c', 'import putfile; print(putfile.sh("status get is_recording"))'], SHELL, timeout=30)
    return rc == 0 and txt.strip().endswith('0')


def ready(timeout=180):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if ep83_ok() and shell_ok():
            return True
        time.sleep(3)
    return False


def restore(log):
    rc, txt = run(PY + ['isp_custom.py', 'restore'], HERE, timeout=120)
    log(f'restore rc={rc} {txt.strip().splitlines()[-1] if txt.strip() else ""}')
    return rc == 0


def case(tag, exp, log):
    d = VAL / f'{dt.date.today():%Y%m%d}-{tag}-{exp.replace(":", "_")}'
    if (d / 'case.json').exists():
        log(f'{exp}: done before, skipped')
        return {'exp': exp, 'dir': d.name, 'skipped': True, 'verdict': json.loads((d / 'case.json').read_text()).get('verdict')}
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    rec = {'exp': exp, 'dir': d.name}
    rc, _ = run(PY + ['ispl.py', 'disarm'], HERE, d / 'disarm.log', timeout=120)   # take refuses an armed sink
    if rc != 0:
        rec['fail'] = 'disarm'
        rec['stop'] = True                          # 10-28 p5: a shell that cannot disarm is not one to poff
        return rec
    rc, txt = run(PY + ['isp_custom.py', 'apply', exp], HERE, d / 'apply.log', timeout=180)
    if rc != 0:
        rec['fail'] = 'apply'
        if not restore(log):
            rec['stop'] = True
        return rec
    shutil.copy2(HERE / '.isp_custom_applied.json', d / 'applied.json')
    rc, txt = run(PY + ['ispl.py', 'take', *TAKE, '--listen', str(d / 'push')], HERE, d / 'take.log', timeout=240)
    rec['take_rc'] = rc
    if rc != 0 and 'still recording' in txt:        # 10-28 p1 C5096955f: a take that does not stop. Any USB now
        rec['fail'] = 'stuck recording'             # (restore, card clean, ping, poff) can wedge the camera: the
        rec['stop'] = True                          # batch ends here, untouched, for someone at the camera
        return rec
    if rc == 0:                                       # the route patched must be the one the menu records with
        mrc, mtxt = run(PY + ['-c', 'from putfile import mem_get; print(mem_get(0xC343B590)[0])'], SHELL, timeout=30)
        try:
            rec['mode'] = int(mtxt.strip().splitlines()[-1])
        except (ValueError, IndexError):
            rec['mode'] = None
    if not restore(log):
        rec['fail'] = 'restore'
        rec['stop'] = True                          # 10-28 p5: "heap parameters did not land", then the echo slot
        return rec                                  # was not ours: a poff then lost the camera (shell never came back)
    if rc != 0:
        rec['fail'] = 'take'
        return rec
    want_mode = json.loads((d / 'applied.json').read_text()).get('sensor_mode')
    if rec.get('mode') is not None and want_mode is not None and rec['mode'] != want_mode:
        rec['fail'] = f'route: recorded with mode {rec["mode"]}, patched the row of mode {want_mode}'
        return rec
    rec['analyse'] = str(d)                           # case.py + archive: host only, done while the next case runs
    return rec


def analyse(rec):
    """case.py and the archive for one recorded case (no camera): fills rec in place."""
    d = pathlib.Path(rec.pop('analyse'))
    rc, txt = run(PY + ['case.py', str(d)], HERE, d / 'case.log', timeout=300)
    if rc != 0:
        rec['fail'] = 'case'
        return rec
    c = json.loads((d / 'case.json').read_text())
    rec.update(verdict=c.get('verdict'), checks=c.get('checks'), counts=c.get('counts'),
               shots=sorted(k for k, v in (c.get('checkpoints') or {}).items() if v and v.get('shot')))
    arc, _ = run(PY + ['archive_validation.py', 'pack', str(d)], HERE, d / 'archive.log', timeout=600)
    if arc == 0:                                      # pack verified every member: the raw copy is a duplicate
        shutil.rmtree(d / 'push')                     # (10-27: two copies filled the disk); restore with zstd -dc
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('tag')
    ap.add_argument('exps', nargs='+')
    a = ap.parse_args()
    journal = VAL / f'{dt.date.today():%Y%m%d}-{a.tag}.jsonl'

    def log(msg):
        line = f'{dt.datetime.now():%H:%M:%S} {msg}'
        print(line, flush=True)
        with open(journal.with_suffix('.log'), 'a') as f:
            f.write(line + '\n')

    if not ready(60):                                     # no automatic poff any more (10-28): a person checks first
        raise SystemExit('camera not reachable: shell or EP83 down -- check it by hand, then restart the batch')
    from concurrent.futures import ThreadPoolExecutor
    pool, pending = ThreadPoolExecutor(2), []

    def finish(rec):
        rec['t'] = f'{dt.datetime.now():%H:%M:%S}'
        with open(journal, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        log(f'{rec["exp"]}: {rec.get("verdict") or "FAIL " + rec.get("fail", "?")}  {rec.get("checks")}  {rec.get("shots")}')

    def drain(block=False):
        for fu in [f for f in pending if block or f.done()]:
            finish(fu.result())
            pending.remove(fu)

    before, batch = cardclean.clips(), 0            # the discard takes still leave clip folders: removed per CLEAN_EVERY
    for i, exp in enumerate(a.exps):
        if (VAL / 'STOP').exists():                 # someone needs the camera: stop between cases
            log(f'STOP file: stopped before {exp}')
            break
        log(f'{exp}: start')
        rec = case(a.tag, exp, log)
        if rec.get('stop'):
            finish(rec)
            log(f'{exp}: {rec["fail"]} -- batch stopped, no further USB: check the camera by hand (stop REC if it '
                f'records, wait 10 s), then restore by hand (isp_custom.py restore)')
            drain(True)
            raise SystemExit(f'{exp}: {rec["fail"]}')
        batch += 'take_rc' in rec
        if batch >= CLEAN_EVERY or i == len(a.exps) - 1:
            try:                                     # one settle for the whole batch's late frames
                rec['card_cleaned'] = cardclean.remove_new(before)
            except Exception as e:                   # a full card stops every later take: stop here
                rec['fail'] = f'card clean: {e}'
                finish(rec)
                drain(True)
                raise SystemExit(f'{exp}: card clean failed: {e}')
            before, batch = cardclean.clips(), 0
        if 'analyse' in rec:
            pending.append(pool.submit(analyse, rec))
        else:
            finish(rec)
        drain()
        if not ready(60):                                  # the next case needs a working shell and EP83
            log('camera not ready: stopping, no poff (10-28: a poff with the echo slot not ours lost the camera)')
            break
    drain(True)
    run(PY + [str(LAB / 'site' / 'build_page.py')], LAB / 'site', timeout=600)
    log('page rebuilt')


if __name__ == '__main__':
    main()
