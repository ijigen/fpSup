"""Loader v4's fpSup home page (FT_Y6), built from MainY5's own objects.

Layout = v3's SupManager page (manage_page.build_manage): the fpSup header,
then either six rows (six rows or fewer: no paging -- the user, 2026-10-21) or
a title row with numbered page tabs (Left/Right page while it has focus) and
five rows a page.  Slot 0 sits where the title row is; FT_Title shows the one
or the other.  A row is whatever a sup registered with svc->page_add()
(fpSup/loader-v4/sloader4.h struct sl_row); the core fills the five slots of
the current page (projects/loader-v4/DESIGN.md §14):

  name     FT_N<k>  left, white
  value    FT_A<k>  right column, grey (TOGGLE / LIST: the current choice)
  arrow    FT_Jump<k>  MainY5's More arrow and its ... (1536), shown on JUMP rows only
  popup    TOGGLE / LIST: Right/OK opens MainY5's native popup; its three
           labels FT_I<k>a..c, FT_Max<k> = choices - 1, FT_Default<k> the
           current one; OK/Right writes FT_Choice<k>
  keys     slot k's codes use j = k + 1: FT_Key 20 + j (its popup has
           focus; 20 = none), 40 + j (Right/OK on a JUMP / ACTION row)
  open     JUMP / ACTION: Right/OK write FT_Key = 40 + j and the core calls
           the row's open() (MainY5's popup opens too, behind the new page)
  locked   FT_Lock<k> = 1 only for an empty slot: a locked row's Right/OK do
           nothing at all, not even FT_Key (camera, 2026-10-21)
  hidden   FT_Visible<k> = 0 clears the row's is-visible: Up/Down skip it, as
           they skip MainY5's closed popup (tab-index = 0 did not).  A watcher
           outside the row does it (manage_page.row_visible): bound on the row
           itself, a hidden row never came back (user 2026-11-10)

v3's manage_page.py is imported, not changed: v3's ALLSUPS.BIN stays as built.
"""
from __future__ import annotations

import struct

import ft6_page as F
import manage_page as MP
from ft6_page import put, u32, check

VISIBLE = MP.VISIBLE                         # rows a page when paged
SLOTS = VISIBLE + 1                          # slot 0 (unpaged only) .. 5
POPUP_ITEMS = 3                              # MainY5's popup has three labels
# Every popup is the stock On / Off popup's size (MainB2's 音訊記錄, camera
# 2026-10-24): x 797..1024, its texts right-aligned to 965, the value column's
# edge.  Fixed: binding the popup's x / width per row cost every key ~100 ms,
# stock pages included (camera A/B 2026-10-24), and no sup has a LIST row yet.
POPUP_WIDTH = 227
TEXT_RIGHT = 965.0 - (1024.0 - POPUP_WIDTH)            # the popup texts' right edge, in the item
ITEM_HEIGHT = 81.0
POPUP_MAX_HEIGHT = POPUP_ITEMS * ITEM_HEIGHT
# A JUMP row's page, by the firmware's own transition: the core names the page
# in GO_TEXT (fpsup_home.c T_GO, svc->ui_go; its length + 1 is sloader4.h
# SL_GO_MAX), then posts GO_VAR, whose change event sends GO_TEXT as the page's
# request.  Posted after open()'s own posts, so the page it opens is built with
# them applied (a key event's request ran first: RES-Custom opened unfocused).
# (An "equals 1" event, as B1_1's CM_TransitionFlag, never fired: camera 10-25.)
GO_TEXT = 'FT_GO' + '_' * 26
GO_VAR = MP.GO_VAR
JUMP_KEY = 40                                 # FT_Key = 40 + k + 1: a JUMP / ACTION row's Right/OK
HEAD_VAR = 'FT_HeadOn'                        # 1 = focus on the hidden stock tab bar: header lit
TITLE_VAR = 'FT_Title'                        # 1 = paged: the title row, not slot 0
POPUP_KEY = 20                                # FT_Key = 20 + k + 1: slot k's popup has focus
TAB_FOCUS = 55                                # the stock tab bar (fpsup_home.c TAB_FOCUS)
ITEM_PARTS = 'abc'


def var(part, k):
    return MP.var(part, k)


def item_var(k, j):
    return f'FT_I{k}{ITEM_PARTS[j]}'


