#!/usr/bin/env python3
"""Build Dial Fix as a loader v4 sup.

    python3 -B fpSup/dialfix/build_dialfix.py --out DIR     # DIR/fpSup/DialFix_v<version>.BIN
"""
import argparse, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'loader-v4'))
import build_v4 as B
import names_v4 as N

SUP_ID = 'DIAL'
NAME, FILE = N.display(SUP_ID), N.file_name(SUP_ID)


def dialfix_sup():
    return B.c_sup(HERE / 'dialfix.c', SUP_ID, name=NAME)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('--out', type=pathlib.Path, required=True)
    a = ap.parse_args()
    d = a.out / 'fpSup'
    d.mkdir(parents=True, exist_ok=True)
    blob = dialfix_sup()
    (d / FILE).write_bytes(blob)
    import hashlib
    print(f'{d / FILE}  {len(blob)} B  {hashlib.sha256(blob).hexdigest()[:8]}')


if __name__ == '__main__':
    main()
