/* SensorLab-IMX410 QS client (sup_id SL41) v0.2.0test, stage "select and display": DC, RES, FPS, RECIPE and
 * FORMAT on the Quick Set page, through the QS container (projects/qs-container/qsc.h, API 4, v0.2.2).
 * Nothing is installed in the sensor or the ISP yet: sq_apply() is the hook point for that step.
 *
 * Behaviour = projects/sensorlab-imx410/preview/dcres.html (the spec Bei signed off) and QS_DC_RES_SPEC.md: this file
 * is that page's logic line for line (the names in the comments are the page's), with every JavaScript double
 * reproduced exactly -- the core's integer IEEE emulation (dratio / dmul / ddiv_int, js_fixed_d = toFixed / Math.round)
 * or an exact rational where the double cannot differ -- so the tests can require the page's visible state, string
 * for string (test_slqs.py runs the page in node).
 *
 *   recipes  core_qualities_tol(DC, RES, uncapped, 2 %) on the camera for any DC x RES (the C core, bit for bit
 *            quality.py), kept per cell in a 4-entry cache.  A recipe: hm, VMAX floor lo, merge mh x mv, AD,
 *            ISP bins, sensor crop scw x sch -> sw x sh, its own visible size, RWZM, rolling shutter.
 *   DC       presets OG..SQ, WIDTH / HEIGHT / RATIO (locked aspect remembered at lock / preset time)
 *   RES      clean ratios + 1K..6K (+ FHD / UHD on HD), K label remembered by name, ratio kept on small DCs,
 *            a custom RES kept per crop; shows the selected recipe's visible size (yellow when short)
 *   FPS      common rates to 1000 (unreachable grey and skipped), recipe maxima marked, fine mode (AEL) on the
 *            VMAX grid of every preset recipe, one tuned rate kept
 *   RECIPE   presets (ISP 1x1) with RS; sub-QS ADC, SENSOR HDC / VDC / HBIN / VBIN, ISP HBIN / VBIN (kernels,
 *            SOFT / STD shared); the user's choice kept while the effective recipe falls back
 *   FORMAT   DNG 12 / 14 bit from the effective recipe's AD; MOV grey
 * All five are locked while recording (QSC_F_LOCK_REC).  The selection lives in this BIN's own record, written at
 * the container's leave() (a layout load), never per dial step, never creating the file.
 *
 * Built as one unit with the core (#include core.c); build_slqs.py moves the read-only data into .text (-fropi,
 * PC-relative) because the loader maps .text only.  No division operator: udiv64.  Firmware Ver.5.02. */
#include "core.c"
#include "sloader4.h"
#include "qsc.h"

typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
typedef int32_t s32;
#define USED __attribute__((used))
#define W(a) (*(volatile u32 *)(uintptr_t)(a))

#define F_CTOR  0xC0365E90u
#define F_OPEN  0xC0365FB0u
#define F_READ  0xC0366060u
#define F_WRITE 0xC03660E8u
#define F_SEEK  0xC03661E0u
#define F_CLOSE 0xC0366020u
#define F_DTOR  0xC0365ED0u
#define FO_BYTES 0x800u
#define MOV_SELECTOR   0xC347D1D4u            /* recording (the container's busy()) */
#define MOVREC_DEFAULT 0xC347E08Fu
#define MOVREC_SEL21   0xC3476609u
#define XMP_FOBJ_PTR   0xC358E140u
#define MOV_ACTIVE     0xC35A952Cu

#define CFG_MAGIC 0x32344C53u                 /* "SL42" */
#define REC_MAGIC 0x32514C53u                 /* "SLQ2" */
#define REC_VERSION 2u
#define N_DC    6u
#define N_RAT   5u
#define N_KL    9u                            /* 1K..6K (7), UHD, FHD */
#define N_MEM   8u
#define N_LIST  16u
#define N_STD   29u
#define N_FPS   (N_STD + 2u * MAXR + 2u)
#define MAXR    80u                           /* recipes per DC x RES kept (the core gives at most CORE_MAX_QUAL) */
#define N_CACHE 4u
#define WMIN 256
#define HMIN 144
#define WMAX 6048
#define HMAX 4040
#define TXT 64u
#define FT 64u
#define VMAX_MAX CD_VMAX_MAX
#define TOL_NUM 1u                            /* the visible tolerance: 2 % (QS_DC_RES_SPEC 看到的尺寸與寬容) */
#define TOL_DEN 50u

enum { F_DC, F_RES, F_FPS, F_RECIPE, F_FORMAT, N_FN };
enum { K_AD, K_SCW, K_SCH, K_MH, K_MV, K_HB, K_VB, N_PARAM };   /* PARAMS order (ADC second, Bei 10-29) */

/* ---------------------------------------------------------------------------------------------- tables */
static const u16 DCW[N_DC] = {6048, 6048, 4192, 3952, 2096, 4032};
static const u16 DCH[N_DC] = {4040, 3402, 2358, 2624, 1240, 4032};
static const char DCN[N_DC][6] = {"OG", "HD", "S35", "APS-C", "S16", "SQ"};
static const u8 RAT_N[N_RAT] = {1, 2, 1, 1, 1}, RAT_D[N_RAT] = {1, 3, 2, 3, 6};
static const u16 KL_W[N_KL] = {1024, 2048, 3072, 3584, 4096, 5120, 6144, 3840, 1920};
static const u16 KL_H[N_KL] = {0, 0, 0, 0, 0, 0, 0, 2160, 1080};
static const char KL_N[N_KL][5] = {"1K", "2K", "3K", "3.5K", "4K", "5K", "6K", "UHD", "FHD"};
static const u8 DIVK[8] = {1, 2, 3, 4, 5, 6, 8, 12};
/* STD: the common rates, as the page writes them (String(f)) and as exact rationals n / d */
static const u32 STD_N[N_STD] = {23976, 24, 25, 2997, 30, 47952, 48, 50, 5994, 60, 72, 90, 96, 100, 11988, 120, 144,
                                 150, 180, 200, 23976, 240, 300, 360, 400, 480, 500, 600, 1000};
static const u16 STD_D[N_STD] = {1000, 1, 1, 100, 1, 1000, 1, 1, 100, 1, 1, 1, 1, 1, 100, 1, 1, 1, 1, 1, 100, 1, 1, 1,
                                 1, 1, 1, 1, 1};
static const char STD_S[N_STD][8] = {"23.976", "24", "25", "29.97", "30", "47.952", "48", "50", "59.94", "60", "72",
                                     "90", "96", "100", "119.88", "120", "144", "150", "180", "200", "239.76", "240",
                                     "300", "360", "400", "480", "500", "600", "1000"};
static const char HW_MODES[9][4] = {"1x1", "1x2", "1x3", "2x1", "2x2", "2x3", "3x2", "3x3", "3x6"};  /* no 3x1 (§72) */
static const char KERN[6][9] = {"1,1,1", "1,2,1", "1,4,1", "1,6,1", "1,14,1", "0,1,0"};
static const char MODE[2][5] = {"SOFT", "STD"};
static const char SUB_LABEL[7][12] = {"ADC", "SENSOR HDC", "SENSOR VDC", "SENSOR HBIN", "SENSOR VBIN", "ISP HBIN",
                                      "ISP VBIN"};
static const char FN_LABEL[N_FN][10] = {"DC", "RES", "SL FPS", "RECIPE", "SL FORMAT"};
static const char FN_NAME[N_FN][7] = {"DC", "RES", "FPS", "RECIPE", "FORMAT"};
static const char FN_ICON[N_FN][21] = {"menu_crop", "menu_cine_resolution", "menu_cine_fps", "", "menu_cine_format"};

/* ---------------------------------------------------------------------------------------------- state */
struct rat { u32 n, d; };                     /* a rate n / d fps: a common rate, or CLK / (hm x VMAX) */
struct rcp {                                  /* one recipe (quality.py case) of a DC x RES */
    u16 hm, lo, mh, mv, ad, hb, vb, scw, sch, sw, sh, vis_w, vis_h, zh, zv, key;
    u32 rs_us;
};
struct cell { u32 dcw, dch, rw, rh, used; s32 n; struct rcp r[MAXR]; };

struct sel {                                  /* the page's S, less the UI state: the record */
    u32 dcw, dch, dclock, reslock, daw, dah, raw, rah;
    u32 rat, resk, custom, cw, ch;
    u32 nmem, mem[N_MEM][4];
    u32 fps_n, fps_d, fc_n, fc_d, fine;
    u32 rq, rd_ok, rd[N_PARAM];
    u32 kh, kv, km;
};

struct fent { struct rat f; u8 std, mark, custom, na; };   /* fpsList() */
struct ritem { u16 w, h; u8 ratio, kl; char lab[6]; char div[8]; };   /* resList() */

struct st {
    const struct sl_svc *svc;
    const u8 *block;
    u32 rec_off, dma_off;
    struct sel s;
    u32 dirty, loaded, writes, write_fails, write_why, leaves, applies, computes, hits, fallbacks;
    /* the QS side */
    struct qsc_func f[N_FN];
    struct qsc_sub sub[N_FN][7];
    struct qsc_subs subs[N_FN];
    struct qsc_table t;
    u8 arg[N_FN][8];                          /* (function, item) <- &arg[f][j] */
    char v[N_FN][8][TXT], sm[N_FN][8][TXT];
    char fl[N_LIST][FT], fs[N_LIST][FT];
    /* the recipes */
    struct cell cache[N_CACHE];
    u32 tick;
    struct cell *cur;                         /* the cell of res() (refreshed by cell_now) */
    core_quality scratch[CORE_MAX_QUAL];
    struct ritem list[N_LIST];
    u32 n_list;
    struct fent fl_e[N_FPS];
    u32 n_fl;
    /* the apply hook (sq_apply): what the later step will install */
    struct { u32 valid, dcw, dch, rw, rh, key, hm, vmax, fps_n, fps_d, kh, kv, km; s32 ri; } applied;
};

