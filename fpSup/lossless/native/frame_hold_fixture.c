/* Host substitutes for the same-frame adapter. Never linked into a camera
 * build. One flat memory holds frame structs, frame buffers and our
 * workspace; the uncached alias (+0x40000000) maps onto the same bytes and
 * every access through it is counted.
 *
 * The fake engine writes, as the first word of its output, the first word
 * of the SOURCE it was started on. So "which frame's picture is in this
 * file" is directly observable: a frame queued with its own marker in its
 * payload is same-frame; any other marker is the bug this design removes. */
#include <string.h>
#include "frame_hold.h"
#include "flush_site.h"

#define MEM        0x10000000u
#define MEM_SIZE   (16u << 20)
#define UNCACHED   0x40000000u
#define FRAMES     (MEM + 0x000000u)      /* struct i at +i*0x2000 */
#define BUFFERS    (MEM + 0x100000u)      /* handle i at +i*0x60000 */
#define OUTPUT     (MEM + 0xA00000u)
#define TABLE      (MEM + 0xB00000u)
#define EXTRA      (MEM + 0xC00000u)      /* more buffers, like the pool's */
#define EXTRAS     10u
#define CREATOR    0xC0DE0000u
#define ENGINE     0xc302cdd4u
#define TILECOUNT  0xc302cdecu
#define ENDPOS     0x300d00f8u
#define E_TMOUT    0xffffffceu
#define MAX_ID     24u

static uint8_t mem[MEM_SIZE];
static uint32_t engine[6], tilecount, endpos, uncached_hits, barriers, oob;
static uint32_t devregs[0x40];         /* the engine's register window */
static uint32_t enq_ids[256], enq_payload[256], enq_state[256], enq_n;
static uint32_t enq_result, enq_calls;
static uint32_t barrier_log[1024], barrier_n;
static uint32_t published(void);
static uint32_t frame_present[MAX_ID];

static uint32_t *slot(uintptr_t a, uint32_t count) {
    if (a >= ENGINE && a < ENGINE + 24) return &engine[(a - ENGINE) / 4];
    if (a == TILECOUNT) return &tilecount;
    if (a == ENDPOS) return &endpos;
    if (a >= 0x300d0000u && a < 0x300d0100u) return &devregs[(a - 0x300d0000u) / 4];
    if (a == 0x300d03fcu) return &devregs[0x3f];
    if (a >= MEM + UNCACHED && a < MEM + UNCACHED + MEM_SIZE) {
        if (count) uncached_hits++;
        a -= UNCACHED;
    }
    if (a >= MEM && a + 4 <= MEM + MEM_SIZE) return (uint32_t *)(void *)&mem[a - MEM];
    oob++;
    return 0;
}
static uint32_t rd(uintptr_t a) { uint32_t *s = slot(a, 1); return s ? *s : 0; }
static void wr(uintptr_t a, uint32_t v) { uint32_t *s = slot(a, 1); if (s) *s = v; }
static uint32_t rd_quiet(uintptr_t a) { uint32_t *s = slot(a, 0); return s ? *s : 0; }
static void wr_quiet(uintptr_t a, uint32_t v) { uint32_t *s = slot(a, 0); if (s) *s = v; }

/* ---- geometry: a small frame keeps the test fast ---------------------- */
/* 520x368: like FHD, the engine is told 512 B MORE than the native frame
 * allocation holds (1 KiB rounding against 512 B rounding). */
static uint32_t width = 520, height = 368, format = 0;
static uint32_t fixture_pitch_test;   /* = hold.pitch_test after reset */
static uint32_t told(void) { return fpl_codec_source_bytes_test(width, height, format, fixture_pitch_test); }
/* the take's header bytes (frame+0x14C): 0x13400 stock, longer with the
 * card's tag (header_tag.h); the file starts that far before the raster */
