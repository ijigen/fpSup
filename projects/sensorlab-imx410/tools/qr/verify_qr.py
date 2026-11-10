#!/usr/bin/env python3
"""Reproducible offline QR-only baseline and mutation checks; never uses USB.

The product source stays untouched. Each mutant is compiled from a temporary
copy and runs only its relevant QR test; the baseline must pass without skips.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
QS = ROOT / 'projects/sensorlab-imx410/qs'
TESTS = ['test_slqs.QRPayload', 'test_slqs.QR',
         'test_slqs.Preview.test_15', 'test_slqs.Preview.test_16']
MARKER = 'QR_RESULT_JSON='
TARGETS = {
    'QR: RS generator on the wrong root': 'test_encoder_matrix',
    'QR: format bits without the xor mask': 'test_encoder_matrix',
    'QR: quiet zone 1 module': 'test_encoder_matrix',
    'QR: CRC poly 0x31': 'test_c_pack_equals_reference',
    'QR: RES custom bit inverted': 'test_live_payload_is_the_selection',
    'QR: ISP window fields swapped': 'test_live_payload_is_the_selection',
    'QR: AEL again does not hide': 'test_triple_buffer_and_present',
    'QR: draws on any layer': 'test_observer_rejects_other_dimensions_and_untouched_hidden_buffers',
    'QR: a full group registered anyway': 'test_refused_without_a_free_slot_after_the_gui',
    'QR: group 0 again (the first 16-bpp layer, live7)': 'test_triple_buffer_and_present',
    'QR: no restore at hide (live7: the code stays in the buffers)': 'test_triple_buffer_and_present',
    'QR: only the presented buffer restored': 'test_triple_buffer_and_present',
    'QR: the shadow never learns': 'test_triple_buffer_and_present',
    'QR: shown while recording': 'test_locked_while_recording',
    'preview: QR code dropped from the runner': 'test_slqs.Preview.test_15',
}


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def child(names):
    sys.path[:0] = [str(QS), str(HERE)]
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    print(stream.getvalue(), end='')
    data = {'tests_run': result.testsRun, 'skipped': [(t.id(), why) for t, why in result.skipped],
            'failures': [(t.id(), error) for t, error in result.failures],
            'errors': [(t.id(), error) for t, error in result.errors],
            'successful': result.wasSuccessful() and not result.skipped}
    print(MARKER + json.dumps(data))
    return 0 if data['successful'] else 1


def invoke(names, env=None):
    cmd = [sys.executable, '-B', str(pathlib.Path(__file__).resolve()), '--child', *names]
    p = subprocess.run(cmd, cwd=QS, env=env, capture_output=True, text=True, timeout=240)
    lines = p.stdout.splitlines()
    result_lines = [line for line in lines if line.startswith(MARKER)]
    data = json.loads(result_lines[-1][len(MARKER):]) if result_lines else None
    transcript = '\n'.join(line for line in lines if not line.startswith(MARKER)) + '\n' + p.stderr
    return p.returncode, data, transcript


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', nargs='+', help=argparse.SUPPRESS)
    parser.add_argument('--out', type=pathlib.Path, default=ROOT / 'projects/sensorlab-imx410/validation/qr-offline-20261030')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--baseline-only', action='store_true')
    args = parser.parse_args()
    if args.child:
        return child(args.child)
    if not 1 <= args.jobs <= 4:
        parser.error('--jobs must be 1..4')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(QS), str(HERE)]
    import test_slqs as T
    src = (QS / 'slqs.c').read_text()
    source_hash = hashlib.sha256(src.encode()).hexdigest()
    snapshot = out / 'slqs.source.c'
    snapshot.write_text(src)
    backend = 'OpenCV + strict pristine V5 reference' if importlib.util.find_spec('cv2') else (
        'SLQS_CV_PYTHON + strict pristine V5 reference' if os.environ.get('SLQS_CV_PYTHON') else 'strict pristine V5 reference only')
    report = {'scope': 'offline ARM QR verification only; no camera operations', 'decoder': backend,
              'optical_or_phone_scan_verified': False, 'python': sys.executable,
              'source_snapshot': str(snapshot), 'source_snapshot_sha256': source_hash,
              'mutations_requested': not args.baseline_only,
              'sources': {str(p.relative_to(ROOT)): hash_file(p) for p in
                          (QS / 'slqs.c', QS / 'test_slqs.py', QS / 'build_slqs.py', HERE / 'qr_v5_reference.py',
                           HERE / 'test_qr_v5_reference.py', HERE / 'verify_qr.py')},
              'firmware_sha256': hash_file(ROOT / 'out/MAIN_c0000000.bin'), 'mutants': []}
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    for key in ('SLQS_SRC', 'SLQS_BUILD_SRC', 'SLQS_RUNNER', 'PYTHONPYCACHEPREFIX'):
        env.pop(key, None)
    env['SLQS_SRC'] = str(snapshot)
    print('Decoder:', backend, flush=True)
    code, result, log = invoke(['test_qr_v5_reference', *TESTS], env)
    (out / 'baseline.log').write_text(log)
    report['baseline'] = result
    if code or not result or not result['successful']:
        report['status'] = 'BASELINE_FAILED'
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(log)
        return 1
    print(f'Baseline: {result["tests_run"]} passed; 0 skips', flush=True)
    chosen = [m for m in T.MUTANTS if m[0].startswith('QR:') or m[0].startswith('preview: QR')]
    if {m[0] for m in chosen} != set(TARGETS):
        raise RuntimeError('QR mutation list changed; update the explicit focused-test mapping')

    def check(item):
        index, (label, old, new, *where) = item
        row = {'label': label, 'test': TARGETS[label]}
        target = (QS / 'preview_runner.js').read_text() if where else src
        if target.count(old) != 1:
            row.update(status='BAD_PATTERN', occurrences=target.count(old))
            return row
        case = TARGETS[label]
        if not case.startswith('test_slqs.'):
            case = 'test_slqs.QR.' + case
        mutant_env = dict(env)
        with tempfile.TemporaryDirectory(prefix='slqs-qr-mut-') as tmp:
            path = pathlib.Path(tmp) / ('preview_runner.js' if where else 'slqs.c')
            path.write_text(target.replace(old, new))
            if where:
                mutant_env['SLQS_RUNNER'] = str(path)
            else:
                mutant_env['SLQS_SRC'] = str(path)
                try:
                    T.BS.compile_text(path)
                except T.BS.BuildError as exc:
                    row.update(status='COMPILE_FAILED', error=str(exc))
                    return row
            try:
                returncode, data, log = invoke([case], mutant_env)
            except subprocess.TimeoutExpired:
                row.update(status='TIMEOUT_UNVERIFIED')
                return row
        (out / f'mutant-{index:02d}.log').write_text(log)
        errors = data['errors'] if data else []
        infrastructure = any(any(tag in error for tag in ('ImportError:', 'ModuleNotFoundError:', 'FileNotFoundError:',
                                                          'SyntaxError:', 'BuildError:')) for _, error in errors)
        caught = (returncode != 0 and data is not None and data['tests_run'] == 1 and not data['skipped']
                  and (data['failures'] or errors) and not infrastructure)
        row.update(status='CAUGHT' if caught else 'UNVERIFIED' if infrastructure or not data else 'SURVIVED',
                   result=data, log=f'mutant-{index:02d}.log')
        print(row['status'] + ': ' + label, flush=True)
        return row

    if not args.baseline_only:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            report['mutants'] = list(pool.map(check, enumerate(chosen)))
    report['source_unchanged'] = hash_file(QS / 'slqs.c') == source_hash
    # A different agent may integrate unrelated code while this frozen source
    # is tested. Record that separately; every baseline/mutant uses the snapshot.
    report['status'] = 'PASS' if all(m['status'] == 'CAUGHT' for m in report['mutants']) else 'FAIL'
    if args.baseline_only and report['status'] == 'PASS':
        report['status'] = 'PASS_BASELINE_ONLY'
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'{report["status"]}: {len(report["mutants"])} QR mutants; report {out / "report.json"}')
    return 0 if report['status'].startswith('PASS') else 1


if __name__ == '__main__':
    raise SystemExit(main())
