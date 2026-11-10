#!/usr/bin/env python3
"""Offline settings migration: builders + actual v4 loader/client/container ARM.

The saved records are real read-only backups. RTOS/file/UI/settings services
use the declared test_qsct/test_slqs models; no camera or card is contacted.
"""
import argparse
import hashlib
import io
import inspect
import json
import os
import pathlib
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / 'projects/qs-container')]
import build_slqs as SL
import build_qsct as QC
import test_slqs as TS
import test_qsct as TQ

FIXTURES = HERE / 'test-fixtures' / 'settings-migration'   # own frozen copies (README.txt there)
FIXTURE = FIXTURES / 'preupgrade_backup'
FROZEN = FIXTURES / 'frozen'
OUT = HERE / 'out' / 'settings-migration'
PRODUCTS = [(SL, 'SensorLab-IMX410_v0.5.0test.BIN'), (QC, 'QSContainer_v0.2.4.BIN')]
BUILT = {}
EVIDENCE = {}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def builds():
    if BUILT:
        return BUILT
    fixture_manifest = {f['file']: f for f in json.loads((FIXTURE / 'manifest.json').read_text())['files']}
    for mod, old in PRODUCTS:
        path = FIXTURE / old
        source = path.read_bytes()
        assert sha(source) == fixture_manifest[old]['sha256'], 'fixture no longer matches backup manifest'
        default = mod.build()
        migrated = mod.build(settings_from=path)
        record, manifest = mod.settings_record(path)
        BUILT[mod.SUP_ID] = dict(module=mod, source=source, record=record, manifest=manifest,
                                default=default, migrated=migrated)
        EVIDENCE[mod.SUP_ID] = dict(default_sha256=sha(default[0]), migrated_sha256=sha(migrated[0]),
                                  default_matches_frozen=default[0] == (FROZEN / mod.file_name()).read_bytes(),
                                  settings_from=manifest, rec_off=migrated[1]['rec_off'])
    return BUILT


