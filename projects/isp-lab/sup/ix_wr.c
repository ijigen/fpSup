/* ISPL fork of projects/imx410-lab/sup/ix_wr.c (IMXL, sha256 1e9a056b...):
 * see ix_wr.h.  Changes: the keep policy and block log in ix_sink, ix_ctl_*.
 *
 * IMXL fork of rec-core/writer/wr.c (ULWR, sha256 2e83816d...): see ix_wr.h.
 * Changes: wr_init stamps the sink, wr_service writes through ix_sink. */
#include "ix_wr.h"

#ifdef WR_HOST                                   /* test_wr.py: a fake 32-bit space */
volatile uint32_t *wr_host_mem(uint32_t a);
#define RD(a)     (*wr_host_mem(a))
#define WRW(a, v) (*wr_host_mem(a) = (uint32_t)(v))
#define TOKEN(b)  ((uint32_t)((uintptr_t)(b) | 1u))   /* only ever tested for 0 */
#define WORDS(a)  ((const uint32_t *)wr_host_mem(a))
#define RD8(a)    ((RD((a) & ~3u) >> (((a) & 3u) * 8u)) & 0xFFu)
#else
#define RD8(a)    (*(volatile uint8_t *)(uintptr_t)(a))
#define RD(a)     (*(volatile uint32_t *)(uintptr_t)(a))
#define WRW(a, v) (*(volatile uint32_t *)(uintptr_t)(a) = (uint32_t)(v))
#define TOKEN(b)  ((uint32_t)(uintptr_t)(b))
#define WORDS(a)  ((const uint32_t *)(uintptr_t)(a))
#endif

static const uint32_t SLOT[6] = { V_CB, V_ACQ, V_ADD, V_CKPT, V_RB, V_REL };

static uint32_t lock(wr_t *w) { return w->fw.irq_off(); }
static void unlock(wr_t *w, uint32_t s) { w->fw.irq_restore(s); }

void wr_init(wr_t *w, const wr_fw *fw, int flag, const uint32_t veneer[6],
             uint32_t block_bytes, uint32_t maxdesc_at) {
    uint8_t *p = (uint8_t *)w;
    for (uint32_t i = 0; i < sizeof *w; i++) p[i] = 0;
    w->magic = WR_MAGIC;
    w->fw = *fw;
    w->flag = flag;
    for (int i = 0; i < 6; i++) w->veneer[i] = veneer[i];
    w->block_bytes = block_bytes;
    w->maxdesc_at = maxdesc_at;
    w->cur = BQ_BLOCKS;
    w->cap.magic = IX_CAP_MAGIC;
    w->cap.version = IX_CAP_VERSION;
}

static uint32_t shift_of(uint32_t v) {           /* v is a power of two        */
    uint32_t s = 0;
    while (s < 31 && (1u << s) != v) s++;
    return (1u << s) == v ? s : 32;
}

/* stock C063F220 returned 1: the vol holds the driver arena, threshold set */
void wr_installed(wr_t *w, uint32_t vol) {
    if (w->vol || !vol || !RD(vol + V_THRESH) || !RD(vol + V_ARENA)) { w->n_refuse++; return; }
    uint32_t acq = RD(vol + V_ACQ);
    bq_limits lim = { 0x400u, 0, 0 };
    if (acq == WR_SD_ACQ) {
        lim.max_heads = 0x100u;
        lim.max_desc = w->maxdesc_at ? RD(w->maxdesc_at) : 0x10000u;
        if (!lim.max_desc) { w->n_refuse++; return; }
    } else if (acq != WR_SSD_ACQ) {
        w->n_refuse++;                           /* a driver we have not read  */
        return;
    }
    uint32_t ss = RD(vol + V_SECTOR), cluster = RD(vol + V_SPC) * ss;
    w->sector_shift = shift_of(ss);
    if (w->sector_shift < 9 || w->sector_shift > 12 || shift_of(cluster) > 25) {
        w->n_refuse++;                           /* exFAT: both powers of two  */
        return;
    }
    for (int i = 0; i < 6; i++) w->saved[i] = RD(vol + SLOT[i]);
#ifndef WR_HOST                                  /* the host fixture supplies them */
    w->fw.drv_acquire = (uint32_t (*)(void))(uintptr_t)w->saved[1];
    w->fw.drv_add = (int (*)(uint32_t, uint32_t))(uintptr_t)w->saved[2];
    w->fw.drv_release = (void (*)(void))(uintptr_t)w->saved[5];
    w->fw.stock_cb = (void (*)(uint32_t, uint32_t))(uintptr_t)w->saved[0];
#endif
    w->fw.drv_release();                         /* our writer acquires per chunk */
    uint32_t s = lock(w);
    bq_init(&w->q, &lim);
    bq_block *b = bq_open(&w->q);
    unlock(w, s);
    if (w->block_bytes) {                        /* stock rounds up to a cluster too */
        WRW(vol + V_THRESH, (w->block_bytes + cluster - 1) & ~(cluster - 1));
    }
    for (int i = 0; i < 6; i++) WRW(vol + SLOT[i], w->veneer[i]);
    WRW(vol + V_ARENA, TOKEN(b));
    w->vol = w->wvol = vol;
    w->n_install++;
}

