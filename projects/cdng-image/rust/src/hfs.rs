//! Read-only HFS+ volume synthesised on demand (Apple TN1150).
//!
//! Layout (4 KiB allocation blocks): block 0 holds the volume header at byte 1024,
//! then the allocation bitmap (all blocks in use), the extents-overflow B-tree (header
//! node only), the catalog B-tree, every file as one contiguous extent, and the last
//! block holding the alternate volume header. Metadata is built up front; file bytes
//! come from a callback when the kernel reads them.
use anyhow::{Result, ensure};

pub const BLOCK: u64 = 4096;
const CAT_NODE: usize = 8192;
const EXT_NODE: usize = 4096;
const FIRST_CNID: u32 = 16;

/// A folder; `parent` is another folder's index, or None for the volume root.
/// Folders must come after their parent.
pub struct Dir {
    pub name: String,
    pub parent: Option<usize>,
}

/// A file in folder `dir` (None = volume root).
pub struct File {
    pub dir: Option<usize>,
    pub name: String,
    pub size: u64,
}

/// One file of the volume, in the order given to `build`.
pub struct FileSpan {
    pub cnid: u32,
    pub start: u64, // byte offset on the volume
    pub size: u64,
}

pub struct Volume {
    pub bytes: u64,
    head: Vec<u8>,         // block 0 (boot blocks + volume header)
    bitmap: (u64, u64),    // byte range of the allocation file (all 0xff)
    extents: (u64, Vec<u8>),
    catalog: (u64, Vec<u8>),
    pub files: Vec<FileSpan>,
    tail: Vec<u8>, // last block (alternate volume header at its byte 3072)
}

fn be16(b: &mut Vec<u8>, v: u16) { b.extend_from_slice(&v.to_be_bytes()); }
fn be32(b: &mut Vec<u8>, v: u32) { b.extend_from_slice(&v.to_be_bytes()); }
fn be64(b: &mut Vec<u8>, v: u64) { b.extend_from_slice(&v.to_be_bytes()); }

fn blocks(bytes: u64) -> u64 { bytes.div_ceil(BLOCK) }

/// HFSPlusForkData: one extent.
fn fork(b: &mut Vec<u8>, logical: u64, start: u64, count: u64) {
    be64(b, logical);
    be32(b, 0); // clump size
    be32(b, count as u32);
    be32(b, if count > 0 { start as u32 } else { 0 });
    be32(b, count as u32);
    b.extend_from_slice(&[0; 56]); // 7 empty extents
}

fn uni(name: &str) -> Vec<u16> { name.encode_utf16().collect() }

/// Catalog key: keyLength, parentID, HFSUniStr255.
fn cat_key(parent: u32, name: &[u16]) -> Vec<u8> {
    let mut k = Vec::new();
    be16(&mut k, (6 + 2 * name.len()) as u16);
    be32(&mut k, parent);
    be16(&mut k, name.len() as u16);
    for c in name { be16(&mut k, *c); }
    k
}

/// HFS+ catalog order: parent ID, then case-insensitive name (ASCII folding is enough
/// for camera file names; anything else is rejected when the volume is built).
/// Names that differ only in case would collide; `build` rejects them.
fn key_order(a: &(u32, Vec<u16>), b: &(u32, Vec<u16>)) -> std::cmp::Ordering {
    let fold = |c: u16| if (b'A' as u16..=b'Z' as u16).contains(&c) { c + 32 } else { c };
    a.0.cmp(&b.0).then_with(|| a.1.iter().map(|c| fold(*c)).cmp(b.1.iter().map(|c| fold(*c))))
}

fn bsd(b: &mut Vec<u8>, dir: bool) {
    be32(b, 99); // owner: unknown
    be32(b, 99);
    b.push(0);
    b.push(0);
    be16(b, if dir { 0o040555 } else { 0o100444 });
    be32(b, if dir { 0 } else { 1 }); // link count for files
}

fn dates(b: &mut Vec<u8>, t: u32) { for _ in 0..5 { be32(b, t); } }

/// B-tree node: descriptor, records, offsets at the end (last u16 = record 0).
fn node(size: usize, flink: u32, blink: u32, kind: i8, height: u8, recs: &[Vec<u8>]) -> Vec<u8> {
    let mut n = Vec::with_capacity(size);
    be32(&mut n, flink);
    be32(&mut n, blink);
    n.push(kind as u8);
    n.push(height);
    be16(&mut n, recs.len() as u16);
    be16(&mut n, 0);
    let mut offs = Vec::new();
    for r in recs {
        offs.push(n.len() as u16);
        n.extend_from_slice(r);
    }
    offs.push(n.len() as u16); // free space
    assert!(n.len() + 2 * offs.len() <= size, "node overflow");
    n.resize(size - 2 * offs.len(), 0);
    for o in offs.iter().rev() { be16(&mut n, *o); }
    n
}

