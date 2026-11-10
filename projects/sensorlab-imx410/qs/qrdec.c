/* qrdec.c -- SensorLab QR scan, phase 1 (notes/QR_SCAN_DESIGN.md §3): read OUR symbol -- QR Model 2, version 5-L,
 * byte mode, one RS block (108 data + 26 EC) -- from a Y8 image such as the one the stock reader thread hands its
 * decoder (the centre 512 x 512 of the display image).  The stock decoder only takes version 20 (FUN_c05cb960), so this
 * runs behind it on the same input.
 *
 * Included after slqs.c's encoder and uses it: gf_mul, mask_bit, QR_N / QR_DATA_CW / QR_EC_CW / QR_URL / QR_CHARS,
 * N_QF / QF_W / QF_BITS / B64U, and the encoder's function-module map (struct qr .fn: it does not depend on the data,
 * so any encoded code's map is the map).  Freestanding: no libc, no float, no '/' or '%' on a variable (the A9 has no
 * divider): divisions go through qd_div (CLZ-aligned shift-subtract, at most ~16 steps here).
 *
 * Pipeline: block min/max/mean -> local mean threshold (5 x 5 blocks; low contrast -> the global one; the midpoint
 * lost glare and low-contrast frames to a bright or dark surround, test_qrdec rates) -> finder runs
 * 1:1:3:1:1 on every 2nd row, checked down the column and again along the row -> the 3 finders of a right angle ->
 * the alignment pattern searched around its affine prediction -> a 4-point homography (integer, homogeneous: no
 * division until a module is sampled) -> 37 x 37 centre samples -> the finder / timing check -> format (nearest of
 * the 32 BCH words, ECC L only) -> unmask + zigzag (the encoder's own map and mask_bit) -> Reed-Solomon (BM, Chien,
 * Forney; t = 13) -> byte segment. */

#define QD_BS    16u                     /* threshold block, pixels (shift 4) */
#define QD_NB    40u                     /* blocks per side: up to 640 x 640 (a larger image: its centre) */
#define QD_MAXC  24u                     /* finder candidates */
#define QD_MINC  24u                     /* a 5 x 5 block neighbourhood with less contrast uses the global threshold */
#define QD_ROWS  2        /* finder scan: every 2nd row (>= 4 sightings of a 3 px/module finder) */
#define QD_TOP   8u                      /* the best candidates combined into triples */
#define QD_TRIES 10u                     /* geometric triples decoded per frame at most */
#define QD_NCW   (QR_DATA_CW + QR_EC_CW) /* 134 */
#define QD_T     (QR_EC_CW / 2u)         /* 13 correctable symbols */

enum { QD_OK, QD_NOFIND, QD_NOTRIPLE, QD_GEOM, QD_FORMAT, QD_RS, QD_SEGMENT };

struct qd_cand { s32 x, y, m; u32 n; s32 sx, sy, sm; };   /* x, y, m: Q4 pixels (first sighting, then the mean) */
struct qrd {
    const u8 *img; s32 w, h; u32 stride, nbx, nby, gthr;
    u8 lo[QD_NB * QD_NB], hi[QD_NB * QD_NB], mn[QD_NB * QD_NB], thr[QD_NB * QD_NB];
    struct qd_cand c[QD_MAXC];
    u32 nc;
    i64 M[9];                             /* module (half units) -> image (Q4), homogeneous */
    u8 mod[QR_N * QR_N];                  /* 1 = dark */
    u8 cw[QD_NCW];
    u8 ex[256], lg[256];
    /* diagnostics (the host tests read them; sq_test later) */
    u32 why, tries, fmt_d, mask, rs_n, align, mirror, pat_bad, hits;
};

/* ------------------------------------------------------------------ arithmetic */
static u32 qd_div(u32 n, u32 d)                        /* n / d (d != 0) */
{
    if (!d || n < d) return 0;
    u32 s = (u32)__builtin_clz(d) - (u32)__builtin_clz(n), q = 0;
    d <<= s;
    for (u32 i = 0; i <= s; i++) { q <<= 1; if (n >= d) { n -= d; q |= 1u; } d >>= 1; }
    return q;
}
static i64 qd_abs64(i64 a) { return a < 0 ? -a : a; }
static u32 qd_bits(u32 v) { u32 n = 0; while (v) { v &= v - 1u; n++; } return n; }
static void qd_norm(i64 *m, u32 k, i64 lim)            /* homogeneous: scale k entries down below lim */
{
    i64 mx = 0;
    for (u32 i = 0; i < k; i++) if (qd_abs64(m[i]) > mx) mx = qd_abs64(m[i]);
    while (mx >= lim) { for (u32 i = 0; i < k; i++) m[i] >>= 1; mx >>= 1; }
}

