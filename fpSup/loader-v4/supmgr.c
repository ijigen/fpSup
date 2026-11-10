/* SupManager as a sup (SUPMGR.BIN), loader v4.  Design: projects/loader-v4/DESIGN.md §7, §14.
 *
 * Its row on the fpSup page (the core puts it first) jumps to its own page,
 * FT_LIST: v3 allsups.c's management page (name, status x 5, pages, the
 * Enable / Disable popup), its data \fpSup\UI\SUPMGR.BIN built by
 * uishare/tab/build_fp4.py supmgr_file() and put in by SupManager itself
 * with fpSup/fpsup-ui at its entry.  What v3 did itself it now asks the core for: the list
 * (sups_list), the next-boot switch (disabled_get / disabled_set).  No More
 * options (the user 2026-10-21: a sup's settings are rows on the fpSup page).
 *
 * Built -fropi like the core: one .text, no globals, no string literals.  Its
 * title is the display name in its own header, its texts and variable names
 * are in its data file; its state is the BSS after the file. */
#include "sloader4.h"
#include "fpsup_ui.c"                         /* fpSup/fpsup-ui: its own page, like any sup */

typedef uint32_t u32;
typedef uint8_t u8;

/* No firmware address and no data-file layout here: the page is reached
 * through fpsup-ui, by number. */

#define ROWS      32u
#define VISIBLE   5u
#define TABS      7u
/* build_fp4.SUPMGR_VARS = v3 build_ft6.variables(), SM_ for FT_: */
enum { P_RED, P_GREEN, P_NAME, P_GREY, P_VER };                  /* registration order */
#define V_KEY        0u
#define V_OK         1u
#define V_PART(p, k) (2u + (p) * VISIBLE + (k) - 1u)
#define V_PAGE       (2u + 5u * VISIBLE)
#define V_VERSION    (V_PAGE + 1u)
#define V_VISIBLE    (V_VERSION + 1u)
#define V_LOCK       (V_VISIBLE + VISIBLE)
#define V_SELECTED   (V_LOCK + VISIBLE)
#define V_MORE       (V_SELECTED + VISIBLE)
#define V_DEFAULT    (V_MORE + VISIBLE)
#define V_CHOICE     (V_DEFAULT + VISIBLE)
#define V_FOCUS      (V_CHOICE + VISIBLE)
#define V_RIGHT_FOOTER (V_FOCUS + 3u)
#define V_VERSION_X  (V_RIGHT_FOOTER + 1u)
#define V_TABS       (V_VERSION_X + VISIBLE)
#define V_COUNT      (V_TABS + 4u * TABS)
/* build_fp4.supmgr_extra(), after v3's: slot 0 (parts, then Visible .. Choice,
 * VersionX), FT_Title, FT_Row0 (slot 0's focus id), FT_HeadOn */
#define V_X0         V_COUNT
#define V_TITLE      (V_X0 + 12u)
#define V_ROW0       (V_X0 + 13u)
#define V_HEAD       (V_X0 + 14u)
/* then FT_TOff0..5, FT_TOn0..5: the stock On / Off in the right column (the
 * page's localized texts; user 2026-10-24), On when the sup loads next boot */
#define V_TOFF       (V_X0 + 15u)
#define V_TON        (V_TOFF + SLOTS)
/* then FT_GShow0..5, FT_RShow0..5: the grey name / the red note drawn only when
 * they say something (an empty text still costs every redraw) */
#define V_GSHOW      (V_TON + SLOTS)
#define V_RSHOW      (V_GSHOW + SLOTS)
#define SLOTS        (VISIBLE + 1u)    /* slot 0 (six sups or fewer: no paging) .. 5 */
#define HEADER_FOCUS 3451u
#define TAB_FOCUS    55u               /* MainY5's tab bar: kept, its paint moved aside */
/* build_fp4.SUPMGR_TEXTS */
enum { T_BLANK, T_UNLOAD, T_LOAD, T_FAILED, T_ERROR, T_FOOTER, T_POPUP_FOOTER, T_PAGE_HINT,
       T_VERSION, T_PAGE };
