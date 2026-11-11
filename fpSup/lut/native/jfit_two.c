/* jfit_two.c -- 兩輪聯合擬合(第一輪 A -> 8-bit YCbCr 寫回 -> 第二輪 B),相機用 float 版。
 *
 * Bei 2026-11-07 定:每次轉檔做兩套表。(1) 單輪 F = jfit.c jf_fit_direct(> 60 fps、UHD 用);(2) 本檔:不受約束的
 * 兩輪聯合解 A -> B(<= 60 fps 用;A 單獨可以是不能看的中間態)。
 *
 * 參考實作(逐項照抄,不改設計):
 *   projects/lut-sup/validation/20261107-twopass-constrained-01/fit_constrained.py  kind = hinge、lam = 0、start = direct
 *   (= 不受約束;它沿用 20261106-isp-compositions-01/fit_visits.py 的解析導數核心、正向模型、JFT 封裝、三段 LM)。
 *   fit_visits.py 本身的「二遍 1.492 / 1.469 / 1.433」是 initial_visits.npz 的封存起點直接打分(它從 n = 3 才開始擬合),
 *   產生那份起點的程式沒有留下,相機上也沒有那份起點:能從 cube 從頭算的只有 fit_constrained 的 direct 起點這條路。
 *   色相旋轉起點(0 / +28 / -34)只在 fit_visits 的 n >= 3 遍使用,二遍沒有,這裡也沒有。
 *
 * 模型(fit_visits.stage / forward):
 *   第一輪:jf2_sample 同一條鏈(M -> 三條 tone -> YCMAT -> CEQ -> YGAM),輸出 Y / Cb / Cr,經 601 反矩陣成 RGB,
 *           導數在 RGB 落在 (0, 1) 外時歸零,再 clip。YGAM 先 running max、再用 H(內部列 .25 / .5 / .25)平滑才進核心;
 *           封裝(jft.quantise)用的是未平滑的原值 -- 參考就是這樣,照做。
 *   寫回:  只在第三段(hard)把每輪輸出經 709 YCbCr 8-bit 取整(np.rint)再轉回 RGB;導數直通(straight-through:
 *           取整當恆等),第二輪的局部導數在取整後的點上求。前兩段完全連續(不取整、不轉 YCbCr)。
 *   第二輪:記憶體入口,沒有 RGBLMAT(矩陣固定恆等),tone 白點 1918(擬合時),其餘同第一輪。
 *   殘差:  (Lab - want) * w,w = wt / sqrt(max(1, |dE| / 2))(每次線性化重算,試步沿用);
 *           + 0.22 x(CEQ 鄰差 0.02 / 2 / 2、曲線編修 2.0)兩輪各一份。
 *   LM:    阻尼 0.02 起,Marquardt 對角(未加尾項前的 JtJ 對角,下限 1e-8),成功 x0.45、失敗 x4,一次最多 10 試,
 *           10 試都失敗該段結束;卡在邊界且梯度往外的參數凍結。三段:750 + 250 樣本 55 次、1400 + 466 樣本 65 次、
 *           1400 + 466 樣本 18 次(hard)。每 5 次(和該段最後一次)把目前解封裝、用整數表重播選解集
 *           (2100 + 700 樣本),損失 = 平均 dE76 + 0.1 x P95,比目前最佳低才收;下一段從最佳開始。
 *   封裝:  第一輪 = jft.quantise;第二輪先把編修烘進恆等 tone、重取樣到白點 2040、表值改 8160 正規化(偶數,<= 8188)
 *           (fit_visits.packets)。重播 = replay_isp.encoded_stage(白點 1918 / 2040、8190 / 8160)。
 *
 * 相機條件同 jfit.c:float(VFP)、沒有 libm、沒有 .rodata(常數寫在程式碼裡)、沒有 double 常數(會逼出 8 對齊的
 * literal pool)、沒有整數除法 helper(只除常數)、工作區全由呼叫端給(jt_work_bytes)。進度:tick(每次收步)/ spin(每 32 樣本)。
 * 本檔要在 jfit.c 之後 include(跟 conv.c 一樣);jfit.c 的 jf2_tone / jf2_slot / jf_* 直接用,核心 jf2_sample 只能輸出 Lab,
 * 所以這裡有一份只到 Y / Cb / Cr 為止的複本 jt_kernel(其餘逐行相同,改了要兩邊一起改;test_jfit_two.py 會比對)。
 * 主機對照:fpSup/lut/test_jfit_two.py(native/host/jfit_two_host.c)。 */
#ifndef JFIT_TWO_C
#define JFIT_TWO_C
#ifndef JFIT_C
#error "include jfit.c first"
#endif

#define JT_NA     131                    /* 第一輪自由參數:M2(0..8)+ 18..139 */
#define JT_NB     122                    /* 第二輪:18..139 */
#define JT_NZ     253
#define JT_LMAX   80                     /* 一個樣本碰得到的欄:A <= 37、B <= 28 */
#define JT_PAYLOAD 12544u                /* jft.PAYLOAD */
#define JT_BIG    3.0e38f

struct jt_set { uint32_t n; const float *xs, *want, *wt; };   /* 相機 RGB、目標 Lab、基本權重(jt_weight) */

/* 一輪的硬體值(jft.quantise 的欄位)+ 重播用的解碼值 */
struct jt_hw {
    uint32_t shift;
    int16_t m2[9];                       /* 表內順序 */
    int16_t q[9];                        /* 列順序(重播) */
    int16_t ycmat[7];
    uint16_t ceq[72];                    /* L、S、H 三個平面 */
    uint32_t ygam[18];
    float post[95];                      /* replay_isp.encoded_stage 的 post */
    uint16_t tone[3 * JF_NTONE];
};

struct jtwo {
    /* 輸入 */
    const float *base_a;                 /* 3 x 2048,第一輪的中性曲線 0..1(jf_fit_direct 的 base_tone) */
    float PA[JF_NP], PB[JF_NP];          /* 起點進(PB = jt_identity),解出 */
    struct jt_set set[3];                /* 三段的訓練樣本(jt_draw 750 / 1400 / 1400) */
    uint32_t iters[3], hard[3];          /* 55 / 65 / 18;0 / 0 / 1 */
    struct jt_set sel;                   /* 選解集(jt_draw 2100;wt 不用) */
    float w_hue, w_gain, w_curve;        /* 0.02、2、2 */
    float w_tail, p95w, damp0, dfloor;   /* 0.22、0.1、0.02、1e-8(資料欄,不是 double 常數) */
    void *work;                          /* jt_work_bytes(max set n, sel n),8 對齊 */
    /* 輸出 */
    float start_cost, sel_cost;          /* 起點 / 最佳的選解損失 */
    uint32_t steps, evals, gevals, checks;
    struct jt_hw *hw;                    /* -> 工作區,[0] = A、[1] = B(最佳解的封裝) */
    int err;                             /* 0;1 最佳解封裝失敗 */
    /* 進度(0 = 無) */
    void (*tick)(void *ctx, uint32_t it);
    void (*spin)(void *ctx);
    void *ctx;
    /* 私有(jt_carve 填) */
    double *A, *g, *dsave, *gsave, *diag;
    float *base_b, *qtone, *w, *de, *z, *best, *zn;
    uint8_t *frz;
    struct jfit Jk[2];
    struct jfit2 Kk[2];
    float Ps[2][JF_NP];                  /* 平滑後(核心用) */
    int act[2][17];                      /* YGAM running max 的來源索引 */
    float Pu[2][JF_NP];                  /* 目前 z 展開的兩輪參數 */
};

