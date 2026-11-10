#!/usr/bin/env python3
"""Native RAW-read format conversion, with the selected clip's real canvas.

Runs ROM C01CE400..458 (inside C01CDBE0) in Thumb mode. The input
frame descriptor is an explicit fixture, populated from the playback canvas;
this is not a DMA or LCD emulator. No SD/USB operations.
"""
import argparse
import json
from pathlib import Path
import struct
import unittest
import test_playback_checked as C
T = C.T
SOURCE = None
EVIDENCE = []
FRAME = T.WORK + 0xA000
RAW = 0xC31DECCC
START, END, SITE = 0xC01CE400, 0xC01CE458, 0xC01CE450


def convert(c, plane, raster, channel=0):
    c.mu.mem_write(FRAME, bytes(0x510))
    c.put(FRAME, 1)
    c.put(FRAME + 0x38, plane)
    c.put(FRAME + 0x58, raster[0])
    c.put(FRAME + 0x60, raster[1])
    sp = T.STACK - 0x1004
    registers = {T.UC_ARM_REG_R0: 0x10203040, T.UC_ARM_REG_R1: 0x11223344,
                 T.UC_ARM_REG_R4: channel, T.UC_ARM_REG_R5: RAW,
                 T.UC_ARM_REG_R6: FRAME, T.UC_ARM_REG_R7: FRAME + 0x38,
                 T.UC_ARM_REG_R8: 0x88, T.UC_ARM_REG_R9: 0x99,
                 T.UC_ARM_REG_R10: 0xAA, T.UC_ARM_REG_R11: 0xBB,
                 T.UC_ARM_REG_R12: 0xCC, T.UC_ARM_REG_SP: sp}
    for reg, value in registers.items(): c.mu.reg_write(reg, value)
    c.put(RAW + channel * 0x10C + 0x50, 0xDEADBEEF)
    def guard(mu, a, size, data):
        if (START <= a < END or T.BLOB <= a < T.BLOB + len(c.img) or
                T.MEM <= a < T.MEM + (len(c.claims)-1)*88 or
                T.CAVE_ARENA <= a < T.CAVE_ARENA+0x1000): return
        raise AssertionError(f'unapproved conversion instruction {a:08x}')
    handle = c.mu.hook_add(T.UC_HOOK_CODE, guard)
    try:
        c.mu.emu_start(START | 1, END, count=100000)
        if c.error: raise c.error
        assert c.r(T.UC_ARM_REG_PC) == END
        assert c.r(T.UC_ARM_REG_CPSR) & 0x20, 'did not return to Thumb'
        for reg, value in registers.items():
            assert c.r(reg) == value, (reg, hex(c.r(reg)), hex(value))
        return c.w(RAW + channel * 0x10C + 0x50)
    finally: c.mu.hook_del(handle)


class Raw14Playback(unittest.TestCase):
    def selected(self, bits=14, raster=(2096,1240)):
        C.SOURCE = SOURCE
        c = C.SelectedCam()
        c.select(C.movie(raster, bits))
        self.assertEqual(c.prepare(), 1)
        _, canvas = c.profile()
        return c, canvas

    def test_native_read_format_keeps_selected_bit_depth(self):
        for bits, expected in ((8,4),(10,3),(12,0),(14,1)):
            for raster in ((2096,1240),(1936,1090),(336,206),(4048,2160)):   # v0.7.24: 6K is refused; a large custom one
                with self.subTest(bits=bits,raster=raster):
                    c, canvas = self.selected(bits,raster)
                    got = convert(c, canvas[0x80//4] & 255, raster)
                    EVIDENCE.append(dict(bits=bits,raster=raster,canvas=hex(canvas[32]),raw_input_enum=got))
                    self.assertEqual(got, expected)

    def test_original_native_bug_is_reproduced_without_hook(self):
        c, canvas = self.selected()
        c.mu.mem_write(SITE,struct.pack('<I',T.iw(SITE)))
        self.assertEqual(convert(c,8,(2096,1240)),0)

    def test_guard_rejects_other_channels_frames_planes_and_stale_owners(self):
        for variant in ('channel','raster','plane','file','exit','unprepared'):
            with self.subTest(variant=variant):
                c, canvas = self.selected()
                channel, raster, plane = 0,(2096,1240),8
                if variant=='channel': channel=1
                if variant=='raster': raster=(2080,1240)
                if variant=='plane': plane=11
                if variant=='file': c.put(T.OBJ+0x88,18)
                if variant=='exit': c.canvas(5)
                if variant=='unprepared': c.select(C.movie())
                self.assertEqual(convert(c,plane,raster,channel),0)


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path);p.add_argument('--report',type=Path)
    args=p.parse_args();SOURCE=args.source
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Raw14Playback))
    if args.report: args.report.write_text(json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),cases=EVIDENCE,hardware_verified=False),indent=2)+'\n')
    raise SystemExit(not result.wasSuccessful())