#[allow(clippy::too_many_arguments)]
fn header_node(size: usize, depth: u16, root: u32, leaf_recs: u32, first: u32, last: u32, max_key: u16,
               total: u32, compare: u8, attrs: u32) -> Vec<u8> {
    let mut h = Vec::new();
    be16(&mut h, depth);
    be32(&mut h, root);
    be32(&mut h, leaf_recs);
    be32(&mut h, first);
    be32(&mut h, last);
    be16(&mut h, size as u16);
    be16(&mut h, max_key);
    be32(&mut h, total);
    be32(&mut h, 0); // free nodes
    be16(&mut h, 0);
    be32(&mut h, size as u32); // clump size
    h.push(0); // btree type
    h.push(compare);
    be32(&mut h, attrs);
    h.extend_from_slice(&[0; 64]);
    let user = vec![0u8; 128];
    let map_len = size - 14 - h.len() - user.len() - 8;
    let mut map = vec![0u8; map_len];
    assert!(total as usize <= map_len * 8, "B-tree needs map nodes");
    for i in 0..total as usize { map[i / 8] |= 0x80 >> (i % 8); }
    node(size, 0, 0, 1, 0, &[h, user, map])
}

/// Packs (key, record) pairs into B-tree levels; returns nodes 1.. (node 0 = header).
fn build_tree(entries: Vec<(Vec<u8>, Vec<u8>)>) -> (Vec<Vec<u8>>, u16, u32, u32, u32) {
    // leaves
    let mut levels: Vec<Vec<(Vec<u8>, Vec<Vec<u8>>)>> = Vec::new(); // per level: (first key, records)
    let mut leaves: Vec<(Vec<u8>, Vec<Vec<u8>>)> = Vec::new();
    let mut used = 14 + 2;
    for (k, r) in entries {
        let mut rec = k.clone();
        rec.extend_from_slice(&r);
        if rec.len() % 2 == 1 { rec.push(0); }
        if leaves.is_empty() || used + rec.len() + 2 > CAT_NODE {
            leaves.push((k.clone(), Vec::new()));
            used = 14 + 2;
        }
        used += rec.len() + 2;
        leaves.last_mut().unwrap().1.push(rec);
    }
    levels.push(leaves);
    // index levels until one node
    while levels.last().unwrap().len() > 1 {
        let below = levels.last().unwrap();
        let mut up: Vec<(Vec<u8>, Vec<Vec<u8>>)> = Vec::new();
        let mut used = 14 + 2;
        let base = levels.iter().map(|l| l.len()).sum::<usize>() - below.len(); // index of `below` in node order
        for (i, (k, _)) in below.iter().enumerate() {
            let mut rec = k.clone();
            be32(&mut rec, 0); // child pointer, patched below
            let child = (base + i) as u32;
            let n = rec.len();
            rec[n - 4..].copy_from_slice(&child.to_be_bytes());
            if up.is_empty() || used + rec.len() + 2 > CAT_NODE {
                up.push((k.clone(), Vec::new()));
                used = 14 + 2;
            }
            used += rec.len() + 2;
            up.last_mut().unwrap().1.push(rec);
        }
        levels.push(up);
    }
    // number nodes: leaves first (1..), then each index level; child pointers above
    // were computed in this same order relative to 0 and are shifted by 1 here.
    let depth = levels.len() as u16;
    let mut nodes = Vec::new();
    let mut start = 1u32;
    let mut starts = Vec::new();
    for l in &levels { starts.push(start); start += l.len() as u32; }
    let nleaf = levels[0].len() as u32;
    for (h, l) in levels.iter().enumerate() {
        let n = l.len() as u32;
        for (i, (_, recs)) in l.iter().enumerate() {
            let i = i as u32;
            let mut recs = recs.clone();
            if h > 0 {
                for r in recs.iter_mut() {
                    let m = r.len();
                    let child = u32::from_be_bytes(r[m - 4..].try_into().unwrap()) + 1;
                    r[m - 4..].copy_from_slice(&child.to_be_bytes());
                }
            }
            let (flink, blink) = if h == 0 {
                (if i + 1 < n { starts[h] + i + 1 } else { 0 }, if i > 0 { starts[h] + i - 1 } else { 0 })
            } else {
                (if i + 1 < n { starts[h] + i + 1 } else { 0 }, if i > 0 { starts[h] + i - 1 } else { 0 })
            };
            nodes.push(node(CAT_NODE, flink, blink, if h == 0 { -1 } else { 0 }, h as u8 + 1, &recs));
        }
    }
    let root = starts[levels.len() - 1];
    (nodes, depth, root, 1, nleaf)
}