/* ------------------------------------------------------------------ binarisation */
__attribute__((noinline)) static void qd_blocks(struct qrd *d)
{
    u32 nbx = (u32)(d->w + 15) >> 4, nby = (u32)(d->h + 15) >> 4, sum = 0;
    d->nbx = nbx; d->nby = nby;
    for (u32 by = 0; by < nby; by++) for (u32 bx = 0; bx < nbx; bx++) {
        u32 lo = 255, hi = 0, s = 0, y1 = by * QD_BS + QD_BS, x1 = bx * QD_BS + QD_BS;
        if (y1 > (u32)d->h) y1 = (u32)d->h;
        if (x1 > (u32)d->w) x1 = (u32)d->w;
        for (u32 y = by * QD_BS; y < y1; y++) {
            const u8 *p = d->img + y * d->stride;
            for (u32 x = bx * QD_BS; x < x1; x++) { u32 v = p[x]; s += v; if (v < lo) lo = v; if (v > hi) hi = v; }
        }
        d->lo[by * nbx + bx] = (u8)lo; d->hi[by * nbx + bx] = (u8)hi;
        d->mn[by * nbx + bx] = (u8)qd_div(s, (y1 - by * QD_BS) * (x1 - bx * QD_BS));
        sum += lo + hi;
    }
    d->gthr = qd_div(sum, 2u * nbx * nby);
    for (u32 by = 0; by < nby; by++) for (u32 bx = 0; bx < nbx; bx++) {
        u32 lo = 255, hi = 0, s = 0, n = 0;            /* 5 x 5 blocks: the contrast test and the local mean */
        for (u32 j = by < 2u ? 0u : by - 2u; j <= by + 2u && j < nby; j++)
            for (u32 i = bx < 2u ? 0u : bx - 2u; i <= bx + 2u && i < nbx; i++) {
                if (d->lo[j * nbx + i] < lo) lo = d->lo[j * nbx + i];
                if (d->hi[j * nbx + i] > hi) hi = d->hi[j * nbx + i];
                s += d->mn[j * nbx + i]; n++;
            }
        d->thr[by * nbx + bx] = (u8)(hi - lo < QD_MINC ? d->gthr : qd_div(s, n));
    }
}
static u32 qd_bit(const u8 *row, const u8 *trow, u32 x) { return row[x] < trow[x >> 4]; }   /* the one pixel test */
static u32 qd_px(const struct qrd *d, s32 x, s32 y)    /* 1 = dark; outside = light */
{
    if ((u32)x >= (u32)d->w || (u32)y >= (u32)d->h) return 0;
    return qd_bit(d->img + (u32)y * d->stride, d->thr + ((u32)y >> 4) * d->nbx, (u32)x);
}

/* ------------------------------------------------------------------ finder patterns */
static u32 qd_ratio(const u32 *r)                      /* 1:1:3:1:1 within tolerance -> the total, else 0 */
{
    u32 t = r[0] + r[1] + r[2] + r[3] + r[4];
    if (t < 7u) return 0;
    for (u32 i = 0; i < 5u; i++) if (i != 2u && (14u * r[i] < t || 14u * r[i] > 3u * t)) return 0;
    if (14u * r[2] < 4u * t || 14u * r[2] > 9u * t) return 0;
    return t;
}
/* the five runs through (x, y) along (dx, dy), (x, y) inside the centre run; -> the total (0 = no pattern) and the
 * centre along the line, Q4 */
