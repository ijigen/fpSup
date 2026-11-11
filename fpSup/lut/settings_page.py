"""The settings page AEL opens on a manager row: two rows, Color space and Gamma
(the user 2026-10-24), each a stock scrolling list -- not MainY5's three-item
popup, and not split into groups ("fp 選單是支援捲動的").

The rows are copies of MainB1's B1_4 row (Drive mode: a MenuItem_SelectJump
whose List has the `list` component, a scroll event and a scrollbar, its rows
from a CSV model).  Their models are this sup's own CSVs, carried in the page
file's extra NBR pack (fpsup_ui.c loads it through the stock NBR loader before
the pages; the lookup is by resource name -- projects/open-gate/build/sl_lists.py
did the same on the camera).  No stock CSV is borrowed or changed.

Gamma follows the color space the stock way: the list's variants (B1_4_excl..)
are chosen by its EXCL variable -- here LC_GammaX: 0 the six common Gammas,
1 the two Blackmagic ones.  Offline only.
"""
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'uishare/tab'))
import ft6_page as P                     # noqa: E402
import manage_page as M                  # noqa: E402
import nbu_format as N                   # noqa: E402
from cinemadng import COLOR_SPACES, COMMON_GAMMAS, BLACKMAGIC_GAMMAS, GAMMAS   # noqa: E402

u32, put, check = P.u32, P.put, P.check
DONOR_SET, DONOR_ROW, DONOR_SELECT, DONOR_NAME = 'MainB1', 127, 288, 299
DONOR_SUMMARY = (12858, 300)             # IconText / Icon: the stock per-index summary
DONOR_MODEL = 'B1_4'
DONOR_VARIANTS = ('B1_4_excl', 'B1_4_excl2', 'B1_4_excl3')
ROW_Y = 81.0

# name, title, model, variant models (by the EXCL value), value / excl variables
SPACE = dict(title='Color space', model='LC_SPACE', variants=('LC_SPACE',) * 3, rows=8,
             value='LC_SpaceV', excl='LC_SpaceX', text='LC_SpaceT', cap=None)
GAMMA = dict(title='Gamma', model='LC_GAMMA', variants=('LC_GAMMA_BMD',) * 3, rows=6,
             value='LC_GammaV', excl='LC_GammaX', text='LC_GammaT', cap='LC_GammaM')
DONOR_LIST, DONOR_ITEM, ITEM_CAPACITY = 292, 293, 8
ZERO = 'LC_Zero'                          # EXCL_ShootingModeCustom's place: never locked


def rows_csv(texts):
    """B1_4.cvm's own columns, a literal TEXT per row and the blank image; the
    UTF-8 BOM and a CRLF after every line, the last one too (fp-native-ui 2)."""
    for t in texts:
        check(t.isascii() and not set(t) & set(',<>'), f'row text {t!r}')
    lines = ['NO,TEXT,Popup,IMAGE,Enabled,Enabled2,Cusor02']
    lines += [f'{i},{t},xxx,blank,1,2,0' for i, t in enumerate(texts, 1)]
    return b'\xef\xbb\xbf' + ('\r\n'.join(lines) + '\r\n').encode()


def models():
    return [('LC_SPACE', rows_csv([c.label for c in COLOR_SPACES.values()])),
            ('LC_GAMMA', rows_csv([GAMMAS[g].label for g in COMMON_GAMMAS])),
            ('LC_GAMMA_BMD', rows_csv([GAMMAS[g].label for g in BLACKMAGIC_GAMMAS]))]


