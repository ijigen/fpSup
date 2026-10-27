//! Classic little-endian Sigma fp CFA DNG. Metadata remains at original offsets.
use crate::{Backend, Effort, cancelled, gpu::Gpu};
use anyhow::{Context, Result, bail, ensure};
use serde::Serialize;
#[cfg(target_endian = "big")]
use crate::digest::Sha256;
use std::{
    collections::{BTreeMap, HashSet},
    sync::atomic::AtomicBool,
};

const LAYOUT: [u16; 8] = [259, 273, 278, 279, 322, 323, 324, 325];
fn u16at(d: &[u8], o: usize) -> Result<u16> {
    Ok(u16::from_le_bytes(
        d.get(o..o + 2).context("Truncated TIFF")?.try_into()?,
    ))
}
fn u32at(d: &[u8], o: usize) -> Result<u32> {
    Ok(u32::from_le_bytes(
        d.get(o..o + 4).context("Truncated TIFF")?.try_into()?,
    ))
}
fn type_size(t: u16) -> Result<usize> {
    Ok(match t {
        1 | 2 | 6 | 7 => 1,
        3 | 8 => 2,
        4 | 9 | 11 | 13 => 4,
        5 | 10 | 12 => 8,
        _ => bail!("Unsupported TIFF type {t}"),
    })
}
#[derive(Clone)]
struct Entry {
    tag: u16,
    typ: u16,
    count: usize,
    value: usize,
    raw: [u8; 12],
}
impl Entry {
    fn values(&self, d: &[u8]) -> Result<Vec<usize>> {
        ensure!(
            matches!(self.typ, 1 | 3 | 4 | 13),
            "Unsupported numeric tag {}",
            self.tag
        );
        let size = type_size(self.typ)?;
        let inline = self.value.to_le_bytes();
        let bytes = if self.count * size <= 4 {
            &inline[..self.count * size]
        } else {
            d.get(self.value..self.value + self.count * size)
                .context("Truncated tag array")?
        };
        (0..self.count)
            .map(|i| {
                Ok(match self.typ {
                    1 => bytes[i] as usize,
                    3 => u16at(bytes, i * 2)? as usize,
                    _ => u32at(bytes, i * 4)? as usize,
                })
            })
            .collect()
    }
}
fn entries(d: &[u8], offset: usize) -> Result<BTreeMap<u16, Entry>> {
    let n = u16at(d, offset)? as usize;
    ensure!(n <= 4096, "Too many TIFF tags");
    let mut tags = BTreeMap::new();
    for i in 0..n {
        let at = offset + 2 + 12 * i;
        let tag = u16at(d, at)?;
        let e = Entry {
            tag,
            typ: u16at(d, at + 2)?,
            count: u32at(d, at + 4)? as usize,
            value: u32at(d, at + 8)? as usize,
            raw: d
                .get(at..at + 12)
                .context("Truncated TIFF entry")?
                .try_into()?,
        };
        ensure!(tags.insert(tag, e).is_none(), "Duplicate TIFF tag {tag}");
    }
    ensure!(
        u32at(d, offset + 2 + 12 * n)? == 0,
        "Multiple image IFDs are unsupported"
    );
    Ok(tags)
}
fn scalar(
    tags: &BTreeMap<u16, Entry>,
    d: &[u8],
    tag: u16,
    default: Option<usize>,
) -> Result<usize> {
    if let Some(e) = tags.get(&tag) {
        ensure!(e.count == 1, "Expected scalar tag {tag}");
        Ok(e.values(d)?[0])
    } else {
        default.context(format!("Missing TIFF tag {tag}"))
    }
}
fn prefix_check(d: &[u8], limit: usize, offset: usize, seen: &mut HashSet<usize>) -> Result<()> {
    ensure!(
        offset >= 8 && offset + 2 <= limit && seen.insert(offset),
        "Invalid or cyclic metadata IFD"
    );
    let tags = entries(d, offset)?;
    ensure!(
        offset + 6 + 12 * tags.len() <= limit,
        "Metadata IFD overlaps RAW data"
    );
    for e in tags.values() {
        let size = e
            .count
            .checked_mul(type_size(e.typ)?)
            .context("Tag size overflow")?;
        if size > 4 && !LAYOUT.contains(&e.tag) {
            ensure!(
                e.value >= 8 && e.value.checked_add(size).is_some_and(|end| end <= limit),
                "Metadata tag {} is outside the retained header",
                e.tag
            );
        }
        if [330, 34665, 34853, 40965].contains(&e.tag) {
            for pointer in e.values(d)? {
                if pointer != 0 {
                    prefix_check(d, limit, pointer, seen)?;
                }
            }
        }
    }
    if tags.contains_key(&513) || tags.contains_key(&514) {
        let at = scalar(&tags, d, 513, None)?;
        let size = scalar(&tags, d, 514, None)?;
        ensure!(
            at.checked_add(size).is_some_and(|e| e <= limit),
            "Thumbnail outside retained header"
        );
    }
    Ok(())
}

