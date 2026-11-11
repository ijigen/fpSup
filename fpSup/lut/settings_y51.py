"""The LUT settings page on Y5_1 (SETUP > Date / Time / Area), whose own
popup-list rows open on the camera.

Why this base (2026-11-03 camera, projects/lut-sup/validation/20261103-list-ab-02):
MainB1's Drive mode row opens its list on a stock MainB1 page but not when
grafted onto the MainY5 base of the fpSup pages -- not even untouched (diagJ:
no list, no summary icon).  MainY5's header has no list / scrollEvent /
drawScrollbar / toggleVisible kinds; every working builder (Sensor Lab, the
shared add_row) refuses new kinds, and Sensor Lab's working lists sit on a page
that already has them.  Y5_1 has all four natively and three list rows of its
own, so this page follows the same two rules: rows of the same page, no new
component kinds (Management.finish -> BM.extend_header refuses them).

What is kept of Y5_1: Root, Header (its title bound to FT_PageTitle), Footer,
BG, Menu with Blind and DateFormat; DateFormat becomes Color space and a copy
of it Gamma, another Color matrix.  What goes: the Date / TimeZone / SummerTime / TimeFormat rows,
SYS_DateSetting (the clock object), DialKeyEvent and EnterFocusEvent (focus
by SYS_TimeZoneSetting).  Focus comes from FT_Focus on screen entry (the native
core posts the first row).  MENU is the stock path (user 2026-11-03: the stock
way first): the row's `Return` to the UIC, then ReturnCheck's `Return`
view-state request (SYS_DateSetting 1, its normal value) -- this sup's machine
has FT_LUTSET -Return-> manager.  Only the core's notice (FT_Key 70) goes in
front of the row's stock action.  (A plain 41-byte Return in its place, as the
MainY5 pages do, did not leave this page on the camera, diagK2.)

Gamma follows the color space as the stock B1_4 list does: the row's SetList
animation becomes ApplyFrame on LC_GammaX, its model clip has a key per
variant (0 -> LC_GAMMA, 0x21 -> LC_GAMMA_BMD), its last row is LC_GammaM.
"""
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'uishare/tab'))
import ft6_page as P                     # noqa: E402
import manage_page as M                  # noqa: E402
import nbu_format as N                   # noqa: E402
import settings_page as S                # noqa: E402
import manager_page as MP                # noqa: E402

u32, put, check = P.u32, P.put, P.check
BASE = 'Y5_1'
ROOT, MENU, HEADER_TITLE = 1, 83, 61
ROW = 85                                   # DateFormat: MenuItem_Select_Y > MenuItem_Select > List
SELECT, LIST, ITEM, NAME = 211, 215, 216, 222
SUMMARY = (675, 223)                       # IconText / Icon: the stock per-index summary
SUMMARY_BOX = 675                          # its objectBase: x 433 y 13 532 x 54, right edge 965
SUMMARY_TEXT = 720                         # IconText01's drawText: right-aligned
MODEL_CLIP = 17                            # List clip 17: model Y5_1_DateFormat (SetList)
DROP_MENU = (84, 4315, 4313, 86)           # Date, TimeZone, SummerTime, TimeFormat
DROP_ROOT = (4306, 4232, 4579)             # SYS_DateSetting (the clock), DialKeyEvent, EnterFocusEvent
RETURN_CHECK, RETURN = 4266, 4300          # kept: the stock MENU path (see menu_notice)
STOCK_VAR = 'CM_DateFormat'
STOCK_MODEL = 'Y5_1_DateFormat'
STOCK_FOCUS = 'MENU_Level2'
ROW_PITCH = 81.0
VARIANT_FRAMES = (0, 0x21)                 # B1_4's ListChange2 keys for EXCL 0, 1
APPLY_FRAME = 7                            # controlAnimation operation ApplyFrame
REQUEST = 'submenu_01'                     # a 41-byte request of this page (MenuItem_Select FocusOn)