def setting_row(pg, k):
    """MainY5's popup row (v3 sup_row's donor) as one fpSup page slot."""
    out, m = pg.clone(MP.SELECT_ROW)
    # v3 also dropped item 33499; here it is the popup's third choice
    gone = {m[o] for o in F.SZ.subtree(pg.objs, 33251)} | {m[33502], m[33506], m[33495]}
    original = out
    out = []
    owner = 0
    for r in original:
        if u32(r, 0) == 0x10003: owner = u32(r, 20)
        if owner not in gone and (owner != m[MP.SELECT_ROW] or u32(r, 0) in (0x10003, 0x10004)):
            out.append(r)
    by = F.by_object(out)
    for o, idx in by.items():
        head = out[idx[0]]
        lost = sum(u32(r, 0) == 0x10003 and u32(r, 24) == o and u32(r, 20) in gone for r in original)
        put(head, 16, u32(head, 16) - lost)
        if o == m[MP.SELECT_ROW]: put(head, 8, 1)
    # As v3: no width-change event, no native submenu dispatch, no forwarding
    # to the removed JumpEvent.
    cleaned, i = [], 0
    while i < len(out):
        r = out[i]
        if u32(r, 0) == 0x1000B and pg.pool.text(u32(r, 20)) == 'submenu_width_NoIcon':
            i += 1; continue
        if u32(r, 0) != 0x10006:
            cleaned.append(r); i += 1; continue
        acts = out[i + 1:i + 1 + u32(r, 16)]
        if F.pool_name(pg, r) == 'appVariableChangeEvent' and pg.pool.text(u32(r, 36)) == 'submenu_width':
            put(cleaned[F.by_object(cleaned)[m[MP.SELECT]][0]], 8,
                u32(cleaned[F.by_object(cleaned)[m[MP.SELECT]][0]], 8) - 1)
            i += 1 + len(acts); continue
        keep = [a for a in acts if not (F.pool_name(pg, a) == 'controlAppState'
                or (F.pool_name(pg, a) == 'controlAppVariable' and
                    (len(a) <= 36 or pg.pool.text(u32(a, 36)) != 'MENU_Level1'))
                or any(kind == 'obj' and u32(a, off) in gone for off, kind in F.P.typed_fields(bytes(a), pg.pool, pg.schemas)))]
        put(r, 16, len(keep)); cleaned += [r] + keep
        i += 1 + len(acts)
    out = cleaned
    texts = {m[o] for o in MP.POPUP_TEXT}
    clips = [r for r in out if u32(r, 0) == 0x1000A and
             (u32(r, 20) in texts or u32(r, 20) == m[30019]
              or (u32(r, 20) == m[MP.LIST] and u32(r, 24) == 10)
              or u32(r, 20) in {m[o] for o in (30022, 30023, 30028, 33501)})]
    out = [r for r in out if not any(r is clip for clip in clips)]
    for clip in clips:
        head = out[F.by_object(out)[u32(clip, 20)][0]]
        put(head, 8, u32(head, 8) - 1)
    by = F.by_object(out)
    base = out[F.comp(out, by[m[MP.SELECT_ROW]], 'objectBase', pg.pool)]
    struct.pack_into('>f', base, 36, 81.0 * k)
    MP.remap_focus(pg, out, MP.FOCUS)
    cv = out[F.comp(out, by[m[MP.SELECT]], 'controlValue', pg.pool)]
    pg.bind(out, m[MP.SELECT], var('Default', k), u32(cv, 24), 'value', 1)
    lock = out[F.comp(out, F.by_object(out)[m[1515]], 'controlValue', pg.pool)]
    pg.bind(out, m[1515], var('Lock', k), u32(lock, 24), 'value', 1)
    MP.row_visible(pg, var('Visible', k), m[MP.SELECT_ROW])
    # The popup: room for three choices beside the row, above the footer;
    # its height and its last choice follow the row (FT_PopH, FT_Max).
    lb = out[F.comp(out, F.by_object(out)[m[MP.LIST]], 'objectBase', pg.pool)]
    check(u32(lb, 28) == 0xD3, 'MainY5 popup base form')
    popup_y = min(81.0 * k, MP.CONTENT_HEIGHT - POPUP_MAX_HEIGHT)
    struct.pack_into('>4f', lb, 32, 1024.0 - POPUP_WIDTH, popup_y - 81.0 * k,
                     float(POPUP_WIDTH), POPUP_MAX_HEIGHT)
    pg.bind_sub(out, m[MP.LIST], var('PopH', k), u32(lb, 24), 'size', 1)
    cv = out[F.comp(out, F.by_object(out)[m[MP.LIST]], 'controlValue', pg.pool)]
    check(u32(cv, 28) == 0xA and len(cv) == 40, 'MainY5 List limit form')
    struct.pack_into('>f', cv, 32, float(POPUP_ITEMS - 1))
    pg.bind(out, m[MP.LIST], var('Default', k), u32(cv, 24), 'value', 1)
    pg.bind(out, m[MP.LIST], var('Max', k), u32(cv, 24), 'max-value', 1)
    # OK and Right both confirm (no More options in v4).
    for key in ('OK', 'Right'):
        pg.event(out, m[MP.LIST_ITEM], key, lambda event: [
            pg.write(m[MP.LIST_ITEM], event, 1, var('Choice', k), source=m[MP.LIST]),
            pg.focus(m[MP.LIST_ITEM], event, 2, m[MP.SELECT])])
    pg.append_action(out, m[MP.LIST_ITEM], 'focusEvent', 'FocusOn',
                     lambda ev, order: pg.write(m[MP.LIST_ITEM], ev, order, MP.PAGE_KEY, POPUP_KEY + k + 1))
    pg.append_action(out, m[MP.LIST_ITEM], 'focusEvent', 'FocusOff',
                     lambda ev, order: pg.write(m[MP.LIST_ITEM], ev, order, MP.PAGE_KEY, POPUP_KEY))
    # A JUMP / ACTION row: the row's own Right/OK tell the core.
    for key in ('Right', 'OK'):
        pg.append_action(out, m[MP.SELECT], 'keyEvent', key,
                         lambda ev, order: pg.write(m[MP.SELECT], ev, order, MP.PAGE_KEY, JUMP_KEY + k + 1))
    for j, old in enumerate(MP.POPUP_TEXT):
        by = F.by_object(out)
        ti = F.comp(out, by[m[old]], 'drawText', pg.pool)
        tr = MP.label_text(pg, out[ti], m[old], MP.NAME_SIZE, 0xFFFFFFFF, int(TEXT_RIGHT - 36), 58)
        put(tr, 45, 3)                                  # right-aligned, as the stock popup's
        out[ti] = tr
        pg.bind(out, m[old], item_var(k, j), u32(tr, 24), 'text')
        bi = F.comp(out, by[m[old]], 'objectBase', pg.pool)
        b = F.owned(pg.raw[F.comp(pg.raw, pg.src[30021], 'objectBase', pg.pool)], m[old])
        struct.pack_into('>4f', b, 32, 36.0, 10.0, TEXT_RIGHT - 36.0, 58.0)
        MP.foreground(b)
        out[bi] = b
    for old in (MP.LIST_ITEM, 30024, 30025, 30026, 33499, 30022, 30023, 30028, 33501):
        by = F.by_object(out)
        b = out[F.comp(out, by[m[old]], 'objectBase', pg.pool)]
        size_off = 40 if u32(b, 28) & 1 else 32
        struct.pack_into('>2f', b, size_off, float(POPUP_WIDTH), 81.0 if old == MP.LIST_ITEM else 79.0)
        for i in by[m[old]]:
            r = out[i]
            if F.pool_name(pg, r) == 'drawRect':
                struct.pack_into('>f', r, len(r) - 8, float(POPUP_WIDTH))
    # The More arrow marks a JUMP row (a page of its own), right of the value.
    arrow = out[F.comp(out, F.by_object(out)[m[30019]], 'objectBase', pg.pool)]
    pg.bind(out, m[30019], var('Jump', k), u32(arrow, 24), 'opacity', 1)
    # ... too: it means "enters a page", so a TOGGLE / LIST row shows only its
    # value (user 2026-10-24: "...是只能進入用的").  1536 = font_G_3dot.
    dots = out[F.comp(out, F.by_object(out)[m[1536]], 'objectBase', pg.pool)]
    pg.bind(out, m[1536], var('Jump', k), u32(dots, 24), 'opacity', 1)
    selected_bg = out[F.comp(out, F.by_object(out)[m[30023]], 'drawRect', pg.pool)]
    put(selected_bg, 32, 0x666666FF)
    # The row's name, centred; the value in the right column (v3's status field).
    name = m[30021]
    by = F.by_object(out)
    ti = F.comp(out, by[name], 'drawText', pg.pool)
    template = pg.raw[F.comp(pg.raw, pg.src[MP.POPUP_TEXT[0]], 'drawText', pg.pool)]
    tr = MP.label_text(pg, template, name, MP.NAME_SIZE, 0xFFFFFFFF, 600, 46)
    out[ti] = tr
    pg.bind(out, name, var('N', k), u32(tr, 24), 'text')
    b = out[F.comp(out, F.by_object(out)[name], 'objectBase', pg.pool)]
    struct.pack_into('>4f', b, 32, 49.0, 16.0, 600.0, 46.0)
    by = F.by_object(out); oid = pg.take_id()
    o = bytearray(out[by[name][0]])
    put(o, 20, oid); put(o, 8, 2); put(o, 16, 0)
    b = F.owned(out[F.comp(out, by[name], 'objectBase', pg.pool)], oid)
    struct.pack_into('>4f', b, 32, 460.0, 20.0, 404.0, 40.0)
    text = bytearray(template)
    put(text, 24, u32(tr, 24)); put(text, 32, 0); text[36] = 0
    t = MP.label_text(pg, text, oid, 32, 0x9A9A9AFF, 404, 40)
    put(t, 45, 3)                                   # right-aligned, as v3's status field
    at = F.by_object(out)[name][-1] + 1
    out[at:at] = [o, b, t]
    pg.bind(out, oid, var('A', k), u32(t, 24), 'text')
    put(out[F.by_object(out)[m[MP.SELECT]][0]], 16, u32(out[F.by_object(out)[m[MP.SELECT]][0]], 16) + 1)

    # A TOGGLE's Off / On, as the stock pages draw them: text fields holding the
    # .nloc keys (B2_6.cvm's 0080 / 0081), which the GUI shows in the camera's
    # language -- a posted string is drawn as it stands (camera 2026-10-24: "0081").
    # The core shows one by FT_TOff<k> / FT_TOn<k> (value) and FT_Tog<k> (the
    # popup's first two items), and posts blanks to the text variables.
    # Their drawText is the stock record itself -- its own font setting, size,
    # colour and alignment (label_text would force the English font setting:
    # the user 2026-10-24 saw our fonts differ) -- with only the text id changed.
    # The value: the row name's (30021), right-aligned to the stock value's
    # right edge (x 965, the stock pages' value column); the popup's: 30013 / 30027.
    for key, group in MP.TOGGLE_KEYS:
        MP.stock_text(pg, out, name, (MP.VALUE_RIGHT, 16.0), 30021, key, var(group, k), right=True)
    for j, (key, _) in enumerate(MP.TOGGLE_KEYS):
        old = m[MP.POPUP_TEXT[j]]
        # the stock item text is right-aligned: its box ends where the stock popup's do
        MP.stock_text(pg, out, old, (36.0, 10.0), MP.POPUP_TEXT[j], key, var('Tog', k),
                   size=(TEXT_RIGHT - 36.0, 58.0))            # within the item: wider is not drawn

    # MENU leaves the menu, as on MainY5: its own exit, not a Return request
    # (TransFtTab has no Return from FT_Y6 -- MENU did nothing, the user 2026-10-21).
    pg.event(out, m[MP.SELECT], 'Menu', lambda event: [stock_exit(pg, m[MP.SELECT], event)])
    return out, m


