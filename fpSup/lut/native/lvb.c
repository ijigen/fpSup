/* The active LUT on the camera's own ISP: Live View, and -- the user's choice
 * (2026-11-04) -- MOV and JPG too.  The DNGs keep the stock tags.
 *
 * Measured on the camera (projects/lut-sup/validation/20261103-lv-isp-01..05):
 * COLOR OFF's pipeline is c (white-balanced camera RGB, tone index / 1918)
 * -> RGBLMAT group 1 (root+0x10, luma) and group 2 (root+0x08, chroma), each
 * one 3x3 entry per colour mode, Q9 in table order R(R,G,B) G(G,R,B) B(B,R,G)
 * -> three 2048-point tone tables (root+0x70 base, root+0x48 three-channel list)
 * -> the 601 luma of the group-1 path with the chroma of the group-2 path.
 * The same 3x3 in both groups is a plain tone(M.c); five live frames matched
 * that model to 0.2 / 0.35 code, the ARRI Classic cube to dE 0.88.
 *
 * lvb_fit() makes M and the tables from render() (the cube as the monitor
 * shows it), the algorithm of projects/lut-sup/probes/lv_fit.py fit_isp in
 * integers: tone = the neutral axis; M = per row an inverse-curve weighted
 * least squares, then Gauss-Newton.  Only the OFF (0x24) entries of copies of
 * the stock tables change, and the root words point at the copies while a
 * LUT row of the COLOR list (= stock OFF + the active row, COL-Share) is active.
 * Since 2026-11-07 the root words are COL-Share's (fpSup/colshare, Bei §9.1): we hand
 * it each row's record (struct cols_rec) and it writes them, from the setter too.
 *
 * DNG: MakerNote 0x124 reads root+0x08 through FUN_c02d5df0 in FUN_c02c5440
 * (site LVB_S124), 0x12D picks its tone slot through FUN_c02d2f40 in
 * FUN_c02c5df0 (site LVB_S12D); both functions are reached only from those two
 * MakerNote producers.  While ours are in, the first returns a root whose
 * +0x08 is stock and the second answers OFF as stock does (base 82 + contrast,
 * one channel) without touching FUN_c02cf490's cache.  MakerNote 0x34 (camera,
 * 2026-11-04: it carried the LUT's matrix) reads the PQ object's live block through
 * FUN_c02d3a90 in FUN_c02cc130 (LVB_S34; the DNG writers' and two more callers):
 * a copy whose 9-word sets equal to ours are the stock OFF identity.
 *
 * No set per row (Bei 2026-11-10, "沒用掉的東西不要佔用記憶體"): at most two sets (~26 KB each), borrowed from the
 * allocator (borrow.c): the active (picked) row's (s->b_set, made at the pick from its .JFT, or fitted) and, while
 * the COLOR menu is open, the one under the cursor (s->b_prev, lvb_preview: COL-Share's v3 preview() after each
 * cursor step -- read the row's .JFT, build, set_record: the row shows its LUT at once, as before 11-10).  The
 * cursor leaving a previewed row gives its set back; the close's pick keeps the previewed set as the active one.
 * Every other row's record is the stock one.  A row with no current .JFT (its strength moved since the conversion)
 * is not fitted at the cursor (seconds): stock until it is picked.  While recording: no preview (no file read);
 * a row shows its set if one is held (the active row, the last previewed one), else stock; a pick waits for the
 * take's end (COL-Share defers it, library_busy refuses any borrow).
 *
 * No division instruction and no EABI helpers here: lvb_udivq does the divides. */
#define LVB_ROOT      0xC2F1A064u
#define LVB_P08       (LVB_ROOT + 0x08u)
#define LVB_P10       (LVB_ROOT + 0x10u)
#define LVB_P48       (LVB_ROOT + 0x48u)
#define LVB_P70       (LVB_ROOT + 0x70u)
#define LVB_T08       0xC0B39CC8u           /* stock {table, count} at each root word */
#define LVB_N08       35u
#define LVB_T10       0xC0B3A010u
#define LVB_N10       34u
#define LVB_T48       0xC0B3AAECu
#define LVB_N48       12u
#define LVB_T70       0xC0B3D670u
#define LVB_N70       36u
#define LVB_CURVES    0xC0971114u           /* curve list: *(+idx*8+4) = table */
#define LVB_KEY       0xC2F19D44u           /* FUN_c02d29e0 ctx0 cache key */
#define LVB_KEY1      0xC2F19D48u           /* ... ctx1's (stills): 11-05 JPEGs kept the previous LUT's tone */
#define LVB_CACHE3    0xC3414D14u           /* FUN_c02cf490's last mode */
#define LVB_CONTRAST  0xC02D25E8u           /* FUN_c02d25e8: {key, value} lookup */
#define LVB_GETTONE   0xC02D2F40u
#define LVB_S124      0xC02C5450u           /* bl FUN_c02d5df0 */
#define LVB_W124      0xEB004266u
#define LVB_S12D      0xC02C5E18u           /* bl FUN_c02d2f40 */
#define LVB_W12D      0xEB003448u
#define LVB_S34       0xC02CC1A0u           /* bl FUN_c02d3a90 in FUN_c02cc130 (MakerNote 0x34) */
#define LVB_W34       0xEB001E3Au
#define LVB_LIVE      0xC02D3A90u           /* PQ object -> its live parameter block (+0x1C / +0x110) */
#define LVB_LIVE_N    0x3Du                 /* words the block holds (FUN_c02d3aa0) */
#define LVB_OFF       0x24u
#define LVB_OFF_BASE  82u
#define LVB_REC       0x18u
#define LVB_WHITE     1918
#define LVB_N         2048u
#define LVB_TMAX      8190
#define LVB_GRID      11u
#define LVB_S         (LVB_GRID * LVB_GRID * LVB_GRID)
#define LVB_Q9        512
#define LVB_CAP       0x400u                /* the resident part (struct lvb_mem); build_sup.LVB_CAP (was 0x1D000: 4 sets) */
/* the joint-fit tables (jft.py, native/jfit.c): YCMAT root+0x28 (RAM .data, filled at boot), CEQ root+0x50,
 * the YGAM writer FUN_c010a160 (Thumb entry hooked: our words after it, ctx 0 only), MakerNote 0x129's root
 * read FUN_c02c55a0 -> FUN_c02d5df0 at 0xC02C55B4 (FUN_c02d2818 indexes root+0x28 there) */
#define LVB_P28       (LVB_ROOT + 0x28u)
#define LVB_T28       0xC2F1AAE8u
#define LVB_N28       35u
#define LVB_R28       0x14u
#define LVB_P50       (LVB_ROOT + 0x50u)
#define LVB_T50       0xC0B3AB1Cu
#define LVB_N50       36u
#define LVB_R50       0x124u
#define LVB_S129      0xC02C55B4u
#define LVB_W129      0xEB00420Du
#define LVB_YGW       0xC010A160u           /* FUN_c010a160, Thumb: push {r4-r7}; mov r4, r0 */
#define LVB_YGW_W     0x4604B4F0u
#define LVB_YG_SHADOW 0x30212140u           /* + (&DAT_c07d4360)[ctx] */
#define LVB_CTXBASE   0xC07D4360u
#define LVB_ROOTW     36u                   /* root words the DNG copy holds (+0x00..+0x8C) */
#define JFT_MAGIC     0x3154464Au           /* 'JFT1' (jft.py) */
#define JFT_BYTES     (64u + 12580u)      /* = jft.HEADER + jft.PAYLOAD (v5: + m1, 20 bytes; v6: + the CKNEE, 16; older are shorter) */
#define JFT_PAY_M1    12544u              /* the payload's m1 (9 x i16 + 2 pad, v5), after the v4 payload (jfit.c JF_PAY_M1) */
#define JFT_PAY_KN    12564u              /* the payload's CKNEE block (v6, jfit.c JF_PAY_KN): u32 on (0 / 1), then the 12 bytes
                                           * of the PQ table record's +4 .. +15 (lvb_knee) */
