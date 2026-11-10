/* Loader v4: the owner of the fpSup page (FT_Y6), and the two fixed-rule
 * hooks that let any sup show pages of its own.  Design: projects/loader-v4/
 * DESIGN.md §14.  Included at the end of sloader4.c when FPSUP_UI is defined
 * (build_v4.loader_bin(ui=True)), with the fpsup-ui library in front of it.
 *
 * Before any sup loads, the core (as the pseudo-sup "LOADER.BIN", sup_id
 * SL_UI_ID, so the claims are journaled and undone at power-off) hooks:
 *   - the page-id site: a page named "FT_..." gets MainY5's GUI id;
 *   - the firmware's three string functions: an id in [0x40000000,
 *     0x80000000) is a string's own address (fpsup-ui writes them), anything
 *     else gets the firmware's rule.
 * Neither knows any sup's pages or strings; svc->borrow() is all a sup tells
 * the core (which memory holds strings the firmware must never free).  Sups
 * build their own pages with fpSup/fpsup-ui; sups that must change the same
 * stock UI are coordinated by a container sup, not here (the user, 2026-10-21).
 *
 * After every sup has loaded, the fpSup page -- \fpSup\UI\FPSUP.BIN, put in
 * with fpsup-ui like anyone's -- shows svc->page_add()'s rows: six or fewer
 * in slots 0..5, more five a page under a title row with page tabs. */

#include "fpsup_ui.c"                           /* fpSup/fpsup-ui: the same library as every sup */

#define GUI_SITE     0xC056461Cu
#define GUI_NEXT0    0xC0564638u
#define READER_POOL_LEN 0x10u                   /* the string functions' r0: the pool's length, */
#define READER_POOL     0x14u                   /* and its address */
/* STOCK_GUI, STOCK_RES, STOCK_OWN, STOCK_REM: the four sites' stock words,
 * read from the firmware image by build_v4.py (-D) */

static inline u32 rd32(uintptr_t a) { return *(volatile u32 *)a; }
static inline void wr32(uintptr_t a, u32 v) { *(volatile u32 *)a = v; }

/* The page-id layer (v3 allsups.c's): any page whose name starts "FT_" is
 * MainY5's GUI id.  ft4_next / ft4_st: words in .text (the resident copy),
 * written at load. */
__asm__(
    ".text\n"
    ".balign 4\n"
    ".arm\n"
    "ft4_layer:\n"
    "    cmp     r1, #0\n"
    "    beq     1f\n"
    "    ldrb    ip, [r1]\n"
    "    cmp     ip, #0x46\n"              /* 'F' */
    "    ldrbeq  ip, [r1, #1]\n"
    "    cmpeq   ip, #0x54\n"              /* 'T' */
    "    ldrbeq  ip, [r1, #2]\n"
    "    cmpeq   ip, #0x5F\n"              /* '_' */
    "    moveq   r0, #21\n"                /* MainY5's GUI id */
    "    bxeq    lr\n"
    "1:  ldr     ip, ft4_next\n"
    "    bx      ip\n"
    "ft4_next:\n"
    "    .word   0\n"
    "ft4_st:\n"
    "    .word   0\n"
    ".thumb\n");
extern const uint8_t ft4_layer[];
extern const u32 ft4_next;
extern const u32 ft4_st;               /* struct state *, for the UI callbacks */

static struct state *ui_state(void) { return (struct state *)(uintptr_t)ft4_st; }


/* The firmware's string functions, one hook each (NESTED_HOOKS.md §3 has the
 * rules they keep: r0 and r2 and the flags change, nothing else):
 *
 *   C05E5B58 resolve(reader r0, id r1)     -> string or 0
 *   C05E61C8 owns(reader r0, pointer r1)   -> 1 if the pointer is borrowed
 *   C05E61E0 remain(reader r0, pointer r1) -> bytes from the pointer to the end
 *
 * A private string's id IS its address, at the uncached alias: 0x4... (the
 * file holding it is read at the cached 0xC..., the same memory).  A pool
 * offset is far below 0x40000000 and FFFFFFFF is above 0x80000000, so
 * resolve needs no table, no search and no limit on how many strings or
 * files there are (the user, 2026-10-21: sups are not all ours, their sizes
 * are unknown).  owns / remain are rare (the allocator's free / realloc of a
 * string): C walking the list of files (str_head), reached through
 * str_callc, which gives C an 8-aligned stack and puts back r1, r3, r12, lr.
 * Anything else gets the firmware's own rule, instruction for instruction
 * (uishare/ui_strings.S, proven against the image). */
