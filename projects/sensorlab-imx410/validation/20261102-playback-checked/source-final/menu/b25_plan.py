#!/usr/bin/env python3
"""SensorLab-IMX410 menu rows: what the page edits touch in the STOCK B2_5 and MainB2 sets (read only).

    python3 -B b25_plan.py [--out plan.json]

For each of the four rows (notes/MENU_DESIGN.md §2) this finds, in the firmware image, every field the edit has to
change -- the variable and list names to make private, the summary texts, the controller caps -- as a stock address
plus the word that must be there (a GUARD).  The FPUI block that carries the edits (fpsup-ui fpui_stock ops, stock
coordinates) is built from this plan in a later step; the plan is what the tests pin today.

Field layout: the stock property schemas (fpSup/lossless/menu/build_menu_candidate.py load_property_schemas, the
same reader nbu_components.py and open-gate/build/sl_b25_page.py use).  Firmware Ver.5.02, out/MAIN_c0000000.bin.
"""
import argparse
import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / 'fpSup/lossless/menu'), str(ROOT / 'research/ui/tools/nbu_probe')]
import build_menu_candidate as BM          # noqa: E402
import nbu_format as N                     # noqa: E402

B = 0xC0000000
IMG = ROOT / 'out/MAIN_c0000000.bin'
POOL, POOL_LEN = 0xC18C0474, 176152
SETS = {'B2_5': (0xC1A5C590, 0xC1A792FB), 'MainB2': (0xC2030364, 0xC2055DB0)}
WIDTH = {0: 4, 1: 4, 2: 4, 3: 4, 4: 16, 5: 16, 6: 8, 7: 12, 8: 16, 9: 4, 10: 4, 11: 5, 12: 4, 13: 4, 14: 4}
STR_KINDS = (9, 10, 11, 12, 13)

# The four rows.  rename: stock string -> private string (in this row's subtree only; anything else named the
# same elsewhere on the page stays stock), or {field: private, '*': private} for a per-field choice.  EXCL_* does
# two jobs (SelectLock's lock event, and the apply-frame of the clips that pick the CSV variant): both go to the one
# private EXCL_SLM_* (0 = selectable; every variant names our one list).  The row count / cap is a separate private
# variable driving an added clip property (MENU_DESIGN §2.1), not one of these fields.  Private names: SLM_ prefix.
ROWS = {
    'RES': dict(page='B2_5', root=4253, csv=('B2_5_4',), rename={
        'MV_Resolution': 'SLM_Res', 'EXCL_MVResolution': 'EXCL_SLM_Res',
        'B2_5_4': 'SLM_RES'}),
    'FPS': dict(page='B2_5', root=4433, csv=('B2_5_5', 'B2_5_5_excl', 'B2_5_5_excl2', 'B2_5_5_excl3',
                                             'B2_5_5_excl4', 'B2_5_5_excl5'), rename={
        'MV_FrameRate': 'SLM_Fps', 'EXCL_FrameRate': 'EXCL_SLM_Fps',
        'B2_n5_ListFocus4': 'SLM_FpsFocus',
        'B2_5_5': 'SLM_FPS', 'B2_5_5_excl': 'SLM_FPS', 'B2_5_5_excl2': 'SLM_FPS', 'B2_5_5_excl3': 'SLM_FPS',
        'B2_5_5_excl4': 'SLM_FPS', 'B2_5_5_excl5': 'SLM_FPS'}),
    # the bit-depth row keeps the stock setting (RAW bit = the stock 12-bit, the one the apply step needs); only
    # its list is ours (8 / 10 greyed) and the 12-bit summary text says RAW
    'BIT': dict(page='B2_5', root=91, csv=('B2_5_2', 'B2_5_2_excl'), rename={
        'B2_5_2': 'SLM_BIT', 'B2_5_2_excl': 'SLM_BIT'}),
    'DC': dict(page='MainB2', root=21878, csv=(), rename={
        'CM_DCCrop': 'SLM_Dc', 'EXCL_DCCrop': 'EXCL_SLM_Dc'}),
}
SUMMARY = {'RES': ('1516', '1517'), 'FPS': ('0316', '1916', '0317', '0318', '2115', '0319', '0320', '0321', '0322'),
           'BIT': ('0307',), 'DC': ('0080', '0236_I')}
CAPS = ('MenuItem_Select', 'List', 'ListItem', 'IconChange')


def u32(d, o):
    return struct.unpack_from('>I', d, o)[0]


def f32(w):
    return struct.unpack('>f', struct.pack('>I', w))[0]


class Image:
    def __init__(self, path=IMG):
        self.img = pathlib.Path(path).read_bytes()
        self.pool = self.img[POOL - B:POOL - B + POOL_LEN]
        self.schemas = BM.load_property_schemas(self.img)

    def text(self, off):
        if off == 0xFFFFFFFF or off >= len(self.pool):
            return None
        return self.pool[off:self.pool.find(b'\0', off)].decode('utf-8', 'replace')

    def page(self, name):
        lo, hi = SETS[name]
        return lo, self.img[lo - B:hi - B]


