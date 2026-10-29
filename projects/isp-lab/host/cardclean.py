#!/usr/bin/env python3
"""Delete the clip folders a discard take left on the card (the file layer still creates them, 10-27: 236 shells
filled the SD).  Only folders that appeared during the take, only A001_NNN-style names under \\CINEMA.

    before = cardclean.clips()      # before the take
    ...take...
    cardclean.remove_new(before)    # after it (not recording, >= 10 s after the stop)

Uses the stock shell: `fl del <file>` per file, then `fl delDir <folder>` (memory card-file-delete).
"""
import re, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'fpSup' / 'fp_usb_shell'))
CLIP = re.compile(r'^[A-Z]\d{3}_\d{3}$')
FILE = re.compile(r'^[A-Z]\d{3}_\d{3}_[0-9A-Za-z_.]+$')


def _sh(cmd):
    import putfile
    return putfile.sh(cmd)


def listing(path):
    """[(name, is_dir)] of a card directory, from the stock `dir`."""
    out = []
    for line in _sh(f'dir {path}').splitlines():
        parts = line.split()
        if len(parts) >= 4 and re.match(r'\d{4}/\d\d/\d\d', parts[0]):
            out.append((parts[-1], parts[2] == '<DIR>'))
    return out


def clips():
    return {n for n, d in listing('\\CINEMA') if d and CLIP.match(n)}


def remove_clip(name, sh=None):
    """Delete one clip folder's files and the folder; returns the files deleted. Refuses anything unexpected."""
    sh = sh or _sh
    if not CLIP.match(name):
        raise ValueError(f'not a clip folder name: {name}')
    folder = f'\\CINEMA\\{name}'
    files = [n for n, d in listing(folder) if not d and n not in ('.', '..')]
    for n in files:
        if not (FILE.match(n) or n == 'SPP_metadata.xmp'):
            raise ValueError(f'{folder}: unexpected file {n}, not deleting it')
    for n in files:
        sh(f'fl del {folder}\\{n}')
    sh(f'fl delDir {folder}')
    return files


SETTLE_S = 5      # the recorder can still close a frame file after the take returns (M173: frame 17 written
ROUNDS = 6        # 37 s after the stop, after the first delete): delete, wait, look again until clean twice


def remove_new(before, sleep=None):
    import time
    sleep = sleep or time.sleep
    gone, clean = {}, 0
    for _ in range(ROUNDS):
        new = sorted(clips() - set(before))
        if not new:
            clean += 1
            if clean == 2:
                return gone
        else:
            clean = 0
            for name in new:
                gone[name] = gone.get(name, 0) + len(remove_clip(name))
        sleep(SETTLE_S)
    raise RuntimeError(f'still on the card: {sorted(clips() - set(before))}')


if __name__ == '__main__':
    print(sorted(clips()))