#define JFT_JFIT      7u                  /* jft.JFIT_VERSION, header +40: the fit that made the file (2026-11-07: v2 =
                                           * jfit.c jf_fit_direct "direct10+144", v3 = "xlm10+144": jf_fit 2 x 20, then
                                           * jf_fit_direct 10 from the cheaper; 11-10: v4 = v3 + the CEQ hue order --
                                           * a v3 file may hold a decreasing hue pair, magenta in greens on camera;
                                           * 11-11: v5 = v4 + the untied refine, M1 (set 1, root+0x10) its own table
                                           * at the payload's end; v6 = v5 + the CKNEE; v7 = v6 with the slope read / 16, not / 19); any other = stale, converted again */
/* The chart block (Bei 2026-11-07, conv.c conv_seal; jft.py CHART_*): appended after the 64 + payload the header's
 * +12 counts, so a v2 file without it stays valid and the ISP read (lvb_jft: the first JFT_BYTES) never sees it.
 *   +0 'JFC1', +4 JFC_BYTES, +8 the match %, +12 the core's fnv (header +56), +16 48 x 0xRRGGBBAA (LC_P00..47:
 *   patch p's target then its fit, the 0 EV ColorChecker as the conversion's overlay left it), +208 fnv1a(+0..+207) */
#define JFC_MAGIC     0x3143464Au           /* 'JFC1' */
#define JFC_BYTES     212u
#define JFT_FILE      (JFT_BYTES + JFC_BYTES)  /* a file with its chart block: what conv.c writes since 11-07 */
#define LVB_MAGIC     0x3142564Cu           /* "LVB1" */
/* CKNEE (JFIT v6; research/imaging-hw/isp-colour-blocks-20260927/blocks-20261104/cknee-write-point.md §4.1, candidate A;
 * the values camera-read 2026-11-11).  No hook: the three PQ parameter objects (Acq = JPG / ctx1, Monit = STILL LV, Movie
 * = CINE LV and MOV / ctx0) each read a table {pointer, count} of 16-byte records ({u32 ISO threshold, then the 12 bytes
 * c010c6c8 parses}) and desc 0x1F's en / up bytes; with en 0 (stock) the ISP gets knee 0x1FF / slope 0x10 = no knee.
 * Ours: the pointers at our own resident record (thr 0), en 1, and up 1 for Monit / Movie (their periodic post rewrites
 * it, so a change shows in LV within a cycle).  Only the four words 10C0/C8/D0/D8; never the second group (10C4..DC). */
#define LVB_KN_ACQ    0xC0B38B84u           /* Acq {table, count}: stock {0xC0B39078, 1} */
#define LVB_KN_MON    0xC0B3F094u           /* Monit: stock {0xC3424E48, 1} */
#define LVB_KN_MOV    0xC0B3F8F4u           /* Movie: stock {0xC34251F0, 1} */
#define LVB_KE_ACQ    0xC0B39B04u           /* desc 0x1F's word +4: en, +5: up, +6 / +7 0 -- stock 0 (Acq's up stays 0: its
                                             * write is forced on every still) */
#define LVB_KE_MON    0xC0B3F6C0u
#define LVB_KE_MOV    0xC0B3FEF8u
#define LVB_KN_MAGIC  0x31454E4Bu           /* "KNE1" */
#define LVB_KN_HOLD   2000u                 /* ms after en goes 0 that up stays 1 (the periodic post writes the stock knee
                                             * into ctx0 meanwhile, ~1 s), before the pointers go back and up goes 0 */
#define LVB_MS        0xC002B920u           /* ms since boot (conv.c MS_CLOCK) */

/* The shown row's tables (borrowed: s->b_set; COL-Share's setter stub writes the root words from crec). */
struct lvb_set {
    u16 tone[3][LVB_N];                     /* read by the ISP: written, then publish() */
    u32 slots_raw[2u * 33u + 2u];           /* 33 {0, table}; the used start is = 4 (mod 8) */
    u32 modes[2u * LVB_N70];
    u8 mat10[LVB_N10 * LVB_REC], mat08[LVB_N08 * LVB_REC];
    i32 mat[9];                             /* set 2 (root+0x08, the chroma): table order, Q9 */
    i32 mat1[9];                            /* set 1 (root+0x10, the luma): = mat unless a v5 .JFT unties it (11-11) */
    u32 shift, keyed, ok, key[7];           /* key: library index, sha[0..7], color, gamma, amount, matrix */
    struct cols_rec crec;                   /* COL-Share's record: +10 +08 +28 +50 +70 +48 +4C, in that order */
    u32 jft, jstats[3];                     /* 1 = from a .JFT; its dE mean/p95/max x100 ("還原度") */
    u32 knee, krec[4], kpad[3];             /* JFIT v6: 1 = the file's CKNEE on; its 16-byte PQ record (thr 0, the file's codes);
                                             * copied to lvb_mem's resident one when shown (lvb_knee: a set is given back) */
    u32 ygam[18];                           /* the YGAM words (jft only) */
    u8 ycm[LVB_N28 * LVB_R28];              /* YCMAT copy, OFF record ours */
    u8 ceq[LVB_N50 * LVB_R50];              /* CEQ copy, OFF TGT ours */
    u32 pad2[0];
};
_Static_assert(sizeof(struct lvb_set) % 32u == 0, "lvb_set keeps the tone tables aligned");

/* The lvb region of the block (cfg->lvb_off): what the ISP / DNG hooks read at any time.  The set and a
 * .JFT being read (s->b_jbuf, lvb_jbuf) are borrowed. */
struct lvb_mem {
    u32 list48[LVB_N48 + 1u];
    u32 shadow[LVB_ROOTW];                  /* the root 0x124 / 0x129 see: the stock root as at the entry */
    struct cols_rec stock;                  /* the stock values: every row that is not the shown one */
    char jpath[48];
    u32 live[LVB_LIVE_N];                   /* the live block 0x34 sees: our matrix sets stock */
    struct {                                /* JFIT v6: the CKNEE (lvb_knee), resident: the PQ objects may read the record
                                             * at any time, and a borrowed set goes back */
        u32 magic, claimed;                 /* LVB_KN_MAGIC; 1 = the 9 words are ours (lvb_install) */
        u32 on, pend, buf, t_off;           /* on: en 1, the pointers at rec[buf]; pend: en 0 since t_off, pointers and up
                                             * still ours (LVB_KN_HOLD) */
        u32 rec[2][4];                      /* the record the ISP reads; a new one goes into the other */
        u32 enables, switches, offs, restores;   /* counts (tests) */
    } kn;
};
_Static_assert(sizeof(struct lvb_mem) <= LVB_CAP, "lvb region");
/* lvb_fit's samples: borrowed for a fit (borrow.c, s->b_fit), never resident (2026-11-07) */
struct lvb_fitmem {
    i32 curve[3][LVB_N];                    /* the fitted curves, Q20 code (monotone) */
    i32 x[LVB_S][3], y[LVB_S][3];           /* samples: camera RGB, target code (Q20) */
    i32 w[LVB_S];                           /* weight, Q16 */
};

static u32 lvb_rd(u32 a) { return *(volatile const u32 *)(uintptr_t)a; }
static void lvb_wr(u32 a, u32 v) { *(volatile u32 *)(uintptr_t)a = v; }
/* the CKNEE's words (JFIT v6, lvb_knee): {table, count}, its stock table, desc 0x1F's en / up word -- Acq, Monit, Movie */
static u32 lvb_kptr(u32 i) { return i == 0u ? LVB_KN_ACQ : i == 1u ? LVB_KN_MON : LVB_KN_MOV; }
static u32 lvb_kstock(u32 i) { return i == 0u ? 0xC0B39078u : i == 1u ? 0xC3424E48u : 0xC34251F0u; }
static u32 lvb_kdesc(u32 i) { return i == 0u ? LVB_KE_ACQ : i == 1u ? LVB_KE_MON : LVB_KE_MOV; }
static void lvb_kb(u32 a, u32 v) { if (*(volatile const u8 *)(uintptr_t)a != (u8)v) *(volatile u8 *)(uintptr_t)a = (u8)v; }
static void lvb_kw(u32 a, u32 v) { if (lvb_rd(a) != v) lvb_wr(a, v); }   /* (a sync that changes nothing writes nothing) */

