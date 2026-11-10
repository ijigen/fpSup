#!/usr/bin/env python3
"""SensorLab-IMX410 + QS container offline tests, in two tiers, in parallel (no camera, no USB).

    python3 -B tools/test.py fast            # < 30 s: host tests + a few unicorn smoke steps
    python3 -B tools/test.py full            # every test of every suite + every mutation run (the release gate)
    python3 -B tools/test.py prelive         # every test + only the mutation suites whose target files changed since
                                             # the last full PASS (tools/.testcache/last_full.json); none recorded -> full
    python3 -B tools/test.py full --no-mutants          # every test, no mutation runs
    python3 -B tools/test.py mutants [--only slqs,apply]  # just the mutation runs
    python3 -B tools/test.py list            # the jobs a tier would run
    python3 -B tools/test.py clean           # drop the test cache (tools/.testcache)

    -j N          worker processes (default: the CPU count)
    --strict      unicorn's instruction counter instead of the wall-clock cap (SL_EMU_COUNT=1), no cache
    --kills       mutation runs without failfast (which tests catch each mutant; slower)

Every job is its own process (unicorn is per process); results and logs go to tools/test-logs/<tier>-<time>/, the
terminal gets one line per suite.  The test cache (qs-container/testcache.py) holds the built BINs, the v4 core and
the preview's page states, keyed by everything they were built from; `full` rebuilds them once before it fans out.
Suite scripts are unchanged and still run on their own (python3 -B -m unittest test_slqs, ...).
"""
import argparse
import concurrent.futures as cf
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
SL = HERE.parent
PROJ = SL.parent
CACHE = pathlib.Path(os.environ.get('SL_TESTCACHE_DIR') or HERE / '.testcache')
TIMED = HERE / 'timed_unittest.py'
HISTORY = CACHE / 'timings.json'
PY = [sys.executable, '-B']

# (suite, directory under projects/, unittest module)
UNIT = [('site', 'sensorlab-imx410/site', 'test_site'),
        ('menu', 'sensorlab-imx410/menu', 'test_menu'),
        ('menu-page', 'sensorlab-imx410/menu', 'test_page'),
        ('menu-runtime', 'sensorlab-imx410/menu', 'test_runtime'),
        ('menu-runtime-mutations', 'sensorlab-imx410/menu', 'test_runtime_mutations'),
        ('pb-page', 'sensorlab-imx410/apply', 'test_pb_page'),
        ('apply', 'sensorlab-imx410/apply', 'test_apply'),
        ('qsc-api5', 'qs-container', 'test_api5'),
        ('qsc', 'qs-container', 'test_qsct'),
        ('qsc-page', 'qs-container', 'test_qs_page'),
        ('slqs', 'sensorlab-imx410/qs', 'test_slqs'),
        ('settings-migration', 'sensorlab-imx410/qs', 'test_settings_migration')]
CORE = 'sensorlab-imx410/core'

# the fast tier: pure host tests (lists, ranking / defaultPick, payload / CRC, menu lists, the host-compiled core and
# apply calc) + unicorn smoke: two short preview sequences step by step, the QS open, the MB/s footer
FAST = {
    'site': ['test_site'],
    'menu': ['test_menu'],
    'menu-page': ['test_page.PageStructure'],
    'apply': ['test_apply.CalcTests', 'test_apply.SourceTests', 'test_apply.PoolTests'],
    'qsc': ['test_qsct.CsvRows'],
    'slqs': ['test_slqs.QRPayload', 'test_slqs.Build',
             'test_slqs.Preview.test_recorded_bits_and_native_width_marks', 'test_slqs.Preview.test_default_pick_examples',
             'test_slqs.Preview.test_s16_back_to_hd_is_the_spec', 'test_slqs.Preview.test_sequences_reach_what_they_name',
             'test_slqs.Preview.test_00', 'test_slqs.Preview.test_12', 'test_slqs.Tiles.test_qs_open',
             'test_slqs.QR.test_mbps_footer_short'],
}