#define SITE_RES     0xC05E5B58u
#define SITE_OWN     0xC05E61C8u
#define SITE_REM     0xC05E61E0u
__asm__(
    ".text\n"
    ".balign 4\n"
    ".arm\n"
    "str_res:\n"
    "    sub     r2, r1, #0x40000000\n"
    "    cmp     r2, #0x40000000\n"
    "    addlo   r0, r1, #0x80000000\n"
    "    bxlo    lr\n"
    "    cmn     r1, #1\n"
    "    ldrne   r2, [r0, #0x10]\n"
    "    cmpne   r1, r2\n"
    "    movhs   r0, #0\n"
    "    ldrlo   r0, [r0, #0x14]\n"
    "    addlo   r0, r1, r0\n"
    "    bx      lr\n"
    "str_own:\n"
    "    ldr     r2, str_ownfn\n"
    "    b       str_callc\n"
    "str_rem:\n"
    "    ldr     r2, str_remfn\n"
    "str_callc:\n"
    "    push    {r4, lr}\n"
    "    mov     r4, sp\n"
    "    bic     lr, r4, #7\n"
    "    mov     sp, lr\n"
    "    push    {r1, r3, r12, lr}\n"
    "    blx     r2\n"
    "    pop     {r1, r3, r12, lr}\n"
    "    mov     sp, r4\n"
    "    pop     {r4, lr}\n"
    "    bx      lr\n"
    "str_ownfn:\n"
    "    .word   0\n"
    "str_remfn:\n"
    "    .word   0\n"
    "str_head:\n"
    "    .word   0\n"
    ".thumb\n");
extern const uint8_t str_res[], str_own[], str_rem[];
extern const u32 str_ownfn, str_remfn, str_head;

/* One loaded file: [lo, hi) is ours (a string in it is borrowed, never freed). */
struct strfile { struct strfile *next; u32 lo, hi; };

static u32 str_owns_c(u32 reader, u32 p)
{
    for (const struct strfile *f = (const struct strfile *)(uintptr_t)str_head; f; f = f->next)
        if (p >= f->lo && p < f->hi) return 1;
    u32 pool = rd32(reader + READER_POOL);
    return p >= pool && p < pool + rd32(reader + READER_POOL_LEN);
}

static u32 str_remain_c(u32 reader, u32 p)
{
    for (const struct strfile *f = (const struct strfile *)(uintptr_t)str_head; f; f = f->next)
        if (p >= f->lo && p < f->hi) return f->hi - p;
    return rd32(reader + READER_POOL_LEN) + rd32(reader + READER_POOL) - p;
}

/* svc->borrow(): [lo, hi) holds strings handed to the firmware, never to be
 * freed.  One node per call, at the cached alias; no limit. */
static int svc_borrow(const struct sl_svc *svc, const void *lo, const void *hi)
{
    struct state *st = (struct state *)svc;
    u32 a = (u32)(uintptr_t)lo, b = (u32)(uintptr_t)hi;
    if (!a || b <= a) return SL_BADARG;
    u8 *raw = mem_get(st->heap, sizeof(struct strfile));
    if (!raw) return SL_FULL;
    struct strfile *f = (struct strfile *)(uintptr_t)cached((u32)(uintptr_t)raw);
    f->lo = a; f->hi = b;
    f->next = (struct strfile *)(uintptr_t)str_head;
    wr32((uintptr_t)&str_head, (u32)(uintptr_t)f);
    return SL_OK;
}

/* Thumb B.W at `site` to `to` (within 16 MiB). */
static u32 bw_word(u32 site, u32 to)
{
    u32 off = to - (site + 4u), s = off >> 31, i1 = (off >> 23) & 1u, i2 = (off >> 22) & 1u;
    u32 j1 = (1u ^ i1) ^ s, j2 = (1u ^ i2) ^ s;
    return (0xF000u | s << 10 | ((off >> 12) & 0x3FFu)) | (0x9000u | j1 << 13 | j2 << 11 | ((off >> 1) & 0x7FFu)) << 16;
}