enum { BOOT_ON, BOOT_OFF, BOOT_FAILED };

#define LABEL     40u               /* "Gyro2 (0.1.0)": the display name, the file name's version */
struct mrow { const char *disp; u32 id, boot, bin, err, lock; char label[LABEL]; };

struct smgr {
    struct sl_row row;                 /* resident: the core keeps the pointer */
    const struct sl_svc *svc;
    u32 opened;                        /* how many times the row was chosen   */
    u32 last;                          /* last toggle result                  */
    const u8 *data;                    /* SUPMGR.BIN, installed (0: no page)  */
    u32 n, page, popup, header;
    u32 hint_last, head_last;          /* last footer / header-light posted, + 1 (0: none yet) */
    char pager[8];
    char path[64];                     /* "\fpSup\UI\SUPMGR.BIN"               */
    struct mrow rows[ROWS];
};

/* The UI callbacks find the state here: a word in .text (the resident block). */
__asm__(
    ".text\n"
    ".balign 4\n"
    "smgr_ctx:\n"
    "    .word   0\n");
extern const u32 smgr_ctx;

static struct smgr *state_of(void *block)
{
    const struct sl4_header *h = block;
    return (struct smgr *)((uintptr_t)block + ((h->file_len + 7u) & ~7u));
}

static const char *text(struct smgr *m, u32 i) { return fpui_text(m->data, i); }
static void post_int(struct smgr *m, u32 i, u32 v) { fpui_set(m->data, i, v); }
static void post_str(struct smgr *m, u32 i, const char *s) { fpui_set_text(m->data, i, s); }

/* ---- the list ---------------------------------------------------------------- */
/* "Gyro2 (0.1.0)": `disp`, then the version a file name such as Gyro2_v0.1.0.BIN
 * carries (the user 2026-10-25), as RES-Custom's "OG3K (3008x2000)".  No "_v":
 * the name alone. */
static void label(char *out, const char *disp, const char *file)
{
    u32 n = 0, at = 0, len = 0;
    while (file && file[len]) len++;
    for (u32 i = 0; len > 4u && i + 2u < len - 4u; i++)
        if (file[i] == '_' && (file[i + 1] == 'v' || file[i + 1] == 'V') && file[i + 2] >= '0' && file[i + 2] <= '9')
            at = i + 2u;
    for (; disp && disp[n] && n < LABEL - 1u; n++) out[n] = disp[n];
    int same = disp && file;                            /* no header name: disp is the file name */
    for (u32 i = 0; same && (disp[i] || file[i]); i++) same = disp[i] == file[i];
    if (at && !same && n + 4u < LABEL) {
        out[n++] = ' '; out[n++] = '(';
        for (u32 i = at; i < len - 4u && n + 2u < LABEL; i++) out[n++] = file[i];
        out[n++] = ')';
    }
    out[n] = 0;
}

static void smgr_list(struct smgr *m)
{
    const struct sl_svc *svc = m->svc;
    struct sl_supinfo info;
    m->n = 0;
    for (u32 i = 0; m->n < ROWS && svc->sups_list(svc, i, &info) == SL_OK; i++) {
        if (info.id == SL_UI_ID) continue;                    /* the core's own UI */
        struct mrow *r = &m->rows[m->n++];
        r->disp = info.display;
        label(r->label, info.display, info.name);
        r->id = info.id;
        r->boot = info.status == SL_S_LOADED ? BOOT_ON
                : info.status == SL_S_DISABLED ? BOOT_OFF : BOOT_FAILED;
        r->bin = info.next_boot;
        r->err = 0;
        r->lock = !info.id || info.id == SL_SMGR_ID || info.status == SL_S_OLD_FORMAT
                  || info.status == SL_S_BAD_HEADER;
    }
}

