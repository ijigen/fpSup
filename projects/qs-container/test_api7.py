"""API 7 (container v0.3.7, QSC_F_GO): AEL on a client's QS tile opens SIGMA's "Load from QR Code" page.

Three layers, offline (README v0.3.7):
  * real ARM: the container and QSTest (a Q_GO function "QR" with QSC_F_LOCK_REC, one "QX" without it, the API 4
    fine-mode "C") under test_qsct's rig -- AEL is the QSC_Key = 5 notification, the layout load is FUN_c05d90f0
    entered at its first word, recording is MOV_ACTIVE = 1;
  * the QS page as the record layer feeds it (test_qs_page.parse) judged with qs_page_data.Model: our object, its
    QSC_Go change event, its controlAppState whose request is the go text;
  * the private state machine (the FT4S file in the BIN) through the firmware's own NBR record interpreter, state
    builders and transition matcher (sl_pages.native_switch on out/MAIN_c0000000.bin), and the stock machines /
    the stock Y5_ReadQR page data for the way back.
What emulation cannot show: the GUI firing the change event and running the deferred request, the transition
itself, the read page entered from QS (README v0.3.7 "live").

    cd projects/qs-container && python3 -B -m unittest test_api7
    python3 -B test_api7.py --mutate
"""
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

import test_qsct as Q
import test_qs_page as P

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
QP, QT, E = Q.QP, Q.QT, Q.E
MOV_ACTIVE = 0xC35A952C
GO_TARGET = 0x100                          # qsc.h QSC_F_GO(t) = t << 8, in QSTest's config flags
FUNCS = QT.FUNCS + [('C', 'QS Test C', 'menu_cine_fps', QT.Q_FINE),
                    ('QR', 'QR', 'menu_crop', QT.Q_GO | QT.Q_LOCK),      # 57: GO, locked while recording
                    ('QX', 'QS Go X', 'menu_crop', QT.Q_GO)]           # 58: GO, no QSC_F_LOCK_REC
FI = {'A': 0, 'B': 1, 'C': 2, 'QR': 3, 'QX': 4}
SLOTS = (21, 54, 56, 57, 58, 9, 55, 19)
_clients = {}


def client(funcs=FUNCS, patch=None):
    """QSTest with `funcs`; `patch` (old, new) edits its source once (state() for the greyed case, ...)."""
    key = (repr(funcs), patch)
    if key not in _clients:
        if patch is None:
            _clients[key] = Q.tblob(funcs=funcs)
        else:
            src = (QT.HERE / 'qstest.c').read_text()
            assert src.count(patch[0]) == 1, patch
            with tempfile.TemporaryDirectory(prefix='qsc-api7-client-') as tmp:
                p = pathlib.Path(tmp) / 'client.c'
                p.write_text(src.replace(*patch))
                _clients[key] = QT.build(funcs=funcs, src=p)
    return _clients[key]


def boot(funcs=FUNCS, patch=None, slots=SLOTS, prepare=None):
    c = Q.boot([(Q.CNAME, Q.cblob()[0]), (Q.TNAME, client(funcs, patch))], prepare=prepare)
    c.layout()
    P.set_cine(c, slots)
    c.posts.clear()
    c.layout()
    return c


def api(c):
    return c.callsvc('find', 0x54435351)


def go_words(c):
    """struct st's v0.3.7 tail: go_result, go_armed, go_seq, goes, go_refused, go_skips (after tm[12] and the two
    lock-width arrays; tm is qsc_api.timing)"""
    names = ('go_result', 'go_armed', 'go_seq', 'goes', 'go_refused', 'go_skips')
    at = c.w(api(c) + 20) + 4 * (12 + 8 + 8)
    return dict(zip(names, struct.unpack('<6I', bytes(c.mu.mem_read(at, 24)))))


def demo(c, name):
    """QSTest's struct demo of function `name`: (address, {toggle, fines, unfines})"""
    table = c.callsvc('find', 0x53545351 ^ 0x80808080)
    arg = c.w(c.w(table + 8) + 60 * FI[name] + 44)
    return arg, {'toggle': c.w(arg + 4), 'fines': c.w(arg + 16), 'unfines': c.w(arg + 20)}


def go_text(c):
    return Q.cstr(c, c.block_of(Q.CNAME) + P.info()['go_text_off'])


def go_posts(c):
    return [v for n, v in c.posts if n == 'QSC_Go']


