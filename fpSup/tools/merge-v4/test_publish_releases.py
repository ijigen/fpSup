"""publish_releases.py against a stand-in for GitHub; no network, no token."""
import hashlib
import pathlib
import unittest

import publish_releases as P

HERE = pathlib.Path(__file__).resolve().parent


class FakeGitHub:
    def __init__(self, releases=()):
        self.store, self.log, self.next = [dict(r) for r in releases], [], 100

    def releases(self):
        return [dict(r, assets=[dict(a) for a in r['assets']]) for r in self.store]

    def create_draft(self, tag, title, body, prerelease, target):
        self.next += 1
        rel = dict(id=self.next, tag_name=tag, name=title, body=body, draft=True, prerelease=prerelease,
                   target=target, assets=[], upload_url=f'https://uploads/{self.next}/assets{{?name,label}}')
        self.store.append(rel)
        self.log.append(('create', tag))
        return dict(rel)

    def upload(self, release, name, data):
        rel = next(r for r in self.store if r['id'] == release['id'])
        assert rel['draft'] or not any(a['name'] == name for a in rel['assets'])
        rel['assets'].append(dict(name=name, size=len(data), state='uploaded',
                                  digest='sha256:' + hashlib.sha256(data).hexdigest()))
        self.log.append(('upload', rel['tag_name'], name))

    def publish(self, release):
        rel = next(r for r in self.store if r['id'] == release['id'])
        rel['draft'] = False
        self.log.append(('publish', rel['tag_name']))


def published(w, **change):
    return dict(id=1, tag_name=w['tag'], draft=False, upload_url='https://uploads/1/assets{?name,label}',
                assets=[dict(dict(name=f['name'], size=f['size'], state='uploaded', digest='sha256:' + f['sha256']), **change)
                        for f in w['files']])


class PublishReleasesTests(unittest.TestCase):
    def setUp(self):
        self.cat = P.catalogue(HERE / 'index.html')
        self.want = P.wanted(self.cat)
        self.quiet = lambda *_: None

    def test_one_release_per_offered_version_with_the_pages_bytes(self):
        self.assertEqual([w['tag'] for w in self.want], [p['release'] for p in self.cat['products']])
        rc = next(w for w in self.want if w['tag'].startswith('fpsup-res-custom-v'))
        self.assertEqual(sorted(f['name'] for f in rc['files'] if f['name'].endswith('.RCD')),
                         ['OG2K.RCD', 'OG35K.RCD', 'OG3K.RCD', 'OG4K.RCD', 'S16.RCD'])
        self.assertEqual(len(rc['files']), 6)
        for w in self.want:
            self.assertEqual(w['prerelease'], w['tag'].endswith('test'))
            self.assertIn('fpSup-Merge', w['body'])
            for f in w['files']:
                self.assertEqual(hashlib.sha256(f['path'].read_bytes()).hexdigest(), f['sha256'])
                # the URL the page requests is this tag / this asset name
                self.assertTrue(any(r.get('asset', '').endswith(f"/{w['tag']}/{f['name']}")
                                    for p in self.cat['products'] for r in [p, *p['data_files'], *p['support_files']]))

    def test_plan_only_changes_nothing(self):
        gh = FakeGitHub()
        self.assertEqual(P.run(gh, self.want, log=self.quiet), len(self.want))
        self.assertEqual(gh.log, [])

    def test_publish_creates_draft_uploads_then_publishes_and_is_idempotent(self):
        gh = FakeGitHub()
        self.assertEqual(P.run(gh, self.want, publish=True, target='abc123', log=self.quiet), 0)
        for w in self.want:
            ops = [op for op in gh.log if op[1] == w['tag']]
            self.assertEqual([op[0] for op in ops], ['create'] + ['upload'] * len(w['files']) + ['publish'])
        self.assertTrue(all(not r['draft'] and r['target'] == 'abc123' for r in gh.store))
        before = list(gh.log)
        self.assertEqual(P.run(gh, self.want, publish=True, log=self.quiet), 0)
        self.assertEqual(gh.log, before)

    def test_only_the_new_version_is_published(self):
        gh = FakeGitHub(published(w) for w in self.want[1:])
        self.assertEqual(P.run(gh, self.want, publish=True, log=self.quiet), 0)
        self.assertEqual({op[1] for op in gh.log}, {self.want[0]['tag']})

    def test_other_bytes_under_an_existing_tag_stop_everything(self):
        for change in (dict(digest='sha256:' + '0' * 64), dict(size=1)):
            gh = FakeGitHub([published(self.want[0], **change)])
            lines = []
            self.assertEqual(P.run(gh, self.want, publish=True, log=lines.append), len(self.want))
            self.assertEqual(gh.log, [])                       # not even the unrelated missing ones
            self.assertTrue(any('new version' in line for line in lines))

    def test_interrupted_run_is_finished_not_duplicated(self):
        w = next(w for w in self.want if len(w['files']) > 1)
        half = published(w)
        half['draft'], half['assets'] = True, half['assets'][:1]
        gh = FakeGitHub([half])
        self.assertEqual(P.run(gh, [w], publish=True, log=self.quiet), 0)
        self.assertEqual([op[0] for op in gh.log], ['upload'] * (len(w['files']) - 1) + ['publish'])
        self.assertEqual(len(gh.store), 1)

    def test_stale_page_is_refused(self):
        cat = P.catalogue(HERE / 'index.html')
        cat['products'][0]['sha256'] = '0' * 64
        with self.assertRaises(SystemExit):
            P.wanted(cat)


if __name__ == '__main__':
    unittest.main()
