// Lossless JPEG XL modular encoder kernels (grey, one channel, gradient predictor).
//
// enc_tokens: one thread per pixel. Neighbours follow the decoder's edge rules inside each
//   group (groups are independent images), the MA tree picks the context, the residual
//   becomes a hybrid-uint token plus raw bits, and the context histogram is counted.
// enc_ans: one thread per group. rANS runs over the group's symbols in reverse, then the
//   section is written forward in the order the decoder reads it: group header, initial
//   state, and per symbol its renormalisation word (if any) followed by its raw bits.
#include <metal_stdlib>
using namespace metal;

struct Frame {
    uint w, h, gshift, gcols;
    uint nnodes;       // tree nodes
    uint nctx;         // tree leaves (histogram rows per frame)
    uint ngroups;      // symbols are interleaved by group in runs of 8, see sidx()
    uint stride;       // symbols per frame in that layout (ngroups << 2 * gshift)
    uint split, msb, lsb; // hybrid uint config shared by all contexts
};

// Tree node (BFS order, like the bitstream): prop < 0 is a leaf with ctx = ~prop;
// otherwise children are left (value > threshold) and right, absolute node indices.
struct Node { int prop, threshold, left, right; };

inline int grad(int w, int n, int nw) {
    int lo = min(w, n), hi = max(w, n);
    return min(max(lo, w + n - nw), hi);
}

inline int prop_value(int p, int W, int N, int NW, int NE, int NN, int WW, int NWW, int x, int y) {
    switch (p) {
    case 2: return y;
    case 3: return x;
    case 4: return abs(N);
    case 5: return abs(W);
    case 6: return N;
    case 7: return W;
    case 8: return x > 0 ? W - (WW + NW - NWW) : W;
    case 9: return W + N - NW;
    case 10: return W - NW;
    case 11: return NW - N;
    case 12: return N - NE;
    case 13: return N - NN;
    case 14: return W - WW;
    default: return 0; // 0/1 (channel, group) are constant here; 15 (WP) is not used
    }
}

// Neighbours of frame pixel (X, Y) inside its group, with the decoder's edge rules
// (decode_channel): groups are independent images.
struct Nb { int W, N, NW, NE, NN, WW, NWW, x, y, cur, gw; uint g; };

inline Nb neighbours(device const ushort *px, constant Frame &f, uint X, uint Y) {
    uint gs = 1u << f.gshift;
    uint gx = X >> f.gshift, gy = Y >> f.gshift;
    Nb b;
    b.x = int(X & (gs - 1)); b.y = int(Y & (gs - 1));
    b.gw = int(min(gs, f.w - gx * gs));
    b.g = gy * f.gcols + gx;
    int x = b.x, y = b.y;
#define at(xx, yy) int(px[(gy * gs + uint(yy)) * f.w + gx * gs + uint(xx)])
    b.cur = at(x, y);
    b.W = x > 0 ? at(x - 1, y) : y > 0 ? at(x, y - 1) : 0;
    b.N = y > 0 ? at(x, y - 1) : b.W;
    b.NW = x > 0 && y > 0 ? at(x - 1, y - 1) : b.W;
    b.NE = x + 1 < b.gw && y > 0 ? at(x + 1, y - 1) : b.N;
    b.NN = y > 1 ? at(x, y - 2) : b.N;
    b.WW = x > 1 ? at(x - 2, y) : b.W;
    b.NWW = x > 1 && y > 0 ? at(x - 2, y - 1) : b.WW;
#undef at
    return b;
}

// Symbol i of group g: runs of 8 consecutive symbols per group, groups side by side. The
// token kernel's lanes (neighbouring pixels of one group) write few cache lines, and the
// ANS threads (one per group) read 8 symbols per line.
inline uint sidx(uint i, uint g, uint ngroups) { return ((i >> 3) * ngroups + g) * 8 + (i & 7); }

inline int prop_of(int p, Nb b) { return prop_value(p, b.W, b.N, b.NW, b.NE, b.NN, b.WW, b.NWW, b.x, b.y); }

