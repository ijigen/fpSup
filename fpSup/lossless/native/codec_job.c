#include "codec_job.h"

/* Every address below is Ver.5.02 [C], read from the encoder core C062F6F8
 * and its callees. Thumb entries carry bit 0. */
#define ENGINE_BLOCK   0xc302cdd4u   /* F_INIT's output: src, src len, dst,
                                        dst len, table, table len */
#define TILE_COUNT_VAR 0xc302cdecu   /* F_SIZE's loop bound */
#define DEV_ENDPOS     0x300d00f8u   /* where the engine says the stream ended */
#define DEV_ENABLE     0x300d0074u   /* bit 0: set by open (C0630480(1)), cleared by close */
#define DEV_SETUP      0x300d0040u   /* C062FFF8 ORs its set-up into 300D0040..0084 */
#define STOCK_CALLBACK 0xc062fcb1u   /* the driver's own completion callback */
#define WAIT_PATTERN   5u            /* bit 0 done, bit 2 error */
#define WAIT_OR        1u
#define WAIT_POLL      1u            /* one tick: measured as a poll live,
                                        2026-09-29/30. The firmware waits a
                                        computed >=100; that wait is the split */
#define E_TMOUT        0xffffffceu   /* -50 */
#define BAND_LIMIT     0x04000000u   /* C062F478: one band holds <= 64 MiB */

#if defined(FPL_CODEC_JOB_HOST_TEST)
#define N (&fpl_codec_test_natives)
#define native_init(p) N->init(p)
#define native_flag() N->flag()
#define native_clr_flg(f, p) N->clr_flg(f, p)
#define native_twai_flg(f, w, m, p, t) N->twai_flg(f, w, m, p, t)
#define native_open() N->open()
#define native_submit(r) N->submit(r)
#define native_reset() N->reset()
#define native_start() N->start()
#define native_close() N->close()
#define native_eoi(d, e) N->eoi(d, e)
#define native_tiles(d, t, n) N->tiles(d, t, n)
#define native_total(t, n) N->total(t, n)
#define peek(a) N->read(a)
#define poke(a, v) N->write(a, v)
#elif defined(__arm__) && UINTPTR_MAX == UINT32_MAX
typedef uint32_t (*fn0)(void);
typedef uint32_t (*fn1)(uintptr_t);
typedef uint32_t (*fn2)(uintptr_t, uintptr_t);
typedef uint32_t (*fn3)(uintptr_t, uintptr_t, uintptr_t);
typedef uint32_t (*fn5)(uint32_t, uint32_t, uint32_t, uint32_t *, uint32_t);
#define native_init(p) ((fn1)0xc05a6890u)((uintptr_t)(p))          /* ARM */
#define native_flag() ((fn0)0xc062f441u)()
#define native_clr_flg(f, p) ((fn2)0xc00169c8u)(f, p)             /* ARM */
#define native_twai_flg(f, w, m, p, t) ((fn5)0xc0016c08u)(f, w, m, p, t)
#define native_open() ((fn0)0xc062fe71u)()
#define native_submit(r) ((fn1)0xc062fe99u)((uintptr_t)(r))
#define native_reset() ((void)((fn0)0xc062fe91u)())
#define native_start() ((fn0)0xc062feb1u)()
#define native_close() ((fn0)0xc062fe81u)()
#define native_eoi(d, e) ((void)((fn2)0xc062f6c1u)(d, e))
#define native_tiles(d, t, n) ((void)((fn3)0xc062fcf9u)(d, t, n))
#define native_total(t, n) ((fn2)0xc062f4e1u)(t, n)
#define peek(a) (*(volatile const uint32_t *)(a))
#define poke(a, v) (*(volatile uint32_t *)(a) = (v))
#else
#error "ARM32 native codec ABI required; host tests must explicitly substitute it"
#endif

/* C062FE40: the engine's depth code -> bits per sample. */
static uint32_t depth_bits(uint32_t depth) {
    switch (depth) {
    case 0: return 12;
    case 1: return 14;
    case 2: return 16;
    case 3: return 10;
    default: return 0;
    }
}
/* No division: the camera build has no runtime library to supply
 * __aeabi_uidiv. Operands are bounded (<= 0x4000 / 368 = 45 steps). */
static uint32_t ceil_div(uint32_t a, uint32_t b) {
    uint32_t q = 0;
    while (a > 0) { ++q; a = a > b ? a - b : 0; }
    return q;
}
static uint32_t align_kib(uint32_t v) { return (v + 0x3ffu) & ~0x3ffu; }
static uint32_t bswap(uint32_t v) {
    return (v >> 24) | ((v >> 8) & 0xff00u) | ((v & 0xff00u) << 8) | (v << 24);
}

