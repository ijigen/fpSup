"""LUT manager: v4 SupManager's page, built the way RES-Custom's file list is
(user 2026-10-25: "lutmanager 的設計可以完全參考 RES-Custom").

manage_page.build_manage(v4=True) -- slot 0 under the title row, six cubes or
fewer do not page, the stock On / Off popup, the footer fixed -- with its
variables LC_ for SM_ (supmgr.c's order: native/color_ui.c MV_*), the title
our own text (LC_Header: "LUT (on/cap)").  Two additions, both on the page's
own objects:

- AEL: a keyEvent on Root's CommonSystemKeyEvent in the form of its QS / MODE
  events (the physical AEL is a system key; on a row or on Menu it never
  arrived -- camera 2026-10-25) -> LC_Key = 80; the core takes the row from
  LC_Focus (LC_RowId0..5 hold the slots' focus ids).
- The settings page by the firmware's own transition (fp-native-ui 8j): a
  change event on LC_Go requests the name the core put in LC_GO___.
"""
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'uishare/tab'))
import build_fp4 as F4                   # noqa: E402
import build_ft6 as FT                   # noqa: E402
import ft6_page as P                     # noqa: E402
import home4_page as H                   # noqa: E402
import manage_page as M                  # noqa: E402

PAGE = 'FT_LUTMGR'
HEADER = 'LC_Header'
AEL_KEY, AEL_CODE = 80, 0x13             # LC_Key; a keyEvent's last word is its key
SYSKEY_OBJECT = 26919                    # MainY5's CommonSystemKeyEvent (Root's child)
GO_VAR, GO_TEXT = 'LC_Go', 'LC_GO' + '_' * 26
RETURN_CHECK = 29767                     # MainY5's ReturnCheck: its appStateEvents (Return / LV / PlayBack)
CONV_EVENT, CONV_DONE_KEY = 'LC_ConvEnd', 90   # native/conv.c's app state; color_ui.c CONV_DONE_KEY
BUSY_EVENT, BUSY_VAR, CLOCK_VAR = 'LC_ConvStart', 'LC_Busy', 'LC_Clock'   # conv.c conv_busy / conv_clock
BUSY_RECT, BUSY_COLOUR = (0, 99, 1024, 486), 0x222222FF   # Y1_1 UpdateProgress's BG
BUSY_CLOCK_Y = 8                                          # within the overlay: above the chart
CLOCK_DONOR, CLOCK_W, CLOCK_H = 60, 44, 80                # MainY5 Icon01's drawImage; cmn_clock_* size


def lc(name):
    return 'LC_' + name[3:]


def manager_vars(row0=0):
    """supmgr_vars() with LC_ for SM_ (color_ui.c MV_0 .. MV_HEADER), then LC_Header."""
    return [(ty, lc(n), first) for ty, n, first in F4.supmgr_vars(row0)] + [(F4.VAR_TEXT, HEADER, ' ')]


def menu_ael(pg):
    by = pg.ob(); ids = by[SYSKEY_OBJECT]
    qs = next(pg.seq[i] for i in ids if P.u32(pg.seq[i], 0) == 0x10006 and len(pg.seq[i]) == 44
              and pg.pool.text(P.u32(pg.seq[i], 20)) == 'QS')
    P.check(P.u32(qs, 40) == 0x14, 'CommonSystemKeyEvent QS form')
    ev = bytearray(qs)
    local = max(P.P.local_ids(pg.seq, ids) | {0}) + 1
    P.put(ev, 20, pg.pool.find('AEL')); P.put(ev, 28, local); P.put(ev, 16, 1); P.put(ev, 40, AEL_CODE)
    act = pg.write(SYSKEY_OBJECT, local, 1, M.PAGE_KEY, AEL_KEY)
    at = ids[-1] + 1
    pg.seq[at:at] = [ev, act]; pg.added += [ev, act]
    head = pg.seq[ids[0]]; P.put(head, 8, P.u32(head, 8) + 1)