def csv_pack(items):
    """modelCSV resources as an NBR pack: sl_lists.build_pack's format."""
    import nbr as NBR
    pool, offs = bytearray(4), {}

    def intern(v):
        if v not in offs:
            offs[v] = len(pool)
            pool.extend(v.encode() + b'\0')
            pool.extend(bytes(-len(pool) % 4))
        return offs[v]

    for name, _ in items:
        intern('modelCSV'); intern(name); intern(f'{name}.cvm')
    out = bytearray(NBR.MAGIC)
    out += struct.pack('>II', 1, 8 + len(pool)) + pool
    table = len(out)
    out += bytes(12 + 16 * len(items))
    files = []
    for name, data in items:
        fn = f'{name}.cvm'
        files.append((NBR.fnv1a(fn), intern(fn), len(out), len(data)))
        out += data + bytes(-len(data) % 4)
    struct.pack_into('>III', out, table, 2, len(out) - table, len(items))
    for i, e in enumerate(sorted(files)):
        struct.pack_into('>4I', out, table + 12 + 16 * i, *e)
    out += struct.pack('>4I', 0x20001, 16 + 36 * len(items), len(items), len(items))
    defs = len(out)
    out += bytes(36 * len(items))
    out += struct.pack('>II', 0xFFFFFFFF, 8)
    for i, (name, _) in enumerate(items):
        prop = len(out)
        struct.pack_into('>9I', out, defs + 36 * i, intern(name), intern('modelCSV'), 0,
                         0xFFFFFFFF, 0, 1, 0xFFFFFFFF, 0xFFFFFFFF, prop)
        out += struct.pack('>5I', 0x20002, 20, 1, 1, intern(f'{name}.cvm'))
    out += struct.pack('>II', 0xFFFFFFFF, 8)
    return bytes(out)


def template_ids(rec):
    """Offsets of the object ids in a list row template (0x10008): the List at
    20, the ListItem at 65, then `count` (at 69) 20-byte entries from 77, each
    led by an object id.  sl_lab_page.LIST_TEMPLATE_IDS is B5_4_2's 9-entry
    form; B1_4's has 13 and its last four kept MainB1's 293 / 297."""
    n = u32(rec, 69)
    check(len(rec) == 77 + 20 * n + 12, f'list template form ({len(rec)} B, {n} entries)')
    return (20, 65) + tuple(77 + 20 * i for i in range(n))


def donor():
    """MainB1's records and its group budgets (allocation header)."""
    img, base, rows, _ = N.load_sets()
    pool = P.stock_pool()[1]
    row = next(r for r in rows if r['name'] == DONOR_SET)
    recs = N.split(img, row['address'] - base)
    header = P.A.parse_header(P.A.Record(0, recs[0].to_bytes()), pool.text)
    gi = [i for i, r in enumerate(recs) if r.tag == 0x1000B]
    budget = {i: header['groups'][n] for n, i in enumerate(gi)}
    return recs, budget, pool


