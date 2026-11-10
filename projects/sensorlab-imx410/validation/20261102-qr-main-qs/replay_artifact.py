"""Exact new BIN + captured loader/QS/UI boot, native RAW14/ring, journal restoration.

Only loader/QS/SensorLab are loaded; other card companions are excluded.
Loader/UI/settings services are the maintained Q/S models, LV is absent.
Native ring execution uses the declared allocation/XMP/lock models from
test_playback_ring; no camera, physical pool, display or decode proof.
RAW14 runs the installed BIN code with an explicit frame descriptor and
selected-player fixture copied from the unit's native tag/profile/canvas path.
It does not execute the entire frame-construction/DMA/display pipeline.
"""
from pathlib import Path
import hashlib
import json
import struct
import sys
from unicorn import UC_HOOK_CODE

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
sys.path[:0]=[str(ROOT/'projects/sensorlab-imx410/qs'),str(ROOT/'projects/qs-container'),
             str(ROOT/'projects/sensorlab-imx410/apply')]
import test_slqs as S
import test_qsct as Q
import test_boot_card_v4 as BC
import test_playback_ring as R
import test_playback_raw14 as P
import capstone

CARD=HERE.parent/'20261102-card-boot-freeze/card-before'
SL='SensorLab-IMX410_v0.7.17test.BIN'
QC='QSContainer_v0.3.5.BIN'
qi=json.loads((HERE/'default-build/build-0.3.5.json').read_text())


class Card(R.RingModel,Q.Cam):
    def __init__(self,*args,**kw):
        self.ring_enabled=False
        super().__init__(*args,**kw)

    def stub(self,a,name):
        self.by_addr[a]=name
        self.put(a,0xE12FFF1E)

    def ret(self,value):return self._ret(value)

    def _hook(self,mu,a,size,data):
        if self.ring_enabled and self.ring_service(mu,a):return
        return super()._hook(mu,a,size,data)

    def check_raw14(self,base,info):
        # Declared selected-player fixture, produced by the unit's real
        # tag/profile/canvas path. Copy only its state, never its hook code.
        ref=P.C.SelectedCam();ref.select(P.C.movie((2096,1240),14))
        assert ref.prepare()==1
        ref.profile()
        pb=ref.fn('ap_pb_info',R.T.MEM)&0xffffffff
        pboff=pb-R.T.MEM
        ins,=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_THUMB).disasm(bytes(self.mu.mem_read(P.SITE,4)),P.SITE)
        assert ins.mnemonic=='blx'
        cave=int(ins.op_str.lstrip('#'),0);veneer=self.w(cave+4);state=self.w(veneer+14*4)
        assert base+info['state_off']<=state<base+info['block_size']
        assert self.w(state+pboff)==0x42504c53
        saved=bytes(self.mu.mem_read(state+pboff,788))
        self.mu.mem_map(R.T.WORK,0x10000)
        self.mu.mem_map(R.T.OBJ,0x2000)
        self.mu.mem_write(R.T.OBJ,bytes(ref.mu.mem_read(R.T.OBJ,0x800)))
        self.mu.mem_write(state+pboff,bytes(ref.mu.mem_read(pb,788)))
        self.mu.mem_write(P.FRAME,bytes(0x510))
        self.put(P.FRAME+0x38,8);self.put(P.FRAME+0x58,2096);self.put(P.FRAME+0x60,1240)
        def guard(mu,a,size,data):
            if P.START<=a<P.END or base<=a<base+info['block_size'] or cave<=a<cave+8:return
            raise AssertionError(f'unapproved exact BIN RAW14 instruction {a:08x}')
        h=self.mu.hook_add(UC_HOOK_CODE,guard);answers=[]
        try:
            for file_id in (17,18):
                self.put(R.T.OBJ+0x88,file_id)
                for reg,value in ((R.T.UC_ARM_REG_SP,Q.T3.STACK-0x1004),(R.T.UC_ARM_REG_R4,0),
                    (R.T.UC_ARM_REG_R5,P.RAW),(R.T.UC_ARM_REG_R6,P.FRAME),(R.T.UC_ARM_REG_R7,P.FRAME+0x38)):
                    self.mu.reg_write(reg,value)
                self.mu.emu_start(P.START|1,P.END,count=100000)
                assert self.r(R.T.UC_ARM_REG_PC)==P.END
                assert self.r(R.T.UC_ARM_REG_CPSR)&0x20
                answers.append(self.w(P.RAW+0x50))
            assert answers==[1,0],answers
        finally:
            self.mu.hook_del(h);self.mu.mem_write(state+pboff,saved)
        return dict(selected_fixture=True,format_enum=answers[0],stale_owner_enum=answers[1],
                    site=f'{P.SITE:08x}',cave=f'{cave:08x}',veneer=f'{veneer:08x}',actual_bin_code=True)

    def check_ring(self,base,info):
        saved={a:(self.by_addr.get(a),bytes(self.mu.mem_read(a,4))) for a in R.SERVICES}
        self.ring_init(1000);self.ring_enabled=True
        siteword=self.w(R.SITE)
        offset=(siteword&0xFFFFFF);offset=offset-(1<<24) if offset&(1<<23) else offset
        cave=R.SITE+8+(offset<<2)
        assert self.w(cave)==0xE51FF004
        veneer=self.w(cave+4)
        assert base+info['state_off']<=veneer<base+info['block_size']
        def guard(mu,a,size,data):
            if (a in R.SERVICES or a==Q.T3.DONE or any(lo<=a<hi for lo,hi in R.NATIVE) or
                base<=a<base+info['block_size'] or cave<=a<cave+8):return
            raise AssertionError(f'unapproved exact BIN ring instruction {a:08x}')
        g=self.mu.hook_add(UC_HOOK_CODE,guard)
        try:
            self.call(R.ENTRY,r0=R.RING,r1=183808,sp=Q.T3.STACK-0x1000)
            assert self.r(Q.T3.UC_ARM_REG_PC)==Q.T3.DONE, (hex(self.r(Q.T3.UC_ARM_REG_PC)), self.w(R.RING+4),len(self.requests),self.error)
            assert self.w(R.RING+4)==300 and len(self.allocated)==300 and self.canary_ok()
            self.call(R.CLEANUP,r0=R.RING,sp=Q.T3.STACK-0x1000)
            assert self.freed==[(10,p) for p in self.allocated]+[(11,R.TABLE)]
            assert self.w(R.RING+4)==0 and self.w(R.RING+8)==0
        finally:
            self.mu.hook_del(g);self.ring_enabled=False
            for a,(name,data) in saved.items():
                self.mu.mem_write(a,data)
                if name is None:self.by_addr.pop(a,None)
                else:self.by_addr[a]=name
        return dict(site=f'{R.SITE:08x}',branch=f'{siteword:08x}',cave=f'{cave:08x}',
                    veneer=f'{veneer:08x}',buffers=len(self.allocated),canary=True,cleanup=True)


