/* conv.c -- a cube's .JFT made on the camera, in the LUT manager (user 2026-11-04: "在 LUT Manager 中做轉檔、
 * 轉完之前不能選"; turning a cube On converts it first; the match shown as a percentage; two starts).
 * Design: projects/lut-sup/notes/STAGE_B_CONVERT_IN_MANAGER.md.  Host twin: jft.py convert().
 *
 *   UI thread   conv_start: the work area borrowed (borrow.c: struct conv_work, with lvb_fit's samples and
 *               the cube's asset for the inputs); the cube's samples, weights, target and neutral curves
 *               (lvb_fit, the cube loaded into the borrowed asset area) and the ColorChecker's target,
 *               copied as floats into the work area; the samples and the asset returned; the worker woken.
 *   worker      conv_task (created once, priority CONV_PRI, sleeps in tk_slp_tsk): JFIT v3 "xlm10+144" (Bei 11-07:
 *               projects/lut-sup/validation/20261107-onepass-steps-01): the v1 jf_fit (20 steps) from the identity
 *               and from lvb's matrix on lvb's samples + the grey axis alone, as JFIT v1 did; the cheaper is the seed
 *               of jf_fit_direct (10 steps) on those + the 144 HSV samples (weight 1).  Packed: the refined
 *               solution, else the seed, else the other v1 start -- the first that quantises (jft.quantise; a YCMAT
 *               overflow does not fail the conversion); the ColorChecker scored from the one packed.  JFIT v5 (Bei
 *               2026-11-11, projects/lut-sup/validation/20261111-fit-ceiling-01): then conv_untie -- jf_fit_untied (40
 *               steps, M1 = RGBLMAT set 1 freed from M2) from the packed result on the dense set (CONV_ND: CONV_NX +
 *               jf_dense_samples), kept when it packs and its packed tables cost less there (jf_packed_cost).  JFIT v6 (2026-11-11,
 *               projects/lut-sup/validation/20261111-cknee-cal): that refine frees the ISP's CKNEE too (8 more parameters,
 *               jfit.c JF_NK); its result packed with the knee and without (the same tables, CKNEE off), the cheapest of
 *               those two and the v4 one on the dense set kept -- the knee only when it lowers the packed cost.  Touches the conv region only; posts progress text and, last,
 *               the app state "LC_ConvEnd" (the page answers with LC_Key = CONV_DONE_KEY on the UI thread).
 *   UI thread   conv_finish (the key, or any later callback): mkdir, write, read back; the work area
 *               returned (success or not); then the cube is enabled and the COLOR list synced (lvb_refresh
 *               reads the file it just wrote).  At steady state the block holds struct conv_keep alone.
 * Nothing here while recording: the manager is not reachable then. */
#include "jfit.c"

#define CONV_CAP      0x400u               /* the resident struct conv_keep; build_sup.CONV_CAP */
#define CONV_CHK      72u
#define CONV_GREY     168u                 /* jft.grey_samples: 24 grey levels x (1 + 6 tints), after the checker in the file */
#define CONV_N        (LVB_S + CONV_GREY)  /* lvb's 11^3 grid, then the grey axis (11-05: the grid's greys too few) */
#define CONV_NX       (CONV_N + JF_NHSV)   /* + the 144 HSV samples (jfit.c jf_hsv_samples), weight 1: what the fit sees */
#define CONV_NF       JF2_NFK              /* A: the untied refine's 148 x 148 + 148 (JFIT v6: + the CKNEE; the earlier stages use
                                            * 131 x 131 + 131 of it) */
#define CONV_XW       (JF_NDX - JF_NDX_HSV)  /* jf_dense_samples' camera RGB + near-grey ones: the stock-look weight */
#define CONV_ND       (CONV_NX + JF_NDX)   /* JFIT v5's dense set: what the fit saw + jf_dense_samples (~5000) */
#define CONV_PRI      29u                  /* inittsk (the idle loop, 77% CPU in live view) is 30 and never yields: 30 starved on camera 11-04 */
#define CONV_STACK    0x4000u
#define CONV_ITERS    20u                  /* the v1 stage: jf_fit's steps per start (jft.CONV_ITERS) */
#define CONV_DIRECT_ITERS 10u              /* the refine: jf_fit_direct's steps from the seed ("xlm10+144"; jft.CONV_DIRECT_ITERS);
                                            * s->conv.iters, when not 0, replaces all three (the tests: 1) */
#define CONV_UNTIE_ITERS 40u               /* JFIT v5: jf_fit_untied's steps (jft.CONV_UNTIE_ITERS) */
#define TK_CRE_TSK    0xC0016A58u
#define TK_STA_TSK    0xC0016BC0u
#define TK_SLP_TSK    0xC01F8D00u
#define TK_WUP_TSK    0xC01F8ED4u
#define FS_DISK       0xC0407E20u          /* the shell's mkdir (0xC03E2D00): ctor(obj, disk), mkdir(obj, path, 0), dtor(obj, 2) */
#define FS_DIR_CTOR   0xC0366918u
#define FS_DIR_MAKE   0xC03669C0u
#define FS_DIR_DTOR   0xC0366940u
#define GUI_FUNCTION  0xC054DD38u          /* the GUI function object, as the card format's end does (MenuMediaFormatConfirmationHandler::v76) */
#define GUI_APPSTATE  0xC055D470u          /* its vtable slot 3, UicGuiFunction::v1(obj, name): an app-state message on the GUI queue (keeps the pointer) */
#define CONV_EVENT    122u                 /* string: "LC_ConvEnd", the page's appStateEvent (manager_page.conv_end) */
#define CONV_BEGIN    123u                 /* string: "LC_ConvStart": the page moves focus onto the overlay (manager_page.busy) */
#define MS_CLOCK      0xC002B920u          /* ms since boot (ARM; Sensor Lab's hold-to-repeat) */
#define CONV_FRAME_MS 333u                 /* the stock hourglass: cmn_clock_1/2/3, 333 ms each (LV ImageProcessing) */
#define CONV_MAGIC    0x31564E43u          /* 'CNV1' */
#define CONV_PATCHES  48u                  /* manager_page.checker_chart: 24 patches x {target, fit} */
#define CONV_CHK0     24u                  /* the checker's 0 EV set (lut_batch_eval.sample_sets: -1, 0, +1) */
#define CONV_BAR_W    640u                 /* manager_page.BAR_RECT's width */
#define CONV_EMPTY    0x222222FFu          /* manager_page.CHART_COLOUR: a half not posted yet */
enum { CV_IDLE, CV_RUN, CV_DONE, CV_FAIL };
enum { CVE_NONE, CVE_STATE, CVE_TASK, CVE_FIT, CVE_RANGE, CVE_YCMAT, CVE_WRITE, CVE_ENABLE, CVE_MEMORY, CVE_HUE };   /* MEMORY: recording / no area; HUE: CEQ hue words out of order (never: jf_hue_safe) */

