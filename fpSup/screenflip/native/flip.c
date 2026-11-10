#include "flip.h"
#ifdef FPF_V4
#include "fpui_stock.c"    /* fpSup/fpsup-ui: the row on the stock TOOLS page */
#else
#include "ui_apply.h"     /* fpSup/uishare: pages composed from each sup's FPUI block */
#endif

/* Ver.5.02 facts. UI registry (fpSup/lossless/native/menu_page.c):
 *   C37B7048        the GUI object; its word +0 is the UI app
 *   app+888 -> +60  the variable registry
 *   C05DB419        lookup(registry, name, &descriptor), Thumb: 0 for hit and miss
 *   C05DB309        register(app, count, {type, name, value}...), Thumb
 *   C0560FB0        subscribe(GUI object, name, fn), ARM; fn(descriptor, x) on
 *                   the UI thread, new value at descriptor +8
 *   C0593F30        queue a UI variable write (x, name, value), ARM: the GUI
 *                   thread does it later, so the name must outlive the call
 *   C02E4420        relayout (display message 4), ARM
 * Display mode (research/firmware/notes/DISPLAY_MODE_SWITCH.md), all ARM:
 *   C0057AE8()      the settings object (0xC31AC530)
 *   C0061BA8(s)     display mode 0..4 of the set in use (4 = LCD off)
 *   C0058340(s)     CinemaMode: 0 STILL
 *   C0061A68(s)     ShootingStyle: 1 = the STILL set even in CINE
 * Tasks and files (fpSup/lossless/native/card.c): tk_cre_tsk C0016A58,
 * tk_sta_tsk C0016BC0, sleep C03705D8; file ctor/open/seek/write/read/close/
 * dtor. is_recording: byte +0x84 of C00178D8() + 0x18 (the system status
 * object, 0xC3033834, built at boot; the shell's `status get is_recording`
 * reads the same byte). NOT *(*(C375896C) + 0x84): C375896C is set only the
 * first time the shell runs `status` (C040FDE0), so on a normal boot it is 0
 * -- read as "recording", which kept every save away (camera, 2026-10-06).
 * Each called routine's first word is checked before the first call. */
#define GUI_OBJECT      0xC37B7048u
#define APP_REGISTRY    0x888u
#define REGISTRY_OFF    0x60u
#define VARIABLE_INT    0u
#define DESC_TYPE       0x00u
#define DESC_NAME       0x04u
#define DESC_VALUE      0x08u
#define CARD_MAGIC      0x50494C46u      /* "FLIP" */
#define TASK_PRIORITY   20u
/* The task's stack. 4 KiB carried the polls, the applies and the row's pushes
 * (camera 2026-10-06, 10 switches) -- but no save ran that day (recording()
 * read 0 as "yes").  With the saves running the camera froze while setting and
 * switching (user 2026-11-10): the card write (file_is, open 7, write, read
 * back) goes through the file system on this stack.  The firmware's own tasks
 * that write files have 0x2000 .. 0x4000 (task table C0B97F90), Lossless's
 * saving task 0x2000; tk_cre_tsk takes no more than 0x2000 (taskcreate.S).
 * v3's 40FLIP.BIN keeps its bytes. */
#ifdef FPF_V4
#define TASK_STACK      0x2000u
#else
#define TASK_STACK      0x1000u
#endif
#define USED __attribute__((used))

#if !defined(__arm__) || UINTPTR_MAX != UINT32_MAX
#error "ARM32 native ABI required"
#endif
#ifndef FPF_SETTINGS_OFF
#error "FPF_SETTINGS_OFF: entry.S `settings`, from the blob's start (build_v3_flip.py)"
#endif

#define peek(a) (*(volatile const uint32_t *)(a))
#define poke(a, v) (*(volatile uint32_t *)(a) = (v))
#define peek8(a) (*(volatile const uint8_t *)(a))

