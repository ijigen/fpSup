"""Loader v3 management pages, built only from MainY5's own objects.

Five visible Sup slots share one page. The focusable first row contains
numbered page tabs, beneath the SupManager header. Each Sup uses MainY5's two-choice popup;
none of its original firmware-update or persistent-setting actions survive.
"""
from __future__ import annotations

import struct

import ft6_page as F
import manager_logo as LOGO
from ft6_page import put, u32, check

VISIBLE = 5
CAPACITY = 32
PAGE_TABS = (CAPACITY + VISIBLE - 1) // VISIBLE
NAME_SIZE, DETAIL_SIZE = 44, 24
POPUP_WIDTH, POPUP_HEIGHT = 420, 162
CONTENT_HEIGHT = 484
ENGLISH_FONT = 'Other_fontsetting'
ACCENT = 0xE03858FF                 # fpSup logo; assets/site.css documents #E03858
DARK_ACCENT = 0x4B121DFF
FOCUS, HOME_FOCUS = 'FT_Focus', 'FT_HomeFocus'
PAGE_TEXT, PAGE_KEY = 'FT_PageText', 'FT_Key'
PREVIOUS, NEXT = 10, 11
SELECT_ROW, SELECT, LIST, LIST_ITEM = 207, 1514, 1517, 1518
POPUP_TEXT = (30013, 30027, 33500)
HOME = (('SupManager', 'FT_LIST'), ('Updates', 'FT_UPDATES'),
        ('SD Card Format (Keep fpSup)', 'FT_CARD'), ('About fpSup', 'FT_ABOUT'))
UNFINISHED_HOME = {'FT_UPDATES', 'FT_CARD', 'FT_ABOUT'}
INFO = {
    'FT_UPDATES': ('Updates', 'Check for updates', 'Scan QR to update'),
    'FT_CARD': ('SD Card Format', 'Keep fpSup'),
    'FT_ABOUT': ('About fpSup', 'Loader v3', 'fpSup QR Code',
                 'https://ijigen.github.io/fpSup/'),
}
UNFINISHED_INFO = {'FT_UPDATES': {1, 2}, 'FT_CARD': {1}, 'FT_ABOUT': {2}}


def var(part, k):
    return f'FT_{part}{k}'


class Management(F.Page):
    def __init__(self, img, pool):
        super().__init__(img, pool)
        header = F.A.parse_header(F.A.Record(0, self.recs[0].to_bytes()), pool.text)
        gi = [i for i, r in enumerate(self.recs) if r.tag == 0x1000B]
        self.group_budget = {id(self.raw[i]): header['groups'][n] for n, i in enumerate(gi)}
        self.drop_rows(self.rows)
        self.tab_bar()

    def clone(self, root, preserve=False):
        sub = F.SZ.subtree(self.objs, root)
        a, b = F.SZ.span(self.recs, self.objs, sub, root)
        mapping = {old: old if preserve else self.take_id() for old in sorted(sub)}
        out = []
        for src in self.raw[a:b]:
            r = bytearray(src)
            for off, kind in F.P.typed_fields(bytes(r), self.pool, self.schemas):
                if kind == 'obj' and u32(r, off) in mapping:
                    put(r, off, mapping[u32(r, off)])
            if u32(r, 0) == 0x10008:
                for off in F.Lab.LIST_TEMPLATE_IDS:
                    if u32(r, off) in mapping:
                        put(r, off, mapping[u32(r, off)])
            out.append(r)
            if u32(r, 0) == 0x1000B:
                self.group_budget[id(r)] = self.group_budget[id(src)]
        return out, mapping

    def add(self, out):
        # Y5 is the final content container in MainY5: insert before END.
        at = len(self.seq) - 1
        self.seq[at:at] = out
        self.added += out
        self.groups += [self.group_budget[id(r)] for r in out if u32(r, 0) == 0x1000B]
        put(self.seq[self.ob()[F.ROWS_PARENT][0]], 16, u32(self.seq[self.ob()[F.ROWS_PARENT][0]], 16) + 1)

    def bind(self, out, owner, name, component, prop, kind=0):
        by = F.by_object(out)
        local = max(F.P.local_ids(out, by[owner]) | {0}) + 1
        r = F.Lab._binding(owner, local, name, component, prop, self.pool, self.refs, kind)
        out.insert(by[owner][-1] + 1, r)
        put(out[by[owner][0]], 8, u32(out[by[owner][0]], 8) + 1)

    def bind_sub(self, out, owner, name, component, prop, subindex):
        by = F.by_object(out)
        local = max(F.P.local_ids(out, by[owner]) | {0}) + 1
        r = F.Lab._binding_sub(owner, local, name, component, prop, subindex,
                              self.pool, self.refs)
        out.insert(by[owner][-1] + 1, r)
        put(out[by[owner][0]], 8, u32(out[by[owner][0]], 8) + 1)

    def literal(self, r, text):
        off = F.text_field(r, self.pool, self.schemas)[0]
        self.refs = [(rec, pos, value) for rec, pos, value in self.refs
                     if rec is not r or pos != off]
        r[off + 4] = 0
        if self.pool.find(text) is None or text in self.pool.added:
            self.private(r, off, text)
        else:
            put(r, off, self.pool.find(text))

    def write(self, owner, event, order, name, value=None, source=None):
        # The same page's literal-value / control-value forms, not cross-page donors.
        if source is None:
            src = next(r for r in self.raw if F.pool_name(self, r) == 'controlAppVariable'
                       and len(r) == 46 and self.pool.text(u32(r, 36)) == 'SoftKeyboard_InputID')
        else:
            # MainY5's Save/Read QR item reads its own popup controlValue.
            src = next(r for r in self.raw if F.pool_name(self, r) == 'controlAppVariable'
                       and u32(r, 20) == 1998 and self.pool.text(u32(r, 36)) == 'CM_SaveReadSettings')
        r = bytearray(src)
        put(r, 20, owner); put(r, 24, event); put(r, 28, order)
        self.private(r, 36, name)
        if source is not None:
            put(r, 45, source)
        elif self.pool.find(str(value)) is None:
            self.private(r, 41, str(value))
        else:
            put(r, 41, self.pool.find(str(value)))
        return r

    def focus(self, owner, event, order, target):
        src = next(r for r in self.raw if F.pool_name(self, r) == 'controlFocus'
                   and u32(r, 20) == LIST_ITEM and len(r) == 44)
        r = bytearray(src)
        put(r, 20, owner); put(r, 24, event); put(r, 28, order); put(r, 40, target)
        return r

    def event(self, out, owner, key, actions):
        by = F.by_object(out)
        hit = next((i for i in by[owner] if u32(out[i], 0) == 0x10006
                    and F.pool_name(self, out[i]) == 'keyEvent'
                    and self.pool.text(u32(out[i], 20)) == key), None)
        if hit is None:
            src = next(r for r in out if u32(r, 0) == 0x10006 and u32(r, 24) == owner
                       and F.pool_name(self, r) == 'keyEvent' and self.pool.text(u32(r, 20)) == 'Right')
            ev = bytearray(src)
            put(ev, 20, self.pool.find(key))
            put(ev, len(ev) - 4, {'Left': 0x25, 'Right': 0x27}[key])
            put(ev, 28, max(F.P.local_ids(out, by[owner]) | {0}) + 1)
            hit = by[owner][-1] + 1
            out[hit:hit] = [ev]
            put(out[by[owner][0]], 8, u32(out[by[owner][0]], 8) + 1)
        ev = out[hit]
        acts = actions(u32(ev, 28))
        out[hit + 1:hit + 1 + u32(ev, 16)] = acts
        put(ev, 16, len(acts))

    def root_focus(self, name):
        for r in self.seq:
            for off, kind in F.P.typed_fields(bytes(r), self.pool, self.schemas):
                if kind in ('str', 'text') and self.pool.text(u32(r, off)) == 'MENU_Level1':
                    self.private(r, off, name)

    def append_action(self, out, owner, kind, event_name, make):
        at = next(i for i in F.by_object(out)[owner] if u32(out[i], 0) == 0x10006
                  and F.pool_name(self, out[i]) == kind
                  and (u32(out[i], 28) == event_name if isinstance(event_name, int)
                       else self.pool.text(u32(out[i], 20)) == event_name))
        ev = out[at]
        end = at + 1 + u32(ev, 16)
        order = max((u32(r, 28) for r in out[at + 1:end]), default=0) + 1
        out.insert(end, make(u32(ev, 28), order))
        put(ev, 16, u32(ev, 16) + 1)

    def finish(self, base=F.BASE):
        theme(self.seq, self.pool)
        live = {id(r) for r in self.seq}
        self.refs = [(r, o, t) for r, o, t in self.refs if id(r) in live]
        return super().finish(base)


