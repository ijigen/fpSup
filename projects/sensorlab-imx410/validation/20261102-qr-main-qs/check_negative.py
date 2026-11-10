"""Bounded negative controls: each variant builds, then must fail a meaningful pixel/display assertion."""
from pathlib import Path
import sys,tempfile,unittest,io,json
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
sys.path.insert(0,str(ROOT/'projects/sensorlab-imx410/qs'))
import test_slqs as S
source=S.BS.SOURCE.read_text()
owner='q->on && W(UIC_DRAW + 8u) == 0xC37859E0u && W(0xC37859E0u) == 0xC0D1D6C4u &&\n        q->qs && W(q->qs + 0xBCu) < 70u && !busy()'
variants=[('prior AEL-only implementation',(HERE/'source-before/slqs.c').read_text(),'test_native_owner_and_absent_tile_prevent_paint'),
 ('missing native owner gate',source.replace(owner,'q->on && !busy()'),'test_native_owner_and_absent_tile_prevent_paint'),
 ('compare every buffer against newest code',source.replace('const u8 *old = dirty >= 0 ? q->prior[dirty] : q->live;','const u8 *old = q->live;'),'test_updates_across_rotating_buffers_then_restores_submenu')]
assert source.count(owner)==1
rows=[]
for name,variant,test in variants:
 assert variant!=source
 with tempfile.TemporaryDirectory(prefix='sl-qr-negative-') as t:
  p=Path(t)/'slqs.c';p.write_text(variant)
  data,info=S.BS.build(src=p)                    # compile success is required; not itself a negative-test pass
  S._built['b']=(data,info)
  stream=io.StringIO();r=unittest.TextTestRunner(stream=stream,verbosity=2).run(S.QR(test))
  assert len(r.failures)==1 and not r.errors,(name,stream.getvalue())
  row=dict(variant=name,test=test,compiled=True,caught=True,assertion=r.failures[0][1].splitlines()[-1]);rows.append(row)
  print(json.dumps(row),flush=True)
(HERE/'negative-tests.json').write_text(json.dumps(rows,indent=2)+'\n')