static u32 qd_line(const struct qrd *d, s32 x, s32 y, s32 dx, s32 dy, u32 max, s32 *c16)
{
    u32 r[5];
    s32 a = 0, b = 0;
    if (!qd_px(d, x, y)) return 0;
    while ((u32)(b - a) < max && qd_px(d, x + (a - 1) * dx, y + (a - 1) * dy)) a--;
    while ((u32)(b - a) < max && qd_px(d, x + (b + 1) * dx, y + (b + 1) * dy)) b++;
    r[2] = (u32)(b - a + 1);
    s32 t = a - 1;
    for (u32 k = 0; k < 2u; k++) {                     /* back: light then dark */
        u32 n = 0, want = k == 0u ? 0u : 1u;
        while (n < max && qd_px(d, x + t * dx, y + t * dy) == want) { n++; t--; }
        if (!n) return 0;
        r[1u - k] = n;
    }
    t = b + 1;
    for (u32 k = 0; k < 2u; k++) {                     /* forward */
        u32 n = 0, want = k == 0u ? 0u : 1u;
        while (n < max && qd_px(d, x + t * dx, y + t * dy) == want) { n++; t++; }
        if (!n) return 0;
        r[3u + k] = n;
    }
    *c16 = (a + b + 1) * 8;
    return qd_ratio(r);
}
static void qd_hit(struct qrd *d, s32 x16, s32 y, u32 th)
{
    s32 x = x16 >> 4, cy, cx;
    u32 tv = qd_line(d, x, y, 0, 1, 2u * th, &cy);
    if (!tv || 2u * tv < th || tv > 2u * th) return;
    cy += y * 16;
    u32 th2 = qd_line(d, x, cy >> 4, 1, 0, 2u * th, &cx);
    if (!th2 || 2u * th2 < tv || th2 > 2u * tv) return;
    cx += x * 16;
    s32 m = (s32)(((th2 + tv) * 4681u) >> 12);         /* (th2 + tv) / 14 modules, Q4 = x 16 / 14 */
    for (u32 i = 0; i < d->nc; i++) {
        struct qd_cand *c = &d->c[i];
        s32 lim = c->m > m ? c->m : m, dm = c->m > m ? c->m - m : m - c->m;
        if (2 * dm > lim) continue;                    /* another size: never merge (a scene blob ate a finder once) */
        if (cx - c->x < lim && c->x - cx < lim && cy - c->y < lim && c->y - cy < lim) {
            c->sx += cx; c->sy += cy; c->sm += m; c->n++;
            return;
        }
    }
    if (d->nc < QD_MAXC) {
        struct qd_cand *c = &d->c[d->nc++];
        c->x = c->sx = cx; c->y = c->sy = cy; c->m = c->sm = m; c->n = 1;
    }
}
__attribute__((noinline)) static void qd_scan(struct qrd *d)
{
    d->nc = 0; d->hits = 0;
    for (s32 y = 0; y < d->h; y += QD_ROWS) {
        const u8 *p = d->img + (u32)y * d->stride, *t = d->thr + ((u32)y >> 4) * d->nbx;   /* = qd_px, row-local */
        u32 r[5] = {0, 0, 0, 0, 0}, runs = 0, run = 0, prev = qd_bit(p, t, 0);
        for (s32 x = 0; x <= d->w; x++) {
            u32 v = x < d->w ? qd_bit(p, t, (u32)x) : prev ^ 1u;
            if (v == prev) { run++; continue; }
            r[0] = r[1]; r[1] = r[2]; r[2] = r[3]; r[3] = r[4]; r[4] = run;
            if (runs < 5u) runs++;
            if (prev && runs == 5u) {                  /* a dark run just ended: d l d l d */
                u32 t = qd_ratio(r);
                if (t) d->hits++;
                if (t) qd_hit(d, (2 * (x - (s32)(r[4] + r[3] + r[2])) + (s32)r[2]) * 8, y, t);
            }
            prev = v; run = 1;
        }
    }
    u32 k = 0;
    for (u32 i = 0; i < d->nc; i++) {                  /* means; drop single sightings */
        struct qd_cand *c = &d->c[i];
        if (c->n < 2u) continue;
        c->x = (s32)qd_div((u32)c->sx, c->n); c->y = (s32)qd_div((u32)c->sy, c->n); c->m = (s32)qd_div((u32)c->sm, c->n);
        d->c[k++] = *c;
    }
    d->nc = k;
    for (u32 i = 1; i < k; i++)                        /* by sightings, most first */
        for (u32 j = i; j > 0u && d->c[j].n > d->c[j - 1u].n; j--) {
            struct qd_cand t = d->c[j]; d->c[j] = d->c[j - 1u]; d->c[j - 1u] = t;
        }
}

