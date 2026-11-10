"""Exact AutoRun/Loader/QS/SensorLab integration. File, RTOS and GUI services
are the existing explicit test models. No physical camera, LCD or SD access.
"""
from pathlib import Path
import hashlib,json,struct,sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
sys.path[:0]=[str(ROOT/'projects/sensorlab-imx410/qs'),str(ROOT/'projects/qs-container')]
import test_slqs as S
import test_dc_steps as D
import test_qsct as Q
import test_boot_card_v4 as BC
CARD=HERE.parent/'20261102-card-boot-freeze/card-before'
BASE=HERE.parent/'20261102-qr-present-fix/card-settings-build'
SL='SensorLab-IMX410_v0.7.24test.BIN';QS='QSContainer_v0.3.5.BIN'
old=(HERE.parent/'20261103-pb-size-text/card-before/SensorLab-IMX410_v0.7.22test.BIN').read_bytes()
oldoff=struct.unpack_from('<I',old,64)[0];n=4*S.BS.REC_WORDS
rows=[]
for kind in ('default','card-settings'):
    folder=HERE/(kind+'-build');D.exact_build(folder,'0.7.24test')
    data,info=S.blob();off=info['rec_off']
    expected_record=old[oldoff:oldoff+n] if kind=='card-settings' else bytes(n)
    assert data[off:off+n]==expected_record
    default=(HERE/'default-build/fpSup'/SL).read_bytes()
    assert data[:off]+data[off+n:]==default[:off]+default[off+n:]
    qi=json.loads((BASE/'build-0.3.5.json').read_text());qd=(BASE/'fpSup'/QS).read_bytes()
    Q.CNAME=QS;Q._built['c']=(qd,qi)
    for ready in (False,True):
        files={'\\fpSup\\LOADER.BIN':(CARD/'fpSup/LOADER.BIN').read_bytes(),
               '\\fpSup\\'+SL:data,'\\fpSup\\'+QS:qd}
        for p in (CARD/'fpSup/UI').iterdir():files['\\fpSup\\UI\\'+p.name]=p.read_bytes()
        names=['LOADER.BIN',QS,SL]
        entries=[(name,0x20,len(files['\\fpSup\\'+name])) for name in names]+[('UI',0x10,0)]
        c=Q.Cam(files,{'\\fpSup':entries});S.ap_firmware(c,descriptor=ready)
        lines,aborted=BC.run_autorun(c,(CARD/'AutoRun.txt').read_bytes());assert not aborted
        assert all(name in Q.T.blocks(c) for name in (QS,SL))
        S.sqt(c,11,4);S.sqt(c,12,1);c.layout()  # collect restored native slots before changing layout, like S.boot
        S.TP.set_cine(c,S.SLOTS);c.layout()
        # (the Playback page frame is applied at the menu setup, which needs the UI app this model lacks:
        #  menu/test_runtime.FirstMenu.test_playback_page_frame_applied_at_the_first_menu covers it)
        expected_dc=struct.unpack_from('<2I',expected_record,8) if kind=='card-settings' else (6048,3402)
        assert (S.ap_sel(c)['dcw'],S.ap_sel(c)['dch'])==expected_dc
        S.press(c,5,1)
        for _ in range(6):S.press(c,2,0)
        S.press(c,1,0)  # HD; leave the restored ratio lock state alone
        for _ in range(7):S.press(c,4,1)
        assert int(S.tile(c,1)[1])==5040
        assert S.footer(c,S.focus_int(c,1))['items'][0][3]
        assert S.ap_sel(c)['dcw']==5040
        assert S.ap_status(c)['active']==int(ready)
        c.layout()
        saved=c.written['\\fpSup\\'+SL]
        assert struct.unpack_from('<I',saved,off+8)[0]==5040
        journal=[];objects=list(dict.fromkeys(obj for obj,_ in c.registered))
        for obj in objects:
            e=c.w(obj+8);count=0
            while c.w(e):
                addr,size=c.w(e),c.w(e+4);assert count<1024 and 0<size<=4096
                journal.append((addr,size,bytes(c.mu.mem_read(e+8,size))))
                e+=8+size;count+=1
        assert len(journal)==56,len(journal)   # v0.7.22: + the v153 PB_OwnModel site
        for obj in objects:c.call(c.w(c.w(obj)+0xc),r0=obj,r1=4)
        assert all(bytes(c.mu.mem_read(addr,size))==before for addr,size,before in journal)
        row=dict(kind=kind,descriptor_ready=ready,restored_dc=expected_dc,width=5040,
                 saved=True,journal_entries=len(journal),journal_restored=True,
                 sha256={name:hashlib.sha256(files['\\fpSup\\'+name]).hexdigest() for name in names},
                 autorun_sha256=hashlib.sha256((CARD/'AutoRun.txt').read_bytes()).hexdigest())
        rows.append(row);print(json.dumps(row),flush=True)
(HERE/'artifact-tests.json').write_text(json.dumps(dict(passed=True,cases=rows,hardware_tested=False,limitations=__doc__),indent=2)+'\n')
