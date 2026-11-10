/* Host substitutes for codec_job.c. Every firmware call is logged by a code
 * so a test can compare the ORDER with the firmware's own encoder. Memory
 * reads and writes go through a small address map: the engine block, the
 * tile-count variable, the end-position register and three test buffers. */
#include <stdint.h>
#include <string.h>
#include "codec_job.h"

enum { C_INIT = 1, C_FLAG, C_CLR, C_TWAI, C_OPEN, C_SUBMIT, C_RESET, C_START,
       C_CLOSE, C_EOI, C_TILES, C_TOTAL };

#define SRC 0x10000000u
#define DST 0x20000000u
#define TBL 0x30000000u
#define ENGINE 0xc302cdd4u
#define TILECOUNT 0xc302cdecu
#define ENDPOS 0x300d00f8u

static uint32_t log_[64], log_n;
static uint32_t devregs[0x40];         /* the engine's register window */
static uint32_t engine[6], tilecount, endpos;
static uint8_t dst[8192];
static uint32_t tbl[1024];
static uint32_t init_args[9], request_seen[12];
static uint32_t eoi_args[2], tiles_args[3], total_args[2];
/* behaviour knobs */
static uint32_t init_ret, flag_id, open_ret, submit_ret, start_ret, close_ret;
static uint32_t twai_ret, twai_pattern, total_ret, engine_dst_len, engine_tbl_len;
static uint32_t tile_sizes[160], tile_count_for_total;

static void rec(uint32_t code) { if (log_n < 64) log_[log_n++] = code; }

static uint32_t f_init(const uint32_t *p) {
    rec(C_INIT);
    memcpy(init_args, p, sizeof init_args);
    engine[0] = p[5];
    engine[1] = 0x0BADu;                 /* F_INIT's own source length: unused */
    engine[2] = p[6];
    engine[3] = engine_dst_len;
    engine[4] = p[7];
    engine[5] = engine_tbl_len;
    return init_ret;
}
static uint32_t f_flag(void) { rec(C_FLAG); return flag_id; }
static uint32_t f_clr(uint32_t f, uint32_t p) { rec(C_CLR); (void)f; (void)p; return 0; }
static uint32_t twai_want = 1;
static uint32_t f_twai(uint32_t f, uint32_t w, uint32_t m, uint32_t *p, uint32_t t) {
    rec(C_TWAI);
    if (f != flag_id || w != 5 || m != 1 || t != twai_want) return 0xDEAD;
    *p = twai_pattern;
    return twai_ret;
}
/* the engine's enable, 300D0074 bit 0, as C0630480 sets and clears it */
static uint32_t f_open(void) { rec(C_OPEN); if (!open_ret) devregs[0x74 / 4] |= 1u; return open_ret; }
static uint32_t submit_regs[19];        /* 300D0040..0088 as the submit found them */
static uint32_t f_submit(const uint32_t *r) {
    rec(C_SUBMIT);
    memcpy(submit_regs, &devregs[0x40 / 4], sizeof submit_regs);
    memcpy(request_seen, r, sizeof request_seen);
    return submit_ret;
}
static void f_reset(void) { rec(C_RESET); }
static uint32_t f_start(void) { rec(C_START); return start_ret; }
static uint32_t f_close(void) { rec(C_CLOSE); if (!close_ret) devregs[0x74 / 4] &= ~1u; return close_ret; }
static void f_eoi(uintptr_t d, uint32_t e) {
    rec(C_EOI); eoi_args[0] = (uint32_t)d; eoi_args[1] = e;
}
static uint32_t bswap(uint32_t v) {
    return (v >> 24) | ((v >> 8) & 0xff00u) | ((v & 0xff00u) << 8) | (v << 24);
}
static void f_tiles(uintptr_t d, uintptr_t t, uint32_t n) {
    rec(C_TILES); tiles_args[0] = (uint32_t)d; tiles_args[1] = (uint32_t)t; tiles_args[2] = n;
    /* the engine's table, big-endian, as the hardware leaves it */
    uint32_t base = ((uint32_t)t - TBL) / 4;
    for (uint32_t i = 0; i < n && base + i < 1024; ++i) tbl[base + i] = bswap(tile_sizes[i]);
}
static uint32_t f_total(uintptr_t t, uint32_t n) {
    rec(C_TOTAL); total_args[0] = (uint32_t)t; total_args[1] = n;
    tile_count_for_total = n;
    return total_ret;
}
static uint32_t *slot(uintptr_t a) {
    if (a >= ENGINE && a < ENGINE + 24) return &engine[(a - ENGINE) / 4];
    if (a == TILECOUNT) return &tilecount;
    if (a == ENDPOS) return &endpos;
    if (a >= 0x300d0000u && a < 0x300d0100u) return &devregs[(a - 0x300d0000u) / 4];
    if (a == 0x300d03fcu) return &devregs[0x3f];
    if (a >= DST && a < DST + sizeof dst) return (uint32_t *)(void *)&dst[a - DST];
    if (a >= TBL && a < TBL + sizeof tbl) return &tbl[(a - TBL) / 4];
    return 0;
}
static uint32_t oob;
static uint32_t f_read(uintptr_t a) { uint32_t *s = slot(a); if (!s) { oob++; return 0; } return *s; }
static void f_write(uintptr_t a, uint32_t v) { uint32_t *s = slot(a); if (!s) { oob++; return; } *s = v; }

