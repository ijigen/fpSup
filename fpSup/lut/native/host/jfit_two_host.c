/* host build of jfit_two.c for the parity test (fpSup/lut/test_jfit_two.py): plain C, malloc for the work area.
 * Also jf_fit_direct (jfit.c) from the same library, for the timing ratio. */
#include <stdlib.h>
#include <string.h>
#include "../jfit.c"
#include "../jfit_two.c"

static struct jtwo *jt_host_new(const float *base_a, const float *PA, const float *PB, uint32_t nmax, uint32_t nsel) {
    struct jtwo *T = calloc(1, sizeof *T);
    jt_defaults(T);
    T->base_a = base_a;
    memcpy(T->PA, PA, sizeof T->PA); memcpy(T->PB, PB, sizeof T->PB);
    T->work = aligned_alloc(8, (jt_work_bytes(nmax, nsel) + 7u) & ~7u);
    jt_carve(T, nmax, nsel);
    return T;
}
static void jt_host_free(struct jtwo *T) { free(T->work); free(T); }

uint32_t jt_host_work_bytes(uint32_t nmax, uint32_t nsel) { return jt_work_bytes(nmax, nsel); }
uint32_t jt_host_struct_bytes(void) { return (uint32_t)sizeof(struct jtwo); }
void jt_host_identity(float *P) { jt_identity(P); }

/* forward of n samples: lab (n x 3); jac (n x 3 x 253, 0 = none) */
void jt_host_forward(const float *base_a, const float *z, uint32_t n, const float *xs, int hard, float *lab, float *jac) {
    float P0[JF_NP]; jt_identity(P0);
    struct jtwo *T = jt_host_new(base_a, P0, P0, n, 1);
    jt_prepare(T, z);
    for (uint32_t j = 0; j < n; j++) {
        float R[3][JT_LMAX]; int col[JT_LMAX], m = 0;
        jt_sample(T, xs + 3 * j, hard, lab + 3 * j, jac ? R : 0, col, &m);
        if (jac) for (int o = 0; o < 3; o++) for (int i = 0; i < m; i++) jac[(3 * j + o) * JT_NZ + col[i]] += R[o][i];
    }
    jt_host_free(T);
}

/* quantise + payloads (2 x 12544) of z; returns rc_a | rc_b << 4 */
int jt_host_pack(const float *base_a, const float *z, uint8_t *pay) {
    float P0[JF_NP]; jt_identity(P0);
    struct jtwo *T = jt_host_new(base_a, P0, P0, 1, 1);
    float PA[JF_NP], PB[JF_NP];
    jt_unpack(z, PA, PB);
    int ra = jt_quantise(T, 0, PA, &T->hw[0]), rb = jt_quantise(T, 1, PB, &T->hw[1]);
    if (!ra) jt_payload(&T->hw[0], pay);
    if (!rb) jt_payload(&T->hw[1], pay + JT_PAYLOAD);
    jt_host_free(T);
    return ra | rb << 4;
}

/* integer replay of n points through z's packed tables (out: 709 code RGB) and the selection loss */
float jt_host_replay(const float *base_a, const float *z, uint32_t n, const float *xs, const float *want, float *out) {
    float P0[JF_NP]; jt_identity(P0);
    struct jtwo *T = jt_host_new(base_a, P0, P0, n, n);
    T->sel.n = n; T->sel.xs = xs; T->sel.want = want;
    float loss = jt_select(T, z);
    if (loss < JT_BIG) for (uint32_t j = 0; j < n; j++) jt_replay2(T, xs + 3 * j, out + 3 * j);
    jt_host_free(T);
    return loss;
}

