/* The TEST card's resident logic: four hook bodies and the take lifecycle.
 *
 * Built only into the direct-compression test card (§12, §16). It is the one
 * place that turns the proven modules into something a camera runs:
 *
 *   rec    C03A33C8  REC preparation: reserve the take's RAW workspace and
 *                    start a lossless take, then set the frame adapter up.
 *   arrive C038BFF0  every CinemaDNG frame reaching the creator.
 *   stop   C0398D88  (entry) every native stop check: finish the held frame,
 *                    then end the take and give the workspace back.
 *   flush  C03A5490  the writer's final flush: the prepared IFD and length.
 *
 * TEST-CARD POLICY, deliberately different from the product contract:
 *
 *   * Lossless RAW is chosen on the camera: a row under Audio Recording on
 *     SHOOT page 2 (CINE), menu_page.c. It lives in memory only and is OFF
 *     at every boot; while it is OFF every take is exactly stock, and so is
 *     every take if the row could not be installed.
 *   * It NEVER refuses a recording. If lossless cannot be prepared -- another
 *     format, no memory, anything -- the take records RAW exactly as stock,
 *     provided the firmware itself agreed to record. The product rule "no
 *     silent RAW when the user chose ON" is about a menu promise; this card
 *     makes no promise and says TEST on its banner.
 *   * Readiness is ASSERTED here, not proven: codec, writer, header,
 *     playback, storage and REC-gate proofs do not all exist yet (in-camera
 *     playback of tiled Compression=7 cannot exist at all). This card is how
 *     the remaining ones get measured. The assertion lives in test_readiness()
 *     and nowhere else.
 *   * CINE, CinemaDNG and SD are asserted the same way. A MOV take never
 *     reaches the kind-1 creator, and its REC preparation fails the mode-3
 *     reservation, so it simply records as stock.
 */
#include "rec_hook.h"
#include "frame_hold.h"
#include "flush_site.h"
#ifdef FPL_V4
#include "menu_row4.h"           /* Loader v4: a TOGGLE row on the fpSup page */
#else
#include "menu_page.h"
#endif
#include "play_decode.h"
#include "record_diag.h"
#include "header_tag.h"

#define FPL_CARD_MAGIC 0x44524143u               /* "CARD" */
#define FPL_TRACE      512u
#define FPL_ELOG       2048u
/* Lossless RAW ON/OFF, kept in this sup's own file (Loader v3 passes its path):
 * card.S `settings`, 16 bytes {"FLST", version 1, 0/1, check}. Read from the
 * block at boot; rewritten in place (open 7, seek, write, read back) by the codec
 * task when the row has held another value for FPL_SAVE_POLLS idle passes and
 * nothing is recording. Never the camera's own settings store. */
#define FPL_SETTINGS_MAGIC 0x54534c46u    /* "FLST" */
/* the codec task waits this many ticks on a running job's flag at a time:
 * it wakes the moment the engine finishes, and at least this often to check
 * a stalled job's give-up time */
#define FPL_TASK_WAIT      10u
#define FPL_SAVE_POLLS     100u           /* x 10 ms idle sleep = 1 s stable */
#define FPL_QUIET_US       3000000u       /* no REC and no frame for this long */
#ifdef FPL_V4
#define FPL_HEADER_LEN     48u            /* the FSB4 header before the blob */
#else
#define FPL_HEADER_LEN     32u            /* the FSB1 header before the blob */
#endif
#define USED __attribute__((used))
/* diagnostic only (FPL_DIAG_HOOK_TIME): every hook's C entry is wrapped to
 * count its calls and time, and to keep the stack pointer it ran on -- the
 * task, from the firmware's TCB stack ranges (C301EACC, 0x34 a task). */
#ifdef FPL_DIAG_HOOK_TIME
#define HOOK_DEF static
#define HOOK(n) n##_body
#else
#define HOOK_DEF USED
#define HOOK(n) n
#endif

#if defined(__arm__) && UINTPTR_MAX == UINT32_MAX
static uint32_t card_original_prepare(uintptr_t camera, const uint32_t *request) {
    typedef uint32_t (*fn)(uintptr_t, const uint32_t *);
    return ((fn)0xc03a2438u)(camera, request);
}
static uint32_t card_original_enqueue(uintptr_t creator, uint32_t id, uint32_t argument) {
    typedef uint32_t (*fn)(uintptr_t, uint32_t, uint32_t);
    return ((fn)0xc037dd50u)(creator, id, argument);
}
#ifdef FPL_DIAG_HOOK_TIME
#define CARD_ENQ(c, cr, i, a) card_timed_enqueue(c, cr, i, a)
#else
#define CARD_ENQ(c, cr, i, a) card_original_enqueue(cr, i, a)
#endif
/* The frames' own allocator: C037A990 gets every kind-1 frame buffer with
 * C001CFD8(C001CF78(10), &frame[0x68], bytes, 0x400, 0) and C0374180 frees
 * it with C001D3D0. The spare comes from the same place, or the firmware
 * could not free it once it is a frame's. */
static void card_get_spare(void *record, uint32_t bytes) {
    typedef uintptr_t (*pool_fn)(uint32_t);
    typedef uintptr_t (*get_fn)(uintptr_t, void *, uint32_t, uint32_t, uint32_t);
    ((get_fn)0xc001cfd8u)(((pool_fn)0xc001cf78u)(10), record, bytes, 0x400, 0);
}
static void card_free_spare(void *record) {
    typedef void (*fn)(void *);
    ((fn)0xc001d3d0u)(record);
}
/* tk_cre_tsk C0016A58 + tk_sta_tsk C0016BC0, as fp_usb_shell/asm/
 * taskcreate.S: {exinf, tskatr TA_HLNG|TA_DSNAME, entry, itskpri, stksz,
 * dsname[8], 0}. Word stores: an initialised struct would be .rodata. */
static int32_t card_task_create(uintptr_t entry, uint32_t priority) {
    typedef int32_t (*cre_fn)(volatile uint32_t *);
    typedef int32_t (*sta_fn)(int32_t, uint32_t);
    volatile uint32_t d[8];
    int32_t id;
    d[0] = 0;
    d[1] = 0x41u;
    d[2] = (uint32_t)entry;
    d[3] = priority;
    d[4] = 0x2000u;
    d[5] = 0x434c5046u;                          /* "FPLC" */
    d[6] = 0x0045444fu;                          /* "ODE\0" */
    d[7] = 0;
    id = ((cre_fn)0xc0016a58u)(d);
    if (id < 1) return id;
    return ((sta_fn)0xc0016bc0u)(id, 0) == 0 ? id : -1;
}
static void card_sleep_ms(uint32_t n) {          /* C03705D8 -> tk_dly_tsk */
    typedef void (*fn)(uint32_t);
    ((fn)0xc03705d8u)(n);
}
static uint32_t card_irq_off(void) {
    typedef uint32_t (*fn)(void);
    return ((fn)0xc000ec14u)();
}
static void card_irq_restore(uint32_t mask) {
    typedef void (*fn)(uint32_t);
    ((fn)0xc000ec24u)(mask);
}
/* The file API loader.S and the 加載器 use (sloader.c), plus the seek the
 * firmware's own update reader uses (LmountFwUp readFile: open 1, seek, read).
 * Open mode 7 overwrites without truncating; 0 from open/write is failure. */