def foreign_row(pg, k, spec):
    """MainB1's B1_4 row as row k of this page, its list on `spec`'s models and
    variables.  Returns (records, id mapping)."""
    recs, budget, pool = donor()
    objs = P.SZ.objects(recs, pool)
    sub = P.SZ.subtree(objs, DONOR_ROW)
    a, b = P.SZ.span(recs, objs, sub, DONOR_ROW)
    mapping = {old: pg.take_id() for old in sorted(sub)}
    rename = {DONOR_MODEL: spec['model'], 'ST_DriveMode': spec['value'],
              'SUB_ST_DriveMode': 'SUB_' + spec['value'], 'EXCL_DriveMode': spec['excl'],
              'EXCL_ShootingModeCustom': ZERO,
              **dict(zip(DONOR_VARIANTS, spec['variants']))}
    rename = {pool.find(o): n for o, n in rename.items() if pool.find(o) is not None}
    out = []
    for i in range(a, b):
        r = bytearray(recs[i].to_bytes())
        for off, kind in P.P.typed_fields(bytes(r), pg.pool, pg.schemas):
            v = u32(r, off)
            if kind == 'obj' and v in mapping:
                put(r, off, mapping[v])
            elif kind in ('str', 'text') and v in rename:
                pg.private(r, off, rename[v])
        if u32(r, 0) == 0x10008:            # the list's row template (2026-11-03 camera: stale
            for o in template_ids(r):          # ids in it -> the list makes no rows, OK opens nothing)
                if u32(r, o) in mapping:
                    put(r, o, mapping[u32(r, o)])
        if u32(r, 0) == 0x1000B:
            pg.group_budget[id(r)] = budget[i]
        out.append(r)
    by = P.by_object(out)
    put(out[by[mapping[DONOR_ROW]][0]], 24, P.ROWS_PARENT)     # a child of this page's Y5, not MainB1's B1
    base = out[P.comp(out, by[mapping[DONOR_ROW]], 'objectBase', pg.pool)]
    check(u32(base, 28) == 1 and struct.unpack_from('>f', base, 36)[0] == 243.0, 'B1_4 row position form')
    struct.pack_into('>f', base, 36, ROW_Y * k)
    # the popup is the content's height from its top, as on MainB1 (y -243 at row 3)
    lb = out[P.comp(out, by[mapping[292]], 'objectBase', pg.pool)]
    check(u32(lb, 28) == 0xD3, 'B1_4 popup base form')
    struct.pack_into('>f', lb, 36, -ROW_Y * k)
    # the list's last row (rows - 1); Gamma's follows its variant (LC_GammaM)
    cv = out[P.comp(out, by[mapping[DONOR_LIST]], 'controlValue', pg.pool)]
    check(u32(cv, 28) == 0xA and struct.unpack_from('>f', cv, 32)[0] == 6.0, 'B1_4 List cap form')
    struct.pack_into('>f', cv, 32, float(spec['rows'] - 1))
    item = out[P.comp(out, by[mapping[DONOR_ITEM]], 'controlValue', pg.pool)]
    check(u32(item, 28) == 3 and struct.unpack_from('>f', item, 36)[0] == ITEM_CAPACITY
          and spec['rows'] <= ITEM_CAPACITY, 'B1_4 ListItem capacity')
    if spec['cap']:
        pg.bind(out, mapping[DONOR_LIST], spec['cap'], u32(cv, 24), 'max-value', 1)
    by = P.by_object(out)
    # the title: a literal
    t = out[P.comp(out, by[mapping[DONOR_NAME]], 'drawText', pg.pool)]
    pg.literal(t, spec['title'])
    # the summary: our own text (the value's label), the stock icons aside
    for old in DONOR_SUMMARY:
        M.move_hidden(out[P.comp(out, by[mapping[old]], 'objectBase', pg.pool)])
    # home4_page's value field: a sibling of the title, grey, right-aligned to
    # the stock value column, its text the variable the core posts
    name = mapping[DONOR_NAME]
    oid = pg.take_id()
    o = bytearray(out[by[name][0]])
    put(o, 20, oid); put(o, 8, 2); put(o, 16, 0)
    nb = P.owned(out[P.comp(out, by[name], 'objectBase', pg.pool)], oid)
    check(u32(nb, 28) == 3, 'B1_4 title base form')
    struct.pack_into('>4f', nb, 32, 460.0, 20.0, 404.0, 40.0)
    template = pg.raw[P.comp(pg.raw, pg.src[M.POPUP_TEXT[0]], 'drawText', pg.pool)]
    text = bytearray(template)
    put(text, 32, 0); text[36] = 0
    vt = M.label_text(pg, text, oid, 32, 0x9A9A9AFF, 404, 40)
    put(vt, 45, 3)                                   # right-aligned
    at = by[name][-1] + 1
    out[at:at] = [o, nb, vt]
    pg.bind(out, oid, spec['text'], u32(vt, 24), 'text')
    sel = mapping[DONOR_SELECT]
    head = out[P.by_object(out)[sel][0]]
    put(head, 16, u32(head, 16) + 1)
    return out, mapping


def extend_header_with_kinds(pool):
    """build_menu_candidate.extend_header, but a component kind MainY5 never
    uses (list, scrollEvent, drawScrollbar ...) is appended as a new
    (name, count) pair instead of refused.  The names are stock pool strings."""
    import build_menu_candidate as BM

    def extend(record, header, delta):
        out = bytearray(record.data[:20])
        struct.pack_into('>I', out, 8, header['objects'] + delta['objects'])
        names = list(header['component_counts'])
        new = [n for n in delta['component_counts'] if n not in names]
        for n in new:
            check(pool.find(n) is not None, f'component kind {n!r} is not a stock string')
        struct.pack_into('>I', out, 16, len(names) + len(new))
        for index, name in enumerate(names):
            out.extend(BM.words(record.word(20 + index * 8),
                                header['component_counts'][name] + delta['component_counts'].get(name, 0)))
        for name in new:
            out.extend(BM.words(pool.find(name), delta['component_counts'][name]))
        for name, added in (('groups', delta['group_budgets']),
                            ('clip_property_counts', delta['clip_property_counts']),
                            ('property_key_counts', delta['property_key_counts']),
                            ('trailing_budget', [])):
            values = header[name] + added
            out.extend(BM.words(len(values)))
            for value in values:
                out.extend(BM.words(*value) if isinstance(value, list) else BM.words(value))
        struct.pack_into('>I', out, 4, len(out))
        return bytes(out)
    return extend


