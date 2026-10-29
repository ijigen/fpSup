#!/usr/bin/env python3
"""Build the SensorLab-IMX410 QS probe (loader v4 sup), one BIN per stage.

    python3 -B build_qsprobe.py --out DIR              # stages 1, 2, 3
    python3 -B build_qsprobe.py --out DIR --stage 2    # one stage
    python3 -B build_qsprobe.py --out DIR --stock-keys # labels: stock KEY ids, no private strings

DIR/fpSup/SLQSProbe<stage>_v<ver>.BIN + DIR/build.json (offsets, sha256).
All stages share one sup_id ('SLQP'), so only one of them loads if more
than one is on the card.  No device I/O.  README.md says what each stage does.

Environment (mutation checks only): QSPROBE_SRC = another qsprobe.c;
QSPROBE_MUTATE = 'nomax' (no list maximum edit), 'nokey' (no KEY placeholder).
"""
import argparse
import csv
import hashlib
import io
import json
import os
import pathlib
import struct
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FPSUP = ROOT / 'fpSup'
sys.path[:0] = [str(FPSUP / 'loader-v4'), str(FPSUP / 'uishare'), str(ROOT / 'research/ui/tools/nbu_probe')]
import build_v4 as B                       # noqa: E402
from ui import fpui, options as O          # noqa: E402
import nbu_format as NF                    # noqa: E402

VERSION = '0.1.0'
SUP_ID = 'SLQP'
SOURCE = HERE / 'qsprobe.c'
CFG_MAGIC = 0x31505351                     # "QSP1"
CFG_WORDS = 24
STATE_RESERVE = 4096                       # sizeof(struct st) is checked by the entry
DMA_BYTES = 0x800 + 0x200                  # qsprobe.c FO_BYTES + buffers
REC_WORDS = 20
INT_BASE, UI_BASE = 54, 49                 # the smallest free ids (QS_ADD_FUNCTION_RESEARCH §1.3)
PLACEHOLDER = 0                            # 撮影モード: what flash gets for our slots
LABELS = ['DC', 'RES', 'FPS', 'QUAL']
ICONS = ['menu_crop', 'menu_cine_resolution', 'menu_cine_fps', 'menu_cine_format']   # stock icons
STOCK_KEYS = ['1107', '1116', '1118', '1114']   # DCクロップ / 解像度 / フレームレート / フォーマット
KEY_HOLD = '#QSPKEY{k}##'                  # qsprobe.c qp_keys: ten characters
# the CINE editor lists (nbr_stock.py list --ext cvm): name, address, size
CSVS = [('Y2_3_CINE', 0xC0F930D4, 1540), ('Y2_3_CINE_W91C1', 0xC0F936D8, 1539),
        ('Y2_3_CINE_angle', 0xC0F93CDC, 1517), ('Y2_3_CINE_angle_W91C1', 0xC0F942CC, 1512)]
PAGES = ['Y2_3C', 'Y2_3C_ShutterAngle']    # the editor pages: their list cursor's maximum
VISIBLE_OBJ = 0x1116                       # 'Visible' controlValue (min 0, max 31, loop)
STOCK_ROWS = 32


class BuildError(RuntimeError):
    pass


def stock_csv(i):
    _n, a, size = CSVS[i]
    return O.at(O.image(), a, size)


def csv_records(data):
    """The CSV's records as the editor sees them (quoted memo cells span lines)."""
    text = data.decode('utf-8-sig')
    rows = list(csv.reader(io.StringIO(text, newline='')))
    return rows[0], rows[1:]


def rows_for(ids, stock_keys, nokey=False):
    """The four new rows: NO, ID, IMAGE, KEY, memo."""
    out = []
    for k, (ui, icon) in enumerate(zip(ids, ICONS)):
        key = STOCK_KEYS[k] if stock_keys or nokey else KEY_HOLD.format(k=k)
        out.append([None, str(ui), icon, key, 'S'])
    return out


def visible_max(set_name, rows=STOCK_ROWS):
    """The address of the list cursor's maximum (a BE float, rows - 1)."""
    img = O.image()
    a, _off, n = O.resource_set(set_name)
    hits = []
    for r in NF.split(img[a - 0xC0000000:a - 0xC0000000 + n]):
        if r.tag != 0x0001000E or len(r.body) != 44:
            continue
        obj = struct.unpack_from('>I', r.body, 12)[0]
        mx = struct.unpack_from('>f', r.body, 28)[0]
        if obj == VISIBLE_OBJ and mx == rows - 1:
            hits.append(a + r.offset + 36)
    if len(hits) != 1:
        raise BuildError(f'{set_name}: {len(hits)} Visible maxima of {rows - 1}')
    return O.be_float_at(img, hits[0], rows - 1)


