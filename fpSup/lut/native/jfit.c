/* jfit.c — the joint LV fit (projects/lut-sup/probes/joint_fit_eval.py, split=False) in float, for the camera.
 *
 * Chain (camera-verified 2026-11-04, lut-joint-06): c -> RGBLMAT M (both groups) -> three tone tables
 * (the neutral curves + 9 knots per channel) -> YCMAT (601 form) -> CEQ (24 anchors, linear in angle, a pair forward mod 360)
 * -> YGAM (17 nodes) -> stock 601 inverse = the ring.  Residual = (Lab(chain) - want) * w, plus CEQ
 * neighbour smoothness, a small cost on the curve edits and the hue-order hinges (11-10) -- exactly the Python resid().
 * Gauss-Newton with a numerical Jacobian; a column is recomputed only on the samples its parameter can
 * move (tone knot: index window; CEQ anchor: hue window; YGAM node: luma above its left neighbour).
 *
 * Floats on the VFP (build: -mfloat-abi=softfp -mfpu=vfpv3-d16).  The kernel saves d0-d15 + FPSCR on every
 * interrupt and switch (0xC0000D24 / 0xC0000E78), so any task may use them; NEON (d16-d31) is not saved.
 * No libm, no .rodata (scalar constants only), no divide helpers (VFP divides).  Also builds natively for
 * the host parity test (fpSup/lut/test_jfit.py). */
#ifndef JFIT_C
#define JFIT_C
#include <stdint.h>

#define JF_NP     148                    /* parameters: the Python layout (140), then JFIT v6's CKNEE (8: JF_NK) */
#define JF_NK     140                    /* JFIT v6 (camera 2026-11-11, projects/lut-sup/validation/20261111-cknee-cal): the ISP's
                                          * CKNEE after YCMAT, before CEQ -- P[JF_NK..+7] = (knee, slope) for +Cb, -Cb, +Cr, -Cr
                                          * (fitter.py iK; shadow 10C0, 10D0, 10C8, 10D8): a half-axis' magnitude v above its
                                          * knee k goes on at k + (v - k) slope.  Knee in the chain's chroma units (YCMAT / 512),
                                          * the 9-bit code / 1024; slope the 5-bit code / 16 (camera-read from JPG pairs 11-11, cknee_direct.py; the /19 of the
                                          * renderer calibration was wrong), at most 24 / 16 (expansion past that clips RGB). */
#define JF_KOFF   8.0f                   /* "no CKNEE": a knee beyond any chroma (the chain unchanged) -- every stage but the
                                          * untied refine, and a file without one */
#define JF_KMAX   0.4990234375f          /* 511 / 1024 */
#define JF_SMAX   1.5f                   /* 24 / 16 (Bei 2026-11-11) */
#define JF_PAY_KN 12564u                 /* jft.PAYLOAD's CKNEE block (v6), after m1: u32 on, then the record's +4 .. +15 */
#define JF_KN     9
#define JF_NTONE  2048
#define JF_WHITE  1918.0f
/* CEQ hue destinations must stay in order (camera 2026-11-10: Fuji 3513DI / Kodak 2383 JFTs with dest[17] < dest[16]
 * showed magenta in greens -- the ISP interpolates a destination pair forward mod 360, so a decreasing pair goes the
 * long way round and the hues between sweep the whole circle).  Forward step between neighbours, in degrees:
 * gap[a] = 15 + dh[a+1] - dh[a] (cyclic).  JF_HUE_GAP is the floor every shipped table keeps (1/4 of the 15 deg node
 * spacing = 682.7 words: no hue span squeezed more than 4x, i.e. never a fold, and far above the 1-word rounding);
 * the fit's hinge starts 1 deg above it (JF_HUE_FIT) so a fitted table needs no clamp; the clamp (jf_hue_safe) aims
 * at JF_HUE_SAFE, a little above the floor, so rounding to words cannot take a gap below it. */
#define JF_HUE_GAP   3.75f
#define JF_HUE_FIT   4.75f
#define JF_HUE_SAFE  3.8f
#define JF_W_MONO    10.0f               /* the hinge weight (struct jfit w_mono): 1 deg short costs 100, ~ 100 dE^2 */
#define JF_HUE_WORDS 683u                /* JF_HUE_GAP in CEQ words (65536 = 360 deg), rounded up */
#define JF_NTAIL     (72 + 27 + 24)      /* jf_tail's rows: CEQ smoothness, curve edits, hue order (hinge) */

struct jfit {
    /* inputs */
    uint32_t n;                          /* samples */
    const float *xs;                     /* n x 3 camera RGB */
    const float *want;                   /* n x 3 Lab of the target */
    const float *w;                      /* n weights (sqrt of the lvb weight) */
    const float *base_tone;              /* 3 x 2048, 0..1 (the neutral curves) */
    float P[JF_NP];                      /* start in, solution out */
    uint32_t iters;
    float w_hue, w_gain, w_curve;        /* tail weights: 0.02, 2.0, 2.0 (data, not literals: a double literal
                                          * would force an 8-aligned literal pool, beyond the sup's .text contract) */
    /* work (caller provides) */
    float *tone;                         /* 3 x 2048 */
    float *res, *res2;                   /* nres each */
    float *pert;                         /* 27 x 2048: each knot's perturbed channel table */
    double *A;                           /* nfree x nfree (+ nfree for g): double, the sums are long */
    float *pre;                          /* n x 4: idx r,g,b (tone index) and hue (deg), then n luma */
    /* out */
    float cost;
    uint32_t evals, steps;
    /* progress (0 = none): called after each Gauss-Newton iteration */
    void (*tick)(void *ctx, uint32_t it);
    void *tick_ctx;
    /* (0 = none) called often inside an iteration (every 32 samples of the Jacobian), same ctx: the camera's
     * hourglass (conv.c conv_spin) */
    void (*spin)(void *ctx);
    float w_mono;                        /* hue-order hinge weight per degree below JF_HUE_FIT (10; 0 = off -- last, so
                                          * the fields before keep their offsets) */
};

/* ---------------------------------------------------------------- math, no libm */
static float jf_abs(float x) { return x < 0 ? -x : x; }
static float jf_clamp(float x, float lo, float hi) { return x < lo ? lo : x > hi ? hi : x; }
static float jf_sqrt(float x) { return x > 0 ? __builtin_sqrtf(x) : 0; }
static float jf_log2(float x) {                         /* x > 0 */
    union { float f; uint32_t u; } v = {x};
    float e = (float)((int)((v.u >> 23) & 0xFF) - 127);
    v.u = (v.u & 0x007FFFFFu) | 0x3F800000u;             /* m in [1,2) */
    float m = v.f, t = (m - 1) / (m + 1), t2 = t * t;    /* log2(m) = 2/ln2 * atanh(t) */
    return e + 2.8853900817779268f * t * (1 + t2 * (0.33333333f + t2 * (0.2f + t2 * (0.14285714f + t2 * 0.11111111f))));
}
static float jf_exp2(float x) {
    if (x < -126) return 0;
    if (x > 127) x = 127;
    int i = (int)x; if ((float)i > x) i--;
    float f = x - (float)i, p = 1 + f * (0.69314718f + f * (0.24022651f + f * (0.05550411f + f * (0.00961813f + f * 0.00133336f))));
    union { float f; uint32_t u; } v; v.u = (uint32_t)(i + 127) << 23;
    return v.f * p;
}
static float jf_pow24(float x) { return x <= 0 ? 0 : jf_exp2(2.4f * jf_log2(x)); }
static float jf_cbrt(float x) {
    if (x <= 0) return 0;
    float y = jf_exp2(jf_log2(x) * 0.33333334f);
    y = y - (y * y * y - x) / (3 * y * y);              /* one Newton step */
    return y;
}
static float jf_atan01(float t) {                        /* atan(t), t in [0,1] */
    float t2 = t * t;
    return t * (0.99997726f + t2 * (-0.33262347f + t2 * (0.19354346f + t2 * (-0.11643287f + t2 * (0.05265332f + t2 * -0.01172120f)))));
}
static float jf_atan2deg(float y, float x) {             /* degrees, 0..360 */
    float ax = jf_abs(x), ay = jf_abs(y), a;
    if (ax == 0 && ay == 0) return 0;
    a = ay <= ax ? jf_atan01(ay / ax) : 1.5707963267948966f - jf_atan01(ax / ay);
    if (x < 0) a = 3.141592653589793f - a;
    if (y < 0) a = -a;
    a *= 57.29577951308232f;
    return a < 0 ? a + 360 : a;
}
static void jf_sincos_deg(float d, float *s, float *c) {
    while (d >= 180) d -= 360;
    while (d < -180) d += 360;
    float sgn = 1;
    if (d > 90) { d = 180 - d; sgn = -1; } else if (d < -90) { d = -180 - d; sgn = -1; }   /* cos flips, sin stays */
    float x = d * 0.017453292519943295f, x2 = x * x;
    float sn = x * (1 - x2 * (0.16666667f - x2 * (0.0083333310f - x2 * (0.00019840874f - x2 * 2.7525562e-6f))));
    float cs = 1 - x2 * (0.5f - x2 * (0.041666638f - x2 * (0.0013888378f - x2 * (2.4760495e-5f - x2 * 2.6051615e-7f))));
    *s = sn; *c = sgn * cs;
}
/* the CEQ hue pair (a0, a1) as the ISP interpolates it: forward, mod 360 (a decreasing pair goes the long way) */
static float jf_hue_dd(const float *dh, int a0, int a1) {
    float d = dh[a1] - dh[a0];
    return d < -15.0f ? d + 360.0f : d;
}
/* the safety clamp (dh: the 24 CEQ hue shifts, deg): every forward gap 15 + dh[a+1] - dh[a] >= JF_HUE_SAFE, by
 * scaling all shifts by the one factor that brings the worst pair there (dh = 0 is always in order); a no-op on a
 * table already in order -- the fit's hinge keeps it so */
