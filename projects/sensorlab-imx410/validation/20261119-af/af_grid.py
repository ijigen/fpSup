#!/usr/bin/env python3
"""Read-only: poll the AF grid registers 0x30050010..1C and the firmware's copy for N s; print every distinct value.
    python3 -B af_grid.py <tag> [seconds]"""
import json, pathlib, re, subprocess, sys, time
F = '/Users/dido/Developer.localized/SIGMAfp_re/fpSup/fp_usb_shell/host/fpsh'
def sh(*a): return subprocess.run([F, *a], capture_output=True, text=True, timeout=20).stdout
def words(a, n):
    out = sh('mem', 'get', f'0x{a:08X},,0x{n*4:X}')
    got = {int(m[0], 16): int(m[1], 16) for m in re.findall(r'A:0x([0-9a-fA-F]+), D:0x([0-9a-fA-F]+)', out)}
    if len(got) != n: raise SystemExit(f'short read at {a:#x}: {out!r}')
    return [got[a + 4*i] for i in range(n)]
assert 'pong' in sh('ping'); assert '-> 0' in sh('status', 'get', 'is_recording')
tag, secs = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 40
t0 = time.time(); seen = []; n = 0
while time.time() - t0 < secs:
    v = words(0x30050000, 8) + words(0xC37CF974, 4); n += 1
    if not seen or seen[-1]['v'] != v: seen.append({'t': round(time.time() - t0, 2), 'v': v})
cv = words(0xC375D848, 1)[0]; c = words(cv, 0x60)
pathlib.Path(__file__).with_name(tag + '.grid.json').write_text(json.dumps({'seen': seen, 'canvas': c, 'polls': n}, indent=1))
print('polls', n, 'pid', c[0], 'raster', c[(0x5C+0xC)//4], c[(0x5C+0x10)//4], 'visible', c[(0x5C+0x20)//4], c[(0x5C+0x28)//4])
for s in seen: print(f" t {s['t']:6.2f}", ' '.join(f'{x:08x}' for x in s['v'][:8]), '| copy', s['v'][8:])