/* borrowed for one conversion (borrow.c, s->b_conv): conv_start .. conv_finish, the worker's alone between */
struct conv_work {
    double A[CONV_NF * CONV_NF + CONV_NF];  /* first: 8-aligned; jf2_normal's J^T J (lower) + g */
    float xs[CONV_ND * 3], want[CONV_ND * 3], w[CONV_ND];   /* the first CONV_NX what v1 / the refine fit */
    float bt[3 * LVB_N], tone[3 * LVB_N];
    float chk[CONV_CHK * 3], chkw[CONV_CHK * 3], dE[CONV_CHK];
    float m0[9], best[JF_NP];
    u8 jft[JFT_FILE];                       /* the file being made, its chart block last (here: the tests know the offset) */
    i32 chki[CONV_CHK][3];                  /* the ColorChecker, rendered in place */
    i32 gx[CONV_GREY][3], gw[CONV_GREY][3], gy[CONV_GREY][3];   /* the grey axis: input, stock look (weights), target */
    i32 hx[JF_NHSV][3];                     /* the HSV samples, Q20, rendered in place: their target */
    float alt[JF_NP], alt2[JF_NP], cost[3]; /* best: the refined solution (after conv_choose: the one packed); alt: the
                                             * v1 seed; alt2: the other v1 start; cost[k] each one's (refine: on CONV_NX) */
    int16_t amax[3 * LVB_N];                /* jf_fit_direct's work: the tone's running argmax */
    float prod[JF_NP], pw[JF_NP];           /* JFIT v5: the packed v4 result (conv_untie); jf_packed_cost's P */
    float ucost[3]; u32 untie, knee;        /* the packed costs on CONV_ND: v4, untied without the CKNEE, untied with it
                                             * (JFIT v6); untie 1 = an untied one kept, 0 = the v4 one, 2 = (neither untied
                                             * one packed); knee 1 = the one with the CKNEE kept */
    float res[JF_NRES(CONV_N)], res2[JF_NRES(CONV_N)];   /* jf_fit's work (the v1 stage, CONV_N samples) */
    union {
        float pert[27 * LVB_N];             /* jf_fit's work (the v1 stage) */
        i32 dx[JF_NDX][3];                  /* conv_inputs, before: the dense extras, Q20, rendered in place */
    } u;
    float pre[5 * CONV_N];
    struct jfit J;
    struct lvb_set scratch;                 /* lvb_fit's output (never shown, never built: no pointer to it anywhere) */
};
/* resident (cfg->conv_off): what the manager reads at any time, and the texts the GUI is handed */
struct conv_keep {
    u8 hdr[64];
    char path[48], text[32], vtext[6][8];
    u32 ck[LIB_MAX], csha[LIB_MAX], score[LIB_MAX];   /* conv_ok's cache: key, sha word, match % + 1 (0 none) */
    char title[48];                         /* the AEL page's title: "<name>  75% match" (conv_title) */
    u32 spin_t, frame;                      /* the hourglass: last frame's ms, frame 0..2 (worker only) */
    u32 chart_on, chart_n;                  /* conv_chart: LC_Chart posted 1; the chart's posts this conversion */
    u32 patch[CONV_PATCHES];                /* the colour last posted per half (0 = none yet) */
    char mtext[2][16]; u32 mi;              /* "Match 87%": two buffers (the GUI keeps the pointer) */
    u32 view_rc, view_n;                    /* conv_view: the last one's result (CVV_*), how many */
};
_Static_assert(sizeof(struct conv_keep) <= CONV_CAP, "conv region");
_Static_assert(CONV_NF == JF2_NFK && JF2_NF <= CONV_NF && JF2_NFU <= CONV_NF && LVB_N == JF_NTONE, "conv_work's A / tone / amax are jf_fit_direct's and jf_fit_untied's");
_Static_assert(JFT_PAY_M1 == JF_PAY_M1 && JFT_PAY_KN == JF_PAY_KN && JF_PAY_KN == JF_PAY_M1 + 20u && JFT_BYTES == 64u + JF_PAY_KN + 16u,
               "the payload: ... m1, then the CKNEE block, last (jfit.c jf_unpack, lvb.c)");
_Static_assert(JFT_BYTES % 4u == 0 && JFT_FILE % 4u == 0, "what follows jft stays aligned");
_Static_assert(JFC_BYTES == 16u + 4u * CONV_PATCHES + 4u, "the chart block: head, the 48 halves, its fnv");

static struct conv_keep *conv_mem(struct lut4_state *s) {
    return s->cfg->conv_off ? (struct conv_keep *)((u8 *)s->block + s->cfg->conv_off) : 0;
}
static struct conv_work *conv_work(struct lut4_state *s) { return (struct conv_work *)(void *)s->b_conv.p; }
static i32 conv_round(float x) { return (i32)(x < 0 ? x - 0.5f : x + 0.5f); }
static i32 conv_clampi(i32 v, i32 lo, i32 hi) { return v < lo ? lo : v > hi ? hi : v; }
static void conv_w16(u8 *p, u32 v) { p[0] = (u8)v; p[1] = (u8)(v >> 8); }
static void conv_w32(u8 *p, u32 v) { conv_w16(p, v); conv_w16(p + 2, v >> 16); }
/* 100 - 10 x mean dE, from the header's dE x 100 (no divide instruction: x 6554 >> 16 ~ / 10) */
static u32 conv_pct(u32 mean100) {
    u32 tenth = (mean100 * 6554u + 32768u) >> 16;
    return tenth >= 100u ? 0u : 100u - tenth;
}
static u32 conv_num(char *p, u32 v) {
    char t[10]; u32 n = 0;
    do { u32 q = (v * 52429u) >> 19; t[n++] = (char)('0' + v - q * 10u); v = q; } while (v);   /* v < 2^16 */
    for (u32 i = 0; i < n; i++) p[i] = t[n - 1u - i];
    return n;
}
static u32 conv_cat(char *p, const char *t) { u32 n = 0; while (t && t[n]) { p[n] = t[n]; n++; } return n; }

/* ---------------------------------------------------------------- is entry i converted (key without strength) */
static u32 conv_key(const struct lib_entry *e) { return 1u << 12 | (e->color & 15u) | (e->gamma & 15u) << 4 | (e->matrix & 15u) << 8; }
static u32 conv_w(const struct lib_entry *e, u32 o) { return (u32)e->sha[o] | (u32)e->sha[o + 1] << 8 | (u32)e->sha[o + 2] << 16 | (u32)e->sha[o + 3] << 24; }
/* the cache key: sha[0..3] is "CAM1" for every card cube, so also its size (4..7) and name hash (20..23) -- an entry
 * whose cube changed size or moved in the list (imp_scan while running) is looked up again (2026-11-10) */
static u32 conv_sha(const struct lib_entry *e) { return conv_w(e, 0) ^ conv_w(e, 4) ^ (conv_w(e, 20) << 7 | conv_w(e, 20) >> 25); }
/* the file's match %, + 1; 0 = no file for this key (the strength may differ: lvb_refresh fits that itself) */
static u32 conv_score(struct lut4_state *s, u32 i) {
    struct conv_keep *C = conv_mem(s);
    if (!C || !s->library || i >= s->library->h.count || i >= LIB_MAX) return 0;
    const struct lib_entry *e = &s->library->entries[i];
    if (C->ck[i] == conv_key(e) && C->csha[i] == conv_sha(e)) return C->score[i];
    lvb_jpath(C->path, e->sha, 0);
    const u8 *b = C->hdr; u32 score = 0;
    if (s->svc->file_read(s->svc, C->path, C->hdr, 64u) == 64 && lvb_u32(b) == JFT_MAGIC && lvb_u32(b + 4) == 1u &&
        lvb_u32(b + 8) == 64u && lvb_u32(b + 12) == JFT_BYTES && lvb_u32(b + 24) == e->color && lvb_u32(b + 28) == e->gamma &&
        lvb_u32(b + 36) == e->matrix && lvb_u32(b + 40) == JFT_JFIT) {
        u32 k = 0; while (k < 8u && b[16 + k] == e->sha[k]) k++;
        if (k == 8u) score = conv_pct(lvb_u32(b + 44)) + 1u;
    }
    C->ck[i] = conv_key(e); C->csha[i] = conv_sha(e); C->score[i] = score;
    return score;
}
/* cols.c / COL-Share: a row only once converted -- or no conv region (an old build: as before) */
static int conv_ok(struct lut4_state *s, u32 i) { return !conv_mem(s) || conv_score(s, i) != 0; }
static void conv_forget(struct lut4_state *s, u32 i) { struct conv_keep *C = conv_mem(s); if (C && i < LIB_MAX) C->ck[i] = 0; }

