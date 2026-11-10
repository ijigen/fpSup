#!/usr/bin/env python3
"""Build QSTest, the container's test client: fpSup/QSTest_v<ver>.BIN.

    python3 -B testclient/build_qstest.py --out out

build(funcs=..., sup_id=..., file=...) makes variants for the tests (another
load order, sixteen functions, a bad label).  No device I/O."""
import argparse
import hashlib
import pathlib
import struct
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / 'fpSup' / 'loader-v4')]
import build_v4 as B                       # noqa: E402

VERSION = '0.2.2'
SUP_ID = 'QSTS'
CFG_MAGIC = 0x31545351                     # "QST1"
Q_DEMO, Q_LOCK, Q_FINE, Q_GO = 1, 2, 4, 8             # Q_GO: API 7 (bits 8..11 = the GO target)
Q_DIAL = 16                                           # API 8: QSC_F_DIAL_HINT
FUNCS = [('A', 'QS Test A', 'menu_crop', Q_DEMO | Q_LOCK), ('B', 'QS Test B', 'menu_lock', 0)]
MAX = 16
STATE_BYTES = 6144                         # sizeof(struct st) in qstest.c (checked by its entry)


def file_name():
    return f'QSTest_v{VERSION}.BIN'


def build(funcs=FUNCS, sup_id=SUP_ID, display='QS Test', src=None, api3=False, texts=None):
    with tempfile.TemporaryDirectory(prefix='qstest-') as t:
        text = B.compile_unit(pathlib.Path(t), pathlib.Path(src or HERE / 'qstest.c'), 'sup_entry',
                              ['-I', str(HERE.parent)] + (['-DQST_API3=1'] if api3 else []))
    words = 4 + 4 * MAX + 5 + 3 + 5
    hdr = B.SL4_HEADER_LEN
    body = bytearray(4 * words) + text.code
    entry = hdr + 4 * words + text.functions['sup_entry']

    def place(data):
        body.extend(bytes(-(hdr + len(body)) % 4))
        at = hdr + len(body)
        body.extend(data)
        return at
    names, labels, icons, flags = [0] * MAX, [0] * MAX, [0] * MAX, [0] * MAX
    for i, fn in enumerate(funcs):
        nm, label, icon = fn[:3]
        flags[i] = fn[3] if len(fn) > 3 else 0
        names[i] = place(nm.encode().ljust(12, b'\0')[:12])
        labels[i] = place(label.encode() + b'\0')
        icons[i] = place(icon.encode() + b'\0') if icon else 0
    base = {k: k for k in ('Count', 'Toggle', 'Ratio', 'On', 'Off', 'STEP 1', 'LOCK', 'FREE', 'C0', 'C1', 'C2', 'C3',
                           'C4')}
    base.update(dict(texts or ()))                 # v0.2.4 tests: {'Off': a long reason, ...}
    texts = [place(t.encode() + b'\0') for t in base.values()]
    probe = B.make_sup(bytes(body), entry, sup_id, min_svc=5, flags=B.SL_F_CACHED_OK, name=display)
    state = (len(probe) + 63) & ~63
    body[0:4 * words] = struct.pack(f'<{words}I', CFG_MAGIC, B._id(sup_id), len(funcs), state,
                                    *names, *labels, *icons, *flags, *texts)
    blob = B.make_sup(bytes(body), entry, sup_id, min_svc=5, flags=B.SL_F_CACHED_OK, name=display,
                      block_size=state + STATE_BYTES, version=int(VERSION.replace('.', '')))
    assert len(blob) == len(probe)
    return blob


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = pathlib.Path(a.out) / 'fpSup'
    out.mkdir(parents=True, exist_ok=True)
    blob = build()
    (out / file_name()).write_bytes(blob)
    print(f'{file_name()}  {len(blob)} B  {hashlib.sha256(blob).hexdigest()[:16]}')


if __name__ == '__main__':
    main()
