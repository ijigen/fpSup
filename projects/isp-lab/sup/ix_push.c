/* ix_push -- the camera side of FPP1 (notes/PUSH_PROTOCOL.md): one image =
 * [256-byte header][segments], pushed out of EP 0x83 from TRBs this engine owns.
 *
 * Firmware facts it rests on (blk_c01.c, FUN_c01e6b80 and its callers):
 *   - StartTransfer(phys) hands the controller [0xC31E3238 + 4*ctx], a DMA
 *     address; [0xC31E3264 + 4*ctx] is the same TRB at its CPU address
 *     (DMA + 0x40000000).  ctx = phys >> 1.
 *   - TRB buffer words are DMA addresses: the firmware writes `cpu - 0x40000000`.
 *   - It returns -2 while [0xC31E38FC] is set (a PTP Cancel/Reset, handover F2).
 * So the engine points ctx 3's two entries at its own chain while it owns the
 * endpoint, and puts the saved ones back in ix_push_release.
 *
 * Mode 0 never waits: the previous chain still owned by the controller (its
 * last TRB's HWO) means this image is skipped and counted.  Mode 1 (a task
 * only) waits for the previous one, sends, and waits for this one, up to
 * timeout_ms each; a transfer that does not finish is ended.
 * Nothing here allocates, sleeps in mode 0, or touches the recording path. */
#include "ix_wr.h"


static volatile uint8_t *px_uc8(volatile void *p) {        /* the uncached alias of our state */
    uint32_t a = (uint32_t)p;
    return (volatile uint8_t *)(a >= 0xC0000000u ? a - 0x80000000u : a);
}
static uint32_t px_dma(volatile void *p) { return (uint32_t)px_uc8(p) - 0x40000000u; }

static uint32_t px_crc32(volatile const uint8_t *b, uint32_t n) {
    uint32_t c = 0xFFFFFFFFu;
    for (uint32_t i = 0; i < n; i++) {
        c ^= b[i];
        for (uint32_t k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u)));
    }
    return ~c;
}

static void px_put32(volatile uint8_t *h, uint32_t off, uint32_t v) {
    h[off] = (uint8_t)v; h[off + 1] = (uint8_t)(v >> 8);
    h[off + 2] = (uint8_t)(v >> 16); h[off + 3] = (uint8_t)(v >> 24);
}

/* 1 while the controller still owns the chain we last started.  A reconfigure of
 * the endpoint (the host reopening the device, a reconnect) drops the transfer
 * and leaves HWO set for good: EP83's last command is then a configure, not our
 * StartTransfer, and the chain is lost -- without this every later push was
 * skipped (validation/20261027-isp-custom-E0-cp: DEPCMD 0x50002, 3173 skips). */
static uint32_t px_busy(wr_t *w) {
    ix_px_t *x = &w->px;
    if (!x->armed) return 0;
    volatile px_trb *t = (volatile px_trb *)px_uc8(&x->trb[x->last_trb]);
    if (t->ctrl & 1u) {
#ifndef IX_MUTANT_NO_LOST_CHECK
        uint32_t cmd = *(volatile uint32_t *)PX_DEPCMD & 0xFu;
        if (cmd == PX_CMD_START || cmd == PX_CMD_UPDATE) return 1;
        x->n_lost++;
#else
        return 1;
#endif
    }
    x->armed = 0;
    return 0;
}

/* Wait for the controller to finish the chain in flight, at most timeout_ms.  On a timeout the transfer is
 * LEFT ARMED: it completes whenever the host reads.  Ending it here (EndTransfer) killed EP83 for the rest
 * of the session when the host was not reading yet (validation/20261027-report-take-01/02); only
 * ix_push_release ends a transfer, and only when the caller knows nobody will read it. */
static uint32_t px_wait_idle(wr_t *w, uint32_t timeout_ms) {
    for (uint32_t ms = 0; px_busy(w); ms++) {
        if (ms >= timeout_ms) {
#ifdef IX_MUTANT_END_ON_TIMEOUT
            w->fw.end_xfer(PX_CTX);
            w->px.armed = 0;
#endif
            w->px.n_timeout++;
            return 0;
        }
        w->fw.dly(1);
    }
    return 1;
}

static void px_take_tables(wr_t *w) {
    ix_px_t *x = &w->px;
    volatile uint32_t *dma = (volatile uint32_t *)(PX_TRB_DMA + 4u * PX_CTX);
    volatile uint32_t *cpu = (volatile uint32_t *)(PX_TRB_CPU + 4u * PX_CTX);
    if (!x->owns) { x->saved_dma = *dma; x->saved_cpu = *cpu; x->owns = 1; }
    uint32_t d = px_dma(&x->trb[0]);
    *dma = d;
    *cpu = d + 0x40000000u;
}