/* ---------------------------------------------------------------- progress (worker or UI thread) */
static void conv_text(struct lut4_state *s, u32 pct, int done) {
    struct conv_keep *C = conv_mem(s); char *p = C->text; u32 n = 0;
    if (!done) { n += conv_cat(p, string(s, 118)); n += conv_num(p + n, pct); p[n++] = '%'; }   /* "Converting 37%" */
    else { n += conv_num(p, pct); n += conv_cat(p + n, string(s, 119)); }                        /* "94% match" */
    p[n] = 0;
    if (s->ui) fpui_set_text(s->ui, MV_OK, C->text);
    s->ui_cache[MV_OK] = 0;
}
/* the overlay (manager_page.busy_overlay): LC_Busy its opacity, LC_Clock0..2 the hourglass frames' */
static void conv_clock(struct lut4_state *s, u32 f) {
    if (s->ui) for (u32 k = 0; k < 3u; k++) fpui_set(s->ui, MV_CLOCK0 + k, k == f);
}
static void conv_spin(void *ctx) {                                    /* worker: jfit's spin */
    struct lut4_state *s = ctx; struct conv_keep *C = conv_mem(s);
    u32 now = FW(MS_CLOCK, u32 (*)(void))();
    if (now - C->spin_t < CONV_FRAME_MS) return;
    C->spin_t = now; C->frame = C->frame >= 2u ? 0u : C->frame + 1u;
    conv_clock(s, C->frame);
}
/* UI thread: on with the conversion (and again when the page opens while it runs), off at its finish.
 * On also asks the page for focus on the overlay (keys go nowhere while it runs, as the stock format's
 * UpdateProgress); the end's appStateEvent gives it back to LC_Focus. */
static void conv_busy(struct lut4_state *s, int on) {
    struct conv_keep *C = conv_mem(s);
    if (!s->ui || !C) return;
    fpui_set(s->ui, MV_BUSY, on ? 1u : 0u); s->ui_cache[MV_BUSY] = 0;
    C->frame = 0; C->spin_t = FW(MS_CLOCK, u32 (*)(void))();
    conv_clock(s, on ? 0u : 3u);
    if (on) FW(GUI_APPSTATE, u32 (*)(void *, const char *))(FW(GUI_FUNCTION, void *(*)(void))(), string(s, CONV_BEGIN));
}
/* ---------------------------------------------------------------- the ColorChecker chart (manager_page.checker_chart)
 * Bei 11-07: the 24 patches, top the cube's colour (target), bottom the fit's, updated as it fits, the result left
 * up when done, and the match.  Each half an int app variable, 0xRRGGBBAA (the drawRect's own colour form). */
static u32 conv_byte(float v) { v = jf_clamp(v, 0, 1); return (u32)conv_round(v * 255.0f); }
static u32 conv_rgba(float r, float g, float b) { return conv_byte(r) << 24 | conv_byte(g) << 16 | conv_byte(b) << 8 | 0xFFu; }
static void conv_patch(struct lut4_state *s, struct conv_keep *K, u32 k, u32 v) {
    if (K->patch[k] == v) return;                                     /* only what changed: the GUI queue */
    K->patch[k] = v; K->chart_n++;
    fpui_set(s->ui, MV_PATCH0 + k, v);
}
static void conv_bar(struct lut4_state *s, u32 pct) {
    if (s->ui) fpui_set(s->ui, MV_BAR, ((pct > 100u ? 100u : pct) * 1638u + 128u) >> 8);   /* x 6.4: 0 .. 640 */
}
static void conv_match(struct lut4_state *s, struct conv_keep *K, u32 pct) {
    char *p = K->mtext[K->mi & 1u]; u32 n = conv_cat(p, string(s, 124));            /* "Match " */
    n += conv_num(p + n, pct); p[n++] = '%'; p[n] = 0;
    K->mi++;
    fpui_set_text(s->ui, MV_MATCH, p);
}
/* patch p's top: the cube's render of the 0 EV checker (C->chki, Q20) */
static u32 conv_target(const struct conv_work *C, u32 p) {
    const i32 *t = C->chki[CONV_CHK0 + p];
    return conv_rgba((float)t[0] / (float)Q, (float)t[1] / (float)Q, (float)t[2] / (float)Q);
}
/* UI thread, conv_start: the chart up, its targets (the cube's render of the 0 EV checker), fits not yet */
static void conv_chart_open(struct lut4_state *s, struct conv_work *C) {
    struct conv_keep *K = conv_mem(s);
    if (!s->ui || !K) return;
    K->chart_n = 0;
    for (u32 p = 0; p < CONV_PATCHES / 2u; p++) {
        K->patch[2u * p] = K->patch[2u * p + 1u] = 0;
        conv_patch(s, K, 2u * p, conv_target(C, p));
        conv_patch(s, K, 2u * p + 1u, CONV_EMPTY);
    }
    conv_bar(s, 0);
    K->mtext[0][0] = ' '; K->mtext[0][1] = 0; K->mi = 1;
    fpui_set_text(s->ui, MV_MATCH, K->mtext[0]);
    fpui_set(s->ui, MV_CHART, 1u); K->chart_on = 1;
}
/* the worker: the fit P (J->tone built for it) -- each half's colour, and the match over the 72.  Every one is
 * also kept in the file's chart block (C->jft + JFT_BYTES: +8 the match, +20 + 8p the fits; conv_seal the rest),
 * so the last -- the result the overlay leaves up -- is what the file carries (Bei 11-07: "查看色卡") */
static void conv_chart(struct lut4_state *s, struct conv_work *C, const float *P) {
    struct conv_keep *K = conv_mem(s);
    int post = s->ui && K;
    u8 *blk = C->jft + JFT_BYTES;
    float sum = 0;
    for (u32 j = 0; j < CONV_CHK; j++) {
        float rgb[3], lab[3];
        jf_chain_t(&C->J, P, C->chk + 3 * j, rgb, 0, 0, -1);
        jf_rgb_lab(rgb[0], rgb[1], rgb[2], lab);
        float a = lab[0] - C->chkw[3 * j], b = lab[1] - C->chkw[3 * j + 1], c = lab[2] - C->chkw[3 * j + 2];
        sum += jf_sqrt(a * a + b * b + c * c);
        if (j >= CONV_CHK0 && j < CONV_CHK0 + CONV_PATCHES / 2u) {
            u32 v = conv_rgba(rgb[0], rgb[1], rgb[2]), k = 2u * (j - CONV_CHK0) + 1u;
            conv_w32(blk + 16u + 4u * k, v);
            if (post) conv_patch(s, K, k, v);
        }
    }
    u32 pct = conv_pct((u32)conv_round(100.0f * sum / (float)CONV_CHK));
    conv_w32(blk + 8u, pct);
    if (post) conv_match(s, K, pct);
}
/* the user's next key or focus move after the finish (color_ui.c), or the manager opened again */
static void conv_chart_close(struct lut4_state *s) {
    struct conv_keep *K = conv_mem(s);
    if (!s->ui || !K || !K->chart_on || s->conv.state != CV_IDLE) return;
    K->chart_on = 0;
    fpui_set(s->ui, MV_CHART, 0);
}
/* the stages' share of the bar: 5 .. 24 the v1 identity start, 24 .. 43 lvb's, 43 .. 47 the refine, 47 .. 99 the untied
 * refine (JFIT v5; host native 11-11: v1 0.21 s a start, the refine 0.04 s, the untied 0.6 s), 100 the result */
