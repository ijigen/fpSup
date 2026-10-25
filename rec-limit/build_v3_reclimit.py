#!/usr/bin/env python3
"""Build the recording-time-limit sup (46RECLM.BIN).

    python3 rec-limit/build_v3_reclimit.py --out DIR

writes DIR/46RECLM.BIN and DIR/build.json.

SIGMA fp Ver.5.02 stops a movie after two hours.  That cap lives in two 32-bit
data words of the reference image, not in code:

    0xC0B9BEDC  the third word of {0, 0, 7200} at 0xC0B9BED4.  0xC0389DE0 copies
                the triple, fills the first two words from the capacity side and
                keeps the minimum {min, id}; the result becomes the recording
                duration at rec parameter +0x3C, so nothing downstream can exceed
                it whatever the free space says.
    0xC0BA0354  table 0xC0BA0348 + 0xC.  0xC03A4AB4 computes floor(value * fps) + 1
                as the frame budget of one recording and compares it with the
                capacity-derived candidate.

This sup is two firmware patch rows through Loader v3 (build_v3.patch_sup): both
words are claimed with SL_EXCL, the stock words are journalled and written back at
power-off, and the new value is copied after the claims.  No code is modified, no
hook, no task, nothing is written to flash, and removing the card gives the stock
camera back after the next power-on.

The value is 28800 s (8 h): large enough to never bind in practice and small enough
to stay exact under 16- and 32-bit arithmetic on both consumers.

Verified on the camera (Ver.5.02): builds that set 60 s and 900 s stop at exactly
60 s and 900 s, so these two words are the cap; an 8 h build recorded 2:01:09, then
a 4:02:54 MOV and a 6:06:25 CinemaDNG sequence, each ending because the medium was
full (109.4 GB and 1.712 TB respectively) rather than the clock.
"""
import argparse
import hashlib
import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent
sys.path.insert(0, str(FPSUP / 'fp_usb_shell' / 'v3'))

import build_v3 as B                                        # noqa: E402

NAME = '46RECLM.BIN'
SUP_ID = 'RCLM'
STOCK, NEW = 7200, 28800            # 7200 s = the stock 2 h cap; 28800 s = 8 h
WORDS = (0xC0B9BEDC, 0xC0BA0354)
CLAIM_KIND = 2                      # SL_EXCL: no other sup may hold these words


def rows():
    """(address, new bytes, kind) for build_v3.patch_sup; stock comes from the image."""
    return [(a, struct.pack('<I', NEW), CLAIM_KIND) for a in WORDS]


def build():
    data = B.patch_sup(SUP_ID, rows())
    info = {
        'product': 'fpRecLimit, Loader v3 sup',
        'file': NAME,
        'sup_id': SUP_ID,
        'version': 1,
        'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'rows': [{'address': f'0x{a:08X}', 'stock': STOCK, 'new': NEW} for a in WORDS],
        'code_modified': False,
        'flash_written': False,
        'tasks': 0,
        'hooks': 0,
    }
    return data, info


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='build 46RECLM.BIN')
    ap.add_argument('--out', type=pathlib.Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    data, info = build()
    (a.out / NAME).write_bytes(data)
    (a.out / 'build.json').write_text(json.dumps(info, indent=2) + '\n')
    print(json.dumps({k: info[k] for k in ('file', 'bytes', 'sha256')}, indent=2))