static void jf_hue_safe(float *dh) {
    float t = 1;
    for (int a = 0; a < 24; a++) {
        float d = dh[a] - dh[a == 23 ? 0 : a + 1];
        if (15.0f - d < JF_HUE_SAFE) { float u = (15.0f - JF_HUE_SAFE) / d; if (u < t) t = u; }
    }
    if (t < 1) for (int a = 0; a < 24; a++) dh[a] *= t;
}
static float jf_interp_lin(float x, const float *ys, uint32_t n, float x1) {   /* ys on 0..x1, n points */
    float t = x / x1 * (float)(n - 1);
    if (t <= 0) return ys[0];
    if (t >= (float)(n - 1)) return ys[n - 1];
    int i = (int)t; float f = t - (float)i;
    return ys[i] + (ys[i + 1] - ys[i]) * f;
}

/* ---------------------------------------------------------------- the chain */
/* JFIT v6: one chroma component through the CKNEE, kn = its (k+, m+, k-, m-); *side 0 below the knee (unchanged), +1 / -1
 * the half that bent (the derivative's sign) */
static float jf_knee(float v, const float *kn, int *side) {
    int neg = v < 0; float x = neg ? -v : v; const float *p = kn + 2 * neg;
    if (!(x > p[0])) { *side = 0; return v; }
    float o = p[0] + (x - p[0]) * p[1];
    *side = neg ? -1 : 1;
    return neg ? -o : o;
}
static void jf_knee_off(float *P) { for (int i = 0; i < 8; i++) P[JF_NK + i] = i & 1 ? 1.0f : JF_KOFF; }
static int jf_knee_on(const float *P) { return P[JF_NK] < 0.5f * JF_KOFF; }
static void jf_build_tone(const struct jfit *J, const float *P) {
    for (int k = 0; k < 3; k++) {
        float prev = 0;
        for (int i = 0; i < JF_NTONE; i++) {
            float x = (float)i / (float)(JF_NTONE - 1) * (float)(JF_KN - 1);
            int a = (int)x; if (a > JF_KN - 2) a = JF_KN - 2;
            float f = x - (float)a, d = P[18 + k * JF_KN + a] + (P[18 + k * JF_KN + a + 1] - P[18 + k * JF_KN + a]) * f;
            float v = J->base_tone[k * JF_NTONE + i] + d;
            if (i && v < prev) v = prev;                  /* np.maximum.accumulate */
            prev = v;
            J->tone[k * JF_NTONE + i] = jf_clamp(v, 0, 1);
        }
    }
}
static float jf_tone_at(const float *t, float idx) {
    if (idx <= 0) return t[0];
    if (idx >= JF_NTONE - 1) return t[JF_NTONE - 1];
    int i = (int)idx; float f = idx - (float)i;
    return t[i] + (t[i + 1] - t[i]) * f;
}
/* 709 code RGB (Gamma 2.4, clipped) -> Lab (D65) -- lv_fit.lab709 */
static void jf_rgb_lab(float R, float G, float B, float *lab) {
    float lin[3] = {jf_pow24(jf_clamp(R, 0, 1)), jf_pow24(jf_clamp(G, 0, 1)), jf_pow24(jf_clamp(B, 0, 1))};
    float X = (0.4123907993f * lin[0] + 0.3575843394f * lin[1] + 0.1804807884f * lin[2]) / 0.95047f;
    float Y = 0.2126390059f * lin[0] + 0.7151686788f * lin[1] + 0.0721923154f * lin[2];
    float Z = (0.0193308187f * lin[0] + 0.1191947798f * lin[1] + 0.9505321522f * lin[2]) / 1.08883f;
    float fx = X > 0.008856f ? jf_cbrt(X) : 7.787f * X + 16.0f / 116;
    float fy = Y > 0.008856f ? jf_cbrt(Y) : 7.787f * Y + 16.0f / 116;
    float fz = Z > 0.008856f ? jf_cbrt(Z) : 7.787f * Z + 16.0f / 116;
    lab[0] = 116 * fy - 16; lab[1] = 500 * (fx - fy); lab[2] = 200 * (fy - fz);
}
/* one sample: 709 code RGB out (unclipped); pre (if not 0): tone indices, hue, pre-YGAM luma */
/* M1 (P[9..17], RGBLMAT set 1, root+0x10: the luma) apart from M2 (P[0..8], set 2, root+0x08: the chroma)?  JFIT v5
 * (2026-11-11, Bei): the untied refine (jf_fit_untied) frees M1; tied, the chain is the plain tone(M2 c) as before */
static int jf_split(const float *P) { for (int k = 0; k < 9; k++) if (P[9 + k] != P[k]) return 1; return 0; }
static void jf_chain_t(const struct jfit *J, const float *P, const float *c, float *out, float *pre,
                       const float *alt, int alt_ch) {         /* alt: channel alt_ch's table instead of J->tone */
    float rgb[3];
    for (int k = 0; k < 3; k++) {
        float idx = (P[3 * k] * c[0] + P[3 * k + 1] * c[1] + P[3 * k + 2] * c[2]) * JF_WHITE;
        idx = jf_clamp(idx, 0, JF_NTONE - 1);
        if (pre) pre[k] = idx;
        rgb[k] = jf_clamp(jf_tone_at(k == alt_ch ? alt : J->tone + k * JF_NTONE, idx), 0, 1);
    }
    if (jf_split(P)) {      /* lv_fit.luma_preserve: the chroma path's RGB + the 601 luma of (luma path - chroma path), clipped */
        float sh = 0;
        for (int k = 0; k < 3; k++) {
            float idx = (P[9 + 3 * k] * c[0] + P[9 + 3 * k + 1] * c[1] + P[9 + 3 * k + 2] * c[2]) * JF_WHITE;
            idx = jf_clamp(idx, 0, JF_NTONE - 1);
            float t1 = jf_clamp(jf_tone_at(k == alt_ch ? alt : J->tone + k * JF_NTONE, idx), 0, 1);
            sh += (k == 0 ? 0.299f : k == 1 ? 0.587f : 0.114f) * (t1 - rgb[k]);
        }
        for (int k = 0; k < 3; k++) rgb[k] = jf_clamp(rgb[k] + sh, 0, 1);
    }
    const float *q = P + 45;
    float r = rgb[0], g = rgb[1], b = rgb[2];
    float y = q[0] * r + (1 - q[0] - q[1]) * g + q[1] * b;
    float cb = q[2] * (r - g) + q[3] * (b - g), cr = q[4] * (r - g) + q[5] * (b - g);
    { int sd; cb = jf_knee(cb, P + JF_NK, &sd); cr = jf_knee(cr, P + JF_NK + 4, &sd); }   /* the CKNEE (JFIT v6) */
    float th = jf_atan2deg(cr, cb), ch = jf_sqrt(cb * cb + cr * cr);
    if (pre) pre[3] = th;
    float t = th / 15.0f; int a = (int)t; if (a > 23) a = 23; float f = t - (float)a; int a1 = a == 23 ? 0 : a + 1;
    const float *dh = q + 6, *gs = q + 30, *gl = q + 54;
    float c2 = ch * (gs[a] + (gs[a1] - gs[a]) * f);
    float h2 = th + dh[a] + jf_hue_dd(dh, a, a1) * f;
    float y2 = y + (gl[a] + (gl[a1] - gl[a]) * f - 1) * ch;
    if (pre) pre[4] = y2;
    {   /* YGAM: np.interp over 17 nodes after np.maximum.accumulate */
        float nodes[17], m = q[78];
        for (int i = 0; i < 17; i++) { if (q[78 + i] > m) m = q[78 + i]; nodes[i] = i ? m : q[78]; }
        y2 = jf_interp_lin(y2, nodes, 17, 1.0f);
    }
    float sn, cs; jf_sincos_deg(h2, &sn, &cs);
    float cb2 = c2 * cs, cr2 = c2 * sn;
    const float kr = 0.299f, kb = 0.114f, kg = 1 - kr - kb;
    float R = y2 + 2 * (1 - kr) * cr2, B = y2 + 2 * (1 - kb) * cb2, G = (y2 - kr * R - kb * B) / kg;
    out[0] = R; out[1] = G; out[2] = B;
}
/* one sample: Lab out (jf_chain_t, then lv_fit.lab709) */
static void jf_sample_t(const struct jfit *J, const float *P, const float *c, float *lab, float *pre,
                        const float *alt, int alt_ch) {
    float rgb[3];
    jf_chain_t(J, P, c, rgb, pre, alt, alt_ch);
    jf_rgb_lab(rgb[0], rgb[1], rgb[2], lab);
}
static void jf_sample(const struct jfit *J, const float *P, const float *c, float *lab, float *pre) {
    jf_sample_t(J, P, c, lab, pre, 0, -1);
}

/* the residual vector: 3n Lab terms, then 72 CEQ smoothness, 27 curve-edit costs, 24 hue-order hinges */
#define JF_NRES(n) (3 * (n) + JF_NTAIL)
/* hinge a: w_mono x (JF_HUE_FIT - gap[a]) while the gap is below it, else 0; d/d dh[a] = +w, d/d dh[a+1] = -w */
static float jf_hinge(const struct jfit *J, const float *P, int a) {
    float gap = 15.0f + P[51 + (a == 23 ? 0 : a + 1)] - P[51 + a];
    return gap < JF_HUE_FIT ? (JF_HUE_FIT - gap) * J->w_mono : 0.0f;
}
static void jf_tail(const struct jfit *J, const float *P, float *res, uint32_t n) {
    float *r = res + 3 * n;
    for (int p = 0; p < 3; p++) {
        float sw = p ? J->w_gain : J->w_hue;
        for (int a = 0; a < 24; a++)
            *r++ = (P[51 + 24 * p + a] - P[51 + 24 * p + (a + 1) % 24]) * sw;
    }
    for (int k = 0; k < 27; k++) *r++ = P[18 + k] * J->w_curve;
    for (int a = 0; a < 24; a++) *r++ = jf_hinge(J, P, a);
}
static void jf_resid(struct jfit *J, const float *P, float *res, int keep_pre) {
    jf_build_tone(J, P);
    for (uint32_t j = 0; j < J->n; j++) {
        float lab[3];
        jf_sample(J, P, J->xs + 3 * j, lab, keep_pre ? J->pre + 5 * j : 0);
        for (int k = 0; k < 3; k++) res[3 * j + k] = (lab[k] - J->want[3 * j + k]) * J->w[j];
    }
    jf_tail(J, P, res, J->n);
    J->evals++;
}
static float jf_dot(const float *a, const float *b, uint32_t n) { float s = 0; for (uint32_t i = 0; i < n; i++) s += a[i] * b[i]; return s; }

