/* Host substitutes for play_decode.c. One flat memory holds the player's
 * frame buffer -- NOT 1 KiB aligned, as measured on the camera -- the slot
 * describing it and the scratch the decoder takes at clip open. Every write
 * is checked against where it may land.
 *
 * The fake engine: a tile in the "stream" is {length, tile id} then filler.
 * Decoding a tile row writes, for every tile, `th` WHOLE rows (as the real
 * engine does: it overran a short buffer on the camera, 2026-10-01) but only
 * the columns inside the frame, each byte (id * 7 + row in tile + column). */
#include <string.h>
#include "play_decode.h"

#define MEM        0x50000000u
#define MEM_SIZE   (4u << 20)
/* the player's pool (the one-job tests): an object, its slot array, buffers the
 * allocator hands out at addresses that are not 1 KiB aligned */
#define POOL       (MEM + 0x400u)
#define SLOTS      (MEM + 0x1000u)
#define STRIDE     0x5ecu
#define HEAP       (MEM + 0x10000u)
#define HEAP_MAX   8u
#define READER     (MEM + 0x800u)        /* C05C0C38's object: path +0x80, volume +0xB4 */
#define VOLUME     0x5D0001u
#define DISK_MAX   4u
#define SLOT       (MEM + 0x100u)
#define BUF        (MEM + 0x10780u)            /* not 1 KiB aligned */
#define SCRATCH    (MEM + 0x200000u)
#define ENGINE_BLK 0xc302cdd4u
#define TILE_VAR   0xc302cdecu

static uint8_t mem[MEM_SIZE];
static uint8_t first[FPL_PLAY_HEADER];
static uint32_t first_len, first_fails;
static uint32_t engine_blk[4], tile_var, oob, bad_writes, cap_bytes;
static uint32_t opens, closes, inits, submits, starts, waits, dmas, allocs, releases, syncs;
static uint32_t dma_fail_at, engine_fail, alloc_fail, misaligned_engine;
static uint32_t out_addr, stream_addr, rows_told, width_told, started;
static uint32_t tw_, th_, bits_, scratch_bytes;
static struct { char path[96]; uint8_t data[0x8000]; uint32_t len; } disk[DISK_MAX];
static uint32_t disk_n, file_reads, file_read_while_engine;
static uint32_t heap_at[HEAP_MAX], heap_len[HEAP_MAX], heap_n, heap_step, heap_fail, heap_calls, heap_fail_call, puts, bad_puts, pooled;

static uint32_t *slot32(uintptr_t a) {
    if (a >= ENGINE_BLK && a < ENGINE_BLK + 16) return &engine_blk[(a - ENGINE_BLK) / 4];
    if (a == TILE_VAR) return &tile_var;
    if (a >= MEM && a + 4 <= MEM + MEM_SIZE && !(a & 3u)) return (uint32_t *)(void *)&mem[a - MEM];
    oob++;
    return 0;
}
static uint32_t rd(uintptr_t a) { uint32_t *s = slot32(a); return s ? *s : 0; }
/* The decoder may write: the buffer up to its capacity, the scratch it was
 * given, the engine variables. Nothing else. */
static uint32_t allowed(uintptr_t a, uint32_t n) {
    if (a >= BUF && a + n <= BUF + cap_bytes) return 1;
    if (scratch_bytes && a >= SCRATCH && a + n <= SCRATCH + scratch_bytes) return 1;
    for (uint32_t k = 0; k < heap_n; ++k)
        if (heap_len[k] && a >= heap_at[k] && a + n <= heap_at[k] + heap_len[k]) return 1;
    if (pooled && a >= SLOTS && a + n <= SLOTS + HEAP_MAX * STRIDE) return 1;
    return 0;
}
static void wr(uintptr_t a, uint32_t v) {
    uint32_t *s;
    if (a != TILE_VAR && !(a >= ENGINE_BLK && a < ENGINE_BLK + 16) && !allowed(a, 4))
        bad_writes++;
    if ((s = slot32(a))) *s = v;
}
static uint8_t *at(uintptr_t a) { return &mem[a - MEM]; }