static void card_f_ctor(void *o)                      { ((void (*)(void *, uint32_t))0xc0365e90u)(o, 1u); }
static uint32_t card_f_open(void *o, const char *p, uint32_t mode)
                                                      { return ((uint32_t (*)(void *, const char *, uint32_t))0xc0365fb0u)(o, p, mode); }
static uint32_t card_f_seek(void *o, uint32_t at)     { return ((uint32_t (*)(void *, uint32_t, uint32_t))0xc03661e0u)(o, at, 0u); }
static uint32_t card_f_write(void *o, const void *b, uint32_t n)
                                                      { return ((uint32_t (*)(void *, const void *, uint32_t))0xc03660e8u)(o, b, n); }
static uint32_t card_f_read(void *o, void *b, uint32_t n, uint32_t *got)
                                                      { return ((uint32_t (*)(void *, void *, uint32_t, uint32_t *))0xc0366060u)(o, b, n, got); }
static void card_f_close(void *o)                     { ((void (*)(void *))0xc0366020u)(o); }
static void card_f_dtor(void *o)                      { ((void (*)(void *, uint32_t))0xc0365ed0u)(o, 2u); }
/* status get is_recording: *(*(C375896C) + 0x84), one byte. The pointer is
 * only set once the status table has been asked (2026-10-06: 0 after a boot),
 * so this is one sign among others (settings_poll). */
static uint32_t card_status_recording(void) {
    uintptr_t p = *(volatile const uint32_t *)0xc375896cu;
    if (p < 0xc0000000u || p > 0xc8000000u) return 0u;
    return *(volatile const uint8_t *)(p + 0x84u);
}
static uint32_t card_tick_us(void) {             /* C002B6E0: the 1 MHz counter */
    typedef uint32_t (*fn)(void);
    return ((fn)0xc002b6e0u)();
}
/* The CinemaDNG descriptor pool, MPoolFixed<4380,96> (projects/open-gate/notes/
 * HSW_240FPS_MODE12.md §53, §59.3): its object pointer at C2F1F3D8, the free
 * count at +0x112C -- the rec log's `sdb`. A frame holds one from its request
 * until the writer is finished with it; REC stops ("vbuf") when it runs out. */
static uint32_t card_pool_left(void) {
    uintptr_t pool = *(volatile const uint32_t *)0xc2f1f3d8u;
    if (pool < 0xc0000000u || pool > 0xc8000000u || (pool & 3u)) return 0xffffu;
    return *(volatile const uint32_t *)(pool + 0x112cu);
}
/* The CinemaDNG frame registry C0374220() = C351FF44: 96 frame pointers at
 * +4, a lock byte at +0x190 (C03768D8 deletes nothing while it is set).
 * C0375030 deletes a written frame only when it has no parent (+0x1118 == -1)
 * and no live children (+0x1110 == 0). out: {lock | occupied << 8, the oldest
 * occupied frame's state +0x1104, children +0x1110 | duplicates +0x1114 << 16,
 * parent +0x1118}. Read only. */
static void card_registry(uint32_t out[4]) {
    const uintptr_t reg = 0xc351ff44u;
    uintptr_t oldest = 0;
    uint32_t occupied = 0, gen = UINT32_MAX;
    for (uint32_t n = 0; n < 96u; ++n) {
        uintptr_t f = *(volatile const uint32_t *)(reg + 4u + 4u * n);
        if (f < 0x40000000u || (f & 3u)) continue;
        ++occupied;
        uint32_t g = *(volatile const uint32_t *)(f + 0x1100u);
        if (g <= gen) { gen = g; oldest = f; }
    }
    out[0] = *(volatile const uint8_t *)(reg + 0x190u) | occupied << 8;
    if (!oldest) { out[1] = out[2] = out[3] = UINT32_MAX; return; }
    out[1] = *(volatile const uint32_t *)(oldest + 0x1104u);
    out[2] = (*(volatile const uint32_t *)(oldest + 0x1110u) & 0xffffu) |
             *(volatile const uint32_t *)(oldest + 0x1114u) << 16;
    out[3] = *(volatile const uint32_t *)(oldest + 0x1118u);
}
/* The CinemaDNG tag Subject and the take's header template (research/
 * firmware/notes/cinemadng-header/HDR_CDNG.md §0.1, §0.6, §1): nine observer
 * slots, each called vt+0xC(observer, DataPool) at every notify; the
 * template's address and length in the MovRec singleton C358DB98. */
#define CARD_SUBJECT       0xc31ac4ecu
#define CARD_TEMPLATE      0xc358dba8u     /* singleton +0x10 */
#define CARD_TEMPLATE_LEN  0xc358dba4u     /* singleton +0xC = req+0x14C */
/* the builder's tag add, as the lens observer calls it (FUN_c0364810) */
static uint32_t card_tag_add(uintptr_t builder, uint32_t ifd, uint32_t tag, uint32_t type,
                             uint32_t count, const void *value) {
    typedef uint32_t (*fn)(uintptr_t, uint32_t, uint32_t, uint32_t, uint32_t, const void *);
    return ((fn)0xc00ba378u)(builder, ifd, tag, type, count, value);
}
/* DataPool->vtable[slot](DataPool): +0x40 the event {mode, type, flag},
 * +0x2C the tag builder (0 once serialized) */
static uintptr_t card_pool_call(uintptr_t pool, uint32_t slot) {
    typedef uintptr_t (*fn)(uintptr_t);
    uintptr_t vt = *(volatile const uint32_t *)pool;
    return ((fn)*(volatile const uint32_t *)(vt + slot))(pool);
}
/* The template is cached heap and the firmware's DMA reads it: clean what we
 * wrote to memory (DCCMVAC per 32-byte line). */