static uint32_t fixture_head = 0x13400u;
#define FILE_AT (0x15400u - fixture_head)
void fpl_fixture_head(uint32_t head) { fixture_head = head; }
static uintptr_t frame_at(uint32_t id) { return FRAMES + id * 0x2000u; }
/* C0135D40 for Sigpro formats 0 (12), 1 (14) and 3 (10) bit */
static uint32_t row_of(uint32_t w) {
    return format == 1 ? w * 7 / 4 : format == 3 ? w * 5 / 4 : w * 3 / 2;
}
static uint32_t raster_bytes(void) {
    return (height - 1) * ((row_of(width) + 3) & ~3u) + ((row_of((width + 11) / 12 * 12) + 3) & ~3u);
}
/* The geometry of the NEXT reset only (2026-11-10, 14 bit); then 520x368x12. */
static uint32_t shape_w = 520, shape_h = 368, shape_f = 0;
void fpl_fixture_shape(uint32_t w, uint32_t h, uint32_t f) { shape_w = w; shape_h = h; shape_f = f; }
/* The row-pitch test switch for the NEXT reset only: bit 0 -> control's
 * ready bit (FPL_TEST_PITCH), bit 1 -> the hold's pitch_test (card.c sets
 * both from one word; separate here to test each guard alone). */
static uint32_t shape_pitch = 0;
void fpl_fixture_pitch(uint32_t v) { shape_pitch = v; }
/* What C037A990 asks the allocator for: reserve + align512(raster). */
static uint32_t native_allocation(void) {
    return 0x15400u + ((raster_bytes() + 0x1ffu) & ~0x1ffu);
}
static uintptr_t handle_of(uint32_t id) { return BUFFERS + id * 0x60000u; }
/* The allocation frame `id` holds NOW: a swap moves frames between buffers,
 * so everything the firmware reads goes through the frame's own record. */
static uintptr_t current_handle(uint32_t id) { return rd_quiet(frame_at(id) + 0x68); }
static uintptr_t raster_of(uint32_t id) { return current_handle(id) + 0x15400u; }

/* ---- hold natives ----------------------------------------------------- */
static uintptr_t n_frame(uint32_t id) {
    return id < MAX_ID && frame_present[id] ? frame_at(id) : 0;
}
static uint32_t reenter;
static void collect_both(void);
static uint32_t n_enqueue(uintptr_t creator, uint32_t id, uint32_t argument) {
    enq_calls++;
    /* another context collecting while this one is inside a collect */
    if (reenter) { reenter = 0; collect_both(); }
    if (creator != CREATOR || argument != 1) oob++;
    if (enq_result != 1) return enq_result;
    /* C037DD50's busy no-insert branch still returns 1. */
    if (id < MAX_ID && frame_present[id] && !(rd_quiet(frame_at(id)) & 0xffu)) return 1;
    if (enq_n < 256) {
        enq_ids[enq_n] = id;
        enq_payload[enq_n] = id < MAX_ID && frame_present[id] ? rd_quiet(raster_of(id)) : 0;
        enq_state[enq_n] = id < MAX_ID ? rd_quiet(frame_at(id) + 0x1104) : 0;
        enq_n++;
    }
    if (id < MAX_ID) wr_quiet(frame_at(id) + 0x1104, 0xB);   /* as C037DD50 */
    return 1;
}
static uintptr_t n_uncached(uintptr_t a) { return a + UNCACHED; }
static void n_barrier(void) {
    barriers++;
    if (barrier_n < 1024) barrier_log[barrier_n++] = published();
}
/* IRQ masking: depth counted, and what the lane word held each time. */
static uint32_t irq_depth, irq_offs, irq_bad;
static uint32_t n_irq_off(void) { irq_offs++; return irq_depth++ ? 0x80u : 0u; }
static void n_irq_restore(uint32_t m) {
    if (!irq_depth || (m != 0 && m != 0x80u)) irq_bad++;
    else irq_depth--;
}
/* The codec task runs while stop sleeps: each millisecond is one pass. */
static uint32_t sleeps, task_in_sleep;
static void task_pass(void);
/* The clock: each sleep and each codec-task pass is that many ms. */
static uint32_t clock_us;
static uint32_t n_tick_us(void) { return clock_us; }
static void n_sleep_ms(uint32_t n) {
    sleeps += n;
    clock_us += 1000u * n;
    if (task_in_sleep) task_pass();
}
/* The header DMA: copies through the cached (plain) addresses, counted. */
static uint32_t dmas, dma_fail, dma_bad;
static uint32_t n_dma(uintptr_t to, uintptr_t from, uint32_t bytes) {
    dmas++;
    if (to >= MEM + UNCACHED || from >= MEM + UNCACHED || (bytes & 3u)) dma_bad++;
    if (dma_fail) return 5;
    for (uint32_t n = 0; n < bytes; n += 4) wr_quiet(to + n, rd_quiet(from + n));
    return 0;
}
void fpl_fixture_dma_fails(uint32_t v) { dma_fail = v; }
const struct fpl_hold_natives fpl_hold_test_natives = {
    n_frame, n_enqueue, rd, wr, n_uncached, n_barrier, n_irq_off, n_irq_restore, n_sleep_ms,
    n_dma, n_tick_us
};