/* Slot k's variables: v3's for 1..5, supmgr_extra()'s for 0.  `group` is
 * V_VISIBLE .. V_CHOICE (each VISIBLE long) or V_VERSION_X. */
static u32 vpart(u32 p, u32 k) { return k ? V_PART(p, k) : V_X0 + p; }
static u32 vslot(u32 group, u32 k)
{
    if (group == V_VERSION_X) return k ? V_VERSION_X + k - 1u : V_X0 + 11u;
    return k ? group + k - 1u : V_X0 + 5u + (group - V_VISIBLE) / VISIBLE;
}

/* Six sups or fewer fill slots 0..5 and the title row is hidden; more page
 * five at a time in slots 1..5 (the user, 2026-10-21). */
static int paged(struct smgr *m) { return m->n > SLOTS; }

static struct mrow *visible(struct smgr *m, u32 k)
{
    if (k >= SLOTS) return 0;
    u32 i = k;
    if (paged(m)) {
        if (!k) return 0;
        i = m->page * VISIBLE + k - 1u;
    }
    return i < m->n ? &m->rows[i] : 0;
}

static u32 pages(struct smgr *m) { return paged(m) ? 1u + (m->n - 1u) / VISIBLE : 1u; }

/* What cell part p shows (v3 allsups.c ft6_part, no version). */
static const char *part(struct smgr *m, const struct mrow *r, u32 p)
{
    if (!r) return text(m, T_BLANK);
    if (p == P_NAME) return r->boot == BOOT_ON ? r->label : text(m, T_BLANK);
    if (p == P_GREY) return r->boot != BOOT_ON ? r->label : text(m, T_BLANK);
    if (p == P_RED)
        return text(m, r->err ? T_ERROR : r->boot == BOOT_ON && !r->bin ? T_UNLOAD
                       : r->boot == BOOT_FAILED && r->bin ? T_FAILED : T_BLANK);
    if (p == P_GREEN) return text(m, !r->err && r->boot == BOOT_OFF && r->bin ? T_LOAD : T_BLANK);
    return text(m, T_BLANK);
}

static u32 tab(struct smgr *m, u32 i)
{
    u32 n = pages(m);
    if (n > TABS) n = TABS;
    /* paged: two pages at least -- one 1024-wide tab drew colour stripes (camera, 2026-10-21) */
    u32 width = n == 2u ? 512u : n == 3u ? 341u : n == 4u ? 256u : n == 5u ? 204u : n == 6u ? 170u : 146u;
    u32 group = (i - V_TABS) / TABS, k = (i - V_TABS) % TABS;
    return group == 0u ? paged(m) && k < n
         : group == 1u ? k == m->page
         : group == 2u ? width * k
         : k + 1u == n ? 1024u - width * k : width;
}

static void hint(struct smgr *m)
{
    /* paged: one fixed "OK <> Page MENU Back" -- redrawing the icon footer on every
       title <-> row move cost ~55 ms (camera, 2026-10-25: 85 -> 32 ms) */
    u32 t = m->popup ? T_POPUP_FOOTER : paged(m) ? T_PAGE_HINT : T_FOOTER;
    if (m->hint_last == t + 1u) return;          /* every post is another GUI update pass */
    m->hint_last = t + 1u;
    post_str(m, V_OK, text(m, t));
}

static char *dec(char *p, u32 v)
{
    u32 tens = 0;
    while (v >= 10u) { v -= 10u; tens++; }
    if (tens) *p++ = (char)('0' + tens);
    *p++ = (char)('0' + v);
    return p;
}