def state_event(pg, name, actions):
    """An appStateEvent on `name` on ReturnCheck, copied from its stock "Return" one (41 bytes, +20 and +36
    the name); `actions(local)` its actions."""
    ids = pg.ob()[RETURN_CHECK]
    src = next(pg.seq[i] for i in ids if P.u32(pg.seq[i], 0) == 0x10006 and len(pg.seq[i]) == 41
               and P.pool_name(pg, pg.seq[i]) == 'appStateEvent' and pg.pool.text(P.u32(pg.seq[i], 36)) == 'Return')
    P.check(P.u32(src, 20) == P.u32(src, 36) and P.u32(src, 16) == 1, 'ReturnCheck appStateEvent form')
    ev = bytearray(src)
    local = max(P.P.local_ids(pg.seq, ids) | {0}) + 1
    pg.private(ev, 20, name); pg.private(ev, 36, name); P.put(ev, 28, local)
    acts = actions(local)
    P.put(ev, 16, len(acts))
    at = ids[-1] + 1
    pg.seq[at:at] = [ev, *acts]; pg.added += [ev, *acts]
    head = pg.seq[ids[0]]; P.put(head, 8, P.u32(head, 8) + 1)


def focus_from_variable(pg, owner, event, order):
    """Root's own entry focus (controlFocus by focus-variable FT_Focus, 45 bytes) for `owner`'s event."""
    src = next(r for r in pg.seq if P.u32(r, 0) == 0x10009 and P.u32(r, 20) == 1 and len(r) == 45
               and P.pool_name(pg, r) == 'controlFocus')
    P.check(pg.pool.text(P.u32(src, 40)) == M.FOCUS, 'Root focus-variable form')
    r = bytearray(src)
    P.put(r, 20, owner); P.put(r, 24, event); P.put(r, 28, order)
    pg.private(r, 40, M.FOCUS)
    return r


def conv_end(pg):
    """The worker's end, the stock way (the card format: v76 sends "ProcessingComplete", Y1_1's
    UpdateProgress answers): an appStateEvent on CONV_EVENT gives focus back to LC_Focus (the row the
    core keeps there) and writes LC_Key = CONV_DONE_KEY -- a page write, so our watch runs conv_finish
    (the worker's own post of LC_Key never reached the watch: camera 11-04; this, camera 11-05 v9)."""
    state_event(pg, CONV_EVENT, lambda local: [focus_from_variable(pg, RETURN_CHECK, local, 1),
                                               pg.write(RETURN_CHECK, local, 2, M.PAGE_KEY, CONV_DONE_KEY)])


