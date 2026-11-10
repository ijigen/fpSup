#!/usr/bin/env python3
"""build_v4.py --pwroff-log under unicorn: the early record (core power-off
routine -> XC_CommonSaveData +0x210), the armed wrapper around the stock veto
callback [0xC31D848C] = C0023B60, and the late record in the cave.

    cd fpSup/loader-v4 && python3 -B -m unittest test_pwroff_log_v4
    python3 -B test_pwroff_log_v4.py --mutate      # each mutant must fail a test

The power controller block 0x2D000000 is mapped as plain memory so the values
the record should copy can be planted.  C0023B60 is replaced by a two-word stub
returning a chosen value (the real one consults devices not emulated here).
"""
import pathlib, shutil, struct, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'fp_usb_shell' / 'v3'))
sys.path.insert(0, str(HERE.parent / 'fp_usb_shell'))

import build_v4 as B
import test_v3 as T3
import test_v4 as T4

STORE, WORDS = 0xC307544C, 28
MAGIC, LMAGIC = 0x314C5750, 0x4C4C5750
MGR, PMU, CBOBJ, CB_STOCK = 0xC30756C4, 0x2D000280, 0xC31D848C, 0xC0023B60
L_PWRLOG = 21                                   # L_OLD_FORMAT (20) + 1
SRC = None                                      # the mutation check swaps these
ENTRY = None


def loader(on=True):
    return B.loader_bin(src=SRC, entry_src=ENTRY, pwroff_log=on)[0]


class Camera(T4.Camera):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.mu.mem_map(0x2D000000, 0x1000)

    def put(self, addr, *words):
        self.mu.mem_write(addr, struct.pack(f'<{len(words)}I', *words))

    def words(self, addr, n):
        return list(struct.unpack(f'<{n}I', self.mu.mem_read(addr, 4 * n)))

    def stub_veto(self, ret):
        self.put(CB_STOCK, 0xE3A00000 | (ret & 0xFF), 0xE12FFF1E)    # mov r0,#ret; bx lr


def boot(on=True, sups=(), store=None):
    cam = Camera(*T4.card(*sups, loader=loader(on)))
    if store is not None:
        cam.put(STORE, *store)
    cam.boot()
    return cam


def plant(cam, wake=(0, 0, 2, 0), pmu=0x37042730, mgr8=1, reason=1):
    cam.put(CBOBJ, CB_STOCK)
    cam.put(CBOBJ + 0x230, 1, 1)
    cam.put(MGR + 0x08, mgr8)
    cam.put(MGR + 0x60, reason)
    cam.put(MGR + 0x68, 0x00010101)
    cam.put(MGR + 0x6C, 900, 0x55)
    cam.put(PMU, pmu)
    cam.put(PMU + 0x80, *wake)