/* {address, first word}: every routine called, checked once at load */
#define CHECKS(X) \
    X(0xC05DB418u, 0x3014B510u)  /* lookup (Thumb) */ \
    X(0xC05DB308u, 0x4FF0E92Du)  /* register (Thumb) */ \
    X(0xC0560FB0u, 0xE92D49F0u)  /* subscribe */ \
    X(0xC02E4420u, 0xE92D4010u)  /* relayout */ \
    X(0xC0593F30u, 0xE92D4070u)  /* queue a variable write */ \
    X(0xC0057AE8u, 0xE92D4070u)  /* settings object */ \
    X(0xC0061BA8u, 0xE92D4030u)  /* display mode */ \
    X(0xC0058340u, 0xE92D4030u)  /* cinema mode */ \
    X(0xC0061A68u, 0xE92D4030u)  /* shooting style */ \
    X(0xC00178D8u, 0xE92D4010u)  /* system status object */ \
    X(0xC0016A58u, 0xE92D0010u)  /* tk_cre_tsk */ \
    X(0xC0016BC0u, 0xE92D0010u)  /* tk_sta_tsk */ \
    X(0xC03705D8u, 0xE92D4030u)  /* sleep */ \
    X(0xC0365E90u, 0xE92D4030u)  /* file ctor */ \
    X(0xC0365FB0u, 0xE92D4070u)  /* file open */ \
    X(0xC03661E0u, 0xE92D40F0u)  /* file seek */ \
    X(0xC03660E8u, 0xE92D40F0u)  /* file write */ \
    X(0xC0366060u, 0xE92D44F0u)  /* file read */ \
    X(0xC0366020u, 0xE92D4010u)  /* file close */ \
    X(0xC0365ED0u, 0xE92D4030u)  /* file dtor */

static uint32_t firmware_ok(void) {
#define CHECK(at, word) if (peek(at) != (word)) return 0;
    CHECKS(CHECK)
#undef CHECK
    return 1;
}

static void relayout(void) { ((void (*)(uint32_t))0xC02E4420u)(0); }
static uint32_t lookup(uintptr_t r, const char *n, uintptr_t *d) {
    return ((uint32_t (*)(uintptr_t, const char *, uintptr_t *))(0xC05DB418u | 1u))(r, n, d);
}
static uint32_t reg(uintptr_t a, uint32_t c, const uint32_t *d) {
    return ((uint32_t (*)(uintptr_t, uint32_t, const uint32_t *))(0xC05DB308u | 1u))(a, c, d);
}
static uint32_t subscribe(uintptr_t g, const char *n, uintptr_t f) {
    return ((uint32_t (*)(uintptr_t, const char *, uintptr_t))0xC0560FB0u)(g, n, f);
}
static void queue_write(const char *n, uint32_t v) {
    ((void (*)(uint32_t, const char *, uint32_t))0xC0593F30u)(0, n, v);
}
static void publish(void) { ((void (*)(void))0xC000E91Cu)(); }
static uintptr_t settings_object(void) { return ((uintptr_t (*)(void))0xC0057AE8u)(); }
static uint32_t display_mode(uintptr_t s) { return ((uint32_t (*)(uintptr_t))0xC0061BA8u)(s); }
static uint32_t cinema_mode(uintptr_t s) { return ((uint32_t (*)(uintptr_t))0xC0058340u)(s); }
static uint32_t shooting_style(uintptr_t s) { return ((uint32_t (*)(uintptr_t))0xC0061A68u)(s); }
static void sleep_ms(uint32_t n) { ((void (*)(uint32_t))0xC03705D8u)(n); }
static uint32_t recording(void) {
    uintptr_t st = ((uintptr_t (*)(void))0xC00178D8u)();
    if (st < 0xC0000000u || st > 0xC8000000u || (st & 3u)) return 1u;  /* unknown: assume yes */
    return peek8(st + 0x18u + 0x84u);
}
/* {exinf, TA_HLNG|TA_DSNAME, entry, priority, stack, "FPFL", "IP", 0} */
static int32_t task_create(uintptr_t entry) {
    volatile uint32_t d[8];
    int32_t id;
    d[0] = 0; d[1] = 0x41u; d[2] = (uint32_t)entry; d[3] = TASK_PRIORITY; d[4] = TASK_STACK;
    d[5] = 0x4C465046u; d[6] = 0x00005049u; d[7] = 0;
    id = ((int32_t (*)(volatile uint32_t *))0xC0016A58u)(d);
    if (id < 1) return id;
    return ((int32_t (*)(int32_t, uint32_t))0xC0016BC0u)(id, 0) == 0 ? id : -1;
}
static void f_ctor(void *o) { ((void (*)(void *, uint32_t))0xC0365E90u)(o, 1u); }
static uint32_t f_open(void *o, const char *p, uint32_t m) {
    return ((uint32_t (*)(void *, const char *, uint32_t))0xC0365FB0u)(o, p, m);
}
static uint32_t f_seek(void *o, uint32_t at) {
    return ((uint32_t (*)(void *, uint32_t, uint32_t))0xC03661E0u)(o, at, 0u);
}
static uint32_t f_write(void *o, const void *b, uint32_t n) {
    return ((uint32_t (*)(void *, const void *, uint32_t))0xC03660E8u)(o, b, n);
}
static uint32_t f_read(void *o, void *b, uint32_t n, uint32_t *got) {
    return ((uint32_t (*)(void *, void *, uint32_t, uint32_t *))0xC0366060u)(o, b, n, got);
}
static void f_close(void *o) { ((void (*)(void *))0xC0366020u)(o); }
static void f_dtor(void *o) { ((void (*)(void *, uint32_t))0xC0365ED0u)(o, 2u); }

