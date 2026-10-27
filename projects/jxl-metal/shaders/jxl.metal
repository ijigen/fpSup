// JPEG XL lossless (modular) decoder on Metal.
//
// jxl_parse_frame: one thread per frame. Headers, TOC, LfGlobal (MA tree +
//   entropy code tables) are written into that frame's arena.
// jxl_decode_group: one thread per (frame, group). Entropy decode, MA tree,
//   prediction and reconstruction straight into the frame plane.
//
// Ported from the structure of J40 (public domain, third_party/j40/j40.h);
// results are checked against libjxl output, not against J40.
#include <metal_stdlib>
using namespace metal;

// ---------------------------------------------------------------- layout

// Frame arena header (ints).
enum {
    H_ERR = 0, H_WIDTH, H_HEIGHT, H_BPP, H_GSHIFT, H_GCOLS, H_GROWS, H_NGROUPS,
    H_NLFGROUPS, H_TREE, H_SPEC, H_GROUPS, H_FEATURES, H_ERRPOS, H_WP_TREE,
    H_TOP, H_DBG0, H_DBG1, H_DBG2, H_DBG3,
    H_PALETTE, H_PAL, H_PAL_N, H_PAL_DELTAS, H_PAL_DPRED, // global single-channel palette
    H_CTREE, H_LEAVES, H_LINFO, H_ROOT, H_LINFO_OK, H_QT16, // shared compact global tree
    H_SIZE = 32,
};

// Feature bits (what the stream actually uses).
enum {
    F_LZ77 = 1, F_PREFIX = 2, F_ANS = 4, F_GLOBAL_TRANSFORM = 8, F_GROUP_TRANSFORM = 16,
    F_LOCAL_TREE = 32, F_WP = 64, F_PERMUTED_TOC = 128,
};

// Errors (first one wins). Value * 1000 + detail is stored in H_ERR.
enum {
    E_SHORT = 1, E_SIG, E_UNSUPPORTED, E_ENUM, E_PAD, E_HUFF, E_ANS, E_CLUSTER, E_LZ77,
    E_TREE, E_TOC, E_ARENA, E_RANGE, E_EXCESS, E_ANS_FINAL, E_TOKEN, E_WINDOW, E_PRED,
};

// Spec record (ints).
enum {
    S_NUM_DIST = 0, S_LZ77, S_MIN_SYMBOL, S_MIN_LENGTH, S_LZ_CFG /*4 ints*/,
    S_USE_PREFIX = 8, S_LOG_ALPHA, S_NUM_CLUSTERS, S_CMAP, S_CLUSTERS, S_CR, S_TBASE, S_SIZE = 16,
};

// Cluster record (ints). cfg = split, msb, lsb, max_token.
enum {
    C_CFG = 0, C_A /*prefix: max_len / ans: D offset*/ = 4, C_B /*fast / alias*/, C_C /*syms*/,
    C_FIRST /*16*/ = 8, C_BASE /*16*/ = 24, C_COUNT /*16*/ = 40, C_SIZE = 56,
};

#define FAST_BITS 8
#define ANS_INIT_STATE 0x130000u

// ---------------------------------------------------------------- reader

struct Ctx {
    device const uchar *d;
    uint pos, end;
    ulong buf;
    uint n;
    int err;
    device int *A;   // arena of this frame
    uint top, cap;   // bump allocator (ints)
};

inline void fail(thread Ctx &c, int code, int detail) {
    if (!c.err) c.err = code * 1000 + detail;
}

// Tops the buffer up to >= 57 bits. Away from the section end this is one unaligned
// 64-bit read assembled from aligned words (c.d is 4-byte aligned; the source
// buffer is padded so reading a little past a section is safe).
inline void refill(thread Ctx &c) {
    if (c.pos + 8 <= c.end) {
        uint k = (64 - c.n) >> 3;
        device const uint *w = (device const uint *)(c.d + (c.pos & ~3u));
        uint sh = (c.pos & 3) * 8;
        ulong lo = ulong(w[0]) | (ulong(w[1]) << 32);
        ulong v = sh ? (lo >> sh) | (ulong(w[2]) << (64 - sh)) : lo;
        if (k < 8) v &= (1ul << (k * 8)) - 1;
        c.buf |= v << c.n;
        c.pos += k;
        c.n += k * 8;
        return;
    }
    while (c.n <= 56 && c.pos < c.end) {
        c.buf |= ulong(c.d[c.pos++]) << c.n;
        c.n += 8;
    }
}

inline uint peek(thread Ctx &c, uint k) {
    if (c.n < k) refill(c);
    return uint(c.buf & ((1ul << k) - 1));
}

inline void consume(thread Ctx &c, uint k) {
    if (c.n < k) { fail(c, E_SHORT, 0); c.buf = 0; c.n = 0; return; }
    c.buf >>= k;
    c.n -= k;
}

inline uint u(thread Ctx &c, uint k) {
    if (k == 0) return 0;
    uint v = peek(c, k);
    consume(c, k);
    return v;
}

inline uint u32s(thread Ctx &c, uint o0, uint n0, uint o1, uint n1, uint o2, uint n2, uint o3, uint n3) {
    uint sel = u(c, 2);
    uint o = sel == 0 ? o0 : sel == 1 ? o1 : sel == 2 ? o2 : o3;
    uint n = sel == 0 ? n0 : sel == 1 ? n1 : sel == 2 ? n2 : n3;
    return u(c, n) + o;
}

inline ulong u64v(thread Ctx &c) {
    uint sel = u(c, 2);
    ulong ret = u(c, sel * 4);
    if (sel < 3) {
        ret += 17u >> (8 - sel * 4);
    } else {
        for (uint shift = 12; shift < 64 && u(c, 1); shift += 8)
            ret |= ulong(u(c, shift < 56 ? 8 : 64 - shift)) << shift;
    }
    return ret;
}

inline uint enum_v(thread Ctx &c) {
    uint v = u32s(c, 0, 0, 1, 0, 2, 4, 18, 6);
    if (v >= 31) fail(c, E_ENUM, 0);
    return v;
}

inline uint at_most(thread Ctx &c, uint max) {
    if (max == 0) return 0;
    uint v = u(c, 32 - clz(max));
    if (v > max) fail(c, E_RANGE, 0);
    return v;
}

inline uint u8v(thread Ctx &c) {
    if (u(c, 1)) { uint n = u(c, 3); return u(c, n) + (1u << n); }
    return 0;
}

inline void zero_pad(thread Ctx &c) {
    if (u(c, c.n & 7)) fail(c, E_PAD, 0);
}

inline void skip_bits(thread Ctx &c, ulong n) {
    while (n > 0 && !c.err) { uint k = uint(min(n, 32ul)); u(c, k); n -= k; }
}

inline uint byte_pos(thread Ctx &c) { return c.pos - c.n / 8; }

inline void finish_section(thread Ctx &c) {
    zero_pad(c);
    if (!c.err && (c.n != 0 || c.pos != c.end)) fail(c, E_EXCESS, 0);
}

inline int unpack_signed(uint v) { return int(v >> 1) ^ -int(v & 1); }

inline uint alloc(thread Ctx &c, uint n) {
    uint o = c.top;
    if (c.top + n > c.cap) { fail(c, E_ARENA, 0); return H_SIZE; }
    c.top += n;
    return o;
}

// ---------------------------------------------------------------- hybrid uint

inline void read_hcfg(thread Ctx &c, int log_alpha, device int *cfg) {
    int split = int(at_most(c, uint(log_alpha)));
    int msb = 0, lsb = 0;
    if (split != log_alpha) {
        msb = int(at_most(c, uint(split)));
        lsb = int(at_most(c, uint(split - msb)));
    }
    cfg[0] = split; cfg[1] = msb; cfg[2] = lsb;
    cfg[3] = (1 << split) + ((30 - split) << (lsb + msb)) - 1;
}

inline int hybrid_int(thread Ctx &c, int token, device const int *cfg) {
    int split_exp = cfg[0], msb = cfg[1], lsb = cfg[2], split = 1 << split_exp;
    if (token < split) return token;
    if (token > cfg[3]) { fail(c, E_TOKEN, 0); token = cfg[3]; }
    int in_token = msb + lsb;
    int midbits = split_exp - in_token + ((token - split) >> in_token);
    int mid = int(u(c, uint(midbits)));
    int top = 1 << msb;
    int lo = token & ((1 << lsb) - 1);
    int hi = (token >> lsb) & (top - 1);
    return ((top | hi) << (midbits + lsb)) | ((mid << lsb) | lo);
}

// ---------------------------------------------------------------- prefix codes

// Canonical table from code lengths. Writes fast table (2^FAST_BITS entries of
// sym << 8 | 0x80 | len), first/base/count per length and the symbol list.
inline void build_prefix(thread Ctx &c, device const int *lengths, int nsym, device int *cl) {
    device int *first = cl + C_FIRST, *base = cl + C_BASE, *count = cl + C_COUNT;
    for (int i = 0; i < 16; i++) count[i] = 0;
    int nonzero = 0, max_len = 0, only = 0;
    for (int s = 0; s < nsym; s++) {
        int l = lengths[s];
        if (l) { count[l]++; nonzero++; max_len = max(max_len, l); only = s; }
    }
    uint fast = alloc(c, 1u << FAST_BITS);
    uint syms = alloc(c, uint(max(nonzero, 1)));
    if (c.err) return;
    device int *F = c.A + fast, *S = c.A + syms;
    for (int i = 0; i < (1 << FAST_BITS); i++) F[i] = 0;
    cl[C_B] = int(fast);
    cl[C_C] = int(syms);
    if (nonzero <= 1) { cl[C_A] = 0; S[0] = only; return; }
    cl[C_A] = max_len;
    first[0] = 0; base[0] = 0; first[1] = 0; base[1] = 0;
    for (int l = 2; l < 16; l++) {
        first[l] = (first[l - 1] + count[l - 1]) << 1;
        base[l] = base[l - 1] + count[l - 1];
    }
    int next[16];
    for (int l = 0; l < 16; l++) next[l] = first[l];
    for (int s = 0; s < nsym; s++) {
        int l = lengths[s];
        if (!l) continue;
        int code = next[l]++;
        S[base[l] + (code - first[l])] = s;
        if (l <= FAST_BITS) {
            int rev = int(reverse_bits(uint(code)) >> (32 - l));
            for (int k = rev; k < (1 << FAST_BITS); k += 1 << l) F[k] = (s << 8) | 0x80 | l;
        }
    }
}

inline int prefix_decode(thread Ctx &c, device const int *A, device const int *cl) {
    int max_len = cl[C_A];
    device const int *S = A + cl[C_C];
    if (max_len == 0) return S[0];
    int e = A[cl[C_B] + int(peek(c, FAST_BITS))];
    if (e & 0x80) { consume(c, uint(e & 15)); return e >> 8; }
    uint p = peek(c, 15);
    int code = 0;
    for (int l = 1; l <= max_len; l++) {
        code = (code << 1) | int((p >> (l - 1)) & 1);
        int off = code - cl[C_FIRST + l];
        if (off >= 0 && off < cl[C_COUNT + l]) {
            consume(c, uint(l));
            return S[cl[C_BASE + l] + off];
        }
    }
    fail(c, E_HUFF, 9);
    return 0;
}

constant int L0TABLE[16] = {
    0x00002, 0x40002, 0x30002, 0x20003, 0x00002, 0x40002, 0x30002, 0x10004,
    0x00002, 0x40002, 0x30002, 0x20003, 0x00002, 0x40002, 0x30002, 0x50004,
};
constant uchar L1ZIGZAG[18] = {1,2,3,4,0,5,17,6,16,7,8,9,10,11,12,13,14,15};

// RFC 7932 section 3 prefix code for a cluster with alphabet size l2size.
inline void read_prefix(thread Ctx &c, int l2size, device int *cl) {
    uint lens = alloc(c, uint(max(l2size, 18)));
    if (c.err) return;
    device int *L = c.A + lens;
    for (int i = 0; i < l2size; i++) L[i] = 0;
    if (l2size == 1) { build_prefix(c, L, 1, cl); cl[C_A] = 0; c.A[cl[C_C]] = 0; return; }

    int hskip = int(u(c, 2));
    if (hskip == 1) { // simple
        int nsym = int(u(c, 2)) + 1, syms[4];
        for (int i = 0; i < nsym; i++) {
            syms[i] = int(at_most(c, uint(l2size - 1)));
            for (int j = 0; j < i; j++) if (syms[i] == syms[j]) fail(c, E_HUFF, 1);
        }
        if (nsym == 1) { build_prefix(c, L, l2size, cl); cl[C_A] = 0; c.A[cl[C_C]] = syms[0]; return; }
        if (nsym == 2) { L[syms[0]] = 1; L[syms[1]] = 1; }
        else if (nsym == 3) { L[syms[0]] = 1; L[syms[1]] = 2; L[syms[2]] = 2; }
        else if (u(c, 1)) { L[syms[0]] = 1; L[syms[1]] = 2; L[syms[2]] = 3; L[syms[3]] = 3; }
        else { for (int i = 0; i < 4; i++) L[syms[i]] = 2; }
        build_prefix(c, L, l2size, cl);
        return;
    }

    // complex: layer 1 code lengths with the fixed layer 0 code
    int l1len[18];
    for (int i = 0; i < 18; i++) l1len[i] = 0;
    int total = 0, zeros = hskip, i = hskip;
    for (; i < 18 && total < 32; i++) {
        int e = L0TABLE[peek(c, 4)];
        consume(c, uint(e & 15));
        int code = e >> 16;
        l1len[L1ZIGZAG[i]] = code;
        if (code) total += 32 >> code; else zeros++;
    }
    // RFC 7932 3.5: valid if the lengths fill the code space, or if exactly one
    // code-length symbol is used (it then takes 0 bits). J40 rejects the latter.
    int used = i - zeros;
    if (used == 0 || (used > 1 && total != 32)) { fail(c, E_HUFF, 2); return; }
    uint l1 = alloc(c, C_SIZE);
    uint l1lens = alloc(c, 18);
    if (c.err) return;
    for (int k = 0; k < 18; k++) c.A[l1lens + k] = l1len[k];
    build_prefix(c, c.A + l1lens, 18, c.A + l1);

    // layer 2 code lengths
    int prev = 8, prev_rep = 0;
    total = 0;
    for (i = 0; i < l2size && total < 32768 && !c.err; ) {
        int code = prefix_decode(c, c.A, c.A + l1);
        if (code < 16) {
            L[i++] = code;
            if (code) { total += 32768 >> code; prev = code; }
            prev_rep = 0;
        } else if (code == 16) {
            if (prev_rep < 0) prev_rep = 0;
            int rep = (prev_rep > 0 ? 4 * prev_rep - 5 : 3) + int(u(c, 2));
            if (i + (rep - prev_rep) > l2size) { fail(c, E_HUFF, 3); return; }
            total += (32768 * (rep - prev_rep)) >> prev;
            for (; prev_rep < rep; prev_rep++) L[i++] = prev;
        } else {
            if (prev_rep > 0) prev_rep = 0;
            int rep = (prev_rep < 0 ? 8 * prev_rep + 13 : -3) - int(u(c, 3));
            if (i + (prev_rep - rep) > l2size) { fail(c, E_HUFF, 4); return; }
            for (; prev_rep > rep; prev_rep--) L[i++] = 0;
        }
    }
    if (total != 32768) { fail(c, E_HUFF, 5); return; }
    build_prefix(c, L, l2size, cl);
}