SPACE = dict(title='Color space', models=('LC_SPACE',), rows=8, value='LC_SpaceV',
             text='LC_SpaceT', variant=None, cap=None)
GAMMA = dict(title='Gamma', models=('LC_GAMMA', 'LC_GAMMA_BMD'), rows=6, value='LC_GammaV',
             text='LC_GammaT', variant='LC_GammaX', cap='LC_GammaM')
# user 2026-11-03: the third row.  Values are library4.h MAT_*: 0 Standard, 1 OFF,
# 2 Custom -- Custom listed only when the author's .cube carries matrices
# (LC_MatrixX 1: LC_MATRIX_C), as Gamma's Blackmagic variant
MATRIX = dict(title='Color matrix', models=('LC_MATRIX', 'LC_MATRIX_C'), rows=3, value='LC_MatrixV',
              text='LC_MatrixT', variant='LC_MatrixX', cap='LC_MatrixM')
MATRIX_LABELS = ('Standard', 'OFF', 'Custom')     # build_sup.strings() 115..117, the core's row texts
# Bei 2026-11-07: the fourth row, "查看色卡" -- the ColorChecker the conversion left (native/conv.c conv_view, from
# the .JFT's chart block).  A copy of DateFormat as the others (no list of its own to open: OK / Right only tell
# the core, LC_Key = CHART_KEY); its value field LC_ChartT says why not ("Convert again", "Recording busy").
# Its list keeps the Matrix model and the never-written LC_Zero, so nothing the stock list would write lands
# anywhere (the list is never focused).
CHART_KEY = 81                             # native/color_ui.c CHART_KEY
CHART = dict(title='Color chart', models=('LC_MATRIX',), rows=2, value=S.ZERO, text='LC_ChartT',
             variant=None, cap=None)


def rows_csv(texts):
    """Y5_1_DateFormat.cvm's own columns (NO,TEXT,Popup,IMAGE,Enabled,Enabled2;
    `Popup`, `blank`, 1, 3 as its rows), a literal TEXT per row, the UTF-8 BOM
    and a CRLF after every line, the last one too (fp-native-ui 2)."""
    for t in texts:
        check(t.isascii() and not set(t) & set(',<>'), f'row text {t!r}')
    lines = ['NO,TEXT,Popup,IMAGE,Enabled,Enabled2']
    lines += [f'{i},{t},Popup,blank,1,3' for i, t in enumerate(texts, 1)]
    return b'\xef\xbb\xbf' + ('\r\n'.join(lines) + '\r\n').encode()


def models():
    from cinemadng import COLOR_SPACES, COMMON_GAMMAS, BLACKMAGIC_GAMMAS, GAMMAS
    return [('LC_SPACE', rows_csv([c.label for c in COLOR_SPACES.values()])),
            ('LC_GAMMA', rows_csv([GAMMAS[g].label for g in COMMON_GAMMAS])),
            ('LC_GAMMA_BMD', rows_csv([GAMMAS[g].label for g in BLACKMAGIC_GAMMAS])),
            ('LC_MATRIX', rows_csv(MATRIX_LABELS[:2])),
            ('LC_MATRIX_C', rows_csv(MATRIX_LABELS))]