#define CONV_SPAN_V1  19u
#define CONV_SPAN_REF 4u
#define CONV_SPAN_UNTIE 52u
/* it of n steps -> floor(span it / n), no divide instruction (n small) */
static u32 conv_part(u32 it, u32 n, u32 span) {
    u32 q = 0, a = it * span;
    if (!n || it >= n) return span;
    while (q < span && (q + 1u) * n <= a) q++;
    return q;
}
/* jf_fit (the v1 stage: J.n = CONV_N) ticks it = 0.. after jf_resid(J->P); jf2_lm (the refine: CONV_NX; the untied
 * refine: CONV_ND) it = 1.. after jf2_normal(z = J->P): either way J->tone is J->P's when the chart is drawn */
static void conv_tick(void *ctx, u32 it) {
    struct lut4_state *s = ctx;
    struct conv_work *C = conv_work(s);
    u32 v1 = C && C->J.n == CONV_N, un = C && C->J.n == CONV_ND;
    u32 pct = s->conv.base + conv_part(v1 ? it + 1u : it, C ? C->J.iters : 1u, v1 ? CONV_SPAN_V1 : un ? CONV_SPAN_UNTIE : CONV_SPAN_REF);
    if (pct < s->conv.pct) pct = s->conv.pct;                         /* never back */
    s->conv.pct = pct; s->conv.ticks++;
    conv_text(s, pct, 0);
    conv_bar(s, pct);
    if (C) conv_chart(s, C, C->J.P);
}

/* ---------------------------------------------------------------- quantise (jft.quantise) and pack (jft.pack) */
/* ygam_words: 17 Y outputs (12-bit at x = 0, 256 .. 4096) -> the 18 YGAM shadow words */
static void conv_ygam(const i32 *p, u32 *w) {
    i32 sl[16], knots[15];
    i32 y0 = p[0] > 0xfff ? 0xfff : p[0];
    sl[0] = conv_clampi(((p[1] - p[0]) * 0x80 + 0x80) / 256, 0, 0x3ff);    /* C's / truncates, as jft._cdiv */
    sl[1] = conv_clampi(((p[2] - p[0]) * 0x80 + 0x100) / 512, 0, 0x3ff);
    for (int i = 3; i < 17; i++) sl[i - 1] = conv_clampi(((p[i] - p[i - 2]) * 0x80 + 0x100) / 512, 0, 0x3ff);
    i32 prev = y0;
    for (int i = 0; i < 15; i++) { prev = conv_clampi(prev + sl[i] + sl[i + 1], 0, 0xfff); knots[i] = prev; }
    i32 last = conv_clampi(p[16] - (knots[14] + sl[15]) + 1, 0, 0x3ff);
    w[0] = 1u | (u32)y0 << 16;
    for (int i = 0; i < 16; i += 2) {
        i32 a = knots[i], b = i + 1 < 15 ? knots[i + 1] : 0x1000;
        w[1 + i / 2] = (u32)a | (u32)b << 16;
    }
    for (int i = 0; i < 16; i += 2) w[9 + i / 2] = (u32)sl[i] | (u32)sl[i + 1] << 16;
    w[17] = (u32)last;
}
static int conv_pack(struct lut4_state *s, struct conv_work *C, const float *P) {
    u8 *pay = C->jft + 64u;
    jf_build_tone(&C->J, P);                                          /* C->tone: the curves with the knots */
    i32 q[3][3], q1[3][3]; int16_t t[9], t1[9]; u32 shift = 0;   /* M2 (set 2) and M1 (set 1, JFIT v5): one shift */
    for (;; shift++) {
        float k = (float)(512u >> shift);
        for (u32 r = 0; r < 3u; r++) for (u32 c = 0; c < 3u; c++) {
            q[r][c] = conv_round(P[3 * r + c] * k); q1[r][c] = conv_round(P[9 + 3 * r + c] * k);
        }
        lvb_order((const i32 (*)[3])q, t); lvb_order((const i32 (*)[3])q1, t1);
        if (lvb_in_range(t) && lvb_in_range(t1)) break;
        if (shift == 2u) return CVE_RANGE;
    }
    for (u32 k = 0; k < 9u; k++) conv_w16(pay + JF_PAY_M1 + 2 * k, (u16)t1[k]);
    conv_w16(pay + JF_PAY_M1 + 18, 0);
    conv_w32(pay, shift);
    for (u32 k = 0; k < 9u; k++) conv_w16(pay + 4 + 2 * k, (u16)t[k]);
    conv_w16(pay + 22, 0);
    for (u32 c = 0; c < 3u; c++) for (u32 i = 0; i < LVB_N; i++) {
        u32 at = i << shift; if (at > LVB_N - 1u) at = LVB_N - 1u;
        conv_w16(pay + 24 + 2 * (c * LVB_N + i), (u32)conv_round((float)LVB_TMAX * C->tone[c * LVB_N + at]));
    }
    u8 *yc = pay + 24 + 6 * LVB_N, *cq = yc + 16, *yg = cq + 144;
    const float *post = P + 45;
    i32 yr = conv_round(post[0] * 4096.0f), yb = conv_round(post[1] * 4096.0f), ygg = 4096 - yr - yb;
    if (yr < 0 || yr > 4095 || yb < 0 || yb > 4095 || ygg < 0 || ygg > 4095) return CVE_YCMAT;
    i32 ycm[7] = {yr, ygg, yb, conv_clampi(conv_round(post[2] * 512.0f), -511, 511), conv_clampi(conv_round(post[3] * 512.0f), 0, 1023),
                  conv_clampi(conv_round(post[4] * 512.0f), 0, 1023), conv_clampi(conv_round(post[5] * 512.0f), -511, 511)};
    for (u32 k = 0; k < 7u; k++) conv_w16(yc + 2 * k, (u32)ycm[k]);
    conv_w16(yc + 14, 0);
    float dh[24];                                                     /* the hue shifts, clamped in order (11-10) */
    for (u32 a = 0; a < 24u; a++) dh[a] = post[6 + a];
    jf_hue_safe(dh);
    u32 hw[24];
    for (u32 a = 0; a < 24u; a++) {
        conv_w16(cq + 2 * a, (u32)conv_round(512.0f * post[54 + a]));                  /* L */
        conv_w16(cq + 48 + 2 * a, (u32)conv_round(683.0f * post[30 + a]));             /* S */
        i32 org = conv_round((float)a * 2730.6667f);                                    /* jft.ORG_H */
        hw[a] = (u32)(org + conv_round(dh[a] * 182.04445f)) & 0xFFFFu;                  /* H: 65536 / 360 */
        conv_w16(cq + 96 + 2 * a, hw[a]);
    }
    {   /* never ship a hue table the ISP takes the long way: each forward step >= JF_HUE_WORDS, one turn in all */
        u32 sum = 0;
        for (u32 a = 0; a < 24u; a++) {
            u32 st = (hw[a == 23u ? 0u : a + 1u] - hw[a]) & 0xFFFFu;
            if (st < JF_HUE_WORDS) return CVE_HUE;
            sum += st;
        }
        if (sum != 0x10000u) return CVE_HUE;
    }
    i32 yo[17]; float m = 0;
    for (u32 i = 0; i < 17u; i++) {
        float v = jf_clamp(post[78 + i], 0, 1);
        if (!i || v > m) m = v;
        yo[i] = conv_round(4095.0f * m);
    }
    u32 words[18]; conv_ygam(yo, words);
    for (u32 k = 0; k < 18u; k++) conv_w32(yg + 4 * k, words[k]);
    {   /* JFIT v6: the CKNEE block (jft.payload) -- on, then the 16-byte record's +4 .. +15: knee 9 bits (x 1024), slope 5
         * bits (x 19), as P orders them (+Cb, -Cb, +Cr, -Cr) into the record's halves A (10C0), C (10D0), B (10C8), D (10D8) */
        u8 *kb = pay + JF_PAY_KN; u32 on = jf_knee_on(P) ? 1u : 0u, kc[8];
        for (u32 i = 0; i < 8u; i++)
            kc[i] = on ? (u32)conv_clampi(conv_round(P[JF_NK + i] * (i & 1u ? 16.0f : 1024.0f)), 0, i & 1u ? 24 : 511) : 0u;
        conv_w32(kb, on); conv_w16(kb + 4, kc[0]); conv_w16(kb + 6, kc[2]); kb[8] = (u8)kc[1]; kb[9] = (u8)kc[3];
        conv_w16(kb + 10, kc[4]); conv_w16(kb + 12, kc[6]); kb[14] = (u8)kc[5]; kb[15] = (u8)kc[7];
    }
    /* the header (jft.pack) */
    u8 *h = C->jft;
    conv_w32(h, JFT_MAGIC); conv_w32(h + 4, 1u); conv_w32(h + 8, 64u); conv_w32(h + 12, JFT_BYTES);
    for (u32 k = 0; k < 8u; k++) h[16 + k] = s->conv.sha[k];
    conv_w32(h + 24, s->conv.color); conv_w32(h + 28, s->conv.gamma); conv_w32(h + 32, s->conv.amount);
    conv_w32(h + 36, s->conv.matrix); conv_w32(h + 40, JFT_JFIT);
    for (u32 k = 0; k < 3u; k++) conv_w32(h + 44 + 4 * k, s->conv.stats[k]);
    conv_w32(h + 56, lvb_fnv(pay, JFT_BYTES - 64u)); conv_w32(h + 60, 0);
    return CVE_NONE;
}
/* the chart block's head, the targets and its fnv, after the last conv_chart (its fits and match) and conv_pack */
static void conv_seal(struct conv_work *C) {
    u8 *blk = C->jft + JFT_BYTES;
    conv_w32(blk, JFC_MAGIC); conv_w32(blk + 4, JFC_BYTES);
    copy(blk + 12, C->jft + 56, 4u);                                  /* pairs it with this core */
    for (u32 p = 0; p < CONV_PATCHES / 2u; p++) conv_w32(blk + 16u + 8u * p, conv_target(C, p));
    conv_w32(blk + JFC_BYTES - 4u, lvb_fnv(blk, JFC_BYTES - 4u));
}