static void card_clean_lines(uintptr_t at, uint32_t bytes) {
    for (uintptr_t p = at & ~(uintptr_t)31; p < at + bytes; p += 32)
        __asm__ volatile("mcr p15, 0, %0, c7, c10, 1" :: "r"(p) : "memory");
    __asm__ volatile("dsb sy" ::: "memory");
}
static uint32_t card_tag_read(uintptr_t a) { return *(volatile const uint32_t *)a; }
static void card_tag_write(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }
static void card_publish_barrier(void) { __asm__ volatile("dmb sy" ::: "memory"); }
#elif defined(FPL_CARD_HOST_TEST)
extern uint32_t fpl_test_card_prepare(uintptr_t, const uint32_t *);
extern uint32_t fpl_test_card_enqueue(uintptr_t, uint32_t, uint32_t);
extern void fpl_test_card_get_spare(void *, uint32_t);
extern void fpl_test_card_free_spare(void *);
extern int32_t fpl_test_card_task_create(uintptr_t, uint32_t);
extern void fpl_test_card_sleep(uint32_t);
extern uint32_t fpl_test_card_irq_off(void);
extern void fpl_test_card_irq_restore(uint32_t);
#define card_task_create fpl_test_card_task_create
#define card_sleep_ms fpl_test_card_sleep
#define card_original_prepare fpl_test_card_prepare
#define card_original_enqueue fpl_test_card_enqueue
#define CARD_ENQ(c, cr, i, a) card_original_enqueue(cr, i, a)
#define card_get_spare fpl_test_card_get_spare
#define card_free_spare fpl_test_card_free_spare
#define card_irq_off fpl_test_card_irq_off
#define card_irq_restore fpl_test_card_irq_restore
#define card_tick_us() 0u
#define card_status_recording() 1u
static void card_f_ctor(void *o) { (void)o; }
static uint32_t card_f_open(void *o, const char *p, uint32_t m) { (void)o; (void)p; (void)m; return 0; }
static uint32_t card_f_seek(void *o, uint32_t a) { (void)o; (void)a; return 0; }
static uint32_t card_f_write(void *o, const void *b, uint32_t n) { (void)o; (void)b; (void)n; return 0; }
static uint32_t card_f_read(void *o, void *b, uint32_t n, uint32_t *g) { (void)o; (void)b; (void)n; *g = 0; return 0; }
static void card_f_close(void *o) { (void)o; }
static void card_f_dtor(void *o) { (void)o; }
#define card_pool_left() 0u
static void card_registry(uint32_t out[4]) { out[0] = out[1] = out[2] = out[3] = 0; }
extern uintptr_t fpl_test_card_subject;
#define CARD_SUBJECT fpl_test_card_subject
#define CARD_TEMPLATE 0u
#define CARD_TEMPLATE_LEN 0u
static uint32_t card_tag_add(uintptr_t b, uint32_t i, uint32_t t, uint32_t y, uint32_t n,
                             const void *v) { (void)b; (void)i; (void)t; (void)y; (void)n; (void)v; return 0; }
static uintptr_t card_pool_call(uintptr_t p, uint32_t s) { (void)p; (void)s; return 0; }
static void card_clean_lines(uintptr_t a, uint32_t n) { (void)a; (void)n; }
static uint32_t card_tag_read(uintptr_t a) { return *(volatile const uint32_t *)a; }
static void card_tag_write(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }
static void card_publish_barrier(void) { __asm__ volatile("" ::: "memory"); }
#else
#error "ARM32 native card ABI required; host tests must explicitly substitute it"
#endif

struct fpl_card {
    uint32_t magic, block_bytes;
    uintptr_t base;
    struct fpl_rec_hook rec;
    struct fpl_frame_hold hold;
    /* The second lane (frame_hold.c, "lanes"): its own pipeline, spare and
     * table. lane[1] stays invalid when any of them cannot be had, and the
     * card runs on one lane. */
    struct fpl_pipeline pipe_b;
    struct fpl_frame_hold hold_b;
    struct { uintptr_t handle; uint32_t capacity, allocator_class; } table_b;
    struct fpl_frame_hold *lane[2];
    struct fpl_flush_stats flush;
#ifdef FPL_DIAG_FLUSH_TIME
    /* diagnostic only: the writer hook's own time, all calls and the ones
     * that wrote a trailer */
    uint32_t flush_n, flush_us, flush_max_us, flush_applied_us;
#endif
    uint32_t hold_live;
    /* read over USB after a test take; all saturating */
    uint32_t rec_events, rec_admitted, rec_raw, rec_firmware_refused;
    uint32_t rec_hold_refused, hold_init_failed, ring_busy;
    uint32_t stops, finishes, finish_busy, last_finish;
    /* the take's spare for the buffer swap: asked, granted, given back */
    uint32_t spare_bytes, spare_failed, spares_freed;
    uint32_t stale_promises;            /* forgotten at a new take, see start_hold */
    uint32_t take_frames;               /* CinemaDNG arrivals, also when OFF */
    uintptr_t task_entry;               /* card.S task_shim */
    int32_t task_id;                    /* the codec task; < 1: none, and the
                                           card holds frames the old way */
    uint32_t lane_b_failed, lane_stop_result;
    /* playback: compressed frames decoded back as the player reads them */
    struct fpl_play play;
    /* SHOOT 2 (CINE) Lossless RAW row: memory only, OFF at every boot */
    struct fpl_menu menu;
    uintptr_t menu_area;
    uint32_t menu_area_bytes, rec_menu_off;
    /* Per REC attempt, including Lossless OFF: observe the native error and
     * discard paths without changing their decisions or doing I/O. */
    struct fpl_record_diag record_diag;
    const char *self_path;              /* this sup's file (Loader v3 r2), or 0 */
#ifdef FPL_V4
    const struct sl_svc *svc;           /* Loader v4: file_is before a save */
#endif
    uint32_t settings_on;               /* the saved state, as on the card */
    uint32_t settings_ok;               /* the record was valid at boot */
    uint32_t save_pending, saves, save_failed, save_last;
    uint32_t rec_tick, arrive_tick;     /* microseconds of the last REC / arrival */
    uint32_t fobj[1024];                /* a file object: loader.S gives it 4 KiB */
    uint32_t tile_force;                /* tile_grid.h, for measuring: w << 16 | h, 0 = default */
    /* The row-pitch test switch (Bei 2026-11-10), written only by a host
     * (mem set at state + layout 'pitch_test'). 0 at every boot (the
     * launcher zeroes the state); never saved. 1: a 10/14-bit width whose
     * packed row is not a multiple of 4 bytes is compressed anyway --
     * control.c and codec_job.c skip their row-pitch refusal, nothing else.
     * Any other value = 0. The take's count of such compressed frames is
     * hold.pitch_forced + hold_b.pitch_forced (zeroed at each REC). */
    uint32_t pitch_test;
    /* The take's compressed IFD inside the header template (header_tag.h):
     * the observer adds the tag at the template build and prepares the IFD
     * after the serialization; nothing per frame. Two copies:
     * a flush still finishing the previous take keeps the one it read. */
    struct fpl_header_tag tags[2];
    const struct fpl_header_tag *volatile tag_live;   /* 0: this take is RAW */
    uint32_t tag_index, tag_want, tag_pending;
    uint32_t tag_mode0, tag_added, tag_add_result, tag_add_failed;
    uint32_t tag_prepared, tag_prepare_failed, tag_prepare_result, tag_head;
    uint32_t observer[1], observer_vtable[4];   /* {vtable}; +0xC = card.S obs_shim */
    uint32_t observer_slot;             /* 1 + the Subject slot; 0 = not registered */
    uint32_t observer_full, observer_calls;
    uint32_t tag_tiles, tag_bytes;      /* this take's grid; its tag's size */
    uint32_t engine_release;            /* the last fpl_codec_job_release result */
#ifdef FPL_DIAG_HOOK_TIME
    /* rec, arrive, stop, flush, observe, written, event, discard:
     * {calls, microseconds, longest, last stack pointer} */
    uint32_t hook_time[8][4];
    uint32_t enq_n, enq_us;             /* stock C037DD50 from the arrive hook */
#endif
    uint32_t tag_zero[FPL_HEADER_TAG_MAX / 4];     /* the tag's value as added */
    /* One record per CinemaDNG arrival this take (the first FPL_TRACE ones):
     * where the frames are. {microseconds, arrivals so far, writer flushes
     * so far (record_diag.writer_calls), descriptor pool free | lane A state
     * << 16 | lane B state << 24, then card_registry()'s four words}. Last,
     * so nothing above moves. */
    uint32_t trace_n;
    uint32_t trace[FPL_TRACE][8];
    /* When the native side handled what (this take, the first FPL_ELOG):
     * {microseconds, kind | slot << 8 | result << 16 | frame state << 24}.
     * kind: the CinemaDNG event number at C038BD08 (5 captured, 8/9 the file
     * is done), or 'W' (0x57) when the writer's final flush returned. */
    uint32_t elog_n;
    uint32_t elog[FPL_ELOG][2];
};