def theme(seq, pool):
    """Recolour yellow paint and its animation keys in these private pages only."""
    for r in seq:
        if u32(r, 0) == 0x10005:
            for old, new in ((0xFFDD44FF, ACCENT), (F.Y_COLOUR, DARK_ACCENT)):
                at = bytes(r).find(struct.pack('>I', old), 28)
                if at >= 0:
                    put(r, at, new)


def colour_clips(pg):
    rgb = tuple((ACCENT >> s & 255) / 255 for s in (24, 16, 8))
    dim = tuple((DARK_ACCENT >> s & 255) / 255 for s in (24, 16, 8))
    for r in pg.seq:
        if u32(r, 0) != 0x1000A:
            continue
        at = 28
        properties = []
        for _ in range(u32(r, 12)):
            n, kind, _component, name, channel = struct.unpack_from('>5I', r, at)
            if kind == 1 and pg.pool.text(name) == 'color' and channel < 3:
                properties.append((channel, [at + 26 + 10 * k for k in range(n)]))
            at += 20 + 10 * n
        # Detect a yellow triplet, including the SYSTEM header's animation.
        blue = next((offsets for channel, offsets in properties if channel == 2), [])
        green = next((offsets for channel, offsets in properties if channel == 1), [])
        if any(abs(struct.unpack_from('>f', r, off)[0] - 0.266667) < 0.00001 for off in blue) and any(
                abs(struct.unpack_from('>f', r, off)[0] - 0.866667) < 0.00001 for off in green):
            for channel, offsets in properties:
                for off in offsets:
                    v = struct.unpack_from('>f', r, off)[0]
                    oldbright = (1, 0.866667, 0.266667)[channel]
                    struct.pack_into('>f', r, off, rgb[channel] if abs(v - oldbright) < 0.00001 else dim[channel])


def label_text(pg, template, owner, size, color, width, height):
    font = pg.pool.find(ENGLISH_FONT)
    check(font is not None, 'stock English font setting missing')
    t = F.styled_text(template, owner, size, color, (0, 0, width, height),
                      font=font)
    # A valid initial string is required before the native text component can
    # accept its app-variable binding. Offset zero is not a text-pool entry.
    pg.literal(t, ' ')
    put(t, 28, u32(t, 28) | 0x10)       # horz-align = left
    t[45:45] = struct.pack('>I', 1)     # after text, font-setting and size, before colour
    put(t, 4, len(t))
    return t


def chrome(pg, manage=False):
    """Use MainY5's Footer text frame and typography for the private footer."""
    by = pg.ob()
    original = pg.seq[F.comp(pg.seq, by[19499], 'objectBase', pg.pool)]
    struct.pack_into('>f', original, 32, 3000.0)
    # FooterSelect is animated by the native popup: move the whole stock box.
    original = pg.seq[F.comp(pg.seq, by[31], 'objectBase', pg.pool)]
    check(u32(original, 28) == 0x42, 'FooterSelect size form')
    original[:] = original[:28] + struct.pack('>I2f', 0x43, 3000.0, 0.0) + original[32:]
    put(original, 4, len(original))
    fields = [('FT_OK', 28, 510), ('FT_Version', 901, 107)]
    if manage:
        fields.append(('FT_RightFooter', 550, 474))
    for name, x, w in fields:
        oid = pg.take_id()
        o = bytearray(pg.raw[pg.src[19499][0]])
        put(o, 20, oid); put(o, 8, 2); put(o, 16, 0)
        b = F.owned(pg.raw[F.comp(pg.raw, pg.src[19499], 'objectBase', pg.pool)], oid)
        struct.pack_into('>4f', b, 32, float(x), 31.0 if name == 'FT_Version' else 23.0,
                         float(w), 54.0)
        if name == 'FT_Version':
            foreground(b)
            render_group(b)
        if name != 'FT_Version':
            t = F.owned(pg.raw[F.comp(pg.raw, pg.src[19499], 'drawText', pg.pool)], oid)
            pg.literal(t, ' ')
            struct.pack_into('>f', t, len(t) - 8, float(w))
        else:
            t = pg.raw[F.comp(pg.raw, pg.src[POPUP_TEXT[0]], 'drawText', pg.pool)]
            t = label_text(pg, t, oid, 32, 0x9A9A9AFF, w, 54)
        out = [o, b, t]
        pg.bind(out, oid, name, u32(t, 24), 'text')
        at = pg.ob()[19499][-1] + 1
        pg.seq[at:at] = out; pg.added += out
        put(pg.seq[pg.ob()[72][0]], 16, u32(pg.seq[pg.ob()[72][0]], 16) + 1)