static void refresh(struct smgr *m)
{
    char *p = m->pager;
    if (pages(m) <= 1u) { p[0] = ' '; p[1] = 0; }
    else { p = dec(p, m->page + 1u); *p++ = ' '; *p++ = '/'; *p++ = ' '; p = dec(p, pages(m)); *p = 0; }
    post_str(m, V_PAGE, m->pager);
    for (u32 i = V_TABS; i < V_COUNT; i++) post_int(m, i, tab(m, i));
    post_int(m, V_TITLE, (u32)paged(m));
    for (u32 k = 0; k < SLOTS; k++) {
        struct mrow *r = visible(m, k);
        /* shown before its words, hidden after them: a hidden row is not told
           (paging back from a one-row page left the others gone, user 2026-11-10) */
        if (r) post_int(m, vslot(V_VISIBLE, k), 1);
        for (u32 pp = P_RED; pp <= P_VER; pp++) post_str(m, vpart(pp, k), part(m, r, pp));
        post_int(m, V_GSHOW + k, part(m, r, P_GREY) != text(m, T_BLANK));
        post_int(m, V_RSHOW + k, part(m, r, P_RED) != text(m, T_BLANK));
        post_int(m, vslot(V_LOCK, k), !r || r->lock);
        post_int(m, vslot(V_MORE, k), 0);
        post_int(m, vslot(V_DEFAULT, k), r && !r->bin);
        post_int(m, vslot(V_SELECTED, k), r && !r->bin);
        post_int(m, vslot(V_VERSION_X, k), 49u);
        post_int(m, V_TOFF + k, r && !r->bin);
        post_int(m, V_TON + k, r && r->bin);
        if (!r) post_int(m, vslot(V_VISIBLE, k), 0);
    }
    post_str(m, V_RIGHT_FOOTER, text(m, T_BLANK));
    post_str(m, V_VERSION, text(m, T_VERSION));
    hint(m);
}

/* ---- UI callbacks (the UI thread) ------------------------------------------ */
static struct smgr *ctx(void) { return (struct smgr *)(uintptr_t)smgr_ctx; }

static u32 smgr_key(uintptr_t desc)
{
    struct smgr *m = ctx();
    if (!m || !m->data) return 0;
    u32 key = fpui_value(desc);
    if (!key) return 0;
    if (key == 30u || key == 31u) {
        m->header = key == 31u && paged(m);
        m->popup = 0;
        hint(m);
    } else if (key >= 20u && key <= 20u + SLOTS) {     /* 20 + slot + 1; 20 = closed */
        m->popup = key - 20u;
        hint(m);
    } else if (key == 10u || key == 11u) {
        if (key == 10u && m->page) m->page--;
        if (key == 11u && m->page + 1u < pages(m)) m->page++;
        refresh(m);
    }
    post_int(m, V_KEY, 0);
    return 0;
}

static u32 smgr_choice(uintptr_t desc, u32 k)
{
    struct smgr *m = ctx();
    if (!m || !m->data) return 0;
    u32 choice = fpui_value(desc);
    if (choice == 255u) return 0;
    struct mrow *r = visible(m, k);
    if (r && !r->lock && choice <= 1u && (r->bin == choice || r->err)) {   /* 0 Enable, 1 Disable */
        int rc = m->svc->disabled_set(m->svc, r->id, choice);
        r->err = rc != SL_OK;
        if (!r->err) r->bin = !choice;
    }
    refresh(m);
    post_int(m, vslot(V_CHOICE, k), 255u);
    return 0;
}
static u32 smgr_choice0(uintptr_t d) { return smgr_choice(d, 0); }
static u32 smgr_choice1(uintptr_t d) { return smgr_choice(d, 1); }
static u32 smgr_choice2(uintptr_t d) { return smgr_choice(d, 2); }
static u32 smgr_choice3(uintptr_t d) { return smgr_choice(d, 3); }
static u32 smgr_choice4(uintptr_t d) { return smgr_choice(d, 4); }
static u32 smgr_choice5(uintptr_t d) { return smgr_choice(d, 5); }

static u32 smgr_focus(uintptr_t desc)
{
    struct smgr *m = ctx();
    if (!m || !m->data) return 0;
    u32 v = fpui_value(desc);
    m->header = v == HEADER_FOCUS && paged(m);
    u32 on = v == TAB_FOCUS;                     /* light the header: no other mark there */
    if (m->head_last != on + 1u) {               /* posted only when it changes */
        m->head_last = on + 1u;
        post_int(m, V_HEAD, on);
    }
    hint(m);
    return 0;
}