static void restore(wr_t *w) {
    uint32_t vol = w->vol;
    for (int i = 0; i < 6; i++) WRW(vol + SLOT[i], w->saved[i]);
    WRW(vol + V_ARENA, 0);                       /* C063F310 then skips release */
    w->vol = 0;
    w->ended_vol = vol;
}

void wr_take_start(wr_t *w) { w->ended_vol = 0; }

/* The stop task can run C063F310 between C03A5348 marking a frame 0xC and that
 * frame's write: C069ADE0 opens, writes and closes under three separate holds
 * of the FS lock, so a stop queued on the lock while SRecFile blocked gets it
 * at the open's release.  The write then finds +0x4828 == 0 and C063F380
 * (F816) skips the cookie, while C03A5348 (mgr+0xD != 0) waits for one: the
 * frame never completes.  Such a frame was written synchronously, as with
 * aggregation off, so let stock take its own aggregation-off branch.  Any frame
 * that did reach the vol was completed (0xD) by the drain before the restore. */
int wr_late_frame(wr_t *w, uint32_t mgr, uint32_t node) {
#ifdef WR_MUTANT_NO_LATE
    return 0;
#endif
    uint32_t vol = w->ended_vol;
    if (!vol || !mgr || !node) return 0;
    if (!RD8(mgr + M_AGGREGATE) || RD(node + N_STATE) != N_HANDED || RD(vol + V_THRESH)) return 0;
    w->n_late_frame++;
    return 1;
}

static void wait_bits(wr_t *w, uint32_t bits) {
    uint32_t got;
    w->fw.flg_wait(w->flag, bits, TWF_ORW_BITCLR, &got, 1000);
}

/* C063F140(vol), called with the FS lock held */
int wr_send(wr_t *w, uint32_t vol, uint32_t lr) {
    if (!w->vol || vol != w->vol) { w->n_stock_send++; return 1; }
    if (!RD(vol + V_ARENA)) return 0;            /* stock: nothing to do        */
    uint32_t n = RD(vol + V_NCOOKIE);
    if (n > BQ_MAX_COOKIE) n = BQ_MAX_COOKIE;
    uint32_t s = lock(w);
    int r = bq_seal(&w->q, RD(vol + V_CL), RD(vol + V_BYTES),
                    WORDS(vol + V_COOKIES), n);
    unlock(w, s);
    if (r == BQ_MISMATCH) w->n_mismatch++;
    if (r == BQ_STATE) {                         /* no open block: cannot happen; */
        const uint32_t *ck = WORDS(vol + V_COOKIES);
        w->n_mismatch++;                         /* never strand a frame          */
        for (uint32_t i = 0; i < n; i++) w->fw.stock_cb(ck[i], (uint32_t)-4);
    }
    w->n_send++;
    WRW(vol + V_NCOOKIE, 0);
    WRW(vol + V_CL, 0);
    WRW(vol + V_BYTES, 0);
    w->fw.flg_set(w->flag, WR_F_WORK);
    if (lr == WR_LR_STOP) {                      /* C063F310: all written on return */
        uint32_t tries = 0;
#ifdef WR_MUTANT_NO_DRAIN
        tries = 1000;
#endif
        for (;;) {
            s = lock(w);
            int idle = bq_idle(&w->q);
            unlock(w, s);
            if (idle) break;
            if (++tries > 30) { if (tries < 1000) w->n_drain_timeout++; break; }
            wait_bits(w, WR_F_IDLE);
        }
        w->n_drain++;
        restore(w);
        return 0;
    }
    bq_block *b;
    for (;;) {
        s = lock(w);
        b = bq_open(&w->q);
        unlock(w, s);
        if (b) break;
        w->n_wait_free++;                        /* the writer needs no FS lock */
        wait_bits(w, WR_F_FREE);
    }
    WRW(vol + V_ARENA, TOKEN(b));
    return 0;
}

/* +0x4834 while installed: only C063F380's "4A58 == 0" path calls it */
void wr_cb_cookie(wr_t *w, uint32_t frame, uint32_t status) {
    w->n_late++;
    uint32_t st = 0;
    for (;;) {
        uint32_t s = lock(w);
        int r = bq_late_cookie(&w->q, frame, &st);
        unlock(w, s);
        if (r == BQ_OK) return;
        if (r == BQ_NONE) break;
        w->n_late_full++;                        /* wait until it drains        */
        wait_bits(w, WR_F_IDLE);
    }
    w->n_late_direct++;
    w->fw.stock_cb(frame, status ? status : st);
}

uint32_t wr_cb_acquire(wr_t *w) {
    for (;;) {
        uint32_t s = lock(w);
        bq_block *b = bq_open(&w->q);
        unlock(w, s);
        if (b) return TOKEN(b);    /* never 0: 0 degrades the take */
        w->n_wait_free++;
        wait_bits(w, WR_F_FREE);
    }
}

int wr_cb_add(wr_t *w, uint32_t addr, uint32_t len) {
    uint32_t s = lock(w);
    int r = bq_add(&w->q, addr, len);
    unlock(w, s);
    return r < 0 ? -1 : 0;
}

void wr_cb_ckpt(wr_t *w)     { uint32_t s = lock(w); bq_checkpoint(&w->q); unlock(w, s); }
void wr_cb_rollback(wr_t *w) { uint32_t s = lock(w); bq_rollback(&w->q); unlock(w, s); }
void wr_cb_release(wr_t *w)  { (void)w; }        /* blocks come back via the writer */

