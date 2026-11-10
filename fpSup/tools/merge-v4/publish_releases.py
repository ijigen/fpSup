#!/usr/bin/env python3
"""Every sup version the Merge page offers is a GitHub Release (Bei 2026-11-10).

    python3 -B tools/merge-v4/publish_releases.py              what is on GitHub, what is missing
    python3 -B tools/merge-v4/publish_releases.py --check      exit 1 unless everything is there
    python3 -B tools/merge-v4/publish_releases.py --publish    create what is missing (GH_TOKEN)

GitHub counts each asset's downloads; the page requests the assets of a card
when its zip is downloaded and shows the totals (template.html: countDownloads,
loadCounts).  So the count only means something if the asset is exactly what
the page puts on cards.  This reads the built index.html -- the catalogue the
page itself uses -- and for each product wants

    tag     the product's `release`           fpsup-lossless-v0.3.1
    assets  its .BIN and its data files       Lossless_v0.3.1.BIN

with the catalogue's size and sha256.  A release is never rewritten: an asset
of that name with other bytes stops the run -- new bytes are a new version
(names_v4.py), which is a new tag with its own count.  --publish makes a draft,
uploads, then publishes it, so a release is never visible half filled.

The Pages workflow runs --publish before it deploys, so a pushed page never
names an asset that is not there.  Nothing here reads a camera or a card.
"""
import argparse, hashlib, json, os, pathlib, re, sys, urllib.error, urllib.parse, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
PAGE = 'https://ijigen.github.io/fpSup/tools/card-composer/'


def catalogue(index):
    page = index.read_text(encoding='utf-8')
    return json.loads(re.search(r'<script id="cat" type="application/json">(.*?)</script>', page, re.S)[1])


def wanted(cat, root=HERE):
    """[{tag, title, prerelease, body, files: [{name, path, size, sha256}]}], one per offered product."""
    out = []
    for p in cat['products']:
        records = [p, *p.get('data_files', []), *p.get('support_files', []), *([p['virtual']] if p.get('virtual') else [])]
        files = []
        for r in records:
            if not r.get('asset'):
                raise SystemExit(f"{p['id']}: a file without a release asset (snapshot outside tools/merge-v4?)")
            prefix = f"https://github.com/{cat['repo']}/releases/download/{p['release']}/"
            if not r['asset'].startswith(prefix):
                raise SystemExit(f"{p['id']}: asset is not under its own tag: {r['asset']}")
            path = root / r['src']
            b = path.read_bytes()
            if len(b) != r['size'] or hashlib.sha256(b).hexdigest() != r['sha256']:
                raise SystemExit(f"{r['src']}: not the bytes the page names; rebuild index.html")
            files.append(dict(name=r['asset'][len(prefix):], path=path, size=r['size'], sha256=r['sha256']))
        current = next((h for h in p.get('history', []) if h.get('current')), {})
        changes = current.get('changes', {})
        body = [f"{p['name']} v{p['version']} for the SIGMA fp (firmware Ver.5.02), Loader v4.", '',
                f"The file here is the sup alone, not a card. Make a card with fpSup-Merge: {PAGE}", '']
        for lang in ('en', 'zh'):
            if changes.get(lang):
                body += [f'- {line}' for line in changes[lang]] + ['']
        body += [f"`{f['name']}` sha256 `{f['sha256']}`" + '  ' for f in files]
        out.append(dict(tag=p['release'], title=f"{p['name']} v{p['version']}", body='\n'.join(body).rstrip() + '\n',
                        prerelease=p['version'].endswith('test'), files=files))
    return out


class GitHub:
    """The four calls this needs.  Tests put a stand-in here."""
    def __init__(self, repo, token=None):
        self.repo, self.token = repo, token

    def _call(self, method, url, data=None, content_type='application/json'):
        headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
                   'User-Agent': 'merge-page-releases'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        if data is not None:
            headers['Content-Type'] = content_type
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as res:
                return json.loads(res.read() or b'null')
        except urllib.error.HTTPError as e:
            raise SystemExit(f'GitHub {method} {url.split("?")[0]}: {e.code} {e.read().decode(errors="replace")[:300]}')

    def releases(self):
        out, page = [], 1
        while True:
            got = self._call('GET', f'https://api.github.com/repos/{self.repo}/releases?per_page=100&page={page}')
            out += got
            if len(got) < 100:
                return out
            page += 1

    def create_draft(self, tag, title, body, prerelease, target):
        payload = dict(tag_name=tag, name=title, body=body, draft=True, prerelease=prerelease)
        if target:
            payload['target_commitish'] = target
        return self._call('POST', f'https://api.github.com/repos/{self.repo}/releases', json.dumps(payload).encode())

    def upload(self, release, name, data):
        url = release['upload_url'].split('{')[0] + '?name=' + urllib.parse.quote(name)
        return self._call('POST', url, data, 'application/octet-stream')

    def publish(self, release):
        return self._call('PATCH', f"https://api.github.com/repos/{self.repo}/releases/{release['id']}",
                          json.dumps(dict(draft=False)).encode())