// Gradient residual as a hybrid-uint token plus raw bits.
inline uint residual_token(Nb b, constant Frame &f, thread uint &nbits, thread uint &bits) {
    int r = b.cur - grad(b.W, b.N, b.NW);
    uint v = r >= 0 ? uint(r) << 1 : (uint(-r) << 1) - 1;
    nbits = 0; bits = 0;
    if (v < (1u << f.split)) return v;
    uint e = 31 - clz(v);
    uint m = v - (1u << e);
    nbits = e - f.msb - f.lsb;
    bits = (v >> f.lsb) & ((1u << nbits) - 1);
    return (1u << f.split) + ((e - f.split) << (f.msb + f.lsb)) + ((m >> (e - f.msb)) << f.lsb) + (m & ((1u << f.lsb) - 1));
}

// Batched: z is the frame; planes, symbols and histograms are frame after frame. Symbols
// are stored group-interleaved (sidx). HIST: count context histograms (only needed while
// learning a model; frames are coded with the model's tables).
template <bool HIST>
inline void tokens(device const ushort *planes,
                   constant Frame &f, device const Node *tree,
                   device uint *syms,          // ctx << 8 | token
                   device uint *extras,        // nbits | bits << 5
                   device atomic_uint *hists,  // [frame][ctx][256]
                   uint3 gid) {
    if (gid.x >= f.w || gid.y >= f.h) return;
    ulong npx = ulong(f.w) * f.h;
    device const ushort *px = planes + gid.z * npx;
    device uint *sym = syms + ulong(gid.z) * f.stride;
    device uint *extra = extras + ulong(gid.z) * f.stride;
    device atomic_uint *hist = hists + ulong(gid.z) * f.nctx * 256;
    Nb b = neighbours(px, f, gid.x, gid.y);
#ifdef NO_TREE
    uint ctx = 0;
#else
    int n = 0;
    for (uint guard = 0; tree[n].prop >= 0 && guard < f.nnodes; guard++) {
        Node t = tree[n];
        n = prop_of(t.prop, b) > t.threshold ? t.left : t.right;
    }
    uint ctx = uint(~tree[n].prop);
#endif
    uint nbits, bits;
    uint token = residual_token(b, f, nbits, bits);
    uint i = sidx(uint(b.y * b.gw + b.x), b.g, f.ngroups);
    sym[i] = ctx << 8 | token;
    extra[i] = nbits | bits << 5;
    if (HIST) atomic_fetch_add_explicit(&hist[ctx * 256 + token], 1, memory_order_relaxed);
}

#define TOKEN_ARGS device const ushort *planes [[buffer(0)]], constant Frame &f [[buffer(1)]], \
    device const Node *tree [[buffer(2)]], device uint *syms [[buffer(4)]], device uint *extras [[buffer(5)]], \
    device atomic_uint *hists [[buffer(6)]], uint3 gid [[thread_position_in_grid]]
kernel void enc_tokens_hist(TOKEN_ARGS) { tokens<true>(planes, f, tree, syms, extras, hists, gid); }
kernel void enc_tokens(TOKEN_ARGS) { tokens<false>(planes, f, tree, syms, extras, hists, gid); }

// ---------------------------------------------------------------- tree learning
//
// A sample of pixels (every `stride`-th, jittered) is described by its token and, per
// candidate property, the index of the property value among that property's thresholds.
// The tree grows one level per round: every sample walks the partial tree and adds its
// token to the histogram of its frontier node for each (property, threshold index).

#define NPROPS 13   // properties 2..14
#define NQ 32       // threshold indices per property (31 thresholds)
#define NT 64       // tokens counted while learning

inline uint2 sample_xy(uint s, uint stride, constant Frame &f) {
    uint h = s * 2654435761u;
    uint i = s * stride + (h >> 16) % stride;
    return uint2(i % f.w, i / f.w);
}

// Per property: value histogram over [-4096, 4096) (clamped), for the thresholds.
kernel void learn_values(device const ushort *px [[buffer(0)]],
                         constant Frame &f [[buffer(1)]],
                         constant uint &stride [[buffer(2)]],
                         constant uint &nsamples [[buffer(3)]],
                         device atomic_uint *vhist [[buffer(4)]],   // [NPROPS][8192]
                         uint s [[thread_position_in_grid]]) {
    if (s >= nsamples) return;
    uint2 p = sample_xy(s, stride, f);
    Nb b = neighbours(px, f, p.x, p.y);
    for (int k = 0; k < NPROPS; k++) {
        int v = clamp(prop_of(k + 2, b), -4096, 4095);
        atomic_fetch_add_explicit(&vhist[k * 8192 + uint(v + 4096)], 1, memory_order_relaxed);
    }
}

