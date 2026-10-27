//! Lossless JPEG XL encoder: per-pixel work and ANS coding on Metal, headers and tables on
//! the CPU. Output is a standard codestream (one grey modular frame, 128 x 128 groups, one
//! frame-wide MA tree and entropy code, like `cjxl --buffering=0 -g 0`).
//!
//! usage: jxl-metal encode in.pgm out.jxl
//!
//! Every field is written in the order the decoder in shaders/jxl.metal reads it; the
//! functions there are the reference for the bit layouts used here.
use anyhow::{Context, Result, ensure};
use metal::{CompileOptions, Device, MTLResourceOptions, MTLSize};
use objc::rc::autoreleasepool;
use crate::decode::wait_completed;
use std::{ffi::c_void, mem::size_of, path::PathBuf, time::Instant};

const ANS_INIT: u32 = 0x130000;
const LOG_ALPHA: u32 = 8; // 256-symbol ANS tables
const GSHIFT: u32 = 7; // 128 x 128 groups
const PREDICTOR: u32 = 5; // gradient
const HYBRID: (u32, u32, u32) = (4, 1, 1); // split exponent, msb, lsb for pixel tokens

// ---------------------------------------------------------------- bit writer

#[derive(Default)]
struct Bits {
    out: Vec<u8>,
    acc: u64,
    n: u32,
}

impl Bits {
    fn put(&mut self, v: u64, k: u32) {
        debug_assert!(k == 64 || v >> k == 0, "value {v} does not fit {k} bits");
        if k == 0 {
            return;
        }
        let mut v = v;
        let mut k = k;
        while k > 0 {
            let take = k.min(32);
            self.acc |= (v & ((1u64 << take) - 1)) << self.n;
            self.n += take;
            v >>= take.min(63);
            k -= take;
            while self.n >= 8 {
                self.out.push(self.acc as u8);
                self.acc >>= 8;
                self.n -= 8;
            }
        }
    }
    fn bit(&mut self, b: bool) {
        self.put(b as u64, 1);
    }
    fn zero_pad(&mut self) {
        if self.n > 0 {
            self.put(0, 8 - self.n);
        }
    }
    /// U32 field: the first distribution whose range holds `v`.
    fn u32s(&mut self, v: u32, d: [(u32, u32); 4]) {
        for (sel, (off, nbits)) in d.iter().enumerate() {
            if v >= *off && (v - off) as u64 >> nbits == 0 {
                self.put(sel as u64, 2);
                self.put((v - off) as u64, *nbits);
                return;
            }
        }
        panic!("{v} does not fit the U32 field");
    }
    fn enum_v(&mut self, v: u32) {
        self.u32s(v, [(0, 0), (1, 0), (2, 4), (18, 6)]);
    }
    fn u64_zero(&mut self) {
        self.put(0, 2);
    }
    fn u8v(&mut self, v: u32) {
        if v == 0 {
            self.bit(false);
        } else {
            let n = 31 - v.leading_zeros();
            self.bit(true);
            self.put(n as u64, 3);
            self.put((v - (1 << n)) as u64, n);
        }
    }
    fn at_most(&mut self, v: u32, max: u32) {
        if max > 0 {
            self.put(v as u64, 32 - max.leading_zeros());
        }
    }
    fn append(&mut self, bytes: &[u8]) {
        assert_eq!(self.n, 0);
        self.out.extend_from_slice(bytes);
    }
}

fn pack_signed(v: i32) -> u32 {
    if v >= 0 { (v as u32) << 1 } else { ((-v) as u32) * 2 - 1 }
}

// ---------------------------------------------------------------- ANS tables

/// Normalised frequencies (sum 4096) over 2^LOG_ALPHA symbols.
fn normalize(counts: &[u32]) -> Vec<u32> {
    let total: u64 = counts.iter().map(|&c| c as u64).sum();
    let mut d = vec![0u32; counts.len()];
    if total == 0 {
        d[0] = 4096;
        return d;
    }
    for (i, &c) in counts.iter().enumerate() {
        if c > 0 {
            d[i] = ((c as u64 * 4096 + total / 2) / total).max(1) as u32;
        }
    }
    // put the rounding error on the largest entries (keeping every used symbol >= 1)
    let mut sum: i64 = d.iter().map(|&x| x as i64).sum();
    while sum != 4096 {
        let big = (0..d.len()).max_by_key(|&i| d[i]).unwrap();
        if sum > 4096 {
            let take = (sum - 4096).min(d[big] as i64 - 1);
            d[big] -= take as u32;
            sum -= take;
        } else {
            d[big] += (4096 - sum) as u32;
            sum = 4096;
        }
    }
    d
}

/// The decoder's prefix code for log counts (LOGCOUNT in jxl.metal), as (bits, length).
fn logcount_code(v: u32) -> (u64, u32) {
    const T: [i32; 20] = [
        0xa0003, -16, 0x70003, 0x30004, 0x60003, 0x80003, 0x90003, 0x50004, 0xa0003, 0x40004, 0x70003,
        0x10004, 0x60003, 0x80003, 0x90003, 0x20004, 0x00011, 0xb0022, 0xc0003, 0xd0043,
    ];
    let mut best: Option<(u64, u32)> = None;
    for idx in 0..16u64 {
        let e = T[idx as usize];
        if e >= 0 && (e >> 16) as u32 == v {
            let len = (e & 15) as u32;
            let code = idx & ((1 << len) - 1);
            if best.is_none_or(|b| len < b.1) {
                best = Some((code, len));
            }
        }
    }
    for e in &T[16..] {
        if (e >> 16) as u32 == v {
            let (code, len) = (((e >> 4) & 0xfff) as u64, (e & 15) as u32);
            best = Some((1 | code << 4, 4 + len)); // escape 0b0001, then the code
        }
    }
    best.expect("no log-count code")
}

/// read_ans_table: single symbol, or the general form with exact counts (shift 13).
fn write_table(b: &mut Bits, d: &[u32]) {
    let used: Vec<usize> = (0..d.len()).filter(|&i| d[i] > 0).collect();
    if used.len() == 1 {
        b.put(1, 2);
        b.u8v(used[0] as u32);
        return;
    }
    b.put(0, 2);
    b.put(0b111, 3); // shift length 3 ...
    b.put(6, 3); //    ... shift = 7 + 6 = 13: every count is stored exactly
    let alpha = (*used.last().unwrap() + 1).max(3);
    b.u8v(alpha as u32 - 3);
    let code = |x: u32| if x == 0 { 0 } else { 32 - x.leading_zeros() };
    let codes: Vec<u32> = (0..alpha).map(|i| code(d[i])).collect();
    let omit_log = *codes.iter().max().unwrap();
    let omit = codes.iter().position(|&c| c == omit_log).unwrap();
    for &c in &codes {
        let (bits, len) = logcount_code(c);
        b.put(bits, len);
    }
    for i in 0..alpha {
        let c = codes[i];
        if i == omit || c < 2 {
            continue;
        }
        let lg = c - 1;
        let bitcount = lg.min(13u32.saturating_sub((12 - lg) >> 1));
        b.put(((d[i] - (1 << lg)) >> (lg - bitcount)) as u64, bitcount);
    }
}

