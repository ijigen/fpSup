/* ix_cdng -- after a take, push the CinemaDNG frames still lying in the RAW
 * class arena (notes/PUSH_CALLERS.md §3).  Measured 10-25
 * (validation/20261025-rawpool-01): the last 14 of 53 FHD frames were
 * byte-identical to the card's files there, RAW used 0; older takes linger at
 * higher addresses across reboots, so only the newest DateTime is pushed.
 *
 * Reads go through the uncached alias: that is what the card was written from.
 * Runs in the control task only (it waits on the engine in mode 1).  It never
 * allocates and never runs while the class is in use -- the caller only starts
 * it after a stop.  Host mirror: host/rawpool.py (same parse, same rules). */
#include "ix_wr.h"

static uint32_t cd_u16(uint32_t a) {
    volatile uint8_t *p = (volatile uint8_t *)a;
    return p[0] | ((uint32_t)p[1] << 8);
}
static uint32_t cd_u32(uint32_t a) {
    volatile uint8_t *p = (volatile uint8_t *)a;
    return p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* One TIFF value list (SHORT or LONG): element i. */
static uint32_t cd_val(uint32_t base, uint32_t typ, uint32_t cnt, uint32_t val, uint32_t i) {
    uint32_t sz = typ == 3u ? 2u : 4u;
    if (cnt * sz <= 4u) {                       /* inline in the entry's value word */
        return sz == 2u ? (val >> (16u * i)) & 0xFFFFu : val;
    }
    return sz == 2u ? cd_u16(base + val + 2u * i) : cd_u32(base + val + 4u * i);
}

typedef struct { uint32_t w, h, size, dt; } cd_dng;

/* A little-endian DNG at `base` that ends below `hi`: its size is the end of
 * the furthest strip/tile in IFD0 (CinemaDNG keeps the image there). */
static uint32_t cd_parse(uint32_t base, uint32_t hi, cd_dng *d) {
    if (cd_u32(base) != 0x002A4949u) return 0;              /* "II*\0" */
    uint32_t ifd = cd_u32(base + 4u);
    if (ifd < 8u || ifd >= (1u << 20) || base + ifd + 2u >= hi) return 0;
    uint32_t n = cd_u16(base + ifd);
    if (n < 1u || n > 512u || base + ifd + 2u + 12u * n + 4u > hi) return 0;
    uint32_t ot = 0, oc = 0, ov = 0, ct = 0, cc = 0, cv = 0;
    d->w = d->h = d->dt = 0;
    for (uint32_t i = 0; i < n; i++) {
        uint32_t e = base + ifd + 2u + 12u * i;
        uint32_t tag = cd_u16(e), typ = cd_u16(e + 2u), cnt = cd_u32(e + 4u), val = cd_u32(e + 8u);
        if (tag == 256u) d->w = typ == 3u ? val & 0xFFFFu : val;
        else if (tag == 257u) d->h = typ == 3u ? val & 0xFFFFu : val;
        else if (tag == 273u || tag == 324u) { ot = typ; oc = cnt; ov = val; }
        else if (tag == 279u || tag == 325u) { ct = typ; cc = cnt; cv = val; }
        else if (tag == 306u && cnt == 20u && val < (1u << 20)) d->dt = base + val;
    }
    if (!d->w || !d->h || !oc || oc != cc || oc > 4096u || (ot != 3u && ot != 4u) || (ct != 3u && ct != 4u)) return 0;
    uint32_t end = 0;
    for (uint32_t i = 0; i < oc; i++) {
        uint32_t o = cd_val(base, ot, oc, ov, i), c = cd_val(base, ct, cc, cv, i);
        if (o > IX_CD_DNG_MAX || c > IX_CD_DNG_MAX) return 0;
        if (o + c > end) end = o + c;
    }
    if (!end || end > IX_CD_DNG_MAX || base + end > hi) return 0;
    d->size = end;
    return 1;
}

/* -1, 0, 1 as DateTime a sorts before, equal to, after b (19 characters). */
static int cd_cmp(uint32_t a, volatile const uint8_t *b) {
    for (uint32_t i = 0; i < 19u; i++) {
        uint8_t x = *(volatile uint8_t *)(a + i), y = b[i];
        if (x != y) return x < y ? -1 : 1;
    }
    return 0;
}

/* The arena the class chain covers, uncached: [lo, hi). 0 if no chain. */
static uint32_t cd_arena(uint32_t *lo, uint32_t *hi) {
    uint32_t obj = *(volatile uint32_t *)(IX_CD_CLASS_TBL + 4u * IX_CD_RAW_CLASS);
    if (obj < 0xC0000000u) return 0;
    uint32_t at = *(volatile uint32_t *)(obj + 0xCu);       /* heap = obj + 8; chain at heap + 4 */
    *lo = 0xFFFFFFFFu; *hi = 0;
    for (uint32_t k = 0; at && k < 4096u; k++) {
        if (at < 0x40000000u || at >= 0x80000000u) return 0;
        volatile uint32_t *b = (volatile uint32_t *)at;
        if (b[0] != IX_CD_BLOCK) return 0;
        if (at < *lo) *lo = at;
        if (at + b[1] > *hi) *hi = at + b[1];
        at = b[3] & ~0x3Fu;
    }
    return *hi > *lo;
}

void ix_cdng_run(wr_t *w) {
    ix_cap *c = &w->cap;
    uint32_t t0 = w->fw.tick_us(), lo, hi;
    c->cd_found = c->cd_newest_n = c->cd_sent = c->cd_skip = 0;
    for (uint32_t i = 0; i < 20u; i++) c->cd_newest[i] = 0;
    if (!cd_arena(&lo, &hi)) { c->cd_state = IX_CD_NO_ARENA; return; }
    c->cd_lo = lo; c->cd_hi = hi;
    c->cd_state = IX_CD_BUSY;
    uint32_t first = (lo + IX_CD_STEP - 1u) & ~(IX_CD_STEP - 1u);
    cd_dng d;
    /* pass 1: the newest DateTime */
    uint32_t have = 0;
    for (uint32_t a = first; a + 8u < hi; a += IX_CD_STEP) {
        if (*(volatile uint32_t *)a != 0x002A4949u || !cd_parse(a, hi, &d)) continue;
        c->cd_found++;
        if (!d.dt) continue;
        if (!have || cd_cmp(d.dt, c->cd_newest) > 0) {
            for (uint32_t i = 0; i < 19u; i++) c->cd_newest[i] = *(volatile uint8_t *)(d.dt + i);
            have = 1;
        }
    }
    /* pass 2: push that take's frames, in arena order */
    for (uint32_t a = first; have && a + 8u < hi; a += IX_CD_STEP) {
        if (*(volatile uint32_t *)a != 0x002A4949u || !cd_parse(a, hi, &d) || !d.dt) continue;
#ifndef IX_MUTANT_CD_ALL
        if (cd_cmp(d.dt, c->cd_newest) != 0) continue;
#endif
        c->cd_newest_n++;
        if (c->cd_max && c->cd_sent >= c->cd_max) continue;
        volatile ix_push_req q;
        q.mode = 1; q.source = 4; q.frame_no = c->cd_newest_n - 1u;
        q.w = d.w; q.h = d.h; q.fmt = 5; q.stride = 0; q.flags = 0;
        q.aux0 = a; q.aux1 = 0; q.nseg = 1;
        q.seg[0].addr = a; q.seg[0].len = d.size;
        q.seg[1].addr = q.seg[1].len = q.seg[2].addr = q.seg[2].len = q.seg[3].addr = q.seg[3].len = 0;
        if (ix_push(w, &q, 2000u) == PX_SENT) c->cd_sent++;
        else c->cd_skip++;
    }
    ix_push_release(w);
    c->cd_us = w->fw.tick_us() - t0;
    c->cd_state = IX_CD_DONE;
}