static void card_saturate(uint32_t *v) { if (*v != UINT32_MAX) ++*v; }

/* ---- the test card's assertions: the only place they are made -------- */
static uint32_t test_yes(void *c) { (void)c; return 1; }
static uint32_t test_readiness(void *c, uint32_t reserved) {
    const volatile struct fpl_card *card = (const volatile struct fpl_card *)c;
    (void)reserved;
    /* ASSERTED for measurement, not proven; plus the host's test switch */
    return FPL_READY_CAPTURE | (card && card->pitch_test == 1u ? FPL_TEST_PITCH : 0u);
}

static uint32_t card_valid(const struct fpl_card *c) {
    return c && c->magic == FPL_CARD_MAGIC;
}
#ifdef FPL_DIAG_HOOK_TIME
static uint32_t card_timed_enqueue(struct fpl_card *c, uintptr_t creator, uint32_t id,
                                   uint32_t argument) {
    uint32_t began = card_tick_us(), r = card_original_enqueue(creator, id, argument);
    c->enq_n++;
    c->enq_us += card_tick_us() - began;
    return r;
}
#endif
static uint32_t ring_empty(const struct fpl_card *c) {
    for (uint32_t n = 0; n < FPL_HOLD_COMMITS; ++n)
        if (c->hold.ring[n].file || c->hold_b.ring[n].file) return 0;
    return 1;
}

static uint32_t settings_check(uint32_t on) {
    return FPL_SETTINGS_MAGIC ^ 1u ^ on ^ 0xffffffffu;
}

USED uint32_t fpl_card_init(struct fpl_card *c, uintptr_t base, uint32_t block_bytes,
                           uintptr_t task_entry, const char *path
#ifdef FPL_V4
                           , const struct sl_svc *svc
#endif
                           ) {
    uint32_t result;
    /* the whole state inside the block the launcher was given */
    if (!c || !base || (uintptr_t)c < base || (uintptr_t)c - base > block_bytes ||
        block_bytes - ((uintptr_t)c - base) < sizeof(*c) || ((uintptr_t)c & 7u))
        return FPL_INVALID;
    const unsigned char *bytes = (const unsigned char *)c;
    for (uint32_t n = 0; n < sizeof(*c); ++n)
        if (bytes[n]) return FPL_INVALID;      /* the launcher zeroes it */
    if ((result = fpl_rec_hook_init(&c->rec, 1, 0x15400u)) != FPL_OK) return result;
    c->rec.facts.cine = test_yes;
    c->rec.facts.cinemadng = test_yes;
    c->rec.facts.sd_media = test_yes;
    c->rec.facts.readiness = test_readiness;
    c->rec.facts.readiness_context = c;
    /* No source copy: the engine reads each frame in place (operator
     * decision 2026-09-30; see frame_hold.c readable()). */
    c->rec.setup.copy_source = 0;
    /* Nor an output span: the engine writes into the spare frame allocation
     * (buffer swap). A frame-sized output nobody uses took the frames' memory
     * and stopped a 3K take (2026-10-01, rec log "mem"). A frame the swap
     * cannot take goes out as it is. */
    c->rec.setup.no_output = 1;
    c->base = base;
    c->block_bytes = block_bytes;
    c->task_entry = task_entry;      /* card.S task_shim: the codec task */
    c->lane[0] = &c->hold;
    c->lane[1] = &c->hold_b;
    if (fpl_pipeline_init(&c->pipe_b, 2) != FPL_OK) card_saturate(&c->lane_b_failed);
    c->magic = FPL_CARD_MAGIC;
    /* Priority 12: above SRecRaw (15), where frames arrive, below SRecFile
     * (6); it sleeps a millisecond between passes. Without it the card holds
     * frames the old way, one at a time from the arrival. */
    c->task_id = task_entry ? card_task_create(task_entry, 12) : -1;
    /* The row. The rest of the block, never freed: the UI borrows the page
     * and pool for the whole boot. Whatever the outcome, recording is safe:
     * without an installed row fpl_menu_on() is 0 and every take is stock. */
    c->menu_area = ((uintptr_t)c + sizeof(*c) + 7u) & ~(uintptr_t)7u;
    c->menu_area_bytes = c->menu_area < base + block_bytes ?
                         (uint32_t)(base + block_bytes - c->menu_area) : 0;
#ifdef FPL_SETTINGS_OFF
    {
        const volatile uint32_t *r = (const volatile uint32_t *)(base + FPL_SETTINGS_OFF);
        c->settings_ok = r[0] == FPL_SETTINGS_MAGIC && r[1] == 1u && r[2] <= 1u &&
                         r[3] == settings_check(r[2]);
        c->settings_on = c->settings_ok ? r[2] : 0u;
        c->self_path = c->settings_ok ? path : 0;
        c->menu.initial = c->settings_on;
    }
#else
    (void)path;
#endif
#if defined(FPL_V4)
    /* Loader v4: the row is on the fpSup page; the core keeps it. */
    c->svc = svc;
    fpl_menu_install_row(&c->menu, svc);
#elif defined(FPL_MENU_OFF)
    /* Loader v3: the FPUI block is part of this sup's own file, which the
     * 加載器 read into this block (build_v3_lossless.py puts it after the C
     * text, at a build-time offset) -- there is no \fpSup.BIN to read. */
    fpl_menu_install_data(&c->menu, base + FPL_MENU_OFF, FPL_MENU_LEN);
#else
    fpl_menu_install(&c->menu, c->menu_area, c->menu_area_bytes);
#endif
    return FPL_OK;
}