/* ---- the fake engine ---------------------------------------------------- */
enum { MODE_OK, MODE_REFUSE, MODE_WAIT_ERROR, MODE_NEVER, MODE_NEVER_ONCE };
static uint32_t mode, latency, left, running, payload_bytes, open_ret, close_ret, stuck;
static uintptr_t started_source, started_dest, band_table;
static uint32_t starts, closes;

static uint32_t bswap(uint32_t v) {
    return (v >> 24) | ((v >> 8) & 0xff00u) | ((v & 0xff00u) << 8) | (v << 24);
}
static uint32_t c_init(const uint32_t *p) {
    uint32_t bits = p[2] == 0 ? 12 : p[2] == 3 ? 10 : p[2] == 1 ? 14 : 16;
    engine[0] = p[5]; engine[1] = 0; engine[2] = p[6];
    engine[3] = (p[0] * p[1] * bits / 8 + 0x3ffu) & ~0x3ffu;
    engine[4] = p[7]; engine[5] = 160 * 4;
    return 1;
}
static uint32_t c_flag(void) { return 42; }
static uint32_t c_clr(uint32_t f, uint32_t p) { (void)f; (void)p; return 0; }
static uint32_t c_open(void) { return open_ret; }
static uint32_t c_submit(const uint32_t *r) {
    started_source = r[5]; started_dest = r[7]; band_table = r[9];
    return 0;
}
static void c_reset(void) {}
static uint32_t c_start(void) {
    if (running) oob++;                  /* one engine: started while running */
    if (mode == MODE_NEVER_ONCE) { stuck = 1; mode = MODE_OK; }   /* this job only */
    running = 1; left = latency; starts++; return 0;
}
static uint32_t c_close(void) {
    closes++;
    if (close_ret) return close_ret;  /* failure leaves hardware ownership unknown */
    running = 0; stuck = 0; return 0;
}
static uint32_t twai_calls, twai_last_ticks;
static uint32_t c_twai(uint32_t f, uint32_t w, uint32_t m, uint32_t *p, uint32_t t) {
    (void)f; (void)w; (void)m;
    twai_calls++;
    twai_last_ticks = t;
    if (mode == MODE_WAIT_ERROR) return 0xffffffefu;
    if (mode == MODE_NEVER || stuck) return E_TMOUT;
    /* `left` ticks of work remain: a wait of t ticks covers t of them */
    if (left) {
        if (t <= 1u || left > t) { left -= t > 1u ? t : 1u; return E_TMOUT; }
        left = 0;
    }
    if (mode == MODE_REFUSE) { *p = 5; return 0; }
    /* "encode": the source's marker, then filler, into our output */
    /* compressed marker 0xC00000id, carrying the SOURCE frame's id */
    wr_quiet(started_dest, 0xC0000000u | (rd_quiet(started_source) & 0xFFFFu));
    for (uint32_t n = 4; n < payload_bytes; n += 4) wr_quiet(started_dest + n, 0x11111111u);
    *p = 1;
    return 0;
}
static void c_eoi(uintptr_t d, uint32_t e) { (void)d; (void)e; }
static void c_tiles(uintptr_t d, uintptr_t t, uint32_t n) {
    (void)d;
    for (uint32_t i = 0; i < n; ++i)
        wr_quiet(t + 4 * i, bswap(i + 1 < n ? payload_bytes / n : payload_bytes - (n - 1) * (payload_bytes / n)));
}
static uint32_t c_total(uintptr_t t, uint32_t n) {
    uint32_t s = 0;
    for (uint32_t i = 0; i < n; ++i) s += bswap(rd_quiet(t + 4 * i));
    return s;
}
const struct fpl_codec_natives fpl_codec_test_natives = {
    c_init, c_flag, c_clr, c_twai, c_open, c_submit, c_reset, c_start, c_close,
    c_eoi, c_tiles, c_total, rd_quiet, wr_quiet
};

