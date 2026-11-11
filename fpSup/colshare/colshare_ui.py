"""COL-Share 的主機端資料:原生 COLOR 清單多出來的列(由 lut/clist_ui.py 搬來,2026-11-07)。

相機端(colshare.c)擁有清單的點,如同 raw-view 的第 17 列
(projects/lut-sup/notes/NATIVE_COLOR_LIST_RESEARCH.md);這裡做它起始的資料:

- an FPUI block: the shared file redirect (fv_handler at C05E5BEC) and a copy of
  the ColorButtonMenu resource set with its row limits and label keys for MAX_ROWS
  (the camera rewrites the limits to the rows present);
- no file copies (Bei 2026-11-10, "沒用掉的東西不要佔用記憶體"): colshare.c makes the three
  CSVs (the stock file + one line a row) and each row's icon at sync, sized to them,
  only for rows that exist.  Here: where the stock CSVs' two edited cells are, the
  donors' names, the _EXCL lines' tails;
- one placeholder tile (86 x 74, rv_icon.render) for a client without an icon (rows-test: one a row).

列的名字在大標籤(Text 121)與圖示上;內容都來自客戶(colshare.h)。
"""
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE.parent / 'uishare'), str(ROOT / 'projects/open-gate/build'),
                str(ROOT / 'projects/rawview/tools')]
from ui import fpui, options as O        # noqa: E402

ROWS_PRODUCT = 12                         # Bei 2026-11-10 (rows-test passed on the camera at 19)
MAX_ROWS = ROWS_PRODUCT                   # configure() for rows-test
STOCK_ROWS = 16
# 86 x 74 icons no stock page and no stock CSV names (offline scan 2026-10-27);
# set_flash_1 is raw-view's.  To confirm on the camera with `gui image log`.
DONORS = [('set_flash_2.xci', 0xC14EBCC4, 750), ('menu_flash.xci', 0xC145D120, 535),
          ('set_frameGuide_broken.xci', 0xC14F3420, 713), ('menu_isoAuto_S-Limit.xci', 0xC1467924, 1009)]
# rows-test (2026-11-10 scan, rows-test/README.md): every other 86 x 74 .xci whose name occurs in the image
# only in the NBR directory (no page, no .cvm, no code string, no format string builds it) -- 18 with the
# four above; set_flash_1 last (old raw-view's RAW icon: COL-Share leaves when old raw-view is on the card).
# Not yet watched with `gui image log`: the crop-zoom / ISO-limit ones may show in their own menus.
MORE_DONORS = [('menu_cropZoom_highestLimit.xci', 0xC1456C98, 1060), ('menu_cropZoom_lowestLimit.xci', 0xC1457668, 1221),
               ('menu_isoAuto_highestLimit.xci', 0xC14690DC, 1830), ('menu_isoAuto_lowestLimit.xci', 0xC146A6AC, 1754),
               ('set_cropZoom_1_00.xci', 0xC14E5ABC, 1109), ('set_cropZoom_1_24.xci', 0xC14E5F14, 1073),
               ('set_cropZoom_1_30.xci', 0xC14E6348, 1100), ('set_cropZoom_1_53.xci', 0xC14E6794, 1066),
               ('set_cropZoom_1_67.xci', 0xC14E6BC0, 1123), ('set_cropZoom_1_83.xci', 0xC14E7024, 1121),
               ('set_cropZoom_1_91.xci', 0xC14E7488, 1090), ('set_cropZoom_2_0.xci', 0xC14E78CC, 919),
               ('set_cropZoom_2_5.xci', 0xC14E7C64, 976), ('set_cropZoom_5_0.xci', 0xC14E8034, 937),
               ('set_flash_1.xci', 0xC14EBAAC, 533)]
ALL_DONORS = DONORS + MORE_DONORS
ROWS_LIMIT = len(ALL_DONORS)              # 19: the most a build can have (one distinct 86 x 74 donor a row)
FILES_PER_BLOCK = 8                       # fpui_stock.c MAX_FILES: OP_FILE copies in one FPUI block
TEST = False                              # rows-test: placeholder tiles "TEST j" (one a row)
FV_CAPACITY = 64                          # the shared redirect table (the first sup that hooks makes it): 3 + 12 ours,
                                          # Res-Custom's 9, room for others (rows-test ran 64 on the camera, 11-10)