/* ------------------------------------------------------------------ geometry */
static void qd_sq2quad(i64 *m, const i64 *x, const i64 *y) /* unit square (0,0),(1,0),(1,1),(0,1) -> the quad */
{
    i64 sx = x[0] - x[1] + x[2] - x[3], sy = y[0] - y[1] + y[2] - y[3];
    i64 dx1 = x[1] - x[2], dx2 = x[3] - x[2], dy1 = y[1] - y[2], dy2 = y[3] - y[2];
    i64 den = dx1 * dy2 - dx2 * dy1, g = sx * dy2 - dx2 * sy, h = dx1 * sy - sx * dy1;
    m[0] = (x[1] - x[0]) * den + g * x[1]; m[1] = (x[3] - x[0]) * den + h * x[3]; m[2] = x[0] * den;
    m[3] = (y[1] - y[0]) * den + g * y[1]; m[4] = (y[3] - y[0]) * den + h * y[3]; m[5] = y[0] * den;
    m[6] = g; m[7] = h; m[8] = den;
}
static int qd_map(const struct qrd *d, s32 u, s32 v, s32 *x16, s32 *y16)   /* u, v: half modules */
{
    const i64 *M = d->M;
    i64 X = M[0] * u + M[1] * v + M[2], Y = M[3] * u + M[4] * v + M[5], Z = M[6] * u + M[7] * v + M[8];
    if (Z <= 0 || X < 0 || Y < 0) return 0;
    while (X >= 0x40000000 || Y >= 0x40000000 || Z >= 0x40000000) { X >>= 1; Y >>= 1; Z >>= 1; }
    if (!Z) return 0;
    *x16 = (s32)qd_div((u32)X, (u32)Z); *y16 = (s32)qd_div((u32)Y, (u32)Z);
    return 1;
}
/* finders at modules 3.5 (TL, TR, BL), the alignment centre at 30.5 -> M; 0 = degenerate */
static int qd_homography(struct qrd *d, const s32 *px, const s32 *py)
{
    static const i64 SX[4] = {7, 67, 61, 7}, SY[4] = {7, 7, 61, 67};   /* TL, TR, AL, BL in half modules */
    i64 qx[4], qy[4], A[9], B[9], J[9];
    for (u32 i = 0; i < 4u; i++) { qx[i] = px[i]; qy[i] = py[i]; }
    qd_sq2quad(B, qx, qy);
    qd_sq2quad(A, SX, SY);
    if (!A[8] || !B[8]) return 0;
    J[0] = A[4] * A[8] - A[5] * A[7]; J[1] = A[2] * A[7] - A[1] * A[8]; J[2] = A[1] * A[5] - A[2] * A[4];  /* adj(A) */
    J[3] = A[5] * A[6] - A[3] * A[8]; J[4] = A[0] * A[8] - A[2] * A[6]; J[5] = A[2] * A[3] - A[0] * A[5];
    J[6] = A[3] * A[7] - A[4] * A[6]; J[7] = A[1] * A[6] - A[0] * A[7]; J[8] = A[0] * A[4] - A[1] * A[3];
    qd_norm(B, 9, (i64)1 << 28);
    qd_norm(J, 9, (i64)1 << 28);
    for (u32 r = 0; r < 3u; r++) for (u32 c = 0; c < 3u; c++)
        d->M[3u * r + c] = B[3u * r] * J[c] + B[3u * r + 1u] * J[3u + c] + B[3u * r + 2u] * J[6u + c];
    qd_norm(d->M, 9, (i64)1 << 40);                    /* keep the Z row's perspective terms: 2^24 rounded them away */
    if (d->M[6] * 37 + d->M[7] * 37 + d->M[8] < 0) for (u32 i = 0; i < 9u; i++) d->M[i] = -d->M[i];
    return 1;
}
/* the alignment pattern near (ax, ay) (Q4), module vectors eu, ev (Q4 per module): best of 25 module tests */
static u32 qd_align_score(const struct qrd *d, s32 x16, s32 y16, const s32 *e)
{
    u32 s = 0;
    for (s32 j = -2; j <= 2; j++) for (s32 i = -2; i <= 2; i++) {
        s32 r = sq_max(sq_abs(i), sq_abs(j));
        u32 want = r != 1;
        s += qd_px(d, (x16 + i * e[0] + j * e[2]) >> 4, (y16 + i * e[1] + j * e[3]) >> 4) == want;
    }
    return s;
}
static void qd_align(struct qrd *d, s32 *ax, s32 *ay, const s32 *e, s32 msz)
{
    s32 bx = *ax, by = *ay, step = msz > 32 ? msz >> 1 : 16, rad = 4 * msz;
    u32 best = qd_align_score(d, bx, by, e), sx = 0, sy = 0, n = 0;
    s32 cx = bx, cy = by;
    for (s32 dy = -rad; dy <= rad; dy += step) for (s32 dx = -rad; dx <= rad; dx += step) {
        u32 s = qd_align_score(d, cx + dx, cy + dy, e);
        if (s > best) { best = s; bx = cx + dx; by = cy + dy; }
    }
    best = 0;
    for (s32 dy = -msz; dy <= msz; dy += 16) for (s32 dx = -msz; dx <= msz; dx += 16) {   /* pixel steps */
        u32 s = qd_align_score(d, bx + dx, by + dy, e);
        if (s > best) { best = s; sx = sy = n = 0; }
        if (s == best) { sx += (u32)(bx + dx + 0x10000); sy += (u32)(by + dy + 0x10000); n++; }
    }
    d->align = best;
    if (best >= 22u && n) { *ax = (s32)qd_div(sx, n) - 0x10000; *ay = (s32)qd_div(sy, n) - 0x10000; }
}
static u32 qd_sample(struct qrd *d)                    /* -> modules into d->mod; the function pattern misfit count */
{
    u32 bad = 0;
    for (u32 y = 0; y < QR_N; y++) for (u32 x = 0; x < QR_N; x++) {
        s32 px, py;
        if (!qd_map(d, (s32)(2u * x + 1u), (s32)(2u * y + 1u), &px, &py)) return 0xFFFFu;
        d->mod[y * QR_N + x] = (u8)qd_px(d, px >> 4, py >> 4);   /* the centre (a 5-point majority measured no gain) */
    }
    static const u8 FO[3][2] = {{0, 0}, {QR_N - 7u, 0}, {0, QR_N - 7u}};
    for (u32 k = 0; k < 3u; k++) for (u32 j = 0; j < 7u; j++) for (u32 i = 0; i < 7u; i++) {
        s32 r = sq_max(sq_abs((s32)i - 3), sq_abs((s32)j - 3));
        bad += d->mod[(FO[k][1] + j) * QR_N + FO[k][0] + i] != (r != 2);
    }
    for (u32 i = 8; i < QR_N - 8u; i++) bad += (d->mod[6u * QR_N + i] != ((i & 1u) == 0u)) + (d->mod[i * QR_N + 6u] != ((i & 1u) == 0u));
    return bad;
}