/* producer_facts.c is linked for its match(); its services are unused here */
uintptr_t fpl_test_settings(void) { return 0; }
void fpl_test_query(uintptr_t *o, uint32_t a, uintptr_t b, uint32_t c) { (void)a; (void)b; (void)c; *o = 0; }
void fpl_test_release(uintptr_t *o, uint32_t f) { (void)o; (void)f; }
uint32_t fpl_test_raster(uint32_t w, uint32_t h, uint32_t f) { (void)w; (void)h; (void)f; return 0; }
void fpl_test_rate(uint32_t *o) { o[0] = o[1] = 0; }

/* ---- the objects under test ------------------------------------------- */
static struct fpl_pipeline pipeline;
static struct fpl_state control;
static struct fpl_producer_facts facts;
static struct fpl_frame_hold hold;
static struct fpl_pipeline pipeline_b;
static struct fpl_frame_hold hold_b;
static struct fpl_frame_hold *const lanes[2] = {&hold, &hold_b};
static void task_pass(void) { fpl_lanes_task(lanes); }
static void collect_both(void) { fpl_hold_collect(&hold); fpl_hold_collect(&hold_b); }
void fpl_fixture_reenter(uint32_t v) { reenter = v; }
/* 0: the codec task does not run while stop sleeps (starved) */
void fpl_fixture_task_in_sleep(uint32_t v) { task_in_sleep = v; }
static struct fpl_flush_stats flush_stats;
/* The take's prepared IFD (header_tag.h): every frame's header is the same
 * template, so preparing it in each frame's header gives the same record. */
static struct fpl_header_tag fixture_tag;
static uint32_t fixture_tag_ready;
#define FIXTURE_TAG_AT 0x400u
static uint32_t writer_count;
static uint32_t published(void) {
    uint32_t n = 0;
    for (uint32_t i = 0; i < FPL_HOLD_COMMITS; ++i)
        n += (hold.ring[i].file != 0) + (hold_b.ring[i].file != 0);
    return n;
}
static uint32_t descriptor[18];
static uint32_t use_spare;
/* The next reset gives the adapter a spare allocation for the buffer swap. */
void fpl_fixture_use_spare(uint32_t v) { use_spare = v; }
static uint32_t no_output;
/* The next reset gives the adapter no output span (the card's setting). */
void fpl_fixture_no_output(uint32_t v) { no_output = v; }

/* Like the class-10 pool: a buffer some live owner holds -- a present frame
 * or the adapter's spare -- is never handed out again. The frame being
 * (re)created gives its previous buffer back first, as C0374180 does after
 * that file was written. Prefers the frame's usual buffer, so tests can name
 * addresses. */
static uint32_t buffer_owned(uintptr_t b, uint32_t except) {
    if (hold.workspace.spare.handle == b || hold_b.workspace.spare.handle == b) return 1;
    for (uint32_t i = 0; i < MAX_ID; ++i)
        if (i != except && frame_present[i] && current_handle(i) == b) return 1;
    return 0;
}
static uintptr_t allocate(uint32_t id) {
    if (!buffer_owned(handle_of(id), id)) return handle_of(id);
    for (uint32_t k = 0; k < EXTRAS; ++k)
        if (!buffer_owned(EXTRA + k * 0x60000u, id)) return EXTRA + k * 0x60000u;
    oob++;
    return 0;
}


