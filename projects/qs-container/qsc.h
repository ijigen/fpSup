/* QS container (QSCT) -- the contract with a client sup.
 *
 * A client adds functions to the stock custom-QS editor's list and to the
 * Quick Set page without knowing any QS address.  In its entry, one line,
 * whoever loads first:
 *
 *     static const struct qsc_func f[2] = {...};          // resident in the block
 *     static const struct qsc_table t = {QSC_TABLE_MAGIC, 2, f};
 *     svc->provide(svc, QSC_TAG(MY_SUP_ID), (void *)&t);
 *
 * The container collects every LOADED sup's table once, at the first layout
 * load after all entries ran (so load order does not matter), and hands out
 * the ids then: function i (in load order, then table order) = UI 49+i,
 * internal 54+i, this boot only.  What is kept across boots is the KEY
 * (sup_id + name), never the id.  At most QSC_MAX functions.
 *
 * Stage 1: the list row, the editor tile (icon + label), the save swap.
 * Stage 2: on the QS page (QS_CINE) the tile shows the icon, value() in the
 * stock bold value glyphs and small() under it; the dials call adjust(+1 / -1)
 * while the tile is focused; footer() fills the option strip under the panel
 * (labels, a second line, the current one boxed; nothing when 0 options); the
 * dial arrows show only with adjust, the "AEL more options" hint only with
 * sub-items.  AEL on the tile opens the function's sub-QS in the same panel:
 * the function moves to tile 1 (focused), its sub-items fill tiles 2.., the
 * rest are blank; AEL or MENU returns to the user's layout (focus back on the
 * function's own tile); leaving QS returns too.  state() / QSC_F_LOCK_REC grey
 * the tile and stop adjust and AEL.
 *
 * All callbacks run on the UI thread, must be quick, and live in the client's
 * own block (cached alias).  Texts: labels and titles printable ASCII; value
 * and small text printable ASCII or UTF-8 (x U+00D7 is drawn with the stock
 * glyph; other non-ASCII in the system font), up to QSC_VALUE - 1 bytes.
 * Value glyphs: digits, A-Z, . : - / + % # x -- anything else (lower case,
 * space) is drawn in the system font in the same line.
 *
 * API 4 (v0.2.2, magic QSF4): fine mode (qsc_func.fine), footer mark / custom / grey bits, 7 sub-items,
 * the rear dial as +-QSC_STEP_REAR, QSC_F_TITLE, the lock icon in the value row, qsc_table.leave.
 * API 7 (v0.3.7, the same structs): QSC_F_GO -- AEL on the tile opens a stock page (fine() is the request).
 * API 8 (v0.3.8, the same structs): QSC_F_DIAL_HINT -- the dial guide in the QS footer guide line.
 * API 9 (0.0.2test, the same structs): fine() and sub together -- AEL on the tile = fine mode in place; the sub-QS
 * only through open(QSC_OPEN_SUB[_AT]).  API <= 8 refuses such a function (set fine only when version >= 9).
 * Table magic: QSC_TABLE_MAGIC4 (API 4) or QSC_TABLE_MAGIC (API 3, the same structs).  The API 2 layout
 * (magic "QSF1": qsc_func without small / footer, qsc_sub without icon /
 * small / footer / lock, up to 7 sub-items) is still accepted, up to 6 items.
 *
 * Design: projects/qs-touch/notes/QS_CONTAINER_DESIGN.md.  Firmware Ver.5.02. */
#ifndef QSC_H
#define QSC_H
#include <stdint.h>