/* The three string hooks, through veneers at `ven` (24 bytes of the cave).
 * 0 = in place; 1..3 = that site does not hold its stock word. */
static u32 str_hooks(u32 ven)
{
    /* no arrays of constants: they would be .rodata, which LOADER.BIN does not have */
    for (u32 i = 0; i < 3u; i++) {
        if (rd32(i == 0 ? SITE_RES : i == 1 ? SITE_OWN : SITE_REM) != (i == 0 ? STOCK_RES : i == 1 ? STOCK_OWN : STOCK_REM)) return 1u + i;
        wr32(ven + 8u * i, 0xF000F8DFu);              /* ldr.w pc, [pc, #0] */
        wr32(ven + 8u * i + 4u, i == 0 ? (u32)(uintptr_t)str_res : i == 1 ? (u32)(uintptr_t)str_own
                                                                         : (u32)(uintptr_t)str_rem);
    }
    wr32((uintptr_t)&str_ownfn, (u32)(uintptr_t)&str_owns_c);
    wr32((uintptr_t)&str_remfn, (u32)(uintptr_t)&str_remain_c);
    publish();
    /* the checks first, so a pointer is recognised before it can be produced */
    wr32(SITE_OWN, bw_word(SITE_OWN, ven + 8u));
    wr32(SITE_REM, bw_word(SITE_REM, ven + 16u));
    publish();
    wr32(SITE_RES, bw_word(SITE_RES, ven));
    publish();
    return 0;
}

/* ---- the home page --------------------------------------------------------- */
/* build_fp4.HOME_VARS: eight fixed, then twelve groups of six slots, then the
 * tab bar's four groups of HOME_TABS.
 *
 * Six rows or fewer fill slots 0..5 and the title row is hidden; more page
 * five at a time in slots 1..5 under the title row (the user, 2026-10-21:
 * no paging for six or fewer).  The page writes slot k's codes as j = k + 1:
 * FT_Key 20 + j (its popup has focus, 20 = none), 40 + j (Right/OK on a JUMP
 * or ACTION row). */
enum { V_KEY, V_OK, V_PAGE, V_VERSION, V_FOCUS, V_TITLE, V_ROW0, V_HEAD, V_SLOTS };
/* G_TOG / G_TOFF / G_TON: a TOGGLE row's Off / On are the page's own stock
 * texts (.nloc keys 0080 / 0081, as the stock pages draw them), so they follow
 * the camera's language; these say which to show (user 2026-10-24). */
enum { G_NAME, G_VALUE, G_ITEM_A, G_ITEM_B, G_ITEM_C, G_VISIBLE, G_LOCK, G_DEFAULT,
       G_CHOICE, G_MAX, G_POPH, G_JUMP, G_TOG, G_TOFF, G_TON, G_COUNT };
#define HOME_VISIBLE  SL_PAGE_ROWS                  /* rows a page when paged */
#define HOME_SLOTS    (HOME_VISIBLE + 1u)           /* slot 0 (unpaged only) .. 5 */
#define HOME_TABS     7u
#define V_TABS        (V_SLOTS + G_COUNT * HOME_SLOTS)
#define V_COUNT       (V_TABS + 4u * HOME_TABS)
#define V_GO          V_COUNT                /* build_fp4.home_file: after home_vars() */
#define HEADER_FOCUS  3451u
#define TAB_FOCUS     55u            /* MainY5's tab bar: kept, its paint moved aside */
#define POPUP_ITEM_H  81u
/* build_fp4.HOME_TEXTS */
enum { T_BLANK, T_FOOTER, T_POPUP_FOOTER, T_PAGE_HINT, T_VERSION, T_OFF, T_ON, T_GO, T_COUNT };

static u32 vi(u32 g, u32 k) { return V_SLOTS + g * HOME_SLOTS + k; }

static int home_paged(struct state *st) { return st->nrows > HOME_SLOTS; }

static u32 home_pages(struct state *st)
{
    return home_paged(st) ? 1u + (st->nrows - 1u) / HOME_VISIBLE : 1u;
}

