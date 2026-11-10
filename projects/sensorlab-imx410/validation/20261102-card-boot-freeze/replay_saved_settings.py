"""Read only captured files; execute exact card loader/QS/SensorLab in existing models.

The UI/file/settings services and liveview absence are declared test_slqs models.
This cannot reproduce hardware scheduling, card insertion or DMA stalls.
"""
from pathlib import Path
import hashlib
import json
import struct
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(ROOT/'projects/sensorlab-imx410/qs'),str(ROOT/'projects/qs-container')]
import test_slqs as S
import test_qsct as Q
import test_boot_card_v4 as BC

CARD = HERE/'card-before'
SL = 'SensorLab-IMX410_v0.7.12test.BIN'
QC = 'QSContainer_v0.3.4.BIN'
si = json.loads((HERE.parent/'20261102-hirate-followup/default-build/build-0.7.12test.json').read_text())
si['functions'] = {'sq_test':si['sq_test_off']-si['code_off']}
qi = json.loads((HERE.parent/'20261102-lock-position/default-build/build-0.3.4.json').read_text())

def checksum(b):
    h=2166136261
    for v in b:h=((h^v)*16777619)&0xffffffff
    return h

def variant(name):
    b=bytearray((CARD/'fpSup'/SL).read_bytes());r=si['rec_off']
    if name=='cleared':b[r:r+260]=bytes(260)
    if name=='saved_5994':
        struct.pack_into('<2I',b,r+16*4,5994,100)
        struct.pack_into('<I',b,r+256,checksum(b[r:r+256]))
    return bytes(b)

def replay(name,descriptor):
    data=variant(name);qc=(CARD/'fpSup'/QC).read_bytes()
    S._built['b']=(data,si);Q._built['c']=(qc,qi)
    files={f'\\fpSup\\{n}':(CARD/'fpSup'/n).read_bytes() for n in ('LOADER.BIN',QC)}
    files['\\fpSup\\'+SL]=data
    for p in (CARD/'fpSup/UI').iterdir():files['\\fpSup\\UI\\'+p.name]=p.read_bytes()
    ents=[(n,0x20,len(files['\\fpSup\\'+n])) for n in ('LOADER.BIN',QC,SL)]+[('UI',0x10,0)]
    c=Q.Cam(files,{'\\fpSup':ents})
    S.ap_firmware(c,descriptor=descriptor)
    ar=(CARD/'AutoRun.txt').read_bytes()
    lines,aborted=BC.run_autorun(c,ar)
    assert c.r(Q.T3.UC_ARM_REG_PC)==Q.T3.DONE
    loaded=Q.T.blocks(c);assert SL in loaded and QC in loaded,loaded
    before=S.ap_status(c)
    S.sqt(c,11,4);S.sqt(c,12,1)
    for i in range(3):c.layout()
    sel=S.ap_sel(c);status=S.ap_status(c)
    record_loaded=c.w(S.st_addr(c)+272)
    journal=c.journal()
    c.power_off()
    restored=all(bytes(c.mu.mem_read(a,n))==b for a,n,b in journal)
    assert restored
    return dict(case=name,descriptor_ready=descriptor,sha256=hashlib.sha256(data).hexdigest(),
                autorun_lines=lines,autorun_aborted=aborted,loaded=loaded,record_loaded=record_loaded,
                before_layout=before,selection=sel,after_layout=status,journal_entries=len(journal),
                journal_restored=restored,loadlog=c.loadlog())

if __name__=='__main__':
    out=[]
    for name in ('saved','cleared','saved_5994'):
        for ready in (False,True):
            print('Running',name,ready,flush=True)
            row=replay(name,ready);out.append(row)
            (HERE/'settings-replay.json').write_text(json.dumps(dict(cases=out,hardware_verified=False),indent=2)+'\n')
            print(json.dumps({k:row[k] for k in ('case','descriptor_ready','record_loaded','selection','after_layout','journal_restored')}),flush=True)