#define QSC_ID            0x54435351u          /* "QSCT": the container's sup_id    */
#define QSC_TAG(sup_id)   ((uint32_t)(sup_id) ^ 0x80808080u)   /* a client's table */
#define QSC_TABLE_MAGIC4  0x34465351u          /* "QSF4": API 4 (this header)       */
#define QSC_TABLE_MAGIC   0x33465351u          /* "QSF3": API 3 (fine / grey / leave ignored) */
#define QSC_TABLE_MAGIC2  0x31465351u          /* "QSF1": API 2 layout              */
#define QSC_API_MAGIC     0x31415351u          /* "QSA1"                            */
#define QSC_MAX           16u
#define QSC_SUB_MAX       7u                   /* tiles 2..8 (tile 1 = the function); API 3: 6 */
#define QSC_NAME          12u                  /* name bytes, NUL included          */
#define QSC_LABEL         12u                  /* label bytes, NUL included         */
#define QSC_VALUE         24u                  /* value / small text bytes, NUL incl. */
#define QSC_FOOT_MAX      16u                  /* footer options                    */
#define QSC_FOOT_TEXT     16u                  /* footer label / small bytes, NUL incl. */

enum { QSC_F_CINE = 1u,          /* required (only the CINE editor / QS page is extended) */
       QSC_F_LOCK_REC = 2u,      /* greyed, no adjust / AEL while recording           */
       QSC_F_TITLE = 4u };       /* API 4: the QS tile's title is the label as text, no icon */
/* API 5 container: route the stock CINE tile to this function only while QS
 * is active. Settings/flash/editor retain the stock id; no duplicate editor
 * row is added. Supported stock internals: DC=12, FORMAT=21, RES=23, FPS=25.
 * The table/function layout stays API 4; older containers ignore these bits. */
#define QSC_F_REPLACE(internal) ((((uint32_t)(internal) + 1u) & 0xFFu) << 16)
#define QSC_REPLACE_MASK        0x00FF0000u
enum { QSC_OPEN_SUB = 1u, QSC_OPEN_FINE = 2u };
/* API 7 (container v0.3.7, api->version >= 7): AEL on the function's QS tile leaves the QS for a stock page.
 * Needs a non-0 fine() (API 4 table, QSC_TABLE_MAGIC4) and no sub.  AEL on the tile (not greyed by state(), not
 * QSC_F_LOCK_REC-locked while recording, and never while recording at all) calls fine(arg, 1) as a REQUEST:
 * non-0 = go -- the container closes any sub-QS / fine state, then asks the stock state machine for the page
 * (a controlAppState request, like a stock menu row); 0 = nothing happens, the QS stays.  fine(arg, 0) is never
 * called for a GO function (there is no fine mode to end).  Leaving the QS runs leave() as any layout load does.
 * Target values other than QSC_GO_* refuse the function at registration (as an unknown QSC_F_REPLACE does).
 * Older containers ignore these bits and run fine() as a fine mode: a client sets them only when
 * svc->find(svc, QSC_ID)'s api->version >= 7, or checks the version inside fine() and returns 0.
 * QSC_GO_READQR: SIGMA's "Load from QR Code" page (state Y5_ReadQR).  MENU there returns by the stock path to
 * the setup menu page (MainY5), the QS button to the QS, a half-press to live view (README v0.3.7). */
#define QSC_F_GO(t)  ((((uint32_t)(t)) & 0xFu) << 8)
#define QSC_GO_MASK  0x00000F00u
enum { QSC_GO_READQR = 1u };
/* API 8 (container v0.3.8, api->version >= 8): opt in to the dial guide.  While the QS focus is on this function's
 * tile (fine mode included, and tile 1 of its sub-QS) or on one of its sub-items, and that item has an adjust() and
 * is not locked (state() non-0, or QSC_F_LOCK_REC while recording), the QS footer guide line (the stock "AEL Further
 * Options" band, left end) shows the stock front / rear dial glyphs with their steps:
 * "[front dial] +-1  [rear dial] +-10" (API 3 / API 2 tables: "+-1  +-1", their rear step).  Anywhere else -- no
 * adjust(), locked, a stock tile, the blank tile -- nothing (stock tiles keep their stock guide).  No callback, no
 * text from the client.  Older containers (v0.3.7 and before) do not check this bit: they register the function
 * as before and show no guide, so a client may set it without looking at the version. */