void ix_push_release(wr_t *w) {
    ix_px_t *x = &w->px;
    /* A chain still in flight is left to finish: the host may be about to read it, and ending it killed EP83
     * live. The controller already holds the TRB address; the firmware never uses ctx 3, so putting its
     * table entries back does not touch the transfer, and px_busy() still sees our last TRB. */
    if (x->owns) {
        *(volatile uint32_t *)(PX_TRB_DMA + 4u * PX_CTX) = x->saved_dma;
        *(volatile uint32_t *)(PX_TRB_CPU + 4u * PX_CTX) = x->saved_cpu;
        x->owns = 0;
    }
}

uint32_t ix_push(wr_t *w, const volatile ix_push_req *q, uint32_t timeout_ms) {
    ix_px_t *x = &w->px;
    uint32_t src = q->source & 7u;
    if (q->mode == 0) {
        if (px_busy(w)) { x->n_skip[src]++; x->seq[src]++; return PX_SKIPPED; }   /* a seq gap = a skip */
    } else if (!px_wait_idle(w, timeout_ms)) {
        x->n_skip[src]++; x->seq[src]++;
        return PX_ERR_TIMEOUT;
    }
    uint32_t nseg = q->nseg, total = 0;
    if (nseg < 1u || nseg > PX_MAX_SEG) { x->n_bad++; return PX_ERR_BAD; }
    /* the chain: header, then each segment cut to TRB-sized pieces */
    volatile px_trb *t = (volatile px_trb *)px_uc8(&x->trb[0]);
    uint32_t n = 0;
    t[n].lo = px_dma(x->hdr); t[n].hi = 0; t[n].size = PX_HDR; t[n].ctrl = PX_TRB_MID; n++;
    for (uint32_t i = 0; i < nseg; i++) {
        uint32_t a = q->seg[i].addr, len = q->seg[i].len;
        if (a >= 0xC0000000u) a -= 0x80000000u;                  /* a cached alias: read uncached */
        if (!len || a < 0x40000000u || a >= 0x80000000u || len > 0x80000000u - a) { x->n_bad++; return PX_ERR_BAD; }
        total += len;
        while (len) {
            uint32_t k = len > PX_TRB_MAX_LEN ? PX_TRB_MAX_LEN : len;
            if (n >= PX_MAX_TRB) { x->n_bad++; return PX_ERR_BAD; }
            t[n].lo = a - 0x40000000u; t[n].hi = 0; t[n].size = k; t[n].ctrl = PX_TRB_MID;
            n++; a += k; len -= k;
        }
    }
    /* the header (FPP1 v1): every byte written, then the CRC over it with its field 0 */
    volatile uint8_t *h = px_uc8(x->hdr);
    for (uint32_t i = 0; i < PX_HDR; i++) h[i] = 0;
    px_put32(h, 0x00, PX_MAGIC);
    px_put32(h, 0x04, PX_HDR);
    px_put32(h, 0x08, q->source);
    px_put32(h, 0x0C, x->seq[src]);
    px_put32(h, 0x10, w->fw.tick_us());
    px_put32(h, 0x14, q->frame_no);
    px_put32(h, 0x18, nseg);
    px_put32(h, 0x1C, total);
    px_put32(h, 0x20, (q->w & 0xFFFFu) | (q->h << 16));
    px_put32(h, 0x24, q->fmt);
    px_put32(h, 0x28, q->stride);
    px_put32(h, 0x2C, q->flags);
    px_put32(h, 0x30, x->n_skip[src]);
    px_put32(h, 0x34, q->aux0);
    px_put32(h, 0x38, q->aux1);
    for (uint32_t i = 0; i < nseg; i++) px_put32(h, 0x40 + 4u * i, q->seg[i].len);
#ifndef IX_MUTANT_NO_CRC
    px_put32(h, 0x3C, px_crc32(h, PX_HDR));
#endif
    t[n - 1].ctrl = PX_TRB_LAST;
    __asm__ volatile("dsb" ::: "memory");
    px_take_tables(w);
    int rc = w->fw.start_xfer(PX_PHYS);
    x->last_rc = (uint32_t)rc;
    if (rc) {
        if (*(volatile uint32_t *)PX_DEAF) x->n_deaf++;
        x->n_start_err++;
        x->n_skip[src]++; x->seq[src]++;
        return PX_ERR_START;
    }
    x->armed = 1;
    x->last_trb = n - 1;
    x->seq[src]++;
    x->n_sent++;
    x->bytes += total;
    if (q->mode != 0 && !px_wait_idle(w, timeout_ms)) {
        /* StartTransfer acceptance is not delivery. In particular, the CDNG
         * caller must not count an ended, uncompleted transfer as cd_sent. */
        x->n_skip[src]++;
        return PX_ERR_TIMEOUT;
    }
    return PX_SENT;
}
