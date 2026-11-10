#!/usr/bin/env python3
"""Playback FPUI block: stock-frame invariance, budgets, guards, real ARM applier.

The ARM test runs fpui_stock.c and only stubs allocation/cache publication.
Record parsing and animation evaluation are declared Python models; this does
not emulate GUI rendering or establish camera playback stability.
"""
import functools
import pathlib
import shutil
import struct
import subprocess
import tempfile
import unittest

import pb_page as P
import test_apply as T


def clips(page):
    return {P.B.u32(r.to_bytes(), 20): P.A.parse_clip(P.A.Record(r.offset, r.to_bytes()), P.source()[0].text)
            for r in P.B.N.split(page) if r.tag == 0x1000A and P.B.u32(r.to_bytes(), 20) in P.OWNERS}


@functools.lru_cache(None)
def native_code():
    with tempfile.TemporaryDirectory(prefix='slpb-page-') as d:
        d = pathlib.Path(d)
        src = d / 'pb_ui.c'
        src.write_text('#include "fpui_stock.c"\n'
                       '__attribute__((used)) uint32_t pb_apply(uintptr_t b, uint32_t n, struct uia_outcome *o) '
                       '{ return fpui_stock_apply_plain(b, n, o); }\n')
        obj = d / 'pb_ui.o'
        subprocess.run([shutil.which('clang'), *T.BA.CFLAGS, '-I', str(P.ROOT / 'fpSup/fpsup-ui'),
                        '-I', str(P.ROOT / 'fpSup/loader-v4'), '-c', str(src), '-o', str(obj)],
                       check=True, capture_output=True, text=True)
        return T.BA.link_flat(obj.read_bytes())


class UiCam(T.Cam):
    APP, SCREEN, READER, TABLE, NAME, DATA, RESULT = [T.WORK + x for x in
        (0xA0000, 0xA0100, 0xA0200, 0xA0400, 0xA0500, 0xA1000, 0xA2000)]

    def __init__(self):
        super().__init__(build_desc=False)
        code, self.ui_funcs = native_code()
        self.mu.mem_write(T.BLOB, code)
        self.mu.mem_map(0xC9000000, 0x200000)
        self.next_alloc = 0x49000000
        self.stub(0xC001D740, 'PB_ALLOC'); self.stub(0xC001D7F0, 'PB_ADDR')
        self.put(0xC37B7048, self.APP)
        self.put(self.APP + 0x80, 1); self.put(self.APP + 0x8C, self.APP + 0x90)
        self.put(self.APP + 0x90, self.SCREEN); self.put(self.SCREEN + 0x24, self.READER)
        self.put(self.READER + 0x24, P.NBU); self.put(self.READER + 0xA8, 1)
        self.put(self.READER + 0xAC, self.TABLE); self.put(self.TABLE + 4, self.NAME)
        self.put(self.TABLE + 8, P.source()[1] - P.NBU)
        self.mu.mem_write(self.NAME, b'Playback\0')

    def _hook(self, mu, addr, size, data):
        n = self.by_addr.get(addr)
        if n == 'PB_ALLOC':
            p, count = self.r(T.UC_ARM_REG_R0), self.r(T.UC_ARM_REG_R2)
            self.put(p, self.next_alloc)
            self.next_alloc += (count + 63) & ~63
            return self.ret(0)
        if n == 'PB_ADDR':
            return self.ret(self.w(self.r(T.UC_ARM_REG_R0)))
        return super()._hook(mu, addr, size, data)

    def apply_page(self, block=None):
        block = P.build() if block is None else block
        self.mu.mem_write(self.DATA, block)
        result = self.call(T.BLOB + self.ui_funcs['pb_apply'], self.DATA, len(block), self.RESULT)
        page = (P.NBU + self.w(self.TABLE + 8)) & 0xFFFFFFFF
        return result, page


class PlaybackPageTests(unittest.TestCase):
    def test_header_is_current_and_stock_frames_remain_identical(self):
        self.assertEqual((P.HERE / 'pb_page.h').read_text(), P.header())
        before, after = clips(P.source()[2]), clips(P.applied())
        self.assertEqual(set(before), set(P.OWNERS))
        for owner in P.OWNERS:
            self.assertEqual(after[owner]['properties'][:3], before[owner]['properties'])
            opacity = after[owner]['properties'][3]
            self.assertEqual((opacity['name'], opacity['component_ref'], opacity['kind']), ('opacity', 0, 1))
            self.assertEqual([(k['time'], k['value']) for k in opacity['keys']], [(0, 1), (33, 1), (66, 1), (100, 0)])

    def test_native_record_counts_and_unchanged_objects(self):
        im = P.source()[0]
        old, new = [list(P.B.N.split(p)) for p in (P.source()[2], P.applied())]
        self.assertEqual(len(old), len(new))
        def budget(recs):
            head = P.A.parse_header(P.A.Record(0, recs[0].to_bytes()), im.text)
            cs = [P.A.parse_clip(P.A.Record(r.offset, r.to_bytes()), im.text) for r in recs if r.tag == 0x1000A]
            return (sum(head['clip_property_counts']) - sum(len(c['properties']) for c in cs),
                    sum(head['property_key_counts']) - sum(len(p['keys']) for c in cs for p in c['properties']))
        self.assertEqual(budget(old), budget(new))
        for a, b in zip(old[1:], new[1:]):
            ra, rb = a.to_bytes(), b.to_bytes()
            if a.tag == 0x1000A and P.B.u32(ra, 20) in P.OWNERS:
                self.assertEqual(rb[28:len(ra)], ra[28:])
            elif a.tag == 0x1000B and P.B.u32(ra, 24) in P.OWNERS and im.text(P.B.u32(ra, 20)) == 'Resolution':
                self.assertEqual(rb[:36] + rb[40:], ra[:36] + ra[40:])
                self.assertEqual(P.B.u32(rb, 36), 100)
            else:
                self.assertEqual(rb, ra)

    def test_real_fpui_stock_applier_matches_reference_and_preserves_firmware(self):
        cam = UiCam()
        result, page = cam.apply_page()
        self.assertEqual(result, 0)
        self.assertEqual(bytes(cam.mu.mem_read(page, len(P.applied()))), P.applied())
        self.assertEqual(bytes(cam.mu.mem_read(P.source()[1], len(P.source()[2]))), P.source()[2])
        # A second install is refused by the stock guard; the first copy stays selected.
        result, again = cam.apply_page()
        self.assertEqual((result, again), (4, page))

    def test_guard_failure_keeps_the_runtime_entry(self):
        cam = UiCam()
        strings, ops, frag = P.fpui.decode(P.build())
        block = P.fpui.Block(); block.strings = strings; block.ops = ops; block.frag = bytearray(frag)
        i = next(i for i, (op, args) in enumerate(ops) if op == P.fpui.OP_GUARD)
        block.ops[i] = (ops[i][0], [ops[i][1][0], ops[i][1][1] ^ 1])
        result, page = cam.apply_page(block.encode())
        self.assertEqual((result, page), (4, P.source()[1]))


if __name__ == '__main__':
    unittest.main()
