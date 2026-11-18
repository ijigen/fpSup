#include "play_decode.h"
#include "tile_grid.h"

#define ROOT_STOCK      8u            /* IFD0, where the recorder put it */
#define TIFF_LE         0x002a4949u   /* "II*\0" */
#define MAX_TAGS        128u
#define MAX_TILES       160u          /* codec_job's FPL_CODEC_TILE_MAX */
#define MAX_ROWS        64u
#define MAX_TILE_H      0x200u        /* the engine's own bound */
#define WAIT_TICKS      200u          /* a 3K tile row takes ~4 ms */
#define ENGINE_BLOCK    0xc302cdd4u   /* what init latched: buffers, lengths */
#define TILE_COUNT_VAR  0xc302cdecu
#define DECODE_CALLBACK 0xc062fce1u   /* C062FAD0's own: sets flag bit 2 */
#define SLOT_BUFFER     0x14u
#define SLOT_CAPACITY   0x18u
#define SLOT_READ       0x1cu
#define READER_PATH     0x80u         /* C05C0C38's object: the frame file's path */
#define READER_VOLUME   0xb4u
#define POOL_COUNT      0x04u         /* XC_CinemaDngPlay's pool: slots made */
#define POOL_SLOTS      0x08u         /* the slot array, POOL_STRIDE B each */
#define POOL_MADE       0x3cu         /* a byte: 1 once made */
#define POOL_STRIDE     0x5ecu
#define POOL_MAX        300u          /* the array C05C2D10 allocates: 0x6F090 B */
#define ALIGN           0x400u
#define BAND_TICKS      2000u         /* a 6048x4040 frame takes ~90 ms */

#if defined(FPL_PLAY_DECODE_HOST_TEST)
#define N (&fpl_play_test_natives)
#define peek(a) N->read(a)
#define poke(a, v) N->write(a, v)
#define scratch_get(o, n) N->alloc(o, n)
#define scratch_put(o) N->release(o)
#define buffer_get(n) N->buffer_get(n)
#define buffer_put(a) N->buffer_put(a)
#define dma(t, f, n) N->dma(t, f, n)
#define engine_init(p) N->init(p)
#define engine_flag() N->flag()
#define engine_clr(f) N->clr(f, 0)
#define engine_open() N->open()
#define engine_submit(r) N->submit(r)
#define engine_start() N->start()
#define engine_wait(f, p, t) ((void)(t), N->wait(f, p))
#define engine_close() N->close()
#define now_us() N->now()
#define cache_sync() N->sync()
#define first_frame(d, f, b, n, g) N->first_frame(d, f, b, n, g)
#define file_read(v, p, f, b, n, g) N->file_read(v, p, f, b, n, g)
#elif defined(__arm__) && UINTPTR_MAX == UINT32_MAX
#define peek(a) (*(volatile const uint32_t *)(a))
#define poke(a, v) (*(volatile uint32_t *)(a) = (v))
typedef uint32_t (*fn0)(void);
typedef uint32_t (*fnp)(volatile uint32_t *);
static uintptr_t scratch_get(uint32_t *obj, uint32_t bytes) {
    typedef uint32_t (*get_fn)(uint32_t *, uint32_t, uint32_t, uint32_t, uint32_t);
    typedef uintptr_t (*addr_fn)(uint32_t *);
    ((get_fn)0xc001d740u)(obj, 10, bytes, 0x400u, 0);           /* the RAW pool */
    return ((addr_fn)0xc001d7f0u)(obj);
}
static void scratch_put(uint32_t *obj) {
    typedef void (*fn)(uint32_t *, uint32_t);
    ((fn)0xc001d7a0u)(obj, 2);
}
/* The player's own way (C05C2D10 / C05C2E90): the RAW pool's handle, a
 * buffer of it by address. */
static uintptr_t buffer_get(uint32_t bytes) {
    typedef uintptr_t (*get_fn)(uint32_t, uint32_t, uint32_t, uint32_t, uint32_t);
    return ((get_fn)0xc001d1e8u)(((uint32_t (*)(uint32_t))0xc001cf78u)(10), bytes, 0, 0, 0);
}
static void buffer_put(uintptr_t address) {
    typedef void (*put_fn)(uint32_t, uintptr_t);
    ((put_fn)0xc001d2b8u)(((uint32_t (*)(uint32_t))0xc001cf78u)(10), address);
}
/* C00FBB90 {source, destination, bytes, flags 0}: synchronous, its own cache
 * maintenance and semaphore (frame_hold.c header_dma). */