class Y51(M.Management):
    """Management's editing helpers on Y5_1 instead of MainY5 (its __init__
    drops MainY5's rows and builds MainY5's tab bar: not called)."""

    def __init__(self, img, pool):                          # noqa: super not called on purpose
        self.img, self.pool = img, pool
        self.schemas = P.P.load_schemas(img)
        self.recs = N.split(P.SL.set_bytes(BASE))
        self.objs = P.SZ.objects(self.recs, pool)
        self.raw = [bytearray(r.to_bytes()) for r in self.recs]
        self.src = P.by_object(self.raw)
        check(self.objs[MENU]['name'] == 'Menu' and self.objs[ROW]['name'] == 'DateFormat'
              and self.objs[SELECT]['name'] == 'MenuItem_Select' and self.objs[LIST]['name'] == 'List'
              and self.objs[ITEM]['name'] == 'ListItem' and self.objs[NAME]['parent'] == SELECT, 'Y5_1 changed')
        self.next_id = max(self.objs) + 1
        self.removed, self.added, self.groups, self.refs = [], [], [], []
        header = P.A.parse_header(P.A.Record(0, self.recs[0].to_bytes()), pool.text)
        gi = [i for i, r in enumerate(self.recs) if r.tag == 0x1000B]
        self.group_budget = {id(self.raw[i]): header['groups'][n] for n, i in enumerate(gi)}
        self.gone = set()
        for root in DROP_MENU + DROP_ROOT:
            self.gone |= P.SZ.subtree(self.objs, root)
        self.drop_subtrees(DROP_MENU + DROP_ROOT)
        ob = self.ob()
        put(self.seq[ob[MENU][0]], 16, self.objs[MENU]['n'] - len(DROP_MENU))
        put(self.seq[ob[ROOT][0]], 16, self.objs[ROOT]['n'] - len(DROP_ROOT))

    def template(self, kind, length, test=lambda r: True):
        return next(r for r in self.raw if len(r) == length and P.pool_name(self, r) == kind and test(r))

    def write(self, owner, event, order, name, value=None, source=None):
        """controlAppVariable `name` = literal `value`, Y5_1's own 46-byte form."""
        check(source is None, 'Y5_1 write: literal values only')
        # Y5_1's 46-byte records are mask 0x11 (destination-variable, component-name);
        # the same layout with mask 0x81 is MainY5's camera-proven literal write
        # (destination-variable, value).  2026-11-03 camera: with 0x11 the "70" went
        # into component-name, LC_Key stayed 0 and MENU never left the page.
        r = bytearray(self.template('controlAppVariable', 46, lambda r: u32(r, 32) == 0x11))
        put(r, 32, 0x81)
        put(r, 20, owner); put(r, 24, event); put(r, 28, order)
        self.private(r, 36, name)
        if self.pool.find(str(value)) is None:
            self.private(r, 41, str(value))
        else:
            put(r, 41, self.pool.find(str(value)))
        return r

    def clone(self, root, preserve=False):
        sub = P.SZ.subtree(self.objs, root)
        a, b = P.SZ.span(self.recs, self.objs, sub, root)
        mapping = {old: self.take_id() for old in sorted(sub)}
        out = []
        for src in self.raw[a:b]:
            r = bytearray(src)
            for off, kind in P.P.typed_fields(bytes(r), self.pool, self.schemas):
                if kind == 'obj' and u32(r, off) in mapping:
                    put(r, off, mapping[u32(r, off)])
            if u32(r, 0) == 0x10008:
                for off in S.template_ids(r):
                    if u32(r, off) in mapping:
                        put(r, off, mapping[u32(r, off)])
            if u32(r, 0) == 0x1000B:
                self.group_budget[id(r)] = self.group_budget[id(src)]
            out.append(r)
        return self.without_gone(out), mapping

    def without_gone(self, recs):
        """drop_subtrees' rule for records copied from the stock page: an action
        aimed at a dropped object goes and its event's count follows; an event
        left with none goes too and its object's component count follows."""
        def names_gone(r):
            return any(kind == 'obj' and u32(r, off) in self.gone and u32(r, off) > 64
                       for off, kind in P.P.typed_fields(bytes(r), self.pool, self.schemas))
        out, k = [], 0
        while k < len(recs):
            r = recs[k]
            if u32(r, 0) != 0x10006:
                out.append(r); k += 1
                continue
            n = u32(r, 16)
            acts = recs[k + 1:k + 1 + n]
            keep = [a for a in acts if not names_gone(a)]
            if keep or not n:
                put(r, 16, len(keep))
                out += [r] + keep
            else:
                head = next(j for j in range(len(out) - 1, -1, -1) if u32(out[j], 0) == 0x10003)
                put(out[head], 8, u32(out[head], 8) - 1)
            k += 1 + n
        check(not any(names_gone(r) for r in out), 'a copied record still names a dropped object')
        return out