struct Image {
    width: usize,
    height: usize,
    bits: usize,
    pixels: Vec<u16>,
    prefix: usize,
    tags: BTreeMap<u16, Entry>,
}
fn fill_tile(image: &Image, x: usize, y: usize, tw: usize, th: usize, tile: &mut [u16]) {
    let vw = tw.min(image.width - x);
    let vh = th.min(image.height - y);
    for yy in 0..vh {
        tile[yy * tw..yy * tw + vw].copy_from_slice(
            &image.pixels[(y + yy) * image.width + x..(y + yy) * image.width + x + vw],
        );
        for xx in vw..tw {
            tile[yy * tw + xx] = tile[yy * tw + xx - 2];
        }
    }
    for yy in vh..th {
        for xx in 0..tw {
            tile[yy * tw + xx] = tile[yy.saturating_sub(2) * tw + xx];
        }
    }
}
fn adaptive_geometry(width: usize, height: usize) -> (usize, usize) {
    let grid = ((width as f64 * height as f64 / 131072.).sqrt().round() as usize).max(1);
    // TIFF tiles must use multiples of 16. A merely even tile height can
    // round-trip internally while LibRaw/Resolve interpret the JPEG rows differently.
    let dimension = |n: usize| n.div_ceil(grid).next_multiple_of(16).clamp(16, 65520);
    (dimension(width), dimension(height))
}
struct Audit {
    tw: usize,
    th: usize,
    offsets: Vec<u32>,
    sizes: Vec<u32>,
    // Keep the already verified encoder allocations until container auditing.
    // Comparing exact bytes avoids hashing every tile twice solely to prove a copy.
    payloads: Vec<Vec<u8>>,
}
fn audit_gpu_container(output: &[u8], source: &[u8], image: &Image, audit: &Audit) -> Result<()> {
    ensure!(
        output[..4] == source[..4] && output[8..image.prefix] == source[8..image.prefix],
        "RAW metadata prefix changed"
    );
    let tags = entries(output, u32at(output, 4)? as usize)?;
    ensure!(
        tags.len() == image.tags.keys().filter(|t| !LAYOUT.contains(t)).count() + 5,
        "Unexpected DNG tags"
    );
    for (&tag, entry) in &image.tags {
        if !LAYOUT.contains(&tag) {
            ensure!(
                tags.get(&tag).is_some_and(|e| e.raw == entry.raw),
                "RAW metadata changed: {tag}"
            );
        }
    }
    for (tag, value) in [(259, 7), (322, audit.tw), (323, audit.th)] {
        ensure!(
            scalar(&tags, output, tag, None)? == value,
            "DNG layout mismatch"
        );
    }
    for (tag, expected) in [(324, &audit.offsets), (325, &audit.sizes)] {
        let actual = tags
            .get(&tag)
            .context("Missing DNG tile table")?
            .values(output)?;
        ensure!(
            actual
                .iter()
                .copied()
                .eq(expected.iter().map(|&v| v as usize)),
            "DNG tile table mismatch"
        );
    }
    ensure!(
        audit.offsets.len() == image.width.div_ceil(audit.tw) * image.height.div_ceil(audit.th)
            && audit.sizes.len() == audit.offsets.len()
            && audit.payloads.len() == audit.offsets.len(),
        "DNG tile placement mismatch"
    );
    for (i, (&offset, &size)) in audit.offsets.iter().zip(&audit.sizes).enumerate() {
        let payload = output
            .get(offset as usize..offset as usize + size as usize)
            .context("DNG tile outside file")?;
        ensure!(
            payload == audit.payloads[i].as_slice(),
            "Verified GPU tile changed during DNG assembly"
        );
    }
    Ok(())
}
struct Prepared {
    tw: usize,
    th: usize,
    tiles: Option<crate::tile_buffer::TileBuffer>,
    rankings: Option<Vec<Vec<u8>>>,
    histograms: Option<Vec<u32>>,
    estimated_bits: u64,
}
fn prepare_geometry(
    image: &Image,
    geometry: (usize, usize),
    effort: Effort,
    gpu: Option<&Gpu>,
    cancel: &AtomicBool,
) -> Result<Prepared> {
    let (tw, th) = geometry;
    let mut prepared = Prepared {
        tw,
        th,
        tiles: None,
        rankings: None,
        histograms: None,
        estimated_bits: 0,
    };
    if let Some(gpu) = gpu.filter(|g| effort != Effort::Fast || g.entropy_enabled()) {
        let nx = image.width.div_ceil(tw);
        let shared = gpu.entropy_enabled() && cfg!(target_os = "macos")
            && std::env::var_os("CDNG_METAL_SHARED_INPUT").is_none_or(|v| v != "0");
        let mut tiles = crate::tile_buffer::TileBuffer::new(nx * image.height.div_ceil(th) * tw * th, shared)?;
        for (i, tile) in tiles.chunks_exact_mut(tw * th).enumerate() {
            cancelled(cancel)?;
            fill_tile(image, (i % nx) * tw, (i / nx) * th, tw, th, tile);
        }
        let predictors: &[u8] = match effort {
            Effort::Fast => &[7],
            Effort::Balanced => &[1, 5, 7],
            Effort::Max => &[1, 2, 3, 4, 5, 6, 7],
        };
        let (rankings, estimate, histograms) = gpu.analyze_tiles(
            &tiles,
            tw * th,
            (tw * 2) as u32,
            image.bits as u32,
            predictors,
        )?;
        prepared.tiles = Some(tiles);
        prepared.rankings = Some(rankings);
        prepared.histograms = Some(histograms);
        prepared.estimated_bits = estimate;
    }
    Ok(prepared)
}