static uint32_t dma(uintptr_t to, uintptr_t from, uint32_t bytes) {
    volatile uint32_t r[4];
    r[0] = (uint32_t)from;
    r[1] = (uint32_t)to;
    r[2] = bytes;
    r[3] = 0;
    return ((fnp)0xc00fbb91u)(r);
}
#define engine_init(p) ((fnp)0xc05a6890u)(p)                     /* ARM */
#define engine_flag() ((fn0)0xc062f441u)()
#define engine_clr(f) ((uint32_t (*)(uint32_t, uint32_t))0xc00169c8u)(f, 0)
#define engine_open() ((fn0)0xc062fe71u)()
#define engine_submit(r) ((fnp)0xc062fec1u)(r)                    /* C0630240 */
#define engine_start() ((fn0)0xc062fed9u)()                       /* C06303F8 */
static uint32_t engine_wait(uint32_t flag, uint32_t *pattern, uint32_t ticks) {
    typedef uint32_t (*fn)(uint32_t, uint32_t, uint32_t, uint32_t *, uint32_t);
    return ((fn)0xc0016c08u)(flag, 2, 1, pattern, ticks);        /* twai_flg */
}
#define engine_close() ((fn0)0xc062fe81u)()
#define now_us() ((fn0)0xc002b6e0u)()
#define cache_sync() ((void)((fn0)0xc000e91cu)())   /* what the player calls
                                                       around its own read */
/* The clip's first frame, opened the way C05BDD68 names it: the descriptor's
 * volume (C069B930) and path (C069B9B8); the file API menu_page.c uses. */
static uint32_t first_frame(uintptr_t desc, uint32_t *file, uint8_t *buf, uint32_t bytes,
                            uint32_t *got) {
    typedef uint32_t (*d_fn)(uintptr_t);
    typedef void (*ctor_fn)(uint32_t *, uint32_t);
    typedef uint32_t (*open_fn)(uint32_t *, uint32_t, uint32_t);
    typedef uint32_t (*read_fn)(uint32_t *, uint8_t *, uint32_t, uint32_t *);
    typedef void (*close_fn)(uint32_t *);
    uint32_t ok;
    ((ctor_fn)0xc0365e90u)(file, ((d_fn)0xc069b930u)(desc));
    ok = ((open_fn)0xc0365fb0u)(file, ((d_fn)0xc069b9b8u)(desc), 1);
    if (ok) {
        ok = ((read_fn)0xc0366060u)(file, buf, bytes, got);
        ((close_fn)0xc0366020u)(file);
    }
    ((ctor_fn)0xc0365ed0u)(file, 2);                            /* destructor */
    return ok;
}
/* A file read whole, the way C05C0C38 reads a frame: the volume's file
 * object, open for reading, one read, close. */
static uint32_t file_read(uint32_t volume, const char *path, uint32_t *file, uintptr_t buf,
                          uint32_t bytes, uint32_t *got) {
    typedef void (*ctor_fn)(uint32_t *, uint32_t);
    typedef uint32_t (*open_fn)(uint32_t *, const char *, uint32_t);
    typedef uint32_t (*read_fn)(uint32_t *, uintptr_t, uint32_t, uint32_t *);
    typedef void (*close_fn)(uint32_t *);
    uint32_t ok;
    ((ctor_fn)0xc0365e90u)(file, volume);
    ok = ((open_fn)0xc0365fb0u)(file, path, 1);
    if (ok) {
        ok = ((read_fn)0xc0366060u)(file, buf, bytes, got);
        ((close_fn)0xc0366020u)(file);
    }
    ((ctor_fn)0xc0365ed0u)(file, 2);                            /* destructor */
    return ok;
}
#else
#error "ARM32 native playback ABI required; host tests must explicitly substitute it"
#endif

static void saturate(uint32_t *v) { if (*v != UINT32_MAX) ++*v; }
static uint32_t kib(uint32_t v) { return (v + 0x3ffu) & ~0x3ffu; }
/* No division: there is no runtime library on the camera. Bounded operands. */
static uint32_t ceil_div(uint32_t a, uint32_t b) {
    uint32_t q = 0;
    while (a > 0) { ++q; a = a > b ? a - b : 0; }
    return q;
}

/* The player's buffer is read through its own mapping (what it will see);
 * our own copy of a first frame's header, `local`, directly. */
static uint32_t rd8(uintptr_t a, uint32_t local) {
    if (local) return *(const volatile uint8_t *)a;
    return (peek(a & ~(uintptr_t)3u) >> ((a & 3u) * 8u)) & 0xffu;
}
static uint32_t rd16(uintptr_t a, uint32_t l) { return rd8(a, l) | rd8(a + 1, l) << 8; }
static uint32_t rd32(uintptr_t a, uint32_t l) { return rd16(a, l) | rd16(a + 2, l) << 16; }

struct ifd {
    uint32_t w, h, bits, comp, tw, th;
    uint32_t toff_type, toff_n, toff, tcnt_type, tcnt_n, tcnt;
    uint32_t soff, scnt, soff_n, scnt_n;
    uint32_t rate;                       /* where FrameRate's SRATIONAL lies; 0: none */
};

