#!/usr/bin/env python3
"""Offline menu page validation. ARM parser/applier execute; GUI is not rendered.

The small action/cap model below checks the declared runtime contract, not
native event scheduling. Native parser tests use the fixed construction-service
allow-list; ARM FPUI tests stub allocation/cache publication only.
"""
import pathlib
import functools
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import io

import slm_page as P

sys.path.insert(0, str(P.HERE.parent / 'apply'))
import test_pb_page as PB
import test_apply as T


@functools.lru_cache(None)
def native_code():
    with tempfile.TemporaryDirectory(prefix='slm-fpui-') as d:
        d = pathlib.Path(d)
        src, obj = d / 'ui.c', d / 'ui.o'
        src.write_text('#include "fpui_stock.c"\n'
                       'static int borrow(const struct sl_svc *s,const void *lo,const void *hi) {'
                       '(void)s; ((volatile uint32_t*)0x484f0000)[0]=(uintptr_t)lo;'
                       '((volatile uint32_t*)0x484f0000)[1]=(uintptr_t)hi; return 0;}\n'
                       '__attribute__((used)) uint32_t pb_apply(uintptr_t b,uint32_t n,struct uia_outcome *o) {'
                       'struct sl_svc svc={.version=7,.borrow=borrow};'
                       'return fpui_stock_apply(&svc,(void*)b,n,o);}\n')
        subprocess.run([shutil.which('clang'), *T.BA.CFLAGS, '-I', str(P.ROOT / 'fpSup/fpsup-ui'),
                        '-I', str(P.ROOT / 'fpSup/loader-v4'), '-c', str(src), '-o', str(obj)],
                       check=True, capture_output=True, text=True)
        return T.BA.link_flat(obj.read_bytes())


def records(page):
    return [r.to_bytes() for r in P.B.N.split(page)]


def semantic(page, pool, schemas):
    """Native records with typed string refs replaced by resolved texts."""
    result = []
    for r in records(page):
        rr, ss = bytearray(r), []
        for at, kind in P.S.typed_fields(r, pool, schemas):
            if kind in ('str', 'text'):
                v = P.u32(r, at)
                ss.append((at, None if v == 0xFFFFFFFF else pool.text(v)))
                rr[at:at + 4] = bytes(4)
        result.append((bytes(rr), ss))
    return result


class UiCam(PB.UiCam):
    DATA, RESULT = 0xCA000000, T.WORK + 0x170000

    def __init__(self):
        super().__init__()
        code, self.ui_funcs = native_code()
        self.mu.mem_write(T.BLOB, code)
        self.mu.mem_map(self.DATA, 0x20000)
        self.put(self.READER + 0xA8, len(P.pages()))
        for i, p in enumerate(P.pages()):
            self.put(self.TABLE + i * 44 + 4, self.NAME + i * 32)
            self.put(self.TABLE + i * 44 + 8, p.base - P.NBU)
            self.mu.mem_write(self.NAME + i * 32, p.name.encode() + b'\0')

    def apply_menu(self, block=None):
        block = P.build() if block is None else block
        self.mu.mem_write(self.DATA, block)
        result = self.call(T.BLOB + self.ui_funcs['pb_apply'], self.DATA, len(block), self.RESULT)
        pages = [(P.NBU + self.w(self.TABLE + i * 44 + 8)) & 0xFFFFFFFF for i in range(len(P.pages()))]
        return result, pages

    def text(self, offset):
        if offset < len(P.pages()[0].im.pool):
            return P.pages()[0].im.text(offset)
        # fpui_stock stores the private text's uncached address as its ID.
        address = offset + 0x80000000 if 0x40000000 <= offset < 0x80000000 else offset
        data = bytes(self.mu.mem_read(address, 64))
        return data.split(b'\0', 1)[0].decode()