static const struct sl_row *home_row(struct state *st, u32 k)
{
    if (k >= HOME_SLOTS) return 0;
    u32 i = k;
    if (home_paged(st)) {
        if (!k) return 0;
        i = st->ui_page * HOME_VISIBLE + k - 1u;
    }
    return i < st->nrows ? st->rows[i].row : 0;
}

static u32 home_tab(struct state *st, u32 i)
{
    u32 n = home_pages(st);
    if (n > HOME_TABS) n = HOME_TABS;
    /* paged: two pages at least -- one 1024-wide tab drew colour stripes (camera, 2026-10-21) */
    u32 width = n == 2u ? 512u : n == 3u ? 341u : n == 4u ? 256u : n == 5u ? 204u : n == 6u ? 170u : 146u;
    u32 group = (i - V_TABS) / HOME_TABS, k = (i - V_TABS) % HOME_TABS;
    return group == 0u ? home_paged(st) && k < n
         : group == 1u ? k == st->ui_page
         : group == 2u ? width * k
         : k + 1u == n ? 1024u - width * k : width;
}

/* The choice a TOGGLE / LIST row shows: its label j, or " ". */
static const char *home_label(const u8 *b, const struct sl_row *r, u32 j)
{
    if (r->kind == SL_ROW_TOGGLE)                    /* the page's stock Off / On draw it (G_TOG) */
        return fpui_text(b, T_BLANK);
    if (r->kind == SL_ROW_LIST && j < r->n_choices && r->choices[j]) return r->choices[j];
    return fpui_text(b, T_BLANK);
}

static u32 home_choices(const struct sl_row *r)
{
    return !r ? 0u : r->kind == SL_ROW_TOGGLE ? 2u : r->kind == SL_ROW_LIST ? r->n_choices : 0u;
}

/* Every word of slot k: its row, or an empty slot (hidden, locked). */
static void home_slot(struct state *st, u32 k)
{
    const u8 *b = st->ui_home;
    const struct sl_row *r = home_row(st, k);
    u32 n = home_choices(r), v = 0;
    if (n) {
        v = (u32)r->get(r->arg);
        if (v >= n) v = 0;
    }
    /* shown before its words, hidden after them: a hidden row is not told (supmgr.c refresh) */
    if (r) fpui_set(b, vi(G_VISIBLE, k), 1);
    fpui_set_text(b, vi(G_NAME, k), r ? r->title : fpui_text(b, T_BLANK));
    fpui_set_text(b, vi(G_VALUE, k), n ? home_label(b, r, v) : r && r->value ? r->value : fpui_text(b, T_BLANK));
    for (u32 j = 0; j < 3u; j++)
        fpui_set_text(b, vi(G_ITEM_A + j, k), r ? home_label(b, r, j) : fpui_text(b, T_BLANK));
    fpui_set(b, vi(G_LOCK, k), !r);                  /* a locked row's keys never reach us */
    fpui_set(b, vi(G_DEFAULT, k), v);
    fpui_set(b, vi(G_MAX, k), n ? n - 1u : 0u);
    fpui_set(b, vi(G_POPH, k), (n ? n : 1u) * POPUP_ITEM_H);
    fpui_set(b, vi(G_JUMP, k), r && r->kind == SL_ROW_JUMP);
    u32 tog = r && r->kind == SL_ROW_TOGGLE;
    fpui_set(b, vi(G_TOG, k), tog);
    fpui_set(b, vi(G_TOFF, k), tog && v == 0);
    fpui_set(b, vi(G_TON, k), tog && v == 1);
    if (!r) fpui_set(b, vi(G_VISIBLE, k), 0);
}

static void home_hint(struct state *st)
{
    const u8 *b = st->ui_home;
    u32 t = st->ui_popup ? T_POPUP_FOOTER : st->ui_header ? T_PAGE_HINT : T_FOOTER;
    if (st->ui_hint == t + 1u) return;              /* every post is another GUI update pass */
    st->ui_hint = t + 1u;
    fpui_set_text(b, V_OK, fpui_text(b, t));
}

static char *home_dec(char *p, u32 v)               /* 1..99, no division */
{
    u32 tens = 0;
    while (v >= 10u) { v -= 10u; tens++; }
    if (tens) *p++ = (char)('0' + tens);
    *p++ = (char)('0' + v);
    return p;
}