/* The fpSup page's row: the list again (a choice may have changed it), then the page. */
static int smgr_open(void *arg)
{
    struct smgr *m = arg;
    m->opened++;
    if (!m->data) return SL_BADARG;
    smgr_list(m);
    if (m->page + 1u > pages(m)) m->page = 0;
    refresh(m);
    /* the page takes its focus variable as it opens: the title row, or slot 0 */
    u32 row0 = fpui_first(m->data, V_ROW0);
    post_int(m, V_FOCUS, paged(m) || !row0 ? HEADER_FOCUS : row0);
    return fpui_open(m->svc, text(m, T_PAGE));
}

/* Its page is installed: watch it, fill it. */
static void smgr_ready(void *arg, const void *data)
{
    struct smgr *m = arg;
    const u8 *d = data;
    m->data = d;
    *(volatile u32 *)(uintptr_t)&smgr_ctx = (u32)(uintptr_t)m;
    fpui_watch(d, V_KEY, &smgr_key);
    fpui_watch(d, V_FOCUS, &smgr_focus);
    for (u32 k = 0; k < SLOTS; k++) {
        uintptr_t fn = k == 0 ? (uintptr_t)&smgr_choice0 : k == 1 ? (uintptr_t)&smgr_choice1
                     : k == 2 ? (uintptr_t)&smgr_choice2 : k == 3 ? (uintptr_t)&smgr_choice3
                     : k == 4 ? (uintptr_t)&smgr_choice4 : (uintptr_t)&smgr_choice5;
        fpui_watch(d, vslot(V_CHOICE, k), (u32 (*)(uintptr_t))fn);
    }
    smgr_list(m);
    refresh(m);
}

/* What the page calls for row i of the list: flip next-boot loading.
 * SupManager's own id is refused by the core. */
int smgr_toggle(struct smgr *m, u32 i)
{
    struct sl_supinfo info;
    if (m->svc->sups_list(m->svc, i, &info) != SL_OK) return SL_BADARG;
    u32 off = !m->svc->disabled_get(m->svc, info.id);
    m->last = (u32)m->svc->disabled_set(m->svc, info.id, off);
    return (int)m->last;
}

/* "\fpSup\SUPMGR.BIN" -> "\fpSup\UI\SUPMGR.BIN" (no string literals here) */
static int ui_path(char *out, const char *self)
{
    u32 n = 0, cut = 0;
    while (self[n]) { if (self[n] == '\\') cut = n; n++; }
    if (!cut || n + 4u > 64u) return 0;
    u32 o = 0;
    for (u32 i = 0; i <= cut; i++) out[o++] = self[i];
    out[o++] = 'U'; out[o++] = 'I'; out[o++] = '\\';
    for (u32 i = cut + 1u; i <= n; i++) out[o++] = self[i];
    return 1;
}

int sup_entry(void *block, const struct sl_svc *svc, const char *path)
{
    const struct sl4_header *h = block;
    if (svc->version < 6u || !h->name_off) return SL_RELEASE;   /* 6: borrow; ui_go (7) is optional */
    struct smgr *m = state_of(block);
    m->svc = svc;
    m->row.kind = SL_ROW_JUMP;
    m->row.title = (const char *)block + h->name_off;
    m->row.open = smgr_open;
    m->row.arg = m;
    if (svc->page_add(svc, &m->row) < 0) return SL_RELEASE;
    /* the page (when ported) finds its toggle through the core, not a veneer */
    svc->provide(svc, SL_SMGR_ID, (void *)smgr_toggle);
    /* its own page, now: nothing to wait for (the core's hooks are in place) */
    const void *ui = ui_path(m->path, path) ? fpui_read(svc, m->path) : 0;
    if (ui && !fpui_install(svc, ui)) smgr_ready(m, ui);
    return SL_KEEP;
}