/* which samples parameter k can move (given the current pre-pass) */
#ifdef JF_TEST
static int jf_force_dense;                                         /* the test compares against every sample */
#endif
static int jf_affects(const struct jfit *J, int k, uint32_t j) {
    const float *pr = J->pre + 5 * j;
#ifdef JF_TEST
    if (jf_force_dense) return 1;
#endif
    if (k < 18 || (k >= 45 && k < 51)) return 1;                 /* matrices, YCMAT: everything */
    if (k < 45) {                                                  /* tone knot: the two table entries the sample */
        int ch = (k - 18) / JF_KN;                                 /* interpolates, moved in the knot's perturbed table? */
        int i0 = (int)pr[ch]; if (i0 > JF_NTONE - 2) i0 = JF_NTONE - 2;   /* (11-07: the curve is monotone -- a knot that */
        const float *pt = J->pert + (k - 18) * JF_NTONE, *t = J->tone + ch * JF_NTONE;   /* lifts a plateau moves every */
        return pt[i0] != t[i0] || pt[i0 + 1] != t[i0 + 1];          /* entry the plateau holds, not just its neighbours) */
    }
    if (k < 123) {                                                 /* CEQ anchor */
        int a = (k - 51) % 24;
        float d = pr[3] - 15.0f * (float)a;
        while (d > 180) d -= 360;
        while (d < -180) d += 360;
        return d > -15.0001f && d < 15.0001f;
    }
    int node = k - 123;                                            /* YGAM node (accumulate: everything above) */
    return pr[4] * 16.0f > (float)node - 1.0001f;
}

static float jf_bound(int k, int hi) {
    if (k >= JF_NK) return (k - JF_NK) & 1 ? (hi ? JF_SMAX : 0) : (hi ? JF_KMAX : 0);   /* the CKNEE's codes: 9 / 5 bits */
    if (k < 18) return hi ? 4.0f : -2.0f;
    if (k < 45) return hi ? 0.3f : -0.3f;
    int q = k - 45;
    if (q == 0 || q == 1) return hi ? 4095.0f / 4096 : 0;
    if (q == 2 || q == 5) return hi ? 511.0f / 512 : -511.0f / 512;
    if (q == 3 || q == 4) return hi ? 1023.0f / 512 : 0;
    if (q < 30) return hi ? 90 : -90;
    if (q < 78) return hi ? 4.0f : 0;
    return hi ? 1.0f : 0;
}
static float jf_step(int k) {
    if (k < 45) return 0.002f;
    int q = k - 45;
    if (q < 6) return 0.004f;
    if (q < 30) return 0.5f;
    if (q < 78) return 0.005f;
    return 0.004f;
}

/* Cholesky solve of (A + lam I) x = g, in place: A n x n (lower used), g n; returns 0 if not SPD */
static double jf_sqrtd(double x) { return x > 0 ? __builtin_sqrt(x) : x - x; }
static int jf_solve(double *A, double *g, int n, double lam) {
    for (int i = 0; i < n; i++) A[i * n + i] += lam;
    for (int i = 0; i < n; i++) {
        for (int k = 0; k < i; k++) A[i * n + i] -= A[i * n + k] * A[i * n + k];
        if (A[i * n + i] <= 0) return 0;
        A[i * n + i] = jf_sqrtd(A[i * n + i]);
        for (int j = i + 1; j < n; j++) {
            double s = A[j * n + i];
            for (int k = 0; k < i; k++) s -= A[j * n + k] * A[i * n + k];
            A[j * n + i] = s / A[i * n + i];
        }
    }
    for (int i = 0; i < n; i++) { double s = g[i]; for (int k = 0; k < i; k++) s -= A[i * n + k] * g[k]; g[i] = s / A[i * n + i]; }
    for (int i = n - 1; i >= 0; i--) { double s = g[i]; for (int k = i + 1; k < n; k++) s -= A[k * n + i] * g[k]; g[i] = s / A[i * n + i]; }
    return 1;
}

/* free parameters: everything but M1 (9..17, = M2 here) and the CKNEE (off) */
static int jf_free(int *idx) { int m = 0; for (int k = 0; k < JF_NK; k++) if (k < 9 || k >= 18) idx[m++] = k; return m; }

/* one knot's channel table with that knot moved by h (the same build as jf_build_tone, one channel) */
static void jf_knot_table(const struct jfit *J, const float *P, int k, float h, float *out) {
    int ch = (k - 18) / JF_KN, kn = (k - 18) % JF_KN;
    float prev = 0;
    for (int i = 0; i < JF_NTONE; i++) {
        float x = (float)i / (float)(JF_NTONE - 1) * (float)(JF_KN - 1);
        int a = (int)x; if (a > JF_KN - 2) a = JF_KN - 2;
        float f = x - (float)a;
        float d0 = P[18 + ch * JF_KN + a] + (a == kn ? h : 0), d1 = P[18 + ch * JF_KN + a + 1] + (a + 1 == kn ? h : 0);
        float v = J->base_tone[ch * JF_NTONE + i] + d0 + (d1 - d0) * f;
        if (i && v < prev) v = prev;
        prev = v;
        out[i] = jf_clamp(v, 0, 1);
    }
}

/* Gauss-Newton; the normal equations are accumulated sample by sample (no stored Jacobian): each sample's
 * residual row has entries only for the parameters that reach it.  The tail (CEQ smoothness, curve cost)
 * is linear in P: its rows go in analytically. */
#ifndef JF_DAMP_TRIES
#define JF_DAMP_TRIES 6                  /* damping 1e-3 .. 1e2 x trace / n, as the host LM (estimate.py) */
#endif
static float jf_fit(struct jfit *J) {
    int idx[JF_NP], nf = jf_free(idx), col_of[JF_NP];
    uint32_t n = J->n, nr = JF_NRES(n);
    for (int k = 0; k < JF_NP; k++) col_of[k] = -1;
    for (int c = 0; c < nf; c++) col_of[idx[c]] = c;
    for (int k = 0; k < 9; k++) J->P[9 + k] = J->P[k];
    jf_resid(J, J->P, J->res, 1);
    float cost = jf_dot(J->res, J->res, nr);
    float Qp[JF_NP];
    for (uint32_t it = 0; it < J->iters; it++) {
        double *A = J->A, *g = J->A + nf * nf;
        double dz = (double)J->iters - (double)J->iters;   /* 0 without a double literal (no fast-math: not folded) */
        for (int i = 0; i < nf * nf + nf; i++) A[i] = dz;
        jf_build_tone(J, J->P);
        for (int kn = 0; kn < 27; kn++) jf_knot_table(J, J->P, 18 + kn, jf_step(18 + kn), J->pert + kn * JF_NTONE);
        for (int i = 0; i < JF_NP; i++) Qp[i] = J->P[i];             /* once an iteration; each column restores its own */
        for (uint32_t j = 0; j < n; j++) {
            if (J->spin && !(j & 31u)) J->spin(J->tick_ctx);
            float row[3][JF_NP]; int nz[JF_NP], m = 0;
            const float *c = J->xs + 3 * j;
            for (int cc = 0; cc < nf; cc++) {
                int k = idx[cc];
                if (!jf_affects(J, k, j)) continue;
                float h = jf_step(k), lab[3];
                if (k >= 18 && k < 45) {
                    jf_sample_t(J, Qp, c, lab, 0, J->pert + (k - 18) * JF_NTONE, (k - 18) / JF_KN);
                } else {
                    Qp[k] += h; if (k < 9) Qp[9 + k] = Qp[k];
                    jf_sample(J, Qp, c, lab, 0);
                    Qp[k] = J->P[k]; if (k < 9) Qp[9 + k] = J->P[9 + k];    /* back: the perturbed one and its tied M1 */
                }
                for (int r = 0; r < 3; r++) row[r][m] = ((lab[r] - J->want[3 * j + r]) * J->w[j] - J->res[3 * j + r]) / h;
                nz[m++] = cc;
            }
            for (int r = 0; r < 3; r++) {
                double rv = J->res[3 * j + r];
                for (int a = 0; a < m; a++) {
                    double va = row[r][a]; int ca = nz[a];
                    g[ca] -= va * rv;
                    for (int b = 0; b <= a; b++) {
                        int cb = nz[b];
                        if (ca >= cb) A[ca * nf + cb] += va * row[r][b]; else A[cb * nf + ca] += va * row[r][b];
                    }
                }
            }
        }
        {   /* the linear tail: CEQ smoothness rows (sw, -sw) and curve-cost rows (2.0) */
            const float *t = J->res + 3 * n;
            for (int p = 0; p < 3; p++) {
                double sw = p ? J->w_gain : J->w_hue;
                for (int a = 0; a < 24; a++) {
                    int ka = col_of[51 + 24 * p + a], kb = col_of[51 + 24 * p + (a + 1) % 24];
                    double rv = t[24 * p + a];
                    g[ka] -= sw * rv; g[kb] += sw * rv;
                    A[ka * nf + ka] += sw * sw; A[kb * nf + kb] += sw * sw;
                    if (ka > kb) A[ka * nf + kb] -= sw * sw; else A[kb * nf + ka] -= sw * sw;
                }
            }
            double wc = J->w_curve;
            for (int k = 0; k < 27; k++) { int ck = col_of[18 + k]; g[ck] -= wc * t[72 + k]; A[ck * nf + ck] += wc * wc; }
            double wm = J->w_mono;                                     /* the hue-order hinges that are active */
            for (int a = 0; a < 24; a++) {
                if (!(t[99 + a] > 0)) continue;
                int ka = col_of[51 + a], kb = col_of[51 + (a + 1) % 24];
                double rv = t[99 + a];
                g[ka] -= wm * rv; g[kb] += wm * rv;
                A[ka * nf + ka] += wm * wm; A[kb * nf + kb] += wm * wm;
                if (ka > kb) A[ka * nf + kb] -= wm * wm; else A[kb * nf + ka] -= wm * wm;
            }
        }
        double tr = dz;
        for (int a = 0; a < nf; a++) tr += A[a * nf + a];
        J->evals += nf;
        /* Levenberg-Marquardt: a step that does not lower the cost is tried again with 10x the damping (up to
         * JF_DAMP_TRIES times) before the fit stops -- the old "first refusal ends it" stopped short
         * (11-05: ARRI_Classic33 2.21 -> 1.96 dE on the host).  jf_solve works in the lower triangle and g:
         * the upper triangle keeps A's lower half, dsave/gsave the diagonal and g, for the retries. */
        double dsave[JF_NP], gsave[JF_NP];
        for (int i = 0; i < nf; i++) {
            dsave[i] = A[i * nf + i]; gsave[i] = g[i];
            for (int j = 0; j < i; j++) A[j * nf + i] = A[i * nf + j];
        }
        double lam = tr / (double)(1000 * nf);                   /* no double literal: .text stays 4-aligned */
        float c2 = cost;
        int moved = 0;
        for (int t = 0; t < JF_DAMP_TRIES && !moved; t++) {
            if (t) {
                for (int i = 0; i < nf; i++) {
                    A[i * nf + i] = dsave[i]; g[i] = gsave[i];
                    for (int j = 0; j < i; j++) A[i * nf + j] = A[j * nf + i];
                }
                double l2 = lam + lam, l8 = l2 + l2; l8 = l8 + l8; lam = l8 + l2;   /* x 10, no literal */
            }
            if (!jf_solve(A, g, nf, lam)) continue;
            for (int i = 0; i < JF_NP; i++) Qp[i] = J->P[i];
            for (int c = 0; c < nf; c++) { int k = idx[c]; Qp[k] = jf_clamp(Qp[k] + (float)g[c], jf_bound(k, 0), jf_bound(k, 1)); }
            for (int k = 0; k < 9; k++) Qp[9 + k] = Qp[k];
            jf_resid(J, Qp, J->res2, 0);
            c2 = jf_dot(J->res2, J->res2, nr);
            moved = c2 < cost;
        }
        if (!moved) break;
        for (int i = 0; i < JF_NP; i++) J->P[i] = Qp[i];
        jf_resid(J, J->P, J->res, 1);
        cost = c2; J->steps++;
        if (J->tick) J->tick(J->tick_ctx, it);
    }
    J->cost = cost;
    return cost;
}
#endif