/* struct copies: the compiler calls these (no libgcc on the camera); byte loops, volatile so they stay loops */
void __aeabi_memcpy(void *d, const void *s, unsigned n)
{
    volatile u8 *o = d;
    const u8 *i = s;
    while (n--) *o++ = *i++;
}
void __aeabi_memcpy4(void *d, const void *s, unsigned n) { __aeabi_memcpy(d, s, n); }
void __aeabi_memcpy8(void *d, const void *s, unsigned n) { __aeabi_memcpy(d, s, n); }
void __aeabi_memclr(void *d, unsigned n) { volatile u8 *o = d; while (n--) *o++ = 0; }
void __aeabi_memclr4(void *d, unsigned n) { __aeabi_memclr(d, n); }
void __aeabi_memclr8(void *d, unsigned n) { __aeabi_memclr(d, n); }

__attribute__((noinline)) static u32 sq_ctx_at(void)
{
    u32 at;
    __asm__ volatile("adr %0, 1f\n\tb 2f\n\t.balign 4\n1:\t.word 0\n2:" : "=r"(at));
    return at;
}
static struct st *sq_ctx(void) { return (struct st *)(uintptr_t)W(sq_ctx_at()); }

/* ---------------------------------------------------------------------------------------------- helpers */
static u32 udiv(u32 n, u32 d) { return d ? (u32)udiv64(n, d, 0) : 0; }
static int a16i(int x) { return x < 0 ? -(int)udiv((u32)(-x + 15), 16u) * 16 : (int)(udiv((u32)x, 16u) * 16u); }
static int evi(int x) { return x < 0 ? -(int)(((u32)(-x) + 1u) & ~1u) : x & ~1; }
static int sq_min(int a, int b) { return a < b ? a : b; }
static int sq_max(int a, int b) { return a > b ? a : b; }
static int sq_abs(int a) { return a < 0 ? -a : a; }
static u32 sq_len(const char *t) { u32 n = 0; while (t[n]) n++; return n; }
static int sq_eq(const char *a, const char *b) { while (*a && *a == *b) { a++; b++; } return *a == *b; }
static u32 put_s(char *d, u32 n, u32 cap, const char *t) { while (*t && n < cap - 1u) d[n++] = *t++; d[n] = 0; return n; }
static u32 put_u(char *d, u32 n, u32 cap, u64 v)
{
    char tmp[24];
    u32 k = 0;
    do { u64 r, q = udiv64(v, 10u, &r); tmp[k++] = (char)('0' + r); v = q; } while (v);
    while (k && n < cap - 1u) d[n++] = tmp[--k];
    d[n] = 0;
    return n;
}
/* a scaled integer v (value x 10^places, as js_fixed_d gives it) as the page's toFixed(places) text */
static u32 put_fix(char *d, u32 n, u32 cap, u64 v, int places)
{
    u64 p10 = places == 0 ? 1u : places == 1 ? 10u : places == 2 ? 100u : 1000u, fr;
    n = put_u(d, n, cap, udiv64(v, p10, &fr));
    if (places && n < cap - 1u) {
        d[n++] = '.';
        for (u64 p = p10; p > 1u && n < cap - 1u; ) { p = udiv64(p, 10u, 0); u64 q = udiv64(fr, p, &fr); d[n++] = (char)('0' + q); }
        d[n] = 0;
    }
    return n;
}
/* JS a16(W * r) / ev(H * r) for the ratio r (the doubles 2/3, 1/3, 1/6 as the page computes them) */
static i64 dfloor(dbl x) { return !x.m ? 0 : x.e >= 0 ? (i64)(x.m << x.e) : -x.e > 63 ? 0 : (i64)(x.m >> -x.e); }
static dbl rat_d(u32 r) { return dratio(RAT_N[r], RAT_D[r]); }
static int a16r(int W_, u32 r) { return (int)(udiv((u32)dfloor(dmul(rat_d(r), (u64)W_)), 16u) * 16u); }
static int evr(int H_, u32 r) { return (int)(dfloor(dmul(rat_d(r), (u64)H_)) & ~(i64)1); }
static int is_int_bin(u32 r) { return r != 1u; }     /* Number.isInteger(1 / r): 1, 2, 3, 6 yes; 1.5 no (node) */
/* Math.round(x / 2) * 2 and Math.round(x / 16) * 16 of a positive double (round half up, exact) */
static int round_to(dbl x, int k) { x.e -= k == 2 ? 1 : 4; return (int)js_fixed_d(x, 0) * k; }

static void rec_write(struct st *st);

static int busy(void)
{
    u32 sel = W(MOV_SELECTOR) == 0x21u ? MOVREC_SEL21 : MOVREC_DEFAULT;
    return *(volatile u8 *)(uintptr_t)sel || W(XMP_FOBJ_PTR) || *(volatile u8 *)(uintptr_t)MOV_ACTIVE;
}

/* ---------------------------------------------------------------------------------------------- rates */
static struct rat rate_q(const struct rcp *q) { struct rat r = {CD_CLK, (u32)q->hm * q->lo}; return r; }
static struct rat rate_std(u32 i) { struct rat r = {STD_N[i], STD_D[i]}; return r; }
static i64 rdiff(struct rat a, struct rat b) { return (i64)((u64)a.n * b.d) - (i64)((u64)b.n * a.d); }   /* sign of a - b */
static u64 rden(struct rat a, struct rat b) { return (u64)a.d * b.d; }
static int same(struct rat a, struct rat b)          /* |a - b| < 5e-4 */
{
    i64 x = rdiff(a, b);
    return (u64)(x < 0 ? -x : x) * 2000u < rden(a, b);
}
static int ge_tol(struct rat a, struct rat b) { return rdiff(a, b) * 2000 >= -(i64)rden(a, b); }   /* a >= b - 5e-4 */
static int gt_tol(struct rat a, struct rat b) { return rdiff(a, b) * 2000 > (i64)rden(a, b); }     /* a > b + 5e-4 */
static int lt_tol(struct rat a, struct rat b) { return rdiff(a, b) * 2000 < -(i64)rden(a, b); }    /* a < b - 5e-4 */
static int rgt(struct rat a, struct rat b) { return rdiff(a, b) > 0; }
static int rge(struct rat a, struct rat b) { return rdiff(a, b) >= 0; }
static u32 f3_put(char *d, u32 n, u32 cap, struct rat f) { return put_fix(d, n, cap, (u64)js_fixed_d(dratio(f.n, f.d), 3), 3); }
static int f3_same(struct rat a, struct rat b) { return js_fixed_d(dratio(a.n, a.d), 3) == js_fixed_d(dratio(b.n, b.d), 3); }

/* ---------------------------------------------------------------------------------------------- geometry */
static int dc_preset(u32 w, u32 h)
{
    for (u32 i = 0; i < N_DC; i++) if (DCW[i] == w && DCH[i] == h) return (int)i;
    return -1;
}
static void k_label(char *d, u32 w)                  /* kLabel */
{
    u32 n = 0;
    if (4u * w < 3u * 1024u) {
        u32 t = (10u * w + 512u) >> 10;
        n = put_u(d, n, 6, udiv(t, 10u));
        d[n++] = '.';
        n = put_u(d, n, 6, t - 10u * udiv(t, 10u));
    } else {
        u32 x2 = (w + 256u) >> 9;
        n = put_u(d, n, 6, x2 >> 1);
        if (x2 & 1u) { d[n++] = '.'; d[n++] = '5'; }
    }
    d[n++] = 'K';
    d[n] = 0;
}
static void div_text(char *d, u32 W_, u32 H_, u32 w, u32 h)   /* divText */
{
    u32 n = 0, kw = 0, kh = 0;
    for (u32 i = 0; i < 8u && !kw; i++) if (a16i((int)udiv(W_, DIVK[i])) == (int)w) kw = DIVK[i];
    for (u32 i = 0; i < 8u && !kh; i++) if (evi((int)udiv(H_, DIVK[i])) == (int)h) kh = DIVK[i];
    d[0] = 0;
    if (!kw && !kh) return;
    if (kw) n = put_u(d, n, 8, kw);
    d[n++] = 'x'; d[n] = 0;
    if (kh) put_u(d, n, 8, kh);
}
static u32 res_list(struct st *st, u32 W_, u32 H_, struct ritem *out)   /* resList */
{
    u32 n = 0, hd = dc_preset(W_, H_) == 1;
    for (u32 r = 0; r < N_RAT; r++) {
        int w = a16r((int)W_, r), h = is_int_bin(r) ? evr((int)H_, r) : evi((int)udiv((u32)w * H_, W_));
        if (w < WMIN || h < HMIN) continue;
        struct ritem *it = &out[n++];
        it->w = (u16)w; it->h = (u16)h; it->ratio = 1; it->kl = (u8)r;
        k_label(it->lab, (u32)w);
    }
    u32 nr = n;
    for (u32 k = 0; k < 7u; k++) {
        u32 w = KL_W[k];
        if (w > W_ || evi((int)udiv(w * H_, W_)) < HMIN) continue;
        u32 dup = 0;
        for (u32 i = 0; i < nr && !dup; i++) dup = sq_eq(out[i].lab, KL_N[k]);
        if (dup) continue;
        struct ritem *it = &out[n++];
        it->w = (u16)w; it->h = (u16)evi((int)udiv(w * H_, W_)); it->ratio = 0; it->kl = (u8)k;
        put_s(it->lab, 0, 6, KL_N[k]);
    }
    if (hd)
        for (u32 k = 7; k < N_KL; k++) {
            struct ritem *it = &out[n++];
            it->w = KL_W[k]; it->h = KL_H[k]; it->ratio = 0; it->kl = (u8)k;
            put_s(it->lab, 0, 6, KL_N[k]);
        }
    u32 m = 0;
    for (u32 i = 0; i < n; i++) {                    /* one per W x H (the first), then by width, stable */
        u32 seen = 0;
        for (u32 j = 0; j < m && !seen; j++) seen = out[j].w == out[i].w && out[j].h == out[i].h;
        if (!seen) { if (m != i) out[m] = out[i]; m++; }
    }
    for (u32 i = 1; i < m; i++) {
        struct ritem x = out[i];
        u32 j = i;
        while (j && out[j - 1u].w > x.w) { out[j] = out[j - 1u]; j--; }
        out[j] = x;
    }
    for (u32 i = 0; i < m; i++) div_text(out[i].div, W_, H_, out[i].w, out[i].h);
    (void)st;
    return m;
}
static u32 refresh_list(struct st *st) { return st->n_list = res_list(st, st->s.dcw, st->s.dch, st->list); }

