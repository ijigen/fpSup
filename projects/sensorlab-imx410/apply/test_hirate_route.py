"""Native CRCT selection for the user's 320x196-visible S16 high-rate case.

This checks a proposed record-tap preview policy, not DMA timing or a physical
freeze. The reference is the native selector and the accepted r10/240p route.
"""
import argparse
import ctypes
import json
import struct
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import test_apply as T

SOURCE = None
EVIDENCE = []


def native_route(cam, words):
    inp, out = T.WORK + 0xC000, T.WORK + 0xC100
    cam.mu.mem_write(inp, bytes(0x38)); cam.mu.mem_write(out, bytes(0x4C))
    # Native C031D988 caller defaults and the inputs it extracts from canvas.
    for o, v in ((4, 1), (8, 1), (12, 1), (16, 1), (24, 1), (28, 2),
                 (36, 1), (40, 1), (44, 1), (48, 1), (52, 1024), (56, 1024), (60, 1024), (64, 1024)):
        cam.put(out + o, v)
    c = lambda off: words[off // 4]
    for o, v in ((0,c(0)), (4,c(4)), (8,max(1024,c(0x64))), (12,max(1024,c(0xD4))),
                 (16,(1,3,5)[c(0x5C)]), (20,(1,3,5)[c(0xC8)]), (24,0),
                 (28,c(0xC)), (32,c(0x10)), (36,max(1024,c(0x60))), (40,max(1024,c(0xD0))),
                 (44,(1,3,5)[c(0x58)]), (48,(1,3,5)[c(0xC4)])):
        cam.put(inp + o, v)
    # This pure native selector has no external calls. Restore its bytes in
    # the emulator only; these cases have no CRCT bin correction to apply.
    cam.mu.mem_write(0xC0325228, T.image()[0x325228:0x3255B0])
    def guard(mu, a, size, data):
        if a != T.DONE and not 0xC0325228 <= a < 0xC03255B0:
            raise AssertionError(f'unmodeled selector instruction {a:08x}')
    hook = cam.mu.hook_add(T.UC_HOOK_CODE, guard)
    try:
        cam.call(0xC0325228, 0xC343B588, inp, out)
    finally:
        cam.mu.hook_del(hook)
    b = bytes(cam.mu.mem_read(out, 0x4C))
    return dict(enabled=list(b[:3]), mux=list(struct.unpack_from('<2I', b, 4)),
                record=struct.unpack_from('<I', b, 0x48)[0],
                zoom=list(struct.unpack_from('<2I', b, 0x34)))


class HighRateRoute(unittest.TestCase):
    def test_record_tap_preference_keeps_source_and_visible_bounds(self):
        cases = ((4202,1200,2048,1024,336,206,5),  # width source >2100: E3
                 (2048,1711,2048,1024,336,206,5),  # height source >1710: E3
                 (4192,1240,2048,1024,2096,1240,5),# C would newly crop >2000 visible: E3
                 (704,206,2145,1024,336,206,2))    # user case fits fully: C
        with tempfile.TemporaryDirectory(prefix='sl-preview-bounds-') as tmp:
            lib=T.BA.host(SOURCE or T.HERE, out_dir=tmp)
            lib.core_isp_plan.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
            for W,H,zh,zv,rw,rh,path in cases:
                with self.subTest(window=(W,H),record=(rw,rh)):
                    spec=(ctypes.c_int32*14)(W,H,zh,zv,1,1,1,1,12,1,1,rw,rh,1)
                    out=ctypes.create_string_buffer(512)
                    self.assertEqual(lib.core_isp_plan(spec,out),0)
                    self.assertEqual(struct.unpack_from('<i',out.raw,20)[0],path)

    # The reported case was S16 2096x1240 -> 336x206; since 0.0.5test that 3x6 recipe has no vertical margin and is not
    # offered, so the same 3x6 readout (full height: the same rates) is taken at HD 6048x3402 -> 1008x566.
    def case(self, ad, fps, raw=(1008,566), dc=(6048,3402)):
        c = T.Cam(SOURCE)
        self.assertEqual(c.init(), T.AP_OK)
        sel, _, _, rows, spec = T.recipe(*dc,*raw,'3x6',ad,fps=Fraction(fps))
        self.assertEqual(c.apply(sel), T.AP_OK)
        pid = c.status()['pid']; w = c.canvas(pid)
        route = native_route(c, w)
        EVIDENCE.append(dict(ad=ad, requested_fps=str(fps), actual_fps=T.CLK/(sel['hm']*sel['vmax']),
                             raw=list(raw), visible=[w[9],w[11]], route=route,
                             preview=[w[i//4] for i in (0xC,0x10,0x20,0x28,0x60,0xD0)]))
        return c, w, route, spec

    def test_reported_3x6_recipes_use_the_record_tap_above_stock_rates(self):
        for ad in (11,12):
            for fps in (144,200,209):
                with self.subTest(ad=ad,fps=fps):
                    _, w, r, spec = self.case(ad,fps)
                    self.assertEqual((r['enabled'],r['mux'],r['record']),([0,1,0],[1,4],0))
                    self.assertEqual(r['zoom'],list(spec.zoom))
                    self.assertEqual([w[i//4] for i in (0xC,0x10,0x20,0x28)],[1008,556,992,546])   # 3x6 vertical 1:1: the shorter record

    def test_stock_rate_preview_policy_is_unchanged(self):
        for fps in (25,100,Fraction(120000,1001)):
            _,w,r,spec=self.case(12,fps)
            ref=T.F.row(spec,T.profile_rows()[171])
            for off in (0xC,0x10,0x20,0x28,0x60,0xD0):self.assertEqual(w[off//4],ref[off//4])
            self.assertEqual((r['enabled'],r['mux'],r['record']),([0,0,1],[1,3],1))

    def test_high_to_low_reselect_restores_independent_preview(self):
        c,_,_,_=self.case(12,200)
        sel=T.recipe(6048,3402,1008,566,'3x6',12,fps=Fraction(25))[0]
        self.assertEqual(c.apply(sel),T.AP_OK)
        r=native_route(c,c.canvas(c.status()['pid']))
        self.assertEqual((r['enabled'],r['mux'],r['record']),([0,0,1],[1,3],1))


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path);p.add_argument('--report',type=Path)
    args=p.parse_args();SOURCE=args.source
    r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(HighRateRoute))
    if args.report:args.report.write_text(json.dumps(dict(passed=r.wasSuccessful(),tests=r.testsRun,
        errors=len(r.errors),failures=len(r.failures),evidence=EVIDENCE,hardware_verified=False),indent=2)+'\n')
    raise SystemExit(not r.wasSuccessful())