/* ================================================================ jf_fit_direct: the v2 conversion (2026-11-07)
 * projects/lut-sup/validation/20261106-fitter-proto-01 route "direct10+144" (review_sampling.py; chosen by Bei
 * 11-07): from each start, an exact-Jacobian projected Levenberg-Marquardt (forward mode over the <= JF2_LMAX
 * parameters a sample reaches, accumulated straight into A / g in double; Marquardt scaling, x4 / /3 damping,
 * parameters at a bound with the gradient pushing out held, relative decrease < ftol three times stops), on the
 * lvb samples plus 144 HSV samples (weight 1).  Same chain and cost as jf_fit; no cap against any earlier
 * solution (Bei 11-06: the camera's own fit is only a start).  Code from port_r5c0's jf2_* with the cap removed. */
#define JF2_LMAX   64                    /* parameters one sample reaches: 9 + 12 + 6 + 6 + 2 = 35 tied; untied (JFIT v5)
                                          * 18 + at most 24 knots (3 channels x 2 paths x 2 entries x 2) + 6 + 6 + 2 = 56,
                                          * + the CKNEE (v6: one half of Cb and one of Cr, knee and slope each) = 60 */
#define JF2_NF     131                   /* free: everything but M1 and the CKNEE (jf_fit_direct) */
#define JF2_NFU    140                   /* free in the untied refine without the CKNEE (jf_fit_untied, knee 0): M1 too */
#define JF2_NFK    JF_NP                 /* ... with it (JFIT v6, knee 1): 148 */
/* the YCMAT green weight 1 - yr - yb must stay >= 0 to pack (jft.quantise: 4096 - yr - yb in 12 bits): in the untied
 * refine a hinge w_yg x (yr + yb - JF_YG_MAX) above it (projects/lut-sup/validation/20261111-fit-ceiling-01 ceil.py
 * HModel: Fuji Classic Neg's free M1 drove yg below 0 there) */
#define JF_YG_MAX  0.99951171875f        /* 4094 / 4096 */
#define JF_YG_MIN  0.00048828125f        /* 2 / 4096: and yg <= 4094 below it (JFIT v6: with the CKNEE free, ARRI 709's refine
                                          * drove yr = yb = 0, yg 4096 -- beyond 12 bits, so it did not pack) */
#define JF_W_YG    3000.0f

struct jfit2 {
    struct jfit *J;                      /* base_tone, tone (work), A (nf*nf + nf), w_*, spin / tick */
    uint32_t n;
    const float *xs, *want, *w;          /* n samples: camera RGB, target Lab, weight */
    int16_t *amax;                       /* 3 x 2048: the tone's running argmax, -1 = clipped */
    float ftol;                          /* 1e-6 */
    uint32_t iters, evals, gevals, tick_it;
    int untied, nf;                      /* untied (jf_fit_untied): M1 free, luma_preserve; nf = the free columns
                                          * (JF2_NF, JF2_NFU untied, JF2_NFK untied + knee): A is nf x nf + nf */
    float w_yg;                          /* the YCMAT yr + yb hinge (JF_W_YG untied, 0 = none) */
    int knee;                            /* JFIT v6: the CKNEE (P[JF_NK..]) free too (untied only); else it stays as P has it */
};

static void jf2_tone(struct jfit2 *K, const float *P) {
    struct jfit *J = K->J;
    for (int k = 0; k < 3; k++) {
        float cm = 0; int am = 0;
        for (int i = 0; i < JF_NTONE; i++) {
            float x = (float)i / (float)(JF_NTONE - 1) * (float)(JF_KN - 1);
            int a = (int)x; if (a > JF_KN - 2) a = JF_KN - 2;
            float f = x - (float)a, d = P[18 + k * JF_KN + a] + (P[18 + k * JF_KN + a + 1] - P[18 + k * JF_KN + a]) * f;
            float v = J->base_tone[k * JF_NTONE + i] + d;
            if (!i || v >= cm) { cm = v; am = i; }
            J->tone[k * JF_NTONE + i] = jf_clamp(cm, 0, 1);
            K->amax[k * JF_NTONE + i] = (int16_t)(cm > 0 && cm < 1 ? am : -1);
        }
    }
}
static int jf2_slot(int *gid, int *m, int g) {
    for (int i = 0; i < *m; i++) if (gid[i] == g) return i;
    gid[*m] = g; return (*m)++;
}
/* table entry i of channel k: its two knots (hat of its argmax entry) -> slots, weights */
static void jf2_knots(const struct jfit2 *K, int k, int i, int *gid, int *m, int *s, float *wt) {
    int a = K->amax[k * JF_NTONE + i];
    if (a < 0) { s[0] = s[1] = -1; return; }
    float x = (float)a / (float)(JF_NTONE - 1) * (float)(JF_KN - 1);
    int kn = (int)x; if (kn > JF_KN - 2) kn = JF_KN - 2;
    float f = x - (float)kn;
    s[0] = jf2_slot(gid, m, 18 + k * JF_KN + kn); wt[0] = 1 - f;
    s[1] = jf2_slot(gid, m, 18 + k * JF_KN + kn + 1); wt[1] = f;
}

/* one sample: Lab, and (D != 0) its Jacobian rows D[3][JF2_LMAX] over gid[0..*m) (the tone must be jf2_tone's) */
/* untied: channel k through one matrix (M = P or P + 9, its slots m0 .. m0 + 8 = its gids), the tone table's value
 * (fitter.py Model.forward through(): no clip, the table is 0..1) and (d != 0) its derivative row */
