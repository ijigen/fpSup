"""Prior v0.7.17 source must compile and fail the real native present regression, not a syntax/model error."""
from pathlib import Path
import sys,tempfile,unittest,io,json
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
sys.path.insert(0,str(ROOT/'projects/sensorlab-imx410/qs'))
import test_slqs as S
import test_qr_present as N
with tempfile.TemporaryDirectory(prefix='sl-qr-present-negative-') as t:
 p=Path(t)/'slqs.c';p.write_text((HERE/'source-before/slqs.c').read_text())
 data,info=S.BS.build(src=p);S._built['b']=(data,info)
 stream=io.StringIO();r=unittest.TextTestRunner(stream=stream,verbosity=2).run(N.Present('test_native_update_only_does_not_present_stale_qs'))
 assert len(r.failures)==1 and not r.errors,stream.getvalue()
 row=dict(variant='v0.7.17 unconditional QR present',compiled=True,caught=True,assertion=r.failures[0][1].splitlines()[-1])
 print(json.dumps(row),flush=True)
 (HERE/'negative-tests.json').write_text(json.dumps(row,indent=2)+'\n')
