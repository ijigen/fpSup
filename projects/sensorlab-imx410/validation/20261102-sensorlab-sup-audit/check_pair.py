"""Exact existing BIN compatibility check. UI/file/RTOS models are test_qsct's;
no camera, physical LCD or other companion SUP execution is claimed.
"""
from pathlib import Path
import argparse,hashlib,json,struct,sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
sys.path[:0]=[str(ROOT/'projects/sensorlab-imx410/qs'),str(ROOT/'projects/qs-container')]
import test_slqs as S
import test_qsct as Q
import test_boot_card_v4 as BC

CARD=HERE.parent/'20261102-card-boot-freeze/card-before'
COMMON=HERE.parent/'20261102-playback-raw14-fix/card-settings-build'
p=argparse.ArgumentParser();p.add_argument('--version',default='0.7.15test');p.add_argument('--folder',type=Path,default=COMMON)
p.add_argument('--expect-fallback',action='store_true');p.add_argument('--report',default='pair-results.json')
args=p.parse_args();NEW=args.folder;SL=f'SensorLab-IMX410_v{args.version}.BIN'
S.BS.VERSION=args.version  # test helper locates this exact loaded file, never a rebuilt substitute
si=json.loads((NEW/f'build-{args.version}.json').read_text())
si['functions']={'sq_test':si['sq_test_off']-si['code_off']}
S._built['b']=((NEW/'fpSup'/SL).read_bytes(),si)
rows=[]
for version,path in [('0.3.2',CARD/'fpSup/QSContainer_v0.3.2.BIN_.BIN'),
                     ('0.3.3',CARD/'fpSup/QSContainer_v0.3.3.BIN'),
                     ('0.3.4',CARD/'fpSup/QSContainer_v0.3.4.BIN'),
                     ('0.3.5',COMMON/'fpSup/QSContainer_v0.3.5.BIN')]:
    data=path.read_bytes();name=path.name
    Q.CNAME=name
    Q._built['c']=(data,{'state_off':struct.unpack_from('<I',data,56)[0]})
    files={'\\fpSup\\LOADER.BIN':(CARD/'fpSup/LOADER.BIN').read_bytes(),
           '\\fpSup\\'+name:data,'\\fpSup\\'+SL:S._built['b'][0]}
    for p in (CARD/'fpSup/UI').iterdir():files['\\fpSup\\UI\\'+p.name]=p.read_bytes()
    entries=[(n,0x20,len(files['\\fpSup\\'+n])) for n in ('LOADER.BIN',name,SL)]+[('UI',0x10,0)]
    c=Q.Cam(files,{'\\fpSup':entries});S.ap_firmware(c,descriptor=False)
    lines,aborted=BC.run_autorun(c,(CARD/'AutoRun.txt').read_bytes())
    assert not aborted
    blocks=Q.T.blocks(c);assert SL in blocks and name in blocks
    S.sqt(c,11,4);S.sqt(c,12,1)
    S.TP.set_cine(c,S.SLOTS);c.layout()
    states=[]
    for main in (1,2):
        S.press(c,5,main)
        widths=[];choices=[];small_texts=[]
        for _ in range(2):
            assert S.tile(c,3)[0]=='RATIO'
            widths.append(c.vars.get('QSC_SW4',(0,None))[1])
            choices.append(S.footer(c,S.focus_int(c,3))['cur'])
            small_texts.append(S.tile(c,3)[2].strip())
            expected='LOCK' if args.expect_fallback and version!='0.3.5' and choices[-1]==0 else ''
            assert small_texts[-1]==expected,(version,choices[-1],small_texts[-1],expected)
            S.press(c,1,3)
        assert set(choices)=={0,1},choices
        assert set(widths)==({0,120} if version=='0.3.5' else {None}),widths
        if version=='0.3.5':
            assert all(c.vars[f'QSC_SW{k}'][1]==0 for k in (1,2,3,5,6,7,8))
        S.press(c,5,3)
        if version=='0.3.5':assert all(c.vars[f'QSC_SW{k}'][1]==0 for k in range(1,9))
        states.append(dict(menu='DC' if main==1 else 'RES',footer_choices=choices,small_lock_widths=widths,small_texts=small_texts))
    rows.append(dict(qs_version=version,qs_sha256=hashlib.sha256(data).hexdigest(),sensorlab_sha256=si['sha256'],
                     exact_binaries=True,states=states,loaded=True,hardware_verified=False))
    print(json.dumps(rows[-1]),flush=True)
(HERE/args.report).write_text(json.dumps({'cases':rows,'passed':True,'limitations':__doc__},indent=2)+'\n')