/* the ColorChecker at -1 / 0 / +1 EV: the chain (P) against the cube's target, dE76 mean / p95 / max x 100 */
static void conv_score_chk(struct lut4_state *s, struct conv_work *C, const float *P) {
    jf_build_tone(&C->J, P);
    float *d = C->dE, sum = 0;
    for (u32 j = 0; j < CONV_CHK; j++) {
        float lab[3]; jf_sample(&C->J, P, C->chk + 3 * j, lab, 0);
        float a = lab[0] - C->chkw[3 * j], b = lab[1] - C->chkw[3 * j + 1], c = lab[2] - C->chkw[3 * j + 2];
        float v = jf_sqrt(a * a + b * b + c * c);
        u32 k = j; while (k && d[k - 1] > v) { d[k] = d[k - 1]; k--; }   /* insertion: d stays sorted */
        d[k] = v; sum += v;
    }
    float mean = sum / (float)CONV_CHK;
    float p95 = d[67] + 0.45f * (d[68] - d[67]);                       /* np.percentile(95), 72 values: 67.45 */
    s->conv.stats[0] = (u32)conv_round(100.0f * mean); s->conv.stats[1] = (u32)conv_round(100.0f * p95);
    s->conv.stats[2] = (u32)conv_round(100.0f * d[CONV_CHK - 1u]);
}

/* ---------------------------------------------------------------- the worker's job */
/* the candidates in order -- best (refined), alt (the seed), alt2 (the other v1 start) -- the first that packs
 * (jft.choose): the score from it, its bytes in C->jft, it in C->best (swapped there with its cost) */
static void conv_swap(struct conv_work *C, float *o, u32 k) {
    for (u32 j = 0; j < JF_NP; j++) { float v = C->best[j]; C->best[j] = o[j]; o[j] = v; }
    float c = C->cost[0]; C->cost[0] = C->cost[k]; C->cost[k] = c;
}
static int conv_choose(struct lut4_state *s, struct conv_work *C) {
    int rc = CVE_FIT;
    for (u32 k = 0; k < 3u && rc; k++) {
        if (k) conv_swap(C, k == 1u ? C->alt : C->alt2, k);          /* k 2: best <-> alt2 (best is the seed then) */
        jf_hue_safe(C->best + 51);                                     /* the hue order (11-10): scored as packed */
        conv_score_chk(s, C, C->best);
        rc = conv_pack(s, C, C->best);                                 /* builds the tone for best */
    }
    return rc;
}
/* JFIT v5 (Bei 2026-11-11): from the packed v4 result (best, its bytes in C->jft), jf_fit_untied on the dense set
 * (CONV_ND); its result packed and kept when that packs and its packed tables cost less on the dense set than the v4
 * one's (jf_packed_cost: the training cost on the hardware's integers -- no validation set chooses); else the v4 one
 * again.  JFIT v6 (2026-11-11): the refine frees the CKNEE too, and its result is offered twice -- with its knee and
 * with the CKNEE off (the same other tables) -- so the knee is kept only when its packed tables cost less than both the
 * knee-less ones and the v4 one (jft.untie).  The score and bytes are the kept one's; C->tone best's (the chart after). */
