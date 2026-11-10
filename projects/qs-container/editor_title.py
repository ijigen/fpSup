#!/usr/bin/env python3
"""v0.3.6: a text title in the custom-QS editor's tile for a QSC_F_TITLE
function (RECIPE / MB/s / QR), instead of the borrowed menu_crop icon that made
them look like three more DC tiles (Bei, 2026-11-03, SS__3054-3056).

Per tile, in both editor pages (Y2_3C, Y2_3C_ShutterAngle), one new object
`String` under Icon01_CINE, beside `string` (its shape: objectBase, drawText, clip 2).
Live 2026-11-03 (SS__3066): under Icon01 (outside the group owner's subtree) the
group never played it -- the pair must name an object inside Icon01_CINE.

  * drawText from the name bar's (MenuText/Text: centred both ways), font 36,
    one line over the icon's area; visible;
  * clip 2, prop text: t=0 blank, t(49+i) = function i's label if it is a
    QSC_F_TITLE function, else blank (patched at collection: S_TITLE / S_BLANK);
  * played by the tile's own Icon01_CINE group (one more pair), so it follows
    MV_QSMENU_QSn exactly as the icon and the name-bar text do.

The icon of a QSC_F_TITLE function gets rect / size 0 (qsct.c sel_value), as
the QS page's tile already does.  Every stock id plays blank, so stock tiles
draw as before.

New edit kinds for the streaming copy (qsct.c qc_page), in stock coordinates:
  K_FRAG    insert `b` bytes from the block at offset `a` before stock `pos`
  K_FPATCH  write sel_value(sel, fi=b) at offset `a` of the last K_FRAG
  K_ADDC    add `b` to the word at stock `pos` (record sizes, counts, budget)

Budget (record 0, as qs_page_data.Design.header): objects, objectBase,
drawText, animationClip (+1 pair each), the group's pair count, one pair-props
entry (1) and one prop-keys entry (1 + MAX_FUNCS) per tile.  Icon01's child
count, the group's size and pair count.  No device I/O."""
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import editor_data as E               # noqa: E402
import qs_page_data as QP             # noqa: E402

K_FRAG, K_FPATCH, K_ADDC = 8, 9, 10
S_TITLE, S_BLANK = 7, 8
OBJ_BASE = 30000                      # Y2_3C's stock ids end at 11186
FONT = 36
POS = (0.0, 14.0)                     # in the tile: over the icon area (made relative to Icon01_CINE)
SIZE = (255.0, 70.0)
OBJ_NAME = 'String'


def _anchor_end(P, root):
    """End of the last record of `root`'s subtree, in stock order."""
    ids, grew = {root}, True
    while grew:
        grew = False
        for i, (_n, p) in P.objs.items():
            if p in ids and i not in ids:
                ids.add(i)
                grew = True
    last = 0
    for o, t, _s in P.recs:
        if (t == QP.T_OBJECT and E.be(P.data, o + 20) in ids) or \
                (t in QP.OWNER and E.be(P.data, o + QP.OWNER[t]) in ids):
            last = max(last, o)
    return last + P.at[last][1]


def tile_records(P, tile, k):
    """(fragment bytes, [(offset in fragment, sel, fi)]) and the object id."""
    icon01 = P.children(tile, 'Icon01')
    cine = P.children(icon01, 'Icon01_CINE')
    string = P.children(cine, 'string')
    oid = OBJ_BASE + k
    E.check(oid not in P.objs, f'object id {oid} is taken')
    obj = bytearray(P.rec(P.obj_rec[string]))
    E.check(struct.unpack_from('>3I', obj, 8) == (3, 0, 0), 'the string object is not local 3 / no groups / no children')
    struct.pack_into('>III', obj, 20, oid, cine, QP.pstr(OBJ_NAME))
    _c, cf = QP.fields(P.rec(P.records_of(cine, 'objectBase')[0]))
    cr = P.records_of(cine, 'objectBase')[0]
    cx, cy = struct.unpack_from('>ff', P.data, cr + cf['position'][0])
    base_donor = P.rec(P.records_of(string, 'objectBase')[0])
    ob = bytearray(QP.encode(base_donor, {'is-visible': struct.pack('>I', 1),
                                          'position': struct.pack('>ff', POS[0] - cx, POS[1] - cy),
                                          'size': struct.pack('>ff', *SIZE)}))
    struct.pack_into('>II', ob, 20, oid, 0)
    text_obj = P.children(P.named('MenuText'), 'Text')
    dt_donor = P.rec(P.records_of(text_obj, 'drawText')[0])
    dt = bytearray(QP.encode(dt_donor, {'font-size': struct.pack('>I', FONT),
                                        'rect': struct.pack('>4f', 0.0, 0.0, *SIZE)}))
    struct.pack_into('>II', dt, 20, oid, 1)
    _c, f = QP.fields(bytes(dt))
    text_at = f['text'][0]
    clip_donor = P.rec(P.clips[(string, 2)])
    sp = E.Clip(P.data, P.clips[(string, 2)]).prop('text', 0)
    keys = [(0, S_BLANK, 0)] + [(E.t_of(E.UI_BASE + i), S_TITLE, i) for i in range(E.MAX_FUNCS)]
    clip = bytearray(clip_donor[:28])
    struct.pack_into('>III', clip, 12, 1, 0xFFFFFFFF, oid)
    struct.pack_into('>I', clip, 24, 2)
    clip += struct.pack('>5I', len(keys), sp.kind, sp.c, QP.pstr('text'), 0)
    key_at = []
    for t, sel, fi in keys:
        key_at.append((len(clip) + 6, sel, fi))
        clip += QP.key_bytes(t, 0)
    struct.pack_into('>I', clip, 4, len(clip))
    frag = bytes(obj) + bytes(ob) + bytes(dt) + bytes(clip)
    o_dt = len(obj) + len(ob)
    o_clip = o_dt + len(dt)
    patches = [(o_dt + text_at, S_BLANK, 0)] + [(o_clip + a, sel, fi) for a, sel, fi in key_at]
    return frag, patches, oid, icon01, cine