/* ---------------------------------------------------------------- writer */

static uint32_t write_block(wr_t *w, uint32_t vol, bq_block *b) {
    uint32_t from = 0, sent = 0, bytes;
    int n;
    uint32_t spc = RD(vol + V_SPC), heap = RD(vol + V_HEAP_LBA), dev = RD(vol + V_DEV);
    uint64_t base = (uint64_t)(b->cl - 2) * spc + heap;
    while ((n = bq_chunk(&w->q, b, &from, &bytes)) > 0) {
        uint32_t arena, tries = 0;
        while (!(arena = w->fw.drv_acquire())) { /* another user of the one table */
            w->n_acq_retry++;
            if (++tries > 2000) return (uint32_t)-5;
            w->fw.dly(1);
        }
        int ok = 1;
        for (uint32_t i = from - (uint32_t)n; i < from; i++)
            if (w->fw.drv_add(b->seg[i].addr, b->seg[i].len) < 0) { ok = 0; break; }
        int r = 0;
        if (ok) {
            uint64_t lba = base + (sent >> w->sector_shift);
            r = w->fw.dev_write(dev, (uint32_t)lba, (uint32_t)(lba >> 32), bytes >> w->sector_shift, arena);
        }
        w->fw.drv_release();
        w->n_chunk++;
        if (!ok) return (uint32_t)-4;
        if (r != 1) { w->n_dev_err++; return (uint32_t)(r < 0 ? r : -1); }
        sent += bytes;
    }
    if (n < 0) return (uint32_t)n;
    return 0;
}


/* ---------------------------------------------------------------- sink */

#ifdef WR_HOST
#error "the sink runs only on the card build (test_card.py)"
#endif

/* Frame bytes are read through the uncached alias: the SD driver hands the
 * same addresses to its DMA without touching the cache, so whoever produced
 * them has already cleaned them to memory. */
static uint32_t ix_src(uint32_t a) {
#ifdef IX_MUTANT_NO_UNCACHE
    return a;
#endif
    return a >= 0xC0000000u ? a - 0x80000000u : a;
}

static void ix_copy(uint32_t dst, uint32_t src, uint32_t n) {
    while (n && (dst & 3u)) { *(volatile uint8_t *)dst++ = *(const volatile uint8_t *)src++; n--; }
    if (!(src & 3u)) {
        uint32_t *d = (uint32_t *)dst;
        const uint32_t *s = (const uint32_t *)src;
        while (n >= 32u) {
            uint32_t a = s[0], b = s[1], c = s[2], e = s[3], f = s[4], g = s[5], h = s[6], i = s[7];
            d[0] = a; d[1] = b; d[2] = c; d[3] = e; d[4] = f; d[5] = g; d[6] = h; d[7] = i;
            d += 8; s += 8; n -= 32u;
        }
        while (n >= 4u) { *d++ = *s++; n -= 4u; }
        dst = (uint32_t)d;
        src = (uint32_t)s;
    }
    while (n--) *(volatile uint8_t *)dst++ = *(const volatile uint8_t *)src++;
}

/* Lent memory only: the uncached alias, below the firmware image. */
static uint32_t ix_room(const ix_cap *c) {
    if (c->nchunk > IX_MAX_CHUNK || c->ci > c->nchunk) return 0;
    uint32_t total = 0;
    for (uint32_t i = 0; i < c->nchunk; i++) {
        const ix_chunk *k = &c->chunk[i];
        /* addr >= 0xC0000000 first: the subtraction below would wrap and pass
         * (IMXL's check did; its test only failed because the chunk was small) */
#ifndef IX_MUTANT_WRAP
        if (k->addr >= 0xC0000000u) return 0;
#endif
        if (k->addr < 0x40000000u || k->len > 0xC0000000u - k->addr) return 0;
        if (i > c->ci) total += k->len;
        else if (i == c->ci) { if (c->coff > k->len) return 0; total += k->len - c->coff; }
    }
    return total;
}

/* `n` bytes from `src` at the cursor (src == 0: leave them as they are). */
static void ix_put(ix_cap *c, uint32_t src, uint32_t n) {
    while (n) {
        const ix_chunk *k = &c->chunk[c->ci];
        uint32_t room = k->len - c->coff;
        if (!room) { c->ci++; c->coff = 0; continue; }
        uint32_t m = n < room ? n : room;
        if (src) { ix_copy(k->addr + c->coff, src, m); src += m; }
        c->coff += m;
        n -= m;
    }
}

static uint32_t ix_capture(wr_t *w, bq_block *b) {
    ix_cap *c = &w->cap;
    uint32_t data = (b->bytes + 3u) & ~3u;
#ifndef IX_MUTANT_NO_ROOM
    if (data < b->bytes || ix_room(c) < data + sizeof(ix_rec)) { c->n_full++; return 0; }
#endif
    uint32_t t0 = w->fw.tick_us();
    uint32_t hci = c->ci, hoff = c->coff;
    ix_put(c, 0, sizeof(ix_rec));               /* the header goes in last  */
    for (uint32_t i = 0; i < b->nseg; i++) ix_put(c, ix_src(b->seg[i].addr), b->seg[i].len);
    ix_put(c, 0, data - b->bytes);
    uint32_t dt = w->fw.tick_us() - t0;
    ix_rec r;
    r.magic = IX_REC_MAGIC; r.seq = b->seq; r.cl = b->cl; r.bytes = b->bytes;
    r.ncookie = b->ncookie; r.t_us = t0; r.copy_us = dt; r.nseg = b->nseg;
    uint32_t eci = c->ci, eoff = c->coff;
    c->ci = hci; c->coff = hoff;
    ix_put(c, (uint32_t)&r, sizeof r);
    c->ci = eci; c->coff = eoff;
    c->used += data + sizeof(ix_rec);
    if (!c->n_rec) c->t_first = t0;
    c->t_last = t0;
    c->n_rec++;
    c->copy_us += dt;
    if (dt > c->copy_max_us) c->copy_max_us = dt;
    return 0;
}

