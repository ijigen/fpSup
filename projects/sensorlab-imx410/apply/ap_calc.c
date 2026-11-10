/* SensorLab-IMX410 apply: the pure half -- one selection -> everything a slot installs.
 *
 * No firmware access, no globals: host-testable (test_apply.py CalcTests compiles this with core.c for the host and
 * compares every field with the Python it ports).  ap.c includes this file.  Sources of each field:
 *   tables, R10        core_quality_plan(q, CLK / (hm x VMAX)) -> core_smc_create     (imx410-lab readout_cfg + smc)
 *   ISP words / mask   core_quality_spec -> core_isp_plan                              (isp-lab isp_formula v2)
 *   standby w / h      core_isp_plan .standby                                          (isp_custom standby_diffs)
 *   aspect, LV boxes   record output w/h + isp_custom lv_box / lvout_rules / display_diffs
 *   binfilt            isp_custom binfilt_cfg packing (res-custom ogc_binfilt.c SEC_BINFILT)
 *   DNG FrameRate      APPLY_DESIGN §11.4: the selected rate's broadcast rational when the sensor's real rate is
 *                      within 50 ppm of it, else the real rate CLK / (HMAX x VMAX) reduced
 *   carrier            APPLY_DESIGN §12.4: the slowest stock rate >= the selection (within 50 ppm), 119.88 above it
 *   engine fps (+0x30) the carrier's stock value (ogc_layout.RATES) up to 119.88; above it the real rate as a float
 *                      (res-custom rate() default; > 99 takes the high-rate path, HIGH_FRAME_RATE_PATH.md)
 *   standby words      the formula's preview-side words over the standby profile 5, only inside the freeze gate
 *                      (§12.2: source <= 2100 x 1710, visible <= 2000 x 1334, raster inside the source) */
#include <stdint.h>
#include "core.h"
#include "core_data.h"

typedef uint32_t u32;
typedef int32_t s32;
typedef uint64_t u64;

#define APC_TOL_NUM 1u                    /* slqs.c TOL_NUM / TOL_DEN: the 2 % visible tolerance */
#define APC_TOL_DEN 50u
#define APC_LCD_W 1620u                   /* isp_custom LCD_W / LCD_H, DET_W / DET_HMAX */
#define APC_LCD_H 1080u
#define APC_DET_W 320u
#define APC_DET_HMAX 240u
#define APC_PPM_TOL 20000u                /* 1 / 20000 = 50 ppm */

/* the nine carriers: the firmware's internal frame-rate enum (FR_GET), fps x 100, the picker key suffix,
 * canvas +0x30 as stock declares it (ogc_layout.RATES) */
struct apc_rate { u32 en, rank, engine, num, den; char sfx[6]; };
static const struct apc_rate APC_RATES[9] = {                 /* slowest first */
    {1, 2398, 0x41C00000u, 24000, 1001, "23_98"}, {12, 2400, 0x41C00000u, 24, 1, "24"},
    {2, 2500, 0x41C80000u, 25, 1, "25"}, {3, 2997, 0x41F00000u, 30000, 1001, "30"},
    {13, 4800, 0x42400000u, 48, 1, "48"}, {4, 5000, 0x42480000u, 50, 1, "50"},
    {5, 5994, 0x42700000u, 60000, 1001, "60"}, {6, 10000, 0x42480000u, 100, 1, "100"},
    {7, 11988, 0x42700000u, 120000, 1001, "120"},
};
/* the preview-side words of the formula that a standby (class 1, no record) profile takes (§12.2) */
static const uint8_t APC_SB_WORDS[14] = {0x0C / 4, 0x10 / 4, 0x1C / 4, 0x20 / 4, 0x28 / 4, 0x38 / 4, 0x58 / 4, 0x60 / 4,
                                         0xC4 / 4, 0xD0 / 4, 0xF4 / 4, 0xF8 / 4, 0xFC / 4, 0x100 / 4};   /* word indices */