/* One IFD of [base, base + got). 0: not readable. */
static uint32_t read_ifd(uintptr_t base, uint32_t got, uint32_t at, struct ifd *f,
                         uint32_t local) {
    uint32_t n;
    for (uint32_t k = 0; k < sizeof(*f) / 4u; ++k) ((uint32_t *)f)[k] = 0;
    if (got < 16u || (at & 1u) || at < 8u || at > got - 2u) return 0;
    n = rd16(base + at, local);
    if (!n || n > MAX_TAGS || 2u + 12u * n + 4u > got - at) return 0;
    for (uint32_t k = 0; k < n; ++k) {
        uintptr_t e = base + at + 2u + 12u * k;
        uint32_t tag = rd16(e, local), type = rd16(e + 2, local), count = rd32(e + 4, local);
        uint32_t v = type == 3 ? rd16(e + 8, local) : rd32(e + 8, local);
        switch (tag) {
        case 256: f->w = v; break;
        case 257: f->h = v; break;
        case 258: f->bits = v; break;
        case 259: f->comp = v; break;
        case 322: f->tw = v; break;
        case 323: f->th = v; break;
        case 324: f->toff_type = type; f->toff_n = count; f->toff = rd32(e + 8, local); break;
        case 325: f->tcnt_type = type; f->tcnt_n = count; f->tcnt = rd32(e + 8, local); break;
        case 273: f->soff = v; f->soff_n = count; break;
        case 279: f->scnt = v; f->scnt_n = count; break;
        case 51044: if (type == 10 && count == 1) f->rate = v; break;
        default: break;
        }
    }
    return 1;
}

static uint32_t format_code(uint32_t bits) {
    switch (bits) {
    case 12: return 0;
    case 14: return 1;
    case 16: return 2;
    case 10: return 3;
    default: return 0xffu;
    }
}
static uint32_t pitch_of(uint32_t w, uint32_t bits) { return ((w * bits >> 3) + 3u) & ~3u; }

/* The recorder's raster (C0135D40) rounds its LAST row up to 12 pixels: at
 * FHD 1936 wide that row is 2916 B, not 2904, and the strip 12 B longer than
 * rows x pitch (2026-10-01: an FHD clip was taken for not ours). The extra is
 * padding past the frame; nothing decoded lands in it. */
#define LAST_ROW_SLACK 64u
static uint32_t strip_bytes(const struct ifd *f0) {
    uint32_t rows = pitch_of(f0->w, f0->bits) * f0->h;
    return f0->scnt > rows ? f0->scnt : rows;
}

/* IFD0 of a frame: the stock strip of a frame we know how to decode. */
static uint32_t stock_strip(const struct ifd *f0) {
    return f0->comp == 1 && format_code(f0->bits) != 0xffu && f0->w >= 8 &&
           f0->w <= 0x4000 && !(f0->w & 7u) && f0->h >= 2 && f0->h <= 0x4000 &&
           !(f0->h & 1u) && f0->soff_n == 1 && f0->scnt_n == 1 && f0->soff >= 8u &&
           f0->scnt && f0->scnt <= pitch_of(f0->w, f0->bits) * f0->h + LAST_ROW_SLACK;
}

/* ---- clip open ---------------------------------------------------------- */
/* A buffer moved up to 1 KiB: the address the allocator gave is the word
 * below it. 0: not one we moved. */
static uintptr_t given(uintptr_t a) {
    uintptr_t raw;
    if (!a || (a & (ALIGN - 1u))) return 0;
    raw = peek(a - 4u);
    if (raw >= a || (raw & 3u) || a - raw != ALIGN - (raw & (ALIGN - 1u))) return 0;
    return raw;
}
static uintptr_t moved_up(uintptr_t raw) {
    uintptr_t a = raw + ALIGN - (raw & (ALIGN - 1u));    /* 4..0x400 B up */
    poke(a - 4u, (uint32_t)raw);
    return a;
}

void fpl_play_end(struct fpl_play *p) {
    if (!p) return;
    if (p->pool && p->slots && peek(p->pool + POOL_COUNT) == p->slots &&
        peek(p->pool + POOL_SLOTS) == p->slots_base) {
        for (uint32_t n = 0; n < p->slots; ++n) {
            uintptr_t slot = p->slots_base + n * POOL_STRIDE, a = peek(slot + SLOT_BUFFER);
            uintptr_t raw = given(a);
            if (!raw) { saturate(&p->not_ours); continue; }
            poke(slot + SLOT_BUFFER, (uint32_t)raw);
            poke(slot + SLOT_CAPACITY, peek(slot + SLOT_CAPACITY) + (uint32_t)(a - raw));
            saturate(&p->restored);
        }
    }
    p->pool = 0;
    p->slots = 0;
    for (uint32_t k = 0; k < 2; ++k) {               /* the spare, the one read ahead into */
        uintptr_t *held = k ? &p->ahead : &p->spare, raw;
        if (!*held) continue;
        raw = given(*held);
        if (raw) buffer_put(raw); else saturate(&p->spare_lost);
        *held = 0;
    }
    p->spare_cap = p->ahead_cap = 0;
    p->ahead_got = 0;
    if (!p->scratch) return;
    scratch_put(p->obj);
    p->scratch = 0;
    p->scratch_bytes = 0;
    saturate(&p->scratch_freed);
}