/* ------------------------------------------------------------------ format, data */
static u32 qd_fmt_word(u32 ecl, u32 mask)              /* = slqs.c qr_format's word */
{
    u32 data = ecl << 3 | mask, rem = data;
    for (u32 i = 0; i < 10u; i++) rem = (rem << 1) ^ ((rem >> 9) * 0x537u);
    return (data << 10 | rem) ^ 0x5412u;
}
static u32 qd_m(const struct qrd *d, u32 x, u32 y) { return d->mod[y * QR_N + x]; }
static int qd_format(struct qrd *d)                    /* -> mask, or -1 (not ECC L / too far from any word) */
{
    u32 a = 0, b = 0;
    for (u32 i = 0; i <= 5u; i++) a |= qd_m(d, 8, i) << i;
    a |= qd_m(d, 8, 7) << 6 | qd_m(d, 8, 8) << 7 | qd_m(d, 7, 8) << 8;
    for (u32 i = 9; i < 15u; i++) a |= qd_m(d, 14u - i, 8) << i;
    for (u32 i = 0; i < 8u; i++) b |= qd_m(d, QR_N - 1u - i, 8) << i;
    for (u32 i = 8; i < 15u; i++) b |= qd_m(d, 8, QR_N - 15u + i) << i;
    u32 bd = 99, be = 0, bm = 0;
    for (u32 e = 0; e < 4u; e++) for (u32 m = 0; m < 8u; m++) {
        u32 w = qd_fmt_word(e, m), da = qd_bits(w ^ a), db = qd_bits(w ^ b);
        u32 dd = da < db ? da : db;
        if (dd < bd) { bd = dd; be = e; bm = m; }
    }
    d->fmt_d = bd;
    return be == 1u && bd <= 3u ? (int)bm : -1;
}
static void qd_read(struct qrd *d, const u8 *fn, u32 mask)   /* unmask + the encoder's zigzag -> d->cw */
{
    u32 i = 0, total = 8u * QD_NCW;
    for (u32 k = 0; k < QD_NCW; k++) d->cw[k] = 0;
    for (int right = (int)QR_N - 1; right >= 1; right -= 2) {
        if (right == 6) right = 5;
        for (u32 v = 0; v < QR_N; v++) for (u32 j = 0; j < 2u; j++) {
            u32 x = (u32)right - j, up = (((u32)right + 1u) & 2u) == 0u, y = up ? QR_N - 1u - v : v;
            if (!fn[y * QR_N + x] && i < total) {
                if (qd_m(d, x, y) ^ mask_bit(mask, x, y)) d->cw[i >> 3] |= (u8)(0x80u >> (i & 7u));
                i++;
            }
        }
    }
}

