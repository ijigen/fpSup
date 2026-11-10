#include "control.h"

static uint32_t valid(const struct fpl_state *s) {
    return s && s->magic == FPL_MAGIC && s->abi == FPL_ABI &&
           s->requested <= 1 && s->clip <= FPL_STOP &&
           !s->reserved0 && !s->reserved1;
}

void fpl_boot(struct fpl_state *s) {
    if (!s) return;
    s->magic = 0;
    s->abi = FPL_ABI;
    s->requested = 0;
    s->clip = FPL_IDLE;
    s->frames = 0;
    s->fault = 0;
    s->reserved0 = 0;
    s->reserved1 = 0;
    s->magic = FPL_MAGIC;
}

static uint32_t capture_eligible(const struct fpl_context *c) {
    uint32_t columns, rows;
    if (!c) return FPL_INVALID;
    if (c->ready & FPL_BLOCK_REC) return FPL_FAULT;
    /* Actual 10/12/14-bit CinemaDNG geometry, independent of a 1K/2K/4K/6K
     * menu label. The request ABI requires width divisible by 8 and even
     * height, both <= 0x4000. This is only candidate eligibility: the
     * adapter still has to prove packing, complete source coverage, bounded
     * output, writer/metadata/lifetime and rate support for this tuple.
     * 14 (2026-11-10, Sensor Lab 1:1 true 14, Sigpro format 1): the stock
     * stills path feeds the same format-1 raster to the same engine. */
    if (c->firmware != 502 || c->cine != 1 || c->compression != 1 ||
        (c->bits != 10 && c->bits != 12 && c->bits != 14) ||
        c->width < 8 || c->width > 0x4000 || (c->width & 7u) ||
        c->height < 2 || c->height > 0x4000 || (c->height & 1u) ||
        !c->fps_num || !c->fps_den || c->media != 1)
        return FPL_UNSUPPORTED;
    /* The engine reads rows bits x width / 8 bytes apart (C062FFF8 sets
     * 300D006C from bits x width); the raster's rows are that rounded up to
     * 4 bytes (C0135D40). Only where the two agree are the pixels where the
     * engine reads them: always at 12 bit, at 10 and 14 only for widths
     * that are multiples of 16. */
    if (((c->width * c->bits) >> 3) & 3u && !(c->ready & FPL_TEST_PITCH))
        return FPL_UNSUPPORTED;
    columns = (c->width + FPL_TILE_WIDTH - 1u) / FPL_TILE_WIDTH;
    rows = (c->height + FPL_TILE_HEIGHT - 1u) / FPL_TILE_HEIGHT;
    if (columns * rows > FPL_TILE_MAX)
        return FPL_UNSUPPORTED;
    return FPL_OK;
}

/* Always inlined, so the menu entries below need no link-time relocation
 * (the strict ARM extractor of tests/test_direct_control_arm.py). */
__attribute__((always_inline))
static inline uint32_t can_enable(const struct fpl_context *c) {
    uint32_t result = capture_eligible(c);
    if (result != FPL_OK) return result;
    if ((c->ready & FPL_READY_ALL) != FPL_READY_ALL) return FPL_NOT_READY;
    return FPL_OK;
}

uint32_t fpl_can_enable(const struct fpl_context *c) {
    return can_enable(c);
}

uint32_t fpl_menu_value(const struct fpl_state *s) {
    return valid(s) ? s->requested : 0;
}

uint32_t fpl_set(struct fpl_state *s, uint32_t on,
                 const struct fpl_context *c) {
    uint32_t result;
    if (!valid(s) || on > 1) return FPL_INVALID;
    if (s->clip != FPL_IDLE) return FPL_BUSY;
    if (on) {
        if (s->fault) return FPL_FAULT;
        result = can_enable(c);
        if (result) return result;
    }
    s->requested = on;
    return FPL_OK;
}

uint32_t fpl_begin(struct fpl_state *s, const struct fpl_context *c) {
    uint32_t result;
    if (!valid(s)) return FPL_INVALID;
    if (s->clip != FPL_IDLE) return FPL_BUSY;
    if (c && (c->ready & FPL_BLOCK_REC)) return FPL_FAULT;
    if (s->requested) {
        if (s->fault) return FPL_FAULT;
        result = can_enable(c);
        if (result) return result; /* refuse unready ON; not an implicit OFF */
    }
    s->frames = 0;
    s->clip = s->requested ? FPL_LOSSLESS : FPL_RAW;
    return FPL_OK;
}

uint32_t fpl_frame_done(struct fpl_state *s) {
    if (!valid(s)) return FPL_INVALID;
    if (s->clip == FPL_STOP) return FPL_FAULT;
    if (s->clip != FPL_LOSSLESS) return FPL_INVALID;
    if (s->frames != UINT32_MAX) ++s->frames;
    return FPL_OK;
}

uint32_t fpl_begin_direct(struct fpl_state *s, const struct fpl_context *c) {
    uint32_t result;
    if (!valid(s)) return FPL_INVALID;
    if (s->clip != FPL_IDLE) return FPL_BUSY;
    if (s->fault) return FPL_FAULT;
    result = capture_eligible(c);
    if (result != FPL_OK) return result;
    if ((c->ready & FPL_READY_CAPTURE) != FPL_READY_CAPTURE) return FPL_NOT_READY;
    s->requested = 1;
    s->frames = 0;
    s->clip = FPL_LOSSLESS;
    return FPL_OK;
}

uint32_t fpl_fail(struct fpl_state *s, uint32_t error) {
    if (!valid(s) || !error) return FPL_INVALID;
    if (s->clip != FPL_LOSSLESS && s->clip != FPL_STOP) return FPL_INVALID;
    if (!s->fault) s->fault = error;
    s->clip = FPL_STOP; /* adapter must stop, report and unwind owned resources */
    return FPL_FAULT;
}

uint32_t fpl_end(struct fpl_state *s, uint32_t cleanup_complete) {
    if (!valid(s)) return FPL_INVALID;
    if (cleanup_complete != 1) return FPL_BUSY;
    s->clip = FPL_IDLE;
    s->frames = 0;
    return FPL_OK; /* fault remains sticky until a quiescent boot reset */
}