static struct lvb_mem *lvb_mem(struct lut4_state *s) {
    return s->cfg->lvb_off ? (struct lvb_mem *)((u8 *)s->block + s->cfg->lvb_off) : 0;
}
static struct lvb_set *lvb_held(struct lut4_state *s) { return s->b_set.raw ? (struct lvb_set *)(void *)s->b_set.p : 0; }
/* a .JFT's bytes: borrowed for the read, back right after (lvb_jbuf_done) */
static u8 *lvb_jbuf(struct lut4_state *s) { return lut_borrow(s, &s->b_jbuf, JFT_FILE); }
static void lvb_jbuf_done(struct lut4_state *s) { lut_return(s, &s->b_jbuf); }
static u32 *lvb_slots(struct lvb_set *m) {
    u32 *p = m->slots_raw;
    return ((uintptr_t)p & 7u) == 4u ? p : p + 1;
}

/* ours: matrices, YCMAT, CEQ, base (still one channel), then the list -- clist_stub_mc's order; COL-Share
 * puts stock back in reverse (the list's count before its pointer: never 13 entries on the stock 12) */
static void lvb_rec(struct cols_rec *r, u32 p10, u32 p08, u32 p28, u32 p50, u32 p70, u32 p48, u32 n48) {
    r->w[0].off = 0x10u; r->w[0].val = p10; r->w[1].off = 0x08u; r->w[1].val = p08;
    r->w[2].off = 0x28u; r->w[2].val = p28; r->w[3].off = 0x50u; r->w[3].val = p50;
    r->w[4].off = 0x70u; r->w[4].val = p70; r->w[5].off = 0x48u; r->w[5].val = p48;
    r->w[6].off = 0x4Cu; r->w[6].val = n48;
    for (u32 k = 0; k < 7u; k++) r->w[k]._r = 0;
    r->n = 7u;
}
/* (n << frac) / d, n >= 0, d > 0, n < d << 31 (restoring division) */
static u64 lvb_udivq(u64 n, u64 d, u32 frac) {
    u64 q = 0, r = 0;
    for (u32 i = 64u; i--;) {
        r = r << 1 | (n >> i & 1u); q <<= 1;
        if (r >= d) { r -= d; q |= 1u; }
    }
    for (u32 i = 0; i < frac; i++) {
        r <<= 1; q <<= 1;
        if (r >= d) { r -= d; q |= 1u; }
    }
    return q;
}
static i64 lvb_divq(i64 n, i64 d, u32 frac) {
    u32 neg = (n < 0) != (d < 0);
    u64 q = lvb_udivq(n < 0 ? (u64)-n : (u64)n, d < 0 ? (u64)-d : (u64)d, frac);
    return neg ? -(i64)q : (i64)q;
}

/* camera RGB (Q20) -> XYZ D65 (Q20): rv_color.cam_to_709() then 709 -> XYZ (lv_fit.C2R, M709) */
static void lvb_xyz(const i32 *c, i32 *out) {
    i64 r = c[0], g = c[1], b = c[2];
    out[0] = (i32)((570889 * r + 124374 * g + 301362 * b) >> 20);
    out[1] = (i32)((238996 * r + 755001 * g + 54578 * b) >> 20);
    out[2] = (i32)((76447 * r - 296584 * g + 1362098 * b) >> 20);
}
static i32 lvb_clip(i32 v) { return v < 0 ? 0 : v > Q ? Q : v; }

/* render() count samples of camera RGB in place: buf holds RGB in, clipped code out */
static int lvb_render(struct lut4_state *s, i32 (*buf)[3], u32 count) {
    for (u32 i = 0; i < count; i++) { i32 c[3] = {buf[i][0], buf[i][1], buf[i][2]}; lvb_xyz(c, buf[i]); }
    int rc = lut4_render(s, &buf[0][0], &buf[0][0], count);
    if (rc != OK) return rc;
    for (u32 i = 0; i < count; i++) for (u32 c = 0; c < 3; c++) buf[i][c] = lvb_clip(buf[i][c]);
    return OK;
}

/* the curve at z (Q20 camera value; index z * 1918, clamped like np.interp), and its slope */
static i32 lvb_at(const i32 *g, i64 z, i32 *slope) {
    i64 pos = z * LVB_WHITE;
    if (pos <= 0) { if (slope) *slope = 0; return g[0]; }
    u32 i = (u32)(pos >> 20), f = (u32)(pos & (Q - 1));
    if (i >= LVB_N - 1u) { if (slope) *slope = 0; return g[LVB_N - 1u]; }
    if (slope) {                                    /* np.gradient: central, one-sided at the ends */
        i32 s0 = i ? (g[i + 1] - g[i - 1]) / 2 : g[1] - g[0];
        i32 s1 = i + 2u < LVB_N ? (g[i + 2] - g[i]) / 2 : g[i + 1] - g[i];
        *slope = (i32)(((i64)s0 * (Q - f) + (i64)s1 * f) >> 20);   /* code per index step */
    }
    return (i32)(g[i] + (((i64)(g[i + 1] - g[i]) * f) >> 20));
}
/* the inverse: the camera value (Q20) whose curve value is y (g monotone) */
static i32 lvb_inverse(const i32 *g, i32 y) {
    u32 lo = 0, hi = LVB_N - 1u;
    while (hi - lo > 1u) { u32 mid = (lo + hi) >> 1; if (g[mid] <= y) lo = mid; else hi = mid; }
    i64 span = g[hi] - g[lo], idx = (i64)lo << 20;
    if (span > 0) idx += lvb_divq((i64)(y - g[lo]), span, 20);
    return (i32)lvb_divq(idx, LVB_WHITE, 0);
}

/* [a b; b d] [s0 s1] = [e f], s in Q20 */
static int lvb_solve(i64 a, i64 b, i64 d, i64 e, i64 f, i32 *s0, i32 *s1) {
    i64 big = 0, v[5] = {a, b, d, e, f};
    for (u32 k = 0; k < 5; k++) { i64 m = v[k] < 0 ? -v[k] : v[k]; if (m > big) big = m; }
    while (big >= ((i64)1 << 28)) { for (u32 k = 0; k < 5; k++) v[k] >>= 1; big >>= 1; }
    i64 det = v[0] * v[2] - v[1] * v[1];
    if (det <= 0) return 0;
    i64 n0 = v[3] * v[2] - v[1] * v[4], n1 = v[0] * v[4] - v[1] * v[3];
    *s0 = (i32)lvb_divq(n0, det, 20); *s1 = (i32)lvb_divq(n1, det, 20);
    return 1;
}

/* one row c: y_c = G_c(m0 (x0-x2) + m1 (x1-x2) + x2); m in Q20 */
static void lvb_row(struct lvb_fitmem *M, u32 c, i32 *m) {
    const i32 *g = M->curve[c];
    i32 lo = g[0] + 105, hi = g[LVB_N - 1u] - 105;              /* lv_fit's 1e-4 */
    i64 a = 0, b = 0, d = 0, e = 0, f = 0;
    for (u32 j = 0; j < LVB_S; j++) {
        i32 y = M->y[j][c];
        if (y <= lo || y >= hi) continue;
        i64 w = M->w[j] >> 8, A0 = (M->x[j][0] - M->x[j][2]) >> 4, A1 = (M->x[j][1] - M->x[j][2]) >> 4;
        i64 t = (lvb_inverse(g, y) - M->x[j][2]) >> 4, ww = w * w;
        a += ww * A0 * A0 >> 16; b += ww * A0 * A1 >> 16; d += ww * A1 * A1 >> 16;
        e += ww * A0 * t >> 16; f += ww * A1 * t >> 16;
    }
    if (!lvb_solve(a, b, d, e, f, &m[0], &m[1])) { m[0] = c == 0 ? Q : 0; m[1] = c == 1 ? Q : 0; }
    for (u32 it = 0; it < 12u; it++) {
        a = b = d = e = f = 0;
        for (u32 j = 0; j < LVB_S; j++) {
            i64 A0 = M->x[j][0] - M->x[j][2], A1 = M->x[j][1] - M->x[j][2];
            i64 z = M->x[j][2] + ((m[0] * A0 + m[1] * A1) >> 20);
            i32 slope, G = lvb_at(g, z, &slope);
            i64 w = M->w[j] >> 8;
            i64 r = ((i64)(G - M->y[j][c]) >> 4) * w >> 8;           /* Q16 */
            i64 sl = (i64)slope * LVB_WHITE >> 8;                     /* dG/dz, Q12 */
            i64 J0 = ((A0 >> 4) * sl >> 12) * w >> 8, J1 = ((A1 >> 4) * sl >> 12) * w >> 8;
            a += J0 * J0; b += J0 * J1; d += J1 * J1; e -= J0 * r; f -= J1 * r;
        }
        i64 damp = (a + d) >> 20; if (damp < 1) damp = 1;
        i32 s0, s1;
        if (!lvb_solve(a + damp, b, d + damp, e, f, &s0, &s1)) break;
        m[0] += s0; m[1] += s1;
        if (s0 > -2 && s0 < 2 && s1 > -2 && s1 < 2) break;
    }
}