static void home_pager(struct state *st)
{
    char *p = st->ui_pager;
    u32 n = home_pages(st);
    if (n <= 1u) { p[0] = ' '; p[1] = 0; return; }
    p = home_dec(p, st->ui_page + 1u);
    *p++ = ' '; *p++ = '/'; *p++ = ' ';
    p = home_dec(p, n);
    *p = 0;
}

static void home_refresh(struct state *st)
{
    const u8 *b = st->ui_home;
    home_pager(st);
    fpui_set_text(b, V_PAGE, st->ui_pager);
    for (u32 i = V_TABS; i < V_COUNT; i++) fpui_set(b, i, home_tab(st, i));
    for (u32 k = 0; k < HOME_SLOTS; k++) home_slot(st, k);
    home_hint(st);
}

/* svc->ui_go(): the pressed row's request becomes `page` -- the firmware's own
 * transition, as a stock row's Right (a controlAppState request).  Only while
 * home_key runs the row's open(): any other time there is no request to name. */
static int svc_ui_go(const struct sl_svc *svc, const char *page)
{
    struct state *st = (struct state *)svc;
    char *go = st->ui_going && st->ui_home ? (char *)fpui_text(st->ui_home, T_GO) : 0;
    u32 n = 0;
    if (!go || !page) return SL_BADARG;
    while (page[n]) if (++n >= SL_GO_MAX) return SL_BADARG;
    for (u32 i = 0; i <= n; i++) go[i] = page[i];
    return SL_OK;
}

static u32 home_key(uintptr_t desc)
{
    struct state *st = ui_state();
    if (!st || !st->ui_home) return 0;
    u32 key = fpui_value(desc), last = home_pages(st) - 1u;
    if (key == 0u) return 0;
    if (key == 30u || key == 31u) {
        st->ui_header = key == 31u && home_paged(st);
        st->ui_popup = 0;
        home_hint(st);
    } else if (key >= 20u && key <= 20u + HOME_SLOTS) {
        st->ui_popup = key - 20u;                    /* slot + 1; 0 = closed */
        home_hint(st);
    } else if (key == 10u || key == 11u) {
        if (key == 10u && st->ui_page) st->ui_page--;
        if (key == 11u && st->ui_page < last) st->ui_page++;
        home_refresh(st);
    } else if (key > 40u && key <= 40u + HOME_SLOTS) {
        u32 k = key - 41u;
        const struct sl_row *r = home_row(st, k);
        if (r && (r->kind == SL_ROW_JUMP || r->kind == SL_ROW_ACTION) && r->open) {
            /* open() posts its page's variables, then names the page (svc_ui_go);
             * V_GO's next value posted after them: its change event requests T_GO,
             * so the page is built with open()'s posts applied */
            char *go = (char *)fpui_text(st->ui_home, T_GO);
            *go = 0;
            st->ui_going = 1u;
            r->open(r->arg);
            st->ui_going = 0;
            if (*go) fpui_set(st->ui_home, V_GO, ++st->ui_goseq);
            home_slot(st, k);
        }
    }
    fpui_set(st->ui_home, V_KEY, 0);
    return 0;
}

/* V_GO back to 0: the opened page wrote it as it entered (manage_page.enter_write).
 * Forget the name, so this page's change event, firing again as the page is
 * rebuilt, asks for nothing. */
static u32 home_go(uintptr_t desc)
{
    struct state *st = ui_state();
    if (st && st->ui_home && !fpui_value(desc)) *(char *)fpui_text(st->ui_home, T_GO) = 0;
    return 0;
}

static u32 home_choice(uintptr_t desc, u32 k)
{
    struct state *st = ui_state();
    if (!st || !st->ui_home) return 0;
    u32 v = fpui_value(desc);
    const struct sl_row *r = home_row(st, k);
    if (v != 255u) {
        if (r && v < home_choices(r)) r->set(r->arg, (int)v);
        home_slot(st, k);
        fpui_set(st->ui_home, vi(G_CHOICE, k), 255u);
    }
    return 0;
}
static u32 home_choice0(uintptr_t d) { return home_choice(d, 0); }
static u32 home_choice1(uintptr_t d) { return home_choice(d, 1); }
static u32 home_choice2(uintptr_t d) { return home_choice(d, 2); }
static u32 home_choice3(uintptr_t d) { return home_choice(d, 3); }
static u32 home_choice4(uintptr_t d) { return home_choice(d, 4); }
static u32 home_choice5(uintptr_t d) { return home_choice(d, 5); }

