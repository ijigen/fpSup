"""Execute SensorLab's compiled menu model through the real loader/QS harness.

The page builder's tests cover native page edits; these tests cover the C menu
rows and selection path, using the same QS state and apply unit as the camera.
"""
import pathlib
import struct
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'qs')]
import test_slqs as S
import menu_lists as M

OWED_OFF = 92 + 3 * 50 * 48 + 2 * 3 * 32            # struct slm_state.owed (appended, v0.7.1test)


def model(c):
    p = S.sqt(c, 25)
    header = struct.unpack('<23I', bytes(c.mu.mem_read(p, 92)))
    out = []
    for k in range(3):
        n, cur = header[8 + k], header[11 + k]
        rows = []
        for i in range(n):
            raw = bytes(c.mu.mem_read(p + 92 + (50 * k + i) * 48, 48))
            a, b, en, custom = struct.unpack_from('<4I', raw)
            rows.append(dict(a=a, b=b, enabled=bool(en), custom=bool(custom),
                             text=raw[16:].split(b'\0')[0].decode()))
        out.append(dict(rows=rows, current=cur))
    return header, out


@S.SKIP
class Runtime(unittest.TestCase):
    def test_every_dc_uses_qs_rows_and_always_offers_custom(self):
        c = S.boot()
        for dc, (name, w, h) in enumerate(M.DCS):
            model(c)
            self.assertEqual(S.sqt(c, 26, 0, dc), 1)
            _, menus = model(c)
            self.assertEqual([r['text'] for r in menus[0]['rows']], [x[0] for x in M.DCS] + ['CUSTOM'])
            self.assertEqual(menus[0]['current'], dc)
            ref = M.res_list(w, h)
            self.assertEqual([(r['text'], r['a'], r['b']) for r in menus[1]['rows'][:-1]],
                             [(r['label'], r['w'], r['h']) for r in ref], name)
            self.assertEqual(menus[1]['rows'][-1]['text'], 'CUSTOM')
            self.assertTrue(menus[1]['rows'][-1]['custom'])
            self.assertLessEqual(len(menus[1]['rows']), M.CAP['RES'])
            self.assertLessEqual(len(menus[2]['rows']), M.CAP['FPS'])
            self.assertTrue(any(r['custom'] for r in menus[2]['rows']))
            self.assertTrue(any(not r['enabled'] for r in menus[2]['rows']))

    def test_selection_reaches_qs_and_apply_and_invalid_rows_are_rejected(self):
        c = S.boot()
        _, menus = model(c)
        target = next(i for i, r in enumerate(menus[1]['rows']) if r['text'] == 'UHD')
        pushes = S.sqt(c, 20)
        self.assertEqual(S.sqt(c, 26, 1, target), 1)
        self.assertEqual(S.sqt(c, 20), pushes, 'v0.7.1test: a pick only records; leave() pushes')
        c.layout()
        self.assertGreater(S.sqt(c, 20), pushes)
        self.assertEqual(S.ap_sel(c)['rw'], 3840)
        _, menus = model(c)
        self.assertEqual(menus[1]['current'], target)
        unavailable = next(i for i, r in enumerate(menus[2]['rows']) if not r['enabled'])
        before = S.ap_sel(c)
        self.assertEqual(S.sqt(c, 26, 2, unavailable), 0)
        self.assertEqual(S.sqt(c, 26, 1, 50), 0)
        self.assertEqual(S.ap_sel(c), before)

    def test_recording_guard_does_not_change_selection(self):
        c = S.boot()
        model(c)
        before = S.ap_sel(c)
        c.mu.mem_write(0xC35A952C, b'\1')
        self.assertEqual(S.sqt(c, 26, 0, 0), 0)
        self.assertEqual(S.ap_sel(c), before)


