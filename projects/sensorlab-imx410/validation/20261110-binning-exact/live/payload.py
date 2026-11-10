#!/usr/bin/env python3
"""Print the current SensorLab selection's QR payload and fields.  python3 -B payload.py BLOCK"""
import sys, json, pathlib
HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parents[4]
sys.path[:0] = [str(ROOT / 'fpSup/fp_usb_shell'), str(ROOT / 'projects/sensorlab-imx410/qs')]
from callfn import call; import putfile as pf; import test_slqs as T
INFO = json.load(open(next((HERE / 'out-product').glob('build-*.json'))))
SQ = int(sys.argv[1], 16) + INFO['sq_test_off']
r = call(SQ, r0=13, r1=0, r2=0); a = r[1] if isinstance(r, tuple) else r
s = bytes(b for w in pf.mem_get(a, 16) for b in w.to_bytes(4, 'little')).split(b'\0')[0].decode()
d, ok = T.qr_unpack(s)
print(s); print(ok, d)