fn uniform(alpha: u32) -> Vec<u32> {
    let mut d = vec![0u32; 1 << LOG_ALPHA];
    for i in 0..alpha {
        d[i as usize] = 4096 / alpha + (i < 4096 % alpha) as u32;
    }
    d
}

/// Encoder view of the decoder's alias table: slot k of symbol s -> state index.
struct EncTable {
    freq: Vec<u16>,
    start: Vec<u16>,
    rev: Vec<u16>,
}

fn enc_table(d: &[u32]) -> EncTable {
    let ts = 1usize << LOG_ALPHA;
    let lb = 12 - LOG_ALPHA;
    let bs = 1i32 << lb;
    // init_alias, as in the decoder
    let mut cut = vec![0i32; ts];
    let mut off = vec![0i32; ts];
    let mut sym = vec![0i32; ts];
    let nz: Vec<usize> = (0..ts).filter(|&i| d[i] > 0).collect();
    if nz.len() == 1 {
        for j in 0..ts {
            cut[j] = 0;
            off[j] = (j as i32) << lb;
            sym[j] = nz[0] as i32;
        }
    } else {
        let (mut under, mut over) = (-1i32, -1i32);
        let mut next = vec![0i32; ts];
        for i in 0..ts {
            cut[i] = d[i] as i32;
            if cut[i] > bs {
                next[i] = over;
                over = i as i32;
            } else if cut[i] < bs {
                next[i] = under;
                under = i as i32;
            } else {
                sym[i] = i as i32;
                next[i] = 0;
            }
        }
        while over >= 0 {
            let (u, o) = (under as usize, over as usize);
            assert!(under >= 0);
            let by = bs - cut[u];
            let tmp = next[u];
            cut[o] -= by;
            sym[u] = o as i32;
            next[u] = cut[o] - cut[u];
            under = tmp;
            if cut[o] < bs {
                let t = next[o];
                next[o] = under;
                under = o as i32;
                over = t;
            } else if cut[o] == bs {
                let t = next[o];
                next[o] = 0;
                over = t;
            }
        }
        off = next; // the decoder keeps offset_or_next in the same slot
    }
    // finalize_spec: full buckets are their own symbol
    for j in 0..ts {
        if cut[j] >= bs {
            cut[j] = bs;
            sym[j] = j as i32;
            off[j] = 0;
        }
    }
    let mut start = vec![0u16; ts];
    let mut acc = 0u32;
    for s in 0..ts {
        start[s] = acc as u16;
        acc += d[s];
    }
    assert_eq!(acc, 4096);
    let mut rev = vec![u16::MAX; 4096];
    for idx in 0..4096i32 {
        let (bucket, pos) = ((idx >> lb) as usize, idx & (bs - 1));
        let (s, k) = if pos < cut[bucket] { (bucket, pos) } else { (sym[bucket] as usize, off[bucket] + pos) };
        assert!(k >= 0 && (k as u32) < d[s], "alias slot outside its symbol");
        let at = start[s] as usize + k as usize;
        assert_eq!(rev[at], u16::MAX, "alias slot used twice");
        rev[at] = idx as u16;
    }
    EncTable { freq: d.iter().map(|&x| x as u16).collect(), start, rev }
}

// ---------------------------------------------------------------- MA tree

#[repr(C)]
#[derive(Clone, Copy, Debug)]
struct Node {
    prop: i32, // < 0: leaf, ctx = !prop
    threshold: i32,
    left: i32,
    right: i32,
}

enum Tree {
    Leaf,
    Split(u32, i32, Box<Tree>, Box<Tree>), // property, threshold, value > threshold, else
}

/// Balanced split of `prop` over sorted thresholds; each interval gets `inner()`.
fn ladder(prop: u32, t: &[i32], inner: &dyn Fn() -> Tree) -> Tree {
    if t.is_empty() {
        return inner();
    }
    let m = t.len() / 2;
    Tree::Split(prop, t[m], Box::new(ladder(prop, &t[m + 1..], inner)), Box::new(ladder(prop, &t[..m], inner)))
}

/// Breadth-first nodes with absolute child indices; leaves numbered in that order.
fn flatten(tree: Tree) -> Vec<Node> {
    let mut queue = std::collections::VecDeque::from([tree]);
    let mut nodes = Vec::new();
    let mut next = 1i32;
    let mut leaves = 0;
    while let Some(t) = queue.pop_front() {
        match t {
            Tree::Leaf => {
                nodes.push(Node { prop: !leaves, threshold: 0, left: 0, right: 0 });
                leaves += 1;
            }
            Tree::Split(p, th, l, r) => {
                nodes.push(Node { prop: p as i32, threshold: th, left: next, right: next + 1 });
                next += 2;
                queue.push_back(*l);
                queue.push_back(*r);
            }
        }
    }
    nodes
}

fn fixed_tree() -> Vec<Node> {
    const T: [i32; 8] = [-48, -16, -6, -2, 1, 5, 15, 47];
    flatten(ladder(10, &T, &|| ladder(11, &T, &|| Tree::Leaf)))
}

/// read_tree: the tree's own code (6 contexts, one uniform cluster), its tokens, then the
/// data code spec is written by the caller.
fn write_tree(b: &mut Bits, nodes: &[Node]) {
    let mut tokens = Vec::new();
    for n in nodes {
        if n.prop < 0 {
            tokens.extend([(1, 0), (2, PREDICTOR), (3, pack_signed(0)), (4, 0), (5, 0)]);
        } else {
            tokens.extend([(1, n.prop as u32 + 1), (0, pack_signed(n.threshold))]);
        }
    }
    let alpha = tokens.iter().map(|t| hybrid(t.1, TREE_CFG).0).max().unwrap() + 1;
    // code spec for 6 contexts: no LZ77, simple cluster map onto one cluster, ANS,
    // direct tokens (split exponent = log alpha), uniform table
    b.bit(false);
    b.bit(true);
    b.put(0, 2);
    b.bit(false);
    b.put((LOG_ALPHA - 5) as u64, 2);
    b.at_most(TREE_CFG.0, LOG_ALPHA);
    b.at_most(TREE_CFG.1, TREE_CFG.0);
    b.at_most(TREE_CFG.2, TREE_CFG.0 - TREE_CFG.1);
    b.put(2, 2);
    b.u8v(alpha - 1);
    let tab = enc_table(&uniform(alpha));
    let flat: Vec<(usize, u32)> = tokens.iter().map(|&(_, t)| (0, t)).collect();
    write_stream(b, &flat, std::slice::from_ref(&tab), TREE_CFG);
}

