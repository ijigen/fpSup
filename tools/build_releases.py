#!/usr/bin/env python3
"""Generate the Releases tables from releases/ — so adding a release edits nothing.

    ./tools/build_releases.py            rewrite the tables in place
    ./tools/build_releases.py --check    fail if they are stale (this is what CI runs)

**Source of truth is `releases/`, not `git tag`.** The two are the same set by the
rule in releases/TAGS.md, but the directories are what the site links to and what
Pages serves, and they are present in the shallow checkout the workflow makes —
tags are not, without an extra fetch.

Each release folder carries its own one-line blurb in `ABOUT.txt`:

    en: what it does, in one line
    zh: 一行說明

If there is no ABOUT.txt the banner line of README.txt is used instead. The
version-specific test log belongs in the release's own README.txt, not here —
the table says what a product is, not what changed.

Only the newest release of each product is listed, by the rule in
releases/README.md: compare the numeric segments as integers, then the
qualifier — none is newest, then letters, then `test`.
"""
import html as _html
import pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
RELEASES = ROOT / 'releases'
# A product may carry hyphens -- `fpsup-gyro-base-v1.2` is the Base edition of the
# gyro, a separate product here because it is a separate card you choose instead of
# the other one. The `-v<digit>` boundary is what ends the name, so backtracking
# settles product on `gyro-base` and not on `gyro-base-v1`.
NAME = re.compile(
    r'^fpsup-(?P<product>[a-z0-9]+(?:-[a-z0-9]+)*)-v(?P<num>\d+(?:\.\d+)*)(?P<qual>[a-z]*)$')


def rank(qual):
    """none is newest, then letters (b > a), then test."""
    if qual == '':
        return (2, '')
    if qual == 'test':
        return (0, '')
    return (1, qual)


def blurb(d):
    about = d / 'ABOUT.txt'
    out = {}
    if about.exists():
        for line in about.read_text(encoding='utf-8').splitlines():
            if ':' in line:
                k, _, v = line.partition(':')
                if k.strip() in ('en', 'zh'):
                    out[k.strip()] = v.strip()
    if 'en' not in out:
        readme = d / 'README.txt'
        if readme.exists():
            for line in readme.read_text(encoding='utf-8').splitlines()[:6]:
                if '—' in line or '--' in line:
                    out['en'] = line.split('—')[-1].split('--')[-1].strip()
                    break
    out.setdefault('en', '')
    out.setdefault('zh', out['en'])
    return out


def latest():
    best = {}
    for d in sorted(RELEASES.iterdir()):
        if not d.is_dir():
            continue
        m = NAME.match(d.name)
        if not m:
            # Silence here is how a release goes missing from the site without
            # anyone noticing: the directory is present, the files are right, and
            # the table simply does not mention it. Say so instead.
            if d.name.startswith('fpsup-'):
                print(f'  ! {d.name}: does not match fpsup-<product>-v<version>, '
                      f'so it is not on the site', file=sys.stderr)
            continue
        if not (d / 'AutoRun.txt').exists() or not (d / 'VSHL.BIN').exists():
            print(f'  skipping {d.name}: needs both AutoRun.txt and VSHL.BIN', file=sys.stderr)
            continue
        key = tuple(int(x) for x in m['num'].split('.')), rank(m['qual'])
        p = m['product']
        if p not in best or key > best[p][0]:
            best[p] = (key, d, m)
    return [best[p] for p in sorted(best)]


def to_html(text):
    """ABOUT.txt is written once, in Markdown; the HTML table needs real tags."""
    return re.sub(r'`([^`]+)`', r'<code>\1</code>', _html.escape(text, quote=False))


def rows_html(rels):
    """The site's table. Links land on README.txt, not on the directory.

    Pages serves files but does not generate directory listings, so
    `releases/<dir>/` is a 404 on the site while every file inside it is fine.
    The Markdown table below keeps the directory link on purpose: it is read on
    GitHub, which does list a directory, and that is the more useful landing
    place there.
    """
    out = []
    for _, d, m in rels:
        b = blurb(d)
        out.append(f'    <tr><td><a href="releases/{d.name}/README.txt">fpsup-{m["product"]}</a></td>'
                   f'<td>v{m["num"]}{m["qual"]}</td>\n        <td>{to_html(b["en"])}</td></tr>')
    return '\n'.join(out)


def rows_md(rels, lang):
    out = []
    for _, d, m in rels:
        b = blurb(d)
        out.append(f'| [`fpsup-{m["product"]}`](releases/{d.name}/) '
                   f'| v{m["num"]}{m["qual"]} | {b[lang]} |')
    return '\n'.join(out)


def splice(text, tag, body):
    a = f'<!-- releases:begin{tag} -->'
    b = f'<!-- releases:end{tag} -->'
    if a not in text or b not in text:
        raise SystemExit(f'  markers {a} / {b} not found')
    i = text.index(a) + len(a)
    j = text.index(b)
    return text[:i] + '\n' + body + '\n' + text[j:]


def main():
    check = '--check' in sys.argv
    rels = latest()
    if not rels:
        raise SystemExit('  no releases found')
    work = [(ROOT / 'index.html', [('', rows_html(rels))]),
            (ROOT / 'README.md', [(':en', rows_md(rels, 'en')),
                                  (':zh', rows_md(rels, 'zh'))])]
    stale = []
    for path, parts in work:
        text = original = path.read_text(encoding='utf-8')
        for tag, body in parts:
            text = splice(text, tag, body)
        if text != original:
            stale.append(path)
            if not check:
                path.write_text(text, encoding='utf-8')
    for _, d, m in rels:
        print(f'  fpsup-{m["product"]:<10} v{m["num"]}{m["qual"]:<10} {d.name}')
    if check and stale:
        print('\n  STALE: ' + ', '.join(p.name for p in stale) +
              ' — run tools/build_releases.py and commit', file=sys.stderr)
        return 1
    print('\n  ' + ('up to date' if not stale else
                    'rewrote ' + ', '.join(p.name for p in stale)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