#define APC_SRC_MAX_W 2100u               /* isp_formula R6 / R12 / STANDBY_VIS_MAX */
#define APC_SRC_MAX_H 1710u
#define APC_VIS_MAX_W 2000u
#define APC_VIS_MAX_H 1334u
#define APC_VIS_CUT 8u                    /* the most preview rows / columns the standby copy cuts to reach the cap */

struct apc_work {                         /* scratch, caller-owned (big: the quality list) */
    core_quality q[CORE_MAX_QUAL];
    core_plan plan;
    core_isp_result isp;
    core_spec spec;
};

struct apc_out {
    core_mode mode;                       /* the eight rows (mode id words 0: the installer writes its own) */
    u32 donor, key, hm, vmax, carrier, rank, engine, sfx_len;
    char sfx[6];
    u32 isp[65], mask[3];                 /* the formula's words (only the mask's) */
    u32 rec_w, rec_h, sb_w, sb_h;
    u32 asp_n, asp_d;                     /* RES output image aspect, limit_denominator(1000) */
    u32 is169;                            /* within 0.5 % of 16:9: the stock display is right */
    u32 box_w, box_h, det_h;              /* LV buffers: idx 0 and idx 2 (det_h 0 = keep the stock one) */
    u32 dng_n, dng_d, binfilt;
    s32 detail;                           /* the CORE_E_* / ISP_WHY_* of a refusal */
    u32 fast;                             /* engine > 99: the high-rate path, clock gate forced */
    u32 sok, smask[3];                    /* standby readout allowed; its words = isp[i] for i in smask */
    u32 src_w, src_h, vis_w, vis_h, ras_w, ras_h;
    u32 rec14;                            /* a true 14-bit DNG (1:1): the DNG BlackLevel needs the 14-bit scale */
    u32 ds_on, ds[4];                     /* v0.6.0: the DNG DefaultScale {h num, h den, v num, v den} when the pixels
                                             are not square (> 0.5 %): one axis stretched, never shrunk */
    /* v0.7.1test: the standby copy of the preview's visible / raster (0x20 / 0x28, 0x0C / 0x10). The formula's visible
     * can run a few rows past the stock standby cap 2000 x 1334 (a custom DC: 1335 on every other 16 px step of
     * OG width); that turned the standby gate off, the stock LV ran under our LV box / aspect = the picture
     * squeezed, not cropped. Standby takes the visible cut to the cap (a few preview rows, the same centre);
     * the record keeps the formula's words. sclamp: the standby words differ from isp[]. */
    u32 sv_w, sv_h, sr_w, sr_h, sclamp;
    /* v0.7.2test: rok -- the record route may run in standby.  In CinemaDNG standby asks the record route table TAB3
     * (live 10-30), so standby IS the record's readout: the only hard limits are the freezes (R12 source <= 1710
     * rows, R6 / r71 raster inside the source, visible <= 2000 wide).  The 2000 x 1334 visible cap is the stock
     * standby profiles' window (full sensor / 3 = 2016 x 1344), not a freeze: isp-lab 10-28 p5 ran HD 3x2 (visible
     * 1671..1686 over a 1702-row source) in standby and recording, 6 of 6 pass.  sok (with the cap) stays the MOV-table
     * standby's gate (its base row is the stock standby profile 5). */
    u32 rok;
};

enum { APC_OK = 0, APC_E_RECIPE = -4, APC_E_CORE = -5, APC_E_ISP = -6, APC_E_RATE = -7 };