/// Hybrid uint: (token, raw bits, number of raw bits).
fn hybrid(v: u32, (split, msb, lsb): (u32, u32, u32)) -> (u32, u64, u32) {
    if v < 1 << split {
        return (v, 0, 0);
    }
    let e = 31 - v.leading_zeros();
    let m = v - (1 << e);
    let nbits = e - msb - lsb;
    let token = (1 << split) + ((e - split) << (msb + lsb)) + ((m >> (e - msb)) << lsb) + (m & ((1 << lsb) - 1));
    (token, ((v >> lsb) & ((1 << nbits) - 1)) as u64, nbits)
}

/// ANS stream of (table, value) with one hybrid config: initial state, then per value its
/// renormalisation word (if any) followed by its raw bits.
fn write_stream(b: &mut Bits, values: &[(usize, u32)], tables: &[EncTable], cfg: (u32, u32, u32)) {
    let coded: Vec<(usize, u32, u64, u32)> = values
        .iter()
        .map(|&(c, v)| {
            let (t, bits, n) = hybrid(v, cfg);
            (c, t, bits, n)
        })
        .collect();
    let mut state = ANS_INIT;
    let mut words = vec![None; coded.len()];
    for (i, &(c, t, _, _)) in coded.iter().enumerate().rev() {
        let tab = &tables[c];
        let f = tab.freq[t as usize] as u32;
        assert!(f > 0, "token {t} has no frequency");
        if (state >> 20) >= f {
            words[i] = Some(state & 0xffff);
            state >>= 16;
        }
        state = ((state / f) << 12) + tab.rev[tab.start[t as usize] as usize + (state % f) as usize] as u32;
    }
    b.put((state & 0xffff) as u64, 16);
    b.put((state >> 16) as u64, 16);
    for (w, &(_, _, bits, n)) in words.into_iter().zip(&coded) {
        if let Some(w) = w {
            b.put(w as u64, 16);
        }
        b.put(bits, n);
    }
}

const DIRECT: (u32, u32, u32) = (LOG_ALPHA, 0, 0); // tokens are the values (< 256)
const TREE_CFG: (u32, u32, u32) = (4, 0, 0);

/// Data code spec: cluster map (context -> table) and one ANS table per cluster.
fn write_data_spec(b: &mut Bits, map: &[u16], tables_d: &[Vec<u32>]) {
    let (n, k) = (map.len() as u32, tables_d.len() as u32);
    b.bit(false); // no LZ77
    if n > 1 {
        if k <= 8 {
            b.bit(true); // simple map: fixed-width entries
            let nbits = 32 - (k - 1).leading_zeros();
            b.put(nbits as u64, 2);
            for &c in map {
                b.put(c as u64, nbits);
            }
        } else {
            b.bit(false);
            b.bit(false); // no move-to-front
            // nested spec (one distribution): no LZ77, ANS, direct tokens, uniform over k
            b.bit(false);
            b.bit(false);
            b.put((LOG_ALPHA - 5) as u64, 2);
            b.at_most(LOG_ALPHA, LOG_ALPHA);
            b.put(2, 2);
            b.u8v(k - 1);
            let tab = enc_table(&uniform(k));
            let ids: Vec<(usize, u32)> = map.iter().map(|&c| (0, c as u32)).collect();
            write_stream(b, &ids, std::slice::from_ref(&tab), DIRECT);
        }
    }
    b.bit(false); // ANS
    b.put((LOG_ALPHA - 5) as u64, 2);
    let (split, msb, lsb) = HYBRID;
    for _ in 0..k {
        b.at_most(split, LOG_ALPHA);
        b.at_most(msb, split);
        b.at_most(lsb, split - msb);
    }
    for d in tables_d {
        write_table(b, d);
    }
}

/// x * log2(x), from a table for small counts.
struct XLogX(Vec<f64>);

impl XLogX {
    fn new() -> Self {
        Self((0..1u32 << 16).map(|x| if x == 0 { 0. } else { x as f64 * (x as f64).log2() }).collect())
    }
    #[inline]
    fn get(&self, x: u64) -> f64 {
        if x < 1 << 16 { self.0[x as usize] } else { x as f64 * (x as f64).log2() }
    }
    /// Entropy-coded size of `a` (+ `b`, if given) in bits, without allocating.
    #[inline]
    fn cost(&self, a: &[u64], b: Option<&[u64]>) -> f64 {
        let (mut n, mut s) = (0u64, 0.);
        match b {
            Some(b) => {
                for (x, y) in a.iter().zip(b) {
                    let v = x + y;
                    n += v;
                    s += self.get(v);
                }
            }
            None => {
                for &v in a {
                    n += v;
                    s += self.get(v);
                }
            }
        }
        self.get(n) - s
    }
}

