#!/usr/bin/env python3
"""Set a SensorLab selection from QR fields over USB (sq_test 41/43/19).  python3 -B setrecipe.py BLOCK base_payload key=v ..."""
import sys, json, pathlib, struct
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[4]
sys.path[:0] = [str(ROOT / 'fpSup/fp_usb_shell'), str(ROOT / 'projects/sensorlab-imx410/qs')]
from callfn import call; import putfile as pf; import test_slqs as T
INFO = json.load(open(next((HERE / 'out-purple-live').glob('build-*.json'))))
BLOCK = int(sys.argv[1], 16); SQ = BLOCK + INFO['sq_test_off']
def op(n, a=0, b=0):
    r = call(SQ, r0=n, r1=a, r2=b); return r[1] if isinstance(r, tuple) else r
d, ok = T.qr_unpack(sys.argv[2]); assert ok
for kv in sys.argv[3:]:
    k, v = kv.split('='); d[k] = int(v)
names = [n for n, _w in T.QR_FIELDS]
buf = pf.mem_caps()['pool'] + 0x10000 + 0x8000
def put(vals):
    for i, v in enumerate(vals): pf.mem_set(buf + 4 * i, v)
    assert pf.mem_get(buf, len(vals)) == list(vals)
put([d[n] for n in names])
r = op(41, buf, 2)                                  # force the inputs
op(43, buf)                                         # the fields the selection now gives
got = dict(zip(names, pf.mem_get(buf, len(names))))
put([got[n] for n in names])
chk = op(41, buf, 0)                                # exact check
print('fields', {k: got[k] for k in ('dcw','dch','rw','rh','fps','vmax','hmax','ad','mh','mv','key','visw','vish','rs','fmt')})
print('check', chk, '(1 = exact)')
if chk != 1: raise SystemExit('not a valid recipe')
print('push rc', op(19))
