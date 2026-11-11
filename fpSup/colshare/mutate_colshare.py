#!/usr/bin/env python3
"""COL-Share 的突變檢查(DESIGN.md §11):每個突變改 colshare.c 一處,跑指定的測試,必須有測試失敗。

    cd fpSup/colshare && python3 -B mutate_colshare.py [名字 ...]

突變版原始碼放在暫存目錄,經環境變數 COLSHARE_SOURCE 交給 build_colshare.build();原檔不動。
目標是 LUT 的(名字以 lut- 開頭、第四欄是 native/ 下的檔名):整個 lut/native 抄到暫存目錄改那一個檔,
LUT_MUTANT_SOURCE 指向暫存的 lut4.c(test_capacity 用它建 LUT.BIN)。
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / 'colshare.c'

# name: (old, new, tests)
MUTANTS = {
    'stock-word': ('case 6: a = S_MC; w = 0xE15A0006u;', 'case 6: a = S_MC; w = 0xE15A0007u;',
                   ['test_colshare.ColShareTests.test_power_off_puts_every_word_back_and_the_setter_stays_stock']),
    'root-stock-count': ("case 3: o = 0x48u; *table = 0xC0B3AAECu; *count = 12u;", "case 3: o = 0x48u; *table = 0xC0B3AAECu; *count = 13u;",
                         ['test_colshare.ColShareTests.test_the_setter_writes_the_record_in_order_and_stock_in_reverse']),
    'record-order-reversed': ('"   ldr     r5, [r1]\\n"                    /* the new one\'s words, in its order */\n'
                              '"   add     r6, r1, #4\\n"\n'
                              '"15:ldrh    r7, [r6]\\n"\n'
                              '"   ldr     ip, [r6, #4]\\n"\n'
                              '"   str     ip, [r4, r7]\\n"\n'
                              '"   add     r6, r6, #8\\n"',
                              '"   ldr     r5, [r1]\\n"\n'
                              '"   add     r6, r1, r5, lsl #3\\n"\n'
                              '"   sub     r6, r6, #4\\n"\n'
                              '"15:ldrh    r7, [r6]\\n"\n'
                              '"   ldr     ip, [r6, #4]\\n"\n'
                              '"   str     ip, [r4, r7]\\n"\n'
                              '"   sub     r6, r6, #8\\n"',
                              ['test_colshare.ColShareTests.test_the_setter_writes_the_record_in_order_and_stock_in_reverse']),
    'stock-not-reversed': ('"12:subs    r5, r5, #1\\n"', '"12:subs    r5, r5, #0\\n"',
                           ['test_colshare.ColShareTests.test_the_setter_writes_the_record_in_order_and_stock_in_reverse']),
    'recording-gate-off': ('    return *(volatile const u8 *)(uintptr_t)(sel == 0x21u ? 0xC3476609u : 0xC347E08Fu) != 0;',
                           '    (void)sel; return 0;',
                           ['test_colshare.ColShareTests.test_recording_defers_the_callbacks_flag_at_0x157']),
    'recording-one-location': ('(sel == 0x21u ? 0xC3476609u : 0xC347E08Fu)', '((void)sel, 0xC347E08Fu)',
                               ['test_colshare.ColShareTests.test_recording_defers_the_callbacks_flag_at_0x3d']),
    'on-pick-not-called': ('        if (now) now->c->on_pick(now->c->arg, nk);', '        (void)now;',
                           ['test_colshare.ColShareTests.test_recording_defers_the_callbacks_flag_at_0x157']),
    'icon-pointer-wrong': ('    copy(b, icon, len);', '    copy(b, icon + 4, len);',
                           ['test_clist_native.ClistNativeTests.test_redirected_copies_hold_the_rows_and_icons_of_the_cubes_on']),
    # ---- 12 rows / v3 / copies only for rows that exist (Bei 2026-11-10): test_capacity
    'room-counts-self': ('    for (u32 j = 1; j <= L->n; j++) if (L->row_sup[j] != sup) others++;',
                         '    for (u32 j = 1; j <= L->n; j++) if (L->row_sup[j] != sup || 1) others++;',
                         ['test_capacity.CapacityTests.test_v3_reports_rows_max_and_each_clients_room']),
    'icons-never-dropped': ('L->snap[j] = L->live[j] = L->glyph[j] = 0; cs_drop(L, 2u + j); }',
                            'L->snap[j] = L->live[j] = L->glyph[j] = 0; }',
                            ['test_capacity.CapacityTests.test_two_rows_have_two_icons_and_rows_that_go_free_theirs']),
    'entry-kept-live': ('    if (f->entry && rd(f->entry)) { wr(f->entry, 0); L->svc->publish(L->svc); }',
                        '    if (0) { wr(f->entry, 0); L->svc->publish(L->svc); }',
                        ['test_capacity.CapacityTests.test_two_rows_have_two_icons_and_rows_that_go_free_theirs']),
    'csv-ring-open': ('            at = cs_num(out, at, j + 1u < n ? k + 1u : 0u); at = cs_ch(out, at, \',\');',
                      '            at = cs_num(out, at, k + 1u); at = cs_ch(out, at, \',\');',
                      ['test_capacity.CapacityTests.test_twelve_rows_get_twelve_icons_and_csvs_sized_to_them']),
    'csv-first-cell-stale': ('at = cs_mem(out, at, src, o1); at = cs_num(out, at, 15u + n);',
                             'at = cs_mem(out, at, src, o1); at = cs_num(out, at, 15u);',
                             ['test_capacity.CapacityTests.test_twelve_rows_get_twelve_icons_and_csvs_sized_to_them']),
    'copies-while-recording': ('    if (recording()) { L->sync_pending = 1; L->sync_late++; return; }   /* the copies\' allocations: not during a take */',
                               '',
                               ['test_capacity.CapacityTests.test_no_copy_is_made_while_recording']),
    'copy-oversized': ('    u32 cap = (n + CS_LINE - 1u) & ~(CS_LINE - 1u);', '    u32 cap = n > 13312u ? n : 13312u;',
                       ['test_capacity.CapacityTests.test_twelve_rows_get_twelve_icons_and_csvs_sized_to_them']),
    # LUT (native/): the manager's cap, the overflow flag, one set held
    'lut-cap-ignored': ('mv_used(s)>=lut_room(s))s->ui_result=R_FULL;', 'mv_used(s)>=99u)s->ui_result=R_FULL;',
                        ['test_capacity.CapacityTests.test_the_manager_refuses_more_than_room'], 'color_ui.c'),
    'lut-overflow-unflagged': ('norow?ctext(s,T_NOROW):', '0?ctext(s,T_NOROW):',
                               ['test_capacity.CapacityTests.test_raw_view_after_twelve_luts_the_last_one_waits_and_is_flagged'], 'color_ui.c'),
    'lut-rows-ignore-max': ('        if (n >= CL_MAX || n >= max) { over++; continue; }', '        if (n >= CL_MAX || n >= max + 1u) { over++; continue; }',
                            ['test_capacity.CapacityTests.test_raw_view_after_twelve_luts_the_last_one_waits_and_is_flagged'], 'cols.c'),
    'lut-old-set-kept': ('    if (S && S != keep) { lut_return(s, &s->b_set); s->lvb.set_returns++; }', '',
                         ['test_capacity.CapacityTests.test_eleven_lut_rows_each_pick_shows_its_own_set_and_only_one_is_held'], 'lvb.c'),
    'lut-every-row-its-set': ('        api->set_record(api, API_ID, L->map[jj], keep && jj + 1u == row ? &keep->crec : &M->stock);',
                              '        api->set_record(api, API_ID, L->map[jj], keep ? &keep->crec : &M->stock);',
                              ['test_capacity.CapacityTests.test_while_recording_the_cursor_reads_no_file'], 'lvb.c'),
    'preview-not-called': ('"   blx     ip\\n"\n"   mov     sp, r4\\n"\n"   pop     {r4, lr}\\n"', '"   nop\\n"\n"   mov     sp, r4\\n"\n"   pop     {r4, lr}\\n"',
                           ['test_capacity.CapacityTests.test_the_cursor_previews_each_row_at_once_and_holds_at_most_two_sets']),
    'preview-while-recording': ('    if (!L->menu || L->down || recording()) return;', '    if (!L->menu || L->down) return;',
                                ['test_capacity.CapacityTests.test_while_recording_the_cursor_reads_no_file']),
    'lut-preview-not-freed': ('        lut_return(s, &s->b_prev); s->lvb.set_returns++;\n    }\n    if (N) s->b_prev = nb;',
                              '        s->lvb.set_returns++;\n    }\n    if (N) s->b_prev = nb;',
                              ['test_capacity.CapacityTests.test_the_cursor_previews_each_row_at_once_and_holds_at_most_two_sets'], 'lvb.c'),
    'lut-preview-not-promoted': ('        else if (V && V->ok && library_same(key, V->key, sizeof key)) keep = V;', '',
                                 ['test_capacity.CapacityTests.test_the_cursor_previews_each_row_at_once_and_holds_at_most_two_sets'], 'lvb.c'),
    'lut-jft-path-size-only': ('    u32 cam = sha[0] == \'C\' && sha[1] == \'A\' && sha[2] == \'M\' && sha[3] == \'1\';', '    u32 cam = 0;',
                               ['test_capacity.CapacityTests.test_eleven_lut_rows_each_pick_shows_its_own_set_and_only_one_is_held'], 'lvb.c'),
    'rawview-version-reversed': ('if (h[6] >= c->rawview_client) client = 1; else old = 1;',
                                 'if (h[6] < c->rawview_client) client = 1; else old = 1;',
                                 ['test_colshare.ColShareTests.test_old_raw_view_releases_col_share_and_nothing_is_written']),
    'rawview-disabled-ignored': ('    if (svc->disabled_get && svc->disabled_get(svc, c->rawview_id) == 1) return 0;   /* off in SupManager */', '',
                                 ['test_colshare.ColShareTests.test_a_raw_view_client_or_a_disabled_old_one_keeps_col_share']),
    'record-check-off': ('        for (u32 i = 0; i < r->n; i++) if (!COLS_OFF_OK(r->w[i].off)) return SL_BADARG;   /* only what we claimed */', '',
                         ['test_colshare.ColShareTests.test_a_record_outside_the_claimed_words_is_refused']),
    'box-max-ignored': ('"   movgt   r0, ip\\n"', '"   nop\\n"',
                        ['test_colshare.ColShareTests.test_the_box_clamps_to_each_rows_range_and_close_saves_once']),
    'no-poweroff-root': ('    if (L->shown_rec) root_write(L, 0, 0);\n    L->down = 1;', '    L->down = 1;',
                         ['test_colshare.ColShareTests.test_power_off_routine_alone_restores_the_root']),
    'fv-unclaimed': ('        if (svc->claim(svc, FV_SITE, 4u, &fv, SL_SHARED_UI) != SL_OK) return fail(L, 2);', '        (void)fv;',
                     ['test_colshare.ColShareTests.test_power_off_puts_every_word_back_and_the_setter_stays_stock']),
    'pull-not-collected': ('        if (info.status != SL_S_LOADED || info.id == COLS_ID) continue;',
                           '        if (1) continue;',
                           ['test_colshare.ColShareTests.test_both_load_orders_give_the_same_rows_table_and_active']),
    'no-write-on-late-record': ('        if (r) show(L, j);', '        if (0) show(L, j);',
                                ['test_colshare.ColShareTests.test_a_row_without_a_record_leaves_the_root_and_a_later_record_shows_at_once']),
}


def main():
    names = sys.argv[1:] or list(MUTANTS)
    src = SRC.read_text()
    survived = []
    for name in names:
        old, new, tests, *lut = MUTANTS[name]
        text = (HERE.parent / 'lut/native' / lut[0]).read_text() if lut else src
        if text.count(old) != 1:
            print(f'{name}: pattern found {text.count(old)} times'); survived.append(name); continue
        with tempfile.TemporaryDirectory(prefix='colshare-mut-') as td:
            if lut:
                nat = Path(td) / 'native'
                shutil.copytree(HERE.parent / 'lut/native', nat)
                (nat / lut[0]).write_text(text.replace(old, new))
                env = dict(os.environ, LUT_MUTANT_SOURCE=str(nat / 'lut4.c'), PYTHONPATH=str(HERE.parent / 'lut'))
            else:
                m = Path(td) / 'colshare.c'
                m.write_text(src.replace(old, new))
                env = dict(os.environ, COLSHARE_SOURCE=str(m), PYTHONPATH=str(HERE.parent / 'lut'))
            r = subprocess.run([sys.executable, '-B', '-m', 'unittest', *tests], cwd=HERE, env=env,
                               capture_output=True, text=True)
        killed = r.returncode != 0 and ('FAIL:' in r.stderr or 'ERROR:' in r.stderr) and 'compile failed' not in r.stderr   # not a build error
        print(f'{name}: {"killed" if killed else "SURVIVED"}')
        if not killed:
            survived.append(name)
    print('all killed' if not survived else f'survived: {survived}')
    return 1 if survived else 0


if __name__ == '__main__':
    raise SystemExit(main())