fn prepare_search(image: &Image, effort: Effort, gpu: Option<&Gpu>, cancel: &AtomicBool,
    mut host_work: Option<&mut dyn FnMut() -> Result<()>>) -> Result<Vec<Prepared>> {
    let adaptive = adaptive_geometry(image.width, image.height);
    let mut geometries = vec![adaptive];
    if effort == Effort::Max {
        geometries.extend([(256, 256), (512, 256), (1024, 512)].into_iter().filter(|&g| g != adaptive));
    }
    let mut candidates = None;
    #[cfg(target_os = "macos")]
    if effort == Effort::Max && image.height.is_multiple_of(2) && image.height >= 2
        && std::env::var_os("CDNG_METAL_BATCH_SEARCH").is_none_or(|v| v != "0")
        && let Some(gpu) = gpu.filter(|g| g.backend == Backend::Metal)
    {
        let predictors = [1, 2, 3, 4, 5, 6, 7];
        cancelled(cancel)?;
        let histograms = gpu.histogram_geometries_with_work(&image.pixels, image.width, image.height,
            image.bits as u32, &predictors, &geometries, host_work.take())?;
        let mut results = Vec::with_capacity(geometries.len());
        for (&(tw, th), histograms) in geometries.iter().zip(histograms) {
            cancelled(cancel)?;
            let (rankings, estimated_bits) = Gpu::analyze_histograms(&histograms, &predictors)?;
            results.push(Prepared { tw, th, tiles: None, rankings: Some(rankings),
                histograms: Some(histograms), estimated_bits });
        }
        candidates = Some(results);
    }
    let mut candidates = match candidates {
        Some(candidates) => candidates,
        None => {
            // Preserve the original streaming selection and memory bound for
            // CPU, CUDA and source dimensions that use the individual search.
            let mut geometries = geometries.into_iter();
            let first = prepare_geometry(image, geometries.next().unwrap(), effort, gpu, cancel)?;
            let mut prepared = vec![first];
            let mut alternative: Option<Prepared> = None;
            for geometry in geometries {
                let candidate = prepare_geometry(image, geometry, effort, gpu, cancel)?;
                if gpu.is_none() {
                    prepared.push(candidate);
                } else if candidate.estimated_bits < prepared[0].estimated_bits
                    && alternative.as_ref().is_none_or(|best| candidate.estimated_bits < best.estimated_bits)
                { alternative = Some(candidate); }
            }
            if let Some(alternative) = alternative { prepared.push(alternative); }
            // CPU/CUDA, odd-height and disabled batching retain the same full
            // hashes, computed after preparation when no GPU overlap exists.
            if let Some(work) = host_work.take() { work()?; }
            return Ok(prepared);
        },
    };
    let first = candidates.remove(0);
    let mut prepared = vec![first];
    if gpu.is_none() {
        prepared.extend(candidates);
    } else {
        // Exactly the original strict comparison and geometry order: retain
        // adaptive as the size floor and fully encode the best promising alternative.
        let mut alternative: Option<Prepared> = None;
        for candidate in candidates {
            if candidate.estimated_bits < prepared[0].estimated_bits
                && alternative.as_ref().is_none_or(|best| candidate.estimated_bits < best.estimated_bits)
            { alternative = Some(candidate); }
        }
        if let Some(alternative) = alternative { prepared.push(alternative); }
        for geometry in &mut prepared {
            if geometry.tiles.is_none() && geometry.histograms.is_some() {
                let (tw, th) = (geometry.tw, geometry.th);
                let nx = image.width.div_ceil(tw);
                let shared = gpu.unwrap().entropy_enabled()
                    && std::env::var_os("CDNG_METAL_SHARED_INPUT").is_none_or(|v| v != "0");
                let mut tiles = crate::tile_buffer::TileBuffer::new(nx * image.height.div_ceil(th) * tw * th, shared)?;
                for (i, tile) in tiles.chunks_exact_mut(tw * th).enumerate() {
                    cancelled(cancel)?;
                    fill_tile(image, (i % nx) * tw, (i / nx) * th, tw, th, tile);
                }
                geometry.tiles = Some(tiles);
            }
        }
    }
    Ok(prepared)
}
fn unpack_bits<const BITS: usize>(row: &[u8], pixels: &mut [u16]) {
    let mask = (1u32 << BITS) - 1;
    for (x, pixel) in pixels.iter_mut().enumerate() {
        let bit = x * BITS;
        let at = bit / 8;
        let word = ((row[at] as u32) << 16)
            | ((row.get(at + 1).copied().unwrap_or(0) as u32) << 8)
            | row.get(at + 2).copied().unwrap_or(0) as u32;
        *pixel = ((word >> (24 - BITS - bit % 8)) & mask) as u16;
    }
}
fn unpack_row(row: &[u8], pixels: &mut [u16], bits: usize) {
    match bits {
        8 => {
            for (pixel, &byte) in pixels.iter_mut().zip(row) {
                *pixel = byte as u16;
            }
        }
        12 => {
            for (pair, bytes) in pixels.chunks_exact_mut(2).zip(row.chunks_exact(3)) {
                pair[0] = ((bytes[0] as u16) << 4) | ((bytes[1] as u16) >> 4);
                pair[1] = (((bytes[1] & 15) as u16) << 8) | bytes[2] as u16;
            }
        }
        16 => {
            for (pixel, bytes) in pixels.iter_mut().zip(row.chunks_exact(2)) {
                *pixel = u16::from_le_bytes([bytes[0], bytes[1]]);
            }
        }
        10 => unpack_bits::<10>(row, pixels),
        14 => unpack_bits::<14>(row, pixels),
        _ => unreachable!(),
    }
}
pub(crate) fn pixel_hash(pixels: &[u16]) -> String {
    #[cfg(target_endian = "little")]
    {
        // Integer samples have no padding; borrow the little-endian bytes rather
        // than copying every sample into an intermediate conversion buffer.
        let bytes = unsafe {
            std::slice::from_raw_parts(pixels.as_ptr().cast::<u8>(), std::mem::size_of_val(pixels))
        };
        crate::hash(bytes)
    }
    #[cfg(target_endian = "big")]
    {
    let mut hash = Sha256::new();
    let mut bytes = [0u8; 16384];
    for chunk in pixels.chunks(bytes.len() / 2) {
        for (&sample, dst) in chunk.iter().zip(bytes.chunks_exact_mut(2)) {
            dst.copy_from_slice(&sample.to_le_bytes());
        }
        hash.update(&bytes[..chunk.len() * 2]);
    }
    format!("{:x}", hash.finalize())
    }
}
fn read(d: &[u8], check_prefix: bool) -> Result<Image> {
    ensure!(
        d.starts_with(b"II*\0"),
        "Only little-endian classic Sigma fp DNG is supported"
    );
    let tags = entries(d, u32at(d, 4)? as usize)?;
    ensure!(
        scalar(&tags, d, 262, None)? == 32803 && scalar(&tags, d, 277, Some(1))? == 1,
        "Expected one-channel Bayer CFA DNG"
    );
    ensure!(!tags.contains_key(&330), "SubIFD images are unsupported");
    ensure!(
        scalar(&tags, d, 339, Some(1))? == 1,
        "Only unsigned integer RAW samples are supported"
    );
    for t in [266, 317, 50974, 50975, 52547] {
        if let Some(e) = tags.get(&t) {
            ensure!(
                e.values(d)?.iter().all(|&v| v == 1),
                "Non-default pixel interleaving or TIFF predictor is unsupported"
            );
        }
    }
    let width = scalar(&tags, d, 256, None)?;
    let height = scalar(&tags, d, 257, None)?;
    let bits = scalar(&tags, d, 258, None)?;
    ensure!(
        width > 0
            && height > 0
            && width % 2 == 0
            && width <= 65535
            && height <= 65535
            && width * height <= 100_000_000,
        "Invalid RAW dimensions"
    );
    ensure!(
        [8, 10, 12, 14, 16].contains(&bits),
        "Unsupported RAW bit depth {bits}"
    );
    let compression = scalar(&tags, d, 259, None)?;
    let tiled = tags.contains_key(&324);
    let offsets = tags
        .get(&(if tiled { 324 } else { 273 }))
        .context("Missing RAW offsets")?
        .values(d)?;
    let sizes = tags
        .get(&(if tiled { 325 } else { 279 }))
        .context("Missing RAW byte counts")?
        .values(d)?;
    ensure!(
        !offsets.is_empty() && offsets.len() == sizes.len(),
        "Invalid RAW segment arrays"
    );
    let prefix = *offsets.iter().min().unwrap();
    if check_prefix {
        prefix_check(d, prefix, u32at(d, 4)? as usize, &mut HashSet::new())?;
    }
    let mut pixels = vec![0u16; width * height];
    if compression == 1 {
        ensure!(
            !tiled && offsets.len() == 1,
            "Uncompressed input requires one strip"
        );
        let rowbytes = (width * bits).div_ceil(8);
        let required = rowbytes * height;
        ensure!(sizes[0] >= required, "Truncated packed RAW");
        let raw = d
            .get(prefix..prefix + required)
            .context("Truncated packed RAW")?;
        for (row, output) in raw
            .chunks_exact(rowbytes)
            .zip(pixels.chunks_exact_mut(width))
        {
            unpack_row(row, output, bits);
        }
    } else if compression == 7 {
        let tw = if tiled {
            scalar(&tags, d, 322, None)?
        } else {
            width
        };
        let th = if tiled {
            scalar(&tags, d, 323, None)?
        } else {
            scalar(&tags, d, 278, Some(height))?
        };
        ensure!(
            tw > 0 && th > 0 && tw <= 65535 && th <= 65535,
            "Invalid tile dimensions"
        );
        ensure!(
            offsets.len() == width.div_ceil(tw) * height.div_ceil(th),
            "RAW tile count mismatch"
        );
        let mut decoded = Vec::new();
        for (i, (&at, &size)) in offsets.iter().zip(&sizes).enumerate() {
            let blob = d.get(at..at + size).context("Truncated JPEG tile")?;
            let decoder =
                ljpeg::Decoder::new(blob).map_err(|e| anyhow::anyhow!("Lossless JPEG: {e:?}"))?;
            ensure!(
                decoder.width() * decoder.height() * decoder.components() == tw * th
                    && decoder.bitdepth() == bits,
                "JPEG dimensions or precision mismatch"
            );
            if offsets.len() == 1 && tw == width && th == height {
                // A complete contiguous segment can be decoded directly into
                // the final RAW allocation, including C2's flattened layout.
                decoder.decode_to_buffer(&mut pixels, decoder.width(), decoder.height())
                    .map_err(|e| anyhow::anyhow!("Lossless JPEG: {e:?}"))?;
                continue;
            }
            // Reuse one initialized tile allocation throughout this frame.
            // Full decoding overwrites every sample before any crop is copied.
            decoded.resize(tw * th, 0);
            if decoder.super_h() != 1 || decoder.super_v() != 1 || decoder.predictor() == 8 {
                // Preserve the old zero-initialized allocation semantics for
                // special scan layouts; ordinary CFA tiles overwrite all samples.
                decoded.fill(0);
            }
            decoder.decode_to_buffer(&mut decoded, decoder.width(), decoder.height())
                .map_err(|e| anyhow::anyhow!("Lossless JPEG: {e:?}"))?;
            let x = (i % width.div_ceil(tw)) * tw;
            let y = (i / width.div_ceil(tw)) * th;
            for yy in 0..th.min(height - y) {
                let n = tw.min(width - x);
                pixels[(y + yy) * width + x..(y + yy) * width + x + n]
                    .copy_from_slice(&decoded[yy * tw..yy * tw + n]);
            }
        }
    } else {
        bail!("Input compression {compression} is unsupported; lossless mode refuses lossy RAW");
    }
    Ok(Image {
        width,
        height,
        bits,
        pixels,
        prefix,
        tags,
    })
}