def rename_strings(pg, recs, old, new):
    """Every typed string field naming `old` -> private `new`; returns how many."""
    o, n = pg.pool.find(old), 0
    check(o is not None, f'{old} is not a stock string')
    for r in recs:
        for off, kind in P.P.typed_fields(bytes(r), pg.pool, pg.schemas):
            if kind in ('str', 'text') and u32(r, off) == o:
                pg.private(r, off, new)
                n += 1
    return n


def model_clip(pg, recs, by, lst, spec):
    """List clip 17 (model): one key per variant model."""
    at = next(i for i in by[lst] if u32(recs[i], 0) == 0x1000A and u32(recs[i], 24) == MODEL_CLIP)
    c = recs[at]
    check(len(c) == 58 and u32(c, 12) == 1 and struct.unpack_from('>5I', c, 28) ==
          (1, 2, 1, pg.pool.find('model'), 0) and u32(c, 50) == 0 and u32(c, 54) == pg.pool.find(STOCK_MODEL),
          'Y5_1 model clip form')
    keys = []
    for frame, model in zip(VARIANT_FRAMES, spec['models']):
        keys.append(struct.pack('>HII', 0, frame, 0))
    new = bytearray(c[:28]) + struct.pack('>5I', len(keys), 2, 1, pg.pool.find('model'), 0) + b''.join(keys)
    put(new, 4, len(new))
    for k, model in enumerate(spec['models']):
        pg.private(new, 48 + 10 * k + 6, model)
    recs[at] = new
    return new


def apply_frame(pg, recs, by, sel, lst, variable):
    """SetList (the row's FocusOn) -> ApplyFrame on `variable`, B1_4's form:
    mask 0x10f (operation, owner, set, interval, apply-frame)."""
    setlist = pg.pool.find('SetList')
    at = next(i for i in by[sel] if P.pool_name(pg, recs[i]) == 'controlAnimation' and len(recs[i]) == 50
              and u32(recs[i], 36) == lst and u32(recs[i], 40) == setlist)
    a = recs[at]
    # owner (4), animationset and interval: string fields of 4 B + a resolver byte
    check(u32(a, 32) == 0xE and u32(a, 45) == setlist and a[44] == 0 and a[49] == 0, 'Y5_1 SetList form')
    new = bytearray(a[:32]) + struct.pack('>II', 0x10F, APPLY_FRAME) + a[36:50] + bytes(5)
    put(new, 4, len(new))
    check(len(new) == 59, 'ApplyFrame form (MainB1 B1_4: 59 B)')
    pg.private(new, 54, variable)
    recs[at] = new


def value_field(pg, out, by, sel, name, var):
    """A sibling of the title: the stock summary's box and right-aligned
    drawText (IconText / IconText01), its text the variable the core posts."""
    oid = pg.take_id()
    head = bytearray(out[by[name][0]])
    put(head, 20, oid); put(head, 8, 2); put(head, 16, 0)
    box = P.owned(pg.raw[P.comp(pg.raw, pg.src[SUMMARY_BOX], 'objectBase', pg.pool)], oid)
    text = P.owned(pg.raw[P.comp(pg.raw, pg.src[SUMMARY_TEXT], 'drawText', pg.pool)], oid)
    check(u32(box, 28) == 3 and u32(text, 28) == 0x40000011 and len(text) == 57 and text[36] == 1
          and u32(text, 37) == 3, 'Y5_1 summary form')
    check(u32(box, 24) != u32(text, 24), 'value field local ids')
    pg.literal(text, ' ')
    at = by[name][-1] + 1
    out[at:at] = [head, box, text]
    pg.bind(out, oid, var, u32(text, 24), 'text')
    s = out[P.by_object(out)[sel][0]]
    put(s, 16, u32(s, 16) + 1)