/* ---- the panel ---------------------------------------------------------- */
uint32_t fpf_want(uint32_t value) {
    return value == 1u ? 0x333000u : value == 2u ? 0x001000u : value == 3u ? 0x332000u : 0u;
}

uint32_t fpf_touch(uint32_t value) { return value == 1u || value == 3u; }

uint32_t fpf_apply(uint32_t value) {
    uint32_t want, now, touch_ok;
    if (value >= FPF_VALUES) value = 0;
    want = fpf_want(value);
    now = peek(FPF_LAYER_REG);
    touch_ok = peek(FPF_TOUCH_VT_AT) == FPF_TOUCH_VT;
    /* A turned UI with touch left upright would invert the touch screen. */
    if (fpf_touch(value) && !touch_ok) return FPF_APPLY_REFUSED;
    if (touch_ok && peek(FPF_TOUCH_FLAG) != fpf_touch(value)) poke(FPF_TOUCH_FLAG, fpf_touch(value));
    if ((now & FPF_LAYER_MASK) == want) return FPF_APPLY_NONE;
    poke(FPF_LAYER_REG, (now & ~FPF_LAYER_MASK) | want);
    relayout();
    return FPF_APPLY_WRITTEN;
}

/* ---- which slot --------------------------------------------------------- */
static uint32_t set_in_use(uintptr_t s) {      /* DISPLAY_MODE_SWITCH.md §3 */
    return cinema_mode(s) == 0u || shooting_style(s) == 1u ? 0u : 1u;
}

/* The slot Y2_5_1 is editing now, or FPF_NO_KEY (never opened, LCD off). */
static uint32_t editing(uintptr_t s) {
    uint32_t n = peek(FPF_EDITING);
    return n < FPF_CUSTOMS ? set_in_use(s) * FPF_CUSTOMS + n : FPF_NO_KEY;
}

static uint32_t valid(const struct fpf_card *c) { return c && c->magic == CARD_MAGIC; }

/* The row was written (UI thread): remember it for the custom being edited.
 * The panel is NOT touched: that happens when the camera switches into it. */
USED uint32_t fpf_changed(uintptr_t descriptor, struct fpf_card *c) {
    uint32_t key, value;
    if (!valid(c) || !descriptor || (descriptor & 3u)) return 0;
    value = peek(descriptor + DESC_VALUE);
    key = editing(settings_object());
    if (key == FPF_NO_KEY || value >= FPF_VALUES) return 0;
    if (c->table[key] != value) {
        c->table[key] = (uint8_t)value;
        if (c->edits != 0xFFFFFFFFu) ++c->edits;
    }
    return 0;
}

/* ---- this sup's file ---------------------------------------------------- */
static uint32_t pack(const uint8_t *t, uint32_t from) {
    return t[from] | t[from + 1] << 8 | t[from + 2] << 16 | (uint32_t)t[from + 3] << 24;
}

static uint32_t record_check(uint32_t lo, uint32_t hi) {
    return FPF_SETTINGS_MAGIC ^ 1u ^ lo ^ hi ^ 0xFFFFFFFFu;
}