class PageStructure(unittest.TestCase):
    def test_header_current_pack_private_and_format_grey(self):
        self.assertEqual((P.HERE / 'slm_page.h').read_text(), P.header())
        pack = P.CSV.inspect_pack(P.pack())
        self.assertEqual(set(pack), {'SLM_RES', 'SLM_FPS', 'SLM_BIT', 'SLM_FORMAT'})
        self.assertEqual(P.M.parse_csv(pack['SLM_FORMAT']), [('0302', True), ('0303', False)])
        self.assertEqual(P.M.parse_csv(pack['SLM_BIT']), list(P.M.BIT_ROWS))
        self.assertLessEqual(len(P.fpui.decode(P.build())[0]), 64)

    def test_budget_graph_typed_refs_and_local_namespaces(self):
        for p in P.pages():
            old = P.S.page_shape(p.stock, p.pool)
            new = P.S.page_shape(p.assemble(), p.pool)
            self.assertEqual(old['header_minus_actual'], new['header_minus_actual'], p.name)
            self.assertEqual((new['orphans'], new['bad_child_counts']), ([], []))
            ids = set(new['objects'])
            old_ids = set(old['objects'])
            old_missing = {P.u32(r, at) for r in records(p.stock)
                           for at, kind in P.S.typed_fields(r, p.pool, p.im.schemas)
                           if kind == 'obj' and P.u32(r, at) not in old_ids | {0, 0xFFFFFFFF}}
            missing = set()
            used = {}
            for r in records(p.assemble()):
                for at, kind in P.S.typed_fields(r, p.pool, p.im.schemas):
                    v = P.u32(r, at)
                    if kind == 'obj' and v not in (0, 0xFFFFFFFF):
                        if v not in ids:
                            missing.add(v)
                if P.u32(r, 0) in (0x10006, 0x1000A):
                    owner = P.B.owner(r)
                    local = P.u32(r, 28 if P.u32(r, 0) == 0x10006 else 24)
                    self.assertNotIn((owner, local), used, (p.name, owner, local))
                    used[owner, local] = True
            self.assertEqual(missing, old_missing, p.name)

    def test_reference_applier_matches_builder(self):
        target, pool = P.applied()
        for p in P.pages():
            self.assertEqual(semantic(bytes(target[p.name].data), pool, p.im.schemas),
                             semantic(p.assemble(), p.pool, p.im.schemas))

    def test_renamed_subtrees_leave_stock_other_rows_unchanged(self):
        for p in P.pages():
            affected = set()
            for key, row in P.B.ROWS.items():
                if row['page'] == p.name:
                    affected |= P.B.subtree(p.objs, row['root'])
                    names = set()
                    for r in records(p.assemble()):
                        if P.B.owner(r) in P.B.subtree(p.objs, row['root']):
                            names |= {p.pool.text(P.u32(r, at)) for at, k in P.S.typed_fields(r, p.pool, p.im.schemas)
                                      if k in ('str', 'text')}
                    self.assertFalse(set(row['rename']) & names, (key, set(row['rename']) & names))
            for r in p.out:
                if id(r) not in p.old:
                    continue
                off, raw = p.old[id(r)]
                # Allowed external edits: allocation header, root child count,
                # recording format's model name. All unrelated original rows stay exact.
                if off == 0 or P.B.owner(r) in affected or P.B.owner(r) == 1:
                    continue
                expected = bytearray(raw)
                for at, k in p.typed(r):
                    if k in ('str', 'text') and p.pool.text(P.u32(raw, at)) == 'B2_5_1':
                        P.put(expected, at, p.pool.intern('SLM_FORMAT')[0])
                self.assertEqual(bytes(r), bytes(expected), (p.name, off, P.B.owner(r)))

    def test_max_index_bindings_all_clamps_cursor_pairs_and_shrink(self):
        for key, s in P.SPEC.items():
            p = next(p for p in P.pages() if p.name == P.B.ROWS[key]['page'])
            for part in ('select', 'lst', 'icon'):
                if part not in s:
                    continue
                oid = s[part]
                cv = next(r for r in p.records(oid, 0x1000E) if p.pool.text(P.u32(r, 8)) == 'controlValue')
                self.assertEqual(struct.unpack_from('>f', cv, p.field(cv, 'max-value'))[0], s['cap'] - 1)
                binding = [r for r in p.records(oid, 0x10006) if p.pool.text(P.u32(r, 8)) == 'appVariableEvent'
                           and p.pool.text(P.u32(r, 40)) == 'SLM_' + s['var'] + 'N']
                self.assertEqual(len(binding), 1)
                r = binding[0]
                self.assertEqual((len(r), P.u32(r, 36), P.u32(r, 45), p.pool.text(P.u32(r, 49))),
                                 (58, 1, P.u32(cv, 24), 'max-value'))
            vals = [int(struct.unpack_from('>f', r, 40)[0]) for r in p.records(s['lst'], 0x10006)
                    if p.pool.text(P.u32(r, 8)) == 'controlValueEvent' and P.u32(r, 32) == 3]
            if key != 'DC':
                self.assertEqual(vals, list(range(1, s['cap'])))
                item = next(r for r in p.records(s['item'], 0x1000E))
                self.assertEqual(struct.unpack_from('>f', item, p.field(item, 'max-value'))[0], s['cap'])
            # Declared post order: model -> max-index -> current index. Once N
            # is delivered all three clamps must use the same reduced max.
            for count in range(2, s['cap'] + 1):
                cap = count - 1
                for previous in range(s['cap']):
                    clamped = min(previous, cap)
                    self.assertLess(clamped, count)
                    self.assertEqual(min(clamped, cap), clamped)

    def test_confirm_pulses_only_follow_native_commit_and_same_custom_reopens(self):
        for key, s in P.SPEC.items():
            p = next(p for p in P.pages() if p.name == P.B.ROWS[key]['page'])
            picks = []
            for i, r in enumerate(p.out):
                if P.u32(r, 0) != 0x10009 or p.pool.text(P.u32(r, 8)) != 'controlAppVariable':
                    continue
                ff = P.B.fields(p.im, r)
                if not any(pr == 'destination-variable' and p.pool.text(P.u32(r, at)) == 'SLM_Pick' + s['var']
                           for at, pr, k, c in ff):
                    continue
                picks.append((i, r))
            self.assertEqual(len(picks), 2 if key == 'FPS' else 4)
            for j in range(0, len(picks), 2):
                i, reset = picks[j]
                _, pick = picks[j + 1]
                original = p.out[i - 1]
                self.assertEqual(p.pool.text(P.u32(original, 36)), 'SLM_' + s['var'])
                self.assertEqual(P.u32(reset, 32), 0x81)
                self.assertEqual(p.pool.text(P.u32(reset, 41)), '-1')
                self.assertEqual(P.u32(pick, 45), s['lst'])
                self.assertEqual(P.u32(reset, 24), P.u32(pick, 24))
                if key == 'FPS':
                    self.assertEqual((P.u32(pick, 20), P.u32(pick, 24)), (29812, 3))
                    # Grey handling's native Help event2 is byte-identical;
                    # new writes occur only in Help event3, equal-value1.
                    event = next(r for r in p.records(29812, 0x10006) if P.u32(r, 28) == 3)
                    self.assertEqual((P.u32(event, 32), P.u32(event, 40)), (3, 0x3F800000))
                    for rr in p.records(29812):
                        if P.u32(rr, 0) == 0x10009 and P.u32(rr, 24) == 2:
                            self.assertEqual(bytes(rr), p.old[id(rr)][1])
            # Watcher ignores -1, reads only Pick, and therefore sees same-row
            # confirmations twice while programmatic VALUE posts see none.
            selected, watched, calls = s['cap'] - 1, -1, []
            for confirmation in range(2):
                for value in (-1, selected):
                    if value != watched and value >= 0:
                        calls.append(value)
                    watched = value
            self.assertEqual(calls, [selected, selected])

    def test_dc_all_seven_labels_and_cursors_fit_the_viewport(self):
        p = P.pages()[1]
        rr = records(p.assemble())
        ob = {P.u32(r, 20): r for r in rr if P.u32(r, 0) == 0x10003}
        roots = [o for o, r in ob.items() if P.u32(r, 24) == 21884 and p.pool.text(P.u32(r, 28)).isdigit()]
        self.assertEqual(len(roots), 7)
        labels = []
        for oid in sorted(roots, key=lambda o: p.pool.text(P.u32(ob[o], 28))):
            child = {o for o, r in ob.items() if P.u32(r, 24) == oid}
            text = next(r for r in rr if P.B.owner(r) in child and P.u32(r, 0) == 0x10005
                        and p.pool.text(P.u32(r, 8)) == 'drawText')
            labels.append(p.pool.text(P.u32(text, p.field(text, 'text'))))
        self.assertEqual(labels, [x[0] for x in P.M.DCS] + ['CUSTOM'])
        for oid, cid in ((31938, 1), (21890, 2)):
            r = next(r for r in rr if P.u32(r, 0) == 0x1000A and P.B.owner(r) == oid and P.u32(r, 24) == cid)
            c = P.A.parse_clip(P.A.Record(0, r), p.pool.text)
            self.assertEqual([k['value'] for k in c['properties'][0]['keys']], [float(i * 69) for i in range(7)])
        group = next(r for r in rr if P.u32(r, 0) == 0x1000B and P.B.owner(r) == 21879
                     and p.pool.text(P.u32(r, 20)) == 'DCCropCFix')
        self.assertEqual(P.u32(group, 36), 200)

    def test_go_uses_shared_mutable_request_and_known_change_form(self):
        for p in P.pages():
            oid = next(P.u32(r, 20) for r in p.out if P.u32(r, 0) == 0x10003
                       and p.pool.text(P.u32(r, 28)) == 'SLM_GoEvent')
            e = p.records(oid, 0x10006)[0]
            self.assertEqual((len(e), P.u32(e, 32), P.u32(e, 41)), (45, 3, 3))
            self.assertEqual(p.pool.text(P.u32(e, 36)), 'SLM_Go')
            actions = p.records(oid, 0x10009)
            self.assertEqual(len(actions), 5)
            self.assertEqual(p.pool.text(P.u32(actions[2], 36)), P.REQUEST_RESERVE)
            # The fixed native QS request must not remain on the added event:
            # it would jump again when the menu is reconstructed.
            self.assertNotEqual(p.pool.text(P.u32(actions[2], 36)), 'QS')
            self.assertEqual(p.pool.text(P.u32(actions[3], 36)), 'MENU_ReturnScreen')
            # Every source field except owner/event/action ID and the one QS
            # request is an exact copy of this page's native QS sequence.
            native_owner = next(o for o, (_par, name) in p.objs.items() if name == 'CommonSystemKeyEvent')
            native_event = next(r for r in p.records(native_owner, 0x10006) if p.pool.text(P.u32(r, 20)) == 'QS')
            native = [r for r in p.records(native_owner, 0x10009) if P.u32(r, 24) == P.u32(native_event, 28)]
            for i, (r, src) in enumerate(zip(actions, native)):
                want = bytearray(src)
                for at in (20, 24, 28):
                    want[at:at + 4] = r[at:at + 4]
                if i == 2:
                    want[36:40] = r[36:40]
                self.assertEqual(bytes(r), bytes(want))
        import re
        off = int(re.search(r'SLM_REQUEST_OFFSET (\d+)u', P.header()).group(1))
        self.assertEqual(P.build()[off:off + len(P.REQUEST_RESERVE)], P.REQUEST_RESERVE.encode())

    def test_format_change_uses_native_binding_and_private_refresh_pulse(self):
        for p in P.pages():
            owner, = [P.u32(r, 20) for r in p.out if P.u32(r, 0) == 0x10003 and
                      p.pool.text(P.u32(r, 28)) == 'SLM_FormatEvent']
            event, = p.records(owner, 0x10006)
            self.assertEqual((len(event), P.u32(event, 16), P.u32(event, 32), P.u32(event, 41)),
                             (45, 2, 3, 3))
            self.assertEqual(p.pool.text(P.u32(event, 36)), 'MV_RecordingFormat')
            actions = p.records(owner, 0x10009)
            self.assertEqual(len(actions), 2)
            for i, (r, value) in enumerate(zip(actions, ('-1', '1')), 1):
                self.assertEqual((len(r), P.u32(r, 24), P.u32(r, 28), P.u32(r, 32)), (46, 1, i, 0x81))
                self.assertEqual(p.pool.text(P.u32(r, 8)), 'controlAppVariable')
                self.assertEqual(p.pool.text(P.u32(r, 36)), 'SLM_Refresh')
                self.assertEqual(p.pool.text(P.u32(r, 41)), value)
                self.assertEqual((r[40], r[45]), (0, 0))

    def test_actual_lossless_row_composes_in_both_orders(self):
        import build_fpui as LOSS
        lossless, info, _ = LOSS.build()
        lp = P.pages()[1]
        loss_pool = P.fpui.Strings(lp.im.pool)
        loss_target = {lp.name: P.fpui.PageCopy(lp.stock, len(lp.stock), lp.first)}
        P.fpui.apply(lossless, loss_target, loss_pool)
        loss_budget = P.S.page_shape(bytes(loss_target[lp.name].data), loss_pool)['header_minus_actual']
        for order in ((lossless, P.build()), (P.build(), lossless)):
            pool = P.fpui.Strings(P.pages()[0].im.pool)
            target = {p.name: P.fpui.PageCopy(p.stock, len(p.stock), p.first) for p in P.pages()}
            for blob in order:
                P.fpui.apply(blob, target, pool)
            p = P.pages()[1]
            page = bytes(target[p.name].data)
            result = P.S.page_shape(page, pool)
            self.assertEqual((result['orphans'], result['bad_child_counts']), ([], []))
            self.assertEqual(len(result['objects']), len(p.objs) + p.next - p.first + info['objects'])
            self.assertEqual(result['header_minus_actual'], loss_budget)
            names = [o['name'] for o in result['objects'].values()]
            self.assertEqual(names.count('SLM_DcSummary'), 1)
            self.assertEqual(names.count('fpLossless_Row_GATED'), 1)