static void res_now(struct st *st, u32 *w, u32 *h)  /* res() */
{
    struct sel *s = &st->s;
    if (s->custom) { *w = s->cw; *h = s->ch; return; }
    if (s->resk) {
        refresh_list(st);
        for (u32 i = 0; i < st->n_list; i++)
            if (sq_eq(st->list[i].lab, KL_N[s->resk - 1u])) { *w = st->list[i].w; *h = st->list[i].h; return; }
    }
    u32 r = s->rat;
    if (a16r((int)s->dcw, r) < WMIN || evr((int)s->dch, r) < HMIN) r = 0;   /* x1, the ratio not forgotten */
    int rw = a16r((int)s->dcw, r);
    *w = (u32)rw;
    *h = (u32)(is_int_bin(r) ? evr((int)s->dch, r) : evi((int)udiv((u32)rw * s->dch, s->dcw)));
}
static int res_hit(struct st *st, u32 w, u32 h)
{
    refresh_list(st);
    for (u32 i = 0; i < st->n_list; i++) if (st->list[i].w == w && st->list[i].h == h) return (int)i;
    return -1;
}

/* ---------------------------------------------------------------------------------------------- recipes */
static struct cell *cell_now(struct st *st)
{
    u32 rw, rh;
    res_now(st, &rw, &rh);
    struct sel *s = &st->s;
    struct cell *c = 0, *old = &st->cache[0];
    for (u32 i = 0; i < N_CACHE; i++) {
        struct cell *x = &st->cache[i];
        if (x->used && x->dcw == s->dcw && x->dch == s->dch && x->rw == rw && x->rh == rh) c = x;
        if (x->used < old->used) old = x;
    }
    if (c) { st->hits++; c->used = ++st->tick; return st->cur = c; }
    c = old;
    st->computes++;
    int n = core_qualities_tol((int)s->dcw, (int)s->dch, (int)rw, (int)rh, 0, 1, TOL_NUM, TOL_DEN, st->scratch,
                               (int)CORE_MAX_QUAL);
    c->dcw = s->dcw; c->dch = s->dch; c->rw = rw; c->rh = rh; c->used = ++st->tick;
    c->n = n < 0 || n > (int)MAXR ? -1 : n;          /* no data: the page's "no FPSDATA" */
    for (int i = 0; i < c->n; i++) {
        const core_quality *q = &st->scratch[i];
        struct rcp *r = &c->r[i];
        r->hm = (u16)q->hm; r->lo = (u16)q->vmin_lo; r->mh = (u16)q->mh; r->mv = (u16)q->mv; r->ad = (u16)q->ad;
        r->hb = (u16)q->hbin; r->vb = (u16)q->vbin; r->scw = (u16)q->cw; r->sch = (u16)q->ch; r->sw = (u16)q->sw;
        r->sh = (u16)q->sh; r->vis_w = (u16)q->vis_w; r->vis_h = (u16)q->vis_h; r->zh = (u16)q->zh;
        r->zv = (u16)q->zv; r->key = (u16)q->key; r->rs_us = (u32)q->rs_us;
    }
    return st->cur = c;
}
static u32 rq_of(const struct rcp *q) { return (u32)q->ad << 16 | (u32)q->mh << 12 | (u32)q->mv << 8 | (u32)q->hb << 4 | q->vb; }
static int is_preset(const struct rcp *q) { return q->hb == 1 && q->vb == 1; }
static u32 pval(const struct rcp *q, u32 k)
{
    return k == K_AD ? q->ad : k == K_SCW ? q->scw : k == K_SCH ? q->sch : k == K_MH ? q->mh : k == K_MV ? q->mv :
           k == K_HB ? q->hb : q->vb;
}
static int usable(const struct st *st, const struct rcp *q)
{
    struct rat f = {st->s.fps_n, st->s.fps_d};
    return ge_tol(rate_q(q), f);
}
/* nearest(R, d) over the cell's recipes with filter `want` (bit 0 usable, bit 1 preset) */
static const struct rcp *nearest(struct st *st, u32 want)
{
    struct cell *c = st->cur;
    const struct rcp *best = 0;
    u32 bd = 0;
    for (int i = 0; i < c->n; i++) {
        const struct rcp *q = &c->r[i];
        if (((want & 1u) && !usable(st, q)) || ((want & 2u) && !is_preset(q))) continue;
        if (!st->s.rd_ok) return q;                     /* !d: R[0] */
        u32 d = 0;
        for (u32 k = 0; k < N_PARAM; k++) d += pval(q, k) != st->s.rd[k];
        if (!best || d < bd || (d == bd && rgt(rate_q(q), rate_q(best)))) { best = q; bd = d; }
    }
    return best;
}
static const struct rcp *cur_recipe(struct st *st)    /* curRecipe */
{
    struct cell *c = st->cur;
    if (c->n <= 0) return 0;
    for (int i = 0; i < c->n; i++) if (rq_of(&c->r[i]) == st->s.rq && usable(st, &c->r[i])) return &c->r[i];
    const struct rcp *q = nearest(st, 3u);
    return q ? q : nearest(st, 1u);
}
static int has_q(const struct st *st) { return st->cur->n > 0; }    /* quals() non-null (and not empty) */
static struct rat fps_max(const struct st *st)       /* fpsMax(quals()) */
{
    struct rat m = {0, 1}, k1000 = {1000, 1};
    const struct cell *c = st->cur;
    for (int i = 0; i < c->n; i++) if (is_preset(&c->r[i]) && rgt(rate_q(&c->r[i]), m)) m = rate_q(&c->r[i]);
    return rgt(m, k1000) ? k1000 : m;
}
static int qmark(const struct st *st, struct rat f)  /* Q.some(q => same(q.max, f)) */
{
    const struct cell *c = st->cur;
    for (int i = 0; i < c->n; i++) if (is_preset(&c->r[i]) && same(rate_q(&c->r[i]), f)) return 1;
    return 0;
}
static u32 fps_list(struct st *st)                    /* fpsList */
{
    struct sel *s = &st->s;
    u32 n = 0;
    if (!has_q(st)) return st->n_fl = 0;
    struct rat M = fps_max(st), k1000 = {1000, 1};
    for (u32 i = 0; i < N_STD; i++) {
        struct fent *e = &st->fl_e[n++];
        e->f = rate_std(i); e->std = (u8)(i + 1u); e->custom = 0; e->na = gt_tol(e->f, M);
    }
    const struct cell *c = st->cur;
    for (int i = 0; i < c->n; i++) {
        if (!is_preset(&c->r[i])) continue;
        struct rat f = rate_q(&c->r[i]);
        if (rgt(f, k1000)) continue;
        u32 dup = 0;
        for (u32 j = 0; j < n && !dup; j++) dup = same(st->fl_e[j].f, f);
        if (dup) continue;
        struct fent *e = &st->fl_e[n++];
        e->f = f; e->std = 0; e->custom = 0; e->na = 0;
    }
    for (u32 j = 0; j < n; j++) st->fl_e[j].mark = (u8)qmark(st, st->fl_e[j].f);
    if (s->fc_d) {
        struct rat fc = {s->fc_n, s->fc_d};
        u32 dup = 0;
        for (u32 j = 0; j < n && !dup; j++) dup = same(st->fl_e[j].f, fc);
        if (!gt_tol(fc, M) && !dup) {
            struct fent *e = &st->fl_e[n++];
            e->f = fc; e->std = 0; e->custom = 1; e->na = 0; e->mark = (u8)qmark(st, fc);
        }
    }
    for (u32 i = 1; i < n; i++) {                    /* by rate (no two within 5e-4: no ties) */
        struct fent x = st->fl_e[i];
        u32 j = i;
        while (j && rgt(st->fl_e[j - 1u].f, x.f)) { st->fl_e[j] = st->fl_e[j - 1u]; j--; }
        st->fl_e[j] = x;
    }
    return st->n_fl = n;
}
static int fps_sel(struct st *st)
{
    struct rat f = {st->s.fps_n, st->s.fps_d};
    fps_list(st);
    for (u32 i = 0; i < st->n_fl; i++) if (same(st->fl_e[i].f, f)) return (int)i;
    return -1;
}
static u32 fmt_rate(char *d, u32 cap, const struct fent *e)   /* fmtF */
{
    return e->std ? put_s(d, 0, cap, STD_S[e->std - 1u]) : f3_put(d, 0, cap, e->f);
}
static void fix_fps(struct st *st)                    /* fixFps: after a DC / RES change */
{
    cell_now(st);
    if (!has_q(st)) return;
    struct rat M = fps_max(st), f = {st->s.fps_n, st->s.fps_d};
    if (!gt_tol(f, M)) return;
    fps_list(st);
    struct rat to = M;
    for (u32 i = 0; i < st->n_fl; i++) if (st->fl_e[i].std && !st->fl_e[i].na) to = st->fl_e[i].f;
    st->s.fps_n = to.n; st->s.fps_d = to.d;
}
static void fine_exit(struct st *st)                  /* fineExit */
{
    struct sel *s = &st->s;
    struct rat f = {s->fps_n, s->fps_d};
    s->fine = 0;
    fps_list(st);
    u32 hit = 0;
    for (u32 i = 0; i < st->n_fl; i++) if (!st->fl_e[i].custom && same(st->fl_e[i].f, f)) hit = 1;
    if (hit) s->fc_d = 0; else { s->fc_n = f.n; s->fc_d = f.d; }
}
static struct rat fine_step(struct st *st, struct rat f, int d, int big)   /* fineStep */
{
    const struct cell *c = st->cur;
    struct rat k1000 = {1000, 1};
    for (int n = 0; n < (big ? 10 : 1); n++) {
        struct rat best = {0, 0};
        for (int i = 0; i < c->n; i++) {
            const struct rcp *q = &c->r[i];
            if (!is_preset(q)) continue;
            u64 num = (u64)CD_CLK * f.d, den = (u64)q->hm * f.n, V;      /* v = clk / (hm x f) */
            V = d > 0 ? udiv64(num - 1u, den, 0) : udiv64(num, den, 0) + 1u;   /* ceil(v) - 1 / floor(v) + 1 */
            if (V < q->lo || V > VMAX_MAX) continue;
            struct rat g = {CD_CLK, (u32)(q->hm * V)};
            if (gt_tol(g, k1000)) continue;
            if (d > 0 ? gt_tol(g, f) && (!best.d || rgt(best, g)) : lt_tol(g, f) && (!best.d || rgt(g, best))) best = g;
        }
        if (!best.d) break;
        if (f3_same(best, f)) { f = best; n--; continue; }   /* the user sees every step move */
        f = best;
    }
    return f;
}