/// Greedy histogram clustering: contexts (largest first) join the cluster whose cost grows
/// least, or open a new one when that growth beats `new_bits` (about a table's cost);
/// then two reassignment passes. Returns context -> cluster and the cluster histograms.
fn cluster(h: &[u32], nctx: usize, max_k: usize, new_bits: f64) -> (Vec<u16>, Vec<Vec<u64>>) {
    // only the token range that occurs
    let nt = (0..256).rev().find(|&t| (0..nctx).any(|c| h[c * 256 + t] > 0)).map_or(1, |t| t + 1);
    let ctx: Vec<Vec<u64>> = (0..nctx).map(|c| h[c * 256..c * 256 + nt].iter().map(|&x| x as u64).collect()).collect();
    let xl = XLogX::new();
    let own: Vec<f64> = ctx.iter().map(|c| xl.cost(c, None)).collect();
    let totals: Vec<u64> = ctx.iter().map(|c| c.iter().sum()).collect();
    let mut order: Vec<usize> = (0..nctx).collect();
    order.sort_by_key(|&c| std::cmp::Reverse(totals[c]));
    let mut clusters: Vec<Vec<u64>> = Vec::new();
    let mut ccost: Vec<f64> = Vec::new();
    let mut map = vec![0usize; nctx];
    let add = |k: &mut Vec<u64>, c: &[u64], sign: i64| {
        for (x, y) in k.iter_mut().zip(c) {
            *x = (*x as i64 + sign * *y as i64) as u64;
        }
    };
    for &c in &order {
        let best = (0..clusters.len())
            .map(|i| (xl.cost(&clusters[i], Some(&ctx[c])) - ccost[i] - own[c], i))
            .min_by(|a, b| a.0.total_cmp(&b.0));
        match best {
            Some((inc, i)) if clusters.len() >= max_k || inc <= new_bits || totals[c] == 0 => {
                add(&mut clusters[i], &ctx[c], 1);
                ccost[i] = xl.cost(&clusters[i], None);
                map[c] = i;
            }
            _ => {
                map[c] = clusters.len();
                clusters.push(ctx[c].clone());
                ccost.push(own[c]);
            }
        }
    }
    for _ in 0..2 {
        for &c in &order {
            let o = map[c];
            let mut without = clusters[o].clone();
            add(&mut without, &ctx[c], -1);
            let without_cost = xl.cost(&without, None);
            let stay = ccost[o] - without_cost;
            let best = (0..clusters.len())
                .filter(|&i| i != o)
                .map(|i| (xl.cost(&clusters[i], Some(&ctx[c])) - ccost[i], i))
                .min_by(|a, b| a.0.total_cmp(&b.0));
            if let Some((inc, i)) = best
                && inc < stay
            {
                clusters[o] = without;
                ccost[o] = without_cost;
                add(&mut clusters[i], &ctx[c], 1);
                ccost[i] = xl.cost(&clusters[i], None);
                map[c] = i;
            }
        }
    }
    // drop emptied clusters, number the rest by first use, widen back to 256 tokens
    let mut renum = vec![u16::MAX; clusters.len()];
    let mut out = Vec::new();
    let mut m16 = vec![0u16; nctx];
    for c in 0..nctx {
        let k = map[c];
        if renum[k] == u16::MAX {
            renum[k] = out.len() as u16;
            let mut wide = clusters[k].clone();
            wide.resize(256, 0);
            out.push(wide);
        }
        m16[c] = renum[k];
    }
    (m16, out)
}

// ---------------------------------------------------------------- headers

fn write_headers(b: &mut Bits, w: u32, h: u32, bits: u32) {
    b.put(0xff, 8);
    b.put(0x0a, 8);
    let dim = [(1, 9), (1, 13), (1, 18), (1, 30)];
    b.bit(false); // not div8
    b.u32s(h, dim);
    b.put(0, 3); // explicit width
    b.u32s(w, dim);
    // ImageMetadata
    b.bit(false); // !all_default
    b.bit(false); // no extra fields
    b.bit(false); // integer samples
    b.u32s(bits, [(8, 0), (10, 0), (12, 0), (1, 6)]);
    b.bit(true); // modular 16-bit buffers
    b.put(0, 2); // no extra channels
    b.bit(false); // not XYB
    b.bit(false); // colour encoding: !all_default
    b.bit(false); // no ICC
    b.enum_v(1); // grey
    b.enum_v(1); // D65
    b.bit(false); // no gamma
    b.enum_v(8); // linear
    b.enum_v(0); // perceptual
    b.u64_zero(); // extensions
    b.bit(true); // default transform data
    // FrameHeader
    b.zero_pad();
    b.bit(false); // !all_default
    b.put(0, 2); // regular frame
    b.bit(true); // modular
    b.u64_zero(); // flags
    b.bit(false); // no YCbCr
    b.put(0, 2); // no upsampling
    b.put((GSHIFT - 7) as u64, 2);
    b.put(0, 2); // one pass
    b.bit(false); // no crop
    b.put(0, 2); // blend: replace
    b.bit(true); // last frame
    b.put(0, 2); // empty name
    b.bit(false); // restoration: !all_default
    b.bit(false); // no Gabor-like filter
    b.put(0, 2); // no edge-preserving filter
    b.u64_zero(); // restoration extensions
    b.u64_zero(); // frame extensions
}

fn write_toc(b: &mut Bits, sizes: &[u32]) {
    b.bit(false); // not permuted
    b.zero_pad();
    for &s in sizes {
        b.u32s(s, [(0, 10), (1024, 14), (17408, 22), (4211712, 30)]);
    }
    b.zero_pad();
}

// ---------------------------------------------------------------- tree learning

const NPROPS: usize = 13; // properties 2..14
const NQ: usize = 32;
const NT: usize = 64;

#[repr(C)]
#[derive(Clone, Copy)]
struct LNode {
    prop: i32, // < 0: leaf
    k: i32,    // branch: threshold index; leaf: frontier slot or -1
    left: i32,
    right: i32,
}

fn env_or<T: std::str::FromStr>(name: &str, default: T) -> T {
    std::env::var(name).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}

fn dispatch(queue: &metal::CommandQueueRef, k: &metal::ComputePipelineState, n: u64, bind: &dyn Fn(&metal::ComputeCommandEncoderRef)) -> Result<()> {
    let cb = queue.new_command_buffer();
    let enc = cb.new_compute_command_encoder();
    enc.set_compute_pipeline_state(k);
    bind(enc);
    enc.dispatch_threads(MTLSize::new(n, 1, 1), MTLSize::new(256.min(n), 1, 1));
    enc.end_encoding();
    cb.commit();
    wait_completed(cb, "model learning")
}

fn set_u32(enc: &metal::ComputeCommandEncoderRef, i: u64, v: &u32) {
    enc.set_bytes(i, 4, v as *const u32 as *const c_void);
}

