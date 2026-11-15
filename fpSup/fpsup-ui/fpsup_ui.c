/* fpsup-ui: a sup's own pages on the SIGMA fp (fw 5.02), loader v4.
 *
 * What uishare did for v3 -- load a page pack, give it private strings,
 * register its variables and pages -- without the sharing: no nested layers,
 * no string search, no copies, no limits (the user, 2026-10-21).  Each sup
 * that wants pages #includes this file (one -fropi unit, as every v4 sup);
 * LOADER.BIN uses it for the fpSup page too.  Nothing here coordinates with
 * other sups: a page of yours touches nobody else's.  Sups that DO need to
 * change the same stock UI go under a container sup that coordinates them.
 *
 * The data file (uishare/tab/build_fp4.py, magic "FT4S") is the sup's own:
 * its page pack, its variables, its fixed texts, its strings.  A private
 * string's id is the string's own address at the uncached alias (0x4...):
 * LOADER.BIN's resolve hook turns any id in [0x40000000, 0x80000000) back
 * into the cached address, with no table and no knowledge of who owns it
 * (v4/fpsup_home.c).  The only thing a sup tells the loader is which memory
 * holds such strings, svc->borrow(), so the firmware never frees them.
 *
 *     const void *ui = fpui_read(svc, "\\fpSup\\UI\\MINE.BIN");
 *     if (ui && !fpui_install(svc, ui)) {
 *         fpui_watch(ui, MY_KEY, &my_key_changed);     // on the UI thread
 *         fpui_set(ui, MY_VALUE, 3);
 *     }
 *     ... from the fpSup page row's open(): fpui_open(svc, "FT_MINE");
 *
 * Variables and texts are reached by number, in the order build_fp4.ft4_file()
 * was given them; a wrong file or number does nothing.  Page names that
 * start "FT_" get MainY5's GUI id (LOADER.BIN's page-id hook). */
#ifndef FPSUP_UI_LIB
#define FPSUP_UI_LIB
#include <stdint.h>
#include "sloader4.h"

#define FPUI_MAGIC        0x53345446u     /* "FT4S" */
#define FPUI_GUI_OBJECT   0xC37B7048u
#define FPUI_NBR_LOAD     0xC05E84D9u     /* Thumb: (app, pack, len, &reader) */
#define FPUI_LANG_STALE   0xC05DE6B1u     /* Thumb: (app) -- texts are translated again on the next GUI pass */
#define FPUI_UI_BUSY      0xC05DCCB9u     /* Thumb: (app) -- 1 while the GUI is inside a screen change */
#define FPUI_LANG_APPLY   0xC05DE5B9u     /* Thumb: (app) -- translate the stale texts now */
#define FPUI_SLEEP_MS     0xC01F89C4u     /* ARM: tk_dly_tsk(ms); an error, not a wait, outside a task */
#define FPUI_BUSY_POLLS   100u            /* x FPUI_BUSY_POLL_MS: at most half a second per load */
#define FPUI_BUSY_POLL_MS 5u
#define FPUI_NBU_BASE     0xC18C0460u
#define FPUI_VAR_REGISTER 0xC05DB309u     /* Thumb: (app, n, {type, name, first value}) */
#define FPUI_VAR_WATCH    0xC0560FB0u     /* ARM: (GUI object, name, fn) -- fn(desc) on the UI thread */
#define FPUI_POST_INT     0xC0593F30u     /* ARM: (0, name, value) queued to the GUI */
#define FPUI_POST_STR     0xC0593FE0u     /* ARM: (0, name, text) -- the GUI keeps the pointer */
#define FPUI_SCREENS      0xC054DD38u     /* ARM: () -> the screen manager; vt+0x48 (mgr, name) */
#define FPUI_ALLOC_GET    0xC001D740u     /* (desc, class, bytes, 0) */
#define FPUI_ALLOC_ADDR   0xC001D7F0u     /* (desc) -> the uncached alias */
#define FPUI_VAR_TEXT     2u