/* ---------------------------------------------------------------------------------------------- setDC / setRes */
static int mem_find(const struct sel *s, u32 w, u32 h)
{
    for (u32 i = 0; i < s->nmem; i++) if (s->mem[i][0] == w && s->mem[i][1] == h) return (int)i;
    return -1;
}
static void mem_drop(struct sel *s, int i)
{
    if (i < 0) return;
    for (u32 j = (u32)i; j + 1u < s->nmem; j++) for (u32 k = 0; k < 4u; k++) s->mem[j][k] = s->mem[j + 1u][k];
    s->nmem--;
}
static void mem_put(struct sel *s, u32 dw, u32 dh, u32 w, u32 h)
{
    int i = mem_find(s, dw, dh);
    if (i < 0) {
        if (s->nmem == N_MEM) mem_drop(s, 0);         /* the oldest goes (the page keeps all) */
        i = (int)s->nmem++;
    }
    s->mem[i][0] = dw; s->mem[i][1] = dh; s->mem[i][2] = w; s->mem[i][3] = h;
}
static void set_dc0(struct st *st, int w, int h)
{
    struct sel *s = &st->s;
    if (s->custom) mem_put(s, s->dcw, s->dch, s->cw, s->ch);
    s->dcw = (u32)sq_max(WMIN, sq_min(WMAX, a16i(w)));
    s->dch = (u32)sq_max(HMIN, sq_min(HMAX, evi(h)));
    int m = mem_find(s, s->dcw, s->dch);
    s->custom = 0;
    if (m >= 0 && s->mem[m][2] <= s->dcw && s->mem[m][3] <= s->dch) { s->custom = 1; s->cw = s->mem[m][2]; s->ch = s->mem[m][3]; }
    u32 rw, rh;
    res_now(st, &rw, &rh);
    s->raw = rw; s->rah = rh;
    st->dirty = 1;
}
static void set_dc(struct st *st, int w, int h) { set_dc0(st, w, h); fix_fps(st); }
static void set_res0(struct st *st, int w, int h)
{
    struct sel *s = &st->s;
    w = sq_max(WMIN, sq_min((int)s->dcw, a16i(w)));
    h = sq_max(HMIN, sq_min((int)s->dch, evi(h)));
    int hit = res_hit(st, (u32)w, (u32)h), q = -1;
    if (hit >= 0 && st->list[hit].ratio)
        for (u32 r = 0; r < N_RAT && q < 0; r++) if (a16r((int)s->dcw, r) == w) q = (int)r;
    if (q >= 0) { s->rat = (u32)q; s->resk = 0; s->custom = 0; mem_drop(s, mem_find(s, s->dcw, s->dch)); }
    else if (hit >= 0) { s->resk = st->list[hit].kl + 1u; s->custom = 0; mem_drop(s, mem_find(s, s->dcw, s->dch)); }
    else { s->resk = 0; s->custom = 1; s->cw = (u32)w; s->ch = (u32)h; }
    st->dirty = 1;
}
static void set_res(struct st *st, int w, int h) { set_res0(st, w, h); fix_fps(st); }

/* visible(): the selected recipe's own visible size (<= 2 % short), else the nominal */
static void visible(struct st *st, u32 *w, u32 *h, u32 *shrt)
{
    u32 rw, rh;
    res_now(st, &rw, &rh);
    cell_now(st);
    const struct rcp *c = cur_recipe(st);
    if (c) { *w = c->vis_w; *h = c->vis_h; *shrt = c->vis_h + 10u < rh || c->vis_w + 16u < rw; return; }
    *w = rw - 16u; *h = rh - 10u; *shrt = 0;
}

/* ---------------------------------------------------------------------------------------------- recipe parameters */
static const struct rcp *combo(struct st *st, u32 key, u32 v)   /* combo(key, v): every other choice kept */
{
    const struct rcp *c = cur_recipe(st), *best = 0;
    if (!c) return 0;
    const struct cell *cl = st->cur;
    for (int i = 0; i < cl->n; i++) {
        const struct rcp *q = &cl->r[i];
        if (pval(q, key) != v) continue;
        u32 ok = 1;
        for (u32 k = K_AD; k <= K_VB && ok; k++)
            if (k != key && k != K_SCW && k != K_SCH && pval(q, k) != pval(c, k)) ok = 0;
        if (!ok) continue;
        if (key == K_SCW || key == K_SCH) return q;
        if (!best || rgt(rate_q(q), rate_q(best))) best = q;
    }
    return best;
}
static void use_recipe(struct st *st, const struct rcp *q)   /* useRecipe */
{
    struct sel *s = &st->s;
    struct rat f = {s->fps_n, s->fps_d}, m = rate_q(q);
    s->rq = rq_of(q); s->rd_ok = 1;
    for (u32 k = 0; k < N_PARAM; k++) s->rd[k] = pval(q, k);
    if (lt_tol(m, f)) { s->fps_n = m.n; s->fps_d = m.d; }
    st->dirty = 1;
}
static u32 vals(struct st *st, u32 key, u32 *out)   /* the distinct values of key, ascending */
{
    u32 n = 0;
    const struct cell *c = st->cur;
    for (int i = 0; i < c->n; i++) {
        u32 v = pval(&c->r[i], key), seen = 0;
        for (u32 j = 0; j < n && !seen; j++) seen = out[j] == v;
        if (seen) continue;
        u32 j = n++;
        while (j && out[j - 1u] > v) { out[j] = out[j - 1u]; j--; }
        out[j] = v;
    }
    return n;
}
static u32 short_name(char *d, u32 n, u32 k, u32 v)  /* SHORT */
{
    n = put_s(d, n, FT, k == K_AD ? "" : k == K_MH ? "SENSOR H" : k == K_MV ? "SENSOR V" : k == K_HB ? "ISP H" : "ISP V");
    n = put_u(d, n, FT, v);
    return k == K_AD ? put_s(d, n, FT, "bit") : n;
}
static void why_not(struct st *st, char *d, u32 key, u32 v)   /* whyNot */
{
    const struct rcp *c = cur_recipe(st), *best = 0;
    u32 n = 0, bd = 0;
    d[0] = 0;
    if (!c) return;
    if (key == K_MH || key == K_MV) {
        u32 mh = key == K_MH ? v : c->mh, mv = key == K_MV ? v : c->mv, hw = 0;
        for (u32 i = 0; i < 9u; i++) hw |= (u32)(HW_MODES[i][0] - '0') == mh && (u32)(HW_MODES[i][2] - '0') == mv;
        if (!hw) {
            n = put_s(d, 0, FT, "no "); n = put_u(d, n, FT, mh); n = put_s(d, n, FT, "x"); put_u(d, n, FT, mv);
            return;
        }
    }
    const struct cell *cl = st->cur;
    for (int i = 0; i < cl->n; i++) {
        const struct rcp *q = &cl->r[i];
        if (pval(q, key) != v) continue;
        u32 df = 0;
        for (u32 k = K_AD; k <= K_VB; k++) if (k != key && k != K_SCW && k != K_SCH && pval(q, k) != pval(c, k)) df++;
        if (!best || df < bd) { best = q; bd = df; }
    }
    if (!best) { put_s(d, 0, FT, "not at this RES"); return; }
    n = put_s(d, 0, FT, "needs");
    static const u8 CHOICE[5] = {K_AD, K_MH, K_MV, K_HB, K_VB};
    for (u32 j = 0; j < 5u; j++) {
        u32 k = CHOICE[j];
        if (k == key || pval(best, k) == pval(c, k)) continue;
        n = put_s(d, n, FT, " ");
        n = short_name(d, n, k, pval(best, k));
    }
}
static u32 rwzm(char *d, u32 n, u32 z)               /* RWZM 1:1 within 0.5 %, else 1/x.xx */
{
    if (z < 1029u) return put_s(d, n, TXT, "RWZM 1:1");
    n = put_s(d, n, TXT, "RWZM 1/");
    return put_fix(d, n, TXT, (u64)js_fixed_d(dratio(z, 1024), 2), 2);
}

