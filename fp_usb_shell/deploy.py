#!/usr/bin/env python3
"""Write a card's two files over the shell, and do not believe they landed.

    ./deploy.py path/to/card-directory

WHY THIS EXISTS.  `putfile.py` reports what the camera told it, and the camera
is not always right about this.  In one afternoon it reported `written` while
the card still held the previous file, returned `status 3 -- open returned 0`
with an exit code of zero, and failed with `echo handler is [None]` because a
`mem get` of the slot had been dropped.  Acting on the first of those cost a
whole measurement round: the card was believed to carry the new build and did
not, so the numbers were attributed to the wrong bytes.

So a write is not a write until the file reads back identical. This writes,
reads the whole file back, compares it byte for byte, and retries the pair up
to five times before refusing -- and it refuses loudly, because the next thing
anyone does after deploying is reboot, and rebooting onto half a card is how
the camera ends up frozen with no shell to repair it with.

It writes the payload first and the script second, so that the window in which
the two disagree is as short as it can be. That window cannot be closed from
here: the loader checks fpSup.BIN's magic and nothing checks that the two files
came from one build.
"""
import filecmp
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
# Payload first: the AutoRun is what makes a card run at all, so it is the one
# to land last.
FILES = ('fpSup.BIN', 'AutoRun.txt')
TRIES = 5


def run(script, *args):
    return subprocess.run([sys.executable, str(HERE / script), *args],
                          capture_output=True, text=True, timeout=300, cwd=HERE)


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: deploy.py <card directory>')
    card = pathlib.Path(sys.argv[1])
    back = HERE / '.deploy-readback'
    back.mkdir(exist_ok=True)

    for name in FILES:
        src = card / name
        if not src.is_file():
            raise SystemExit(f'  {src} is not there')
        size = src.stat().st_size
        copy = back / name
        for attempt in range(1, TRIES + 1):
            run('putfile.py', str(src), '\\' + name)
            copy.unlink(missing_ok=True)
            run('getfile.py', '\\' + name, str(copy), '--size', str(size))
            if copy.is_file() and filecmp.cmp(src, copy, shallow=False):
                print(f'  {name}  {size} B  (attempt {attempt})')
                break
            print(f'  {name}: attempt {attempt} did not read back identical')
        else:
            raise SystemExit(f'  {name} did not land in {TRIES} attempts '
                             f'-- DO NOT REBOOT')
    print('  both files read back identical; safe to reboot')


main()