def remap_focus(pg, out, name):
    for r in out:
        for off, kind in F.P.typed_fields(bytes(r), pg.pool, pg.schemas):
            if kind in ('str', 'text') and pg.pool.text(u32(r, off)) == 'MENU_Level1':
                pg.private(r, off, name)


def jump_row(pg, k, title, request=None, focus=HOME_FOCUS, disabled=False):
    out, m = pg.clone(F.KEEP_ROW, preserve=k == 0)
    by = F.by_object(out)
    root = m[F.KEEP_ROW]
    # First row has no position property; use Y5_2's positioned container.
    base = F.owned(pg.raw[F.comp(pg.raw, pg.src[pg.rows[1]], 'objectBase', pg.pool)], root)
    struct.pack_into('>f', base, 36, 81.0 * k)
    out[F.comp(out, by[root], 'objectBase', pg.pool)] = base
    remap_focus(pg, out, focus)
    if focus != FOCUS:
        pg.append_action(out, m[F.ROW_ITEM], 'focusEvent', 'FocusOn',
                         lambda ev, order: pg.write(m[F.ROW_ITEM], ev, order, PAGE_KEY, 30))
    name = m[F.ROW_NAME]
    tr = out[F.comp(out, F.by_object(out)[name], 'drawText', pg.pool)]
    template = pg.raw[F.comp(pg.raw, pg.src[POPUP_TEXT[0]], 'drawText', pg.pool)]
    tr[:] = label_text(pg, template, name, NAME_SIZE,
                      0x888888FF if disabled else 0xFFFFFFFF, 870, 54)
    pg.literal(tr, title)
    if disabled:
        # MainY5's SelectLock is its native disabled-row control. Keep focus
        # and Menu navigation, but lock confirmation and hide entry affordances.
        lock = out[F.comp(out, F.by_object(out)[m[3452]], 'controlValue', pg.pool)]
        check(u32(lock, 28) == 0, 'Jump SelectLock default form changed')
        lock[:] = lock[:28] + struct.pack('>If', 4, 1.0)
        put(lock, 4, len(lock))
        for old in (10062, 3457):
            draw = out[F.comp(out, F.by_object(out)[m[old]], 'drawImage', pg.pool)]
            put(draw, 32, pg.pool.find('blank'))
        # SelectLock's Off interval can replay while entering/focusing a row.
        # Both ends stay grey so no stock animation revives unfinished labels.
        for clip in out:
            if u32(clip, 0) != 0x1000A or u32(clip, 20) != name:
                continue
            at = 28
            for _ in range(u32(clip, 12)):
                n, kind, _comp, prop, channel = struct.unpack_from('>5I', clip, at)
                if kind == 1 and pg.pool.text(prop) == 'color' and channel < 3:
                    for j in range(n):
                        struct.pack_into('>f', clip, at + 26 + 10 * j, 136 / 255)
                at += 20 + 10 * n
        request = None
    for key in ('Right', 'OK'):
        def actions(event):
            if request is None:
                return []
            r = bytearray(pg.raw[F.row_actions_raw(pg, F.ROW_ITEM, 'Right')])
            put(r, 20, m[F.ROW_ITEM]); put(r, 24, event); put(r, 28, 1)
            pg.request(r, request)
            return [r]
        pg.event(out, m[F.ROW_ITEM], key, actions)
    return out, m


def menu_return(pg, out):
    for r in out:
        if F.pool_name(pg, r) == 'controlAppState' and len(r) != 41:
            # Menu exit -> this private page's explicit Return transition.
            if u32(r, 20) not in (1,):
                new = bytearray(pg.raw[F.row_actions_raw(pg, F.ROW_ITEM, 'Right')])
                for off in (20, 24, 28): put(new, off, u32(r, off))
                pg.request(new, 'Return')
                r[:] = new


NATIVE_POPUP_WIDTH = 227      # v4: the stock On / Off popup (MainB2's 音訊記錄), texts right-aligned to x 965
NATIVE_KEYS = ('0081', '0080')
NATIVE_STATUS_RIGHT = 855     # v4: R's right edge, left of the On / Off column (965)  # v4: Enable / Disable as the stock .nloc On / Off, localized by the GUI


TOGGLE_KEYS = (('0080', 'TOff'), ('0081', 'TOn'))     # .nloc Off / On (B2_6.cvm)
VALUE_RIGHT = 965.0          # the stock pages' value column ends here (MainB2's 開啟 / 關閉)


def stock_text(pg, out, beside, at, donor, key, show, right=False, size=None):
    """A sibling of object `beside`: the stock text `key` (a .nloc key in the
    pool, so the GUI localizes it) at `at` (x, y; right=True: x is its right
    edge), drawn by the stock
    drawText of stock object `donor` as it is in the image (its font setting,
    size, colour), its opacity bound to `show`."""
    by = F.by_object(out)
    oid = pg.take_id()
    head = bytearray(out[by[beside][0]])
    put(head, 20, oid); put(head, 8, 2); put(head, 16, 0)
    base = F.owned(out[F.comp(out, by[beside], 'objectBase', pg.pool)], oid)
    t = F.owned(pg.raw[F.comp(pg.raw, pg.src[donor], 'drawText', pg.pool)], oid)
    # fields in mask-bit order (ft6_page.styled_text): text = id + 1 byte (1: a
    # .nloc key the GUI localizes, 0: a literal), then horz-align (bit 4) when
    # there is no font / size (bits 1, 2); the record ends with its rect
    mask, off = u32(t, 28), F.text_field(t, pg.pool, pg.schemas)[0]
    check(mask & 0x6 == 0 and t[off + 4] == 1, 'stock drawText form (a key, no font / size)')
    check(pg.pool.find(key) is not None, f'stock text {key} is not in the pool')
    put(t, off, pg.pool.find(key))                      # the key; the flag stays 1
    if right:
        check(mask & 0x10, 'stock drawText without its horz-align field')
        put(t, off + 5, 3)                              # right-aligned, as the stock value
    # the stock rect (its size is what the stock text is laid out in), or `size`
    w, h = size or struct.unpack_from('>2f', t, len(t) - 8)
    struct.pack_into('>2f', t, len(t) - 8, w, h)
    struct.pack_into('>4f', base, 32, at[0] - w if right else at[0], at[1], w, h)
    at = by[beside][-1] + 1
    out[at:at] = [head, base, t]
    parent = u32(head, 24)
    ph = out[F.by_object(out)[parent][0]]
    put(ph, 16, u32(ph, 16) + 1)
    pg.bind(out, oid, show, u32(base, 24), 'opacity', 1)
    return oid