/* Lent memory for the log: the same rule as the chunks. */
static void ix_log(wr_t *w, bq_block *b) {
    ix_cap *c = &w->cap;
    if (!c->log_addr || c->log_n >= c->log_max) return;
    if (c->log_addr < 0x40000000u || c->log_addr >= 0xC0000000u ||
        c->log_max > (0xC0000000u - c->log_addr) / sizeof(ix_logline)) return;
    volatile uint32_t *l = (volatile uint32_t *)(c->log_addr + c->log_n * sizeof(ix_logline));
    l[0] = b->seq; l[1] = w->fw.tick_us(); l[2] = b->ncookie; l[3] = b->bytes;
    c->log_n++;
}

/* The first keep_first blocks, then the first block at least every_us after
 * the last one kept.  Counted in blocks the policy saw, not records stored:
 * a full sink must not turn into "keep everything" (n_rec stops growing). */
static int ix_keep(wr_t *w) {
    ix_cap *c = &w->cap;
#ifdef IX_MUTANT_KEEP_ALL
    return 1;
#endif
    if (c->n_rec + c->n_full < c->keep_first) return 1;
    return c->every_us && w->fw.tick_us() - c->t_last >= c->every_us;
}

static uint32_t ix_sink(wr_t *w, uint32_t vol, bq_block *b) {
    uint32_t mode = w->cap.mode;
#ifdef IX_MUTANT_ALWAYS_SD
    mode = IX_SD;
#endif
    ix_log(w, b);
    if (mode == IX_CAPTURE) {
        if (ix_keep(w)) return ix_capture(w, b);
        w->cap.n_skip++;
        return 0;
    }
    if (mode == IX_SD) { w->cap.n_sd++; return write_block(w, vol, b); }
    w->cap.n_discard++;                          /* IX_DISCARD and anything else */
    return 0;
}

void wr_service(wr_t *w) {
    for (;;) {
        uint32_t s = lock(w);
        bq_block *b = bq_take(&w->q);
        uint32_t vol = w->wvol;                  /* survives a drain timeout     */
        unlock(w, s);
        if (!b) break;
        uint32_t st = b->skip ? 0 : ix_sink(w, vol, b);
        w->last_status = st;
        s = lock(w);
        bq_complete_begin(&w->q, b, st);
        unlock(w, s);
        w->fw.flg_set(w->flag, WR_F_FREE);
        uint32_t c, cs;
        for (;;) {
            s = lock(w);
            int got = bq_complete_next(&w->q, &c, &cs);
            unlock(w, s);
            if (!got) break;
            w->fw.stock_cb(c, cs);                   /* C03A55D0, outside any lock */
        }
    }
    uint32_t s = lock(w);
    int idle = bq_idle(&w->q);
    unlock(w, s);
    if (idle) w->fw.flg_set(w->flag, WR_F_IDLE);
}

void wr_task(wr_t *w) {
    for (;;) {
        uint32_t got;
        w->fw.flg_wait(w->flag, WR_F_WORK, TWF_ORW_BITCLR, &got, -1);
        wr_service(w);
    }
}


/* ---------------------------------------------------------------- control */

/* One line through the stock shell executor, as FUN_c0405ba0 (the firmware's
 * own "record N movies" script) does: no .rodata in a sup, so word stores. */
enum { IX_SH_ENA = 1, IX_SH_INIT, IX_SH_MOVON, IX_SH_RECWAI, IX_SH_SAVEWAI, IX_SH_DISA,
       IX_SH_S1ON, IX_SH_S1OFF, IX_SH_OKON, IX_SH_OKOFF, IX_SH_USBOFF, IX_SH_USBON };