static uint32_t jt_al(uint32_t v) { return (v + 7u) & ~7u; }
static uint32_t jt_work_bytes(uint32_t nmax, uint32_t nsel) {
    uint32_t b = 8u * (JT_NZ * JT_NZ + 4u * JT_NZ);
    b += jt_al(4u * 14u * JF_NTONE);                     /* tone x 2、base_b(各 3 x 2048)、qtone(5 x 2048) */
    b += jt_al(2u * 2u * 3u * JF_NTONE);                 /* amax x 2 */
    b += jt_al(4u * nmax) + jt_al(4u * nsel) + jt_al(4u * 3u * JT_NZ) + jt_al(JT_NZ);
    b += 2u * jt_al((uint32_t)sizeof(struct jt_hw));
    return b;
}
static void jt_carve(struct jtwo *T, uint32_t nmax, uint32_t nsel) {
    uint8_t *p = (uint8_t *)T->work;
    T->A = (double *)(void *)p; p += 8u * JT_NZ * JT_NZ;
    T->g = (double *)(void *)p; p += 8u * JT_NZ;
    T->dsave = (double *)(void *)p; p += 8u * JT_NZ;
    T->gsave = (double *)(void *)p; p += 8u * JT_NZ;
    T->diag = (double *)(void *)p; p += 8u * JT_NZ;
    float *f = (float *)(void *)p;
    T->Jk[0].tone = f; T->Jk[1].tone = f + 3 * JF_NTONE; T->base_b = f + 6 * JF_NTONE; T->qtone = f + 9 * JF_NTONE;
    p += jt_al(4u * 14u * JF_NTONE);
    T->Kk[0].amax = (int16_t *)(void *)p; T->Kk[1].amax = (int16_t *)(void *)p + 3 * JF_NTONE;
    p += jt_al(2u * 2u * 3u * JF_NTONE);
    T->w = (float *)(void *)p; p += jt_al(4u * nmax);
    T->de = (float *)(void *)p; p += jt_al(4u * nsel);
    T->z = (float *)(void *)p; T->best = T->z + JT_NZ; T->zn = T->z + 2 * JT_NZ; p += jt_al(4u * 3u * JT_NZ);
    T->frz = p; p += jt_al(JT_NZ);
    T->hw = (struct jt_hw *)(void *)p;
    for (int k = 0; k < 2; k++) { T->Kk[k].J = &T->Jk[k]; T->Jk[k].w_hue = T->w_hue; T->Jk[k].w_gain = T->w_gain; T->Jk[k].w_curve = T->w_curve; T->Jk[k].w_mono = 0; }   /* 11-10 hue hinge: not in this archived route */
    T->Jk[0].base_tone = T->base_a; T->Jk[1].base_tone = T->base_b;
    for (int i = 0; i < 3 * JF_NTONE; i++) {               /* fit_visits.IDENTITY_TONE = clip(i / 1918, 0, 1) */
        float v = (float)(i % JF_NTONE) / JF_WHITE;
        T->base_b[i] = v > 1 ? 1 : v;
    }
}

/* fit_visits.IDENTITY:恆等矩陣兩組、無編修、lut_batch_eval.POST_ID */
static void jt_identity(float *P) {
    for (int k = 0; k < 18; k++) P[k] = k % 9 % 4 ? 0.0f : 1.0f;
    for (int k = 18; k < 45; k++) P[k] = 0;
    float *q = P + 45;
    q[0] = 0.299f; q[1] = 0.114f; q[2] = -86.0f / 512.0f; q[3] = 0.5f; q[4] = 0.5f; q[5] = -42.0f / 512.0f;
    for (int a = 0; a < 24; a++) { q[6 + a] = 0; q[30 + a] = 1.0f; q[54 + a] = 1.0f; }
    for (int i = 0; i < 17; i++) q[78 + i] = (float)i / 16.0f;
    jf_knee_off(P);                                      /* JFIT v6 的 CKNEE:這裡不用 */
}
static void jt_defaults(struct jtwo *T) {
    T->w_hue = 0.02f; T->w_gain = 2.0f; T->w_curve = 2.0f;
    T->w_tail = 0.22f; T->p95w = 0.1f; T->damp0 = 0.02f; T->dfloor = 1e-8f;
    T->iters[0] = 55; T->iters[1] = 65; T->iters[2] = 18;
    T->hard[0] = 0; T->hard[1] = 0; T->hard[2] = 1;
}

/* ---------------------------------------------------------------- z <-> 兩輪參數 */
static int jt_gid(int c) { return c < 9 ? c : c < JT_NA ? c + 9 : c - JT_NA + 18; }   /* z 欄 -> 140 位置 */
static int jt_pass(int c) { return c >= JT_NA; }
/* fit_visits.unpack_vector 的 YCMAT 亮度和:> 0.9996 縮、< 0.0004 補(用的是原本的和) */
static void jt_ynorm(float *y) {
    float t = y[0] + y[1];
    if (t > 0.9996f) { y[0] *= 0.9996f / t; y[1] *= 0.9996f / t; }
    if (t < 0.0004f) { y[0] += (0.0004f - t) * 0.5f; y[1] += (0.0004f - t) * 0.5f; }
}
static void jt_normalise(float *z) { jt_ynorm(z + 36); jt_ynorm(z + JT_NA + 27); }   /* 45 - 9;131 + 45 - 18 */
static void jt_vector(const float *PA, const float *PB, float *z) {
    for (int c = 0; c < JT_NZ; c++) z[c] = jt_pass(c) ? PB[jt_gid(c)] : PA[jt_gid(c)];
}
static void jt_unpack(const float *z, float *PA, float *PB) {
    jt_identity(PA); jt_identity(PB);
    for (int c = 0; c < JT_NZ; c++) (jt_pass(c) ? PB : PA)[jt_gid(c)] = z[c];
    for (int k = 0; k < 9; k++) PA[9 + k] = PA[k];
}
/* fit_visits.stage:YGAM running max(來源索引 act)、再 H 平滑 */
static void jt_smooth(const float *P, float *Ps, int *act) {
    float m[17]; int a = 0;
    for (int i = 0; i < 17; i++) {
        float v = P[123 + i];
        if (!i || v >= m[i - 1]) { m[i] = v; a = i; } else m[i] = m[i - 1];
        act[i] = a;
    }
    for (int k = 0; k < JF_NP; k++) Ps[k] = P[k];
    Ps[123] = m[0]; Ps[139] = m[16];
    for (int i = 1; i < 16; i++) Ps[123 + i] = 0.25f * m[i - 1] + 0.5f * m[i] + 0.25f * m[i + 1];
}
static void jt_prepare(struct jtwo *T, const float *z) {
    jt_unpack(z, T->Pu[0], T->Pu[1]);
    for (int p = 0; p < 2; p++) { jt_smooth(T->Pu[p], T->Ps[p], T->act[p]); jf2_tone(&T->Kk[p], T->Ps[p]); }
}