def fpui_blocks(ids, stock_keys, mutate=''):
    """Two FPUI blocks (eight CSV_ADDs each at most): A = the redirect, CSVs
    0-1, the two pages' list maxima; B = the redirect, CSVs 2-3."""
    img = O.image()
    blocks = []
    for part in (0, 1):
        blk = fpui.Block()
        O.hook_fv(blk)
        for i in (2 * part, 2 * part + 1):
            name, addr, size = CSVS[i]
            head, body = csv_records(stock_csv(i))
            if head != ['NO', 'ID', 'IMAGE', 'KEY', 'memo'] or len(body) != STOCK_ROWS or body[-1][0] != str(STOCK_ROWS):
                raise BuildError(f'{name}: not the stock {STOCK_ROWS}-row list')
            if not stock_csv(i).endswith(b'\r\n'):
                raise BuildError(f'{name}: no CRLF at the end')
            adds = []
            for j, row in enumerate(rows_for(ids, stock_keys, mutate == 'nokey')):
                row[0] = str(STOCK_ROWS + 1 + j)
                tpl = ','.join(row)
                if len(tpl) >= 64 or '{' in tpl:
                    raise BuildError('row template too long / has a token: ' + tpl)
                adds.append(tpl)
            O.csv_file(blk, addr, size, adds, growth=256)
        if part == 0 and mutate != 'nomax':
            for page in PAGES:
                O.page_ops(blk, img, page, [(fpui.OP_ADDF, visible_max(page), len(ids))])
        blocks.append(blk.encode())
    return blocks


def compile_code(src):
    with tempfile.TemporaryDirectory(prefix='qsprobe-') as t:
        return B.compile_unit(pathlib.Path(t), pathlib.Path(src), 'sup_entry')


def build(stage, *, stock_keys=False, ids=(INT_BASE, UI_BASE, 4), sup_id=SUP_ID, name=None,
          no_emit=False, src=None, mutate=None):
    if stage not in (1, 2, 3):
        raise BuildError('stage is 1, 2 or 3')
    src = src or os.environ.get('QSPROBE_SRC') or SOURCE
    mutate = os.environ.get('QSPROBE_MUTATE', '') if mutate is None else mutate
    ibase, ubase, n = ids
    if not 1 <= n <= 4:
        raise BuildError('1..4 ids')
    text = compile_code(src)
    hdr = B.SL4_HEADER_LEN
    body = bytearray(4 * CFG_WORDS) + text.code
    body += bytes(-len(body) % 4)
    entry = hdr + 4 * CFG_WORDS + text.functions['sup_entry']

    def place(data, align=4):
        body.extend(bytes(-(hdr + len(body)) % align))
        at = hdr + len(body)
        body.extend(data)
        return at
    labels = [0] * 4
    if not stock_keys:
        labels = [place(s.encode() + b'\0') if k < n else 0 for k, s in enumerate(LABELS)]
    blocks = fpui_blocks([ubase + k for k in range(n)], stock_keys, mutate)
    offs = [place(b, 8) for b in blocks]
    rec_off = place(bytes(4 * REC_WORDS)) if stage == 3 else 0
    display = name or f'SensorLab QS probe {stage}'
    probe = B.make_sup(bytes(body), entry, sup_id, min_svc=B.SL4_SVC_VERSION, flags=B.SL_F_CACHED_OK,
                       name=display)
    file_len = len(probe)
    state_off = (file_len + 63) & ~63
    dma_off = (state_off + STATE_RESERVE + 63) & ~63
    block = dma_off + DMA_BYTES
    cfg = struct.pack(f'<{CFG_WORDS}I', CFG_MAGIC, stage, n, ibase, ubase, PLACEHOLDER,
                      offs[0], offs[1], len(blocks[0]), len(blocks[1]),
                      *O.handler()[1:],
                      *[a for _n, a, _s in CSVS], *labels,
                      rec_off, state_off, dma_off, 1 if no_emit else 0)
    body[0:4 * CFG_WORDS] = cfg
    blob = B.make_sup(bytes(body), entry, sup_id, min_svc=B.SL4_SVC_VERSION, flags=B.SL_F_CACHED_OK,
                      name=display, block_size=block, dma=(dma_off, DMA_BYTES),
                      version=int(VERSION.replace('.', '')))
    if len(blob) != file_len:
        raise BuildError('layout moved')
    info = dict(stage=stage, bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest(),
                entry=entry, code=len(text.code), state_off=state_off, dma_off=dma_off,
                block_size=block, rec_off=rec_off, labels=labels, fpui=offs,
                ids=dict(internal=list(range(ibase, ibase + n)), ui=list(range(ubase, ubase + n))),
                placeholder=PLACEHOLDER, stock_keys=stock_keys,
                visible_max=[hex(visible_max(p)) for p in PAGES])
    return blob, info


def file_name(stage):
    return f'SLQSProbe{stage}_v{VERSION}.BIN'


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', required=True)
    ap.add_argument('--stage', type=int, action='append')
    ap.add_argument('--stock-keys', action='store_true', help='stock KEY ids instead of DC/RES/FPS/QUAL')
    ap.add_argument('--no-emit', action='store_true', help='stage 3: do not re-post MV_QSMENU_QSn after boot')
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    (out / 'fpSup').mkdir(parents=True, exist_ok=True)
    infos = {}
    for st in a.stage or (1, 2, 3):
        blob, info = build(st, stock_keys=a.stock_keys, no_emit=a.no_emit)
        (out / 'fpSup' / file_name(st)).write_bytes(blob)
        infos[file_name(st)] = info
        print(f'{file_name(st)}  {len(blob)} B  {info["sha256"][:16]}')
    (out / 'build.json').write_text(json.dumps(infos, indent=1) + '\n')


if __name__ == '__main__':
    main()