#define QSC_F_DIAL_HINT 0x00001000u
/* API 6 (container v0.3.1): open the sub-QS with the focus on sub-item k (tile k + 2) instead of tile 1. */
#define QSC_OPEN_SUB_AT(k) (QSC_OPEN_SUB | (((uint32_t)(k) + 1u) & 0xFFu) << 8)
#define QSC_STEP_REAR 10         /* API 4: the rear dial calls adjust(+-QSC_STEP_REAR); API 3: +-1 */
enum { QSC_T_APPROX = 1u };      /* small(): draw it in the "approximate" colour (yellow) */
enum { QSC_LOCK_NONE = -1, QSC_LOCK_OPEN = 0, QSC_LOCK_SHUT = 1,
       /* v0.3.3 opt-in: title uses qsc_sub.icon when shut (absent when open); keep the large value.
        * Older containers ignore these two values and retain label/value text. */
       QSC_LOCK_TITLE_OPEN = 2, QSC_LOCK_TITLE_SHUT = 3,
       /* v0.3.5: native QS LOCK image in the small row; retain title and value.
        * Open is invisible. Older containers retain text and omit the image. */
       QSC_LOCK_SMALL_OPEN = 4, QSC_LOCK_SMALL_SHUT = 5 };

/* The option strip under the panel.  The container zeroes it and calls
 * footer(); the client fills n labels (1..15 bytes; the pointers need to stay
 * valid only until the call returns -- the container copies them), optional
 * second lines, the APPROX bits and the current index (n = no box), and
 * returns n.  At most 7 are shown, scrolled around the current one.
 * spin = 1: a numeric spinner like the stock colour-temperature tile's footer,
 * "<  label[0]  >" centred, no box (n = 1). */
struct qsc_foot {
    uint32_t n, cur, approx;                    /* approx: bit i = option i's small is approximate */
    uint32_t spin;
    uint32_t mark, custom;                      /* API 4: bit i = option i dotted-underlined / its label yellow */
    const char *label[QSC_FOOT_MAX];
    const char *small[QSC_FOOT_MAX];            /* 0 = none                          */
    uint32_t grey;                              /* API 4: bit i = option i not selectable (grey label; its
                                                   small line, e.g. the reason, in the "grey reason" colour) */
};

/* One sub-item tile (shown while the function's sub-QS is open). */
struct qsc_sub {
    const char *label;                          /* the title: 1..11 printable ASCII, no , " { } */
    const char *(*value)(void *arg);            /* big text; 0 = none                */
    int         (*adjust)(void *arg, int step); /* dial +1 / -1; 0 = no dial (no arrows) */
    void       *arg;
    /* API 3 */
    const char *icon;                           /* a stock image drawn instead of the title; 0 = title */
    const char *(*small)(void *arg, uint32_t *flags);  /* second line; *flags |= QSC_T_APPROX; 0 = none */
    uint32_t    (*footer)(void *arg, struct qsc_foot *out);   /* option count; 0 = none */
    int         (*lock)(void *arg);             /* QSC_LOCK_*: a lock / unlock icon (API 3: instead of the title;
                                                   API 4: instead of the value, under the title); TITLE_* uses icon above value; 0 = none */
    /* API 6 (container v0.3.1, api->version >= 6): called once when the focus leaves this item -- another tile
     * focused, AEL / MENU back, the sub-QS closed, any layout load (QS closed, OK, a menu).  UI thread, the key
     * path; quick.  0 = none.  An older container refuses a non-0 value (the function is not registered). */
    union { const void *reserved; void (*blur)(void *arg); };
};
struct qsc_subs { uint32_t n; const struct qsc_sub *item; };   /* n 1..QSC_SUB_MAX (API 3: 1..6) */