def busy_overlay(pg):
    """While a cube converts (user 11-05: "跳出漏斗讓他跑 並顯示出進度"): the stock format's way -- an
    overlay on the page (Y1_1 UpdateProgress: BG 0x222222 at y 99 h 486), focus on it so the keys go
    nowhere -- with the stock hourglass (LV ImageProcessing: cmn_clock_1/2/3, 44 x 80).  Every record is
    one of this page's own forms (fp-native-ui 8b: foreign objects fail silently): the Name object, the
    tab rect, ReturnCheck's controlValue (focusable), Icon01's drawImage (mask 0x81) with the clock's
    name.  Shown by opacity (LC_Busy; LC_Clock0..2 the frames, conv.c conv_spin).  The progress text is
    the footer's own LC_OK ("Converting 37%").  First among Root's children: drawn on top.

    2026-11-07: the overlay's own copy of LC_OK (a label_text drawText: centred, 1024 wide, 44 px, at
    y 290 h 60) drew a band of red / white / green / blue stripes over exactly its rectangle (camera
    SS__3197) and never the text; which of its fields the renderer chokes on is not known offline (the
    same form, left-aligned and 107 wide, draws FT_Version).  It is gone; the progress is the chart's bar
    (checker_chart) and the footer's text, the match a text in the footer's own FT_OK form."""
    out, o_id = M.plain_object(pg, 1, BUSY_RECT[0], BUSY_RECT[1], BUSY_RECT[2], BUSY_RECT[3])
    head, base = out
    out.append(M.fill_rect(pg, o_id, BUSY_COLOUR, BUSY_RECT[2], BUSY_RECT[3]))
    cv = F_owned(pg, pg.raw[F_comp(pg, RETURN_CHECK, 'controlValue')], o_id)
    out.append(cv)
    P.put(head, 8, P.u32(head, 8) + 2)
    pg.bind(out, o_id, BUSY_VAR, P.u32(base, 24), 'opacity', 1)
    w = BUSY_RECT[2]
    kids = []
    icon = pg.raw[F_comp(pg, CLOCK_DONOR, 'drawImage')]
    P.check(len(icon) == 52 and P.u32(icon, 28) == 0x81, 'Icon01 drawImage form')
    for k in range(3):
        c, c_id = M.plain_object(pg, o_id, (w - CLOCK_W) // 2, BUSY_CLOCK_Y, CLOCK_W, CLOCK_H)
        img = F_owned(pg, icon, c_id)
        name = pg.pool.find(f'cmn_clock_{k + 1}')
        P.check(name is not None, 'the stock hourglass images')
        P.put(img, 32, name)
        struct.pack_into('>4f', img, 36, 0.0, 0.0, float(CLOCK_W), float(CLOCK_H))
        c.append(img); P.put(c[0], 8, P.u32(c[0], 8) + 1)
        pg.bind(c, c_id, f'{CLOCK_VAR}{k}', P.u32(c[1], 24), 'opacity', 1)
        kids += c
    P.put(head, 16, 3)
    recs = out + kids
    chart, chart_id = checker_chart(pg)
    ob = pg.ob()
    at = ob[1][-1] + 1                                                     # after Root's own records
    P.check(P.u32(pg.seq[at], 0) == 0x10003, 'Root then its first child')
    pg.seq[at:at] = chart + recs; pg.added += chart + recs                 # the chart first: drawn over the box
    root = pg.seq[ob[1][0]]; P.put(root, 16, P.u32(root, 16) + 2)
    state_event(pg, BUSY_EVENT, lambda local: [pg.focus(RETURN_CHECK, local, 1, o_id)])
    return o_id


# The ColorChecker while it converts (Bei 11-07): 24 patches, 6 x 4, each split -- top the cube's colour
# (the target), bottom the fit's -- the match and a bar for the progress.  A Root child of its own (opacity
# LC_Chart), so it stays up over the manager when the box (LC_Busy) goes at the finish; the first key after
# takes it down (color_ui.c).  Each half a drawRect whose colour is an int app variable (RGBA, 0xRRGGBBAA,
# as the records hold it): native/conv.c conv_chart posts them -- LC_P00.. in patch order, top then bottom.
CHART_VAR, BAR_VAR, MATCH_VAR, PATCH_VAR = 'LC_Chart', 'LC_Bar', 'LC_Match', 'LC_P'
CHART_RECT = (172, 195, 680, 380)                         # page coordinates: under the hourglass, over the box
CHART_COLOUR, TRACK_COLOUR, BAR_COLOUR = 0x222222FF, 0x555555FF, 0xFFFFFFFF
PATCH_W, PATCH_H, PATCH_GAP, PATCH_X0, PATCH_Y0 = 100, 56, 8, 20, 10   # within the chart
BAR_RECT = (20, 270, 640, 14)                             # LC_Bar = the fill's width, 0 .. 640
MATCH_RECT = (20, 292, 640, 54)                           # "Match 87%": the footer's FT_OK form
FOOTER_TEXT = 19499                                       # MainY5's footer text object (chrome's FT_OK)
N_PATCH = 24


def patch_vars():
    return [f'{PATCH_VAR}{k:02d}' for k in range(2 * N_PATCH)]


def chart_vars():
    """color_ui.c MV_CHART, MV_BAR, MV_MATCH, MV_PATCH0 .. + 47."""
    return [(F4.VAR_INT, CHART_VAR, 0), (F4.VAR_INT, BAR_VAR, 0), (F4.VAR_TEXT, MATCH_VAR, ' ')] + \
        [(F4.VAR_INT, n, CHART_COLOUR) for n in patch_vars()]


def _rect_object(pg, parent, x, y, w, h, colour):
    out, oid = M.plain_object(pg, parent, x, y, w, h)
    draw = M.fill_rect(pg, oid, colour, w, h)
    out.append(draw); P.put(out[0], 8, P.u32(out[0], 8) + 1)
    pg.bind(out, oid, CHART_VAR, P.u32(out[1], 24), 'opacity', 1)
    return out, oid, draw


def checker_chart(pg):
    x, y, w, h = CHART_RECT
    out, c_id, _d = _rect_object(pg, 1, x, y, w, h, CHART_COLOUR)
    kids = []
    names = patch_vars()
    for p in range(N_PATCH):
        r, c = divmod(p, 6)
        px, py = PATCH_X0 + c * (PATCH_W + PATCH_GAP), PATCH_Y0 + r * (PATCH_H + PATCH_GAP)
        for half in range(2):
            o, oid, draw = _rect_object(pg, c_id, px, py + half * (PATCH_H // 2), PATCH_W, PATCH_H // 2, CHART_COLOUR)
            pg.bind(o, oid, names[2 * p + half], P.u32(draw, 24), 'color', 1)
            kids += o
    bx, by, bw, bh = BAR_RECT
    o, _t, _d = _rect_object(pg, c_id, bx, by, bw, bh, TRACK_COLOUR)
    kids += o
    o, f_id, draw = _rect_object(pg, c_id, bx, by, bw, bh, BAR_COLOUR)
    struct.pack_into('>f', draw, len(draw) - 8, 0.0)                   # empty until the first post
    pg.bind_sub(o, f_id, BAR_VAR, P.u32(draw, 24), 'rect', 2)
    kids += o
    kids += _match_text(pg, c_id)
    P.put(out[0], 16, 2 * N_PATCH + 3)
    return out + kids, c_id


def _match_text(pg, parent):
    """chrome()'s FT_OK: the footer's Name object, objectBase and drawText (camera-proven with posted
    strings), re-owned under the chart, its text LC_Match."""
    oid = pg.take_id()
    o = bytearray(pg.raw[pg.src[FOOTER_TEXT][0]])
    P.put(o, 20, oid); P.put(o, 24, parent); P.put(o, 8, 2); P.put(o, 16, 0)
    b = M.F.owned(pg.raw[F_comp(pg, FOOTER_TEXT, 'objectBase')], oid)
    struct.pack_into('>4f', b, 32, *(float(v) for v in MATCH_RECT))
    t = M.F.owned(pg.raw[F_comp(pg, FOOTER_TEXT, 'drawText')], oid)
    pg.literal(t, ' ')
    struct.pack_into('>f', t, len(t) - 8, float(MATCH_RECT[2]))
    out = [o, b, t]
    pg.bind(out, oid, MATCH_VAR, P.u32(t, 24), 'text')
    pg.bind(out, oid, CHART_VAR, P.u32(b, 24), 'opacity', 1)
    return out


def F_comp(pg, owner, name):
    return M.F.comp(pg.raw, pg.src[owner], name, pg.pool)


def F_owned(pg, rec, owner):
    return M.F.owned(rec, owner)


def go_on_change(pg):
    """home4_page.go_on_change with this pack's variable and request."""
    saved = H.GO_VAR, H.GO_TEXT
    H.GO_VAR, H.GO_TEXT = GO_VAR, GO_TEXT
    try:
        H.go_on_change(pg)
    finally:
        H.GO_VAR, H.GO_TEXT = saved


def build():
    """(page, refs, row0, slot focus ids 0..5)."""
    img, pool = P.stock_pool()
    header, sup_row, finish = M.manager_header, M.sup_row, M.Management.finish
    slots = {}

    def titled(pg, title_text='SupManager', **kw):          # rc_files_page.ft4's counted_header
        header(pg, title_text, **kw)
        title, field = next((r, o) for r, o, t in pg.refs if t == title_text)
        pg.refs = [(r, o, t) for r, o, t in pg.refs if r is not title or o != field]
        P.put(title, field, 0); title[field + 4] = 0
        owner = P.u32(title, 20)
        pg.bind(pg.seq, owner, HEADER, P.u32(title, 24), 'text')
        pg.added.append(pg.seq[P.by_object(pg.seq)[owner][-1]])

    def recorded(pg, k, **kw):
        out, m = sup_row(pg, k, **kw)
        slots[k] = m[M.SELECT]
        return out, m

    def finished(pg, *a, **kw):
        menu_ael(pg); go_on_change(pg); busy_overlay(pg); conv_end(pg)
        return finish(pg, *a, **kw)
    try:
        M.manager_header, M.sup_row, M.Management.finish = titled, recorded, finished
        page, refs, row0 = M.build_manage(img, pool, v4=True)
    finally:
        M.manager_header, M.sup_row, M.Management.finish = header, sup_row, finish
    names = {n for _t, n in FT.variables() + F4.supmgr_extra()}
    refs = [(o, lc(t) if t in names else t) for o, t in refs]
    return bytes(page), refs, row0, [slots[k] for k in range(len(slots))]
