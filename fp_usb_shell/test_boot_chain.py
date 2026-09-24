#!/usr/bin/env python3
"""Offline regression checks for the assembled boot chain (no camera access).

These inspect ARM instructions and build outputs, not firmware behaviour or
cache hardware. Run with: python3 -m unittest -v test_boot_chain
"""
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

from armasm import assemble, words

HERE = pathlib.Path(__file__).resolve().parent
LOADER_BASE = 0xC072DE64
DCACHE, ICACHE = 0xC000E91C, 0xC000EABC
DEFINES = [f'LOADER_BASE={LOADER_BASE}', 'POOL_DESC=0xC072F6D8',
           'BIN_PATH="\\\\fpSup.BIN"']


def branch_target(instruction, offset, base=0):
    displacement = instruction & 0xFFFFFF
    if displacement & 0x800000:
        displacement -= 0x1000000
    return (base + offset + 8 + displacement * 4) & 0xFFFFFFFF


class BootChainTests(unittest.TestCase):
    def test_loader_publishes_before_stage2_normal_and_profile(self):
        for profile in (False, True):
            with self.subTest(profile=profile):
                defines = DEFINES + (['LOAD_START_US=0xC072F6F4'] if profile else [])
                code = words(assemble(HERE / 'templates/loader.S', defines))
                calls = [(i, branch_target(w, i * 4, LOADER_BASE))
                         for i, w in enumerate(code) if w >> 24 == 0xEB]
                dcall = [i for i, target in calls if target == DCACHE]
                icall = [i for i, target in calls if target == ICACHE]
                self.assertEqual(len(dcall), 1)
                self.assertEqual(icall, [dcall[0] + 1])
                # Only register branch is the first execution of fresh stage2.
                stage2 = [i for i, w in enumerate(code) if w == 0xE12FFF31]
                self.assertEqual(stage2, [dcall[0] + 6])
                self.assertEqual(code[icall[0] + 1:stage2[0]],
                                 (0xE5961004, 0xE0861181, 0xE2811010, 0xE1A00006))
                self.assertEqual(code[1], 0xE92D47F0)  # r4-r10,lr: 32 bytes
                self.assertTrue(all(i > 1 for i, _target in calls))
                self.assertIn(0xE8BD87F0, code)         # matching return via pc

    def test_store_hit_and_miss_preserve_stack_and_return(self):
        for profile in (False, True):
            defines = DEFINES + (['LOAD_START_US=0xC072F6F4'] if profile else [])
            length = len(assemble(HERE / 'templates/loader.S', defines))
            with self.subTest(length=length):
                code = words(assemble(HERE / 'templates/store_boot.S',
                                      [f'STORE_LEN={length}', 'STORE_MAGIC=0x12345678']))
                # The complete executable part: reject unexpected control/stack
                # changes, including changes inside the repeated copy loop.
                self.assertEqual(code[:21], (
                    0xE92D41F0, 0xE28F7048, 0xE8B70070, 0xE5940000,
                    0xE1500005, 0x1A00000C, 0xE2841004, 0xE1A02006,
                    0xE3005000 | length, 0xE491C004, 0xE482C004,
                    0xE2555004, 0x1AFFFFFB, 0xE8970030, 0xE12FFF34,
                    0xE12FFF35, 0xE1A00006, 0xE8BD41F0, 0xE12FFF10,
                    0xE3A00000, 0xE8BD81F0))
                self.assertEqual(code[21:], (0xC3075264, 0x12345678,
                                             LOADER_BASE, DCACHE, ICACHE))
                # Magic mismatch skips copy/cache/tail and returns zero via pc.
                self.assertEqual(branch_target(code[5], 5 * 4), 19 * 4)
                # The matching path's sole loop performs no stack adjustment.
                self.assertEqual(branch_target(code[12], 12 * 4), 9 * 4)
                saved = [r for r in range(16) if code[0] & (1 << r)]
                self.assertEqual(saved, [4, 5, 6, 7, 8, 14])
                self.assertEqual(len(saved) * 4 % 8, 0)  # both cache calls aligned
                for pop_at in (17, 20):  # hit restores lr; miss restores pc
                    restored = [r for r in range(16) if code[pop_at] & (1 << r)]
                    self.assertEqual(restored[:-1], saved[:-1])
                    self.assertEqual(len(restored), len(saved))
                    self.assertEqual(restored[-1], 14 if pop_at == 17 else 15)

    def test_payload_update_does_not_change_autorun(self):
        with tempfile.TemporaryDirectory(prefix='boot-chain-test-') as tmp:
            tmp = pathlib.Path(tmp)
            for flags in ([], ['--store-boot'], ['--store-boot', '--profile']):
                with self.subTest(flags=flags):
                    products = []
                    for revision in (0, 1):
                        payload = tmp / 'payload.bin'
                        # Deliberately change contents AND length of an ordinary
                        # absolute data section, without changing the loader ABI.
                        payload.write_bytes(struct.pack('<I', 0x12345678 + revision)
                                            * (revision + 1))
                        out = tmp / f'card-{revision}'
                        out.mkdir(exist_ok=True)
                        result = subprocess.run(
                            [sys.executable, str(HERE / 'build_autorun.py'),
                             '--loader', '--no-shell', '--out', str(out / 'AutoRun.txt'),
                             '--also-bin', f'0xC0731000:{payload}', *flags],
                            capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0,
                                         result.stdout + result.stderr)
                        products.append(((out / 'AutoRun.txt').read_bytes(),
                                         (out / 'fpSup.BIN').read_bytes()))
                    self.assertEqual(products[0][0], products[1][0])
                    self.assertNotEqual(products[0][1], products[1][1])

    def test_bin_padding_uses_loader_capacity_without_changing_autorun(self):
        import re
        source = (HERE / 'templates/loader.S').read_text()
        cap = int(re.search(r'^\.equ\s+MAXLEN,\s*(0x[0-9A-Fa-f]+)',
                            source, re.M).group(1), 16)
        with tempfile.TemporaryDirectory(prefix='boot-padding-test-') as tmp:
            tmp = pathlib.Path(tmp)
            baseline, overhead = None, None
            for wanted in (None, 32768, 32772, cap, cap + 4):
                with self.subTest(used=wanted):
                    out = tmp / str(wanted)
                    out.mkdir()
                    payload = out / 'payload.bin'
                    payload.write_bytes(b'\x00' * (4 if wanted is None else wanted - overhead))
                    result = subprocess.run(
                        [sys.executable, str(HERE / 'build_autorun.py'),
                         '--loader', '--no-shell', '--out', str(out / 'AutoRun.txt'),
                         '--also-bin', f'0xC0740000:{payload}'],
                        capture_output=True, text=True)
                    if wanted is not None and wanted > cap:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('past loader MAXLEN', result.stderr)
                        self.assertFalse((out / 'fpSup.BIN').exists())
                        continue
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    blob = (out / 'fpSup.BIN').read_bytes()
                    _, count, _, body = struct.unpack_from('<4sIII', blob)
                    used = 16 + 8 * count + body
                    auto = (out / 'AutoRun.txt').read_bytes()
                    if wanted is None:
                        overhead, baseline = used - 4, auto
                    else:
                        self.assertEqual(used, wanted)
                        self.assertEqual(auto, baseline)
                    self.assertEqual(len(blob), 32768 if used <= 32768 else cap)
                    self.assertFalse(any(blob[used:]))


if __name__ == '__main__':
    unittest.main()