/* ------------------------------------------------------------------ Reed-Solomon, GF(2^8) of slqs.c's gf_mul, roots a^0..a^25 */
static void qd_gf(struct qrd *d)
{
    u32 x = 1;
    for (u32 i = 0; i < 255u; i++) { d->ex[i] = (u8)x; d->lg[x] = (u8)i; x = gf_mul(x, 2); }
    d->ex[255] = d->ex[0]; d->lg[0] = 0;
}
static u32 qd_mul(const struct qrd *d, u32 a, u32 b)
{
    if (!a || !b) return 0;
    u32 s = (u32)d->lg[a] + d->lg[b];
    return d->ex[s >= 255u ? s - 255u : s];
}
static u32 qd_inv(const struct qrd *d, u32 a) { return d->lg[a] ? d->ex[255u - d->lg[a]] : 1u; }
static u32 qd_pw(const struct qrd *d, u32 e) { while (e >= 255u) e -= 255u; return d->ex[e]; }
static u32 qd_eval(const struct qrd *d, const u8 *p, u32 deg, u32 x)   /* p[0] + p[1] x + ... */
{
    u32 r = 0;
    for (u32 i = deg + 1u; i--;) r = qd_mul(d, r, x) ^ p[i];
    return r;
}
static int qd_syn(const struct qrd *d, u8 *S)          /* 1 = all zero */
{
    u32 z = 1;
    for (u32 j = 0; j < QR_EC_CW; j++) {
        u32 a = qd_pw(d, j), s = 0;
        for (u32 i = 0; i < QD_NCW; i++) s = qd_mul(d, s, a) ^ d->cw[i];
        S[j] = (u8)s; if (s) z = 0;
    }
    return (int)z;
}
static int qd_rs(struct qrd *d)                        /* corrects d->cw in place: errors corrected, or -1 */
{
    u8 S[QR_EC_CW], C[QR_EC_CW + 1u], B[QR_EC_CW + 1u], T[QR_EC_CW + 1u], O[QR_EC_CW];
    if (qd_syn(d, S)) return 0;
    for (u32 i = 0; i <= QR_EC_CW; i++) C[i] = B[i] = 0;
    C[0] = B[0] = 1;
    u32 L = 0, m = 1, b = 1;
    for (u32 n = 0; n < QR_EC_CW; n++) {               /* Berlekamp-Massey */
        u32 e = S[n];
        for (u32 i = 1; i <= L; i++) e ^= qd_mul(d, C[i], S[n - i]);
        if (!e) { m++; continue; }
        u32 f = qd_mul(d, e, qd_inv(d, b));
        for (u32 i = 0; i <= QR_EC_CW; i++) T[i] = C[i];
        for (u32 i = 0; i + m <= QR_EC_CW; i++) C[i + m] ^= (u8)qd_mul(d, f, B[i]);
        if (2u * L <= n) { L = n + 1u - L; for (u32 i = 0; i <= QR_EC_CW; i++) B[i] = T[i]; b = e; m = 1; }
        else m++;
    }
    if (L > QD_T) return -1;
    for (u32 k = 0; k < QR_EC_CW; k++) {               /* Omega = S Lambda mod x^26 */
        u32 o = 0;
        for (u32 j = 0; j <= k; j++) if (k - j <= L) o ^= qd_mul(d, S[j], C[k - j]);
        O[k] = (u8)o;
    }
    u32 found = 0;
    for (u32 i = 0; i < QD_NCW; i++) {                 /* Chien: position i <-> X = a^(133 - i) */
        u32 p = QD_NCW - 1u - i, X = qd_pw(d, p), Xi = qd_inv(d, X);
        if (qd_eval(d, C, L, Xi)) continue;
        u32 dl = 0;                                    /* Lambda'(Xi): the odd terms */
        for (u32 k = 1; k <= L; k += 2u) dl ^= qd_mul(d, C[k], qd_pw(d, (k - 1u) * d->lg[Xi]));
        if (!dl) return -1;
        u32 om = qd_eval(d, O, QR_EC_CW - 1u, Xi);
        d->cw[i] ^= (u8)qd_mul(d, qd_mul(d, X, om), qd_inv(d, dl));   /* Forney, first root a^0 */
        found++;
    }
    if (found != L || !qd_syn(d, S)) return -1;
    return (int)L;
}
static int qd_segment(const struct qrd *d, u8 *out, u32 *len)   /* byte mode only: 0100, count (8), bytes */
{
    if (d->cw[0] >> 4 != 4u) return -1;
    u32 n = (u32)(d->cw[0] & 0xFu) << 4 | d->cw[1] >> 4;
    if (n > QR_DATA_CW - 2u) return -1;
    for (u32 i = 0; i < n; i++) out[i] = (u8)((d->cw[1u + i] & 0xFu) << 4 | d->cw[2u + i] >> 4);
    *len = n;
    return 0;
}

