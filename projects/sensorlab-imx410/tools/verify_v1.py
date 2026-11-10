#!/usr/bin/env python3
"""Freeze the exact v1 client/container bytes, then run their integrated tests.

Offline only. Registry/modelCSV services remain declared emulation substitutes;
the saved results do not claim camera rendering or DMA timing validation.
"""
import argparse
import hashlib
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
LAB = ROOT / 'projects/sensorlab-imx410'
sys.path[:0] = [str(LAB / 'qs'), str(LAB / 'menu')]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=pathlib.Path, required=True)
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    import test_slqs as S
    sources = [LAB / p for p in ('qs/slqs.c', 'qs/build_slqs.py', 'apply/ap.c', 'apply/ap_calc.c',
               'apply/pb_page.h', 'menu/slm_runtime.h', 'menu/slm_state.h', 'menu/slm_page.h')]
    hashes = lambda: {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    before = hashes()
    client, info = S.blob()
    container, ci = S.Q1.cblob()
    (out / 'fpSup').mkdir()
    (out / 'fpSup' / S.BS.file_name()).write_bytes(client)
    (out / 'fpSup' / S.Q1.CNAME).write_bytes(container)
    (out / 'client-build.json').write_text(json.dumps(info, indent=2) + '\n')
    (out / 'container-build.json').write_text(json.dumps(ci, indent=2) + '\n')
    suite = unittest.defaultTestLoader.loadTestsFromNames(['test_slqs', 'test_runtime'])
    with (out / 'tests.txt').open('w', buffering=1) as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    report = dict(tests=result.testsRun, failures=[t.id() for t, _ in result.failures],
                  errors=[t.id() for t, _ in result.errors], skips=[t.id() for t, _ in result.skipped],
                  success=result.wasSuccessful() and not result.skipped,
                  client_sha256=hashlib.sha256(client).hexdigest(),
                  container_sha256=hashlib.sha256(container).hexdigest(), sources=before,
                  source_unchanged=before == hashes())
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