/// Greedy top-down MA tree on a pixel sample: each frontier node takes the (property,
/// threshold) split that saves the most entropy, if the saving beats `JXL_SPLIT_BITS`
/// (per real frame, the cost of one more context); at most `JXL_MAX_LEAVES` leaves.
fn learn_tree(
    dev: &Device,
    queue: &metal::CommandQueueRef,
    lib: &metal::LibraryRef,
    px_buf: &metal::Buffer,
    params: &FrameParams,
) -> Result<Vec<Node>> {
    let pipeline = |name: &str| -> Result<metal::ComputePipelineState> {
        let f = lib.get_function(name, None).map_err(anyhow::Error::msg)?;
        dev.new_compute_pipeline_state_with_function(&f).map_err(anyhow::Error::msg)
    };
    let stride: u32 = env_or("JXL_STRIDE", 8);
    let split_bits: f64 = env_or("JXL_SPLIT_BITS", 400.);
    let max_leaves: usize = env_or("JXL_MAX_LEAVES", 2048).min(8000);
    // bit p: property p may be split on. Not 8: libjxl rejects streams that use it (djxl
    // fails while J40 and our decoder agree), and libjxl itself never splits on it.
    let props_mask: u32 = env_or("JXL_PROPS", 0x7efc);
    let nsamples = params.w * params.h / stride;
    let scale = stride as f64; // sample bits -> frame bits
    let fp = params as *const FrameParams as *const c_void;
    let fp_len = size_of::<FrameParams>() as u64;

    // thresholds: 31 quantiles of each property's values
    let vhist = buffer(dev, &vec![0u32; NPROPS * 8192]);
    dispatch(queue, &pipeline("learn_values")?, nsamples as u64, &|e| {
        e.set_buffer(0, Some(px_buf), 0);
        e.set_bytes(1, fp_len, fp);
        set_u32(e, 2, &stride);
        set_u32(e, 3, &nsamples);
        e.set_buffer(4, Some(&vhist), 0);
    })?;
    let vh = unsafe { std::slice::from_raw_parts(vhist.contents() as *const u32, NPROPS * 8192) };
    let mut thr = vec![0i32; NPROPS * (NQ - 1)];
    for k in 0..NPROPS {
        let h = &vh[k * 8192..(k + 1) * 8192];
        let total: u64 = h.iter().map(|&x| x as u64).sum();
        let (mut acc, mut v) = (0u64, 0usize);
        for j in 1..NQ {
            let target = total * j as u64 / NQ as u64;
            while v < 8191 && acc + (h[v] as u64) <= target {
                acc += h[v] as u64;
                v += 1;
            }
            thr[k * (NQ - 1) + j - 1] = v as i32 - 4096;
        }
    }
    let thr_buf = buffer(dev, &thr);
    let q_buf = dev.new_buffer(nsamples as u64 * NPROPS as u64, MTLResourceOptions::StorageModePrivate);
    let tok_buf = dev.new_buffer(nsamples as u64, MTLResourceOptions::StorageModePrivate);
    dispatch(queue, &pipeline("learn_quantise")?, nsamples as u64, &|e| {
        e.set_buffer(0, Some(px_buf), 0);
        e.set_bytes(1, fp_len, fp);
        set_u32(e, 2, &stride);
        set_u32(e, 3, &nsamples);
        e.set_buffer(4, Some(&thr_buf), 0);
        e.set_buffer(5, Some(&q_buf), 0);
        e.set_buffer(6, Some(&tok_buf), 0);
    })?;

    let hist_k = pipeline("learn_hist")?;
    let gain_k = pipeline("learn_gain")?;
    let ngain = NPROPS * (NQ - 1);
    let mut tree = vec![LNode { prop: -1, k: 0, left: 0, right: 0 }];
    let mut frontier = vec![0usize];
    let mut leaves = 1usize;
    let per_slot = NPROPS * NQ * NT;
    const CHUNK: usize = 256; // frontier nodes per histogram dispatch (~27 MB)
    let hist = dev.new_buffer((CHUNK * per_slot * 4) as u64, MTLResourceOptions::StorageModePrivate);
    let zero = buffer(dev, &vec![0u32; CHUNK * per_slot]);
    let gains = dev.new_buffer((CHUNK * ngain * 4) as u64, MTLResourceOptions::StorageModeShared);
    let mut next = Vec::new();
    while !frontier.is_empty() {
        let chunk: Vec<usize> = frontier.drain(..frontier.len().min(CHUNK)).collect();
        for (slot, &n) in chunk.iter().enumerate() {
            tree[n].k = slot as i32;
        }
        for &n in &frontier {
            tree[n].k = -1; // later chunk
        }
        let tree_buf = buffer(dev, &tree);
        // zero the histograms, count, then score every split, in one command buffer
        let nslots = chunk.len() as u32;
        let cb = queue.new_command_buffer();
        let blit = cb.new_blit_command_encoder();
        blit.copy_from_buffer(&zero, 0, &hist, 0, (chunk.len() * per_slot * 4) as u64);
        blit.end_encoding();
        let enc = cb.new_compute_command_encoder();
        enc.set_compute_pipeline_state(&hist_k);
        enc.set_buffer(0, Some(&q_buf), 0);
        enc.set_buffer(1, Some(&tok_buf), 0);
        set_u32(enc, 2, &nsamples);
        enc.set_buffer(3, Some(&tree_buf), 0);
        enc.set_buffer(4, Some(&hist), 0);
        enc.dispatch_threads(MTLSize::new(nsamples as u64, 1, 1), MTLSize::new(256, 1, 1));
        enc.end_encoding();
        let enc = cb.new_compute_command_encoder();
        enc.set_compute_pipeline_state(&gain_k);
        enc.set_buffer(0, Some(&hist), 0);
        set_u32(enc, 1, &nslots);
        enc.set_buffer(2, Some(&gains), 0);
        let n = (chunk.len() * ngain) as u64;
        enc.dispatch_threads(MTLSize::new(n, 1, 1), MTLSize::new(256.min(n), 1, 1));
        enc.end_encoding();
        cb.commit();
        wait_completed(cb, "model learning")?;
        let gs = unsafe { std::slice::from_raw_parts(gains.contents() as *const f32, chunk.len() * ngain) };
        for (slot, &n) in chunk.iter().enumerate() {
            let mut best = (0f64, 0usize, 0usize);
            for p in 0..NPROPS {
                if props_mask >> (p + 2) & 1 == 0 {
                    continue;
                }
                for k in 0..NQ - 1 {
                    let gain = gs[slot * ngain + p * (NQ - 1) + k] as f64;
                    if gain > best.0 {
                        best = (gain, p, k);
                    }
                }
            }
            if leaves < max_leaves && best.0 * scale > split_bits {
                let l = tree.len() as i32;
                // new leaves get a histogram slot when their round comes
                tree.push(LNode { prop: -1, k: -1, left: 0, right: 0 });
                tree.push(LNode { prop: -1, k: -1, left: 0, right: 0 });
                tree[n] = LNode { prop: best.1 as i32, k: best.2 as i32, left: l, right: l + 1 };
                next.push(l as usize);
                next.push(l as usize + 1);
                leaves += 1;
            } else {
                tree[n].k = -1;
            }
        }
        if frontier.is_empty() {
            frontier = std::mem::take(&mut next);
        }
    }
    fn build(t: &[LNode], n: usize, thr: &[i32]) -> Tree {
        let x = t[n];
        if x.prop < 0 {
            return Tree::Leaf;
        }
        let p = x.prop as usize;
        Tree::Split(
            p as u32 + 2,
            thr[p * (NQ - 1) + x.k as usize],
            Box::new(build(t, x.left as usize, thr)),
            Box::new(build(t, x.right as usize, thr)),
        )
    }
    Ok(flatten(build(&tree, 0, &thr)))
}