uint32_t fpl_play_clip(struct fpl_play *p, uintptr_t desc, uint32_t size, uint32_t busy) {
    struct ifd f0;
    uint32_t got = 0, want, stock, need;
    uintptr_t h;
    if (!p) return size;
    saturate(&p->clips);
    p->clip_size_was = size;
    p->scratch_want = 0;
    p->hook_end_us = 0;
    p->ahead_got = 0;
    p->sums_stale = 1;                   /* the sums restart at this clip's first fast frame */
    p->rate_num = p->rate_den = 0;
    p->pace_last_us = p->pace_sum_us = p->pace_n = 0;
    p->gate_waiting = 0;
    if (busy || !desc) return size;
    for (uint32_t n = 0; n < FPL_PLAY_HEADER / 4u; ++n) p->header[n] = 0;
    if (!first_frame(desc, p->file, (uint8_t *)p->header, FPL_PLAY_HEADER, &got) ||
        got < 16u || got > FPL_PLAY_HEADER) {
        saturate(&p->clip_failed);
        return size;
    }
    h = (uintptr_t)p->header;
    if (rd32(h, 1) != TIFF_LE) return size;
    if (!read_ifd(h, got, ROOT_STOCK, &f0, 1) || !stock_strip(&f0)) {
        if (rd32(h + 4, 1) != ROOT_STOCK) saturate(&p->clip_failed);   /* ours, unreadable */
        return size;                     /* a format we do not decode: stock */
    }
    /* One tile row's stream and output, for the tallest tile the engine
     * takes; taken when the pool is made (fpl_play_pool). For EVERY clip of
     * a format we decode: a take's first frame is left uncompressed (card.c,
     * for DaVinci), so the first frame cannot say whether later ones are. */
    need = 2u * kib(pitch_of(f0.w, f0.bits) * MAX_TILE_H);
    p->scratch_want = need;
    /* the stock frame file: header, then the strip padded to 512 B */
    stock = f0.soff + ((f0.scnt + 0x1ffu) & ~0x1ffu);
    /* ... and room for whole tiles below the last row: the engine writes
     * them, and the one-job decode goes straight into a buffer of this
     * size. The recorder's default grid; another grid's frames that do not
     * fit go the row way. */
    {
        uint32_t tw, th, padded;
        fpl_tile_grid(f0.w, f0.h, 0, &tw, &th);
        padded = f0.soff + pitch_of(f0.w, f0.bits) * (ceil_div(f0.h, th) * th);
        if (padded > stock) stock = padded;
    }
    want = stock > size ? stock : size;
    if (rd32(h + 4, 1) == ROOT_STOCK) saturate(&p->clips_first_stock);
    else saturate(&p->clips_ours);
    if (want != size) p->clip_size_set = want;
    return want;
}

void fpl_play_pool(struct fpl_play *p, uintptr_t pool, uint32_t size) {
    if (!p || !p->scratch_want) return;
    if (p->scratch && p->scratch_bytes < p->scratch_want) fpl_play_end(p);
    if (!p->scratch) {
        p->scratch = scratch_get(p->obj, p->scratch_want);
        if (!p->scratch || (p->scratch & 0x3ffu)) {
            if (p->scratch) scratch_put(p->obj);
            p->scratch = 0;
            saturate(&p->scratch_failed);
        } else {
            p->scratch_bytes = p->scratch_want;
        }
    }
    /* The spare, as the player is about to take its own: only when this call
     * will make the pool (not made, no slots), and none is held. */
    if (!pool || p->pool || p->spare || rd8(pool + POOL_MADE, 0) || peek(pool + POOL_COUNT) ||
        size > 0xfffff000u - 0x1fffu)
        return;
    {
        uint32_t cap = (size + 0x1fffu) & ~0xfffu;       /* C05C2D10's own size */
        uintptr_t raw = buffer_get(cap);
        if (!raw || (raw & 3u)) {
            if (raw) buffer_put(raw);
            saturate(&p->spare_failed);
            return;
        }
        p->spare = moved_up(raw);
        p->spare_cap = cap - (uint32_t)(p->spare - raw);
        p->pool = pool;
        raw = buffer_get(cap);                           /* and one to read ahead into */
        if (!raw || (raw & 3u)) {
            if (raw) buffer_put(raw);
            saturate(&p->ahead_failed);
            return;
        }
        p->ahead = moved_up(raw);
        p->ahead_cap = cap - (uint32_t)(p->ahead - raw);
        p->ahead_got = 0;
    }
}

void fpl_play_made(struct fpl_play *p) {
    uint32_t n;
    uintptr_t base;
    if (!p || !p->pool || !p->spare || p->slots) return;
    n = peek(p->pool + POOL_COUNT);
    base = peek(p->pool + POOL_SLOTS);
    if (!n || n > POOL_MAX || !base || (base & 3u)) return;   /* the spare stays unused */
    for (uint32_t k = 0; k < n; ++k) {
        uintptr_t slot = base + k * POOL_STRIDE, raw = peek(slot + SLOT_BUFFER), a;
        uint32_t cap = peek(slot + SLOT_CAPACITY);
        if (!raw || (raw & 3u) || cap <= ALIGN) continue;
        a = moved_up(raw);
        poke(slot + SLOT_BUFFER, (uint32_t)a);
        poke(slot + SLOT_CAPACITY, cap - (uint32_t)(a - raw));
    }
    p->slots = n;
    p->slots_base = (uint32_t)base;
    cache_sync();
}

