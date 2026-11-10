#!/usr/bin/env python3
"""What the QS container changes in the stock custom-QS editor, worked out from
the firmware image (Ver.5.02) at build time.  No device I/O.

The editor (pages Y2_3C and Y2_3C_ShutterAngle, GUI 123) is data: each of its
eight tiles shows the function in MV_QSMENU_QSn by playing an animation at frame
= the UI id (time = id * 100 / 3 ms).  A new id needs, in every tile
(projects/qs-touch/notes/QS_EDITOR_ID_PATHS.md §1.1, §3):

  * Icon01_CINE's appVariableChangeEvent range upper 48 -> 48+N   (E2)
  * the 'Icon01_CINE' interval's end 1600 -> t(48+N)              (E3)
  * a key at t(id) in clip Icon01_CINE/2 (image, rect, size, position),
    index/3 (position = the list row) and string/2 (text = the label)   (E4)

plus, per page, the list cursor maximum (Visible 31 -> 31+N) and the total
count's two digit images (E5).  Without E2..E4 a tile holding a new id is never
initialised at page build: name 'xxxx', index.position_x 90.0 -> the OK path
focuses the list at item 90, which does not exist (the 2026-10-28 freeze).

The clips also hold a second half, t = 1800..3400, played only by the W91C1
(fp L) twin interval whose event never fires on the fp.  Ids 49..53 fit below
1800; from 54 on a new key lands on a twin key's time, which is then
overwritten (value, and its interpolation flag set to step).

The result is an edit list in STOCK page coordinates that qsct.c applies in one
streaming copy of the page (no per-insert memmove), for any N <= MAX_FUNCS.
"""
import pathlib
import struct
import sys
from fractions import Fraction

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / 'fpSup' / 'uishare')]
from ui import options as O        # noqa: E402

POOL, POOL_LEN = 0xC18C0474, 176152
MAX_FUNCS = 16
UI_BASE, INT_BASE = 49, 54           # the smallest free ids (QS_ADD_FUNCTION_RESEARCH §1.3)
STOCK_MAX_UI = 48
STOCK_ROWS = 32
PAGES = ['Y2_3C', 'Y2_3C_ShutterAngle']
PAGE_CSV = {'Y2_3C': 0, 'Y2_3C_ShutterAngle': 2}   # index into CSVS: the list the page shows on the fp
CSVS = [('Y2_3_CINE', 0xC0F930D4, 1540), ('Y2_3_CINE_W91C1', 0xC0F936D8, 1539),
        ('Y2_3_CINE_angle', 0xC0F93CDC, 1517), ('Y2_3_CINE_angle_W91C1', 0xC0F942CC, 1512)]
VISIBLE_OBJ = 0x1116
LINEAR = 0x0100                      # a key's 2-byte flag: interpolate to the next key; 0 = hold

T_OBJECT, T_EVENT, T_CLIP, T_GROUP = 0x10003, 0x10006, 0x1000A, 0x1000B

# edit kinds (qsct.c K_*) and value selectors (S_*)
K_ADDF_N, K_SET_END, K_ADJ, K_INS, K_SETV, K_SETFLAG, K_DIGIT = 1, 2, 3, 4, 5, 6, 7
S_NONE, S_IMAGE, S_RECT, S_SIZE, S_POS, S_ROW, S_LABEL = 0, 1, 2, 3, 4, 5, 6
EDIT_FMT = '<IBBBBII'                # pos, kind, sel, fi, pad, a, b  (16 bytes)


class DataError(RuntimeError):
    pass


def check(cond, msg):
    if not cond:
        raise DataError(msg)


def t_of(ui):
    """The stock key time of frame `ui` (33, 66, 100, ... 1600): floor(ui * 100 / 3)."""
    return ui * 100 // 3


def be(d, o):
    return struct.unpack_from('>I', d, o)[0]


def pool_str(off):
    img = O.image()
    if off >= POOL_LEN:
        return None
    a = POOL - 0xC0000000 + off
    return img[a:img.index(b'\0', a)].decode('utf-8', 'replace')