ICON_CAP = 13312                          # a camera-made tile (import_ui.ICON_BYTES) fits
CSV = [('ListColorButtonMenu', 0xC0D566EC, 453), ('ListColorButtonMenu_EXCL', 0xC0D568B4, 483),
       ('ListColorButtonMenu_EXCL2', 0xC0D56A98, 452)]
TEXT_END_STEP = 33                        # options.COLOR_TEXT_END: +33 per row


def stock_csv(i):
    _name, addr, size = CSV[i]
    return O.at(O.image(), addr, size)


def rows_csv(i, n):
    """CSV i with n added rows after the stock sixteen (colshare.c sync
    writes the same bytes).  Main list: a ring -- the first row's Left and OFF's
    Right go to the added rows; _EXCL / _EXCL2: raw-view's disabled rows."""
    text = stock_csv(i).decode('utf-8-sig')
    lines = text.split('\r\n')
    assert lines[-1] == '' and len(lines) == STOCK_ROWS + 2, CSV[i][0]
    body = [l.split(',') for l in lines[1:-1]]
    if i == 0 and n:
        body[0][3] = str(STOCK_ROWS + n - 1)
        body[-1][4] = str(STOCK_ROWS)
    for j in range(n):
        k = STOCK_ROWS + j                                  # 0-based index of the row
        donor = DONORS[j][0][:-4]
        if i == 0:
            body.append([str(k + 1), donor, '0', str(k - 1), str(k + 1 if j + 1 < n else 0), str(k)])
        elif i == 1:
            body.append([str(k + 1), 'set_common_1', '1', '15', '15', '15'])
        else:
            body.append([str(k + 1), 'set_common_1', '1', '14', '0', '15'])
    return b'\xef\xbb\xbf' + ('\r\n'.join([lines[0]] + [','.join(r) for r in body]) + '\r\n').encode()


def label(name):
    """A cube's tile text: its file name without .cube, at most 8 characters."""
    stem = name[:-5] if name.lower().endswith('.cube') else name
    return stem[:8] or '?'


def icon(name):
    import numpy as np
    import rv_icon
    import xci
    w, h = 86, 74
    for cap in range(23, 9, -1):                          # the stock tile's 23 px, smaller when long
        t = rv_icon.render(label(name), w, h, cap=cap)
        cols = np.where(t.max(axis=0) > 10)[0]
        if len(cols) and cols[0] >= 3 and cols[-1] <= w - 4:
            blob = xci.encode(t, t)
            fpui.check(len(blob) <= ICON_CAP, f'icon for {name!r}: {len(blob)} B')
            return blob
    raise ValueError(f'no fitting label for {name!r}')


# The big name under the strip (2026-11-07, Bei: every LUT row said "Off").  It is
# ColorButtonMenu's Text 121, whose text clip 2 has one key per GUI value: time
# 33.3 x GUI (List 14's controlAnimation, apply-frame CM_COLAJ_ColorMode), 0 '0378'
# .. 500 '1350' (= Off).  COLOR_TEXT_END (+33 a row) only lengthens the interval:
# with no key past 500 every added row held "Off".  The copy gets one key per row,
# at 500 + 33 (j + 1) - 1 (<= every GUI's time 33.3 x (16 + j), however the
# interval is clamped), its text one of the block's own strings, which clist_sync
# rewrites to the row's cube name (Text 121 resolves through the stock string
# table and keeps the literal when that has no such id: FUN_c05ec490's fallback).
LABEL_CLIP = 0xC1D66BC8                   # the clip record (owner 121, clip 2, 'text', 16 keys)
LABEL_KEYS = [500 + TEXT_END_STEP * (j + 1) - 1 for j in range(MAX_ROWS)]
LABEL_CAP = 31                            # bytes of a row's name (and its placeholder)
KEY_BYTES = 10                            # {u8 in, u8 out, u32 time, u32 value}


def label_placeholder(j):
    return (f'COLLABEL{j + 1}' + '_' * LABEL_CAP)[:LABEL_CAP]


def row_label(name):
    """The big label's text: the file name without .cube, printable ASCII
    (others '?'), at most LABEL_CAP bytes (colshare.c label after LUT's .cube strip)."""
    b = name.encode('utf-8', 'replace')
    if len(b) >= 5 and b[-5:].lower() == b'.cube':
        b = b[:-5]
    out = bytes(c if 0x20 <= c <= 0x7E else 0x3F for c in b[:LABEL_CAP])
    return (out or b'?').decode()