// ---------------------------------------------------------------- ANS

constant int LOGCOUNT[20] = {
    0xa0003, -16, 0x70003, 0x30004, 0x60003, 0x80003, 0x90003, 0x50004,
    0xa0003, 0x40004, 0x70003, 0x10004, 0x60003, 0x80003, 0x90003, 0x20004,
    0x00011, 0xb0022, 0xc0003, 0xd0043,
};

inline int logcount_code(thread Ctx &c) {
    int e = LOGCOUNT[peek(c, 4)];
    if (e >= 0) { consume(c, uint(e & 15)); return e >> 16; }
    consume(c, 4);
    for (int k = 16; k < 20; k++) {
        e = LOGCOUNT[k];
        uint code = uint(e >> 4) & 0xfff, len = uint(e & 15);
        if (peek(c, len) == code) { consume(c, len); return e >> 16; }
    }
    fail(c, E_ANS, 1);
    return 0;
}

inline void read_ans_table(thread Ctx &c, int log_alpha, device int *D) {
    int table_size = 1 << log_alpha;
    switch (u(c, 2)) {
    case 1: {
        int v = int(u8v(c));
        for (int i = 0; i < table_size; i++) D[i] = 0;
        if (v >= table_size) { fail(c, E_ANS, 2); return; }
        D[v] = 4096;
        break;
    }
    case 3: {
        int v1 = int(u8v(c)), v2 = int(u8v(c));
        if (v1 == v2 || v1 >= table_size || v2 >= table_size) { fail(c, E_ANS, 3); return; }
        for (int i = 0; i < table_size; i++) D[i] = 0;
        D[v1] = int(u(c, 12));
        D[v2] = 4096 - D[v1];
        break;
    }
    case 2: {
        int alpha_size = int(u8v(c)) + 1;
        if (alpha_size > table_size) { fail(c, E_ANS, 4); return; }
        int d = 4096 / alpha_size, bias = 4096 % alpha_size, i = 0;
        for (; i < bias; i++) D[i] = d + 1;
        for (; i < alpha_size; i++) D[i] = d;
        for (; i < table_size; i++) D[i] = 0;
        break;
    }
    default: {
        int len = u(c, 1) ? (u(c, 1) ? (u(c, 1) ? 3 : 2) : 1) : 0;
        int shift = int(u(c, uint(len))) + (1 << len) - 1;
        if (shift > 13) { fail(c, E_ANS, 5); return; }
        int alpha_size = int(u8v(c)) + 3;
        int codes[259], ncodes = 0, omit_log = -1, i = 0;
        while (i < alpha_size && !c.err) {
            if (ncodes >= 259) { fail(c, E_ANS, 6); return; }
            int code = logcount_code(c);
            if (code < 13) {
                i++;
                codes[ncodes++] = code;
                if (omit_log < code) omit_log = code;
            } else {
                code = int(u8v(c)) + 4;
                i += code;
                codes[ncodes++] = -code;
            }
        }
        if (i != alpha_size || omit_log < 0) { fail(c, E_ANS, 7); return; }
        int omit_pos = -1, n = 0, total = 0;
        for (i = 0; i < ncodes && n < table_size; i++) {
            int code = codes[i];
            if (code < 0) {
                int prev = n > 0 ? D[n - 1] : 0;
                if (prev < 0) { fail(c, E_ANS, 8); return; }
                code = min(-code, table_size - n);
                total += prev * code;
                while (code-- > 0) D[n++] = prev;
            } else if (code == omit_log) {
                omit_pos = n;
                omit_log = -1;
                D[n++] = -1;
            } else if (code < 2) {
                total += code;
                D[n++] = code;
            } else {
                code--;
                int bitcount = min(max(0, shift - ((12 - code) >> 1)), code);
                code = (1 << code) + (int(u(c, uint(bitcount))) << (code - bitcount));
                total += code;
                D[n++] = code;
            }
        }
        for (; n < table_size; n++) D[n] = 0;
        if (omit_pos < 0 || total > 4096) { fail(c, E_ANS, 9); return; }
        D[omit_pos] = 4096 - total;
    }
    }
}

// Alias table: 3 ints per bucket (cutoff, offset_or_next, symbol).
inline void init_alias(thread Ctx &c, device const int *D, int log_alpha, device int *B) {
    int log_bucket = 12 - log_alpha, bucket_size = 1 << log_bucket, table_size = 1 << log_alpha;
    int i = 0, j;
    for (; i < table_size && !D[i]; i++);
    for (j = i + 1; j < table_size && !D[j]; j++);
    if (i < table_size && j >= table_size) {
        for (j = 0; j < table_size; j++) { B[3*j+2] = i; B[3*j+1] = j << log_bucket; B[3*j] = 0; }
        return;
    }
    int uu = -1, o = -1;
    for (i = 0; i < table_size; i++) {
        int cutoff = D[i];
        B[3*i] = cutoff;
        if (cutoff > bucket_size) { B[3*i+1] = o; o = i; }
        else if (cutoff < bucket_size) { B[3*i+1] = uu; uu = i; }
        else { B[3*i+2] = i; B[3*i+1] = 0; }
    }
    while (o >= 0) {
        if (uu < 0) { fail(c, E_ANS, 10); return; }
        int by = bucket_size - B[3*uu];
        int tmp = B[3*uu+1];
        B[3*o] -= by;
        B[3*uu+2] = o;
        B[3*uu+1] = B[3*o] - B[3*uu];
        uu = tmp;
        if (B[3*o] < bucket_size) {
            tmp = B[3*o+1]; B[3*o+1] = uu; uu = o; o = tmp;
        } else if (B[3*o] == bucket_size) {
            tmp = B[3*o+1]; B[3*o+1] = 0; o = tmp;
        }
    }
}

// Packed ANS bucket (one 64-bit load per symbol):
//   cutoff:8 | alias symbol:8 | alias offset:16 (signed) | D[i]:13 | D[alias symbol]:13
inline ulong ans_fetch(thread Ctx &c, thread uint &state, uint log_bucket, device const ulong *T) {
    if (state == 0) { state = u(c, 16); state |= u(c, 16) << 16; }
    return T[(state & 0xfff) >> log_bucket];
}

// Finishes an ANS symbol whose bucket entry was already loaded (lets the load overlap other work).
inline int ans_finish(thread Ctx &c, thread uint &state, uint log_bucket, ulong e) {
    uint index = state & 0xfff;
    uint i = index >> log_bucket, pos = index & ((1u << log_bucket) - 1);
    bool own = pos < uint(e & 0xff);
    uint symbol = own ? i : uint(e >> 8) & 0xff;
    int offset = own ? 0 : int(short(ushort(e >> 16)));
    uint freq = own ? uint(e >> 32) & 0x1fff : uint(e >> 45) & 0x1fff;
    state = freq * (state >> 12) + uint(offset) + pos;
    if (state < (1u << 16)) state = (state << 16) | u(c, 16);
    return int(symbol);
}

inline int ans_decode(thread Ctx &c, thread uint &state, uint log_bucket, device const ulong *T) {
    if (state == 0) { state = u(c, 16); state |= u(c, 16) << 16; }
    uint index = state & 0xfff;
    uint i = index >> log_bucket, pos = index & ((1u << log_bucket) - 1);
    ulong e = T[i];
    bool own = pos < uint(e & 0xff);
    uint symbol = own ? i : uint(e >> 8) & 0xff;
    int offset = own ? 0 : int(short(ushort(e >> 16)));
    uint freq = own ? uint(e >> 32) & 0x1fff : uint(e >> 45) & 0x1fff;
    state = freq * (state >> 12) + uint(offset) + pos;
    if (state < (1u << 16)) state = (state << 16) | u(c, 16);
    return int(symbol);
}

// ---------------------------------------------------------------- entropy code

// Compact cluster record (CR, 4 ints): table (packed ANS or prefix fast table),
// hybrid config packed split | msb << 5 | lsb << 10, max token, full cluster record.
enum { CR_TABLE = 0, CR_CFG, CR_MAXTOK, CR_CL, CR_SIZE };

struct CodeSt {
    uint ans;
    int num_to_copy, copy_pos, num_decoded;
    device int *window;
    int window_mask;
    // spec fields hoisted into registers
    bool use_prefix, lz77;
    uint log_bucket;
    int num_dist, min_symbol, min_length, lz_cfg, lz_max;
    uint cmap, cr, lz_cr;
};

inline int pack_cfg(device const int *cfg) { return cfg[0] | (cfg[1] << 5) | (cfg[2] << 10); }

inline void init_code(thread CodeSt &cs, device const int *A, uint spec, device int *window, int window_cap) {
    device const int *S = A + spec;
    cs.ans = 0; cs.num_to_copy = 0; cs.copy_pos = 0; cs.num_decoded = 0;
    cs.window = window; cs.window_mask = window_cap - 1;
    cs.use_prefix = S[S_USE_PREFIX] != 0;
    cs.lz77 = S[S_LZ77] != 0;
    cs.log_bucket = uint(12 - S[S_LOG_ALPHA]);
    cs.num_dist = S[S_NUM_DIST];
    cs.min_symbol = S[S_MIN_SYMBOL];
    cs.min_length = S[S_MIN_LENGTH];
    cs.lz_cfg = pack_cfg(S + S_LZ_CFG);
    cs.lz_max = S[S_LZ_CFG + 3];
    cs.cmap = uint(S[S_CMAP]);
    cs.cr = uint(S[S_CR]);
    cs.lz_cr = cs.lz77 ? cs.cr + CR_SIZE * uint(A[cs.cmap + cs.num_dist - 1]) : 0;
}

inline int hybrid_packed(thread Ctx &c, int token, int cfg, int max_token) {
    int split_exp = cfg & 31, msb = (cfg >> 5) & 31, lsb = (cfg >> 10) & 31, split = 1 << split_exp;
    if (token < split) return token;
    if (token > max_token) { fail(c, E_TOKEN, 0); token = max_token; }
    int in_token = msb + lsb;
    int midbits = split_exp - in_token + ((token - split) >> in_token);
    int mid = int(u(c, uint(midbits)));
    int top = 1 << msb;
    int lo = token & ((1 << lsb) - 1);
    int hi = (token >> lsb) & (top - 1);
    return ((top | hi) << (midbits + lsb)) | ((mid << lsb) | lo);
}

inline int prefix_decode_cr(thread Ctx &c, device const int *A, device const int *cr) {
    device const int *cl = A + cr[CR_CL];
    if (cl[C_A] == 0) return A[cl[C_C]];
    int e = A[cr[CR_TABLE] + int(peek(c, FAST_BITS))];
    if (e & 0x80) { consume(c, uint(e & 15)); return e >> 8; }
    return prefix_decode(c, A, cl);
}

inline int code_cluster(thread Ctx &c, thread CodeSt &cs, device const int *A, device const int *cr) {
    return cs.use_prefix ? prefix_decode_cr(c, A, cr)
                         : ans_decode(c, cs.ans, cs.log_bucket, (device const ulong *)(A + cr[CR_TABLE]));
}

constant uchar SPECIAL_DISTANCES[120] = {
    0x71, 0x80, 0x81, 0x61, 0x72, 0x90, 0x82, 0x62, 0x91, 0x51, 0x92, 0x52,
    0x73, 0xa0, 0x83, 0x63, 0xa1, 0x41, 0x93, 0x53, 0xa2, 0x42, 0x74, 0xb0,
    0x84, 0x64, 0xb1, 0x31, 0xa3, 0x43, 0x94, 0x54, 0xb2, 0x32, 0x75, 0xa4,
    0x44, 0xb3, 0x33, 0xc0, 0x85, 0x65, 0xc1, 0x21, 0x95, 0x55, 0xc2, 0x22,
    0xb4, 0x34, 0xa5, 0x45, 0xc3, 0x23, 0x76, 0xd0, 0x86, 0x66, 0xd1, 0x11,
    0x96, 0x56, 0xd2, 0x12, 0xb5, 0x35, 0xc4, 0x24, 0xa6, 0x46, 0xd3, 0x13,
    0x77, 0xe0, 0x87, 0x67, 0xc5, 0x25, 0xe1, 0x01, 0xb6, 0x36, 0xd4, 0x14,
    0x97, 0x57, 0xe2, 0x02, 0xa7, 0x47, 0xe3, 0x03, 0xc6, 0x26, 0xd5, 0x15,
    0xf0, 0xb7, 0x37, 0xe4, 0x04, 0xf1, 0xf2, 0xd6, 0x16, 0xf3, 0xc7, 0x27,
    0xe5, 0x05, 0xf4, 0xd7, 0x17, 0xe6, 0x06, 0xf5, 0xe7, 0x07, 0xf6, 0xf7,
};

