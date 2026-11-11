/* host build of jfit.c for the parity test (test_jfit.py): plain C, malloc for the work arrays. */
#include <stdlib.h>
#define JF_TEST 1
#include "../jfit.c"
#ifndef JF_HOST_W_MONO
#define JF_HOST_W_MONO JF_W_MONO          /* as conv.c conv_compute */
#endif
void jf_host_dense(int on) { jf_force_dense = on; }

int jf_host_lab(const float *P, const float *base_tone, uint32_t n, const float *xs, float *out) {
    struct jfit J = {0};
    J.base_tone = base_tone;
    J.tone = malloc(3 * JF_NTONE * sizeof(float));
    jf_build_tone(&J, P);
    for (uint32_t j = 0; j < n; j++) jf_sample(&J, P, xs + 3 * j, out + 3 * j, 0);
    free(J.tone);
    return 0;
}

float jf_host_fit(float *P, const float *base_tone, uint32_t n, const float *xs, const float *want, const float *w,
                  uint32_t iters, uint32_t *evals_steps) {
    struct jfit J = {0};
    int idx[JF_NP], nf = jf_free(idx);
    uint32_t nr = JF_NRES(n);
    J.w_hue = 0.02f; J.w_gain = 2.0f; J.w_curve = 2.0f; J.w_mono = JF_HOST_W_MONO;
    J.n = n; J.xs = xs; J.want = want; J.w = w; J.base_tone = base_tone; J.iters = iters;
    for (int i = 0; i < JF_NP; i++) J.P[i] = P[i];
    J.tone = malloc(3 * JF_NTONE * sizeof(float));
    J.res = malloc(nr * sizeof(float)); J.res2 = malloc(nr * sizeof(float));
    J.pert = malloc(27 * JF_NTONE * sizeof(float));
    J.A = malloc(((size_t)nf * nf + nf) * sizeof(double));
    J.pre = malloc(5 * n * sizeof(float));
    float c = jf_fit(&J);
    for (int i = 0; i < JF_NP; i++) P[i] = J.P[i];
    evals_steps[0] = J.evals; evals_steps[1] = J.steps;
    free(J.tone); free(J.res); free(J.res2); free(J.pert); free(J.A); free(J.pre);
    return c;
}

float jf_host_direct(float *P, const float *base_tone, uint32_t n, const float *xs, const float *want, const float *w,
                     uint32_t iters, uint32_t *evals_steps) {
    struct jfit J = {0};
    J.w_hue = 0.02f; J.w_gain = 2.0f; J.w_curve = 2.0f; J.w_mono = JF_HOST_W_MONO;
    J.n = n; J.xs = xs; J.want = want; J.w = w; J.base_tone = base_tone;
    for (int i = 0; i < JF_NP; i++) J.P[i] = P[i];
    J.tone = malloc(3 * JF_NTONE * sizeof(float));
    J.A = malloc(((size_t)JF2_NF * JF2_NF + JF2_NF) * sizeof(double));
    int16_t *amax = malloc(3 * JF_NTONE * sizeof(int16_t));
    float c = jf_fit_direct(&J, amax, iters);
    for (int i = 0; i < JF_NP; i++) P[i] = J.P[i];
    evals_steps[0] = J.evals; evals_steps[1] = J.steps;
    free(J.tone); free(J.A); free(amax);
    return c;
}
void jf_host_hsv(float *xs) { jf_hsv_samples(xs); }

/* JFIT v5 (2026-11-11): the untied refine, its dense samples and the packed-cost choice (conv.c conv_untie);
 * JFIT v6: knee 1 frees the CKNEE too (P[JF_NK..], from jf_knee_start) */
float jf_host_untied_k(float *P, const float *base_tone, uint32_t n, const float *xs, const float *want, const float *w,
                       uint32_t iters, uint32_t *evals_steps, int knee) {
    struct jfit J = {0};
    J.w_hue = 0.02f; J.w_gain = 2.0f; J.w_curve = 2.0f; J.w_mono = JF_HOST_W_MONO;
    J.n = n; J.xs = xs; J.want = want; J.w = w; J.base_tone = base_tone;
    for (int i = 0; i < JF_NP; i++) J.P[i] = P[i];
    J.tone = malloc(3 * JF_NTONE * sizeof(float));
    J.A = malloc(((size_t)JF2_NFK * JF2_NFK + JF2_NFK) * sizeof(double));
    int16_t *amax = malloc(3 * JF_NTONE * sizeof(int16_t));
    float c = jf_fit_untied(&J, amax, iters, knee);
    for (int i = 0; i < JF_NP; i++) P[i] = J.P[i];
    evals_steps[0] = J.evals; evals_steps[1] = J.steps;
    free(J.tone); free(J.A); free(amax);
    return c;
}
float jf_host_untied(float *P, const float *base_tone, uint32_t n, const float *xs, const float *want, const float *w,
                     uint32_t iters, uint32_t *evals_steps) {
    return jf_host_untied_k(P, base_tone, n, xs, want, w, iters, evals_steps, 0);
}
void jf_host_dense_samples(float *xs) { jf_dense_samples(xs); }
uint32_t jf_host_ndx(void) { return JF_NDX; }
double jf_host_packed_cost(const uint8_t *pay, uint32_t n, const float *xs, const float *want, const float *w) {
    struct jfit J = {0};
    J.n = n; J.xs = xs; J.want = want; J.w = w;
    float P[JF_NP], *tone = malloc(3 * JF_NTONE * sizeof(float));
    double c = jf_packed_cost(&J, pay, P, tone);
    free(tone);
    return c;
}
/* the chain on a payload's packed tables (tests: jf_unpack against jft.unpack + ceil.hw_code) */
void jf_host_packed_lab(const uint8_t *pay, uint32_t n, const float *xs, float *out) {
    struct jfit J = {0};
    float P[JF_NP], *tone = malloc(3 * JF_NTONE * sizeof(float));
    jf_unpack(pay, P, tone);
    J.tone = tone;
    for (uint32_t j = 0; j < n; j++) jf_sample(&J, P, xs + 3 * j, out + 3 * j, 0);
    free(tone);
}
/* tests: jf2_normal's cost and gradient J^T r (the free columns: 131 tied, 140 untied, 148 untied + the CKNEE:
 * untied 2) and jf2_cost at P */
double jf_host_normal(const float *P, int untied, const float *base_tone, uint32_t n, const float *xs, const float *want,
                      const float *w, double *g_out, double *cost_only) {
    struct jfit J = {0};
    struct jfit2 K = {0};
    J.w_hue = 0.02f; J.w_gain = 2.0f; J.w_curve = 2.0f; J.w_mono = JF_HOST_W_MONO; J.base_tone = base_tone;
    K.J = &J; K.n = n; K.xs = xs; K.want = want; K.w = w; K.untied = untied != 0; K.knee = untied == 2;
    K.nf = untied == 2 ? JF2_NFK : untied ? JF2_NFU : JF2_NF;
    K.w_yg = untied ? JF_W_YG : 0;
    J.tone = malloc(3 * JF_NTONE * sizeof(float));
    J.A = malloc(((size_t)JF2_NFK * JF2_NFK + JF2_NFK) * sizeof(double));
    K.amax = malloc(3 * JF_NTONE * sizeof(int16_t));
    double c = jf2_normal(&K, P);
    for (int i = 0; i < K.nf; i++) g_out[i] = J.A[K.nf * K.nf + i];
    *cost_only = jf2_cost(&K, P);
    free(J.tone); free(J.A); free(K.amax);
    return c;
}