def setting_row(pg, out, m, k, spec):
    """DateFormat's records `out` (ids `m`: old -> this row's) as row k of `spec`."""
    by = P.by_object(out)
    sel, lst, item, name = (m[o] for o in (SELECT, LIST, ITEM, NAME))
    check(rename_strings(pg, out, STOCK_VAR, spec['value']) >= 5, f'{STOCK_VAR} fields')
    # DateFormat's own value (3 formats) is capped at 2 and bound to the variable:
    # left so, it clamps the cube's value -- 2026-11-03 camera: Rec.709 became
    # Blackmagic Design and the camera wrote it to LUT.BIN
    rcv = out[P.comp(out, by[m[ROW]], 'controlValue', pg.pool)]
    check(u32(rcv, 28) == 2 and struct.unpack_from('>f', rcv, 32)[0] == 2.0, 'DateFormat value form')
    struct.pack_into('>f', rcv, 32, float(spec['rows'] - 1))
    base = out[P.comp(out, by[m[ROW]], 'objectBase', pg.pool)]
    check(u32(base, 28) == 3 and struct.unpack_from('>f', base, 36)[0] == 4 * ROW_PITCH, 'DateFormat row form')
    struct.pack_into('>f', base, 36, k * ROW_PITCH)
    model_clip(pg, out, by, lst, spec)
    if spec['variant']:
        apply_frame(pg, out, by, sel, lst, spec['variant'])
    cv = out[P.comp(out, by[lst], 'controlValue', pg.pool)]
    check(u32(cv, 28) == 0xA and struct.unpack_from('>f', cv, 32)[0] == 2.0, 'Y5_1 List cap form')
    struct.pack_into('>f', cv, 32, float(spec['rows'] - 1))
    capacity = out[P.comp(out, by[item], 'controlValue', pg.pool)]
    check(u32(capacity, 28) == 3 and struct.unpack_from('>f', capacity, 36)[0] == 8.0
          and spec['rows'] <= 8, 'Y5_1 ListItem capacity')
    if spec['cap']:
        pg.bind(out, lst, spec['cap'], u32(cv, 24), 'max-value', 1)
    by = P.by_object(out)
    pg.literal(out[P.comp(out, by[name], 'drawText', pg.pool)], spec['title'])
    for old in SUMMARY:
        M.move_hidden(out[P.comp(out, by[m[old]], 'objectBase', pg.pool)])
    value_field(pg, out, P.by_object(out), sel, name, spec['text'])


def chart_row(pg, out, m, k):
    """DateFormat's records as row k, "Color chart": setting_row's copy, then its OK and Right (which open
    the list) only write LC_Key = CHART_KEY in this page's own literal form (Y51.write)."""
    setting_row(pg, out, m, k, CHART)
    sel = m[SELECT]
    by = P.by_object(out)
    done = []
    for i in list(by[sel]):
        r = out[i]
        if u32(r, 0) == 0x10006 and P.pool_name(pg, r) == 'keyEvent' and pg.pool.text(u32(r, 20)) in ('OK', 'Right'):
            done.append(pg.pool.text(u32(r, 20)))
    check(sorted(done) == ['OK', 'Right'], 'DateFormat OK / Right')
    i = 0
    while i < len(out):
        r = out[i]
        if u32(r, 0) == 0x10006 and u32(r, 24) == sel and P.pool_name(pg, r) == 'keyEvent' \
                and pg.pool.text(u32(r, 20)) in ('OK', 'Right'):
            n = u32(r, 16)
            check(n == 2, 'DateFormat OK / Right: controlFocus + changePropertyByControl')
            out[i + 1:i + 1 + n] = [pg.write(sel, u32(r, 28), 1, 'FT_Key', CHART_KEY)]
            put(r, 16, 1)
        i += 1