/* ------------------------------------------------------------------ one geometric try */
static int qd_try(struct qrd *d, const struct qd_cand *tl, const struct qd_cand *tr, const struct qd_cand *bl,
                  const u8 *fn, u8 *out, u32 *len)
{
    s32 e[4], px[4], py[4];
    e[0] = (s32)qd_div((u32)(tr->x - tl->x + 0x40000), 30u) - (s32)qd_div(0x40000u, 30u);   /* Q4 per module */
    e[1] = (s32)qd_div((u32)(tr->y - tl->y + 0x40000), 30u) - (s32)qd_div(0x40000u, 30u);
    e[2] = (s32)qd_div((u32)(bl->x - tl->x + 0x40000), 30u) - (s32)qd_div(0x40000u, 30u);
    e[3] = (s32)qd_div((u32)(bl->y - tl->y + 0x40000), 30u) - (s32)qd_div(0x40000u, 30u);
    s32 msz = (s32)(((u32)(tl->m + tr->m + bl->m) * 0x5556u) >> 16);   /* the mean finder module, Q4 */
    if (msz < 16) msz = 16;
    s32 ax = tl->x + 27 * (e[0] + e[2]), ay = tl->y + 27 * (e[1] + e[3]);
    qd_align(d, &ax, &ay, e, msz);
    px[0] = tl->x; py[0] = tl->y; px[1] = tr->x; py[1] = tr->y; px[2] = ax; py[2] = ay; px[3] = bl->x; py[3] = bl->y;
    if (!qd_homography(d, px, py)) return QD_GEOM;
    d->pat_bad = qd_sample(d);
    if (d->pat_bad > 40u) return QD_GEOM;
    int mask = qd_format(d);
    if (mask < 0) return QD_FORMAT;
    d->mask = (u32)mask;
    qd_read(d, fn, (u32)mask);
    int ne = qd_rs(d);
    if (ne < 0) return QD_RS;
    d->rs_n = (u32)ne;
    return qd_segment(d, out, len) ? QD_SEGMENT : QD_OK;
}
static i64 qd_d2(const struct qd_cand *a, const struct qd_cand *b)
{
    i64 dx = a->x - b->x, dy = a->y - b->y;
    return dx * dx + dy * dy;
}
/* img: Y8, w x h, row stride; fn: the encoder's function map (any V5 code's struct qr .fn); out: >= 106 bytes.
 * -> QD_OK and the byte segment (plain bytes, as printed), or the furthest stage reached */
static int qrd_decode(struct qrd *d, const u8 *img, u32 w, u32 h, u32 stride, const u8 *fn, u8 *out, u32 *len)
{
    u32 cw_ = w > QD_NB * QD_BS ? QD_NB * QD_BS : w, ch = h > QD_NB * QD_BS ? QD_NB * QD_BS : h;
    d->img = img + ((h - ch) >> 1) * stride + ((w - cw_) >> 1);
    d->w = (s32)cw_; d->h = (s32)ch; d->stride = stride;
    d->why = QD_NOFIND; d->tries = 0; d->mirror = 0; *len = 0;
    qd_gf(d);
    qd_blocks(d);
    qd_scan(d);
    if (d->nc < 3u) return (int)(d->why = QD_NOFIND);
    d->why = QD_NOTRIPLE;
    u32 top = d->nc < QD_TOP ? d->nc : QD_TOP;
    for (u32 i = 0; i < top; i++) for (u32 j = i + 1u; j < top; j++) for (u32 k = j + 1u; k < top; k++) {
        const struct qd_cand *p[3] = {&d->c[i], &d->c[j], &d->c[k]};
        s32 mmin = p[0]->m, mmax = p[0]->m;
        for (u32 q = 1; q < 3u; q++) { if (p[q]->m < mmin) mmin = p[q]->m; if (p[q]->m > mmax) mmax = p[q]->m; }
        if (mmax > 2 * mmin) continue;
        i64 d01 = qd_d2(p[0], p[1]), d02 = qd_d2(p[0], p[2]), d12 = qd_d2(p[1], p[2]);
        const struct qd_cand *tl, *a, *b;
        i64 s1, s2, hy;
        if (d12 >= d01 && d12 >= d02) { tl = p[0]; a = p[1]; b = p[2]; s1 = d01; s2 = d02; hy = d12; }
        else if (d02 >= d01) { tl = p[1]; a = p[0]; b = p[2]; s1 = d01; s2 = d12; hy = d02; }
        else { tl = p[2]; a = p[0]; b = p[1]; s1 = d02; s2 = d12; hy = d01; }
        if (4 * s1 < s2 || 4 * s2 < s1) continue;        /* side lengths within 1:2 */
        i64 sum = s1 + s2, diff = hy - sum;
        if (4 * qd_abs64(diff) > sum) continue;           /* right angle within ~ +-15 degrees */
        i64 mm = (i64)(mmin + mmax) * (mmin + mmax) >> 2;   /* (mean m)^2, Q8 */
        if (s1 < 400 * mm || s1 > 1600 * mm || s2 < 400 * mm || s2 > 1600 * mm) continue;   /* 20..40 modules */
        i64 cr = (i64)(a->x - tl->x) * (b->y - tl->y) - (i64)(a->y - tl->y) * (b->x - tl->x);
        const struct qd_cand *tr = cr > 0 ? a : b, *bl = cr > 0 ? b : a;
        if (d->tries >= QD_TRIES) return (int)d->why;
        d->tries++;
        int r = qd_try(d, tl, tr, bl, fn, out, len);
        if (r == QD_FORMAT || r == QD_GEOM) {            /* a mirrored symbol: the transpose */
            int r2 = qd_try(d, tl, bl, tr, fn, out, len);
            if (r2 == QD_OK) { d->mirror = 1; r = QD_OK; }
            else if (r2 > r) r = r2;
        }
        if (r == QD_OK) return (int)(d->why = QD_OK);
        if ((u32)r > d->why) d->why = (u32)r;
    }
    return (int)d->why;
}