// DecodeHybridVarLenUint with the cluster already resolved (tree leaves store CR offsets).
inline int decode_token(thread Ctx &c, thread CodeSt &cs, device const int *A, device const int *cr, int dist_mult,
                        bool prefetched = false, ulong pre = 0) {
    if (cs.num_to_copy > 0) {
        cs.num_to_copy--;
        int v = cs.window[cs.copy_pos++ & cs.window_mask];
        cs.window[cs.num_decoded++ & cs.window_mask] = v;
        return v;
    }
    int token = prefetched ? ans_finish(c, cs.ans, cs.log_bucket, pre) : code_cluster(c, cs, A, cr);
    if (cs.lz77 && token >= cs.min_symbol) {
        if (!cs.window) { fail(c, E_WINDOW, 0); return 0; }
        device const int *lz = A + cs.lz_cr;
        int num_to_copy = hybrid_packed(c, token - cs.min_symbol, cs.lz_cfg, cs.lz_max) + cs.min_length;
        token = code_cluster(c, cs, A, lz);
        int distance = hybrid_packed(c, token, lz[CR_CFG], lz[CR_MAXTOK]);
        if (!dist_mult) {
            distance++;
        } else if (distance >= 120) {
            distance -= 119;
        } else {
            int special = SPECIAL_DISTANCES[distance];
            distance = max(1, ((special >> 4) - 7) + dist_mult * (special & 7));
        }
        distance = min(min(distance, cs.num_decoded), 1 << 20);
        cs.copy_pos = cs.num_decoded - distance;
        if (distance == 0) { // libjxl: window initially zero
            for (int k = 0; k <= cs.window_mask; k++) cs.window[k] = 0;
        }
        cs.num_to_copy = num_to_copy - 1;
        int v = cs.window[cs.copy_pos++ & cs.window_mask];
        cs.window[cs.num_decoded++ & cs.window_mask] = v;
        return v;
    }
    token = hybrid_packed(c, token, cr[CR_CFG], cr[CR_MAXTOK]);
    if (cs.lz77) {
        if (cs.num_decoded > cs.window_mask) { fail(c, E_WINDOW, 1); return 0; }
        cs.window[cs.num_decoded++ & cs.window_mask] = token;
    }
    return token;
}

// Common case (ANS, no LZ77): nothing else of the code state needs to stay live.
// Lean token decode. The caller tops the bit buffer up once per pixel (>= 40 bits), which
// covers one ANS renormalisation (16) plus the hybrid-uint extra bits, so the bit
// reads below are branch-free. A read past the section end shows up as c.n wrapping
// and is reported after the loop.
// Leaf info word for the lean path: ANS table offset / 2 (17 bits) | hybrid config << 17.
inline int decode_token_ans(thread Ctx &c, thread uint &ans, uint log_bucket, device const int *A, int info) {
    device const ulong *T = (device const ulong *)(A + ((info & 0x1ffff) << 1));
    uint index = ans & 0xfff;
    uint i = index >> log_bucket, pos = index & ((1u << log_bucket) - 1);
    ulong e = T[i];
    bool own = pos < uint(e & 0xff);
    uint symbol = own ? i : uint(e >> 8) & 0xff;
    int offset = own ? 0 : int(short(ushort(e >> 16)));
    uint freq = own ? uint(e >> 32) & 0x1fff : uint(e >> 45) & 0x1fff;
    uint st = freq * (ans >> 12) + uint(offset) + pos;
    uint renorm = st < (1u << 16) ? 16u : 0u;
    ans = renorm ? (st << 16) | uint(c.buf & 0xffff) : st;
    c.buf >>= renorm;
    c.n -= renorm;

    int token = int(symbol), cfg = info >> 17;
    int split_exp = cfg & 31, msb = (cfg >> 5) & 31, lsb = (cfg >> 10) & 31, in_token = msb + lsb;
    bool big = token >= (1 << split_exp);
    if (big && token > (1 << split_exp) + ((30 - split_exp) << in_token) - 1) fail(c, E_TOKEN, 0);
    int t = max(token - (1 << split_exp), 0);
    int midbits = big ? split_exp - in_token + (t >> in_token) : 0;
    uint mid = uint(c.buf) & ((1u << midbits) - 1);
    c.buf >>= midbits;
    c.n -= uint(midbits);
    int top = 1 << msb, lo = token & ((1 << lsb) - 1), hi = (token >> lsb) & (top - 1);
    return big ? ((top | hi) << (midbits + lsb)) | (int(mid) << lsb) | lo : token;
}

inline int decode_ctx(thread Ctx &c, thread CodeSt &cs, device const int *A, int ctx, int dist_mult) {
    if (cs.num_to_copy == 0 && ctx >= cs.num_dist) { fail(c, E_TOKEN, 1); return 0; }
    return decode_token(c, cs, A, A + cs.cr + CR_SIZE * uint(A[cs.cmap + ctx]), dist_mult);
}

inline void finish_code(thread Ctx &c, thread CodeSt &cs) {
    if (cs.use_prefix) return;
    if (cs.ans) {
        if (cs.ans != ANS_INIT_STATE) fail(c, E_ANS_FINAL, 0);
    } else {
        if (u(c, 16) != (ANS_INIT_STATE & 0xffff) || u(c, 16) != (ANS_INIT_STATE >> 16)) fail(c, E_ANS_FINAL, 1);
    }
}

// Builds the compact cluster records and packed ANS tables for a spec.
inline void finalize_spec(thread Ctx &c, device int *S) {
    int nc = S[S_NUM_CLUSTERS];
    uint cr = alloc(c, uint(CR_SIZE * nc));
    if (c.err) return;
    S[S_CR] = int(cr);
    for (int i = 0; i < nc && !c.err; i++) {
        device int *cl = c.A + S[S_CLUSTERS] + C_SIZE * i;
        device int *R = c.A + cr + CR_SIZE * i;
        R[CR_CFG] = pack_cfg(cl + C_CFG);
        R[CR_MAXTOK] = cl[C_CFG + 3];
        R[CR_CL] = S[S_CLUSTERS] + C_SIZE * i;
        if (S[S_USE_PREFIX]) { R[CR_TABLE] = cl[C_B]; continue; }
        int la = S[S_LOG_ALPHA], ts = 1 << la, bs = 1 << (12 - la);
        // packed tables were reserved before the D/B scratch (read_code_spec), so their
        // offsets stay low enough for the lean path's 17-bit leaf info
        uint t = uint(S[S_TBASE]) + uint(2 * ts + 2) * uint(i);
        R[CR_TABLE] = int(t);
        device const int *D = c.A + cl[C_A];
        device const int *B = c.A + cl[C_B];
        device ulong *T = (device ulong *)(c.A + t);
        for (int j = 0; j < ts; j++) {
            int cut = B[3 * j], off = B[3 * j + 1], sym = B[3 * j + 2];
            if (cut >= bs) { cut = bs; sym = j; off = 0; }
            T[j] = ulong(uint(cut) & 0xff) | (ulong(uint(sym) & 0xff) << 8) | (ulong(uint(off) & 0xffff) << 16) |
                   (ulong(uint(D[j]) & 0x1fff) << 32) | (ulong(uint(D[sym]) & 0x1fff) << 45);
        }
    }
}

// ---------------------------------------------------------------- code spec

// Nested code specs (cluster maps) recurse at most twice; templates keep it static.
template <int DEPTH> uint read_code_spec(thread Ctx &c, int num_dist_signed, thread int &features);

template <int DEPTH>
inline void read_cluster_map(thread Ctx &c, int num_dist, int max_allowed, device int *map,
                             thread int &num_clusters, thread int &features) {
    if (max_allowed > num_dist) max_allowed = num_dist;
    if (num_dist == 1) { map[0] = 0; num_clusters = 1; return; }
    if (u(c, 1)) {
        int nbits = int(u(c, 2));
        for (int i = 0; i < num_dist; i++) {
            map[i] = int(u(c, uint(nbits)));
            if (map[i] >= max_allowed) fail(c, E_CLUSTER, 0);
        }
    } else {
        int use_mtf = int(u(c, 1));
        uint spec = read_code_spec<DEPTH + 1>(c, num_dist <= 2 ? -1 : 1, features);
        if (c.err) return;
        uint win = 0;
        if (c.A[spec + S_LZ77]) win = alloc(c, 1u << 12);
        CodeSt cs;
        init_code(cs, c.A, spec, win ? c.A + win : (device int *)0, 1 << 12);
        for (int i = 0; i < num_dist && !c.err; i++) {
            int index = decode_ctx(c, cs, c.A, 0, 0);
            if (index >= max_allowed) fail(c, E_CLUSTER, 1);
            map[i] = index;
        }
        finish_code(c, cs);
        if (use_mtf) {
            int mtf[256];
            for (int i = 0; i < 256; i++) mtf[i] = i;
            for (int i = 0; i < num_dist; i++) {
                int j = map[i], moved = mtf[j];
                map[i] = moved;
                for (; j > 0; j--) mtf[j] = mtf[j - 1];
                mtf[0] = moved;
            }
        }
    }
    uint seen[8] = {0, 0, 0, 0, 0, 0, 0, 0};
    for (int i = 0; i < num_dist; i++) seen[map[i] >> 5] |= 1u << (map[i] & 31);
    int i = 0;
    for (; i < 256 && ((seen[i >> 5] >> (i & 31)) & 1); i++);
    num_clusters = i;
    for (; i < 256 && !((seen[i >> 5] >> (i & 31)) & 1); i++);
    if (i != 256) fail(c, E_CLUSTER, 2);
}

template <int DEPTH>
uint read_code_spec(thread Ctx &c, int num_dist_signed, thread int &features) {
    int allow_lz77 = num_dist_signed > 0;
    int num_dist = abs(num_dist_signed);
    uint s = alloc(c, S_SIZE);
    if (c.err) return s;
    device int *S = c.A + s;
    S[S_LZ77] = int(u(c, 1));
    if (S[S_LZ77]) {
        features |= F_LZ77;
        if (!allow_lz77) fail(c, E_LZ77, 0);
        S[S_MIN_SYMBOL] = int(u32s(c, 224, 0, 512, 0, 4096, 0, 8, 15));
        S[S_MIN_LENGTH] = int(u32s(c, 3, 0, 4, 0, 5, 2, 9, 8));
        read_hcfg(c, 8, S + S_LZ_CFG);
        num_dist++;
    } else {
        S[S_MIN_SYMBOL] = S[S_MIN_LENGTH] = 0x7fffffff;
    }
    S[S_NUM_DIST] = num_dist;
    uint cmap = alloc(c, uint(num_dist));
    if (c.err) return s;
    S[S_CMAP] = int(cmap);
    int num_clusters = 0;
    read_cluster_map<DEPTH>(c, num_dist, 256, c.A + cmap, num_clusters, features);
    if (c.err) return s;
    S[S_NUM_CLUSTERS] = num_clusters;
    uint cls = alloc(c, uint(C_SIZE * num_clusters));
    if (c.err) return s;
    S[S_CLUSTERS] = int(cls);
    S[S_USE_PREFIX] = int(u(c, 1));
    if (S[S_USE_PREFIX]) {
        features |= F_PREFIX;
        for (int i = 0; i < num_clusters; i++) read_hcfg(c, 15, c.A + cls + C_SIZE * i + C_CFG);
        int counts[256];
        for (int i = 0; i < num_clusters; i++) {
            if (u(c, 1)) {
                int n = int(u(c, 4));
                counts[i] = 1 + (1 << n) + int(u(c, uint(n)));
                if (counts[i] > (1 << 15)) fail(c, E_HUFF, 6);
            } else {
                counts[i] = 1;
            }
        }
        for (int i = 0; i < num_clusters && !c.err; i++) read_prefix(c, counts[i], c.A + cls + C_SIZE * i);
    } else {
        features |= F_ANS;
        S[S_LOG_ALPHA] = 5 + int(u(c, 2));
        int log_alpha = S[S_LOG_ALPHA];
        uint tbase = alloc(c, uint((2 << log_alpha) + 2) * uint(num_clusters) + 1);
        S[S_TBASE] = int(tbase + (tbase & 1)); // 8-byte aligned
        for (int i = 0; i < num_clusters; i++) read_hcfg(c, log_alpha, c.A + cls + C_SIZE * i + C_CFG);
        for (int i = 0; i < num_clusters && !c.err; i++) {
            device int *cl = c.A + cls + C_SIZE * i;
            uint D = alloc(c, 1u << log_alpha);
            uint B = alloc(c, 3u << log_alpha);
            if (c.err) return s;
            cl[C_A] = int(D);
            cl[C_B] = int(B);
            read_ans_table(c, log_alpha, c.A + D);
            if (!c.err) init_alias(c, c.A + D, log_alpha, c.A + B);
        }
    }
    if (!c.err) finalize_spec(c, S);
    return s;
}

template <>
uint read_code_spec<3>(thread Ctx &c, int, thread int &) {
    fail(c, E_CLUSTER, 9);
    return 0;
}

// ---------------------------------------------------------------- MA tree

