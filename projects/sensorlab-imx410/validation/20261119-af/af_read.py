#!/usr/bin/env python3
"""Read-only: the AF grid / ROI registers and the live-view canvas words, for one standby state.
    python3 -B af_read.py <tag>      -> <tag>.json beside this file.   Only `mem get` and `imager mode_now`."""
import json, pathlib, re, subprocess, sys
F = '/Users/dido/Developer.localized/SIGMAfp_re/fpSup/fp_usb_shell/host/fpsh'
def sh(*a):
    return subprocess.run([F, *a], capture_output=True, text=True, timeout=20).stdout
def words(a, n):
    out = sh('mem', 'get', f'0x{a:08X},,0x{n*4:X}')
    got = {int(m[0], 16): int(m[1], 16) for m in re.findall(r'A:0x([0-9a-fA-F]+), D:0x([0-9a-fA-F]+)', out)}
    if len(got) != n: raise SystemExit(f'short read at {a:#x}: {out!r}')
    return [got[a + 4*i] for i in range(n)]
assert 'pong' in sh('ping'); assert '-> 0' in sh('status', 'get', 'is_recording')
r = {'mode_now': sh('imager', 'mode_now'),
     'mode_id': words(0xC343B58C, 1)[0], 'c31d8a04': words(0xC31D8A04, 1)[0],
     'grid_reg_10_18': words(0x30050010, 3), 'grid_copy': words(0xC37CF974, 4),
     'roi_enable': words(0x30050500, 1)[0], 'roi_540_708': words(0x30050540, (0x708 - 0x540)//4 + 1)}
cv = words(0xC375D840 + 8, 1)[0]; r['canvas_ptr'] = cv
r['canvas'] = words(cv, 0x180//4) if 0xC0000000 <= cv < 0xD0000000 else None
p = pathlib.Path(__file__).with_name(sys.argv[1] + '.json'); p.write_text(json.dumps(r, indent=1))
print(r['mode_now'].split('\n')[2] if r['mode_now'].count('\n') > 2 else r['mode_now'])
print('mode id', r['mode_id'], ' c31d8a04', hex(r['c31d8a04']))
print('grid reg', [hex(x) for x in r['grid_reg_10_18']], 'copy', r['grid_copy'])
print('roi enable', hex(r['roi_enable']))
for i in range(0, len(r['roi_540_708']), 8): print(f'  {0x540+i*4:03x}', ' '.join(f'{x:08x}' for x in r['roi_540_708'][i:i+8]))
if r['canvas']:
    c = r['canvas'][0x5C//4:]          # ap.c H_CANVAS: the canvas words start at holder + 0x5C
    print('pid', r['canvas'][0])
    for off in (0, 4, 0xC, 0x10, 0x20, 0x24, 0x28, 0x2C, 0x30, 0x58, 0x5C, 0x60, 0x64, 0x80, 0x84, 0xA0, 0xA4, 0xA8, 0xAC, 0xC4, 0xD0, 0xD4, 0xDC, 0xE4, 0xF4, 0xF8):
        print(f'  c+{off:02x} = {c[off//4]:#x} ({c[off//4]})')
