#!/usr/bin/env python3
"""build_v4.py --pwroff-file under unicorn: the core's power-off routine writes
one fixed 128 B record to \\fpSup\\PWROFF.LOG (a card file survives the cold
boot that wipes RAM; the settings area is flushed before the lists run).

    cd fpSup/loader-v4 && python3 -B -m unittest test_pwroff_file_v4
    python3 -B test_pwroff_file_v4.py --mutate      # each mutant must fail a test

The firmware file API is the harness's (test_v3.Camera); the power controller
block 0x2D000000 is mapped as plain memory so the values the record copies can
be planted.
"""
import pathlib, shutil, struct, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'fp_usb_shell' / 'v3'))
sys.path.insert(0, str(HERE.parent / 'fp_usb_shell'))

import build_v4 as B
import test_v3 as T3
import test_v4 as T4

PATH = '\\fpSup\\PWROFF.LOG'
MAGIC, WORDS = 0x31465750, 32
MGR, PMU, CBOBJ, CB_STOCK = 0xC30756C4, 0x2D000280, 0xC31D848C, 0xC0023B60
BATT, BATT_OBJ, BUSY, NOW_MS = 0xC30783D8, 0xC3079000, 0xC3075748, 0xC301EAE4
L_PWRFILE = 0x31
SRC = None                                      # the mutation check swaps these
ENTRY = None


def loader(on=True):
    return B.loader_bin(src=SRC, entry_src=ENTRY, pwroff_file=on)[0]


class Camera(T4.Camera):
    fail_create = False

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.mu.mem_map(0x2D000000, 0x1000)
        self.creates = 0

    def _hook(self, mu, addr, size, data):
        if self.by_addr.get(addr) == 'F_OPEN':
            mode = self.r(T3.UC_ARM_REG_R2)
            if mode == 7:
                self.creates += 1
                if self.fail_create:
                    self.opened.append(self.cstr(self.r(T3.UC_ARM_REG_R1)))
                    return self._ret(0)
        return super()._hook(mu, addr, size, data)

    def puts(self, addr, *words):
        self.mu.mem_write(addr, struct.pack(f'<{len(words)}I', *(w & 0xFFFFFFFF for w in words)))

    def record(self):
        data = self.written.get(PATH)
        if data is None:
            return None
        return list(struct.unpack(f'<{WORDS}I', data[:4 * WORDS]))



def boot(on=True, sups=(), existing=None):
    files, dirs = T4.card(*sups, loader=loader(on))
    if existing is not None:
        files[PATH] = existing
    cam = Camera(files, dirs)
    cam.boot()
    return cam


def plant(cam, wake=(0, 0, 2, 0), pin314=0x5027F1C, ext=1, busy=0):
    cam.puts(CBOBJ, CB_STOCK)
    cam.puts(CBOBJ + 0x230, 1, 0)
    cam.puts(MGR + 0x08, 0)
    cam.puts(MGR + 0x60, 1)
    cam.puts(MGR + 0x68, 0x00010101)
    cam.puts(MGR + 0x6C, 900, 0x55)
    cam.puts(PMU, 0x37042730)
    cam.puts(PMU + 0x80, *wake)
    cam.puts(PMU + 0x94, pin314)
    cam.puts(BATT + 4, BATT_OBJ)
    cam.puts(BATT_OBJ + 0xB8, ext)
    cam.puts(BUSY, busy)
    cam.puts(NOW_MS, 73000)


def rec_bytes(seq):
    return struct.pack(f'<{WORDS}I', MAGIC, seq, *([0] * (WORDS - 3)), ~MAGIC & 0xFFFFFFFF)