uint32_t fpl_fixture_reset(uint32_t latency_polls, uint32_t payload, uint32_t lossless) {
    uint32_t pitch;
    struct fpl_context c;
    struct fpl_hold_workspace w;
    memset(mem, 0, sizeof mem);
    memset(engine, 0, sizeof engine);
    fixture_head = 0x13400u;
    memset(&pipeline, 0, sizeof pipeline); memset(&control, 0, sizeof control);
    memset(&facts, 0, sizeof facts); memset(&hold, 0, sizeof hold);
    memset(&pipeline_b, 0, sizeof pipeline_b); memset(&hold_b, 0, sizeof hold_b);
    irq_depth = irq_offs = irq_bad = sleeps = task_in_sleep = reenter = 0;
    twai_calls = twai_last_ticks = 0;
    dmas = dma_fail = dma_bad = 0;
    memset(frame_present, 0, sizeof frame_present);
    enq_n = uncached_hits = barriers = oob = tilecount = endpos = barrier_n = 0;
    enq_result = 1; enq_calls = 0;
    memset(&flush_stats, 0, sizeof flush_stats);
    fixture_tag_ready = 0;
    writer_count = 1;
    mode = MODE_OK; latency = latency_polls; left = running = stuck = 0;
    payload_bytes = payload; open_ret = close_ret = 0; starts = closes = 0;
    width = shape_w; height = shape_h; format = shape_f;
    shape_w = 520; shape_h = 368; shape_f = 0;
    pitch = shape_pitch; shape_pitch = 0;
    fixture_pitch_test = 0;
    for (uint32_t n = 0; n < 18; ++n) descriptor[n] = 0x2000u + n;
    descriptor[0] = width; descriptor[1] = height; descriptor[8] = format;
    if (fpl_producer_facts_init(&facts) != FPL_OK) return 90;
    facts.seen.width = width; facts.seen.height = height; facts.seen.format = format;
    facts.seen.bits = format == 1 ? 14 : format == 3 ? 10 : 12; facts.seen.raster = raster_bytes();
    memcpy(facts.seen.descriptor, descriptor, sizeof descriptor);
    fpl_boot(&control);
    if (fpl_pipeline_init(&pipeline, 7) != FPL_OK) return 91;
    memset(&c, 0, sizeof c);
    c.firmware = 502; c.cine = 1; c.compression = 1; c.bits = facts.seen.bits;
    c.width = width; c.height = height; c.fps_num = 24000; c.fps_den = 1001;
    c.media = 1; c.ready = 0x7E | (pitch & 1u ? FPL_TEST_PITCH : 0u);
    if (lossless && fpl_begin_direct(&control, &c) != FPL_OK) return 92;
    if (lossless && fpl_pipeline_begin(&pipeline, &control) != FPL_OK) return 93;
    w.output = no_output ? 0 : OUTPUT; w.table = TABLE;
    w.output_capacity = no_output ? 0 : 0x80000; w.table_capacity = 0x1000;
    w.spare.handle = use_spare ? EXTRA + (EXTRAS - 1) * 0x60000u : 0;
    w.spare.capacity = use_spare ? native_allocation() + 1024u : 0;
    w.spare.allocator_class = use_spare ? 10u : 0;
    {
        uint32_t r = fpl_hold_init(&hold, &pipeline, &facts, &w);
        hold.pitch_test = (pitch >> 1) & 1u;
        fixture_pitch_test = hold.pitch_test;
        return r;
    }
}
void fpl_fixture_mode(uint32_t m) { mode = m; }
void fpl_fixture_open_fails(uint32_t v) { open_ret = v; }
void fpl_fixture_close_fails(uint32_t v) { close_ret = v; }
void fpl_fixture_enqueue_result(uint32_t v) { enq_result = v; }
void fpl_fixture_present(uint32_t id, uint32_t v) {
    if (id < MAX_ID) frame_present[id] = v;
}
/* A frame as the creator leaves it: kind 1, descriptor, allocation, reserve,
 * and a marker as the first pixel word so its picture can be recognised. */
void fpl_fixture_frame(uint32_t id, uint32_t spare_capacity) {
    uintptr_t f = frame_at(id), handle = allocate(id);
    frame_present[id] = 1;
    wr_quiet(f, 1);                         /* a new submission, not FIFO re-entry */
    wr_quiet(f + 0x04, 1);
    for (uint32_t n = 0; n < 18; ++n) wr_quiet(f + 0x10 + 4 * n, descriptor[n]);
    wr_quiet(f + 0x68, (uint32_t)handle);
    /* the native request, plus whatever more the allocator granted */
    wr_quiet(f + 0x6c, native_allocation() + spare_capacity);
    wr_quiet(f + 0x70, 10);
    wr_quiet(f + 0x128, 0x15400u);
    wr_quiet(f + 0x4c, (uint32_t)handle + 0x15400u);    /* descriptor word 15 */
    wr_quiet(f + 0x14c, fixture_head);                 /* set before the enqueue */
    wr_quiet(f + 0x1104, 8);
    wr_quiet(f + 0x1114, 0);                           /* no clones */
    wr_quiet(f + 0x1118, 0xffffffffu);                 /* owns its allocation */
    wr_quiet(handle + FILE_AT, 0x48000000u | id);      /* its header, DMA'd in */
    wr_quiet(raster_of(id), 0xF0000000u | id);          /* this frame's picture */
    wr_quiet(raster_of(id) + 4, 0xFEEDFACEu);
}
void fpl_fixture_frame_field(uint32_t id, uint32_t offset, uint32_t value) {
    wr_quiet(frame_at(id) + offset, value);
}
/* Lane mode: a second lane with its own pipeline, spare and table, and the
 * codec task, run by hand (fpl_fixture_task) or inside stop's sleeps. */