/* The data file's header (build_fp4.ft4_file): word offsets from its first byte. */
struct fpui_file {
    uint32_t magic, pack_off, pack_len;
    uint32_t strs_off, n_str;              /* n_str data offsets of NUL-ended strings   */
    uint32_t n_refs, refs_off;             /* {pack offset, string #}: BE id fields     */
    uint32_t n_vars, vars_off;             /* {type, name, first value}: offsets / ints */
    uint32_t logo_off, logo_len;           /* an image pack; 0 = none                   */
    uint32_t texts_off, n_texts;           /* fixed texts: data offsets                 */
    char machine[12];                      /* the pack's state machine                  */
    uint32_t file_len;
};

typedef uint32_t (*fpui_fn1)(uint32_t);
typedef uint32_t (*fpui_fn3)(uint32_t, uint32_t, uint32_t);
typedef uint32_t (*fpui_fn4)(uint32_t, uint32_t, uint32_t, uint32_t);
#define FPUI_FW(addr, type) ((type)(uintptr_t)(addr))

static inline uint32_t fpui_rd(uintptr_t a) { return *(volatile const uint32_t *)a; }
static inline void fpui_wr(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }
static inline int fpui_bad(uintptr_t p) { return !p || (p & 3u); }

static uint32_t fpui_be(uint32_t v)
{
    return (v >> 24) | ((v >> 8) & 0xFF00u) | ((v << 8) & 0xFF0000u) | (v << 24);
}

static int fpui_same(uintptr_t a, const char *b)
{
    for (;; ++a, ++b) {
        if (*(const volatile uint8_t *)a != (uint8_t)*b) return 0;
        if (!*b) return 1;
    }
}

/* A file in memory that this library knows; anything else is 0. */
static const struct fpui_file *fpui_file(const void *ui)
{
    const struct fpui_file *t = ui;
    return !fpui_bad((uintptr_t)ui) && t->magic == FPUI_MAGIC ? t : 0;
}

static int fpui_header_ok(const struct fpui_file *h)
{
    return h->magic == FPUI_MAGIC && h->file_len >= sizeof *h && h->file_len <= 0x01000000u
        && h->pack_off + h->pack_len <= h->file_len && h->strs_off + 4u * h->n_str <= h->file_len
        && h->refs_off + 8u * h->n_refs <= h->file_len && h->vars_off + 12u * h->n_vars <= h->file_len
        && h->texts_off + 4u * h->n_texts <= h->file_len && h->logo_off + h->logo_len <= h->file_len;
}

/* The file at `path` into memory of its own, at the cached alias, on whole
 * 64-byte lines (none shared with the allocator's books).  0: none. */
static const void *fpui_read(const struct sl_svc *svc, const char *path)
{
    struct fpui_file h;
    if (!svc || !path || svc->file_read(svc, path, &h, sizeof h) != (int)sizeof h || !fpui_header_ok(&h))
        return 0;
    uint32_t desc[4] = {0, 0, 0, 0};
    FPUI_FW(FPUI_ALLOC_GET, void (*)(uint32_t *, uint32_t, uint32_t, uint32_t))(desc, 0, h.file_len + 128u, 0);
    uintptr_t raw = FPUI_FW(FPUI_ALLOC_ADDR, uintptr_t (*)(uint32_t *))(desc);
    if (!raw) return 0;
    uintptr_t ub = (raw + 63u) & ~(uintptr_t)63u;
    if (svc->file_read(svc, path, (void *)ub, h.file_len) != (int)h.file_len) return 0;
    svc->publish(svc);                          /* stale lines of the cached alias go */
    return (const void *)(ub >= 0x40000000u && ub < 0x80000000u ? ub + SL_ALIAS : ub);
}

static const char *fpui_text(const void *ui, uint32_t i)
{
    const struct fpui_file *t = fpui_file(ui);
    return t && i < t->n_texts ? (const char *)ui + fpui_rd((uintptr_t)ui + t->texts_off + 4u * i) : 0;
}

static const char *fpui_var(const void *ui, uint32_t i)
{
    const struct fpui_file *t = fpui_file(ui);
    return t && i < t->n_vars ? (const char *)ui + fpui_rd((uintptr_t)ui + t->vars_off + 12u * i + 4u) : 0;
}

/* Variable i's first value (a text's: its data offset). */
static uint32_t fpui_first(const void *ui, uint32_t i)
{
    const struct fpui_file *t = fpui_file(ui);
    return t && i < t->n_vars ? fpui_rd((uintptr_t)ui + t->vars_off + 12u * i + 8u) : 0;
}