/* ---------------------------------------------------------------------------------------------- the apply hook */
/* The later "apply" step installs the effective selection: core_quality_plan(q, CLK, hm x VMAX) -> core_smc_create
 * (the sensor mode) and core_quality_spec -> core_isp_plan / core_isp_row (the ISP), the kernels / mode into BINFILT.
 * Today it only records what that would be (st->applied), at every leave(), outside the QS key path. */
static void sq_apply(struct st *st)
{
    struct sel *s = &st->s;
    u32 rw, rh;
    res_now(st, &rw, &rh);
    cell_now(st);
    const struct rcp *c = cur_recipe(st);
    st->applies++;
    st->applied.valid = c != 0;
    if (!c) return;
    st->applied.dcw = s->dcw; st->applied.dch = s->dch; st->applied.rw = rw; st->applied.rh = rh;
    st->applied.key = c->key; st->applied.hm = c->hm;
    /* the VMAX step at the selected rate: the smallest VMAX >= lo whose rate does not exceed it */
    u64 num = (u64)CD_CLK * s->fps_d, den = (u64)c->hm * s->fps_n, v = udiv64(num + den - 1u, den, 0);
    st->applied.vmax = (u32)(v < c->lo ? c->lo : v > VMAX_MAX ? VMAX_MAX : v);
    st->applied.fps_n = s->fps_n; st->applied.fps_d = s->fps_d;
    st->applied.kh = s->kh; st->applied.kv = s->kv; st->applied.km = s->km;
    st->applied.ri = (s32)(c - st->cur->r);
}

/* ---------------------------------------------------------------------------------------------- the record */
#define REC_WORDS (2u + 30u + 4u * N_MEM + 1u)
static void rec_pack(const struct sel *s, u32 *r)
{
    u32 k = 0;
    r[k++] = REC_MAGIC; r[k++] = REC_VERSION;
    const u32 *w = &s->dcw;
    for (u32 i = 0; i < 13u; i++) r[k++] = w[i];      /* dcw .. ch */
    r[k++] = s->nmem;
    r[k++] = s->fps_n; r[k++] = s->fps_d; r[k++] = s->fc_n; r[k++] = s->fc_d;
    r[k++] = s->rq; r[k++] = s->rd_ok;
    for (u32 i = 0; i < N_PARAM; i++) r[k++] = s->rd[i];
    r[k++] = s->kh; r[k++] = s->kv; r[k++] = s->km;
    for (u32 i = 0; i < N_MEM; i++) for (u32 j = 0; j < 4u; j++) r[k++] = i < s->nmem ? s->mem[i][j] : 0;
    u32 h = 2166136261u;
    for (u32 i = 0; i < k; i++) { u32 v = r[i]; for (u32 b = 0; b < 4u; b++) { h = (h ^ (v & 0xFFu)) * 16777619u; v >>= 8; } }
    r[k] = h;
}
static int size_ok(u32 w, u32 h, u32 mw, u32 mh) { return !(w & 15u) && !(h & 1u) && w >= WMIN && h >= HMIN && w <= mw && h <= mh; }
static int rec_load(struct sel *out, const u32 *r)
{
    struct sel s;
    u32 chk[REC_WORDS];
    if (r[0] != REC_MAGIC || r[1] != REC_VERSION) return 0;
    u32 k = 2, *w = &s.dcw;
    for (u32 i = 0; i < 13u; i++) w[i] = r[k++];
    s.nmem = r[k++];
    s.fps_n = r[k++]; s.fps_d = r[k++]; s.fc_n = r[k++]; s.fc_d = r[k++]; s.fine = 0;
    s.rq = r[k++]; s.rd_ok = r[k++];
    for (u32 i = 0; i < N_PARAM; i++) s.rd[i] = r[k++];
    s.kh = r[k++]; s.kv = r[k++]; s.km = r[k++];
    if (s.nmem > N_MEM) return 0;
    for (u32 i = 0; i < N_MEM; i++) for (u32 j = 0; j < 4u; j++) s.mem[i][j] = r[k++];
    rec_pack(&s, chk);
    for (u32 i = 0; i < REC_WORDS; i++) if (chk[i] != r[i]) return 0;
    if (!size_ok(s.dcw, s.dch, WMAX, HMAX) || s.rat >= N_RAT || s.resk > N_KL || s.dclock > 1u || s.reslock > 1u ||
        s.custom > 1u || (s.custom && !size_ok(s.cw, s.ch, s.dcw, s.dch)) || !s.daw || !s.dah || !s.raw || !s.rah ||
        !s.fps_n || !s.fps_d || s.kh > 5u || s.kv > 5u || s.km > 1u)
        return 0;
    for (u32 i = 0; i < s.nmem; i++)
        if (!size_ok(s.mem[i][0], s.mem[i][1], WMAX, HMAX) || !size_ok(s.mem[i][2], s.mem[i][3], s.mem[i][0], s.mem[i][1]))
            return 0;
    *out = s;
    return 1;
}
/* Into this sup's own BIN, in place (open 7 = overwrite, no truncation), read back.  Never creates: the file must
 * still be this sup (its 48-byte header) -- sup-writeback-must-not-create.  Not while recording. */
static void rec_write(struct st *st)
{
    const struct sl_svc *svc = st->svc;
    const char *path = svc->self_path(svc, st->block);
    u32 fo = (u32)(uintptr_t)svc->uncached(svc, st->block + st->dma_off);
    u32 buf = fo + FO_BYTES, back = buf + 0x200u, ok = 0, got = 0, r[REC_WORDS];
    rec_pack(&st->s, r);
    if (!path || svc->file_is(svc, path, st->block, SL4_HEADER_LEN) != SL_OK) { st->write_why = 2; st->write_fails++; return; }
    for (u32 i = 0; i < REC_WORDS; i++) W(buf + 4u * i) = r[i];
    ((u32 (*)(u32, u32))F_CTOR)(fo, 1);
    if (((u32 (*)(u32, u32, u32))F_OPEN)(fo, (u32)(uintptr_t)path, 7)) {
        if (((u32 (*)(u32, u32, u32))F_SEEK)(fo, st->rec_off, 0) &&
            ((u32 (*)(u32, u32, u32))F_WRITE)(fo, buf, 4u * REC_WORDS) &&
            ((u32 (*)(u32, u32, u32))F_SEEK)(fo, st->rec_off, 0)) {
            for (u32 i = 0; i < REC_WORDS; i++) W(back + 4u * i) = 0xFFFFFFFFu;
            ((u32 (*)(u32, u32, u32, u32))F_READ)(fo, back, 4u * REC_WORDS, (u32)(uintptr_t)&got);
            ok = got == 4u * REC_WORDS;
            for (u32 i = 0; ok && i < REC_WORDS; i++) if (W(back + 4u * i) != r[i]) ok = 0;
        }
        ((u32 (*)(u32))F_CLOSE)(fo);
    }
    ((u32 (*)(u32, u32))F_DTOR)(fo, 2);
    if (ok) { st->writes++; st->dirty = 0; } else { st->write_why = 3; st->write_fails++; }
}
static void sq_leave(void *arg)                       /* the container's leave(): every layout load */
{
    struct st *st = (struct st *)arg;
    st->leaves++;
    if (busy()) return;
    sq_apply(st);
    if (st->dirty) rec_write(st);
}

/* ---------------------------------------------------------------------------------------------- callbacks */
static u32 who(void *arg, u32 *item)
{
    struct st *st = sq_ctx();
    u32 a = (u32)((u8 *)arg - &st->arg[0][0]);
    *item = a & 7u;
    return a >> 3;
}
static char *vbuf(u32 f, u32 j) { return sq_ctx()->v[f][j]; }
static char *sbuf(u32 f, u32 j) { return sq_ctx()->sm[f][j]; }
static u32 mm_put(char *d, u32 n, u32 px)            /* mm(px) = (px * (35.9 / 6048)).toFixed(1) */
{
    dbl k = dratio(359, 10), pxmm = dratio(k.m, 6048);
    pxmm.e += k.e;
    return put_fix(d, n, TXT, (u64)js_fixed_d(dmul(pxmm, px), 1), 1);
}
static void dc_size(struct st *st, u32 f, u32 *w, u32 *h) { if (f == F_DC) { *w = st->s.dcw; *h = st->s.dch; } else res_now(st, w, h); }