// ---------------------------------------------------------------- Metal

fn buffer<T: Copy>(dev: &Device, data: &[T]) -> metal::Buffer {
    dev.new_buffer_with_data(
        data.as_ptr() as *const c_void,
        (data.len() * size_of::<T>()).max(4) as u64,
        MTLResourceOptions::StorageModeShared,
    )
}

#[repr(C)]
struct FrameParams {
    w: u32,
    h: u32,
    gshift: u32,
    gcols: u32,
    nnodes: u32,
    nctx: u32,
    ngroups: u32,
    stride: u32,
    split: u32,
    msb: u32,
    lsb: u32,
}

/// Encoder shader with optional `JXL_EDEFS="A B=1"` defines (timing experiments).
fn shader_source() -> String {
    let mut src = String::new();
    for d in std::env::var("JXL_EDEFS").unwrap_or_default().split_whitespace() {
        let (k, v) = d.split_once('=').unwrap_or((d, "1"));
        src += &format!("#define {k} {v}\n");
    }
    src + include_str!("../shaders/encode.metal")
}

/// Device, kernels and command queue, created once.
pub struct Encoder {
    dev: Device,
    queue: metal::CommandQueue,
    lib: metal::Library,
    tokens_k: metal::ComputePipelineState,
    tokens_hist_k: metal::ComputePipelineState,
    ans_k: metal::ComputePipelineState,
    /// scratch buffers kept between batches (a 4K batch allocates ~0.5 GB otherwise)
    pool: std::cell::RefCell<std::collections::HashMap<&'static str, metal::Buffer>>,
}

/// What a frame is coded with: the MA tree and which ANS table each leaf uses. Learnt from
/// one frame and reused for the following ones (their tables are rebuilt per frame).
pub struct Model {
    nodes: Vec<Node>,
    cmap: Vec<u16>,
    nclusters: usize,
    /// start of the LfGlobal section (LF dequantisation flag, global-tree flag, the tree),
    /// the same for every frame; the code spec after it comes from each batch's histograms.
    /// (Tables from the learning frame alone are not enough: a later frame can use a token
    /// that frame never had, which then has no frequency.)
    lf_tree: Bits,
}

/// Frame geometry shared by a batch.
struct Geometry {
    w: u32,
    h: u32,
    gcols: u32,
    ngroups: u32,
    goff: Vec<u32>,
}

impl Geometry {
    fn new(w: u32, h: u32) -> Result<Self> {
        let gs = 1u32 << GSHIFT;
        let (gcols, grows) = (w.div_ceil(gs), h.div_ceil(gs));
        let ngroups = gcols * grows;
        ensure!(ngroups > 1, "single-group images are not handled yet");
        let mut goff = vec![0u32];
        for g in 0..ngroups {
            let (gx, gy) = (g % gcols, g / gcols);
            goff.push(goff.last().unwrap() + gs.min(w - gx * gs) * gs.min(h - gy * gs));
        }
        Ok(Self { w, h, gcols, ngroups, goff })
    }
    /// Symbols per frame in the group-interleaved layout.
    fn stride(&self) -> u32 {
        self.ngroups << (2 * GSHIFT)
    }
    fn params(&self, nodes: usize, nctx: usize) -> FrameParams {
        FrameParams {
            w: self.w,
            h: self.h,
            gshift: GSHIFT,
            gcols: self.gcols,
            nnodes: nodes as u32,
            nctx: nctx as u32,
            ngroups: self.ngroups,
            stride: self.stride(),
            split: HYBRID.0,
            msb: HYBRID.1,
            lsb: HYBRID.2,
        }
    }
}

/// Timings of one batch (milliseconds).
#[derive(Default, Debug)]
pub struct Timing {
    pub upload: f64,
    pub tokens: f64,
    pub tables: f64,
    pub ans: f64,
    pub assemble: f64,
}

impl Encoder {
    pub fn new() -> Result<Self> {
        autoreleasepool(Self::new_inner)
    }

    fn new_inner() -> Result<Self> {
        let dev = Device::system_default().context("no Metal device")?;
        let lib = dev
            .new_library_with_source(&shader_source(), &CompileOptions::new())
            .map_err(|e| anyhow::anyhow!("shader compile failed:\n{e}"))?;
        let pipeline = |name: &str| -> Result<metal::ComputePipelineState> {
            let f = lib.get_function(name, None).map_err(anyhow::Error::msg)?;
            dev.new_compute_pipeline_state_with_function(&f).map_err(anyhow::Error::msg)
        };
        let (tokens_k, tokens_hist_k, ans_k) = (pipeline("enc_tokens")?, pipeline("enc_tokens_hist")?, pipeline("enc_ans")?);
        let queue = dev.new_command_queue();
        Ok(Self { dev, queue, lib, tokens_k, tokens_hist_k, ans_k, pool: Default::default() })
    }

    /// A scratch buffer of at least `bytes`, reused while big enough.
    fn scratch(&self, name: &'static str, bytes: u64, shared: bool) -> metal::Buffer {
        let mut pool = self.pool.borrow_mut();
        if let Some(b) = pool.get(name)
            && b.length() >= bytes
        {
            return b.clone();
        }
        let mode = if shared { MTLResourceOptions::StorageModeShared } else { MTLResourceOptions::StorageModePrivate };
        let b = self.dev.new_buffer(bytes.max(4), mode);
        pool.insert(name, b.clone());
        b
    }

    /// Runs the token kernel over `frames` (one plane after another) and returns the
    /// symbol, raw-bit and per-frame histogram buffers.
    fn tokens(&self, g: &Geometry, nodes: &[Node], nctx: usize, planes: &metal::Buffer, nframes: usize, hist: bool)
        -> Result<(metal::Buffer, metal::Buffer, metal::Buffer)> {
        let stride = g.stride() as u64;
        let params = g.params(nodes.len(), nctx);
        let tree_buf = buffer(&self.dev, nodes);
        let goff_buf = buffer(&self.dev, &g.goff);
        let sym = self.scratch("sym", stride * 4 * nframes as u64, false);
        let extra = self.scratch("extra", stride * 4 * nframes as u64, false);
        let hist_bytes = if hist { (nctx * 256 * nframes * 4) as u64 } else { 4 };
        let hist_buf = self.scratch("hist", hist_bytes, true);
        unsafe { std::ptr::write_bytes(hist_buf.contents() as *mut u8, 0, hist_bytes as usize) };
        let cb = self.queue.new_command_buffer();
        let enc = cb.new_compute_command_encoder();
        enc.set_compute_pipeline_state(if hist { &self.tokens_hist_k } else { &self.tokens_k });
        enc.set_buffer(0, Some(planes), 0);
        enc.set_bytes(1, size_of::<FrameParams>() as u64, &params as *const _ as *const c_void);
        enc.set_buffer(2, Some(&tree_buf), 0);
        enc.set_buffer(3, Some(&goff_buf), 0);
        enc.set_buffer(4, Some(&sym), 0);
        enc.set_buffer(5, Some(&extra), 0);
        enc.set_buffer(6, Some(&hist_buf), 0);
        enc.dispatch_threads(MTLSize::new(g.w as u64, g.h as u64, nframes as u64), MTLSize::new(32, 8, 1));
        enc.end_encoding();
        cb.commit();
        wait_completed(cb, "token encoding")?;
        Ok((sym, extra, hist_buf))
    }

