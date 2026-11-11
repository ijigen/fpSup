#!/usr/bin/env python3
"""建 COL-Share(Loader v4 sup,sup_id COLS):原生 COLOR 清單多出來的列,LUT / RAW-View 共用。

    python3 -B fpSup/colshare/build_colshare.py                 # -> fpSup/COL-Share_v0.0.1test.BIN
    python3 -B fpSup/colshare/build_colshare.py --out /新的/目錄/COL-Share_v0.0.1test.BIN --info /新檔.json
    python3 -B fpSup/colshare/build_colshare.py --rows 8      # 列數測試版 -> fpSup/colshare/rows-test/out/rows8/
                                                               # (內建 TEST 1..8 假客戶;rows-test/README.md)

一個 sup 一個檔(Bei):FPUI 區塊、組 CSV 的資料、一張佔位圖示、標籤佔位字串都在 BIN 裡;狀態在 BSS。
產品 12 列(Bei 2026-11-10);CSV 與圖示複本在機上、同步時才配(只給存在的列,大小剛好:colshare.c)。
不碰相機。設計:DESIGN.md;測試:test_colshare.py。
"""
import argparse
import hashlib
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FPSUP = HERE.parent
ROOT = FPSUP.parent
sys.path[:0] = [str(HERE), str(FPSUP / 'loader-v4')]
import build_v4 as B          # noqa: E402
import names_v4 as NV         # noqa: E402
import colshare_ui as CU      # noqa: E402

SOURCE = Path(os.environ.get('COLSHARE_SOURCE') or HERE / 'colshare.c')   # env: the mutation check's copy
SUP_ID = 'COLS'
CFG_MAGIC = 0x31474643        # "CFG1": colshare.c struct cfg
CONFIG = 12
STATE = 3072                  # colshare.c: sizeof(struct cols) <= this (12 rows: 2 640 B)
RESIDENT_MAX = 64 * 1024      # DESIGN.md §7


def version_word(text):
    major, minor, patch = (int(''.join(ch for ch in x if ch.isdigit()) or 0) for x in text.split('.')[:3])
    return major << 16 | minor << 8 | patch


RESIDENT_MAX_TEST = 128 * 1024   # rows-test only (one TEST tile a row in the BIN)
STATE_TEST = 6144            # rows-test: struct cols grows ~150 B a row + the dummy client (colshare.c asserts)
TEST_DIR = HERE / 'rows-test' / 'out'


def adv_word(rows):
    """The AEL page's MenuMode Normal range at C1D6ED48: BE float 15 + rows, as the little-endian word."""
    return struct.unpack('<I', struct.pack('>f', 15.0 + rows))[0]


def layout(rows):
    """struct cols offsets the tests read (colshare.c's O_* and its _Static_asserts: the same arithmetic)."""
    eff = 28
    guitab = eff + 4 * (rows + 1) + 8
    rec = guitab + 8 * (16 + rows)
    shown = rec + 4 * (rows + 1)
    effmin = shown + 12
    effmax = effmin + 4 * (rows + 1)
    stock = effmax + 4 * (rows + 1)
    api = stock + 4 * 36
    clients = api + 40 + 16
    ncl = clients + 4 * (8 + 8 * rows)
    page = ncl + 4 + 8 * (rows + 1)
    pend_pick = page + 20
    snap = pend_pick + 56
    file = snap + 3 * 4 * (rows + 1) + 4
    return dict(eff=eff, guitab=guitab, rec=rec, shown=shown, shown_rec=shown + 4, down=shown + 8, effmin=effmin,
                effmax=effmax, root_stock=stock, api=api, clients=clients, ncl=ncl, page=page, table=page + 4,
                pend_pick=pend_pick, poffs=pend_pick + 36, syncs=pend_pick + 40, deferred=pend_pick + 44,
                snap=snap, file=file, n_csv=file + 20 * (3 + rows), heap=file + 20 * (3 + rows) + 4,
                allocs=file + 20 * (3 + rows) + 8, frees=file + 20 * (3 + rows) + 12,
                alloc_failed=file + 20 * (3 + rows) + 16, sync_late=file + 20 * (3 + rows) + 20,
                on_cursor=file + 20 * (3 + rows) + 24, previews=file + 20 * (3 + rows) + 28)