/* lv_fit.quantise_rows: round, then the largest entry takes the row's remainder */
static void lvb_quantise(const i32 (*M)[3], u32 shift, i32 (*q)[3]) {
    for (u32 r = 0; r < 3; r++) {
        i32 sum = 0, big = 0;
        for (u32 k = 0; k < 3; k++) {
            i64 v = (i64)M[r][k] * LVB_Q9 >> shift;
            q[r][k] = (i32)((v + (1 << 19)) >> 20); sum += q[r][k];
            i32 mag = M[r][k] < 0 ? -M[r][k] : M[r][k], best = M[r][big] < 0 ? -M[r][big] : M[r][big];
            if (mag > best) big = (i32)k;
        }
        q[r][big] += (LVB_Q9 >> shift) - sum;         /* rows sum to 1 / 2^shift: the tone index is 2^shift wider */
    }
}
static void lvb_order(const i32 (*q)[3], int16_t *t) {          /* lv_fit.table_order */
    t[0] = (int16_t)q[0][0]; t[1] = (int16_t)q[0][1]; t[2] = (int16_t)q[0][2];
    t[3] = (int16_t)q[1][1]; t[4] = (int16_t)q[1][0]; t[5] = (int16_t)q[1][2];
    t[6] = (int16_t)q[2][2]; t[7] = (int16_t)q[2][0]; t[8] = (int16_t)q[2][1];
}
static int lvb_in_range(const int16_t *t) {                    /* the hardware halves, then must fit 11 bits */
    for (u32 k = 0; k < 9u; k += 3u) {
        if (t[k] < -1024 || t[k] > 2047) return 0;
        for (u32 j = 1; j < 3u; j++) if (t[k + j] < -1022 || t[k + j] > 2047) return 0;
    }
    return 1;
}

/* a sample's weight (Q16) from its stock-look render: (1 - 2.5 sat / 8)^8 ~ exp(-2.5 sat) */
static i32 lvb_weight(const i32 *y) {
    i32 hi = y[0], lo = hi;
    for (u32 c = 1; c < 3; c++) { if (y[c] > hi) hi = y[c]; if (y[c] < lo) lo = y[c]; }
    i64 sat = hi > 1 ? lvb_divq((i64)(hi - lo), hi, 16) : 0;
    i64 v = 65536 - (sat * 5 >> 4);
    for (u32 k = 0; k < 3; k++) v = v * v >> 16;
    return (i32)v;
}

/* the fit for the loaded entry at its strength: tables and M into the row's set (M: the borrowed samples). */
static int lvb_fit(struct lut4_state *s, struct lvb_fitmem *M, struct lvb_set *S) {
    /* the neutral axis, two batches of 1024 (x holds LVB_S * 3 >= 3072 words) */
    for (u32 half = 0; half < 2u; half++) {
        for (u32 i = 0; i < 1024u; i++) {
            i32 t = (i32)lvb_divq((i64)(half * 1024u + i) << 20, LVB_WHITE, 0);
            M->x[i][0] = M->x[i][1] = M->x[i][2] = t;
        }
        int rc = lvb_render(s, M->x, 1024u);
        if (rc != OK) return rc;
        for (u32 i = 0; i < 1024u; i++) for (u32 c = 0; c < 3; c++) M->curve[c][half * 1024u + i] = M->x[i][c];
    }
    for (u32 c = 0; c < 3; c++) for (u32 i = 1; i < LVB_N; i++)
        if (M->curve[c][i] < M->curve[c][i - 1]) M->curve[c][i] = M->curve[c][i - 1];
    /* samples: CMAX (k/10)^2 per channel, 11^3 */
    for (u32 j = 0; j < LVB_S; j++) {
        u32 k[3] = {j / 121u, j / 11u % 11u, j % 11u};
        for (u32 c = 0; c < 3; c++)
            M->x[j][c] = M->y[j][c] = (i32)lvb_divq((i64)2047 * k[c] * k[c] << 20, (i64)LVB_WHITE * 100, 0);
    }
    u32 amount = s->amount;
    s->amount = 0;                                      /* the weights: saturation of the stock look */
    int rc = lvb_render(s, M->y, LVB_S);
    s->amount = amount;
    if (rc != OK) return rc;
    for (u32 j = 0; j < LVB_S; j++) {
        M->w[j] = lvb_weight(M->y[j]);
        for (u32 c = 0; c < 3; c++) M->y[j][c] = M->x[j][c];
    }
    rc = lvb_render(s, M->y, LVB_S);
    if (rc != OK) return rc;
    i32 F[3][3];
    for (u32 c = 0; c < 3; c++) {
        i32 m[2]; lvb_row(M, c, m);
        F[c][0] = m[0]; F[c][1] = m[1]; F[c][2] = Q - m[0] - m[1];
    }
    i32 q[3][3]; int16_t t[9]; u32 shift = 0;
    for (;; shift++) {
        lvb_quantise((const i32 (*)[3])F, shift, q); lvb_order((const i32 (*)[3])q, t);
        if (lvb_in_range(t) || shift == 2u) break;
    }
    if (!lvb_in_range(t)) return BAD_INPUT;
    for (u32 c = 0; c < 3; c++) for (u32 i = 0; i < LVB_N; i++) {
        u32 at = i << shift; if (at > LVB_N - 1u) at = LVB_N - 1u;
        S->tone[c][i] = (u16)(((i64)M->curve[c][at] * LVB_TMAX + (1 << 19)) >> 20);
    }
    for (u32 k = 0; k < 9u; k++) S->mat[k] = S->mat1[k] = t[k];   /* lvb's own fit: both sets the one matrix */
    S->shift = shift; S->knee = 0;
    return OK;
}

/* stock copies with the OFF entries ours; nothing is pointed at yet */
static int lvb_build(struct lvb_mem *M, struct lvb_set *S) {
    for (u32 g = 0; g < 2u; g++) {
        u8 *dst = g ? S->mat08 : S->mat10;
        u32 src = g ? LVB_T08 : LVB_T10, n = g ? LVB_N08 : LVB_N10, off = n;
        copy(dst, (const void *)(uintptr_t)src, n * LVB_REC);
        for (u32 i = 0; i < n; i++) if (*(u32 *)(dst + i * LVB_REC) == LVB_OFF) off = i;
        if (off == n) return 2;
        int16_t *e = (int16_t *)(dst + off * LVB_REC + 4u);
        if (e[0] != LVB_Q9 || e[1] || e[2] || e[3] != LVB_Q9 || e[4] || e[5] || e[6] != LVB_Q9 || e[7] || e[8]) return 3;
        for (u32 k = 0; k < 9u; k++) e[k] = (int16_t)(g ? S->mat[k] : S->mat1[k]);   /* root+0x10 set 1, root+0x08 set 2 */
    }
    u32 *slots = lvb_slots(S);
    for (u32 j = 0; j < 33u; j++) { slots[2u * j] = 0; slots[2u * j + 1u] = (u32)(uintptr_t)S->tone[j % 3u]; }
    u32 base = ((((u32)(uintptr_t)slots - LVB_CURVES)) >> 3) + 15u;   /* idx = base + 3 contrast + ch */
    copy(S->modes, (const void *)(uintptr_t)LVB_T70, LVB_N70 * 8u);
    u32 hit = 0;
    for (u32 i = 0; i < LVB_N70; i++)
        if (S->modes[2u * i] == LVB_OFF && S->modes[2u * i + 1u] == LVB_OFF_BASE) { S->modes[2u * i + 1u] = base; hit++; }
    if (hit != 1u) return 4;
    copy(M->list48, (const void *)(uintptr_t)LVB_T48, LVB_N48 * 4u);
    M->list48[LVB_N48] = LVB_OFF;
    lvb_rec(&S->crec, (u32)(uintptr_t)S->mat10, (u32)(uintptr_t)S->mat08, S->jft ? (u32)(uintptr_t)S->ycm : LVB_T28,
            S->jft ? (u32)(uintptr_t)S->ceq : LVB_T50, (u32)(uintptr_t)S->modes, (u32)(uintptr_t)M->list48, LVB_N48 + 1u);
    return 0;
}
static struct lvb_set *lvb_prevset(struct lut4_state *s) { return s->b_prev.raw ? (struct lvb_set *)(void *)s->b_prev.p : 0; }
/* The set the roots show now (read from root+0x08: the stub may have moved it), or 0. */
static struct lvb_set *lvb_cur(struct lut4_state *s) {
    u32 p08 = lvb_rd(LVB_P08);
    struct lvb_set *S = lvb_held(s), *V = lvb_prevset(s);
    if (S && S->ok && p08 == (u32)(uintptr_t)S->mat08) return S;
    return V && V->ok && p08 == (u32)(uintptr_t)V->mat08 ? V : 0;
}
static void lvb_stockrec(struct cols_rec *r) {
    lvb_rec(r, LVB_T10, LVB_T08, LVB_T28, LVB_T50, LVB_T70, LVB_T48, LVB_N48);
}