uint32_t fpl_codec_job_init(struct fpl_codec_job *j) {
    if (!j) return FPL_INVALID;
    const unsigned char *bytes = (const unsigned char *)j;
    for (uint32_t n = 0; n < sizeof(*j); ++n)
        if (bytes[n]) return FPL_INVALID;
    j->magic = FPL_CODEC_JOB_MAGIC;
    return FPL_OK;
}

/* C062F478 with its band rule, for one band: the engine is told
 * align_kib(bits * width * height / 8). */
static uint32_t source_bytes(uint32_t width, uint32_t height, uint32_t format,
                             uint32_t pitch_any) {
    uint32_t bits = depth_bits(format), row_band;
    if (!bits || width < 8 || width > 0x4000 || (width & 7u) ||
        height < 2 || height > 0x4000 || (height & 1u))
        return 0;
    /* C062FFF8: the engine's row pitch is bits x width / 8 (300D006C), the
     * raster's (C0135D40) that rounded up to 4 bytes. A frame where they
     * differ (10 or 14 bit, width 8 mod 16) is refused, not misread. */
    if (((bits * width) >> 3) & 3u && pitch_any != 1u) return 0;
    row_band = bits * width * FPL_TILE_HEIGHT / 8u;        /* one tile row */
    if (row_band > BAND_LIMIT) return 0;
    /* C062F478: rows per band = 64 MiB / row_band. One band only. */
    if ((uint64_t)row_band * ceil_div(height, FPL_TILE_HEIGHT) > BAND_LIMIT) return 0;
    return align_kib((uint32_t)(((uint64_t)bits * width * height) >> 3));
}
uint32_t fpl_codec_source_bytes(uint32_t width, uint32_t height, uint32_t format) {
    return source_bytes(width, height, format, 0);
}
uint32_t fpl_codec_source_bytes_test(uint32_t width, uint32_t height, uint32_t format,
                                     uint32_t pitch_any) {
    return source_bytes(width, height, format, pitch_any);
}

static uint32_t fail(struct fpl_codec_job *j, uint32_t native) {
    j->last_native = native;
    j->phase = FPL_CODEC_FAILED;
    return FPL_FAULT;
}
static uint32_t refuse(struct fpl_codec_job *j, uint32_t result) {
    j->phase = FPL_CODEC_IDLE;
    return result;
}

#if defined(FPL_DIAG_HOOK_TIME) && !defined(FPL_CODEC_JOB_HOST_TEST)
static uint32_t diag_tick(void) { return ((uint32_t (*)(void))0xc002b6e0u)(); }
#define DIAG_T0 uint32_t diag_t = diag_tick(), diag_u
#define DIAG_STEP(arr, i) (diag_u = diag_tick(), (arr)[i] += diag_u - diag_t, diag_t = diag_u)
#else
#define DIAG_T0 (void)0
#define DIAG_STEP(arr, i) ((void)0)
#endif