static const char *sq_value(void *arg)
{
    struct st *st = sq_ctx();
    u32 j, f = who(arg, &j), w, h, shr;
    char *d = vbuf(f, j);
    d[0] = 0;
    cell_now(st);
    const struct rcp *c = cur_recipe(st);
    if (f == F_DC || f == F_RES) {
        if (j == 0u && f == F_DC) {
            int p = dc_preset(st->s.dcw, st->s.dch);
            put_s(d, 0, TXT, p >= 0 ? DCN[p] : "CUSTOM");
        } else if (j == 0u) {
            res_now(st, &w, &h);
            int i = res_hit(st, w, h);
            put_s(d, 0, TXT, i >= 0 ? st->list[i].lab : "CUSTOM");
        } else if (j == 1u || j == 2u) {
            if (f == F_DC) { w = st->s.dcw; h = st->s.dch; } else visible(st, &w, &h, &shr);
            put_u(d, 0, TXT, j == 1u ? w : h);
        } else {
            put_s(d, 0, TXT, (f == F_DC ? st->s.dclock : st->s.reslock) ? "LOCK" : "FREE");
        }
    } else if (f == F_FPS) {
        if (!has_q(st)) return "\xE2\x80\x94";
        struct rat fr = {st->s.fps_n, st->s.fps_d};
        int k = fps_sel(st);
        if (st->s.fine || k < 0) f3_put(d, 0, TXT, fr); else fmt_rate(d, TXT, &st->fl_e[k]);
    } else if (f == F_FORMAT) {
        put_s(d, 0, TXT, "DNG");
    } else if (j == 0u) {
        if (!c) return "\xE2\x80\x94";
        if (!is_preset(c)) put_s(d, 0, TXT, "CUSTOM");
        else { u32 n = put_u(d, 0, TXT, c->ad); n = put_s(d, n, TXT, "b "); n = put_u(d, n, TXT, c->mh);
               n = put_s(d, n, TXT, "x"); put_u(d, n, TXT, c->mv); }
    } else {
        if (!c) return "\xE2\x80\x94";
        u32 key = j - 1u;
        u32 n = put_u(d, 0, TXT, pval(c, key));
        if (key == K_AD) put_s(d, n, TXT, "bit");
    }
    return d;
}

static const char *sq_small(void *arg, uint32_t *flags)
{
    struct st *st = sq_ctx();
    u32 j, f = who(arg, &j), w, h, vw, vh, shr, n = 0;
    char *d = sbuf(f, j), dv[8];
    d[0] = 0;
    cell_now(st);
    const struct rcp *c = cur_recipe(st);
    if (f == F_DC && j == 0u) {                       /* "35.9 × 20.2 mm" */
        n = mm_put(d, 0, st->s.dcw); n = put_s(d, n, TXT, " \xC3\x97 "); n = mm_put(d, n, st->s.dch);
        put_s(d, n, TXT, " mm");
    } else if (f == F_RES && j == 0u) {               /* visible size · HxV, yellow when the recipe is short */
        res_now(st, &w, &h);
        int i = res_hit(st, w, h);
        if (i >= 0) put_s(dv, 0, 8, st->list[i].div); else div_text(dv, st->s.dcw, st->s.dch, w, h);
        visible(st, &vw, &vh, &shr);
        n = put_u(d, 0, TXT, vw); n = put_s(d, n, TXT, "\xC3\x97"); n = put_u(d, n, TXT, vh);
        if (dv[0]) { n = put_s(d, n, TXT, " \xC2\xB7 "); put_s(d, n, TXT, dv); }
        if (shr) *flags |= QSC_T_APPROX;
    } else if ((f == F_DC || f == F_RES) && (j == 1u || j == 2u)) {
        if (f == F_DC) { n = mm_put(d, 0, j == 1u ? st->s.dcw : st->s.dch); put_s(d, n, TXT, " mm"); }
        else { res_now(st, &w, &h); div_text(d, st->s.dcw, st->s.dch, w, h); }
    } else if (f == F_DC || f == F_RES) {             /* RATIO "1.778 : 1" */
        dc_size(st, f, &w, &h);
        n = put_fix(d, 0, TXT, (u64)js_fixed_d(dratio(w, h), 3), 3);
        put_s(d, n, TXT, " : 1");
    } else if (f == F_FPS) {                          /* "• 32 recipes" (• at a recipe's maximum) */
        if (!has_q(st)) return "no recipe";
        struct rat fr = {st->s.fps_n, st->s.fps_d};
        u32 a = 0;
        const struct cell *cl = st->cur;
        for (int i = 0; i < cl->n; i++) if (is_preset(&cl->r[i]) && ge_tol(rate_q(&cl->r[i]), fr)) a++;
        if (qmark(st, fr)) n = put_s(d, 0, TXT, "\xE2\x80\xA2 ");
        n = put_u(d, n, TXT, a);
        put_s(d, n, TXT, " recipes");
    } else if (f == F_FORMAT) {
        if (c) put_s(d, 0, TXT, c->ad == 14u ? "14bit" : "12bit");   /* 11-bit AD records 12-bit */
    } else if (j == 0u) {                             /* RECIPE */
        if (!c) return "no recipe";
        visible(st, &vw, &vh, &shr);
        if (!is_preset(c)) {
            n = put_u(d, 0, TXT, c->ad); n = put_s(d, n, TXT, "b "); n = put_u(d, n, TXT, c->mh); n = put_s(d, n, TXT, "x");
            n = put_u(d, n, TXT, c->mv); n = put_s(d, n, TXT, " ISP "); n = put_u(d, n, TXT, c->hb); n = put_s(d, n, TXT, "x");
            n = put_u(d, n, TXT, c->vb); n = put_s(d, n, TXT, " \xC2\xB7 ");
        }
        n = put_s(d, n, TXT, "RS ");
        n = put_fix(d, n, TXT, (u64)js_fixed_d(dratio(c->rs_us, 1000), 2), 2);
        n = put_s(d, n, TXT, " ms");
        if (shr) { n = put_s(d, n, TXT, " \xC2\xB7 "); n = put_u(d, n, TXT, vw); n = put_s(d, n, TXT, "\xC3\x97"); put_u(d, n, TXT, vh);
                   *flags |= QSC_T_APPROX; }
    } else if (c) {
        u32 key = j - 1u;
        if (key == K_SCW || key == K_SCH) { n = put_s(d, 0, TXT, "read \xE2\x86\x92 "); put_u(d, n, TXT, key == K_SCW ? c->sw : c->sh); }
        else if (key == K_HB || key == K_VB) {
            u32 b = key == K_HB ? c->hb : c->vb, kk = key == K_HB ? st->s.kh : st->s.kv;
            if (b == 3u) { n = put_s(d, 0, TXT, "("); n = put_s(d, n, TXT, KERN[kk]); n = put_s(d, n, TXT, ") ");
                           n = put_s(d, n, TXT, MODE[st->s.km]); n = put_s(d, n, TXT, " \xC2\xB7 "); }
            rwzm(d, n, key == K_HB ? c->zh : c->zv);
        }
    }
    return d[0] ? d : 0;
}

/* the footer: at most N_LIST options, a window of 15 around the current one (the container shows 7 of them) */
static u32 window(u32 n, int cur, u32 *lo)
{
    *lo = 0;
    if (n <= N_LIST) return n;
    int a = cur - 7;
    if (a < 0) a = 0;
    if (a > (int)n - 15) a = (int)n - 15;
    *lo = (u32)a;
    return 15;
}
static const u8 OPTS_B[13] = {1, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3};   /* ISP bin options: 1, then 3 x kernel x mode */
static int isp_cur(struct st *st, u32 key)
{
    const struct rcp *c = cur_recipe(st);
    if (!c) return -1;
    u32 b = key == K_HB ? c->hb : c->vb;
    return b == 3u ? 1 + (int)st->s.km * 6 + (int)(key == K_HB ? st->s.kh : st->s.kv) : 0;
}