/* ---- integer helpers (the A9 has no divider: shift-subtract, as core.c) ---- */
static u64 apc_div(u64 n, u64 d)
{
    if (!d) return 0;
    u64 q = 0, r = 0;
    for (int i = 63; i >= 0; i--) {
        r = (r << 1) | ((n >> i) & 1u);
        if (r >= d) { r -= d; q |= (u64)1 << i; }
    }
    return q;
}
static u64 apc_mod(u64 n, u64 d) { return n - apc_div(n, d) * d; }
static u64 apc_gcd(u64 a, u64 b) { while (b) { u64 t = apc_mod(a, b); a = b; b = t; } return a; }
/* round(n / d) half to even (Python round of an exact rational) */
static u64 apc_round(u64 n, u64 d)
{
    u64 q = apc_div(n, d), r = n - q * d;
    if (2u * r > d || (2u * r == d && (q & 1u))) q++;
    return q;
}

/* Fraction(n, d).limit_denominator(lim) -- CPython's algorithm, exact */
static void apc_limit(u64 n, u64 d, u64 lim, u32 *pn, u32 *pd)
{
    u64 g = apc_gcd(n, d);
    n = apc_div(n, g); d = apc_div(d, g);
    if (d <= lim) { *pn = (u32)n; *pd = (u32)d; return; }
    u64 p0 = 0, q0 = 1, p1 = 1, q1 = 0, N = n, D = d;
    for (;;) {
        u64 a = apc_div(N, D), q2 = q0 + a * q1;
        if (q2 > lim) break;
        u64 t = p0 + a * p1;
        p0 = p1; q0 = q1; p1 = t; q1 = q2;
        u64 r = N - a * D;
        N = D; D = r;
    }
    u64 k = apc_div(lim - q0, q1);
    u64 bn = p0 + k * p1, bd = q0 + k * q1;               /* bound1 = bn / bd, bound2 = p1 / q1 */
    /* |p1/q1 - n/d| <= |bn/bd - n/d|  <=>  |p1 d - n q1| bd <= |bn d - n bd| q1 */
    u64 e2 = p1 * d > n * q1 ? p1 * d - n * q1 : n * q1 - p1 * d;
    u64 e1 = bn * d > n * bd ? bn * d - n * bd : n * bd - bn * d;
    if (e2 * bd <= e1 * q1) { *pn = (u32)p1; *pd = (u32)q1; }
    else { *pn = (u32)bn; *pd = (u32)bd; }
}

/* the carrier: the slowest stock rate not slower than sn / sd (50 ppm under counts as equal), else 119.88 */
static const struct apc_rate *apc_carrier(u32 sn, u32 sd)
{
    for (u32 i = 0; i < 9u; i++) {
        const struct apc_rate *r = &APC_RATES[i];
        /* r >= sel (1 - 50 ppm)  <=>  20000 r.num sd >= 19999 sn r.den */
        if (20000u * (u64)r->num * sd >= 19999u * (u64)sn * r->den) return r;
    }
    return &APC_RATES[8];
}
/* IEEE single of n / d, round to nearest even (n, d > 0, the ratio far inside the normal range) */
static u32 apc_f32(u64 n, u64 d)
{
    if (!n || !d) return 0;
    int e = 23;
    while (n < (d << 23)) { n <<= 1; e--; }
    while (n >= (d << 24)) { d <<= 1; e++; }
    u64 m = apc_div(n, d), r = n - m * d;
    if (2u * r > d || (2u * r == d && (m & 1u))) m++;
    if (m == (1u << 24)) { m >>= 1; e++; }
    return (u32)(e + 127) << 23 | (u32)(m & 0x7FFFFFu);
}

/* The DNG FrameRate: the real rate CLK / (hm x vmax); the selected rate's own rational when within 50 ppm of it,
 * as k x 1000 / 1001 when the selection is a broadcast rate (29.97 = 2997/100 -> 30000/1001). */