def native_text(pg, owner, donor, key, w, h):
    """The stock drawText of object `donor` for `owner`, showing the .nloc key
    `key` (text id + flag 1: the GUI draws it in the camera's language) in a
    w x h rect; the stock font setting, size and alignment stay."""
    t = F.owned(pg.raw[F.comp(pg.raw, pg.src[donor], 'drawText', pg.pool)], owner)
    off = F.text_field(t, pg.pool, pg.schemas)[0]
    check(u32(t, 28) & 0x6 == 0 and t[off + 4] == 1, 'stock drawText form (a key, no font / size)')
    check(pg.pool.find(key) is not None, f'stock text {key} is not in the pool')
    put(t, off, pg.pool.find(key))
    struct.pack_into('>2f', t, len(t) - 8, float(w), float(h))
    return t


def sup_row(pg, k, key_shift=0, dots=True, native=False):
    """`key_shift` 1 (loader v4, slot 0 exists): the popup's FT_Key is 20 + k + 1, so slot 0's is not 20.
    `dots` False (loader v4): no ... -- it means "enters a page", and these rows
    open a popup (user 2026-10-24: "...是只能進入用的").
    `native` (loader v4): the popup is the stock On / Off popup -- its size,
    and Enable / Disable as the stock On / Off texts, localized (user 2026-10-24)."""
    W = NATIVE_POPUP_WIDTH if native else POPUP_WIDTH
    out, m = pg.clone(SELECT_ROW)
    # Keep the popup, lock and paint, remove the native update routing and
    # the parent's camera/EVF exclusion objects.
    gone = {m[o] for root in (33251, 33499) for o in F.SZ.subtree(pg.objs, root)} | {
        m[33502], m[33506], m[33495]}
    original = out
    out = []
    owner = 0
    for r in original:
        if u32(r, 0) == 0x10003: owner = u32(r, 20)
        if owner not in gone and (owner != m[SELECT_ROW] or u32(r, 0) in (0x10003, 0x10004)):
            out.append(r)
    by = F.by_object(out)
    for o, idx in by.items():
        head = out[idx[0]]
        lost = sum(u32(r, 0) == 0x10003 and u32(r, 24) == o and u32(r, 20) in gone for r in original)
        put(head, 16, u32(head, 16) - lost)
        if o == m[SELECT_ROW]: put(head, 8, 1)
    # Remove width-change event + its animation, native FocusOn's submenu
    # dispatch and variable, and List's forwarding to the removed JumpEvent.
    cleaned, i = [], 0
    while i < len(out):
        r = out[i]
        if u32(r, 0) == 0x1000B and pg.pool.text(u32(r, 20)) == 'submenu_width_NoIcon':
            i += 1; continue
        if u32(r, 0) != 0x10006:
            cleaned.append(r); i += 1; continue
        acts = out[i + 1:i + 1 + u32(r, 16)]
        if F.pool_name(pg, r) == 'appVariableChangeEvent' and pg.pool.text(u32(r, 36)) == 'submenu_width':
            put(cleaned[F.by_object(cleaned)[m[SELECT]][0]], 8,
                u32(cleaned[F.by_object(cleaned)[m[SELECT]][0]], 8) - 1)
            i += 1 + len(acts); continue
        keep = [a for a in acts if not (F.pool_name(pg, a) == 'controlAppState'
                or (F.pool_name(pg, a) == 'controlAppVariable' and
                    (len(a) <= 36 or pg.pool.text(u32(a, 36)) != 'MENU_Level1'))
                or any(kind == 'obj' and u32(a, off) in gone for off, kind in F.P.typed_fields(bytes(a), pg.pool, pg.schemas)))]
        put(r, 16, len(keep)); cleaned += [r] + keep
        i += 1 + len(acts)
    out = cleaned
    # The donor scrolls firmware-version labels with position/rect clips.
    # Those clips run again when its list value changes and would move our
    # fixed labels away after Up/Down. Keep the native list/cursor animations.
    texts = {m[o] for o in POPUP_TEXT}
    clips = [r for r in out if u32(r, 0) == 0x1000A and
             (u32(r, 20) in texts or u32(r, 20) == m[30019]
              or (u32(r, 20) == m[LIST] and u32(r, 24) == 10)
              or u32(r, 20) in {m[o] for o in (30022, 30023, 30028)})]
    out = [r for r in out if not any(r is clip for clip in clips)]
    for clip in clips:
        head = out[F.by_object(out)[u32(clip, 20)][0]]
        put(head, 8, u32(head, 8) - 1)
    by = F.by_object(out)
    base = out[F.comp(out, by[m[SELECT_ROW]], 'objectBase', pg.pool)]
    struct.pack_into('>f', base, 36, 81.0 * k)
    remap_focus(pg, out, FOCUS)
    # Popup selection starts at next boot's current state.
    cv = out[F.comp(out, by[m[SELECT]], 'controlValue', pg.pool)]
    pg.bind(out, m[SELECT], var('Default', k), u32(cv, 24), 'value', 1)
    lock = out[F.comp(out, F.by_object(out)[m[1515]], 'controlValue', pg.pool)]
    pg.bind(out, m[1515], var('Lock', k), u32(lock, 24), 'value', 1)
    # tab-index = 0 does not keep Up/Down out of an empty row (camera,
    # 2026-10-21); is-visible = 0 does for MainY5's closed popup.
    if native:
        row_visible(pg, var('Visible', k), m[SELECT_ROW])
    else:                                               # v3's ALLSUPS.BIN: its bytes as built
        rootbase = out[F.comp(out, F.by_object(out)[m[SELECT_ROW]], 'objectBase', pg.pool)]
        pg.bind(out, m[SELECT_ROW], var('Visible', k), u32(rootbase, 24), 'opacity', 1)
        pg.bind(out, m[SELECT_ROW], var('Visible', k), u32(rootbase, 24), 'is-visible', 1)
        selectbase = out[F.comp(out, F.by_object(out)[m[SELECT]], 'objectBase', pg.pool)]
        pg.bind(out, m[SELECT], var('Visible', k), u32(selectbase, 24), 'tab-index', 1)
    lb = out[F.comp(out, F.by_object(out)[m[LIST]], 'objectBase', pg.pool)]
    check(u32(lb, 28) == 0xD3, 'MainY5 popup base form')
    # Position beside this Sup, keeping both choices above the footer.
    popup_y = min(81.0 * k, CONTENT_HEIGHT - POPUP_HEIGHT)
    struct.pack_into('>4f', lb, 32, 1024.0 - W, popup_y - 81.0 * k,
                     float(W), float(POPUP_HEIGHT))
    cv = out[F.comp(out, F.by_object(out)[m[LIST]], 'controlValue', pg.pool)]
    check(u32(cv, 28) == 0xA and len(cv) == 40, 'MainY5 List limit form')
    struct.pack_into('>f', cv, 32, 1.0)
    pg.bind(out, m[LIST], var('Default', k), u32(cv, 24), 'value', 1)
    # Native Audio pattern: OK confirms; Right requests settings from Enable.
    pg.event(out, m[LIST_ITEM], 'OK', lambda event: [
        pg.write(m[LIST_ITEM], event, 1, var('Choice', k), source=m[LIST]),
        pg.focus(m[LIST_ITEM], event, 2, m[SELECT])])
    pg.event(out, m[LIST_ITEM], 'Right', lambda event: [
        pg.write(m[LIST_ITEM], event, 1, var('Choice', k), value=2),
        pg.focus(m[LIST_ITEM], event, 2, m[SELECT])])
    for event, value in ((6, 0), (7, 1)):
        pg.append_action(out, m[LIST], 'controlValueEvent', event,
                         lambda ev, order, value=value: pg.write(m[LIST], ev, order, var('Selected', k), value))
    pg.append_action(out, m[LIST_ITEM], 'focusEvent', 'FocusOn',
                     lambda ev, order: pg.write(m[LIST_ITEM], ev, order, PAGE_KEY, 20 + k + key_shift))
    pg.append_action(out, m[LIST_ITEM], 'focusEvent', 'FocusOff',
                     lambda ev, order: pg.write(m[LIST_ITEM], ev, order, PAGE_KEY, 20))
    text_w = 965.0 - (1024.0 - W) - 36.0 if native else W - 120   # native: right-aligned to 965
    for old, label, key in zip(POPUP_TEXT[:2], ('Enable', 'Disable'), NATIVE_KEYS):
        by = F.by_object(out)
        ti = F.comp(out, by[m[old]], 'drawText', pg.pool)
        if native:
            tr = native_text(pg, m[old], old, key, text_w, 58)
        else:
            tr = label_text(pg, out[ti], m[old], NAME_SIZE, 0xFFFFFFFF, W - 120, 58)
            pg.literal(tr, label)
        out[ti] = tr
        # Text01's stock anchor moves its label outside the narrow QR column.
        # Use this same page's plain Name frame inside the compact popup.
        bi = F.comp(out, by[m[old]], 'objectBase', pg.pool)
        b = F.owned(pg.raw[F.comp(pg.raw, pg.src[30021], 'objectBase', pg.pool)], m[old])
        struct.pack_into('>4f', b, 32, 36.0, 10.0, float(text_w), 58.0)
        foreground(b)  # keep the native cursor fill behind the choice label
        out[bi] = b
    # Resize the donor's item/background frames with the outer List.
    for old in (LIST_ITEM, 30024, 30025, 30026, 30022, 30023, 30028):
        by = F.by_object(out)
        b = out[F.comp(out, by[m[old]], 'objectBase', pg.pool)]
        size_off = 40 if u32(b, 28) & 1 else 32
        struct.pack_into('>2f', b, size_off, float(W), 81.0 if old == LIST_ITEM else 79.0)
        for i in by[m[old]]:
            r = out[i]
            if F.pool_name(pg, r) == 'drawRect':
                struct.pack_into('>f', r, len(r) - 8, float(W))
    if not dots:                                    # 1536 = font_G_3dot
        r = out[F.comp(out, F.by_object(out)[m[1536]], 'drawImage', pg.pool)]
        put(r, 32, pg.pool.find('blank'))
    arrow = out[F.comp(out, F.by_object(out)[m[30019]], 'objectBase', pg.pool)]
    struct.pack_into('>f', arrow, 32, float(W - 52))
    pg.bind(out, m[30019], var('More', k), u32(arrow, 24), 'opacity', 1)
    selected_bg = out[F.comp(out, F.by_object(out)[m[30023]], 'drawRect', pg.pool)]
    put(selected_bg, 32, 0x666666FF)
    # Centre the name vertically. Its grey version follows the name with a
    # small gap on the same baseline; status is a separate right-aligned field.
    name = m[30021]
    by = F.by_object(out)
    ti = F.comp(out, by[name], 'drawText', pg.pool)
    # label_text needs the donor's compact text form, not its styled replacement.
    template = pg.raw[F.comp(pg.raw, pg.src[POPUP_TEXT[0]], 'drawText', pg.pool)]
    tr = label_text(pg, template, name, NAME_SIZE, 0xFFFFFFFF, 600, 46)
    out[ti] = tr
    pg.bind(out, name, var('N', k), u32(tr, 24), 'text')
    b = out[F.comp(out, F.by_object(out)[name], 'objectBase', pg.pool)]
    struct.pack_into('>4f', b, 32, 49.0, 16.0, 600.0, 46.0)
    # New text objects use this page's Name object and its native drawText form.
    # native (v4): the right column is the stock On / Off (below), so no green
    # E; R (Unload on restart ...) is the name's size, ending left of it
    # (user 2026-10-24)
    parts = (('G', 0x8A8A8AFF, 49, 16, 600), ('V', 0x9A9A9AFF, 49, 30, 400),
             ('R', 0xFF453AFF, 460, 31, 404), ('E', 0x30D158FF, 460, 31, 404))
    if native:
        # no V: v4 shows no version, and its x binding ('position' on VersionX,
        # one per slot) cost every key on the page (a bound position re-lays out;
        # camera A/B 2026-10-24 on the fpSup page's popups)
        parts = parts[:1] + (('R', 0xFF453AFF, NATIVE_STATUS_RIGHT - 500, 16, 500),)
    for part, color, x, y, w in parts:
        big = part == 'G' or (native and part == 'R')
        by = F.by_object(out); oid = pg.take_id()
        o = bytearray(out[by[name][0]])
        put(o, 20, oid); put(o, 8, 2); put(o, 16, 0)
        b = F.owned(out[F.comp(out, by[name], 'objectBase', pg.pool)], oid)
        struct.pack_into('>4f', b, 32, float(x), float(y), float(w),
                         46.0 if big else 32.0 if part == 'V' else 26.0)
        # Native text mask 0x40000003 includes horizontal alignment. Build a
        # literal text component from the language page's well-tested form.
        text = bytearray(template)
        put(text, 24, u32(tr, 24)); put(text, 32, 0); text[36] = 0
        t = label_text(pg, text, oid, NAME_SIZE if big else 26 if part == 'V' else DETAIL_SIZE,
                       color, w, 46 if big else 32 if part == 'V' else 28)
        if part in ('R', 'E'):
            put(t, 45, 3)
        at = F.by_object(out)[name][-1] + 1
        out[at:at] = [o, b, t]
        pg.bind(out, oid, var(part, k), u32(t, 24), 'text')
        if native and part in ('G', 'R'):
            # drawn only when it says something: an empty text object still costs
            # every redraw (camera A/B 2026-10-24: Render 33 -> 24 ms with these hidden)
            # opacity only: an is-visible text object, once hidden, is never drawn again (camera)
            pg.bind(out, oid, var(part + 'Show', k), u32(b, 24), 'opacity', 1)
        if part == 'V':
            pg.bind_sub(out, oid, var('VersionX', k), u32(b, 24), 'position', 0)
        put(out[F.by_object(out)[m[SELECT]][0]], 16, u32(out[F.by_object(out)[m[SELECT]][0]], 16) + 1)
    if native:                                      # the stock On / Off, localized: FT_TOff<k> / FT_TOn<k>
        for key, group in TOGGLE_KEYS:
            stock_text(pg, out, name, (VALUE_RIGHT, 16.0), 30021, key, var(group, k), right=True)
    def back(event):
        r = bytearray(pg.raw[F.row_actions_raw(pg, F.ROW_ITEM, 'Right')])
        put(r, 20, m[SELECT]); put(r, 24, event); put(r, 28, 1)
        pg.request(r, 'Return')
        return [r]
    pg.event(out, m[SELECT], 'Menu', back)
    menu_return(pg, out)
    return out, m