/* the whole fit.  sets: 3 x (n, xs, want, wt); sel: (n, xs, want).  out z (253), stats[8]; payloads 2 x 12544 */
float jt_host_fit(const float *base_a, float *PA, float *PB, const uint32_t *ns, const float *const *xs,
                  const float *const *want, const float *const *wt, uint32_t nsel, const float *sxs, const float *swant,
                  const uint32_t *iters, float *zout, float *stats, uint8_t *pay) {
    uint32_t nmax = nsel;
    for (int s = 0; s < 3; s++) if (ns[s] > nmax) nmax = ns[s];
    struct jtwo *T = jt_host_new(base_a, PA, PB, nmax, nsel);
    for (int s = 0; s < 3; s++) { T->set[s].n = ns[s]; T->set[s].xs = xs[s]; T->set[s].want = want[s]; T->set[s].wt = wt[s]; if (iters) T->iters[s] = iters[s]; }
    T->sel.n = nsel; T->sel.xs = sxs; T->sel.want = swant;
    float c = jt_fit(T);
    memcpy(PA, T->PA, sizeof T->PA); memcpy(PB, T->PB, sizeof T->PB);
    for (int k = 0; k < JT_NZ; k++) zout[k] = T->best[k];
    stats[0] = T->start_cost; stats[1] = T->sel_cost; stats[2] = (float)T->steps; stats[3] = (float)T->evals;
    stats[4] = (float)T->gevals; stats[5] = (float)T->checks; stats[6] = (float)T->err; stats[7] = 0;
    if (!T->err) { jt_payload(&T->hw[0], pay); jt_payload(&T->hw[1], pay + JT_PAYLOAD); }
    jt_host_free(T);
    return c;
}

uint32_t jt_host_draw(uint32_t seed, uint32_t n, float *xs) { return jt_draw(&seed, n, xs); }
void jt_host_weight(uint32_t n, const float *rgb0, float *w) { for (uint32_t j = 0; j < n; j++) w[j] = jt_weight(rgb0 + 3 * j); }

/* jf_fit_direct (one start), as jfit_host.c */
float jt_host_direct(float *P, const float *base_tone, uint32_t n, const float *xs, const float *want, const float *w, uint32_t iters) {
    struct jfit J = {0};
    J.w_hue = 0.02f; J.w_gain = 2.0f; J.w_curve = 2.0f;
    J.n = n; J.xs = xs; J.want = want; J.w = w; J.base_tone = base_tone;
    for (int i = 0; i < JF_NK; i++) J.P[i] = P[i];   /* the 140 (JFIT v6: no CKNEE here) */
    jf_knee_off(J.P);
    J.tone = malloc(3 * JF_NTONE * sizeof(float));
    J.A = malloc(((size_t)JF2_NF * JF2_NF + JF2_NF) * sizeof(double));
    int16_t *amax = malloc(3 * JF_NTONE * sizeof(int16_t));
    float c = jf_fit_direct(&J, amax, iters);
    for (int i = 0; i < JF_NK; i++) P[i] = J.P[i];
    free(J.tone); free(J.A); free(amax);
    return c;
}
/* the old jf_fit (numerical Jacobian), for the camera / host ratio (joint-bench-01: camera 4.77 s, 10 iterations) */
float jt_host_oldfit(float *P, const float *base_tone, uint32_t n, const float *xs, const float *want, const float *w, uint32_t iters) {
    struct jfit J = {0};
    int idx[JF_NP], nf = jf_free(idx);
    uint32_t nr = JF_NRES(n);
    J.w_hue = 0.02f; J.w_gain = 2.0f; J.w_curve = 2.0f;
    J.n = n; J.xs = xs; J.want = want; J.w = w; J.base_tone = base_tone; J.iters = iters;
    for (int i = 0; i < JF_NK; i++) J.P[i] = P[i];   /* the 140 (JFIT v6: no CKNEE here) */
    jf_knee_off(J.P);
    J.tone = malloc(3 * JF_NTONE * sizeof(float));
    J.res = malloc(nr * sizeof(float)); J.res2 = malloc(nr * sizeof(float));
    J.pert = malloc(27 * JF_NTONE * sizeof(float));
    J.A = malloc(((size_t)nf * nf + nf) * sizeof(double));
    J.pre = malloc(5 * n * sizeof(float));
    float c = jf_fit(&J);
    for (int i = 0; i < JF_NK; i++) P[i] = J.P[i];
    free(J.tone); free(J.res); free(J.res2); free(J.pert); free(J.A); free(J.pre);
    return c;
}