impl Volume {
    pub fn build(volname: &str, dirs: &[Dir], input: &[File], now_hfs: u32) -> Result<Volume> {
        for (i, d) in dirs.iter().enumerate() {
            ensure!(d.name.is_ascii() && !d.name.is_empty(), "folder name must be ASCII");
            ensure!(d.parent.is_none_or(|p| p < i), "folder listed before its parent");
        }
        for f in input {
            ensure!(f.name.is_ascii() && !f.name.is_empty(), "file name must be ASCII");
            ensure!(f.dir.is_none_or(|d| d < dirs.len()), "file in unknown folder");
        }
        // CNIDs: root 2, folders from 16, then files
        let ndirs = dirs.len() as u32;
        let dir_id = |d: Option<usize>| d.map_or(2, |i| FIRST_CNID + i as u32);
        let mut next = FIRST_CNID + ndirs;
        let mut files = Vec::new();
        for f in input {
            files.push(FileSpan { cnid: next, start: 0, size: f.size });
            next += 1;
        }
        let nfiles = files.len() as u32;
        let mut valence = vec![0u32; dirs.len() + 1]; // [0] = root
        for d in dirs { valence[d.parent.map_or(0, |p| p + 1)] += 1; }
        for f in input { valence[f.dir.map_or(0, |d| d + 1)] += 1; }

        // catalog records
        let vol = uni(volname);
        let mut entries: Vec<((u32, Vec<u16>), Vec<u8>)> = Vec::new();
        let folder = |id: u32, valence: u32| {
            let mut r = Vec::new();
            be16(&mut r, 1);
            be16(&mut r, 0);
            be32(&mut r, valence);
            be32(&mut r, id);
            dates(&mut r, now_hfs);
            bsd(&mut r, true);
            r.extend_from_slice(&[0; 32]); // folder + extended finder info
            be32(&mut r, 0);
            be32(&mut r, 0);
            r
        };
        let thread = |kind: u16, parent: u32, name: &[u16]| {
            let mut r = Vec::new();
            be16(&mut r, kind);
            be16(&mut r, 0);
            be32(&mut r, parent);
            be16(&mut r, name.len() as u16);
            for c in name { be16(&mut r, *c); }
            r
        };
        entries.push(((1, vol.clone()), folder(2, valence[0])));
        entries.push(((2, vec![]), thread(3, 1, &vol)));
        for (i, d) in dirs.iter().enumerate() {
            let n = uni(&d.name);
            entries.push(((dir_id(d.parent), n.clone()), folder(dir_id(Some(i)), valence[i + 1])));
            entries.push(((dir_id(Some(i)), vec![]), thread(3, dir_id(d.parent), &n)));
        }
        // file records are completed after layout (fork extents); collect names now
        let file_names: Vec<Vec<u16>> = input.iter().map(|f| uni(&f.name)).collect();

        // layout: catalog size depends only on record sizes, so size it with a dry run
        let file_rec_len = 248;
        let mut probe = entries.clone();
        for ((f, n), src) in files.iter().zip(&file_names).zip(input) {
            probe.push(((dir_id(src.dir), n.clone()), vec![0; file_rec_len]));
            probe.push(((f.cnid, vec![]), thread(4, dir_id(src.dir), n)));
        }
        probe.sort_by(|a, b| key_order(&a.0, &b.0));
        ensure!(
            probe.windows(2).all(|w| key_order(&w[0].0, &w[1].0).is_lt()),
            "two names in one folder differ only in case"
        );
        let (probe_nodes, ..) = build_tree(probe.into_iter().map(|(k, r)| (cat_key(k.0, &k.1), r)).collect());
        let cat_nodes = probe_nodes.len() as u64 + 1;
        let cat_bytes = cat_nodes * CAT_NODE as u64;

        let data_blocks: u64 = files.iter().map(|f| blocks(f.size)).sum();
        let fixed = 1 + blocks(EXT_NODE as u64) + blocks(cat_bytes) + data_blocks + 1;
        let mut total = fixed;
        loop {
            let bm = blocks(total.div_ceil(8));
            if fixed + bm == total { break; }
            total = fixed + bm;
        }
        ensure!(total < u32::MAX as u64, "volume too large for 32-bit block numbers");
        let bm_blocks = blocks(total.div_ceil(8));
        let bm_start = 1u64;
        let ext_start = bm_start + bm_blocks;
        let cat_start = ext_start + blocks(EXT_NODE as u64);
        let mut cursor = cat_start + blocks(cat_bytes);
        for f in files.iter_mut() {
            f.start = cursor * BLOCK;
            cursor += blocks(f.size);
        }
        ensure!(cursor + 1 == total, "layout mismatch");

        for ((f, n), src) in files.iter().zip(&file_names).zip(input) {
            let mut r = Vec::new();
            be16(&mut r, 2);
            be16(&mut r, 0x0002); // thread exists
            be32(&mut r, 0);
            be32(&mut r, f.cnid);
            dates(&mut r, now_hfs);
            bsd(&mut r, false);
            r.extend_from_slice(&[0; 32]); // file + extended finder info
            be32(&mut r, 0);
            be32(&mut r, 0);
            fork(&mut r, f.size, f.start / BLOCK, blocks(f.size));
            fork(&mut r, 0, 0, 0);
            debug_assert_eq!(r.len(), file_rec_len);
            entries.push(((dir_id(src.dir), n.clone()), r));
            entries.push(((f.cnid, vec![]), thread(4, dir_id(src.dir), n)));
        }
        entries.sort_by(|a, b| key_order(&a.0, &b.0));
        let leaf_records = entries.len() as u32;
        let (nodes, depth, root, first, last) =
            build_tree(entries.into_iter().map(|(k, r)| (cat_key(k.0, &k.1), r)).collect());
        ensure!(nodes.len() as u64 + 1 == cat_nodes, "catalog size changed after layout");
        let mut catalog = header_node(CAT_NODE, depth, root, leaf_records, first, last, 516,
                                      cat_nodes as u32, 0xCF, 0x6);
        for n in nodes { catalog.extend_from_slice(&n); }
        let extents = header_node(EXT_NODE, 0, 0, 0, 0, 0, 10, 1, 0, 0x2);

        // volume header
        let mut vh = Vec::new();
        be16(&mut vh, 0x482B); // 'H+'
        be16(&mut vh, 4);
        be32(&mut vh, 0x0000_0100 | 0x0000_8000); // cleanly unmounted, software locked
        be32(&mut vh, 0x3130_2E30); // '10.0'
        be32(&mut vh, 0); // no journal
        for _ in 0..4 { be32(&mut vh, now_hfs); }
        be32(&mut vh, nfiles);
        be32(&mut vh, ndirs);
        be32(&mut vh, BLOCK as u32);
        be32(&mut vh, total as u32);
        be32(&mut vh, 0); // free blocks
        be32(&mut vh, 0);
        be32(&mut vh, BLOCK as u32);
        be32(&mut vh, BLOCK as u32);
        be32(&mut vh, next); // next CNID
        be32(&mut vh, 1);
        be64(&mut vh, 1); // encodings: MacRoman
        vh.extend_from_slice(&[0; 32]);
        fork(&mut vh, total.div_ceil(8), bm_start, bm_blocks);
        fork(&mut vh, EXT_NODE as u64, ext_start, blocks(EXT_NODE as u64));
        fork(&mut vh, cat_bytes, cat_start, blocks(cat_bytes));
        fork(&mut vh, 0, 0, 0); // attributes
        fork(&mut vh, 0, 0, 0); // startup
        ensure!(vh.len() == 512);

        let mut head = vec![0u8; BLOCK as usize];
        head[1024..1536].copy_from_slice(&vh);
        let mut tail = vec![0u8; BLOCK as usize];
        tail[BLOCK as usize - 1024..BLOCK as usize - 512].copy_from_slice(&vh);
        Ok(Volume {
            bytes: total * BLOCK,
            head,
            bitmap: (bm_start * BLOCK, total.div_ceil(8)),
            extents: (ext_start * BLOCK, extents),
            catalog: (cat_start * BLOCK, catalog),
            files,
            tail,
        })
    }