#[derive(Serialize, Clone)]
pub struct Info {
    pub codec: String,
    pub width: usize,
    pub height: usize,
    pub bits: usize,
    pub pixel_sha256: String,
    pub pixel_verified: bool,
    pub verification: String,
    pub backend: Backend,
}
pub fn decode(d: &[u8]) -> Result<Vec<u16>> {
    Ok(read(d, false)?.pixels)
}

/// Keep temporal groups within one Bayer layout and sensor orientation.
pub(crate) fn archive_layout_key(d: &[u8]) -> Result<Vec<usize>> {
    ensure!(d.get(..4) == Some(b"II*\0"), "Unsupported DNG byte order");
    let tags = entries(d, u32at(d, 4)? as usize)?;
    let mut key = Vec::new();
    // Distinguish Bayer geometry, plane identity and orientation. Exposure and
    // per-frame metadata remain in each frame's own unchanged metadata prefix.
    for tag in [262, 274, 277, 33421, 33422, 50710, 50711] {
        key.push(tag as usize);
        if let Some(entry) = tags.get(&tag) {
            let values = entry.values(d)?;
            key.push(values.len());
            key.extend(values);
        } else { key.push(0); }
    }
    Ok(key)
}

/// Header for the virtual, ordinary uncompressed DNG. No complete output file.
pub(crate) fn archive_input(d: &[u8]) -> Result<(Vec<u8>, Vec<u16>, Info)> {
    let image = read(d, true)?;
    let info = Info {
        codec: "jpeg-xl-lossless".into(),
        width: image.width,
        height: image.height,
        bits: image.bits,
        pixel_sha256: pixel_hash(&image.pixels),
        pixel_verified: true,
        verification: "cpu-full-jxl-decode".into(),
        backend: Backend::Cpu,
    };
    let mut tags: BTreeMap<u16, [u8; 12]> = image
        .tags
        .iter()
        .filter(|(t, _)| !LAYOUT.contains(t))
        .map(|(&t, e)| (t, e.raw))
        .collect();
    let entry = |tag: u16, typ: u16, value: u32| {
        let mut b = [0; 12];
        b[..2].copy_from_slice(&tag.to_le_bytes());
        b[2..4].copy_from_slice(&typ.to_le_bytes());
        b[4..8].copy_from_slice(&1u32.to_le_bytes());
        b[8..].copy_from_slice(&value.to_le_bytes());
        b
    };
    for (tag, typ, value) in [
        (258, 3, 16),
        (259, 3, 1),
        (273, 4, 0),
        (278, 4, image.height as u32),
        (279, 4, (image.width * image.height * 2) as u32),
    ] {
        tags.insert(tag, entry(tag, typ, value));
    }
    let mut header = d[..image.prefix].to_vec();
    if header.len() % 2 != 0 {
        header.push(0);
    }
    let ifd = header.len() as u32;
    let offset = ifd + 6 + tags.len() as u32 * 12;
    tags.insert(273, entry(273, 4, offset));
    header[4..8].copy_from_slice(&ifd.to_le_bytes());
    header.extend((tags.len() as u16).to_le_bytes());
    for e in tags.values() {
        header.extend(e);
    }
    header.extend([0; 4]);
    Ok((header, image.pixels, info))
}

/// libjxl settings per effort for archive DNGs (measured 2026-10-24 on fp 4K night footage,
/// see projects/jxl-metal/README.md). `--buffering=0` gives one frame-wide tree and table
/// set, which is both smaller and what the GPU decoder reads fastest.
pub fn jxl_settings(effort: Effort, bits: usize) -> crate::jxl::Settings {
    let (effort, tier) = match effort {
        Effort::Fast => (3, 0),
        Effort::Balanced => (5, 0),
        Effort::Max => (7, 1),
    };
    crate::jxl::Settings { bits: bits as u32, effort, tier, buffering: 0, group: 0 }
}

/// A RAW frame read for JPEG XL: the Bayer mosaic as four same-colour subimages
/// (RowInterleaveFactor = ColumnInterleaveFactor = 2, DNG spec p.97), which compresses
/// far better than the interleaved mosaic.
pub struct JxlFrame {
    image: Image,
    /// the source file up to its RAW data: every metadata offset stays valid
    head: Vec<u8>,
    /// SHA-256 of the RAW samples in mosaic order (worked out on the reading thread)
    pixel_sha256: String,
    pub width: usize,
    pub height: usize,
    pub bits: usize,
    pub planes: Vec<u16>,
}

impl JxlFrame {
    /// Queue accounting includes every retained byte buffer, including a large
    /// metadata prefix. The tag-map allowance is conservative because BTreeMap
    /// does not expose its allocated node capacity.
    pub(crate) fn retained_bytes(&self) -> usize {
        self.planes.capacity().saturating_mul(std::mem::size_of::<u16>())
            .saturating_add(self.image.pixels.capacity().saturating_mul(std::mem::size_of::<u16>()))
            .saturating_add(self.head.capacity())
            .saturating_add(self.pixel_sha256.capacity())
            .saturating_add(self.image.tags.len().saturating_mul(std::mem::size_of::<Entry>() + 64))
            .saturating_add(1024)
            .saturating_add(std::mem::size_of::<Self>())
    }
}

pub fn jxl_frame(d: &[u8]) -> Result<JxlFrame> {
    let mut image = read(d, true)?;
    let (w, h) = (image.width, image.height);
    ensure!(h % 2 == 0, "JPEG XL DNG needs an even RAW height");
    // Hash the original mosaic before reusing its allocation for the Bayer
    // permutation. Container assembly needs the image metadata, not a second
    // retained full-resolution copy of the RAW samples.
    let pixel_sha256 = pixel_hash(&image.pixels);
    let mut planes = std::mem::take(&mut image.pixels);
    crate::jxl::cfa_permute(&mut planes, w, h, false)?;
    let head = d[..image.prefix].to_vec();
    Ok(JxlFrame { width: w, height: h, bits: image.bits, planes, head, pixel_sha256, image })
}