static int conv_untie(struct lut4_state *s, struct conv_work *C) {
    struct jfit *J = &C->J;
    J->n = CONV_ND;
    double c0 = jf_packed_cost(J, C->jft + 64u, C->pw, C->tone);
    for (u32 k = 0; k < JF_NP; k++) { C->prod[k] = C->best[k]; J->P[k] = C->best[k]; }
    J->iters = s->conv.iters ? s->conv.iters : CONV_UNTIE_ITERS; J->evals = J->steps = 0;
    s->conv.base = 5u + 2u * CONV_SPAN_V1 + CONV_SPAN_REF;
    jf_fit_untied(J, C->amax, J->iters, 1);
    jf_hue_safe(J->P + 51);                                          /* scored as packed (conv_choose) */
    float kn[8];
    for (u32 k = 0; k < 8u; k++) kn[k] = J->P[JF_NK + k];
    int rk = conv_pack(s, C, J->P);                                  /* with its CKNEE */
    double ck = rk ? c0 : jf_packed_cost(J, C->jft + 64u, C->pw, C->tone);
    jf_knee_off(J->P);
    int rn = conv_pack(s, C, J->P);                                  /* the same tables, the CKNEE off */
    double cn = rn ? c0 : jf_packed_cost(J, C->jft + 64u, C->pw, C->tone);
    C->ucost[0] = (float)c0; C->ucost[1] = (float)cn; C->ucost[2] = (float)ck;
    C->knee = !rk && ck < c0 && (rn || ck < cn) ? 1u : 0u;
    C->untie = C->knee || (!rn && cn < c0) ? 1u : rk && rn ? 2u : 0u;
    if (C->knee) for (u32 k = 0; k < 8u; k++) J->P[JF_NK + k] = kn[k];
    if (C->untie == 1u) for (u32 k = 0; k < JF_NP; k++) C->best[k] = J->P[k];
    conv_score_chk(s, C, C->best);                                   /* the kept one (the v4 one packed before) */
    int rc = conv_pack(s, C, C->best);
    jf_build_tone(J, C->best);
    return rc;
}
static void conv_compute(struct lut4_state *s) {
    struct conv_work *C = conv_work(s);
    if (!C) { s->conv.err = CVE_MEMORY; s->conv.state = CV_FAIL; return; }
    struct jfit *J = &C->J;
    J->xs = C->xs; J->want = C->want; J->w = C->w; J->base_tone = C->bt;       /* the first CONV_N: lvb's + greys */
    J->tone = C->tone; J->A = C->A; J->res = C->res; J->res2 = C->res2; J->pert = C->u.pert; J->pre = C->pre;
    J->w_hue = 0.02f; J->w_gain = 2.0f; J->w_curve = 2.0f; J->w_mono = JF_W_MONO;   /* the hue-order hinge (jfit.c JF_HUE_FIT; 11-10) */
    J->tick = conv_tick; J->tick_ctx = s; J->spin = conv_spin;
    s->conv.pct = 0;
    for (u32 start = 0; start < 2u; start++) {                        /* jft.convert: v1, the identity, then lvb's */
        float *P = J->P;
        for (u32 k = 0; k < 9u; k++) { float v = start ? C->m0[k] : (k % 4u ? 0.0f : 1.0f); P[k] = v; P[9 + k] = v; }
        for (u32 k = 18; k < 45u; k++) P[k] = 0;
        jf_knee_off(P);                                               /* JFIT v6: no CKNEE until the untied refine */
        float *q = P + 45;                                            /* lut_batch_eval.POST_ID */
        q[0] = 0.299f; q[1] = 0.114f; q[2] = -86.0f / 512.0f; q[3] = 0.5f; q[4] = 0.5f; q[5] = -42.0f / 512.0f;
        for (u32 a = 0; a < 24u; a++) { q[6 + a] = 0; q[30 + a] = 1.0f; q[54 + a] = 1.0f; }
        for (u32 i = 0; i < 17u; i++) q[78 + i] = (float)i / 16.0f;
        J->n = CONV_N; J->iters = s->conv.iters ? s->conv.iters : CONV_ITERS; J->evals = J->steps = 0;
        s->conv.base = 5u + CONV_SPAN_V1 * start;
        jf_build_tone(J, P); conv_chart(s, C, P);                     /* this start's colours, before its first step */
        C->cost[1u + start] = jf_fit(J);                              /* the ordinary samples and weights alone (JFIT v1) */
        float *to = start ? C->alt2 : C->alt;
        for (u32 k = 0; k < JF_NP; k++) to[k] = J->P[k];
    }
    if (C->cost[2] == C->cost[2] && !(C->cost[1] <= C->cost[2])) {    /* the seed: the cheaper (a NaN last) in alt */
        for (u32 k = 0; k < JF_NP; k++) { float v = C->alt[k]; C->alt[k] = C->alt2[k]; C->alt2[k] = v; }
        float c = C->cost[1]; C->cost[1] = C->cost[2]; C->cost[2] = c;
    }
    for (u32 k = 0; k < JF_NP; k++) J->P[k] = C->alt[k];
    J->n = CONV_NX; J->iters = s->conv.iters ? s->conv.iters : CONV_DIRECT_ITERS; J->evals = J->steps = 0;   /* + the 144 HSV */
    s->conv.base = 5u + 2u * CONV_SPAN_V1;
    jf_build_tone(J, J->P); conv_chart(s, C, J->P);                   /* the seed's colours */
    C->cost[0] = jf_fit_direct(J, C->amax, J->iters);
    for (u32 k = 0; k < JF_NP; k++) C->best[k] = J->P[k];
    int rc = conv_choose(s, C);
    if (!rc) rc = conv_untie(s, C);                                   /* JFIT v5; the tone is C->best's: */
    conv_chart(s, C, C->best);                                        /* the result, left up (conv_chart_close) */
    if (!rc) conv_seal(C);                                            /* ... and kept in the file (conv_view) */
    conv_bar(s, 100u);
    s->conv.err = (u32)rc;
    __asm__ volatile("dmb" ::: "memory");             /* the work area's bytes before the state the UI thread reads */
    s->conv.state = rc ? CV_FAIL : CV_DONE;
    s->conv.pct = 100u;
    /* The worker's own post of LC_Key reaches the page but never our watch (camera 11-04: stuck at 86%).  The stock
     * way: an app-state message (format: "ProcessingComplete"); the page's appStateEvent writes LC_Key = CONV_DONE_KEY
     * itself, and that write is what the watch sees -> conv_finish on the UI thread. */
    if (s->ui) FW(GUI_APPSTATE, u32 (*)(void *, const char *))(FW(GUI_FUNCTION, void *(*)(void))(), string(s, CONV_EVENT));
}
static void conv_task(int stacd, void *exinf) {
    (void)stacd;
    struct lut4_state *s = exinf;
    for (;;) {
        FW(TK_SLP_TSK, int (*)(int))(-1);
        if (s->conv.state == CV_RUN) { s->conv.runs++; conv_compute(s); }
    }
}

/* ---------------------------------------------------------------- the UI thread */
static int conv_worker(struct lut4_state *s) {
    if (s->conv.tid > 0) return 1;
    u32 v = s->svc->cave_alloc(s->svc, 8u);                           /* ARM entry: ldr pc, [pc, #-4]; conv_task | 1 */
    if (!v) return 0;
    lvb_wr(v, 0xE51FF004u); lvb_wr(v + 4u, ((u32)(uintptr_t)&conv_task & ~1u) | 1u);
    s->svc->publish(s->svc);
    u32 desc[8] = {(u32)(uintptr_t)s, 0x41u, v, CONV_PRI, CONV_STACK, 0x4354554Cu, 0, 0};   /* "LUTC" */
    int id = FW(TK_CRE_TSK, int (*)(u32 *))(desc);
    if (id <= 0) { s->conv.err_task = (u32)id; return 0; }
    if (FW(TK_STA_TSK, int (*)(int, int))(id, 0)) { s->conv.err_task = 0x8000u; return 0; }
    s->conv.tid = id;
    return 1;
}
/* entry i's inputs, then the worker.  Borrowed here (borrow.c): the work area (kept until conv_finish), and
 * for the inputs lvb_fit's samples and the asset area (entry i's cube loaded into it) -- both returned
 * before this returns, whatever happens; on any failure the work area too. */