/* ---- a frame -------------------------------------------------------------- */
/* C062FAD0's steps for one band of `rows` rows (whole tiles) and `tiles`
 * tiles: init with the decode flag, the request, OPEN, SUBMIT, START -- then,
 * in band_finish, wait for bit 2, CLOSE. band_start: the flag, or negative
 * (nothing left open). */
static int32_t band_start(const struct ifd *f, uint32_t rows, uint32_t tiles, uintptr_t out,
                          uintptr_t stream) {
    volatile uint32_t init[9], req[12];
    uint32_t flag;
    init[0] = f->w; init[1] = rows; init[2] = format_code(f->bits);
    init[3] = f->tw; init[4] = f->th;
    init[5] = (uint32_t)out;
    init[6] = (uint32_t)stream;
    init[7] = 0;
    init[8] = 1;                                     /* decode */
    if (engine_init(init) != 1) return -1;
    for (uint32_t n = 0; n < 12; ++n) req[n] = 0;
    req[0] = f->w; req[1] = rows; req[2] = format_code(f->bits);
    req[3] = f->tw; req[4] = f->th;
    for (uint32_t n = 0; n < 4; ++n) req[5 + n] = peek(ENGINE_BLOCK + 4u * n);
    req[11] = DECODE_CALLBACK;
    flag = engine_flag();
    if ((int32_t)flag < 0) return -1;
    poke(TILE_COUNT_VAR, tiles);
    engine_clr(flag);
    if (engine_open() != 0) return -1;
    if (engine_submit(req) != 0 || engine_start() != 0) {
        engine_clr(flag);
        engine_close();
        return -1;
    }
    return (int32_t)flag;
}
static uint32_t band_finish(uint32_t flag, uint32_t ticks) {     /* 0 = decoded */
    uint32_t pattern = 0, ok;
    ok = engine_wait(flag, &pattern, ticks) == 0 && (pattern & 2u);
    engine_clr(flag);
    if (engine_close() != 0) ok = 0;
    return ok ? 0 : 1;
}
static uint32_t decode_band(const struct ifd *f, uint32_t rows, uint32_t tiles, uintptr_t out,
                            uintptr_t stream, uint32_t ticks) {
    int32_t flag = band_start(f, rows, tiles, out, stream);
    return flag < 0 ? 1 : band_finish((uint32_t)flag, ticks);
}

static uint32_t refuse(struct fpl_play *p, uint32_t why) { saturate(&p->refused_by[why]); return why; }

/* The header in front of the decoded strip: whole words through the cache,
 * every line of [0, bytes) written whole (bytes is a multiple of 1 KiB), so
 * the clean at the end puts exactly this in memory. */
#if defined(FPL_PLAY_DECODE_HOST_TEST)
static void head_copy(uintptr_t to, uintptr_t from, uint32_t bytes) {
    for (uint32_t n = 0; n < bytes; n += 4) poke(to + n, peek(from + n));
}
#else
static void head_copy(uintptr_t to, uintptr_t from, uint32_t bytes) {
    uint32_t *d = (uint32_t *)to;
    const uint32_t *s = (const uint32_t *)from;
    for (uint32_t n = bytes >> 5; n; --n) {
        uint32_t a = s[0], b = s[1], c = s[2], e = s[3], g = s[4], h = s[5], i = s[6], j = s[7];
        d[0] = a; d[1] = b; d[2] = c; d[3] = e; d[4] = g; d[5] = h; d[6] = i; d[7] = j;
        s += 8; d += 8;
    }
}
#endif

/* The whole frame in one job: the stream where it was read, the pixels into
 * the spare at the same strip offset, then the two buffers change places.
 * 0xffff: not this way (counted); else what fpl_play_frame returns. */
#define NOT_FAST 0xffffu
/* The file after the one `reader` names, into the second spare: the same
 * path with its six digits one higher. Called while the engine runs. */
static void read_ahead(struct fpl_play *p, uintptr_t reader) {
    uint32_t n = 0, got = 0;
    p->ahead_got = 0;
    if (!reader || !p->ahead || !given(p->ahead)) { saturate(&p->ahead_none); return; }
    while (n < FPL_PLAY_PATH - 1u && rd8(reader + READER_PATH + n, 0)) {
        p->ahead_path[n] = (char)rd8(reader + READER_PATH + n, 0);
        ++n;
    }
    p->ahead_path[n] = 0;
    if (rd8(reader + READER_PATH + n, 0) || n < FPL_PLAY_DIGITS + 6u) {
        saturate(&p->ahead_none);
        return;
    }
    for (uint32_t k = FPL_PLAY_DIGITS + 6u; k-- > FPL_PLAY_DIGITS;) {     /* + 1, decimal */
        char c = p->ahead_path[k];
        if (c < '0' || c > '9') { saturate(&p->ahead_none); return; }
        if (c != '9') { p->ahead_path[k] = (char)(c + 1); break; }
        p->ahead_path[k] = '0';
        if (k == FPL_PLAY_DIGITS) { saturate(&p->ahead_none); return; }  /* 999999 */
    }
    if (!file_read(peek(reader + READER_VOLUME), p->ahead_path, p->file, p->ahead, p->ahead_cap,
                   &got) || !got || got >= p->ahead_cap) {
        saturate(&p->ahead_none);                    /* the clip's last frame, or too long */
        return;
    }
    p->ahead_got = got;
    saturate(&p->ahead_read);
}

