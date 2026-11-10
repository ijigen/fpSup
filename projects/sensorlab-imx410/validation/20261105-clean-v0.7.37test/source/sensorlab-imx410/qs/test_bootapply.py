"""SensorLab-IMX410 v0.7.35test: the recorded selection applied after boot without MENU / QS (qs/slqs.c "boot apply").

On the real SensorLab BIN in the real v4 core with the real QSContainer (test_slqs.boot), the real firmware image:
  - sup_entry creates the poller task only with a valid record (tk_cre_tsk / tk_sta_tsk recorded, not run);
  - sup_entry registers SLM_Boot and its UI-thread callback (v0.7.37test; the boot LV screen enters before the sups
    load); the standby screen's enter and the first leave() are fallbacks (the harness's real GUI variable code);
  - one poll at a time (sq_test 47): nothing before a standby LV start + the mode descriptor, nothing while recording,
    a post after BOOT_STABLE ready polls; the callback (sq_test 48) commits -> sq_test 17 active = 1;
  - idempotent with a later leave(); never during recording; no record -> no task, nothing applied.

    cd projects/sensorlab-imx410/qs && python3 -B -m unittest test_bootapply
    python3 -B test_bootapply.py --mutate
"""
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_slqs as S                     # noqa: E402
import build_slqs as BS                   # noqa: E402

Q1 = S.Q1
RECORD_SRC = HERE.parent / 'validation' / '20261104-qr-scan-build3' / 'live' / 'readback.BIN'   # the card's v0.7.34test
TK_CRE, TK_STA, GUI_POST = 0xC0016A58, 0xC0016BC0, 0xC0593F30
PICKER, TABS = 0xC043CCF8, 0xC0BE4990
MOV_ACTIVE = 0xC35A952C
BOOT_NAMES = 'task var_ok polls ready_polls posts runs done why last_rc last_post tries stable stby_ok stby_enters lv_load entry_rc'.split()
STBY_V72, STBY_STOCK = 0xC0CD7A88, 0xC0481D80
GUI_OBJECT = 0xC37B7048
LV_HOLDER_FN, CINE_FN, LVH = 0xC0423C48, 0xC0058340, 0xC3F3E000
KEY = 0xC3F3F000
_card = {}


def card():
    if 'c' not in _card:
        _card['c'] = BS.build(settings_from=RECORD_SRC)[0]
    return _card['c']


sys.path.insert(0, str(HERE.parent / 'menu'))
import runtime_camera as RC              # noqa: E402  (the menu harness: the GUI variable registry)


