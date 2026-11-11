#!/usr/bin/env python3
"""RAW-View 0.4 (COL-Share client) mutation check: each mutant changes one place of the sources, runs the
named tests, and some test must fail.

    cd projects/rawview/build && python3 -B mutate_cols_rawview.py [name ...]

The sources are copied to projects/rawview-mut-*/build (the same depth: the builders find the repo by
parents[2]), mutated there, tested there, and removed; the originals are not touched.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
T = 'test_v4_cols_rawview.RawViewColsTests.'
CS_SRC = HERE.parents[2] / 'fpSup/colshare/colshare.c'      # 'colshare.c' mutants: COLSHARE_SOURCE (build_colshare)
BOX = T + 'test_the_box_on_the_raw_row_snaps_sa_ga_and_persists'

# name: (file, old, new, tests)
MUTANTS = {
    'record-wrong-word': ('rv_launch.S', '    mov     r1, #0x08\n    str     r1, [r0, #12]', '    mov     r1, #0x10\n    str     r1, [r0, #12]',
                          [T + 'test_loads_after_col_share_with_its_own_sites_and_the_first_row']),
    'boxes-not-gated': ('rv_resident.S', '    SHOWN\n    bne     9f', '    SHOWN\n    nop',
                        [T + 'test_the_boxes_act_only_while_the_root_shows_raw']),
    'gain-copy-not-stock': ('rv_resident.S', '    moveq   r1, #82                 /* 原廠 OFF 曲線 */', '    moveq   r1, #83',
                            [T + 'test_gain_stub_switches_the_copies_not_the_root']),
    'playback-not-stock': ('rv_resident.S', '    mov     r1, #82\n    str     r1, [r0, #0x11C]\n    ldr     r0, [r4, #P_MAT]',
                           '    mov     r1, #81\n    str     r1, [r0, #0x11C]\n    ldr     r0, [r4, #P_MAT]',
                           [T + 'test_playback_command_puts_stock_contents_back']),
    'gain-ignores-shown': ('rv_resident.S', '    ldr     r1, [r3, #P_MODE]\n    cmp     ip, r1\n    bne     1f',
                           '    ldr     r1, [r3, #P_MODE]\n    cmp     ip, r1\n    nop',
                           [T + 'test_gain_stub_switches_the_copies_not_the_root']),
    'on-pick-ignored': ('rv_launch.S', '    cmp     r1, #0\n    moveq   r2, #1\n    movne   r2, #0',
                        '    cmp     r1, #0\n    moveq   r2, #0\n    movne   r2, #0',
                        [T + 'test_on_pick_follows_the_menu_and_one_row_is_active']),
    'flag-not-mirrored': ('rv_launch.S', '    strne   r2, [r3, #P_FLAG_R]', '    nop',
                          [T + 'test_the_pick_is_saved_into_its_own_file_and_restored_through_picked']),
    'picked-ignores-colour': ('rv_launch.S', '    cmp     r1, #0xC\n    moveq   r3, #1', '    cmp     r1, #0xC\n    mov     r3, #1',
                              [T + 'test_the_pick_is_saved_into_its_own_file_and_restored_through_picked']),
    'order-not-first': ('rv_launch.S', '    .word   CLC1, 2, RAWV_ID, 0 ', '    .word   CLC1, 2, RAWV_ID, 200 ',
                        [T + 'test_switching_lut_raw_stock_writes_the_records_and_restores_stock']),
    'early-not-prepared': ('rv_launch.S', '    moveq   r3, #3', '    moveq   r3, #2',
                           [T + 'test_both_load_orders_give_the_same_rows']),
    'page-reason-kept': ('rv_launch.S', '    str     r0, [r4, #CB_ROW + 8]', '    nop',
                         [T + 'test_both_load_orders_give_the_same_rows']),
    'no-dng-redirect': ('rv_launch.S', '    add     r3, r9, r3\n    MOVWT_R2 DNG_CM1_MOVW, DNG_CM1_MOVT\n    add     r3, r3, #72\n    MOVWT_R2 DNG_CM2_MOVW, DNG_CM2_MOVT\n    ARM     SITE_A, V_GS',
                        '    add     r3, r9, r3\n    ARM     SITE_A, V_GS',
                        [T + 'test_loads_after_col_share_with_its_own_sites_and_the_first_row']),
    'old-version': ('build_v3_rawview.py', 'COLS_VERSION = 0x000400', 'COLS_VERSION = 0x000301',
                    [T + 'test_loads_after_col_share_with_its_own_sites_and_the_first_row']),
    'site-b-unclaimed': ('build_v3_rawview.py', 'COLS_KEEP = {0xC0313244, 0xC032F728, ', 'COLS_KEEP = {0xC0313244, ',
                         [T + 'test_loads_after_col_share_with_its_own_sites_and_the_first_row']),
    'claims-a-colshare-site': ('build_v3_rawview.py', 'COLS_KEEP = {0xC0313244, ', 'COLS_KEEP = {0xC0075CF4, 0xC0313244, ',
                               [T + 'test_loads_after_col_share_with_its_own_sites_and_the_first_row']),
    # ---- API v2: the box (Bei 11-08) ----
    'cs-snap-off': ('colshare.c', '"   addgt   ip, r3, #268\\n"\n"   addlt   ip, r3, #248\\n"\n"   ldr     r0, [ip, r2, lsl #2]\\n"',
                    '"   nop\\n"\n"   nop\\n"\n"   nop\\n"', [BOX]),
    'cs-live-not-written': ('colshare.c', '"   strne   r0, [ip]\\n"', '"   nop\\n"', [BOX]),
    'cs-glyph-table-ignored': ('colshare.c', '"   addeq   r2, r6, r4\\n"', '"   nop\\n"',
                               [T + 'test_the_box_glyphs_follow_the_raw_row']),
    'cs-glyph-any-row': ('colshare.c', '"   bne     8f\\n"                           /* not the active row */', '"   nop\\n"',
                         [T + 'test_the_box_glyphs_follow_the_raw_row']),
    'cs-box-ignored': ('colshare.c', '            L->snap[j] = r[i].flags & COLS_R_SNAP;', '            L->snap[j] = 0;',
                       [T + 'test_switching_rows_changes_the_box']),
    'cs-v1-reads-box': ('colshare.c', 'cc->api >= 2u && cc->box ?', 'cc->box ?',
                        [T + 'test_a_version_1_client_has_no_box_field']),
    'rv-sset-no-lat': ('rv_launch.S', '    str     r2, [r3, #P_VAR_R]\n    bx      lr', '    nop\n    bx      lr', [BOX]),
    'rv-gain-ignores-box': ('rv_resident.S', '    movle   ip, #0\n    str     ip, [r3, #P_VAR]', '    movle   ip, #0\n    nop', [BOX]),
    'rv-box-not-from-record': ('rv_launch.S', '    movne   r1, #5\n    strne   r1, [r7, #CB_BOX]', '    movne   r1, #5\n    nop', [BOX]),
    'rv-wrong-glyph': ('rv_launch.S', '0xC18E6BB8 - STOCK_POOL, 0xC18E6990 - STOCK_POOL', '0xC18E6BB8 - STOCK_POOL, 0xC18E6918 - STOCK_POOL',
                       [T + 'test_the_box_glyphs_follow_the_raw_row']),
    'no-record-handed': ('rv_launch.S', '    ldr     ip, [r5, #API_SET_RECORD]\n    blx     ip\n    cmp     r0, #0',
                         '    mov     r0, #0\n    nop\n    cmp     r0, #0',
                         [T + 'test_switching_lut_raw_stock_writes_the_records_and_restores_stock']),
}


CONTROL = ('rv_launch.S', 'cb_rows:', 'cb_rows:', [T + 'test_loads_after_col_share_with_its_own_sites_and_the_first_row',
                                                     T + 'test_both_load_orders_give_the_same_rows'])


def main():
    names = sys.argv[1:] or ['control'] + list(MUTANTS)
    MUTANTS['control'] = CONTROL                         # unchanged sources: must pass, or the harness is broken
    survived = []
    for name in names:
        fname, old, new, tests = MUTANTS[name]
        src = (CS_SRC if fname == 'colshare.c' else HERE / fname).read_text()
        if src.count(old) != 1:
            print(f'{name}: pattern found {src.count(old)} times'); survived.append(name); continue
        top = Path(tempfile.mkdtemp(prefix='rawview-mut-', dir=HERE.parents[1]))
        try:
            b = top / 'build'
            shutil.copytree(HERE, b, ignore=shutil.ignore_patterns('out', '__pycache__'))
            (top / 'tools').symlink_to(HERE.parent / 'tools')       # rv_tables imports rv_curves from there
            env = dict(os.environ)
            if fname == 'colshare.c':
                (top / 'colshare.c').write_text(src.replace(old, new))
                env['COLSHARE_SOURCE'] = str(top / 'colshare.c')
            else:
                (b / fname).write_text(src.replace(old, new))
            r = subprocess.run([sys.executable, '-B', '-m', 'unittest', *tests], cwd=b, env=env, capture_output=True, text=True)
        finally:
            shutil.rmtree(top)
        killed = r.returncode != 0 and ('FAIL:' in r.stderr or 'ERROR:' in r.stderr)
        built = 'BuildError' not in r.stderr and 'SystemExit' not in r.stderr
        if name == 'control':
            print(f'control: {"passes" if not killed else "FAILS -- harness broken"}')
            if killed:
                print(r.stderr[-2000:]); return 2
            continue
        print(f'{name}: {"killed" if killed else "SURVIVED"}{"" if built else " (build error)"}')
        if not killed:
            survived.append(name)
    print('all killed' if not survived else f'survived: {survived}')
    return 1 if survived else 0


if __name__ == '__main__':
    raise SystemExit(main())