static u32 home_focus(uintptr_t desc)
{
    struct state *st = ui_state();
    if (!st || !st->ui_home) return 0;
    u32 v = fpui_value(desc);
    st->ui_header = v == HEADER_FOCUS && home_paged(st);
    u32 on = v == TAB_FOCUS;                            /* light the header: no other mark there */
    if (st->ui_head != on + 1u) {                       /* posted only when it changes */
        st->ui_head = on + 1u;
        fpui_set(st->ui_home, V_HEAD, on);
    }
    home_hint(st);
    return 0;
}

/* page_refresh() from a sup: the slot again, if it is on the current page. */
static void home_dirty(struct state *st, u32 row)
{
    if (!st->ui_home) return;
    if (!home_paged(st)) { home_slot(st, row); return; }
    if (row < st->ui_page * HOME_VISIBLE || row >= (st->ui_page + 1u) * HOME_VISIBLE) return;
    home_slot(st, row - st->ui_page * HOME_VISIBLE + 1u);
}

/* The first values of the home page's variables, before they are registered:
 * focus on the title row when paged, else on slot 0 (FT_Row0's first value). */
static void home_initial(struct state *st, u8 *b)
{
    const struct fpui_file *t = (const struct fpui_file *)b;
    st->ui_home = b;
    home_pager(st);
    for (u32 i = 0; i < t->n_vars && i < V_COUNT; i++) {
        uintptr_t e = (uintptr_t)(b + t->vars_off) + 12u * i + 8u;
        u32 v = rd32(e);
        if (i == V_PAGE) v = (u32)(uintptr_t)st->ui_pager - (u32)(uintptr_t)b;
        /* the tab bar: arriving from the next tab, LEFT / RIGHT go on switching
         * pages, as on the stock pages (user 2026-10-24); DOWN enters the rows */
        else if (i == V_FOCUS) v = TAB_FOCUS;
        else if (i == V_HEAD) v = 1u;                   /* lit: the focus is on the tab bar */
        else if (i == V_TITLE) v = (u32)home_paged(st);
        else if (i >= V_TABS) v = home_tab(st, i);
        else if (i >= V_SLOTS) {
            u32 g = (i - V_SLOTS) / HOME_SLOTS, k = (i - V_SLOTS) % HOME_SLOTS;
            const struct sl_row *r = home_row(st, k);
            u32 n = home_choices(r), sel = 0;
            if (n) { sel = (u32)r->get(r->arg); if (sel >= n) sel = 0; }
            const char *s = 0;
            if (g == G_NAME) s = r ? r->title : 0;
            else if (g == G_VALUE) s = n ? home_label(b, r, sel) : r ? r->value : 0;
            else if (g >= G_ITEM_A && g <= G_ITEM_C) s = r ? home_label(b, r, g - G_ITEM_A) : 0;
            if (g <= G_ITEM_C) v = (u32)(uintptr_t)(s ? s : fpui_text(b, T_BLANK)) - (u32)(uintptr_t)b;
            else v = g == G_VISIBLE ? !!r : g == G_LOCK ? !r : g == G_DEFAULT ? sel
                   : g == G_CHOICE ? 255u : g == G_MAX ? (n ? n - 1u : 0u)
                   : g == G_POPH ? (n ? n : 1u) * POPUP_ITEM_H : g == G_JUMP ? r && r->kind == SL_ROW_JUMP
                   : g == G_TOG ? r && r->kind == SL_ROW_TOGGLE
                   : (r && r->kind == SL_ROW_TOGGLE && sel == (g == G_TON));
        }
        wr32(e, v);
    }
    st->ui_head = 2u;                                   /* V_HEAD posted as 1 */
}

