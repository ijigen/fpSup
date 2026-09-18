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

uint32_t fpl_can_enable(const struct fpl_context *c) {
    if (!c) return FPL_INVALID;
    if (c->ready & FPL_BLOCK_REC) return FPL_FAULT;
    /* First integration target only: FHD RAW12, SD, 24000/1001.
     * No sensor-mode IDs, OpenGate tables or crop state are modified here.
     * Geometry eligibility is NOT proof of a functioning compression path. */
    if (c->firmware != 502 || c->cine != 1 || c->compression != 1 ||
        c->bits != 12 || c->width != 1936 || c->height != 1090 ||
        c->fps_num != 24000 || c->fps_den != 1001 || c->media != 1)
        return FPL_UNSUPPORTED;
    if ((c->ready & FPL_READY_ALL) != FPL_READY_ALL) return FPL_NOT_READY;
    return FPL_OK;
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
        result = fpl_can_enable(c);
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
        result = fpl_can_enable(c);
        if (result) return result; /* refuse REC; never silently write RAW */
    }
    s->frames = 0;
    s->clip = s->requested ? FPL_LOSSLESS : FPL_RAW;
    return FPL_OK;
}

uint32_t fpl_frame_done(struct fpl_state *s) {
    if (!valid(s)) return FPL_INVALID;
    if (s->clip == FPL_STOP) return FPL_FAULT;
    if (s->clip != FPL_LOSSLESS) return FPL_INVALID;
    if (s->frames == UINT32_MAX) return fpl_fail(s, FPL_INVALID);
    ++s->frames;
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