static int conv_inputs(struct lut4_state *s, struct conv_work *C, struct lvb_fitmem *F, u32 i) {
    struct lib_entry *e = &s->library->entries[i];
    u32 active = s->library->h.active;
    u32 k_flags = e->flags;
    e->flags |= 1u;                                                   /* library_load_index loads enabled cubes only: */
    int rc = library_load_index(s, i);                                /* On is what is being asked for */
    e->flags = k_flags; s->library->h.checksum = library_hash(s->library);
    if (rc != OK) return rc;
    s->color = e->color; s->gamma = e->gamma; s->amount = e->amount;
    s->library->h.active = i;
    rc = lvb_fit(s, F, &C->scratch);
    if (rc == OK) {
        const i32 *src = (const i32 *)((const u8 *)s->block + s->cfg->chk_off);
        for (u32 j = 0; j < CONV_CHK * 3u; j++) { C->chki[j / 3u][j % 3u] = src[j]; C->chk[j] = (float)src[j] / (float)Q; }
        rc = lvb_render(s, C->chki, CONV_CHK);
        for (u32 j = 0; rc == OK && j < CONV_GREY * 3u; j++)
            C->gx[j / 3u][j % 3u] = C->gw[j / 3u][j % 3u] = C->gy[j / 3u][j % 3u] = src[CONV_CHK * 3u + j];
        if (rc == OK) {                                               /* lvb_fit's two renders: the weight at amount 0 */
            u32 am = s->amount; s->amount = 0;
            rc = lvb_render(s, C->gw, CONV_GREY);
            s->amount = am;
        }
        if (rc == OK) rc = lvb_render(s, C->gy, CONV_GREY);
        if (rc == OK) {                                               /* the 144 HSV samples: as the fit sees them, */
            jf_hsv_samples(C->xs + 3u * CONV_N);                      /* and Q20 for the cube's render */
            for (u32 j = 0; j < JF_NHSV * 3u; j++) C->hx[j / 3u][j % 3u] = conv_round(C->xs[3u * CONV_N + j] * (float)Q);
            rc = lvb_render(s, C->hx, JF_NHSV);
        }
        if (rc == OK) {                                               /* JFIT v5: the dense extras (Q20-exact floats) -- */
            float *xd = C->xs + 3u * CONV_NX;                         /* the stock look of the weighted ones, then the */
            jf_dense_samples(xd);                                     /* cube's render of all: their weights and targets */
            for (u32 j = 0; j < CONV_XW * 3u; j++) C->u.dx[j / 3u][j % 3u] = conv_round(xd[j] * (float)Q);
            u32 am = s->amount; s->amount = 0;
            rc = lvb_render(s, C->u.dx, CONV_XW);
            s->amount = am;
            for (u32 j = 0; rc == OK && j < JF_NDX; j++) C->w[CONV_NX + j] = j < CONV_XW ? jf_sqrt((float)lvb_weight(C->u.dx[j]) / 65536.0f) : 1.0f;
            for (u32 j = 0; rc == OK && j < JF_NDX * 3u; j++) C->u.dx[j / 3u][j % 3u] = conv_round(xd[j] * (float)Q);
            if (rc == OK) rc = lvb_render(s, C->u.dx, JF_NDX);
            for (u32 j = 0; rc == OK && j < JF_NDX; j++)
                jf_rgb_lab((float)C->u.dx[j][0] / (float)Q, (float)C->u.dx[j][1] / (float)Q, (float)C->u.dx[j][2] / (float)Q, C->want + 3 * (CONV_NX + j));
        }
    }
    s->library->h.active = active;
    if (rc != OK) return rc;
    for (u32 j = 0; j < CONV_N; j++) {
        const i32 *x = j < LVB_S ? F->x[j] : C->gx[j - LVB_S], *y = j < LVB_S ? F->y[j] : C->gy[j - LVB_S];
        for (u32 c = 0; c < 3u; c++) C->xs[3 * j + c] = (float)x[c] / (float)Q;
        jf_rgb_lab((float)y[0] / (float)Q, (float)y[1] / (float)Q, (float)y[2] / (float)Q, C->want + 3 * j);
        C->w[j] = jf_sqrt((float)(j < LVB_S ? F->w[j] : lvb_weight(C->gw[j - LVB_S])) / 65536.0f);
    }
    for (u32 j = 0; j < JF_NHSV; j++) {
        jf_rgb_lab((float)C->hx[j][0] / (float)Q, (float)C->hx[j][1] / (float)Q, (float)C->hx[j][2] / (float)Q, C->want + 3 * (CONV_N + j));
        C->w[CONV_N + j] = 1.0f;
    }
    for (u32 j = 0; j < CONV_CHK; j++)
        jf_rgb_lab((float)C->chki[j][0] / (float)Q, (float)C->chki[j][1] / (float)Q, (float)C->chki[j][2] / (float)Q, C->chkw + 3 * j);
    for (u32 c = 0; c < 3u; c++) for (u32 k = 0; k < LVB_N; k++) C->bt[c * LVB_N + k] = jf_clamp((float)F->curve[c][k] / (float)Q, 0, 1);
    {   /* lvb's matrix, table order -> rows (lv_fit.table_order), x 2^shift / 512 */
        const i32 *t = C->scratch.mat; float k = (float)(1u << C->scratch.shift) / 512.0f;
        float m[9] = {(float)t[0], (float)t[1], (float)t[2], (float)t[4], (float)t[3], (float)t[5], (float)t[7], (float)t[8], (float)t[6]};
        for (u32 j = 0; j < 9u; j++) C->m0[j] = m[j] * k;
    }
    return OK;
}
static int conv_start(struct lut4_state *s, u32 i) {
    struct conv_keep *K = conv_mem(s); struct lvb_mem *M = lvb_mem(s);
    if (!K || !M || !s->library || i >= s->library->h.count || s->conv.state != CV_IDLE || s->b_conv.raw) return CVE_STATE;
    if (!conv_worker(s)) return CVE_TASK;
    struct lib_entry *e = &s->library->entries[i];
    u32 k_color = s->color, k_gamma = s->gamma, k_amount = s->amount;
    int k_status = s->file_status;
    u8 *A = lut_borrow(s, &s->b_asset, s->cfg->asset_cap);          /* the largest first */
    struct conv_work *C = A ? (struct conv_work *)(void *)lut_borrow(s, &s->b_conv, sizeof(struct conv_work)) : 0;
    struct lvb_fitmem *F = C ? (struct lvb_fitmem *)(void *)lut_borrow(s, &s->b_fit, sizeof(struct lvb_fitmem)) : 0;
    int rc = F ? conv_inputs(s, C, F, i) : NO_MEMORY;
    lut_return(s, &s->b_asset); lut_return(s, &s->b_fit);
    s->asset = 0; s->file_status = k_status;
    s->color = k_color; s->gamma = k_gamma; s->amount = k_amount;
    if (rc != OK) {
        lut_return(s, &s->b_conv);
        s->conv.err = rc == NO_MEMORY || rc == RECORD_BUSY ? CVE_MEMORY : CVE_FIT;
        return (int)s->conv.err;
    }
    for (u32 k = 0; k < 32u; k++) s->conv.sha[k] = e->sha[k];   /* the whole identity: lvb_jpath names CAM1 ones by size + name */
    s->conv.color = e->color; s->conv.gamma = e->gamma; s->conv.amount = e->amount; s->conv.matrix = e->matrix;
    s->conv.index = i; s->conv.pct = 0; s->conv.err = 0; s->conv.base = 5u;
    s->conv.state = CV_RUN;
    conv_text(s, 0, 0);
    conv_chart_open(s, conv_work(s));
    conv_busy(s, 1);
    FW(TK_WUP_TSK, int (*)(int))(s->conv.tid);
    return CVE_NONE;
}
/* the file: the folder (may exist), mode 7 (not truncated: an old one is the same size, or a v2 file without the
 * chart block, shorter -- overwritten whole either way), read back */