    /// Fills `out` with volume bytes at `offset`; file contents come from `data(file, offset, out)`.
    pub fn read(&self, offset: u64, out: &mut [u8], data: &dyn Fn(&FileSpan, u64, &mut [u8])) {
        out.fill(0);
        let end = offset + out.len() as u64;
        let mut copy = |start: u64, bytes: &[u8]| {
            let (s, e) = (start.max(offset), (start + bytes.len() as u64).min(end));
            if s < e {
                out[(s - offset) as usize..(e - offset) as usize]
                    .copy_from_slice(&bytes[(s - start) as usize..(e - start) as usize]);
            }
        };
        copy(0, &self.head);
        copy(self.extents.0, &self.extents.1);
        copy(self.catalog.0, &self.catalog.1);
        copy(self.bytes - BLOCK, &self.tail);
        let (bs, bl) = self.bitmap;
        let (s, e) = (bs.max(offset), (bs + bl).min(end));
        if s < e { out[(s - offset) as usize..(e - offset) as usize].fill(0xff); }
        // files: binary search by start
        let i = self.files.partition_point(|f| f.start + f.size <= offset);
        for f in &self.files[i..] {
            if f.start >= end { break; }
            let (s, e) = (f.start.max(offset), (f.start + f.size).min(end));
            if s < e { data(f, s - f.start, &mut out[(s - offset) as usize..(e - offset) as usize]); }
        }
    }
}
