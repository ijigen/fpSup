"""run_checklist.py against a fake camera (no USB): the step logic, expectations, safety rules, freeze stop, --from."""
import json, pathlib, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_checklist as R

VER = '0.7.2test'
SQ_OFF = json.loads((R.SL / 'qs/out' / f'build-{VER}.json').read_text())['sq_test_off']
BLOCK = 0xC55F9D40
LOG = (f'0A C55BCC80 00000008 QSContainer_v0.3.2.BIN\r\n0A {BLOCK:08X} 00000025 SensorLab-IMX410_v{VER}.BIN\r\n')


class Fake:
    """a camera model: screens move with keys, sq_test structs in a word memory, a clock, a freeze switch"""

    def __init__(self):
        self.t = 0.0
        self.screen_ = 'LV_CINE_MEDIUM'
        self.vars = {'MENU_Level1': 0, 'MENU_Level2': 0, 'MENU_Level3': 0}
        self.words = {}
        self.ap = dict(armed=1, active=1, commits=3, result=0, gated=0, standby_picks=10, owed=0)
        self.menu = dict(ready=1, result=0, picks=0, owed=0, rejected=0, opened=0)
        self.frozen_at = None
        self.calls, self.keys, self.recording_ = [], [], False
        self.usb_while_rec = 0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def alive_(self):
        return self.frozen_at is None or self.t < self.frozen_at

    def ping(self):
        self.t += 0.05
        return self.alive_()

    def recording(self):
        return self.recording_

    def key(self, name, n=1):
        self.keys.append(name)
        if name == 'MENU':
            self.screen_ = 'MainB1' if self.screen_.startswith('LV') else 'LV_CINE_MEDIUM'
        elif name == 'RIGHT' and self.screen_ == 'MainB1':
            self.screen_ = 'MainB2'
        elif name == 'OK' and self.screen_ == 'B2_5':
            self.menu['picks'] += 1; self.menu['owed'] = 1
        return 0

    def _struct(self, op):
        names = R.STRUCTS[op]
        src = {17: self.ap, 27: self.menu, 18: {}}[op]
        base = 0xC4000000 + op * 0x10000
        for i, k in enumerate(names):
            self.words[base + 4 * i] = src.get(k, 0) & 0xFFFFFFFF
        for k, off in R.EXTRA.get(op, {}).items():
            self.words[base + off] = src.get(k, 0)
        return base

    def call(self, addr, r0=0, r1=0, r2=0):
        self.calls.append((addr, r0))
        assert addr == BLOCK + SQ_OFF, hex(addr)
        if r0 in R.STRUCTS:
            return self._struct(r0)
        return 0

    def mem(self, addr, n):
        if self.recording_:
            self.usb_while_rec += 1
        return [self.words.get(addr + 4 * i, 0) for i in range(n)]

    def screen(self):
        return self.screen_

    def app_vars(self, names):
        return {k: self.vars.get(k, 0) for k in names}

    def getfile(self, remote, local, size=None):
        if remote.endswith('LOAD.LOG'):
            pathlib.Path(local).write_text(LOG)
            return True
        return False

    def shot(self, n, local):
        pathlib.Path(local).write_bytes(b'jpg')
        return True

    def rec_take(self, s):
        self.recording_ = True; self.t += s; self.recording_ = False; self.t += R.POST_REC_S

    def latest_clip(self):
        return None


def runner(fake, d):
    r = R.Runner(fake, d, VER)
    r.qsc = None
    r.ask = lambda prompt: True
    r.next_shot = 100
    return r