static void jf2_path(const struct jfit2 *K, const float *M, int m0, const float *c, int k, float *v, float *d, int *gid, int *nm) {
    const struct jfit *J = K->J;
    float u = (M[3 * k] * c[0] + M[3 * k + 1] * c[1] + M[3 * k + 2] * c[2]) * JF_WHITE;
    float idx = jf_clamp(u, 0, JF_NTONE - 1);
    const float *tb = J->tone + k * JF_NTONE;
    int i0 = (int)idx; if (i0 > JF_NTONE - 2) i0 = JF_NTONE - 2;
    float f = idx - (float)i0;
    *v = tb[i0] + (tb[i0 + 1] - tb[i0]) * f;
    if (!d) return;
    for (int i = 0; i < JF2_LMAX; i++) d[i] = 0;
    if (u > 0 && u < JF_NTONE - 1) {
        float sl = (tb[i0 + 1] - tb[i0]) * JF_WHITE;
        for (int j = 0; j < 3; j++) d[m0 + 3 * k + j] = sl * c[j];
    }
    int s[2]; float wt[2];
    jf2_knots(K, k, i0, gid, nm, s, wt);
    if (s[0] >= 0) { d[s[0]] += (1 - f) * wt[0]; d[s[1]] += (1 - f) * wt[1]; }
    jf2_knots(K, k, i0 + 1, gid, nm, s, wt);
    if (s[0] >= 0) { d[s[0]] += f * wt[0]; d[s[1]] += f * wt[1]; }
}
/* untied: t = clip(chroma + 601 luma of (luma - chroma)) (lv_fit.luma_preserve, joint_fit_eval.chain split=True), dt */
static void jf2_split(const struct jfit2 *K, const float *P, const float *c, float *t, float (*dt)[JF2_LMAX], int *gid, int *nm) {
    float v2[3], v1[3], d2[3][JF2_LMAX], d1[3][JF2_LMAX], sh = 0;
    for (int k = 0; k < 3; k++) {
        jf2_path(K, P, 0, c, k, &v2[k], dt ? d2[k] : 0, gid, nm);
        jf2_path(K, P + 9, 9, c, k, &v1[k], dt ? d1[k] : 0, gid, nm);
    }
    for (int k = 0; k < 3; k++) sh += (k == 0 ? 0.299f : k == 1 ? 0.587f : 0.114f) * (v1[k] - v2[k]);
    for (int k = 0; k < 3; k++) {
        float x = v2[k] + sh;
        t[k] = jf_clamp(x, 0, 1);
        if (!dt) continue;
        for (int i = 0; i < JF2_LMAX; i++) dt[k][i] = 0;
        if (!(x > 0 && x < 1)) continue;
        for (int i = 0; i < *nm; i++)
            dt[k][i] = d2[k][i] + 0.299f * (d1[0][i] - d2[0][i]) + 0.587f * (d1[1][i] - d2[1][i]) + 0.114f * (d1[2][i] - d2[2][i]);
    }
}
static void jf2_sample(const struct jfit2 *K, const float *P, const float *c, float *lab, float (*D)[JF2_LMAX], int *gid, int *m) {
    const struct jfit *J = K->J;
    float t[3], dt[3][JF2_LMAX];
    int nm = 0;
    if (D) for (int i = 0; i < (K->untied ? 18 : 9); i++) gid[nm++] = i;
    if (K->untied) jf2_split(K, P, c, t, D ? dt : 0, gid, &nm);
    else for (int k = 0; k < 3; k++) {
        float u = (P[3 * k] * c[0] + P[3 * k + 1] * c[1] + P[3 * k + 2] * c[2]) * JF_WHITE;
        float idx = jf_clamp(u, 0, JF_NTONE - 1);
        const float *tb = J->tone + k * JF_NTONE;
        int i0 = (int)idx; if (i0 > JF_NTONE - 2) i0 = JF_NTONE - 2;
        float f = idx - (float)i0;
        float v = tb[i0] + (tb[i0 + 1] - tb[i0]) * f;
        t[k] = jf_clamp(v, 0, 1);
        if (!D) continue;
        for (int i = 0; i < JF2_LMAX; i++) dt[k][i] = 0;
        if (!(v > 0 && v < 1)) continue;
        if (u > 0 && u < JF_NTONE - 1) {
            float sl = (tb[i0 + 1] - tb[i0]) * JF_WHITE;
            for (int j = 0; j < 3; j++) dt[k][3 * k + j] = sl * c[j];
        }
        int s[2]; float wt[2];
        jf2_knots(K, k, i0, gid, &nm, s, wt);
        if (s[0] >= 0) { dt[k][s[0]] += (1 - f) * wt[0]; dt[k][s[1]] += (1 - f) * wt[1]; }
        jf2_knots(K, k, i0 + 1, gid, &nm, s, wt);
        if (s[0] >= 0) { dt[k][s[0]] += f * wt[0]; dt[k][s[1]] += f * wt[1]; }
    }
    const float *q = P + 45;
    float r = t[0], g = t[1], b = t[2], rg = r - g, bg = b - g;
    float y = g + q[0] * rg + q[1] * bg;
    float cb0 = q[2] * rg + q[3] * bg, cr0 = q[4] * rg + q[5] * bg;
    int skb, skr;                                                      /* the CKNEE (JFIT v6): which half bent, if any */
    float cb = jf_knee(cb0, P + JF_NK, &skb), cr = jf_knee(cr0, P + JF_NK + 4, &skr);
    float th = jf_atan2deg(cr, cb), ch = jf_sqrt(cb * cb + cr * cr);
    float tt = th / 15.0f; int a0 = (int)tt; if (a0 > 23) a0 = 23; float fa = tt - (float)a0; int a1 = a0 == 23 ? 0 : a0 + 1;
    const float *dh = q + 6, *gs = q + 30, *gl = q + 54;
    float ddh = jf_hue_dd(dh, a0, a1);
    float hs = dh[a0] + ddh * fa, gsv = gs[a0] + (gs[a1] - gs[a0]) * fa, ls = gl[a0] + (gl[a1] - gl[a0]) * fa;
    float c2 = ch * gsv, h2 = th + hs, y2 = y + (ls - 1) * ch;
    float nodes[17]; int nam[17];
    { float mx = q[78]; int am = 0; for (int i = 0; i < 17; i++) { if (!i || q[78 + i] >= mx) { mx = q[78 + i]; am = i; } nodes[i] = mx; nam[i] = am; } }
    float ug = y2 * 16.0f, ugc = jf_clamp(ug, 0, 16);
    int g0 = (int)ugc; if (g0 > 15) g0 = 15; float fg = ugc - (float)g0;
    float Y = nodes[g0] + (nodes[g0 + 1] - nodes[g0]) * fg;
    float sn, cs; jf_sincos_deg(h2, &sn, &cs);
    float cb2 = c2 * cs, cr2 = c2 * sn;
    const float kr = 0.299f, kb = 0.114f, kg = 1 - kr - kb;
    float R = Y + 2 * (1 - kr) * cr2, B = Y + 2 * (1 - kb) * cb2, G = (Y - kr * R - kb * B) / kg;
    jf_rgb_lab(R, G, B, lab);
    if (!D) return;
    /* ---- derivatives: slots for YCMAT, CEQ, YGAM */
    int sy[6]; for (int i = 0; i < 6; i++) sy[i] = jf2_slot(gid, &nm, 45 + i);
    int sq[3][2]; for (int p = 0; p < 3; p++) { sq[p][0] = jf2_slot(gid, &nm, 51 + 24 * p + a0); sq[p][1] = jf2_slot(gid, &nm, 51 + 24 * p + a1); }
    int sg0 = jf2_slot(gid, &nm, 123 + nam[g0]), sg1 = jf2_slot(gid, &nm, 123 + nam[g0 + 1]);
    int kb0 = -1, kr0 = -1;                                            /* the CKNEE half that bent: its knee, slope + 1 */
    if (K->knee && skb) { kb0 = jf2_slot(gid, &nm, JF_NK + (skb < 0 ? 2 : 0)); jf2_slot(gid, &nm, JF_NK + (skb < 0 ? 3 : 1)); }
    if (K->knee && skr) { kr0 = jf2_slot(gid, &nm, JF_NK + (skr < 0 ? 6 : 4)); jf2_slot(gid, &nm, JF_NK + (skr < 0 ? 7 : 5)); }
    *m = nm;
    float drg[JF2_LMAX], dbg[JF2_LMAX], dy[JF2_LMAX], dcb[JF2_LMAX], dcr[JF2_LMAX];
    for (int i = 0; i < nm; i++) {
        drg[i] = dt[0][i] - dt[1][i]; dbg[i] = dt[2][i] - dt[1][i];
        dy[i] = dt[1][i] + q[0] * drg[i] + q[1] * dbg[i];
        dcb[i] = q[2] * drg[i] + q[3] * dbg[i]; dcr[i] = q[4] * drg[i] + q[5] * dbg[i];
    }
    dy[sy[0]] += rg; dy[sy[1]] += bg; dcb[sy[2]] += rg; dcb[sy[3]] += bg; dcr[sy[4]] += rg; dcr[sy[5]] += bg;
    for (int c = 0; c < 2; c++) {                                      /* the CKNEE: d out = m d in (+ its knee and slope) */
        int sd = c ? skr : skb; if (!sd) continue;
        float *dv = c ? dcr : dcb, v = c ? cr0 : cb0, x = sd < 0 ? -v : v, sg = (float)sd;
        const float *p = P + JF_NK + 4 * c + (sd < 0 ? 2 : 0);
        for (int i = 0; i < nm; i++) dv[i] *= p[1];
        int s0 = c ? kr0 : kb0;
        if (s0 >= 0) { dv[s0] += sg * (1 - p[1]); dv[s0 + 1] += sg * (x - p[0]); }
    }
    float r2 = cb * cb + cr * cr; if (r2 < 1e-12f) r2 = 1e-12f;
    float chd = ch < 1e-12f ? 1e-12f : ch;
    float kt = 57.29577951308232f / r2, in_h = tt > 0 && tt < 24 ? 1.0f : 0.0f;
    float slh = ddh / 15.0f * in_h, slg = (gs[a1] - gs[a0]) / 15.0f * in_h, sll = (gl[a1] - gl[a0]) / 15.0f * in_h;
    float in_g = ug > 0 && ug < 16 ? 1.0f : 0.0f, slY = (nodes[g0 + 1] - nodes[g0]) * 16.0f * in_g;
    float dY[JF2_LMAX], dc2[JF2_LMAX], dh2[JF2_LMAX];
    for (int i = 0; i < nm; i++) {
        float dth = (cb * dcr[i] - cr * dcb[i]) * kt, dch = (cb * dcb[i] + cr * dcr[i]) / chd;
        float dhs = slh * dth, dgs = slg * dth, dls = sll * dth;
        if (i == sq[0][0]) dhs += 1 - fa; if (i == sq[0][1]) dhs += fa;
        if (i == sq[1][0]) dgs += 1 - fa; if (i == sq[1][1]) dgs += fa;
        if (i == sq[2][0]) dls += 1 - fa; if (i == sq[2][1]) dls += fa;
        dc2[i] = dch * gsv + ch * dgs; dh2[i] = dth + dhs;
        float dy2 = dy[i] + dls * ch + (ls - 1) * dch;
        dY[i] = slY * dy2;
    }
    dY[sg0] += 1 - fg; dY[sg1] += fg;
    /* (R, G, B) from (Y, cb2, cr2), then Lab: the 3 x 3 dLab/dRGB at this sample */
    float rgbv[3] = {R, G, B}, dl[3];
    for (int k = 0; k < 3; k++) {
        float v = rgbv[k];
        dl[k] = v > 0 && v < 1 ? 2.4f * jf_pow24(v) / v : 0;
    }
    float X = (0.4123907993f * jf_pow24(jf_clamp(R, 0, 1)) + 0.3575843394f * jf_pow24(jf_clamp(G, 0, 1)) + 0.1804807884f * jf_pow24(jf_clamp(B, 0, 1))) / 0.95047f;
    float Yl = 0.2126390059f * jf_pow24(jf_clamp(R, 0, 1)) + 0.7151686788f * jf_pow24(jf_clamp(G, 0, 1)) + 0.0721923154f * jf_pow24(jf_clamp(B, 0, 1));
    float Z = (0.0193308187f * jf_pow24(jf_clamp(R, 0, 1)) + 0.1191947798f * jf_pow24(jf_clamp(G, 0, 1)) + 0.9505321522f * jf_pow24(jf_clamp(B, 0, 1))) / 1.08883f;
    float fx, fy, fz;
    { float cx = jf_cbrt(X), cy = jf_cbrt(Yl), cz = jf_cbrt(Z);
      fx = X > 0.008856f ? 1.0f / (3 * cx * cx) : 7.787f; fy = Yl > 0.008856f ? 1.0f / (3 * cy * cy) : 7.787f; fz = Z > 0.008856f ? 1.0f / (3 * cz * cz) : 7.787f; }
    float JL[3][3];                                   /* d(L, a, b) / d(R, G, B): scalars, no constant tables */
    for (int k = 0; k < 3; k++) {
        float mx = k == 0 ? 0.4123907993f : k == 1 ? 0.3575843394f : 0.1804807884f;
        float my = k == 0 ? 0.2126390059f : k == 1 ? 0.7151686788f : 0.0721923154f;
        float mz = k == 0 ? 0.0193308187f : k == 1 ? 0.1191947798f : 0.9505321522f;
        float ex = fx * mx / 0.95047f * dl[k], ey = fy * my * dl[k], ez = fz * mz / 1.08883f * dl[k];
        JL[0][k] = 116 * ey; JL[1][k] = 500 * (ex - ey); JL[2][k] = 200 * (ey - ez);
    }
    /* R = Y + 2(1-kr) cr2, B = Y + 2(1-kb) cb2, G = (Y - kr R - kb B) / kg  ->  d(R,G,B)/d(Y, cb2, cr2) */
    float kR = 2 * (1 - kr), kB = 2 * (1 - kb);
    float A3[3][3];                                   /* d(L,a,b) / d(Y, cb2, cr2) */
    for (int o = 0; o < 3; o++) {
        A3[o][0] = JL[o][0] + JL[o][1] + JL[o][2];
        A3[o][1] = JL[o][1] * (-kb * kB / kg) + JL[o][2] * kB;
        A3[o][2] = JL[o][0] * kR + JL[o][1] * (-kr * kR / kg);
    }
    float kd = 0.017453292519943295f;
    for (int i = 0; i < nm; i++) {
        float dcb2 = dc2[i] * cs - c2 * sn * dh2[i] * kd, dcr2 = dc2[i] * sn + c2 * cs * dh2[i] * kd;
        for (int o = 0; o < 3; o++) D[o][i] = A3[o][0] * dY[i] + A3[o][1] * dcb2 + A3[o][2] * dcr2;
    }
}