static void ix_sh(wr_t *w, uint32_t id) {
    volatile uint32_t b[6];
    b[0] = b[1] = b[2] = b[3] = b[4] = b[5] = 0;
    switch (id) {
    case IX_SH_ENA: b[0] = 0x73636572u; b[1] = 0x65746174u; b[2] = 0x616E6520u; b[3] = 0x00000000u; break;   /* "recstate ena" */
    case IX_SH_INIT: b[0] = 0x73636572u; b[1] = 0x65746174u; b[2] = 0x696E6920u; b[3] = 0x00000074u; break;   /* "recstate init" */
    case IX_SH_MOVON: b[0] = 0x2079656Bu; b[1] = 0x4F564F4Du; b[2] = 0x0000004Eu; break;   /* "key MOVON" */
    case IX_SH_RECWAI: b[0] = 0x73636572u; b[1] = 0x65746174u; b[2] = 0x766F6D20u; b[3] = 0x73636572u; b[4] = 0x69617774u; b[5] = 0x00000000u; break;   /* "recstate movrecstwai" */
    case IX_SH_SAVEWAI: b[0] = 0x73636572u; b[1] = 0x65746174u; b[2] = 0x766F6D20u; b[3] = 0x65766173u; b[4] = 0x00696177u; break;   /* "recstate movsavewai" */
    case IX_SH_DISA: b[0] = 0x73636572u; b[1] = 0x65746174u; b[2] = 0x73696420u; b[3] = 0x00000061u; break;   /* "recstate disa" */
    case IX_SH_S1ON: b[0] = 0x2079656Bu; b[1] = 0x4E4F3153u; break;   /* "key S1ON" */
    case IX_SH_S1OFF: b[0] = 0x2079656Bu; b[1] = 0x464F3153u; b[2] = 0x00000046u; break;   /* "key S1OFF" */
    case IX_SH_OKON: b[0] = 0x2079656Bu; b[1] = 0x4E4F4B4Fu; break;   /* "key OKON" */
    case IX_SH_OKOFF: b[0] = 0x2079656Bu; b[1] = 0x464F4B4Fu; b[2] = 0x00000046u; break;   /* "key OKOFF" */
    case IX_SH_USBOFF: b[0] = 0x20627375u; b[1] = 0x0066666Fu; break;   /* "usb off" */
    case IX_SH_USBON: b[0] = 0x20627375u; b[1] = 0x00006E6Fu; break;   /* "usb on" */
    default: return;
    }
    w->cap.ctl_line = id;                       /* the last line started: a hang shows here */
    w->fw.shell_exec(w->fw.shell_ctx, (char *)b);
    if (id == IX_SH_DISA) {
        /* fp 5.02 C0407948 unregisters ShellRecOb but leaves its +4 byte
         * set. The next C0407908 then skips registration, so a second take
         * records without receiving started/saved notifications. Only after
         * OUR disa returned, make that byte match the completed unregister. */
        *(volatile uint8_t *)(w->fw.recstate + 4u) = 0;
    }
    if (id == IX_SH_MOVON) w->cap.n_press++;
}

/* recstate's observer (ShellRecOb, 0xC3757F30): +6 movie recording started,
 * +7 movie saved.  "recstate init" clears them, movrecstwai / movsavewai poll
 * them every 100 ms for up to 60 s (FUN_c0407ab8). */
#define RS_STARTED 6u
#define RS_SAVED   7u
static uint32_t ix_rs(wr_t *w, uint32_t off) { return *(volatile uint8_t *)(w->fw.recstate + off); }

/* The display DMA channel's slot register (FUN_c01822b8's table, channels 0..8),
 * raw.  Measured 10-24 (validation/20261024-lvslot-01): byte2 = the slot being
 * written, byte1 = the last one finished (always byte2 - 1), byte0 = the slot on
 * screen (the firmware's & 0x1F/& 7, flips from byte1 to byte2). */
static uint32_t ix_lv_reg(uint32_t ch) {
    switch (ch) {
    case 0: return *(volatile uint32_t *)0x301821E8u;
    case 1: return *(volatile uint32_t *)0x301822E8u;
    case 2: return *(volatile uint32_t *)0x301832E8u;
    case 3: return *(volatile uint32_t *)0x301833E8u;
    case 4: return *(volatile uint32_t *)0x301834E8u;
    case 5: return *(volatile uint32_t *)0x301835E8u;
    case 6: return *(volatile uint32_t *)0x301836E8u;
    case 7: return *(volatile uint32_t *)0x301823E8u;
    default: return *(volatile uint32_t *)0x301837E8u;
    }
}

/* The display watch words now: into the standby or the recording copy, and into `out`. */
static void ix_wt_sample(ix_cap *c, uint32_t *out) {
    static const uint32_t wt[IX_WT_N] = IX_WT_ADDRS;
    int rec = c->ctl == IX_CTL_REC;
    uint32_t *dst = rec ? c->wt_rec : c->wt_sby;
    for (uint32_t i = 0; i < IX_WT_N; i++) dst[i] = out[i] = *(volatile uint32_t *)wt[i];
    if (rec) c->wt_n_rec++; else c->wt_n_sby++;
}

/* The burst window (layout 10): from our start MOVON until lv_burst_ms after recstate +6 was seen. */
static int ix_bu_on(const ix_cap *c, uint32_t now) {
#ifndef IX_MUTANT_BU_ALWAYS
    if (!c->lv_burst_ms) return 0;
#endif
    if (c->ctl == IX_CTL_STARTING) return 1;
#ifdef IX_MUTANT_BU_NO_END
    return c->ctl == IX_CTL_REC;
#endif
    return c->ctl == IX_CTL_REC && now - c->t_rec < c->lv_burst_ms * 1000u;
}

/* One LV sample, at most every lv_every_us -- or, inside the burst window, one per newly finished ring slot
 * (the slot changed since the last burst push; time does not matter).  Never waits: the engine's mode 0 skips
 * when the previous push has not finished, and a skipped slot is still new at the next step.  A whole ring
 * wrap between two steps (n frames, 67 ms at 60 fps with 4 slots) looks like no new frame. */