def title_edits(name, mutate=None):
    """`mutate` (tests only): notitlehdr / notitlechild / notitlepair leave that part out.
    (edits as (pos, kind, sel, fi, a, b) with a = offset into `frags` for K_FRAG, frags bytes, notes)."""
    P = QP.Page(name=name)
    edits, frags = [], bytearray()
    added_groups = []
    for k in range(1, 9):
        tile = P.named(f'QS{k}C')
        frag, patches, oid, icon01, cine = tile_records(P, tile, k)
        g = P.groups_of(cine, 'Icon01_CINE')
        E.check(len(g) == 1, f'{name} QS{k}C: Icon01_CINE groups {len(g)}')
        g = g[0]
        # the pair, the group's pair count and size
        pair = struct.pack('>II', oid, 2)
        if mutate != 'notitlepair':
            edits.append((g['pairs_end'], K_FRAG, 0, 0xFF, len(frags), len(pair)))
            frags += pair
            edits.append((g['n_c_at'], K_ADDC, 0, 0xFF, 0, 1))
            edits.append((g['at'] + 4, K_ADDC, 0, 0xFF, 0, len(pair)))
            added_groups.append(g['at'])
        # Icon01_CINE gets a child
        if mutate != 'notitlechild':
            edits.append((P.obj_rec[cine] + 16, K_ADDC, 0, 0xFF, 0, 1))
        # the new records, after Icon01_CINE's subtree
        at = _anchor_end(P, cine)
        edits.append((at, K_FRAG, 0, 0xFF, len(frags), len(frag)))
        for off, sel, fi in patches:
            edits.append((at, K_FPATCH, sel, 0xFF, off, fi))
        frags += frag
    if mutate == 'notitlehdr':
        return edits, bytes(frags)
    # the allocation header (record 0)
    E.check(P.at[0][0] == 0x10002, f'{name}: record 0 is not the allocation header')
    from ui import rows as R
    h = P.rec(0)
    comps, arrays = R.header_layout(h)
    kinds = {E.pool_str(E.be(h, c - 4)): c for c in comps}
    n = 8
    edits.append((8, K_ADDC, 0, 0xFF, 0, n))                                   # objects
    for kind in ('objectBase', 'drawText', 'animationClip'):
        E.check(kind in kinds, f'{name}: header has no {kind}')
        edits.append((kinds[kind], K_ADDC, 0, 0xFF, 0, n))
    (c0, _e0, _w0), (c1, e1, _w1), (c2, e2, _w2), _a3 = arrays
    gi = {o: i for i, o in enumerate(P.groups)}
    for g_at in added_groups:
        edits.append((c0 + 4 + 12 * gi[g_at] + 8, K_ADDC, 0, 0xFF, 0, 1))
    a1 = struct.pack('>I', 1) * n                                               # props per new pair
    a2 = struct.pack('>I', 1 + E.MAX_FUNCS) * n                                 # keys per new prop
    edits.append((e1, K_FRAG, 0, 0xFF, len(frags), len(a1)))
    frags += a1
    edits.append((c1, K_ADDC, 0, 0xFF, 0, n))
    edits.append((e2, K_FRAG, 0, 0xFF, len(frags), len(a2)))
    frags += a2
    edits.append((c2, K_ADDC, 0, 0xFF, 0, n))
    edits.append((4, K_ADDC, 0, 0xFF, 0, len(a1) + len(a2)))                    # record 0's size
    return edits, bytes(frags)


RANK = {E.K_INS: 0, K_FRAG: 1, K_FPATCH: 1}


def merged(stock_edits, title, frag_base):
    """page_edits + title_edits in the order qc_page streams them: by stock
    position; at one position the key inserts, then each fragment followed by its
    patches, then the in-place edits.  K_FRAG's offset becomes a block offset."""
    t_edits, _frags = title
    seq = []
    for i, e in enumerate(stock_edits):
        seq.append((e[0], RANK.get(e[1], 2), 0, i, e))
    for i, e in enumerate(t_edits):
        if e[1] == K_FRAG:
            e = (e[0], e[1], e[2], e[3], e[4] + frag_base, e[5])
        seq.append((e[0], RANK.get(e[1], 2), 1, i, e))
    seq.sort(key=lambda x: x[:4])
    out = [x[4] for x in seq]
    width = {E.K_ADDF_N: 4, E.K_SET_END: 4, E.K_ADJ: 4, E.K_SETV: 4, E.K_SETFLAG: 2, E.K_DIGIT: 4, K_ADDC: 4}
    ins_at = sorted({e[0] for e in out if e[1] in (E.K_INS, K_FRAG)})
    for pos, kind, *_ in out:
        w = width.get(kind, 0)
        E.check(not any(pos < q < pos + w for q in ins_at), f'an edit at +0x{pos:X} straddles an insert')
    return out


if __name__ == '__main__':
    for p in E.PAGES:
        ed, fr = title_edits(p)
        print(p, len(ed), 'title edits,', len(fr), 'fragment bytes')
