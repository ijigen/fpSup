"""Focused UI/record/apply regressions on exact new default BIN; no camera I/O."""
from pathlib import Path
import json,sys,unittest
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
sys.path.insert(0,str(ROOT/'projects/sensorlab-imx410/qs'))
import test_slqs as S
import test_dc_steps as D
D.exact_build(HERE/'default-build','0.7.19test')
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c)
                         for c in (S.Tiles,S.RatioTile,S.Record,S.ApplyUnit))
r=unittest.TextTestRunner(verbosity=2).run(suite)
result=dict(passed=r.wasSuccessful(),tests=r.testsRun,failures=len(r.failures),errors=len(r.errors),skipped=len(r.skipped))
(HERE/'regressions.json').write_text(json.dumps(result,indent=2)+'\n')
assert r.wasSuccessful() and not r.skipped
seqs=[S.SEQS[18],dict(name='coarse native stops',keys=['focus:1','ael','focus:1']+['r-']*15+['r+']*15)]
for seq,got in zip(seqs,S.page_states(seqs)):
    bad=S.drive(S.boot(),seq['keys'],got['states'])
    assert not bad,(seq['name'],bad)
    print('preview PASS',seq['name'],flush=True)
result['preview_sequences']=[dict(name=s['name'],steps=len(s['keys'])) for s in seqs]
(HERE/'regressions.json').write_text(json.dumps(result,indent=2)+'\n')