def build(source=SOURCE, rows=None):
    """(BIN bytes, facts).  rows = None: the product (12 rows).  rows = N: the rows-test
    variant -- CS_MAX N, a built-in client with N rows "TEST 1".. (a placeholder tile each)."""
    test = rows is not None
    CU.configure(rows if test else CU.ROWS_PRODUCT, test=test)
    try:
        return _build(source, rows)
    finally:
        CU.configure(CU.ROWS_PRODUCT)


def _build(source, rows):
    test = rows is not None
    defs = []
    if test:
        defs = [f'-DCS_MAX={rows}', f'-DCS_TILES={rows}', f'-DCS_TEST_ROWS={rows}', f'-DCS_STATE={STATE_TEST}']
    defs.append(f'-DADV_NEW=0x{adv_word(rows if test else CU.ROWS_PRODUCT):08X}u')
    state = STATE_TEST if test else STATE
    with tempfile.TemporaryDirectory(prefix='colshare-') as td:
        text = B.compile_unit(Path(td), Path(source), 'sup_entry', ['-I', str(HERE), '-mno-movt', *defs])
    code_off = B.SL4_HEADER_LEN + CONFIG
    body = bytearray(CONFIG) + text.code
    body.extend(bytes(-(B.SL4_HEADER_LEN + len(body)) % 8))
    section_off = B.SL4_HEADER_LEN + len(body)
    body.extend(CU.section(section_off))
    name = NV.display(SUP_ID) if not test else f'COL-Share T{rows}'   # SupManager shows which test
    ver = version_word(NV.version(SUP_ID))

    def make(state_off, block):
        struct.pack_into('<3I', body, 0, CFG_MAGIC, state_off, section_off)
        return B.make_sup(bytes(body), code_off + text.functions['sup_entry'], SUP_ID, name=name,
                          flags=B.SL_F_CACHED_OK, min_svc=6, version=ver, block_size=block)
    probe = make(0, None)
    state_off = (len(probe) + 63) & ~63
    block = state_off + state
    blob = make(state_off, block)
    assert len(blob) == len(probe)
    limit = RESIDENT_MAX_TEST if test else RESIDENT_MAX
    if block > limit:
        raise B.BuildError(f'COL-Share resident {block} B > {limit} B (DESIGN.md §7)')
    facts = dict(file=NV.file_name(SUP_ID), sup_id=SUP_ID, version=NV.version(SUP_ID), version_word=ver,
                 file_bytes=len(blob), block_bytes=block, code_bytes=len(text.code), state_offset=state_off,
                 section_offset=section_off, max_rows=CU.MAX_ROWS, sha256=hashlib.sha256(blob).hexdigest(),
                 test_rows=rows or 0, fv_capacity=CU.fv_capacity(), layout=layout(CU.MAX_ROWS),
                 donors=[d[0] for d in CU.DONORS], adv_word=adv_word(CU.MAX_ROWS), over_64k=block > RESIDENT_MAX,
                 entries={k: code_off + v for k, v in text.functions.items() if k.startswith(('sup_', 'cs_', 'api_'))})
    return blob, facts


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', type=Path, default=FPSUP / NV.file_name(SUP_ID))
    ap.add_argument('--info', type=Path, help='建置紀錄(JSON):新檔')
    ap.add_argument('--rows', type=int, help=f'列數測試版:N 列 TEST 1..N(1..{CU.ROWS_LIMIT});預設 = 產品')
    a = ap.parse_args()
    if a.rows is not None and a.out == ap.get_default('out'):
        a.out = TEST_DIR / f'rows{a.rows}' / NV.file_name(SUP_ID)        # never over the product BIN
    blob, facts = build(rows=a.rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_bytes(blob)
    if a.info:
        with a.info.open('x') as f:
            f.write(json.dumps(facts, ensure_ascii=False, indent=1) + '\n')
    print(f"{a.out}  {facts['file_bytes']} B  resident {facts['block_bytes']} B  sha256 {facts['sha256'][:16]}")


if __name__ == '__main__':
    main()
