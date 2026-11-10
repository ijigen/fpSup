"""Read-only version notes for the Merge page; never add download choices."""
import json
import pathlib
import re
from urllib.parse import quote

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent.parent


def readme_changes(path):
    """Fallback for a new release without a translated summary yet."""
    if not path.is_file():
        return []
    text = path.read_text(encoding='utf-8')
    match = re.search(r'^WHAT CHANGED[^\n]*\n(.*?)(?=\n[A-Z][A-Z0-9 /().:_-]{3,}\n|\n[-=]{3,}|\Z)',
                      text, re.M | re.S)
    if not match:
        return []
    # Do not repeat the older versions' cumulative changes under this version.
    body = re.split(r'\n\s*Since v\d', match[1], maxsplit=1)[0].strip()
    parts = re.split(r'\n\s*- ', body.lstrip('- '))
    return [' '.join(p.split()) for p in parts if p.strip()]


def source_link(path):
    """Only files served within fpSup can be linked from the static page."""
    if not path.is_file() or not path.is_relative_to(FPSUP):
        return ''
    return quote(str(path.relative_to(HERE)), safe='/') if path.is_relative_to(HERE) else '../../' + quote(str(path.relative_to(FPSUP)), safe='/')


def attach_history(cat, releases):
    """All retained release folders, plus the exact snapshot offered now.

    Older single-BIN releases belong in the history too. Drafts and unrelated
    products do not. Unselected snapshots are not presented as releases.
    """
    notes = json.loads((HERE / 'version_notes.json').read_text(encoding='utf-8'))

    def version_key(version):
        nums = tuple(int(n) for n in re.findall(r'\d+', version))
        tail = re.sub(r'^[\d.]*', '', version)
        return nums, 2 if not tail else (1 if len(tail) == 1 else 0), tail

    for p in cat['products'] + cat.get('pending', []):
        history = []
        for d in releases.glob(f'fpsup-{p["id"]}-v*'):
            version = re.split(r'-v(?=\d)', d.name, maxsplit=1)[1]
            if not d.is_dir() or not re.fullmatch(r'\d+(?:\.\d+)*[a-z]*', version):
                continue
            readme = d / 'README.txt'
            history.append(dict(release=d.name, version=version, label='v' + version,
                                current=d.name == p.get('release'),
                                changes=notes.get(d.name, dict(en=readme_changes(readme))),
                                source=source_link(readme), source_kind='release'))
        # versions this page offered from an earlier snapshot (build_catalogue_v4: a later snapshot replaces them)
        for old in p.get('superseded', []):
            if not any(h['release'] == old['release'] for h in history):
                manifest = pathlib.Path(old['manifest'])
                history.append(dict(release=old['release'], version=old['version'], label='v' + old['version'],
                                    date=old['date'], current=False, changes=notes.get(old['release'], {}),
                                    source=source_link(manifest if manifest.is_absolute() else HERE / manifest),
                                    source_kind='manifest'))
        history.sort(key=lambda h: version_key(h['version']), reverse=True)
        if p.get('provenance') and not any(h['current'] for h in history):
            manifest = pathlib.Path(p['provenance']['manifest'])
            if not manifest.is_absolute():
                manifest = HERE / manifest
            history.insert(0, dict(release=p['release'], version=p['version'],
                                   label='',
                                   date=p['date'], build_label=p['build_label'], current=True,
                                   changes=notes.get(p['release'], {}),
                                   source=source_link(manifest), source_kind='manifest'))
        p['history'] = history
    return cat
