#!/usr/bin/env python3
"""Stage 2: what the QS container changes in the stock Quick Set page QS_CINE
(GUI 159), worked out from the firmware image (Ver.5.02) at build time, plus
the playback model the tests judge it with.  No device I/O.

The QS page is data.  Every id-keyed behaviour is an animation played at
frame time t(ui) = ui * 100 // 3 by an event on the tile's variable
MV_QSMENU_QSn (Icon01 label, Icon02 value) or on QS_QSMode (the focused tile's
id, written by the tile's focusEvent): the dial's FR/FL/BR/BL key clips, the
AEL button's key clip, the footer.  In stock every one of those stops at UI 48:

  * the tiles' Icon01/Icon02 events have range-upperlimit 48.0;
  * DialKeyEvent's controlValue is -1..48;
  * every interval (Icon01_CINE, Icon02, FR, FL, BR, BL, Btn, Footer) ends at
    1600 = t(48).

So a tile holding UI 49+ is never applied: its frame stays where the PREVIOUS
tile left it.  That is the 2026-10-29 live bug (validation/2026-10-29-live
LOG.md D): focus FORMAT -> our tile -> dial changed FORMAT (its keyEvent 19
stayed enabled); RES -> our tile -> dial changed the resolution; our tiles
drew nothing; and the headphone keyEvent, which the key clips leave ON from
1600 on (no closing key), was never reached either (hp_blocks 0).

Our id space on this page (fixed, so the edits do not depend on N):
  UI 49..64  functions (internal 54..69, stage 1)
  UI 65..71  sub-item tiles of the open function (internal 70..76)
  UI 72      a blank tile (internal 77)

The edits (all through the C05E6400 record layer, qsct.c; stock coordinates):
  R1 every tile: Icon01 and Icon02 event range upper 48 -> 72
  R2 every id interval above ends at t(72)
  R3 DialKeyEvent controlValue max 48 -> 72
  K1 FR/FL/BR/BL/AEL key clips: at t(49) every stock keyEvent is OFF (the
     headphone's closing key) and a new keyEvent of ours is ON (49..72); the
     new keyEvent's one action is controlAppVariable(QSC_Key <- code):
     1 = +1, 2 = -1 (each object's stock direction), 5 = AEL
  K2 the other props of those groups and of Icon02 / Footer take, from t(49),
     the value they have at the neutral stock frame D (an id no CINE function
     uses, where nothing is enabled or visible)
  I1 every tile: Icon01 at t(49+i) = function i's borrowed look (runtime
     relocation); at 65..72 width 0 (no icon)
  I2 every tile: a new clip hides Icon02 (all stock value images) from t(49)
  T1 every tile: two drawText objects, label (QSC_Lk) and value (QSC_Vk),
     bound to private string variables the container posts; their colour
     follows the tile's 'Color' group (grey); a QSC_Gk event plays the tile's
     grey frame (the stock ActDeact form)
  T2 one object of ours: QS_QSMode in 49..72 -> 'Dial' ON (DialKeyEvent)
  H  the allocation header 0x10002: object/component counts, and budget for
     every added pair / prop / key (the arena is sized from these sums)

Every new record is copied from a QS_CINE record (fp-native-ui §8b: donors
from the same page)."""
import os
import pathlib
import struct
import sys
from fractions import Fraction

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / 'fpSup' / 'lossless' / 'menu'), str(ROOT / 'research/ui/tools/nbu_probe'),
                str(ROOT / 'fpSup' / 'uishare')]
import editor_data as E               # noqa: E402
import build_menu_candidate as BM     # noqa: E402
import nbu_format as NF               # noqa: E402

PAGE = 'QS_CINE'
UI_FN0, UI_SUB0, UI_BLANK = 49, 65, 72
UI_MAIN = UI_SUB0                # v0.2.1: the sub-QS's own function on tile 1 (any function)
UI_ITEM0 = UI_SUB0 + 1           # its sub-items 66..71
N_FN, N_SUB = 16, 6
UI_LAST = UI_BLANK
INT_SUB0, INT_BLANK = 70, 77
D_FRAME = 30                     # neutral: no CINE function uses UI 30 (Y2_3_CINE.cvm)
OBJ_BASE = 30000                 # our object ids (stock max 11686)
CODE_UP, CODE_DOWN, CODE_AEL, CODE_MENU = 1, 2, 5, 6
CODE_REAR = 2            # v0.2.2: the rear dial's codes are the front's + 2 (BL 3 = +1, BR 4 = -1)
MENU_BACK = os.environ.get('QSCT_MENU_BACK') == '1'   # v0.2.1's M (MENU returns from the sub-QS); off: live run 3
T_OBJECT, T_COMP, T_DRAW, T_EVENT, T_ACTION, T_CLIP, T_GROUP, T_CTRL = (
    0x10003, 0x10004, 0x10005, 0x10006, 0x10009, 0x1000A, 0x1000B, 0x1000E)
OWNER = {T_COMP: 20, T_DRAW: 20, T_EVENT: 24, T_ACTION: 20, T_CLIP: 20, T_CTRL: 20, T_GROUP: 24, 0x10007: 20,
         0x10008: 20}
LOCAL = {T_COMP: 24, T_DRAW: 24, T_EVENT: 28, T_CLIP: 24, T_CTRL: 24, 0x10007: 24, 0x10008: 24}
WIDTH = {0: 4, 1: 4, 2: 4, 3: 4, 4: 16, 5: 16, 6: 8, 7: 12, 8: 16, 9: 4, 10: 4, 11: 5, 12: 4, 13: 4, 14: 4}
# the footer option strip (v0.2.1): 15 slot positions on a 64 px grid, a slot 128 px wide, so n <= 7
# options are centred whatever n's parity (slot of option j = 8 - n + 2j); box child 15 = no box
N_SLOT, SLOT_GRID, SLOT_W, FOOT_H, BOX_NONE = 15, 64.0, 128.0, 74.0, 15
HINT_MORE, HINT_BACK = 1, 14     # QS_FooterGuid1: Footer14_K 'AEL Further Options', ours: Footer03_K 'MENU Back'
# private strings (the container's names; the record fields get their ids at boot)
NAMES = ['QSC_Key'] + [f'QSC_L{k}' for k in range(1, 9)] + [f'QSC_V{k}' for k in range(1, 9)] + \
        [f'QSC_G{k}' for k in range(1, 9)] + [f'QSC_S{k}' for k in range(1, 9)] + \
        [f'QSC_Y{k}' for k in range(1, 9)] + [f'QSC_FL{j}' for j in range(N_SLOT)] + \
        [f'QSC_FS{j}' for j in range(N_SLOT)] + [f'QSC_FY{j}' for j in range(N_SLOT)] + \
        [f'QSC_F{r}{j}' for r in 'GCNMPQR' for j in range(N_SLOT)] + ['QSC_FB', 'QSC_Arw'] + \
        [f'QSC_LW{k}' for k in range(1, 9)] + [f'QSC_SW{k}' for k in range(1, 9)]
S_KEY, S_L, S_V, S_G, S_S, S_Y = 0, 1, 9, 17, 25, 33
S_FL, S_FS, S_FY = 41, 41 + N_SLOT, 41 + 2 * N_SLOT
S_FG, S_FC, S_FN, S_FM = (41 + r * N_SLOT for r in range(3, 7))   # v0.2.2 roles
S_FP, S_FQ, S_FR = (41 + r * N_SLOT for r in range(7, 10))        # v0.2.3: centred labels (no second line)
S_FB, S_ARW = 41 + 10 * N_SLOT, 42 + 10 * N_SLOT
TEXT_ROLES = {'L': S_L, 'V': S_V, 'S': S_S, 'Y': S_Y}
S_LW = S_ARW + 1  # native QS LOCK image width: 0 hidden / 150 shown; append, preserve older variable ids
S_SW = S_LW + 8   # same asset in the small line: 0 hidden / 120 shown
INT_NAMES = {S_KEY, S_FB, S_ARW} | set(range(S_G, S_G + 8)) | set(range(S_LW, S_SW + 8))
# patch kinds (qsct.c P_*)
P_STR, P_LOOK = 1, 2
LOOK_IMAGE, LOOK_RECT, LOOK_SIZE, LOOK_POS = 0, 1, 2, 3
# op kinds (qsct.c Q_*)
Q_SET, Q_ADD, Q_INS, Q_APP = 1, 2, 3, 4
# a tile is 256 x 223: title / icon row, the big value, the small second line (stock FORMAT tile:
# title centre y 62, value 127, "12bit" 169 -- screenshots 2026-10-29 024040)
TEXT_RECT = {'L': (0.0, 38.0, 256.0, 48.0), 'V': (0.0, 96.0, 256.0, 62.0),
             'S': (24.0, 150.0, 208.0, 40.0), 'Y': (24.0, 150.0, 208.0, 40.0)}   # v0.2.2: clear of the arrows