static void apc_dng_rate(u32 hm, u32 vmax, u32 sn, u32 sd, u32 *on, u32 *od)
{
    u64 an = CD_CLK, ad = (u64)hm * vmax;                 /* the real rate an / ad */
    u64 g = apc_gcd(an, ad);
    *on = (u32)apc_div(an, g); *od = (u32)apc_div(ad, g);
    if (!sn || !sd) return;
    u64 x = an * sd, y = (u64)sn * ad;                    /* real - sel ~ (x - y) / (ad sd) */
    u64 diff = x > y ? x - y : y - x;
    if (diff > apc_div(y, APC_PPM_TOL)) return;           /* more than 50 ppm off: the real rate */
    u64 k = apc_round((u64)sn * 1001u, (u64)sd * 1000u);  /* sel ~ k x 1000 / 1001 ? */
    u64 bx = (u64)sn * 1001u, by = k * 1000u * sd;
    u64 bdiff = bx > by ? bx - by : by - bx;
    if (k && sd != 1u && bdiff * 100000u <= by) { *on = (u32)(k * 1000u); *od = 1001u; return; }
    g = apc_gcd(sn, sd);
    *on = (u32)apc_div(sn, g); *od = (u32)apc_div(sd, g);
}

/* isp_custom lv_box / lvout_rules / display_diffs on the exact rational a = an / ad.
 * b = {is169, asp_n, asp_d, box_w, box_h, det_h}: shared by live RES output (apc_display)
 * and playback's metadata-derived aspect (ap.c). */
static void apc_box(u64 an, u64 ad, u32 *b)
{
    /* 16:9 within 0.5 %: |a / (16/9) - 1| < 0.005  <=>  200 |9 an - 16 ad| < 16 ad */
    u64 x = 9u * an, y = 16u * ad, dd = x > y ? x - y : y - x;
    b[0] = 200u * dd < 16u * ad;
    apc_limit(an, ad, 1000u, &b[1], &b[2]);
    if (2u * an >= 3u * ad) {                             /* a >= 1620 / 1080 */
        b[3] = APC_LCD_W;
        b[4] = (u32)apc_div(apc_round(APC_LCD_W * ad, an), 2u) * 2u;
    } else {
        b[3] = (u32)apc_div(apc_round(APC_LCD_H * an, ad), 16u) * 16u;
        b[4] = APC_LCD_H;
    }
    u64 dh = apc_round(APC_DET_W * ad, an);
    b[5] = dh <= APC_DET_HMAX ? (u32)dh : 0u;
}
static void apc_display(struct apc_out *o, u64 an, u64 ad)
{
    u32 b[6];
    apc_box(an, ad, b);
    o->is169 = b[0]; o->asp_n = b[1]; o->asp_d = b[2]; o->box_w = b[3]; o->box_h = b[4]; o->det_h = b[5];
}

/* v0.6.0 (Bei 10-30): the DNG DefaultScale (0xC61E) of an anamorphic recipe.  The DNG holds rec_w x rec_h pixels of
 * a scene an : ad wide, so one pixel is p = (an rec_h) / (ad rec_w) as wide as it is tall; the scale that makes them
 * square stretches the short axis: (p, 1) or (1, 1 / p), limit_denominator(1000).  Square within 0.5 %: no tag. */
static void apc_dscale(struct apc_out *o, u64 an, u64 ad)
{
    u64 pn = an * o->rec_h, pd = ad * o->rec_w, x = pn > pd ? pn - pd : pd - pn;
    o->ds_on = 0; o->ds[0] = o->ds[1] = o->ds[2] = o->ds[3] = 1u;
    if (!pn || !pd || 200u * x < pd) return;
    if (pn > pd) apc_limit(pn, pd, 1000u, &o->ds[0], &o->ds[1]);
    else apc_limit(pd, pn, 1000u, &o->ds[2], &o->ds[3]);
    o->ds_on = 1;
}

/* the standby readout's freeze gate (§12.2) */
static u32 apc_route_ok(u32 sw, u32 sh, u32 vw, u32 vh, u32 rw, u32 rh)
{
    return sw <= APC_SRC_MAX_W && sh <= APC_SRC_MAX_H && vw <= APC_VIS_MAX_W && rw <= sw && rh <= sh && vw && vh;
}
static u32 apc_standby_ok(u32 sw, u32 sh, u32 vw, u32 vh, u32 rw, u32 rh)
{
    return apc_route_ok(sw, sh, vw, vh, rw, rh) && vh <= APC_VIS_MAX_H;
}

