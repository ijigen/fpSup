"""The v1 live checklist (qs/README.md「v1 上機清單」, v0.7.2test expectations) as data for run_checklist.py.

Positions come from the UI log (`at`: screen + page focus variables + the container's sub_open / QS focus), never from
screenshots; `shot` steps are only the visual checks (`look: True` puts them in the summary's "look at" list).
Focus ids: MainB2 MENU_Level1 650 = 記錄設定, 21879 = DC; B2_5 MENU_Level2 4247 = 格式, 4254 = 解析度, 4434 = 每秒幀數
(menu/slm_page.py SPEC; fp-ui-selftest map).  If a path is off, fix the keys here, not on the camera.
Items 0, 8, 10, 15, 16 need hands or a phone: MANUAL (not run).  `pause` steps wait for Enter (a selection by hand).
"""
LV = {'startswith': 'LV'}
# from the live view to B2_5 (記錄設定), whichever page the menu remembers
TO_B25 = {'do': 'nav', 'by': {'MainB1': ['RIGHT', 'DOWN:2', 'RIGHT', 'wait1'],
                              'MainB2': ['RIGHT', 'wait1']},
          'at': {'screen': 'B2_5'}}
MENU = {'do': 'keys', 'keys': ['MENU', 'wait1'], 'at': {'screen': {'in': ['MainB1', 'MainB2']}}}


def ap(save=None, **expect):
    return {'do': 'sq', 'op': 17, 'save': save, 'expect': expect}


def menu(save=None, **expect):
    return {'do': 'sq', 'op': 27, 'save': save, 'expect': expect}