def build_home(img, pool):
    pg = Management(img, pool)
    manager_header(pg, 'fpSUP', legacy_logo=True)
    for k, (title, request) in enumerate(HOME):
        out, _ = jump_row(pg, k, title, request, disabled=request in UNFINISHED_HOME)
        pg.add(out)
    pg.root_focus(HOME_FOCUS)
    chrome(pg)
    colour_clips(pg)
    return pg.finish()


def plain_object(pg, parent, x, y, w, h, text=None, size=44, color=0xFFFFFFFF):
    """MainY5's own Name object and tab rectangle, without foreign controllers."""
    oid = pg.take_id()
    head = bytearray(pg.raw[pg.src[F.ROW_NAME][0]])
    put(head, 20, oid); put(head, 24, parent)
    put(head, 8, 1 if text is None else 2); put(head, 16, 0)
    base = F.owned(pg.raw[F.comp(pg.raw, pg.src[F.ROW_NAME], 'objectBase', pg.pool)], oid)
    struct.pack_into('>4f', base, 32, float(x), float(y), float(w), float(h))
    out = [head, base]
    if text is not None:
        template = pg.raw[F.comp(pg.raw, pg.src[POPUP_TEXT[0]], 'drawText', pg.pool)]
        draw = label_text(pg, template, oid, size, color, w, h)
        pg.literal(draw, text)
        out.append(draw)
    return out, oid