static u32 sq_footer(void *arg, struct qsc_foot *o)
{
    struct st *st = sq_ctx();
    u32 j, f = who(arg, &j), w, h, n = 0, lo = 0;
    int cur = -1;
    cell_now(st);
    const struct rcp *c = cur_recipe(st);
    if (f == F_DC && j == 0u) {
        for (u32 i = 0; i < N_DC; i++) {
            u32 k = put_u(st->fs[i], 0, FT, DCW[i]); k = put_s(st->fs[i], k, FT, "\xC3\x97"); put_u(st->fs[i], k, FT, DCH[i]);
            o->label[i] = DCN[i]; o->small[i] = st->fs[i];
        }
        n = N_DC; cur = dc_preset(st->s.dcw, st->s.dch);
    } else if (f == F_RES && j == 0u) {
        res_now(st, &w, &h);
        cur = res_hit(st, w, h);
        n = window(st->n_list, cur, &lo);
        for (u32 i = 0; i < n; i++) { o->label[i] = st->list[lo + i].lab; o->small[i] = st->list[lo + i].div[0] ? st->list[lo + i].div : 0; }
    } else if ((f == F_DC || f == F_RES) && (j == 1u || j == 2u)) {
        o->label[0] = sq_value(arg); o->n = 1; o->spin = 1;
        return 1;
    } else if (f == F_DC || f == F_RES) {
        o->label[0] = "LOCK"; o->label[1] = "FREE";
        n = 2; cur = (f == F_DC ? st->s.dclock : st->s.reslock) ? 0 : 1;
    } else if (f == F_FPS) {
        if (!has_q(st)) return 0;
        struct rat fr = {st->s.fps_n, st->s.fps_d};
        if (st->s.fine) {                             /* fine: the K-style spinner, marked at a recipe's maximum */
            f3_put(st->fl[0], 0, FT, fr);
            o->label[0] = st->fl[0]; o->n = 1; o->spin = 1; o->mark = (u32)qmark(st, fr);
            return 1;
        }
        cur = fps_sel(st);
        n = window(st->n_fl, cur, &lo);
        for (u32 i = 0; i < n; i++) {
            const struct fent *e = &st->fl_e[lo + i];
            fmt_rate(st->fl[i], FT, e);
            o->label[i] = st->fl[i];
            o->mark |= (u32)e->mark << i; o->custom |= (u32)e->custom << i; o->grey |= (u32)e->na << i;
        }
    } else if (f == F_FORMAT) {
        o->label[0] = "DNG"; o->label[1] = "MOV"; o->grey = 2u;
        n = 2; cur = 0;
    } else if (j == 0u) {                             /* RECIPE: the presets, RS, H<rows> when short */
        res_now(st, &w, &h);
        u32 k = 0;
        const struct cell *cl = st->cur;
        int csel = -1;
        u32 np = 0;
        for (int i = 0; i < cl->n; i++) if (is_preset(&cl->r[i])) { if (c && rq_of(&cl->r[i]) == rq_of(c)) csel = (int)np; np++; }
        cur = csel;
        n = window(np, cur, &lo);
        for (int i = 0; i < cl->n && k < lo + n; i++) {
            const struct rcp *q = &cl->r[i];
            if (!is_preset(q)) continue;
            if (k >= lo) {
                u32 t = k - lo, m;
                m = put_u(st->fl[t], 0, FT, q->ad); m = put_s(st->fl[t], m, FT, "b "); m = put_u(st->fl[t], m, FT, q->mh);
                m = put_s(st->fl[t], m, FT, "x"); put_u(st->fl[t], m, FT, q->mv);
                m = put_s(st->fs[t], 0, FT, "RS ");
                m = put_fix(st->fs[t], m, FT, (u64)js_fixed_d(dratio(q->rs_us, 1000), 2), 2);
                if (q->vis_h + 10u < h) { m = put_s(st->fs[t], m, FT, " \xC2\xB7 H"); put_u(st->fs[t], m, FT, q->vis_h); o->approx |= 1u << t; }
                o->label[t] = st->fl[t]; o->small[t] = st->fs[t];
                if (!usable(st, q)) o->grey |= 1u << t;
            }
            k++;
        }
    } else {                                          /* the recipe parameters */
        u32 key = j - 1u;
        if (!c) return 0;
        if (key == K_HB || key == K_VB) {
            cur = isp_cur(st, key);
            for (u32 i = 0; i < 13u; i++) {
                u32 b = OPTS_B[i], ok = combo(st, key, b) != 0, m = 0;
                put_s(st->fl[i], 0, FT, b == 1u ? "1" : "3");
                st->fs[i][0] = 0;
                if (i) { u32 md = i > 6u, ki = i - 1u - 6u * md;
                         m = put_s(st->fs[i], 0, FT, "("); m = put_s(st->fs[i], m, FT, KERN[ki]);
                         m = put_s(st->fs[i], m, FT, ") "); m = put_s(st->fs[i], m, FT, MODE[md]); }
                if (!ok) { char wn[FT]; why_not(st, wn, key, b); m = put_s(st->fs[i], m, FT, " \xC2\xB7 "); put_s(st->fs[i], m, FT, wn);
                           o->grey |= 1u << i; }
                o->label[i] = st->fl[i]; o->small[i] = st->fs[i][0] ? st->fs[i] : 0;
            }
            n = 13;
        } else {
            u32 V[MAXR];
            u32 nv = vals(st, key, V);
            for (u32 i = 0; i < nv; i++) if (V[i] == pval(c, key)) cur = (int)i;
            n = window(nv, cur, &lo);
            for (u32 i = 0; i < n; i++) {
                u32 v = V[lo + i], m = put_u(st->fl[i], 0, FT, v);
                if (key == K_AD) put_s(st->fl[i], m, FT, "bit");
                o->label[i] = st->fl[i];
                o->small[i] = 0;
                if (!combo(st, key, v)) { why_not(st, st->fs[i], key, v); o->small[i] = st->fs[i]; o->grey |= 1u << i; }
            }
        }
    }
    o->n = n;
    o->cur = cur >= 0 ? (u32)cur - lo : n;
    return n;
}

static int sq_lock_icon(void *arg)
{
    struct st *st = sq_ctx();
    u32 j, f = who(arg, &j);
    (void)j;
    return (f == F_DC ? st->s.dclock : st->s.reslock) ? QSC_LOCK_SHUT : QSC_LOCK_OPEN;
}

/* the page's p.w / p.h vs asp within 0.002, as the doubles compare (subtraction exact, Sterbenz) */
static int asp_near(u32 pw, u32 ph, u32 aw, u32 ah)
{
    dbl a = dratio(pw, ph), b = dratio(aw, ah), c = dratio(2, 1000);
    if (a.e - b.e > 1 || b.e - a.e > 1) return 0;     /* not within a factor of 2: far apart */
    int e1 = a.e < b.e ? a.e : b.e;
    u64 x = a.m << (a.e - e1), y = b.m << (b.e - e1), d = x > y ? x - y : y - x;
    if (!d) return 1;
    int sh = e1 - c.e;                                /* d * 2^e1 < c.m * 2^c.e */
    if (sh >= 0) return sh < 63 && d < ((u64)1 << (63 - sh)) ? (d << sh) < c.m : 0;
    return d < (c.m << -sh);
}