uint32_t fpl_codec_job_submit(struct fpl_codec_job *j, const struct fpl_codec_input *in) {
    uint32_t init[9], tiles_x, tiles_y, tiles, source_bytes, native, tw, th;
    uint32_t engine[6];
    uintptr_t band_table;

    if (!j || j->magic != FPL_CODEC_JOB_MAGIC || !in) return FPL_INVALID;
    if (j->phase == FPL_CODEC_RUNNING) return FPL_BUSY;
    if (j->phase == FPL_CODEC_FAILED) return FPL_FAULT;
    source_bytes = fpl_codec_source_bytes_test(in->width, in->height, in->format,
                                               in->pitch_any);
    if (!source_bytes) return refuse(j, FPL_UNSUPPORTED);
    if (!j->grid[0] || j->grid_for[0] != in->width || j->grid_for[1] != in->height ||
        j->grid_for[2] != in->tile_force) {
        fpl_tile_grid(in->width, in->height, in->tile_force, &j->grid[0], &j->grid[1]);
        j->grid_for[0] = in->width;
        j->grid_for[1] = in->height;
        j->grid_for[2] = in->tile_force;
    }
    tw = j->grid[0];
    th = j->grid[1];
    tiles_x = ceil_div(in->width, tw);
    tiles_y = ceil_div(in->height, th);
    tiles = tiles_x * tiles_y;
    if (tiles > FPL_CODEC_TILE_MAX) return refuse(j, FPL_UNSUPPORTED);
    /* C062F478's one-band rule for this grid's tile row */
    if ((uint64_t)(depth_bits(in->format) * in->width * th / 8u) * tiles_y > BAND_LIMIT)
        return refuse(j, FPL_UNSUPPORTED);
    if (!in->source || !in->destination || !in->table ||
        ((in->source | in->destination | in->table) & 0x3ffu))
        return refuse(j, FPL_INVALID);
    /* The engine may read the whole 1 KiB-rounded length it is told. */
    if (source_bytes > in->source_capacity) return refuse(j, FPL_NOT_READY);

    /* ---- F_INIT, exactly as a caller of F_ENC would -------------------- */
    DIAG_T0;
    init[0] = in->width;
    init[1] = in->height;
    init[2] = in->format;
    init[3] = tw;
    init[4] = th;
    init[5] = (uint32_t)in->source;
    init[6] = (uint32_t)in->destination;
    init[7] = (uint32_t)in->table;
    init[8] = 0;                         /* flag byte 0: the stock path */
    native = native_init(init);
    DIAG_STEP(j->diag_submit_us, 0);
    if (native != 1) return refuse(j, FPL_NOT_READY);  /* nothing started */
    for (uint32_t n = 0; n < 6; ++n) engine[n] = peek(ENGINE_BLOCK + 4u * n);

    /* F_INIT decided the lengths. Check every one of them against what we
     * own BEFORE the engine is started: this is the bound, not a hope. */
    band_table = engine[4] + align_kib(engine[5]);
    if (engine[0] != (uint32_t)in->source || engine[2] != (uint32_t)in->destination ||
        engine[4] != (uint32_t)in->table ||
        engine[3] > in->destination_capacity || (engine[3] & 0x3ffu) || !engine[3] ||
        !engine[5] || engine[5] < tiles * 4u ||
        band_table + engine[5] > in->table + in->table_capacity ||
        band_table + engine[5] < band_table)
        return refuse(j, FPL_NOT_READY);

    /* ---- C062F6F8 up to its wait -------------------------------------- */
    j->flag = native_flag();
    if ((int32_t)j->flag < 0) return refuse(j, FPL_NOT_READY);
    poke(TILE_COUNT_VAR, tiles);
    for (uint32_t n = 0; n < 12; ++n) j->request[n] = 0;
    j->request[0] = in->width;
    /* One band covers the frame. C062F6F8 computes the last band's height as
     * height % (tile_h * rows), which is 0 -- and refused by its own
     * validator -- when the height is an exact multiple of that. The band's
     * real height is the frame's height; that is what is passed. */
    j->request[1] = in->height;
    j->request[2] = in->format;          /* C03D9668: 0..3 map to themselves */
    j->request[3] = tw;
    j->request[4] = th;
    j->request[5] = engine[0];
    j->request[6] = source_bytes;
    j->request[7] = engine[2];
    j->request[8] = engine[3];
    j->request[9] = (uint32_t)band_table;
    j->request[10] = engine[5];
    j->request[11] = STOCK_CALLBACK;

    native_clr_flg(j->flag, 0);
    DIAG_STEP(j->diag_submit_us, 0);
    if (j->keep_open && (peek(DEV_ENABLE) & 1u)) {
        /* Still open from this take's last job: what close+open would give
         * is the set-up registers at zero. 300D0040..0070 and 0078..0088;
         * 0074 is the enable itself. */
        for (uint32_t n = 0; n < 13u; ++n) poke(DEV_SETUP + 4u * n, 0);
        for (uint32_t n = 14u; n < 19u; ++n) poke(DEV_SETUP + 4u * n, 0);
        j->reused++;
    } else if ((native = native_open()) != 0) {
        return refuse(j, FPL_NOT_READY);
    }
    DIAG_STEP(j->diag_submit_us, 1);
    for (uint32_t n = 0; n < engine[5]; n += 4) poke(band_table + n, 0);
    DIAG_STEP(j->diag_submit_us, 2);
    if ((native = native_submit(j->request)) != 0) {
        native_close();
        return refuse(j, FPL_NOT_READY);
    }
    DIAG_STEP(j->diag_submit_us, 3);
    native_reset();                      /* C062FE90: the firmware pulses the
                                            soft reset before EVERY start */
    if ((native = native_start()) != 0) {
        native_close();
        return refuse(j, FPL_NOT_READY);
    }

    j->width = in->width;
    j->height = in->height;
    j->format = in->format;
    j->depth = depth_bits(in->format);
    j->misaligned = ((j->depth * in->width) >> 3) & 3u ? 1u : 0u;
    j->tiles = tiles;
    j->tile_width = tw;
    j->tile_height = th;
    j->band_height = in->height;
    j->source = in->source;
    j->destination = in->destination;
    j->table = in->table;
    j->band_table = band_table;
    j->source_bytes = source_bytes;
    j->source_capacity = in->source_capacity;
    j->destination_bytes = engine[3];
    j->table_bytes = engine[5];
    j->polls = j->pattern = j->end_position = j->total = j->padded = 0;
    j->last_native = 0;
    DIAG_STEP(j->diag_submit_us, 4);
#ifdef FPL_DIAG_HOOK_TIME
    j->diag_n++;
#endif
    j->phase = FPL_CODEC_RUNNING;
    return FPL_OK;
}