/// The JPEG XL DNG (DNG 1.7.1): the source metadata at its original offsets and `payload`
/// (a JXL codestream of `f.planes`, already decoded again and compared by the caller) as
/// one strip. `effort` goes into the optional JXLEffort tag.
pub fn jxl_dng(f: &JxlFrame, payload: &[u8], effort: Option<u32>, verification: &str, backend: Backend) -> (Vec<u8>, Info) {
    let image = &f.image;
    let (w, h) = (f.width, f.height);
    const VERSION: u32 = u32::from_le_bytes([1, 7, 1, 0]); // DNG 1.7.1.0, BYTE[4] inline
    let entry = |tag: u16, typ: u16, count: u32, value: u32| {
        let mut b = [0; 12];
        b[..2].copy_from_slice(&tag.to_le_bytes());
        b[2..4].copy_from_slice(&typ.to_le_bytes());
        b[4..8].copy_from_slice(&count.to_le_bytes());
        b[8..].copy_from_slice(&value.to_le_bytes());
        b
    };
    let mut tags: BTreeMap<u16, [u8; 12]> = image
        .tags
        .iter()
        .filter(|(t, _)| !LAYOUT.contains(t))
        .map(|(&t, e)| (t, e.raw))
        .collect();
    for (tag, typ, count, value) in [
        (259, 3, 1, 52546), // JPEG XL
        (273, 4, 1, 0),     // strip offset, set below
        (278, 4, 1, h as u32),
        (279, 4, 1, payload.len() as u32),
        (50706, 1, 4, VERSION),
        (50707, 1, 4, VERSION),
        (50975, 3, 1, 2), // RowInterleaveFactor
        (52547, 3, 1, 2), // ColumnInterleaveFactor
        (52553, 11, 1, 0f32.to_bits()), // JXLDistance: lossless
    ] {
        tags.insert(tag, entry(tag, typ, count, value));
    }
    if let Some(e) = effort {
        tags.insert(52554, entry(52554, 4, 1, e)); // JXLEffort
    }
    let mut out = f.head.clone();
    if out.len() % 2 != 0 {
        out.push(0);
    }
    let ifd = out.len() as u32;
    let offset = ifd + 6 + tags.len() as u32 * 12;
    tags.insert(273, entry(273, 4, 1, offset));
    out[4..8].copy_from_slice(&ifd.to_le_bytes());
    out.extend((tags.len() as u16).to_le_bytes());
    for e in tags.values() {
        out.extend(e);
    }
    out.extend([0; 4]);
    out.extend(payload);
    let info = Info {
        codec: "jpeg-xl-dng".into(),
        width: w,
        height: h,
        bits: image.bits,
        pixel_sha256: f.pixel_sha256.clone(),
        pixel_verified: true,
        verification: verification.into(),
        backend,
    };
    (out, info)
}

/// Lossless JPEG XL DNG with libjxl on the CPU; the stream is decoded again and compared.
pub fn compress_jxl(d: &[u8], effort: Effort, codec: &crate::jxl::Codec, cancel: &AtomicBool) -> Result<(Vec<u8>, Info)> {
    let f = jxl_frame(d)?;
    cancelled(cancel)?;
    let settings = jxl_settings(effort, f.bits);
    let payload = codec.encode_with(&f.planes, f.width, f.height, &settings)?;
    cancelled(cancel)?;
    ensure!(
        codec.decode_bits(&payload, f.width, f.height, settings.bits)? == f.planes,
        "JPEG XL changed RAW samples"
    );
    Ok(jxl_dng(&f, &payload, Some(settings.effort as u32), "cpu-full-jxl-decode", Backend::Cpu))
}

pub struct Preview {
    pub width: usize,
    pub height: usize,
    pub rgb: Vec<u8>,
    pub source_width: usize,
    pub source_height: usize,
    pub bits: usize,
    pub fps: f64,
}
fn numbers(entry: &Entry, d: &[u8]) -> Result<Vec<f64>> {
    if matches!(entry.typ, 1 | 3 | 4) {
        return Ok(entry.values(d)?.into_iter().map(|v| v as f64).collect());
    }
    ensure!(
        entry.count <= 16 && matches!(entry.typ, 5 | 10),
        "Unsupported preview metadata"
    );
    (0..entry.count)
        .map(|i| {
            let at = entry.value + i * 8;
            let a = u32at(d, at)?;
            let b = u32at(d, at + 4)?;
            ensure!(b != 0, "Invalid rational metadata");
            Ok(if entry.typ == 10 {
                a as i32 as f64 / b as i32 as f64
            } else {
                a as f64 / b as f64
            })
        })
        .collect()
}
/// Fast Bayer identification preview with white balance and automatic brightness.
pub fn preview(d: &[u8]) -> Result<Preview> {
    let image = read(d, false)?;
    ensure!(
        image.width >= 2 && image.height >= 2,
        "Preview needs a full 2x2 Bayer block"
    );
    let pattern = image
        .tags
        .get(&33422)
        .context("Missing Bayer pattern")?
        .values(d)?;
    ensure!(
        pattern.len() == 4 && pattern.iter().all(|&v| v <= 2),
        "Preview supports 2x2 RGB Bayer patterns"
    );
    let black = image
        .tags
        .get(&50714)
        .and_then(|e| numbers(e, d).ok())
        .and_then(|v| v.first().copied())
        .unwrap_or(0.);
    let white = scalar(&image.tags, d, 50717, Some((1 << image.bits) - 1))? as f64;
    let neutral = image
        .tags
        .get(&50728)
        .and_then(|e| numbers(e, d).ok())
        .filter(|v| v.len() == 3)
        .unwrap_or(vec![1.; 3]);
    let fps = image
        .tags
        .get(&51044)
        .and_then(|e| numbers(e, d).ok())
        .and_then(|v| v.first().copied())
        .filter(|v| *v > 0. && *v < 1000.)
        .unwrap_or(24.);
    let step = (image.width / 2).div_ceil(640).max(1);
    let width = (image.width / 2).div_ceil(step);
    let height = (image.height / 2).div_ceil(step);
    let mut linear = Vec::with_capacity(width * height);
    let mut levels = Vec::with_capacity(width * height);
    for y in 0..height {
        for x in 0..width {
            let sx = (x * step * 2).min(image.width - 2);
            let sy = (y * step * 2).min(image.height - 2);
            let mut rgb = [0f64; 3];
            let mut counts = [0f64; 3];
            for by in 0..2 {
                for bx in 0..2 {
                    let color = pattern[by * 2 + bx];
                    let sample = image.pixels[(sy + by) * image.width + sx + bx] as f64;
                    let value = ((sample - black) / (white - black).max(1.)).max(0.);
                    rgb[color] += value / neutral[color].max(0.001);
                    counts[color] += 1.;
                }
            }
            for c in 0..3 {
                rgb[c] /= counts[c].max(1.);
            }
            levels.push((rgb[0] + 2. * rgb[1] + rgb[2]) / 4.);
            linear.push(rgb);
        }
    }
    let percentile = (levels.len() * 99 / 100).min(levels.len() - 1);
    let p99 = *levels.select_nth_unstable_by(percentile, f64::total_cmp).1;
    let gain = (0.8 / p99.max(0.001)).clamp(0.25, 32.);
    let rgb: Vec<u8> = linear
        .into_iter()
        .flat_map(|p| p.map(|v| ((v * gain).clamp(0., 1.).powf(1. / 2.2) * 255.).round() as u8))
        .collect();
    let orientation = scalar(&image.tags, d, 274, Some(1))?;
    let (width, height, rgb) = if matches!(orientation, 3 | 6 | 8) {
        let (nw, nh) = if orientation == 3 {
            (width, height)
        } else {
            (height, width)
        };
        let mut rotated = vec![0; rgb.len()];
        for y in 0..height {
            for x in 0..width {
                let (nx, ny) = match orientation {
                    3 => (width - 1 - x, height - 1 - y),
                    6 => (height - 1 - y, x),
                    _ => (y, width - 1 - x),
                };
                rotated[(ny * nw + nx) * 3..(ny * nw + nx) * 3 + 3]
                    .copy_from_slice(&rgb[(y * width + x) * 3..(y * width + x) * 3 + 3]);
            }
        }
        (nw, nh, rotated)
    } else {
        (width, height, rgb)
    };
    Ok(Preview {
        width,
        height,
        rgb,
        source_width: image.width,
        source_height: image.height,
        bits: image.bits,
        fps,
    })
}
pub fn compress(
    d: &[u8],
    effort: Effort,
    backend: Backend,
    gpu: Option<&Gpu>,
    cancel: &AtomicBool,
) -> Result<(Vec<u8>, Info)> {
    let (output, info, _) = compress_impl(d, effort, backend, gpu, cancel, false)?;
    Ok((output, info))
}