static uintptr_t f_alloc(uint32_t *obj, uint32_t bytes) {
    if (alloc_fail || bytes > MEM_SIZE - (SCRATCH - MEM)) return 0;
    allocs++;
    obj[0] = SCRATCH;
    scratch_bytes = bytes;
    memset(at(SCRATCH), 0xEE, bytes);
    return SCRATCH;
}
static void f_release(uint32_t *obj) { releases++; obj[0] = 0; scratch_bytes = 0; }
/* The player's allocator: the next block, `heap_step` past a 1 KiB boundary. */
static uintptr_t f_buffer_get(uint32_t bytes) {
    uintptr_t a = heap_n ? heap_at[heap_n - 1] + heap_len[heap_n - 1] : HEAP;
    a = ((a + 0x3ffu) & ~0x3ffu) + heap_step;
    if (++heap_calls == heap_fail_call) return 0;
    if (heap_fail || heap_n == HEAP_MAX || a + bytes > SCRATCH) return 0;
    heap_at[heap_n] = a; heap_len[heap_n] = bytes; heap_n++;
    return a;
}
static void f_buffer_put(uintptr_t a) {
    puts++;
    for (uint32_t k = 0; k < heap_n; ++k)
        if (heap_len[k] && heap_at[k] == a) { heap_len[k] = 0; return; }
    bad_puts++;
}
static uint32_t f_dma(uintptr_t to, uintptr_t from, uint32_t n) {
    dmas++;
    if (dma_fail_at && dmas == dma_fail_at) return 5;
    if (!allowed(to, n) || from < MEM || from + n > MEM + MEM_SIZE) { bad_writes++; return 5; }
    memmove(at(to), at(from), n);
    return 0;
}
static uint32_t f_init(volatile uint32_t *p) {
    inits++;
    if (p[8] != 1) return 0;                        /* only the decode flag */
    engine_blk[0] = p[5]; engine_blk[1] = 0x1111; engine_blk[2] = p[6]; engine_blk[3] = 0x2222;
    width_told = p[0]; rows_told = p[1]; tw_ = p[3]; th_ = p[4];
    bits_ = p[2] == 0 ? 12 : p[2] == 1 ? 14 : p[2] == 2 ? 16 : 10;
    return 1;
}
static uint32_t f_flag(void) { return 77; }
static uint32_t f_clr(uint32_t f, uint32_t p) { (void)f; (void)p; return 0; }
static uint32_t f_open(void) { opens++; return 0; }
static uint32_t f_submit(volatile uint32_t *r) {
    submits++;
    if (r[11] != 0xc062fce1u || r[5] != engine_blk[0] || r[7] != engine_blk[2] ||
        r[0] != width_told || r[1] != rows_told) return 1;
    if ((r[5] | r[7]) & 0x3ffu) { misaligned_engine++; return 1; }
    if (r[5] <= r[7] ? r[7] - r[5] < 0x400u : 0) { misaligned_engine++; return 1; }
    out_addr = r[5]; stream_addr = r[7];
    return 0;
}
static uint32_t f_start(void) { starts++; started = 1; return 0; }
static uint32_t f_wait(uint32_t flag, uint32_t *pattern) {
    waits++;
    if (flag != 77 || !started) return 0xffffffceu;
    started = 0;
    if (engine_fail) return 0xffffffceu;
    uint32_t across = (width_told + tw_ - 1) / tw_, pitch = ((width_told * bits_ / 8) + 3) & ~3u;
    uintptr_t s = stream_addr;
    for (uint32_t t = 0; t < tile_var; ++t) {
        uint32_t len = rd(s), id = rd(s + 4);
        uint32_t tx = t % across, ty = t / across;
        uint32_t x0 = tx * tw_, x1 = x0 + tw_ > width_told ? width_told : x0 + tw_;
        uint32_t b0 = x0 * bits_ / 8, b1 = x1 * bits_ / 8;
        for (uint32_t y = 0; y < th_; ++y) {
            uintptr_t row = out_addr + (ty * th_ + y) * pitch;
            if (!allowed(row + b0, b1 - b0)) { bad_writes++; continue; }
            for (uint32_t b = b0; b < b1; ++b) *at(row + b) = (uint8_t)(id * 7 + y + b);
        }
        s += len;
    }
    *pattern = 2;
    return 0;
}
static uint32_t f_close(void) { closes++; return 0; }
static uint32_t clock_us = 1000;
static uint32_t f_now(void) { return clock_us; }
static void f_sync(void) { syncs++; }
static uint32_t f_first(uintptr_t desc, uint32_t *file, uint8_t *buf, uint32_t bytes,
                        uint32_t *got) {
    (void)file;
    if (desc != 0xDE5C || first_fails) return 0;
    *got = first_len < bytes ? first_len : bytes;
    memcpy(buf, first, *got);
    return 1;
}