uint32_t fpl_play_read(struct fpl_play *p, uintptr_t slot, uintptr_t reader, uint32_t busy) {
    uintptr_t buf;
    uint32_t cap, n;
    if (!p || !p->ahead_got) return 0;
    if (busy || !slot || !reader || !p->ahead || !given(p->ahead)) { p->ahead_got = 0; return 0; }
    for (n = 0; n < FPL_PLAY_PATH && p->ahead_path[n] &&
                rd8(reader + READER_PATH + n, 0) == (uint8_t)p->ahead_path[n]; ++n) {}
    buf = peek(slot + SLOT_BUFFER);
    cap = peek(slot + SLOT_CAPACITY);
    if (n >= FPL_PLAY_PATH || p->ahead_path[n] || rd8(reader + READER_PATH + n, 0) || !given(buf) || p->ahead_got >= cap) {
        p->ahead_got = 0;                            /* another frame: the player reads it */
        saturate(&p->ahead_missed);
        return 0;
    }
    poke(slot + SLOT_BUFFER, (uint32_t)p->ahead);
    poke(slot + SLOT_CAPACITY, p->ahead_cap);
    poke(slot + SLOT_READ, p->ahead_got);
    p->ahead = buf;
    p->ahead_cap = cap;
    p->ahead_got = 0;
    saturate(&p->ahead_used);
    return 1;
}

static uint32_t fast_frame(struct fpl_play *p, uintptr_t slot, uintptr_t buf, uint32_t cap,
                           const struct ifd *f, uint32_t soff, uint32_t stream_at,
                           uint32_t tiles, uint32_t padded_rows, uintptr_t reader) {
    uint32_t t0, t1, t2, t3;
    int32_t flag;
    if (!p->spare || !p->slots) { saturate(&p->fast_no_spare); return NOT_FAST; }
    if (!given(buf) || !given(p->spare) || (soff & (ALIGN - 1u)) || (stream_at & (ALIGN - 1u)) ||
        soff < ALIGN) {
        saturate(&p->fast_no_align);
        return NOT_FAST;
    }
    if (p->spare_cap < soff || p->spare_cap - soff < pitch_of(f->w, f->bits) * padded_rows) {
        saturate(&p->fast_no_room);
        return NOT_FAST;
    }
    t0 = now_us();
    if (p->sums_stale) {
        p->sum_engine_us = p->sum_hook_us = p->sum_gap_us = p->timed = p->gaps = 0;
        p->sum_read_us = p->sum_wait_us = 0;
        p->max_gap_us = p->min_gap_us = 0;
        p->sums_stale = 0;
    }
    if (p->hook_end_us && t0 - p->hook_end_us < 1000000u) {
        p->last_gap_us = t0 - p->hook_end_us;
        p->sum_gap_us += p->last_gap_us;
        if (p->last_gap_us > p->max_gap_us) p->max_gap_us = p->last_gap_us;
        if (!p->min_gap_us || p->last_gap_us < p->min_gap_us) p->min_gap_us = p->last_gap_us;
        saturate(&p->gaps);
    }
    t1 = now_us();
    flag = band_start(f, padded_rows, tiles, p->spare + soff, buf + stream_at);
    if (flag < 0) {
        p->hook_end_us = 0;
        return refuse(p, FPL_PLAY_R_ENGINE);         /* the frame as it was read */
    }
    /* while the engine runs: the header in front of its output (other cache
     * lines: the strip starts on a 1 KiB boundary), then the next file */
    head_copy(p->spare, buf, soff);
    poke(p->spare + 4, ROOT_STOCK);                  /* the player's tag reader starts there */
    p->last_head_us = now_us() - t1;
    read_ahead(p, reader);                           /* the next file, while the engine runs */
    t3 = now_us();
    if (band_finish((uint32_t)flag, BAND_TICKS) != 0) {
        p->hook_end_us = 0;
        return refuse(p, FPL_PLAY_R_ENGINE);         /* the frame as it was read */
    }
    t2 = now_us();
    p->last_read_us = t3 - t1;
    p->last_wait_us = t2 - t3;
    p->sum_read_us += p->last_read_us;
    p->sum_wait_us += p->last_wait_us;
    poke(slot + SLOT_BUFFER, (uint32_t)p->spare);
    poke(slot + SLOT_CAPACITY, p->spare_cap);
    p->spare = buf;
    p->spare_cap = cap;
    cache_sync();
    p->last_engine_us = t2 - t1;
    p->hook_end_us = now_us();
    p->last_us = p->hook_end_us - t0;
    if (p->last_us > p->max_us) p->max_us = p->last_us;
    p->sum_engine_us += p->last_engine_us;
    p->sum_hook_us += p->last_us;
    saturate(&p->timed);
    saturate(&p->fast);
    saturate(&p->decoded);
    return FPL_PLAY_DECODED;
}