def fields(im, rec):
    """[(offset in the record, property name, kind, component)] for one component record; [] otherwise."""
    tag = u32(rec, 0)
    if tag not in BM.OWNER_OFFSETS or tag == 0x1000A:
        return []
    comp = im.text(u32(rec, 8))
    if comp not in im.schemas:
        return []
    out, cur, mask = [], BM.MASK_OFFSETS[tag], 0
    for i, p in enumerate(im.schemas[comp]):
        if i % 32 == 0:
            mask, cur = u32(rec, cur), cur + 4
        if not (mask >> (i % 32)) & 1:
            continue
        out.append((cur, p['name'], p['kind'], comp))
        cur += WIDTH[p['kind']]
    return out


def clip_strings(rec):
    """[(offset, what)] of the string words in an animation clip (0x1000A) or image array (0x1000B) record
    (layouts: sl_b25_page.typed_fields, nbu_format.decode_image_array)."""
    tag, out = u32(rec, 0), []
    if tag == 0x1000A:
        cur = 28
        for _ in range(u32(rec, 12)):
            count, kind = u32(rec, cur), u32(rec, cur + 4)
            out.append((cur + 12, 'clip property'))
            if kind == 2:
                out += [(cur + 20 + 10 * i + 6, 'clip key') for i in range(count)]
            cur += 20 + count * 10
    elif tag == 0x1000B:
        na, nb = u32(rec, 8), u32(rec, 12)
        out.append((20, 'image group'))
        cur = 28
        for _ in range(na):
            out.append((cur, 'image'))
            cur += 21
        for _ in range(nb):
            out.append((cur, 'image value'))
            cur += 13 if rec[cur + 8] else 9
    return out


def walk(im, name):
    base, page = im.page(name)
    recs = [(r.offset, r.to_bytes()) for r in N.split(page)]
    objs = {u32(rec, 20): (u32(rec, 24), im.text(u32(rec, 28))) for _o, rec in recs if u32(rec, 0) == 0x10003}
    return base, page, objs, recs


def subtree(objs, root):
    ids, grew = {root}, True
    while grew:
        grew = False
        for i, (p, _n) in objs.items():
            if p in ids and i not in ids:
                ids.add(i)
                grew = True
    return ids


def owner(rec):
    tag = u32(rec, 0)
    if tag == 0x10003:
        return u32(rec, 20)
    if tag in BM.OWNER_OFFSETS and tag != 0x1000A:
        return u32(rec, BM.OWNER_OFFSETS[tag])
    if tag in (0x1000A, 0x1000B):
        return u32(rec, 20 if tag == 0x1000A else 24)
    return None


def new_name(row, old, prop):
    n = row['rename'][old]
    return n if isinstance(n, str) else n.get(prop, n['*'])


def plan(im=None):
    im = im or Image()
    out = {}
    cache = {}
    for key, row in ROWS.items():
        if row['page'] not in cache:
            cache[row['page']] = walk(im, row['page'])
        base, page, objs, recs = cache[row['page']]
        ids = subtree(objs, row['root'])
        renames, summary, caps = [], [], []
        for off, rec in recs:
            if owner(rec) not in ids:
                continue
            for at, what in clip_strings(rec):
                s = im.text(u32(rec, at))
                if s in row['rename']:
                    renames.append(dict(addr=base + off + at, word=u32(rec, at), old=s, new=new_name(row, s, what),
                                        prop=what, comp=hex(u32(rec, 0)), owner=owner(rec),
                                        owner_name=objs[owner(rec)][1]))
            for at, prop, kind, comp in fields(im, rec):
                addr = base + off + at
                word = u32(rec, at)
                if kind in STR_KINDS:
                    s = im.text(word)
                    if s in row['rename']:
                        renames.append(dict(addr=addr, word=word, old=s, new=new_name(row, s, prop), prop=prop, comp=comp,
                                            owner=owner(rec), owner_name=objs[owner(rec)][1]))
                    if comp == 'drawText' and prop == 'text' and s in SUMMARY[key]:
                        summary.append(dict(addr=addr, word=word, old=s, owner=owner(rec),
                                            owner_name=objs[owner(rec)][1]))
                if comp == 'controlValue' and prop == 'max-value' and objs[owner(rec)][1] in CAPS:
                    caps.append(dict(addr=addr, word=word, value=f32(word), owner=owner(rec),
                                     owner_name=objs[owner(rec)][1]))
        out[key] = dict(page=row['page'], root=row['root'], objects=len(ids), renames=renames, summary=summary,
                        caps=caps)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', type=pathlib.Path)
    a = ap.parse_args(argv)
    p = plan()
    for k, v in p.items():
        print(f"{k}: {v['page']} root {v['root']} ({v['objects']} objects): {len(v['renames'])} renames, "
              f"{len(v['summary'])} summary texts, caps " +
              ', '.join(f"{c['owner_name']}={c['value']:g}" for c in v['caps']))
    if a.out:
        a.out.write_text(json.dumps(p, indent=1) + '\n')


if __name__ == '__main__':
    main()
