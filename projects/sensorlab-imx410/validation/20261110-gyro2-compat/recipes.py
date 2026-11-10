#!/usr/bin/env python3
"""Offline: what Gyro2 (v0.2.1, build 6) would record for Sensor Lab recipes, vs Sensor Lab's own numbers.

Gyro2 mode_info (projects/gyro2-sup/src/gyr2.S): F_TIMING row +4 hmax (u16); F_GEOM row +4 width, +8 lines,
+0x44 'bin_h', +0x48 'bin_v'.  Under Sensor Lab both accessors land on Sensor Lab's own TIM / META rows (the hooked
index lookups C0320BA0 / C0320B38), which are smc.create(plan) -- core.c is bit-identical (core/test_core.py).
The plugin (tools/gyroflow-plugins/common/src/fsg2.rs) then: readout = hmax*lines/72 MHz;
crop = (min(w*bin_h,6000), min(lines*bin_v,4000)); focal_px = frame_w*mm/(35.9*crop_w/6000); fps = DNG FrameRate.
    python3 -B recipes.py
"""
import pathlib, struct, sys
ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'projects/isp-lab/host'), str(ROOT / 'projects/imx410-lab'), str(ROOT / 'projects/imx410-lab/offline')]
import quality as Q, smc, readout_cfg as RCF

CLK = 72e6
# (label, DC cw x ch, RES ow x oh incl. the 16x10 margin, wanted quality prefix)
RECIPES = [
    ('UHD 1x1 12b (3856x2170)',               3856, 2170, 3856, 2170, ('1x1', '12')),
    ('OG 6048x4040 -> 3024x2020, 2x2 12b',    6048, 4040, 3024, 2020, ('2x2', '12')),
    ('2K 3x2 merge (6048x3402 -> 2016x1134)', 6048, 3402, 2016, 1134, ('3x2', '12')),
    ('2K 3x3 merge (6048x3402 -> 2016x1134)', 6048, 3402, 2016, 1134, ('3x3', '12')),
    ('2K 1x3 V3 (6048x3402 -> 2032x1090)',    6048, 3402, 2032, 1090, ('1x3', '12')),
    ('6048x4040 1:1 14b',                     6048, 4040, 6048, 4040, ('1x1', '14')),
    ('A001_273 class: 3x6 fast (6048x4040 -> 1008x672)', 6048, 4040, 1008, 672, ('3x6', '11')),
]

def u16(b, o): return struct.unpack_from('<H', b, o)[0]

def one(label, cw, ch, ow, oh, want):
    try:
        cs = Q.qualities(cw, ch, ow, oh, cap=None, tol=0.02, vmargin_floor=Q.VMARGIN)
    except Exception as ex:
        print(f'{label}: {ex!r}'); return
    sel = [c for c in cs if Q.quality_of(c)[0] == want[0] and (want[1] is None or Q.quality_of(c)[1] == want[1])
           and c['hbin'] == 1 and c['vbin'] == 1] or [c for c in cs if Q.quality_of(c)[0] == want[0]]
    if not sel:
        print(f'{label}: no such quality among {[Q.quality_of(c) for c in cs]}'); return
    c = sel[0]
    p, spec = Q.settings(c)
    a, rows, _ = smc.create(p)
    tim, meta = rows['TIM'], rows['META']
    hmax, tail, vmax = u16(tim, 4), u16(tim, 6), u16(tim, 8)
    w, lines, b44, b48, b4c, b50 = (struct.unpack_from('<I', meta, o)[0] & 0xFFFF for o in (4, 8, 0x44, 0x48, 0x4C, 0x50))
    r = RCF.BY_KEY[p['key']]
    g_ro = hmax * lines / CLK * 1e6
    g_cw, g_ch = min(w * max(b44, 1), 6000), min(lines * max(b48, 1), 4000)
    sl_rs = p['rolling_ms'] * 1000
    zh, zv = c['zoom']
    rec_w, rec_h = c['rec']
    img_rows = rec_h * zv / 1024            # readout-grid rows the record covers
    img_ro = hmax * img_rows / CLK * 1e6
    true_cw = rec_w * zh / 1024 * r['mh']   # sensor columns the record covers
    true_ch = img_rows * r['mv']
    fps = CLK / (hmax * vmax)
    fps_g1 = CLK / (hmax * (vmax - 1) + tail)
    print(f'== {label}: quality {Q.quality_of(c)} readout {p["id"]}')
    print(f'   TIM hmax {hmax} tail {tail} vmax {vmax} | META w {w} h {lines} +44 {b44} +48 {b48} +4C {b4c} +50 {b50} '
          f'(mh {r["mh"]} mv {r["mv"]}) | receiver_lines {p["receiver_lines"]} (over {r["over"]}, y_skip {p["y_skip"]})')
    print(f'   RS   Gyro2 {g_ro:8.1f} us | Sensor Lab rs {sl_rs:8.1f} us ({100*(g_ro/sl_rs-1):+.2f} %) | record rows {img_ro:8.1f} us '
          f'({100*(g_ro/img_ro-1):+.2f} %)')
    print(f'   fps  sensor {fps:.4f} | Gyro1 formula {fps_g1:.4f} | rec {rec_w}x{rec_h} zoom {zh}/{zv}')
    print(f'   crop Gyro2 {g_cw}x{g_ch} | record covers {true_cw:.0f}x{true_ch:.0f} sensor px '
          f'(w {100*(g_cw/true_cw-1):+.2f} %, h {100*(g_ch/true_ch-1):+.2f} %)')

if __name__ == '__main__':
    for rcp in RECIPES:
        one(*rcp)