pub(crate) fn compress_with_source_hash(
    d: &[u8], effort: Effort, backend: Backend, gpu: Option<&Gpu>, cancel: &AtomicBool,
) -> Result<(Vec<u8>, Info, String)> {
    let (output, info, digest) = compress_impl(d, effort, backend, gpu, cancel, true)?;
    Ok((output, info, digest.context("Source hash was not computed")?))
}

fn compress_impl(
    d: &[u8], effort: Effort, backend: Backend, gpu: Option<&Gpu>, cancel: &AtomicBool,
    include_source_hash: bool,
) -> Result<(Vec<u8>, Info, Option<String>)> {
    let profile = std::env::var_os("CDNG_PROFILE_STAGES").is_some();
    let started = std::time::Instant::now();
    let image = read(d, true)?;
    let read_at = started.elapsed();
    let mut pixel_sha256 = None;
    let mut source_sha256 = None;
    let mut hashes = || {
        cancelled(cancel)?;
        pixel_sha256 = Some(pixel_hash(&image.pixels));
        cancelled(cancel)?;
        if include_source_hash { source_sha256 = Some(crate::hash(d)); }
        cancelled(cancel)
    };
    let prepared = prepare_search(&image, effort, gpu, cancel, Some(&mut hashes))?;
    let mut info = Info {
        codec: "lossless-jpeg".into(),
        width: image.width,
        height: image.height,
        bits: image.bits,
        pixel_sha256: pixel_sha256.context("RAW pixel hash was not computed")?,
        pixel_verified: true,
        verification: if gpu.is_some_and(|g| g.entropy_enabled()) {
            "metal-entropy-roundtrip"
        } else {
            "cpu-full-decode"
        }
        .into(),
        backend,
    };
    // Allocate the original fallback only if no smaller candidate is produced.
    let mut best = Vec::new();
    let mut best_audit = None;
    let prepared_at = started.elapsed();
    for geometry in prepared {
        let (tw, th) = (geometry.tw, geometry.th);
        let (jw, jh) = (tw, th / 2);
        let candidates: &[u8] = match effort {
            Effort::Fast => &[7],
            Effort::Balanced => &[1, 5, 7],
            Effort::Max => &[1, 2, 3, 4, 5, 6, 7],
        };
        let nx = image.width.div_ceil(tw);
        let gpu_tiles = geometry.tiles;
        let rankings = geometry.rankings;
        let mut encoded_tiles: Option<Vec<Vec<u8>>> = None;
        if let Some(gpu) = gpu.filter(|g| g.entropy_enabled()) {
            let tiles = gpu_tiles.as_ref().unwrap();
            let histograms = geometry.histograms.as_ref().unwrap();
            for attempt in 0..if effort == Effort::Max { 2 } else { 1 } {
                cancelled(cancel)?;
                let predictors: Vec<u8> = rankings
                    .as_ref()
                    .unwrap()
                    .iter()
                    .map(|r| r[attempt])
                    .collect();
                let maximum_sizes: Option<Vec<usize>> = encoded_tiles.as_ref()
                    .filter(|_| std::env::var_os("CDNG_METAL_EXACT_PRUNE").is_none_or(|v| v != "0"))
                    .map(|tiles| tiles.iter().map(Vec::len).collect());
                let encoded = gpu.encode_shared_tiles_bounded(
                    tiles,
                    tw * th,
                    (tw * 2) as u32,
                    image.bits as u32,
                    &predictors,
                    histograms,
                    maximum_sizes.as_deref(),
                )?;
                if let Some(best) = &mut encoded_tiles {
                    for (old, new) in best.iter_mut().zip(encoded) {
                        if !new.is_empty() && new.len() < old.len() {
                            *old = new;
                        }
                    }
                } else {
                    encoded_tiles = Some(encoded);
                }
            }
        }
        let mut scratch = vec![0; if gpu_tiles.is_some() { 0 } else { tw * th }];
        let tile_count = nx * image.height.div_ceil(th);
        let capacity = if let Some(encoded) = &encoded_tiles {
            let payload = encoded.iter().try_fold(0usize, |total, tile| total.checked_add(tile.len()))
                .context("DNG allocation overflow")?;
            let tags = image.tags.keys().filter(|t| !LAYOUT.contains(t)).count() + 5;
            image.prefix.checked_add(payload)
                .and_then(|n| n.checked_add(1 + 6 + tags * 12))
                .and_then(|n| n.checked_add(if tile_count > 1 { tile_count * 8 } else { 0 }))
                .context("DNG allocation overflow")?
        } else { image.prefix };
        let mut out = Vec::with_capacity(capacity);
        out.extend_from_slice(&d[..image.prefix]);
        let mut offsets = Vec::with_capacity(tile_count);
        let mut sizes = Vec::with_capacity(tile_count);
        let mut verified_payloads = Vec::with_capacity(if encoded_tiles.is_some() { tile_count } else { 0 });
        for y in (0..image.height).step_by(th) {
            for x in (0..image.width).step_by(tw) {
                cancelled(cancel)?;
                let i = (y / th) * nx + x / tw;
                let tile = if let Some(tiles) = &gpu_tiles {
                    &tiles[i * tw * th..(i + 1) * tw * th]
                } else {
                    fill_tile(&image, x, y, tw, th, &mut scratch);
                    &scratch
                };
                let predictors = rankings.as_ref().map_or(candidates, |rankings| {
                    &rankings[i][..if effort == Effort::Max { 2 } else { 1 }]
                });
                let mut best_tile: Option<Vec<u8>> = None;
                if let Some(encoded) = &mut encoded_tiles {
                    best_tile = Some(std::mem::take(&mut encoded[i]));
                } else {
                    for &p in predictors {
                        let encoder = ljpeg::Encoder::new(
                            jw as u16,
                            jh as u16,
                            ljpeg::Components::C2,
                            ljpeg::Bitdepth::try_from(image.bits as u8)
                                .map_err(|_| anyhow::anyhow!("Invalid JPEG depth"))?,
                            ljpeg::Predictor::try_from(p)
                                .map_err(|_| anyhow::anyhow!("Invalid JPEG predictor"))?,
                            0,
                            0,
                        );
                        let blob = encoder.encode(tile).context("JPEG encoder failed")?;
                        if best_tile.as_ref().is_none_or(|old| blob.len() < old.len()) {
                            best_tile = Some(blob);
                        }
                    }
                }
                let blob = best_tile.unwrap();
                offsets.push(out.len() as u32);
                sizes.push(blob.len() as u32);
                out.extend_from_slice(&blob);
                if gpu.is_some_and(|g| g.entropy_enabled()) {
                    verified_payloads.push(blob);
                }
            }
        }
        if out.len() % 2 != 0 {
            out.push(0);
        }
        let mut entries: BTreeMap<u16, [u8; 12]> = image
            .tags
            .iter()
            .filter(|(tag, _)| !LAYOUT.contains(tag))
            .map(|(&t, e)| (t, e.raw))
            .collect();
        fn entry(tags: &mut BTreeMap<u16, [u8; 12]>, tag: u16, typ: u16, count: u32, value: u32) {
            let mut e = [0; 12];
            e[..2].copy_from_slice(&tag.to_le_bytes());
            e[2..4].copy_from_slice(&typ.to_le_bytes());
            e[4..8].copy_from_slice(&count.to_le_bytes());
            e[8..].copy_from_slice(&value.to_le_bytes());
            tags.insert(tag, e);
        }
        entry(&mut entries, 259, 3, 1, 7);
        entry(&mut entries, 322, 4, 1, tw as u32);
        entry(&mut entries, 323, 4, 1, th as u32);
        for (tag, values) in [(324, &offsets), (325, &sizes)] {
            let location = if values.len() == 1 {
                values[0]
            } else {
                let at = out.len() as u32;
                for v in values {
                    out.extend(v.to_le_bytes());
                }
                at
            };
            entry(&mut entries, tag, 4, values.len() as u32, location);
        }
        let ifd = out.len() as u32;
        out.extend((entries.len() as u16).to_le_bytes());
        for e in entries.values() {
            out.extend(e);
        }
        out.extend([0; 4]);
        out[4..8].copy_from_slice(&ifd.to_le_bytes());
        if out.len() < if best.is_empty() { d.len() } else { best.len() } {
            best = out;
            if gpu.is_some_and(|g| g.entropy_enabled()) {
                best_audit = Some(Audit {
                    tw,
                    th,
                    offsets,
                    sizes,
                    payloads: verified_payloads,
                });
            }
        }
    }
    if best.is_empty() {
        best = d.to_vec();
    }
    let encoded_at = started.elapsed();
    if best.len() == d.len() {
        info.codec = "original-passthrough".into();
        info.verification = "original-bytes".into();
        info.pixel_verified = true;
    } else if let Some(audit) = best_audit {
        audit_gpu_container(&best, d, &image, &audit)?;
    } else {
        // Verify the exact DNG that will be archived, including tile placement.
        // Rejected candidates never reach the image and need no extra decode.
        ensure!(
            decode(&best)? == image.pixels,
            "DNG reconstruction changed RAW samples"
        );
    }
    if profile {
        eprintln!(
            "CDNG_STAGES read_hash_ms={:.3} prepare_ms={:.3} encode_ms={:.3} verify_ms={:.3}",
            read_at.as_secs_f64() * 1000.,
            (prepared_at - read_at).as_secs_f64() * 1000.,
            (encoded_at - prepared_at).as_secs_f64() * 1000.,
            (started.elapsed() - encoded_at).as_secs_f64() * 1000.
        );
    }
    Ok((best, info, source_sha256))
}