def replay(kind,ready):
    folder=HERE/(kind+'-build')
    data=(folder/'fpSup'/SL).read_bytes()
    info=json.loads((folder/'build-0.7.17test.json').read_text())
    assert hashlib.sha256(data).hexdigest()==info['sha256']
    info['functions']={'sq_test':info['sq_test_off']-info['code_off']}
    S._built['b']=(data,info);Q._built['c']=((folder/'fpSup'/QC).read_bytes(),qi)
    files={'\\fpSup\\LOADER.BIN':(CARD/'fpSup/LOADER.BIN').read_bytes(), '\\fpSup\\'+QC:(folder/'fpSup'/QC).read_bytes()}
    files['\\fpSup\\'+SL]=data
    for p in (CARD/'fpSup/UI').iterdir():files['\\fpSup\\UI\\'+p.name]=p.read_bytes()
    ents=[(n,0x20,len(files['\\fpSup\\'+n])) for n in ('LOADER.BIN',QC,SL)]+[('UI',0x10,0)]
    c=Card(files,{'\\fpSup':ents});S.ap_firmware(c,descriptor=ready)
    lines,aborted=BC.run_autorun(c,(CARD/'AutoRun.txt').read_bytes())
    assert not aborted and c.r(Q.T3.UC_ARM_REG_PC)==Q.T3.DONE
    loaded=Q.T.blocks(c);assert QC in loaded and SL in loaded
    S.sqt(c,11,4);S.sqt(c,12,1)
    for _ in range(3):c.layout()
    status=S.ap_status(c)
    assert status['active']==int(ready)
    result=c.check_ring(loaded[SL],info)
    raw14=c.check_raw14(loaded[SL],info)
    selection=S.ap_sel(c)
    # Use the same declared CINE test layout as test_slqs; backup slots differ.
    S.TP.set_cine(c,S.SLOTS);c.layout()
    for main in (1,2):
        S.press(c,5,main)
        assert S.tile(c,3)[0]=='RATIO'
        assert not any(c.vars[f'QSC_LW{k}'][1] for k in range(1,9))
        widths=[]
        for _ in range(2):
            widths.append(c.vars['QSC_SW4'][1]);S.press(c,1,3)
        assert set(widths)=={0,120}
        assert [c.vars[f'QSC_SW{k}'][1] for k in (1,2,3,5,6,7,8)]==[0]*7
        S.press(c,5,3)
        assert not any(c.vars[f'QSC_SW{k}'][1] for k in range(1,9))

    # Exact delivered QR implementation, native observer registry functions and modeled LCD buffers.
    import numpy as np
    S.sqt(c,12,0)
    lcd=S.QRScreen(c)
    c.layout()                                  # drop the earlier display-suppressed test preparation
    c.guid(S.FMT_ID)                             # QR is not focused and no AEL is pressed
    q=S.qr_info(c)
    assert (q['on'],q['reg'],q['tile'])==(1,1,5),q
    url=S.QR_URL+c.cstr(S.sqt(c,13),64)
    for _ in range(3):
        frame=lcd.cycle();x,y,n=q['x0'],q['y0'],q['side']
        square=np.where(frame[y:y+n,x:x+n]==0xF000,0,255).astype(np.uint8)
        assert S.decode_qr(np.pad(square,20,constant_values=255))==url
    c.put(0xC35A952C,1);c.guid(S.FMT_ID)
    for _ in range(3):assert (lcd.cycle()==lcd.G).all()
    c.put(0xC35A952C,0)
    # No QR in the next layout: unregister before power-off journal replay.
    S.TP.set_cine(c,[S.FMT_ID,S.DC_ID,S.RES_ID,S.FPS_ID,S.RCP_ID,19,S.MB_ID,20]);c.layout()
    assert S.qr_info(c)['reg']==0
    qr=dict(auto_main=True,focus='FORMAT',decoded_url=url,recording_restored=True,absent_detached=True)

    # AutoRun registers an outer stage2 and the inner v4 loader. Q.Cam's
    # single-loader helper selects only the first (empty) journal here.
    # Read every unique registered object's journal and run each real callback.
    objects=list(dict.fromkeys(obj for obj,phase in c.registered))
    journal=[];counts=[]
    for obj in objects:
        e=c.w(obj+8);nentries=0
        while c.w(e):
            assert nentries<1024
            a,n=c.w(e),c.w(e+4)
            assert 0<n<=4096 and not n%4
            journal.append((a,n,bytes(c.mu.mem_read(e+8,n))))
            e+=8+n;nentries+=1
        counts.append(dict(object=f'{obj:08x}',entries=nentries))
    assert len(journal)>=42
    assert (R.SITE,4,struct.pack('<I',R.T.iw(R.SITE))) in journal
    assert (P.SITE,4,struct.pack('<I',R.T.iw(P.SITE))) in journal
    for obj in objects:
        c.call(c.w(c.w(obj)+0xC),r0=obj,r1=4)
        assert c.r(Q.T3.UC_ARM_REG_PC)==Q.T3.DONE
    assert all(bytes(c.mu.mem_read(a,n))==b for a,n,b in journal)
    return dict(kind=kind,descriptor_ready=ready,sha256=info['sha256'],autorun_lines=lines,
                status=status,selection=selection,ratio_ui_verified=True,qr=qr,raw14=raw14,ring=result,journal_entries=len(journal),journal_objects=counts,
                journal_restored=True,loadlog=c.loadlog())


if __name__=='__main__':
    rows=[]
    for kind in ('default','card-settings'):
        for ready in (False,True):
            row=replay(kind,ready);rows.append(row);print(json.dumps(row),flush=True)
    (HERE/'artifact-tests.json').write_text(json.dumps(dict(cases=rows,limitations=__doc__,hardware_tested=False),indent=2)+'\n')