# mutation runs: (suite, directory, how to count the mutants, the command for mutant i of n)
MUTANTS = [
    ('slqs', 'sensorlab-imx410/qs', 'test_slqs', lambda i, n: ['test_slqs.py', '--mutate', f'--part={i}/{n}']),
    ('qsc', 'qs-container', 'test_qsct', lambda i, n: ['test_qsct.py', '--mutate', f'--part={i}/{n}']),
    ('qsc-page', 'qs-container', 'test_qs_page', lambda i, n: ['test_qs_page.py', '--mutate', f'--part={i}/{n}']),
    ('apply', 'sensorlab-imx410/apply', 'test_apply', lambda i, n: ['test_apply.py', '--mutate', f'--only={i}']),
    ('core', CORE, 'test_core', lambda i, n: ['test_core.py', '--mutants-only', f'--part={i}/{n}']),
    ('menu', 'sensorlab-imx410/menu', None, lambda i, n: ['test_menu.py', '--mutate']),
]


# the files each mutation suite patches (and its own test module: a changed mutant list reruns the suite).  prelive
# reruns a suite's mutants when any of these differs from the hashes `full` recorded at its last PASS.
MUT_TARGETS = {
    'slqs': ['sensorlab-imx410/qs/slqs.c', 'sensorlab-imx410/qs/build_slqs.py', 'sensorlab-imx410/qs/preview_runner.js',
             'sensorlab-imx410/qs/test_slqs.py'],
    'qsc': ['qs-container/qsct.c', 'qs-container/test_qsct.py'],
    'qsc-page': ['qs-container/qsct.c', 'qs-container/test_qs_page.py'],
    'apply': ['sensorlab-imx410/apply/ap.c', 'sensorlab-imx410/apply/ap_calc.c', 'sensorlab-imx410/apply/ap.h',
              'sensorlab-imx410/apply/test_apply.py'],
    'core': ['sensorlab-imx410/core/core.c', 'sensorlab-imx410/core/core.h', 'sensorlab-imx410/core/test_core.py'],
    'menu': ['sensorlab-imx410/menu/menu_lists.py', 'sensorlab-imx410/menu/slm_page.py',
             'sensorlab-imx410/menu/test_menu.py'],
}
LAST_FULL = CACHE / 'last_full.json'


def target_hashes():
    import hashlib
    out = {}
    for files in MUT_TARGETS.values():
        for f in files:
            p = PROJ / f
            out[f] = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    return out


def changed_suites():
    """the mutation suites whose targets differ from the last full PASS, or None when nothing is recorded"""
    try:
        rec = json.loads(LAST_FULL.read_text())['files']
    except Exception:
        return None
    now = target_hashes()
    return {s for s, files in MUT_TARGETS.items() if any(rec.get(f) != now[f] for f in files)}


def env_for(a, extra=None):
    e = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    if a.strict:
        e.update(SL_EMU_COUNT='1', SL_TESTCACHE='0')
    if not a.kills:
        e['SL_MUT_FAILFAST'] = '1'
    e.update(extra or {})
    return e


def run(cmd, cwd, log, env, timeout=None):
    t = time.time()
    with open(log, 'w') as f:
        try:
            rc = subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, env=env, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            f.write(f'\nTIMEOUT after {timeout} s\n')
            rc = 124
    return rc, time.time() - t


# ------------------------------------------------------------------------------------------------------ jobs
class Job:
    def __init__(self, suite, kind, label, cwd, cmd, est=1.0):
        self.suite, self.kind, self.label, self.cwd, self.cmd, self.est = suite, kind, label, cwd, cmd, est
        self.rc, self.secs, self.result = None, 0.0, None


def list_ids(cwd, module):
    """the test ids of a module (loaded in its own process, as the suite runs)"""
    code = ('import json, sys, unittest; sys.path.insert(0, "."); s = unittest.defaultTestLoader.loadTestsFromName(%r)\n'
            'def walk(x):\n'
            '    for t in x:\n'
            '        yield from (walk(t) if isinstance(t, unittest.TestSuite) else [t.id()])\n'
            'print(json.dumps(list(walk(s))))' % module)
    r = subprocess.run(PY + ['-c', code], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f'{module}: cannot list tests\n{r.stderr[-2000:]}')
    return json.loads(r.stdout.strip().splitlines()[-1])