static void ix_lv_step(wr_t *w, uint32_t now) {
    ix_cap *c = &w->cap;
    int burst = ix_bu_on(c, now);
    if (!c->lv_push || !(c->lv_every_us || burst)) return;
#ifndef IX_MUTANT_LV_ALWAYS
    /* Only while a take is armed, starting or recording.  After it the sampler wrote lv_t_last into the line
     * the host's next arm rewrites, and the host's cache clean then put the sup's stale lv_push back over its 0
     * (10-27 night1e-d10 / night2 z1536: "readback differs from offset 392"). */
    if (c->ctl != IX_CTL_ARMED && c->ctl != IX_CTL_STARTING && c->ctl != IX_CTL_REC) return;
#endif
    if (c->lv_max && c->lv_n_sent >= c->lv_max) return;
    uint32_t wv[IX_WT_N];
    if (!burst) {
        if (c->lv_t_last && now - c->lv_t_last < c->lv_every_us) return;
        c->lv_t_last = now;                     /* 0 = never: costs one early push per 71 min */
        ix_wt_sample(c, wv);
    }
    volatile uint32_t *d = (volatile uint32_t *)IX_LV_DESC;
    uint32_t wd = d[3], ht = d[4], n = d[8];
    uint32_t ch = *(volatile uint32_t *)IX_LV_CHSEL + 2u;
    if (ch >= 7u) ch = 8u;
    uint32_t reg = ix_lv_reg(ch);
    c->lv_last_reg = reg;
    if (n < 1u || n > IX_LV_MAX_N || wd < 16u || wd > 4096u || ht < 16u || ht > 4096u ||
        wd * ht * 2u > IX_LV_MAX_BYTES) { c->lv_n_bad++; return; }
    uint32_t lag = c->lv_lag ? c->lv_lag : 1u;
    uint32_t done = (reg >> 8) & 0xFFu;          /* the last slot finished */
#ifdef IX_MUTANT_LV_CURRENT
    done = (reg >> 16) & 0xFFu;                  /* the one being written */
#endif
    if (lag > n || done >= n) { c->lv_n_bad++; return; }
    uint32_t slot = done + n - (lag - 1u);       /* lag 1 = the last finished */
    if (slot >= n) slot -= n;
    uint32_t h = d[9u + slot];
    uint32_t addr = 0x40000000u + 4u * h;
    if (!h || addr < 0x40000000u || addr + wd * ht * 2u > 0x80000000u) { c->lv_n_bad++; return; }
    if (burst) {
#ifndef IX_MUTANT_BU_NO_DEDUPE
        if (slot == c->bu_last) return;          /* nothing finished since the last burst push */
#endif
        c->lv_t_last = now;                      /* the cadence goes on from here after the window */
        ix_wt_sample(c, wv);
    }
    uint32_t flags = (c->ctl == IX_CTL_REC ? 1u : 0u) | (c->cp_phase == IX_CP_FOCUS ? 2u : 0u) |
                     (c->cp_phase == IX_CP_MAG ? 4u : 0u) | (burst ? IX_LV_F_BURST : 0u) |
                     (c->ctl == IX_CTL_STARTING ? IX_LV_F_STARTING : 0u);
    volatile ix_push_req q;
    q.mode = 0; q.source = 1; q.frame_no = slot; q.w = wd; q.h = ht;
    q.fmt = 1; q.stride = wd * 2u;
    q.flags = flags;
    /* a burst push carries the bu entry's join keys: its tick_us and index (the raw register is in the entry) */
    q.aux0 = burst ? now : reg; q.aux1 = burst ? c->bu_sent : ch; q.nseg = 1;
#ifdef IX_MUTANT_BU_AUX
    q.aux0 = reg;
#endif
    q.seg[0].addr = addr; q.seg[0].len = wd * ht * 2u;
    q.seg[1].addr = q.seg[1].len = q.seg[2].addr = q.seg[2].len = q.seg[3].addr = q.seg[3].len = 0;
    c->lv_last_addr = addr;
    uint32_t r = c->lv_push == IX_LV_ENGINE
        ? ix_push(w, &q, 0)                                    /* this sup's own engine, mode 0 */
        : ((uint32_t (*)(volatile ix_push_req *))c->lv_push)(&q);
    if (r == IX_PUSH_SENT) c->lv_n_sent++;
    else if (r == IX_PUSH_SKIPPED) c->lv_n_skip++;
    else c->lv_n_err++;
    if (!burst) return;
    if (r != IX_PUSH_SENT) {                     /* not sent: the slot stays new for the next step */
        if (r == IX_PUSH_SKIPPED) c->bu_skip++; else c->bu_err++;
        return;
    }
    c->bu_last = slot;
    if (c->bu_n < IX_BU_N) {
        ix_burst *e = &c->bu[c->bu_n++];
        e->tick_us = now; e->slot = slot; e->flags = flags; e->reg = reg;
#ifndef IX_MUTANT_BU_NO_WT
        for (uint32_t i = 0; i < IX_WT_N; i++) e->wt[i] = wv[i];
#endif
    }
    c->bu_sent++;
}

typedef char ix_rp_fits[(sizeof(ix_cap) <= IX_RP_BUF) ? 1 : -1];

/* Push a snapshot of the whole ix_cap as FPP1 source 5.  The copy goes through the uncached alias, so the
 * controller reads exactly what the task saw without a cache flush.  Events wait briefly (mode 1); the
 * heartbeat never waits (mode 0). */
