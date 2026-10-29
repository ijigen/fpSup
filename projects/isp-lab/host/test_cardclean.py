"""cardclean deletes only the clip folders a take created, and refuses anything that is not a clip."""
import unittest

import cardclean as K

DIR = {'\\CINEMA': ['2026/10/27  15:26:14 <DIR>                A001_001', '2026/10/27  15:26:14 <DIR>                A001_002'],
       '\\CINEMA\\A001_002': ['2026/10/27  15:26:16                  298 SPP_metadata.xmp',
                              '2026/10/27  15:26:16               274432 A001_002_20261027.WAV',
                              '2026/10/27  15:26:14              3922432 A001_002_20261027_000001.DNG']}


class Fake:
    def __init__(self, tree):
        self.tree, self.cmds = {k: list(v) for k, v in tree.items()}, []

    def __call__(self, cmd):
        self.cmds.append(cmd)
        if cmd.startswith('dir '):
            return '\n'.join(['                                          .'] + self.tree.get(cmd[4:], []))
        if cmd.startswith('fl delDir '):
            name = cmd.rsplit('\\', 1)[1]
            self.tree['\\CINEMA'] = [l for l in self.tree['\\CINEMA'] if not l.endswith(name)]
        return 'OK'


class CardCleanTests(unittest.TestCase):
    def setUp(self):
        self.fake = Fake(DIR)
        self.saved, K._sh = K._sh, self.fake

    def tearDown(self):
        K._sh = self.saved

    def test_only_the_new_clip_goes(self):
        gone = K.remove_new({'A001_001'}, sleep=lambda s: None)
        self.assertEqual(gone, {'A001_002': 3})
        dels = [c for c in self.fake.cmds if c.startswith('fl ')]
        self.assertEqual(dels[-1], 'fl delDir \\CINEMA\\A001_002')
        self.assertTrue(all('A001_002' in c for c in dels))
        self.assertEqual(K.clips(), {'A001_001'})

    def test_nothing_new_nothing_deleted(self):
        self.assertEqual(K.remove_new({'A001_001', 'A001_002'}, sleep=lambda s: None), {})
        self.assertFalse([c for c in self.fake.cmds if c.startswith('fl ')])

    def test_refuses_odd_names_and_files(self):
        with self.assertRaises(ValueError):
            K.remove_clip('DCIM')
        self.fake.tree['\\CINEMA\\A001_002'].append('2026/10/27  15:26:16  10 notes.txt')
        with self.assertRaises(ValueError):
            K.remove_clip('A001_002')
        self.assertFalse([c for c in self.fake.cmds if c.startswith('fl del')])

    def test_a_folder_that_will_not_go_is_an_error(self):
        K._sh = lambda c: Fake.__call__(self.fake, c) if not c.startswith('fl delDir') else 'can\'t delete'
        with self.assertRaises(RuntimeError):
            K.remove_new({'A001_001'}, sleep=lambda s: None)

    def test_a_late_file_is_caught_on_the_next_look(self):
        late = {'n': 0}
        def sleep(_):                     # the recorder recreates the folder with one late frame, once
            if late['n'] == 0:
                self.fake.tree['\\CINEMA'].append('2026/10/27  15:26:14 <DIR>                A001_002')
                self.fake.tree['\\CINEMA\\A001_002'] = ['2026/10/27  15:26:58   750592 A001_002_20261027_000017.DNG']
            late['n'] += 1
        gone = K.remove_new({'A001_001'}, sleep=sleep)
        self.assertEqual(gone, {'A001_002': 4})
        self.assertEqual(K.clips(), {'A001_001'})


if __name__ == '__main__':
    unittest.main()