/* The card: the files put there by fpl_fixture_disk. A read while the engine
 * runs is what reading ahead is for; it is counted. */
static uint32_t f_file_read(uint32_t volume, const char *path, uint32_t *file, uintptr_t buf,
                            uint32_t bytes, uint32_t *got) {
    (void)file;
    file_reads++;
    if (started) file_read_while_engine++;
    if (volume != VOLUME) return 0;
    for (uint32_t k = 0; k < disk_n; ++k)
        if (!strcmp(disk[k].path, path)) {
            uint32_t n = disk[k].len < bytes ? disk[k].len : bytes;
            if (!allowed(buf, n)) { bad_writes++; return 0; }
            memcpy(at(buf), disk[k].data, n);
            *got = n;
            return 1;
        }
    return 0;
}

const struct fpl_play_natives fpl_play_test_natives = {
    rd, wr, f_alloc, f_release, f_buffer_get, f_buffer_put, f_dma, f_init, f_flag, f_clr, f_open, f_submit, f_start,
    f_wait, f_close, f_now, f_sync, f_first, f_file_read
};

static struct fpl_play play;

void fpl_fixture_reset(void) {
    memset(&play, 0, sizeof play);
    scratch_bytes = 0;
    alloc_fail = first_fails = 0;
    heap_n = heap_step = heap_fail = puts = bad_puts = pooled = 0;
    disk_n = file_reads = file_read_while_engine = 0;
    heap_fail_call = 0;
    clock_us = 1000;
}
/* The clip's first frame file, as C05BDD68 names it. */
uint32_t fpl_fixture_clip(const uint8_t *file, uint32_t len, uint32_t size, uint32_t busy) {
    first_len = len < sizeof first ? len : sizeof first;
    memcpy(first, file, first_len);
    allocs = releases = 0;
    return fpl_play_clip(&play, 0xDE5C, size, busy);
}
/* clip open then the player's pool, as the camera does: the old pool
 * freed first when the size changed, then made */
uint32_t fpl_fixture_open(const uint8_t *file, uint32_t len, uint32_t size, uint32_t busy) {
    uint32_t r = fpl_fixture_clip(file, len, size, busy);
    fpl_play_end(&play);
    fpl_play_pool(&play, 0, 0);
    return r;
}
void fpl_fixture_end(void) { fpl_play_end(&play); }
void fpl_fixture_pool(void) { fpl_play_pool(&play, 0, 0); }
/* The camera's order with a pool: clip open, the old pool freed, C05C2D10's
 * entry (ours first), the player takes `slots` buffers of its size, its
 * return (ours). `step`: how far past 1 KiB the allocator's blocks start. */