# The chart on this page (Bei 11-07): the manager's (manager_page.checker_chart) is a MainY5 page's objects, so this
# page has its own copy made of Y5_1's own forms (fp-native-ui 8b: no foreign records) -- BG 2's Name / objectBase /
# drawRect (filled as manage_page.fill_rect does), the summary's box and right-aligned drawText (value_field) for
# the match -- bound to the same variables: LC_Chart (opacity), LC_P00..47 (colour), LC_Match (text).  No bar.
# A Root child before the others: drawn over the rows.
CHART_BG = 2                               # BG (under 8): Name, objectBase (mask 3), drawRect 0x201


def _chart_object(pg, parent, x, y, w, h):
    oid = pg.take_id()
    head = bytearray(pg.raw[pg.src[CHART_BG][0]])
    check(u32(head, 0) == 0x10003 and u32(head, 16) == 0, 'Y5_1 BG head form')
    put(head, 20, oid); put(head, 24, parent); put(head, 8, 1); put(head, 16, 0)
    base = P.owned(pg.raw[P.comp(pg.raw, pg.src[CHART_BG], 'objectBase', pg.pool)], oid)
    check(u32(base, 28) == 3 and len(base) == 48, 'Y5_1 BG objectBase form')
    struct.pack_into('>4f', base, 32, float(x), float(y), float(w), float(h))
    return [head, base], oid


def _chart_rect(pg, parent, x, y, w, h, colour):
    out, oid = _chart_object(pg, parent, x, y, w, h)
    draw = P.owned(pg.raw[P.comp(pg.raw, pg.src[CHART_BG], 'drawRect', pg.pool)], oid)
    check(u32(draw, 28) == 0x201 and len(draw) == 52, 'Y5_1 BG drawRect form')
    draw[:] = draw[:28] + struct.pack('>III4f', 0x203, colour, 1, 0.0, 0.0, float(w), float(h))   # fill_rect's form
    put(draw, 4, len(draw))
    check(u32(draw, 24) != u32(out[1], 24), 'chart rect local ids')
    out.append(draw); put(out[0], 8, u32(out[0], 8) + 1)
    pg.bind(out, oid, MP.CHART_VAR, u32(out[1], 24), 'opacity', 1)
    return out, oid, draw


CHART_MATCH = (128, 276, 532, 54)          # the summary box's size: right edge 20 in from the chart's