static int sq_adjust(void *arg, int step)
{
    struct st *st = sq_ctx();
    struct sel *s = &st->s;
    u32 j, f = who(arg, &j), w, h;
    int d = step > 0 ? 1 : -1, big = step > 1 || step < -1;
    cell_now(st);
    if ((f == F_DC || f == F_RES) && j == 0u && f == F_DC) {   /* DC.adj: the next preset, stops at the ends */
        int k = dc_preset(s->dcw, s->dch);
        if (k < 0) { k = 0; for (u32 i = 1; i < N_DC; i++) if (sq_abs(DCW[i] - (int)s->dcw) < sq_abs(DCW[k] - (int)s->dcw)) k = (int)i; }
        else k = sq_max(0, sq_min((int)N_DC - 1, k + d));
        set_dc(st, DCW[k], DCH[k]);
        s->daw = DCW[k]; s->dah = DCH[k];
    } else if (f == F_RES && j == 0u) {               /* RES.adj */
        res_now(st, &w, &h);
        int k = res_hit(st, w, h), L = (int)st->n_list;
        if (k < 0) {
            k = -1;
            for (int i = 0; i < L && k < 0; i++) if (st->list[i].w > w) k = i;
            k = k < 0 ? L - 1 : d > 0 ? k : k - 1;
        } else k += d;
        k = sq_max(0, sq_min(L - 1, k));
        u32 nw = st->list[k].w, nh = st->list[k].h;
        set_res(st, (int)nw, (int)nh);
        s->raw = nw; s->rah = nh;
    } else if ((f == F_DC || f == F_RES) && (j == 1u || j == 2u)) {   /* dimTile.adj */
        u32 isdc = f == F_DC, lock = isdc ? s->dclock : s->reslock, aw = isdc ? s->daw : s->raw, ah = isdc ? s->dah : s->rah;
        if (isdc) { w = s->dcw; h = s->dch; } else res_now(st, &w, &h);
        int Wl = isdc ? WMAX : (int)s->dcw, Hl = isdc ? HMAX : (int)s->dch, nw = (int)w, nh = (int)h;
        dbl asp = dratio(aw, ah);
        if (j == 1u) { nw += d * 16 * (big ? 10 : 1); if (lock) nh = round_to(ddiv_int((u64)(nw > 0 ? nw : 0), asp), 2); }
        else { nh += d * 2 * (big ? 10 : 1); if (lock) nw = round_to(dmul(asp, (u64)(nh > 0 ? nh : 0)), 16); }
        if (nw > Wl || nh > Hl) {
            if (lock) return 0;
            nw = sq_min(nw, Wl); nh = sq_min(nh, Hl);
        }
        if (nw < WMIN || nh < HMIN) return 0;
        int pw = -1, ph = -1;
        if (isdc) {
            for (u32 i = 0; i < N_DC && pw < 0; i++)
                if (sq_abs(DCW[i] - nw) <= 16 && sq_abs(DCH[i] - nh) <= 2 && (!lock || asp_near(DCW[i], DCH[i], aw, ah))) { pw = DCW[i]; ph = DCH[i]; }
        } else {
            refresh_list(st);
            for (u32 i = 0; i < st->n_list && pw < 0; i++)
                if (sq_abs(st->list[i].w - nw) <= 16 && sq_abs(st->list[i].h - nh) <= 2 &&
                    (!lock || asp_near(st->list[i].w, st->list[i].h, aw, ah))) { pw = st->list[i].w; ph = st->list[i].h; }
        }
        if (pw >= 0 && lock) { nw = pw; nh = ph; }
        if (isdc) set_dc(st, nw, nh); else set_res(st, nw, nh);
    } else if (f == F_DC || f == F_RES) {             /* lockTile: the dial flips; locking takes the ratio */
        u32 *lk = f == F_DC ? &s->dclock : &s->reslock;
        *lk ^= 1u;
        if (*lk) { dc_size(st, f, &w, &h); if (f == F_DC) { s->daw = w; s->dah = h; } else { s->raw = w; s->rah = h; } }
        st->dirty = 1;
    } else if (f == F_FPS) {
        if (!has_q(st)) return 0;
        struct rat fr = {s->fps_n, s->fps_d};
        if (s->fine) { fr = fine_step(st, fr, d, big); s->fps_n = fr.n; s->fps_d = fr.d; st->dirty = 1; return 0; }
        fps_list(st);
        int k = fps_sel(st), L = (int)st->n_fl;
        if (k < 0) {
            int a = -1;
            for (int i = 0; i < L && a < 0; i++) if (d > 0 ? rgt(st->fl_e[i].f, fr) : rge(st->fl_e[i].f, fr)) a = i;
            k = d > 0 ? a - 1 : a;
        }
        int jj = k + d;
        while (jj >= 0 && jj < L && st->fl_e[jj].na) jj += d;
        if (jj >= 0 && jj < L) { s->fps_n = st->fl_e[jj].f.n; s->fps_d = st->fl_e[jj].f.d; st->dirty = 1; }
    } else if (f == F_RECIPE && j == 0u) {            /* RECIPE.adj: presets, usable only */
        const struct cell *cl = st->cur;
        const struct rcp *c = cur_recipe(st), *P[MAXR];
        int np = 0, jj = -1;
        for (int i = 0; i < cl->n; i++) if (is_preset(&cl->r[i])) { if (c && rq_of(&cl->r[i]) == rq_of(c)) jj = np; P[np++] = &cl->r[i]; }
        if (jj < 0 && c) {
            jj = 0;
            for (int i = 0; i < np; i++) if (P[i]->ad == c->ad && P[i]->mh == c->mh && P[i]->mv == c->mv) { jj = i; break; }
        } else jj += d;
        while (jj >= 0 && jj < np && !usable(st, P[jj])) jj += d;
        if (jj >= 0 && jj < np) {
            s->rq = rq_of(P[jj]); s->rd_ok = 1;
            for (u32 k = 0; k < N_PARAM; k++) s->rd[k] = pval(P[jj], k);
            st->dirty = 1;
        }
    } else if (f == F_RECIPE) {
        const struct rcp *c = cur_recipe(st);
        u32 key = j - 1u;
        if (!c) return 0;
        if (key == K_HB || key == K_VB) {             /* ispBinTile.adj: 1, then this mode's kernels */
            u32 *kk = key == K_HB ? &s->kh : &s->kv, b = key == K_HB ? c->hb : c->vb;
            int jj = b == 3u ? 1 + (int)*kk + d : (d > 0 ? 1 + (int)*kk : -1);
            if (jj < 0 || jj > 6) return 0;
            const struct rcp *q = combo(st, key, jj == 0 ? 1u : 3u);
            if (!q) return 0;
            use_recipe(st, q);
            if (jj) *kk = (u32)jj - 1u;
        } else {
            u32 V[MAXR], nv = vals(st, key, V);
            int jj = -1;
            for (u32 i = 0; i < nv; i++) if (V[i] == pval(c, key)) jj = (int)i;
            jj += d;
            while (jj >= 0 && jj < (int)nv && !combo(st, key, V[jj])) jj += d;
            if (jj >= 0 && jj < (int)nv) use_recipe(st, combo(st, key, V[jj]));
        }
    }
    return 0;
}

static int sq_fine(void *arg, int on)                /* AEL on FPS: fine mode */
{
    struct st *st = sq_ctx();
    (void)arg;
    cell_now(st);
    if (on) {
        if (!has_q(st)) return 0;
        st->s.fine = 1; st->s.fc_d = 0;               /* entering fine drops the old tuned rate */
        st->dirty = 1;
        return 1;
    }
    if (st->s.fine) { fine_exit(st); st->dirty = 1; }
    return 0;
}

/* ---------------------------------------------------------------------------------------------- test entry */
/* The pure rules for the exhaustive offline tests (test_slqs.py calls it under unicorn): op 1 a16(W*r),
 * 2 ev(H*r), 3 mm text, 4 ratio text, 5 kLabel (3-5 return the text's address), 6 rh(w / (b/c)), 7 rw(h * (b/c)),
 * 8 |pw/ph - b/c| < 0.002, 9 core_qualities_tol of the cell (timing). */
USED int sq_test(u32 op, u32 a, u32 b, u32 c)
{
    struct st *st = sq_ctx();
    char *d = st->v[0][0];
    d[0] = 0;
    if (op == 1u) return a16r((int)a, b);
    if (op == 2u) return evr((int)a, b);
    if (op == 3u) { mm_put(d, 0, a); return (int)(uintptr_t)d; }
    if (op == 4u) { put_fix(d, 0, TXT, (u64)js_fixed_d(dratio(a, b), 3), 3); return (int)(uintptr_t)d; }
    if (op == 5u) { k_label(d, a); return (int)(uintptr_t)d; }
    if (op == 6u) return round_to(ddiv_int(a, dratio(b, c)), 2);
    if (op == 7u) return round_to(dmul(dratio(b, c), a), 16);
    if (op == 8u) return asp_near(a >> 16, a & 0xFFFFu, b, c);
    if (op == 10u) return (int)(uintptr_t)&st->applied;
    if (op == 9u) return core_qualities_tol((int)(a >> 16), (int)(a & 0xFFFFu), (int)(b >> 16), (int)(b & 0xFFFFu), 0, 1,
                                            TOL_NUM, TOL_DEN, st->scratch, (int)CORE_MAX_QUAL);
    return -1;
}

/* ---------------------------------------------------------------------------------------------- entry */
struct cfg { u32 magic, version, state_off, dma_off, rec_off; };

USED int sup_entry(void *block, const struct sl_svc *svc, const char *path)
{
    const struct sl4_header *hd = (const struct sl4_header *)block;
    const struct cfg *c = (const struct cfg *)((const u8 *)block + SL4_HEADER_LEN);
    (void)path;
    if (svc->version < 6u || c->magic != CFG_MAGIC || c->version != 2u || c->state_off < hd->file_len ||
        c->state_off + sizeof(struct st) > c->dma_off || c->dma_off + FO_BYTES + 0x400u > hd->block_size ||
        c->rec_off + 4u * REC_WORDS > hd->file_len || (c->rec_off & 3u))
        return SL_RELEASE;
    struct st *st = (struct st *)((u8 *)block + c->state_off);
    zero(st, sizeof *st);
    st->svc = svc; st->block = (const u8 *)block; st->rec_off = c->rec_off; st->dma_off = c->dma_off;
    W(sq_ctx_at()) = (u32)(uintptr_t)st;
    struct sel *s = &st->s;                           /* the page's initial S */
    s->dcw = 6048; s->dch = 3402; s->dclock = 1; s->reslock = 1; s->daw = 6048; s->dah = 3402; s->raw = 6048; s->rah = 3402;
    s->rat = 3; s->fps_n = 5994; s->fps_d = 100; s->kh = 1; s->kv = 1;
    st->loaded = (u32)rec_load(s, (const u32 *)((const u8 *)block + c->rec_off));
    for (u32 fi = 0; fi < N_FN; fi++) {
        struct qsc_func *f = &st->f[fi];
        f->sup_id = hd->sup_id;
        for (u32 k = 0; k < QSC_NAME - 1u && FN_NAME[fi][k]; k++) f->name[k] = FN_NAME[fi][k];
        f->label = FN_LABEL[fi];
        f->icon = FN_ICON[fi][0] ? FN_ICON[fi] : 0;
        f->flags = QSC_F_CINE | QSC_F_LOCK_REC | (fi == F_RECIPE ? QSC_F_TITLE : 0u);
        f->value = sq_value;
        f->adjust = fi == F_FORMAT ? 0 : sq_adjust;
        f->small = sq_small;
        f->footer = sq_footer;
        f->arg = &st->arg[fi][0];
        if (fi == F_FPS) f->fine = sq_fine;
        u32 ns = fi == F_DC || fi == F_RES ? 3u : fi == F_RECIPE ? 7u : 0u;
        for (u32 j = 0; j < ns; j++) {
            struct qsc_sub *b = &st->sub[fi][j];
            b->label = fi == F_RECIPE ? SUB_LABEL[j] : j == 0u ? "WIDTH" : j == 1u ? "HEIGHT" : "RATIO";
            b->value = sq_value;
            b->adjust = sq_adjust;
            b->arg = &st->arg[fi][j + 1u];
            b->small = sq_small;
            b->footer = sq_footer;
            b->lock = fi != F_RECIPE && j == 2u ? sq_lock_icon : 0;
        }
        if (ns) { st->subs[fi].n = ns; st->subs[fi].item = st->sub[fi]; f->sub = &st->subs[fi]; }
    }
    st->t.magic = QSC_TABLE_MAGIC4;
    st->t.n = N_FN;
    st->t.f = st->f;
    st->t.leave = sq_leave;
    st->t.leave_arg = st;
    svc->publish(svc);
    return svc->provide(svc, QSC_TAG(hd->sup_id), &st->t) == SL_OK ? SL_KEEP : SL_RELEASE;
}