/* Rewrite the record in this file, then read it back. 1 = on the card. */
static uint32_t settings_write(struct fpf_card *c) {
    uint32_t rec[FPF_SETTINGS_WORDS], back[FPF_SETTINGS_WORDS], got = 0, ok;
    void *o = c->fobj;
    rec[0] = FPF_SETTINGS_MAGIC; rec[1] = 1u;
    rec[2] = pack(c->table, 0); rec[3] = pack(c->table, 4);
    rec[4] = record_check(rec[2], rec[3]);
#ifdef FPF_V4
    /* mode 7 creates a missing file: only into a file that is still this sup */
    if (!c->svc || c->svc->file_is(c->svc, c->self_path,
                                   (const void *)(c->base - FPF_HEADER_LEN), FPF_HEADER_LEN) != SL_OK)
        return 0;
#endif
    f_ctor(o);
    ok = f_open(o, c->self_path, 7u) && f_seek(o, FPF_HEADER_LEN + FPF_SETTINGS_OFF) &&
         f_write(o, rec, sizeof rec);
    f_close(o);
    f_dtor(o);
    if (!ok) return 0;
    f_ctor(o);
    ok = f_open(o, c->self_path, 1u) && f_seek(o, FPF_HEADER_LEN + FPF_SETTINGS_OFF) &&
         f_read(o, back, sizeof back, &got) && got == sizeof back;
    f_close(o);
    f_dtor(o);
    for (uint32_t n = 0; ok && n < FPF_SETTINGS_WORDS; ++n) ok = back[n] == rec[n];
    return ok;
}

static void settings_read(struct fpf_card *c, uintptr_t base) {
    const volatile uint32_t *r = (const volatile uint32_t *)(base + FPF_SETTINGS_OFF);
    uint32_t ok = r[0] == FPF_SETTINGS_MAGIC && r[1] == 1u && r[4] == record_check(r[2], r[3]);
    for (uint32_t n = 0; ok && n < FPF_SLOTS; ++n)
        ok = ((n < 4u ? r[2] : r[3]) >> (8u * (n & 3u)) & 0xFFu) < FPF_VALUES;
    c->settings_ok = ok;
    for (uint32_t n = 0; n < FPF_SLOTS; ++n) {
        uint8_t v = ok ? (uint8_t)((n < 4u ? r[2] : r[3]) >> (8u * (n & 3u))) : 0u;
        c->table[n] = c->saved[n] = v;
    }
}

static uint32_t unsaved(const struct fpf_card *c) {
    for (uint32_t n = 0; n < FPF_SLOTS; ++n)
        if (c->table[n] != c->saved[n]) return 1;
    return 0;
}

/* ---- the task ----------------------------------------------------------- */
static void count(uint32_t *n) { if (*n != 0xFFFFFFFFu) ++*n; }

USED void fpf_poll(struct fpf_card *c) {
    uintptr_t s;
    uint32_t set, mode, key;
    if (!valid(c)) return;
    count(&c->polls);
    s = settings_object();
    set = set_in_use(s);
    mode = display_mode(s);
    /* 1. switched into another display mode (or set): apply its value */
    key = mode < FPF_CUSTOMS ? set * FPF_CUSTOMS + mode : 0x100u | set;
    if (key != c->live_key) {
        c->live_key = key;
        count(&c->switches);
        if (mode < FPF_CUSTOMS) {                 /* LCD off: nothing to flip */
            c->last_apply = fpf_apply(c->table[key]);
            count(c->last_apply == FPF_APPLY_REFUSED ? &c->refused : &c->applies);
        }
    }
    /* 2. the menu now edits another custom: show that custom's value */
    key = editing(s);
    if (key != c->edit_key) {
        c->edit_key = key;
        if (key != FPF_NO_KEY) {
            queue_write((const char *)c->name, c->table[key]);
            count(&c->pushes);
        }
    }
    /* 3. keep the file in step, once the table has held still and the camera
     * is not recording */
    if (!c->self_path || !unsaved(c) || recording()) {
        c->save_pending = 0;
        return;
    }
    if (++c->save_pending < FPF_SAVE_POLLS) return;
    c->save_pending = 0;
    {
        uint8_t was[FPF_SLOTS];
        for (uint32_t n = 0; n < FPF_SLOTS; ++n) was[n] = c->table[n];
        if (settings_write(c)) {
            for (uint32_t n = 0; n < FPF_SLOTS; ++n) c->saved[n] = was[n];
            count(&c->saves);
        } else {
            count(&c->save_failed);
        }
    }
}