/* the DNG sites, through dng.c's stub: (ctx, p1, p2, p3) */
static USED u32 lvb_root(const struct dng_ctx *d, u32 p1, u32 p2, u32 p3) {
    (void)p1; (void)p2; (void)p3;
    struct lut4_state *s = d->s; struct lvb_mem *M = lvb_mem(s);
    s->lvb.calls124++;
    return lvb_cur(s) ? (u32)(uintptr_t)M->shadow : LVB_ROOT;
}
static USED u32 lvb_tone_slot(const struct dng_ctx *d, u32 p1, u32 mode, u32 p3) {
    struct lut4_state *s = d->s;
    s->lvb.calls12d++;
    if (mode == LVB_OFF && lvb_cur(s)) {            /* stock: base 82, OFF not three-channel */
        u32 root = lvb_rd(p1);
        u32 c = FW(LVB_CONTRAST, u32 (*)(u32, u32, u32, u32))(p1, p3, lvb_rd(root + 0x78u), lvb_rd(root + 0x7Cu));
        return c + LVB_OFF_BASE;
    }
    return FW(LVB_GETTONE, u32 (*)(u32, u32, u32))(p1, mode, p3);
}

/* One live set (9 words, 11-bit signed) is ours: the record's values as they are, or (camera 2026-11-11, a v5
 * .JFT with shift 1: record 441 -> live 220, -109 -> -54; stock OFF stays 512) divided by 2^shift toward zero.
 * +-1 for the rounding. */
static int lvb_s11(u32 x) { x &= 0x7FFu; return (x & 0x400u) ? (int)x - 2048 : (int)x; }
static int lvb_live_is(const u32 *w, const i32 *m, u32 shift) {
    for (u32 j = 0; j <= shift; j++) {
        u32 k = 0;
        while (k < 9u) {
            int v = (int)m[k], q = v < 0 ? -((-v) >> j) : v >> j, d = lvb_s11(w[k]) - q;
            if (d < -1 || d > 1) break;
            k++;
        }
        if (k == 9u) return 1;
    }
    return 0;
}

static USED u32 lvb_live(const struct dng_ctx *d, u32 obj, u32 which, u32 p3) {
    (void)p3;
    struct lut4_state *s = d->s; struct lvb_mem *M = lvb_mem(s);
    u32 live = FW(LVB_LIVE, u32 (*)(u32, u32))(obj, which);
    s->lvb.calls34++;
    const struct lvb_set *S = lvb_cur(s);
    if (!S) return live;
    copy(M->live, (const void *)(uintptr_t)live, sizeof M->live);
    for (u32 at = 0; at + 9u <= LVB_LIVE_N; at++) {       /* each set as the hardware holds it: 11 bits; */
        if (!lvb_live_is(M->live + at, S->mat, S->shift) && !lvb_live_is(M->live + at, S->mat1, S->shift))
            continue;                                      /* set 2 or (v5, untied) set 1 */
        for (u32 k = 0; k < 9u; k++) M->live[at + k] = (k % 3u) ? 0u : (u32)LVB_Q9;
        at += 8u;
    }
    return (u32)(uintptr_t)M->live;
}

/* No power-off routine of our own any more (camera 2026-11-08: XC_PowerOffMgr's lists were full with
 * COL-Share's object added, the registration failed and lvb never became ready).  The root words and the
 * PQ caches are COL-Share's (journal + cs_poweroff); our own sites go back by the loader's journal; after
 * a power-off COL-Share writes no record, so a late refresh changes nothing on the ISP.  lvb.poff / poffs
 * stay in the struct, unused (the layout the tests read). */

/* The YGAM writer FUN_c010a160(struct, ctx) is entered here (site B.W -> cave veneer -> this): run the original
 * through its trampoline (the two moved instructions, then fn+4), then lvb_ygam_post(ctx) on an 8-aligned stack.
 * The trampoline and post addresses are words in this code, set at the entry (no symbol references). */
__asm__(
"   .thumb\n"
"   .global lvb_ygam_stub\n"
"lvb_ygam_stub:\n"
"   push    {r1, lr}\n"
"   ldr     r2, 1f\n"
"   blx     r2\n"                       /* the original: r0, r1 as the caller gave them */
"   pop     {r1, r2}\n"
"   push    {r0, r2}\n"
"   mov     r0, r1\n"
"   mov     r3, sp\n"
"   bic     r2, r3, #7\n"
"   mov     sp, r2\n"
"   sub     sp, #8\n"
"   str     r3, [sp]\n"
"   ldr     r2, 2f\n"
"   blx     r2\n"                       /* lvb_ygam_post(ctx) */
"   ldr     r3, [sp]\n"
"   mov     sp, r3\n"
"   pop     {r0, pc}\n"
"   .balign 4\n"
"   .global lvb_ygam_words\n"
"lvb_ygam_words:\n"
"1: .word 0\n"                          /* the trampoline (Thumb, +1) */
"2: .word 0\n"                          /* lvb_ygam_post (Thumb, +1) */
"   .thumb\n");
extern const u8 lvb_ygam_stub[], lvb_ygam_words[];

static u32 lvb_bw(u32 site, u32 to) {                  /* Thumb B.W site -> to (fpui_stock fst_hook_fv) */
    u32 off = to - (site + 4u), s = off >> 31, i1 = (off >> 23) & 1u, i2 = (off >> 22) & 1u;
    u32 j1 = (1u ^ i1) ^ s, j2 = (1u ^ i2) ^ s;
    u32 hw1 = 0xF000u | s << 10 | ((off >> 12) & 0x3FFu), hw2 = 0x9000u | j1 << 13 | j2 << 11 | ((off >> 1) & 0x7FFu);
    return hw1 | hw2 << 16;
}

/* after the stock YGAM write: ctx 0 (LV) or 1 (stills; 11-05 JPEGs came out red without it -- the joint fit
 * counts on YGAM) and a row from a .JFT on -> its words */
static USED void lvb_ygam_post(u32 ctx) {
    struct lut4_state *s = color_ctx();
    ctx &= 0xFFu;
    if (!s || !s->lvb.ready || ctx > 1u) return;
    const struct lvb_set *S = lvb_cur(s);
    if (!S || !S->jft) return;
    u32 base = lvb_rd(LVB_CTXBASE + 4u * ctx) + LVB_YG_SHADOW;
    for (u32 k = 0; k < 18u; k++) lvb_wr(base + 4u * k, S->ygam[k]);
    s->lvb.ygam_posts++;
}