def ui_id(c, name, sup_id=0x53545351):
    a = api(c)
    p = Q.F6.FAKE + 0x7C00
    c.mu.mem_write(p, name.encode() + b'\0')
    fn = c.w(a + 8)
    r = c.call(fn & ~1, r0=a, r1=sup_id, r2=p, thumb=bool(fn & 1))[0]
    return r - (1 << 32) if r >> 31 else r


def request(c, name, how, sup_id=0x53545351):
    a = api(c)
    p = Q.F6.FAKE + 0x7C00
    c.mu.mem_write(p, name.encode() + b'\0')
    c.mu.reg_write(Q.T3.UC_ARM_REG_R3, how)
    fn = c.w(a + 16)
    return c.call(fn & ~1, r0=a, r1=sup_id, r2=p, thumb=bool(fn & 1))[0]


def go_pack():
    """(the BIN's FT4S go file, its NBR page pack)"""
    blob, info = Q.cblob()
    f = blob[info['go_file_off']:info['go_file_off'] + info['go_file_len']]
    pack_off, pack_len = struct.unpack_from('<2I', f, 4)
    return f, f[pack_off:pack_off + pack_len]


def stock_machines():
    """The stock NBM container (0xC2DE3D20, research/ui/tools/nbm_probe/dump_nbm.py): [(machine, from, to, event,
    condition)] of every transition."""
    d, base = Q.IMG, 0xC2DE3D20 - 0xC0000000
    o, recs = base + 12, []
    while True:
        tag, ln = struct.unpack_from('>II', d, o)
        recs.append((tag, o, ln))
        o += ln
        if tag == 0xFFFFFFFF:
            break
    pool = recs[0][1] + 8

    def s(x):
        return d[pool + x:d.index(b'\0', pool + x)].decode('latin1')
    out, cur = [], None
    for tag, o, ln in recs[1:]:
        w = struct.unpack_from('>%dI' % ((ln - 8) // 4), d, o + 8)
        if tag == 0x50002:
            cur = s(w[-1])
        elif tag == 0x50004:
            out.append((cur, s(w[0]), s(w[1]), s(w[2]), s(w[3])))
    return out


@Q.SKIP
class Go(unittest.TestCase):
    # ---- the API and the install --------------------------------------------------------------------
    def test_api_version_and_machine_installed(self):
        c = boot()
        self.assertEqual((c.w(api(c)), c.w(api(c) + 4)), (0x31415351, 9))   # 0.0.2test: API 9 (fine + sub)
        self.assertEqual(go_words(c)['go_result'], 0)
        f, pack = go_pack()
        ours = [call for call in c.nbr_calls if call[2] == pack]
        self.assertEqual(len(ours), 1, 'the go pack loaded once, at entry')
        self.assertEqual(c.vars['QSC_Go'], (0, 0))                     # an int variable, registered at collection
        self.assertEqual(go_text(c), '')                                # nothing asked until a go
        self.assertEqual([ui_id(c, n) for n in ('QR', 'QX', 'C')], [52, 53, 51])

    def test_registration_refuses_unknown_target_and_go_without_fine(self):
        bad = QT.FUNCS + [('QY', 'QS Go Y', 'menu_crop', QT.Q_GO | 2 * GO_TARGET), ('QR', 'QR', 'menu_crop', QT.Q_GO)]
        c = boot(funcs=bad, slots=(21, 54, 56, 25, 39, 9, 55, 19))
        self.assertEqual((ui_id(c, 'QY'), ui_id(c, 'QR')), (-1, 51))    # target 2 is no QSC_GO_*: refused
        c = boot(funcs=bad, patch=('            f->fine = qt_go;', '            f->fine = 0;'),
                 slots=(21, 54, 56, 25, 39, 9, 55, 19))
        self.assertEqual((ui_id(c, 'QY'), ui_id(c, 'QR')), (-1, -1))    # GO without fine(): refused

    # ---- AEL on a GO tile -----------------------------------------------------------------------------
    def test_ael_go_posts_the_request_and_leave_runs(self):
        c = boot()
        c.guid(57)
        self.assertEqual(c.guid_cur, 1)                                 # "AEL Further Options" on the GO tile
        self.assertIn(('QS_AELbtn', 1), c.posts)                        # the AEL object (our keyEvent) visible
        leaves = P.st(c, 'leaves')
        posts = P.press(c, 5, 57)
        self.assertEqual(demo(c, 'QR')[1], {'toggle': 1, 'fines': 1, 'unfines': 0})
        self.assertEqual([v for n, v in posts if n == 'QSC_Go'], [1])
        self.assertEqual(go_text(c), 'Y5_ReadQR')
        self.assertEqual((P.st(c, 'fine_on'), P.st(c, 'sub_open'), P.st(c, 'fines')), (0, -1, 0))
        self.assertEqual({k: go_words(c)[k] for k in ('go_armed', 'goes', 'go_refused', 'go_skips')},
                         {'go_armed': 1, 'goes': 1, 'go_refused': 0, 'go_skips': 0})
        self.assertFalse([n for n, _v in posts if n.startswith('MV_QSMENU')], 'the QS layout is not touched')
        c.layout()                                                      # the transition's layout load
        self.assertEqual(go_text(c), '', 'a QS built again must ask for nothing')
        self.assertEqual(go_words(c)['go_armed'], 0)
        self.assertEqual(P.st(c, 'leaves'), leaves + 1, "leave() runs when the go leaves the QS")
        self.assertEqual(demo(c, 'QR')[1]['unfines'], 0, 'fine(arg, 0) is never called for a go')
        c.layout()
        c.guid(57)
        posts = P.press(c, 5, 57)                                       # back in QS: a second go is a change again
        self.assertEqual([v for n, v in posts if n == 'QSC_Go'], [2])
        self.assertEqual(go_text(c), 'Y5_ReadQR')
        c.layout()
        self.assertEqual(demo(c, 'QR')[1], {'toggle': 1, 'fines': 2, 'unfines': 0})

    def test_ael_go_closes_an_open_sub_qs_first(self):
        """A sub-QS open elsewhere: AEL anywhere closes it first (stock rule); a GO from a fine mode ends it."""
        c = boot()
        c.guid(56)
        P.press(c, 5, 56)                                               # C: fine mode on
        self.assertEqual(P.st(c, 'fine_on'), 3)
        c.guid(57)                                                      # the focus moves to QR: fine ends
        self.assertEqual(P.st(c, 'fine_on'), 0)
        P.press(c, 5, 57)
        self.assertEqual((go_text(c), P.st(c, 'fine_on'), P.st(c, 'sub_open')), ('Y5_ReadQR', 0, -1))

    def test_client_says_no_nothing_happens(self):
        c = boot()
        arg, _d = demo(c, 'QR')
        c.put(arg + 4, 0)                                               # fine(arg, 1) answers 0
        c.guid(57)
        posts = P.press(c, 5, 57)
        self.assertEqual(demo(c, 'QR')[1], {'toggle': 0, 'fines': 1, 'unfines': 0})
        self.assertEqual(([v for n, v in posts if n == 'QSC_Go'], go_text(c)), ([], ''))
        self.assertEqual((go_words(c)['go_refused'], go_words(c)['goes'], P.st(c, 'fine_on')), (1, 0, 0))
        c.layout()
        self.assertEqual(demo(c, 'QR')[1]['unfines'], 0)

    def test_locked_greyed_or_recording_no_call(self):
        c = boot()
        c.put(MOV_ACTIVE, 1)                                            # recording
        for name, ui in (('QR', 57), ('QX', 58)):                       # QR: LOCK_REC; QX: none -- a go never
            c.guid(ui)                                                  # while recording
            posts = P.press(c, 5, ui)
            self.assertEqual(demo(c, name)[1]['fines'], 0, name)
            self.assertEqual(([v for n, v in posts if n == 'QSC_Go'], go_text(c)), ([], ''), name)
        self.assertEqual(go_words(c)['go_skips'], 1, 'QX reached the go and was skipped: recording')
        self.assertGreaterEqual(P.st(c, 'locked'), 1, 'QR stopped by its lock')
        c.put(MOV_ACTIVE, 0)
        # greyed: state() != 0 (QSTest's QX gets a state() that returns its demo's lock word)
        patch = ('        f->state = 0;\n', '        f->state = (c->flags[i] & Q_GO) && !(c->flags[i] & Q_LOCK) ? '
                 '(int (*)(void *))qt_lock_state : 0;\n')
        c = boot(patch=patch)
        arg, _d = demo(c, 'QX')
        c.put(arg + 8, 1)                                               # demo.lock = 1: greyed
        c.guid(58)
        posts = P.press(c, 5, 58)
        self.assertEqual((demo(c, 'QX')[1]['fines'], go_posts(c), go_text(c)), (0, [], ''))
        c.put(arg + 8, 0)                                               # not greyed: the go is asked
        P.press(c, 5, 58)
        self.assertEqual((demo(c, 'QX')[1]['fines'], go_text(c)), (1, 'Y5_ReadQR'))

    def test_no_machine_no_go(self):
        """The private machine refused at entry: AEL on a GO tile does nothing, fine() is not asked."""
        def refuse(cam):
            cam.nbr_result = 1
        c = boot(prepare=refuse)
        self.assertNotEqual(go_words(c)['go_result'], 0)
        c.guid(57)
        P.press(c, 5, 57)
        self.assertEqual((demo(c, 'QR')[1]['fines'], go_text(c), go_words(c)['go_skips']), (0, '', 1))

    def test_tile_without_go_bits_keeps_fine_mode_and_open_fine_refused_on_go(self):
        c = boot()
        c.guid(56)
        P.press(c, 5, 56)                                               # C (API 4 fine, no GO bits)
        self.assertEqual((P.st(c, 'fine_on'), P.st(c, 'fines'), go_posts(c), go_text(c)), (3, 1, [], ''))
        P.press(c, 5, 56)
        self.assertEqual(P.st(c, 'fine_on'), 0)
        self.assertEqual(request(c, 'QR', 2), 0, 'open(QSC_OPEN_FINE) is no way into a GO function')
        self.assertEqual(request(c, 'C', 2), 1)

    # ---- the QS page data ------------------------------------------------------------------------------
    def test_page_carries_the_go_event_and_request(self):
        c = boot()
        m = QP.Model(P.stream(P.parse(c)), P.text_of(c))
        root = m.named('Root')
        watching = [i for i, r in enumerate(m.recs) if E.be(r, 0) == QP.T_EVENT and m.comp(i) == 'appVariableChangeEvent'
                    and m.values(i).get('variable-name') == 'QSC_Go']
        self.assertEqual(len(watching), 1, 'one event on QSC_Go')
        oid = E.be(m.recs[watching[0]], 24)
        self.assertEqual(oid, P.info()['qs_notes'].get('go'))
        self.assertEqual((m.objs[oid]['name'], m.objs[oid]['parent']), ('ChangeScreen', root))
        evs = m.events(oid)
        self.assertEqual(list(evs), [1])
        ev = m.recs[evs[1]]
        self.assertEqual((m.comp(evs[1]), len(ev), E.be(ev, 32), E.be(ev, 16)), ('appVariableChangeEvent', 45, 3, 1))
        self.assertEqual(m.values(evs[1]), {'variable-name': 'QSC_Go', 'type': 3})   # loader v4's FT_Go form
        acts = m.actions(oid, 1)
        self.assertEqual([m.comp(i) for i in acts], ['controlAppState'])
        a = m.recs[acts[0]]
        self.assertEqual((len(a), E.be(a, 32)), (49, 0x23))            # the stock AEL's QS -> B2_5 form
        v = m.values(acts[0])
        self.assertEqual((v['app-sync-request'], v['view-state-event'], v['sync-request']), (0, 1, ''))
        _c, f = QP.fields(a)
        rid = E.be(a, f['sync-request'][0])
        self.assertEqual(rid, c.block_of(Q.CNAME) + P.info()['go_text_off'] - 0x80000000, 'the request is the go text')
        c.guid(57)
        P.press(c, 5, 57)
        self.assertEqual(m.values(acts[0])['sync-request'], 'Y5_ReadQR')   # read when the request runs
        self.assertEqual(m.objs[root]['n_children'], len(m.children(root)))

    # ---- the state machine -----------------------------------------------------------------------------
    def test_private_machine_through_the_stock_matcher(self):
        import sl_pages as SL
        f, pack = go_pack()
        self.assertEqual(f[52:64].rstrip(b'\0').decode(), QP.GO_MACHINE)
        old, SL.MACHINE = SL.MACHINE, QP.GO_MACHINE
        try:
            got = SL.native_switch(pack, [('QS_CINE', 'Y5_ReadQR'), ('QS_CINE', ''), ('QS_CINE', 'B2_5'),
                                          ('Y5_ReadQR', 'Return'), ('LV_CINE_LARGE', 'Y5_ReadQR'),
                                          ('MainY5', 'Y5_ReadQR')], Q.IMG)
        finally:
            SL.MACHINE = old
        self.assertEqual(got[('QS_CINE', 'Y5_ReadQR')], ('Y5_ReadQR', 0))
        self.assertIsNone(got[('QS_CINE', '')], 'an empty request (a QS built again) asks nothing')
        for q in (('QS_CINE', 'B2_5'), ('Y5_ReadQR', 'Return'), ('LV_CINE_LARGE', 'Y5_ReadQR'), ('MainY5', 'Y5_ReadQR')):
            self.assertIsNone(got[q], q)                                # everything else stays the stock machines'

    def test_stock_needs_the_private_machine_and_keeps_the_way_back(self):
        t = stock_machines()
        self.assertFalse([x for x in t if x[1] in ('QS_CINE', 'WildCard') and x[3] == 'Y5_ReadQR'],
                         'no stock transition reaches Y5_ReadQR from the QS')
        self.assertIn(('TransMain_Y', 'Y5_ReadQR', 'MainY5', 'Return', ''), t)    # MENU on the read page
        self.assertIn(('TransMain_Y', 'MainY5', 'Y5_ReadQR', 'Y5_ReadQR', ''), t)  # the stock way in
        self.assertIn(('TransSystem', 'WildCard', 'Choice0002', 'QS', ''), t)      # the QS button anywhere
        self.assertFalse([x for x in t if x[1] == 'QS_CINE' and not x[3]], 'no event-less transition from QS_CINE')
        # the read page's own keys (its NBU data): MENU -> "Return", the QS button -> "QS", no ChangeScreen
        # (the stock QS-AEL round trip by CM_TransitionFlag == 2 needs one: B2_5 has it, Y5_ReadQR does not)
        page = QP.Page(name='Y5_ReadQR')
        reqs = {}
        for o, _l, _n in [e for oid in page.objs for e in page.events(oid)]:
            if page.comp(o) != 'keyEvent':
                continue
            owner = E.be(page.data, o + 24)
            args = E.be(page.data, page.field(o, 'args')[0]) if 'args' in QP.fields(page.rec(o))[1] else None
            for a in page.actions_of(owner, E.be(page.data, o + 28)):
                if page.comp(a) == 'controlAppState' and 'sync-request' in QP.fields(page.rec(a))[1]:
                    reqs.setdefault(args, []).append(E.pool_str(E.be(page.data, page.field(a, 'sync-request')[0])))
        self.assertIn('Return', reqs[0x1B])
        self.assertEqual(reqs[0x14], ['QS'])
        self.assertNotIn('ChangeScreen', [n for n, _p in page.objs.values()])


# ---- mutations: (label, qsct.c old, new, test) or (label, 'qs', qs_page_data mutation, test) ------------------
MUTANTS = [
    ('no request posted', '    ((fn3)POST_INT)(0, (u32)(uintptr_t)qc_name(s, S_GO), ++s->go_seq);\n', '    ++s->go_seq;\n',
     'test_ael_go_posts_the_request_and_leave_runs'),
    ('wrong request text', '    const char *pg = (const char *)(s->block + c->go_page_off);',
     '    const char *pg = qc_name(s, S_GO);', 'test_ael_go_posts_the_request_and_leave_runs'),
    ('request text never emptied', '        *(char *)(uintptr_t)(s->block + s->cfg->go_text_off) = 0;\n', '',
     'test_ael_go_posts_the_request_and_leave_runs'),
    ('fine(0) called after a go', '    s->go_armed = 1;\n', '    s->go_armed = 1;\n    s->fine_on = i + 1u;\n',
     'test_ael_go_posts_the_request_and_leave_runs'),
    ('GO run as a fine mode', '    if (qc_go_target(&s->fx[i])) { qc_go(s, i); return; }     /* API 7: a stock page, not a fine mode */\n',
     '', 'test_ael_go_posts_the_request_and_leave_runs'),
    ('client answer ignored', '    if (!((int (*)(void *, int))s->xfine[i])((void *)(uintptr_t)s->fx[i].arg, 1)) { s->go_refused++; return; }',
     '    ((int (*)(void *, int))s->xfine[i])((void *)(uintptr_t)s->fx[i].arg, 1);', 'test_client_says_no_nothing_happens'),
    ('lock / grey ignored', '    if (qc_locked(s, i)) { s->locked++; return; }\n    if (qc_go_target(&s->fx[i])) { qc_go(s, i); return; }',
     '    if (qc_go_target(&s->fx[i])) { qc_go(s, i); return; }\n    if (qc_locked(s, i)) { s->locked++; return; }',
     'test_locked_greyed_or_recording_no_call'),
    ('go while recording without LOCK_REC', 'qc_go_target(&s->fx[i]) != QSC_GO_READQR || busy()) { s->go_skips++; return; }',
     'qc_go_target(&s->fx[i]) != QSC_GO_READQR) { s->go_skips++; return; }', 'test_locked_greyed_or_recording_no_call'),
    ('go without the machine', '    if (s->go_result || qc_go_target', '    if (qc_go_target', 'test_no_machine_no_go'),
    ('machine never installed', '        u32 r = fpui_install(svc, s->block + c->go_file_off);', '        u32 r = 0;',
     'test_api_version_and_machine_installed'),
    ('API version still 6', 's->api.version = 9;', 's->api.version = 6;', 'test_api_version_and_machine_installed'),
    ('unknown target accepted', '(!v4 || go != QSC_GO_READQR || !q->fine || q->sub)', '(!v4 || !q->fine || q->sub)',
     'test_registration_refuses_unknown_target_and_go_without_fine'),
    ('GO without fine accepted', '(!v4 || go != QSC_GO_READQR || !q->fine || q->sub)', '(!v4 || go != QSC_GO_READQR || q->sub)',
     'test_registration_refuses_unknown_target_and_go_without_fine'),
    ('open(FINE) into a GO function', '(at || !s->xfine[i] || qc_go_target(&s->fx[i]))', '(at || !s->xfine[i])',
     'test_tile_without_go_bits_keeps_fine_mode_and_open_fine_refused_on_go'),
    ('go variable registered as text', '                     k == S_GO || k == S_DHB), def[3];',
     '                     k == S_DHB), def[3];',
     'test_api_version_and_machine_installed'),
    ('request id not the go text', '        *v = (u32)(uintptr_t)(s->block + s->cfg->go_text_off) - SL_ALIAS;',
     '        *v = qc_name_id(s, S_GO);', 'test_page_carries_the_go_event_and_request'),
    ('data: no go object', 'qs', 'nogo', 'test_page_carries_the_go_event_and_request'),
    ('data: request is a variable name', 'qs', 'goreqname', 'test_page_carries_the_go_event_and_request'),
    ('data: event watches QSC_Key', 'qs', 'gowatchkey', 'test_page_carries_the_go_event_and_request'),
    ('data: transition missing', 'qs', 'gonotrans', 'test_private_machine_through_the_stock_matcher'),
    ('data: transition from live view', 'qs', 'gotransfrom', 'test_private_machine_through_the_stock_matcher'),
]


def mutate():
    source = (HERE / 'qsct.c').read_text()
    passed, caught_n = True, 0
    only = [a for a in sys.argv[1:] if a != '--mutate']
    todo = [m for m in MUTANTS if not only or any(o in m[0] for o in only)]
    for label, old, new, test in todo:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        if env.get('SL_TESTCACHE', '1') != '0':
            env['SL_TESTCACHE'] = 'ro'
        with tempfile.TemporaryDirectory(prefix='qsc-api7-mut-') as tmp:
            env['PYTHONPYCACHEPREFIX'] = tmp
            if old == 'qs':
                env['QSCT_QS_MUTATE'] = new
                os.environ['QSCT_QS_MUTATE'] = new
                try:
                    Q.Q.build()                                    # a build failure must never count as a catch
                finally:
                    del os.environ['QSCT_QS_MUTATE']
            else:
                assert source.count(old) == 1, label
                src = pathlib.Path(tmp) / 'qsct.c'
                src.write_text(source.replace(old, new))
                Q.Q.build(src=src)                                 # a compile failure must never count as a catch
                env['QSCT_SRC'] = str(src)
            p = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-q', 'test_api7.Go.' + test],
                               cwd=HERE, env=env, capture_output=True, text=True)
        caught = p.returncode != 0 and ('FAIL: ' + test) in p.stderr
        caught_n += caught
        print(('CAUGHT' if caught else 'UNVERIFIED/SURVIVED') + ': ' + label, flush=True)
        if not caught:
            print(p.stdout + p.stderr)
            passed = False
    print(f'{caught_n}/{len(todo)} mutants caught')
    return 0 if passed else 1


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        raise SystemExit(mutate())
    unittest.main()