uint32_t fpl_fixture_lanes(uint32_t second) {
    struct fpl_hold_workspace w = hold.workspace;
    task_in_sleep = 1;
    if (!second) return FPL_OK;
    if (fpl_pipeline_init(&pipeline_b, 8) != FPL_OK) return 94;
    if (pipeline.active && fpl_pipeline_begin(&pipeline_b, &control) != FPL_OK) return 95;
    w.output = 0; w.output_capacity = 0;
    w.table = TABLE + 0x1000u;
    w.spare.handle = EXTRA + (EXTRAS - 2) * 0x60000u;
    w.spare.capacity = native_allocation() + 1024u;
    w.spare.allocator_class = 10u;
    return fpl_hold_init(&hold_b, &pipeline_b, &facts, &w);
}
uint32_t fpl_fixture_lane_arrive(uint32_t id) { return fpl_lanes_arrive(lanes, CREATOR, id, 1); }
uint32_t fpl_fixture_task_wait(uint32_t ticks) { return fpl_lanes_task_wait(lanes, ticks); }
uint32_t fpl_fixture_twai(uint32_t which) { return which ? twai_last_ticks : twai_calls; }
uint32_t fpl_fixture_task(void) {           /* one pass, then its 1 ms sleep */
    uint32_t r = fpl_lanes_task(lanes);
    clock_us += 1000u;
    return r;
}
uint32_t fpl_fixture_kick(uint32_t n) { return fpl_hold_kick(lanes[n & 1u]); }
uint32_t fpl_fixture_lane_stop(void) { return fpl_lanes_stop(lanes); }
uint32_t fpl_fixture_lane_abandon(uint32_t n) { return fpl_hold_abandon(lanes[n & 1u]); }
uint32_t fpl_fixture_lane_finish(uint32_t n) {
    return fpl_pipeline_finish(n ? &pipeline_b : &pipeline, 1);
}
uint32_t fpl_fixture_lane_get(uint32_t n, uint32_t field) {
    struct fpl_frame_hold *h = lanes[n & 1u];
    switch (field) {
    case 0: return h->lane;
    case 1: return h->compressed;
    case 2: return h->held;
    case 4: return h->faults;
    case 5: return (n ? &pipeline_b : &pipeline)->phase;
    case 6: return h->order;
    case 7: return h->lanes_full;
    case 8: return irq_depth;
    case 9: return irq_offs;
    case 10: return irq_bad;
    case 11: return sleeps;
    case 12: return h->drained;
    case 13: return h->swapped;
    case 14: return running;
    case 15: return h->last_result;
    case 16: { uint32_t m = 0; for (uint32_t i = 0; i < 8; ++i) m |= (h->refused_by[i] != 0) << i; return m; }
    case 17: return h->arrivals;
    case 18: return h->stalls;
    case 19: return enq_calls;
    default: return 0xFFFFFFFFu;
    }
}
uint32_t fpl_fixture_arrive(uint32_t id) { return fpl_hold_arrive(&hold, CREATOR, id, 1); }
uint32_t fpl_fixture_arrive_arg(uint32_t id, uint32_t arg) {
    return fpl_hold_arrive(&hold, CREATOR, id, arg);
}
uint32_t fpl_fixture_stop(void) { return fpl_hold_stop(&hold); }
uint32_t fpl_fixture_finish(void) { return fpl_pipeline_finish(&pipeline, 1); }
void fpl_fixture_break(void) { hold.magic = 0; }
/* the pipeline in a state where completion is refused */
void fpl_fixture_pipeline_phase(uint32_t v) { pipeline.phase = v; }
/* The writer's flush for frame `id`: returns the payload it was promised, or
 * 0xFFFFFFFF for none, and consumes the promise when `consume`. */
