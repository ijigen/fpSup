"""Scoped SensorLab v1 diagnostics. Never run during recording or playback."""
import pathlib, sys, json, re, fcntl, argparse, time
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / 'fpSup/fp_usb_shell'))
import putfile, callfn, ui_drive

def read_op(op, words=0):
    info = json.loads((HERE/'SL41-build.json').read_text())
    log = (HERE/'LOAD.LOG').read_text()
    match = re.search(r'^0A ([0-9A-F]+) [0-9A-F]+ '+re.escape(info['file'])+r'$',log,re.M)
    if not match: raise RuntimeError('exact current product missing from LOAD.LOG')
    base = int(match[1],16)
    ok, val = callfn.call(base+info['code_off']+info['functions']['sq_test'],r0=op,verbose=False)
    if not ok: raise RuntimeError(f'op {op} did not return')
    return dict(op=op,value=val,words=putfile.mem_get(val,words) if words else [])

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['health','diag','key','shot','where'])
    ap.add_argument('--key',choices=['MENU','OK','UP','DOWN','LEFT','RIGHT','QS','S1','DISP','AEL'])
    ap.add_argument('--tag',required=True)
    a=ap.parse_args()
    lock=open('/tmp/fp-af-fusion.lock','a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    d={}
    for cmd in ['status get is_recording','status get app_current']:
        d[cmd]=putfile.sh(cmd,retries=0)
    if 'is_recording -> 0' not in d['status get is_recording']: raise RuntimeError('not idle')
    if a.action=='health': d['mode']=putfile.sh('imager mode_now',retries=0)
    elif a.action=='diag':
        d['ops']=[read_op(op,words) for op,words in [(21,0),(17,24),(18,24),(23,30),(27,23),(28,0)]]
    elif a.action=='key':
        if not a.key: raise ValueError('key required')
        d['key']=putfile.sh('key '+a.key+'ON',retries=0,timeout_ms=5000)
        if 'ERR' in d['key']:
            (HERE/(a.tag+'.json')).write_text(json.dumps(d,indent=2))
            raise RuntimeError('uncertain key result; do not retry')
        if a.key=='S1':
            time.sleep(.8);d['release']=putfile.sh('key S1OFF',retries=0)
        time.sleep(.8)
    elif a.action=='shot': d['image']=str(ui_drive.shot(a.tag))
    elif a.action=='where': d['where']=ui_drive.where()
    (HERE/(a.tag+'.json')).write_text(json.dumps(d,indent=2))
    print(json.dumps(d,indent=2))

if __name__=='__main__': main()
