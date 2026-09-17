#!/usr/bin/env python3
"""Re-render index.html and artifact.html from template.html, reusing the
catalogue that is already embedded in them.

    ./render.py            rewrite both pages
    ./render.py --check    fail if either is stale

**This is for presentation changes only.** `build_catalogue.py` is still the
only thing that may produce the catalogue: it reads the shipping artefacts,
rebuilds the AutoRun templates, and refuses to write a page whose output does
not reproduce those artefacts byte for byte. Nothing here re-derives any of
that -- it lifts the existing catalogue out verbatim and puts it back.

The reason this exists is that `build_catalogue.py` needs an ARM assembler to
rebuild the AutoRun templates, so on a machine without one it cannot run at
all, and a wording or layout fix in template.html could not be shipped. That
is a bad trade: the layout is the part that changes most often and the part
whose correctness does not depend on the toolchain.

The substitution is the same two steps build_catalogue.py ends with, and this
file asserts it reproduces the current pages before it will write anything --
so a drift between the two implementations is caught here rather than in
somebody's browser.
"""
import json, pathlib, subprocess, shutil, sys, re

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE = HERE / 'template.html'
INDEX = HERE / 'index.html'
ARTIFACT = HERE / 'artifact.html'

HEAD = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n')


def render(template, catalogue):
    """Exactly what build_catalogue.py's main() does with the finished page."""
    page = template.replace('@@CATALOGUE@@', catalogue)
    css, rest = page.split('</style>', 1)
    index = HEAD + css + '</style>\n</head>\n<body>\n' + rest + '\n</body>\n</html>\n'
    return index, page


def catalogue_from(page):
    """Lift the catalogue out of a rendered page by its own script tag.

    An earlier version located it by matching the template's text either side of
    @@CATALOGUE@@. That works only while the template and the page were built
    from the same commit -- edit the template and the ends stop matching, which
    is exactly when you want to re-render. Reading the tag does not care.

    The result must parse as JSON and carry the keys the page indexes, so a bad
    extraction fails here rather than producing a page whose catalogue is a
    truncated string.
    """
    m = re.search(r'<script id="cat"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        return None
    raw = m.group(1)
    try:
        cat = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(cat, dict) or 'cards' not in cat or not cat['cards']:
        return None
    return raw


def check_js(page):
    """Refuse to write a page whose script does not parse. Two outages came from
    exactly that; build_catalogue.py has the same guard and the same reason."""
    blocks = [js for attrs, js in
              re.findall(r'<script([^>]*)>(.*?)</script>', page, re.S)
              if 'json' not in attrs.lower()]
    if not blocks:
        raise SystemExit('  no script found in the template')
    if not shutil.which('node'):
        print('  note: node not found -- the page was NOT syntax-checked')
        return
    for i, js in enumerate(blocks):
        r = subprocess.run(['node', '--check', '-'], input=js,
                           capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stderr)
            raise SystemExit(f'  script block {i} does not parse; page not written')
    print(f'  js       {len(blocks)} script blocks parse')


def main():
    check = '--check' in sys.argv
    template = TEMPLATE.read_text()
    artifact = ARTIFACT.read_text()

    cat = catalogue_from(artifact) or catalogue_from(INDEX.read_text())
    if cat is None:
        raise SystemExit(
            '  no usable catalogue in artifact.html or index.html.\n'
            '  Run build_catalogue.py -- that is the only thing that can build one.')
    n = len(json.loads(cat)['cards'])
    print(f'  catalogue  {len(cat):,} bytes, {n} cards')

    index, page = render(template, cat)
    check_js(page)

    stale = [p.name for p, got in ((INDEX, index), (ARTIFACT, page))
             if p.read_text() != got]
    if not check:
        INDEX.write_text(index)
        ARTIFACT.write_text(page)
    for p in (INDEX, ARTIFACT):
        print(f'  {p.name:14} {p.stat().st_size:,} bytes'
              f'{"   STALE" if p.name in stale and check else ""}')
    if check and stale:
        print('\n  STALE: ' + ', '.join(stale) + ' -- run render.py and commit',
              file=sys.stderr)
        return 1
    print('\n  ' + ('up to date' if not stale else 'rewrote both pages'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
