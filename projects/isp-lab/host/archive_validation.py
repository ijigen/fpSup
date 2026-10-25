#!/usr/bin/env python3
"""Losslessly archive one validation run and verify every member's SHA-256.

    archive_validation.py pack validation/RUN
    archive_validation.py verify validation/RUN

Raw working files remain available locally. Git stores evidence.tar.zst,
ARCHIVE.json and RESULTS.md. Restore with:
    zstd -dc evidence.tar.zst | tar -xf - -C EMPTY_DIRECTORY
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import tarfile
import tempfile

ARCHIVE = 'evidence.tar.zst'
MANIFEST = 'ARCHIVE.json'


def digest(stream):
    h = hashlib.sha256()
    for block in iter(lambda: stream.read(1 << 20), b''):
        h.update(block)
    return h.hexdigest()


def fingerprint(path):
    with path.open('rb') as f:
        return {'bytes': path.stat().st_size, 'sha256': digest(f)}


def verify(run, manifest=None, archive=None):
    run = pathlib.Path(run)
    manifest = manifest or json.loads((run / MANIFEST).read_text())
    archive = archive or run / ARCHIVE
    if fingerprint(archive) != manifest['archive']:
        raise ValueError('archive fingerprint mismatch')
    expected = manifest['files']
    found = {}
    with subprocess.Popen(['zstd', '-q', '-dc', str(archive)], stdout=subprocess.PIPE) as proc:
        try:
            with tarfile.open(fileobj=proc.stdout, mode='r|') as tar:
                for member in tar:
                    name = pathlib.PurePosixPath(member.name)
                    if not member.isfile() or name.is_absolute() or '..' in name.parts or member.name in found:
                        raise ValueError(f'unsafe or duplicate member: {member.name}')
                    with tar.extractfile(member) as f:
                        found[member.name] = {'bytes': member.size, 'sha256': digest(f)}
        finally:
            proc.stdout.close()
        if proc.wait():
            raise ValueError('zstd could not decode the archive')
    if found != expected:
        raise ValueError('archive contents differ from the source manifest')
    return manifest


def pack(run):
    run = pathlib.Path(run).resolve()
    sources = {}
    for path in sorted(run.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'refusing symlink: {path}')
        if not path.is_file() or path.name in (ARCHIVE, ARCHIVE + '.new', MANIFEST) or '__pycache__' in path.parts:
            continue
        sources[path.relative_to(run).as_posix()] = fingerprint(path)
    if not sources:
        raise ValueError('no evidence files')
    # Build outside RUN so an interrupted pack cannot become a source member.
    with tempfile.TemporaryDirectory(prefix='ispl-archive-') as tmp:
        archive = pathlib.Path(tmp) / ARCHIVE
        with subprocess.Popen(['zstd', '-q', '-10', '--long=27', '-T2', '-o', str(archive)],
                              stdin=subprocess.PIPE) as proc:
            try:
                with tarfile.open(fileobj=proc.stdin, mode='w|', format=tarfile.PAX_FORMAT) as tar:
                    for name in sources:
                        info = tar.gettarinfo(str(run / name), arcname=name)
                        info.uid = info.gid = 0
                        info.uname = info.gname = ''
                        with (run / name).open('rb') as f:
                            tar.addfile(info, f)
            finally:
                proc.stdin.close()
            if proc.wait():
                raise ValueError('zstd compression failed')
        manifest = {'version': 1, 'format': 'tar+zstd', 'archive': fingerprint(archive),
                    'original_bytes': sum(f['bytes'] for f in sources.values()), 'files': sources}
        verify(run, manifest, archive)
        # A changing source is not a valid snapshot, even when tar decoded.
        if any(fingerprint(run / name) != fp for name, fp in sources.items()):
            raise ValueError('source changed during archival')
        # Preserve the old archive until its verified replacement is ready.
        target = run / (ARCHIVE + '.new')
        target.write_bytes(archive.read_bytes())
        target.replace(run / ARCHIVE)
        (run / MANIFEST).write_text(json.dumps(manifest, indent=1) + '\n')
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=('pack', 'verify'))
    ap.add_argument('run', type=pathlib.Path)
    a = ap.parse_args()
    report = pack(a.run) if a.command == 'pack' else verify(a.run)
    print(json.dumps({'run': a.run.name, 'files': len(report['files']),
                      'original_bytes': report['original_bytes'], 'archive': report['archive']}))


if __name__ == '__main__':
    main()
