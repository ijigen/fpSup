#!/usr/bin/env python3
"""Read-only: wait (up to N s) for the AF ROI enable word to become non-zero (a half-press by hand), then dump the
ROI windows, the grid, the mode words and the live canvas.   python3 -B af_catch.py <tag> [seconds]"""
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
t0 = time.time(); caught = []
while time.time() - t0 < secs and len(caught) < 3:
    en = words(0x30050500, 1)[0]
    if en:
        caught.append({'t': round(time.time() - t0, 2), 'enable': en, 'roi': words(0x30050540, 115),
                       'grid': words(0x30050010, 3), 'grid_copy': words(0xC37CF974, 4),
                       'mode': words(0xC343B58C, 2), 'c31d8a04': words(0xC31D8A04, 1)[0]})
        time.sleep(0.5)
cv = words(0xC375D848, 1)[0]
r = {'caught': caught, 'canvas_ptr': cv, 'canvas': words(cv, 0x60), 'mode_now': sh('imager', 'mode_now')}
pathlib.Path(__file__).with_name(tag + '.catch.json').write_text(json.dumps(r, indent=1))
print('caught', len(caught), 'pid', r['canvas'][0], 'visible', r['canvas'][(0x5C+0x20)//4], r['canvas'][(0x5C+0x28)//4])
for c in caught:
    print(' t', c['t'], 'enable', hex(c['enable']), 'grid', [hex(x) for x in c['grid']], 'mode', c['mode'])
    nz = [(0x540 + 4*i, v) for i, v in enumerate(c['roi']) if v]
    print('  ', ' '.join(f'{a:03x}:{v:08x}' for a, v in nz[:40]))