def stock_exit(pg, owner, event):
    """MainY5's MENU action (its Select row's, a 48-byte controlAppState with
    no request name: stock's own menu exit) for `owner`'s event."""
    for i in pg.src[MP.SELECT]:
        r = pg.raw[i]
        if u32(r, 0) == 0x10006 and F.pool_name(pg, r) == 'keyEvent' and pg.pool.text(u32(r, 20)) == 'Menu':
            acts = [pg.raw[j] for j in range(i + 1, i + 1 + u32(r, 16))]
            check(len(acts) == 1 and F.pool_name(pg, acts[0]) == 'controlAppState' and len(acts[0]) == 48,
                  'MainY5 Select MENU is not the stock exit')
            a = bytearray(acts[0])
            put(a, 20, owner); put(a, 24, event); put(a, 28, 1)
            return a
    raise SystemExit('MainY5 Select has no MENU event')


def build_home(img, pool):
    """FT_Y6: header, title row with page tabs, slots 0..5.  Returns (page,
    refs, slot 0's focus id): the core's first FT_Focus when it does not page."""
    pg = MP.Management(img, pool)
    MP.manager_header(pg, 'fpSup', head_var=HEAD_VAR, title_y=MP.V4_TITLE_Y)   # user 2026-10-24: fpSup, a little lower
    out, m = MP.jump_row(pg, 0, ' ', focus=MP.FOCUS)
    title = out[F.comp(out, F.by_object(out)[m[F.KEEP_ROW]], 'objectBase', pool)]
    for prop in ('opacity', 'is-visible'):
        pg.bind(out, m[F.KEEP_ROW], TITLE_VAR, u32(title, 24), prop, 1)
    MP.page_tabs(pg, out, m[F.ROW_ITEM])
    for old in (10062, 3457):
        r = out[F.comp(out, F.by_object(out)[m[old]], 'drawImage', pool)]
        put(r, 32, pool.find('blank'))
    MP.move_hidden(out[F.comp(out, F.by_object(out)[m[3456]], 'objectBase', pool)])
    pg.append_action(out, m[F.ROW_ITEM], 'focusEvent', 'FocusOn',
                     lambda ev, order: pg.write(m[F.ROW_ITEM], ev, order, MP.PAGE_KEY, 31))
    for key, code in (('Left', MP.PREVIOUS), ('Right', MP.NEXT)):
        pg.event(out, m[F.ROW_ITEM], key, lambda event, code=code: [pg.write(m[F.ROW_ITEM], event, 1, MP.PAGE_KEY, code)])
    pg.add(out)                                     # the title row keeps MainY5's MENU exit
    row0 = 0
    for k in range(SLOTS):
        out, rm = setting_row(pg, k); pg.add(out)
        row0 = row0 or rm[MP.SELECT]
    pg.root_focus(MP.FOCUS)
    enter_on_tabs(pg)
    go_on_change(pg)
    MP.chrome(pg)
    MP.colour_clips(pg)
    return pg.finish() + (row0,)