@S.SKIP
class MenuBridge(unittest.TestCase):
    def boot(self):
        import runtime_camera as C
        c = C.boot()
        p = S.sqt(c, 27)
        self.assertEqual(c.w(p), 1, 'private menu setup must succeed')
        self.assertEqual(c.w(p + 8), 0)
        return c, p

    def test_native_models_private_confirm_and_silent_sync(self):
        c, p = self.boot()
        _, menus = model(c)
        for k in (1, 2):
            # v0.7.2test: a 4-digit text is a .nloc string id to the native list (1000 = Off): it goes as "1000.0"
            self.assertEqual([row[1] for row in c.model_rows[k]],
                             [r['text'] + ('.0' if len(r['text']) == 4 and r['text'].isdigit() else '')
                              for r in menus[k]['rows']])
            self.assertFalse([row[1] for row in c.model_rows[k]
                              if len(row[1]) >= 4 and row[1][:4].isdigit() and row[1][4:5] in ('', '_')])
            self.assertEqual(len(c.model_rows[k]) - 1, c.vars['SLM_' + ('Res','Fps')[k-1] + 'N'][1])
        self.assertIn('1000', [r['text'] for r in menus[2]['rows']], 'the default HD 2K list reaches 1000')
        self.assertIn('1000.0', [row[1] for row in c.model_rows[2]])
        callbacks = [n for _ctx, n, _fn in c.subs if n.startswith('SLM_')]
        self.assertEqual(callbacks, ['SLM_PickDc', 'SLM_PickRes', 'SLM_PickFps', 'SLM_Refresh'])
        self.assertEqual([n for n in callbacks if n.startswith('SLM_Pick')],
                         ['SLM_PickDc', 'SLM_PickRes', 'SLM_PickFps'])
        picks = c.w(p + 16)
        c.layout()  # queued VALUE updates may not look like user confirmation
        self.assertEqual(c.w(p + 16), picks)
        c.confirm(0, 0xFFFFFFFF)  # reset half of the explicit confirmation pulse
        self.assertEqual(c.w(p + 16), picks)
        c.confirm(0, 0)
        self.assertEqual(c.w(p + 16), picks + 1)
        _, menus = model(c)
        self.assertEqual(menus[0]['current'], 0)
        self.assertEqual(c.model_rows[1][-1][1], 'CUSTOM')

    def owed(self, p):
        return self.c.w(p + OWED_OFF)

    def test_confirm_event_only_records_and_leave_applies(self):
        """v0.7.1test (live v1 item 3: OK on 2K in the RES popup froze the camera). Inside the change event: no push,
        no commit / carrier setter / LV reload / list recompute, no NBR load, no modelCSV edit or notify -- only the
        selection, the owed mark and queued posts. The next leave() pushes, commits and rebuilds both models."""
        import runtime_camera as C
        for k, pick in ((1, lambda rows, cur: next(i for i, r in enumerate(rows) if i != cur and r['enabled']
                                                 and not r['custom'])),
                        (0, lambda rows, cur: next(i for i, r in enumerate(rows) if i != cur and not r['custom'])),
                        (2, lambda rows, cur: next(i for i, r in enumerate(rows) if i != cur and r['enabled']
                                                 and not r['custom']))):
            with self.subTest(list=k):
                c = C.boot(descriptor=True)
                self.c = c
                p = S.sqt(c, 27)
                self.assertEqual(c.w(p), 1)
                c.layout()
                _, menus = model(c)
                row = pick(menus[k]['rows'], menus[k]['current'])
                want = menus[k]['rows'][row]
                pushes, notices = S.sqt(c, 20), len(c.notices)
                commits = S.ap_status(c)['commits'] if hasattr(S, 'ap_status') else None
                picks, before = c.w(p + 16), S.ap_sel(c)
                text = 'SLM_' + ('Dc', 'Res', 'Fps')[k] + 'Text'
                shown = c.vars[text][1]
                c.event_calls.clear()
                c.confirm(k, 0xFFFFFFFF); c.confirm(k, row)
                self.assertEqual(c.event_calls, [], 'firmware work inside the change event')
                self.assertEqual(c.w(p + 16), picks + 1, 'the pick is recorded')
                self.assertEqual(self.owed(p), 1)
                self.assertEqual(S.sqt(c, 20), pushes, 'no push inside the change event')
                self.assertEqual(len(c.notices), notices, 'no model rewrite inside the change event')
                self.assertEqual(S.ap_sel(c), before, 'nothing handed to the apply unit yet')
                if commits is not None:
                    self.assertEqual(S.ap_status(c)['commits'], commits)
                self.assertNotEqual(c.vars[text][1], shown, 'the row summary is posted (queued) from the other bank')
                c.layout()                                   # leave(): the safe point
                self.assertGreater(S.sqt(c, 20), pushes)
                self.assertEqual(self.owed(p), 0)
                self.assertEqual(sorted(n for n, _ in c.notices[notices:]), [1, 2], 'both models rebuilt once')
                _, menus = model(c)
                self.assertEqual(menus[k]['rows'][menus[k]['current']]['text'], want['text'])
                if k == 1:
                    self.assertEqual((S.ap_sel(c)['rw'], S.ap_sel(c)['rh']), (want['a'], want['b']))

    def test_stale_row_after_an_earlier_pick_is_checked(self):
        """two picks in one menu visit: the second list is stale until leave(); a row it no longer offers is refused"""
        import runtime_camera as C
        c = C.boot()
        self.c = c
        p = S.sqt(c, 27)
        _, menus = model(c)
        dc_now = menus[0]['current']
        res_rows = {(r['a'], r['b']) for r in menus[1]['rows'] if not r['custom']}
        for dc, (name, w, h) in enumerate(M.DCS):
            new = {(r['w'], r['h']) for r in M.res_list(w, h)}
            gone = sorted(res_rows - new)
            if dc != dc_now and gone:
                break
        else:
            self.skipTest('no DC drops a RES row')
        c.confirm(0, 0xFFFFFFFF); c.confirm(0, dc)
        self.assertEqual(self.owed(p), 1)
        stale = next(i for i, r in enumerate(menus[1]['rows']) if (r['a'], r['b']) == gone[0])
        rejected, picks = c.w(p + 20), c.w(p + 16)
        c.confirm(1, 0xFFFFFFFF); c.confirm(1, stale)
        self.assertEqual((c.w(p + 16), c.w(p + 20)), (picks, rejected + 1), 'stale RES row refused')
        keep = next((i for i, r in enumerate(menus[1]['rows']) if not r['custom'] and (r['a'], r['b']) in new), None)
        if keep is not None:
            c.confirm(1, 0xFFFFFFFF); c.confirm(1, keep)
            self.assertEqual(c.w(p + 16), picks + 1, 'a row still offered is taken')
        self.assertEqual(c.event_calls, [])

    def test_custom_reselection_queues_open_and_recording_refuses(self):
        c, p = self.boot()
        blob = S.blob()[0]
        self.assertEqual(blob.count(b'SLM_QS_REQUEST'), 1)
        request = c.block_of(S.BS.file_name()) + blob.index(b'SLM_QS_REQUEST')
        self.assertEqual(c.cstr(request), '')
        _, menus = model(c)
        row = len(menus[1]['rows']) - 1
        self.assertEqual(c.w(p + 24), 0)
        c.confirm(1, 0xFFFFFFFF); c.confirm(1, row)
        self.assertEqual(c.w(p + 24), 1)
        self.assertEqual(c.vars['SLM_Go'][1], 1)
        self.assertEqual(c.cstr(request), 'QS')
        c.layout()  # requested transition consumed the string before next menu construction
        self.assertEqual(c.cstr(request), '')
        c.guid(S.FMT_ID)
        self.assertEqual(S.TP.st(c, 'sub_open'), 1)
        c.layout()  # return to menu; no stale request may reopen QS
        self.assertEqual(c.cstr(request), '')
        self.assertEqual(S.TP.st(c, 'sub_open'), -1)
        c.confirm(1, 0xFFFFFFFF); c.confirm(1, row)
        self.assertEqual(c.w(p + 24), 2)
        self.assertEqual(c.vars['SLM_Go'][1], 2)
        c.mu.mem_write(0xC35A952C, b'\1')
        c.confirm(1, 0xFFFFFFFF); c.confirm(1, row)
        self.assertEqual(c.w(p + 24), 2)
        self.assertEqual(c.w(p + 20), 1)

    def test_fps_custom_opens_the_fps_sub_qs_on_fine(self):
        """v0.7.0test (Bei 10-30 A): the menu's FPS CUSTOM opens the FPS sub-QS focused on FINE -- with FPS in the
        user's eight tiles and without it (the container's standalone sub-QS, as DC / RES); a FINE step, AEL back,
        and the tuned rate is applied and listed (QS footer yellow, the menu's CUSTOM row)"""
        absent = (S.FMT_ID, S.DC_ID, S.RES_ID, 4, S.RCP_ID, S.QR_ID, S.MB_ID, 19)
        for slots in (S.SLOTS, absent):
            with self.subTest(fps_on_layout=slots == S.SLOTS):
                c, p = self.boot()
                if slots != S.SLOTS:
                    S.TP.set_cine(c, slots)
                    c.layout()
                _, menus = model(c)
                row = next(i for i, r in enumerate(menus[2]['rows']) if r['custom'])
                c.confirm(2, 0xFFFFFFFF); c.confirm(2, row)
                self.assertEqual(c.vars['SLM_Go'][1], 1)
                c.layout()                                  # menu -> QS
                c.guid(slots[0])
                self.assertEqual(S.TP.st(c, 'sub_open'), 2, 'the FPS sub-QS')
                self.assertEqual(c.w(S.Q1.QSOBJ + 0xBC), 71, 'focused on FINE (tile 2)')
                self.assertEqual(S.tile(c, 1)[0], 'FINE')
                self.assertEqual(S.footer(c, 71)['spin'], 1)
                was = S.tile(c, 1)[1]
                S.TP.press(c, 1, 71)                         # one FINE step
                tuned = S.tile(c, 1)[1]
                self.assertNotEqual(tuned, was)
                pushes = S.sqt(c, 20)
                S.TP.press(c, 5, 71)                         # AEL: back; FINE left
                self.assertEqual(S.TP.st(c, 'sub_open'), -1)
                self.assertGreater(S.sqt(c, 20), pushes, 'the tuned rate is applied when FINE is left')
                custom = [x for x in S.footer(c, S.FPS_ID)['items'] if x[4]]
                self.assertEqual(len(custom), 1, 'one tuned rate in the list, yellow')
                c.layout()
                _, menus = model(c)
                self.assertIn('CUSTOM ' + tuned, [r['text'] for r in menus[2]['rows'] if r['custom']])

    def test_recording_rejects_confirmed_preset_before_state_changes(self):
        c, p = self.boot()
        _, before = model(c)
        picks = c.w(p + 16)
        c.mu.mem_write(0xC35A952C, b'\1')
        c.confirm(0, 0)
        self.assertEqual(c.w(p + 16), picks)
        _, after = model(c)
        self.assertEqual(after, before)
        self.assertEqual(c.w(p + 20), 1)

    def test_mov_locks_sensor_rows_and_dng_unlocks(self):
        c, p = self.boot()
        _, before = model(c)
        picks = c.w(p + 16)
        c.mov_format = 1
        c.layout()
        for name in ('Dc', 'Res', 'Fps'):
            self.assertEqual(c.vars['EXCL_SLM_' + name][1], 1)
        c.confirm(0, 0)
        self.assertEqual(c.w(p + 16), picks)
        _, after = model(c)
        self.assertEqual(after, before)
        self.assertEqual(c.w(p + 20), 1)
        c.mov_format = 0
        c.layout()
        for name in ('Dc', 'Res', 'Fps'):
            self.assertEqual(c.vars['EXCL_SLM_' + name][1], 0)
        c.confirm(0, 0)
        self.assertEqual(c.w(p + 16), picks + 1)

    def test_format_notification_unlocks_same_page_without_applying_settings(self):
        c, p = self.boot()
        self.assertEqual(c.subscription_failures, [], 'must not claim a stock variable callback slot')
        self.assertEqual([ctx for ctx, name, _fn in c.subs if name == 'MV_RecordingFormat'],
                         [0xC37B7048])
        self.assertEqual([fn for _ctx, name, fn in c.subs if name == 'MV_RecordingFormat'], [0xC057A598])
        self.assertNotIn('MV_RecordingFormat', c.registered_names)
        before = S.ap_sel(c)
        pushes = S.sqt(c, 20)
        counters = tuple(c.w(p + off) for off in (16, 20, 24, 28))
        for i, value in enumerate((1, 0, 2, 0)):
            c.change_format(value, page='B2_5' if i < 2 else 'MainB2')
            for name in ('Dc', 'Res', 'Fps'):
                self.assertEqual(c.vars['EXCL_SLM_' + name][1], int(value != 0))
            self.assertEqual(S.ap_sel(c), before)
            self.assertEqual(S.sqt(c, 20), pushes)
            self.assertEqual(tuple(c.w(p + off) for off in (16, 20, 24, 28)), counters)
        self.assertEqual(c.stock_format_calls, 4)
        self.assertEqual([x for x in c.event_calls if x.startswith('model')], [],
                         'v0.7.1test: the format event posts locks / values only, no model rewrite')
        self.assertEqual(c.page_event_trace, [('SLM_Refresh', -1), ('SLM_Refresh', 1)] * 4)
        c.confirm(0, 0)
        self.assertEqual(c.w(p + 16), counters[0] + 1)