def row_visible(pg, name, row):
    """`name` = 0 / 1 hides / shows `row` through its is-visible, the way MainY5
    does it: a watcher that is always visible (a child of the page root, no
    paint) holds the variable in a controlValue, and its value events change the
    row's property (stock: 2816 changePropertyByControl is-visible, no variable
    bound to is-visible).  Bound on the row itself, the row hid and never came
    back -- paging back from a one-row page showed one row (user 2026-11-10);
    a hidden text object likewise (camera 2026-10-24).  The watcher starts at 1,
    the row's own state, so 0 is a change whatever the engine does on building."""
    raw, pool = pg.raw, pg.pool
    out, oid = plain_object(pg, 1, 0, 0, 0, 0)
    lock = pg.src[1515]                                 # SelectLock: value, == 0, == 1
    check(u32(raw[lock[0]], 8) == 4, 'SelectLock components')
    cv = F.owned(raw[F.comp(raw, lock, 'controlValue', pool)], oid)
    check(len(cv) == 32 and u32(cv, 28) == 0, 'SelectLock controlValue form')
    cv[:] = cv[:28] + struct.pack('>If', 4, 1.0)        # value = 1 (stock's 36-byte mask-4 form)
    put(cv, 4, len(cv))
    events = [bytearray(raw[i]) for i in lock if u32(raw[i], 0) == 0x10006]
    check([(len(e), u32(e, 32), e[36:]) for e in events]
          == [(40, 1, struct.pack('>I', 0x13)), (44, 3, struct.pack('>If', 0x13, 1.0))],
          'SelectLock value events: == 0, == 1')
    vis = pool.find('is-visible')
    donor = {len(r): r for r in raw if len(r) in (50, 55) and u32(r, 0) == 0x10009
             and F.pool_name(pg, r) == 'changePropertyByControl' and u32(r, 45) == vis
             and pool.text(u32(r, 40)) == 'objectBase'}
    check(len(donor) == 2 and u32(donor[50], 32) == 0x0B and u32(donor[55], 32) == 0x1B
          and pool.text(u32(donor[55], 50)) == '1', 'MainY5 is-visible 0 / 1 actions')
    out += [cv]
    put(out[0], 8, 2)
    for ev, size in zip(events, (50, 55)):              # == 0: hidden; == 1: shown
        act = bytearray(donor[size])
        put(ev, 24, oid); put(ev, 16, 1)
        put(act, 20, oid); put(act, 24, u32(ev, 28)); put(act, 28, 1); put(act, 36, row)
        out += [ev, act]
        put(out[0], 8, u32(out[0], 8) + 1)
    pg.bind(out, oid, name, u32(cv, 24), 'value', 1)    # last, as SelectLock's FT_Lock
    at = next(i for i, r in enumerate(pg.seq) if u32(r, 0) == 0x10003 and u32(r, 24) == 1)
    pg.seq[at:at] = out; pg.added += out
    put(pg.seq[pg.ob()[1][0]], 16, u32(pg.seq[pg.ob()[1][0]], 16) + 1)