struct qsc_func {
    uint32_t    sup_id;          /* the key's first half: the client's own sup_id    */
    char        name[QSC_NAME];  /* the key's second half; unique in the sup, never changes */
    const char *label;           /* list row, name bar: 1..11 printable ASCII,
                                    not only digits, no , " { } (it is CSV text)     */
    const char *icon;            /* a stock list icon name ("menu_crop"); the tile
                                    borrows that function's look.  0 / unknown: menu_crop */
    uint32_t    flags;           /* QSC_F_*, QSC_F_REPLACE(), QSC_F_GO(), QSC_F_DIAL_HINT */
    const char *(*value)(void *arg);             /* the QS tile's value text; 0 = none */
    int         (*adjust)(void *arg, int step);  /* dial +1 / -1 on the QS tile; 0 = none (no arrows) */
    int         (*state)(void *arg);             /* non-0: greyed (no adjust, no AEL); 0 = none */
    const struct qsc_subs *sub;  /* the sub-QS opened with AEL; 0 = none (no AEL hint) */
    void       *arg;
    /* API 3 */
    const char *(*small)(void *arg, uint32_t *flags);          /* second line; 0 = none */
    uint32_t    (*footer)(void *arg, struct qsc_foot *out);    /* option count; 0 = none */
    /* API 4: a fine mode instead of a sub-QS (API 9: or next to one; AEL then takes fine, open() the sub-QS).
     * AEL on the tile calls fine(arg, 1): non-0 = entered.  The
     * layout stays (the tile keeps its place, the "MENU / AEL" hint follows the sub-QS rule); the dials keep
     * calling adjust() and footer() (the client shows its spinner).  AEL again, the focus moving off the tile,
     * or any layout load (QS closed, OK, MENU) call fine(arg, 0).  API 3: must be 0.
     * API 7: with QSC_F_GO bits in flags, fine(arg, 1) is the "go" request instead (see QSC_F_GO). */
    union { const void *reserved; int (*fine)(void *arg, int on); };
};

struct qsc_table {
    uint32_t magic;              /* QSC_TABLE_MAGIC4 (or MAGIC / MAGIC2)              */
    uint32_t n;                  /* 1..QSC_MAX                                       */
    const struct qsc_func *f;
    /* API 4 only: called at every layout load once collected (QS closed, a menu, ...), on the UI thread,
     * outside the QS key path -- where a client writes its settings record (never per dial step). 0 = none. */
    void (*leave)(void *arg);
    void *leave_arg;
};

/* svc->find(svc, QSC_ID), after the entries: what the container handed out. */
struct qsc_api {
    uint32_t magic, version;     /* QSC_API_MAGIC, 9 (0.0.2test: fine + sub); 8 (v0.3.8: QSC_F_DIAL_HINT; 7 = v0.3.7: QSC_F_GO; 6 = v0.3.1;
                                    5 = v0.3.0; check before reading open) */
    /* The UI id this boot gave (sup_id, name), or -1 (not registered, not yet
     * collected, or the container stood down). */
    int (*ui_id)(const struct qsc_api *, uint32_t sup_id, const char *name);
    /* A value changed elsewhere: redraw the QS tiles and the footer (UI thread). */
    void (*refresh)(const struct qsc_api *, uint32_t sup_id, const char *name);
    /* API 5: queue one request for the next CINE QS focus notification. Return
     * 1 = accepted, 0 = rejected. The last accepted request replaces the prior
     * one. UI thread only; this does not transition screens. Rechecked once at
     * consumption, then discarded if unavailable/locked/recording/not CINE.
     * A function absent from the eight slots opens a temporary standalone
     * layout; AEL returns to the user's layout with focus on its first tile. */
    int (*open)(const struct qsc_api *, uint32_t sup_id, const char *name, uint32_t how);
    /* API 6: read-only layout timing (firmware tick, us), 12 words: the first layout load's entry / collection start /
     * collection end / leave() start / leave() end / stock loader end (absolute), its slot write-back us, layouts
     * timed, the largest and the last layout us (whole hook), the first layout us, write-backs */
    const uint32_t *timing;
};
#endif