/* A task cannot end in this firmware. */
USED void fpf_task(struct fpf_card *c) {
    for (;;) {
        fpf_poll(c);
        sleep_ms(FPF_POLL_MS);
    }
}

/* ---- load --------------------------------------------------------------- */
static uint32_t aligned(uintptr_t a) { return a && !(a & 3u); }

static uint32_t same(uintptr_t a, const char *s) {
    if (!a) return 0;
    for (uint32_t n = 0;; ++n) {
        uint32_t ch = peek8(a + n);
        if (ch != (uint8_t)s[n]) return 0;
        if (!ch) return 1;
    }
}

/* The registered integer's descriptor, or 0. */
static uintptr_t variable(uintptr_t app, const char *NAME) {
    uintptr_t d = 0;
    if (lookup(peek(app + APP_REGISTRY) + REGISTRY_OFF, NAME, &d) != 0 || !aligned(d)) return 0;
    if (peek(d + DESC_TYPE) != VARIABLE_INT || !same(peek(d + DESC_NAME), NAME)) return 0;
    return d;
}

/* Before the registration: refuse (SL_RELEASE, nothing outside this block
 * written). From it on: keep (the registry borrows the name in the block). */
static uint32_t refuse(struct fpf_card *c, uint32_t why) { if (c) c->result = why; return 1; }
static uint32_t stop(struct fpf_card *c, uint32_t why) { c->result = why; return 0; }

USED uint32_t fpf_card_init(struct fpf_card *c, uintptr_t base, const char *path
#ifdef FPF_V4
                            , const struct sl_svc *svc
#endif
                            ) {
    volatile uint32_t *w;
    const char *NAME;
    uintptr_t app;
    if (!c || ((uintptr_t)c & 7u) || c->magic || c->result || !c->ui_at || !c->ui_len ||
        !c->task_entry || !c->changed_entry)
        return refuse(c, FPF_INVALID);
    c->magic = CARD_MAGIC;
    c->base = base;
#ifdef FPF_V4
    c->svc = svc;
#endif
    c->task_id = -1;
    c->live_key = c->edit_key = FPF_NO_KEY;
    w = c->name;                                    /* MV_fpScreenFlip; .text only */
    w[0] = 0x665F564Du; w[1] = 0x72635370u; w[2] = 0x466E6565u; w[3] = 0x0070696Cu; w[4] = 0u;
    NAME = (const char *)c->name;
    if (!firmware_ok()) return refuse(c, FPF_FIRMWARE);
    settings_read(c, base);
    c->self_path = c->settings_ok ? path : 0;     /* a damaged record is never rewritten */
    app = peek(GUI_OBJECT);
    if (!aligned(app) || !aligned(peek(app + APP_REGISTRY))) return refuse(c, FPF_NO_GUI);
    if (!variable(app, NAME)) {
        uint32_t def[3];
        def[0] = VARIABLE_INT;
        def[1] = (uint32_t)(uintptr_t)NAME;
        def[2] = 0u;
        if (reg(app, 1, def) != 0) return refuse(c, FPF_REGISTER);
        c->registered = 1;
        if (!variable(app, NAME)) return stop(c, FPF_VARIABLE);
    }
    publish();
    {
        struct uia_outcome ui;
#ifdef FPF_V4
        c->ui_result = fpui_stock_apply(svc, (const void *)c->ui_at, c->ui_len, &ui);
#else
        c->ui_result = uia_apply(c->ui_at, c->ui_len, &ui);
#endif
        c->ui_op = ui.op;
        if (c->ui_result != UIA_OK) return stop(c, FPF_UI);
        c->first_id = ui.first_id;
        c->row_y = ui.n_slots ? ui.slots[0] : 0;
        c->page = ui.page;
    }
    c->subscribe_result = subscribe(GUI_OBJECT, NAME, c->changed_entry);
    if (c->subscribe_result != 0) return stop(c, FPF_SUBSCRIBE);
    publish();                                      /* the task reads this state */
    c->task_id = task_create(c->task_entry);
    if (c->task_id < 1) return stop(c, FPF_TASK);
    c->result = FPF_READY;
    return 0;
}