def go_on_change(pg):
    """On the screen-enter event's object (the page root): when GO_VAR changes,
    request GO_TEXT -- MainY5's own change event (submenu_width's: variable and
    type only) and its rows' request record, renamed.  This page fires it again
    as it is rebuilt (camera 10-25: MENU came straight back); by then the page it
    opened has written GO_VAR = 0 on entering (manage_page.enter_write) and the
    core has emptied GO_TEXT, so that asks for nothing."""
    seq = pg.seq
    at = next(i for i, r in enumerate(seq) if len(r) >= 32 and u32(r, 0) == 0x10006
              and F.pool_name(pg, r) == 'screenEvent'
              and any(F.pool_name(pg, a) == 'controlFocus' for a in seq[i + 1:i + 1 + u32(r, 16)]))
    owner = u32(seq[at], 24)
    src = next(r for r in pg.raw if len(r) == 45 and u32(r, 0) == 0x10006 and u32(r, 20) == 0xFFFFFFFF
               and F.pool_name(pg, r) == 'appVariableChangeEvent' and pg.pool.text(u32(r, 36)) == 'submenu_width')
    check(u32(src, 32) == 3 and src[40:] == bytes(4) + b'\x03', 'MainY5 change event form')
    ids = F.by_object(seq)[owner]
    ev = bytearray(src)
    put(ev, 24, owner); put(ev, 28, max(F.P.local_ids(seq, ids) | {0}) + 1); put(ev, 16, 1)
    pg.private(ev, 36, GO_VAR)
    req = bytearray(pg.raw[F.row_actions_raw(pg, F.ROW_ITEM, 'Right')])
    put(req, 20, owner); put(req, 24, u32(ev, 28)); put(req, 28, 1)
    pg.request(req, GO_TEXT)
    end = at + 1 + u32(seq[at], 16)
    seq[end:end] = [ev, req]
    pg.added += [ev, req]
    put(seq[ids[0]], 8, u32(seq[ids[0]], 8) + 1)        # the object's event count