/* The second lane: a spare like the first, and a table of its own (the
 * engine writes its size table there while the other lane's is read).
 * 0: not made, nothing of it held. */
static uint32_t start_lane_b(struct fpl_card *c, const struct fpl_hold_workspace *a) {
    struct fpl_hold_workspace ws;
    ws.output = 0;
    ws.output_capacity = 0;
    ws.table_capacity = a->table_capacity;
    c->table_b.handle = c->table_b.capacity = c->table_b.allocator_class = 0;
    card_get_spare(&c->table_b, ws.table_capacity);
    ws.spare.handle = ws.spare.capacity = ws.spare.allocator_class = 0;
    card_get_spare(&ws.spare, c->spare_bytes);
    ws.table = c->table_b.handle;
    if (!c->table_b.handle || (c->table_b.handle & 0x3ffu) ||
        c->table_b.capacity < ws.table_capacity ||
        !ws.spare.handle || ws.spare.allocator_class != 10u ||
        ws.spare.capacity < c->spare_bytes ||
        fpl_pipeline_begin(&c->pipe_b, &c->rec.workspace.control) != FPL_OK) {
        if (ws.spare.handle) card_free_spare(&ws.spare);
        if (c->table_b.handle) card_free_spare(&c->table_b);
        c->table_b.handle = 0;
        card_saturate(&c->lane_b_failed);
        return 0;
    }
    if (fpl_hold_init(&c->hold_b, &c->pipe_b, &c->rec.facts, &ws) != FPL_OK) {
        /* the pipeline began: end it, it never held anything */
        fpl_pipeline_stop(&c->pipe_b);
        fpl_pipeline_finish(&c->pipe_b, 1);
        card_free_spare(&ws.spare);
        card_free_spare(&c->table_b);
        c->table_b.handle = 0;
        card_saturate(&c->lane_b_failed);
        return 0;
    }
    return 1;
}

static void release_spare(struct fpl_card *c);

/* Both lanes and the codec task, or no compression at all: the take was
 * admitted (workspace reserved, pipeline begun), so on any failure that is
 * undone here and the take records exactly as stock. 1 = live. */
static uint32_t start_hold(struct fpl_card *c) {
    struct fpl_rec_workspace *w = &c->rec.workspace;
    struct fpl_hold_workspace ws;
    uintptr_t handle = w->memory.allocation.handle;
    unsigned char *h = (unsigned char *)&c->hold;

    /* Promises the last take left: frames the firmware dropped (a take that
     * stopped itself drops what is still queued, 2026-10-01: 8 left at 3K).
     * Their files will never reach the flush: REC cannot start before the
     * last take's files are written. Forget them, count them. */
    if (!ring_empty(c)) {
        for (uint32_t n = 0; n < FPL_HOLD_COMMITS; ++n) {
            if (c->hold.ring[n].file) card_saturate(&c->stale_promises);
            if (c->hold_b.ring[n].file) card_saturate(&c->stale_promises);
        }
        card_saturate(&c->ring_busy);
    }
    for (uint32_t n = 0; n < sizeof(c->hold); ++n) h[n] = 0;
    h = (unsigned char *)&c->hold_b;
    for (uint32_t n = 0; n < sizeof(c->hold_b); ++n) h[n] = 0;
    ws.output = w->layout.output.capacity ? handle + w->layout.output.offset : 0;
    ws.output_capacity = w->layout.output.capacity;
    ws.table = handle + w->layout.codec_sizes.offset;
    ws.table_capacity = w->layout.codec_sizes.capacity + w->layout.codec_scratch.capacity;
    /* One frame's worth, exactly what C037A990 asks for: the header reserve
     * plus the raster in 512 B units. Without it, every result is copied
     * back into its own frame. */
    ws.spare.handle = ws.spare.capacity = ws.spare.allocator_class = 0;
    c->spare_bytes = 0x15400u + ((c->rec.facts.seen.raster + 0x1ffu) & ~0x1ffu);
    card_get_spare(&ws.spare, c->spare_bytes);
    if (!ws.spare.handle || ws.spare.allocator_class != 10u ||
        ws.spare.capacity < c->spare_bytes) {
        if (ws.spare.handle) card_free_spare(&ws.spare);
        ws.spare.handle = ws.spare.capacity = ws.spare.allocator_class = 0;
        card_saturate(&c->spare_failed);
    }
    if (c->task_id < 1 || !ws.spare.handle ||
        fpl_hold_init(&c->hold, &w->pipeline, &c->rec.facts, &ws) != FPL_OK) {
        if (ws.spare.handle) card_free_spare(&ws.spare);
        card_saturate(&c->hold_init_failed);
        fpl_rec_workspace_finish(w, w->pipeline.take, 1);     /* the take is stock */
        return 0;
    }
    if (!start_lane_b(c, &ws)) {
        release_spare(c);                                  /* lane A's spare */
        fpl_rec_workspace_finish(w, w->pipeline.take, 1);
        return 0;
    }
    c->hold.tile_force = c->hold_b.tile_force = c->tile_force;
    c->hold.pitch_test = c->hold_b.pitch_test = *(volatile uint32_t *)&c->pitch_test == 1u;
    /* one open a take: codec_job.h keep_open */
    c->hold.job.keep_open = c->hold_b.job.keep_open = 1;
    c->take_frames = 0;
    c->hold_live = 1;
    return 1;
}

/* The engine is idle (the take finished): the spare -- by now some earlier
 * frame's buffer -- goes back to the pool. */
static void release_spare(struct fpl_card *c) {
    struct fpl_frame_hold *h[2] = {&c->hold, &c->hold_b};
    for (uint32_t n = 0; n < 2; ++n) {
        if (!h[n]->workspace.spare.handle) continue;
        card_free_spare(&h[n]->workspace.spare);
        h[n]->workspace.spare.handle = 0;
        h[n]->workspace.spare.capacity = 0;
        h[n]->workspace.spare.allocator_class = 0;
        card_saturate(&c->spares_freed);
    }
    if (c->table_b.handle) {
        card_free_spare(&c->table_b);
        c->table_b.handle = 0;
    }
}