def items(version):
    claims = '00000027' if version == '0.7.3test' else '00000025'
    return [
        {'id': 0, 'title': '部署', 'steps': [
            {'do': 'manual', 'text': f'deploy_v3 with --settings-from, read back; card: SensorLab v{version} + '
                                     'QSContainer v0.3.2 only, no SLTP / RES-Custom'}]},
        {'id': 1, 'title': '開機', 'stop_run': True, 'steps': [
            {'do': 'loadlog', 'expect': {'sl': [version], 'sl_claims': claims, 'qsc': ['QSContainer_v0.3.2.BIN'],
                                         'sltp': False}},
            {'do': 'sq', 'op': 21, 'decode': False, 'expect': {'value': 0}},
            ap(armed=1),
            {'do': 'where', 'at': {'screen': LV}, 'expect': {'screen': LV}}]},
        {'id': 2, 'title': '首個 MENU', 'stop_run': True, 'steps': [
            {'do': 'pingkey', 'key': 'MENU', 'before': 2, 'after': 12, 'save': 'menu1',
             'at': {'screen': 'MainB1'}, 'expect': {'max_gap': {'lt': 3.0}}},
            {'do': 'sq', 'op': 29, 'decode': False, 'words': 16},
            {'do': 'sq', 'op': 31, 'decode': False, 'words': 12},
            menu('m2', ready=1, result=0),
            ap('a2', active=1, result=0)]},
        {'id': 3, 'title': '選單：解析度', 'steps': [
            MENU, TO_B25,
            {'do': 'keys', 'keys': ['DOWN:2'], 'at': {'MENU_Level2': 4254}},
            {'do': 'keys', 'keys': ['RIGHT', 'wait1']},
            {'do': 'shot', 'tag': 'res-list', 'look': True},
            menu('m3'), ap('a3'),
            {'do': 'keys', 'keys': ['UP']},
            {'do': 'pingkey', 'key': 'OK', 'before': 1, 'after': 6, 'save': 'ok3', 'expect': {'max_gap': {'lt': 3.0}}},
            menu(None, picks={'ref': 'm3.picks', 'add': 1}, owed=1, rejected=0),
            ap(None, commits={'ref': 'a3.commits'}),
            {'do': 'to_lv', 'at': {'screen': LV}},
            ap('a3b', commits={'ref': 'a3.commits', 'add': 1}, owed=0),
            menu(None, owed=0)]},
        {'id': 4, 'title': '選單：每秒幀數', 'steps': [
            MENU, TO_B25,
            {'do': 'keys', 'keys': ['DOWN:3'], 'at': {'MENU_Level2': 4434}},
            {'do': 'keys', 'keys': ['RIGHT', 'wait1']},
            {'do': 'shot', 'tag': 'fps-list', 'look': True},     # the 1000 row reads 1000.0 (not 關閉)
            {'do': 'keys', 'keys': ['MENU']},
            {'do': 'to_lv', 'at': {'screen': LV}}]},
        {'id': 5, 'title': '選單：位元深度', 'steps': [
            MENU, TO_B25,
            {'do': 'keys', 'keys': ['DOWN:1', 'RIGHT', 'wait1']},
            {'do': 'shot', 'tag': 'bits-list', 'look': True},     # 8 / 10 bit grey, RAW selectable
            {'do': 'keys', 'keys': ['MENU']},
            {'do': 'to_lv', 'at': {'screen': LV}}]},
        {'id': 6, 'title': '選單：DC', 'steps': [
            MENU,
            {'do': 'nav', 'by': {'MainB1': ['RIGHT', 'DOWN:1'], 'MainB2': ['UP']}, 'at': {'MENU_Level1': 21879}},
            {'do': 'keys', 'keys': ['RIGHT', 'wait1']},
            {'do': 'shot', 'tag': 'dc-list', 'look': True},
            {'do': 'keys', 'keys': ['MENU']},
            {'do': 'to_lv', 'at': {'screen': LV}}]},
        {'id': 7, 'title': 'FPS CUSTOM 跳轉（焦點 FINE，第一下 AEL）', 'steps': [
            MENU, TO_B25,
            {'do': 'keys', 'keys': ['DOWN:3'], 'at': {'MENU_Level2': 4434}},
            {'do': 'keys', 'keys': ['RIGHT', 'wait1', 'UP']},    # the list's last row = CUSTOM (wraps from the top)
            menu('m7'), ap('a7'),
            {'do': 'pingkey', 'key': 'OK', 'before': 1, 'after': 6, 'at': {'screen': 'QS_CINE', 'sub_open': {'ge': 0}}},
            menu(None, opened={'ref': 'm7.opened', 'add': 1}),
            {'do': 'keys', 'keys': ['DIAL1:1', 'wait1']},
            ap(None, commits={'ref': 'a7.commits', 'add': 1}),     # v0.7.2test: FINE applies per step (Bei: confirm)
            {'do': 'keys', 'keys': ['AEL', 'wait1'], 'at': {'sub_open': -1}},   # container v0.3.2: the FIRST AEL works
            {'do': 'shot', 'tag': 'fine-back', 'look': True},
            {'do': 'keys', 'keys': ['QS', 'wait1']},
            {'do': 'to_lv', 'at': {'screen': LV}}]},
        {'id': 8, 'title': 'QS 取代模式（編輯器）', 'steps': [{'do': 'manual', 'text': 'editor slots by hand'}]},
        {'id': 9, 'title': 'QS FPS 子 QS：開機後第一下 AEL', 'steps': [
            {'do': 'keys', 'keys': ['QS', 'wait1'], 'at': {'screen': 'QS_CINE'}},
            {'do': 'shot', 'tag': 'qs', 'look': True},
            {'do': 'pause', 'text': 'move the focus to FPS by hand if it is not there (the slot depends on the editor)'},
            {'do': 'keys', 'keys': ['AEL', 'wait1'], 'at': {'sub_open': {'ge': 0}}},
            {'do': 'keys', 'keys': ['AEL', 'wait1'], 'at': {'sub_open': -1}},
            {'do': 'keys', 'keys': ['QS', 'wait1'], 'at': {'screen': LV}}]},
        {'id': 10, 'title': 'QR（手機掃）', 'steps': [{'do': 'manual', 'text': 'phone scan vs sq_test 13'}]},
        {'id': 11, 'title': 'MB/s 與 RATIO 版面', 'steps': [
            {'do': 'keys', 'keys': ['QS', 'wait1'], 'at': {'screen': 'QS_CINE'}},
            {'do': 'shot', 'tag': 'qs-mbps', 'look': True},
            {'do': 'keys', 'keys': ['QS', 'wait1'], 'at': {'screen': LV}}]},
        {'id': 12, 'title': '錄影 A：OG 2K 14b 1x3（12-bit 容器）', 'steps': [
            {'do': 'pause', 'text': 'select OG 2K, RECIPE 14b 1x3 in the QS first'},
            ap('a12', active=1),
            {'do': 'rec', 's': 3},
            {'do': 'curmode', 'expect': {'value': {'in': [230, 231]}}},
            {'do': 'dng', 'frame': 40, 'tag': 'A', 'expect': {'bits': 12, 'white': 4095}}]},
        {'id': 13, 'title': '錄影 B：OG 6K 14b 1x1（真 14）', 'steps': [
            {'do': 'pause', 'text': 'select OG 6K, RECIPE 14b 1x1'},
            {'do': 'rec', 's': 3},
            {'do': 'curmode', 'expect': {'value': {'in': [230, 231]}}},
            {'do': 'dng', 'frame': 3, 'tag': 'B', 'expect': {'bits': 14, 'white': 16383}}]},
        {'id': 14, 'title': '錄影 C：HD 2K 11b 3x2（v0.7.1 凍結的那組）', 'stop_run': True, 'steps': [
            {'do': 'pause', 'text': 'select HD 2K, RECIPE 11b 3x2'},
            ap('a14', active=1, gated=0, result=0),
            {'do': 'shot', 'tag': 'standby-3x2', 'look': True},
            {'do': 'wait', 's': 30},
            ap(None, gated=0, standby_picks={'ref': 'a14.standby_picks', 'cmp': 'gt'}),
            {'do': 'curmode', 'save': 'm14', 'expect': {'value': {'in': [230, 231]}}},
            {'do': 'rec', 's': 3},
            {'do': 'curmode', 'expect': {'value': {'ref': 'm14.value'}}},
            {'do': 'dng', 'frame': 20, 'tag': 'C', 'expect': {'bits': 12}}]},
        {'id': 15, 'title': '回放安全', 'steps': [{'do': 'manual', 'text': 'no USB: Bei, by hand'}]},
        {'id': 16, 'title': '暖開機', 'steps': [{'do': 'manual', 'text': 'unplug, power switch, replug'}]},
        {'id': 17, 'title': '收尾：回原廠', 'steps': [
            {'do': 'sq', 'op': 22, 'decode': False},
            ap(None, active=0)]},
    ]