def arm_boot(client=True, corrupt=False, stale=None):
    d = builds()
    qc = bytearray(d['QSCT']['migrated'][0])
    sl = bytearray(d['SL41']['migrated'][0])
    if corrupt:
        qc[d['QSCT']['migrated'][1]['rec_off'] + 8] ^= 1
        sl[d['SL41']['migrated'][1]['rec_off'] + 8] ^= 1
    qr = struct.unpack('<83I', d['QSCT']['record'])
    slots = list(QC.DEFAULTS)
    for i in range(16):
        if qr[2 + 5 * i]:
            slots[i] = qr[6 + 5 * i]
    if stale is not None:
        slots[stale] = 9

    def prep(c):
        TS.ap_firmware(c)
        for i, v in enumerate(slots):
            c.set_slot(i // 8, i % 8, v)
    sups = [(QC.file_name(), bytes(qc))]
    if client:
        sups.append((SL.file_name(), bytes(sl)))
    with patch.dict(TQ._built, {'c': d['QSCT']['migrated']}):
        c = TQ.boot(sups, prepare=prep)
        if client:
            info = d['SL41']['migrated'][1]
            fn = TQ.T.blocks(c)[SL.file_name()] + info['code_off'] + info['functions']['sq_test']
            # A restored MBPS tile is emitted during first collection. Use the
            # same explicit SD model as test_slqs before that first emission.
            c.call(fn & ~1, r0=11, r1=4, r2=0, thumb=True)
            c.call(fn & ~1, r0=12, r1=1, r2=0, thumb=True)
        c.layout()  # real collection/record restore after both entries ran
    return c, slots


class Envelope(unittest.TestCase):
    def test_default_bytes_match_both_frozen_builds(self):
        for sid, item in builds().items():
            with self.subTest(sid=sid):
                mod, (data, info) = item['module'], item['default']
                self.assertEqual(data, (FROZEN / mod.file_name()).read_bytes())
                self.assertEqual(data[info['rec_off']:info['rec_off'] + 4 * mod.REC_WORDS], bytes(4 * mod.REC_WORDS))
                self.assertNotIn('settings_from', info)

    def test_only_record_bytes_change_and_source_is_unchanged(self):
        for sid, item in builds().items():
            with self.subTest(sid=sid):
                mod, (data, info), (default, di) = item['module'], item['migrated'], item['default']
                off, n = info['rec_off'], 4 * mod.REC_WORDS
                self.assertEqual(off, di['rec_off'])
                self.assertNotEqual(off, item['manifest']['source_rec_off'])
                self.assertEqual(data[:off] + data[off+n:], default[:off] + default[off+n:])
                self.assertEqual(data[off:off+n], item['record'])
                self.assertEqual(info['settings_from'], item['manifest'])
                self.assertEqual(pathlib.Path(item['manifest']['source_file']).read_bytes(), item['source'])
                self.assertEqual(info['sha256'], sha(data))

    def test_invalid_envelopes_fail_closed_before_compile(self):
        count = 0
        for sid, item in builds().items():
            mod, original = item['module'], item['source']
            rec = item['manifest']['source_rec_off']
            changes = [('header magic', 0, 0), ('header length', 4, 44), ('file length', 8, len(original) + 4),
                       ('block range', 12, 0), ('entry range', 16, 1), ('wrong product', 20, 0x41414141),
                       ('config magic', 48, 0), ('config version', 52, 99), ('state range', 56, 0),
                       ('DMA range', 60, 0), ('record alignment', 64, rec + 1),
                       ('record before config', 64, 48), ('record beyond file', 64, len(original) - 4),
                       ('record magic', rec, 0), ('record version', rec + 4, 99),
                       ('record FNV', rec + 4 * (mod.REC_WORDS - 1), 0)]
            with tempfile.TemporaryDirectory(prefix='settings-invalid-') as tmp:
                source = pathlib.Path(tmp) / 'bad.BIN'
                for name, off, value in changes:
                    with self.subTest(product=sid, damage=name):
                        bad = bytearray(original)
                        struct.pack_into('<I', bad, off, value)
                        source.write_bytes(bad)
                        compiler = 'compile_text' if mod is SL else 'compile_code'
                        with patch.object(mod, compiler, side_effect=AssertionError('compiled invalid source')):
                            with self.assertRaises(mod.BuildError):
                                mod.build(settings_from=source)
                        count += 1
                for name, bad in [('truncated', original[:40]), ('raw record', item['record']),
                                  ('blank default', item['default'][0])]:
                    with self.subTest(product=sid, damage=name):
                        source.write_bytes(bad)
                        with self.assertRaises(mod.BuildError):
                            mod.settings_record(source)
                        count += 1
        EVIDENCE['invalid_sources_rejected'] = count


    def test_cli_refuses_to_overwrite_its_source(self):
        for mod, old in PRODUCTS:
            with self.subTest(product=mod.SUP_ID), tempfile.TemporaryDirectory(prefix='settings-cli-') as tmp:
                path = pathlib.Path(tmp) / 'fpSup' / mod.file_name()
                path.parent.mkdir()
                source = (FIXTURE / old).read_bytes()
                path.write_bytes(source)
                with patch.object(sys, 'argv', [mod.__file__, '--out', tmp, '--settings-from', str(path)]):
                    with self.assertRaisesRegex(mod.BuildError, 'overwrite'):
                        mod.main()
                self.assertEqual(path.read_bytes(), source)

    def test_validation_mutations_are_detected(self):
        killed = []
        for mod, old in PRODUCTS:
            sid = mod.SUP_ID
            _, manifest = mod.settings_record(FIXTURE / old)
            original = (FIXTURE / old).read_bytes()
            rec = manifest['source_rec_off']
            mutants = [
                ('header', 'if magic != 0x34425346 or hlen != hdr or flen != len(data):', 0),
                ('sup_id', "if sid != int.from_bytes(SUP_ID.encode('ascii'), 'little'):", 20),
                ('config', 'if cfg_magic != CFG_MAGIC or cfg_version != SETTINGS_CFG_VERSION:', 52),
                ('record magic/version', 'if words[:2] != (SETTINGS_REC_MAGIC, SETTINGS_REC_VERSION):', rec + 4),
                ('FNV', 'if checksum != words[-1]:', rec + 4 * (mod.REC_WORDS - 1)),
            ]
            for name, check, offset in mutants:
                with self.subTest(product=sid, mutant=name), tempfile.TemporaryDirectory(prefix='settings-mutant-') as tmp:
                    source = inspect.getsource(mod.settings_record)
                    self.assertEqual(source.count(check), 1)
                    source = source.replace(check, 'if False:')
                    namespace = mod.__dict__.copy()
                    exec(compile(source, '<settings-validation-mutant>', 'exec'), namespace)
                    bad = bytearray(original)
                    struct.pack_into('<I', bad, offset, 0)
                    if name == 'record magic/version':
                        # Keep FNV valid so this mutation probes version validation independently.
                        h = 2166136261
                        for byte in bad[rec:rec + 4 * (mod.REC_WORDS - 1)]:
                            h = ((h ^ byte) * 16777619) & 0xFFFFFFFF
                        struct.pack_into('<I', bad, rec + 4 * (mod.REC_WORDS - 1), h)
                    path = pathlib.Path(tmp) / 'bad.BIN'
                    path.write_bytes(bad)
                    # Run the same rejection assertion on an actual mutated parser.
                    # Its AssertionError is the required caught mutant, never an import/crash.
                    with self.assertRaises(AssertionError):
                        with self.assertRaises(mod.BuildError):
                            namespace['settings_record'](path)
                    killed.append(dict(product=sid, removed_check=name, caught_by='BuildError rejection assertion',
                                       mutant_source_sha256=sha(source.encode())))
        EVIDENCE['validation_mutants'] = killed


class ArmMigration(unittest.TestCase):
    def test_actual_loader_loads_exact_selection_and_qs_slots(self):
        d = builds()
        c, original = arm_boot()
        base = TQ.T.blocks(c)[SL.file_name()]
        state = base + d['SL41']['migrated'][1]['state_off']
        r = struct.unpack('<65I', d['SL41']['record'])
        # Record serialization differs from struct sel: mem precedes FPS; fine is transient.
        expected_sel = (*r[2:16], *r[32:64], *r[16:20], 0, *r[20:32])
        self.assertEqual(len(expected_sel), 63)
        got = struct.unpack('<63I', bytes(c.mu.mem_read(state + 16, 252)))
        self.assertEqual(c.w(state + 272), 1, 'real rec_load did not set loaded')
        self.assertEqual(got, expected_sel)
        # Invoke real rec_pack on the loaded state: its checksum/serialization must round-trip.
        fn = base + d['SL41']['migrated'][1]['code_off'] + d['SL41']['migrated'][1]['functions']['rec_pack']
        output = TS.F6.FAKE + 0x9000
        c.call(fn & ~1, r0=state + 16, r1=output, thumb=bool(fn & 1))
        self.assertEqual(bytes(c.mu.mem_read(output, 260)), d['SL41']['record'])
        # Stable named keys from the actual old record (including now-hidden replacements).
        ids = {'DC': 54, 'RES': 55, 'FPS': 56, 'RECIPE': 57, 'FORMAT': 58, 'MBPS': 59, 'QR': 60}
        q = d['QSCT']['record']
        expected = original[:]
        names = []
        for i in range(16):
            entry = q[8 + 20*i:28 + 20*i]
            if struct.unpack_from('<I', entry)[0]:
                name = entry[4:16].split(b'\0', 1)[0].decode('ascii')
                expected[i] = ids[name]
                names.append(dict(slot=i, name=name, placeholder=original[i], restored=ids[name]))
        got_slots = [c.slot(i // 8, i % 8) for i in range(16)]
        self.assertEqual(got_slots, expected)
        self.assertEqual(TQ.counter(c, 'restored'), len(names))
        self.assertEqual(TQ.counter(c, 'stale'), 0)
        self.assertEqual(TQ.counter(c, 'orphans'), 0)
        self.assertNotIn('\\fpSup\\' + SL.file_name(), c.written)
        self.assertNotIn('\\fpSup\\' + QC.file_name(), c.written)
        EVIDENCE['arm_boot'] = dict(loaded=1, selection_words=list(got), selection_roundtrip=True,
                                   slots=got_slots, restored=names, record_writes=0)

    def test_corrupt_runtime_records_are_rejected_by_real_c(self):
        c, original = arm_boot(corrupt=True)
        state = TQ.T.blocks(c)[SL.file_name()] + builds()['SL41']['migrated'][1]['state_off']
        self.assertEqual(c.w(state + 272), 0)
        self.assertEqual([c.w(state + 16 + 4*i) for i in range(2)], [6048, 3402])
        self.assertEqual(TQ.counter(c, 'restored'), 0)
        self.assertEqual([c.slot(i // 8, i % 8) for i in range(16)], original)

    def test_changed_stock_placeholder_remains_owned_by_user(self):
        c, original = arm_boot(stale=9)
        self.assertEqual(c.slot(1, 1), 9)
        self.assertEqual(TQ.counter(c, 'stale'), 1)
        self.assertEqual(TQ.counter(c, 'restored'), 6)


#: v0.7.39test: CPU x2 (ISP HBIN hbin 2, option 13 of v0.7.38test) was removed (validation/20261105-cpux2-archive).
#: A v0.7.38test BIN can hold a selection with hbin 2; the loader must restore ISP HBIN 1 (its RWZM twin).
CPU2_FROM = 'SensorLab-IMX410_v0.7.38test.BIN'
CPU2_KEYS = ['focus:2', 'f+', 'focus:4', 'ael', 'focus:6', 'f+', 'focus:4', 'f-', 'focus:6', 'ael']   # HD 3K 12b 1x2, ISP HBIN 1
REC_RQ, REC_HB = 2 + 13 + 1 + 4, 2 + 13 + 1 + 4 + 2 + 5      # record words: rq, rd[K_HB] (slqs.c rec_pack)
SEL_RQ, SEL_HB = 13 + 1 + 32 + 5, 13 + 1 + 32 + 5 + 2 + 5    # struct sel words: rq, rd[K_HB]
CPU2_MUTANTS = [
    ('rd[K_HB] kept at 2', '    if (s.rd[K_HB] == 2u) s.rd[K_HB] = 1u;\n', ''),
    ('rq kept at hbin 2', '    if ((s.rq >> 4 & 0xFu) == 2u) s.rq = (s.rq & ~0xF0u) | 0x10u;\n', ''),
    ('mapped to ISP HBIN 3', 'if (s.rd[K_HB] == 2u) s.rd[K_HB] = 1u;', 'if (s.rd[K_HB] == 2u) s.rd[K_HB] = 3u;'),
    ('rq mapped to ISP HBIN 3', '(s.rq & ~0xF0u) | 0x10u;', '(s.rq & ~0xF0u) | 0x30u;'),
    ('rq AD / merge bits lost', '(s.rq & ~0xF0u) | 0x10u;', '(s.rq & 0xFu) | 0x10u;'),
]


def fnv_record(words):
    data = struct.pack(f'<{len(words) - 1}I', *words[:-1])
    h = 2166136261
    for b in data:
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return struct.pack(f'<{len(words)}I', *words[:-1], h)


def cpu2_source(tmp):
    """(a v0.7.38test BIN whose record selects hbin 2, the v0.7.39test record of the same selection at ISP HBIN 1, the
    camera that made it): the selection is driven on today's build, saved by the real rec_write, then hbin 2 put in"""
    c = TS.boot()
    keys = CPU2_KEYS
    states = TS.page_states([dict(name='cpu2 twin', keys=keys)])[0]['states']
    assert TS.drive(c, keys, states) == [], 'the page and the camera differ on the CPU x2 twin sequence'
    c.layout()                                                          # leave(): rec_write
    info = TS.blob()[1]
    off, n = info['rec_off'], 4 * SL.REC_WORDS
    want = c.written[TS.PATH][off:off + n]
    w = list(struct.unpack(f'<{SL.REC_WORDS}I', want))
    assert w[REC_HB] == 1 and (w[REC_RQ] >> 4 & 0xF) == 1 and w[REC_RQ + 1] == 1, w
    w[REC_HB] = 2
    w[REC_RQ] = (w[REC_RQ] & ~0xF0) | 0x20
    old = bytearray((FROZEN / CPU2_FROM).read_bytes())
    old_off = struct.unpack_from('<5I', old, SL.B.SL4_HEADER_LEN)[4]
    old[old_off:old_off + n] = fnv_record(w)
    path = pathlib.Path(tmp) / CPU2_FROM
    path.write_bytes(bytes(old))
    return path, want, c


def cpu2_problems(src, want, c, slqs_src=None):
    """what is wrong with the v0.7.39test boot of `src` (hbin 2 saved): [] when ISP HBIN 1 is restored exactly"""
    if slqs_src is None:
        default, migrated = TS.blob(), SL.build(settings_from=src)
    else:
        default, migrated = SL.build(src=slqs_src), SL.build(src=slqs_src, settings_from=src)
    saved = dict(TS._built)
    TS._built['b'] = default                                            # fn_addr: this build's offsets
    try:
        d = TS.boot(card=migrated[0])
        info = migrated[1]
        state = TQ.T.blocks(d)[SL.file_name()] + info['state_off']
        bad = []
        if d.w(state + 272) != 1:
            return ['record not loaded']
        sel = struct.unpack('<63I', bytes(d.mu.mem_read(state + 16, 252)))
        if sel[SEL_HB] != 1:
            bad.append(('rd[K_HB]', sel[SEL_HB]))
        if sel[SEL_RQ] != struct.unpack_from('<I', want, 4 * REC_RQ)[0]:
            bad.append(('rq', hex(sel[SEL_RQ])))
        fn = TQ.T.blocks(d)[SL.file_name()] + info['code_off'] + info['functions']['rec_pack']
        out = TS.F6.FAKE + 0x9000
        d.call(fn & ~1, r0=state + 16, r1=out, thumb=bool(fn & 1))
        if bytes(d.mu.mem_read(out, 4 * SL.REC_WORDS)) != want:
            bad.append('the loaded selection is not the ISP HBIN 1 one')
        a, b = TS.ap_sel(c), TS.ap_sel(d)
        if (b['hbin'], b['vbin'], b['key']) != (1, 1, a['key']):
            bad.append(('apply selection', b['hbin'], b['vbin'], b['key']))
        if [TS.tile(d, k)[:3] for k in range(6)] != [TS.tile(c, k)[:3] for k in range(6)]:
            bad.append(('tiles', [TS.tile(d, k) for k in range(6)]))
        return bad
    finally:
        TS._built.clear()
        TS._built.update(saved)


class CpuX2Removed(unittest.TestCase):
    def test_a_saved_cpu_x2_selection_restores_isp_hbin_1(self):
        """v0.7.39test: a v0.7.38test record with hbin 2 (CPU x2, ISP HBIN option 13) loads, and the camera selects
        ISP HBIN 1 -- the same recipe a v0.7.39test user gets with ISP HBIN 1 picked -- not a refusal, not ISP 3"""
        with tempfile.TemporaryDirectory(prefix='sl-cpu2-') as t:
            src, want, c = cpu2_source(t)
            self.assertEqual(SL.settings_record(src)[0][4 * REC_HB:4 * REC_HB + 4], struct.pack('<I', 2))
            self.assertEqual(cpu2_problems(src, want, c), [])
            EVIDENCE['cpu2_migration'] = dict(source=CPU2_FROM, keys=CPU2_KEYS, restored_hbin=1,
                                              apply=TS.ap_sel(c), tiles=[TS.tile(c, k)[:3] for k in range(6)])


def cpu2_mutate():
    """the CPU x2 migration's mutants: each must make cpu2_problems() non-empty"""
    src_c = SL.SOURCE.read_text()
    survived = []
    with tempfile.TemporaryDirectory(prefix='sl-cpu2-') as t:
        src, want, c = cpu2_source(t)
        for i, (label, old, new) in enumerate(CPU2_MUTANTS):
            assert src_c.count(old) == 1, label
            p = SL.SOURCE.parent / f'.mut_cpu2_{os.getpid()}_{i}.c'   # next to slqs.c: it #includes qrdec.c
            p.write_text(src_c.replace(old, new))
            try:
                bad = cpu2_problems(src, want, c, slqs_src=p)
            finally:
                p.unlink()
            print(f'  {"caught " if bad else "SURVIVED"}  {label}  {bad[:2]}', flush=True)
            if not bad:
                survived.append(label)
    print(f'{len(CPU2_MUTANTS) - len(survived)} of {len(CPU2_MUTANTS)} caught')
    return survived


def main():
    global FIXTURE, FROZEN
    if sys.argv[1:] == ['--mutate-cpu2']:
        raise SystemExit(1 if cpu2_mutate() else 0)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=pathlib.Path, default=OUT)
    parser.add_argument('--fixture', type=pathlib.Path, default=FIXTURE)
    parser.add_argument('--frozen', type=pathlib.Path, default=FROZEN, help='directory of independently frozen default BINs')
    a = parser.parse_args()
    FIXTURE, FROZEN = a.fixture.resolve(), a.frozen.resolve()
    if TQ.T.Uc is None or not TQ.IMG:
        raise SystemExit('Unicorn/firmware unavailable: migration remains unverified')
    a.out.mkdir(parents=True, exist_ok=True)
    transcript = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(stream=transcript, verbosity=2).run(suite)
    (a.out / 'tests.txt').write_text(transcript.getvalue())
    print(transcript.getvalue(), end='')
    for sid, item in BUILT.items():
        for kind in ('default', 'migrated'):
            data, info = item[kind]
            out = a.out / kind
            (out / 'fpSup').mkdir(parents=True, exist_ok=True)
            (out / 'fpSup' / item['module'].file_name()).write_bytes(data)
            (out / f'{sid}-build.json').write_text(json.dumps(info, indent=2) + '\n')
    report = dict(status='PASS_OFFLINE' if result.wasSuccessful() else 'FAIL', tests=result.testsRun,
                  failures=len(result.failures), errors=len(result.errors), evidence=EVIDENCE,
                  models='test_qsct/test_slqs file, UI and settings services; native v4 loader and both sup ARM entries/record code execute',
                  fixture=str(FIXTURE), frozen=str(FROZEN), physical_camera_test=False,
                  source_sha256={str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in
                                 (pathlib.Path(SL.__file__), pathlib.Path(QC.__file__), pathlib.Path(__file__))})
    (a.out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