class Steps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def lines(self):
        return [json.loads(x) for x in (self.d / 'results.jsonl').read_text().splitlines()]

    def test_boot_item_passes_and_reads_the_offset_from_the_build_json(self):
        f = Fake()
        status, rows = runner(f, self.d).run([it for it in R.load_checklist('v1').items(VER) if it['id'] == 1])
        self.assertEqual(status, 'done')
        self.assertEqual(rows[0][1], 'PASS', rows[0][2])
        self.assertTrue(all(a == BLOCK + SQ_OFF for a, _ in f.calls))
        self.assertIn('| 1 | 開機 | PASS |', (self.d / 'summary.md').read_text())

    def test_expectations_refs_and_position(self):
        f = Fake()
        items = [{'id': 3, 'title': 't', 'steps': [
            {'do': 'sq', 'op': 17, 'save': 'a'},
            {'do': 'keys', 'keys': ['MENU'], 'at': {'screen': 'MainB1'}},
            {'do': 'sq', 'op': 17, 'expect': {'commits': {'ref': 'a.commits', 'add': 1}}, 'stop_on_fail': False},
            {'do': 'keys', 'keys': ['RIGHT'], 'at': {'screen': 'B2_5'}}]}]
        f.ap['commits'] = 3
        r = runner(f, self.d)
        r.block = BLOCK
        status, rows = r.run(items)
        self.assertEqual(rows[0][1], 'FAIL')
        bad = [x for x in self.lines() if 'bad' in x]
        self.assertEqual(bad[0]['bad']['commits'], {'want': {'ref': 'a.commits', 'add': 1}, 'got': 3})
        self.assertEqual(bad[1]['bad']['at.screen'], {'want': 'B2_5', 'got': 'MainB2'}, 'the UI log, not a screenshot')

    def test_unsafe_keys_are_refused(self):
        for k in ('S1', 'S2', 'MOVON', 'MOV', 'PLAY', 'CAPTURE'):
            f = Fake()
            status, rows = runner(f, self.d).run([{'id': 1, 'title': 't', 'steps': [{'do': 'keys', 'keys': [k]}]}])
            self.assertEqual(rows[0][1], 'FAIL', k)
            self.assertEqual(f.keys, [], k)

    def test_no_usb_right_after_a_recording(self):
        f = Fake()
        r = runner(f, self.d)
        r.block = BLOCK
        r.rec_stop = f.now()                          # as if a recording had just stopped
        status, rows = r.run([{'id': 1, 'title': 't', 'steps': [{'do': 'sq', 'op': 17}]}])
        self.assertEqual(rows[0][1], 'FAIL')
        self.assertIn('after the recording stopped', rows[0][2][0])
        self.assertEqual(f.calls, [])

    def test_rec_step_never_touches_usb_while_recording(self):
        f = Fake()
        r = runner(f, self.d)
        r.block = BLOCK
        status, rows = r.run([{'id': 12, 'title': 't', 'steps': [{'do': 'rec', 's': 3},
                                                                  {'do': 'sq', 'op': 17}]}])
        self.assertEqual((status, rows[0][1]), ('done', 'PASS'), rows[0][2])
        self.assertEqual(f.usb_while_rec, 0)

    def test_freeze_stops_the_run_with_the_last_action(self):
        f = Fake()
        f.frozen_at = 1.0
        items = [{'id': 2, 'title': 'menu', 'steps': [{'do': 'pingkey', 'key': 'MENU', 'before': 0.5, 'after': 10}]},
                 {'id': 3, 'title': 'never', 'steps': [{'do': 'keys', 'keys': ['OK']}]}]
        status, rows = runner(f, self.d).run(items)
        self.assertTrue(status.startswith('FREEZE'), status)
        self.assertEqual([it['id'] for it, _, _ in rows], [2])
        self.assertNotIn('OK', f.keys)
        s = (self.d / 'summary.md').read_text()
        self.assertIn('FREEZE', s)
        self.assertIn('pingkey MENU', s)
        self.assertEqual(self.lines()[-1]['last'], 'pingkey MENU')

    def test_a_reply_timeout_that_recovers_is_not_a_freeze(self):
        f = Fake()
        f.frozen_at = 1.0
        items = [{'id': 2, 'title': 'menu', 'steps': [{'do': 'pingkey', 'key': 'MENU', 'before': 0.5, 'after': 6}]}]
        r = runner(f, self.d)
        orig = f.ping
        f.ping = lambda: orig() or f.t > 3.0         # 2 s silent, then answers again
        status, rows = r.run(items)
        self.assertEqual(status, 'done')
        self.assertGreater(json.loads((self.d / 'results.jsonl').read_text().splitlines()[0])['got']['max_gap'], 1.5)

    def test_from_skips_earlier_items_and_manual_items_are_marked(self):
        f = Fake()
        items = R.load_checklist('v1').items(VER)
        r = runner(f, self.d)
        status, rows = r.run([it for it in items if it['id'] in (0, 1, 8, 10)], first=1)
        self.assertEqual([(it['id'], v) for it, v, _ in rows], [(1, 'PASS'), (8, 'MANUAL'), (10, 'MANUAL')])

    def test_the_v1_checklist_is_well_formed(self):
        items = R.load_checklist('v1').items(VER)
        self.assertEqual([it['id'] for it in items], list(range(18)))
        for it in items:
            for st in it['steps']:
                self.assertIn(st['do'], R.Runner.STEPS, (it['id'], st))
                for k in st.get('keys', []):
                    name = k.partition(':')[0]
                    self.assertTrue(k.startswith('wait') or name in R.KEYS, (it['id'], k))
        recs = [it['id'] for it in items for st in it['steps'] if st['do'] == 'rec']
        self.assertEqual(recs, [12, 13, 14], 'recording only through rec')


if __name__ == '__main__':
    unittest.main()