def label_clip():
    """(stock clip bytes, its end = the insert position (both set-relative), the
    header's budget word for the clip's key count (set-relative))."""
    img = O.image()
    a, _off, n = O.resource_set('ColorButtonMenu')
    rec = O.at(img, LABEL_CLIP, 8)
    tag, size = struct.unpack('>II', rec)
    clip = O.at(img, LABEL_CLIP, size)
    fpui.check(tag == 0x1000A and size == 48 + KEY_BYTES * 16, 'label clip form')
    fpui.check(struct.unpack_from('>8I', clip, 12) == (1, 0xFFFFFFFF, 121, 2, 16, 2, 1,
                                                     struct.unpack_from('>I', clip, 40)[0]), 'label clip head')
    keys = [struct.unpack_from('>I', clip, 48 + KEY_BYTES * i + 2)[0] for i in range(16)]
    fpui.check(keys[-1] == 500 and keys == sorted(keys), 'label clip keys')
    head_size = struct.unpack('>I', O.at(img, a + 4, 4))[0]
    budget = a + head_size - 12                       # property_key_counts' last: this clip (the page's last)
    fpui.check(struct.unpack('>I', O.at(img, budget, 4))[0] == 16 and
               struct.unpack('>2I', O.at(img, budget + 4, 8)) == (1, 11), 'label clip budget')
    fpui.check(LABEL_CLIP > max(O.be_float_at(img, w, 15) for w in O.COLOR_ROW_MAX + [O.RAWVIEW_EFFECT_END])
               and LABEL_CLIP + size <= O.COLOR_TEXT_END, 'the insert sits between the limits and the text end')
    return clip, LABEL_CLIP + size - a, budget - a


LABEL_INSERT = KEY_BYTES * MAX_ROWS


def configure(rows=ROWS_PRODUCT, test=False):
    """The row count every function below builds for (the product: 12, not a test).  rows-test only:
    build_colshare.py --rows N."""
    global MAX_ROWS, DONORS, LABEL_KEYS, LABEL_INSERT, WORDS, TEST
    fpui.check(1 <= rows <= ROWS_LIMIT, f'rows {rows}: 1..{ROWS_LIMIT} (one unused 86 x 74 donor each)')
    MAX_ROWS, TEST = rows, test
    DONORS = ALL_DONORS[:rows]
    LABEL_KEYS = [500 + TEXT_END_STEP * (j + 1) - 1 for j in range(MAX_ROWS)]
    LABEL_INSERT = KEY_BYTES * MAX_ROWS
    WORDS = _words()


def extra_blocks():
    """No more FPUI blocks: the block has no file copies (colshare.c makes them at sync)."""
    return 0


def fv_capacity():
    return FV_CAPACITY


def hook_fv(blk):
    """options.hook_fv with COL-Share's table capacity (the first sup that hooks makes the table)."""
    code, entry, table_word = O.handler()
    blk.op(fpui.OP_HOOK_FV, O.FV_SITE, O.FV_STOCK, fv_capacity(), blk.fragment(code), len(code),
           entry, O.CAVE_BUMP, O.CAVE_ARENA_END, O.THUMB_VENEER, table_word)


def placeholder_name(j):
    return f'TEST {j + 1}' if TEST else 'COL'


def tiles():
    """The placeholder tiles: the product one ('COL'), rows-test one a row ('TEST j')."""
    return [icon(placeholder_name(j)) for j in range(n_tiles())]


def csv_fields():
    """The main list's two cells the rows change, in the stock file: {offset, length} of the first row's Left
    and of the last (OFF) row's Right (rows_csv: 15 + n and 16)."""
    raw = stock_csv(0)
    fpui.check(raw[:3] == b'\xef\xbb\xbf' and all(c < 0x80 for c in raw[3:]), 'CSV: BOM + ASCII')
    lines = raw[3:].split(b'\r\n')
    fpui.check(len(lines) == STOCK_ROWS + 2 and lines[-1] == b'', 'CSV rows')
    starts, at = [], 3
    for line in lines:
        starts.append(at); at += len(line) + 2

    def cell(row, col):
        cells = lines[row].split(b',')
        off = starts[row] + sum(len(x) + 1 for x in cells[:col])
        return off, len(cells[col])
    return (*cell(1, 3), *cell(STOCK_ROWS, 4))


