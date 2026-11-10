#!/usr/bin/env python3
"""This run's guarded standby-only driver. Root is the sole USB owner."""
import argparse, json, pathlib, re, shutil, subprocess, sys, time

OUT = pathlib.Path(__file__).resolve().parent
SL = OUT.parents[2]
sys.path.insert(0, str(SL / 'tools/live'))
import run_checklist as C

p = argparse.ArgumentParser()
p.add_argument('act', choices=['read', 'keys', 'sq', 'shot', 'pair', 'resume'])
p.add_argument('args', nargs='*')
p.add_argument('--tag', required=True)
p.add_argument('--before', action='store_true')
p.add_argument('--restored', action='store_true')
p.add_argument('--at', default='{}')
a = p.parse_args()
version = '0.7.2test' if a.before or a.restored else '0.7.3test'
log = OUT / ('backup/LOAD.LOG' if a.before else 'LOAD-restored.LOG' if a.restored else 'LOAD-current.LOG')
build = SL / 'qs/out/build-0.7.2test.json' if a.before or a.restored else OUT / 'build/build-0.7.3test.json'
cam = C.Camera()
if cam.recording():
    raise SystemExit('Not confirmed idle: STOP')
r = C.Runner(cam, OUT, version, build)
text = log.read_bytes().decode('latin1')
hits = re.findall(r'0A ([0-9A-F]{8}) ([0-9A-F]{8}) SensorLab-IMX410_v(\S+?)\.BIN', text)
assert len(hits) == 1 and hits[0][2] == version, hits
r.block = int(hits[0][0], 16)
q = re.findall(r'0A ([0-9A-F]{8}) [0-9A-F]{8} QSContainer_v(\S+?)\.BIN', text)
assert len(q) == 1, q
r.qsc = C.qsc_layout(int(q[0][0], 16), q[0][1])
event = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'tag': a.tag, 'act': a.act}
def capture(n, tag):
    target = OUT/'shots'/f'{tag}-SS{n:04d}.jpg'
    transcript = []
    # Same numbered capture/getfile protocol as ui_shot.sh, but do not keep
    # fetching after an absent file or failed transfer; check pong each time.
    for key in ('CAPTUREON','CAPTUREOFF'):
        r.usb('screenshot '+key)
        rc, msg = cam.sh('key',key)
        transcript.append(key+': '+msg)
        r.alive()
        assert rc==0,(key,msg)
    cam.sleep(1.5)
    remote = f'\\DCIM\\100SIGMA\\SS__{n:04d}.JPG'
    for count, dst in ((600000, OUT/'probe.jpg'), (None, target)):
        if count is None:
            m=re.search(r'file length is (\d+)',transcript[-1])
            assert m,'No exact screenshot length; STOP without another capture'
            count=int(m[1]);assert 0<count<600000,count
        r.usb(f'getfile screenshot {n} {count}')
        try:
            s=subprocess.run([sys.executable,'-B',str(C.SH/'getfile.py'),remote,str(dst),'--size',str(count)],
                             cwd=C.SH,capture_output=True,text=True,timeout=45)
        except subprocess.TimeoutExpired:
            raise C.Freeze('Screenshot transfer host timeout: STOP, no retry')
        transcript.append(s.stdout+s.stderr)
        (OUT/f'{tag}-shot.txt').write_text('\n'.join(transcript))
        r.alive()
        if dst==target:
            assert s.returncode==0 and target.stat().st_size==count,transcript[-1]
    return str(target)

try:
    ui = r.ui()
    event['before_ui'] = ui
    for k, v in json.loads(a.at).items():
        assert ui.get(k) == v, (k, ui.get(k), v)
    if a.act == 'keys':
        event['keys'] = r.s_keys({'keys': a.args})
    elif a.act == 'sq':
        op = int(a.args[0])
        assert op in (21, 22, 30), 'Only reviewed init/stock/pause operations'
        event['value'] = r.sq(op, *(int(v) for v in a.args[1:]))
        r.alive()
    elif a.act == 'resume':
        target = int(a.args[0]); assert target in (71,72)
        assert ui['screen'].startswith('LV_') and ui['sub_open']==-1,ui
        r.s_keys({'keys':['QS']});u=r.ui();event['reopened_ui']=u
        assert u['screen']=='QS_CINE' and u['sub_open']==-1,u
        seek={54:[],58:['RIGHT'],55:['LEFT'],56:['LEFT:2']}
        assert u['qs_focus'] in seek,u
        r.s_keys({'keys':seek[u['qs_focus']]});u=r.ui()
        assert u['qs_focus']==54 and u['sub_open']==-1,u
        r.s_keys({'keys':['AEL']});u=r.ui()
        assert u['qs_focus']==70 and u['sub_open']==0,u
        r.s_keys({'keys':['RIGHT:'+str(target-70)]});u=r.ui()
        assert u['qs_focus']==target and u['sub_open']==0,u
    elif a.act == 'shot':
        assert ui['screen'].startswith(('LV_', 'QS_')), ui
        n = int(a.args[0])
        event['shot'] = capture(n, a.tag)
    elif a.act == 'pair':
        assert ui['screen'] == 'QS_CINE' and ui['sub_open'] == 0 and ui['qs_focus'] in (71,72), ui
        n = int(a.args[0])
        event['qs_shot'] = capture(n, a.tag+'-qs')
        u = r.ui(); event['after_qs_capture_ui'] = u
        assert u['screen'] == 'QS_CINE' and u['sub_open'] == 0 and u['qs_focus'] == ui['qs_focus'],u
        r.s_keys({'keys':['AEL']});u = r.ui();event['main_ui'] = u
        assert u['screen'] == 'QS_CINE' and u['sub_open'] == -1 and u['qs_focus'] == 54,u
        r.s_keys({'keys':['QS']});u=r.ui();event['closed_ui']=u
        assert u['screen'].startswith('LV_') and u['sub_open']==-1,u
        cam.sleep(8)
        event['lv_shot'] = capture(n+1,a.tag+'-lv')
    event['ui'] = r.ui()
    event['selection_words'] = cam.mem(r.block+r.build['state_off']+16, 63)
    event['selection'] = dict(zip(('dcw','dch','dclock','reslock','daw','dah','raw','rah','rat','resk','custom','cw','ch','nmem'),event['selection_words']))
    for op in (17,18):
        ptr = r.sq(op)
        event[str(op)] = dict(zip(C.STRUCTS[op],cam.mem(ptr,len(C.STRUCTS[op]))))
    r.alive()
except Exception as e:
    event['error'] = str(e)
    with (OUT/'standby.jsonl').open('a') as f: f.write(json.dumps(event)+'\n')
    raise
with (OUT/'standby.jsonl').open('a') as f: f.write(json.dumps(event)+'\n')
print(json.dumps(event), flush=True)