def pool_offset(text):
    img = O.image()
    pool = img[POOL - 0xC0000000:POOL - 0xC0000000 + POOL_LEN]
    want = text.encode() + b'\0'
    hits, i = [], pool.find(want)               # every (overlapping) occurrence, as startswith at each i did
    while i >= 0:
        if i == 0 or pool[i - 1] == 0:
            hits.append(i)
        i = pool.find(want, i + 1)
    check(len(hits) == 1, f'pool string {text!r}: {len(hits)} hits')
    return hits[0]


def page_bytes(name):
    a, off, n = O.resource_set(name)
    return a, off, O.at(O.image(), a, n)


def records(page):
    out, o = [], 0
    while o + 8 <= len(page):
        tag, size = be(page, o), be(page, o + 4)
        check(size >= 8 and o + size <= len(page), f'bad record at +0x{o:X}')
        out.append((o, tag, size))
        o += size
        if tag == 0xFFFFFFFF:
            break
    return out


def objects(page, recs):
    return {be(page, o + 20): (pool_str(be(page, o + 28)), be(page, o + 24))
            for o, tag, _s in recs if tag == T_OBJECT}


def children(objs, parent, name):
    hits = [i for i, (n, p) in objs.items() if p == parent and n == name]
    check(len(hits) == 1, f'{len(hits)} children {name!r} of {parent}')
    return hits[0]


class Prop:
    """One animated property of a clip record: its keys {flag, time, value}."""

    def __init__(self, page, at):
        self.at = at                                       # page offset of the prop header
        self.count, self.kind, self.c, self.name_off, self.dim = struct.unpack_from('>5I', page, at)
        self.name = pool_str(self.name_off)
        self.keys = []
        for i in range(self.count):
            k = at + 20 + 10 * i
            flag, t, v = struct.unpack_from('>HII', page, k)
            self.keys.append((k, flag, t, v))
        self.end = at + 20 + 10 * self.count

    def value_at(self, time):
        """The firmware's playback as modelled: the last key at or before `time`;
        a LINEAR float key interpolates to the next one, anything else holds."""
        prev = None
        for i, (k, flag, t, v) in enumerate(self.keys):
            if t <= time:
                prev = i
        check(prev is not None, 'no key at or before t=%s' % time)
        k, flag, t, v = self.keys[prev]
        if self.kind == 1:
            f = struct.unpack('>f', struct.pack('>I', v))[0]
            if flag & LINEAR and prev + 1 < len(self.keys):
                _k2, _f2, t2, v2 = self.keys[prev + 1]
                f2 = struct.unpack('>f', struct.pack('>I', v2))[0]
                f = f + (f2 - f) * float(Fraction(time) - t) / (t2 - t)
            return f
        return v


class Clip:
    def __init__(self, page, at):
        self.at, self.size = at, be(page, at + 4)
        self.owner, self.id = be(page, at + 20), be(page, at + 24)
        self.props, cur = [], at + 28
        for _ in range(be(page, at + 12)):
            p = Prop(page, cur)
            self.props.append(p)
            cur = p.end
        check(cur == at + self.size, f'clip at +0x{at:X} does not end where its size says')

    def prop(self, name, dim=None):
        hits = [p for p in self.props if p.name == name and (dim is None or p.dim == dim)]
        check(len(hits) == 1, f'clip {self.owner}/{self.id}: {len(hits)} props {name}[{dim}]')
        return hits[0]


def clip_of(page, recs, owner, cid):
    hits = [o for o, tag, _s in recs if tag == T_CLIP and be(page, o + 20) == owner and be(page, o + 24) == cid]
    check(len(hits) == 1, f'{len(hits)} clips {owner}/{cid}')
    return Clip(page, hits[0])