static double jf2_tail(const struct jfit *J, const float *P) {
    float tl[JF_NTAIL]; jf_tail(J, P, tl, 0);
    double c = (double)tl[0] * tl[0];
    for (int i = 1; i < JF_NTAIL; i++) c += (double)tl[i] * tl[i];
    return c;
}
/* the YCMAT yr + yb hinges' residual (0 = inactive): w_yg (yr + yb - the bound) above JF_YG_MAX or below JF_YG_MIN --
 * d / d yr = d / d yb = w_yg either way */
static float jf2_yg(const struct jfit2 *K, const float *P) {
    float s = P[45] + P[46];
    if (!(K->w_yg > 0)) return 0.0f;
    return s > JF_YG_MAX ? (s - JF_YG_MAX) * K->w_yg : s < JF_YG_MIN ? (s - JF_YG_MIN) * K->w_yg : 0.0f;
}
static double jf2_tailk(const struct jfit2 *K, const float *P) {
    double c = jf2_tail(K->J, P);
    if (K->w_yg > 0) { float r = jf2_yg(K, P); c += (double)r * r; }
    return c;
}
/* the cost over all samples */
static double jf2_cost(struct jfit2 *K, const float *P) {
    struct jfit *J = K->J;
    double c = jf2_tailk(K, P);
    jf2_tone(K, P);
    for (uint32_t j = 0; j < K->n; j++) {
        if (J->spin && !(j & 31u)) J->spin(J->tick_ctx);
        float lab[3]; jf2_sample(K, P, K->xs + 3 * j, lab, 0, 0, 0);
        float e0 = lab[0] - K->want[3 * j], e1 = lab[1] - K->want[3 * j + 1], e2 = lab[2] - K->want[3 * j + 2];
        { float w = K->w[j]; c += (double)(e0 * w) * (e0 * w) + (double)(e1 * w) * (e1 * w) + (double)(e2 * w) * (e2 * w); }
        K->evals++;
    }
    return c;
}
/* free columns: M2, then 18.. (tied); every parameter (untied) */
static int jf2_col(const struct jfit2 *K, int gid) { return K->untied || gid < 9 ? gid : gid - 9; }
static int jf2_gid(const struct jfit2 *K, int col) { return K->untied || col < 9 ? col : col + 9; }
static void jf2_add_row(const struct jfit2 *K, double *A, double *g, const float *d, const int *gid, int m, float rv) {
    int nf = K->nf;
    for (int a = 0; a < m; a++) {
        double va = d[a]; if (va == 0) continue;
        int ca = jf2_col(K, gid[a]);
        g[ca] += va * rv;
        for (int b = 0; b < m; b++) {
            int cb = jf2_col(K, gid[b]);
            if (cb <= ca) A[ca * nf + cb] += va * d[b];
        }
    }
}
/* A = J^T J (lower), g = J^T r; returns the cost */
static double jf2_normal(struct jfit2 *K, const float *P) {
    struct jfit *J = K->J;
    int nf = K->nf;
    double *A = J->A, *g = J->A + nf * nf;
    double c = jf2_tailk(K, P);
    for (int i = 0; i < nf * nf + nf; i++) A[i] = c - c;
    jf2_tone(K, P);
    for (uint32_t j = 0; j < K->n; j++) {
        if (J->spin && !(j & 31u)) J->spin(J->tick_ctx);
        float lab[3], D[3][JF2_LMAX], row[JF2_LMAX]; int gid[JF2_LMAX], m = 0;
        jf2_sample(K, P, K->xs + 3 * j, lab, D, gid, &m);
        float e[3] = {lab[0] - K->want[3 * j], lab[1] - K->want[3 * j + 1], lab[2] - K->want[3 * j + 2]};
        {
            float w = K->w[j];
            for (int o = 0; o < 3; o++) {
                float rv = e[o] * w;
                c += (double)rv * rv;
                for (int i = 0; i < m; i++) row[i] = D[o][i] * w;
                jf2_add_row(K, A, g, row, gid, m, rv);
            }
        }
        K->gevals++;
    }
    {   /* the linear tail: CEQ smoothness (sw, -sw) and the curve-edit cost (w_curve) */
        float tl[JF_NTAIL]; jf_tail(J, P, tl, 0);
        for (int p = 0; p < 3; p++) {
            double sw = p ? J->w_gain : J->w_hue;
            for (int a = 0; a < 24; a++) {
                int ka = jf2_col(K, 51 + 24 * p + a), kb = jf2_col(K, 51 + 24 * p + (a + 1) % 24);
                double rv = tl[24 * p + a];
                g[ka] += sw * rv; g[kb] -= sw * rv;
                A[ka * nf + ka] += sw * sw; A[kb * nf + kb] += sw * sw;
                if (ka > kb) A[ka * nf + kb] -= sw * sw; else A[kb * nf + ka] -= sw * sw;
            }
        }
        double wc = J->w_curve;
        for (int k = 0; k < 27; k++) { int ck = jf2_col(K, 18 + k); g[ck] += wc * tl[72 + k]; A[ck * nf + ck] += wc * wc; }
        double wm = J->w_mono;                                         /* the hue-order hinges that are active */
        for (int a = 0; a < 24; a++) {
            if (!(tl[99 + a] > 0)) continue;
            int ka = jf2_col(K, 51 + a), kb = jf2_col(K, 51 + (a + 1) % 24);
            double rv = tl[99 + a];
            g[ka] += wm * rv; g[kb] -= wm * rv;
            A[ka * nf + ka] += wm * wm; A[kb * nf + kb] += wm * wm;
            if (ka > kb) A[ka * nf + kb] -= wm * wm; else A[kb * nf + ka] -= wm * wm;
        }
        float ry = jf2_yg(K, P);                                       /* the YCMAT hinges (untied), when active */
        if (ry != 0) {
            int ka = jf2_col(K, 45), kb = jf2_col(K, 46); double wy = K->w_yg;
            g[ka] += wy * ry; g[kb] += wy * ry;
            A[ka * nf + ka] += wy * wy; A[kb * nf + kb] += wy * wy; A[kb * nf + ka] += wy * wy;
        }
    }
    return c;
}
static void jf2_tie(float *P) { for (int k = 0; k < 9; k++) P[9 + k] = P[k]; }
static void jf2_clip(const struct jfit2 *K, float *P) {
    for (int k = 0; k < (K->knee ? JF_NP : JF_NK); k++) P[k] = jf_clamp(P[k], jf_bound(k, 0), jf_bound(k, 1));   /* the CKNEE as it is
                                                                                   * unless fitted (off = JF_KOFF, beyond the bounds) */
    if (!K->untied) jf2_tie(P);
}