/* ---------------------------------------------------------------- 核心:jf2_sample 到 Y / Cb / Cr 為止(fit_visits.load_stage) */
static void jt_kernel(const struct jfit2 *K, const float *P, const float *c, float *ycc, float (*D)[JF2_LMAX], int *gid, int *m) {
    const struct jfit *J = K->J;
    float t[3], dt[3][JF2_LMAX];
    int nm = 0;
    if (D) for (int i = 0; i < 9; i++) gid[nm++] = i;
    for (int k = 0; k < 3; k++) {
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
    float cb = q[2] * rg + q[3] * bg, cr = q[4] * rg + q[5] * bg;
    float th = jf_atan2deg(cr, cb), ch = jf_sqrt(cb * cb + cr * cr);
    float tt = th / 15.0f; int a0 = (int)tt; if (a0 > 23) a0 = 23; float fa = tt - (float)a0; int a1 = a0 == 23 ? 0 : a0 + 1;
    const float *dh = q + 6, *gs = q + 30, *gl = q + 54;
    float ddh = jf_hue_dd(dh, a0, a1);                      /* 11-10: the ISP's forward mod 360, as jfit.c */
    float hs = dh[a0] + ddh * fa, gsv = gs[a0] + (gs[a1] - gs[a0]) * fa, ls = gl[a0] + (gl[a1] - gl[a0]) * fa;
    float c2 = ch * gsv, h2 = th + hs, y2 = y + (ls - 1) * ch;
    float nodes[17]; int nam[17];
    { float mx = q[78]; int am = 0; for (int i = 0; i < 17; i++) { if (!i || q[78 + i] >= mx) { mx = q[78 + i]; am = i; } nodes[i] = mx; nam[i] = am; } }
    float ug = y2 * 16.0f, ugc = jf_clamp(ug, 0, 16);
    int g0 = (int)ugc; if (g0 > 15) g0 = 15; float fg = ugc - (float)g0;
    float Y = nodes[g0] + (nodes[g0 + 1] - nodes[g0]) * fg;
    float sn, cs; jf_sincos_deg(h2, &sn, &cs);
    float cb2 = c2 * cs, cr2 = c2 * sn;
    ycc[0] = Y; ycc[1] = cb2; ycc[2] = cr2;
    if (!D) return;
    int sy[6]; for (int i = 0; i < 6; i++) sy[i] = jf2_slot(gid, &nm, 45 + i);
    int sq[3][2]; for (int p = 0; p < 3; p++) { sq[p][0] = jf2_slot(gid, &nm, 51 + 24 * p + a0); sq[p][1] = jf2_slot(gid, &nm, 51 + 24 * p + a1); }
    int sg0 = jf2_slot(gid, &nm, 123 + nam[g0]), sg1 = jf2_slot(gid, &nm, 123 + nam[g0 + 1]);
    *m = nm;
    float drg[JF2_LMAX], dbg[JF2_LMAX], dy[JF2_LMAX], dcb[JF2_LMAX], dcr[JF2_LMAX];
    for (int i = 0; i < nm; i++) {
        drg[i] = dt[0][i] - dt[1][i]; dbg[i] = dt[2][i] - dt[1][i];
        dy[i] = dt[1][i] + q[0] * drg[i] + q[1] * dbg[i];
        dcb[i] = q[2] * drg[i] + q[3] * dbg[i]; dcr[i] = q[4] * drg[i] + q[5] * dbg[i];
    }
    dy[sy[0]] += rg; dy[sy[1]] += bg; dcb[sy[2]] += rg; dcb[sy[3]] += bg; dcr[sy[4]] += rg; dcr[sy[5]] += bg;
    float r2 = cb * cb + cr * cr; if (r2 < 1e-12f) r2 = 1e-12f;
    float chd = ch < 1e-12f ? 1e-12f : ch;
    float kt = 57.29577951308232f / r2, in_h = tt > 0 && tt < 24 ? 1.0f : 0.0f;
    float slh = ddh / 15.0f * in_h, slg = (gs[a1] - gs[a0]) / 15.0f * in_h, sll = (gl[a1] - gl[a0]) / 15.0f * in_h;
    float in_g = ug > 0 && ug < 16 ? 1.0f : 0.0f, slY = (nodes[g0 + 1] - nodes[g0]) * 16.0f * in_g;
    float dY[JF2_LMAX], dc2[JF2_LMAX], dh2[JF2_LMAX];
    for (int i = 0; i < nm; i++) {
        float dth = (cb * dcr[i] - cr * dcb[i]) * kt, dch = (cb * dcb[i] + cr * dcr[i]) / chd;
        float dhs = slh * dth, dgs = slg * dth, dls = sll * dth;
        if (i == sq[0][0]) dhs += 1 - fa;
        if (i == sq[0][1]) dhs += fa;
        if (i == sq[1][0]) dgs += 1 - fa;
        if (i == sq[1][1]) dgs += fa;
        if (i == sq[2][0]) dls += 1 - fa;
        if (i == sq[2][1]) dls += fa;
        dc2[i] = dch * gsv + ch * dgs; dh2[i] = dth + dhs;
        float dy2 = dy[i] + dls * ch + (ls - 1) * dch;
        dY[i] = slY * dy2;
    }
    dY[sg0] += 1 - fg; dY[sg1] += fg;
    float kd = 0.017453292519943295f;
    for (int i = 0; i < nm; i++) {
        D[0][i] = dY[i];
        D[1][i] = dc2[i] * cs - c2 * sn * dh2[i] * kd;
        D[2][i] = dc2[i] * sn + c2 * cs * dh2[i] * kd;
    }
}

/* ---------------------------------------------------------------- 一輪(fit_visits.stage):Y/Cb/Cr -> 601 反矩陣 RGB */
/* D(非 0):d RGB / d 參數(140 位置 gid;YGAM 已從平滑節點換回原值)。rgb 出來已 clip。 */
static void jt_stage(const struct jtwo *T, int p, const float *c, float *rgb, float (*D)[JT_LMAX], int *gid, int *m) {
    float ycc[3], Dk[3][JF2_LMAX]; int gk[JF2_LMAX], nk = 0;
    jt_kernel(&T->Kk[p], T->Ps[p], c, ycc, D ? Dk : 0, gk, &nk);
    const float kr = 0.299f, kb = 0.114f, kg = 1 - kr - kb;
    const float cR = 2 * (1 - kr), cB = 2 * (1 - kb), gB = 2 * kb * (1 - kb) / kg, gR = 2 * kr * (1 - kr) / kg;
    float u[3] = {ycc[0] + cR * ycc[2], ycc[0] - gB * ycc[1] - gR * ycc[2], ycc[0] + cB * ycc[1]};
    for (int o = 0; o < 3; o++) rgb[o] = jf_clamp(u[o], 0, 1);
    if (!D) return;
    float in[3]; for (int o = 0; o < 3; o++) in[o] = u[o] > 0 && u[o] < 1 ? 1.0f : 0.0f;
    int n = 0;
    for (int i = 0; i < nk; i++) {                       /* YGAM 以外:原樣(順序不變,0..8 = 矩陣) */
        if (gk[i] >= 123) continue;
        D[0][n] = (Dk[0][i] + cR * Dk[2][i]) * in[0];
        D[1][n] = (Dk[0][i] - gB * Dk[1][i] - gR * Dk[2][i]) * in[1];
        D[2][n] = (Dk[0][i] + cB * Dk[1][i]) * in[2];
        gid[n++] = gk[i];
    }
    for (int i = 0; i < nk; i++) {                       /* YGAM:d 平滑節點 -> (H @ E[act]) -> d 原值 */
        if (gk[i] < 123) continue;
        int node = gk[i] - 123;
        float dv[3] = {(Dk[0][i] + cR * Dk[2][i]) * in[0], (Dk[0][i] - gB * Dk[1][i] - gR * Dk[2][i]) * in[1], (Dk[0][i] + cB * Dk[1][i]) * in[2]};
        int lo = node == 0 || node == 16 ? node : node - 1, hi = node == 0 || node == 16 ? node : node + 1;
        for (int mm = lo; mm <= hi; mm++) {
            float h = lo == hi ? 1.0f : mm == node ? 0.5f : 0.25f;
            int g = 123 + T->act[p][mm], s = -1;
            for (int j = 0; j < n; j++) if (gid[j] == g) { s = j; break; }
            if (s < 0) { s = n++; gid[s] = g; D[0][s] = D[1][s] = D[2][s] = 0; }
            for (int o = 0; o < 3; o++) D[o][s] += h * dv[o];
        }
    }
    *m = n;
}

/* 709 環(t1_matrix_check):RGB -> YCbCr x 255(+128)-> np.rint、clip 0..255 -> RGB、clip */
static float jt_rintf(float x) {                         /* 0 <= x <= 255:半數取偶 */
    int i = (int)x; float f = x - (float)i;
    if (f > 0.5f || (f == 0.5f && (i & 1))) i++;
    return (float)i;
}
static void jt_ring(float *v) {
    const float KR = 0.2126f, KB = 0.0722f, KG = 1 - KR - KB;
    float y = KR * v[0] + KG * v[1] + KB * v[2];
    float c0 = jt_rintf(jf_clamp(y * 255.0f, 0, 255));
    float c1 = jt_rintf(jf_clamp((v[2] - y) / (2 * (1 - KB)) * 255.0f + 128.0f, 0, 255));
    float c2 = jt_rintf(jf_clamp((v[0] - y) / (2 * (1 - KR)) * 255.0f + 128.0f, 0, 255));
    float Y = c0 / 255.0f, cb = (c1 - 128.0f) / 255.0f, cr = (c2 - 128.0f) / 255.0f;
    v[0] = jf_clamp(Y + 2 * (1 - KR) * cr, 0, 1);
    v[1] = jf_clamp(Y - 2 * KB * (1 - KB) / KG * cb - 2 * KR * (1 - KR) / KG * cr, 0, 1);
    v[2] = jf_clamp(Y + 2 * (1 - KB) * cb, 0, 1);
}

/* fit_visits.lab_gradient:d Lab / d 709 碼值(碼值在 (0, 1) 外為 0) */
static void jt_labgrad(const float *v, float JL[3][3]) {
    float a[3], dl[3];
    for (int k = 0; k < 3; k++) { a[k] = jf_pow24(jf_clamp(v[k], 0, 1)); dl[k] = v[k] > 0 && v[k] < 1 ? 2.4f * a[k] / v[k] : 0; }
    float X = (0.4123907993f * a[0] + 0.3575843394f * a[1] + 0.1804807884f * a[2]) / 0.95047f;
    float Yl = 0.2126390059f * a[0] + 0.7151686788f * a[1] + 0.0721923154f * a[2];
    float Z = (0.0193308187f * a[0] + 0.1191947798f * a[1] + 0.9505321522f * a[2]) / 1.08883f;
    float cx = jf_cbrt(X), cy = jf_cbrt(Yl), cz = jf_cbrt(Z);
    float fx = X > 0.008856f ? 1.0f / (3 * cx * cx) : 7.787f, fy = Yl > 0.008856f ? 1.0f / (3 * cy * cy) : 7.787f;
    float fz = Z > 0.008856f ? 1.0f / (3 * cz * cz) : 7.787f;
    for (int k = 0; k < 3; k++) {
        float mx = k == 0 ? 0.4123907993f : k == 1 ? 0.3575843394f : 0.1804807884f;
        float my = k == 0 ? 0.2126390059f : k == 1 ? 0.7151686788f : 0.0721923154f;
        float mz = k == 0 ? 0.0193308187f : k == 1 ? 0.1191947798f : 0.9505321522f;
        float ex = fx * mx / 0.95047f * dl[k], ey = fy * my * dl[k], ez = fz * mz / 1.08883f * dl[k];
        JL[0][k] = 116 * ey; JL[1][k] = 500 * (ex - ey); JL[2][k] = 200 * (ey - ez);
    }
}

/* ---------------------------------------------------------------- 兩輪一個樣本(fit_visits.forward) */
static int jt_colA(int g) { return g < 9 ? g : g - 9; }
static int jt_colB(int g) { return JT_NA + g - 18; }
/* lab 出;R(非 0):3 列 x m 欄(z 欄號 col) */
static void jt_sample(const struct jtwo *T, const float *x, int hard, float *lab, float (*R)[JT_LMAX], int *col, int *m) {
    float a[3], b[3], DA[3][JT_LMAX], DB[3][JT_LMAX]; int gA[JT_LMAX], gB[JT_LMAX], mA = 0, mB = 0;
    jt_stage(T, 0, x, a, R ? DA : 0, gA, &mA);
    if (hard) jt_ring(a);
    jt_stage(T, 1, a, b, R ? DB : 0, gB, &mB);
    if (hard) jt_ring(b);
    jf_rgb_lab(b[0], b[1], b[2], lab);
    if (!R) return;
    /* 第二輪對輸入的導數:恆等矩陣下 d/dM[k][col] = d/du_k * a[col](col = |a| 最大的,同值取前) */
    int cc = 0; float ab = jf_abs(a[0]);
    for (int k = 1; k < 3; k++) if (jf_abs(a[k]) > ab) { ab = jf_abs(a[k]); cc = k; }
    float div = jf_abs(a[cc]) > 1e-7f ? a[cc] : 1.0f, loc[3][3];
    for (int o = 0; o < 3; o++) for (int k = 0; k < 3; k++) loc[o][k] = DB[o][3 * k + cc] / div;
    float JL[3][3]; jt_labgrad(b, JL);
    float G[3][3];                                       /* d Lab / d 第一輪 RGB */
    for (int o = 0; o < 3; o++) for (int k = 0; k < 3; k++) G[o][k] = JL[o][0] * loc[0][k] + JL[o][1] * loc[1][k] + JL[o][2] * loc[2][k];
    int n = 0;
    for (int i = 0; i < mA; i++) {
        for (int o = 0; o < 3; o++) R[o][n] = G[o][0] * DA[0][i] + G[o][1] * DA[1][i] + G[o][2] * DA[2][i];
        col[n++] = jt_colA(gA[i]);
    }
    for (int i = 0; i < mB; i++) {
        if (gB[i] < 18) continue;                        /* 第二輪沒有矩陣 */
        for (int o = 0; o < 3; o++) R[o][n] = JL[o][0] * DB[0][i] + JL[o][1] * DB[1][i] + JL[o][2] * DB[2][i];
        col[n++] = jt_colB(gB[i]);
    }
    *m = n;
}

/* ---------------------------------------------------------------- 成本與正規方程 */
static double jt_zero(const struct jtwo *T) { double v = (double)T->w_tail; return v - v; }
/* 尾項(fit_visits:0.22 x MODEL.tail):兩輪各 99 列 */
static double jt_tail_cost(const struct jtwo *T) {
    double c = jt_zero(T);
    for (int p = 0; p < 2; p++) {
        float tl[JF_NTAIL]; jf_tail(&T->Jk[p], T->Pu[p], tl, 0);
        for (int i = 0; i < 99; i++) c += (double)tl[i] * tl[i];
    }
    return c * (double)T->w_tail;
}
/* 值:sum |(Lab - want) w|^2(w = 線性化時存的 T->w)+ 尾項;z 要先 jt_prepare */
static double jt_cost(struct jtwo *T, const struct jt_set *S, int hard) {
    double c = jt_tail_cost(T);
    for (uint32_t j = 0; j < S->n; j++) {
        if (T->spin && !(j & 31u)) T->spin(T->ctx);
        float lab[3]; jt_sample(T, S->xs + 3 * j, hard, lab, 0, 0, 0);
        for (int o = 0; o < 3; o++) { float e = (lab[o] - S->want[3 * j + o]) * T->w[j]; c += (double)e * e; }
        T->evals++;
    }
    return c;
}
static void jt_addrow(double *A, double *g, const float *d, const int *col, int m, float rv) {
    for (int a = 0; a < m; a++) {
        double va = d[a]; if (va == 0) continue;
        int ca = col[a];
        g[ca] += va * rv;
        for (int b = 0; b < m; b++) {
            int cb = col[b];
            if (cb <= ca) A[ca * JT_NZ + cb] += va * d[b];
        }
    }
}
/* A = JtJ(下三角)+ 尾項,g = Jt r + 尾項,T->w、T->diag(尾項前的對角);回傳目前成本 */
static double jt_normal(struct jtwo *T, const struct jt_set *S, int hard) {
    double *A = T->A, *g = T->g, z0 = jt_zero(T), c = z0;
    for (int i = 0; i < JT_NZ * JT_NZ; i++) A[i] = z0;
    for (int i = 0; i < JT_NZ; i++) g[i] = z0;
    for (uint32_t j = 0; j < S->n; j++) {
        if (T->spin && !(j & 31u)) T->spin(T->ctx);
        float lab[3], R[3][JT_LMAX], row[JT_LMAX]; int col[JT_LMAX], m = 0;
        jt_sample(T, S->xs + 3 * j, hard, lab, R, col, &m);
        float e[3], d2 = 0;
        for (int o = 0; o < 3; o++) { e[o] = lab[o] - S->want[3 * j + o]; d2 += e[o] * e[o]; }
        float h = jf_sqrt(d2) * 0.5f, w = S->wt[j] / jf_sqrt(h > 1 ? h : 1.0f);
        T->w[j] = w;
        for (int o = 0; o < 3; o++) {
            float rv = e[o] * w;
            c += (double)rv * rv;
            for (int i = 0; i < m; i++) row[i] = R[o][i] * w;
            jt_addrow(A, g, row, col, m, rv);
        }
        T->gevals++;
    }
    for (int i = 0; i < JT_NZ; i++) {
        double d = A[i * JT_NZ + i], fl = (double)T->dfloor;
        T->diag[i] = d > fl ? d : fl;
    }
    /* 尾項:CEQ 鄰差(sw, -sw)、曲線編修(w_curve),x w_tail */
    double kt = (double)T->w_tail;
    for (int p = 0; p < 2; p++) {
        float tl[JF_NTAIL]; jf_tail(&T->Jk[p], T->Pu[p], tl, 0);
        for (int i = 0; i < 99; i++) c += kt * ((double)tl[i] * tl[i]);
        for (int q = 0; q < 3; q++) {
            double sw = q ? T->w_gain : T->w_hue;
            for (int a = 0; a < 24; a++) {
                int g1 = 51 + 24 * q + a, g2 = 51 + 24 * q + (a + 1) % 24;
                int ka = p ? jt_colB(g1) : jt_colA(g1), kb = p ? jt_colB(g2) : jt_colA(g2);
                double rv = tl[24 * q + a];
                g[ka] += kt * sw * rv; g[kb] -= kt * sw * rv;
                A[ka * JT_NZ + ka] += kt * sw * sw; A[kb * JT_NZ + kb] += kt * sw * sw;
                if (ka > kb) A[ka * JT_NZ + kb] -= kt * sw * sw; else A[kb * JT_NZ + ka] -= kt * sw * sw;
            }
        }
        double wc = T->w_curve;
        for (int k = 0; k < 27; k++) {
            int ck = p ? jt_colB(18 + k) : jt_colA(18 + k);
            g[ck] += kt * wc * tl[72 + k]; A[ck * JT_NZ + ck] += kt * wc * wc;
        }
    }
    return c;
}

/* ---------------------------------------------------------------- 封裝(jft.quantise / fit_visits.packets) */
static int32_t jt_rint(float x) {                        /* Python round / np.rint:半數取偶 */
    float a = jf_abs(x);
    int32_t i = (int32_t)a; float f = a - (float)i;
    if (f > 0.5f || (f == 0.5f && (i & 1))) i++;
    return x < 0 ? -i : i;
}
static int32_t jt_clampi(int32_t v, int32_t lo, int32_t hi) { return v < lo ? lo : v > hi ? hi : v; }
static void jt_ygam_words(const int32_t *p, uint32_t *w) {   /* jft.ygam_words(= conv.c conv_ygam) */
    int32_t sl[16], knots[15];
    int32_t y0 = p[0] > 0xfff ? 0xfff : p[0];
    sl[0] = jt_clampi(((p[1] - p[0]) * 0x80 + 0x80) / 256, 0, 0x3ff);
    sl[1] = jt_clampi(((p[2] - p[0]) * 0x80 + 0x100) / 512, 0, 0x3ff);
    for (int i = 3; i < 17; i++) sl[i - 1] = jt_clampi(((p[i] - p[i - 2]) * 0x80 + 0x100) / 512, 0, 0x3ff);
    int32_t prev = y0;
    for (int i = 0; i < 15; i++) { prev = jt_clampi(prev + sl[i] + sl[i + 1], 0, 0xfff); knots[i] = prev; }
    int32_t last = jt_clampi(p[16] - (knots[14] + sl[15]) + 1, 0, 0x3ff);
    w[0] = 1u | (uint32_t)y0 << 16;
    for (int i = 0; i < 16; i += 2) {
        int32_t a = knots[i], b = i + 1 < 15 ? knots[i + 1] : 0x1000;
        w[1 + i / 2] = (uint32_t)a | (uint32_t)b << 16;
    }
    for (int i = 0; i < 16; i += 2) w[9 + i / 2] = (uint32_t)sl[i] | (uint32_t)sl[i + 1] << 16;
    w[17] = (uint32_t)last;
}
static int jt_org(int a) { return (a * 65536 + 12) / 24; }   /* jft.ORG_H(餘數只有 0 / 1/3 / 2/3,沒有平手) */
/* 曲線:base + 9 節點編修(np.interp)、running max、clip(jft.quantise 的 curve) */
static void jt_curve(const float *base, const float *d, float *out) {
    float m = 0;
    for (int i = 0; i < JF_NTONE; i++) {
        float x = (float)i / (float)(JF_NTONE - 1) * (float)(JF_KN - 1);
        int a = (int)x; if (a > JF_KN - 2) a = JF_KN - 2;
        float v = base[i] + d[a] + (d[a + 1] - d[a]) * (x - (float)a);
        if (!i || v > m) m = v;
        out[i] = jf_clamp(m, 0, 1);
    }
}
/* 0 好;1 矩陣超出硬體;2 YCMAT 亮度超出 12 bit */
static int jt_quantise(struct jtwo *T, int pass, const float *P, struct jt_hw *h) {
    float *cv = T->qtone;
    for (int k = 0; k < 3; k++) {
        if (!pass) { jt_curve(T->base_a + k * JF_NTONE, P + 18 + 9 * k, cv + k * JF_NTONE); continue; }
        /* 第二輪(fit_visits.packets):編修烘進恆等 tone,再取樣到白點 2040:new[i] = table(i x 1918 / 2040) */
        float *tmp = cv + 3 * JF_NTONE, *nb = cv + 4 * JF_NTONE;   /* qtone 的兩段暫存(不放堆疊:相機任務 16 KiB) */
        jt_curve(T->base_b + k * JF_NTONE, P + 18 + 9 * k, tmp);
        float zero9[9]; for (int i = 0; i < 9; i++) zero9[i] = 0;
        for (int i = 0; i < JF_NTONE; i++) {
            float x = (float)i * (JF_WHITE / 2040.0f);
            int a = (int)x; if (a > JF_NTONE - 2) a = JF_NTONE - 2;
            nb[i] = tmp[a] + (tmp[a + 1] - tmp[a]) * (x - (float)a);
        }
        jt_curve(nb, zero9, cv + k * JF_NTONE);
    }
    int32_t q[3][3]; uint32_t shift = 0;
    for (;; shift++) {
        float s = (float)(512u >> shift);
        for (int r = 0; r < 3; r++) for (int c = 0; c < 3; c++) q[r][c] = jt_rint(P[3 * r + c] * s);
        int32_t t[9] = {q[0][0], q[0][1], q[0][2], q[1][1], q[1][0], q[1][2], q[2][2], q[2][0], q[2][1]};
        int ok = 1;
        for (int k = 0; k < 9; k += 3) {
            if (t[k] < -1024 || t[k] > 2047) ok = 0;
            for (int j = 1; j < 3; j++) if (t[k + j] < -1022 || t[k + j] > 2047) ok = 0;
        }
        if (ok) { for (int k = 0; k < 9; k++) h->m2[k] = (int16_t)t[k]; break; }
        if (shift == 2u) return 1;
    }
    h->shift = shift;
    for (int r = 0; r < 3; r++) for (int c = 0; c < 3; c++) h->q[3 * r + c] = (int16_t)q[r][c];
    for (int k = 0; k < 3; k++) for (int i = 0; i < JF_NTONE; i++) {
        int at = i << shift; if (at > JF_NTONE - 1) at = JF_NTONE - 1;
        int32_t v = jt_rint(8190.0f * cv[k * JF_NTONE + at]);
        if (pass) v = jt_clampi(2 * ((272 * v + 273) / 546), 0, 8188);   /* 2 rint(v 8160 / 16380):不會平手 */
        h->tone[k * JF_NTONE + i] = (uint16_t)v;
    }
    const float *post = P + 45;
    int32_t yr = jt_rint(post[0] * 4096.0f), yb = jt_rint(post[1] * 4096.0f), yg = 4096 - yr - yb;
    if (yr < 0 || yr > 4095 || yb < 0 || yb > 4095 || yg < 0 || yg > 4095) return 2;
    int32_t ycm[7] = {yr, yg, yb, jt_clampi(jt_rint(post[2] * 512.0f), -511, 511), jt_clampi(jt_rint(post[3] * 512.0f), 0, 1023),
                      jt_clampi(jt_rint(post[4] * 512.0f), 0, 1023), jt_clampi(jt_rint(post[5] * 512.0f), -511, 511)};
    for (int k = 0; k < 7; k++) h->ycmat[k] = (int16_t)ycm[k];
    float dhq[24];                                          /* 11-10: the hue order clamp, as conv.c conv_pack */
    for (int a = 0; a < 24; a++) dhq[a] = post[6 + a];
    jf_hue_safe(dhq);
    for (int a = 0; a < 24; a++) {
        h->ceq[a] = (uint16_t)jt_rint(512.0f * post[54 + a]);
        h->ceq[24 + a] = (uint16_t)jt_rint(683.0f * post[30 + a]);
        h->ceq[48 + a] = (uint16_t)((uint32_t)jt_rint((float)jt_org(a) + dhq[a] * 65536.0f / 360.0f) & 0xFFFFu);
    }
    int32_t yo[17]; float mx = 0;
    for (int i = 0; i < 17; i++) { float v = jf_clamp(post[78 + i], 0, 1); if (!i || v > mx) mx = v; yo[i] = jt_rint(4095.0f * mx); }
    jt_ygam_words(yo, h->ygam);
    /* 重播用的 post(replay_isp.encoded_stage) */
    float *pp = h->post;
    pp[0] = (float)h->ycmat[0] / 4096.0f; pp[1] = (float)h->ycmat[2] / 4096.0f;
    for (int k = 0; k < 4; k++) pp[2 + k] = (float)h->ycmat[3 + k] / 512.0f;
    for (int a = 0; a < 24; a++) {
        int32_t d = ((int32_t)h->ceq[48 + a] - jt_org(a) + 32768) & 0xFFFF;
        pp[6 + a] = (float)(d - 32768) * (360.0f / 65536.0f);
        pp[30 + a] = (float)h->ceq[24 + a] / 683.0f;
        pp[54 + a] = (float)(int16_t)h->ceq[a] / 512.0f;
    }
    int32_t kn[17]; const uint32_t *w = h->ygam;
    kn[0] = (int32_t)(w[0] >> 16);
    for (int i = 1; i < 9; i++) { kn[2 * i - 1] = (int32_t)(w[i] & 0xFFFFu); kn[2 * i] = (int32_t)(w[i] >> 16); }
    { int32_t v = kn[15] + (int32_t)(w[16] >> 16) + (int32_t)w[17]; kn[16] = v < 4095 ? v : 4095; }
    for (int i = 0; i < 17; i++) pp[78 + i] = (float)kn[i] / 4095.0f;
    return 0;
}
/* jft.pack 的 payload(12544 bytes);標頭由呼叫端寫 */
static void jt_w16(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void jt_w32(uint8_t *p, uint32_t v) { jt_w16(p, v); jt_w16(p + 2, v >> 16); }
static void jt_payload(const struct jt_hw *h, uint8_t *pay) {
    jt_w32(pay, h->shift);
    for (int k = 0; k < 9; k++) jt_w16(pay + 4 + 2 * k, (uint16_t)h->m2[k]);
    jt_w16(pay + 22, 0);
    for (int i = 0; i < 3 * JF_NTONE; i++) jt_w16(pay + 24 + 2 * i, h->tone[i]);
    uint8_t *yc = pay + 24 + 6 * JF_NTONE, *cq = yc + 16, *yg = cq + 144;
    for (int k = 0; k < 7; k++) jt_w16(yc + 2 * k, (uint16_t)h->ycmat[k]);
    jt_w16(yc + 14, 0);
    for (int k = 0; k < 72; k++) jt_w16(cq + 2 * k, h->ceq[k]);
    for (int k = 0; k < 18; k++) jt_w32(yg + 4 * k, h->ygam[k]);
}

/* ---------------------------------------------------------------- 重播(replay_isp.encoded_stage + lut_batch_eval.post_apply + 環) */
static void jt_replay(const struct jt_hw *h, int pass, const float *x, float *out) {
    float white = pass ? 2040.0f : JF_WHITE, sc = pass ? 1.0f / 8160.0f : 1.0f / 8190.0f, t[3];
    for (int k = 0; k < 3; k++) {
        float idx = ((float)h->q[3 * k] * x[0] + (float)h->q[3 * k + 1] * x[1] + (float)h->q[3 * k + 2] * x[2]) / 512.0f * white;
        idx = jf_clamp(idx, 0, JF_NTONE - 1);
        const uint16_t *tb = h->tone + k * JF_NTONE;
        int i0 = (int)idx; if (i0 > JF_NTONE - 2) i0 = JF_NTONE - 2;
        float f = idx - (float)i0, a = (float)tb[i0] * sc, b = (float)tb[i0 + 1] * sc;
        t[k] = jf_clamp(a + (b - a) * f, 0, 1);
    }
    const float *q = h->post;
    float r = t[0], g = t[1], b = t[2];
    float y = q[0] * r + (1 - q[0] - q[1]) * g + q[1] * b;
    float cb = q[2] * (r - g) + q[3] * (b - g), cr = q[4] * (r - g) + q[5] * (b - g);
    float th = jf_atan2deg(cr, cb), ch = jf_sqrt(cb * cb + cr * cr);
    float tt = th / 15.0f; int a0 = (int)tt; if (a0 > 23) a0 = 23; float fa = tt - (float)a0; int a1 = a0 == 23 ? 0 : a0 + 1;
    const float *dh = q + 6, *gs = q + 30, *gl = q + 54;
    float c2 = ch * (gs[a0] + (gs[a1] - gs[a0]) * fa);
    float h2 = th + dh[a0] + jf_hue_dd(dh, a0, a1) * fa;
    float y2 = y + (gl[a0] + (gl[a1] - gl[a0]) * fa - 1) * ch;
    float nodes[17], m = q[78];
    for (int i = 0; i < 17; i++) { if (q[78 + i] > m) m = q[78 + i]; nodes[i] = i ? m : q[78]; }
    y2 = jf_interp_lin(y2, nodes, 17, 1.0f);
    float sn, cs; jf_sincos_deg(h2, &sn, &cs);
    float cb2 = c2 * cs, cr2 = c2 * sn;
    const float kr = 0.299f, kb = 0.114f, kg = 1 - kr - kb;
    float R = y2 + 2 * (1 - kr) * cr2, B = y2 + 2 * (1 - kb) * cb2, G = (y2 - kr * R - kb * B) / kg;
    out[0] = jf_clamp(R, 0, 1); out[1] = jf_clamp(G, 0, 1); out[2] = jf_clamp(B, 0, 1);
    jt_ring(out);
}
/* 兩輪重播一點 -> 709 碼值 */
static void jt_replay2(const struct jtwo *T, const float *x, float *out) {
    float a[3]; jt_replay(&T->hw[0], 0, x, a); jt_replay(&T->hw[1], 1, a, out);
}

/* heapsort(np.percentile 要兩個順序統計量) */
static void jt_sift(float *d, uint32_t i, uint32_t n) {
    for (;;) {
        uint32_t c = 2u * i + 1u;
        if (c >= n) return;
        if (c + 1u < n && d[c + 1u] > d[c]) c++;
        if (!(d[c] > d[i])) return;
        float t = d[c]; d[c] = d[i]; d[i] = t; i = c;
    }
}
static void jt_sort(float *d, uint32_t n) {
    for (uint32_t i = n / 2u; i-- > 0;) jt_sift(d, i, n);
    for (uint32_t e = n; e-- > 1u;) { float t = d[0]; d[0] = d[e]; d[e] = t; jt_sift(d, 0, e); }
}
/* 選解損失:封裝 z、整數表重播選解集、平均 + p95w x P95(np.percentile 線性)。封不了 -> JT_BIG */
static float jt_select(struct jtwo *T, const float *z) {
    float PA[JF_NP], PB[JF_NP];
    jt_unpack(z, PA, PB);
    T->checks++;
    if (jt_quantise(T, 0, PA, &T->hw[0]) || jt_quantise(T, 1, PB, &T->hw[1])) return JT_BIG;
    const struct jt_set *S = &T->sel;
    double sum = jt_zero(T);
    for (uint32_t j = 0; j < S->n; j++) {
        if (T->spin && !(j & 31u)) T->spin(T->ctx);
        float v[3], lab[3]; jt_replay2(T, S->xs + 3 * j, v);
        jf_rgb_lab(v[0], v[1], v[2], lab);
        float e0 = lab[0] - S->want[3 * j], e1 = lab[1] - S->want[3 * j + 1], e2 = lab[2] - S->want[3 * j + 2];
        T->de[j] = jf_sqrt(e0 * e0 + e1 * e1 + e2 * e2);
        sum += (double)T->de[j];
    }
    jt_sort(T->de, S->n);
    float pos = 0.95f * (float)(S->n - 1u); uint32_t i = (uint32_t)pos; float f = pos - (float)i;
    float p95 = i + 1u < S->n ? T->de[i] + (T->de[i + 1u] - T->de[i]) * f : T->de[i];
    return (float)(sum / (double)S->n) + T->p95w * p95;
}

/* ---------------------------------------------------------------- 整個擬合(fit_constrained.fit_constrained,hinge,lam = 0) */
static float jt_fit(struct jtwo *T) {
    uint32_t nmax = T->sel.n;
    for (int s = 0; s < 3; s++) if (T->set[s].n > nmax) nmax = T->set[s].n;
    jt_carve(T, nmax, T->sel.n);
    T->steps = T->evals = T->gevals = T->checks = 0; T->err = 0;
    float *z = T->z, *best = T->best, *zn = T->zn;
    jt_vector(T->PA, T->PB, best);
    jt_normalise(best);
    float best_cost = jt_select(T, best);
    T->start_cost = best_cost;
    for (int s = 0; s < 3; s++) {
        const struct jt_set *S = &T->set[s];
        int hard = (int)T->hard[s];
        float damping = T->damp0;
        for (int c = 0; c < JT_NZ; c++) z[c] = best[c];
        for (uint32_t it = 0; it < T->iters[s]; it++) {
            jt_prepare(T, z);
            double current = jt_normal(T, S, hard);
            double *A = T->A, *g = T->g, z0 = jt_zero(T);
            for (int c = 0; c < JT_NZ; c++) {                /* 卡在邊界、梯度往外:凍結 */
                int k = jt_gid(c); float lo = jf_bound(k, 0), hi = jf_bound(k, 1);
                T->frz[c] = (uint8_t)((z[c] <= lo + 1e-7f && g[c] > 0) || (z[c] >= hi - 1e-7f && g[c] < 0));
            }
            for (int i = 0; i < JT_NZ; i++) {
                T->dsave[i] = A[i * JT_NZ + i]; T->gsave[i] = T->frz[i] ? z0 : g[i];
                for (int j = 0; j < i; j++) A[j * JT_NZ + i] = A[i * JT_NZ + j];   /* 上三角存一份,重試用 */
            }
            int moved = 0;
            for (int tr = 0; tr < 10; tr++) {
                double dmp = (double)damping;
                for (int i = 0; i < JT_NZ; i++) {
                    for (int j = 0; j < i; j++) A[i * JT_NZ + j] = T->frz[i] || T->frz[j] ? z0 : A[j * JT_NZ + i];
                    A[i * JT_NZ + i] = (T->frz[i] ? z0 + 1 : T->dsave[i]) + dmp * T->diag[i];
                    g[i] = -T->gsave[i];
                }
                int ok = jf_solve(A, g, JT_NZ, z0);
                if (ok) {
                    for (int c = 0; c < JT_NZ; c++) {
                        int k = jt_gid(c);
                        zn[c] = jf_clamp(z[c] + (float)g[c], jf_bound(k, 0), jf_bound(k, 1));
                    }
                    jt_normalise(zn);
                    jt_prepare(T, zn);
                    if (jt_cost(T, S, hard) < current) {
                        for (int c = 0; c < JT_NZ; c++) z[c] = zn[c];
                        damping *= 0.45f; if (damping < 1e-6f) damping = 1e-6f;
                        moved = 1;
                        break;
                    }
                }
                damping *= 4;
            }
            if (!moved) break;
            T->steps++;
            if (T->tick) T->tick(T->ctx, T->steps);
            if (it % 5u == 4u || it == T->iters[s] - 1u) {
                float q = jt_select(T, z);
                if (q < best_cost) { best_cost = q; for (int c = 0; c < JT_NZ; c++) best[c] = z[c]; }
            }
        }
    }
    jt_unpack(best, T->PA, T->PB);
    if (jt_quantise(T, 0, T->PA, &T->hw[0]) || jt_quantise(T, 1, T->PB, &T->hw[1])) T->err = 1;
    T->sel_cost = best_cost;
    return best_cost;
}

/* ---------------------------------------------------------------- 樣本(fit_visits.draw 的分布;相機用自己的亂數) */
static float jt_unif(uint32_t *s) {                      /* xorshift32 -> [0, 1) */
    uint32_t x = *s; x ^= x << 13; x ^= x >> 17; x ^= x << 5; *s = x;
    return (float)(x >> 8) * (1.0f / 16777216.0f);
}
static float jt_powf(float x, float e) { return x <= 0 ? 0 : jf_exp2(e * jf_log2(x)); }
/* n 個顯示取向樣本(四組:混灰 / 混合 / 曝光 +-1 EV / 原樣)+ n / 3 個 CMAX u^2.2;xs: (n + n / 3) x 3,回傳個數 */
static uint32_t jt_draw(uint32_t *seed, uint32_t n, float *xs) {
    uint32_t k = 0;
    for (uint32_t i = 0; i < n; i++, k++) {
        float v[3] = {jt_unif(seed), jt_unif(seed), jt_unif(seed)};
        float grey = 0.03f + 0.97f * jt_unif(seed), mix = jt_unif(seed), ex = 0;
        uint32_t grp = i & 3u;
        for (int c = 0; c < 3; c++) {
            if (grp == 0u) v[c] = 0.75f * v[c] + 0.25f * grey;
            else if (grp == 1u) v[c] = mix * v[c] + (1 - mix) * grey;
        }
        if (grp == 2u) ex = 2 * jt_unif(seed) - 1;
        float l[3], e = jf_exp2(ex);
        for (int c = 0; c < 3; c++) l[c] = jf_pow24(v[c]) * e;
        xs[3 * k]     =  0.7525381f   * l[0] + 0.32845083f * l[1] - 0.08098891f * l[2];   /* lut_batch_eval.to_camera */
        xs[3 * k + 1] =  0.058166765f * l[0] + 0.8702844f  * l[1] + 0.07154885f * l[2];
        xs[3 * k + 2] = -0.014688964f * l[0] + 0.26282156f * l[1] + 0.7518674f  * l[2];
    }
    for (uint32_t i = 0; i < n / 3u; i++, k++)
        for (int c = 0; c < 3; c++) xs[3 * k + c] = (2047.0f / JF_WHITE) * jt_powf(jt_unif(seed), 2.2f);
    return k;
}
/* 基本權重:(1 - 2.5 sat / 8)^0.7,sat = lv_fit.saturation(目標在強度 0 的碼值) */
static float jt_weight(const float *rgb0) {
    float mx = rgb0[0], mn = rgb0[0];
    for (int c = 1; c < 3; c++) { if (rgb0[c] > mx) mx = rgb0[c]; if (rgb0[c] < mn) mn = rgb0[c]; }
    float sat = mx > 1e-6f ? (mx - mn) / mx : 0;
    return jt_powf(1 - 2.5f * sat / 8.0f, 0.7f);
}
#endif