/* ---- a clip slower than its frame rate: start with the pool full -------- */
#define PLAYER_STATE    0x450u        /* XC_CinemaDngPlay: 1 = buffering before the start */
#define PLAYER_BUFFERING 1u
#define POOL_FREE       0x18u         /* the pool's free list: slots in it */
#define SLOT_LAST       0x08u         /* a slot: the reader's "nothing after this" */
#define GATE_FRAMES     64u           /* enough waiting, however many slots there are */
#define PACE_MIN        4u            /* intervals before the pace says anything */
#define PACE_BREAK_US   500000u       /* longer than this is a pause, not the pace */
#define PACE_KEEP       4096u         /* intervals summed; then both are halved */
#define PACE_MARGIN     1010000u      /* slow: 1 % over the frame period, in us */

/* A frame file has reached our hook: the time since the one before, and (once
 * a clip) the frame rate IFD0 gives. */
static void pace(struct fpl_play *p, uintptr_t buf, uint32_t got) {
    uint32_t t = now_us();
    if (p->pace_last_us) {
        uint32_t d = t - p->pace_last_us;
        if (d < PACE_BREAK_US) {
            p->pace_sum_us += d;
            if (++p->pace_n >= PACE_KEEP) { p->pace_n >>= 1; p->pace_sum_us >>= 1; }
        }
    }
    p->pace_last_us = t ? t : 1u;
    if (!p->rate_den) {
        struct ifd f0;
        p->rate_den = 1;
        p->rate_num = 0;
        if (read_ifd(buf, got, ROOT_STOCK, &f0, 0) && f0.rate >= 8u && !(f0.rate & 1u) &&
            got >= 8u && f0.rate <= got - 8u) {
            uint32_t n = rd32(buf + f0.rate, 0), d = rd32(buf + f0.rate + 4u, 0);
            /* Sensor Lab writes 14400000/600661: both halved until the
             * denominator fits 16 bits (the pace's products stay in 32) */
            if (n && d && d <= 0x1000000u && n <= 240u * d) {
                while (d > 0xffffu) { n >>= 1; d >>= 1; }
                p->rate_num = n; p->rate_den = d;
            }
        }
    }
}

/* The frames of this clip reach us slower than its frame rate. */
static uint32_t slow(const struct fpl_play *p) {
    if (p->pace_n < PACE_MIN || !p->rate_num || p->rate_den > 0xffffu) return 0;
    return (uint64_t)p->pace_sum_us * p->rate_num >
           (uint64_t)(p->pace_n * p->rate_den) * PACE_MARGIN;
}

uint32_t fpl_play_gate(struct fpl_play *p, uintptr_t pool, uintptr_t player, uint32_t stock,
                       uint32_t busy) {
    uint32_t total, free_n;
    if (!p || !stock) return stock;
    saturate(&p->gate_asked);
    if (busy || !pool || !player || p->pool != pool || !p->slots) return stock;
    p->gate_state = peek(player + PLAYER_STATE);
    if (p->gate_state != PLAYER_BUFFERING) { saturate(&p->gate_other); p->gate_waiting = 0; return stock; }
    p->gate_pace_n = p->pace_n;
    p->gate_pace_us = p->pace_sum_us;
    p->gate_rate_num = p->rate_num;
    p->gate_rate_den = p->rate_den;
    p->gate_slow = slow(p);
    if (!p->gate_slow && !p->gate_waiting) { saturate(&p->gate_fast); return stock; }
    total = peek(pool + POOL_COUNT);
    free_n = peek(pool + POOL_FREE);
    p->gate_total = total;
    p->gate_free = free_n;
    if (total != p->slots || peek(pool + POOL_SLOTS) != p->slots_base || free_n > total)
        return stock;
    if (free_n > 1u && total - free_n < GATE_FRAMES) {
        uint32_t ended = 0;
        for (uint32_t n = 0; n < total && !ended; ++n)
            ended = rd8(p->slots_base + n * POOL_STRIDE + SLOT_LAST, 0);
        if (!ended) { saturate(&p->gate_held); p->gate_waiting = 1; return 0; }
    }
    p->gate_waiting = 0;
    saturate(&p->gate_let);
    return stock;
}

uint32_t fpl_play_frame(struct fpl_play *p, uintptr_t slot, uint32_t busy) {
    return fpl_play_frame_at(p, slot, 0, busy);
}