static void ix_report(wr_t *w, uint32_t ev, uint32_t mode) {
    ix_cap *c = &w->cap;
    if (!(ev == IX_EV_HEARTBEAT ? c->rp_every_us : c->rp_on)) return;
    c->rp_last_ev = ev;
    volatile uint8_t *dst = px_uc8(w->rp_buf);
    const uint8_t *src = (const uint8_t *)c;
    for (uint32_t i = 0; i < sizeof(ix_cap); i++) dst[i] = src[i];
    volatile ix_push_req q;
    q.mode = mode; q.source = IX_RP_SOURCE; q.frame_no = ev; q.w = IX_CAP_VERSION; q.h = sizeof(ix_cap);
    q.fmt = IX_RP_FMT; q.stride = 0; q.flags = c->ctl == IX_CTL_REC ? 1u : 0u; q.aux0 = ev; q.aux1 = c->ctl;
    q.nseg = 1; q.seg[0].addr = (uint32_t)dst; q.seg[0].len = sizeof(ix_cap);
    q.seg[1].addr = q.seg[1].len = q.seg[2].addr = q.seg[2].len = q.seg[3].addr = q.seg[3].len = 0;
    if (ix_push(w, &q, 500u) == PX_SENT) c->rp_n_sent++;
    else c->rp_n_skip++;
}

/* The checkpoints before the take, one phase per call; leaves cp_phase = IX_CP_DONE when all are through. */
static void ix_cp_step(wr_t *w, uint32_t now) {
    ix_cap *c = &w->cap;
    uint32_t el = now - c->cp_t;
    switch (c->cp_phase) {
    case IX_CP_STANDBY:
        if (now - c->t_arm < c->cp_standby_ms * 1000u) return;
        if (c->cp_focus_ms) { ix_sh(w, IX_SH_S1ON); c->cp_phase = IX_CP_FOCUS; c->cp_t = now; return; }
        goto magnify;
    case IX_CP_FOCUS:
        if (el < c->cp_focus_ms * 1000u) return;
#ifndef IX_MUTANT_NO_S1OFF
        ix_sh(w, IX_SH_S1OFF);
#endif
    magnify:
        if (c->cp_mag_ms) { ix_sh(w, IX_SH_OKON); ix_sh(w, IX_SH_OKOFF); c->cp_phase = IX_CP_MAG; c->cp_t = now; }
        else c->cp_phase = IX_CP_DONE;
        return;
    case IX_CP_MAG:
        if (el < c->cp_mag_ms * 1000u) return;
        ix_sh(w, IX_SH_OKON); ix_sh(w, IX_SH_OKOFF);          /* the centre button toggles magnify back off */
        c->cp_phase = IX_CP_SETTLE; c->cp_t = now;
        return;
    case IX_CP_SETTLE:
        if (el >= IX_CP_SETTLE_MS * 1000u) c->cp_phase = IX_CP_DONE;
        return;
    default:
        return;
    }
}

/* The stock "usb off" / "usb on" (FUN_c0419028 -> FUN_c002c420(obj, 0/1): an
 * asynchronous connect-state request to the USB task), once, so the host
 * enumerates again with the patched descriptor and nobody has to replug. */
static void ix_ur_step(wr_t *w, uint32_t now) {
    ix_cap *c = &w->cap;
    if (c->ur_state >= IX_UR_DONE) return;
    if (!c->ur_t0) { c->ur_t0 = now | 1u; return; }
    if (c->ur_state == IX_UR_WAIT) {
        uint32_t el = now - c->ur_t0;
        if (el < IX_UR_AFTER_MS * 1000u || c->ctl != IX_CTL_IDLE) return;
#ifndef IX_MUTANT_UR_NO_FIX_CHECK
        if (*(volatile uint32_t *)IX_USBFIX_AT != IX_USBFIX_WORD) {
            if (el >= IX_UR_GIVEUP_MS * 1000u) c->ur_state = IX_UR_NOFIX;
            return;
        }
#endif
        ix_sh(w, IX_SH_USBOFF);
        c->ur_state = IX_UR_OFF; c->ur_t = now;
        return;
    }
    if (now - c->ur_t < IX_UR_OFF_MS * 1000u) return;
    ix_sh(w, IX_SH_USBON);
    c->ur_state = IX_UR_DONE;
}

/* The sensor's real frame rate during the take: each change of the receiver counter is a frame edge seen within
 * one control step; the first and last edges bound fc_frames frame periods. */
static void ix_fc_step(ix_cap *c, uint32_t now) {
    if (c->ctl != IX_CTL_REC) return;
    volatile uint32_t *r = (volatile uint32_t *)IX_FC_REG;
    uint32_t v = *r & 0x7FFu, v2 = *r & 0x7FFu;
    if (v != v2) return;                         /* read in the middle of an update */
    c->fc_steps++;
    if (!c->fc_t_first) { c->fc_prev = v; c->fc_t_first = now | 1u; c->fc_t_last = 0; return; }
    if (v == c->fc_prev) return;
    uint32_t d = (v - c->fc_prev) & 0x7FFu;
    if (!c->fc_t_last) { c->fc_t_first = now | 1u; c->fc_frames = 0; }   /* the first edge starts the clock */
    else { c->fc_frames += d; if (d > c->fc_gap_max) c->fc_gap_max = d; }
    c->fc_t_last = now | 1u;
    c->fc_prev = v;
}