static u32 lvb_fnv(const u8 *p, u32 n) { u32 h = 2166136261u; for (u32 i = 0; i < n; i++) h = (h ^ p[i]) * 16777619u; return h; }
static int16_t lvb_s16(const u8 *p) { return (int16_t)(p[0] | p[1] << 8); }
static u32 lvb_u16(const u8 *p) { return (u32)(p[0] | p[1] << 8); }
static u32 lvb_u32(const u8 *p) { return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24; }

/* \fpSup\LUTDATA\<sha[:8] hex>.JFT into p (>= 36 bytes); dir_only: just the folder.  The sup's own
 * files stay out of \fpSup\LUT\, which is the user's cubes alone (2026-11-06) */
static void lvb_jpath(char *p, const u8 *sha, int dir_only) {
    const char *pre = "\\fpSup\\LUTDATA\\";
    u32 n = 0;
    while (pre[n]) { p[n] = pre[n]; n++; }
    if (dir_only) { p[n - 1u] = 0; return; }
    /* 2026-11-10: a camera identity ("CAM1" + size, ..., +20 the name's fnv: import.c imp_identity) by its size AND
     * name -- sha[0..7] alone named two cubes of one size (Resolve's 33^3 exports) the same file: one LUT's tables
     * under the other's row.  Others (host sha256) as before.  jft.py path_for: the same rule. */
    u32 cam = sha[0] == 'C' && sha[1] == 'A' && sha[2] == 'M' && sha[3] == '1';
    for (u32 k = 0; k < 8u; k++) for (u32 h = 0; h < 2u; h++) {
        u32 i = cam ? (k < 4u ? 4u + k : 16u + k) : k;
        u32 d = (sha[i] >> (h ? 0 : 4)) & 15u; p[n++] = (char)(d < 10u ? '0' + d : 'a' + d - 10u);
    }
    p[n++] = '.'; p[n++] = 'J'; p[n++] = 'F'; p[n++] = 'T'; p[n] = 0;
}
/* The row's .JFT (jft.py, conv.c) into its set: 1 = used, 0 = none / stale / damaged */
static int lvb_jft_in(struct lut4_state *s, struct lvb_mem *M, struct lvb_set *S, const struct lib_entry *e, const u8 *b);
static int lvb_jft(struct lut4_state *s, struct lvb_mem *M, struct lvb_set *S, const struct lib_entry *e) {
    lvb_jpath(M->jpath, e->sha, 0);
    u32 *why = &s->lvb.jft_why[0];
    *why = 0;
    u8 *b = lvb_jbuf(s);
    if (!b) return *why = 0x20000u, 0;                   /* 2xxxx: no buffer */
    int got = s->svc->file_read(s->svc, M->jpath, b, JFT_BYTES);
    int used = got == (int)JFT_BYTES ? lvb_jft_in(s, M, S, e, b) : (*why = 0x10000u | ((u32)got & 0xFFFFu), 0);   /* 1xxxx: read */
    lvb_jbuf_done(s);
    return used;
}
static int lvb_jft_in(struct lut4_state *s, struct lvb_mem *M, struct lvb_set *S, const struct lib_entry *e, const u8 *b) {
    (void)M;
    u32 *why = &s->lvb.jft_why[0];
    const u8 *y = b + 64u;
    if (lvb_u32(b) != JFT_MAGIC || lvb_u32(b + 4) != 1u || lvb_u32(b + 8) != 64u || lvb_u32(b + 12) != JFT_BYTES) return *why = 2, 0;
    for (u32 i = 0; i < 8u; i++) if (b[16 + i] != e->sha[i]) return *why = 3, 0;
    if (lvb_u32(b + 24) != e->color || lvb_u32(b + 28) != e->gamma || lvb_u32(b + 32) != e->amount ||
        lvb_u32(b + 36) != e->matrix || lvb_u32(b + 40) != JFT_JFIT) return *why = 4, 0;
    if (lvb_fnv(y, JFT_BYTES - 64u) != lvb_u32(b + 56)) return *why = 5, 0;
    u32 shift = lvb_u32(y);
    if (shift > 2u) return *why = 6, 0;
    S->shift = shift;
    for (u32 k = 0; k < 9u; k++) { S->mat[k] = lvb_s16(y + 4 + 2 * k); S->mat1[k] = lvb_s16(y + JFT_PAY_M1 + 2 * k); }
    for (u32 c = 0; c < 3u; c++) for (u32 i = 0; i < LVB_N; i++) S->tone[c][i] = (u16)lvb_u16(y + 24 + 2 * (c * LVB_N + i));
    const u8 *yc = y + 24 + 6 * LVB_N, *cq = yc + 16, *yg = cq + 144;
    copy(S->ycm, (const void *)(uintptr_t)LVB_T28, LVB_N28 * LVB_R28);           /* the live YCMAT table (boot-filled Y) */
    u32 at = LVB_N28;
    for (u32 i = 0; i < LVB_N28; i++) if (lvb_u32(S->ycm + i * LVB_R28) == LVB_OFF) at = i;
    if (at == LVB_N28) return *why = 7, 0;
    copy(S->ycm + at * LVB_R28 + 4u, yc, 14u);
    copy(S->ceq, (const void *)(uintptr_t)LVB_T50, LVB_N50 * LVB_R50);
    at = LVB_N50;
    for (u32 i = 0; i < LVB_N50; i++) if (lvb_u32(S->ceq + i * LVB_R50) == LVB_OFF) at = i;
    if (at == LVB_N50) return *why = 8, 0;
    copy(S->ceq + at * LVB_R50 + 4u + 144u, cq, 144u);
    for (u32 k = 0; k < 18u; k++) S->ygam[k] = lvb_u32(yg + 4 * k);
    for (u32 k = 0; k < 3u; k++) S->jstats[k] = lvb_u32(b + 44 + 4 * k);
    {   /* JFIT v6: the CKNEE -- off, or the record's codes within their 9 / 5 bits */
        const u8 *kb = y + JFT_PAY_KN; u32 on = lvb_u32(kb);
        if (on > 1u) return *why = 9, 0;
        S->knee = 0;
        if (on) {
            for (u32 h = 0; h < 2u; h++)                              /* +4 kA +6 kC (+10 kB +12 kD): 9 bits; +8 sA +9 sC ...: 5 */
                if (lvb_u16(kb + 4 + 6 * h) > 0x1FFu || lvb_u16(kb + 6 + 6 * h) > 0x1FFu || kb[8 + 6 * h] > 31u || kb[9 + 6 * h] > 31u)
                    return *why = 9, 0;
            S->krec[0] = 0;                                           /* thr 0: every ISO (a key below it would assert) */
            for (u32 k = 1; k < 4u; k++) S->krec[k] = lvb_u32(kb + 4 * k);
            S->knee = 1;
        }
    }
    S->jft = 1;
    return 1;
}

/* From lc_attached (cols.c): claim our own sites -- MakerNote 0x124 / 0x12D / 0x34 / 0x129 and the YGAM
 * writer (one refusal: nothing written; the root words are COL-Share's), veneers, patches.  0 = ready. */