def count_mutants(cwd, module):
    r = subprocess.run(PY + ['-c', f'import sys; sys.path.insert(0, "."); import {module} as m; print(len(m.MUTANTS))'],
                       cwd=cwd, capture_output=True, text=True, env=dict(os.environ, SL_TESTCACHE='0'))
    if r.returncode:
        raise RuntimeError(f'{module}: cannot count mutants\n{r.stderr[-2000:]}')
    return int(r.stdout.strip().splitlines()[-1])


def history():
    try:
        return json.loads(HISTORY.read_text())
    except Exception:
        return {}


def unit_jobs(tier, hist, split_over=6.0):
    """one job per class; a class that took over `split_over` s last time: one job per test"""
    jobs = []
    for suite, d, mod in UNIT:
        cwd = PROJ / d
        if tier == 'fast':
            if suite in FAST:
                names = FAST[suite]
                jobs.append(Job(suite, 'unit', f'{suite}:fast', cwd, None, sum(hist.get(n, 1.0) for n in names)))
                jobs[-1].names = names
            continue
        ids = list_ids(cwd, mod)
        by_cls = {}
        for i in ids:
            by_cls.setdefault(i.rsplit('.', 1)[0], []).append(i)
        for cls, tests in by_cls.items():
            est = sum(hist.get(t, 1.0) for t in tests)
            groups = [[t] for t in tests] if est > split_over and len(tests) > 1 else [tests]
            for g in groups:
                j = Job(suite, 'unit', g[0] if len(g) == 1 else cls, cwd, None, sum(hist.get(t, 1.0) for t in g))
                j.names = g
                jobs.append(j)
    return jobs


def core_job(tier, hist, jobs_n):
    cmd = ['test_core.py', '--jobs', str(min(jobs_n, 10))] + (['--quick'] if tier == 'fast' else [])
    return Job('core', 'script', f'core:{tier}', PROJ / CORE, cmd, hist.get(f'core:{tier}', 60.0 if tier == 'full' else 6.0))


def mutant_jobs(hist, only=None):
    jobs = []
    for suite, d, mod, cmd in MUTANTS:
        if only and suite not in only:
            continue
        cwd = PROJ / d
        n = count_mutants(cwd, mod) if mod else 1
        for i in range(n):
            label = f'mut:{suite}:{i}'
            jobs.append(Job(suite, 'mutant', label, cwd, cmd(i, n), hist.get(label, 60.0)))
    return jobs


def execute(job, logdir, a):
    log = logdir / (job.label.replace(':', '_').replace('/', '_') + '.log')
    env = env_for(a)
    if job.kind == 'unit':
        out = log.with_suffix('.json')
        job.rc, job.secs = run(PY + [str(TIMED), str(out)] + job.names, job.cwd, log, env)
        try:
            job.result = json.loads(out.read_text())
        except Exception:
            job.result = None
    else:
        job.rc, job.secs = run(PY + job.cmd, job.cwd, log, env)
        job.result = dict(tail=log.read_text()[-400:])
    job.log = log
    return job


def warm(logdir, a):
    """build the cached pieces once from the current sources (SL_TESTCACHE=refresh) before the fan-out"""
    if a.strict:
        return 0.0
    code = ('import sys; sys.path.insert(0, "."); import test_slqs as S\n'
            'S.blob(); S.Q1.cblob(); S.Q1.U.built(); S.page_states(S.SEQS)\n')
    rc, secs = run(PY + ['-c', code], SL / 'qs', logdir / 'warm.log', env_for(a, dict(SL_TESTCACHE='refresh')))
    if rc:
        raise SystemExit(f'warm-up failed, see {logdir / "warm.log"}')
    return secs


