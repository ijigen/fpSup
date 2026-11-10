import sys,json,hashlib
from pathlib import Path
ROOT=Path('/Users/dido/Developer.localized/SIGMAfp_re')
sys.path.insert(0,str(ROOT/'projects/sensorlab-imx410/apply'))
import test_ui_layers as U
import test_lv_outer as O
import test_lv_fit as L
import test_apply as T
from unicorn import arm_const as R

class NativeBranches(U.Layers):
    def __init__(self,flag):
        self.flag=flag
        self.seen=[]
        super().__init__()
        for lo,hi in ((0xC0307280,0xC03077C0),(0xC02E9F78,0xC02EA014)):
            self.cam.mu.ctl_remove_cache(lo,hi)
    def _code(self,mu,a,size,data):
        if a==0xC0307810:
            self.cam.put(O.STATE+0x1F8,2)
            self.cam.put(O.STATE+0x23C,self.flag)
            self.cam.put(O.ROOT+0x800+0x44,1)
        if a in (0xC0021C00,0xC0021C40):
            self.fixture_calls.append('camera state: private zero-filled fixture +44=1')
            return self.cam.ret(O.ROOT+0x800)
        if 0xC0307280<=a and a+size<=0xC03077C0 or 0xC02E9F78<=a and a+size<=0xC02EA014:
            self.seen.append(a)
            return
        return super()._code(mu,a,size,data)

out=[]
for flag in (0,1):
    c=NativeBranches(flag)
    r=c.frame('yuv',(2016,1346))
    r.update(state_1f8=2,state_23c=flag,camera_44=1,expected=L.continuous_rectangle((8,5)),
             native_predicates_reached=[f'{a:08X}' for a in (0xC0307280,0xC0307408,0xC0307520,0xC0307680) if a in c.seen])
    r['matches_custom_aspect']=tuple(r['rectangle'][2:])==tuple(r['expected'])
    out.append(r)
report=dict(cases=out,firmware_sha256=hashlib.sha256(T.image()).hexdigest(),
            limitations='Offline only. Real ROM branch predicates and metadata-kind getters; private logical state fixtures and physical display aspect enum 2. No camera state was read, so neither branch is established as the user runtime branch.')
Path(__file__).with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
for r in out: print(json.dumps({k:r[k] for k in ('state_23c','rectangle','expected','matches_custom_aspect','native_predicates_reached')}))