def compare(want, existing):
    """Per wanted release: (state, release-or-None, files to upload, problems).

    state: 'ok' everything is there; 'missing' no release; 'draft' / 'partial' a
    release without all its assets; 'conflict' an asset with other bytes."""
    by_tag = {}
    for r in existing:
        by_tag.setdefault(r['tag_name'], r)
    out = []
    for w in want:
        rel = by_tag.get(w['tag'])
        if rel is None:
            out.append(('missing', None, list(w['files']), []))
            continue
        have = {a['name']: a for a in rel.get('assets', [])}
        todo, problems = [], []
        for f in w['files']:
            a = have.get(f['name'])
            if a is None:
                todo.append(f)
            elif a.get('state', 'uploaded') != 'uploaded':
                problems.append(f"{f['name']}: an upload that did not finish; delete that asset on GitHub and run again")
            elif a['size'] != f['size'] or (a.get('digest') and a['digest'] != 'sha256:' + f['sha256']):
                problems.append(f"{f['name']}: GitHub has other bytes under {w['tag']} "
                                f"({a['size']} B {a.get('digest') or 'no digest'}); the page has {f['size']} B sha256:{f['sha256']}. "
                                'New bytes need a new version, not a rewritten release')
        state = 'conflict' if problems else 'draft' if rel.get('draft') else 'partial' if todo else 'ok'
        out.append((state, rel, todo, problems))
    return out


def run(gh, want, publish=False, target=None, log=print):
    """Returns the number of wanted releases that are not complete on GitHub afterwards."""
    plan = compare(want, gh.releases())
    for w, (state, _rel, todo, problems) in zip(want, plan):
        log(f"  {state:<8} {w['tag']:<36} {', '.join(f['name'] for f in w['files'])}"
            + (f"   to upload: {', '.join(f['name'] for f in todo)}" if todo and state != 'missing' else ''))
        for line in problems:
            log('           ' + line)
    if any(state == 'conflict' for state, *_ in plan):
        log('nothing changed: resolve the conflicts first')
        return sum(state != 'ok' for state, *_ in plan)
    if not publish:
        return sum(state != 'ok' for state, *_ in plan)
    for w, (state, rel, todo, _problems) in zip(want, plan):
        if state == 'ok':
            continue
        if rel is None:
            rel = gh.create_draft(w['tag'], w['title'], w['body'], w['prerelease'], target)
        for f in todo:
            gh.upload(rel, f['name'], f['path'].read_bytes())
        if rel.get('draft'):
            gh.publish(rel)
        log(f"  published {w['tag']}")
    left = sum(state != 'ok' for state, *_ in compare(want, gh.releases()))
    if left:
        log(f'{left} release(s) still not as the page names them')
    return left


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--index', type=pathlib.Path, default=HERE / 'index.html')
    ap.add_argument('--check', action='store_true', help='exit 1 unless every asset is on GitHub')
    ap.add_argument('--publish', action='store_true', help='create the missing releases (needs GH_TOKEN or GITHUB_TOKEN)')
    ap.add_argument('--target', help='commit the new tags point at (default: the default branch)')
    a = ap.parse_args()
    cat = catalogue(a.index)
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if a.publish and not token:
        raise SystemExit('--publish needs GH_TOKEN or GITHUB_TOKEN (contents: write on the repository)')
    want = wanted(cat)
    print(f"{cat['repo']}: {len(want)} offered versions")
    left = run(GitHub(cat['repo'], token), want, publish=a.publish, target=a.target)
    if not left:
        print('every offered version is a release with the page\'s bytes')
    sys.exit(1 if left and (a.check or a.publish) else 0)


if __name__ == '__main__':
    main()
