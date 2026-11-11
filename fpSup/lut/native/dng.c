/* The LUT's color matrix in the DNGs the camera writes (user 2026-11-03: cine and
 * still DNGs both; projects/lut-sup/notes/COLOR_MATRIX_AUTHOR_LAYER.md).
 *
 * Stock: FUN_c02c4a50 (ColorMatrix1/2), FUN_c02c4d40 (HueSatMap) and
 * FUN_c02c4e80 (ToneCurve) pick their set by one word, the writer context's
 * color mode `p3 + 0x30 + 4 * [p3 + 0x118]`: 0x24 (OFF) the OFF set, anything
 * else the one Standard set.  A LUT row of the COLOR list is the stock OFF mode
 * (COL-Share), so with no help the files carry the OFF set.  Here each of the six
 * calls (two writers x three functions -- the image's only branches to them)
 * goes through dng_wrap: while the row's cube is the active one, that word is
 * the cube's choice for the call (Standard: not 0x24, OFF: 0x24) and back after.
 * Custom: the OFF set, the two OFF base tables (9 doubles each, read only by
 * FUN_c02c4a50) holding the author's matrices for the call -- the firmware's own
 * code still reads the body's calibration (tag 0x11F), inverts and multiplies,
 * as it does for its own tables.  No float in this file (soft-float build). */
#define DNG_OFF       0x24u
#define DNG_STANDARD  0u                 /* any word but 0x24: the three test only == 0x24 */
#define DNG_CM        0xC02C4A50u
#define DNG_HSM       0xC02C4D40u
#define DNG_CURVE     0xC02C4E80u
#define DNG_TAB_A     0xC096FD74u        /* FUN_c02c4a50's OFF ColorMatrix1 base (A) */
#define DNG_TAB_D65   0xC096FCE4u        /*                    ColorMatrix2 base (D65) */
#define DNG_TAB_LEN   72u
#define DNG_CM1_MOVW  0xC02C4BE4u        /* FUN_c02c4a50's OFF branch: movw / movt r2 = the CM1 base, */
#define DNG_CM2_MOVW  0xC02C4C98u        /* then CM2's.  RAW-View 0.4 points them at its own cm_buf */

static u32 dng_rd(u32 a) { return *(volatile const u32 *)(uintptr_t)a; }
static void dng_wr(u32 a, u32 v) { *(volatile u32 *)(uintptr_t)a = v; }

/* site i: the `bl`, its target's kind, the word Ver.5.02 holds (no .rodata: no linker) */
static u32 dng_site(u32 i, u32 *kind, u32 *stock) {
    switch (i) {
    case 0: *kind = 0; *stock = 0xEBFFF84Au; return 0xC02C6920u;
    case 1: *kind = 1; *stock = 0xEBFFF8FEu; return 0xC02C6940u;
    case 2: *kind = 2; *stock = 0xEBFFF94Au; return 0xC02C6950u;
    case 3: *kind = 0; *stock = 0xEBFFF50Au; return 0xC02C7620u;
    case 4: *kind = 1; *stock = 0xEBFFF5BEu; return 0xC02C7640u;
    default: *kind = 2; *stock = 0xEBFFF60Au; return 0xC02C7650u;
    }
}
static u32 dng_target(u32 kind) { return kind == 0 ? DNG_CM : kind == 1 ? DNG_HSM : DNG_CURVE; }

/* The cube of the row the root shows (COL-Share's shown()) and its matrix, or LIB_NONE: stock. */
static u32 dng_choice(struct lut4_state *s, const struct lib_entry **out) {
    const struct lut_cols *L = &s->cols;
    u32 sup = 0, i = COLS_NONE;
    if (!L->attached || !s->library || !L->api->shown(L->api, &sup, &i) || sup != API_ID) return LIB_NONE;
    if (i >= s->library->h.count) return LIB_NONE;
    const struct lib_entry *e = &s->library->entries[i];
    if (!(e->flags & LIB_MATRIX) || e->matrix >= MAT_N) return LIB_NONE;
    if (e->matrix == MAT_CUSTOM && !(e->author_flags & AUTH_CUSTOM)) return LIB_NONE;
    *out = e;
    return e->matrix;
}

/* Q20 -> IEEE 754 double (lo, hi words), shifts only. */
static void dng_double(i32 v, u32 *lo, u32 *hi) {
    if (!v) { *lo = 0; *hi = 0; return; }
    u32 sign = v < 0 ? 1u : 0u, a = sign ? 0u - (u32)v : (u32)v;
    u32 p = 31u - (u32)__builtin_clz(a), frac = p ? a & ((1u << p) - 1u) : 0u, h, l;
    if (p <= 20u) { h = frac << (20u - p); l = 0; }
    else { h = frac >> (p - 20u); l = frac << (32u - (p - 20u)); }
    *hi = sign << 31 | (p + 1023u - 20u) << 20 | h;
    *lo = l;
}

/* The base table a movw / movt r2 pair at `at` loads: where FUN_c02c4a50 reads now (stock: DNG_TAB_A /
 * DNG_TAB_D65; with RAW-View on the card its cm_buf -- 2026-11-08, both COL-Share clients).  0 = not a pair. */