def tiles(name):
    """Per tile: the stock offsets the edits need, and its three clips."""
    a, _off, page = page_bytes(name)
    recs = records(page)
    objs = objects(page, recs)
    menu = next(i for i, (n, _p) in objs.items() if n == 'Menu01')
    icon_name = pool_offset('Icon01_CINE')
    out = []
    for k in range(1, 9):
        tile = children(objs, menu, f'QS{k}C')
        cine = children(objs, children(objs, tile, 'Icon01'), 'Icon01_CINE')
        index, string = children(objs, cine, 'index'), children(objs, cine, 'string')
        var = pool_offset(f'MV_QSMENU_QS{k}')
        events = [o for o, tag, s in recs if tag == T_EVENT and be(page, o + 24) == cine
                  and be(page, o + 36) == var and page[o + 44] == 0x23
                  and page[o + 45:o + 49] == struct.pack('>f', 48.0)]
        # one: the W91C1 twin's event has type 0 (never fires on the fp)
        check(len(events) == 1, f'{name} QS{k}C: {len(events)} live ranged events')
        groups = [o for o, tag, s in recs if tag == T_GROUP and be(page, o + 24) == cine
                  and be(page, o + 20) == icon_name]
        check(len(groups) == 1 and be(page, groups[0] + 32) == 0 and be(page, groups[0] + 36) == 1600,
              f'{name} QS{k}C: the Icon01_CINE interval is not 0..1600')
        out.append(dict(k=k, tile=tile, cine=cine, index=index, string=string,
                        range=events[0] + 45, end=groups[0] + 36,
                        icon=clip_of(page, recs, cine, 2), row=clip_of(page, recs, index, 3),
                        text=clip_of(page, recs, string, 2)))
    return a, page, recs, objs, out


def visible_max(name):
    """The list cursor's maximum (a BE float, rows - 1): the probe's finder
    (sensorlab-imx410/qsprobe build_qsprobe.visible_max), as a page offset."""
    sys.path.insert(0, str(ROOT / 'research/ui/tools/nbu_probe'))
    import nbu_format as NF
    a, _off, page = page_bytes(name)
    hits = []
    for r in NF.split(page):
        if r.tag != 0x0001000E or len(r.body) != 44:
            continue
        if struct.unpack_from('>I', r.body, 12)[0] == VISIBLE_OBJ and \
                struct.unpack_from('>f', r.body, 28)[0] == STOCK_ROWS - 1:
            hits.append(a + r.offset + 36)
    check(len(hits) == 1, f'{name}: {len(hits)} Visible maxima')
    return O.be_float_at(O.image(), hits[0], STOCK_ROWS - 1) - a


def total_digits(name):
    """The stock offsets of the total count's two key values (tens, units)."""
    _a, _off, page = page_bytes(name)
    recs = records(page)
    objs = objects(page, recs)
    number = next(i for i, (n, _p) in objs.items() if n == 'Number')
    out = []
    for nm, want in (('total1', '3'), ('total2', '2')):
        c = clip_of(page, recs, children(objs, number, nm), 2)
        p = c.prop('image')
        check(p.count == 1 and pool_str(p.keys[0][3]) == 'font_menu_S_' + want, f'{name} {nm}')
        out.append((p.keys[0][0] + 6, p.keys[0][3]))
    return out


def csv_rows(i):
    """(ID, IMAGE) of the stock CSV's rows."""
    import csv
    import io
    _n, a, size = CSVS[i]
    rows = list(csv.reader(io.StringIO(O.at(O.image(), a, size).decode('utf-8-sig'), newline='')))
    check(rows[0] == ['NO', 'ID', 'IMAGE', 'KEY', 'memo'] and len(rows) == STOCK_ROWS + 1, CSVS[i][0])
    return [(int(r[1]), r[2]) for r in rows[1:]]


def icon_table():
    """{list image name: (tile image pool offset, rect, size, position)} -- the
    look a stock function has in the tile, borrowed by name.  Only names whose
    look is the same in all 16 tiles of both pages."""
    looks = {}
    for name in PAGES:
        _a, _page, _recs, _objs, ts = tiles(name)
        for ui, img in csv_rows(PAGE_CSV[name]):
            t = Fraction(ui * 100, 3)
            for tl in ts:
                c = tl['icon']
                look = (c.prop('image').value_at(t), c.prop('rect', 2).value_at(t),
                        c.prop('size', 0).value_at(t), c.prop('position', 0).value_at(t))
                looks.setdefault(img, set()).add(look)
    out = {}
    for img, s in looks.items():
        if len(s) == 1:
            image, rect, size, pos = s.pop()
            out[img] = (image, *(struct.unpack('<I', struct.pack('<f', x))[0] for x in (rect, size, pos)))
    return out