static void fpui_set(const void *ui, uint32_t i, uint32_t v)
{
    const char *n = fpui_var(ui, i);
    if (n) FPUI_FW(FPUI_POST_INT, fpui_fn3)(0, (uint32_t)(uintptr_t)n, v);
}

/* The GUI keeps `text`'s pointer: it must stay resident. */
static void fpui_set_text(const void *ui, uint32_t i, const char *text)
{
    const char *n = fpui_var(ui, i);
    if (n && text) FPUI_FW(FPUI_POST_STR, fpui_fn3)(0, (uint32_t)(uintptr_t)n, (uint32_t)(uintptr_t)text);
}

/* fn(desc) on the UI thread when the page changes variable i; the value is fpui_value(desc). */
static int fpui_watch(const void *ui, uint32_t i, uint32_t (*fn)(uintptr_t desc))
{
    const char *n = fpui_var(ui, i);
    if (!n || !fn) return SL_BADARG;
    FPUI_FW(FPUI_VAR_WATCH, fpui_fn3)(FPUI_GUI_OBJECT, (uint32_t)(uintptr_t)n, (uint32_t)(uintptr_t)fn);
    return SL_OK;
}

static uint32_t fpui_value(uintptr_t desc) { return desc ? fpui_rd(desc + 8u) : 0; }

/* The page `name` now (the firmware's `gui scr set`): from the UI thread only. */
static int fpui_show(const char *name)
{
    uintptr_t m = FPUI_FW(FPUI_SCREENS, uintptr_t (*)(void))();
    if (fpui_bad(m) || !name) return SL_BADARG;
    FPUI_FW(fpui_rd(fpui_rd(m) + 0x48u), void (*)(uintptr_t, const char *))(m, name);
    return SL_OK;
}

/* A JUMP row's open(): the page `name` through the firmware's own transition --
 * the fpSup page's request, which this pack's machine must take (FT_Y6 -> name,
 * request = name; build_fp4.open_transition).  A loader without svc->ui_go, or a
 * call from anywhere else, sets the screen directly instead (fpui_show): the menu
 * then drops fast keys until it is left (camera, 2026-10-25). */
static int fpui_open(const struct sl_svc *svc, const char *name)
{
    if (svc && svc->version >= 7u && svc->ui_go && svc->ui_go(svc, name) == SL_OK) return SL_OK;
    return fpui_show(name);
}

/* One stock pack load, the way stock's own wrapper leaves the UI (C05DAA40): the load
 * unbinds every resource already handed out (C05E0940), the localised texts among
 * them, and the GUI draws their keys at once ("1474" for "Now Connecting...";
 * camera 2026-11-15: C05E0940 alone turns an open menu into numbers).  So the
 * language is marked stale and translated again right after it.
 *
 * Stock does not translate while the GUI is in the middle of a screen change
 * (C05DCCB8, as C05DE718), and from this thread neither may we; the keys then stay
 * up until the GUI is done -- half a second of "1474" at a boot with an SSD
 * attached, where LOAD.LOG showed two such stretches (camera 2026-11-15).  So the
 * load itself waits for the GUI to be idle, a little: sleeping also hands it the
 * CPU the boot thread was keeping from it.  Where the sleep does not block the
 * loop is over at once, and the load goes ahead as before. */
static uint32_t fpui_load(uintptr_t app, const uint8_t *pack, uint32_t len, uintptr_t *reader)
{
    uint32_t bad, i;
    for (i = 0; i < FPUI_BUSY_POLLS && FPUI_FW(FPUI_UI_BUSY, fpui_fn1)((uint32_t)app); i++)
        FPUI_FW(FPUI_SLEEP_MS, fpui_fn1)(FPUI_BUSY_POLL_MS);
    bad = FPUI_FW(FPUI_NBR_LOAD, fpui_fn4)((uint32_t)app, (uint32_t)(uintptr_t)pack, len, (uint32_t)(uintptr_t)reader);
    FPUI_FW(FPUI_LANG_STALE, fpui_fn1)((uint32_t)app);
    if (!FPUI_FW(FPUI_UI_BUSY, fpui_fn1)((uint32_t)app)) FPUI_FW(FPUI_LANG_APPLY, fpui_fn1)((uint32_t)app);
    return bad;
}