HOOK_DEF uint32_t HOOK(fpl_card_rec)(uintptr_t camera, const uint32_t *request, struct fpl_card *c) {
    uint32_t dispatch;
    if (!card_valid(c) || !request || !FPL_REC_IS_START(request[0]))
        return card_valid(c) ? fpl_rec_hook_call(camera, request, &c->rec)
                             : card_original_prepare(camera, request);
    card_saturate(&c->rec_events);
    c->rec_tick = card_tick_us() | 1u;
    /* a new take: no prepared IFD until its own template has one */
    c->tag_live = 0;
    c->tag_want = c->tag_pending = 0;
    c->take_frames = 0;
    uint32_t mask = card_irq_off();
    fpl_record_diag_reset(&c->record_diag);
    c->trace_n = 0;
    c->elog_n = 0;
    card_irq_restore(mask);
    fpl_play_end(&c->play);             /* a scratch playback left: back to the pool */
    if (!fpl_menu_on(&c->menu)) {
        /* Lossless RAW is OFF (the default): the take is exactly stock */
        card_saturate(&c->rec_menu_off);
        return card_original_prepare(camera, request);
    }
    if (c->hold_live) {
        /* a previous take never finished: record RAW, touch nothing */
        card_saturate(&c->rec_hold_refused);
        return card_original_prepare(camera, request);
    }
    dispatch = fpl_rec_hook_call(camera, request, &c->rec);
    if (dispatch) {
        if (start_hold(c)) {
            card_saturate(&c->rec_admitted);
            /* Nothing is held until the take's IFD is in its template: the
             * template is built after this (FUN_c0378a50), and the tag is
             * asked for here, sized for this take's tiles. No observer, no
             * tag: the whole take is RAW. */
            c->hold.require_head = c->hold_b.require_head = 0xffffffffu;
            {
                uint32_t tw, th, w = c->rec.facts.seen.width, ht = c->rec.facts.seen.height;
                fpl_tile_grid(w, ht, c->tile_force, &tw, &th);
                c->tag_tiles = fpl_tile_steps(w, tw) * fpl_tile_steps(ht, th);
            }
            c->tag_bytes = FPL_HEADER_TAG_BYTES(c->tag_tiles);
            c->tag_want = c->observer_slot != 0 && c->tag_tiles &&
                          c->tag_tiles <= FPL_TILE_MAX;
        } else {
            card_saturate(&c->rec_raw);
        }
        return dispatch;
    }
    if (c->rec.workspace.native_result) {
        /* We refused, the firmware agreed: record as stock. */
        card_saturate(&c->rec_raw);
        return c->rec.workspace.native_result;
    }
    card_saturate(&c->rec_firmware_refused);
    return 0;
}

HOOK_DEF uint32_t HOOK(fpl_card_arrive)(uintptr_t creator, uint32_t id, uint32_t argument,
                              struct fpl_card *c) {
    if (!card_valid(c))
        return card_original_enqueue(creator, id, argument);
    uint32_t first = c->take_frames == 0;
    card_saturate(&c->take_frames);
    c->arrive_tick = card_tick_us() | 1u;
#ifdef FPL_DIAG_TRACE
    if (c->trace_n < FPL_TRACE) {
        uint32_t *t = c->trace[c->trace_n++];
        t[0] = card_tick_us();
        t[1] = c->take_frames;
        t[2] = c->record_diag.writer_calls;
        t[3] = (card_pool_left() & 0xffffu) | (c->hold.lane & 0xffu) << 16 |
               (c->hold_b.lane & 0xffu) << 24;
        card_registry(t + 4);
    }
#endif
    if (!c->hold_live) return CARD_ENQ(c, creator, id, argument);
    /* The take's first frame always goes out uncompressed: DaVinci Resolve
     * decides a clip's decoding from its first frame and plays a clip that
     * mixes compressed and uncompressed frames only when that one is
     * uncompressed (reported by users, 2026-10-02). It is queued at once, so
     * it is the clip's first file. */
    if (first)
        return CARD_ENQ(c, creator, id, argument);
    return fpl_lanes_arrive(c->lane, creator, id, argument);
}

HOOK_DEF void HOOK(fpl_card_stop)(struct fpl_card *c, uint32_t kind) {
    struct fpl_rec_workspace *w;
    if (!card_valid(c) || !c->hold_live || (kind != 1 && kind != 9)) return;
    card_saturate(&c->stops);
    w = &c->rec.workspace;
    c->lane_stop_result = fpl_lanes_stop(c->lane);
    if (w->pipeline.phase != FPL_SLOT_FREE || c->hold.job.phase == FPL_CODEC_RUNNING ||
        c->hold.lane != FPL_LANE_IDLE ||
        (c->hold_b.magic && (c->pipe_b.phase != FPL_SLOT_FREE ||
                             c->hold_b.lane != FPL_LANE_IDLE))) {
        card_saturate(&c->finish_busy);          /* the engine still owns it */
        return;
    }
    if (c->hold_b.magic && c->pipe_b.active &&
        fpl_pipeline_finish(&c->pipe_b, 1) != FPL_OK) {
        card_saturate(&c->finish_busy);
        return;
    }
    c->last_finish = fpl_rec_workspace_finish(w, w->pipeline.take, 1);
    if (c->last_finish == FPL_OK) {
        c->engine_release = fpl_codec_job_release(&c->hold.job);
        release_spare(c);
        c->hold_live = 0;                        /* the adapter stays valid
                                                    until its promises flush */
        card_saturate(&c->finishes);
    } else {
        card_saturate(&c->finish_busy);
    }
}

HOOK_DEF void HOOK(fpl_card_flush)(uintptr_t writer, struct fpl_card *c) {
    if (!card_valid(c)) return;
#ifdef FPL_DIAG_FLUSH_TIME
    uint32_t applied = c->flush.applied, began = card_tick_us(), took;
#endif
    fpl_flush_before(writer, &c->hold, &c->hold_b, c->tag_live, &c->flush);
#ifdef FPL_DIAG_FLUSH_TIME
    took = card_tick_us() - began;
    ++c->flush_n;
    c->flush_us += took;
    if (took > c->flush_max_us) c->flush_max_us = took;
    if (c->flush.applied != applied) c->flush_applied_us += took;
#endif
}