def enter_on_tabs(pg):
    """The page's own screen-enter event (MainY5's: focus from the focus
    variable, then CM_MenuTabNo, PB_MENUTabDirect) first writes FT_Focus = 55:
    every entry lands on the tab bar, as the stock pages do (user 2026-10-24:
    the focus remembered its row, so RIGHT from the tab bar entered that row)."""
    seq = pg.seq
    at = next(i for i, r in enumerate(seq) if len(r) >= 32 and u32(r, 0) == 0x10006
              and F.pool_name(pg, r) == 'screenEvent'
              and any(F.pool_name(pg, a) == 'controlFocus' for a in seq[i + 1:i + 1 + u32(r, 16)]))
    ev = seq[at]
    acts = seq[at + 1:at + 1 + u32(ev, 16)]
    focus = next(a for a in acts if F.pool_name(pg, a) == 'controlFocus')
    check(u32(focus, 28) == 1 and pg.pool.text(u32(focus, 40)) == MP.FOCUS, 'screen-enter focus is not first / not FT_Focus')
    for a in acts:
        put(a, 28, u32(a, 28) + 1)
    w = pg.write(u32(focus, 20), u32(focus, 24), 1, MP.FOCUS, TAB_FOCUS)
    seq.insert(at + 1, w)
    pg.added.append(w)                                  # counted in the allocation header
    put(ev, 16, u32(ev, 16) + 1)