// Node: 4 ints. Branch: prop (<0, ~prop = property), value, leftoff, rightoff.
//       Leaf: ctx (>=0), predictor, offset, multiplier.
inline void read_tree(thread Ctx &c, thread uint &tree_out, thread uint &spec_out, thread int &features) {
    uint tspec = read_code_spec<0>(c, 6, features);
    if (c.err) return;
    uint win = 0;
    if (c.A[tspec + S_LZ77]) win = alloc(c, 1u << 14);
    CodeSt cs;
    init_code(cs, c.A, tspec, win ? c.A + win : (device int *)0, 1 << 14);
    uint tree = c.top; // nodes grow at the arena top while decoding
    int idx = 0, ctx_id = 0, nodes_left = 1;
    while (nodes_left-- > 0 && !c.err) {
        uint nd = alloc(c, 4);
        if (c.err) return;
        device int *n = c.A + nd;
        int prop = decode_ctx(c, cs, c.A, 1, 0);
        if (prop > 0) {
            n[0] = -prop;
            n[1] = unpack_signed(uint(decode_ctx(c, cs, c.A, 0, 0)));
            n[2] = ++nodes_left;
            n[3] = ++nodes_left;
        } else {
            n[0] = ctx_id++;
            n[1] = decode_ctx(c, cs, c.A, 2, 0);
            n[2] = unpack_signed(uint(decode_ctx(c, cs, c.A, 3, 0)));
            int shift = decode_ctx(c, cs, c.A, 4, 0);
            int val = decode_ctx(c, cs, c.A, 5, 0);
            if (shift >= 31 || ((val + 1) >> (31 - shift)) != 0) fail(c, E_TREE, 1);
            n[3] = (val + 1) << shift;
            if (n[1] >= 14) fail(c, E_PRED, 0);
        }
        idx++;
        if (idx > (1 << 20)) fail(c, E_TREE, 2);
    }
    finish_code(c, cs);
    // nodes are contiguous (decoding never allocates), so `tree` indexes them directly
    tree_out = tree;
    spec_out = read_code_spec<0>(c, ctx_id, features);
    if (c.err) return;
    // leaves point straight at their compact cluster record
    device const int *S = c.A + spec_out;
    for (int k = 0; k < idx; k++) {
        device int *n = c.A + tree + 4 * k;
        if (n[0] >= 0) n[0] = S[S_CR] + CR_SIZE * c.A[S[S_CMAP] + n[0]];
    }
}

// ---------------------------------------------------------------- prediction

constant int DIV24P1[64] = {
    0x1000000, 0x800000, 0x555555, 0x400000, 0x333333, 0x2aaaaa, 0x249249, 0x200000,
    0x1c71c7, 0x199999, 0x1745d1, 0x155555, 0x13b13b, 0x124924, 0x111111, 0x100000,
    0xf0f0f, 0xe38e3, 0xd7943, 0xccccc, 0xc30c3, 0xba2e8, 0xb2164, 0xaaaaa,
    0xa3d70, 0x9d89d, 0x97b42, 0x92492, 0x8d3dc, 0x88888, 0x84210, 0x80000,
    0x7c1f0, 0x78787, 0x75075, 0x71c71, 0x6eb3e, 0x6bca1, 0x69069, 0x66666,
    0x63e70, 0x61861, 0x5f417, 0x5d174, 0x5b05b, 0x590b2, 0x57262, 0x55555,
    0x53978, 0x51eb8, 0x50505, 0x4ec4e, 0x4d487, 0x4bda1, 0x4a790, 0x49249,
    0x47dc1, 0x469ee, 0x456c7, 0x44444, 0x4325c, 0x42108, 0x41041, 0x40000,
};

// floor(2^24 / d) for d in 1..64 without a table: float estimate, then exact integer fix-up
// (lane-varying indices into a constant table serialise; this is a few ALU ops).
inline int div24(int d) {
#ifdef DIV_TABLE
    return DIV24P1[d - 1];
#else
    int q = int(16777216.0f / float(d));
    q -= q * d > 16777216 ? 1 : 0;
    q += (q + 1) * d <= 16777216 ? 1 : 0;
    return q;
#endif
}

struct WpParams { short p1, p2, p3[5], w[4]; };

inline int floor_lg(uint x) { return 31 - int(clz(x)); }

inline int grad(int w, int n, int nw) {
    int lo = min(w, n), hi = max(w, n);
    return min(max(lo, w + n - nw), hi);
}

// Row state shared by all jobs of one dispatch, interleaved by job index so that
// the 32 lanes of a SIMD group touching the same x hit one memory transaction.
struct Rows {
    device int *px;   // [3][maxw][njobs]   pixel rows y%3
    device int *err;  // [2][maxw][5][njobs] WP errors rows y&1
    uint njobs, maxw, lane;
};

inline device int &RP(Rows r, int row, int x) { return r.px[(ulong(row) * r.maxw + uint(x)) * r.njobs + r.lane]; }
// Lean layout: pixel rows as short; WP errors as 3 words (e0 | e1 << 16, e2 | e3 << 16, e4).
inline device short &RPS(Rows r, int row, int x) {
    return ((device short *)r.px)[(ulong(row) * r.maxw + uint(x)) * r.njobs + r.lane];
}
inline device int &RE3(Rows r, int row, int x, int k) {
    return r.err[((ulong(row) * r.maxw + uint(x)) * 3 + uint(k)) * r.njobs + r.lane];
}
template <bool GENERIC> inline int rp_load(Rows r, int row, int x) { return GENERIC ? RP(r, row, x) : int(RPS(r, row, x)); }

inline device int &RE(Rows r, int row, int x, int k) {
    return r.err[((ulong(row) * r.maxw + uint(x)) * 5 + uint(k)) * r.njobs + r.lane];
}

// Decodes one modular channel of size w x h into `px` (row stride `stride`).
// Neighbours slide through registers; only x+2 of the row above, x of the row two
// above and the WP errors at x+1 of the row above are loaded per pixel.
// Compact tree: branches only, 2 ints each: threshold, prop | left << 8 | right << 20.
// A child reference with bit 11 set is a leaf index into the leaf records (8 ints:
// CR copy (table, cfg, max token, cluster), predictor, offset, multiplier).
enum { LR_PRED = 4, LR_OFF, LR_MUL, LR_SIZE = 8 };
// Compact node word: prop (4 bits; properties 16+ are not supported) | left ref << 4 |
// right ref << 18, refs 14 bits: branch index or LEAF_BIT | leaf index (8192 of each).
#define LEAF_BIT 0x2000
inline int nprop(int v) { return v & 15; }
inline int nleft(int v) { return (v >> 4) & 0x3fff; }
inline int nright(int v) { return (v >> 18) & 0x3fff; }
#ifndef TG_NODES
#define TG_NODES 64
#endif

// ROWS: keep the row ring (false for 1-row meta channels, which may be wider than it).
// GENERIC: prefix codes or LZ77 present; otherwise the lean ANS-only token path.
struct Nb { int pw, pn, pnw, pne, pnn, pww, pnww, tew, ten, tenw, tene; };

// One 8-byte load per tree node (threshold, node word).
inline int2 node2(threadgroup const int *T, int ref) { return ((threadgroup const int2 *)T)[ref]; }
inline int2 node2(device const int *T, int ref) { return ((device const int2 *)T)[ref]; }
inline int4 node4(threadgroup const int *T, int ref) { return ((threadgroup const int4 *)T)[ref]; }
inline int4 node4(device const int *T, int ref) { return ((device const int4 *)T)[ref]; }

// Two-level nodes for multi-property trees (16 bytes, indexed like the compact tree):
// x = threshold | threshold of the child taken when val > threshold << 16,
// y = other child's threshold (16) | props of node, first, second child << 16/20/24,
// z, w = four 12-bit grandchild refs (compact-tree refs). Needs 16-bit thresholds and
// properties 0..15; returns false otherwise.
inline bool build_qt16(thread Ctx &c, device const int *CT, int nbranch, thread uint &out) {
    out = alloc(c, uint(4 * max(nbranch, 1)) + 3);
    out = (out + 3) & ~3u;
    if (c.err) return false;
    for (int b = 0; b < nbranch; b++) {
        int t = CT[2 * b], v = CT[2 * b + 1];
        int kid[2] = {nleft(v), nright(v)}, kt[2], kp[2], g[4];
        if (t < -32768 || t > 32767) return false;
        for (int s2 = 0; s2 < 2; s2++) {
            int k = kid[s2];
            if (k & LEAF_BIT) { kt[s2] = 0; kp[s2] = 0; g[2 * s2] = g[2 * s2 + 1] = k; continue; }
            int kv = CT[2 * k + 1];
            kt[s2] = CT[2 * k]; kp[s2] = nprop(kv);
            if (kp[s2] > 15 || kt[s2] < -32768 || kt[s2] > 32767) return false;
            g[2 * s2] = nleft(kv); g[2 * s2 + 1] = nright(kv);
        }
        device int *q = c.A + out + 4 * b;
        q[0] = (t & 0xffff) | (kt[0] << 16);
        q[1] = (kt[1] & 0xffff) | (nprop(v) << 16) | (kp[0] << 20) | (kp[1] << 24);
        q[2] = g[0] | (g[1] << 14) | ((g[2] & 0xf) << 28); // four 14-bit grandchild refs
        q[3] = (g[2] >> 4) | (g[3] << 10);
    }
    return true;
}

// Two-level nodes for single-property trees, packed in 8 bytes so the threadgroup tree
// stays within 16 KB (more costs occupancy): three 12-bit signed thresholds (node, child
// taken when val > node, the other child) and four 7-bit grandchild refs (0x40 = leaf).

inline int prop_value(int p, thread const Nb &b, int cidx, int sidx, int x, int y) {
    switch (p) {
    case 0: return cidx;
    case 1: return sidx;
    case 2: return y;
    case 3: return x;
    case 4: return abs(b.pn);
    case 5: return abs(b.pw);
    case 6: return b.pn;
    case 7: return b.pw;
    case 8: return x > 0 ? b.pw - (b.pww + b.pnw - b.pnww) : b.pw;
    case 9: return b.pw + b.pn - b.pnw;
    case 10: return b.pw - b.pnw;
    case 11: return b.pnw - b.pn;
    case 12: return b.pn - b.pne;
    case 13: return b.pn - b.pnn;
    case 14: return b.pw - b.pww;
    default: {
        int val = b.tew;
        if (abs(val) < abs(b.ten)) val = b.ten;
        if (abs(val) < abs(b.tenw)) val = b.tenw;
        if (abs(val) < abs(b.tene)) val = b.tene;
        return val;
    }
    }
}

