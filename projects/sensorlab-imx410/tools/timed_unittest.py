#!/usr/bin/env python3
"""Run unittest names in this process and write per-test wall times as JSON (used by tools/test.py).

    python3 -B timed_unittest.py OUT.json NAME [NAME ...]      # NAME: module, module.Class or module.Class.test

Run it with the suite's directory as cwd (the suites import their neighbours from there).  The text log goes to
stderr like `unittest -v`; OUT.json gets {tests: [{id, class, s, outcome}], ran, failures, errors, skipped, wall}.
"""
import json
import os
import sys
import time
import unittest


class Result(unittest.TextTestResult):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.times, self._t0, self.outcome = [], {}, {}

    def startTest(self, test):
        self._t0[test.id()] = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        self.times.append((test.id(), time.perf_counter() - self._t0.pop(test.id(), time.perf_counter())))

    def _mark(self, test, what):
        self.outcome[test.id()] = what

    def addSuccess(self, t): super().addSuccess(t); self._mark(t, 'ok')
    def addFailure(self, t, e): super().addFailure(t, e); self._mark(t, 'FAIL')
    def addError(self, t, e): super().addError(t, e); self._mark(t, 'ERROR')
    def addSkip(self, t, r): super().addSkip(t, r); self._mark(t, 'skip')
    def addExpectedFailure(self, t, e): super().addExpectedFailure(t, e); self._mark(t, 'xfail')
    def addUnexpectedSuccess(self, t): super().addUnexpectedSuccess(t); self._mark(t, 'XPASS')


def main():
    out, names = sys.argv[1], sys.argv[2:]
    sys.path.insert(0, os.getcwd())
    t0 = time.perf_counter()
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    r = unittest.TextTestRunner(verbosity=2, resultclass=Result, stream=sys.stderr).run(suite)
    wall = time.perf_counter() - t0
    tests = [dict(id=i, cls=i.rsplit('.', 1)[0], s=round(s, 3), outcome=r.outcome.get(i, 'ERROR')) for i, s in r.times]
    # setUpClass / module errors are reported as _ErrorHolder "tests" without startTest
    for t, _e in r.errors:
        if t.id() not in r.outcome:
            tests.append(dict(id=t.id(), cls=t.id(), s=0, outcome='ERROR'))
    with open(out, 'w') as f:
        json.dump(dict(names=names, ran=r.testsRun, failures=len(r.failures), errors=len(r.errors),
                       skipped=len(r.skipped), ok=r.wasSuccessful(), wall=round(wall, 2), tests=tests), f, indent=1)
    sys.exit(0 if r.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