    /// Learns a model (tree, then context clustering) from one frame.
    pub fn learn(&self, px: &[u16], w: usize, h: usize) -> Result<Model> {
        autoreleasepool(|| self.learn_inner(px, w, h))
    }

    fn learn_inner(&self, px: &[u16], w: usize, h: usize) -> Result<Model> {
        let g = Geometry::new(w as u32, h as u32)?;
        let planes = buffer(&self.dev, px);
        let t0 = Instant::now();
        let nodes = if std::env::var("JXL_FIXED_TREE").is_ok() {
            fixed_tree()
        } else {
            learn_tree(&self.dev, &self.queue, &self.lib, &planes, &g.params(0, 0))?
        };
        let nctx = nodes.iter().filter(|n| n.prop < 0).count();
        let t1 = Instant::now();
        let (_, _, hist) = self.tokens(&g, &nodes, nctx, &planes, 1, true)?;
        let t2 = Instant::now();
        let hist = unsafe { std::slice::from_raw_parts(hist.contents() as *const u32, nctx * 256) };
        let max_k: usize = env_or("JXL_MAX_CLUSTERS", 255).min(255);
        let (cmap, clusters) = cluster(hist, nctx, max_k, env_or("JXL_CLUSTER_BITS", 200.));
        if std::env::var("JXL_VERBOSE").is_ok() {
            eprintln!(
                "learn: tree {:.0} ms, histogram {:.0} ms, clustering {:.0} ms ({nctx} contexts -> {} clusters)",
                (t1 - t0).as_secs_f64() * 1e3,
                (t2 - t1).as_secs_f64() * 1e3,
                t2.elapsed().as_secs_f64() * 1e3,
                clusters.len()
            );
        }
        let mut lf_tree = Bits::default();
        lf_tree.bit(true); // default LF dequantisation
        lf_tree.bit(true); // global tree
        write_tree(&mut lf_tree, &nodes);
        Ok(Model { nodes, cmap, nclusters: clusters.len(), lf_tree })
    }

    /// Encodes a batch of frames (same size and bit depth) with one model.
    pub fn encode(&self, model: &Model, frames: &[&[u16]], w: usize, h: usize, bits: u32) -> Result<(Vec<Vec<u8>>, Timing)> {
        autoreleasepool(|| self.encode_inner(model, frames, w, h, bits))
    }

    fn encode_inner(&self, model: &Model, frames: &[&[u16]], w: usize, h: usize, bits: u32) -> Result<(Vec<Vec<u8>>, Timing)> {
        let mut timing = Timing::default();
        let t = Instant::now();
        let g = Geometry::new(w as u32, h as u32)?;
        let (nf, npx, nctx) = (frames.len(), w * h, model.cmap.len());
        let planes = self.scratch("planes", (npx * 2 * nf) as u64, true);
        for (i, f) in frames.iter().enumerate() {
            ensure!(f.len() == npx, "frame {i} has the wrong size");
            unsafe { std::ptr::copy_nonoverlapping(f.as_ptr(), (planes.contents() as *mut u16).add(i * npx), npx) };
        }
        timing.upload = t.elapsed().as_secs_f64() * 1e3;

        let t = Instant::now();
        let (sym, extra, hist_buf) = self.tokens(&g, &model.nodes, nctx, &planes, nf, true)?;
        timing.tokens = t.elapsed().as_secs_f64() * 1e3;

        // one table set per batch, from the batch's histograms
        let t = Instant::now();
        let k = model.nclusters;
        let hist = unsafe { std::slice::from_raw_parts(hist_buf.contents() as *const u32, nf * nctx * 256) };
        let mut ch = vec![0u32; k * 256];
        for (i, &x) in hist.iter().enumerate() {
            let (c, t) = ((i / 256) % nctx, i % 256);
            ch[model.cmap[c] as usize * 256 + t] += x;
        }
        let tables_d: Vec<Vec<u32>> = (0..k).map(|c| normalize(&ch[c * 256..(c + 1) * 256])).collect();
        let (mut sinfo, mut rev) = (Vec::new(), Vec::new());
        for t in tables_d.iter().map(|d| enc_table(d)) {
            // per symbol: freq | start << 13, and floor((2^32 - 1) / freq) for the division
            sinfo.extend(t.freq.iter().zip(&t.start).map(|(&f, &s)| {
                [f as u32 | (s as u32) << 13, if f == 0 { 0 } else { u32::MAX / f as u32 }]
            }));
            rev.extend_from_slice(&t.rev);
        }
        // LfGlobal: the model's tree, this batch's code spec, global modular header and
        // the (empty) global channel stream
        let mut lf = Bits { out: model.lf_tree.out.clone(), acc: model.lf_tree.acc, n: model.lf_tree.n };
        write_data_spec(&mut lf, &model.cmap, &tables_d);
        lf.bit(true); // use the global tree
        lf.bit(true); // default WP header
        lf.put(0, 2); // no transforms
        lf.put((ANS_INIT & 0xffff) as u64, 16);
        lf.put((ANS_INIT >> 16) as u64, 16);
        lf.zero_pad();
        let lf_global = lf.out;
        timing.tables = t.elapsed().as_secs_f64() * 1e3;

        // rANS: one thread per (frame, group)
        let out_words: u32 = (1u32 << (2 * GSHIFT)) * 30 / 32 + 64; // <= 12 ANS + 17 raw bits per pixel
        let ngg = g.ngroups as u64 * nf as u64;
        let words = self.scratch("words", g.stride() as u64 * 4 * nf as u64, false);
        let out = self.scratch("out", ngg * out_words as u64 * 4, true);
        let out_bytes = self.scratch("out_bytes", ngg * 4, true);
        // per (table, symbol): freq | start << 13, and floor((2^32 - 1) / freq) for the division
        let (goff_buf, freq_buf, start_buf, rev_buf, cmap_buf) = (
            buffer(&self.dev, &g.goff),
            buffer(&self.dev, &sinfo),
            buffer(&self.dev, &[0u16]),
            buffer(&self.dev, &rev),
            buffer(&self.dev, &model.cmap),
        );
        let t = Instant::now();
        let cb = self.queue.new_command_buffer();
        let enc = cb.new_compute_command_encoder();
        enc.set_compute_pipeline_state(&self.ans_k);
        for (i, b) in [&sym, &extra, &goff_buf, &freq_buf, &start_buf, &rev_buf, &words, &out, &out_bytes].iter().enumerate() {
            enc.set_buffer(i as u64, Some(b), 0);
        }
        let (ngroups, nfu, ku, npxu) = (g.ngroups, nf as u32, 0u32, g.stride()); // one table set
        set_u32(enc, 9, &ngroups);
        set_u32(enc, 10, &out_words);
        enc.set_buffer(11, Some(&cmap_buf), 0);
        set_u32(enc, 12, &nfu);
        set_u32(enc, 13, &ku);
        set_u32(enc, 14, &npxu);
        enc.dispatch_threads(MTLSize::new(ngg, 1, 1), MTLSize::new(32, 1, 1));
        enc.end_encoding();
        cb.commit();
        wait_completed(cb, "ANS encoding")?;
        timing.ans = t.elapsed().as_secs_f64() * 1e3;

        let t = Instant::now();
        let sizes = unsafe { std::slice::from_raw_parts(out_bytes.contents() as *const u32, ngg as usize) };
        ensure!(sizes.iter().all(|&s| s != u32::MAX), "group output overflow");
        let data = unsafe { std::slice::from_raw_parts(out.contents() as *const u8, ngg as usize * out_words as usize * 4) };
        let mut files = Vec::with_capacity(nf);
        let gs = 1u32 << GSHIFT;
        let lf_groups = g.w.div_ceil(gs * 8) * g.h.div_ceil(gs * 8);
        for z in 0..nf {
            let groups = &sizes[z * g.ngroups as usize..(z + 1) * g.ngroups as usize];
            let mut toc = vec![lf_global.len() as u32];
            toc.extend(std::iter::repeat_n(0, lf_groups as usize + 1)); // LF groups, HF global
            toc.extend_from_slice(groups);
            let mut file = Bits::default();
            write_headers(&mut file, g.w, g.h, bits);
            write_toc(&mut file, &toc);
            file.append(&lf_global);
            for (i, &n) in groups.iter().enumerate() {
                let at = (z * g.ngroups as usize + i) * out_words as usize * 4;
                file.append(&data[at..at + n as usize]);
            }
            files.push(file.out);
        }
        timing.assemble = t.elapsed().as_secs_f64() * 1e3;
        Ok((files, timing))
    }
}

