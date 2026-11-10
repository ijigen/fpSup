"""Version history tests; no card building or camera access."""
import json
import pathlib
import re
import tempfile
import unittest

from release_history import HERE, attach_history, readme_changes


class VersionHistoryTests(unittest.TestCase):
    def test_retained_versions_and_exact_current_build(self):
        page = (HERE / 'index.html').read_text()
        cat = json.loads(re.search(r'<script id="cat"[^>]*>(.*?)</script>', page, re.S)[1])
        before = json.dumps(cat, sort_keys=True)
        attach_history(cat, HERE.parent.parent / 'releases')
        self.assertEqual(json.dumps(cat, sort_keys=True), before)
        translated = json.loads((HERE / 'version_notes.json').read_text())
        for p in cat['products']:
            self.assertEqual([h['release'] for h in p['history'] if h['current']], [p['release']])
            for h in p['history']:
                if h['release'] in translated:
                    self.assertTrue(h['changes']['en'])
                    self.assertTrue(h['changes']['zh'])
                self.assertTrue((HERE / h['source']).is_file(), h['source'])
        lossless = next(p for p in cat['products'] if p['id'] == 'lossless')
        # v4: every product is the v4 snapshot, named by its version; the v3 releases stay as history
        self.assertEqual(lossless['release'], 'fpsup-lossless-v0.3.2test')
        self.assertEqual(lossless['history'][0]['release'], lossless['release'])
        self.assertIn('fpsup-lossless-v0.3.0test', [h['release'] for h in lossless['history']])
        # a version an earlier snapshot offered stays in the history, with its notes, not current
        old = [h for h in lossless['history'] if h['release'] == 'fpsup-lossless-v0.3.1']
        self.assertEqual([(h['current'], bool(h['changes'].get('zh'))) for h in old], [(False, True)])
        self.assertTrue(all(p['release'].startswith(f"fpsup-{p['id']}-v") for p in cat['products']))
        self.assertTrue(all(not p['history'] for p in cat['pending']))

    def test_new_release_fallback_sorting_and_draft_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            releases = pathlib.Path(tmp)
            for name in ['fpsup-new-sup-v0.2.0test', 'fpsup-new-sup-v0.10.0test',
                         'fpsup-new-sup-v0.10.0', '_draft-fpsup-new-sup-v99.0',
                         'fpsup-other-v99.0']:
                d = releases / name
                d.mkdir()
                (d / 'README.txt').write_text('WHAT CHANGED\n\n  - New feature.\n    Continues here.\n\nHOW TO USE\n\n  Copy files.')
            cat = dict(products=[dict(id='new-sup', release='fpsup-new-sup-v0.10.0test')])
            attach_history(cat, releases)
            history = cat['products'][0]['history']
            self.assertEqual([h['version'] for h in history], ['0.10.0', '0.10.0test', '0.2.0test'])
            self.assertFalse(history[0]['current'])
            self.assertTrue(history[1]['current'])
            self.assertEqual(history[0]['changes'], dict(en=['New feature. Continues here.']))

    def test_hyphenated_product_and_non_cumulative_changes(self):
        raw = HERE.parent.parent / 'releases/fpsup-raw-view-v0.2.2test/README.txt'
        changes = readme_changes(raw)
        self.assertEqual(len(changes), 1)
        self.assertIn('Playback is stock again.', changes[0])
        self.assertNotIn('Since v0.2.0test', changes[0])
        self.assertNotIn('HOW TO USE', changes[0])

    def test_missing_changes_are_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            readme = pathlib.Path(tmp) / 'README.txt'
            self.assertEqual(readme_changes(readme), [])
            readme.write_text('WHAT IT IS\n\n  A product description.\n')
            self.assertEqual(readme_changes(readme), [])


if __name__ == '__main__':
    unittest.main()