class Native(unittest.TestCase):
    def test_native_firmware_parses_both_pages(self):
        for p in P.pages():
            q = P.S.native_parse(p.assemble(), bytes(p.pool.data), p.im.img)
            self.assertFalse(q.error_flag())
            self.assertEqual(len(q.traces), len(records(p.assemble())))

    def test_arm_fpui_stock_composes_both_pages_and_guards_reinstall(self):
        cam = UiCam()
        result, target = cam.apply_menu()
        self.assertEqual(result, 0, (result, cam.w(cam.RESULT + 4)))
        self.assertEqual((cam.w(0x484f0000), cam.w(0x484f0004)), (cam.DATA, cam.DATA + len(P.build())))
        for p, at in zip(P.pages(), target):
            self.assertEqual(semantic(bytes(cam.mu.mem_read(at, len(p.assemble()))), cam, p.im.schemas),
                             semantic(p.assemble(), p.pool, p.im.schemas))
            self.assertEqual(bytes(cam.mu.mem_read(p.base, len(p.stock))), p.stock)
        again, same = cam.apply_menu()
        self.assertEqual((again, same), (4, target))
        # Both page actions hold the resident request ID, so clearing/filling
        # the one buffer changes both without editing either composed page.
        import re
        off = int(re.search(r'SLM_REQUEST_OFFSET (\d+)u', P.header()).group(1))
        for value in (b'\0', b'QS\0', b'\0'):
            cam.mu.mem_write(cam.DATA + off, value)
            for p, at in zip(P.pages(), target):
                rr = records(bytes(cam.mu.mem_read(at, len(p.assemble()))))
                go = next(P.u32(r, 20) for r in rr if P.u32(r, 0) == 0x10003
                          and cam.text(P.u32(r, 28)) == 'SLM_GoEvent')
                actions = [r for r in rr if P.u32(r, 0) == 0x10009 and P.B.owner(r) == go]
                self.assertEqual(cam.text(P.u32(actions[2], 36)), value.rstrip(b'\0').decode())

    def test_guard_failure_publishes_neither_page(self):
        ss, ops, frag = P.fpui.decode(P.build())
        block = P.fpui.Block(); block.strings = ss; block.ops = ops; block.frag = bytearray(frag)
        # Fail in the second page: the first is still uncommitted.
        i = max(i for i, (op, args) in enumerate(ops) if op == P.fpui.OP_GUARD)
        code, args = ops[i]
        block.ops[i] = (code, [args[0], args[1] ^ 1])
        cam = UiCam()
        result, pages = cam.apply_menu(block.encode())
        self.assertEqual((result, pages), (4, [p.base for p in P.pages()]))