def inspect_csv_pack(pack):
    """{resource name: CSV bytes} of a modelCSV pack, bounds checked
    (sl_lists.inspect_pack; nbr.inspect assumes xcimage properties)."""
    import nbr as NBR
    u = lambda o: struct.unpack_from('>I', pack, o)[0]
    check(pack.startswith(NBR.MAGIC), 'not an NBR pack')
    s = lambda o: pack[20 + o:pack.index(b'\0', 20 + o)].decode()
    table = 12 + u(16)
    check(u(table) == 2, 'no file table')
    files, keys = {}, []
    for i in range(u(table + 8)):
        k, no, do, ln = struct.unpack_from('>4I', pack, table + 12 + 16 * i)
        check(k == NBR.fnv1a(s(no)) and do + ln <= table + u(table + 4), 'file entry')
        files[s(no)] = pack[do:do + ln]; keys.append(k)
    check(keys == sorted(keys), 'file table not FNV-sorted')
    decl = table + u(table + 4)
    tag, total, cnt, var = struct.unpack_from('>4I', pack, decl)
    check(tag == 0x20001 and total == 16 + 36 * cnt and cnt == var == len(files), 'declarations')
    out = {}
    for i in range(cnt):
        f = struct.unpack_from('>9I', pack, decl + 16 + 36 * i)
        prop = struct.unpack_from('>5I', pack, f[8])
        check(s(f[1]) == 'modelCSV' and f[5] == 1 and prop[:4] == (0x20002, 20, 1, 1), 'modelCSV declaration')
        out[s(f[0])] = files[s(prop[4])]
    return out


def check_settings_page(page):
    """ft6_page.check_page, except that a component kind stock MainY5 lacks
    counts as stock 0 there: the settings page's lists add list / scrollEvent /
    drawScrollbar / toggleVisible budgets exactly as used (header - actual = 0)."""
    img, pool = P.stock_pool()
    old, new = P.P.page_shape(P.SL.set_bytes(P.BASE), pool), P.P.page_shape(page, pool)
    hn, ho = dict(new['header_minus_actual']), dict(old['header_minus_actual'])
    check(all(n >= o for n, o in zip(hn.pop('group_slots'), ho.pop('group_slots'))), 'group slots')
    for k in ('groups', 'clips', 'clip_properties', 'keys'):
        check(hn.pop(k) >= ho.pop(k), f'{k} budget below the page')
    cn, co = hn.pop('components'), ho.pop('components')
    check(set(co) <= set(cn), 'a stock component kind went')
    check(all(cn[k] == co.get(k, 0) for k in cn), f'components: {cn} vs stock {co}')
    check(hn == ho, f'allocation header: {hn} vs stock {ho}')
    check(not new['orphans'] and not new['bad_child_counts'],
          f"object graph: orphans {new['orphans']} child counts {new['bad_child_counts']}")
    schemas = P.P.load_schemas(img)
    for r in N.split(page):
        d = r.to_bytes()
        for off, kind in P.P.typed_fields(d, pool, schemas):
            v = u32(d, off)
            if kind == 'obj' and v not in (0, 0xFFFFFFFF) and v > 64:
                check(v in new['objects'], f'dangling object {v} in tag {r.tag:#x}')
        if r.tag == 0x10008:                   # typed_fields does not see the row template's ids
            for o in template_ids(d):
                v = u32(d, o)
                check(v in (0, 0xFFFFFFFF) or v in new['objects'], f'list template names missing object {v}')
    P.P.native_parse(page, pool.data, img)
    return new