static int lvb_install(struct lut4_state *s) {
    const struct sl_svc *svc = s->svc;
    struct lvb_mem *M = lvb_mem(s);
    s->lvb.magic = LVB_MAGIC;
    if (!M || svc->version < 6u) return 1;
    if (!s->cols.attached) return 2;                     /* no COL-Share: no LUT row would turn it on */
    u32 stock[2];
    if (lvb_rd(LVB_S124) != LVB_W124 || lvb_rd(LVB_S12D) != LVB_W12D || lvb_rd(LVB_S34) != LVB_W34) return 4;
    if (lvb_rd(LVB_S129) != LVB_W129 || lvb_rd(LVB_YGW) != LVB_YGW_W) return 4;
    for (u32 k = 0; k < LVB_ROOTW; k++)                  /* the DNG's root: all stock (COL-Share's snapshot) */
        M->shadow[k] = s->cols.api->stock_root ? s->cols.api->stock_root[k] : lvb_rd(LVB_ROOT + 4u * k);
    stock[0] = LVB_W124; if (svc->claim(svc, LVB_S124, 4u, stock, SL_EXCL) != SL_OK) return 5;
    stock[0] = LVB_W12D; if (svc->claim(svc, LVB_S12D, 4u, stock, SL_EXCL) != SL_OK) return 5;
    stock[0] = LVB_W34; if (svc->claim(svc, LVB_S34, 4u, stock, SL_EXCL) != SL_OK) return 5;
    stock[0] = LVB_W129; if (svc->claim(svc, LVB_S129, 4u, stock, SL_EXCL) != SL_OK) return 5;
    stock[0] = LVB_YGW_W; if (svc->claim(svc, LVB_YGW, 4u, stock, SL_EXCL) != SL_OK) return 5;
    {   /* JFIT v6, the CKNEE: the three desc 0x1F words (en, up) first, then the three {table, count} -- the loader's
         * journal writes back in claim order, so at power-off en is 0 before a pointer goes back to the stock record
         * (with en 1 the stock record's zeros would be knee 0 / slope 0).  A refusal leaves only the CKNEE stock. */
        u32 ok = 1;
        for (u32 i = 0; i < 3u && ok; i++) { stock[0] = 0; ok = svc->claim(svc, lvb_kdesc(i), 4u, stock, SL_EXCL) == SL_OK; }
        for (u32 i = 0; i < 3u && ok; i++) {
            stock[0] = lvb_kstock(i); stock[1] = 1u;
            ok = svc->claim(svc, lvb_kptr(i), 8u, stock, SL_EXCL) == SL_OK;
        }
        M->kn.magic = LVB_KN_MAGIC; M->kn.claimed = ok; M->kn.on = M->kn.pend = M->kn.buf = 0;
    }
    u32 v = svc->cave_alloc(svc, 64u + 24u);
    if (!v || (v & 7u)) return 6;
    for (u32 k = 0; k < 4u; k++) {
        struct dng_ctx *c = &s->lvb.ctx[k];
        c->s = s; c->wrap = (u32)(uintptr_t)(k == 2u ? (void *)&lvb_live : k == 1u ? (void *)&lvb_tone_slot : (void *)&lvb_root);
        c->original = k == 2u ? LVB_LIVE : k == 1u ? LVB_GETTONE : 0xC02D5DF0u; c->kind = 0x10u + k;   /* 3: 0x129's root */
        lvb_wr(v + 16u * k, VENEER_IP); lvb_wr(v + 16u * k + 4u, VENEER_PC);
        lvb_wr(v + 16u * k + 8u, (u32)(uintptr_t)c); lvb_wr(v + 16u * k + 12u, (u32)(uintptr_t)dng_stub & ~1u);
    }
    {   /* YGAM: cave veneer (Thumb ldr.w pc, [pc]) and trampoline (push {r4-r7}; mov r4, r0; ldr.w pc, [pc]; fn+4) */
        u32 ve = v + 64u, tr = v + 72u;
        lvb_wr(ve, 0xF000F8DFu); lvb_wr(ve + 4u, ((u32)(uintptr_t)lvb_ygam_stub & ~1u) | 1u);
        lvb_wr(tr, LVB_YGW_W); lvb_wr(tr + 4u, 0xF000F8DFu); lvb_wr(tr + 8u, (LVB_YGW + 4u) | 1u);
        u32 w = (u32)(uintptr_t)lvb_ygam_words & ~1u;
        lvb_wr(w, tr | 1u); lvb_wr(w + 4u, ((u32)(uintptr_t)&lvb_ygam_post & ~1u) | 1u);
    }
    svc->publish(svc);
    lvb_wr(LVB_S124, cl_bl(LVB_S124, v)); lvb_wr(LVB_S12D, cl_bl(LVB_S12D, v + 16u));
    lvb_wr(LVB_S34, cl_bl(LVB_S34, v + 32u)); lvb_wr(LVB_S129, cl_bl(LVB_S129, v + 48u));
    lvb_wr(LVB_YGW, lvb_bw(LVB_YGW, v + 64u));
    svc->publish(svc);
    s->lvb.ready = 1;
    return 0;
}

/* JFIT v6: the CKNEE follows the set the roots show (lvb_cur, root+0x08), from the UI thread only (the one writer:
 * lvb_refresh, lvb_preview -- every place a record moves).  On: our record first (into the one the ISP is not reading),
 * published, then the three pointers, then en = 1, up = 1 (Monit, Movie).  Off: en = 0 first -- the stock path writes
 * 0x1FF / 0x10, whatever the pointer -- with up still 1 so the periodic post puts that into ctx0; at a later call, at
 * least LVB_KN_HOLD after, the stock pointers back, then up = 0.  The pointers only ever point at the stock record or
 * one of ours (resident, thr 0), and en is 1 only while they point at ours: never en 1 on the stock zeros. */
static void lvb_knee(struct lut4_state *s) {
    struct lvb_mem *M = lvb_mem(s);
    if (!M || M->kn.magic != LVB_KN_MAGIC || !M->kn.claimed) return;
    const struct lvb_set *S = lvb_cur(s);
    if (S && S->jft && S->knee) {
        u32 b = M->kn.buf;
        if (!(M->kn.on || M->kn.pend) || !library_same(M->kn.rec[b], S->krec, 16u)) {
            if (M->kn.on || M->kn.pend) b ^= 1u;                      /* the pointers may be on rec[buf]: the other one */
            copy(M->kn.rec[b], S->krec, 16u);
            s->svc->publish(s->svc);
            M->kn.switches++;
        }
        u32 at = (u32)(uintptr_t)M->kn.rec[b];
        for (u32 i = 0; i < 3u; i++) { lvb_kw(lvb_kptr(i), at); lvb_kw(lvb_kptr(i) + 4u, 1u); }
        __asm__ volatile("dmb" ::: "memory");
        for (u32 i = 0; i < 3u; i++) lvb_kb(lvb_kdesc(i), 1u);
        lvb_kb(LVB_KE_MON + 1u, 1u); lvb_kb(LVB_KE_MOV + 1u, 1u);
        if (!M->kn.on) M->kn.enables++;
        M->kn.buf = b; M->kn.on = 1; M->kn.pend = 0;
        return;
    }
    if (M->kn.on) {
        for (u32 i = 0; i < 3u; i++) lvb_kb(lvb_kdesc(i), 0u);
        M->kn.on = 0; M->kn.pend = 1; M->kn.offs++;
        M->kn.t_off = FW(LVB_MS, u32 (*)(void))();
        return;
    }
    if (M->kn.pend && FW(LVB_MS, u32 (*)(void))() - M->kn.t_off >= LVB_KN_HOLD) {
        for (u32 i = 0; i < 3u; i++) { lvb_kw(lvb_kptr(i), lvb_kstock(i)); lvb_kw(lvb_kptr(i) + 4u, 1u); }
        __asm__ volatile("dmb" ::: "memory");
        lvb_kb(LVB_KE_MON + 1u, 0u); lvb_kb(LVB_KE_MOV + 1u, 0u);
        M->kn.pend = 0; M->kn.restores++;
    }
}

/* After every state change (choices(), cols_sync(), a pick): the set of the active row -- made if the row,
 * its colour, gamma, strength or matrix moved -- and the records: that row's set, every other row stock.
 * A set comes from the row's .JFT; a row without a current one (its strength moved since the conversion:
 * the file's key holds the strength, conv_ok's does not) is fitted from its cube, loaded into a borrowed asset
 * area with borrowed samples (borrow.c) -- both returned before this returns.  The set itself is borrowed first
 * (small, before the big areas take the first hole) and kept while it is the shown one; the previous set is
 * given back only after COL-Share holds no record in it (its root then points at the new set or stock).
 * Never while recording. */