static u32 apc_binfilt(s32 hbin, s32 vbin, u32 kh, u32 kv, u32 km)
{
    if (hbin != 3 && vbin != 3) return 0;
    if (kh > 5u || kv > 5u || km > 1u) return 0xFFFFFFFFu;
    return 0x800u | (hbin == 3 ? 0x200u : 0u) | (vbin == 3 ? 0x400u : 0u) | km << 8 | kh | kv << 4;
}

/* One selection (dcw, dch, rw, rh, key, hbin, vbin, hm, vmax, fps, kernels) on carrier `carrier_en` -> o. */
static int apc_build(u32 dcw, u32 dch, u32 rw, u32 rh, s32 key, s32 hbin, s32 vbin, u32 hm, u32 vmax,
                     u32 fps_n, u32 fps_d, u32 kh, u32 kv, u32 km,
                     struct apc_work *w, struct apc_out *o)
{
    for (u32 i = 0; i < sizeof *o; i++) ((volatile uint8_t *)o)[i] = 0;
    if (!fps_n || !fps_d || !hm || !vmax) return APC_E_RECIPE;
    const struct apc_rate *cr = apc_carrier(fps_n, fps_d);
    o->carrier = cr->en; o->rank = cr->rank; o->engine = cr->engine;
    /* above 119.88 the engine declares the real rate (> 99: the high-rate path) */
    if (20000u * 120000u * (u64)fps_d < 19999u * (u64)fps_n * 1001u) o->engine = apc_f32(CD_CLK, (u64)hm * vmax);
    o->fast = o->engine > 0x42C60000u;    /* positive floats order as their bits: > 99.0 */
    for (u32 i = 0; i < 6u; i++) { o->sfx[i] = cr->sfx[i]; if (cr->sfx[i]) o->sfx_len = i + 1u; }
    int n = core_qualities_tol((int)dcw, (int)dch, (int)rw, (int)rh, 0, 1, APC_TOL_NUM, APC_TOL_DEN, w->q,
                               (int)CORE_MAX_QUAL);
    if (n < 0) { o->detail = n; return APC_E_RECIPE; }
    const core_quality *q = 0;
    for (int i = 0; i < n; i++)
        if (w->q[i].key == key && w->q[i].hbin == hbin && w->q[i].vbin == vbin) { q = &w->q[i]; break; }
    if (!q || (u32)q->hm != hm || vmax < (u32)q->vmin_lo || vmax > (u32)CD_VMAX_MAX) return APC_E_RECIPE;
    u32 bf = apc_binfilt(hbin, vbin, kh, kv, km);
    if (bf == 0xFFFFFFFFu) return APC_E_RECIPE;
    int rc = core_quality_plan(q, CD_CLK, hm * vmax, &w->plan);
    if (rc) { o->detail = rc; return APC_E_CORE; }
    if ((u32)w->plan.vmax != vmax || (u32)w->plan.hmax != hm) { o->detail = CORE_E_VMAX; return APC_E_CORE; }
    rc = core_smc_create(&w->plan, &o->mode);
    if (rc) { o->detail = rc; return APC_E_CORE; }
    core_quality_spec(q, &w->spec);
    /* Canvas +B0 follows the native 100/120 carrier, including its 50/60 Hz engine. */
    w->spec.hirate = cr->rank >= 10000u;
    w->spec.record_preview = o->fast;  /* >99 engine: prefer the existing record tap, within R6/R12 bounds */
    /* Bei 10-30 (notes/RWZM_14BIT_CHECK.md, 766 frames): RWZM carries 12 bits, so a 14-bit-AD recipe that scales (zoom
     * != 1024 on either axis, every CRCT bin) is recorded in a 12-bit container (12-bit plane code, 12-bit DNG); the
     * sensor stays 14-bit AD.  Only 1:1 stays a true 14-bit DNG. */
    if (w->spec.bits == 14 && !(w->spec.zh == 1024 && w->spec.zv == 1024 && w->spec.hbin == 1 && w->spec.vbin == 1))
        w->spec.bits = 12;
    o->rec14 = w->spec.bits == 14;
    rc = core_isp_plan(&w->spec, &w->isp);
    if (rc) { o->detail = w->isp.why; return APC_E_ISP; }
    for (u32 i = 0; i < 65u; i++) o->isp[i] = w->isp.words[i];
    for (u32 i = 0; i < 3u; i++) o->mask[i] = w->isp.mask[i];
    o->donor = (u32)w->plan.donor; o->key = (u32)key; o->hm = hm; o->vmax = vmax;
    o->rec_w = (u32)w->isp.rec[0]; o->rec_h = (u32)w->isp.rec[1];
    o->sb_w = (u32)w->isp.standby[0]; o->sb_h = (u32)w->isp.standby[1];
    /* aspect.dng_aspect: rec x max(Z, 1024) x scale x bin per axis */
    u64 zh = (u64)(w->spec.zh > 1024 ? w->spec.zh : 1024), zv = (u64)(w->spec.zv > 1024 ? w->spec.zv : 1024);
    u64 an = (u64)o->rec_w * zh * (u64)w->spec.sx * (u64)w->spec.hbin;
    u64 ad = (u64)o->rec_h * zv * (u64)w->spec.sy * (u64)w->spec.vbin;
    if (!an || !ad) { o->detail = CORE_E_ZERO; return APC_E_ISP; }
    /* Liveview shows RES's output shape, including independent-axis scaling.
     * Physical sensor/pixel correction belongs to DNG DefaultScale below. */
    apc_display(o, o->rec_w, o->rec_h);
    apc_dscale(o, an, ad);
    /* the standby readout's gate (the freezes: R12 tall preview source, r71 raster past the source) */
    o->src_w = (u32)w->isp.source[0]; o->src_h = (u32)w->isp.source[1];
    o->vis_w = (u32)w->isp.visible[0]; o->vis_h = (u32)w->isp.visible[1];
    o->ras_w = (u32)w->isp.raster[0]; o->ras_h = (u32)w->isp.raster[1];
    o->sv_w = o->vis_w; o->sv_h = o->vis_h; o->sr_w = o->ras_w; o->sr_h = o->ras_h;
    if (o->sv_w > APC_VIS_MAX_W && o->sv_w <= APC_VIS_MAX_W + APC_VIS_CUT) {
        o->sr_w -= o->sv_w - APC_VIS_MAX_W; o->sv_w = APC_VIS_MAX_W; o->sclamp = 1;
    }
    if (o->sv_h > APC_VIS_MAX_H && o->sv_h <= APC_VIS_MAX_H + APC_VIS_CUT) {
        o->sr_h -= o->sv_h - APC_VIS_MAX_H; o->sv_h = APC_VIS_MAX_H; o->sclamp = 1;
    }
    o->sok = apc_standby_ok(o->src_w, o->src_h, o->sv_w, o->sv_h, o->sr_w, o->sr_h);
    o->rok = apc_route_ok(o->src_w, o->src_h, o->sv_w, o->sv_h, o->sr_w, o->sr_h);
    for (u32 k = 0; k < 14u; k++) {
        u32 i = APC_SB_WORDS[k];
        if (o->mask[i >> 5] >> (i & 31u) & 1u) o->smask[i >> 5] |= 1u << (i & 31u);
    }
    apc_dng_rate(hm, vmax, fps_n, fps_d, &o->dng_n, &o->dng_d);
    o->binfilt = bf;
    return APC_OK;
}
