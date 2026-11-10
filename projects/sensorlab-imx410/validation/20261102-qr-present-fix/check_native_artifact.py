"""Repeat native presentation tests with exact deliverable bytes, never a rebuilt substitute."""
from pathlib import Path
import json,sys,unittest,hashlib
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
sys.path.insert(0,str(ROOT/'projects/sensorlab-imx410/qs'))
import test_slqs as S
import test_qr_present as N
rows=[]
for kind in ('default','card-settings'):
 d=HERE/(kind+'-build');info=json.loads((d/'build-0.7.18test.json').read_text())
 info['functions']={'sq_test':info['sq_test_off']-info['code_off']}
 data=(d/'fpSup/SensorLab-IMX410_v0.7.18test.BIN').read_bytes()
 S._built['b']=(data,info)
 r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(N.Present))
 assert r.wasSuccessful()
 rows.append(dict(kind=kind,sha256=hashlib.sha256(data).hexdigest(),tests=r.testsRun,passed=True))
(HERE/'native-artifact-tests.json').write_text(json.dumps(rows,indent=2)+'\n')