uint32_t fpl_fixture_flush(uint32_t id, uint32_t consume) {
    struct fpl_frame_hold *h = &hold;
    const struct fpl_hold_commit *c = fpl_hold_peek(h, current_handle(id) + FILE_AT);
    if (!c) c = fpl_hold_peek(h = &hold_b, current_handle(id) + FILE_AT);
    if (!c) return 0xFFFFFFFFu;
    uint32_t payload = c->payload;
    if (consume) fpl_hold_consumed(h, c);
    return payload;
}
uint32_t fpl_fixture_commit_tiles(uint32_t id, uint32_t index) {
    const struct fpl_hold_commit *c = fpl_hold_peek(&hold, current_handle(id) + FILE_AT);
    if (!c) return 0xFFFFFFFFu;
    if (index == 0xFFFEu) return c->tile_width << 16 | c->tile_height;
    return index == 0xFFFFu ? c->tiles : c->tile_bytes[index];
}
void fpl_fixture_tile_force(uint32_t force) { hold.tile_force = hold_b.tile_force = force; }
void fpl_fixture_require_head(uint32_t v) { hold.require_head = hold_b.require_head = v; }
uint32_t fpl_fixture_get(uint32_t field) {
    if (field >= 1000 && field < 1256) return enq_ids[field - 1000];
    if (field >= 2000 && field < 2256) return enq_payload[field - 2000];
    if (field >= 3000 && field < 3256) return enq_state[field - 3000];
    if (field >= 4000 && field < 4000 + MAX_ID) return rd_quiet(frame_at(field - 4000) + 0x1104);
    if (field >= 5000 && field < 5000 + MAX_ID) return rd_quiet(raster_of(field - 5000));
    if (field >= 6000 && field < 7024) return barrier_log[field - 6000];
    if (field >= 8000 && field < 8000 + MAX_ID) return (uint32_t)(current_handle(field - 8000) - MEM);
    if (field >= 9000 && field < 9000 + MAX_ID) return rd_quiet(current_handle(field - 9000) + FILE_AT);
    if (field >= 10000 && field < 10000 + MAX_ID) return rd_quiet(frame_at(field - 10000) + 0x6c);
    if (field >= 11000 && field < 11000 + MAX_ID) return rd_quiet(frame_at(field - 11000) + 0x70);
    if (field >= 12000 && field < 12000 + MAX_ID) return rd_quiet(frame_at(field - 12000) + 0x4c) - MEM;
    switch (field) {
    case 0: return enq_n;
    case 1: return hold.arrivals;
    case 2: return hold.held;
    case 3: return hold.passed;
    case 4: return hold.compressed;
    case 5: return hold.refused;
    case 6: return hold.no_benefit;
    case 7: return hold.not_eligible;
    case 8: return hold.drained;
    case 9: return hold.faults;
    case 10: return pipeline.phase;
    case 11: return starts;
    case 12: return closes;
    case 13: return oob;
    case 14: return uncached_hits;
    case 15: return barriers;
    case 16: return told();
    case 17: return (uint32_t)(started_source - MEM);
    case 18: return raster_bytes();
    case 19: return pipeline.active;
    case 20: return native_allocation();
    case 21: return barrier_n;
    case 22: return published();
    case 24: return hold.direct;
    case 26: return hold.job.source_capacity;
    case 27: return hold.workspace.spare.handle ? (uint32_t)(hold.workspace.spare.handle - MEM) : 0;
    case 28: return hold.swapped;
    case 29: return hold.swap_declined;
    case 30: return hold.swap_undone;
    case 31: return hold.workspace.spare.capacity;
    case 32: {                  /* no buffer has two live owners */
        for (uint32_t i = 0; i < MAX_ID; ++i) {
            if (!frame_present[i]) continue;
            if (current_handle(i) == hold.workspace.spare.handle ||
                current_handle(i) == hold_b.workspace.spare.handle) return 0;
            for (uint32_t j = i + 1; j < MAX_ID; ++j)
                if (frame_present[j] && current_handle(j) == current_handle(i)) return 0;
        }
        return 1;
    }
    case 33: return (uint32_t)(started_dest - MEM);
    case 34: return dmas;
    case 35: return dma_bad;
    case 36: return hold.dma_failed;
    case 37: return hold.pitch_forced;
    default: return 0xFFFFFFFFu;
    }
}