/* ---- the header template's observer (header_tag.h) --------------------
 *
 * card.S obs_shim, from the Subject's notify (FUN_c00559f0 -> FUN_c0055fe0),
 * in whatever task notifies -- for the movie, MovRec. Always returns 1: an
 * observer that returns 0 is taken off the list. Only a take this card
 * admitted is touched, in order: the mode-0 notify of its template build
 * (the builder still open) adds the tag; the mode-2 notify after its
 * serialization (C0378F70) prepares the IFD. Nothing per frame: the
 * values the firmware rewrites each frame are out of line and shared
 * (header_tag.h). Anything else -- stills, other DataPools, the per-frame
 * mode-3 notifies, a take we did not admit -- returns at once. */
HOOK_DEF uint32_t HOOK(fpl_card_observe)(uintptr_t pool, struct fpl_card *c) {
    const volatile uint32_t *event;
    uint32_t mode;
    if (!card_valid(c) || !pool) return 1;
    card_saturate(&c->observer_calls);
    event = (const volatile uint32_t *)card_pool_call(pool, 0x40u);
    if (!event) return 1;
    mode = event[0];
    if (mode == 0u) {
        uintptr_t builder;
        /* every template build is counted: one after an admitted REC with no
         * tag added says the REC hook came too late for it */
        card_saturate(&c->tag_mode0);
        if (!c->tag_want) return 1;
        c->tag_want = 0;
        builder = card_pool_call(pool, 0x2cu);
        if (!builder) {
            card_saturate(&c->tag_add_failed);
            return 1;
        }
        c->tag_add_result = card_tag_add(builder, 0u, FPL_HEADER_TAG, 7u,
                                         c->tag_bytes, c->tag_zero);
        c->tag_pending = 1;
        card_saturate(&c->tag_added);
    } else if (mode == 2u) {
        struct fpl_header_tag *next;
        uintptr_t base;
        if (!c->tag_pending) return 1;
        c->tag_pending = 0;
        base = *(volatile const uint32_t *)CARD_TEMPLATE;
        c->tag_head = *(volatile const uint32_t *)CARD_TEMPLATE_LEN;
        next = &c->tags[c->tag_index ^ 1u];
        c->tag_prepare_result = base ? fpl_header_tag_prepare(next, base, c->tag_head,
                                                              card_tag_read, card_tag_write)
                                     : FPL_INVALID;
        if (c->tag_prepare_result != FPL_OK) {
            card_saturate(&c->tag_prepare_failed);
            return 1;
        }
        card_clean_lines(base + next->ifd_at, next->counts_at + 4u * next->max_tiles - next->ifd_at);
        c->tag_index ^= 1u;
        card_publish_barrier();          /* the IFD's record before its pointer:
                                            the writer's task reads it */
        c->tag_live = next;
        /* from now on, frames of this template may be held */
        c->hold.require_head = c->hold_b.require_head = next->head;
        card_saturate(&c->tag_prepared);
    }
    return 1;
}

/* After every hook is armed (card.S): put the observer on the Subject's list
 * as FUN_c00d2958 would -- the first empty slot, interrupts off -- but never
 * through it: with no slot left it asserts and the camera stops. No slot, no
 * observer, and every compressed frame keeps its trailing IFD. */
USED void fpl_card_observer(struct fpl_card *c, uintptr_t shim) {
    volatile uint32_t *slot = (volatile uint32_t *)CARD_SUBJECT;
    uint32_t mask, free_at = 0;
    if (!card_valid(c) || !shim || c->observer_slot) return;
    c->observer_vtable[3] = (uint32_t)shim;
    c->observer[0] = (uint32_t)(uintptr_t)c->observer_vtable;
    mask = card_irq_off();
    for (uint32_t n = 0; n < 9u; ++n) {
        if (slot[n] == (uint32_t)(uintptr_t)c->observer) { free_at = n + 1u; break; }
        if (!slot[n] && !free_at) free_at = n + 1u;
    }
    if (free_at) slot[free_at - 1u] = (uint32_t)(uintptr_t)c->observer;
    card_irq_restore(mask);
    if (free_at) c->observer_slot = free_at;
    else card_saturate(&c->observer_full);
}

/* The writer's full r0:r1 result, observed after the native call. A nonzero
 * byte count is its API result, not proof of durable files on the medium. */
static void card_elog(struct fpl_card *c, uint32_t what) {
    if (c->elog_n >= FPL_ELOG) return;
    uint32_t *e = c->elog[c->elog_n++];
    e[0] = card_tick_us();
    e[1] = what;
}

HOOK_DEF void HOOK(fpl_card_written)(struct fpl_card *c, uint32_t low, uint32_t high) {
    if (!card_valid(c)) return;
    uint32_t mask = card_irq_off();
#ifdef FPL_DIAG_TRACE
    card_elog(c, 0x57u);
#endif
    fpl_record_diag_writer(&c->record_diag, low, high);
    card_irq_restore(mask);
}

/* C038BD08: the CinemaDNG dispatcher already looked this frame up. */
HOOK_DEF void HOOK(fpl_card_event)(uintptr_t message, uintptr_t frame, struct fpl_card *c) {
    if (!card_valid(c)) return;
    uint32_t mask = card_irq_off();
#ifdef FPL_DIAG_TRACE
    if (message) {
        const volatile uint32_t *m = (const volatile uint32_t *)message;
        uint32_t state = frame ? *(const volatile uint32_t *)(frame + 0x1104u) : 0xffu;
        card_elog(c, (m[0x0c / 4] & 0xffu) | (m[0xe8 / 4] & 0xffu) << 8 |
                     (m[0xe4 / 4] & 0xffu) << 16 | (state & 0xffu) << 24);
    }
#endif
    fpl_record_diag_event(&c->record_diag, message, frame);
    card_irq_restore(mask);
}

/* C037DEF8: one frame has actually been popped by the native FIFO discard.
 * The shim immediately continues into the original cleanup exactly once. */
HOOK_DEF void HOOK(fpl_card_discard)(uintptr_t creator, uintptr_t frame, uint32_t caller,
                           struct fpl_card *c) {
    (void)creator;
    if (!card_valid(c)) return;
    uint32_t mask = card_irq_off();
    fpl_record_diag_discard(&c->record_diag, frame, caller);
    card_irq_restore(mask);
}