TICK, TICK_WORD = 0xC002B6E0, 0xC3F80100
TICK_STUB = ['E59F1008', 'E5910000', 'E2800FFA', 'E5810000', 'E12FFF1E', f'{TICK_WORD:08X}']   # +1000 us a call


@S.SKIP
class FirstMenu(unittest.TestCase):
    """v0.7.0test, the first-MENU timeout (live-v1 01): the first layout load after boot carries the one-time work --
    the container's collection, the boot restore, the private menu setup.  The setup builds and writes each native
    model once (v0.6.0 wrote both twice), and leave() keeps its phase times for the live probe (sq_test 29)."""
    def first(self):
        import runtime_camera as C
        from unittest.mock import patch
        with patch.object(S.Q1, 'Cam', C.Cam):
            def prep(cam):
                S.ap_firmware(cam, False)
                cam.mu.mem_write(TICK, b''.join(struct.pack('<I', int(w, 16)) for w in TICK_STUB))
            c = S.Q1.boot([(S.Q1.CNAME, S.Q1.cblob()[0]), (S.BS.file_name(), S.blob()[0])], prepare=prep)
        return c

    def lt(self, c):
        return struct.unpack('<8I', bytes(c.mu.mem_read(S.sqt(c, 29), 32)))

    def lt16(self, c):
        return struct.unpack('<16I', bytes(c.mu.mem_read(S.sqt(c, 29), 64)))

    def container(self, c):
        return struct.unpack('<12I', bytes(c.mu.mem_read(S.sqt(c, 31), 48)))

    def test_first_layout_writes_each_native_model_once_and_times_leave(self):
        c = self.first()
        self.assertEqual(self.lt(c), (0,) * 8)
        c.layout()                                           # the first MENU after boot
        p = S.sqt(c, 27)
        self.assertEqual((c.w(p), c.w(p + 8)), (1, 0), 'private menu ready')
        self.assertEqual(sorted(k for k, _n in c.notices), [1, 2], 'each model written once')
        self.assertEqual(c.w(p + 12), 1, 'published once')
        for k in ('Dc', 'Res', 'Fps'):
            self.assertEqual(c.vars['EXCL_SLM_' + k][1], 0)
        first = self.lt(c)
        self.assertEqual(first[7], 1)
        self.assertTrue(all(first[1:5]), first)
        self.assertGreaterEqual(first[0], sum(first[1:5]))
        self.assertEqual((first[5], first[6]), (first[0], first[0]))
        w = self.lt16(c)
        self.assertTrue(w[8] <= w[10] < w[11] <= w[9], w)            # leave start <= push start < push end <= leave end
        self.assertEqual(w[9] - w[8], first[0])
        self.assertTrue(w[12] and w[13] and w[14] >= w[12] + w[13], w)   # page copies, models, the whole setup
        k = self.container(c)                                          # the container's view of the same layout
        self.assertEqual(k[7], 1)
        self.assertTrue(k[0] < k[2] <= k[3] <= w[8] and w[9] <= k[4] < k[5], (k, w))
        c.layout()                                           # later layouts: one sync, the first times kept
        later = self.lt(c)
        self.assertEqual(later[:5], first[:5])
        self.assertEqual(later[7], 2)
        self.assertEqual(later[5], max(first[0], later[6]))
        self.assertEqual(sorted(k for k, _n in c.notices), [1, 1, 2, 2])

    def test_pause_keeps_stock_across_layouts(self):
        """sq_test 30: 1 = stock now and no push from leave() / dials / the menu until 0 (sq_test 22 is undone by the
        next leave)"""
        c = self.first()
        c.layout()
        n = S.sqt(c, 20)
        self.assertEqual(S.sqt(c, 30, 2), 0xFFFFFFFF)
        S.sqt(c, 30, 1)
        self.assertEqual(S.ap_sel(c)['valid'], 0)
        c.layout(); S.press(c, 1, 1); c.layout()
        self.assertEqual(S.sqt(c, 20), n, 'no push while paused')
        self.assertEqual(S.ap_sel(c)['valid'], 0)
        self.assertGreaterEqual(self.lt16(c)[15], 3)
        S.sqt(c, 30, 0)
        self.assertEqual(S.sqt(c, 20), n + 1)
        self.assertEqual(S.ap_sel(c)['valid'], 1)


if __name__ == '__main__':
    unittest.main()