class BootCam(RC.Cam):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.tasks, self.boot_posts = [], []

    def _hook(self, mu, addr, size, data):
        if addr in (TK_CRE, TK_STA, GUI_POST):
            from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2
            r0, r1, r2 = (self.r(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
            if addr == TK_CRE:
                self.tasks.append(struct.unpack('<8I', bytes(mu.mem_read(r0, 32))))
                return self._ret(7)
            if addr == TK_STA:
                return self._ret(0)
            if self.cstr(r1) == 'SLM_Boot':
                self.boot_posts.append(r2)
        return super()._hook(mu, addr, size, data)


def boot(record=True, descriptor=False):
    with patch.object(Q1, 'Cam', BootCam):
        c = S.boot(card=card() if record else None, descriptor=descriptor)
    assert ('SLM_Boot' in c.registered_names) == record
    return c


def boot_noleave():
    """the real boot with no layout load at all (no MENU / QS ever); the standby screen's own enter body is replaced
    by bx lr -- it is the screen's, not under test; SensorLab's wrapper in its vtable word is"""
    def prep(cam):
        S.ap_firmware(cam, False)
        cam.mu.mem_write(STBY_STOCK, struct.pack('<I', 0xE12FFF1E))
    with patch.object(Q1, 'Cam', BootCam):
        return Q1.boot([(Q1.CNAME, Q1.cblob()[0]), (BS.file_name(), card())], prepare=prep)


def boot_lvup(cine=1, lv=True):
    """the live order (11-05): the boot LV is already running when the sups load -- descriptor built, the LV holder
    running (its state +4 nonzero), CinemaMode cine (0 = STILL); no picker call, no standby enter, no leave()"""
    def prep(cam):
        S.ap_firmware(cam, True)
        cam.mu.mem_write(STBY_STOCK, struct.pack('<I', 0xE12FFF1E))
        cam.put(LVH, LVH + 0x10); cam.put(LVH + 0x10, 0xC3F3E100); cam.put(LVH + 0x14, 3 if lv else 0)
        cam.mu.mem_write(LV_HOLDER_FN, struct.pack('<3I', 0xE59F0000, 0xE12FFF1E, LVH))   # ldr r0, [pc]; bx lr
        cam.cine = bool(cine)                                                             # the harness's IS_CINE
        for a in (0xC0423D28, 0xC0423C88, 0xC02073B8):                                    # LV stop / start, CS set
            cam.mu.mem_write(a, struct.pack('<I', 0xE12FFF1E))
        for a in (0xC0207188, 0xC0207440):                                                # CamSch, CS get: 6
            cam.mu.mem_write(a, struct.pack('<2I', 0xE3A00006, 0xE12FFF1E))
    with patch.object(Q1, 'Cam', BootCam):
        return Q1.boot([(Q1.CNAME, Q1.cblob()[0]), (BS.file_name(), card())], prepare=prep)


def boot_nogui():
    """boot_noleave with no GUI object while the sups load (restored by the test: cam.gui_saved)"""
    def prep(cam):
        S.ap_firmware(cam, False)
        cam.mu.mem_write(STBY_STOCK, struct.pack('<I', 0xE12FFF1E))
        cam.gui_saved = cam.w(GUI_OBJECT)
        cam.put(GUI_OBJECT, 0)
    with patch.object(Q1, 'Cam', BootCam):
        return Q1.boot([(Q1.CNAME, Q1.cblob()[0]), (BS.file_name(), card())], prepare=prep)


def state(c):
    a = S.sqt(c, 46)
    w = struct.unpack('<%di' % len(BOOT_NAMES), bytes(c.mu.mem_read(a, 4 * len(BOOT_NAMES))))
    return dict(zip(BOOT_NAMES, w))


def active(c):
    a = S.sqt(c, 17)
    names = S.AP_STATUS if hasattr(S, 'AP_STATUS') else None
    return a, names


def ap_status(c):
    import importlib
    sys.path.insert(0, str(HERE.parent / 'apply'))
    TA = importlib.import_module('test_apply')
    a = S.sqt(c, 17)
    keys = TA.STATUS_KEYS if hasattr(TA, 'STATUS_KEYS') else None
    return a, keys


def lv_start(c):
    """the standby LV start: the picker (its hook counts it) and the mode descriptor built"""
    c.mu.mem_write(KEY, b'MOV\0')
    c.call(PICKER, r0=0, r1=TABS, r2=KEY)
    S.ap_firmware(c, descriptor=True)


def poll(c, n):
    return [S.sqt(c, 47) for _ in range(n)]


def callback(c):
    return S.sqt(c, 48)


def pushes(c):
    return S.sqt(c, 20)


def live_slot(c):
    """sq_test 17 = struct ap_status: active is word 3 (after bytes, abi, armed)"""
    a = S.sqt(c, 17)
    return c.w(a + 12)


@S.SKIP
class BootApply(unittest.TestCase):
    def test_a_record_starts_the_poller_and_the_first_leave_registers_the_variable(self):
        c = boot()
        b = state(c)
        self.assertEqual(len(c.tasks), 1)
        d = c.tasks[0]
        self.assertEqual((d[1], d[3], d[4]), (0x41, 28, 0x800))            # TA_HLNG|TA_DSNAME, priority, stack
        self.assertEqual(d[2] & 3, 0)                                       # an ARM entry: the trampoline
        self.assertEqual((c.w(d[2]), c.w(d[2] + 4)), (0xE51FF004, S.fn_addr(c, 'sq_boot_task') | 1))
        self.assertEqual((b['task'], b['var_ok'], b['done']), (7, 1, 0))    # S.boot's layouts ran leave()
        subs = [(ctx, fn) for ctx, n, fn in c.subs if n == 'SLM_Boot']
        self.assertEqual(subs, [(0xC37B7048, S.fn_addr(c, 'sq_boot_changed') | 1)])   # the UI-thread callback

    def test_no_leave_ever_registers_at_load_and_the_selection_applies(self):
        """v0.7.37test, live 11-05: the boot LV screen enters before the sups load, so sup_entry registers"""
        c = boot_noleave()
        b = state(c)
        self.assertEqual((b['task'], b['var_ok'], b['stby_ok'], b['stby_enters']), (7, 1, 1, 0))
        self.assertEqual(c.w(STBY_V72), S.fn_addr(c, 'sl_stby_v72') | 1)
        self.assertEqual(c.registered_names.count('SLM_Boot'), 1)
        self.assertEqual([fn for _x, n, fn in c.subs if n == 'SLM_Boot'], [S.fn_addr(c, 'sq_boot_changed') | 1])
        c.call(c.w(STBY_V72), r0=0xC3F40100)                               # back to LV later: registered once
        self.assertEqual((state(c)['stby_enters'], c.registered_names.count('SLM_Boot')), (1, 1))
        self.assertEqual(len([n for _x, n, _f in c.subs if n == 'SLM_Boot']), 1)
        lv_start(c)
        self.assertEqual(poll(c, 5)[-1], 1)
        callback(c)
        self.assertEqual((state(c)['done'], live_slot(c)), (1, 1))

    def test_lv_already_up_at_load_applies_with_no_key(self):
        """live 11-05 cold boot: the boot LV was running at sup_entry; the commit there (Bei: RES-Custom's way) takes,
        done, the poller never posts (the boot UI-thread callback never ran live: runs 0)"""
        c = boot_lvup()
        b = state(c)
        self.assertEqual((b['var_ok'], b['lv_load'], b['stby_enters']), (1, 1, 0))
        self.assertEqual((b['entry_rc'], b['done'], live_slot(c)), (0, 1, 1))
        self.assertEqual(poll(c, 8), [0] * 8)
        self.assertEqual(c.boot_posts, [])

    def test_still_at_load_stays_stock_and_waits(self):
        """STILL at boot (Bei: stays stock): no entry commit, the poller never ready while STILL"""
        c = boot_lvup(cine=0)
        b = state(c)
        self.assertEqual((b['lv_load'], b['entry_rc'], b['done'], live_slot(c)), (0, -99, 0, 0))
        self.assertEqual(poll(c, 8), [0] * 8)
        self.assertEqual(c.boot_posts, [])

    def test_no_lv_at_load_the_entry_commit_still_takes(self):
        """live 11-05 warm restart: no LV at sup_entry (lv_load 0), descriptor built: the commit takes (entry_rc 0,
        active 1); the LV then starts on our mode"""
        c = boot_lvup(lv=False)
        b = state(c)
        self.assertEqual((b['lv_load'], b['entry_rc'], b['done'], live_slot(c)), (0, 0, 1, 1))
        self.assertEqual(poll(c, 8), [0] * 8)

    def test_poller_ready_with_a_running_lv_and_no_picker(self):
        """the fallback's readiness (ap_boot_ready): a CINE LV running counts with no picker call (live: picks 0)"""
        c = boot_noleave()                                                  # no descriptor at load: entry not ready
        self.assertNotEqual(state(c)['entry_rc'], 0)
        S.ap_firmware(c, True)
        c.mu.mem_write(LV_HOLDER_FN, struct.pack('<3I', 0xE59F0000, 0xE12FFF1E, LVH))
        c.mu.ctl_flush_tb()                     # sup_entry ran the no-LV stub: drop its translated block
        c.put(LVH, LVH + 0x10); c.put(LVH + 0x10, 0xC3F3E100); c.put(LVH + 0x14, 3)
        for a in (0xC0423D28, 0xC0423C88, 0xC02073B8):
            c.mu.mem_write(a, struct.pack('<I', 0xE12FFF1E))
        for a in (0xC0207188, 0xC0207440):
            c.mu.mem_write(a, struct.pack('<2I', 0xE3A00006, 0xE12FFF1E))
        self.assertEqual(poll(c, 5), [0, 0, 0, 0, 1])
        callback(c)
        self.assertEqual((state(c)['done'], live_slot(c)), (1, 1))

    def test_no_gui_at_load_the_standby_screen_registers(self):
        """fallback: no GUI object at sup_entry (why 5); the standby screen's enter registers later, once"""
        c = boot_nogui()
        b = state(c)
        self.assertEqual((b['task'], b['var_ok'], b['why'], b['stby_ok']), (7, 0, 5, 1))
        self.assertNotIn('SLM_Boot', c.registered_names)
        c.put(GUI_OBJECT, c.gui_saved)
        c.call(c.w(STBY_V72), r0=0xC3F40100)                               # the LV screen comes up (GUI thread)
        b = state(c)
        self.assertEqual((b['var_ok'], b['stby_enters']), (1, 1))
        c.call(c.w(STBY_V72), r0=0xC3F40100)                               # again: registered and subscribed once
        self.assertEqual(c.registered_names.count('SLM_Boot'), 1)
        self.assertEqual([f for f in c.subscription_failures if f[1] == 'SLM_Boot'], [])
        lv_start(c)
        self.assertEqual(poll(c, 5)[-1], 1)
        callback(c)
        self.assertEqual((state(c)['done'], live_slot(c)), (1, 1))

    def test_no_gui_at_load_the_first_leave_registers(self):
        """fallback: no GUI object at sup_entry and no standby enter; the first leave() (MENU / QS) registers"""
        c = boot_nogui()
        c.put(GUI_OBJECT, c.gui_saved)
        c.layout()
        self.assertEqual((state(c)['var_ok'], state(c)['stby_enters']), (1, 0))
        self.assertEqual(c.registered_names.count('SLM_Boot'), 1)

    def test_a_foreign_standby_word_is_left_alone(self):
        def prep(cam):
            S.ap_firmware(cam, False)
            cam.put(STBY_V72, 0xC0001235)
        with patch.object(Q1, 'Cam', BootCam):
            c = Q1.boot([(Q1.CNAME, Q1.cblob()[0]), (BS.file_name(), card())], prepare=prep)
        self.assertEqual((state(c)['stby_ok'], c.w(STBY_V72)), (0, 0xC0001235))

    def test_no_record_no_task_nothing_owed(self):
        c = boot(record=False)
        self.assertEqual((c.tasks, state(c)['task'], state(c)['why']), ([], -1, 1))
        lv_start(c)
        self.assertEqual(poll(c, 10), [0] * 10)
        self.assertEqual(c.boot_posts, [])

    def test_waits_for_lv_then_posts_and_the_callback_applies(self):
        c = boot()
        self.assertEqual(live_slot(c), 0)                                   # the boot leave(): no descriptor yet
        self.assertEqual(poll(c, 8), [0] * 8)                               # no LV start: never ready
        self.assertEqual(c.boot_posts, [])
        lv_start(c)
        got = poll(c, 5)
        self.assertEqual(got, [0, 0, 0, 0, 1])                              # BOOT_STABLE ready polls, then a post
        self.assertEqual(c.boot_posts, [1])
        before = pushes(c)
        callback(c)
        b = state(c)
        self.assertEqual((b['runs'], b['done'], b['last_rc']), (1, 1, 0))
        self.assertEqual(pushes(c), before + 1)
        self.assertEqual(live_slot(c), 1)                                   # the record's mode is live
        self.assertEqual(poll(c, 10), [0] * 10)                             # done: no more posts
        # a later leave() (MENU / QS) pushes the same selection: nothing to do
        c.layout()
        self.assertEqual((live_slot(c), S.sqt(c, 16)), (1, 1))             # still live; flush: AP_IDLE

    def test_never_while_recording(self):
        c = boot()
        lv_start(c)
        c.mu.mem_write(MOV_ACTIVE, b'\x01')
        self.assertEqual(poll(c, 10), [0] * 10)
        before = pushes(c)
        callback(c)                                                         # a stale post arriving while recording
        self.assertEqual((pushes(c), state(c)['done'], live_slot(c)), (before, 0, 0))
        c.mu.mem_write(MOV_ACTIVE, b'\x00')
        self.assertEqual(poll(c, 5)[-1], 1)
        callback(c)
        self.assertEqual((state(c)['done'], live_slot(c)), (1, 1))

    def test_posts_are_spaced_and_bounded(self):
        c = boot()
        lv_start(c)
        self.assertEqual(poll(c, 5)[-1], 1)
        self.assertEqual(poll(c, 20), [0] * 20)                             # 1.5 s apart: the tick does not move here
        b = state(c)
        self.assertEqual((b['posts'], b['tries']), (1, 1))


MUTANTS = [
    ('entry commit in STILL', '    if (!busy() && ap_cine_now()) {', '    if (!busy()) {'),
    ('entry commit not done', '        if (st->ap_rc == AP_OK || st->ap_rc == AP_IDLE) st->boot.done = 1;\n', ''),
    ('no commit at entry', '        sq_push(st);\n        st->boot.entry_rc = st->ap_rc;', '        st->boot.entry_rc = -98;'),
    ('ready needs the picker', '    if (!A->lv_seen && !ap_cine_lv_now()) return 0;', '    if (!A->lv_seen) return 0;', 'apply/ap.c'),
    ('ready ignores the LV', '    if (!A->lv_seen && !ap_cine_lv_now()) return 0;', '', 'apply/ap.c'),
    ('LV now ignores STILL', '    return ((ap_fw1)AP_CINE)(((ap_fw0)AP_GET_OBJ)()) && ap_lv_running(&holder);', '    return ap_lv_running(&holder);', 'apply/ap.c'),
    ('LV now ignores the holder', '    return ((ap_fw1)AP_CINE)(((ap_fw0)AP_GET_OBJ)()) && ap_lv_running(&holder);', '    (void)holder; return ((ap_fw1)AP_CINE)(((ap_fw0)AP_GET_OBJ)());', 'apply/ap.c'),
    ('no lv at load call', '    st->boot.lv_load = (u32)ap_lv_at_load(st->ap_mem);', '    st->boot.lv_load = 0;'),
    ('entry does not register', '     * and the first leave() stay as fallbacks (both skip once var_ok). */\n    boot_watch_body(st);\n', '     */\n'),
    ('no standby hook', '        W(STBY_V72) = (u32)(uintptr_t)sl_stby_v72;\n', ''),
    ('standby hook over any word', 'if (W(STBY_V72) == STBY_V72_STOCK && st->svc->claim', 'if (st->svc->claim'),
    ('standby enter does not register', '    if (!st->boot.var_ok && st->boot.task > 0 && boot_owed(st)) boot_watch_body(st);\n', ''),
    ('standby enter registers every time', '    if (!st->boot.var_ok && st->boot.task > 0 && boot_owed(st)) boot_watch_body(st);', '    if (st->boot.task > 0 && boot_owed(st)) boot_watch_body(st);'),
    ('no task', '    s32 id = ((s32 (*)(volatile u32 *))TK_CRE_TSK)(d);', '    s32 id = 0; (void)d;'),
    ('task without a record', '    if (!st->loaded) { st->boot.why = 1; return; }    /* no record', '    if (0) { st->boot.why = 1; return; }    /* no record'),
    ('no stability wait', '    if (++b->stable < BOOT_STABLE) return 0;', '    ++b->stable;'),
    ('poll ignores readiness', '    if (!ap_boot_ready(st->ap_mem) || busy()) { b->stable = 0; return 0; }', '    if (busy()) { b->stable = 0; return 0; }'),
    # (recording is guarded twice: busy() here and ap_busy() in ap_boot_ready -- removing one alone is an equivalent
    #  mutant at this level; apply/test_apply.py BootReadyTests + its mutants cover ap_boot_ready's own guard)
    ('callback does not push', '    sq_push(st);\n    st->boot.last_rc', '    st->boot.last_rc'),
    ('never done', '{ st->boot.done = 1; st->boot.why = 0; ap_idle(st->ap_mem); }', '{ st->boot.why = 0; ap_idle(st->ap_mem); }'),
    ('no spacing', '    if (b->posts && ap_now_us() - b->last_post < BOOT_GAP_US) return 0;\n', ''),
    ('no variable', '    st->boot.var_ok = 1;\n', ''),
    ('leave does not register', '    boot_watch(st);                                   /* v0.7.35test', '    (void)boot_watch;                                   /* v0.7.35test'),
]


def mutate():
    src = (HERE / 'slqs.c').read_text()
    survived = []
    apsrc = (HERE.parent / 'apply' / 'ap.c').read_text()
    for name, a, b, *where in MUTANTS:
        target = apsrc if where else src
        assert target.count(a) == 1, name
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        if env.get('SL_TESTCACHE', '1') != '0':
            env['SL_TESTCACHE'] = 'ro'
        with tempfile.TemporaryDirectory(prefix='boot-mut-') as t:
            env['PYTHONPYCACHEPREFIX'] = t
            m = pathlib.Path(t) / 'slqs.c'
            if where:                                   # ap.c: a mutated copy found first on the include path
                (pathlib.Path(t) / 'ap.c').write_text(apsrc.replace(a, b))
                m.write_text(src.replace('#include "ap.c"', '#include "%s"' % (pathlib.Path(t) / 'ap.c')))
            else:
                m.write_text(src.replace(a, b))
            shutil.copy(HERE / 'qrdec.c', pathlib.Path(t) / 'qrdec.c')
            env['SLQS_SRC'] = str(m)
            try:
                BS.compile_text(m)
            except BS.BuildError as e:
                print('BAD (does not build) ' + name + ': ' + str(e)[:200], flush=True)
                survived.append(name)
                continue
            r = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-q', 'test_bootapply'],
                               cwd=HERE, env=env, capture_output=True, text=True)
            caught = r.returncode != 0 and ('FAILED' in r.stderr or 'Error' in r.stderr)
        print(('caught   ' if caught else 'SURVIVED ') + name, flush=True)
        if not caught:
            survived.append(name)
    return survived


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        s = mutate()
        print('survived:', s)
        sys.exit(1 if s else 0)
    unittest.main()