/* projected Levenberg-Marquardt (fitter.lm): z in place; returns its cost.  The double work: A (lower, the upper
 * triangle keeps a copy for the retries), g; dsave / gsave / act on the stack. */
static double jf2_lm(struct jfit2 *K, float *z, uint32_t maxit) {
    struct jfit *J = K->J;
    int nf = K->nf;
    double *A = J->A, *g = J->A + nf * nf;
    float zn[JF_NP];
    jf2_clip(K, z);
    double cost = jf2_normal(K, z), zero = cost - cost;
    float lam = 1e-3f; uint32_t small = 0;
    for (uint32_t it = 0; it < maxit; it++) {
        double dsave[JF2_NFK], gsave[JF2_NFK], gn = zero, tr = zero; uint8_t act[JF2_NFK]; int nfree = 0;
        for (int c = 0; c < nf; c++) {
            int k = jf2_gid(K, c); float lo = jf_bound(k, 0), hi = jf_bound(k, 1);
            act[c] = (z[k] <= lo + 1e-12f && g[c] > 0) || (z[k] >= hi - 1e-12f && g[c] < 0);
            if (!act[c]) { gn += g[c] * g[c]; tr += A[c * nf + c]; nfree++; }
        }
        /* |g| < 1e-4 sqrt(cost) (fitter.lm gtol 1e-7 x 1e3) */
        if ((float)gn < 1e-8f * (float)cost) break;
        float eps = 1e-9f * ((float)tr / (float)(nfree ? nfree : 1) + 1e-12f);
        for (int i = 0; i < nf; i++) {
            dsave[i] = A[i * nf + i] + (double)eps; gsave[i] = g[i];
            for (int j = 0; j < i; j++) A[j * nf + i] = A[i * nf + j];
        }
        int ok = 0; double cn = zero;
        while (lam < 1e10f) {
            for (int i = 0; i < nf; i++) {
                for (int j = 0; j < i; j++) A[i * nf + j] = act[i] || act[j] ? zero : A[j * nf + i];
                A[i * nf + i] = act[i] ? dsave[i] - dsave[i] + 1 : dsave[i] - (double)eps + (double)lam * dsave[i];
                g[i] = act[i] ? zero : -gsave[i];
            }
            if (!jf_solve(A, g, nf, zero)) { lam *= 4; continue; }
            for (int k = 0; k < JF_NP; k++) zn[k] = z[k];
            for (int c = 0; c < nf; c++) if (!act[c]) zn[jf2_gid(K, c)] += (float)g[c];
            jf2_clip(K, zn);
            cn = jf2_cost(K, zn);
            if (cn < cost) { ok = 1; break; }
            lam *= 4;
        }
        if (!ok) break;
        double rel = (cost - cn) / cost;
        for (int k = 0; k < JF_NP; k++) z[k] = zn[k];
        lam = lam / 3; if (lam < 1e-9f) lam = 1e-9f;
        cost = jf2_normal(K, z);
        K->iters++; K->tick_it++;
        if (J->tick) J->tick(J->tick_ctx, K->tick_it);
        small = (float)rel < K->ftol ? small + 1u : 0u;
        if (small >= 3u) break;
    }
    return cost;
}
/* one run from J->P (in place): the exact-Jacobian LM over J's samples; amax = 3 x 2048 int16 work */
static float jf_fit_direct(struct jfit *J, int16_t *amax, uint32_t iters) {
    struct jfit2 K = {0};
    K.J = J; K.n = J->n; K.xs = J->xs; K.want = J->want; K.w = J->w; K.amax = amax; K.ftol = 1e-6f; K.nf = JF2_NF;
    double c = jf2_lm(&K, J->P, iters);
    J->cost = (float)c; J->steps = K.iters; J->evals = K.evals + K.gevals;
    return J->cost;
}
/* JFIT v5 (Bei 2026-11-11, projects/lut-sup/validation/20261111-fit-ceiling-01 cheap_recipe.py Q_untied_5k_40): the
 * untied refine -- the same LM from J->P (the packed product solution, M1 = M2) with M1 (set 1, the luma) free, the chain
 * luma_preserve (jf2_split) and the YCMAT yr + yb hinge, on J's samples (the dense set, jf_dense_samples).  J->A: JF2_NFU
 * x JF2_NFU + JF2_NFU doubles. */
static void jf_knee_start(struct jfit2 *K, float *P);
static float jf_fit_untied(struct jfit *J, int16_t *amax, uint32_t iters, int knee) {
    struct jfit2 K = {0};
    K.J = J; K.n = J->n; K.xs = J->xs; K.want = J->want; K.w = J->w; K.amax = amax; K.ftol = 1e-6f;
    K.untied = 1; K.nf = knee ? JF2_NFK : JF2_NFU; K.w_yg = JF_W_YG; K.knee = knee;
    if (knee) jf_knee_start(&K, J->P);                                 /* JFIT v6: the CKNEE free too, from slope 1 */
    else jf_knee_off(J->P);
    double c = jf2_lm(&K, J->P, iters);
    J->cost = (float)c; J->steps = K.iters; J->evals = K.evals + K.gevals;
    return J->cost;
}

/* JFIT v6: the CKNEE's start (validation/20261106-fitter-proto-01 fitter.py with_extras): each half-axis' knee at the
 * 70th percentile of its magnitudes after YCMAT over K's samples (a 256-bin histogram on 0 .. 0.5, the last bin holding
 * everything above; 5 or fewer: 0.2), at least 0.02 and at most JF_KMAX; slope 1 -- so the chain is the one the knee-less
 * start gives, and the knee and slope have a gradient there. */
#define JF_KBINS 256
static void jf_knee_start(struct jfit2 *K, float *P) {
    uint16_t h[4][JF_KBINS]; uint32_t n[4] = {0, 0, 0, 0};
    for (int a = 0; a < 4; a++) for (int b = 0; b < JF_KBINS; b++) h[a][b] = 0;
    jf_knee_off(P);
    jf2_tone(K, P);
    for (uint32_t j = 0; j < K->n; j++) {
        float t[3]; int gid[JF2_LMAX], nm = 0;
        const float *c = K->xs + 3 * j;
        if (K->untied) jf2_split(K, P, c, t, 0, gid, &nm);
        else for (int k = 0; k < 3; k++) {
            float idx = jf_clamp((P[3 * k] * c[0] + P[3 * k + 1] * c[1] + P[3 * k + 2] * c[2]) * JF_WHITE, 0, JF_NTONE - 1);
            t[k] = jf_clamp(jf_tone_at(K->J->tone + k * JF_NTONE, idx), 0, 1);
        }
        const float *q = P + 45;
        float rg = t[0] - t[1], bg = t[2] - t[1];
        for (int comp = 0; comp < 2; comp++) {
            float v = comp ? q[4] * rg + q[5] * bg : q[2] * rg + q[3] * bg;
            int half = 2 * comp + (v < 0);
            if (v < 0) v = -v; else if (!(v > 0)) continue;
            int b = (int)(v * (float)(2 * JF_KBINS)); if (b > JF_KBINS - 1) b = JF_KBINS - 1;
            if (h[half][b] < 0xFFFFu) h[half][b]++;
            n[half]++;
        }
    }
    for (int half = 0; half < 4; half++) {
        float k = 0.2f;
        if (n[half] > 5u) {                                            /* np.percentile 70: rank 0.7 (n - 1) */
            float rank = 0.7f * (float)(n[half] - 1u); uint32_t cum = 0; int b = 0;
            while (b < JF_KBINS - 1 && (float)(cum + h[half][b]) <= rank) cum += h[half][b++];
            k = ((float)b + 0.5f) / (float)(2 * JF_KBINS);
        }
        P[JF_NK + 2 * half] = jf_clamp(k < 0.02f ? 0.02f : k, 0, JF_KMAX);
        P[JF_NK + 2 * half + 1] = 1.0f;
    }
}

/* The 144 extra samples (FITTER_OPTIMIZATION.md, review_sampling.py): Rec.709 / gamma 2.4 display codes on an HSV
 * grid -- 24 hues from 7.5 deg every 15, saturation 0.40 / 0.75, value 0.32 / 0.60 / 0.88 -- linearised (x^2.4)
 * and taken to camera RGB (lut_batch_eval.to_camera: inv(lv_fit.C2R)).  xs: 144 x 3, in that order (hue, sat, val). */
#define JF_NHSV 144u
static void jf_hsv_samples(float *xs) {
    uint32_t n = 0;
    for (int h = 0; h < 24; h++) for (int si = 0; si < 2; si++) for (int vi = 0; vi < 3; vi++) {
        float s = si ? 0.75f : 0.40f, v = vi == 0 ? 0.32f : vi == 1 ? 0.60f : 0.88f;
        float hh = ((float)h + 0.5f) / 24.0f * 6.0f; int i = (int)hh; float f = hh - (float)i;   /* colorsys.hsv_to_rgb */
        float p = v * (1 - s), q = v * (1 - s * f), t = v * (1 - s * (1 - f)), r, g, b;
        switch (i % 6) { case 0: r = v; g = t; b = p; break; case 1: r = q; g = v; b = p; break; case 2: r = p; g = v; b = t; break;
                         case 3: r = p; g = q; b = v; break; case 4: r = t; g = p; b = v; break; default: r = v; g = p; b = q; }
        float l[3] = {jf_pow24(r), jf_pow24(g), jf_pow24(b)};
        xs[3 * n]     =  0.7525381f   * l[0] + 0.32845083f * l[1] - 0.08098891f * l[2];
        xs[3 * n + 1] =  0.058166765f * l[0] + 0.8702844f  * l[1] + 0.07154885f * l[2];
        xs[3 * n + 2] = -0.014688964f * l[0] + 0.26282156f * l[1] + 0.7518674f  * l[2];
        n++;
    }
}