static void home_subscribe(const u8 *b)
{
    *(char *)fpui_text(b, T_GO) = 0;                    /* a row's request does nothing until named */
    fpui_watch(b, V_KEY, &home_key);
    fpui_watch(b, V_FOCUS, &home_focus);
    fpui_watch(b, V_GO, &home_go);
    for (u32 k = 0; k < HOME_SLOTS; k++) {
        uintptr_t fn = k == 0 ? (uintptr_t)&home_choice0 : k == 1 ? (uintptr_t)&home_choice1
                     : k == 2 ? (uintptr_t)&home_choice2 : k == 3 ? (uintptr_t)&home_choice3
                     : k == 4 ? (uintptr_t)&home_choice4 : (uintptr_t)&home_choice5;
        fpui_watch(b, vi(G_CHOICE, k), (u32 (*)(uintptr_t))fn);
    }
}


/* no table: a const array would be .rodata, which LOADER.BIN does not have */
static u32 ui_site(u32 i)
{
    return i == 0 ? GUI_SITE : i == 1 ? SITE_RES : i == 2 ? SITE_OWN : SITE_REM;
}
static u32 ui_stock(u32 i)
{
    return i == 0 ? STOCK_GUI : i == 1 ? STOCK_RES : i == 2 ? STOCK_OWN : STOCK_REM;
}

/* Before any sup: the pseudo-sup "LOADER.BIN" claims the four sites and hooks
 * them.  st->ui_sup = its index (MAX_SUPS: not in place). */
static void ui_early(struct state *st, u8 *s, const struct strings *str)
{
    st->ui_sup = MAX_SUPS;
    if (!str->ui || st->nsups >= MAX_SUPS) return;
    const char *name = str->self;
    struct sup *sp = &st->sups[st->nsups];
    zero(sp, sizeof *sp);
    copy(sp->name, name, slen(name) + 1);
    char *path = make_path(s, str, name);
    copy(sp->path, path, slen(path) + 1);
    sp->id = SL_UI_ID; sp->state = SL_KEEP; sp->status = SL_S_LOADED;
    st->cur = st->nsups++;
    st->jmark = (u32)(uintptr_t)st->jcur;
    st->cmark = st->nclaims;
    for (u32 i = 0; i < 4; ++i) {
        u32 stock = ui_stock(i);
        /* string sites EXCL: a sup still carrying v3 uishare claims them
         * SHARED_UI and is refused (LOAD.LOG names us) instead of loading
         * with a UI that silently never installs */
        if (svc_claim(&st->svc, ui_site(i), 4, &stock, i ? SL_EXCL : SL_CHAIN) != SL_OK) {
            undo_current(st);
            sp->state = SL_RELEASE; sp->status = SL_S_RELEASED;
            logrec(st, L_UI, 2, i, name);
            return;
        }
    }
    u32 ven = svc_cave_alloc(&st->svc, 32);          /* the GUI site's, then the three string sites' */
    if (!ven) { logrec(st, L_UI, 3, 0, name); return; }
    wr32((uintptr_t)&ft4_st, (u32)(uintptr_t)st);
    u32 h = str_hooks(ven + 8u);
    if (h) { logrec(st, L_UI, 0x300u + h, 0, name); return; }
    u32 next = svc_chain_next(&st->svc, GUI_SITE, 0);
    wr32((uintptr_t)&ft4_next, next ? next : GUI_NEXT0);
    wr32(ven, 0xE51FF004u);                       /* ldr pc, [pc, #-4] */
    wr32(ven + 4u, (u32)(uintptr_t)ft4_layer);
    publish();
    wr32(GUI_SITE, 0xEB000000u | (((ven - GUI_SITE - 8u) >> 2) & 0x00FFFFFFu));
    publish();
    st->ui_sup = st->cur;
    logrec(st, L_UI, 0, 0, name);
}

/* After every sup: the fpSup page, through fpsup-ui like any sup's. */
static void ui_load(struct state *st, u8 *s, const struct strings *str)
{
    (void)s;
    if (st->ui_sup >= MAX_SUPS) return;
    const char *name = str->self;
    u8 *home = (u8 *)(uintptr_t)fpui_read(&st->svc, str->ui);
    if (!home) { logrec(st, L_UI, 1, 0, name); return; }
    home_initial(st, home);
    u32 r = fpui_install(&st->svc, home);
    logrec(st, L_UI, 0x100u + r, st->nrows, name);
    if (r) { st->ui_home = 0; return; }
    home_subscribe(home);
}