// Per sample: threshold index per property (number of thresholds below the value) and token.
kernel void learn_quantise(device const ushort *px [[buffer(0)]],
                           constant Frame &f [[buffer(1)]],
                           constant uint &stride [[buffer(2)]],
                           constant uint &nsamples [[buffer(3)]],
                           device const int *thr [[buffer(4)]],    // [NPROPS][NQ - 1], ascending
                           device uchar *q [[buffer(5)]],          // [nsamples][NPROPS]
                           device uchar *tok [[buffer(6)]],
                           uint s [[thread_position_in_grid]]) {
    if (s >= nsamples) return;
    uint2 p = sample_xy(s, stride, f);
    Nb b = neighbours(px, f, p.x, p.y);
    for (int k = 0; k < NPROPS; k++) {
        int v = prop_of(k + 2, b);
        uint lo = 0, hi = NQ - 1; // count of thresholds < v
        while (lo < hi) { uint m = (lo + hi) / 2; if (v > thr[k * (NQ - 1) + m]) lo = m + 1; else hi = m; }
        q[s * NPROPS + uint(k)] = uchar(lo);
    }
    uint nbits, bits;
    tok[s] = uchar(min(residual_token(b, f, nbits, bits), uint(NT - 1)));
}

// Learning tree node: branch on (property index, threshold index) with value index > k
// going left; leaf with frontier slot (>= 0, histogram wanted) or -1 (finished).
struct LNode { int prop, k, left, right; };

inline float xlogx(float x) { return x > 0 ? x * log2(x) : 0; }

// Entropy saved by splitting frontier slot `slot` on (property p, threshold index k):
// cost(all) - cost(value index > k) - cost(the rest). One thread per (slot, p, k).
kernel void learn_gain(device const uint *hist [[buffer(0)]],   // [slot][NPROPS][NQ][NT]
                       constant uint &nslots [[buffer(1)]],
                       device float *gain [[buffer(2)]],         // [slot][NPROPS][NQ - 1]
                       uint id [[thread_position_in_grid]]) {
    uint k = id % (NQ - 1), p = (id / (NQ - 1)) % NPROPS, slot = id / ((NQ - 1) * NPROPS);
    if (slot >= nslots) return;
    device const uint *h = hist + (ulong(slot) * NPROPS + p) * NQ * NT;
    float nl = 0, nr = 0, sl = 0, sr = 0, sa = 0;
    for (uint t = 0; t < NT; t++) {
        uint l = 0, r = 0;
        for (uint q = 0; q < NQ; q++) {
            uint c = h[q * NT + t];
            if (q > k) l += c; else r += c;
        }
        nl += l; nr += r;
        sl += xlogx(float(l)); sr += xlogx(float(r)); sa += xlogx(float(l + r));
    }
    float all = xlogx(nl + nr) - sa, left = xlogx(nl) - sl, right = xlogx(nr) - sr;
    gain[id] = all - left - right;
}

kernel void learn_hist(device const uchar *q [[buffer(0)]],
                       device const uchar *tok [[buffer(1)]],
                       constant uint &nsamples [[buffer(2)]],
                       device const LNode *tree [[buffer(3)]],
                       device atomic_uint *hist [[buffer(4)]],  // [frontier][NPROPS][NQ][NT]
                       uint s [[thread_position_in_grid]]) {
    if (s >= nsamples) return;
    device const uchar *qs = q + s * NPROPS;
    int n = 0;
    while (tree[n].prop >= 0) {
        LNode t = tree[n];
        n = int(qs[t.prop]) > t.k ? t.left : t.right;
    }
    int slot = tree[n].k;
    if (slot < 0) return;
    uint t = tok[s];
    device atomic_uint *h = hist + ulong(slot) * NPROPS * NQ * NT;
    for (int k = 0; k < NPROPS; k++)
        atomic_fetch_add_explicit(&h[(uint(k) * NQ + qs[k]) * NT + t], 1, memory_order_relaxed);
}