/* ================================================================ JFIT v5 (Bei 2026-11-11): the untied refine's samples and choice
 * The dense set (projects/lut-sup/validation/20261111-fit-ceiling-01 ceil.dense_train, the product's composition): the
 * conversion's own CONV_NX (lvb's 11^3 + the grey axis + the 144 HSV) + these JF_NDX random ones, together ~5000 in the
 * dense set's shares -- camera RGB 81 %, near-grey 10 %, HSV 9 %:
 *   JF_NDX_CAM   camera RGB, CMAX u^2.2 per channel (lv_fit.samples)                       stock-look weight (lvb_weight)
 *   JF_NDX_GREY  the grey axis' recipe (ceil._rand_grey): level 0.01^(1-u), 1 in 7 exact grey,  stock-look weight
 *                else a 3 % tint in a random direction
 *   JF_NDX_HSV   709 codes h, s^0.8, v 0.03..1 -> ^2.4 -> camera RGB (ceil._rand_hsv)          weight 1
 * One generator (xorshift32, fixed seed) for host and camera, each value rounded to Q20 so the camera's render (Q20 in)
 * and the host's target see the same points. */
#define JF_NDX_CAM   2720u
#define JF_NDX_GREY  340u
#define JF_NDX_HSV   297u
#define JF_NDX       (JF_NDX_CAM + JF_NDX_GREY + JF_NDX_HSV)
#define JF_NDX_SEED  0xCE111u
static float jf_rand(uint32_t *x) {                       /* [0, 1), 24 bits */
    uint32_t v = *x; v ^= v << 13; v ^= v >> 17; v ^= v << 5; *x = v;
    return (float)(v >> 8) * 5.9604644775390625e-08f;
}
static float jf_powf(float x, float e) { return x > 0 ? jf_exp2(e * jf_log2(x)) : 0; }
static float jf_q20(float v) { return (float)(int)(v < 0 ? v * 1048576.0f - 0.5f : v * 1048576.0f + 0.5f) * 9.5367431640625e-07f; }
static void jf_cam(const float *l, float *x) {             /* linear 709 -> camera RGB (jf_hsv_samples' matrix) */
    x[0] =  0.7525381f   * l[0] + 0.32845083f * l[1] - 0.08098891f * l[2];
    x[1] =  0.058166765f * l[0] + 0.8702844f  * l[1] + 0.07154885f * l[2];
    x[2] = -0.014688964f * l[0] + 0.26282156f * l[1] + 0.7518674f  * l[2];
}
static void jf_dense_samples(float *xs) {
    uint32_t r = JF_NDX_SEED, n = 0;
    for (uint32_t j = 0; j < JF_NDX_CAM; j++, n++)
        for (int k = 0; k < 3; k++) xs[3 * n + k] = jf_q20(1.0672576f * jf_powf(jf_rand(&r), 2.2f));   /* CMAX = 2047 / 1918 */
    for (uint32_t j = 0; j < JF_NDX_GREY; j++, n++) {
        float lv = jf_exp2((1.0f - jf_rand(&r)) * -6.643856f);                     /* 0.01^(1-u): geometric 0.01..1 */
        float d[3] = {2 * jf_rand(&r) - 1, 2 * jf_rand(&r) - 1, 2 * jf_rand(&r) - 1};
        float nn = jf_sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]), tint = jf_rand(&r) < 0.14285715f || nn < 1e-3f ? 0.0f : 0.03f / nn;
        for (int k = 0; k < 3; k++) xs[3 * n + k] = jf_q20(jf_clamp(lv * (1 + tint * d[k]), 0, 1));
    }
    for (uint32_t j = 0; j < JF_NDX_HSV; j++, n++) {
        float h = jf_rand(&r), s = jf_powf(jf_rand(&r), 0.8f), v = 0.03f + 0.97f * jf_rand(&r);
        float hh = h * 6.0f; int i = (int)hh; float f = hh - (float)i;              /* colorsys.hsv_to_rgb */
        float p = v * (1 - s), q = v * (1 - s * f), t = v * (1 - s * (1 - f)), c[3];
        switch (i % 6) { case 0: c[0] = v; c[1] = t; c[2] = p; break; case 1: c[0] = q; c[1] = v; c[2] = p; break;
                         case 2: c[0] = p; c[1] = v; c[2] = t; break; case 3: c[0] = p; c[1] = q; c[2] = v; break;
                         case 4: c[0] = t; c[1] = p; c[2] = v; break; default: c[0] = v; c[1] = p; c[2] = q; }
        float l[3] = {jf_pow24(c[0]), jf_pow24(c[1]), jf_pow24(c[2])}, x[3];
        jf_cam(l, x);
        for (int k = 0; k < 3; k++) xs[3 * n + k] = jf_q20(x[k]);
    }
}

/* The packed tables of a .JFT payload (jft.py pack: shift, m2, tone, ycmat, ceq, ygam, m1, the CKNEE) as the chain's P and tone
 * (the ISP's view, ceil.hw_code): M = the table / 512 (the tone already resampled by the shift), YCMAT / 4096 / 512,
 * CEQ L / 512, S / 683, H's shift from its node in degrees, YGAM's 17 nodes from its words (y0, the 15 knots, the
 * last from knot 15 + slope 15 + the end word - 1); P[18..44] (the knots, already in the tone) 0. */
static int16_t jf_s16(const uint8_t *p) { return (int16_t)(p[0] | p[1] << 8); }
static uint32_t jf_u16(const uint8_t *p) { return (uint32_t)(p[0] | p[1] << 8); }
static uint32_t jf_u32(const uint8_t *p) { return jf_u16(p) | jf_u16(p + 2) << 16; }
#define JF_PAY_M1  12544u                                  /* jft.PAYLOAD's m1, after the v4 payload */
static void jf_unpack(const uint8_t *pay, float *P, float *tone) {
    for (int g = 0; g < 2; g++) {
        const uint8_t *t = pay + (g ? JF_PAY_M1 : 4u);
        float m[9] = {(float)jf_s16(t), (float)jf_s16(t + 2), (float)jf_s16(t + 4), (float)jf_s16(t + 8), (float)jf_s16(t + 6),
                      (float)jf_s16(t + 10), (float)jf_s16(t + 14), (float)jf_s16(t + 16), (float)jf_s16(t + 12)};
        for (int k = 0; k < 9; k++) P[9 * g + k] = m[k] * 0.001953125f;          /* table order -> rows, / 512 */
    }
    for (int i = 0; i < 3 * JF_NTONE; i++) tone[i] = (float)jf_u16(pay + 24 + 2 * i) / 8190.0f;
    for (int k = 18; k < 45; k++) P[k] = 0;
    const uint8_t *yc = pay + 24 + 6 * JF_NTONE, *cq = yc + 16, *yg = cq + 144;
    float *q = P + 45;
    q[0] = (float)jf_s16(yc) * 0.000244140625f; q[1] = (float)jf_s16(yc + 4) * 0.000244140625f;
    for (int k = 0; k < 4; k++) q[2 + k] = (float)jf_s16(yc + 6 + 2 * k) * 0.001953125f;
    for (int a = 0; a < 24; a++) {
        q[54 + a] = (float)jf_u16(cq + 2 * a) / 512.0f;
        q[30 + a] = (float)jf_u16(cq + 48 + 2 * a) / 683.0f;
        int org = (int)((float)a * 2730.6667f + 0.5f);
        int d = (int)((jf_u16(cq + 96 + 2 * a) - (uint32_t)org + 32768u) & 0xFFFFu) - 32768;
        q[6 + a] = (float)d * 0.0054931640625f;                                  /* 360 / 65536 */
    }
    uint32_t w[18];
    for (int k = 0; k < 18; k++) w[k] = jf_u32(yg + 4 * k);
    q[78] = (float)(w[0] >> 16) / 4095.0f;
    for (int i = 0; i < 15; i++) q[79 + i] = (float)(i & 1 ? w[1 + i / 2] >> 16 : w[1 + i / 2] & 0xFFFFu) / 4095.0f;
    q[94] = (float)((int)(w[8] & 0xFFFFu) + (int)(w[16] >> 16) + (int)w[17] - 1) / 4095.0f;
    const uint8_t *kb = pay + JF_PAY_KN;                               /* JFIT v6: the CKNEE, its codes as the ISP takes them */
    if (jf_u32(kb) == 1u) {                                            /* (record +4 kA +6 kC +8 sA +9 sC +10 kB +12 kD +14 sB +15 sD) */
        uint32_t kc[8] = {jf_u16(kb + 4), kb[8], jf_u16(kb + 6), kb[9], jf_u16(kb + 10), kb[14], jf_u16(kb + 12), kb[15]};
        for (int i = 0; i < 8; i++) P[JF_NK + i] = (float)kc[i] / (i & 1 ? 16.0f : 1024.0f);
    } else jf_knee_off(P);
}
/* the choice's cost (JFIT v5): sum over J's samples of (w (Lab - want))^2 through a payload's packed tables -- the
 * study's training cost on the hardware's integers (no tail: the packed tables have no parameters to regularise).
 * P, tone: work (140, 3 x 2048 floats); J->tone points at tone meanwhile, back after. */
static double jf_packed_cost(struct jfit *J, const uint8_t *pay, float *P, float *tone) {
    float *keep = J->tone;
    jf_unpack(pay, P, tone);
    J->tone = tone;
    double c = (double)P[0] - (double)P[0];
    for (uint32_t j = 0; j < J->n; j++) {
        if (J->spin && !(j & 31u)) J->spin(J->tick_ctx);
        float lab[3]; jf_sample(J, P, J->xs + 3 * j, lab, 0);
        for (int k = 0; k < 3; k++) { float e = (lab[k] - J->want[3 * j + k]) * J->w[j]; c += (double)e * e; }
    }
    J->tone = keep;
    return c;
}
