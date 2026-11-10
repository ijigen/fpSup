#!/usr/bin/env python3
"""Offline reported crop bands through native YUV/RGB constructors and dispatch."""
import hashlib,json,sys,time
from fractions import Fraction
from pathlib import Path
root=Path('/Users/dido/Developer.localized/SIGMAfp_re')
sys.path.insert(0,str(root/'projects/sensorlab-imx410/apply'))
import test_apply as T
import test_lv_fit as L
import test_ui_layers as U
import test_lv_branches as B
out=Path(sys.argv[1]);began=time.time()
files=[root/'projects/sensorlab-imx410'/name for name in ('apply/ap.c','apply/ap_calc.c','apply/ap.h','core/core.c','core/core.h','core/core_data.h','qs/slqs.c','qs/build_slqs.py')]
def fingerprints():return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
before=fingerprints()
current,native=B.NativeBranches(0),U.Layers(False)
stock={pf:native.frame('rgb',(1024,682),pf)['rectangle'] for pf in (0,1)}
crops=sorted({(w,4040) for w in range(5088,6049,16)}|{(6048,h) for h in range(3520,4041,2)})
rows=[]
for label,fps in [('30.018p',Fraction(30018,1000)),('19.026p',Fraction(72000000,3784294))]:
    for dw,dh in crops:
        rw,rh=(dw//3)&~15,(dh//3)&~1
        sel=T.recipe(dw,dh,rw,rh,'3x2',11,fps=fps)[0]
        pair=current.select(sel)
        states=[]
        expected=L.continuous_rectangle(pair)
        for mode,flag in ((0,0),(1,0),(2,0),(2,1),(3,0)):
            current.mode_state,current.flag=mode,flag
            yuv=current.frame('yuv',(rw,rh))
            assert yuv['rectangle'][2:]==expected,(sel,pair,flag,yuv)
            assert (0xC0307680 if mode==3 or flag else 0xC0307408) in current.seen
            rgb={pf:current.frame('rgb',(1024,682),pf)['rectangle'] for pf in (0,1)}
            assert rgb==stock,(sel,pair,flag,rgb,stock)
            states.append(dict(state_1f8=mode,state_23c=flag,yuv_rectangle=yuv['rectangle'],rgb_rectangles=rgb))
        rows.append(dict(dc=[dw,dh],raster=[rw,rh],rate_fixture=label,hmax=sel['hm'],vmax=sel['vmax'],aspect=pair,states=states))
    print(label+': '+str(len(crops))+' crops, YUV custom and both RGB formats native PASS',flush=True)
assert fingerprints()==before
result=dict(result='PASS',selections=len(rows),distinct_crops=len(crops),native_fit_cases=len(rows)*15,
            elapsed_seconds=round(time.time()-began,3),source_fingerprints=before,
            native_stock_rgb=stock,cases=rows,
            limitations=['Declared 2K 11-bit 3x2 rate/RES fixtures; current user recipe unknown.',
            'Starts at real apply API and native constructors; no actual menu event or GUI drawing.',
            'Allocator, display dimensions and state objects are fixtures; W v2 predicates and kind getters run real ROM.',
            'No queue, DMA, scanout, camera I/O or physical LCD executes.'])
out.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ('result','selections','distinct_crops','native_fit_cases','elapsed_seconds')}))