uint32_t fpl_fixture_open_pool(const uint8_t *file, uint32_t len, uint32_t size, uint32_t slots,
                               uint32_t step) {
    uint32_t want = fpl_fixture_clip(file, len, size, 0), cap = (want + 0x1fffu) & ~0xfffu;
    fpl_play_end(&play);
    memset(mem, 0xA5, SCRATCH - MEM);
    heap_n = 0; heap_step = step; pooled = 1; puts = bad_puts = 0; heap_calls = 0;
    *(uint32_t *)(void *)at(POOL + 4) = 0;
    *(uint32_t *)(void *)at(POOL + 8) = 0;
    *(uint32_t *)(void *)at(POOL + 0x3c) = 0;
    fpl_play_pool(&play, POOL, want);
    *(uint32_t *)(void *)at(POOL + 8) = SLOTS;
    memset(at(SLOTS), 0, slots * STRIDE);            /* as C05C2D10 clears each slot */
    for (uint32_t k = 0; k < slots; ++k) {
        uintptr_t a = f_buffer_get(cap);
        if (!a) break;
        *(uint32_t *)(void *)at(SLOTS + k * STRIDE + 0x14) = (uint32_t)a;
        *(uint32_t *)(void *)at(SLOTS + k * STRIDE + 0x18) = cap;
        *(uint32_t *)(void *)at(POOL + 4) = k + 1;
    }
    *(uint32_t *)(void *)at(POOL + 0x3c) = 1;
    fpl_play_made(&play);
    return want;
}
/* The player reads `file` into slot k's buffer, then our hook. */
uint32_t fpl_fixture_play(uint32_t k, const uint8_t *file, uint32_t len) {
    uintptr_t slot = SLOTS + k * STRIDE, buf = rd(slot + 0x14);
    oob = bad_writes = opens = closes = inits = submits = starts = waits = 0;
    dmas = misaligned_engine = syncs = 0;
    started = 0;
    if (len > rd(slot + 0x18)) return 0xdead;
    memcpy(at(buf), file, len);
    *(uint32_t *)(void *)at(slot + 0x1c) = len;
    return fpl_play_frame(&play, slot, 0);
}
/* The player frees its pool (C05C2E90): ours first, then every slot's buffer
 * by its address. Returns the buffers it could not free as given. */
uint32_t fpl_fixture_free_pool(void) {
    uint32_t n = rd(POOL + 4);
    fpl_play_end(&play);
    for (uint32_t k = 0; k < n; ++k) f_buffer_put(rd(SLOTS + k * STRIDE + 0x14));
    *(uint32_t *)(void *)at(POOL + 4) = 0;
    *(uint32_t *)(void *)at(POOL + 0x3c) = 0;
    return bad_puts;
}
/* C05C2D10 called again for a pool that is already made: it does nothing. */
void fpl_fixture_remake(uint32_t size) {
    fpl_play_pool(&play, POOL, size);
    fpl_play_made(&play);
}
/* A file on the card. */
void fpl_fixture_disk(const char *path, const uint8_t *data, uint32_t len) {
    if (disk_n == DISK_MAX || len > sizeof disk[0].data) return;
    strncpy(disk[disk_n].path, path, sizeof disk[0].path - 1);
    memcpy(disk[disk_n].data, data, len);
    disk[disk_n++].len = len;
}
/* The player reads the file `path` into slot k: its f_read site (ours may
 * serve it), else the card's file, then our hook after the read. */
uint32_t fpl_fixture_play_path(uint32_t k, const char *path) {
    uintptr_t slot = SLOTS + k * STRIDE;
    uint32_t got = 0;
    oob = bad_writes = opens = closes = inits = submits = starts = waits = 0;
    dmas = misaligned_engine = syncs = 0;
    started = 0;
    memset(at(READER), 0, 0x100);
    strncpy((char *)at(READER + 0x80), path, 0x30);
    *(uint32_t *)(void *)at(READER + 0xb4) = VOLUME;
    if (!fpl_play_read(&play, slot, READER, 0)) {
        if (!f_file_read(VOLUME, path, 0, rd(slot + 0x14), rd(slot + 0x18), &got)) return 0xdead;
        *(uint32_t *)(void *)at(slot + 0x1c) = got;
        file_reads--;                                /* the player's own read */
    }
    return fpl_play_frame_at(&play, slot, READER, 0);
}
/* The player (state at +0x450) asks whether it may start; its pool has
 * `free_n` slots in the free list and said `stock`. */