TEXT_SIZE = {'L': 40, 'V': 54, 'S': 30, 'Y': 30}
# colour of the small lines: the tile's white/grey Color clip scaled (RGB) -- grey, and "approximate" yellow
TEXT_TINT = {'L': None, 'V': None, 'S': (0.62, 0.62, 0.62), 'Y': (0.94, 0.71, 0.30)}
TILE_SIZE = (256.0, 223.0)
TITLE_LOCK_IMAGE = 'menu_lock_qs'
TITLE_LOCK_RECT = (53.0, 42.0, 150.0, 74.0)  # exact native image bounds centred in a 256 px tile
SMALL_LOCK_RECT = (68.0, 147.0, 120.0, 59.2)  # 0.8 scale; opaque y 158.2..186.2 within the small row
FOOT_ROLES = ('FL', 'FS', 'FY', 'FG', 'FC', 'FN', 'FM', 'FP', 'FQ', 'FR')   # qsct.c N_FROLE order
# v0.2.3 (live run 4): an option without a second line (FPS, RES) sat in the top 42 px of the 74 px box like a
# two-line one, and the mark under it looked like a second line.  FP / FQ / FR: the same white / grey / yellow
# label centred in the box (the stock K spinner's height); the mark: a thin dotted line low in the box.
FOOT_RECT = {'FL': (0.0, 2.0, SLOT_W, 42.0), 'FS': (0.0, 42.0, SLOT_W, 30.0), 'FY': (0.0, 42.0, SLOT_W, 30.0),
             'FG': (0.0, 2.0, SLOT_W, 42.0), 'FC': (0.0, 2.0, SLOT_W, 42.0), 'FN': (0.0, 42.0, SLOT_W, 30.0),
             'FM': (0.0, 56.0, SLOT_W, 12.0),
             'FP': (0.0, 16.0, SLOT_W, 42.0), 'FQ': (0.0, 16.0, SLOT_W, 42.0), 'FR': (0.0, 16.0, SLOT_W, 42.0)}
FOOT_SIZE = {'FL': 34, 'FS': 24, 'FY': 24, 'FG': 34, 'FC': 34, 'FN': 24, 'FM': 12, 'FP': 34, 'FQ': 34, 'FR': 34}
# preview/dcres.html: grey #55595e, custom #ffd66b, the reason #8a6f3a, the mark in the focus colour #45b8e3
FOOT_COLOR = {'FL': 0xFFFFFFFF, 'FS': 0x9AA3ABFF, 'FY': 0xF0B44CFF, 'FG': 0x55595EFF, 'FC': 0xFFD66BFF,
              'FN': 0x8A6F3AFF, 'FM': 0x45B8E3FF, 'FP': 0xFFFFFFFF, 'FQ': 0x55595EFF, 'FR': 0xFFD66BFF}
MARK_TEXT = '. . . . . . . .'                  # v0.2.3: 12 px (was 16 px, six dots)
BOX_W = 120.0

check = E.check
DataError = E.DataError


def t_of(ui):
    return ui * 100 // 3


def be(d, o):
    return struct.unpack_from('>I', d, o)[0]


def f32(v):
    return struct.unpack('>I', struct.pack('>f', v))[0]


def unf32(w):
    return struct.unpack('>f', struct.pack('>I', w))[0]


_SCH = {}


def schemas():
    if not _SCH:
        _SCH.update(BM.load_property_schemas((ROOT / 'out/seg0_c0000000.bin').read_bytes()))
    return _SCH