@unittest.skipIf(T4.Uc is None or not T3.IMAGE.exists(), 'needs unicorn and the image')
class PwroffFileTests(unittest.TestCase):
    def setUp(self):
        self.stock_a = T3.word(T3.IMAGE.read_bytes(), T4.SITE_A)

    def test_boot_logs_and_writes_nothing(self):
        cam = boot()
        self.assertIn(L_PWRFILE, [c for c, *_ in cam.loadlog()])
        self.assertNotIn(PATH, cam.written)
        self.assertEqual(cam.creates, 1)                   # LOAD.LOG only

    def test_power_off_writes_one_fixed_record(self):
        ts = T4.LoaderV4Tests('test_power_off_restores_and_stale_patch_repaired').ts
        cam = boot(sups=[('A.BIN', ts('AAAA', claims=[(T4.SITE_A, self.stock_a, 2, T4.NOP)]))])
        plant(cam)
        cam.power_off()                                    # reason 4 from the harness
        self.assertEqual(len(cam.written[PATH]), 4 * WORDS)
        r = cam.record()
        self.assertEqual(r[0], MAGIC)
        self.assertEqual(r[WORDS - 1], ~MAGIC & 0xFFFFFFFF)
        self.assertEqual(r[1:4], [1, 1, 4])
        self.assertEqual(r[5], 73000)
        self.assertEqual(r[6:11], [0, 1, 0x00010101, 900, 0x55])
        self.assertEqual(r[11:15], [0, 0, 2, 0])
        self.assertEqual(r[15:17], [0x5027F1C, 0x37042730])
        self.assertEqual(r[17:22], [1, 0, CB_STOCK, 1, 0])
        self.assertEqual(r[22:24], [0xFFFFFFFE, 0xFFFFFFFE])  # reserved (the removed FUSB switch)
        self.assertEqual(cam.w(T4.SITE_A), self.stock_a)   # the write-back still happens

    def test_second_list_only_counts(self):
        cam = boot()
        plant(cam)
        cam.power_off()
        first = cam.written[PATH]
        n = cam.creates
        cam.puts(PMU + 0x88, 7)
        cam.power_off()
        self.assertEqual(cam.written[PATH], first)
        self.assertEqual(cam.creates, n)

    def test_seq_continues_from_the_file_on_the_card(self):
        cam = boot(existing=rec_bytes(41))
        plant(cam)
        cam.power_off()
        self.assertEqual(cam.record()[1], 42)

    def test_foreign_file_is_not_trusted(self):
        bad = bytearray(rec_bytes(41))
        bad[-1] ^= 0xFF
        cam = boot(existing=bytes(bad))
        plant(cam)
        cam.power_off()
        self.assertEqual(cam.record()[1], 1)


    def test_create_failure_is_skipped_and_power_off_goes_on(self):
        ts = T4.LoaderV4Tests('test_power_off_restores_and_stale_patch_repaired').ts
        cam = boot(sups=[('A.BIN', ts('AAAA', claims=[(T4.SITE_A, self.stock_a, 2, T4.NOP)]))])
        plant(cam)
        cam.fail_create = True
        cam.power_off()
        self.assertNotIn(PATH, cam.written)
        self.assertEqual(cam.w(T4.SITE_A), self.stock_a)


    def test_off_build_writes_nothing(self):
        cam = boot(on=False)
        plant(cam)
        cam.power_off()
        self.assertNotIn(PATH, cam.written)
        self.assertNotIn(L_PWRFILE, [c for c, *_ in cam.loadlog()])


MUTANTS = [
    ('second list writes too', 'if (st->pf_calls != 1 || !st->pf_obj) return;', 'if (!st->pf_obj) return;', 'c'),
    ('seq not continued', '        st->pf_seq = rec[1];', '        st->pf_seq = 0;', 'c'),
    ('foreign file trusted', 'rec[0] == PF_MAGIC && rec[PF_WORDS - 1] == ~PF_MAGIC)', 'rec[0] == PF_MAGIC)', 'c'),
    ('magic never set', '    r[0] = PF_MAGIC;\n', '', 'c'),
    ('wrong wake offset', 'r[11 + i] = pf_rd(PF_PMU + 0x80u + 4u * i);', 'r[11 + i] = pf_rd(PF_PMU + 0x84u + 4u * i);', 'c'),
    ('reserved words not marked', '    r[22] = r[23] = 0xFFFFFFFEu;', '    r[22] = r[23] = 0;', 'c'),
    ('hook never installed', '            st->poff[3] = (u32)(uintptr_t)poff_hook;\n        }\n        logrec(st, L_PWRFILE',
     '        }\n        logrec(st, L_PWRFILE', 'c'),
    ('reason not recorded', '    r[3] = reason;\n', '    r[3] = 0; (void)reason;\n', 'c'),
]


def mutate():
    global SRC, ENTRY
    csrc = (HERE / 'sloader4.c').read_text()
    ssrc = (HERE / 'sloader4_entry.S').read_text()
    failed = []
    with tempfile.TemporaryDirectory(prefix='pfmut-') as t:
        t = pathlib.Path(t)
        shutil.copy(HERE / 'sloader4.h', t / 'sloader4.h')
        for name, old, new, which in MUTANTS:
            src = csrc if which == 'c' else ssrc
            if src.count(old) != 1:
                failed.append(f'{name}: pattern not found once')
                continue
            (t / 'sloader4.c').write_text(csrc.replace(old, new) if which == 'c' else csrc)
            (t / 'sloader4_entry.S').write_text(ssrc.replace(old, new) if which == 's' else ssrc)
            SRC, ENTRY = t / 'sloader4.c', t / 'sloader4_entry.S'
            try:
                B.loader_bin(src=SRC, entry_src=ENTRY, pwroff_file=True)
            except Exception as e:
                failed.append(f'{name}: does not build ({e})')
                continue
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(PwroffFileTests)
            res = unittest.TextTestRunner(stream=open('/dev/null', 'w'), verbosity=0).run(suite)
            killed = bool(res.failures or res.errors)
            print(f'{"caught " if killed else "SURVIVED"} {name}', flush=True)
            if not killed:
                failed.append(name)
    SRC = ENTRY = None
    print('mutants:', len(MUTANTS), 'survived/invalid:', failed)
    return not failed


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        sys.exit(0 if mutate() else 1)
    unittest.main()