uint32_t fpl_play_frame_at(struct fpl_play *p, uintptr_t slot, uintptr_t reader, uint32_t busy) {
    struct ifd f, f0;
    uintptr_t buf, strip, s_at, o_at;
    uint32_t cap, got, root, across, down, tiles, end, pitch, raw_row, rem, t0;
    uint32_t row_at[MAX_ROWS + 1];

    if (!p || !slot) return FPL_PLAY_R_SLOT;
    saturate(&p->seen);
    buf = peek(slot + SLOT_BUFFER);
    cap = peek(slot + SLOT_CAPACITY);
    got = peek(slot + SLOT_READ);
    p->last_buf = (uint32_t)buf; p->last_cap = cap; p->last_got = got;
    if (!buf || (buf & 3u) || buf + cap < buf) return refuse(p, FPL_PLAY_R_SLOT);
    if (got < 16u || got > cap || rd32(buf, 0) != TIFF_LE) return refuse(p, FPL_PLAY_R_TIFF);
    root = rd32(buf + 4, 0);
    pace(p, buf, got);
    if (root == ROOT_STOCK) { saturate(&p->stock); return FPL_PLAY_STOCK; }
    if (busy) return refuse(p, FPL_PLAY_R_BUSY);

    /* ---- the trailer: ours, and every tile inside what was read --------- */
    if (!read_ifd(buf, got, root, &f, 0)) return refuse(p, FPL_PLAY_R_ROOT);
    if (f.comp != 7 || format_code(f.bits) == 0xffu ||
        f.w < 8 || f.w > 0x4000 || (f.w & 7u) || f.h < 2 || f.h > 0x4000 || (f.h & 1u) ||
        f.tw < 0x20 || f.tw > 0x200 || (f.tw & 0x1fu) ||
        f.th < 2 || f.th > MAX_TILE_H || (f.th & 1u))
        return refuse(p, FPL_PLAY_R_FORMAT);
    across = ceil_div(f.w, f.tw);
    down = ceil_div(f.h, f.th);
    tiles = across * down;
    if (tiles > MAX_TILES || down > MAX_ROWS || f.toff_n != tiles || f.tcnt_n != tiles ||
        tiles < 2 || f.toff_type != 4 || f.tcnt_type != 4 ||
        f.toff > got - 4u * tiles || f.tcnt > got - 4u * tiles)
        return refuse(p, FPL_PLAY_R_TILES);
    end = rd32(buf + f.toff, 0);
    for (uint32_t k = 0, col = 0, row = 0; k < tiles; ++k) {   /* no division */
        uint32_t o = rd32(buf + f.toff + 4u * k, 0), n = rd32(buf + f.tcnt + 4u * k, 0);
        if (o != end || !n || n > got || o > got - n) return refuse(p, FPL_PLAY_R_TILES);
        if (col == 0) row_at[row] = o;
        if (++col == across) { col = 0; ++row; }
        end = o + n;
    }
    row_at[down] = end;

    /* ---- IFD0: the stock strip the pixels go back into ----------------- */
    if (!read_ifd(buf, got, ROOT_STOCK, &f0, 0) || !stock_strip(&f0) || f0.w != f.w ||
        f0.h != f.h || f0.bits != f.bits || f0.soff > row_at[0])
        return refuse(p, FPL_PLAY_R_IFD0);
    pitch = pitch_of(f.w, f.bits);
    if (f0.soff > cap || cap - f0.soff < strip_bytes(&f0)) return refuse(p, FPL_PLAY_R_ROOM);
    {
        uint32_t r = fast_frame(p, slot, buf, cap, &f, f0.soff, row_at[0], tiles, down * f.th,
                                reader);
        if (r != NOT_FAST) return r;
    }
    strip = buf + f0.soff;
    raw_row = pitch * f.th;
    /* Bottom up is safe only if no tile row's output reaches a stream above
     * it: the streams of rows 0..r-1 end where row r's raw output begins. */
    for (uint32_t r = 1; r <= down; ++r)
        if (row_at[r] - f0.soff > (r < down ? r * raw_row : pitch * f.h))
            return refuse(p, FPL_PLAY_R_ORDER);
    if (!p->scratch || p->scratch_bytes < 2u * kib(raw_row))
        return refuse(p, FPL_PLAY_R_SCRATCH);
    o_at = p->scratch;
    s_at = p->scratch + kib(raw_row);
    for (uint32_t r = 0; r < down; ++r)
        if (row_at[r + 1] - row_at[r] > p->scratch_bytes - kib(raw_row))
            return refuse(p, FPL_PLAY_R_SCRATCH);

    rem = f.h - (down - 1u) * f.th;                  /* rows in the last tile row */
    t0 = now_us();
    for (uint32_t r = down; r-- > 0;) {
        if (dma(s_at, buf + row_at[r], row_at[r + 1] - row_at[r]) != 0)
            return refuse(p, FPL_PLAY_R_COPY);
        if (decode_band(&f, f.th, across, o_at, s_at, WAIT_TICKS) != 0)
            return refuse(p, FPL_PLAY_R_ENGINE);
        if (dma(strip + r * raw_row, o_at, (r == down - 1u ? rem : f.th) * pitch) != 0)
            return refuse(p, FPL_PLAY_R_COPY);
    }
    /* The file is now the stock one: its root back on IFD0. */
    poke(buf + 4, ROOT_STOCK);
    cache_sync();
    p->last_us = now_us() - t0;
    if (p->last_us > p->max_us) p->max_us = p->last_us;
    p->hook_end_us = 0;
    saturate(&p->rows);
    saturate(&p->decoded);
    return FPL_PLAY_DECODED;
}