const struct fpl_codec_natives fpl_codec_test_natives = {
    f_init, f_flag, f_clr, f_twai, f_open, f_submit, f_reset, f_start, f_close,
    f_eoi, f_tiles, f_total, f_read, f_write
};

static struct fpl_codec_job job;
static struct fpl_codec_input input;

uint32_t fpl_fixture_reset(uint32_t width, uint32_t height, uint32_t format) {
    memset(&job, 0, sizeof job);
    memset(log_, 0, sizeof log_); log_n = 0;
    memset(engine, 0, sizeof engine); tilecount = 0; endpos = 0;
    memset(dst, 0xAB, sizeof dst); memset(tbl, 0x5A, sizeof tbl);
    memset(request_seen, 0, sizeof request_seen);
    init_ret = 1; flag_id = 42; open_ret = submit_ret = start_ret = close_ret = 0;
    twai_ret = 0; twai_pattern = 1; oob = 0;
    memset(devregs, 0, sizeof devregs);
    engine_dst_len = 0x2000; engine_tbl_len = 160 * 4;
    total_ret = 0x1234;
    for (uint32_t i = 0; i < 160; ++i) tile_sizes[i] = 100 + i;
    input.width = width; input.height = height; input.format = format;
    input.source = SRC; input.destination = DST; input.table = TBL;
    input.source_capacity = 0xFFFFFFFFu;
    input.destination_capacity = sizeof dst;
    input.table_capacity = sizeof tbl;
    input.tile_force = 0;
    input.pitch_any = 0;
    return fpl_codec_job_init(&job);
}
void fpl_fixture_set(uint32_t knob, uint32_t value) {
    switch (knob) {
    case 0: init_ret = value; break;
    case 1: flag_id = value; break;
    case 2: open_ret = value; break;
    case 3: submit_ret = value; break;
    case 4: start_ret = value; break;
    case 5: close_ret = value; break;
    case 6: twai_ret = value; break;
    case 7: twai_pattern = value; break;
    case 8: total_ret = value; break;
    case 9: engine_dst_len = value; break;
    case 10: engine_tbl_len = value; break;
    case 11: input.source_capacity = value; break;
    case 12: input.destination_capacity = value; break;
    case 13: input.table_capacity = value; break;
    case 14: endpos = value; break;
    case 15: input.source = value; break;
    case 16: devregs[2] = value; break;          /* 300D0008 */
    case 17: input.tile_force = value; break;
    case 18: job.keep_open = value; break;
    case 20: input.pitch_any = value; break;
    case 19:                                        /* a finished job's set-up */
        for (uint32_t n = 0; n < 19; ++n) devregs[0x40 / 4 + n] |= value;
        break;
    }
}
uint32_t fpl_fixture_submit(void) { return fpl_codec_job_submit(&job, &input); }
uint32_t fpl_fixture_poll(void) { twai_want = 1; return fpl_codec_job_poll(&job); }
uint32_t fpl_fixture_wait(uint32_t ticks) {
    twai_want = ticks ? ticks : 1;
    return fpl_codec_job_wait(&job, ticks);
}
uint32_t fpl_fixture_abort(void) { return fpl_codec_job_abort(&job); }
uint32_t fpl_fixture_release(void) { return fpl_codec_job_release(&job); }
uint32_t fpl_fixture_reused(void) { return job.reused; }
uint32_t fpl_fixture_submit_reg(uint32_t n) { return submit_regs[n]; }
uint32_t fpl_fixture_engine_open(void) { return devregs[0x74 / 4] & 1u; }
uint32_t fpl_fixture_source_bytes(uint32_t w, uint32_t h, uint32_t f) {
    return fpl_codec_source_bytes(w, h, f);
}
/* 0..63 the call log; 100.. state. */
uint32_t fpl_fixture_get(uint32_t field) {
    if (field < 64) return log_[field];
    if (field >= 200 && field < 212) return request_seen[field - 200];
    if (field >= 220 && field < 229) return init_args[field - 220];
    if (field >= 300 && field < 300 + 1024) return tbl[field - 300];
    if (field >= 2000 && field < 2000 + sizeof dst) return dst[field - 2000];
    switch (field) {
    case 100: return log_n;
    case 101: return job.phase;
    case 102: return job.total;
    case 103: return job.padded;
    case 104: return tilecount;
    case 105: return eoi_args[0];
    case 106: return eoi_args[1];
    case 107: return tiles_args[0];
    case 108: return tiles_args[1];
    case 109: return tiles_args[2];
    case 110: return total_args[0];
    case 111: return total_args[1];
    case 112: return oob;
    case 113: return job.band_table;
    case 114: return job.last_native;
    case 115: return job.stall_regs[2];
    case 116: return job.stall_regs[6];
    case 117: return job.tile_width;
    case 118: return job.tile_height;
    case 119: return job.misaligned;
    default: return 0xFFFFFFFFu;
    }
}