def fields(rec):
    """{name: (offset, width, kind)} of a component/event/action record."""
    tag = be(rec, 0)
    comp = E.pool_str(be(rec, 8))
    cur = BM.MASK_OFFSETS[tag]
    out, mask = {}, 0
    for i, p in enumerate(schemas()[comp]):
        if i % 32 == 0:
            mask = be(rec, cur)
            out['_mask%d' % (i // 32)] = (cur, 4, None)
            cur += 4
        if (mask >> (i % 32)) & 1:
            out[p['name']] = (cur, WIDTH[p['kind']], p['kind'])
            cur += WIDTH[p['kind']]
    check(cur == len(rec), f'{comp}: fields end at {cur}, record is {len(rec)}')
    return comp, out


def encode(donor, values, drop=(), add=()):
    """A record like `donor` (same header words, same fields) with field
    values replaced (bytes, the field's width), `drop` fields removed and `add`
    (name -> bytes) fields added in schema order."""
    tag = be(donor, 0)
    comp, f = fields(donor)
    names = [p['name'] for p in schemas()[comp]]
    have = {n: donor[o:o + w] for n, (o, w, _k) in f.items() if not n.startswith('_')}
    for n in drop:
        have.pop(n)
    have.update(dict(add))
    have.update(values)
    body, mask, words = bytearray(), 0, []
    for i, n in enumerate(names):
        if i % 32 == 0 and i:
            words.append((mask, bytes(body)))
            body, mask = bytearray(), 0
        if n in have:
            k = schemas()[comp][i]['kind']
            check(len(have[n]) == WIDTH[k], f'{comp}.{n}: {len(have[n])} bytes, width {WIDTH[k]}')
            mask |= 1 << (i % 32)
            body += have[n]
    words.append((mask, bytes(body)))
    out = bytearray(donor[:BM.MASK_OFFSETS[tag]])
    for mask, b in words:
        out += struct.pack('>I', mask) + b
    struct.pack_into('>I', out, 4, len(out))
    return bytes(out)


def str5(off, flag=0):
    return struct.pack('>IB', off, flag)


class Page:
    """The stock QS_CINE records, indexed."""

    def __init__(self, data=None, name=PAGE):
        if data is None:
            self.addr, self.entry, data = E.page_bytes(name)
        self.data = bytes(data)
        self.recs = E.records(self.data)
        self.at = {o: (t, s) for o, t, s in self.recs}
        self.objs = {}
        self.obj_rec = {}
        for o, t, s in self.recs:
            if t == T_OBJECT:
                self.objs[be(self.data, o + 20)] = (E.pool_str(be(self.data, o + 28)), be(self.data, o + 24))
                self.obj_rec[be(self.data, o + 20)] = o
        self.clips, self.groups, self.by_owner = {}, [], {}
        for o, t, s in self.recs:
            if t in OWNER:
                self.by_owner.setdefault(be(self.data, o + OWNER[t]), []).append(o)
            if t == T_CLIP:
                self.clips[(be(self.data, o + 20), be(self.data, o + 24))] = o
            elif t == T_GROUP:
                self.groups.append(o)

    def rec(self, o):
        return self.data[o:o + self.at[o][1]]

    def comp(self, o):
        return E.pool_str(be(self.data, o + 8))

    def group(self, o):
        t, s = self.at[o]
        d = NF.decode_image_array(NF.Record(t, o, self.data[o + 8:o + s]), pool())
        n_a, n_b = be(self.data, o + 8), be(self.data, o + 12)
        cur = o + 28 + 21 * n_a
        for _ in range(n_b):
            cur += 9 + (4 if self.data[cur + 8] else 0)
        d['pairs_at'] = cur                      # first pair
        d['pairs_end'] = cur + 8 * len(d['pairs'])
        d['n_c_at'] = o + 16
        check(d['pairs_end'] + 8 == o + s, f'group at +0x{o:X}: tail not where expected')
        d['at'] = o
        return d

    def groups_of(self, owner, name=None):
        out = [self.group(o) for o in self.groups if be(self.data, o + 24) == owner]
        return [g for g in out if name is None or g['group'] == name]

    def clip(self, owner, cid):
        return E.Clip(self.data, self.clips[(owner, cid)])

    def children(self, parent, name):
        hits = [i for i, (n, p) in self.objs.items() if p == parent and n == name]
        check(len(hits) == 1, f'{len(hits)} children {name!r} of {parent}')
        return hits[0]

    def named(self, name, parent=None):
        hits = [i for i, (n, p) in self.objs.items() if n == name and (parent is None or p == parent)]
        check(len(hits) == 1, f'{len(hits)} objects {name!r}')
        return hits[0]

    def records_of(self, owner, comp=None, tag=None):
        return [o for o in self.by_owner.get(owner, []) if (tag is None or self.at[o][0] == tag)
                and (comp is None or (self.at[o][0] != T_CLIP and self.comp(o) == comp))]

    def local_max(self, owner):
        m = -1
        for o in self.by_owner.get(owner, []):
            t = self.at[o][0]
            if t in LOCAL:
                m = max(m, be(self.data, o + LOCAL[t]))
        return m

    def events(self, owner):
        """[(record offset, local id, instance name)] of an object's events."""
        return [(o, be(self.data, o + 28), E.pool_str(be(self.data, o + 20)))
                for o in self.records_of(owner, tag=T_EVENT)]

    def actions_of(self, owner, event_id):
        return [o for o in self.records_of(owner, tag=T_ACTION) if be(self.data, o + 24) == event_id]

    def field(self, o, name):
        _c, f = fields(self.rec(o))
        off, w, _k = f[name]
        return o + off, self.data[o + off:o + off + w]


_POOL = []


def pool():
    if not _POOL:
        img = E.O.image()
        _POOL.append(img[E.POOL - 0xC0000000:E.POOL - 0xC0000000 + E.POOL_LEN])
    return _POOL[0]


def pstr(text):
    return E.pool_offset(text)


# ---------------------------------------------------------------------------
class Edits:
    """Ops on stock records, in each record's own coordinates, and new records
    appended after an anchor record.  A patch is (where, kind, arg): `where` is
    ('stock', record, offset) or ('frag', fragment key, offset)."""

    def __init__(self, page):
        self.page = page
        self.ops = {}                         # record -> [(at, kind, a, frag)]
        self.after = {}                       # record -> [fragment bytes]
        self.patches = {}                     # record -> [(region, at, kind, arg)]
        self.frags = []

    def _o(self, rec):
        check(rec in self.page.at, f'+0x{rec:X} is not a record')
        return self.ops.setdefault(rec, [])

    def set(self, rec, at, value):
        self._o(rec).append((at, Q_SET, value & 0xFFFFFFFF, None))

    def add(self, rec, at, delta):
        self._o(rec).append((at, Q_ADD, delta & 0xFFFFFFFF, None))

    def ins(self, rec, at, data, patches=()):
        self._o(rec).append((at, Q_INS, 0, bytes(data)))
        idx = len(self._o(rec)) - 1
        for off, kind, arg in patches:
            self.patches.setdefault(rec, []).append((('ins', idx), off, kind, arg))

    def patch_stock(self, rec, at, kind, arg):
        self.patches.setdefault(rec, []).append((('stock',), at, kind, arg))

    def append(self, rec, data, patches=()):
        self._o(rec)
        lst = self.after.setdefault(rec, [])
        lst.append(bytes(data))
        for off, kind, arg in patches:
            self.patches.setdefault(rec, []).append((('after', len(lst) - 1), off, kind, arg))

    def build(self, rec):
        """(output bytes with patch fields as they stand, [(out offset, kind, arg)])."""
        stock = self.page.rec(rec)
        ops = sorted(enumerate(self.ops.get(rec, [])), key=lambda x: (x[1][0], 0 if x[1][1] == Q_INS else 1, x[0]))
        out, pos, ins_at = bytearray(), 0, {}
        cur = bytearray(stock)
        # SET/ADD act on the stock bytes; INS splice in at stock offsets
        for _i, (at, kind, a, _f) in ops:
            if kind == Q_SET:
                struct.pack_into('>I', cur, at, a)
            elif kind == Q_ADD:
                struct.pack_into('>I', cur, at, (be(cur, at) + a) & 0xFFFFFFFF)
        grow = 0
        for i, (at, kind, a, frag) in ops:
            if kind != Q_INS:
                continue
            out += cur[pos:at]
            pos = at
            ins_at[i] = len(out)
            out += frag
            grow += len(frag)
        out += cur[pos:]
        struct.pack_into('>I', out, 4, len(stock) + grow)
        after_at = []
        for frag in self.after.get(rec, []):
            after_at.append(len(out))
            out += frag

        def stock_to_out(at):
            return at + sum(len(f) for _i, (a, k, _v, f) in ops if k == Q_INS and a <= at)
        patches = []
        for region, off, kind, arg in self.patches.get(rec, []):
            if region[0] == 'stock':
                o = stock_to_out(off)
            elif region[0] == 'ins':
                o = ins_at[region[1]] + off
            else:
                o = after_at[region[1]] + off
            patches.append((o, kind, arg))
        return bytes(out), sorted(patches)

    def targets(self):
        return sorted(set(self.ops) | set(self.after))


# ---------------------------------------------------------------------------
def prop_value_at(p, t):
    """Playback (editor_data.Prop) incl. a time before the first key (= its value)."""
    if p.keys and t < p.keys[0][2]:
        k = p.keys[0]
        return unf32(k[3]) if p.kind == 1 else k[3]
    return p.value_at(t)


def key_bytes(t, value, flag=0):
    return struct.pack('>HII', flag, t, value)


def keys_after(p, wants):
    """Keys to append to prop `p` so that from t(49) on it holds `wants`:
    [(ui, raw value or None=reloc)], ascending ui.  A key is added only where
    the held value changes (relocated values always)."""
    check(all(k[2] <= t_of(48) for k in p.keys), f'prop {p.name}: a key after t(48)')
    held = p.keys[-1][3] if p.keys else None
    out = []
    for ui, v, reloc in wants:
        if reloc is not None or v != held:
            out.append((ui, v if v is not None else 0, reloc))
            held = v if reloc is None else None
    return out


def raw_at(p, t):
    """The raw word a prop holds at t (float props: interpolated, re-encoded)."""
    v = prop_value_at(p, t)
    return f32(v) if p.kind == 1 else v


RECIPE = ROOT / 'fpSup' / 'uishare' / 'ui' / 'qs_recipe.json'


def shared_recipe_records(page):
    """The QS_CINE records uishare's QS recipe (res-custom's record layer) edits,
    as page offsets: the container leaves them alone."""
    import json
    d = json.loads(RECIPE.read_text())
    return {int(r['address'], 16) - page.addr for r in d['records'] if r['set'] == PAGE}


MUTATIONS = (
    'lockright','menuswitch', 'nohint', 'notrigger', 'nomenu', 'menuopen', 'nocursoroff', 'nostrip', 'noclose', 'norange', 'nodialmax', 'nointerval', 'noourkey', 'nohide', 'nobind', 'noheader',
             'nodialon', 'aelcode', 'nolook', 'footershared', 'footertop', 'fatmark')


class Design:
    """Everything stage 2 adds, computed once from the stock page.  `mutate`
    (tests only) leaves one edit out (MUTATIONS)."""

    def __init__(self, page=None, mutate=None):
        check(mutate is None or mutate in MUTATIONS, f'unknown mutation {mutate}')
        self.mutate = mutate
        self.page = P = page or Page()
        self.ed = Edits(P)
        self.added = {'objects': 0, 'kinds': {}, 'pairs': [], 'props': [], 'keys': 0}
        self.tiles = []
        self.notes = {}
        self.root = P.named('Root')
        for k in range(1, 9):
            tile = P.named(f'QS_CINE{k}')
            self.tiles.append(dict(k=k, tile=tile, icon01=P.children(tile, 'Icon01'),
                                   icon02=P.children(tile, 'Icon02')))
        self.dial = P.named('DialKeyEvent')
        self.dirs = {n: P.children(self.dial, n) for n in ('FR', 'FL', 'BR', 'BL')}
        self.button = P.named('Button', self.root)
        self.ael = P.children(self.button, 'AEL')
        self.qsmode = P.named('QSMode')
        self._ids = iter(range(OBJ_BASE, OBJ_BASE + 256))
        self.make()

    # -- bookkeeping -------------------------------------------------------
    def kind(self, name, n=1):
        self.added['kinds'][name] = self.added['kinds'].get(name, 0) + n

    def new_pair(self, group, clip_props):
        """A pair added to `group`: the header gets its budget."""
        self.added['pairs'].append((group['at'], [p for p in clip_props]))

    def budget_keys(self, group_at, n_keys):
        """Keys added to existing props of a clip in `group_at`: one budget pair."""
        if n_keys:
            self.added['pairs'].append((group_at, [n_keys]))

    # -- the edits -----------------------------------------------------------
    def make(self):
        P, ed = self.page, self.ed
        # R3: the dial's range
        cv = P.records_of(self.dial, 'controlValue')
        check(len(cv) == 1, 'DialKeyEvent controlValue')
        at, old = P.field(cv[0], 'max-value')
        check(old == struct.pack('>f', 48.0) and P.field(cv[0], 'min-value')[1] == struct.pack('>f', -1.0),
              'DialKeyEvent is not -1..48')
        if self.mutate != 'nodialmax':
            ed.set(cv[0], at - cv[0], f32(float(UI_LAST)))
        self.notes['dial_range'] = cv[0]
        # D must be neutral in every group we make hold it
        self.id_groups = []
        for t in self.tiles:
            self.tile_edits(t)
        for n, o in self.dirs.items():
            self.key_object(o, n)
        self.key_object(self.ael, 'AEL')
        self.footer()
        if self.mutate != 'nostrip':
            self.footer_strip()
        if self.mutate != 'nohint':
            self.hint_back()
        if self.mutate != 'nodialon':
            self.dial_on()
        if self.mutate != 'noheader':
            self.header()
        self.check_neutral()

    def check_neutral(self):
        """D must be a frame where every group we make hold it shows and enables
        nothing (is-visible / type all 0)."""
        P = self.page
        t = Fraction(D_FRAME * 100, 3)
        for g_at in self.id_groups:
            for ob, cid in P.group(g_at)['pairs']:
                for p in P.clip(ob, cid).props:
                    if p.name in ('is-visible', 'type'):
                        check(not prop_value_at(p, t), f'D={D_FRAME} is not neutral: {ob}/{cid} {p.name}')

    def interval(self, g):
        """R2: the group's (single) interval ends at t(72)."""
        check(len(g['entries']) == 1 and g['entries'][0]['a'] == 0 and g['entries'][0]['b'] == 1600,
              f"group {g['group']}: not one interval 0..1600")
        if not (self.mutate == 'nointerval' and g['group'] in ('FR', 'FL', 'BR', 'BL', 'Btn')):
            self.ed.set(g['at'], 36, t_of(UI_LAST))
        self.id_groups.append(g['at'])

    def range_event(self, owner, var):
        P = self.page
        hits = [o for o, _lid, _n in P.events(owner)
                if P.comp(o) == 'appVariableChangeEvent' and E.pool_str(be(P.data, P.field(o, 'variable-name')[0])) == var]
        check(len(hits) == 1, f'{owner}: {len(hits)} events on {var}')
        at, old = P.field(hits[0], 'range-upperlimit-value')
        check(old == struct.pack('>f', 48.0), f'{owner}: range upper is not 48')
        if self.mutate != 'norange':
            self.ed.set(hits[0], at - hits[0], f32(float(UI_LAST)))
        return hits[0]

    def hold_from_d(self, g, override=None, skip=()):
        """K2: every prop of every pair clip of group g takes its value at
        t(D) from t(49) on (override(prop) -> raw value or None = the D rule)."""
        P = self.page
        t_d = Fraction(D_FRAME * 100, 3)
        for ob, cid in g['pairs']:
            if (ob, cid) in skip:
                continue
            c = P.clip(ob, cid)
            added = 0
            for p in c.props:
                v = override(ob, cid, p) if override else None
                if v is None:
                    v = raw_at(p, t_d)
                ks = keys_after(p, [(UI_FN0, v, None)])
                if ks:
                    self.ed.ins(c.at, p.end - c.at, b''.join(key_bytes(t_of(u), x) for u, x, _r in ks))
                    self.ed.add(c.at, p.at - c.at, len(ks))
                    added += len(ks)
            if added:
                self.budget_keys(g['at'], added)

    def tile_edits(self, t):
        P, ed = self.page, self.ed
        k = t['k']
        var = f'MV_QSMENU_QS{k}'
        # R1
        self.range_event(t['icon01'], var)
        self.range_event(t['icon02'], var)
        # R2 + I1: Icon01 (its one group, one clip)
        g1, = P.groups_of(t['icon01'], 'Icon01_CINE')
        self.interval(g1)
        (ob, cid), = g1['pairs']
        c = P.clip(ob, cid)
        added = 0
        for p in c.props:
            sel = {('image', 0): LOOK_IMAGE, ('rect', 2): LOOK_RECT, ('size', 0): LOOK_SIZE,
                   ('position', 0): LOOK_POS}[(p.name, p.dim)]
            keys = [(UI_FN0 + i, 0, (P_LOOK, i << 2 | sel)) for i in range(N_FN if self.mutate != 'nolook' else 0)]
            if sel in (LOOK_RECT, LOOK_SIZE):
                keys.append((UI_SUB0, f32(0.0), None))       # no icon on sub-item / blank tiles
            frag, patches = bytearray(), []
            for ui, v, reloc in keys:
                if reloc:
                    patches.append((len(frag) + 6, reloc[0], reloc[1]))
                frag += key_bytes(t_of(ui), v)
            ed.ins(c.at, p.end - c.at, frag, patches)
            ed.add(c.at, p.at - c.at, len(keys))
            added += len(keys)
        self.budget_keys(g1['at'], added)
        # R2 + K2 + I2: Icon02
        g2, = P.groups_of(t['icon02'], 'Icon02')
        self.interval(g2)
        self.hold_from_d(g2)
        cid = P.local_max(t['icon02']) + 1
        hide = self.clip_record(t['icon02'], cid, [('is-visible', 0, 0, 0, [(0, 1), (t_of(UI_FN0), 0)])])
        if self.mutate != 'nohide':
            self.pair(g2, t['icon02'], cid, [2])
        self.notes.setdefault('hide', []).append((t['icon02'], cid))
        # T1: title, value and the two small lines (grey / approximate), appended after the tile's last record
        anchor = self.tile_anchor(t['tile'])
        frags = [(hide, [])]
        gc, = P.groups_of(t['tile'], 'Color')
        color = P.clip(*gc['pairs'][0])
        check(gc['pairs'][0][0] == t['icon01'] and all(p.name == 'color' for p in color.props), 'Color group')
        t['texts'] = {}
        for role in ('L', 'V', 'S', 'Y'):
            oid = next(self._ids)
            t['texts'][role] = oid
            recs = self.text_object(oid, t['tile'], role, k, color)
            frags += recs
            self.pair(gc, oid, 3, [p.count for p in color.props])
        t['lock_image'] = next(self._ids)
        frags += self.title_lock_object(t['lock_image'], t['tile'], k, color)
        self.pair(gc, t['lock_image'], 3, [p.count for p in color.props])
        t['small_lock_image'] = next(self._ids)
        frags += self.title_lock_object(t['small_lock_image'], t['tile'], k, color, small=True)
        self.pair(gc, t['small_lock_image'], 3, [p.count for p in color.props])
        for data, patches in frags:
            ed.append(anchor, data, patches)
        ed.add(P.obj_rec[t['tile']], 16, 6)                   # four text children, title / small lock images
        ed.add(P.obj_rec[t['icon02']], 8, 1)                  # one more clip
        t['anchor'] = anchor
        if (self.mutate != 'nomenu' and MENU_BACK) or self.mutate == 'menuswitch':
            self.tile_menu(t, g1)

    def tile_menu(self, t, g1):
        """MENU in the sub-QS (UI 65..72): the tile's stock 'Menu' keyEvent (closes QS) is off there and
        a keyEvent of ours is on, writing QSC_Key = 6 (the container closes the sub-QS).  The clip that
        switches them (their 'type', as the tile's 'Lock' clip does for the arrow keys) is a pair of the
        tile's Icon01_CINE group, so it follows the tile's id (MV_QSMENU_QSn) like the icon."""
        P, ed = self.page, self.ed
        tile = t['tile']
        evs = {n: (o, l) for o, l, n in P.events(tile) if P.comp(o) == 'keyEvent'}
        menu_o, menu_l = evs['Menu']
        check(P.field(menu_o, 'type')[1] == struct.pack('>I', 2), 'tile Menu keyEvent is not type 2')
        acts = P.actions_of(tile, menu_l)
        lid = P.local_max(tile) + 1
        cid = lid + 1
        kev = bytearray(P.rec(menu_o))
        struct.pack_into('>IIII', kev, 16, 1, 0, tile, lid)
        cav_o = [o for o in P.records_of(self.ael, 'controlAppVariable')
                 if E.pool_str(be(P.data, P.field(o, 'destination-variable')[0])) == 'CM_TransitionFlag'][0]
        cav = bytearray(encode(P.rec(cav_o), {'destination-variable': str5(0, 0),
                                              'value': str5(pstr(str(CODE_MENU)), 0)}))
        struct.pack_into('>III', cav, 20, tile, lid, 1)
        _c, cf = fields(bytes(cav))
        _c, kf = fields(bytes(kev))
        off_key = (0, 2) if self.mutate == 'menuopen' else (t_of(UI_SUB0), 0)
        clip = self.clip_record(tile, cid, [('type', 0, 0, menu_l, [(0, 2), off_key]),
                                            ('type', 0, 0, lid, [(0, 0), (t_of(UI_SUB0), 2)])])
        anchor = max([menu_o] + acts)
        ed.append(anchor, bytes(kev), [(20, P_STR, S_KEY)])
        ed.append(anchor, bytes(cav), [(cf['destination-variable'][0], P_STR, S_KEY)])
        ed.append(anchor, clip)
        ed.add(P.obj_rec[tile], 8, 2)                          # a keyEvent and a clip
        self.pair(g1, tile, cid, [2, 2])
        self.kind('keyEvent'); self.kind('controlAppVariable')
        self.notes.setdefault('menu', []).append((tile, menu_l, lid, cid))

    def tile_anchor(self, tile):
        """The last record of the tile's subtree (stock order)."""
        P = self.page
        ids = {tile}
        grew = True
        while grew:
            grew = False
            for i, (_n, p) in P.objs.items():
                if p in ids and i not in ids:
                    ids.add(i)
                    grew = True
        last = 0
        for o, t, s in P.recs:
            if t == T_OBJECT and be(P.data, o + 20) in ids:
                last = max(last, o)
            elif t in OWNER and be(P.data, o + OWNER[t]) in ids:
                last = max(last, o)
        return last

    def pair(self, g, owner, cid, prop_keys):
        P, ed = self.page, self.ed
        ed.ins(g['at'], g['pairs_end'] - g['at'], struct.pack('>II', owner, cid))
        ed.add(g['at'], 16, 1)
        self.added['pairs'].append((g['at'], list(prop_keys)))

    def clip_record(self, owner, cid, props, donor=None):
        """A clip record: props = [(name, dim, kind, c, [(t, raw)])]."""
        P = self.page
        donor = donor or P.rec(P.clips[(self.tiles[0]['icon01'], 48)])
        out = bytearray(donor[:28])
        struct.pack_into('>III', out, 12, len(props), 0xFFFFFFFF, owner)
        struct.pack_into('>I', out, 24, cid)
        for name, dim, kind, c, keys in props:
            out += struct.pack('>5I', len(keys), kind, c, pstr(name), dim)
            for tt, v in keys:
                out += key_bytes(tt, v)
        struct.pack_into('>I', out, 4, len(out))
        return bytes(out)

    def obj_record(self, oid, parent, name, n_local):
        t1 = self.tiles[0]
        obj = bytearray(self.page.rec(self.page.obj_rec[t1['icon02']]))
        struct.pack_into('>IIIIII', obj, 8, n_local, 0, 0, oid, parent, pstr(name))
        return obj

    def base_record(self, oid, size, pos=None):
        P = self.page
        base_donor = P.rec(P.records_of(self.tiles[0]['icon02'], 'objectBase')[0])
        add = [('position', struct.pack('>ff', *pos))] if pos is not None else []
        ob = bytearray(encode(base_donor, {'size': struct.pack('>ff', *size)}, add=add))
        struct.pack_into('>II', ob, 20, oid, 0)
        return bytes(ob)

    def text_records(self, oid, rect, size, var, color=None):
        """drawText (local 1, LockMessage's) bound to private string `var` (appVariableEvent local 2,
        48_EXCL_HeadphoneVolume's, component-id 1, property 'text')."""
        P = self.page
        lock = P.named('LockMessage')
        dt_donor = P.rec(P.records_of(lock, 'drawText')[0])
        vals = {'text': str5(0, 0), 'rect': struct.pack('>4f', *rect), 'font-size': struct.pack('>I', size)}
        dt = bytearray(encode(dt_donor, vals, add=[('color', struct.pack('>I', color))] if color is not None else ()))
        struct.pack_into('>II', dt, 20, oid, 1)
        t1 = self.tiles[0]
        hp = P.named('48_EXCL_HeadphoneVolume', P.children(t1['icon02'], 'QSMENU'))
        bind_donor = P.rec([o for o, _l, _n in P.events(hp) if P.comp(o) == 'appVariableEvent'][0])
        bind = bytearray(encode(bind_donor, {'variable-name': str5(0, 0),
                                             'component-id': struct.pack('>I', 0 if self.mutate == 'nobind' else 1),
                                             'property-name': str5(pstr('text'), 0)}))
        struct.pack_into('>III', bind, 16, 0, 0xFFFFFFFF, oid)
        struct.pack_into('>I', bind, 28, 2)
        _c, bf = fields(bytes(bind))
        self.kind('drawText'); self.kind('appVariableEvent')
        return [(bytes(dt), []), (bytes(bind), [(bf['variable-name'][0], P_STR, var)])]

    def text_object(self, oid, tile, role, k, color):
        """A drawText object bound to QSC_<role>k, its colour clip (the tile's Color clip, tinted for the
        small lines), the grey event (title) and, on the value object, a second trigger of the Icon02
        animation.  Donors: Icon02's object and objectBase, LockMessage's drawText,
        48_EXCL_HeadphoneVolume's component-bound appVariableEvent, the tile's ActDeact00 event+action,
        Icon02's own MV_QSMENU_QSn event + action."""
        P = self.page
        t1 = self.tiles[0]
        extra = role in ('L', 'V')
        n_local = 5 if extra else 4
        obj = self.obj_record(oid, tile, 'String', n_local)
        ob = self.base_record(oid, TILE_SIZE)
        var = TEXT_ROLES[role] + k - 1
        recs = [(bytes(obj), []), (ob, [])] + self.text_records(oid, TEXT_RECT[role], TEXT_SIZE[role], var)
        tint = TEXT_TINT[role]

        def keys(p):
            out = []
            for kk in p.keys:
                v = kk[3]
                if tint and p.dim < 3:
                    v = f32(unf32(v) * tint[p.dim])
                out.append((kk[2], v))
            return out
        cc = self.clip_record(oid, 3, [(p.name, p.dim, p.kind, 1, keys(p)) for p in color.props],
                              donor=P.rec(color.at))
        recs.append((cc, []))
        self.kind('objectBase')
        self.added['objects'] += 1
        if role == 'L':
            mode = P.named('QSMENU', t1['icon02'])
            ev_o = [o for o, _l, n in P.events(mode) if n == 'ActDeact00'][0]
            act_o = P.actions_of(mode, be(P.data, ev_o + 28))
            check(len(act_o) == 1, 'ActDeact00 has one action')
            ev = bytearray(encode(P.rec(ev_o), {'variable-name': str5(0, 0)}))
            struct.pack_into('>IIII', ev, 16, 1, 0xFFFFFFFF, oid, 4)
            act = bytearray(encode(P.rec(act_o[0]), {'animationset-owner': struct.pack('>I', tile),
                                                     'apply-frame': str5(0, 0)}))
            struct.pack_into('>III', act, 20, oid, 4, 1)
            g = S_G + k - 1
            _c, ef = fields(bytes(ev))
            _c, af = fields(bytes(act))
            recs += [(bytes(ev), [(ef['variable-name'][0], P_STR, g)]),
                     (bytes(act), [(af['apply-frame'][0], P_STR, g)])]
            self.kind('appVariableChangeEvent'); self.kind('controlAnimation')
        elif role == 'V':
            recs += self.icon02_trigger(oid, k)
        return recs

    def title_lock_object(self, oid, tile, k, color, small=False):
        """Native image with an explicit centred rect. SS__2900 shows inline images begin
        at the text centre instead of subtracting half the image width. Keep the object
        visible so its variable binding keeps receiving updates; zero rect width hides it,
        as the stock Icon01 animation already does for the submenu/blank tiles.
        Donors are all QS_CINE: Icon01 drawImage, Icon02 base, headphone binding.
        """
        P = self.page
        donor = P.rec(P.records_of(self.tiles[0]['icon01'], 'drawImage')[0])
        x, y, w, h = SMALL_LOCK_RECT if small else TITLE_LOCK_RECT
        if self.mutate == 'lockright': x = TILE_SIZE[0] / 2  # SS__2900 old inline origin
        image = bytearray(encode(donor, {'image': struct.pack('>I', pstr(TITLE_LOCK_IMAGE)),
                                        'rect': struct.pack('>4f', x, y, 0.0, h)}))
        struct.pack_into('>II', image, 20, oid, 1)
        hp = P.named('48_EXCL_HeadphoneVolume', P.children(self.tiles[0]['icon02'], 'QSMENU'))
        bd = P.rec([o for o, _l, _n in P.events(hp) if P.comp(o) == 'appVariableEvent'][0])
        bind = bytearray(encode(bd, {'variable-name': str5(0, 0),
                                    'component-id': struct.pack('>I', 1),
                                    'property-name': str5(pstr('rect'), 0)},
                               add=[('property-subindex', struct.pack('>I', 2))]))
        struct.pack_into('>IIII', bind, 16, 0, 0xFFFFFFFF, oid, 2)
        bf = fields(bytes(bind))[1]
        clip = self.clip_record(oid, 3, [(p.name, p.dim, p.kind, 1,
                                          [(kk[2], kk[3]) for kk in p.keys]) for p in color.props],
                                donor=P.rec(color.at))
        self.kind('objectBase'); self.kind('drawImage'); self.kind('appVariableEvent')
        self.added['objects'] += 1
        return [(bytes(self.obj_record(oid, tile, 'Icon', 4)), []),
                (self.base_record(oid, TILE_SIZE), []), (bytes(image), []),
                (bytes(bind), [(bf['variable-name'][0], P_STR, (S_SW if small else S_LW) + k - 1)]), (clip, [])]

    def icon02_trigger(self, oid, k):
        """Fix 1 (2026-10-29 step 11): Icon02 is hidden on our ids by its own is-visible, and an
        invisible object's events do not fire -- so after the sub-QS the stock tile's MV_QSMENU_QSn
        change never reached Icon02's event and the stock values stayed hidden.  The same event and
        action on the value text object (never hidden) plays the Icon02 animation as well."""
        P = self.page
        t = self.tiles[k - 1]
        var = f'MV_QSMENU_QS{k}'
        ev_o = [o for o, _l, _n in P.events(t['icon02'])
                if P.comp(o) == 'appVariableChangeEvent'
                and E.pool_str(be(P.data, P.field(o, 'variable-name')[0])) == var][0]
        act_o, = P.actions_of(t['icon02'], be(P.data, ev_o + 28))
        av = fields(P.rec(act_o))[1]
        check(be(P.data, act_o + av['animationset-owner'][0]) == t['icon02'], 'Icon02 action owner')
        ev = bytearray(encode(P.rec(ev_o), {'range-upperlimit-value': struct.pack('>f', float(UI_LAST))}))
        struct.pack_into('>IIII', ev, 16, 1, 0xFFFFFFFF, oid, 4)
        act = bytearray(P.rec(act_o))
        struct.pack_into('>III', act, 20, oid, 4, 1)
        self.kind('appVariableChangeEvent'); self.kind('controlAnimation')
        self.notes.setdefault('icon02_trigger', []).append(oid)
        if self.mutate == 'notrigger':
            struct.pack_into('>I', ev, fields(bytes(ev))[1]['variable-name'][0], pstr('QS_QSMode'))
        return [(bytes(ev), []), (bytes(act), [])]

    def key_object(self, obj, name):
        """K1: one keyEvent of ours in FR/FL/BR/BL/AEL, ON from t(49); every
        stock keyEvent OFF there (the closing keys); the group's other props
        hold D's value."""
        P, ed = self.page, self.ed
        g = P.groups_of(self.button, 'Btn') if name == 'AEL' else P.groups_of(obj, name)
        check(len(g) == 1, f'{name}: its id group')
        g = g[0]
        self.interval(g)
        kc = [(ob, cid) for ob, cid in g['pairs'] if ob == obj]
        check(len(kc) == 1, f'{name}: key clip')
        clip = P.clip(*kc[0])
        check(all(p.name == 'keys' for p in clip.props), f'{name}: not a keys clip')
        # every stock key event OFF from t(49)
        if self.mutate == 'noclose':
            self.hold_from_d(g, skip=[(ob, cid) for ob, cid in g['pairs'] if ob == obj])
        else:
            self.hold_from_d(g, override=lambda ob, cid, p: 0 if ob == obj else None)
        lid = P.local_max(obj) + 1
        self.notes.setdefault('keys', {})[name] = (obj, lid, kc[0])
        # our prop at the end of the key clip
        prop = struct.pack('>5I', 2, 0, lid, pstr('keys'), 0) + key_bytes(0, 0) + \
            key_bytes(t_of(UI_FN0), 0 if self.mutate == 'noourkey' else 1)
        ed.ins(clip.at, clip.size, prop)
        ed.add(clip.at, 12, 1)
        self.added['pairs'].append((g['at'], [2]))           # budget: one prop of 2 keys
        # the keyEvent (a copy of this object's last one) and its one action
        evs = [(o, l, n) for o, l, n in P.events(obj) if P.comp(o) == 'keyEvent']
        donor_o, _l, donor_n = evs[-1]
        acts = P.actions_of(obj, _l)
        anchor = max([donor_o] + acts)
        if name == 'AEL':
            code = CODE_UP if self.mutate == 'aelcode' else CODE_AEL
        else:
            formula = [E.pool_str(be(P.data, P.field(a, 'formula')[0])) for a in acts if P.comp(a) == 'changePropertyByControl']
            check(formula in (['dst + 1'], ['dst - 1']), f'{name}: donor formula {formula}')
            code = (CODE_UP if formula == ['dst + 1'] else CODE_DOWN) + (CODE_REAR if name in ('BR', 'BL') else 0)
        self.notes.setdefault('codes', {})[name] = code
        kev = bytearray(P.rec(donor_o))
        struct.pack_into('>IIII', kev, 16, 1, 0, obj, lid)            # one action, instance name patched
        cav_o = [o for o in P.records_of(self.ael, 'controlAppVariable')
                 if E.pool_str(be(P.data, P.field(o, 'destination-variable')[0])) == 'CM_TransitionFlag'][0]
        cav = bytearray(encode(P.rec(cav_o), {'destination-variable': str5(0, 0),
                                              'value': str5(pstr(str(code)), 0)}))
        struct.pack_into('>III', cav, 20, obj, lid, 1)
        _c, cf = fields(bytes(cav))
        ed.append(anchor, bytes(kev), [(20, P_STR, S_KEY)])
        ed.append(anchor, bytes(cav), [(cf['destination-variable'][0], P_STR, S_KEY)])
        ed.add(P.obj_rec[obj], 8, 1)
        self.kind('keyEvent'); self.kind('controlAppVariable')

    def footer(self):
        """The footer holds D from t(49) -- except the clips the shared QS recipe
        (uishare/res-custom's record layer) edits: a record both layers serve
        would lose one layer's edit (each passes another layer's copy)."""
        g, = self.page.groups_of(self.qsmode, 'Footer')
        self.interval(g)
        theirs = shared_recipe_records(self.page) if self.mutate != 'footershared' else set()
        skip = [pr for pr in g['pairs'] if pr in self.page.clips and self.page.clips[pr] in theirs]
        self.notes['footer_skipped'] = len(skip)
        self.hold_from_d(g, skip=skip)

    def hint_back(self):
        """The hint in the sub-QS (Bei 10-29: stock strings only): the footer hint 'Option' shows the
        stock text of frame QS_FooterGuid1 (1 = Footer14_K 'AEL Further Options').  Frame HINT_BACK
        (14) gets the stock key Footer03_K ('MENU Back', the editor footer's), and the interval ends there."""
        P, ed = self.page, self.ed
        opt = P.named('Option')
        g, = P.groups_of(opt, 'Option')
        check(len(g['entries']) == 1 and g['entries'][0]['a'] == 0 and g['entries'][0]['b'] == t_of(HINT_BACK - 1),
              'Option interval')
        (ob, cid), = [p for p in g['pairs'] if p[0] == opt]
        c = P.clip(ob, cid)
        p, = c.props
        check(p.name == 'text' and p.keys[-1][2] == t_of(HINT_BACK - 1), 'Option text clip')
        ed.ins(c.at, p.end - c.at, key_bytes(t_of(HINT_BACK), pstr('Footer03_K')))
        ed.add(c.at, p.at - c.at, 1)
        self.budget_keys(g['at'], 1)
        ed.set(g['at'], 36, t_of(HINT_BACK))
        self.notes['hint'] = (opt, cid, HINT_BACK)

    def footer_strip(self):
        """Fix 2/3: the option strip of our functions, the stock footer's cursor and the dial arrows.
        One object of ours under QSMode (where the stock footer holders live, so the holders' actions
        resolve the same way): its events -- QS_QSMode in 49..72 -> 'Cursor' OFF (the empty stock box);
        QSC_Arw == 1 / == 0 -> Root 'Arrow' ON / OFF (the container posts it per function: arrows only
        with adjust).  Its children: N_SLOT label / small / approximate-small drawTexts on a 64 px grid
        (QSC_FL/FS/FY<j>), and a toggleVisible (48_EXCL_HeadphoneVolume's form) whose child QSC_FB is
        visible: boxes 0..14 (the stock cursor's drawRect) at the slots, 15 = none."""
        P, ed = self.page, self.ed
        qsmode = self.qsmode
        holder = P.named('19', qsmode)
        greater = [o for o, _l, _n in P.events(holder) if P.comp(o) == 'appVariableChangeEvent'
                   and 'greater-than-value' in fields(P.rec(o))[1]]
        check(len(greater) == 1, 'holder 19: one greater-than event')
        off_acts = P.actions_of(holder, be(P.data, greater[0] + 28))
        names = [E.pool_str(be(P.data, P.field(a, 'animationset')[0])) for a in off_acts]
        check(names == ['Cursor', 'Arrow'], f'holder 19 OFF actions {names}')
        excl = P.named('EXCLChk', holder)
        on_ev = [o for o, _l, n in P.events(excl) if P.comp(o) == 'controlValueEvent' and n == '0'][0]
        on_arrow = [a for a in P.actions_of(excl, be(P.data, on_ev + 28))
                    if 'animationset' in fields(P.rec(a))[1]
                    and E.pool_str(be(P.data, P.field(a, 'animationset')[0])) == 'Arrow']
        check(len(on_arrow) == 1, 'EXCLChk: one Arrow ON')
        eq_o = [o for o, _l, _n in P.events(excl) if P.comp(o) == 'appVariableChangeEvent'][0]
        check('equal-value' in fields(P.rec(eq_o))[1], 'EXCLChk equal event')
        cont = next(self._ids)
        self.notes['footer'] = dict(container=cont)
        recs = [(bytes(self.obj_record(cont, qsmode, 'Image', 4)), []),
                (self.base_record(cont, (1024.0, FOOT_H), (0.0, 0.0)), [])]
        # QS_QSMode in [49, 72] -> Cursor OFF (local 1)
        ev_o = [o for o, _l, _n in P.events(self.tiles[0]['icon01']) if P.comp(o) == 'appVariableChangeEvent'][0]
        ev = bytearray(encode(P.rec(ev_o), {'variable-name': str5(pstr('QS_QSMode'), 0),
                                            'range-upperlimit-value': struct.pack('>f', float(UI_LAST))},
                              add=[('range-lowerlimit-value', struct.pack('>f', float(UI_FN0)))]))
        act = bytearray(P.rec(off_acts[0]))
        struct.pack_into('>III', act, 20, cont, 1, 1)
        if self.mutate == 'nocursoroff':
            struct.pack_into('>IIII', ev, 16, 0, 0xFFFFFFFF, cont, 1)
            recs.append((bytes(ev), []))
        else:
            struct.pack_into('>IIII', ev, 16, 1, 0xFFFFFFFF, cont, 1)
            recs += [(bytes(ev), []), (bytes(act), [])]
        # QSC_Arw == 1 -> Arrow ON (local 2), == 0 -> Arrow OFF (local 3)
        for lid, want, act_o in ((2, 1, on_arrow[0]), (3, 0, off_acts[1])):
            e = bytearray(encode(P.rec(eq_o), {'variable-name': str5(0, 0)},
                                 drop=() if want else ('equal-value',)))
            if want:
                e = bytearray(encode(bytes(e), {'equal-value': struct.pack('>f', 1.0)}))
            struct.pack_into('>IIII', e, 16, 1, 0xFFFFFFFF, cont, lid)
            a = bytearray(P.rec(act_o))
            struct.pack_into('>III', a, 20, cont, lid, 1)
            _c, ef = fields(bytes(e))
            recs += [(bytes(e), [(ef['variable-name'][0], P_STR, S_ARW)]), (bytes(a), [])]
        self.kind('appVariableChangeEvent', 3)
        self.kind('controlAnimation', 2 if self.mutate == 'nocursoroff' else 3)
        self.kind('objectBase')
        self.added['objects'] += 1
        n_child = 0
        for j in range(N_SLOT):
            for role in FOOT_ROLES:
                oid = next(self._ids)
                var = S_FL + N_SLOT * FOOT_ROLES.index(role) + j
                recs.append((bytes(self.obj_record(oid, cont, 'String', 3)), []))
                recs.append((self.base_record(oid, (SLOT_W, FOOT_H), (SLOT_GRID * j, 0.0)), []))
                rect, size = FOOT_RECT[role], FOOT_SIZE[role]
                if self.mutate == 'footertop' and role in ('FP', 'FQ', 'FR'):
                    rect = FOOT_RECT['FL']                       # v0.2.2: one-line labels at the top
                if self.mutate == 'fatmark' and role == 'FM':
                    rect, size = (0.0, 34.0, SLOT_W, 16.0), 16    # v0.2.2's mark
                recs += self.text_records(oid, rect, size, var, FOOT_COLOR[role])
                self.kind('objectBase')
                self.added['objects'] += 1
                n_child += 1
        # the box: a toggleVisible bound to QSC_FB; children 0..14 boxes, 15 none
        hp = P.named('48_EXCL_HeadphoneVolume', P.children(self.tiles[0]['icon02'], 'QSMENU'))
        tv_o, = P.records_of(hp, tag=T_CTRL)
        bind_o, = [o for o, _l, _n in P.events(hp) if P.comp(o) == 'appVariableEvent']
        tog = next(self._ids)
        self.notes['footer']['toggle'] = tog
        recs.append((bytes(self.obj_record(tog, cont, 'Cursor', 3)), []))
        recs.append((self.base_record(tog, (1024.0, FOOT_H), (0.0, 0.0)), []))
        tv = bytearray(P.rec(tv_o))
        struct.pack_into('>II', tv, 20, tog, 1)
        bind = bytearray(encode(P.rec(bind_o), {'variable-name': str5(0, 0), 'component-id': struct.pack('>I', 1)}))
        struct.pack_into('>III', bind, 16, 0, 0xFFFFFFFF, tog)
        struct.pack_into('>I', bind, 28, 2)
        _c, bf = fields(bytes(bind))
        recs += [(bytes(tv), []), (bytes(bind), [(bf['variable-name'][0], P_STR, S_FB)])]
        self.kind('objectBase'); self.kind(E.pool_str(be(P.data, tv_o + 8))); self.kind('appVariableEvent')
        self.added['objects'] += 1
        n_child += 1
        cur = P.named('Cursor', qsmode)
        rect_o, = P.records_of(cur, 'drawRect')
        boxes = []
        for j in range(N_SLOT + 1):
            oid = next(self._ids)
            boxes.append(oid)
            last = j == BOX_NONE
            recs.append((bytes(self.obj_record(oid, tog, 'Cursor', 1 if last else 2)), []))
            x = 0.0 if last else SLOT_GRID * j + (SLOT_W - BOX_W) / 2
            recs.append((self.base_record(oid, (0.0, 0.0) if last else (BOX_W, FOOT_H), (x, 0.0)), []))
            self.kind('objectBase')
            self.added['objects'] += 1
            if not last:
                dr = bytearray(encode(P.rec(rect_o), {'rect': struct.pack('>4f', 0.0, 0.0, BOX_W, FOOT_H)}))
                struct.pack_into('>II', dr, 20, oid, 1)
                recs.append((bytes(dr), []))
                self.kind('drawRect')
        self.notes['footer']['boxes'] = boxes
        # children counts: the container's (texts + toggle), the toggle's (16); QSMode +1
        o = bytearray(recs[0][0]); struct.pack_into('>I', o, 16, n_child); recs[0] = (bytes(o), [])
        i_tog = [i for i, (r, _p) in enumerate(recs) if be(r, 0) == T_OBJECT and be(r, 20) == tog][0]
        o = bytearray(recs[i_tog][0]); struct.pack_into('>I', o, 16, N_SLOT + 1); recs[i_tog] = (bytes(o), [])
        anchor = self.tile_anchor(qsmode)
        for data, patches in recs:
            ed.append(anchor, data, patches)
        ed.add(P.obj_rec[qsmode], 16, 1)

    def dial_on(self):
        """T2: QS_QSMode in 49..72 -> the 'Dial' ON interval of DialKeyEvent
        (the FR..BL objects visible; a stock holder does it for its own id)."""
        P, ed = self.page, self.ed
        oid = next(self._ids)
        self.notes['dial_on'] = oid
        t1 = self.tiles[0]
        obj = bytearray(P.rec(P.obj_rec[t1['icon02']]))
        struct.pack_into('>IIIIII', obj, 8, 2, 0, 0, oid, self.root, pstr('Check'))
        ob = bytearray(encode(P.rec(P.records_of(t1['icon02'], 'objectBase')[0]),
                              {'size': struct.pack('>ff', 0.0, 0.0)}))
        struct.pack_into('>II', ob, 20, oid, 0)
        ev_o = [o for o, _l, _n in P.events(t1['icon01']) if P.comp(o) == 'appVariableChangeEvent'][0]
        ev = bytearray(encode(P.rec(ev_o), {'variable-name': str5(pstr('QS_QSMode'), 0),
                                            'range-upperlimit-value': struct.pack('>f', float(UI_LAST))},
                              add=[('range-lowerlimit-value', struct.pack('>f', float(UI_FN0)))]))
        struct.pack_into('>IIII', ev, 16, 1, 0xFFFFFFFF, oid, 1)
        holder = next(i for i, (n, p) in P.objs.items() if n == '0' and p == self.qsmode)
        on = P.records_of(holder, 'controlAnimation')
        on = [o for o in on if 'animationset-owner' in fields(P.rec(o))[1]
              and be(P.data, P.field(o, 'animationset-owner')[0]) == self.dial
              and E.pool_str(be(P.data, P.field(o, 'interval')[0])) == 'ON'][0]
        act = bytearray(P.rec(on))
        struct.pack_into('>III', act, 20, oid, 1, 1)
        anchor = self.tiles[-1]['anchor']
        for r in (bytes(obj), bytes(ob), bytes(ev), bytes(act)):
            ed.append(anchor, r)
        ed.add(P.obj_rec[self.root], 16, 1)
        self.added['objects'] += 1
        self.kind('objectBase'); self.kind('appVariableChangeEvent'); self.kind('controlAnimation')

    def header(self):
        """H: the allocation header (record 0) carries the budget of every
        addition: invariants sum(groups' nC) == pair entries == animationClip,
        sum(pair entries) == key entries (QS_CINE, Y2_3C, MainB2, B2_5 hold them)."""
        P, ed = self.page, self.ed
        h0 = 0
        check(P.at[0][0] == 0x10002, 'record 0 is not the allocation header')
        from ui import rows as R
        h = P.rec(0)
        comps, arrays = R.header_layout(h)
        kinds = {E.pool_str(be(h, c - 4)): c for c in comps}
        ed.add(h0, 8, self.added['objects'])
        n_pairs = len(self.added['pairs'])
        kc = dict(self.added['kinds'])
        kc['animationClip'] = n_pairs
        for name, n in kc.items():
            if n:
                check(name in kinds, f'header has no {name}')
                ed.add(h0, kinds[name], n)
        (c0, e0, _w0), (c1, e1, _w1), (c2, e2, _w2), _a3 = arrays
        group_index = {o: i for i, o in enumerate(P.groups)}
        per_group = {}
        for g_at, _props in self.added['pairs']:
            per_group[g_at] = per_group.get(g_at, 0) + 1
        for g_at, n in sorted(per_group.items()):
            ed.add(h0, c0 + 4 + 12 * group_index[g_at] + 8, n)
        pair_props = [len(props) for _g, props in self.added['pairs']]
        prop_keys = [k for _g, props in self.added['pairs'] for k in props]
        a1 = b''.join(struct.pack('>I', n) for n in pair_props)
        a2 = b''.join(struct.pack('>I', n) for n in prop_keys)
        ed.ins(h0, e1, a1)
        ed.add(h0, c1, len(pair_props))
        ed.ins(h0, e2, a2)
        ed.add(h0, c2, len(prop_keys))
        self.notes['header'] = dict(objects=self.added['objects'], kinds=kc, pairs=n_pairs, props=len(prop_keys))


def qs_icon_looks(names, page=None):
    """[(image, rect, size, position) raw BE words] per list icon name: the
    QS Icon01 look of the CINE functions whose list row uses that image, the
    same in all eight tiles (else the name is refused: None)."""
    P = page or Page()
    rows = E.csv_rows(0)
    clips = []
    for k in range(1, 9):
        ic = P.children(P.named(f'QS_CINE{k}'), 'Icon01')
        g, = P.groups_of(ic, 'Icon01_CINE')
        clips.append(P.clip(*g['pairs'][0]))
    out = []
    for name in names:
        looks = set()
        for ui, img in rows:
            if img != name:
                continue
            t = Fraction(ui * 100, 3)
            for c in clips:
                looks.add(tuple(raw_at(c.prop(n, dim), t) for n, dim in
                                (('image', 0), ('rect', 2), ('size', 0), ('position', 0))))
        out.append(looks.pop() if len(looks) == 1 else None)
    return out


# ---------------------------------------------------------------------------
def fnv(data):
    h = 2166136261
    for b in data:
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h


QT_FMT = '<9I'        # pos, len, fnv, out_len, op_first, op_n, patch_first, patch_n, n_out_records
OP_FMT = '<IBBHII'    # at, kind, 0, 0, a, b: SET/ADD value a; INS/APP length a, fragment offset b
PATCH_FMT = '<IHH'    # out offset, kind, arg
QT_BYTES, OP_BYTES, PATCH_BYTES = 36, 16, 8


def ordered_ops(ed, rec):
    """The order qsct.c applies them in: stock offset, inserts first at one
    offset (in the order made), then the appended records."""
    lst = sorted(enumerate(ed.ops.get(rec, [])), key=lambda x: (x[1][0], 0 if x[1][1] == Q_INS else 1, x[0]))
    ops = [op for _i, op in lst]
    ins = [a for a, k, _v, _f in ops if k == Q_INS]
    for a, k, _v, _f in ops:
        if k in (Q_SET, Q_ADD):
            check(not any(a < q < a + 4 for q in ins), f'+0x{rec:X}: an edit at +{a} straddles an insert')
    n = len(ed.page.rec(rec))
    return ops + [(n, Q_APP, 0, f) for f in ed.after.get(rec, [])]


def table(design=None):
    """The QS table the camera applies: (bytes, info).  Layout (LE):
    {targets QT_FMT} {ops OP_FMT} {patches PATCH_FMT} {fragments, 4-aligned}."""
    d = design or Design()
    ed = d.ed
    targets, ops, patches, frags = [], [], [], bytearray()
    for rec in ed.targets():
        stock = d.page.rec(rec)
        out, pl = ed.build(rec)
        o_first, p_first = len(ops), len(patches)
        for at, kind, a, frag in ordered_ops(ed, rec):
            if kind in (Q_INS, Q_APP):
                frags.extend(bytes(-len(frags) % 4))
                ops.append((at, kind, len(frag), len(frags)))
                frags += frag
            else:
                ops.append((at, kind, a, 0))
        patches += pl
        targets.append((rec, len(stock), fnv(stock), len(out), o_first, len(ops) - o_first, p_first,
                        len(patches) - p_first, len(E.records(out))))
    blob = bytearray()
    for t in targets:
        blob += struct.pack(QT_FMT, *t)
    ops_off = len(blob)
    for at, kind, a, b in ops:
        blob += struct.pack(OP_FMT, at, kind, 0, 0, a, b)
    patches_off = len(blob)
    for o, kind, arg in patches:
        blob += struct.pack(PATCH_FMT, o, kind, arg)
    blob.extend(bytes(-len(blob) % 4))
    frags_off = len(blob)
    blob += frags
    info = dict(n_targets=len(targets), ops_off=ops_off, n_ops=len(ops), patches_off=patches_off,
                n_patches=len(patches), frags_off=frags_off, out_total=sum(t[3] for t in targets),
                out_max=max(t[3] for t in targets), targets=[t[0] for t in targets])
    return bytes(blob), info


def apply_table(blob, info, src_rec, values):
    """The reference of qsct.c qc_qs_build: {stock offset: output bytes}, from
    the stock records (src_rec(offset)) and the patch values {(kind, arg): word}."""
    out = {}
    for i in range(info['n_targets']):
        pos, n, h, out_len, of, on, pf, pn, _nr = struct.unpack_from(QT_FMT, blob, QT_BYTES * i)
        stock = src_rec(pos)
        check(len(stock) == n and fnv(stock) == h, 'stock record changed')
        res, p, grow, sized = bytearray(), 0, 0, False
        for j in range(of, of + on):
            at, kind, _z0, _z1, a, b = struct.unpack_from(OP_FMT, blob, info['ops_off'] + OP_BYTES * j)
            if kind in (Q_INS, Q_APP):
                if kind == Q_APP and not sized:
                    res += stock[p:n]
                    p = n
                    struct.pack_into('>I', res, 4, n + grow)
                    sized = True
                res += stock[p:at]
                p = at
                res += blob[info['frags_off'] + b:info['frags_off'] + b + a]
                if kind == Q_INS:
                    grow += a
                continue
            if p < at + 4:
                res += stock[p:at + 4]
                p = at + 4
            o = len(res) - (p - at)
            v = a if kind == Q_SET else (be(res, o) + a) & 0xFFFFFFFF
            struct.pack_into('>I', res, o, v)
        if not sized:
            res += stock[p:n]
            struct.pack_into('>I', res, 4, n + grow)
        for j in range(pf, pf + pn):
            o, kind, arg = struct.unpack_from(PATCH_FMT, blob, info['patches_off'] + PATCH_BYTES * j)
            struct.pack_into('>I', res, o, values[(kind, arg)])
        check(len(res) == out_len, 'output length')
        out[pos] = bytes(res)
    return out


# ---------------------------------------------------------------------------
class Model:
    """The QS page as a list of records (what the parser gets: the stock page,
    or the stream the camera's record layer fed), with the playback model the
    tests judge it by.  `text(offset)` resolves a string field (the stock pool,
    or a private id).  [model: frame = UI * 100 // 3; a key holds (or a LINEAR
    float key interpolates); an animation is applied only when its trigger
    admits the id (an event's value-range, DialKeyEvent's controlValue range)
    and t(id) lies in the interval -- otherwise the object keeps the frame the
    previous tile left (camera 2026-10-29 D, and stage 1's editor freeze)]"""

    RANGE = 0x20                 # appVariableChangeEvent type bit: value-range

    def __init__(self, recs, text):
        self.recs = [bytes(r) for r in recs]
        self.text = text
        self.objs, self.own, self.clips, self.groups = {}, {}, {}, {}
        for i, r in enumerate(self.recs):
            t = be(r, 0)
            if t == T_OBJECT:
                self.objs[be(r, 20)] = dict(name=text(be(r, 28)), parent=be(r, 24), rec=i,
                                            n_local=be(r, 8), n_groups=be(r, 12), n_children=be(r, 16))
            elif t in OWNER:
                self.own.setdefault(be(r, OWNER[t]), []).append(i)
                if t == T_CLIP:
                    self.clips[(be(r, 20), be(r, 24))] = E.Clip(r, 0)
                elif t == T_GROUP:
                    d = NF.decode_image_array(NF.Record(t, 0, r[8:]), pool())
                    d['group'] = text(be(r, 20))
                    self.groups.setdefault(be(r, 24), []).append(d)

    def named(self, name, parent=None):
        hits = [i for i, o in self.objs.items() if o['name'] == name and (parent is None or o['parent'] == parent)]
        check(len(hits) == 1, f'{len(hits)} objects {name!r}')
        return hits[0]

    def children(self, parent):
        return [i for i, o in self.objs.items() if o['parent'] == parent]

    def comp(self, i):
        return self.text(be(self.recs[i], 8))

    def values(self, i):
        """{field: value}: strings resolved, floats as float, the rest raw."""
        comp, f = fields(self.recs[i])
        out = {}
        for n, (o, w, k) in f.items():
            if n.startswith('_'):
                continue
            raw = self.recs[i][o:o + w]
            out[n] = (self.text(be(raw, 0)) if k in (11, 12, 13) else unf32(be(raw, 0)) if k == 1
                      else be(raw, 0) if w == 4 else raw)
        return out

    def comps(self, owner, comp=None, tag=None):
        return [i for i in self.own.get(owner, []) if (tag is None or be(self.recs[i], 0) == tag)
                and (comp is None or (be(self.recs[i], 0) not in (T_CLIP, T_GROUP) and self.comp(i) == comp))]

    def events(self, owner, comp=None):
        """{local id: record index}."""
        return {be(self.recs[i], 28): i for i in self.comps(owner, comp, T_EVENT)}

    def actions(self, owner, lid):
        return [i for i in self.comps(owner, tag=T_ACTION) if be(self.recs[i], 24) == lid]

    def group(self, owner, name):
        g = [d for d in self.groups.get(owner, []) if d['group'] == name]
        check(len(g) == 1, f'{len(g)} groups {name} of {owner}')
        return g[0]

    # -- triggers ----------------------------------------------------------------
    def event_admits(self, owner, var, ui):
        evs = [i for i in self.events(owner, 'appVariableChangeEvent').values()
               if self.values(i).get('variable-name', self.text(be(self.recs[i], 20))) == var]
        # (no variable-name field: the event's instance name is the variable, as Button's 'QS_QSMode')
        check(len(evs) == 1, f'{owner}: {len(evs)} events on {var}')
        v = self.values(evs[0])
        if not (v.get('type', 0) & self.RANGE):
            return True
        return v.get('range-lowerlimit-value', 0.0) <= ui <= v.get('range-upperlimit-value', 0.0)

    def interval_admits(self, owner, name, ui):
        g = self.group(owner, name)
        return any(e['a'] <= t_of(ui) <= e['b'] for e in g['entries'])

    def dial_admits(self, ui):
        dial = self.named('DialKeyEvent')
        cv, = self.comps(dial, 'controlValue')
        v = self.values(cv)
        return v.get('min-value', 0.0) <= ui <= v.get('max-value', 0.0)

    def key_gate(self, obj_name, ui):
        """Is frame t(ui) applied to the key clip of FR / FL / BR / BL / AEL?"""
        if obj_name == 'AEL':
            b = self.named('Button', 1)
            return self.event_admits(b, 'QS_QSMode', ui) and self.interval_admits(b, 'Btn', ui)
        o = self.named(obj_name, self.named('DialKeyEvent'))
        return self.dial_admits(ui) and self.interval_admits(o, obj_name, ui)

    def frame_after(self, gate, seq):
        """The frame an object is at after the focus visited `seq` (UI ids) --
        the last one its gate admitted (None: never applied)."""
        t = None
        for ui in seq:
            if gate(ui):
                t = Fraction(ui * 100, 3)
        return t

    # -- keys ---------------------------------------------------------------------
    def key_object(self, name):
        return self.named('AEL', self.named('Button', 1)) if name == 'AEL' else \
            self.named(name, self.named('DialKeyEvent'))

    def key_clip(self, name):
        obj = self.key_object(name)
        owner = self.named('Button', 1) if name == 'AEL' else obj
        g = self.group(owner, 'Btn' if name == 'AEL' else name)
        cs = [self.clips[p] for p in g['pairs'] if p[0] == obj]
        check(len(cs) == 1, f'{name}: key clip')
        return obj, cs[0]

    def active_keys(self, name, t):
        """{local id} of the keyEvents of `name` its key clip enables at frame t."""
        obj, clip = self.key_clip(name)
        if t is None:
            return set()
        return {p.c for p in clip.props if prop_value_at(p, t)}

    def key_actions(self, name, lid):
        obj = self.key_object(name)
        return [(self.comp(i), self.values(i)) for i in self.actions(obj, lid)]

    def key_name(self, name, lid):
        obj = self.key_object(name)
        return self.text(be(self.recs[self.events(obj)[lid]], 20))

    def prop_at(self, owner, cid, pname, dim, t):
        c = self.clips[(owner, cid)]
        return prop_value_at(c.prop(pname, dim), t)


if __name__ == '__main__':
    d = Design()
    blob, info = table(d)
    print(PAGE, 'targets', info['n_targets'], 'ops', info['n_ops'], 'patches', info['n_patches'],
          'table bytes', len(blob), 'output bytes', info['out_total'], 'largest', info['out_max'])
    print('header', d.notes['header'])
    print('codes', d.notes['codes'])