DEFAULT_ICON = 'menu_crop'


def key_edits(prop, fi, sel, rec_at):
    """A key at t(49 + fi) holding selector `sel`: overwrite one that is there
    (the W91C1 twin's), else insert one before the first later key."""
    t = t_of(UI_BASE + fi)
    same = [k for k in prop.keys if k[2] == t]
    if same:
        k, flag, _t, v = same[0]
        out = [(k + 6, K_SETV, sel, fi, v, 0)]
        if flag:
            out.append((k, K_SETFLAG, S_NONE, fi, flag, 0))
        return out, 0
    later = [k for k in prop.keys if k[2] > t]
    at = later[0][0] if later else prop.end
    return [(at, K_INS, sel, fi, 0, t)], 1


def page_edits(name, max_funcs=MAX_FUNCS):
    """The edit list of one page, sorted the way qsct.c applies it."""
    _a, page, _recs, _objs, ts = tiles(name)
    # K_ADDF_N b=1 counts visible editor rows; b=0 counts all dynamic ids.
    edits = [(visible_max(name), K_ADDF_N, S_NONE, 0xFF, be(page, visible_max(name)), 1)]
    for tl in ts:
        edits.append((tl['range'], K_ADDF_N, S_NONE, 0xFF, be(page, tl['range']), 0))
        edits.append((tl['end'], K_SET_END, S_NONE, 0xFF, 1600, 0))
        for clip, props in ((tl['icon'], (('image', None, S_IMAGE), ('rect', 2, S_RECT), ('size', 0, S_SIZE),
                                         ('position', 0, S_POS))),
                            (tl['row'], (('position', 0, S_ROW),)),
                            (tl['text'], (('text', 0, S_LABEL),))):
            for pname, dim, sel in props:
                p = clip.prop(pname, dim)
                mask = 0
                for fi in range(max_funcs):
                    e, ins = key_edits(p, fi, sel, clip.at)
                    edits += e
                    mask |= ins << fi
                if mask:
                    edits.append((p.at, K_ADJ, S_NONE, 0xFF, mask, 1))         # the key count
                    edits.append((clip.at + 4, K_ADJ, S_NONE, 0xFF, mask, 10))  # the record size
    for sel, (pos, old) in enumerate(total_digits(name)):
        edits.append((pos, K_DIGIT, sel, 0xFF, old, 0))
    # stock order; at one position the inserts first (by function), then the rest
    edits.sort(key=lambda e: (e[0], 0 if e[1] == K_INS else 1, e[3]))
    width = {K_ADDF_N: 4, K_SET_END: 4, K_ADJ: 4, K_SETV: 4, K_SETFLAG: 2, K_DIGIT: 4, K_INS: 0}
    ins_at = sorted({e[0] for e in edits if e[1] == K_INS})
    for pos, kind, *_ in edits:
        w = width[kind]
        check(not any(pos < q < pos + w for q in ins_at), f'{name}: an edit at +0x{pos:X} straddles an insert')
    return edits


def pack_edits(edits):
    return b''.join(struct.pack(EDIT_FMT, pos, kind, sel, fi, 0, a & 0xFFFFFFFF, b) for pos, kind, sel, fi, a, b in edits)


def unpack_edits(blob):
    n = struct.calcsize(EDIT_FMT)
    return [struct.unpack_from(EDIT_FMT, blob, i) for i in range(0, len(blob), n)]


def digit_offsets():
    return [pool_offset(f'font_menu_S_{d}') for d in range(10)]


if __name__ == '__main__':
    for p in PAGES:
        e = page_edits(p)
        kinds = {}
        for x in e:
            kinds[x[1]] = kinds.get(x[1], 0) + 1
        print(p, len(e), 'edits', kinds, 'insert bytes at N=16:', 10 * kinds.get(K_INS, 0))
    print(len(icon_table()), 'icons:', sorted(icon_table()))