def fill_rect(pg, owner, color, w, h):
    draw = F.owned(pg.raw[F.comp(pg.raw, pg.src[F.Y_TABS[0]], 'drawRect', pg.pool)], owner)
    # Explicit native do-fill for the brand mark and tab backing.
    draw[:] = draw[:28] + struct.pack('>III4f', 0x203, color, 1, 0.0, 0.0, float(w), float(h))
    put(draw, 4, len(draw))
    return draw


def move_hidden(base):
    """Move stock animated chrome aside without changing its event routing."""
    mask = u32(base, 28)
    if mask & 1:
        struct.pack_into('>f', base, 32, 3000.0)
    else:
        base[:] = base[:28] + struct.pack('>I2f', mask | 1, 3000.0, 0.0) + base[32:]
        put(base, 4, len(base))


def foreground(base):
    """Place fixed chrome in front of the donor's animated black backing."""
    mask = u32(base, 28)
    check(not mask & 0x10, 'fixed chrome already has a transform origin')
    at = 32 + sum(w for bit, w in ((1, 8), (2, 8), (4, 4), (8, 8)) if mask & bit)
    base[at:at] = struct.pack('>3f', 0.0, 0.0, -10.0)
    put(base, 28, mask | 0x10)
    put(base, 4, len(base))


def render_group(base):
    """Keep fixed artwork in its own native redraw group."""
    mask = u32(base, 28)
    check(not mask & 0x1000, 'fixed chrome already has a render group')
    put(base, 28, mask | 0x1000)
    base += struct.pack('>I', 1)
    put(base, 4, len(base))


V4_TITLE_Y = 18          # the v4 pages' title, 5 px lower than v3's 13 (user 2026-10-24)


def manager_header(pg, title_text='SupManager', head_var=None, title_y=13, legacy_logo=False):
    """`head_var` (loader v4): a grey backing behind the header, its opacity
    that variable -- the core sets it while focus is on the hidden stock tab
    bar (object 55), which otherwise shows no highlight at all."""
    # Keep fixed chrome outside the donor's animated category header. Its
    # focus/key controllers remain in place, but its paint is moved aside.
    for owner in (56,):
        move_hidden(pg.seq[F.comp(pg.seq, pg.ob()[owner], 'objectBase', pg.pool)])
    out, group = plain_object(pg, 1, 0, 0, 1024, 99)
    foreground(out[1])
    render_group(out[1])
    logo = LOGO.layers(legacy_logo)                     # v3: its 31 layers, unchanged bytes
    put(out[0], 16, len(logo) + 1)
    lit = []
    if head_var is not None:
        # A sibling before the header group, not its child: as the group's
        # first child it painted over the logo and title (camera, 2026-10-21).
        lit, owner = plain_object(pg, 1, 0, 0, 1024, 99)
        lit.append(fill_rect(pg, owner, 0x444444FF, 1024, 99)); put(lit[0], 8, 2)
        pg.bind(lit, owner, head_var, u32(lit[1], 24), 'opacity', 1)
    for name, color, _blob in logo:
        layer, owner = plain_object(pg, group, 28, 16, LOGO.WIDTH, LOGO.HEIGHT)
        draw = F.owned(pg.raw[F.comp(pg.raw, pg.src[19495], 'drawImage', pg.pool)], owner)
        draw[:] = draw[:28] + struct.pack('>IIII4f', 0x87, 0, 1, color,
                                         0.0, 0.0, float(LOGO.WIDTH), float(LOGO.HEIGHT))
        put(draw, 4, len(draw)); pg.private(draw, 32, name)
        layer.append(draw); put(layer[0], 8, 2)
        out += layer
    title, _ = plain_object(pg, group, 104, title_y, 800, 62, title_text, 50)
    out += title
    out = lit + out
    at = next(i for i, r in enumerate(pg.seq) if u32(r, 0) == 0x10003 and u32(r, 24) == 1)
    pg.seq[at:at] = out; pg.added += out
    put(pg.seq[pg.ob()[1][0]], 16, u32(pg.seq[pg.ob()[1][0]], 16) + 1 + bool(lit))