@unittest.skipIf(T4.Uc is None or not T3.IMAGE.exists(), 'needs unicorn and the image')
class PwroffLogTests(unittest.TestCase):
    def setUp(self):
        self.stock_a = T3.word(T3.IMAGE.read_bytes(), T4.SITE_A)

    def poff(self, cam):
        return cam.registered[0][0]

    def test_boot_logs_and_reserves_a_cave_block(self):
        cam = boot()
        late = cam.w(self.poff(cam) + 20)
        self.assertTrue(0xC072E064 <= late < 0xC072EFB4, hex(late))            # cave.py arena
        self.assertIn((L_PWRLOG, late), [(c, a) for c, a, _, _ in cam.loadlog()])
        self.assertEqual(cam.w(STORE), 0)                     # nothing written until a power-off

    def test_early_record_arms_the_wrapper_and_journal_still_restores(self):
        ts = T4.LoaderV4Tests('test_power_off_restores_and_stale_patch_repaired').ts
        cam = boot(sups=[('A.BIN', ts('AAAA', claims=[(T4.SITE_A, self.stock_a, 2, T4.NOP)]))])
        plant(cam)
        obj = self.poff(cam)
        wrap, late = cam.w(obj + 16), cam.w(obj + 20)
        self.assertEqual(cam.w(T4.SITE_A), T4.NOP)
        cam.power_off()                                      # reason 4 from the harness
        s = cam.words(STORE, WORDS)
        self.assertEqual(s[:5], [MAGIC, 1, late, 1, 4])
        self.assertEqual(s[6:11], [1, 1, 0x00010101, 900, 0x55])
        self.assertEqual(s[11:15], [0, 0, 2, 0])
        self.assertEqual(s[15], 0x37042730)
        self.assertEqual(s[16:20], [CB_STOCK, 1, 1, 1])
        self.assertEqual(s[20], cam.w(obj + 28))
        self.assertEqual(cam.w(CBOBJ), wrap)
        self.assertTrue(wrap & 1)
        self.assertEqual(cam.w(T4.SITE_A), self.stock_a)     # the write-back still happens

    def test_second_list_only_counts(self):
        cam = boot()
        plant(cam)
        cam.power_off()
        first = cam.words(STORE, WORDS)
        cam.put(PMU + 0x88, 7)                               # would change the snapshot
        cam.power_off()
        second = cam.words(STORE, WORDS)
        self.assertEqual(second[3], 2)
        self.assertEqual(second[:3] + second[4:], first[:3] + first[4:])

    def test_wrapper_records_and_returns_the_stock_result(self):
        for ret in (1, 0):
            cam = boot()
            plant(cam, wake=(0, 0, 0xFFFFFFFF, 0xFFFFFFFF))
            cam.power_off()
            cam.stub_veto(ret)
            wrap, late = cam.w(CBOBJ), cam.w(self.poff(cam) + 20)
            r0, _ = cam.call(wrap & ~1, thumb=True)
            self.assertEqual(r0, ret)
            l = cam.words(late, 13)
            self.assertEqual(l[:4], [LMAGIC, 1, 2, ret])
            self.assertEqual(l[5:12], [0, 0, 0xFFFFFFFF, 0xFFFFFFFF, 1, 1, 0x37042730])

    def test_seq_continues_from_the_stored_record(self):
        old = [MAGIC, 41] + [0] * (WORDS - 2)
        cam = boot(store=old)
        plant(cam)
        cam.power_off()
        self.assertEqual(cam.words(STORE, 2), [MAGIC, 42])

    def test_foreign_bytes_are_reset_not_trusted(self):
        cam = boot(store=[0x12345678, 41] + [0xEE] * (WORDS - 2))
        plant(cam)
        cam.power_off()
        s = cam.words(STORE, WORDS)
        self.assertEqual(s[:2], [MAGIC, 1])
        self.assertEqual(s[21:], [0] * (WORDS - 21))

    def test_not_armed_unless_stock(self):
        cam = boot()
        plant(cam)
        cam.put(CBOBJ, 0xC0001234)
        cam.power_off()
        self.assertEqual(cam.w(CBOBJ), 0xC0001234)
        self.assertEqual(cam.words(STORE + 64, 4), [0xC0001234, 1, 1, 0])

    def test_off_build_records_nothing(self):
        cam = boot(on=False)
        plant(cam)
        cam.power_off()
        self.assertEqual(cam.w(STORE), 0)
        self.assertEqual(cam.w(CBOBJ), CB_STOCK)
        self.assertNotIn(L_PWRLOG, [c for c, *_ in cam.loadlog()])


MUTANTS = [
    ('wrapper drops the result', 'l[3] = r;\n        l[2] = 2;', 'l[3] = r; r = 0;\n        l[2] = 2;', 'c'),
    ('arms without checking stock', 'if (cb == PL_CB_STOCK) {', 'if (1) {', 'c'),
    ('seq not advanced', 's[1] = s[1] + 1;', '', 'c'),
    ('late magic never set', 'l[0] = PL_LMAGIC;', '', 'c'),
    ('second list overwrites', 'if (poff[6] != 1) return;', '', 'c'),
    ('foreign bytes trusted', 'if (s[0] != PL_MAGIC) {', 'if (0) {', 'c'),
    ('late block not passed', 's[2] = poff[5];', '', 'c'),
    ('routine never called', '    blx     r3                          @ pl_early(poff, reason)\n', '', 's'),
]


def mutate():
    global SRC, ENTRY
    csrc = (HERE / 'sloader4.c').read_text()
    ssrc = (HERE / 'sloader4_entry.S').read_text()
    failed = []
    with tempfile.TemporaryDirectory(prefix='plmut-') as t:
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
                B.loader_bin(src=SRC, entry_src=ENTRY, pwroff_log=True)
            except Exception as e:
                failed.append(f'{name}: does not build ({e})')
                continue
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(PwroffLogTests)
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
