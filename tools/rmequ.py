#!/usr/bin/env python3
"""Delete a `.equ` from an assembly header, comment and all.

    ./tools/rmequ.py gyro/ring_task.inc.S T_STAGE T_BYTES ...

WHY THIS EXISTS.  These headers put the reason for a constant next to it, and
the reason often runs to three or four lines:

    .equ T_LOST,  0xC072E8EC     /* records overwritten before we took them.
                                  * The one number that says the ring is
                                  * too shallow; it must stay zero.       */

A line-oriented delete takes the first line and leaves the rest as a comment
with no opening, which is either an assembler error or -- if the fragment
happens to parse -- silence.  On 2026-09-22 that happened three times in one
afternoon while the gyro state words were being moved out of the cave. Twice
the assembler caught it. Being more careful was clearly not working, so:

    remove the `.equ` line, and if it opened a comment it did not close,
    keep removing lines until one closes it.

Prints what it removed. A name it cannot find is reported rather than ignored,
because a silent no-op here looks exactly like success.
"""
import pathlib
import re
import sys


def rm(path, *names):
    """Remove each named .equ from the file, with its trailing comment."""
    p = pathlib.Path(path)
    lines = p.read_text().split('\n')
    out, i, removed = [], 0, []
    while i < len(lines):
        m = re.match(r'\.equ\s+([A-Za-z_][A-Za-z_0-9]*),', lines[i])
        if m and m.group(1) in names:
            removed.append(m.group(1))
            depth = lines[i].count('/*') - lines[i].count('*/')
            i += 1
            while depth > 0 and i < len(lines):
                depth += lines[i].count('/*') - lines[i].count('*/')
                i += 1
            continue
        out.append(lines[i])
        i += 1
    p.write_text('\n'.join(out))
    return removed


def main():
    if len(sys.argv) < 3:
        raise SystemExit('usage: rmequ.py <file.S> <NAME> [NAME ...]')
    path, names = sys.argv[1], sys.argv[2:]
    removed = rm(path, *names)
    for name in names:
        print(f'  {"removed" if name in removed else "NOT FOUND"}  {name}')
    if set(names) - set(removed):
        raise SystemExit('  some names were not there -- check the spelling '
                         'before assuming they were already gone')


if __name__ == '__main__':
    main()