/// `jxl-metal encode in.pgm out.jxl` or `jxl-metal encode OUTDIR a.pgm b.pgm ...`
/// (frames of one size; the model is learnt from the first and every JXL_RELEARN frames).
pub fn run(args: &[String]) -> Result<()> {
    ensure!(args.len() >= 2, "usage: jxl-metal encode in.pgm out.jxl | encode OUTDIR a.pgm b.pgm ...");
    let (outputs, inputs): (Vec<PathBuf>, Vec<PathBuf>) = if args.len() == 2 && args[1].ends_with(".jxl") {
        (vec![PathBuf::from(&args[1])], vec![PathBuf::from(&args[0])])
    } else {
        let dir = PathBuf::from(&args[0]);
        std::fs::create_dir_all(&dir)?;
        let inputs: Vec<PathBuf> = args[1..].iter().map(PathBuf::from).collect();
        let outputs = inputs.iter().map(|p| dir.join(p.file_stem().unwrap_or_default()).with_extension("jxl")).collect();
        (outputs, inputs)
    };
    let batch: usize = env_or("JXL_BATCH", 16).max(1);
    let relearn: usize = env_or("JXL_RELEARN", 0);
    let enc = Encoder::new()?;
    let started = Instant::now();
    let (mut model, mut learnt_at) = (None::<Model>, 0usize);
    let (mut total_bytes, mut total_px, mut learn_ms) = (0usize, 0usize, 0.);
    let mut sum = Timing::default();
    let mut i = 0;
    while i < inputs.len() {
        let n = batch.min(inputs.len() - i).min(if relearn > 0 { relearn - (i - learnt_at) % relearn } else { usize::MAX });
        let frames: Vec<(usize, usize, Vec<u16>)> = inputs[i..i + n].iter().map(crate::decode::read_pgm).collect::<Result<_>>()?;
        let (w, h) = (frames[0].0, frames[0].1);
        ensure!(frames.iter().all(|f| f.0 == w && f.1 == h), "frames differ in size");
        let maxv = frames.iter().flat_map(|f| f.2.iter().copied()).max().unwrap_or(0);
        let bits = (16 - maxv.leading_zeros()).max(8);
        if model.is_none() || (relearn > 0 && i - learnt_at >= relearn) {
            let t = Instant::now();
            model = Some(enc.learn(&frames[0].2, w, h)?);
            learn_ms += t.elapsed().as_secs_f64() * 1e3;
            learnt_at = i;
        }
        let m = model.as_ref().unwrap();
        let planes: Vec<&[u16]> = frames.iter().map(|f| f.2.as_slice()).collect();
        let (files, t) = enc.encode(m, &planes, w, h, bits)?;
        for (j, f) in files.iter().enumerate() {
            std::fs::write(&outputs[i + j], f)?;
            total_bytes += f.len();
            total_px += w * h;
        }
        sum.upload += t.upload;
        sum.tokens += t.tokens;
        sum.tables += t.tables;
        sum.ans += t.ans;
        sum.assemble += t.assemble;
        i += n;
        println!(
            "frames {}..{}: {} contexts in {} clusters, {:.3} bit/px",
            i - n,
            i,
            m.cmap.len(),
            m.nclusters,
            files.iter().map(|f| f.len()).sum::<usize>() as f64 * 8. / (n * w * h) as f64
        );
    }
    let secs = started.elapsed().as_secs_f64();
    let work = (learn_ms + sum.upload + sum.tokens + sum.tables + sum.ans + sum.assemble) / 1e3;
    println!(
        "{} frames, {:.0} bytes/frame, {:.2} bit/px; encoding {:.1} frames/s ({:.1} incl. PGM reads); learn {:.0} ms total; stage sums: {:?}",
        inputs.len(),
        total_bytes as f64 / inputs.len() as f64,
        total_bytes as f64 * 8. / total_px as f64,
        inputs.len() as f64 / work,
        inputs.len() as f64 / secs,
        learn_ms,
        sum
    );
    Ok(())
}