def mutate():
    """In-memory isolated page mutants; no camera/source/generated header writes."""
    def cap_missing(pp):
        pp[0].cap(P.SPEC['FPS']['icon'], 8)
    def wrong_binding(pp):
        p = pp[0]
        r = next(r for r in p.records(4439, 0x10006) if p.pool.text(P.u32(r, 8)) == 'appVariableEvent'
                 and p.pool.text(P.u32(r, 40)) == 'SLM_FpsN')
        P.put(r, 36, 0)
    def no_reset(pp):
        p = pp[0]
        r = next(r for r in p.records(29812, 0x10009) if P.u32(r, 32) == 0x81)
        p.text(r, 41, '0')
    def bypass_grey(pp):
        p = pp[0]
        for r in p.records(29812, 0x10009):
            if p.pool.text(P.u32(r, 36)) == 'SLM_PickFps':
                P.put(r, 24, 2)
    def fixed_cursor(pp):
        p = pp[1]
        r = next(r for r in p.records(21879, 0x1000B) if p.pool.text(P.u32(r, 20)) == 'DCCropCFix')
        P.put(r, 36, 66)
    def fixed_request(pp):
        p = pp[0]
        r = next(r for r in p.out if P.u32(r, 0) == 0x10009 and len(r) >= 40
                 and p.pool.text(P.u32(r, 36)) == P.REQUEST_RESERVE)
        p.text(r, 36, 'QS')
    def no_format_pulse(pp):
        p = pp[0]
        r = next(r for r in p.out if P.u32(r, 0) == 0x10009 and len(r) == 46 and
                 p.pool.text(P.u32(r, 36)) == 'SLM_Refresh' and p.pool.text(P.u32(r, 41)) == '1')
        p.text(r, 41, '-1')
    cases = [
        ('IconChange retains stock clamp', cap_missing, 'test_max_index_bindings_all_clamps_cursor_pairs_and_shrink'),
        ('max-index binding uses text type', wrong_binding, 'test_max_index_bindings_all_clamps_cursor_pairs_and_shrink'),
        ('Pick reset is not -1', no_reset, 'test_confirm_pulses_only_follow_native_commit_and_same_custom_reopens'),
        ('FPS Pick before grey validation', bypass_grey, 'test_confirm_pulses_only_follow_native_commit_and_same_custom_reopens'),
        ('DC selected cursor remains three rows', fixed_cursor, 'test_dc_all_seven_labels_and_cursors_fit_the_viewport'),
        ('Go request stays fixed QS', fixed_request, 'test_go_uses_shared_mutable_request_and_known_change_form'),
        ('format event never sends a positive pulse', no_format_pulse, 'test_format_change_uses_native_binding_and_private_refresh_pulse'),
    ]
    original = P.pages
    missed = []
    try:
        for name, mutate_page, test in cases:
            original.cache_clear()
            pp = original()
            mutate_page(pp)
            P.pages = lambda: pp
            result = unittest.TextTestRunner(stream=io.StringIO()).run(PageStructure(test))
            caught = bool(result.failures) and not result.errors
            print(('caught ' if caught else 'MISSED ') + name)
            if not caught:
                missed.append(name)
            P.pages = original
    finally:
        P.pages = original
        original.cache_clear()
    return missed


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        sys.exit(bool(mutate()))
    unittest.main()