/* ------------------------------------------------------------------ SensorLab payload */
/* bytes from qrd_decode (stock = 0) or from the stock decoder, which always returns byte - i (FUN_c05c5bc0; stock = 1)
 * -> 1 and the 37-char code when it is exactly QR_URL + 37 base64url chars */
static int qrd_sensorlab(const u8 *b, u32 len, u32 stock, char *code)
{
    static const char P[] = QR_URL;
    const u32 np = sizeof P - 1u;
    if (len != np + QR_CHARS) return 0;
    for (u32 i = 0; i < len; i++) {
        u32 c = (b[i] + (stock ? i : 0u)) & 0xFFu;
        if (i < np) { if (c != (u8)P[i]) return 0; continue; }
        u32 ok = 0;
        for (u32 k = 0; k < 64u; k++) if ((u8)B64U[k] == c) ok = 1;
        if (!ok) return 0;
        code[i - np] = (char)c;
    }
    code[QR_CHARS] = 0;
    return 1;
}
static void qrd_to_stock(u8 *b, u32 len) { for (u32 i = 0; i < len; i++) b[i] = (u8)(b[i] - i); }   /* our bytes -> the stock convention */
enum { QU_OK, QU_CHAR, QU_CRC, QU_PAD, QU_VERSION };
static int qr_unpack(const char *code, u32 *f)         /* the inverse of slqs.c qr_pack */
{
    u8 b[28];
    for (u32 i = 0; i < sizeof b; i++) b[i] = 0;
    for (u32 i = 0; i < QR_CHARS; i++) {
        u32 v = 64;
        for (u32 k = 0; k < 64u; k++) if (B64U[k] == code[i]) v = k;
        if (v == 64u) return QU_CHAR;
        for (u32 j = 0; j < 6u; j++) { u32 q = 6u * i + j; if (v >> (5u - j) & 1u) b[q >> 3] |= (u8)(0x80u >> (q & 7u)); }
    }
    if (code[QR_CHARS]) return QU_CHAR;
    u32 crc = 0, n = 0, got = 0;
    for (u32 i = 0; i < QF_BITS; i++) {
        u32 top = (crc >> 7 & 1u) ^ (b[i >> 3] >> (7u - (i & 7u)) & 1u);
        crc = crc << 1 & 0xFFu;
        if (top) crc ^= 0x07u;
    }
    for (u32 i = QF_BITS; i < QF_BITS + 8u; i++) got = got << 1 | (b[i >> 3] >> (7u - (i & 7u)) & 1u);
    if (got != crc) return QU_CRC;
    if (b[(QF_BITS + 8u) >> 3] >> (7u - ((QF_BITS + 8u) & 7u)) & 1u) return QU_PAD;
    for (u32 i = 0; i < N_QF; i++) {
        u32 v = 0;
        for (u32 w = QF_W[i]; w--; n++) v = v << 1 | (b[n >> 3] >> (7u - (n & 7u)) & 1u);
        f[i] = v;
    }
    return f[0] == 1u ? QU_OK : QU_VERSION;
}