static u32 dng_movwt(u32 at) {
    u32 lo = dng_rd(at), hi = dng_rd(at + 4u);
    if ((lo & 0xFFF0F000u) != 0xE3002000u || (hi & 0xFFF0F000u) != 0xE3402000u) return 0;
    u32 a = ((lo >> 4) & 0xF000u) | (lo & 0xFFFu) | (((hi >> 4) & 0xF000u) | (hi & 0xFFFu)) << 16;
    return a & 3u ? 0 : a;
}

/* struct dng_ctx: lut4.c (in the state) */

static USED void dng_wrap(const struct dng_ctx *d, u32 p1, u32 p2, u32 p3) {
    struct lut4_state *s = d->s;
    void (*f)(u32, u32, u32) = (void (*)(u32, u32, u32))(uintptr_t)d->original;
    const struct lib_entry *e = 0;
    u32 m = dng_choice(s, &e), sel = p3 ? dng_rd(p3 + 0x118u) : 6u;
    if (m == LIB_NONE || sel >= 6u) { f(p1, p2, p3); return; }
    u32 at = p3 + 0x30u + 4u * sel, old = dng_rd(at), saved[2u * DNG_TAB_LEN / 4u];
    u32 ta = dng_movwt(DNG_CM1_MOVW), td = dng_movwt(DNG_CM2_MOVW);
    u32 swap = d->kind == 0 && m == MAT_CUSTOM && ta && td;
    dng_wr(at, m == MAT_STANDARD ? DNG_STANDARD : DNG_OFF);
    if (swap) {
        for (u32 k = 0; k < DNG_TAB_LEN / 4u; k++) {
            saved[k] = dng_rd(ta + 4u * k); saved[DNG_TAB_LEN / 4u + k] = dng_rd(td + 4u * k);
        }
        for (u32 k = 0; k < 9u; k++) {
            u32 lo, hi;
            dng_double(e->cm[0][k], &lo, &hi); dng_wr(ta + 8u * k, lo); dng_wr(ta + 8u * k + 4u, hi);
            dng_double(e->cm[1][k], &lo, &hi); dng_wr(td + 8u * k, lo); dng_wr(td + 8u * k + 4u, hi);
        }
    }
    f(p1, p2, p3);
    if (swap)
        for (u32 k = 0; k < DNG_TAB_LEN / 4u; k++) {
            dng_wr(ta + 4u * k, saved[k]); dng_wr(td + 4u * k, saved[DNG_TAB_LEN / 4u + k]);
        }
    dng_wr(at, old);
    s->dng_calls++;
}

/* the veneer's stub: ip = the context; (p1, p2, p3) -> dng_wrap(ctx, p1, p2, p3),
 * lr untouched (the writer's return) */
__asm__(
"   .arm\n"
"   .global dng_stub\n"
"dng_stub:\n"
"   mov     r3, r2\n"
"   mov     r2, r1\n"
"   mov     r1, r0\n"
"   mov     r0, ip\n"
"   ldr     ip, [r0, #4]\n"
"   bx      ip\n"
"   .thumb\n");
extern const u8 dng_stub[];

/* From lc_attached (cols.c), once COL-Share has our rows: claim the six sites and the two
 * tables (one refusal: nothing written), veneers, then the patches.  0 = installed. */
static int dng_install(struct lut4_state *s) {
    const struct sl_svc *svc = s->svc;
    if (!s->cols.attached || svc->version < 6u) return 1;
    for (u32 i = 0; i < 6u; i++) {
        u32 kind, stock, a = dng_site(i, &kind, &stock);
        if (dng_rd(a) != stock) return 2;
    }
    for (u32 i = 0; i < 6u; i++) {
        u32 kind, stock, a = dng_site(i, &kind, &stock);
        if (svc->claim(svc, a, 4u, &stock, SL_EXCL) != SL_OK) return 3;
    }
    if (svc->claim(svc, DNG_TAB_A, DNG_TAB_LEN, (const void *)(uintptr_t)DNG_TAB_A, SL_EXCL) != SL_OK ||
        svc->claim(svc, DNG_TAB_D65, DNG_TAB_LEN, (const void *)(uintptr_t)DNG_TAB_D65, SL_EXCL) != SL_OK)
        return 4;
    u32 v = svc->cave_alloc(svc, 16u * 3u);
    if (!v || (v & 7u)) return 5;
    for (u32 k = 0; k < 3u; k++) {
        struct dng_ctx *c = &s->dng[k];
        c->s = s; c->wrap = (u32)(uintptr_t)&dng_wrap; c->original = dng_target(k); c->kind = k;
        dng_wr(v + 16u * k, VENEER_IP); dng_wr(v + 16u * k + 4u, VENEER_PC);
        dng_wr(v + 16u * k + 8u, (u32)(uintptr_t)c); dng_wr(v + 16u * k + 12u, (u32)(uintptr_t)dng_stub & ~1u);
    }
    svc->publish(svc);
    for (u32 i = 0; i < 6u; i++) {
        u32 kind, stock, a = dng_site(i, &kind, &stock);
        dng_wr(a, cl_bl(a, v + 16u * kind));
    }
    svc->publish(svc);
    return 0;
}