// ET: storage for the WP sub-predictor errors kept in registers (ushort in the lean
// kernel; a value that does not fit sets `overflow` and the group is redone generically).
// OutPtr: device short * for the frame plane (16-bit output), device int * for meta channels.
// MODE: 0 lean, single-property tree; 2 lean, multi-property tree; 1 generic (anything).
template <typename TreePtr, bool ROWS, int MODE, typename ET, typename OutPtr>
inline void decode_channel(thread bool &overflow, thread Ctx &c, thread CodeSt &cs, device const int *A, TreePtr T, int root,
                           int sprop,
                           threadgroup const int *DIV, TreePtr LI, device const int *LR,
                           OutPtr px, int stride, int w, int h, int cidx, int sidx,
                           WpParams wp, Rows R, bool use_wp, int dist_mult) {
    const bool GENERIC = MODE == 1;
    uint ans = cs.ans, log_bucket = cs.log_bucket;
#ifndef OLD_TOKEN
    if (!GENERIC && ans == 0 && w > 0 && h > 0) { ans = u(c, 16); ans |= u(c, 16) << 16; }
#endif
    for (int y = 0; y < h && !c.err; y++) {
        int r0 = y % 3, r1 = (y + 2) % 3, r2 = (y + 1) % 3; // rows y, y-1, y-2
        int e0 = y & 1, e1 = e0 ^ 1;
        // previous row, raw values at x-2 .. x+2
        int nm2 = 0, nm1 = 0, n0 = 0, np1 = 0, np2 = 0;
        if (y > 0) {
            n0 = rp_load<MODE == 1>(R, r1, 0);
            if (1 < w) np1 = rp_load<MODE == 1>(R, r1, 1);
            if (2 < w) np2 = rp_load<MODE == 1>(R, r1, 2);
        }
        int w1 = 0, w2 = 0; // current row x-1, x-2
        // WP errors: previous row at x-1, x, x+1; current row at x-1, x-2
        ET Enw[4] = {0, 0, 0, 0}, En[4] = {0, 0, 0, 0}, Ene[4] = {0, 0, 0, 0};
        ET Ew[4] = {0, 0, 0, 0}, Eww[4] = {0, 0, 0, 0};
        int Enw4 = 0, En4 = 0, Ene4 = 0, Ew4 = 0; // true errors (signed, wider)
        if (use_wp && y > 0) {
            if (GENERIC) {
                for (int k = 0; k < 5; k++) {
                    int en = RE(R, e1, 0, k), ene = 1 < w ? RE(R, e1, 1, k) : 0;
                    if (k < 4) { En[k] = ET(en); Ene[k] = ET(ene); } else { En4 = en; Ene4 = ene; }
                }
            } else {
                uint a0 = uint(RE3(R, e1, 0, 0)), a1 = uint(RE3(R, e1, 0, 1));
                En[0] = ET(a0 & 0xffff); En[1] = ET(a0 >> 16); En[2] = ET(a1 & 0xffff); En[3] = ET(a1 >> 16);
                En4 = RE3(R, e1, 0, 2);
                if (1 < w) {
                    a0 = uint(RE3(R, e1, 1, 0)); a1 = uint(RE3(R, e1, 1, 1));
                    Ene[0] = ET(a0 & 0xffff); Ene[1] = ET(a0 >> 16); Ene[2] = ET(a1 & 0xffff); Ene[3] = ET(a1 >> 16);
                    Ene4 = RE3(R, e1, 1, 2);
                }
            }
        }
        for (int x = 0; x < w; x++) {
#ifndef OLD_TOKEN
            if (!GENERIC) {
                if (c.n > 64) { fail(c, E_SHORT, 2); break; } // wrapped: read past the section
                if (c.n < 40) refill(c);
            }
#endif
            int pw = x > 0 ? w1 : y > 0 ? n0 : 0;
            int pn = y > 0 ? n0 : pw;
            int pnw = x > 0 && y > 0 ? nm1 : pw;
            int pne = x + 1 < w && y > 0 ? np1 : pn;
            int pnn = y > 1 ? rp_load<MODE == 1>(R, r2, x) : pn;
            int pnee = x + 2 < w && y > 0 ? np2 : pne;
            int pww = x > 1 ? w2 : pw;
            int pnww = x > 1 && y > 0 ? nm2 : pww;

            // MA tree first: it only needs neighbours and the WP *true errors*, so the
            // ANS bucket load can be in flight while the WP prediction is computed.
            int tew = 0, ten = 0, tenw = 0, tene = 0;
            if (use_wp) {
                bool hn = y > 0, hw = x > 0, he = x + 1 < w;
                tew = hw ? Ew4 : 0;
                ten = hn ? En4 : 0;
                tenw = hw && hn ? Enw4 : ten;
                tene = he && hn ? Ene4 : ten;
            }
            Nb nb = {pw, pn, pnw, pne, pnn, pww, pnww, tew, ten, tenw, tene};
            int ref = root;
#ifdef FLAT_TREE
            ref = LEAF_BIT | (x & 1);
#endif
            if (MODE == 0 || (MODE == 1 && sprop >= 0)) {
                int val = prop_value(sprop, nb, cidx, sidx, x, y);
                while (!(ref & 0x40)) {
                    int2 q = node2(T, ref);
                    int t = (q.x << 20) >> 20, tl = (q.x << 8) >> 20;
                    int tr = ((((q.y & 0xf) << 8) | ((q.x >> 24) & 0xff)) << 20) >> 20;
                    int sel = val > t ? (val > tl ? 0 : 7) : (val > tr ? 14 : 21);
                    ref = (q.y >> (4 + sel)) & 0x7f;
                }
                ref = LEAF_BIT | (ref & 0x3f);
            } else {
#ifdef SKIP_WALK
                if (ROWS) ref = LEAF_BIT | (x & 7); // timing ablations touch image channels only
#endif
#ifdef SWITCH_WALK
                if (true) {
#else
                if (GENERIC) {
#endif
                while (!(ref & LEAF_BIT)) {
                    int2 nd = node2(T, ref);
                    int nv = nd.y;
                    int p = nprop(nv);
                    int val = prop_value(p, nb, cidx, sidx, x, y);
                    ref = val > nd.x ? nleft(nv) : nright(nv);
                }
                } else {
                // all 16 properties once per pixel (branch-free), then a 4-level select per
                // node: no per-node switch, so lanes on different paths do not diverge
                int q[16];
                q[0] = cidx; q[1] = sidx; q[2] = y; q[3] = x;
                q[4] = abs(pn); q[5] = abs(pw); q[6] = pn; q[7] = pw;
                q[8] = x > 0 ? pw - (pww + pnw - pnww) : pw;
                q[9] = pw + pn - pnw; q[10] = pw - pnw; q[11] = pnw - pn;
                q[12] = pn - pne; q[13] = pn - pnn; q[14] = pw - pww;
                q[15] = prop_value(15, nb, cidx, sidx, x, y);
#define QSEL(p, out) do { \
                    int a0 = (p & 1) ? q[1] : q[0], a1 = (p & 1) ? q[3] : q[2]; \
                    int a2 = (p & 1) ? q[5] : q[4], a3 = (p & 1) ? q[7] : q[6]; \
                    int a4 = (p & 1) ? q[9] : q[8], a5 = (p & 1) ? q[11] : q[10]; \
                    int a6 = (p & 1) ? q[13] : q[12], a7 = (p & 1) ? q[15] : q[14]; \
                    int b0 = (p & 2) ? a1 : a0, b1 = (p & 2) ? a3 : a2, b2 = (p & 2) ? a5 : a4, b3 = (p & 2) ? a7 : a6; \
                    int c0 = (p & 4) ? b1 : b0, c1 = (p & 4) ? b3 : b2; \
                    out = (p & 8) ? c1 : c0; } while (0)
#ifdef SKIP_WALK
                if (ROWS) ref = LEAF_BIT | (x & 7);
#endif
                while (!(ref & LEAF_BIT)) {
                    int4 qn = node4(T, ref);
                    int p = (qn.y >> 16) & 15, v1, v2;
                    QSEL(p, v1);
                    bool gt = v1 > ((qn.x << 16) >> 16);
                    int p2 = gt ? (qn.y >> 20) & 15 : (qn.y >> 24) & 15;
                    int t2 = gt ? qn.x >> 16 : (qn.y << 16) >> 16;
                    QSEL(p2, v2);
                    bool gt2 = v2 > t2;
                    int g0 = qn.z & 0x3fff, g1 = (qn.z >> 14) & 0x3fff;
                    int g2 = ((qn.z >> 28) & 0xf) | ((qn.w & 0x3ff) << 4), g3 = (qn.w >> 10) & 0x3fff;
                    ref = gt ? (gt2 ? g0 : g1) : (gt2 ? g2 : g3);
                }
#undef QSEL
                }
            }
            device const int *n = LR + LR_SIZE * (ref & (LEAF_BIT - 1));

            int pred[5] = {0, 0, 0, 0, 0};
#ifdef NO_WP
            if (use_wp && !ROWS) {
#else
            if (use_wp) {
#endif
                bool hn = y > 0, hw = x > 0, he = x + 1 < w;
                pred[0] = (pw + pne - pn) * 8;
                pred[1] = pn * 8 - (((tew + ten + tene) * wp.p1) >> 5);
                pred[2] = pw * 8 - (((tew + ten + tenw) * wp.p2) >> 5);
                pred[3] = pn * 8 - ((tenw * wp.p3[0] + ten * wp.p3[1] + tene * wp.p3[2] +
                                     (pnn - pn) * 8 * wp.p3[3] + (pnw - pw) * 8 * wp.p3[4]) >> 5);
                int wt[4];
                for (int i = 0; i < 4; i++) {
                    int en = hn ? En[i] : 0;
                    int enw = hw && hn ? Enw[i] : en;
                    int ene = he && hn ? Ene[i] : en;
                    int ew = hw ? Ew[i] : 0;
                    int eww = x > 1 ? Eww[i] : 0;
                    int ew2 = he ? 0 : ew;
                    int es = en + ew + enw + eww + ene + ew2;
                    int shift = max(floor_lg(uint(es) + 1) - 5, 0);
                    // reciprocal table in constant memory: threadgroup memory is far slower here (bank conflicts)
                    wt[i] = 4 + ((wp.w[i] * div24((es >> shift) + 1)) >> shift); // w <= 15: fits 32 bits
                }
                int logw = floor_lg(uint(wt[0] + wt[1] + wt[2] + wt[3])) - 4;
                int wsum = 0, sum = 0;
                for (int i = 0; i < 4; i++) {
                    wt[i] >>= logw;
                    wsum += wt[i];
                    sum += pred[i] * wt[i];
                }
                // (a * 2^24/wsum) >> 24 as a 32x32 high multiply when a << 8 fits (12-bit data
                // always does); 64-bit otherwise, so the result is exact either way
                int a = sum + (wsum >> 1) - 1;
                int dw = div24(wsum);
                pred[4] = abs(a) < (1 << 23) ? mulhi(a << 8, dw) : int((long(a) * dw) >> 24);
                if (((ten ^ tew) | (ten ^ tenw)) <= 0) {
                    int lo = min(pw, min(pn, pne)) * 8, hi = max(pw, max(pn, pne)) * 8;
                    pred[4] = min(max(lo, pred[4]), hi);
                }
            }

#ifdef NO_ENTROPY
            int tok = ROWS ? int(x & 1) : (GENERIC ? decode_token(c, cs, A, n, dist_mult)
                                                   : decode_token_ans(c, ans, log_bucket, A, LI[ref & (LEAF_BIT - 1)]));
#else
            int tok = GENERIC ? decode_token(c, cs, A, n, dist_mult)
                              : decode_token_ans(c, ans, log_bucket, A, LI[ref & (LEAF_BIT - 1)]);
#endif
            long v = long(unpack_signed(uint(tok))) * n[LR_MUL] + n[LR_OFF];
            int p;
            switch (n[LR_PRED]) {
            case 0: p = 0; break;
            case 1: p = pw; break;
            case 2: p = pn; break;
            case 3: p = (pw + pn) / 2; break;
            case 4: p = abs(pn - pnw) < abs(pw - pnw) ? pw : pn; break;
            case 5: p = grad(pw, pn, pnw); break;
            case 6: p = (pred[4] + 3) >> 3; break;
            case 7: p = pne; break;
            case 8: p = pnw; break;
            case 9: p = pww; break;
            case 10: p = (pw + pnw) / 2; break;
            case 11: p = (pn + pnw) / 2; break;
            case 12: p = (pn + pne) / 2; break;
            default: p = (6 * pn - 2 * pnn + 7 * pw + pww + pnee + 3 * pne + 8) / 16; break;
            }
            int val = int(v + p);
#ifndef NO_PLANE
            px[y * stride + x] = val;
#endif
            if (sizeof(px[0]) == 2 && val != int(short(val))) fail(c, E_RANGE, 1); // plane is 16-bit
            if (ROWS) {
                if (GENERIC) RP(R, r0, x) = val;
                else { RPS(R, r0, x) = short(val); overflow |= val != int(short(val)); }
            }

            // slide
            nm2 = nm1; nm1 = n0; n0 = np1; np1 = np2;
            np2 = y > 0 && x + 3 < w ? rp_load<MODE == 1>(R, r1, x + 3) : 0;
            w2 = w1; w1 = val;
            if (use_wp) {
                int e[5];
                for (int k = 0; k < 4; k++) e[k] = (abs(pred[k] - val * 8) + 3) >> 3;
                e[4] = pred[4] - val * 8;
                bool more = y > 0 && x + 2 < w;
                int nx[5] = {0, 0, 0, 0, 0};
                if (GENERIC) {
                    for (int k = 0; k < 5; k++) {
                        if (ROWS) RE(R, e0, x, k) = e[k];
                        if (more) nx[k] = RE(R, e1, x + 2, k);
                    }
                } else {
                    overflow |= (e[0] | e[1] | e[2] | e[3]) > 0xffff;
                    if (ROWS) {
                        RE3(R, e0, x, 0) = e[0] | (e[1] << 16);
                        RE3(R, e0, x, 1) = e[2] | (e[3] << 16);
                        RE3(R, e0, x, 2) = e[4];
                    }
                    if (more) {
                        uint a0 = uint(RE3(R, e1, x + 2, 0)), a1 = uint(RE3(R, e1, x + 2, 1));
                        nx[0] = int(a0 & 0xffff); nx[1] = int(a0 >> 16); nx[2] = int(a1 & 0xffff); nx[3] = int(a1 >> 16);
                        nx[4] = RE3(R, e1, x + 2, 2);
                    }
                }
                for (int k = 0; k < 4; k++) {
                    Eww[k] = Ew[k]; Ew[k] = ET(e[k]);
                    Enw[k] = En[k]; En[k] = Ene[k]; Ene[k] = ET(nx[k]);
                }
                Ew4 = e[4]; Enw4 = En4; En4 = Ene4; Ene4 = nx[4];
            }
            if (c.err) break;
        }
    }
    if (!GENERIC) {
        cs.ans = ans;
        if (c.n > 64) fail(c, E_SHORT, 3);
    }
}

inline bool tree_uses_wp(device const int *tree) {
    // depth-first scan of reachable nodes; nodes are contiguous so scan until the last referenced
    int last = 0;
    for (int i = 0; i <= last; i++) {
        device const int *n = tree + 4 * i;
        if (n[0] < 0) {
            if (~n[0] == 15) return true;
            last = max(last, i + max(n[2], n[3]));
        } else if (n[1] == 6) {
            return true;
        }
    }
    return false;
}

inline WpParams read_wp_header(thread Ctx &c) {
    WpParams wp;
    bool def = u(c, 1);
    wp.p1 = def ? 16 : int(u(c, 5));
    wp.p2 = def ? 10 : int(u(c, 5));
    for (int i = 0; i < 5; i++) wp.p3[i] = def ? 7 * (i < 3) : int(u(c, 5));
    for (int i = 0; i < 4; i++) wp.w[i] = def ? 12 + (i < 1) : int(u(c, 4));
    return wp;
}

// ---------------------------------------------------------------- headers

inline void size_header(thread Ctx &c, thread int &w, thread int &h) {
    bool div8 = u(c, 1);
    h = div8 ? int(u(c, 5) + 1) * 8 : int(u32s(c, 1, 9, 1, 13, 1, 18, 1, 30));
    switch (u(c, 3)) {
    case 0: w = div8 ? int(u(c, 5) + 1) * 8 : int(u32s(c, 1, 9, 1, 13, 1, 18, 1, 30)); break;
    case 1: w = h; break;
    case 2: w = int(ulong(h) * 6 / 5); break;
    case 3: w = int(ulong(h) * 4 / 3); break;
    case 4: w = int(ulong(h) * 3 / 2); break;
    case 5: w = int(ulong(h) * 16 / 9); break;
    case 6: w = int(ulong(h) * 5 / 4); break;
    default: w = h * 2; break;
    }
}

inline int bit_depth(thread Ctx &c) {
    if (u(c, 1)) { fail(c, E_UNSUPPORTED, 1); return 0; } // float samples
    return int(u32s(c, 8, 0, 10, 0, 12, 0, 1, 6));
}

inline void skip_name(thread Ctx &c) {
    uint len = u32s(c, 0, 0, 0, 4, 16, 5, 48, 10);
    skip_bits(c, ulong(len) * 8);
}

inline void extensions(thread Ctx &c) {
    ulong ext = u64v(c);
    ulong nbits = 0;
    for (int i = 0; i < 64; i++) if ((ext >> i) & 1) nbits += u64v(c);
    skip_bits(c, nbits);
}

inline void f16skip(thread Ctx &c, int n) { skip_bits(c, ulong(n) * 16); }

// ImageMetadata subset: grey or RGB integer samples, no ICC/preview/extra channels.
inline void image_metadata(thread Ctx &c, thread int &w, thread int &h, thread int &bpp, thread int &grey) {
    size_header(c, w, h);
    bpp = 8;
    grey = 0;
    int xyb = 1;
    if (!u(c, 1)) { // !all_default
        bool extra_fields = u(c, 1);
        if (extra_fields) {
            u(c, 3); // orientation
            if (u(c, 1)) { int a, b; size_header(c, a, b); }
            if (u(c, 1)) { fail(c, E_UNSUPPORTED, 2); return; } // preview
            if (u(c, 1)) { fail(c, E_UNSUPPORTED, 21); return; } // animation
        }
        bpp = bit_depth(c);
        u(c, 1); // modular_16bit_buffers
        uint nec = u32s(c, 0, 0, 1, 0, 2, 4, 1, 12);
        if (nec) { fail(c, E_UNSUPPORTED, 3); return; }
        xyb = int(u(c, 1));
        if (!u(c, 1)) { // colour encoding !all_default
            bool want_icc = u(c, 1);
            uint cs = enum_v(c);
            if (want_icc) { fail(c, E_UNSUPPORTED, 4); return; }
            grey = cs == 1;
            if (cs != 2) {
                uint wpt = enum_v(c);
                if (wpt == 2) { for (int k = 0; k < 2; k++) u32s(c, 0, 19, 0x80000, 19, 0x100000, 20, 0x200000, 21); }
                if (cs != 1) {
                    uint prim = enum_v(c);
                    if (prim == 2) for (int k = 0; k < 6; k++) u32s(c, 0, 19, 0x80000, 19, 0x100000, 20, 0x200000, 21);
                }
            }
            if (u(c, 1)) u(c, 24); else enum_v(c); // gamma / transfer function
            enum_v(c); // rendering intent
        }
        if (extra_fields && !u(c, 1)) { // tone mapping
            f16skip(c, 2);
            u(c, 1);
            f16skip(c, 1);
        }
        extensions(c);
    }
    if (xyb) { fail(c, E_UNSUPPORTED, 5); return; }
    if (!u(c, 1)) { // !default_m (xyb is off, so only cw_mask)
        if (u(c, 3)) fail(c, E_UNSUPPORTED, 6);
    }
}

// FrameHeader subset: single regular modular frame, one pass, no upsampling.
inline void frame_header(thread Ctx &c, int img_w, int img_h, thread int &gshift, thread int &fw, thread int &fh) {
    zero_pad(c);
    gshift = 8;
    fw = img_w; fh = img_h;
    if (u(c, 1)) { fail(c, E_UNSUPPORTED, 7); return; } // all_default would be VarDCT
    uint type = u(c, 2);
    bool modular = u(c, 1);
    if (type != 0 || !modular) { fail(c, E_UNSUPPORTED, 8); return; }
    ulong flags = u64v(c);
    if (flags) { fail(c, E_UNSUPPORTED, 9); return; } // noise/patches/splines/lf frame
    if (u(c, 1)) { fail(c, E_UNSUPPORTED, 10); return; } // do_ycbcr
    if (u(c, 2)) { fail(c, E_UNSUPPORTED, 11); return; } // upsampling
    gshift = 7 + int(u(c, 2));
    uint passes = u32s(c, 1, 0, 2, 0, 3, 0, 4, 3);
    if (passes != 1) { fail(c, E_UNSUPPORTED, 12); return; }
    bool full = true;
    if (u(c, 1)) { // crop
        int x0 = unpack_signed(u32s(c, 0, 8, 256, 11, 2304, 14, 18688, 30));
        int y0 = unpack_signed(u32s(c, 0, 8, 256, 11, 2304, 14, 18688, 30));
        fw = int(u32s(c, 0, 8, 256, 11, 2304, 14, 18688, 30));
        fh = int(u32s(c, 0, 8, 256, 11, 2304, 14, 18688, 30));
        full = x0 <= 0 && y0 <= 0 && fw + x0 >= img_w && fh + y0 >= img_h;
    }
    uint blend = u32s(c, 0, 0, 1, 0, 2, 0, 3, 2);
    if (!full || blend != 0) u(c, 2);
    bool is_last = u(c, 1);
    if (!is_last) { fail(c, E_UNSUPPORTED, 13); return; }
    skip_name(c);
    bool restoration_default = u(c, 1);
    if (!restoration_default) {
        if (u(c, 1)) { if (u(c, 1)) f16skip(c, 6); } // gab
        int epf = int(u(c, 2));
        if (epf) {
            if (u(c, 1)) { f16skip(c, 3); skip_bits(c, 32); }
            if (u(c, 1)) f16skip(c, 3);
            f16skip(c, 1);
        }
        extensions(c);
    }
    extensions(c);
}

// ---------------------------------------------------------------- frame kernel

struct FrameRef { uint offset, size; };

// Compact form of a raw tree (see jxl_group_setup) for decode_channel's generic walk.
inline void compact_tree(thread Ctx &c, device const int *TA, uint tree, thread uint &ctree, thread uint &leaves,
                         thread int &root) {
    int nn = 0, nbranch = 0, nleaf = 0, last = 0;
    device const int *tn = TA + tree;
    for (int k = 0; k <= last; k++) {
        device const int *n = tn + 4 * k;
        if (n[0] < 0) { last = max(last, k + max(n[2], n[3])); nbranch++; } else nleaf++;
    }
    nn = last + 1;
    if (nbranch >= LEAF_BIT || nleaf >= LEAF_BIT) fail(c, E_TREE, 5);
    ctree = alloc(c, uint(2 * max(nbranch, 1)) + 1);
    ctree += ctree & 1;
    leaves = alloc(c, uint(LR_SIZE * max(nleaf, 1)));
    uint remap = alloc(c, uint(max(nn, 1)));
    if (c.err) return;
    int b = 0, l = 0;
    for (int k = 0; k < nn; k++) c.A[remap + k] = tn[4 * k] < 0 ? b++ : (LEAF_BIT | l++);
    for (int k = 0; k < nn; k++) {
        device const int *n = tn + 4 * k;
        int ref = c.A[remap + k];
        if (n[0] < 0) {
            c.A[ctree + 2 * ref] = n[1];
            if (~n[0] > 15) fail(c, E_UNSUPPORTED, 20); // previous-channel properties
            c.A[ctree + 2 * ref + 1] = (~n[0] & 15) | (c.A[remap + k + n[2]] << 4) | (c.A[remap + k + n[3]] << 18);
        } else {
            device int *r = c.A + leaves + LR_SIZE * (ref & (LEAF_BIT - 1));
            device const int *cr = TA + n[0];
            r[0] = cr[0]; r[1] = cr[1]; r[2] = cr[2]; r[3] = cr[3];
            r[LR_PRED] = n[1]; r[LR_OFF] = n[2]; r[LR_MUL] = n[3];
        }
    }
    root = c.A[remap];
}

kernel void jxl_parse_frame(device const uchar *src [[buffer(0)]],
                            device const FrameRef *frames [[buffer(1)]],
                            device int *arenas [[buffer(2)]],
                            constant uint &arena_ints [[buffer(3)]],
                            constant uint &nframes [[buffer(4)]],
                            uint fi [[thread_position_in_grid]]) {
    if (fi >= nframes) return;
    device int *A = arenas + ulong(fi) * arena_ints;
    Ctx c;
    c.d = src + frames[fi].offset; c.pos = 0; c.end = frames[fi].size;
    c.buf = 0; c.n = 0; c.err = 0;
    c.A = A; c.top = H_SIZE; c.cap = arena_ints;
    for (int i = 0; i < H_SIZE; i++) A[i] = 0;
    int features = 0;

    if (u(c, 16) != 0x0aff) fail(c, E_SIG, 0);
    int iw, ih, bpp, grey;
    image_metadata(c, iw, ih, bpp, grey);
    int gshift, fw, fh;
    if (!c.err) frame_header(c, iw, ih, gshift, fw, fh);
    if (!c.err && !grey) fail(c, E_UNSUPPORTED, 14); // colour needs RCT/3 channels: later

    int gsize = 1 << gshift;
    int gcols = (fw + gsize - 1) / gsize, grows = (fh + gsize - 1) / gsize;
    int ngroups = gcols * grows;
    int lfcols = (fw + 8 * gsize - 1) / (8 * gsize), lfrows = (fh + 8 * gsize - 1) / (8 * gsize);
    int nlf = lfcols * lfrows;
    A[H_WIDTH] = fw; A[H_HEIGHT] = fh; A[H_BPP] = bpp; A[H_GSHIFT] = gshift;
    A[H_GCOLS] = gcols; A[H_GROWS] = grows; A[H_NGROUPS] = ngroups; A[H_NLFGROUPS] = nlf;
    if (!c.err && ngroups == 1) fail(c, E_UNSUPPORTED, 15); // single-section layout: later

    // TOC
    int nsections = 1 + nlf + 1 + ngroups;
    uint perm = 0;
    if (!c.err && u(c, 1)) {
        features |= F_PERMUTED_TOC;
        uint pspec = read_code_spec<0>(c, 8, features);
        uint win = (!c.err && A[pspec + S_LZ77]) ? alloc(c, 1u << 16) : 0;
        CodeSt cs;
        init_code(cs, A, pspec, win ? A + win : (device int *)0, 1 << 16);
        int end = decode_ctx(c, cs, A, min(7, int(32 - clz(uint(nsections)))), 0);
        if (end > nsections) fail(c, E_TOC, 1);
        perm = alloc(c, uint(nsections));
        if (!c.err) {
            for (int i = 0; i < nsections; i++) A[perm + i] = i;
            int prev = 0;
            for (int i = 0; i < end && !c.err; i++) {
                prev = decode_ctx(c, cs, A, prev ? min(7, int(32 - clz(uint(prev)))) : 0, 0);
                if (prev >= nsections - i) { fail(c, E_TOC, 2); break; }
                int moved = A[perm + i + prev];
                for (int k = i + prev; k > i; k--) A[perm + k] = A[perm + k - 1];
                A[perm + i] = moved;
            }
        }
        finish_code(c, cs);
    }
    zero_pad(c);
    uint sizes = alloc(c, uint(nsections));
    uint offs = alloc(c, uint(nsections));
    if (!c.err) {
        for (int i = 0; i < nsections; i++) A[sizes + i] = int(u32s(c, 0, 10, 1024, 14, 17408, 22, 4211712, 30));
        zero_pad(c);
        uint base = byte_pos(c);
        uint off = base;
        for (int i = 0; i < nsections; i++) { A[offs + i] = int(off); off += uint(A[sizes + i]); }
        if (off > c.end) fail(c, E_TOC, 3);
    }
    // logical section i lives at physical slot perm[i]
    uint groups = alloc(c, uint(2 * ngroups));
    A[H_GROUPS] = int(groups);
    if (c.err) { A[H_ERR] = c.err; A[H_FEATURES] = features; A[H_TOP] = int(c.top); return; }
    for (int g = 0; g < ngroups; g++) {
        int logical = 1 + nlf + 1 + g;
        int phys = perm ? A[perm + logical] : logical;
        A[groups + 2 * g] = int(frames[fi].offset) + A[offs + phys];
        A[groups + 2 * g + 1] = A[sizes + phys];
    }
    for (int i = 1; i <= nlf; i++) {
        int phys = perm ? A[perm + i] : i;
        if (A[sizes + phys] != 0) fail(c, E_UNSUPPORTED, 16); // modular LF groups unused for lossless
    }

    // LfGlobal section
    int lf_phys = perm ? A[perm] : 0;
    Ctx s = c;
    s.pos = uint(A[offs + lf_phys]); s.end = s.pos + uint(A[sizes + lf_phys]); s.buf = 0; s.n = 0;
    if (!u(s, 1)) f16skip(s, 3); // LfChannelDequantization
    uint tree = 0, spec = 0;
    bool global_tree = u(s, 1);
    if (global_tree) read_tree(s, tree, spec, features);
    A[H_TREE] = global_tree ? int(tree) : -1;
    A[H_SPEC] = int(spec);
    // GlobalModular header for the single grey channel (no channel is coded
    // globally for multi-group frames, but the header and stream end are there)
    if (!s.err) {
        bool use_global = u(s, 1);
        if (use_global && !global_tree) fail(s, E_TREE, 3);
        WpParams gwp = read_wp_header(s);
        uint nb_tr = u32s(s, 0, 0, 1, 0, 2, 4, 18, 8);
        // supported global transform: one single-channel palette; its meta channel
        // (nb_colours x 1) is the only channel coded in the global stream
        int nb_colours = 0;
        for (uint t = 0; t < nb_tr && !s.err; t++) {
            features |= F_GLOBAL_TRANSFORM;
            if (u(s, 2) != 1 || t > 0) { fail(s, E_UNSUPPORTED, 19); break; }
            uint begin_c = u32s(s, 0, 3, 8, 6, 72, 10, 1096, 13);
            uint num_c = u32s(s, 1, 0, 3, 0, 4, 0, 1, 13);
            nb_colours = int(u32s(s, 0, 8, 256, 10, 1280, 12, 5376, 16));
            A[H_PAL_DELTAS] = int(u32s(s, 0, 0, 1, 8, 257, 10, 1281, 16));
            A[H_PAL_DPRED] = int(u(s, 4));
            if (begin_c != 0 || num_c != 1) fail(s, E_UNSUPPORTED, 22);
            if (A[H_PAL_DELTAS] > 0) fail(s, E_UNSUPPORTED, 23); // delta prediction needs a serial pass
            A[H_PALETTE] = 1;
            A[H_PAL_N] = nb_colours;
        }
        uint gm_tree = tree, gm_spec = spec;
        if (!use_global && !s.err) { read_tree(s, gm_tree, gm_spec, features); }
        CodeSt cs;
        init_code(cs, A, gm_spec, (device int *)0, 1);
        if (A[H_PALETTE] && nb_colours > 0 && !s.err) {
            uint ctree, leaves, pal = alloc(s, uint(nb_colours));
            int root = 0;
            compact_tree(s, A, gm_tree, ctree, leaves, root);
            A[H_PAL] = int(pal);
            if (!s.err) {
                Rows R0;
                R0.px = (device int *)0; R0.err = (device int *)0; R0.njobs = 1; R0.maxw = 1; R0.lane = 0;
                bool overflow = false;
                decode_channel<device const int *, false, 1, int, device int *>(
                    overflow, s, cs, A, (device const int *)(A + ctree), root, -1, (threadgroup const int *)0,
                    (device const int *)(A + leaves), A + leaves, A + pal, nb_colours, nb_colours, 1, 0, 0, gwp, R0,
                    tree_uses_wp(A + gm_tree), fw);
            }
        }
        if (!s.err) finish_code(s, cs);
        finish_section(s);
    }
    if (!s.err && global_tree) {
        uint ctree, leaves;
        int root = 0;
        compact_tree(s, A, tree, ctree, leaves, root);
        int nleaf = 0, last = 0;
        for (int k = 0; k <= last; k++) {
            device const int *n = A + tree + 4 * k;
            if (n[0] < 0) last = max(last, k + max(n[2], n[3])); else nleaf++;
        }
        uint linfo = alloc(s, uint(max(nleaf, 1)));
        bool ok = true;
        for (int l = 0; l < nleaf && !s.err; l++) {
            device const int *r = A + leaves + LR_SIZE * l;
            ok &= r[CR_TABLE] < (1 << 18) && !(r[CR_TABLE] & 1);
            A[linfo + l] = ((r[CR_TABLE] >> 1) & 0x1ffff) | (r[CR_CFG] << 17);
        }
        A[H_CTREE] = int(ctree); A[H_LEAVES] = int(leaves); A[H_LINFO] = int(linfo);
        A[H_ROOT] = root; A[H_LINFO_OK] = ok;
        int nbr = 0; last = 0;
        for (int k = 0; k <= last; k++) {
            device const int *n = A + tree + 4 * k;
            if (n[0] < 0) { last = max(last, k + max(n[2], n[3])); nbr++; }
        }
        uint qt;
        A[H_QT16] = build_qt16(s, A + ctree, nbr, qt) ? int(qt) : -1;
    }
    if (!s.err && global_tree && tree_uses_wp(A + tree)) features |= F_WP;
    A[H_WP_TREE] = (features & F_WP) ? 1 : 0;
    A[H_FEATURES] = features;
    A[H_TOP] = int(s.top);
    A[H_ERR] = s.err;
    A[H_ERRPOS] = int(s.pos);
}

// ---------------------------------------------------------------- group kernel

struct GroupJob { uint frame, group; };

// Delta palette, first channel only (the full table has 3 channels).
constant short PALETTE_DELTA0[72] = {
    0, 4, 11, 0, 0, -10, -18, -27, -18, 0, -32, -37, 0, 24, 50, -45, -24, 0,
    -34, -24, -45, 64, -32, 0, -32, -24, 45, 24, -45, 80, 64, 0, 0, -24, 96, 64,
    45, 34, 112, 24, 45, 0, 24, 0, 45, 24, -24, 0, 96, 128, 64, 144, 96, -36,
    45, 45, 0, 0, 0, 45, -128, 24, -45, 64, 64, 96, 45, 24, 64, 128, 0, -24,
};

inline int palette_delta0(int k) { // entries alternate (+v, -v) after the first duplicate
    int base = PALETTE_DELTA0[(k + 1) >> 1];
    return ((k + 1) & 1) ? -base : base;
}

// Simple (non-WP) predictor on already reconstructed samples of a w-wide region.
inline int predict_simple(int pred, device const short *p, int stride, int x, int y, int w) {
    device const short *row = p + y * stride, *rn = p + (y - 1) * stride, *rnn = p + (y - 2) * stride;
    int pw = x > 0 ? row[x - 1] : y > 0 ? rn[x] : 0;
    int pn = y > 0 ? rn[x] : pw;
    int pnw = x > 0 && y > 0 ? rn[x - 1] : pw;
    int pne = x + 1 < w && y > 0 ? rn[x + 1] : pn;
    int pnn = y > 1 ? rnn[x] : pn;
    int pnee = x + 2 < w && y > 0 ? rn[x + 2] : pne;
    int pww = x > 1 ? row[x - 2] : pw;
    switch (pred) {
    case 0: return 0;
    case 1: return pw;
    case 2: return pn;
    case 3: return (pw + pn) / 2;
    case 4: return abs(pn - pnw) < abs(pw - pnw) ? pw : pn;
    case 5: return grad(pw, pn, pnw);
    case 7: return pne;
    case 8: return pnw;
    case 9: return pww;
    case 10: return (pw + pnw) / 2;
    case 11: return (pn + pnw) / 2;
    case 12: return (pn + pne) / 2;
    default: return (6 * pn - 2 * pnn + 7 * pw + pww + pnee + 3 * pne + 8) / 16;
    }
}

// Group state handed from the setup kernel to the decode kernels (first ints of the job's scratch).
enum {
    GS_ERR = 0, GS_POS, GS_END, GS_BUFLO, GS_BUFHI, GS_N, GS_TOP, GS_GENERIC, GS_USEWP, GS_INTG, GS_ROOT,
    GS_CTREE, GS_NBRANCH, GS_LEAVES, GS_SPEC, GS_LOCAL, GS_WIN, GS_WINCAP, GS_PALETTE, GS_PAL, GS_NBCOL,
    GS_NBDELTA, GS_DPRED, GS_SPROP, GS_QTREE, GS_LINFO, GS_NLEAF, GS_SHARED, GS_QT16, GS_WP /* 11 ints */, GS_SIZE = GS_WP + 11,
};

#define GROUP_KERNEL_ARGS                                                                                          \
    device const uchar *src [[buffer(0)]], device const int *arenas [[buffer(1)]],                                 \
    constant uint &arena_ints [[buffer(2)]], device const GroupJob *jobs [[buffer(3)]],                           \
    constant uint &njobs [[buffer(4)]], device short *planes [[buffer(5)]],                                         \
    device const ulong *plane_offsets [[buffer(6)]], device int *scratch [[buffer(7)]],                           \
    constant uint &scratch_ints [[buffer(8)]], device int *status [[buffer(9)]], device int *rowpx [[buffer(10)]], \
    device int *rowerr [[buffer(11)]], constant uint &maxw [[buffer(12)]], constant uint &job_base [[buffer(13)]], \
    uint gi [[thread_position_in_grid]], uint tid [[thread_index_in_threadgroup]]

// Setup: group header, local tree and entropy tables, compact tree and leaf records.
// Heavy but short; kept out of the decode kernels so they stay lean in registers.
kernel void jxl_group_setup(GROUP_KERNEL_ARGS) {
    if (gi >= njobs) return;
    GroupJob job = jobs[job_base + gi];
    device const int *A = arenas + ulong(job.frame) * arena_ints;
    int W = A[H_WIDTH], H = A[H_HEIGHT], shift = A[H_GSHIFT], gcols = A[H_GCOLS];
    int g = int(job.group);
    int gx = (g % gcols) << shift, gy = (g / gcols) << shift;
    int gw = min(W - gx, 1 << shift), gh = min(H - gy, 1 << shift);
    int off = A[A[H_GROUPS] + 2 * g], size = A[A[H_GROUPS] + 2 * g + 1];

    Ctx c;
    c.d = src; c.pos = uint(off); c.end = uint(off + size);
    c.buf = 0; c.n = 0; c.err = 0;
    c.A = scratch + ulong(gi) * scratch_ints; c.top = GS_SIZE; c.cap = scratch_ints;
    device int *GS = c.A;
    int features = 0;

    bool use_global = u(c, 1);
    WpParams wp = read_wp_header(c);
    uint nb_tr = u32s(c, 0, 0, 1, 0, 2, 4, 18, 8);
    int trinfo = 0;
    // supported: one single-channel palette (what libjxl emits for grey groups)
    int nb_colours = 0, nb_deltas = 0, d_pred = 0;
    bool palette = false;
    for (uint t = 0; t < nb_tr && !c.err; t++) {
        uint id = u(c, 2);
        features |= F_GROUP_TRANSFORM;
        if (id == 1 && t == 0) {
            uint begin_c = u32s(c, 0, 3, 8, 6, 72, 10, 1096, 13);
            uint num_c = u32s(c, 1, 0, 3, 0, 4, 0, 1, 13);
            nb_colours = int(u32s(c, 0, 8, 256, 10, 1280, 12, 5376, 16));
            nb_deltas = int(u32s(c, 0, 0, 1, 8, 257, 10, 1281, 16));
            d_pred = int(u(c, 4));
            trinfo = nb_colours | (nb_deltas << 16) | (d_pred << 28);
            if (begin_c != 0 || num_c != 1 || d_pred >= 14) fail(c, E_UNSUPPORTED, 32);
            if (nb_deltas > 0 && d_pred == 6) fail(c, E_UNSUPPORTED, 33);
            palette = true;
        } else {
            trinfo = -int(id) - 1;
            fail(c, E_UNSUPPORTED, 34);
        }
    }
    device const int *TA = A;
    uint tree = uint(A[H_TREE]), spec = uint(A[H_SPEC]);
    bool use_wp = A[H_WP_TREE] != 0;
    if (!use_global && !c.err) {
        read_tree(c, tree, spec, features);
        TA = c.A;
        use_wp = !c.err && tree_uses_wp(c.A + tree);
    } else if (A[H_TREE] < 0) {
        fail(c, E_TREE, 4);
    }
    // Fold properties that are constant inside this group out of the tree: 1 (stream
    // index) always, 0 (channel index) when the group codes a single channel. libjxl's
    // global trees hang a subtree per group off such splits; folding leaves each group
    // its own small tree while the entropy tables stay shared by the whole frame.
    device const int *TN = TA;
    if (!c.err) {
        int sidx = 1 + 3 * A[H_NLFGROUPS] + 17 + g;
        bool fold0 = !palette;
        device const int *src = TA + tree;
        int last = 0;
        for (int q = 0; q <= last; q++)
            if (src[4 * q] < 0) last = max(last, q + max(src[4 * q + 2], src[4 * q + 3]));
        int total = last + 1;
        uint out = alloc(c, uint(4 * total)), from = alloc(c, uint(total));
        if (!c.err) {
            int n_out = 1;
            for (int i = 0; i < n_out; i++) {
                int q = i == 0 ? 0 : c.A[from + i];
                // follow folded splits
                while (src[4 * q] < 0 && (~src[4 * q] == 1 || (fold0 && ~src[4 * q] == 0))) {
                    int v = ~src[4 * q] == 1 ? sidx : 0;
                    q += v > src[4 * q + 1] ? src[4 * q + 2] : src[4 * q + 3];
                }
                device const int *n = src + 4 * q;
                device int *o = c.A + out + 4 * i;
                o[0] = n[0]; o[1] = n[1];
                if (n[0] < 0) {
                    c.A[from + n_out] = q + n[2];
                    c.A[from + n_out + 1] = q + n[3];
                    o[2] = n_out - i; o[3] = n_out + 1 - i;
                    n_out += 2;
                } else {
                    o[2] = n[2]; o[3] = n[3];
                }
            }
            TN = c.A;
            tree = out;
        }
    }
    // compact tree (branches only; leaves are records carrying what the token decode needs)
    int nn = 0, nbranch = 0, nleaf = 0;
    if (!c.err) {
        int last = 0;
        device const int *tn = TN + tree;
        for (int k = 0; k <= last; k++) {
            device const int *n = tn + 4 * k;
            if (n[0] < 0) { last = max(last, k + max(n[2], n[3])); nbranch++; } else nleaf++;
        }
        nn = last + 1;
        if (nbranch >= LEAF_BIT || nleaf >= LEAF_BIT) fail(c, E_TREE, 5);
    }
    uint ctree = alloc(c, uint(2 * max(nbranch, 1)) + 1);
    ctree += ctree & 1; // 8-byte aligned for int2 node loads
    uint leaves = alloc(c, uint(LR_SIZE * max(nleaf, 1)));
    uint remap = alloc(c, uint(max(nn, 1))); // node -> branch index or LEAF_BIT | leaf index
    int root = 0;
    if (!c.err) {
        device const int *tn = TN + tree;
        int b = 0, l = 0;
        for (int k = 0; k < nn; k++) c.A[remap + k] = tn[4 * k] < 0 ? b++ : (LEAF_BIT | l++);
        for (int k = 0; k < nn; k++) {
            device const int *n = tn + 4 * k;
            int ref = c.A[remap + k];
            if (n[0] < 0) {
                c.A[ctree + 2 * ref] = n[1];
                if (~n[0] > 15) fail(c, E_UNSUPPORTED, 20); // previous-channel properties
            c.A[ctree + 2 * ref + 1] = (~n[0] & 15) | (c.A[remap + k + n[2]] << 4) | (c.A[remap + k + n[3]] << 18);
            } else {
                device int *r = c.A + leaves + LR_SIZE * (ref & (LEAF_BIT - 1));
                device const int *cr = TA + n[0];
                r[0] = cr[0]; r[1] = cr[1]; r[2] = cr[2]; r[3] = cr[3];
                r[LR_PRED] = n[1]; r[LR_OFF] = n[2]; r[LR_MUL] = n[3];
            }
        }
        root = c.A[remap];
    }
    // single-property tree: the property is computed once per pixel instead of per node
    int sprop = -1;
    if (!c.err && nbranch > 0) {
        device const int *tn = TN + tree;
        for (int k = 0; k < nn; k++) {
            if (tn[4 * k] >= 0) continue;
            int p = ~tn[4 * k];
            sprop = sprop == -1 ? p : (sprop == p ? p : -2);
        }
        if (sprop > 15) sprop = -1;
    }
    if (sprop >= 0 && (nbranch > 64 || nleaf > 64)) sprop = -1;
    for (int b = 0; b < nbranch && sprop >= 0 && !c.err; b++) {
        int t = c.A[ctree + 2 * b];
        if (t < -2048 || t > 2047) sprop = -1;
    }
    uint qtree = alloc(c, uint(2 * max(nbranch, 1)) + 1);
    qtree += qtree & 1; // 8-byte aligned int2 nodes
    if (!c.err && sprop >= 0) {
        // 7-bit refs: branch index, or 0x40 | leaf index
        for (int b = 0; b < nbranch; b++) {
            int t = c.A[ctree + 2 * b], nv = c.A[ctree + 2 * b + 1];
            int kid[2] = {nleft(nv), nright(nv)}; // [0]: val > t, [1]: otherwise
            int thr2[2] = {0, 0}, g[4];
            for (int s2 = 0; s2 < 2; s2++) {
                int k = kid[s2];
                if (k & LEAF_BIT) {
                    g[2 * s2] = g[2 * s2 + 1] = 0x40 | (k & 0x3f);
                } else {
                    int kv = c.A[ctree + 2 * k + 1];
                    thr2[s2] = c.A[ctree + 2 * k];
                    int l = nleft(kv), r = nright(kv);
                    g[2 * s2] = (l & LEAF_BIT) ? 0x40 | (l & 0x3f) : l;
                    g[2 * s2 + 1] = (r & LEAF_BIT) ? 0x40 | (r & 0x3f) : r;
                }
            }
            device int *q = c.A + qtree + 2 * b;
            q[0] = (t & 0xfff) | ((thr2[0] & 0xfff) << 12) | ((thr2[1] & 0xff) << 24);
            q[1] = ((thr2[1] >> 8) & 0xf) | ((g[0] | (g[1] << 7) | (g[2] << 14) | (g[3] << 21)) << 4);
        }
    }
    uint pal = palette ? alloc(c, uint(max(nb_colours, 1))) : 0;
    int rest = int(c.cap - c.top);
    int win_cap = 1 << floor_lg(uint(max(min(rest, gw * gh * 2), 1)));
    device const int *S = TA + spec;

    GS[GS_POS] = int(c.pos); GS[GS_END] = int(c.end); GS[GS_N] = int(c.n);
    GS[GS_BUFLO] = int(uint(c.buf)); GS[GS_BUFHI] = int(uint(c.buf >> 32));
    GS[GS_TOP] = int(c.top);
    // packed leaf infos for the lean path (even table offset below 2^18)
    uint linfo = alloc(c, uint(max(nleaf, 1)));
    bool linfo_ok = true;
    for (int l = 0; l < nleaf && !c.err; l++) {
        device const int *r = c.A + leaves + LR_SIZE * l;
        linfo_ok &= r[CR_TABLE] < (1 << 18) && !(r[CR_TABLE] & 1);
        c.A[linfo + l] = ((r[CR_TABLE] >> 1) & 0x1ffff) | (r[CR_CFG] << 17);
    }
    // a folded global tree that is still big: walk the frame's shared copy instead of a
    // private one, so every lane reads the same cache lines
    bool shared = use_global && sprop < 0 && 2 * nbranch + nleaf > 2 * TG_NODES;
    if (shared) linfo_ok = A[H_LINFO_OK] != 0;
    uint qt16 = 0;
    bool qt_ok = sprop >= 0 || (shared ? A[H_QT16] >= 0 : build_qt16(c, c.A + ctree, nbranch, qt16));
    GS[GS_QT16] = int(qt16);
    GS[GS_SHARED] = shared;
    GS[GS_GENERIC] = c.err ? 0 : (S[S_USE_PREFIX] || S[S_LZ77] || !linfo_ok || !qt_ok) ? 1 : sprop >= 0 ? 0 : 2;
    GS[GS_LINFO] = int(linfo); GS[GS_NLEAF] = nleaf;
    GS[GS_USEWP] = use_wp; GS[GS_INTG] = !shared && 2 * nbranch + nleaf <= 2 * TG_NODES; GS[GS_ROOT] = root;
    GS[GS_CTREE] = int(ctree); GS[GS_NBRANCH] = nbranch; GS[GS_LEAVES] = int(leaves);
    GS[GS_SPEC] = int(spec); GS[GS_LOCAL] = !use_global; GS[GS_WIN] = int(c.top); GS[GS_WINCAP] = win_cap;
    GS[GS_PALETTE] = palette; GS[GS_PAL] = int(pal); GS[GS_NBCOL] = nb_colours;
    GS[GS_NBDELTA] = nb_deltas; GS[GS_DPRED] = d_pred; GS[GS_SPROP] = sprop; GS[GS_QTREE] = int(qtree);
    GS[GS_WP + 0] = wp.p1; GS[GS_WP + 1] = wp.p2;
    for (int i = 0; i < 5; i++) GS[GS_WP + 2 + i] = wp.p3[i];
    for (int i = 0; i < 4; i++) GS[GS_WP + 7 + i] = wp.w[i];
    GS[GS_ERR] = c.err;
    status[4 * (job_base + gi)] = c.err;
    status[4 * (job_base + gi) + 1] = int(c.top) | (features << 24);
    status[4 * (job_base + gi) + 2] = use_global ? -(nbranch | (sprop >= 0 ? 0x10000 : 0) | (GS[GS_INTG] ? 0x20000 : 0)) - 1 : int(tree);
    status[4 * (job_base + gi) + 3] = nb_tr ? trinfo : int(spec);
}

template <int G, typename ET>
inline void group_decode(device const uchar *src, device const int *arenas, uint arena_ints,
                         device const GroupJob *jobs, uint njobs, device short *planes,
                         device const ulong *plane_offsets, device int *scratch, uint scratch_ints,
                         device int *status, device int *rowpx, device int *rowerr, uint maxw, uint job_base,
                         uint gi, uint tid, threadgroup int *tgtree, threadgroup const int *tgdiv) {
    device int *GS = scratch + ulong(gi) * scratch_ints;
    if (GS[GS_ERR] || GS[GS_GENERIC] != G) return;
    bool overflow = false;
    GroupJob job = jobs[job_base + gi];
    device const int *A = arenas + ulong(job.frame) * arena_ints;
    int W = A[H_WIDTH], H = A[H_HEIGHT], shift = A[H_GSHIFT], gcols = A[H_GCOLS];
    int g = int(job.group);
    int gx = (g % gcols) << shift, gy = (g / gcols) << shift;
    int gw = min(W - gx, 1 << shift), gh = min(H - gy, 1 << shift);

    Ctx c;
    c.d = src; c.pos = uint(GS[GS_POS]); c.end = uint(GS[GS_END]); c.n = uint(GS[GS_N]);
    c.buf = ulong(uint(GS[GS_BUFLO])) | (ulong(uint(GS[GS_BUFHI])) << 32);
    c.err = 0; c.A = GS; c.top = uint(GS[GS_TOP]); c.cap = scratch_ints;

    device const int *TA = GS[GS_LOCAL] ? (device const int *)GS : A;
    WpParams wp;
    wp.p1 = short(GS[GS_WP]); wp.p2 = short(GS[GS_WP + 1]);
    for (int i = 0; i < 5; i++) wp.p3[i] = short(GS[GS_WP + 2 + i]);
    for (int i = 0; i < 4; i++) wp.w[i] = short(GS[GS_WP + 7 + i]);
    bool use_wp = GS[GS_USEWP], in_tg = GS[GS_INTG], palette = GS[GS_PALETTE];
    int root = GS[GS_ROOT], nb_colours = GS[GS_NBCOL], sprop = GS[GS_SPROP];
    threadgroup int *tt = tgtree + tid * 2 * TG_NODES;
    bool shared = GS[GS_SHARED];
    // node formats: sprop -> 8-byte two-level, generic kernel -> compact (int2), lean -> 16-byte two-level
    bool quad16 = G != 1 && sprop < 0;
    device const int *dvt = shared ? A + (quad16 ? A[H_QT16] : A[H_CTREE])
                                   : GS + (sprop >= 0 ? GS[GS_QTREE] : quad16 ? GS[GS_QT16] : GS[GS_CTREE]);
    int nbr = GS[GS_NBRANCH], nlf = GS[GS_NLEAF];
    device const int *dli = shared ? A + A[H_LINFO] : GS + GS[GS_LINFO];
    if (shared) root = A[H_ROOT];
    int tree_ints = (quad16 ? 4 : 2) * nbr;
    in_tg = !shared && tree_ints + nlf <= 2 * TG_NODES;
    if (in_tg) {
        for (int k = 0; k < tree_ints; k++) tt[k] = dvt[k];
        for (int k = 0; k < nlf; k++) tt[tree_ints + k] = dli[k];
    }
    threadgroup const int *tli = tt + tree_ints;
    if (sprop >= 0) root = (root & LEAF_BIT) ? 0x40 | (root & 0x3f) : root;
    device const int *lr = shared ? A + A[H_LEAVES] : GS + GS[GS_LEAVES];
    device int *pal = GS + GS[GS_PAL];

    CodeSt cs;
    init_code(cs, TA, uint(GS[GS_SPEC]), GS + GS[GS_WIN], GS[GS_WINCAP]);
    int sidx = 1 + 3 * A[H_NLFGROUPS] + 17 + g;
    device short *px = planes + plane_offsets[job.frame] + ulong(gy) * W + gx;
    Rows R;
    R.px = rowpx; R.err = rowerr; R.njobs = njobs; R.maxw = maxw; R.lane = gi;
    threadgroup const int *tgt = tt;
    if (palette && nb_colours > 0) {
        if (in_tg) decode_channel<threadgroup const int *, false, G, ET, device int *>(overflow, c, cs, TA, tgt, root, sprop, tgdiv, tli, lr, pal, nb_colours,
                                                                  nb_colours, 1, 0, sidx, wp, R, use_wp, gw);
        else decode_channel<device const int *, false, G, ET, device int *>(overflow, c, cs, TA, dvt, root, sprop, tgdiv, dli, lr, pal, nb_colours,
                                                       nb_colours, 1, 0, sidx, wp, R, use_wp, gw);
    }
    int cidx = palette ? 1 : 0;
    if (in_tg) decode_channel<threadgroup const int *, true, G, ET, device short *>(overflow, c, cs, TA, tgt, root, sprop, tgdiv, tli, lr, px, W, gw, gh, cidx,
                                                             sidx, wp, R, use_wp, gw);
    else decode_channel<device const int *, true, G, ET, device short *>(overflow, c, cs, TA, dvt, root, sprop, tgdiv, dli, lr, px, W, gw, gh, cidx, sidx, wp,
                                                  R, use_wp, gw);
    if (overflow) { GS[GS_GENERIC] = 1; return; } // redo with 32-bit errors (state in GS is untouched)
    finish_code(c, cs);
    finish_section(c);
    if (palette && !c.err) { // inverse palette, in place
        int nb_deltas = GS[GS_NBDELTA], d_pred = GS[GS_DPRED], bpp = A[H_BPP];
        for (int y = 0; y < gh; y++) {
            for (int x = 0; x < gw; x++) {
                int idx = px[y * W + x], val;
                if (idx < 0) {
                    val = palette_delta0((~idx) % 143);
                    if (bpp > 8) val <<= min(bpp, 24) - 8;
                } else if (idx < nb_colours) {
                    val = pal[idx];
                } else {
                    int j = idx - nb_colours;
                    val = j < 64 ? (j % 4) * ((1 << bpp) - 1) / 4 + (1 << max(0, bpp - 3))
                                 : ((j - 64) % 5) * ((1 << bpp) - 1) / 4;
                }
                if (nb_deltas > 0 && idx < nb_deltas) val += predict_simple(d_pred, px, W, x, y, gw);
                if (val != int(short(val))) c.err = E_RANGE * 1000 + 2;
                px[y * W + x] = short(val);
            }
        }
    }
    GS[GS_ERR] = c.err;
    status[4 * (job_base + gi)] = c.err;
}

#define GROUP_DECODE_KERNEL(NAME, G, ET)                                                                              \
    kernel void NAME(GROUP_KERNEL_ARGS) {                                                                         \
        threadgroup int2 tgtree2[32 * TG_NODES];                                                                  \
        threadgroup int *tgtree = (threadgroup int *)tgtree2;                                                     \
        threadgroup int tgdiv[1];                                                                                 \
        if (gi >= njobs) return;                                                                                  \
        group_decode<G, ET>(src, arenas, arena_ints, jobs, njobs, planes, plane_offsets, scratch, scratch_ints,      \
                        status, rowpx, rowerr, maxw, job_base, gi, tid, tgtree, tgdiv);                          \
    }

// ANS without LZ77: lean kernels, one per tree shape so each stays small in registers.
GROUP_DECODE_KERNEL(jxl_group_decode_lean, 0, ushort)
GROUP_DECODE_KERNEL(jxl_group_decode_lean_multi, 2, ushort)
// Prefix codes and/or LZ77, deep or unusual trees, or a lean group whose WP errors overflowed.
GROUP_DECODE_KERNEL(jxl_group_decode_generic, 1, int)

// Global single-channel palette, inverse: one thread per pixel (no delta prediction).
kernel void jxl_inverse_palette(device const int *arenas [[buffer(1)]], constant uint &arena_ints [[buffer(2)]],
                                device short *planes [[buffer(5)]], device const ulong *plane_offsets [[buffer(6)]],
                                constant uint &frame [[buffer(14)]], uint i [[thread_position_in_grid]]) {
    device const int *A = arenas + ulong(frame) * arena_ints;
    if (!A[H_PALETTE] || i >= uint(A[H_WIDTH] * A[H_HEIGHT])) return;
    device short *px = planes + plane_offsets[frame] + i;
    int idx = *px, nb_colours = A[H_PAL_N], bpp = A[H_BPP], val;
    if (idx < 0) {
        val = palette_delta0((~idx) % 143);
        if (bpp > 8) val <<= min(bpp, 24) - 8;
    } else if (idx < nb_colours) {
        val = A[A[H_PAL] + idx];
    } else {
        int j = idx - nb_colours;
        val = j < 64 ? (j % 4) * ((1 << bpp) - 1) / 4 + (1 << max(0, bpp - 3)) : ((j - 64) % 5) * ((1 << bpp) - 1) / 4;
    }
    *px = short(val);
}
