#!/usr/bin/env python3
"""SensorLab's stock menu edits as one composable FPUI block and a modelCSV NBR.

Generate slm_page.h offline. The runtime registers variables and the pack, fills
RES/FPS, then installs SLM_PAGE from a UI callback. N means max index, not count.
All choices pulse Pick=-1 then Pick=selected only at the native commit action.
"""
import functools
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / 'projects/open-gate/build'),
               str(ROOT / 'fpSup/uishare'), str(ROOT / 'research/ui/tools')]
import b25_plan as B
import menu_lists as M
import sl_b25_page as S
import sl_lab_page as L
import sl_lists as CSV
from ui import fpui, rows as FROWS
import native_ui_audit as A
import nbr

u32, put = B.u32, S.put
NBU = 0xC18C0460
REQUEST_RESERVE = 'SLM_QS_REQUEST'
SPEC = {
    'RES': dict(var='Res', select=4254, lst=4259, item=4260, icon=4258, name=4267, cap=10),
    'FPS': dict(var='Fps', select=4434, lst=4439, item=4440, icon=4438, name=4447, cap=50),
    'DC': dict(var='Dc', select=21879, lst=21883, item=21884, name=21891, cap=7),
}


class Page:
    def __init__(self, im, name, pool):
        self.im, self.name, self.pool = im, name, pool
        self.base, self.stock, self.objs, rr = B.walk(im, name)
        self.out = [bytearray(r) for o, r in rr]
        self.old = {id(r): (o, bytes(r)) for r, (o, _) in zip(self.out, rr)}
        self.extra = {}  # insertions within original records, in stock coordinates
        self.first = self.next = max(self.objs) + 1
        self.refs = []

    def typed(self, r):
        raw = self.old[id(r)][1] if id(r) in self.old else r
        return S.typed_fields(raw, self.pool, self.im.schemas)

    def obj(self, oid):
        return next(r for r in self.out if u32(r, 0) == 0x10003 and u32(r, 20) == oid)

    def records(self, oid, tag=None):
        return [r for r in self.out if B.owner(r) == oid and (tag is None or u32(r, 0) == tag)]

    def text(self, r, at, value, literal=False):
        put(r, at, self.pool.intern(value)[0])
        if literal:
            r[at + 4] = 0

    def insert(self, r, at, data):
        """Add bytes within an original record without losing its source coordinates."""
        assert id(r) in self.old
        pos = self.old[id(r)][0] + at
        self.extra.setdefault(pos, []).append(bytearray(data))
        put(r, 4, u32(r, 4) + len(data))

    def after(self, r, seq):
        at = next(i for i, x in enumerate(self.out) if x is r) + 1
        self.out[at:at] = seq

    def local(self, oid):
        ks = [k for k, r in enumerate(self.out) if B.owner(r) == oid]
        return max(S.local_ids(self.out, ks), default=0) + 1

    def component(self, oid, r):
        self.after(self.records(oid)[-1], [r])
        o = self.obj(oid)
        put(o, 8, u32(o, 8) + 1)

    def field(self, r, prop):
        return next(at for at, p, k, c in B.fields(self.im, r) if p == prop)

    def cap(self, oid, n):
        ctl = next(r for r in self.records(oid, 0x1000E) if self.pool.text(u32(r, 8)) == 'controlValue')
        struct.pack_into('>f', ctl, self.field(ctl, 'max-value'), float(n))
        return ctl

    def bind_caps(self, spec):
        for part in ('select', 'lst', 'icon'):
            if part not in spec:
                continue
            oid = spec[part]
            ctl = self.cap(oid, spec['cap'] - 1)
            self.component(oid, L._binding(oid, self.local(oid), 'SLM_' + spec['var'] + 'N',
                                         u32(ctl, 24), 'max-value', self.pool, self.refs, 1))

    def rename(self, key):
        row = B.ROWS[key]
        ids = B.subtree(self.objs, row['root'])
        for r in self.out:
            if B.owner(r) not in ids:
                continue
            for at, kind in self.typed(r):
                if kind not in ('str', 'text'):
                    continue
                old = self.pool.text(u32(r, at))
                if old in row['rename']:
                    self.text(r, at, row['rename'][old])

    def summary(self, key):
        spec = SPEC[key]
        ids = B.subtree(self.objs, B.ROWS[key]['root'])
        summary_ids = {o for o in ids if self.objs[o][1].startswith('IconText')}
        for r in self.out:
            if B.owner(r) not in summary_ids:
                continue
            for at, prop, kind, comp in B.fields(self.im, r):
                if comp == 'drawText' and prop == 'text':
                    self.text(r, at, ' ', True)
            if u32(r, 0) == 0x1000A:
                # DC has animated summary text as well as its initial drawText.
                for at, what in B.clip_strings(r):
                    if what == 'clip key':
                        self.text(r, at, ' ')
        src = self.records(spec['name'])
        obj = bytearray(next(r for r in src if u32(r, 0) == 0x10003))
        base = bytearray(next(r for r in src if u32(r, 0) == 0x10004))
        text = bytearray(next(r for r in src if u32(r, 0) == 0x10005))
        clip = bytearray(next(r for r in src if u32(r, 0) == 0x1000A))
        oid = self.next
        self.next += 1
        put(obj, 20, oid); put(obj, 8, 4); put(obj, 16, 0)
        self.text(obj, 28, 'SLM_' + spec['var'] + 'Summary')
        for r in (base, text, clip):
            put(r, 20, oid)
        assert u32(base, 28) == 3
        struct.pack_into('>f', base, 32, L.RATE_VALUE_X)
        struct.pack_into('>f', base, 40, L.RATE_VALUE_W)
        assert len(text) == 57 and u32(text, 28) == 0x40000011
        text = text[:28] + struct.pack('>I', 0x40000001) + text[32:37] + text[41:]
        put(text, 4, len(text))
        struct.pack_into('>f', text, len(text) - 8, L.RATE_VALUE_W)
        self.text(text, 32, ' ', True)
        put(clip, 24, 2)
        bind = L._binding(oid, 3, 'SLM_' + spec['var'] + 'Text', u32(text, 24),
                          'text', self.pool, self.refs, 0)
        self.after(src[-1], [obj, base, text, clip, bind])
        parent = self.obj(u32(obj, 24))
        put(parent, 16, u32(parent, 16) + 1)
        # Give the added text the same native dimming as the row title.
        group = next(r for r in self.records(spec['select'], 0x1000B)
                     if self.pool.text(u32(r, 20)) == 'SelectLock')
        self.insert(group, len(group) - 8, struct.pack('>II', oid, 2))
        put(group, 16, u32(group, 16) + 1)

    def cursor_pairs(self, spec):
        oid = spec['lst']
        evs = {int(struct.unpack_from('>f', r, 40)[0]): r for r in self.records(oid, 0x10006)
               if self.pool.text(u32(r, 8)) == 'controlValueEvent' and u32(r, 32) == 3}
        focus = {u32(r, 24): r for r in self.records(oid, 0x10009)
                 if self.pool.text(u32(r, 8)) == 'controlFocus' and u32(r, 40) == oid}
        last = max(evs)
        assert set(evs) == set(range(1, last + 1))
        e0 = evs[last]
        f0 = focus[u32(evs[last - 1], 28)]
        local = self.local(oid)
        added = []
        for value in range(last + 1, spec['cap']):
            e, f = bytearray(e0), bytearray(f0)
            self.text(e, 20, str(value + 1)); put(e, 28, local)
            struct.pack_into('>f', e, 40, float(value))
            put(f, 24, local); self.text(f, 44, str(value))
            added += [e, f]
            local += 1
        self.after(focus[u32(e0, 28)], added)
        obj = self.obj(oid)
        put(obj, 8, u32(obj, 8) + len(added) // 2)
        # ListItem is the native repeated instance count, unlike the caps.
        self.cap(spec['item'], spec['cap'])

    def picks(self, key):
        spec = SPEC[key]
        dest = 'SLM_' + spec['var']
        commits = [r for r in self.out if u32(r, 0) == 0x10009 and
                   self.pool.text(u32(r, 8)) == 'controlAppVariable' and
                   any(p == 'destination-variable' and self.pool.text(u32(r, at)) == dest
                       for at, p, k, c in B.fields(self.im, r))]
        assert len(commits) == (1 if key == 'FPS' else 2)
        for commit in commits:
            owner, local = u32(commit, 20), u32(commit, 24)
            event = next(r for r in self.records(owner, 0x10006) if u32(r, 28) == local)
            action_ids = [u32(r, 28) for r in self.records(owner, 0x10009) if u32(r, 24) == local]
            aid = max(action_ids) + 1
            # A literal -1 reset followed by a copy of the native list-value action.
            reset = bytearray(commit[:36]) + struct.pack('>I', self.pool.intern('SLM_Pick' + spec['var'])[0])
            reset += b'\0' + struct.pack('>I', self.pool.intern('-1')[0]) + b'\0'
            put(reset, 4, len(reset)); put(reset, 28, aid); put(reset, 32, 0x81)
            pick = bytearray(commit)
            self.text(pick, 36, 'SLM_Pick' + spec['var']); put(pick, 28, aid + 1)
            self.after(commit, [reset, pick])
            put(event, 16, u32(event, 16) + 2)

    def go(self):
        owner = next(o for o, (p, n) in self.objs.items() if n == 'CommonSystemKeyEvent')
        qr = self.records(owner)
        ev = next(r for r in qr if u32(r, 0) == 0x10006 and self.pool.text(u32(r, 20)) == 'QS')
        local = u32(ev, 28)
        # Keep the whole native QS sequence, including MENU_ReturnScreen and
        # native defaults. B2_5 requests ClearFlg; MainB2's corresponding
        # state request is literally "zzz". Neither is substituted or guessed.
        acts = [bytearray(r) for r in qr if u32(r, 0) == 0x10009 and u32(r, 24) == local]
        assert len(acts) == 5
        oid = self.next
        self.next += 1
        obj = bytearray(self.obj(owner))
        put(obj, 20, oid); put(obj, 8, 1); put(obj, 16, 0)
        self.text(obj, 28, 'SLM_GoEvent')
        # Exact 45-byte MainY5 type3 form used by fpsup home FT_Go. It also
        # fires when a page is rebuilt, so the request is a mutable resident
        # string, cleared by runtime after install and on each layout leave.
        event = bytearray(struct.pack('>9I', 0x10006, 45, self.pool.find('appVariableChangeEvent'),
                                     8, len(acts), 0xFFFFFFFF, oid, 1, 3))
        event += struct.pack('>I', self.pool.intern('SLM_Go')[0]) + b'\0' + struct.pack('>I', 3)
        for i, r in enumerate(acts, 1):
            put(r, 20, oid); put(r, 24, 1); put(r, 28, i)
            if len(r) >= 40 and self.pool.text(u32(r, 8)) == 'controlAppState' and self.pool.text(u32(r, 36)) == 'QS':
                self.text(r, 36, REQUEST_RESERVE)
        self.after(qr[-1], [obj, event] + acts)
        parent = self.obj(u32(obj, 24))
        put(parent, 16, u32(parent, 16) + 1)

    def format_refresh(self):
        # Native change events use the page's binding observers. They do not
        # occupy the stock variable's single native-controller callback slot.
        owner = next(o for o, (_parent, name) in self.objs.items() if name == 'CommonSystemKeyEvent')
        oid = self.next
        self.next += 1
        obj = bytearray(self.obj(owner))
        put(obj, 20, oid); put(obj, 8, 1); put(obj, 16, 0)
        self.text(obj, 28, 'SLM_FormatEvent')
        event = bytearray(struct.pack('>9I', 0x10006, 45, self.pool.find('appVariableChangeEvent'),
                                     8, 2, 0xFFFFFFFF, oid, 1, 3))
        event += struct.pack('>I', self.pool.intern('MV_RecordingFormat')[0]) + b'\0' + struct.pack('>I', 3)
        reset = next(r for r in self.out if u32(r, 0) == 0x10009 and len(r) == 46 and
                     self.pool.text(u32(r, 8)) == 'controlAppVariable' and u32(r, 32) == 0x81 and
                     self.pool.text(u32(r, 36)).startswith('SLM_Pick'))
        actions = []
        for i, value in enumerate(('-1', '1'), 1):
            r = bytearray(reset)
            put(r, 20, oid); put(r, 24, 1); put(r, 28, i)
            self.text(r, 36, 'SLM_Refresh'); self.text(r, 41, value)
            actions.append(r)
        self.after(self.records(owner)[-1], [obj, event] + actions)
        parent = self.obj(u32(obj, 24))
        put(parent, 16, u32(parent, 16) + 1)

    def dc_popup(self):
        # Seven fixed entries in the native 486px viewport. A 69px pitch fits
        # all seven without inventing a scroll controller for this static list.
        pitch = 69
        roots = (31945, 31942, 31939)
        donor_ids = B.subtree(self.objs, roots[-1])
        donor = [r for r in self.out if B.owner(r) in donor_ids]
        width_group = next(r for r in self.records(21879, 0x1000B)
                           if self.pool.text(u32(r, 20)) == 'submenu_width_NoIcon')
        new_width = []
        for i, label in enumerate([x[0] for x in M.DCS] + [M.CUSTOM]):
            if i < 3:
                seq = self.records(roots[i])
                ids = B.subtree(self.objs, roots[i])
                seq = [r for r in self.out if B.owner(r) in ids]
                root = roots[i]
            else:
                mapping = {v: self.next + k for k, v in enumerate(sorted(donor_ids))}
                self.next += len(mapping)
                seq = [bytearray(r) for r in donor]
                for r in seq:
                    for at, kind in self.typed(r):
                        if kind == 'obj' and u32(r, at) in mapping:
                            put(r, at, mapping[u32(r, at)])
                root = mapping[roots[-1]]
                self.text(seq[0], 28, '%02d' % i)
                self.after(donor[-1], seq)
                o = self.obj(21884); put(o, 16, u32(o, 16) + 1)
                new_width += [(mapping[31940], 2), (mapping[31941], 2)]
            for r in seq:
                if u32(r, 0) == 0x10004:
                    for at, prop, kind, comp in B.fields(self.im, r):
                        if B.owner(r) == root and prop == 'position':
                            struct.pack_into('>f', r, at + 4, float(i * pitch))
                        if prop == 'size':
                            struct.pack_into('>f', r, at + 4, float(pitch - 2))
                elif u32(r, 0) == 0x10005 and self.pool.text(u32(r, 8)) == 'drawText':
                    self.text(r, self.field(r, 'text'), label, True)
                if u32(r, 0) == 0x10005:
                    for at, prop, kind, comp in B.fields(self.im, r):
                        if prop == 'rect':
                            struct.pack_into('>f', r, at + 12, float(pitch - 2))
        self.insert(width_group, len(width_group) - 8,
                    b''.join(struct.pack('>II', *x) for x in new_width))
        put(width_group, 16, u32(width_group, 16) + len(new_width))
        # Both the browsing cursor and the selected-row cursor get seven keys.
        for oid, cid, step in ((31938, 1, 2), (21890, 2, 1)):
            clip = next(r for r in self.records(oid, 0x1000A) if u32(r, 24) == cid)
            assert u32(clip, 12) == 1 and u32(clip, 28) == 3
            for i in range(3):
                struct.pack_into('>f', clip, 54 + 10 * i, float(i * pitch))
            self.insert(clip, len(clip), b''.join(struct.pack('>BBIf', 0, 0, i * step * 100 // 3,
                                                           float(i * pitch)) for i in range(3, 7)))
            put(clip, 28, 7)
            base = next(r for r in self.records(oid, 0x10004))
            struct.pack_into('>f', base, self.field(base, 'size') + 4, float(pitch - 2))
        group = next(r for r in self.records(21879, 0x1000B)
                     if self.pool.text(u32(r, 20)) == 'DCCropCAj')
        states = b''.join(struct.pack('>5IB', self.pool.intern('%02d' % i)[0], i * 200 // 3,
                                      (i * 2 + 1) * 100 // 3, 0, 2, 0) for i in range(3, 7))
        self.insert(group, 28 + 3 * 21, states); put(group, 8, 7)
        fixed = next(r for r in self.records(21879, 0x1000B)
                     if self.pool.text(u32(r, 20)) == 'DCCropCFix')
        assert u32(fixed, 8) == 1 and u32(fixed, 36) == 66
        put(fixed, 36, 200)  # selected-row cursor now has indices 0..6
        # Browsing chooses a named animation interval, not a CSV instance.
        evs = [r for r in self.records(21883, 0x10006) if self.pool.text(u32(r, 8)) == 'controlValueEvent'
               and u32(r, 32) == 3]
        e0 = evs[-1]
        a0 = next(r for r in self.records(21883, 0x10009) if u32(r, 24) == u32(e0, 28))
        new = []
        for i in range(3, 7):
            local = self.local(21883) + len(new) // 2
            e, a = bytearray(e0), bytearray(a0)
            put(e, 28, local); self.text(e, 20, '%02d' % i)
            struct.pack_into('>f', e, 40, float(i))
            put(a, 24, local); self.text(a, self.field(a, 'interval'), '%02d' % i)
            new += [e, a]
        self.after(a0, new)
        o = self.obj(21883); put(o, 8, u32(o, 8) + 4)

    def assemble(self):
        out = []
        for r in self.out:
            if id(r) not in self.old:
                out.append(bytes(r))
                continue
            origin, original = self.old[id(r)]
            pos = 0
            for at in sorted(k for k in self.extra if origin <= k <= origin + len(original)):
                # Insertions at a boundary belong to the preceding record only.
                if at == origin and origin:
                    continue
                out += [bytes(r[pos:at - origin]), *map(bytes, self.extra[at])]
                pos = at - origin
            out.append(bytes(r[pos:]))
        return b''.join(out)

    def budgets(self):
        """Append allocation-vector entries, preserving all stock arena slack."""
        stock_rr = [A.Record(o, r) for o, r in B.walk(self.im, self.name)[3]]
        current = self.assemble()
        rr = [A.Record(r.offset, r.to_bytes()) for r in B.N.split(current)]
        header = self.out[0]
        old_counts, counts = (A.component_counts(x, self.pool.text) for x in (stock_rr, rr))
        comps, arrays = FROWS.header_layout(header)
        for pos in comps:
            name = self.pool.text(u32(header, pos - 4))
            put(header, pos, u32(header, pos) + counts.get(name, 0) - old_counts.get(name, 0))
        assert set(counts) <= set(old_counts)
        put(header, 8, u32(header, 8) + self.next - self.first)
        old_groups = [r for r in stock_rr if r.tag == 0x1000B]
        groups = [r for r in rr if r.tag == 0x1000B]
        old_clips = [A.parse_clip(r, self.pool.text) for r in stock_rr if r.tag == 0x1000A]
        clips = [A.parse_clip(r, self.pool.text) for r in rr if r.tag == 0x1000A]
        # No new animation groups; only extra members/intervals in stock groups.
        assert len(groups) == len(old_groups)
        count, end, width = arrays[0]
        for i in range(3):
            delta = sum(r.word(8 + i * 4) for r in groups) - sum(r.word(8 + i * 4) for r in old_groups)
            put(header, end - 12 + i * 4, u32(header, end - 12 + i * 4) + delta)
        # The allocation vectors are totals, so extra clips/properties/keys can
        # be recorded in appended entries without reordering stock budgets.
        np = sum(len(c['properties']) for c in clips) - sum(len(c['properties']) for c in old_clips)
        nk = sum(len(p['keys']) for c in clips for p in c['properties']) - sum(
            len(p['keys']) for c in old_clips for p in c['properties'])
        nc = len(clips) - len(old_clips)
        for index, n, total in ((1, nc, np), (2, np, nk)):
            count, end, width = arrays[index]
            assert n > 0
            self.insert(header, end, struct.pack('>I', total) + bytes(4 * (n - 1)))
            put(header, count, u32(header, count) + n)


@functools.lru_cache(None)
def pages():
    im = B.Image()
    pool = S.Pool(im.pool)
    out = []
    for name, keys in (('B2_5', ('RES', 'FPS', 'BIT')), ('MainB2', ('DC',))):
        p = Page(im, name, pool)
        for key in keys:
            p.rename(key)
            if key != 'BIT':
                p.bind_caps(SPEC[key]); p.summary(key); p.picks(key)
                if key == 'DC':
                    p.dc_popup()
                else:
                    p.cursor_pairs(SPEC[key])
        if name == 'B2_5':
            for r in p.out:
                for at, kind in p.typed(r):
                    if kind in ('str', 'text') and pool.text(u32(r, at)) == 'B2_5_1':
                        p.text(r, at, 'SLM_FORMAT')
                if B.owner(r) in B.subtree(p.objs, B.ROWS['BIT']['root']):
                    for at, prop, kind, comp in B.fields(im, r):
                        if comp == 'drawText' and prop == 'text' and pool.text(u32(r, at)) == '0307':
                            p.text(r, at, 'RAW', True)
        p.go(); p.format_refresh(); p.budgets()
        out.append(p)
    return out


def build():
    block = fpui.Block()
    for slot, p in enumerate(pages()):
        inserts = {k: list(v) for k, v in p.extra.items()}
        extension_fields = {}
        for r in p.out:
            if id(r) not in p.old:
                continue
            origin, original = p.old[id(r)]
            full, ranges, cursor = bytearray(), [], 0
            for pos in sorted(k for k in p.extra if origin < k <= origin + len(original)):
                full += r[cursor:pos - origin]
                cursor = pos - origin
                for frag in p.extra[pos]:
                    ranges.append((id(frag), len(full), len(full) + len(frag)))
                    full += frag
            full += r[cursor:]
            typed = S.typed_fields(full, p.pool, p.im.schemas)
            for ident, lo, hi in ranges:
                extension_fields[ident] = [(at - lo, kind) for at, kind in typed if lo <= at < hi]
        # New records live before the next original record, with its stock
        # coordinate. One INSERT per record keeps the native 24-argument limit.
        pending = []
        for r in p.out:
            if id(r) not in p.old:
                pending.append(r)
            elif pending:
                inserts.setdefault(p.old[id(r)][0], []).extend(pending)
                pending = []
        assert not pending
        total = sum(len(x) for seq in inserts.values() for x in seq)
        name = block.string(p.name, fpui.NAME)
        block.op(fpui.OP_PAGE, name, p.base - NBU, len(p.stock), p.first, p.next - p.first,
                 total, sum(len(v) for v in inserts.values()))
        counter = block.string('SLM_' + p.name + '_Installed', fpui.NAME)
        block.op(fpui.OP_ALLOC, counter, 0, 1)
        block.op(fpui.OP_EXPECT, slot, 0)
        patches, strings = [], []
        for r in p.out:
            if id(r) not in p.old:
                continue
            origin, original = p.old[id(r)]
            work = bytearray(r)
            for at, kind in p.typed(r):
                if kind in ('str', 'text') and u32(r, at) >= len(p.im.pool) and u32(r, at) != 0xFFFFFFFF:
                    idx = block.string(p.pool.text(u32(r, at)), fpui.NOT_STOCK)
                    strings.append((origin + at, idx))
                    work[at:at + 4] = original[at:at + 4]
            # Object/header counters are full aligned BE words. Their ADD32
            # deltas must retain carries when another FPUI sup grew them.
            running = bytearray(original)
            cursor = 0
            while cursor < len(work):
                if work[cursor] == running[cursor]:
                    cursor += 1
                    continue
                at = min(cursor - cursor % 4, len(work) - 4)
                old, new = u32(running, at), u32(work, at)
                # Allocation headers and root child counts are shared sums.
                # All other replacements still require their exact source.
                guard = not (origin == 0 or (u32(r, 0) == 0x10003 and u32(r, 20) == 1 and at == 16))
                patches.append((origin + at, u32(original, at), (new - old) & 0xFFFFFFFF, guard))
                running[at:at + 4] = work[at:at + 4]
                cursor = at + 4
        block.op(fpui.OP_GUARD, 0, 0x10002)
        for pos, old, delta, guard in patches:
            if guard:
                block.op(fpui.OP_GUARD, pos, old)
        for pos, idx in strings:
            block.op(fpui.OP_GUARD, pos, u32(p.stock, pos))
        for pos, old, delta, guard in patches:
            block.op(fpui.OP_ADD32, pos, delta)
        for pos, idx in strings:
            block.op(fpui.OP_SETSTR_SLOT, slot, 0, 1, idx, pos)
        for pos, seq in sorted(inserts.items()):
            for frag in seq:
                rel = []
                # Decode within-record extensions through their complete
                # record. Never guess object/string pointers from raw values.
                if id(frag) in extension_fields:
                    fields = extension_fields[id(frag)]
                else:
                    fields = S.typed_fields(frag, p.pool, p.im.schemas)
                for at, kind in fields:
                    val = u32(frag, at)
                    if kind == 'obj' and p.first <= val < p.next:
                        rel += [(fpui.R_LOCAL_ID << 24) | (val - p.first), at]
                    elif kind in ('str', 'text') and val >= len(p.im.pool) and val != 0xFFFFFFFF:
                        idx = block.string(p.pool.text(val), fpui.NOT_STOCK)
                        rel += [(fpui.R_STRING << 24) | idx, at]
                assert 3 + len(rel) <= 24, (p.name, len(frag), len(rel))
                block.op(fpui.OP_INSERT, pos, block.fragment(frag), len(frag), *rel)
        block.op(fpui.OP_DONE)
    return block.encode()


def applied(blob=None):
    pp = pages()
    pool = fpui.Strings(pp[0].im.pool)
    target = {p.name: fpui.PageCopy(p.stock, len(p.stock), p.first) for p in pp}
    fpui.apply(build() if blob is None else blob, target, pool)
    return target, pool


def pack():
    items = [('SLM_RES', M.csv_bytes([('CUSTOM', True)])),
             ('SLM_FPS', M.csv_bytes([('CUSTOM', True)])),
             ('SLM_BIT', M.csv_bytes(M.BIT_ROWS)),
             ('SLM_FORMAT', M.csv_bytes([('0302', True), ('0303', False)]))]
    pool, offsets = bytearray(4), {}
    def intern(s):
        if s not in offsets:
            offsets[s] = len(pool)
            pool.extend(s.encode() + b'\0'); pool.extend(bytes((-len(pool)) % 4))
        return offsets[s]
    for name, data in items:
        for s in ('modelCSV', name, name + '.cvm'):
            intern(s)
    out = bytearray(nbr.MAGIC) + struct.pack('>II', 1, 8 + len(pool)) + pool
    table = len(out)
    out += bytes(12 + len(items) * 16)
    files = []
    for name, data in items:
        fn = name + '.cvm'
        files.append((nbr.fnv1a(fn), intern(fn), len(out), len(data)))
        out += data + bytes((-len(data)) % 4)
    struct.pack_into('>III', out, table, 2, len(out) - table, len(items))
    for i, e in enumerate(sorted(files)):
        struct.pack_into('>4I', out, table + 12 + i * 16, *e)
    out += struct.pack('>4I', 0x20001, 16 + len(items) * 36, len(items), len(items))
    defs = len(out)
    out += bytes(len(items) * 36) + struct.pack('>II', 0xFFFFFFFF, 8)
    for i, (name, _) in enumerate(items):
        prop = len(out)
        struct.pack_into('>9I', out, defs + 36 * i, intern(name), intern('modelCSV'), 0,
                         0xFFFFFFFF, 0, 1, 0xFFFFFFFF, 0xFFFFFFFF, prop)
        out += struct.pack('>5I', 0x20002, 20, 1, 1, intern(name + '.cvm'))
    out += struct.pack('>II', 0xFFFFFFFF, 8)
    CSV.inspect_pack(bytes(out))
    return bytes(out)


def header():
    page = build()
    request = page.index(REQUEST_RESERVE.encode() + b'\0')
    assert page.count(REQUEST_RESERVE.encode() + b'\0') == 1
    lines = ['/* generated by menu/slm_page.py -- do not edit */', '#ifndef SLM_PAGE_H', '#define SLM_PAGE_H',
             '#include <stdint.h>', '#define SLM_REQUEST_OFFSET %du' % request]
    for name, data in (('SLM_PAGE', page), ('SLM_PACK', pack())):
        lines.append('static const uint8_t %s[%d] = {' % (name, len(data)))
        lines += ['    ' + ', '.join(str(v) for v in data[i:i + 20]) + ',' for i in range(0, len(data), 20)]
        lines.append('};')
    return '\n'.join(lines + ['#endif', ''])


if __name__ == '__main__':
    (HERE / 'slm_page.h').write_text(header())
    targets, pool = applied()
    print('SLM_PAGE %d bytes; SLM_PACK %d bytes' % (len(build()), len(pack())))
    for p in pages():
        print(p.name, len(p.stock), '->', len(targets[p.name].data), 'objects +', p.next - p.first)