/* ---- the writer's flush ------------------------------------------------ */
const struct fpl_flush_natives fpl_flush_test_natives = { rd, wr, n_uncached, n_barrier };
#define WRITER (MEM + 0x0F0000u)


/* A minimal CinemaDNG root IFD, sorted, at the file's offset 8, with the
 * card's tag (header_tag.h) -- as the template of an admitted take is -- and
 * that take's IFD prepared in it. */
void fpl_fixture_header(uint32_t id) {
    static const uint16_t tags[] = {256, 257, 258, 259, 262, 273, 277, 278, 279, 284,
                                    FPL_HEADER_TAG};
    uintptr_t file = current_handle(id) + FILE_AT;
    uint32_t n = sizeof tags / sizeof tags[0];
    wr_quiet(file, 0x002a4949u);                         /* II*\0 */
    wr_quiet(file + 4, 8);
    uint8_t *p = &mem[file - MEM + 8];
    p[0] = (uint8_t)n; p[1] = 0;
    for (uint32_t i = 0; i < n; ++i) {
        uint8_t *e = p + 2 + 12 * i;
        uint32_t value = tags[i] == 256 ? width : tags[i] == 257 ? height :
                         tags[i] == 258 ? facts.seen.bits : tags[i] == 259 ? 1 :
                         tags[i] == 273 ? fixture_head : tags[i] == 279 ? raster_bytes() :
                         tags[i] == FPL_HEADER_TAG ? FIXTURE_TAG_AT : 1;
        uint32_t count = tags[i] == FPL_HEADER_TAG ? FPL_HEADER_TAG_MAX : 1;
        uint16_t type = tags[i] == FPL_HEADER_TAG ? 7 :
                        (tags[i] == 256 || tags[i] == 257 || tags[i] == 273 ||
                         tags[i] == 278 || tags[i] == 279) ? 4 : 3;
        e[0] = (uint8_t)tags[i]; e[1] = (uint8_t)(tags[i] >> 8);
        e[2] = (uint8_t)type; e[3] = 0;
        memcpy(e + 4, &count, 4);
        memcpy(e + 8, &value, 4);
    }
    memset(p + 2 + 12 * n, 0, 4);
    fixture_tag_ready = fpl_header_tag_prepare(&fixture_tag, file, fixture_head,
                                               rd_quiet, wr_quiet) == FPL_OK;
}
/* The writer's final flush for frame `id`, with its node as the stock file. */
uint32_t fpl_fixture_writer_flush(uint32_t id, uint32_t length) {
    wr_quiet(WRITER + 0x90, writer_count);
    wr_quiet(WRITER + 0x8C, WRITER + 0x0C);
    wr_quiet(WRITER + 0x0C + 4, (uint32_t)(current_handle(id) + FILE_AT));
    wr_quiet(WRITER + 0x0C + 8, length ? length : fixture_head + ((raster_bytes() + 0x1ffu) & ~0x1ffu));
    return fpl_flush_before(WRITER, &hold, &hold_b, fixture_tag_ready ? &fixture_tag : NULL,
                            &flush_stats);
}
void fpl_fixture_writer_shape(uint32_t count) { writer_count = count; }
void fpl_fixture_file_poke(uint32_t id, uint32_t offset, uint32_t value) {
    wr_quiet(current_handle(id) + FILE_AT + offset, value);
}
uint32_t fpl_fixture_flush_get(uint32_t field) {
    switch (field) {
    case 0: return rd_quiet(WRITER + 0x0C + 8);
    case 1: return flush_stats.applied;
    case 2: return flush_stats.no_promise;
    case 3: return flush_stats.length_mismatch;
    case 4: return flush_stats.tag_failed;
    case 5: return flush_stats.shape;
    case 6: return rd_quiet(handle_of(0) + FILE_AT + 4);    /* unused */
    default: return 0xFFFFFFFFu;
    }
}
uint32_t fpl_fixture_file_word(uint32_t id, uint32_t offset) {
    return rd_quiet(current_handle(id) + FILE_AT + offset);
}