/* The pages and their state machine, moved to the front of the app's list. */
static uint32_t fpui_register(const void *ui)
{
    const struct fpui_file *t = ui;
    const uint8_t *b = ui;
    uintptr_t app = fpui_rd(FPUI_GUI_OBJECT), screens, screen, reader, rdr = 0, data, last;
    if (fpui_bad(app) || !fpui_rd(app + 0x80u)) return 3;                 /* screens */
    screens = fpui_rd(app + 0x8Cu);
    if (fpui_bad(screens)) return 4;
    screen = fpui_rd(screens);
    if (fpui_bad(screen)) return 4;
    reader = fpui_rd(screen + 0x24u);
    if (fpui_bad(reader) || fpui_rd(reader + 0x24u) != FPUI_NBU_BASE || fpui_rd(reader + 0x08u) != app)
        return 4;
    if (t->logo_len && fpui_load(app, b + t->logo_off, t->logo_len, 0)) return 6;
    if (fpui_rd(app + 0x80u) > fpui_rd(app + 0x84u)) return 5;
    uint32_t n0 = fpui_rd(app + 0xF8u), n;
    if (n0 > fpui_rd(app + 0xFCu)) return 5;
    uint32_t bad = fpui_load(app, b + t->pack_off, t->pack_len, &rdr);
    if (bad) return 6;
    if (fpui_bad(rdr)) return 7;
    fpui_wr(rdr + 0x10u, fpui_rd(reader + 0x10u));      /* the stock pool, as the stock reader has it */
    fpui_wr(rdr + 0x14u, fpui_rd(reader + 0x14u));
    n = fpui_rd(app + 0xF8u);
    if (n != n0 + 1u) return 0;                         /* v3: a machine count that moved is not fatal */
    data = fpui_rd(app + 0x104u);
    last = fpui_rd(data + 4u * (n - 1u));
    if (fpui_bad(last) || !fpui_same(fpui_rd(last + 0x08u), t->machine)) return 0;
    for (uint32_t i = n - 1u; i; --i) fpui_wr(data + 4u * i, fpui_rd(data + 4u * (i - 1u)));
    fpui_wr(data, last);
    return 0;
}

/* A file read by fpui_read (or any FT4 file the sup holds at the cached
 * alias): its strings' ids, the loader told those bytes are borrowed, its
 * variables registered, its pages known.  0 = installed. */
static uint32_t fpui_install(const struct sl_svc *svc, const void *ui)
{
    const struct fpui_file *t = fpui_file(ui);
    uint8_t *b = (uint8_t *)(uintptr_t)ui;
    if (!svc || !t || !fpui_header_ok(t)) return 1;
    if ((uint32_t)(uintptr_t)ui < SL_ALIAS) return 2;    /* the ids are the uncached alias of it */
    for (uint32_t i = 0; i < t->n_refs; i++) {
        uintptr_t ref = (uintptr_t)(b + t->refs_off) + 8u * i;
        uint32_t k = fpui_rd(ref + 4);
        if (k >= t->n_str) return 8;
        uint32_t at = (uint32_t)(uintptr_t)b + fpui_rd((uintptr_t)(b + t->strs_off + 4u * k));
        fpui_wr((uintptr_t)(b + t->pack_off + fpui_rd(ref)), fpui_be(at - SL_ALIAS));
    }
    if (svc->borrow(svc, b, b + t->file_len) != SL_OK) return 9;
    uintptr_t app = fpui_rd(FPUI_GUI_OBJECT);
    if (fpui_bad(app)) return 3;
    for (uint32_t i = 0; i < t->n_vars; i++) {
        uintptr_t e = (uintptr_t)(b + t->vars_off) + 12u * i;
        uint32_t def[3];
        def[0] = fpui_rd(e);
        def[1] = (uint32_t)(uintptr_t)(b + fpui_rd(e + 4));
        def[2] = def[0] == FPUI_VAR_TEXT ? (uint32_t)(uintptr_t)(b + fpui_rd(e + 8)) : fpui_rd(e + 8);
        if (FPUI_FW(FPUI_VAR_REGISTER, fpui_fn3)((uint32_t)app, 1, (uint32_t)(uintptr_t)def)) return 10;
    }
    return fpui_register(ui);
}

#endif