#ifdef FPL_SETTINGS_OFF
/* Rewrite the record in this sup's file, then read it back. 1 = on the card. */
static uint32_t settings_write(struct fpl_card *c, uint32_t on) {
    uint32_t rec[4], back[4], got = 0, ok;
    void *o = c->fobj;
    rec[0] = FPL_SETTINGS_MAGIC; rec[1] = 1u; rec[2] = on; rec[3] = settings_check(on);
#ifdef FPL_V4
    /* mode 7 creates a missing file: write only into a file that is still
     * this sup (its header as loaded), never into a renamed-away name */
    if (!c->svc || c->svc->file_is(c->svc, c->self_path,
                                   (const void *)(c->base - FPL_HEADER_LEN), FPL_HEADER_LEN) != SL_OK)
        return 0;
#endif
    card_f_ctor(o);
    ok = card_f_open(o, c->self_path, 7u) &&
         card_f_seek(o, FPL_HEADER_LEN + FPL_SETTINGS_OFF) &&
         card_f_write(o, rec, sizeof rec);
    card_f_close(o);
    card_f_dtor(o);
    if (!ok) return 0;
    card_f_ctor(o);
    ok = card_f_open(o, c->self_path, 1u) &&
         card_f_seek(o, FPL_HEADER_LEN + FPL_SETTINGS_OFF) &&
         card_f_read(o, back, sizeof back, &got) && got == sizeof back;
    card_f_close(o);
    card_f_dtor(o);
    for (uint32_t n = 0; ok && n < 4u; ++n) ok = back[n] == rec[n];
    return ok;
}

/* Idle only (no take of ours, the camera not recording): the row changed and
 * has held its value for FPL_SAVE_POLLS passes -> save it. A failed save is
 * counted and retried after another FPL_SAVE_POLLS. */
/* Recording, or too close to it to touch the card: the native flag when its
 * table is set up, a REC or a CinemaDNG frame within FPL_QUIET_US. */
static uint32_t card_busy(const struct fpl_card *c) {
    uint32_t t = card_tick_us();
    return card_status_recording() || c->hold_live ||
           (c->rec_tick && t - c->rec_tick < FPL_QUIET_US) ||
           (c->arrive_tick && t - c->arrive_tick < FPL_QUIET_US);
}

static void settings_poll(struct fpl_card *c) {
    uint32_t now;
    if (!c->self_path) return;
    now = fpl_menu_now(&c->menu);
    if (now > 1u || now == c->settings_on || card_busy(c)) {
        c->save_pending = 0;
        return;
    }
    if (++c->save_pending < FPL_SAVE_POLLS) return;
    c->save_pending = 0;
    c->save_last = now;
    if (settings_write(c, now)) {
        c->settings_on = now;
        card_saturate(&c->saves);
    } else {
        card_saturate(&c->save_failed);
    }
}
#endif

/* The codec task (card.S task_shim). It never returns: a task cannot be
 * ended in this firmware. Between takes it only sleeps; during one it waits
 * on the engine's flag and starts the waiting frame the moment it finishes. */
USED void fpl_card_task(struct fpl_card *c) {
    for (;;) {
        uint32_t live = card_valid(c) && c->hold_live, waited = 0;
        if (live) waited = fpl_lanes_task_wait(c->lane, FPL_TASK_WAIT) & 4u;
#ifdef FPL_SETTINGS_OFF
        else if (card_valid(c)) settings_poll(c);
#endif
        /* a pass that waited on the running job has slept already, and the
         * job it saw finish wants its successor started now */
        if (!waited) card_sleep_ms(live ? 1u : 10u);
#if defined(FPL_CARD_HOST_TEST)
        return;                                  /* one pass per call */
#endif
    }
}

/* C05C0EA4: a frame file the player has just read (play_decode.c). Never
 * while a take owns the engine. */
USED void fpl_card_play(uintptr_t slot, struct fpl_card *c) {
    if (!card_valid(c)) return;
    fpl_play_frame(&c->play, slot, c->hold_live);
}

/* C05BDDAC: a clip opens; `size` is its first frame file's. */
USED uint32_t fpl_card_clip(struct fpl_card *c, uintptr_t player, uintptr_t desc,
                            uint32_t size) {
    (void)player;
    if (!card_valid(c)) return size;
    return fpl_play_clip(&c->play, desc, size, c->hold_live);
}

/* C05C2D10: the player makes its buffer pool. */
USED void fpl_card_play_pool(struct fpl_card *c) {
    if (!card_valid(c) || c->hold_live) return;
    /* a take that never finished may have left the engine open */
    if (c->hold.magic) c->engine_release = fpl_codec_job_release(&c->hold.job);
    fpl_play_pool(&c->play);
}

/* C05C2E90: the player frees its buffers. */
USED void fpl_card_play_end(struct fpl_card *c) {
    if (card_valid(c)) fpl_play_end(&c->play);
}

#ifdef FPL_DIAG_HOOK_TIME
static void hook_done(struct fpl_card *c, uint32_t which, uint32_t began) {
    uint32_t took, sp;
    if (!card_valid(c)) return;
    took = card_tick_us() - began;
    __asm__ volatile("mov %0, sp" : "=r"(sp));
    c->hook_time[which][0]++;
    c->hook_time[which][1] += took;
    if (took > c->hook_time[which][2]) c->hook_time[which][2] = took;
    c->hook_time[which][3] = sp;
}
USED uint32_t fpl_card_rec(uintptr_t camera, const uint32_t *request, struct fpl_card *c) {
    uint32_t t = card_tick_us(), r = fpl_card_rec_body(camera, request, c);
    hook_done(c, 0, t); return r;
}
USED uint32_t fpl_card_arrive(uintptr_t creator, uint32_t id, uint32_t argument,
                              struct fpl_card *c) {
    uint32_t t = card_tick_us(), r = fpl_card_arrive_body(creator, id, argument, c);
    hook_done(c, 1, t); return r;
}
USED void fpl_card_stop(struct fpl_card *c, uint32_t kind) {
    uint32_t t = card_tick_us(); fpl_card_stop_body(c, kind); hook_done(c, 2, t);
}
USED void fpl_card_flush(uintptr_t writer, struct fpl_card *c) {
    uint32_t t = card_tick_us(); fpl_card_flush_body(writer, c); hook_done(c, 3, t);
}
USED uint32_t fpl_card_observe(uintptr_t pool, struct fpl_card *c) {
    uint32_t t = card_tick_us(), r = fpl_card_observe_body(pool, c);
    hook_done(c, 4, t); return r;
}
USED void fpl_card_written(struct fpl_card *c, uint32_t low, uint32_t high) {
    uint32_t t = card_tick_us(); fpl_card_written_body(c, low, high); hook_done(c, 5, t);
}
USED void fpl_card_event(uintptr_t message, uintptr_t frame, struct fpl_card *c) {
    uint32_t t = card_tick_us(); fpl_card_event_body(message, frame, c); hook_done(c, 6, t);
}
USED void fpl_card_discard(uintptr_t creator, uintptr_t frame, uint32_t caller,
                           struct fpl_card *c) {
    uint32_t t = card_tick_us(); fpl_card_discard_body(creator, frame, caller, c); hook_done(c, 7, t);
}
#endif
USED uint32_t fpl_card_state_bytes(void) { return sizeof(struct fpl_card); }
