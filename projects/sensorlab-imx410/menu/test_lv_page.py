#!/usr/bin/env python3
"""Offline checks of the live-view frame-rate page edit (slm_lv_page.py).

The stock firmware's own record parser runs over both edited pages (unicorn);
nothing is rendered.  What it looks like on the camera is not covered here.
"""
import struct
import unittest

import slm_lv_page as LV
import test_page as TP

P = TP.P
u32 = P.u32


def records(page):
    return [r.to_bytes() for r in P.B.N.split(page)]


class LvPage(unittest.TestCase):
    def test_header_is_current(self):
        self.assertEqual((LV.HERE / 'slm_lv_page.h').read_text(), LV.header())
        self.assertLessEqual(len(P.fpui.decode(LV.build())[0]), 64)

    def test_only_the_frame_rate_moves_and_one_text_object_is_added(self):
        for p in LV.pages():
            var, _prefix = LV.PAGES[p.name]
            s = LV._set(p.name)
            old, new = records(p.stock), records(p.assemble())
            self.assertEqual(len(new), len(old) + 4, p.name)
            at = next(i for i, r in enumerate(new) if i >= len(old) or r != old[i] and u32(r, 0) == 0x10003
                      and u32(r, 20) == p.first)
            added = new[at:at + 4]
            rest = new[:at] + new[at + 4:]
            changed = [(a, b) for a, b in zip(old, rest) if a != b]
            # the header's budgets, the parent's child count, the stock object's base rect: nothing else
            self.assertEqual(sorted(u32(a, 0) for a, _b in changed), [0x10002, 0x10003, 0x10004], p.name)
            parent = p.objs[s['owner']][0]
            for a, b in changed:
                if u32(a, 0) == 0x10003:
                    self.assertEqual((u32(a, 20), u32(b, 16)), (parent, u32(a, 16) + 1))
                    self.assertEqual(a[:16] + a[20:], b[:16] + b[20:])
                elif u32(a, 0) == 0x10004:
                    self.assertEqual(u32(a, 20), s['owner'])
                    self.assertEqual(struct.unpack_from('>f', b, 36)[0], LV.OFF_SCREEN)
                    self.assertEqual(a[:36] + a[40:], b[:36] + b[40:])
            x, y, w, h = struct.unpack_from('>4f', next(a for a, _b in changed if u32(a, 0) == 0x10004), 32)
            obj, base, text, event = added
            # the donor: the page's own string-variable text, the same records but for what the docstring lists
            donor = next(o for o, (_par, nm) in sorted(p.objs.items()) if nm == LV.DONOR)
            d_obj, d_base, d_text, d_event = [r for r in old if P.B.owner(r) == donor]
            self.assertEqual([u32(r, 0) for r in added], [0x10003, 0x10004, 0x10005, 0x10006])
            self.assertEqual((u32(obj, 20), u32(obj, 24), p.pool.text(u32(obj, 28))), (p.first, parent, var))
            dh = struct.unpack_from('>f', d_base, 44)[0]
            # where stock drew it, as high as the donor (lower than the font: only the first image is drawn)
            self.assertEqual(struct.unpack_from('>4f', base, 32), (x, y + h - dh, w + LV.EXTRA_W, dh))
            self.assertEqual(struct.unpack_from('>4f', text, len(text) - 16), (0.0, 0.0, w + LV.EXTRA_W, dh))
            self.assertEqual(text[41:45], d_text[41:45])                      # horz-align: the donor's
            self.assertEqual([P.B.owner(r) for r in added[1:]], [p.first] * 3)
            self.assertEqual(p.pool.text(u32(text, 8)), 'drawText')
            self.assertEqual(p.pool.text(u32(event, 8)), 'appVariableEvent')
            self.assertEqual((p.pool.text(u32(event, 36)), p.pool.text(u32(event, 41))), (var, 'text'))
            self.assertEqual(obj[:20] + obj[32:], d_obj[:20] + d_obj[32:])
            self.assertEqual(base[:20] + base[24:32], d_base[:20] + d_base[24:32])
            self.assertEqual(text[:20] + text[24:32] + text[37:41], d_text[:20] + d_text[24:32] + d_text[37:41])
            self.assertEqual(event[:24] + event[28:36] + event[40:], d_event[:24] + d_event[28:36] + d_event[40:])
            self.assertTrue(p.pool.text(u32(d_event, 36)).startswith('LV_RemainingRecTimeString'))

    def test_budgets_and_object_graph(self):
        for p in LV.pages():
            old = P.S.page_shape(p.stock, p.pool)
            new = P.S.page_shape(p.assemble(), p.pool)
            self.assertEqual(old['header_minus_actual'], new['header_minus_actual'], p.name)
            self.assertEqual((new['orphans'], new['bad_child_counts']), ([], []))
            self.assertEqual(set(new['objects']) - set(old['objects']), {p.first})

    def test_reference_applier_matches_builder(self):
        target, pool = LV.applied()
        for p in LV.pages():
            self.assertEqual(TP.semantic(bytes(target[p.name].data), pool, p.im.schemas),
                             TP.semantic(p.assemble(), p.pool, p.im.schemas))


class Native(unittest.TestCase):
    def test_native_firmware_parses_both_pages(self):
        for p in LV.pages():
            q = P.S.native_parse(p.assemble(), bytes(p.pool.data), p.im.img)
            self.assertFalse(q.error_flag(), p.name)
            self.assertEqual(len(q.traces), len(records(p.assemble())), p.name)


if __name__ == '__main__':
    unittest.main()