uint32_t fpl_codec_job_abort(struct fpl_codec_job *j) {
    uint32_t native;
    if (!j || j->magic != FPL_CODEC_JOB_MAGIC) return FPL_INVALID;
    if (j->phase != FPL_CODEC_RUNNING) return FPL_OK;
    /* word by word: the card build carries no .rodata for a table */
    for (uint32_t n = 0; n < 4; ++n) j->stall_regs[n] = peek(0x300d0000u + 4u * n);
    j->stall_regs[4] = peek(0x300d0064u);
    j->stall_regs[5] = peek(0x300d0074u);
    j->stall_regs[6] = peek(DEV_ENDPOS);
    j->stall_regs[7] = peek(0x300d03fcu);
    native_clr_flg(j->flag, 0);
    if ((native = native_close()) != 0) return fail(j, native);
    j->phase = FPL_CODEC_IDLE;
    return FPL_OK;
}

uint32_t fpl_codec_job_release(struct fpl_codec_job *j) {
    uint32_t native;
    if (!j || j->magic != FPL_CODEC_JOB_MAGIC) return FPL_INVALID;
    if (j->phase == FPL_CODEC_RUNNING) return FPL_BUSY;
    if (!(peek(DEV_ENABLE) & 1u)) return FPL_OK;
    if ((native = native_close()) != 0) return fail(j, native);
    return FPL_OK;
}

uint32_t fpl_codec_job_poll(struct fpl_codec_job *j) {
    return fpl_codec_job_wait(j, WAIT_POLL);
}

uint32_t fpl_codec_job_wait(struct fpl_codec_job *j, uint32_t ticks) {
    uint32_t pattern = 0, native, total, aligned, pad;
    uintptr_t last;

    if (!j || j->magic != FPL_CODEC_JOB_MAGIC) return FPL_INVALID;
    if (j->phase == FPL_CODEC_DONE) return FPL_OK;
    if (j->phase == FPL_CODEC_FAILED) return FPL_FAULT;
    if (j->phase != FPL_CODEC_RUNNING) return FPL_INVALID;
    j->polls++;

    native = native_twai_flg(j->flag, WAIT_PATTERN, WAIT_OR, &pattern,
                             ticks ? ticks : WAIT_POLL);
    if (native == E_TMOUT) return FPL_BUSY;          /* still encoding */
    native_clr_flg(j->flag, 0);                      /* as C062F8F0 does */
    j->pattern = pattern;
    /* Any other wait failure: the firmware returns without closing, and so
     * does this. The engine's state is unknown, so the job -- and whatever
     * source and destination it was given -- stay held. */
    if (native != 0) return fail(j, native);
    if (pattern & 4u) {                              /* C062F90A */
        /* The engine refused this frame: its output would not fit the one
         * frame of room it was told. Measured 2026-09-28, the refusal writes
         * nothing -- 0 bytes out, guards untouched. The firmware closes and
         * its next call reuses the same buffers; so does this. Not a fault:
         * the frame simply goes to the card as it was. */
        if ((native = native_close()) != 0) return fail(j, native);
        j->last_native = pattern;
        j->phase = FPL_CODEC_IDLE;
        return FPL_UNSUPPORTED;
    }

    /* ---- C062F912 .. C062FA1A, in order ------------------------------- */
    DIAG_T0;
    j->end_position = peek(DEV_ENDPOS);
    native_eoi(j->destination, j->end_position);
    native_tiles(j->destination, j->band_table, j->tiles);
    DIAG_STEP(j->diag_finish_us, 0);
    total = native_total(j->band_table, j->tiles);
    DIAG_STEP(j->diag_finish_us, 1);
    aligned = align_kib(total);
    if (!total || aligned > j->destination_bytes) {  /* cannot be; never trust */
        native_close();
        return fail(j, total);
    }
    pad = aligned - total;
    for (uint32_t n = 0; n < pad; ++n) {             /* memset(dst + total, 0, pad) */
        uintptr_t at = j->destination + total + n;
        uint32_t word = peek(at & ~3u);
        uint32_t shift = (uint32_t)(at & 3u) * 8u;
        poke(at & ~3u, word & ~(0xffu << shift));
    }
    DIAG_STEP(j->diag_finish_us, 2);
    last = j->band_table + (j->tiles - 1u) * 4u;
    poke(last, bswap(bswap(peek(last)) + pad));
    for (uint32_t n = 0; n < j->tiles * 4u; n += 4)  /* into the engine's table */
        poke(j->table + n, peek(j->band_table + n));
    DIAG_STEP(j->diag_finish_us, 3);
    if (!j->keep_open && (native = native_close()) != 0) return fail(j, native);
    DIAG_STEP(j->diag_finish_us, 4);

    j->total = total;
    j->padded = aligned;
    j->phase = FPL_CODEC_DONE;
    return FPL_OK;
}