#[cfg(test)]
#[path = "geometry_prune_diagnostic.rs"]
mod geometry_prune_diagnostic;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn jxl_frame_reuses_samples_without_changing_hash_or_dng_metadata() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let source = std::fs::read(root.join("bmd_gen1/resolve_test/0_fp_original.dng")).unwrap();
        let image = read(&source, true).unwrap();
        let mut expected_planes = image.pixels.clone();
        crate::jxl::cfa_permute(&mut expected_planes, image.width, image.height, false).unwrap();
        let reference = JxlFrame {
            width: image.width, height: image.height, bits: image.bits,
            head: source[..image.prefix].to_vec(), pixel_sha256: pixel_hash(&image.pixels),
            planes: expected_planes, image,
        };
        let mut actual = jxl_frame(&source).unwrap();
        assert_eq!(actual.planes, reference.planes);
        assert_eq!(actual.pixel_sha256, reference.pixel_sha256);
        assert_eq!(actual.image.pixels.capacity(), 0, "second RAW allocation was retained");
        // Container construction is independent of the codec. The same payload
        // must produce identical metadata, offsets, sample hash and DNG bytes.
        let payload = [0xff, 0x0a, 1, 2, 3];
        let (expected, expected_info) = jxl_dng(&reference, &payload, None, "test", Backend::Cpu);
        let (out, info) = jxl_dng(&actual, &payload, None, "test", Backend::Cpu);
        assert_eq!(out, expected);
        assert_eq!(serde_json::to_value(info).unwrap(), serde_json::to_value(expected_info).unwrap());
        let before = actual.retained_bytes();
        let old_capacity = actual.head.capacity();
        actual.head.reserve(1 << 20);
        assert_eq!(actual.retained_bytes() - before, actual.head.capacity() - old_capacity,
            "queue accounting ignored a larger metadata allocation");
        assert!(actual.retained_bytes() >= actual.planes.capacity() * 2 + actual.head.capacity());
    }

    #[test]
    fn deferred_hashes_preserve_source_pixels_and_public_compression_output() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let source = std::fs::read(root.join("bmd_gen1/resolve_test/0_fp_original.dng")).unwrap();
        let pixels = decode(&source).unwrap();
        let expected_pixels: Vec<u8> = pixels.iter().flat_map(|p| p.to_le_bytes()).collect();
        let mut modes = vec![(Backend::Cpu, Effort::Fast)];
        if cfg!(target_os = "macos") && std::env::var_os("CDNG_TEST_GPU").is_some() {
            modes.push((Backend::Metal, Effort::Max));
        }
        for (backend, effort) in modes {
            let gpu = (backend == Backend::Metal).then(|| Gpu::new(backend).unwrap());
            let cancel = AtomicBool::new(false);
            let (expected, public_info) = compress(&source, effort, backend, gpu.as_ref(), &cancel).unwrap();
            let (actual, info, source_digest) = compress_with_source_hash(&source, effort, backend, gpu.as_ref(), &cancel).unwrap();
            assert_eq!(actual, expected);
            assert_eq!(serde_json::to_value(&info).unwrap(), serde_json::to_value(&public_info).unwrap());
            assert_eq!(source_digest, crate::hash(&source));
            assert_eq!(info.pixel_sha256, crate::hash(&expected_pixels));
            assert!(info.pixel_verified);
            assert_eq!(decode(&actual).unwrap(), pixels);
            assert!(compress_with_source_hash(&source, effort, backend, gpu.as_ref(), &AtomicBool::new(true)).is_err());
        }
    }

    #[test]
    fn preparation_host_work_runs_once_in_cpu_and_odd_height_fallbacks() {
        let gpu = if cfg!(target_os = "macos") && std::env::var_os("CDNG_TEST_GPU").is_some() {
            Some(Gpu::new(Backend::Metal).unwrap())
        } else { None };
        for (height, effort, gpu) in [(34, Effort::Max, None), (33, Effort::Max, gpu.as_ref()), (34, Effort::Fast, gpu.as_ref())] {
            let image = Image { width: 18, height, bits: 12,
                pixels: (0..18 * height).map(|i| (i * 31 % 4096) as u16).collect(),
                prefix: 0, tags: BTreeMap::new() };
            let mut calls = 0;
            let mut work = || { calls += 1; Ok(()) };
            let prepared = prepare_search(&image, effort, gpu, &AtomicBool::new(false), Some(&mut work)).unwrap();
            assert!(!prepared.is_empty());
            assert_eq!(calls, 1);
        }
    }
    #[cfg(target_os = "macos")]
    #[test]
    fn gpu_container_exact_payload_audit_rejects_copy_corruption() {
        if std::env::var_os("CDNG_TEST_GPU").is_none() { return; }
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let source = std::fs::read(root.join("bmd_gen1/resolve_test/0_fp_original.dng")).unwrap();
        let gpu = Gpu::new(Backend::Metal).unwrap();
        let image = read(&source, true).unwrap();
        let (mut output, _) = compress(&source, Effort::Max, Backend::Metal, Some(&gpu), &AtomicBool::new(false)).unwrap();
        let tags = entries(&output, u32at(&output, 4).unwrap() as usize).unwrap();
        let offsets: Vec<u32> = tags[&324].values(&output).unwrap().into_iter().map(|v| v as u32).collect();
        let sizes: Vec<u32> = tags[&325].values(&output).unwrap().into_iter().map(|v| v as u32).collect();
        let payloads = offsets.iter().zip(&sizes).map(|(&at, &size)| output[at as usize..(at + size) as usize].to_vec()).collect();
        let audit = Audit { tw: scalar(&tags, &output, 322, None).unwrap(), th: scalar(&tags, &output, 323, None).unwrap(), offsets, sizes, payloads };
        audit_gpu_container(&output, &source, &image, &audit).unwrap();
        let at = audit.offsets[0] as usize + audit.sizes[0] as usize / 2;
        output[at] ^= 1;
        assert!(audit_gpu_container(&output, &source, &image, &audit).is_err());
    }
    #[test]
    fn optimized_jpeg_decodes_with_unmodified_upstream_decoder() {
        for bits in [8u8, 10, 12, 14, 16] {
            for predictor in 1u8..=7 {
                for components in 1u8..=4 {
                    for (width, height) in [(1, 1), (7, 5), (66, 17)] {
                        let mask = (1u32 << bits) - 1;
                        let input: Vec<u16> = (0..width as u32 * height as u32 * components as u32)
                            .map(|i| {
                                (match i % 5 {
                                    0 => 0,
                                    1 => mask,
                                    _ => i.wrapping_mul(23417).wrapping_add(i * i * 11) & mask,
                                }) as u16
                            })
                            .collect();
                        let optimized = ljpeg::Encoder::new(
                            width,
                            height,
                            ljpeg::Components::try_from(components).unwrap(),
                            ljpeg::Bitdepth::try_from(bits).unwrap(),
                            ljpeg::Predictor::try_from(predictor).unwrap(),
                            0,
                            0,
                        )
                        .encode(&input)
                        .unwrap();
                        let reference = ljpeg_reference::Encoder::new(
                            width,
                            height,
                            ljpeg_reference::Components::try_from(components).unwrap(),
                            ljpeg_reference::Bitdepth::try_from(bits).unwrap(),
                            ljpeg_reference::Predictor::try_from(predictor).unwrap(),
                            0,
                            0,
                        )
                        .encode(&input)
                        .unwrap();
                        assert_eq!(
                            ljpeg_reference::Decoder::new(&optimized)
                                .unwrap()
                                .decode()
                                .unwrap(),
                            input,
                            "{bits}-bit P{predictor} C{components} {width}x{height}"
                        );
                        // Both streams remain legal JPEG; integer-frequency Huffman
                        // optimization may choose a different canonical code table.
                        assert_eq!(
                            ljpeg::Decoder::new(&reference).unwrap().decode().unwrap(),
                            input
                        );
                    }
                }
            }
        }
    }
    #[test]
    fn packed_rows_and_pixel_hash_match_scalar_reference() {
        for bits in [8, 10, 12, 14, 16] {
            for width in [2usize, 4, 6, 66, 512] {
                let mask = (1u32 << bits) - 1;
                let expected: Vec<u16> = (0..width)
                    .map(|x| ((x as u32 * 23417 + x as u32 * x as u32 * 11) & mask) as u16)
                    .collect();
                let mut row = vec![0u8; (width * bits).div_ceil(8)];
                for (x, &sample) in expected.iter().enumerate() {
                    if bits == 16 {
                        row[x * 2..x * 2 + 2].copy_from_slice(&sample.to_le_bytes());
                    } else {
                        for b in 0..bits {
                            let at = x * bits + b;
                            row[at / 8] |= (((sample >> (bits - 1 - b)) & 1) as u8) << (7 - at % 8);
                        }
                    }
                }
                let mut actual = vec![0; width];
                unpack_row(&row, &mut actual, bits);
                assert_eq!(actual, expected, "{bits}-bit width {width}");
                let bytes: Vec<u8> = expected.iter().flat_map(|p| p.to_le_bytes()).collect();
                assert_eq!(pixel_hash(&actual), crate::hash(&bytes));
            }
        }
        // Cross the hash buffer boundary, including an incomplete final block.
        let pixels: Vec<u16> = (0..17001).map(|p| p as u16).collect();
        let bytes: Vec<u8> = pixels.iter().flat_map(|p| p.to_le_bytes()).collect();
        assert_eq!(pixel_hash(&pixels), crate::hash(&bytes));
    }
    #[test]
    fn preview_does_not_change_raw_and_handles_compressed_input() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
        for file in [
            "bmd_gen1/resolve_test/0_fp_original.dng",
            "research/slimRAW/captures/A001_083_FHD_f07_compressed_288x368.DNG",
        ] {
            let data = std::fs::read(root.join(file)).unwrap();
            let before = crate::hash(&data);
            let p = preview(&data).unwrap();
            assert_eq!(p.rgb.len(), p.width * p.height * 3);
            assert!(p.width <= 640);
            assert!(p.rgb.iter().any(|&v| v != 0));
            assert!(p.rgb.iter().any(|&v| v != 255));
            assert_eq!(before, crate::hash(&data));
        }
    }
    #[test]
    fn truncated_is_rejected() {
        assert!(decode(b"II*\0\x08\0").is_err());
    }
    #[test]
    fn native_and_already_compressed_pixels() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
        for relative in [
            "bmd_gen1/resolve_test/0_fp_original.dng",
            "research/slimRAW/captures/A001_083_FHD_f07_compressed_288x368.DNG",
        ] {
            let data = std::fs::read(root.join(relative)).unwrap();
            let before = decode(&data).unwrap();
            let (out, _) = compress(
                &data,
                Effort::Max,
                Backend::Cpu,
                None,
                &AtomicBool::new(false),
            )
            .unwrap();
            assert!(out.len() < data.len());
            assert_eq!(decode(&out).unwrap(), before);
        }
    }
}