CSV_TAILS = (None, ',set_common_1,1,15,15,15\r\n', ',set_common_1,1,14,0,15\r\n')   # rows_csv's _EXCL / _EXCL2 lines


def page_offsets():
    """ColorButtonMenu-relative offsets the camera rewrites in its copy:
    the six row limits and the Effect box's (BE floats, 15 + n), the text end
    -- where they are in the copy, after the label keys' insert."""
    img = O.image()
    a, _off, _n = O.resource_set('ColorButtonMenu')
    floats = [O.be_float_at(img, w, 15) - a for w in O.COLOR_ROW_MAX + [O.RAWVIEW_EFFECT_END]]
    _clip, ins, _b = label_clip()
    assert max(floats) < ins < O.COLOR_TEXT_END - a
    return floats, O.COLOR_TEXT_END - a + LABEL_INSERT, struct.unpack('>I', O.at(img, O.COLOR_TEXT_END, 4))[0]


def label_ops(blk):
    """The PAGE's label part: guards, the keys inserted at the clip's end (their
    values: the block's placeholder strings), the clip's size / key count and
    the header's budget for it."""
    clip, ins, budget = label_clip()
    a = O.resource_set('ColorButtonMenu')[0]
    keys = b''.join(struct.pack('>2BII', 0, 0, t, 0) for t in LABEL_KEYS)
    rel = []
    for j in range(MAX_ROWS):
        rel += [fpui.R_STRING << 24 | blk.string(label_placeholder(j), fpui.NOT_STOCK), KEY_BYTES * j + 6]
    clip_at = LABEL_CLIP - a
    return ([(fpui.OP_GUARD, clip_at, 0x1000A), (fpui.OP_GUARD, clip_at + 4, len(clip)),
             (fpui.OP_GUARD, clip_at + 28, 16), (fpui.OP_GUARD, budget, 16),
             (fpui.OP_INSERT, ins, blk.fragment(keys), len(keys), *rel),
             (fpui.OP_ADD32, clip_at + 4, LABEL_INSERT), (fpui.OP_ADD32, clip_at + 28, MAX_ROWS),
             (fpui.OP_ADD32, budget, MAX_ROWS)], ins)


def label_string_offsets(blob):
    """Each placeholder's text in the encoded block (block-relative)."""
    strings, _ops, _frag = fpui.decode(blob)
    cur, at = 0x20, {}
    for text, _hint in strings:
        at[text] = cur + 8
        cur += (8 + len(text.encode()) + 1 + 3) & ~3
    return [at[label_placeholder(j)] for j in range(MAX_ROWS)]


def block():
    img = O.image()
    blk = fpui.Block()
    hook_fv(blk)                                          # no OP_FILE: the copies are colshare.c's, made at sync
    edits = [(fpui.OP_ADDF, O.be_float_at(img, w, 15), MAX_ROWS) for w in O.COLOR_ROW_MAX]
    edits.append((fpui.OP_ADD32, O.COLOR_TEXT_END, TEXT_END_STEP * MAX_ROWS))
    edits.append((fpui.OP_ADDF, O.be_float_at(img, O.RAWVIEW_EFFECT_END, 15), MAX_ROWS))
    a, off, n = O.resource_set('ColorButtonMenu')
    label, _ins = label_ops(blk)
    blk.op(fpui.OP_PAGE, blk.string('ColorButtonMenu', fpui.NAME), off, n, 1, 0, LABEL_INSERT, 1)
    blk.op(fpui.OP_GUARD, 0, struct.unpack('>I', O.at(img, a, 4))[0])     # the set's header
    for op, *args in label:
        blk.op(op, *args)
    for op, addr, delta in edits:
        fpui.check(a <= addr < a + n, '0x%08X outside ColorButtonMenu' % addr)
        blk.op(op, addr - a, delta)
    blk.op(fpui.OP_DONE)
    return blk.encode()