static int conv_write(struct lut4_state *s, struct conv_keep *C, const struct conv_work *W) {
    u32 obj[4] = {0, 0, 0, 0};
    lvb_jpath(C->path, s->conv.sha, 1);
    FW(FS_DIR_CTOR, void (*)(void *, u32))(obj, FW(FS_DISK, u32 (*)(void))());
    FW(FS_DIR_MAKE, u32 (*)(void *, const char *, u32))(obj, C->path, 0);
    FW(FS_DIR_DTOR, void (*)(void *, u32))(obj, 2);
    lvb_jpath(C->path, s->conv.sha, 0);
    u8 *io = s->svc->uncached(s->svc, (u8 *)s->block + s->cfg->io_off), *buf = io + 4096;
    u32 ok = 0;
    FW(0xC0365E90u, void (*)(void *, u32))(io, 1);
    if (FW(0xC0365FB0u, u32 (*)(void *, const char *, u32))(io, C->path, 7)) {
        u32 pos = 0;
        while (pos < JFT_FILE) {
            u32 take = JFT_FILE - pos; if (take > 4096u) take = 4096u;
            copy(buf, W->jft + pos, take);
            if (!FW(0xC03660E8u, u32 (*)(void *, const void *, u32))(io, buf, take)) break;
            pos += take;
        }
        FW(0xC0366020u, void (*)(void *))(io);
        ok = pos == JFT_FILE;
    }
    FW(0xC0365ED0u, void (*)(void *, u32))(io, 2);
    if (!ok) return CVE_WRITE;
    u8 *jb = lvb_jbuf(s);                                           /* read back: what lvb_refresh will read (borrowed) */
    ok = jb && s->svc->file_read(s->svc, C->path, jb, JFT_FILE) == (int)JFT_FILE && library_same(jb, W->jft, JFT_FILE);
    lvb_jbuf_done(s);
    return ok ? CVE_NONE : CVE_WRITE;
}
static void mv_hint(struct lut4_state *s);
static void manager_refresh(struct lut4_state *s);
/* DONE / FAIL -> the file, the cube on, the list; idle again.  1 = something finished. */
static int conv_finish(struct lut4_state *s) {
    struct conv_keep *C = conv_mem(s);
    if (!C || (s->conv.state != CV_DONE && s->conv.state != CV_FAIL)) return 0;
    u32 i = s->conv.index;
    struct conv_work *W = conv_work(s);
    int rc = s->conv.state == CV_DONE ? (W ? conv_write(s, C, W) : CVE_MEMORY) : (int)s->conv.err;
    lut_return(s, &s->b_conv);                                       /* done with it, whatever the result */
    conv_forget(s, i);
    u32 full = 0;
    if (!rc && s->library && i < s->library->h.count) {
        if (mv_used(s) >= lut_room(s)) full = 1;                      /* converted, but no COLOR row free (Bei 11-10): stays Off */
        else {
            int en = library_enabled(s, i, 1);
            if (en != OK) rc = CVE_ENABLE; else cols_sync(s);
        }
    }
    s->conv.last = (u32)rc; s->conv.done++;
    s->conv.state = CV_IDLE;
    conv_busy(s, 0);
    s->ui_result = rc ? R_CONVFAIL : full ? R_FULL : R_CONVERTED;
    if (!rc && !full) conv_text(s, conv_pct(s->conv.stats[0]), 1);
    manager_refresh(s);
    return 1;
}

/* ---------------------------------------------------------------- the manager's words */
static int conv_running(struct lut4_state *s) { return s->conv.state != CV_IDLE; }
static const char *conv_hint(struct lut4_state *s) {
    struct conv_keep *C = conv_mem(s);
    if (!C) return 0;
    if (s->conv.state != CV_IDLE || s->ui_result == R_CONV || s->ui_result == R_CONVERTED) return C->text;
    if (s->ui_result == R_CONVFAIL) return string(s, 120);           /* "Convert failed" */
    return 0;
}
/* entry i in manager slot k: its match % + 1 (the slot's "94%" written), 0 = not converted */
static u32 conv_row(struct lut4_state *s, u32 i, u32 slot) {
    struct conv_keep *C = conv_mem(s);
    if (!C) return 1u;
    u32 score = conv_score(s, i);
    if (score > 1u && slot < 6u) { char *p = C->vtext[slot]; u32 n = conv_num(p, score - 1u); p[n++] = '%'; p[n] = 0; }
    return score;
}
static const char *conv_vtext(struct lut4_state *s, u32 slot) { return conv_mem(s)->vtext[slot]; }
/* the settings (AEL) page's title: the cube's name, and its match when its file is there (user 11-05:
 * "還原度在AEL中也要顯示"); the name alone otherwise (not converted, or the key changed) */
static const char *conv_title(struct lut4_state *s, u32 i, const char *name) {
    struct conv_keep *C = conv_mem(s);
    u32 score = C ? conv_score(s, i) : 0;
    if (score <= 1u || !name) return name;
    char *p = C->title; u32 n = 0;
    while (name[n] && n < 30u) { p[n] = name[n]; n++; }
    p[n++] = ' '; p[n++] = ' ';
    n += conv_num(p + n, score - 1u); n += conv_cat(p + n, string(s, 119));   /* "% match" */
    p[n] = 0;
    return p;
}

/* ---------------------------------------------------------------- the settings page's "Color chart" row
 * Bei 11-07: the chart the conversion left, again, from the file's block alone -- no cube loaded, nothing borrowed
 * (the file into a borrowed buffer, back before this returns: lvb_jbuf), never while recording.  The same variables as the manager's overlay
 * (LC_Chart, LC_Match, LC_P00..47; the settings page has its own copy of the chart, settings_y51.chart_overlay);
 * conv_chart_close takes it down.  CVV_SHOWN, or why not: a file without the block (a v2 one made before
 * 11-07) or none -> the row asks for a conversion again. */
enum { CVV_SHOWN, CVV_BUSY, CVV_READ, CVV_HEAD, CVV_BLOCK, CVV_STATE };
static int conv_chart_up(struct lut4_state *s) { struct conv_keep *K = conv_mem(s); return K && K->chart_on; }
static u32 conv_view(struct lut4_state *s, u32 i) {
    struct conv_keep *K = conv_mem(s); struct lvb_mem *M = lvb_mem(s);
    if (!K) return CVV_STATE;
    u32 rc = CVV_STATE;
    if (!M || !s->ui || !s->library || i >= s->library->h.count || i >= LIB_MAX || s->conv.state != CV_IDLE) rc = CVV_STATE;
    else if (library_busy()) rc = CVV_BUSY;                           /* recording: not even the file */
    else {
        const struct lib_entry *e = &s->library->entries[i];
        lvb_jpath(K->path, e->sha, 0);
        u8 *jb = lvb_jbuf(s);
        int got = jb ? s->svc->file_read(s->svc, K->path, jb, JFT_FILE) : -1;
        const u8 *b = jb, *c = b + JFT_BYTES;
        u32 k = 0;
        if (got == (int)JFT_FILE) while (k < 8u && b[16 + k] == e->sha[k]) k++;
        if (!jb) rc = CVV_BUSY;
        else if (got != (int)JFT_FILE) rc = got == (int)JFT_BYTES ? CVV_BLOCK : CVV_READ;
        else if (lvb_u32(b) != JFT_MAGIC || lvb_u32(b + 4) != 1u || lvb_u32(b + 8) != 64u || lvb_u32(b + 12) != JFT_BYTES ||
                 k != 8u || lvb_u32(b + 24) != e->color || lvb_u32(b + 28) != e->gamma || lvb_u32(b + 36) != e->matrix ||
                 lvb_u32(b + 40) != JFT_JFIT) rc = CVV_HEAD;
        else if (lvb_u32(c) != JFC_MAGIC || lvb_u32(c + 4) != JFC_BYTES || lvb_u32(c + 8) > 100u ||
                 lvb_u32(c + 12) != lvb_u32(b + 56) || lvb_fnv(c, JFC_BYTES - 4u) != lvb_u32(c + JFC_BYTES - 4u)) rc = CVV_BLOCK;
        else {
            for (u32 h = 0; h < CONV_PATCHES; h++) conv_patch(s, K, h, lvb_u32(c + 16u + 4u * h));
            conv_match(s, K, lvb_u32(c + 8));
            fpui_set(s->ui, MV_CHART, 1u); K->chart_on = 1;
            rc = CVV_SHOWN;
        }
        lvb_jbuf_done(s);
    }
    K->view_rc = rc; K->view_n++;
    return rc;
}

/* tests (test_conv_native): the file's bytes again from conv_work.best, as the worker packs them
 * (between the worker's end and conv_finish: the work area is returned there) */
USED int lut4_conv_repack(struct lut4_state *s) {
    struct conv_work *C = conv_work(s);
    if (!C) return CVE_STATE;
    conv_score_chk(s, C, C->best);
    return conv_pack(s, C, C->best);
}
/* tests: the choice again on C->best / C->alt / C->cost as the test left them (conv_choose) */
USED int lut4_conv_choose(struct lut4_state *s) {
    struct conv_work *C = conv_work(s);
    return C ? conv_choose(s, C) : CVE_STATE;
}