#define PLAYER (MEM + 0xF000u)
uint32_t fpl_fixture_gate(uint32_t state, uint32_t free_n, uint32_t stock, uint32_t busy) {
    *(uint32_t *)(void *)at(PLAYER + 0x450) = state;
    *(uint32_t *)(void *)at(POOL + 0x18) = free_n;
    return fpl_play_gate(&play, POOL, PLAYER, stock, busy);
}
/* The reader's "nothing after this" on slot k. */
void fpl_fixture_slot_last(uint32_t k, uint32_t v) { *at(SLOTS + k * STRIDE + 8) = (uint8_t)v; }
/* A pool of n slots (no buffers behind them: for the start gate only). */
void fpl_fixture_big_pool(uint32_t n) {
    memset(at(SLOTS), 0, n * STRIDE);
    *(uint32_t *)(void *)at(POOL + 4) = n;
    play.slots = n;
}
uint32_t fpl_fixture_slot(uint32_t k, uint32_t field) { return rd(SLOTS + k * STRIDE + field); }
uint32_t fpl_fixture_slot_byte(uint32_t k, uint32_t offset) {
    return *at(rd(SLOTS + k * STRIDE + 0x14) + offset);
}
uint32_t fpl_fixture_live(void) {       /* allocator blocks not given back */
    uint32_t n = 0;
    for (uint32_t k = 0; k < heap_n; ++k) n += heap_len[k] != 0;
    return n;
}
/* A frame as the player leaves it: `file` read into BUF, capacity `cap`. */
void fpl_fixture_load(const uint8_t *file, uint32_t len, uint32_t cap) {
    memset(mem, 0xA5, SCRATCH - MEM);
    oob = bad_writes = opens = closes = inits = submits = starts = waits = 0;
    dmas = dma_fail_at = engine_fail = misaligned_engine = syncs = 0;
    started = 0;
    cap_bytes = cap;
    memcpy(at(BUF), file, len);
    *(uint32_t *)(void *)at(SLOT + 0x14) = BUF;
    *(uint32_t *)(void *)at(SLOT + 0x18) = cap;
    *(uint32_t *)(void *)at(SLOT + 0x1c) = len;
}
void fpl_fixture_knob(uint32_t k, uint32_t v) {
    switch (k) {
    case 0: dma_fail_at = v; break;
    case 1: engine_fail = v; break;
    case 2: alloc_fail = v; break;
    case 3: *(uint32_t *)(void *)at(SLOT + 0x14) = v; break;     /* buffer */
    case 4: first_fails = v; break;
    case 5: heap_fail = v; break;
    case 6: heap_fail_call = v; break;               /* this call of the allocator fails */
    case 7: clock_us = v; break;                     /* the microsecond clock */
    }
}
uint32_t fpl_fixture_run(uint32_t busy) { return fpl_play_frame(&play, SLOT, busy); }
uint32_t fpl_fixture_byte(uint32_t offset) { return mem[BUF - MEM + offset]; }
uint32_t fpl_fixture_get(uint32_t f) {
    if (f >= 100 && f < 100 + FPL_PLAY_REASONS) return play.refused_by[f - 100];
    switch (f) {
    case 0: return play.seen;
    case 1: return play.stock;
    case 2: return play.decoded;
    case 3: return oob;
    case 4: return bad_writes;
    case 5: return opens;
    case 6: return closes;
    case 7: return allocs;
    case 8: return releases;
    case 9: return dmas;
    case 10: return submits;
    case 11: return misaligned_engine;
    case 12: return play.scratch_bytes;
    case 13: return play.clips_ours;
    case 14: return syncs;
    case 15: return play.scratch_failed;
    case 16: return play.clip_failed;
    case 17: return play.fast;
    case 18: return play.rows;
    case 19: return play.slots;
    case 20: return play.restored;
    case 21: return play.fast_no_spare;
    case 22: return play.fast_no_align;
    case 23: return play.fast_no_room;
    case 24: return (uint32_t)play.spare;
    case 25: return rows_told;
    case 26: return tile_var;
    case 27: return puts;
    case 28: return play.spare_lost;
    case 29: return play.not_ours;
    case 30: return play.spare_failed;
    case 31: return play.ahead_read;
    case 32: return play.ahead_used;
    case 33: return play.ahead_missed;
    case 34: return play.ahead_none;
    case 35: return file_reads;
    case 36: return file_read_while_engine;
    case 37: return (uint32_t)play.ahead;
    case 38: return play.ahead_got;
    case 39: return play.ahead_failed;
    case 40: return play.gate_held;
    case 41: return play.gate_let;
    case 42: return play.rate_num;
    case 43: return play.rate_den;
    case 44: return play.pace_n;
    default: return 0xffffffffu;
    }
}
