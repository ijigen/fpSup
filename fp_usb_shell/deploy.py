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
import hashlib
import json
import pathlib
import signal
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
# Payload first: the AutoRun is what makes a card run at all, so it is the one
# to land last.
FILES = ('fpSup.BIN', 'AutoRun.txt')
TRIES = 5
# What the card is believed to hold, written after the pair lands and cleared
# before the first byte of a new one moves.  Its absence is the alarm.
STATE = HERE / '.deploy-readback' / 'oncard.json'


def run(script, *args):
    return subprocess.run([sys.executable, str(HERE / script), *args],
                          capture_output=True, text=True, timeout=300, cwd=HERE)


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def note(card, files):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(
        {'card': str(card), 'files': files}, indent=1, sort_keys=True))


def check_pair():
    """Say so if the last deploy left the two files from different builds.

    deploy.py writes fpSup.BIN first and AutoRun.txt second, so an interrupted
    run leaves a card whose payload is one build and whose script is another.
    Nothing downstream notices: the loader checks fpSup.BIN's magic, the magic
    is right, and the camera boots a payload the AutoRun was not written for.
    On 2026-09-23 that quietly removed OG2K from the menu -- the AutoRun was
    the merged card's and the payload was the shell's, so no open-gate section
    was ever placed, and the only symptom was a missing menu entry an hour
    later.

    So: the pair is recorded once it has landed, and the record is torn up
    before the next write begins.  A missing record means a deploy did not
    finish, and the fix is to run this again with the card it should hold.
    """
    if STATE.exists():
        return
    print('  NOTE: the last deploy did not finish, or predates this check.\n'
          '        The camera may hold fpSup.BIN from one build and\n'
          '        AutoRun.txt from another, which boots without complaint.')


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: deploy.py <card directory>')
    card = pathlib.Path(sys.argv[1])
    back = HERE / '.deploy-readback'
    back.mkdir(exist_ok=True)
    check_pair()
    # From here until both files have landed, what the camera holds is not a
    # pair.  Say so by having no record rather than a stale one.
    STATE.unlink(missing_ok=True)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: sys.exit(
            '\n  INTERRUPTED MID-DEPLOY -- the card now holds files from two '
            'builds.\n  Run deploy.py again with the card it should hold '
            'BEFORE rebooting.'))

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
    note(card, {name: sha(card / name) for name in FILES})
    print('  both files read back identical; safe to reboot')


main()