def chart_overlay(pg):
    x, y, w, h = MP.CHART_RECT
    out, c_id, _d = _chart_rect(pg, ROOT, x, y, w, h, MP.CHART_COLOUR)
    kids = []
    names = MP.patch_vars()
    for p in range(MP.N_PATCH):
        r, c = divmod(p, 6)
        px, py = MP.PATCH_X0 + c * (MP.PATCH_W + MP.PATCH_GAP), MP.PATCH_Y0 + r * (MP.PATCH_H + MP.PATCH_GAP)
        for half in range(2):
            o, oid, draw = _chart_rect(pg, c_id, px, py + half * (MP.PATCH_H // 2), MP.PATCH_W, MP.PATCH_H // 2,
                                       MP.CHART_COLOUR)
            pg.bind(o, oid, names[2 * p + half], u32(draw, 24), 'color', 1)
            kids += o
    o, t_id = _chart_object(pg, c_id, 0, 0, 0, 0)
    box = P.owned(pg.raw[P.comp(pg.raw, pg.src[SUMMARY_BOX], 'objectBase', pg.pool)], t_id)
    text = P.owned(pg.raw[P.comp(pg.raw, pg.src[SUMMARY_TEXT], 'drawText', pg.pool)], t_id)
    check(u32(box, 28) == 3 and u32(text, 28) == 0x40000011 and len(text) == 57 and text[36] == 1
          and u32(text, 37) == 3, 'Y5_1 summary form')
    check(u32(box, 24) != u32(text, 24), 'match text local ids')
    struct.pack_into('>4f', box, 32, *(float(v) for v in CHART_MATCH))
    pg.literal(text, ' ')
    o[1:2] = [box, text]; put(o[0], 8, 2)
    pg.bind(o, t_id, MP.MATCH_VAR, u32(text, 24), 'text')
    pg.bind(o, t_id, MP.CHART_VAR, u32(box, 24), 'opacity', 1)
    kids += o
    put(out[0], 16, 2 * MP.N_PATCH + 1)
    recs = out + kids
    ob = pg.ob()
    at = ob[ROOT][-1] + 1                                                   # after Root's own records
    check(u32(pg.seq[at], 0) == 0x10003, 'Root then its first child')
    pg.seq[at:at] = recs; pg.added += recs
    root = pg.seq[ob[ROOT][0]]; put(root, 16, u32(root, 16) + 1)
    return c_id


BACK_VAR = 'LC_Back'                       # color_ui.c MV_BACK: posted after the manager's values
BACK_TEXT = 'LC_BACK' + '_' * 26           # color_ui.c T_BACK: the request, "Return" only after MENU


def menu_notice(pg):
    """A row's MENU only tells the core (FT_Key 70); the core posts the
    manager's values and focus, then LC_Back, whose change event (back_event)
    sends the row's own stock Return.  Variables are applied in batches after
    the deferred requests (research/ui/MENU_PAGE_SWITCH.md): with the stock
    Return on the key itself the manager came up before its focus (diagK3)."""
    rows = {o for o, v in pg.objs.items() if v['name'] == 'MenuItem_Select'} | set(pg.clones_of_select)
    stock = None
    i = 0
    while i < len(pg.seq):
        r = pg.seq[i]
        if len(r) >= 24 and u32(r, 0) == 0x10006 and P.pool_name(pg, r) == 'keyEvent' \
                and pg.pool.text(u32(r, 20)) == 'Menu' and u32(r, 24) in rows:
            count = u32(r, 16)
            j = next(j for j in range(i + 1, i + 1 + count) if P.pool_name(pg, pg.seq[j]) == 'controlAppState')
            a = pg.seq[j]
            check(len(a) == 45 and u32(a, 32) == 5 and pg.pool.text(u32(a, 36)) == 'Return', 'DateFormat MENU form')
            stock = stock or bytes(a)
            pg.seq[j] = pg.write(u32(a, 20), u32(a, 24), u32(a, 28), 'FT_Key', 70)
            pg.removed.append(bytes(a)); pg.added.append(pg.seq[j])
        i += 1
    check(stock is not None, 'no row MENU')
    return stock


def back_event(pg, stock):
    """Root: appVariableChangeEvent on LC_Back (Y5_1's own 41-byte form, any
    change) -> the rows' stock 45-byte request to the UIC, its name T_BACK
    (the core: "Return" at MENU, empty otherwise -- a change event also runs
    when its page is built, diagL: the page left at once with a fixed Return)."""
    ob = pg.ob()
    root = ob[ROOT]
    tmpl = next(r for r in pg.raw if len(r) == 41 and P.pool_name(pg, r) == 'appVariableChangeEvent'
                and u32(r, 32) == 1 and u32(r, 16) == 1)
    local = max(P.P.local_ids(pg.seq, root) | {0}) + 1
    ev = bytearray(tmpl)
    put(ev, 24, ROOT); put(ev, 28, local); put(ev, 16, 1)
    pg.private(ev, 36, BACK_VAR)
    act = bytearray(stock)
    put(act, 20, ROOT); put(act, 24, local); put(act, 28, 1)
    pg.private(act, 36, BACK_TEXT)          # the core writes "Return" here at MENU, empty otherwise
    at = root[-1] + 1
    pg.seq[at:at] = [ev, act]
    pg.added += [ev, act]
    head = pg.seq[root[0]]
    put(head, 8, u32(head, 8) + 1)


def enter_focus(pg):
    """Root's screen-enter event focuses from FT_Focus (Y5_1's EnterFocusEvent
    form: focus-variable), as the MainY5 pages' screenEvent does."""
    ob = pg.ob()
    at = next(i for i in ob[ROOT] if P.pool_name(pg, pg.seq[i]) == 'screenEvent')
    ev = pg.seq[at]
    src = next(r for r in pg.raw if len(r) == 45 and P.pool_name(pg, r) == 'controlFocus'
               and u32(r, 20) == 4579 and u32(r, 32) == 0x11 and pg.pool.text(u32(r, 40)) == STOCK_FOCUS)
    f = bytearray(src)
    put(f, 20, ROOT); put(f, 24, u32(ev, 28))
    pg.private(f, 40, M.FOCUS)
    acts = pg.seq[at + 1:at + 1 + u32(ev, 16)]
    put(f, 28, max((u32(a, 28) for a in acts), default=0) + 1)
    pg.seq.insert(at + 1 + u32(ev, 16), f); pg.added.append(f)
    put(ev, 16, u32(ev, 16) + 1)


def build(title_text='LUT settings'):
    """(page, refs, row0): row0 = Color space's MenuItem_Select (the core's first focus)."""
    img, pool = P.stock_pool()
    pg = Y51(img, pool)
    # Gamma first, from the untouched DateFormat records
    gout, gm = pg.clone(ROW)
    xout, xm = pg.clone(ROW)
    cout, cm = pg.clone(ROW)
    pg.clones_of_select = [gm[SELECT], xm[SELECT], cm[SELECT]]
    ob = pg.ob()
    a, b = ob[ROW][0], max(i for o in P.SZ.subtree(pg.objs, ROW) for i in ob[o]) + 1
    out = pg.seq[a:b]
    before = list(out)
    m = {o: o for o in P.SZ.subtree(pg.objs, ROW)}
    setting_row(pg, out, m, 0, SPACE)
    pg.seq[a:b] = out
    # in place: the header follows only what came and went (replaced records count both ways)
    old_ids, new_ids = {id(r) for r in before}, {id(r) for r in out}
    pg.added += [r for r in out if id(r) not in old_ids]
    pg.removed += [bytes(r) for r in before if id(r) not in new_ids]
    setting_row(pg, gout, gm, 1, GAMMA)
    setting_row(pg, xout, xm, 2, MATRIX)
    chart_row(pg, cout, cm, 3)
    pg.seq[a + len(out):a + len(out)] = gout + xout + cout
    pg.added += gout + xout + cout
    pg.groups += [pg.group_budget[id(r)] for r in gout + xout + cout if u32(r, 0) == 0x1000B]
    put(pg.seq[pg.ob()[MENU][0]], 16, u32(pg.seq[pg.ob()[MENU][0]], 16) + 3)
    # the header's title: the cube's name
    t = pg.seq[P.comp(pg.seq, pg.ob()[HEADER_TITLE], 'drawText', pool)]
    pg.literal(t, title_text)
    prior = {id(r) for r in pg.seq}
    pg.bind(pg.seq, HEADER_TITLE, 'FT_PageTitle', u32(t, 24), 'text')
    pg.added += [r for r in pg.seq if id(r) not in prior]
    pg.root_focus_y51 = rename_strings(pg, pg.seq, STOCK_FOCUS, M.FOCUS)
    enter_focus(pg)
    M.enter_write(pg, M.GO_VAR, 0)
    import manager_page as MP
    M.enter_write(pg, MP.GO_VAR, 0)
    back_event(pg, menu_notice(pg))
    chart_overlay(pg)
    page, refs = pg.finish(BASE)
    return page, refs, m[SELECT]


def check_settings_page(page):
    """ft6_page.check_page on the Y5_1 base, and every list row template names
    an object of the page."""
    img, pool = P.stock_pool()
    shape = P.check_page(page, img, pool, base=BASE)
    for r in N.split(page):
        if r.tag == 0x10008:
            d = r.to_bytes()
            for o in S.template_ids(d):
                v = u32(d, o)
                check(v in (0, 0xFFFFFFFF) or v in shape['objects'], f'list template names missing object {v}')
    return shape


if __name__ == '__main__':
    page, refs, row0 = build()
    shape = check_settings_page(page)
    print(len(page), 'bytes;', len(refs), 'private fields; row0', row0, ';', len(shape['objects']), 'objects')