def page_tabs(pg, out, parent):
    """Stock-sized numbered tabs, driven by the existing paging callback.

    The full strip retains MainY5's own focus and key routing. Only its paint
    uses new native objects; no B4 focus/settings controllers are imported.
    """
    added, focus_backings, dark_backings = [], [], []
    for k in range(1, PAGE_TABS + 1):
        tab, wrapper = plain_object(pg, parent, 0, 0, 1024, 79)
        base = tab[1]
        pg.bind(tab, wrapper, var('TabVisible', k), u32(base, 24), 'opacity', 1)
        pg.bind_sub(tab, wrapper, var('TabX', k), u32(base, 24), 'position', 0)
        pg.bind_sub(tab, wrapper, var('TabWidth', k), u32(base, 24), 'size', 0)
        for active, color in ((True, 0xFFFFFFFF), (False, 0x888888FF)):
            image = f'font_menu_MB_{k}' if active else f'FT_PAGE_DIM_{k}'
            if active:
                check(pg.pool.find(image) is not None, 'stock menu-page digit missing')
            label, owner = plain_object(pg, wrapper, 0, 12, 1024, 54,
                                         f'<!{image},CENTER>', 44, color)
            base, draw = label[1:3]
            put(draw, 45, 2)
            pg.bind_sub(label, owner, var('TabWidth', k), u32(base, 24), 'size', 0)
            pg.bind_sub(label, owner, var('TabWidth', k), u32(draw, 24), 'rect', 2)
            if active:
                pg.bind(label, owner, var('TabActive', k), u32(base, 24), 'opacity', 1)
            tab += label
        divider, owner = plain_object(pg, wrapper, 0, 0, 2, 79)
        divider.append(fill_rect(pg, owner, 0x000000FF, 2, 79)); put(divider[0], 8, 2)
        pg.bind_sub(divider, owner, var('TabWidth', k), u32(divider[1], 24), 'position', 0)
        tab += divider
        # Cursor01 already receives native Focus_On / Focus_Off visibility.
        # Its child is grey only while the pager is focused and this page is
        # active; the white active digit remains visible on content focus.
        backing, owner = plain_object(pg, 3455, 0, 0, 1024, 79)
        draw = fill_rect(pg, owner, 0x444444FF, 1024, 79)
        backing.append(draw); put(backing[0], 8, 2)
        pg.bind(backing, owner, var('TabActive', k), u32(backing[1], 24), 'opacity', 1)
        pg.bind_sub(backing, owner, var('TabX', k), u32(backing[1], 24), 'position', 0)
        pg.bind_sub(backing, owner, var('TabWidth', k), u32(draw, 24), 'rect', 2)
        focus_backings += backing
        dark, owner = plain_object(pg, parent, 0, 0, 1024, 79)
        draw = fill_rect(pg, owner, 0x222222FF, 1024, 79)
        dark.append(draw); put(dark[0], 8, 2)
        pg.bind(dark, owner, var('TabVisible', k), u32(dark[1], 24), 'opacity', 1)
        pg.bind_sub(dark, owner, var('TabX', k), u32(dark[1], 24), 'position', 0)
        pg.bind_sub(dark, owner, var('TabWidth', k), u32(draw, 24), 'rect', 2)
        dark_backings += dark
        put(tab[0], 16, 3)
        added += tab
    # Paint above the donor's animated row background. Appending after its BG
    # would put that grey background over the numbers when focus arrives.
    at = F.by_object(out)[F.ROW_NAME][0]
    out[at:at] = added
    put(out[F.by_object(out)[parent][0]], 16,
        u32(out[F.by_object(out)[parent][0]], 16) + 2 * PAGE_TABS)
    at = F.by_object(out)[3456][0]
    out[at:at] = focus_backings
    cursor = out[F.by_object(out)[3455][0]]
    put(cursor, 16, u32(cursor, 16) + PAGE_TABS)
    # Native child order paints digits before focus backing before dark fill.
    # A dark fill inside the digit wrapper would hide the sibling cursor.
    at = F.by_object(out)[3458][0]
    out[at:at] = dark_backings


def build_manage(img, pool, v4=False):
    """v4: slot 0 under the title row (six sups or fewer: no paging, FT_Title
    hides the title row), the header lights while the stock tab bar has focus
    (FT_HeadOn); returns (page, refs, slot 0's focus id)."""
    pg = Management(img, pool)
    manager_header(pg, head_var='FT_HeadOn' if v4 else None, legacy_logo=not v4, **({'title_y': V4_TITLE_Y} if v4 else {}))
    out, m = jump_row(pg, 0, ' ', focus=FOCUS)
    if v4:
        title = out[F.comp(out, F.by_object(out)[m[F.KEEP_ROW]], 'objectBase', pool)]
        for prop in ('opacity', 'is-visible'):
            pg.bind(out, m[F.KEEP_ROW], 'FT_Title', u32(title, 24), prop, 1)
    page_tabs(pg, out, m[F.ROW_ITEM])
    # Paging is not a submenu: the native Jump donor's dots and arrow are blank.
    for old in (10062, 3457):
        r = out[F.comp(out, F.by_object(out)[m[old]], 'drawImage', pool)]
        put(r, 32, pool.find('blank'))
    # Retain Cursor01's native focus animation, hiding only its left stripe.
    # The numbered tab's grey backing replaces the stripe, as on B4_1.
    move_hidden(out[F.comp(out, F.by_object(out)[m[3456]], 'objectBase', pool)])
    pg.append_action(out, m[F.ROW_ITEM], 'focusEvent', 'FocusOn',
                     lambda ev, order: pg.write(m[F.ROW_ITEM], ev, order, PAGE_KEY, 31))
    for key, code in (('Left', PREVIOUS), ('Right', NEXT)):
        pg.event(out, m[F.ROW_ITEM], key, lambda event, code=code: [pg.write(m[F.ROW_ITEM], event, 1, PAGE_KEY, code)])
    menu_return(pg, out); pg.add(out)
    row0 = 0
    for k in range(0 if v4 else 1, VISIBLE + 1):
        out, rm = sup_row(pg, k, key_shift=1 if v4 else 0, dots=not v4, native=v4); pg.add(out)
        row0 = row0 or rm[SELECT]
    pg.root_focus(FOCUS)
    if v4:
        # entered from the fpSup page's request: done, the core forgets the name
        # (fpsup_home.c home_go) before that page comes back and sees GO_VAR again
        enter_write(pg, GO_VAR, 0)
    chrome(pg, manage=True)
    colour_clips(pg)
    return pg.finish() + ((row0,) if v4 else ())


GO_VAR = 'FT_Go'          # home4_page: the fpSup page's "open this page" variable


def enter_write(pg, name, value):
    """The page's screen-enter event (the one that focuses from the focus
    variable) first writes `name` = `value`."""
    seq = pg.seq
    at = next(i for i, r in enumerate(seq) if len(r) >= 32 and u32(r, 0) == 0x10006
              and F.pool_name(pg, r) == 'screenEvent'
              and any(F.pool_name(pg, a) == 'controlFocus' for a in seq[i + 1:i + 1 + u32(r, 16)]))
    ev = seq[at]
    acts = seq[at + 1:at + 1 + u32(ev, 16)]
    focus = next(a for a in acts if F.pool_name(pg, a) == 'controlFocus')
    for a in acts:
        put(a, 28, u32(a, 28) + 1)
    w = pg.write(u32(focus, 20), u32(focus, 24), 1, name, value)
    seq.insert(at + 1, w)
    pg.added.append(w)                                  # counted in the allocation header
    put(ev, 16, u32(ev, 16) + 1)


def build_info(name, img, pool):
    pg = Management(img, pool)
    manager_header(pg, 'fpSUP', legacy_logo=True)
    for k, title in enumerate(INFO[name]):
        out, _ = jump_row(pg, k, title, focus=var('InfoFocus', 0),
                          disabled=k in UNFINISHED_INFO.get(name, set()))
        menu_return(pg, out); pg.add(out)
    pg.root_focus(var('InfoFocus', 0)); chrome(pg); colour_clips(pg)
    return pg.finish()