// Encoding table per context: freq[ctx][256], start[ctx][256] (offset of the symbol's
// slots in rev), rev[ctx][4096] (slot k of a symbol -> ANS state index).
struct Writer {
    device uint *out;
    uint word, used;   // pending bits (LSB first)
    uint n, cap;       // words written, capacity (n past cap = overflow, nothing stored)
    void put(uint v, uint k) {
        if (k == 0) return;
        word |= v << used;
        if (used + k >= 32) {
            if (n < cap) out[n] = word;
            n++;
            word = used ? v >> (32 - used) : 0;
            used = used + k - 32;
        } else {
            used += k;
        }
    }
};

#define ANS_INIT 0x130000u

// Batched: thread g codes group g % ngroups of frame g / ngroups with that frame's tables.
kernel void enc_ans(device const uint *syms [[buffer(0)]],
                    device const uint *extras [[buffer(1)]],
                    device const uint *goff [[buffer(2)]],
                    device const uint2 *sinfo [[buffer(3)]],   // freq | start << 13, floor((2^32-1) / freq)
                    device const ushort *unused [[buffer(4)]],
                    device const ushort *rev [[buffer(5)]],
                    device uint *words [[buffer(6)]],   // scratch: per symbol renorm word | 1 << 16
                    device uint *out [[buffer(7)]],     // per group, out_words each
                    device uint *out_bytes [[buffer(8)]],
                    constant uint &ngroups [[buffer(9)]],
                    constant uint &out_words [[buffer(10)]],
                    device const ushort *cluster [[buffer(11)]],   // ctx -> table
                    constant uint &nframes [[buffer(12)]],
                    constant uint &nclusters [[buffer(13)]],
                    constant uint &npx [[buffer(14)]],
                    uint gg [[thread_position_in_grid]]) {
    if (gg >= ngroups * nframes) return;
    uint z = gg / ngroups, g = gg % ngroups;
    device const uint *sym = syms + ulong(z) * npx;   // npx: per-frame stride here
    device const uint *extra = extras + ulong(z) * npx;
    device uint *words_z = words + ulong(z) * npx;
    uint tbase = z * nclusters; // this frame's tables
    uint n = goff[g + 1] - goff[g];
    uint state = ANS_INIT;
    for (uint i = n; i > 0; i--) {
        uint at = sidx(i - 1, g, ngroups);
        uint s = sym[at];
        uint c = tbase + cluster[s >> 8], t = s & 255;
        uint2 si = sinfo[c * 256 + t];
        uint fr = si.x & 0x1fff;
        uint w = 0;
        if ((state >> 20) >= fr) { w = (state & 0xffff) | 0x10000; state >>= 16; }
        words_z[at] = w;
        // state / fr from a 32-bit reciprocal (off by at most one, fixed exactly)
        uint q = mulhi(state, si.y);
        uint r = state - q * fr;
        if (r >= fr) { q++; r -= fr; }
        state = (q << 12) + rev[c * 4096 + (si.x >> 13) + r];
    }
    Writer wr = {out + ulong(gg) * out_words, 0, 0, 0, out_words};
    wr.put(1, 1);  // use_global_tree
    wr.put(1, 1);  // default weighted-predictor header
    wr.put(0, 2);  // no transforms
    wr.put(state & 0xffff, 16);
    wr.put(state >> 16, 16);
#ifndef NO_FORWARD
    for (uint i = 0; i < n; i++) {
        uint at = sidx(i, g, ngroups);
        uint w = words_z[at];
        if (w) wr.put(w & 0xffff, 16);
        uint e = extra[at];
        wr.put(e >> 5, e & 31);
    }
#endif
    uint bytes = wr.n * 4 + (wr.used + 7) / 8;
    if (wr.used && wr.n < wr.cap) wr.out[wr.n] = wr.word;
    out_bytes[gg] = wr.n + (wr.used ? 1 : 0) > wr.cap ? 0xffffffffu : bytes;
}