# ------------------------------------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('tier', choices=['fast', 'full', 'prelive', 'mutants', 'list', 'clean'])
    ap.add_argument('which', nargs='?', default='fast', help='for list: fast or full')
    ap.add_argument('-j', '--jobs', type=int, default=os.cpu_count() or 4)
    ap.add_argument('--no-mutants', action='store_true')
    ap.add_argument('--only', default='', help='mutants: comma-separated suites (slqs, qsc, qsc-page, apply, core, menu)')
    ap.add_argument('--strict', action='store_true')
    ap.add_argument('--kills', action='store_true')
    a = ap.parse_args()
    if a.tier == 'clean':
        shutil.rmtree(CACHE, ignore_errors=True)
        print('removed', CACHE)
        return 0
    hist = history()
    tier = a.which if a.tier == 'list' else a.tier
    only = set(filter(None, a.only.split(',')))
    jobs = []
    pre = None
    if tier == 'prelive':
        pre = changed_suites()
        if pre is None:
            print('prelive: no full PASS recorded -> full')
            tier = 'full'
        else:
            print(f"prelive: mutation suites changed since the last full PASS: {', '.join(sorted(pre)) or 'none'}")
            jobs += unit_jobs('full', hist) + [core_job('full', hist, a.jobs)]
            if pre:
                jobs += mutant_jobs(hist, pre)
    if tier in ('fast', 'full'):
        jobs += unit_jobs(tier, hist) + [core_job(tier, hist, a.jobs)]
    if tier == 'mutants' or (tier == 'full' and not a.no_mutants):
        jobs += mutant_jobs(hist, only)
    if a.tier == 'list':
        for j in jobs:
            print(f'{j.est:7.1f}  {j.label}  ' + ' '.join(getattr(j, 'names', None) or j.cmd))
        print(f'{len(jobs)} jobs')
        return 0

    stamp = time.strftime('%Y%m%d-%H%M%S')
    logdir = HERE / 'test-logs' / f'{tier}-{stamp}'
    logdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    hashes = target_hashes()                             # before the run: what this PASS is a PASS of
    warm_s = warm(logdir, a) if tier in ('full', 'mutants', 'prelive') else 0.0
    jobs.sort(key=lambda j: -j.est)                      # longest first: the tail is short jobs
    done = []
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as pool:
        futs = [pool.submit(execute, j, logdir, a) for j in jobs]
        for f in cf.as_completed(futs):
            j = f.result()
            done.append(j)
            if j.rc:
                print(f'  FAIL  {j.label}  ({j.secs:.1f} s)  {j.log}', flush=True)
    wall = time.time() - t0

    # ---- summary per suite
    rows, bad = {}, 0
    for j in done:
        r = rows.setdefault((j.suite, j.kind), dict(jobs=0, ran=0, failures=0, errors=0, skipped=0, cpu=0.0, failed_jobs=0))
        r['jobs'] += 1
        r['cpu'] += j.secs
        if j.rc:
            r['failed_jobs'] += 1
            bad += 1
        if j.kind == 'unit' and j.result:
            for k in ('ran', 'failures', 'errors', 'skipped'):
                r[k] += j.result[k]
    print(f'{tier}: {len(done)} jobs on {a.jobs} workers, wall {wall:.1f} s (warm-up {warm_s:.1f} s); logs {logdir}')
    for (suite, kind), r in sorted(rows.items(), key=lambda x: (x[0][1], x[0][0])):
        what = (f"{r['ran']:4d} tests, {r['failures']} fail, {r['errors']} err, {r['skipped']} skip" if kind == 'unit' else
                f"{r['jobs']:4d} {'mutants' if kind == 'mutant' else 'run'}, {r['failed_jobs']} failed")
        print(f'  {kind:7s} {suite:24s} {what}   cpu {r["cpu"]:7.1f} s')
    # ---- history (scheduling) and the report
    for j in done:
        if j.kind == 'unit' and j.result:
            for t in j.result['tests']:
                hist[t['id']] = t['s']
        hist[j.label] = round(j.secs, 2)
    CACHE.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(hist, indent=0, sort_keys=True))
    report = dict(tier=tier, wall=round(wall, 1), warm=round(warm_s, 1), workers=a.jobs, strict=a.strict,
                  suites={f'{k[1]}:{k[0]}': v for k, v in rows.items()},
                  jobs=[dict(label=j.label, suite=j.suite, kind=j.kind, rc=j.rc, secs=round(j.secs, 2)) for j in
                        sorted(done, key=lambda j: -j.secs)])
    (logdir / 'report.json').write_text(json.dumps(report, indent=1))
    if tier == 'full' and not bad and not a.no_mutants and not only and not a.strict and hashes == target_hashes():
        LAST_FULL.write_text(json.dumps(dict(when=stamp, files=hashes), indent=1, sort_keys=True))
        print(f'recorded the mutation targets of this full PASS in {LAST_FULL}')
    print('PASS' if not bad else f'FAIL: {bad} job(s)')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