static int lvb_borrow_fit(struct lut4_state *s) {               /* the largest first: it takes the first big hole */
    if (!lut_borrow(s, &s->b_asset, s->cfg->asset_cap)) return 0;
    if (lut_borrow(s, &s->b_fit, sizeof(struct lvb_fitmem))) return 1;
    lut_return(s, &s->b_asset);
    return 0;
}
static void lvb_refresh_sets(struct lut4_state *s);
static void lvb_refresh(struct lut4_state *s) { lvb_refresh_sets(s); lvb_knee(s); }   /* the CKNEE after the records */
static void lvb_refresh_sets(struct lut4_state *s) {
    struct lvb_mem *M = lvb_mem(s);
    struct lut_cols *L = &s->cols;
    if (!s->lvb.ready || !M || !s->library || !L->attached || library_busy()) return;
    if (s->b_asset.raw || s->b_fit.raw) return;         /* inside someone's load (none does): theirs, not ours to return */
    u32 active = s->library->h.active, n = L->n, err = 0, row = 0;
    for (u32 j = 0; j < n; j++) if (L->map[j] == active) row = j + 1u;
    /* the active entry as it runs now (lut4_strength moves s->amount alone), put back after */
    u32 k_color = s->color, k_gamma = s->gamma, k_amount = s->amount;
    int k_status = s->file_status;
    struct lvb_set *S = lvb_held(s), *V = lvb_prevset(s), *keep = 0, *N = 0;
    struct lut_area nb = {0, 0, 0};
    if (row) {
        const struct lib_entry *e = &s->library->entries[active];
        u32 now = s->file_status == OK;
        u32 key[7] = {active, 0, 0, now ? k_color : e->color, now ? k_gamma : e->gamma, now ? k_amount : e->amount, e->matrix};
        copy(&key[1], e->sha, 8u);
        if (S && S->keyed && library_same(key, S->key, sizeof key)) keep = S->ok ? S : 0;   /* held already */
        else if (V && V->ok && library_same(key, V->key, sizeof key)) keep = V;   /* the cursor's preview: picked */
        else if (s->lvb.failed && library_same(key, s->lvb.fail_key, sizeof key)) err = s->lvb.result;   /* failed: not again */
        else if (!(N = (struct lvb_set *)(void *)lut_borrow(s, &nb, sizeof(struct lvb_set)))) err = 0x600u;   /* again next time */
        else {
            s->lvb.sets++;
            copy(N->key, key, sizeof key); N->keyed = 1; N->ok = 0; N->jft = 0; N->knee = 0;
            if (lvb_jft(s, M, N, e)) {                     /* converted: the file's tables, no fit */
                int rc = lvb_build(M, N);
                if (rc) { err = (u32)(0x400 | rc); N->jft = 0; } else { N->ok = 1; s->lvb.jfts++; }
            } else if (!lvb_borrow_fit(s)) err = 0x500u;    /* no area: again at the next refresh */
            else {
                int rc = library_load_index(s, active);
                if (rc != OK) err = (u32)(0x300 | (rc & 0xFF));
                else {
                    s->color = key[3]; s->gamma = key[4]; s->amount = key[5];
                    s->lvb.fits++;
                    rc = lvb_fit(s, (struct lvb_fitmem *)(void *)s->b_fit.p, N);
                    if (rc != OK) err = (u32)(0x100 | (rc & 0xFF));
                    else if ((rc = lvb_build(M, N)) != 0) err = (u32)(0x200 | rc);
                    else N->ok = 1;
                }
            }
            if (N->ok) keep = N;
            else if (err != 0x500u) { copy(s->lvb.fail_key, key, sizeof key); s->lvb.failed = 1; }   /* done, or failed: not again */
        }
    }
    if (keep) s->lvb.failed = 0;
    lut_return(s, &s->b_asset); lut_return(s, &s->b_fit);
    s->asset = 0; s->file_status = k_status;
    s->color = k_color; s->gamma = k_gamma; s->amount = k_amount;
    lvb_stockrec(&M->stock);
    const struct cols_api *api = L->api;
    for (u32 k = 0; k < L->nrecd; k++) {                 /* keys no longer rows: their records withdrawn */
        u32 still = 0;
        for (u32 j = 0; j < n; j++) still |= L->map[j] == L->recd[k];
        if (!still) api->set_record(api, API_ID, L->recd[k], 0);
    }
    s->svc->publish(s->svc);                             /* the tables reach memory before the ISP is told */
    for (u32 j = 0; j < n; j++) {                        /* the active row first: the root moves off the old set */
        u32 jj = row ? (j == 0 ? row - 1u : j <= row - 1u ? j - 1u : j) : j;
        api->set_record(api, API_ID, L->map[jj], keep && jj + 1u == row ? &keep->crec : &M->stock);
        L->recd[j] = L->map[jj];
    }
    L->nrecd = n;
    /* nothing of COL-Share's points into a set we do not keep now: give it back */
    if (S && S != keep) { lut_return(s, &s->b_set); s->lvb.set_returns++; }
    if (V && V == keep) { s->b_set = s->b_prev; s->b_prev.raw = 0; s->b_prev.p = 0; s->b_prev.n = 0; }   /* promoted */
    else if (V) { lut_return(s, &s->b_prev); s->lvb.set_returns++; }
    if (N && N != keep) { lut_return(s, &nb); s->lvb.set_returns++; }
    if (N && N == keep) s->b_set = nb;
    s->lvb.keyed = 1;
    u32 sup = 0, key = COLS_NONE, shown = 0;
    if (api->shown(api, &sup, &key) && sup == API_ID)
        for (u32 j = 0; j < n; j++) if (L->map[j] == key) shown = j + 1u;
    s->lvb.installed = shown && shown == row && keep;
    if (s->lvb.installed) { copy(s->lvb.mat, keep->mat, sizeof keep->mat); s->lvb.shift = keep->shift; }
    if (err) s->lvb.result = err;                       /* the last failure stays until a row shows */
    else if (!row) s->lvb.result = 0;
    if (s->lvb.installed) s->lvb.result = 1;
}

/* COL-Share's v3 preview (cs_cursor, after the setter's root write; UI thread, menu open, not recording): the
 * cursor is on our row `key` (a library index) or off our rows (COLS_NONE).  The row's set from its .JFT only
 * (a fit takes seconds: such a row stays stock until it is picked), into a new borrowed area, handed to COL-Share
 * (the root moves to it at once); the previous preview set goes back after its record is the stock one.  Held at
 * most: the active row's set + this one (+ the new one while it is made).  Cost a step: one .JFT read (12.8 KB)
 * and ~26 KB of table copies (test_capacity counts the instructions). */
static void lvb_preview_set(struct lut4_state *s, u32 key);
static void lvb_preview(struct lut4_state *s, u32 key) { lvb_preview_set(s, key); lvb_knee(s); }
static void lvb_preview_set(struct lut4_state *s, u32 key) {
    struct lvb_mem *M = lvb_mem(s);
    struct lut_cols *L = &s->cols;
    if (!s->lvb.ready || !M || !s->library || !L->attached || library_busy()) return;
    if (s->b_asset.raw || s->b_fit.raw) return;
    const struct cols_api *api = L->api;
    struct lvb_set *S = lvb_held(s), *V = lvb_prevset(s), *N = 0;
    struct lut_area nb = {0, 0, 0};
    u32 want = key != COLS_NONE && key < s->library->h.count && lc_row_of(s, key);
    u32 k[7] = {0, 0, 0, 0, 0, 0, 0};
    if (want) {
        const struct lib_entry *e = &s->library->entries[key];
        k[0] = key; copy(&k[1], e->sha, 8u); k[3] = e->color; k[4] = e->gamma; k[5] = e->amount; k[6] = e->matrix;
        if (S && S->ok && library_same(k, S->key, sizeof k)) want = 0;          /* the active row: its set is shown */
        else if (V && V->ok && library_same(k, V->key, sizeof k)) return;     /* shown already */
        else if (!(N = (struct lvb_set *)(void *)lut_borrow(s, &nb, sizeof(struct lvb_set)))) { s->lvb.preview_fail++; want = 0; }
        else {
            copy(N->key, k, sizeof k); N->keyed = 1; N->ok = 0; N->jft = 0; N->knee = 0;
            if (lvb_jft(s, M, N, e) && !lvb_build(M, N)) {
                N->ok = 1; s->lvb.previews++; s->lvb.jfts++;
                s->svc->publish(s->svc);                  /* the tables reach memory before the ISP is told */
                api->set_record(api, API_ID, key, &N->crec);   /* the cursor's row (active in COL-Share): shown now */
            } else { s->lvb.preview_fail++; lut_return(s, &nb); N = 0; }
        }
    }
    if (V) {                                              /* the old preview: stock record first, then back */
        u32 vk = V->key[0];
        if (lc_row_of(s, vk)) api->set_record(api, API_ID, vk, &M->stock);
        lut_return(s, &s->b_prev); s->lvb.set_returns++;
    }
    if (N) s->b_prev = nb;
}
