"""Read verified current OSD buffers. Use only while idle/menu, never playback."""
import pathlib, sys, json, fcntl, contextlib, io
import numpy as np
from PIL import Image
HERE=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[4]/'fpSup/fp_usb_shell'))
import putfile
tag=sys.argv[1]
indices=[int(x) for x in sys.argv[2:]]
lock=open('/tmp/fp-af-fusion.lock','a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
assert 'is_recording -> 0' in putfile.sh('status get is_recording',retries=0)
out=HERE/tag;out.mkdir(exist_ok=True)
front=putfile.mem_get(0xC3824FF0,3)
(out/'front.json').write_text(json.dumps(dict(front=front)))
if not indices:
    assert front[0] in (0xC38D6DB0,0xC38D6DCC,0xC38D6DE8)
    indices=[(front[0]-0xC38D6DB0)//28]
    print('front index',indices[0],flush=True)
for i in indices:
    assert i in (0,1,2)
    desc=putfile.mem_get(0xC38D6DB0+28*i,3)
    dims=putfile.mem_get(desc[2],2)
    assert dims==[1024,682] and 0xC0000000<=desc[1]<0xE0000000
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        raw=putfile.read_bulk(desc[1],dims[0]*dims[1]*2)
    px=np.frombuffer(raw,'<u2').reshape(dims[1],dims[0]);alpha=(px>>12&15)[...,None]/15
    rgb=np.stack([(px>>8&15)*17,(px>>4&15)*17,(px&15)*17],axis=-1)
    img=(alpha*rgb+(1-alpha)*128).astype(np.uint8)
    (out/f'fb{i}.bin').write_bytes(raw);Image.fromarray(img).save(out/f'fb{i}.png')
    (out/f'fb{i}.json').write_text(json.dumps(dict(desc=desc,dims=dims)))
    print(out/f'fb{i}.png',flush=True)