void ix_ctl_step(wr_t *w) {
    ix_cap *c = &w->cap;
    uint32_t now = w->fw.tick_us();
#ifndef IX_MUTANT_CANCEL_STARTING
    /* A pressed start is never abandoned: a host write over ctl (a cancel, a new arm) during it would leave a take
     * that may be starting with nobody to stop it.  movrecstwai made this hold by blocking. */
    if (w->starting) c->ctl = IX_CTL_STARTING;
#endif
    ix_fc_step(c, now);
    ix_ur_step(w, now);
    ix_lv_step(w, now);
    /* CDNG after the stop: on the host's word (a manual take), or cd_after_ms
     * after our own take's stop.  Once per arm: cd_state leaves IDLE. */
    if (c->cd_go) { c->cd_go = 0; ix_cdng_run(w); ix_report(w, IX_EV_CDNG, 1); }
    else if (c->ctl == IX_CTL_DONE && c->cd_after_ms && c->cd_state == IX_CD_IDLE &&
             now - c->t_stop >= c->cd_after_ms * 1000u) { ix_cdng_run(w); ix_report(w, IX_EV_CDNG, 1); }
    if (c->rp_every_us && now - c->rp_t_last >= c->rp_every_us) {
        c->rp_t_last = now;
        ix_report(w, IX_EV_HEARTBEAT, 0);
    }
    switch (c->ctl) {
    case IX_CTL_ARMED:
        if (!c->t_arm) {
            c->t_arm = now | 1u; c->install_at_arm = w->n_install;
            /* layout 10 lives past the host's arm image: this take's burst starts empty */
            c->t_movon = c->bu_sent = c->bu_skip = c->bu_err = c->bu_n = 0;
            c->bu_last = 0xFFFFFFFFu;
            ix_report(w, IX_EV_ARMED, 0);           /* mode 0: the host is not reading yet at the arm */
            break;
        }
        if (c->cp_phase != IX_CP_DONE) {
            ix_cp_step(w, now);
            if (c->cp_phase != IX_CP_DONE) break;    /* all done in this step: go on to the take now */
        }
        if (now - c->t_arm < c->start_ms * 1000u) break;
        ix_sh(w, IX_SH_ENA);
        ix_sh(w, IX_SH_INIT);
        ix_sh(w, IX_SH_MOVON);
        c->t_movon = w->starting = w->fw.tick_us() | 1u;
        c->ctl = IX_CTL_STARTING;
#ifndef IX_MUTANT_START_BLOCKS
        /* movrecstwai would block here until +6 (~600 ms live), with no LV pushed across the start: poll +6
         * from the next step on instead, with movrecstwai's own bound */
        break;
#else
        ix_sh(w, IX_SH_RECWAI);
#endif
    case IX_CTL_STARTING:
#if !defined(IX_MUTANT_START_BLOCKS) && !defined(IX_MUTANT_START_NO_TIMEOUT)
        if (!ix_rs(w, RS_STARTED) && now - c->t_movon < IX_START_WAIT_MS * 1000u) break;
#elif defined(IX_MUTANT_START_NO_TIMEOUT)
        if (!ix_rs(w, RS_STARTED)) break;
#endif
        /* +6 seen, or movrecstwai's 60 s are over: decide exactly as after it */
        w->starting = 0;
        c->t_rec = w->fw.tick_us() | 1u;
        /* layout 8 lives past the host's arm image: this take starts its own frame clock and REC watch */
        c->fc_t_first = c->fc_t_last = c->fc_frames = c->fc_steps = c->fc_gap_max = 0;
        c->wt_n_rec = 0;
        c->rs_started = ix_rs(w, RS_STARTED);
        /* Only a take that really started may get the second press: a press
         * on a camera that did not start would START one, with nobody to stop it. */
#ifdef IX_MUTANT_NO_START_CHECK
        c->rs_started = 1;
#endif
        if (c->rs_started || w->n_install != c->install_at_arm) { c->ctl = IX_CTL_REC; ix_report(w, IX_EV_REC, 1); }
        else { ix_sh(w, IX_SH_DISA); c->ctl = IX_CTL_FAIL_START; ix_report(w, IX_EV_FAIL_START, 1); }
        break;
    case IX_CTL_REC:
        if (now - c->t_rec < c->rec_ms * 1000u) break;
#ifndef IX_MUTANT_NO_STOP
        ix_sh(w, IX_SH_MOVON);
        ix_sh(w, IX_SH_SAVEWAI);
        c->rs_saved = ix_rs(w, RS_SAVED);
#endif
        /* A missing saved notification does not prove that recording still
         * runs. Another toggle could start a new take. Fail without retry. */
        c->t_stop = w->fw.tick_us() | 1u;
        ix_sh(w, IX_SH_DISA);
        c->ctl = c->rs_saved ? IX_CTL_DONE : IX_CTL_FAIL_STOP;
#ifndef IX_MUTANT_NO_STOP_REPORT
        ix_report(w, c->rs_saved ? IX_EV_STOPPED : IX_EV_FAIL_STOP, 1);
#endif
        break;
    default:
        break;
    }
}

void ix_ctl_task(wr_t *w) {
    for (;;) {
        w->fw.dly(20);
        ix_ctl_step(w);
    }
}