MAGIC = 0x31535343                        # "CSS1": colshare.c struct cs_section
RAWVIEW_FILES = ('RAWV.BIN',)             # + names_v4's, and its last few versions (rawview_files)
RAWVIEW_CLIENT = 0x00000400               # RAW-View 的檔頭 version >= 0.4.0(maj<<16|min<<8|patch):COL-Share 的客戶(P3)
LOG_OLD_RAWVIEW = 'COL-Share: old RAW-View on the card, leaving it the COLOR list'
LOG_FAILED = 'COL-Share: install failed, released'


def rawview_files():
    """The names a RAW-View file can have on the card.  The loader loads the newest of one base name, so an
    old 0.3.x file can sit next to the 0.4 client it does not load: the client's names are probed too
    (P3, 2026-11-08: names_v4 gets '0.4.0test' -- a version with a suffix -- once the merge page takes it)."""
    import re
    sys.path.insert(0, str(HERE.parent / 'loader-v4'))
    import names_v4 as NV
    _d, base, ver = NV.SUPS['RAWV']
    major, minor, patch = (int(re.match(r'\d+', x).group()) for x in ver.split('.')[:3])
    vers = [f'{major}.{minor}.{p}' for p in range(max(0, patch - 3), patch + 4)]
    vers += [ver] + [f'0.3.{p}' for p in range(5)] + [f'0.4.{p}{t}' for p in range(3) for t in ('', 'test')]
    names = RAWVIEW_FILES + tuple(f'{base}_v{v}.BIN' for v in vers)
    return tuple(dict.fromkeys(names))


def rawview_id():
    sys.path.insert(0, str(HERE.parent / 'loader-v4'))
    import build_v4 as B
    return B._id('RAWV')


def n_tiles():
    return MAX_ROWS if TEST else 1


def _words():
    return (4 + 3 + 3 + 3 + 4 + 2 * MAX_ROWS + 2 * n_tiles() + 7 + 4 + (MAX_ROWS + 1) + 4 + MAX_ROWS + 2 + 2)


WORDS = _words()


def section(base):
    """struct cs_section and its data, for a block-relative `base` (the section's own offset in the block)."""
    head = 4 * WORDS
    data = bytearray()

    def place(b, align=4):
        data.extend(bytes(-(head + len(data)) % align))
        at = base + head + len(data)
        data.extend(b)
        return at
    blk = block()
    block_off = place(blk, 8)
    tails = [place(s.encode() + b'\0') if s else 0 for s in CSV_TAILS]
    names = [place(d[0][:-4].encode() + b'\0') for d in DONORS]
    tl = tiles()
    t_off = [place(x) for x in tl]
    probe = place(b''.join(('\\fpSup\\' + n).encode() + b'\0' for n in rawview_files()))
    log_old = place(LOG_OLD_RAWVIEW.encode() + b'\0')
    log_fail = place(LOG_FAILED.encode() + b'\0')
    floats, text_off, text_base = page_offsets()
    _code, entry, table_word = O.handler()
    out = struct.pack('<4I', MAGIC, block_off, len(blk), ICON_CAP)
    out += struct.pack('<3I', *(a for _n, a, _s in CSV))
    out += struct.pack('<3I', *(s for _n, _a, s in CSV))
    out += struct.pack('<3I', *tails)
    out += struct.pack('<4I', *csv_fields())
    out += struct.pack(f'<{MAX_ROWS}I', *(a for _n, a, _s in DONORS))
    out += struct.pack(f'<{MAX_ROWS}I', *names)
    out += struct.pack(f'<{len(tl)}I', *t_off)
    out += struct.pack(f'<{len(tl)}I', *(len(x) for x in tl))
    out += struct.pack('<7I', *floats)
    out += struct.pack('<4I', text_off, text_base, entry, table_word)
    out += struct.pack(f'<{MAX_ROWS + 1}I', *(struct.unpack('>I', struct.pack('>f', 15.0 + n))[0]
                                             for n in range(MAX_ROWS + 1)))
    out += struct.pack('<4I', probe, len(rawview_files()), rawview_id(), RAWVIEW_CLIENT)
    out += struct.pack(f'<{MAX_ROWS}I', *(block_off + o for o in label_string_offsets(blk)))
    _clip, ins, _budget = label_clip()
    out += struct.pack('<2I', ins, LABEL_INSERT)
    out += struct.pack('<2I', log_old, log_fail)
    assert len(out) == head
    return out + bytes(data)
