//! Versioned JXL archive, mmap input, independent frames, byte-limited single-flight cache.
//! This is the mount-independent read engine; it does not install a system driver.
use crate::{
    Backend, Effort, cancelled, dng, hash, jxl,
    pack::{self, Options, Summary},
};
use anyhow::{Context, Result, ensure};
use memmap2::Mmap;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::{HashMap, HashSet},
    fs::{self, File, OpenOptions},
    io::{Read, Seek, SeekFrom, Write},
    path::{Path, PathBuf},
    sync::{
        Arc, Condvar, Mutex,
        atomic::{AtomicBool, AtomicUsize, Ordering},
    },
    time::{Instant, SystemTime, UNIX_EPOCH},
};
const HEADER: usize = 128;
const MAGIC: &[u8; 8] = b"CDNGJXL1";
const TEMPORAL_GROUP_BYTES: usize = 192 << 20;
#[derive(Serialize, Deserialize, Clone)]
pub struct TemporalFrame {
    pub count: usize,
    pub index: usize,
}
#[derive(Serialize, Deserialize, Clone)]
pub struct Frame {
    pub width: usize,
    pub height: usize,
    pub original_bits: usize,
    pub raw_sha256: String,
    pub header_offset: u64,
    pub header_len: usize,
    pub header_sha256: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub temporal: Option<TemporalFrame>,
}
#[derive(Serialize, Deserialize, Clone)]
pub struct Entry {
    pub path: String,
    pub offset: u64,
    pub length: usize,
    pub sha256: String,
    pub virtual_size: u64,
    pub frame: Option<Frame>,
}
#[derive(Serialize, Deserialize)]
pub struct Index {
    pub format: String,
    pub version: u32,
    pub profile: String,
    pub libjxl: u32,
    pub directories: Vec<String>,
    pub entries: Vec<Entry>,
}
fn safe_path(path: &str) -> bool {
    !path.is_empty()
        && !path.contains('\\')
        && !path.contains('\0')
        && !path.contains(':')
        && path
            .split('/')
            .all(|p| !p.is_empty() && p != "." && p != "..")
}
fn map(file: &File) -> Result<Mmap> {
    // Published archives and sources must stay immutable while mapped.
    Ok(unsafe { memmap2::MmapOptions::new().map(file)? })
}
pub fn pack(
    options: &Options,
    cancel: &AtomicBool,
    progress: impl Fn(Value) + Sync,
) -> Result<Summary> {
    ensure!(!options.store, "JPEG XL 封存需要無損壓縮模式");
    ensure!(
        (1..=32).contains(&options.workers),
        "Worker count must be 1–32"
    );
    let started = Instant::now();
    let codec = jxl::Codec::load()?;
    let source = options.source.canonicalize()?;
    ensure!(source.is_dir(), "請選擇素材資料夾");
    let parent = options
        .output
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."))
        .canonicalize()?;
    let output = parent.join(
        options
            .output
            .file_name()
            .context("Missing output filename")?,
    );
    ensure!(!output.starts_with(&source), "封存檔需存放在素材資料夾之外");
    ensure!(!output.exists(), "封存檔已存在");
    let items = pack::select_items(pack::inventory(&source)?, &options.excluded_clips)?;
    let files: Vec<_> = items.iter().filter(|i| !i.dir).collect();
    ensure!(!files.is_empty(), "素材資料夾是空的");
    ensure!(
        items.iter().all(|i| safe_path(&i.relative)),
        "不支援的封存路徑"
    );
    let source_bytes = files.iter().map(|i| i.stamp.length).sum();
    let (partial, mut out) = crate::output::OutputFile::create(&output)?;
    out.write_all(&[0; HEADER])?;
    let (effort, tier, profile) = match options.effort {
        Effort::Fast => (7, 4, "fast-decode"),
        Effort::Balanced => (3, 0, "balanced"),
        Effort::Max => (7, 0, "dense"),
    };
    let budget = options
        .ram_buffer_bytes
        .unwrap_or_else(crate::ram::default_budget);
    ensure!(budget <= 32usize << 30, "RAM buffer exceeds 32 GiB");
    let queue = crate::ram::Queue::new(budget);
    let stopped = AtomicBool::new(false);
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(options.workers)
        .build()?;
    struct Work {
        header: Vec<u8>,
        payload: Vec<u8>,
        info: dng::Info,
    }
    let prepare = |item: &&pack::Item| -> Result<Option<Work>> {
        cancelled(cancel)?;
        pack::check(item)?;
        if !pack::is_dng_source(&item.path) {
            return Ok(None);
        }
        let file = File::open(&item.path)?;
        ensure!(
            pack::fingerprint(&file.metadata()?)? == item.stamp,
            "Source changed"
        );
        let input = map(&file)?;
        let (header, mut pixels, info) = dng::archive_input(&input)?;
        jxl::cfa_permute(&mut pixels, info.width, info.height, false)?;
        let payload = codec.encode(&pixels, info.width, info.height, effort, tier)?;
        cancelled(cancel)?;
        let decoded = codec.decode(&payload, info.width, info.height)?;
        ensure!(decoded == pixels, "JPEG XL 改變 RAW 像素");
        pack::check(item)?;
        Ok(Some(Work {
            header,
            payload,
            info,
        }))
    };
    let mut entries = Vec::new();
    let mut compressed_files = 0;
    let mut write_seconds = 0.;
    let mut wait_seconds = 0.;
    std::thread::scope(|scope| -> Result<()> {
        let queue = &queue;
        let stop = &stopped;
        let worker = scope.spawn(|| {
            let _done = queue.producer();
            pool.install(|| {
                files.par_iter().for_each(|item| {
                    if stop.load(Ordering::Relaxed) {
                        return;
                    }
                    let result = prepare(item);
                    let cost = result
                        .as_ref()
                        .ok()
                        .and_then(|r| r.as_ref())
                        .map_or(512, |w| w.header.capacity() + w.payload.capacity() + 512);
                    if !queue.push((*item, result), cost) {
                        stop.store(true, Ordering::Relaxed);
                    }
                })
            });
        });
        let result = (|| -> Result<()> {
            loop {
                let t = Instant::now();
                let next = queue.pop();
                wait_seconds += t.elapsed().as_secs_f64();
                let Some((item, result)) = next else {
                    break;
                };
                let work = result?;
                cancelled(cancel)?;
                let t = Instant::now();
                let entry = if let Some(work) = work {
                    let header_offset = out.stream_position()?;
                    out.write_all(&work.header)?;
                    let offset = out.stream_position()?;
                    out.write_all(&work.payload)?;
                    let virtual_size =
                        (work.header.len() + work.info.width * work.info.height * 2) as u64;
                    Entry {
                        path: item.relative.clone(),
                        offset,
                        length: work.payload.len(),
                        sha256: hash(&work.payload),
                        virtual_size,
                        frame: Some(Frame {
                            width: work.info.width,
                            height: work.info.height,
                            original_bits: work.info.bits,
                            raw_sha256: work.info.pixel_sha256,
                            header_offset,
                            header_len: work.header.len(),
                            header_sha256: hash(&work.header),
                            temporal: None,
                        }),
                    }
                } else {
                    pack::check(item)?;
                    let mut file = File::open(&item.path)?;
                    ensure!(
                        pack::fingerprint(&file.metadata()?)? == item.stamp,
                        "Source changed"
                    );
                    let offset = out.stream_position()?;
                    use crate::digest::Sha256;
                    let mut digest = Sha256::new();
                    let mut buffer = vec![0; 1 << 20];
                    let mut n = 0usize;
                    loop {
                        cancelled(cancel)?;
                        let got = file.read(&mut buffer)?;
                        if got == 0 {
                            break;
                        }
                        out.write_all(&buffer[..got])?;
                        digest.update(&buffer[..got]);
                        n += got;
                    }
                    ensure!(n as u64 == item.stamp.length, "Source changed");
                    Entry {
                        path: item.relative.clone(),
                        offset,
                        length: n,
                        sha256: format!("{:x}", digest.finalize()),
                        virtual_size: n as u64,
                        frame: None,
                    }
                };
                pack::check(item)?;
                if ((entry.length + entry.frame.as_ref().map_or(0, |f| f.header_len)) as u64)
                    < item.stamp.length
                {
                    compressed_files += 1;
                }
                entries.push(entry);
                write_seconds += t.elapsed().as_secs_f64();
                progress(
                    json!({"stage":"compress","done":entries.len(),"total":files.len(),"name":item.relative,"backend":"cpu-jxl","ram_buffered_bytes":queue.stats().0,"ram_buffer_bytes":budget}),
                );
            }
            Ok(())
        })();
        stopped.store(true, Ordering::Relaxed);
        queue.abort();
        worker
            .join()
            .map_err(|_| anyhow::anyhow!("JPEG XL 工作失敗"))?;
        result
    })?;
    ensure!(
        pack::select_items(pack::inventory(&source)?, &options.excluded_clips)? == items,
        "素材在處理期間改變"
    );
    entries.sort_by(|a, b| a.path.cmp(&b.path));
    let index = Index {
        format: "CDNG JXL Archive".into(),
        version: 1,
        profile: profile.into(),
        libjxl: codec.version(),
        directories: items
            .iter()
            .filter(|i| i.dir)
            .map(|i| i.relative.clone())
            .collect(),
        entries,
    };
    let bytes = serde_json::to_vec(&index)?;
    ensure!(bytes.len() <= 64 << 20, "Archive index too large");
    let index_at = out.stream_position()?;
    out.write_all(&bytes)?;
    let mut header = [0; HEADER];
    header[..8].copy_from_slice(MAGIC);
    header[8..12].copy_from_slice(&1u32.to_le_bytes());
    header[12..16].copy_from_slice(&(HEADER as u32).to_le_bytes());
    header[16..24].copy_from_slice(&index_at.to_le_bytes());
    header[24..32].copy_from_slice(&(bytes.len() as u64).to_le_bytes());
    header[32..96].copy_from_slice(hash(&bytes).as_bytes());
    out.seek(SeekFrom::Start(0))?;
    out.write_all(&header)?;
    out.sync_all()?;
    let image_bytes = out.metadata()?.len();
    drop(out);
    let checking = Instant::now();
    if options.verify {
        let reader = Archive::open(partial.path(), 256 << 20)?;
        for i in 0..reader.index.entries.len() {
            cancelled(cancel)?;
            reader.verify_entry(i)?;
            progress(
                json!({"stage":"verify","done":i+1,"total":files.len(),"name":reader.index.entries[i].path}),
            );
        }
    }
    cancelled(cancel)?;
    let check_seconds = checking.elapsed().as_secs_f64();
    partial.finish()?;
    let result = Summary {
        output_format: "cdng-jxl-v1",
        output,
        source_bytes,
        image_bytes,
        files: files.len(),
        compressed_files,
        seconds: started.elapsed().as_secs_f64(),
        backend: Backend::Cpu,
        effort: options.effort,
        workers: options.workers,
        checksums_verified: options.verify,
        raw_verification: "cpu-full-jxl-decode",
        ram_buffer_bytes: budget,
        ram_peak_bytes: queue.stats().1,
        iso_write_seconds: write_seconds,
        writer_wait_seconds: wait_seconds,
        image_check_seconds: check_seconds,
        image_check_pipelined: false,
        dmg_finalize_seconds: 0.,
        dmg_checksum_streamed: false,
        engine: "rust",
    };
    progress(json!({"stage":"done","result":result}));
    Ok(result)
}
struct TemporalWork<'a> {
    item: &'a pack::Item,
    header: Vec<u8>,
    pixels: Vec<u16>,
    info: dng::Info,
    layout: Vec<usize>,
}

impl TemporalWork<'_> {
    fn clip(&self) -> &str { self.item.relative.rsplit_once('/').map_or("", |(p, _)| p) }
    fn retained_bytes(&self) -> usize {
        self.header.capacity() + self.pixels.capacity() * 2 + self.layout.capacity() * std::mem::size_of::<usize>() + 1024
    }
    fn compatible(&self, other: &Self) -> bool {
        self.clip() == other.clip() && self.info.width == other.info.width
            && self.info.height == other.info.height && self.info.bits == other.info.bits
            && self.layout == other.layout
    }
}

fn write_temporal_group(
    batch: &mut Vec<TemporalWork<'_>>, coder: &mut crate::temporal::GroupCoder,
    out: &mut File, entries: &mut Vec<Entry>, cancel: &AtomicBool,
    total: usize, progress: &(impl Fn(Value) + Sync), compressed: &mut usize,
    write_seconds: &mut f64, peak: &mut usize,
) -> Result<()> {
    if batch.is_empty() { return Ok(()); }
    cancelled(cancel)?;
    let first = &batch[0];
    let (width, height, bits) = (first.info.width, first.info.height, first.info.bits);
    progress(json!({"stage":"codec","codec":"temporal","phase":"encode",
        "name":"Compressing TemporalCube frames…","frames":batch.len()}));
    let planes: Vec<&[u16]> = batch.iter().map(|f| f.pixels.as_slice()).collect();
    let encoded = coder.encode(first.clip(), &planes, width, height, bits, cancel)?;
    cancelled(cancel)?;
    ensure!((encoded.temporal && batch.len() >= 2 && encoded.payloads.len() == 1)
        || (!encoded.temporal && encoded.payloads.len() == batch.len()), "Temporal encoder returned an invalid group");
    *peak = (*peak).max(batch.iter().map(TemporalWork::retained_bytes).sum::<usize>()
        + encoded.payloads.iter().map(Vec::capacity).sum::<usize>());
    for work in batch.iter() { pack::check(work.item)?; }
    let writing = Instant::now();
    let shared = if encoded.temporal {
        let payload = &encoded.payloads[0];
        let offset = out.stream_position()?;
        out.write_all(payload)?;
        Some((offset, payload.len(), hash(payload)))
    } else { None };
    let count = batch.len();
    for (i, work) in batch.drain(..).enumerate() {
        cancelled(cancel)?;
        let header_offset = out.stream_position()?;
        out.write_all(&work.header)?;
        let (offset, length, sha256) = if let Some(shared) = &shared { shared.clone() } else {
            let payload = &encoded.payloads[i];
            let offset = out.stream_position()?;
            out.write_all(payload)?;
            (offset, payload.len(), hash(payload))
        };
        let physical_share = if encoded.temporal { length / count + usize::from(i < length % count) } else { length };
        if ((physical_share + work.header.len()) as u64) < work.item.stamp.length { *compressed += 1; }
        let header_len = work.header.len();
        entries.push(Entry {
            path: work.item.relative.clone(), offset, length, sha256,
            virtual_size: (header_len + width * height * 2) as u64,
            frame: Some(Frame { width, height, original_bits: bits, raw_sha256: work.info.pixel_sha256,
                header_offset, header_len, header_sha256: hash(&work.header),
                temporal: encoded.temporal.then_some(TemporalFrame { count, index: i }) }),
        });
        pack::check(work.item)?;
        progress(json!({"stage":"compress","done":entries.len(),"total":total,"name":work.item.relative}));
    }
    *write_seconds += writing.elapsed().as_secs_f64();
    Ok(())
}

/// Version 2 archive: independently verifiable DNG metadata and bounded groups
/// of reversible temporal RAW samples. The existing reader also opens version 1.
pub fn pack_temporal(options: &Options, cancel: &AtomicBool, progress: impl Fn(Value) + Sync) -> Result<Summary> {
    ensure!(!options.store, "TemporalCube requires lossless compression");
    ensure!((1..=32).contains(&options.workers), "Worker count must be 1–32");
    cancelled(cancel)?;
    let started = Instant::now();
    let source = options.source.canonicalize()?;
    ensure!(source.is_dir(), "請選擇素材資料夾");
    let parent = options.output.parent().filter(|p| !p.as_os_str().is_empty()).unwrap_or(Path::new(".")).canonicalize()?;
    let output = parent.join(options.output.file_name().context("Missing output filename")?);
    ensure!(!output.starts_with(&source), "封存檔需存放在素材資料夾之外");
    ensure!(fs::symlink_metadata(&output).is_err(), "封存檔已存在");
    let items = pack::select_items(pack::inventory(&source)?, &options.excluded_clips)?;
    let files: Vec<_> = items.iter().filter(|i| !i.dir).collect();
    ensure!(!files.is_empty(), "素材資料夾是空的");
    ensure!(items.iter().all(|i| safe_path(&i.relative)), "不支援的封存路徑");
    let source_bytes = files.iter().map(|i| i.stamp.length).sum();
    let budget = options.ram_buffer_bytes.unwrap_or_else(crate::ram::default_budget);
    ensure!(budget <= 32usize << 30, "RAM buffer exceeds 32 GiB");
    let group_budget = budget.min(TEMPORAL_GROUP_BYTES);
    progress(json!({"stage":"codec","codec":"temporal","phase":"initialize","name":"Preparing TemporalCube compression…"}));
    let mut coder = crate::temporal::GroupCoder::new(options.backend, options.effort)?;
    let codec_version = coder.version();
    cancelled(cancel)?;
    progress(json!({"stage":"codec","codec":"temporal","phase":"ready","name":"Preparing TemporalCube frames…"}));
    let (partial, mut out) = crate::output::OutputFile::create(&output)?;
    out.write_all(&[0; HEADER])?;
    let mut batch = Vec::<TemporalWork<'_>>::new();
    let mut entries = Vec::new();
    let (mut compressed_files, mut peak) = (0, 0);
    let mut write_seconds = 0.;
    for item in &files {
        cancelled(cancel)?;
        pack::check(item)?;
        if pack::is_dng_source(&item.path) {
            let file = File::open(&item.path)?;
            ensure!(pack::fingerprint(&file.metadata()?)? == item.stamp, "Source changed");
            let input = map(&file)?;
            let layout = dng::archive_layout_key(&input)?;
            let (header, pixels, info) = dng::archive_input(&input).with_context(|| format!("無法讀取 {}", item.relative))?;
            ensure!(pixels.len() * 2 <= TEMPORAL_GROUP_BYTES, "Single RAW frame exceeds 192 MiB");
            ensure!(pack::fingerprint(&file.metadata()?)? == item.stamp, "Source changed");
            pack::check(item)?;
            let work = TemporalWork { item, header, pixels, info, layout };
            let max_count = (group_budget / (work.pixels.len() * 2)).clamp(1, 8);
            if batch.first().is_some_and(|first| !first.compatible(&work)) || batch.len() >= max_count {
                write_temporal_group(&mut batch, &mut coder, &mut out, &mut entries, cancel,
                    files.len(), &progress, &mut compressed_files, &mut write_seconds, &mut peak)?;
            }
            batch.push(work);
            peak = peak.max(batch.iter().map(TemporalWork::retained_bytes).sum());
            if batch.len() >= max_count {
                write_temporal_group(&mut batch, &mut coder, &mut out, &mut entries, cancel,
                    files.len(), &progress, &mut compressed_files, &mut write_seconds, &mut peak)?;
            }
        } else {
            write_temporal_group(&mut batch, &mut coder, &mut out, &mut entries, cancel,
                files.len(), &progress, &mut compressed_files, &mut write_seconds, &mut peak)?;
            let writing = Instant::now();
            let mut file = File::open(&item.path)?;
            ensure!(pack::fingerprint(&file.metadata()?)? == item.stamp, "Source changed");
            let offset = out.stream_position()?;
            let mut digest = crate::digest::Sha256::new();
            let mut buffer = vec![0; 1 << 20];
            let mut length = 0usize;
            loop {
                cancelled(cancel)?;
                let n = file.read(&mut buffer)?;
                if n == 0 { break; }
                out.write_all(&buffer[..n])?;
                digest.update(&buffer[..n]);
                length = length.checked_add(n).context("Sidecar size overflow")?;
            }
            ensure!(length as u64 == item.stamp.length && pack::fingerprint(&file.metadata()?)? == item.stamp, "Source changed");
            pack::check(item)?;
            entries.push(Entry { path: item.relative.clone(), offset, length, sha256: format!("{:x}", digest.finalize()),
                virtual_size: length as u64, frame: None });
            write_seconds += writing.elapsed().as_secs_f64();
            progress(json!({"stage":"compress","done":entries.len(),"total":files.len(),"name":item.relative}));
        }
    }
    write_temporal_group(&mut batch, &mut coder, &mut out, &mut entries, cancel,
        files.len(), &progress, &mut compressed_files, &mut write_seconds, &mut peak)?;
    // Release encoder/GPU scratch before the independent archive readback cache.
    drop(coder);
    cancelled(cancel)?;
    ensure!(entries.len() == files.len(), "Archive is missing files");
    ensure!(pack::select_items(pack::inventory(&source)?, &options.excluded_clips)? == items, "素材在處理期間改變");
    entries.sort_by(|a, b| a.path.cmp(&b.path));
    let index = Index { format: "CDNG JXL Archive".into(), version: 2, profile: "temporal-cube-lossless".into(),
        libjxl: codec_version, directories: items.iter().filter(|i| i.dir).map(|i| i.relative.clone()).collect(), entries };
    let bytes = serde_json::to_vec(&index)?;
    ensure!(bytes.len() <= 64 << 20, "Archive index too large");
    let index_at = out.stream_position()?;
    out.write_all(&bytes)?;
    let mut header = [0; HEADER];
    header[..8].copy_from_slice(MAGIC);
    header[8..12].copy_from_slice(&2u32.to_le_bytes());
    header[12..16].copy_from_slice(&(HEADER as u32).to_le_bytes());
    header[16..24].copy_from_slice(&index_at.to_le_bytes());
    header[24..32].copy_from_slice(&(bytes.len() as u64).to_le_bytes());
    header[32..96].copy_from_slice(hash(&bytes).as_bytes());
    out.seek(SeekFrom::Start(0))?;
    out.write_all(&header)?;
    out.sync_all()?;
    let image_bytes = out.metadata()?.len();
    drop(out);
    let checking = Instant::now();
    // Independently decode every group and compare every original RAW hash.
    // Process one task per shared payload, with cache reservations bounding RAM.
    let reader = Archive::open(partial.path(), TEMPORAL_GROUP_BYTES)?;
    reader.verify_all(options.workers, cancel, &progress)?;
    drop(reader);
    cancelled(cancel)?;
    ensure!(pack::select_items(pack::inventory(&source)?, &options.excluded_clips)? == items, "素材在處理期間改變");
    let check_seconds = checking.elapsed().as_secs_f64();
    partial.finish()?;
    let result = Summary { output_format: "cdng-temporal-v2", output, source_bytes, image_bytes,
        files: files.len(), compressed_files, seconds: started.elapsed().as_secs_f64(),
        backend: options.backend, effort: options.effort, workers: options.workers.clamp(1, 8), checksums_verified: true,
        raw_verification: "full-temporal-roundtrip", ram_buffer_bytes: group_budget, ram_peak_bytes: peak,
        iso_write_seconds: write_seconds, writer_wait_seconds: 0., image_check_seconds: check_seconds,
        image_check_pipelined: false, dmg_finalize_seconds: 0., dmg_checksum_streamed: false, engine: "rust" };
    progress(json!({"stage":"done","result":result}));
    Ok(result)
}

struct Cached {
    pixels: Arc<Vec<u16>>,
    tick: u64,
}
#[derive(Default)]
struct Cache {
    frames: HashMap<usize, Cached>,
    used: usize,
    reserved: usize,
    peak: usize,
    tick: u64,
}
pub struct Archive {
    pub index: Index,
    data: Mmap,
    codec: Mutex<Option<Arc<jxl::Codec>>>,
    gates: Vec<Mutex<()>>,
    verified: Vec<AtomicBool>,
    cache: Mutex<Cache>,
    changed: Condvar,
    budget: usize,
    hits: AtomicUsize,
    misses: AtomicUsize,
    cache_keys: Vec<usize>,
    groups: HashMap<usize, Vec<usize>>,
}
struct Lease<'a> {
    pixels: Option<Arc<Vec<u16>>>,
    start: usize,
    len: usize,
    owner: &'a Archive,
}
impl Drop for Lease<'_> {
    fn drop(&mut self) {
        drop(self.pixels.take());
        let _lock = self.owner.cache.lock();
        self.owner.changed.notify_all();
    }
}
impl Archive {
    pub fn open(path: &Path, budget: usize) -> Result<Self> {
        let file = File::open(path)?;
        let data = map(&file)?;
        ensure!(
            data.len() >= HEADER && &data[..8] == MAGIC,
            "不是 CDNG JXL 封存檔"
        );
        let version = u32::from_le_bytes(data[8..12].try_into()?);
        ensure!(
            matches!(version, 1 | 2)
                && u32::from_le_bytes(data[12..16].try_into()?) == HEADER as u32,
            "Unsupported archive version"
        );
        let at = usize::try_from(u64::from_le_bytes(data[16..24].try_into()?))?;
        let len = usize::try_from(u64::from_le_bytes(data[24..32].try_into()?))?;
        ensure!(
            at >= HEADER && len <= 64 << 20 && at.checked_add(len) == Some(data.len()),
            "Invalid archive index range"
        );
        let bytes = &data[at..];
        ensure!(
            hash(bytes).as_bytes() == &data[32..96],
            "Archive index checksum mismatch"
        );
        let index: Index = serde_json::from_slice(bytes)?;
        ensure!(
            index.version == version
                && index.format == "CDNG JXL Archive"
                && index.entries.len() <= 1_000_000,
            "Invalid archive index"
        );
        let mut names = HashSet::new();
        let valid = |off: u64, len: usize| -> bool {
            usize::try_from(off)
                .ok()
                .is_some_and(|o| o >= HEADER && o.checked_add(len).is_some_and(|e| e <= at))
        };
        for dir in &index.directories {
            ensure!(
                safe_path(dir) && names.insert(dir.clone()),
                "Invalid/duplicate archive directory"
            );
        }
        for e in &index.entries {
            ensure!(
                safe_path(&e.path) && names.insert(e.path.clone()) && valid(e.offset, e.length),
                "Invalid/duplicate entry or payload range"
            );
            ensure!(e.sha256.len() == 64, "Invalid payload checksum");
            if let Some(f) = &e.frame {
                let pixels = f.width.checked_mul(f.height).context("RAW size overflow")?;
                ensure!(
                    f.width > 0
                        && f.height > 0
                        && f.width <= 65535
                        && f.height <= 65535
                        && f.width % 2 == 0
                        && f.height % 2 == 0
                        && pixels <= 100_000_000
                        && (version == 1 || (8..=16).contains(&f.original_bits))
                        && valid(f.header_offset, f.header_len)
                        && f.header_len <= 64 << 20,
                    "Invalid DNG shape/header"
                );
                ensure!(
                    e.virtual_size == f.header_len as u64 + (pixels * 2) as u64,
                    "Invalid virtual DNG length"
                );
                ensure!(
                    pixels * 2 <= budget,
                    "快取容量不足以容納單張 RAW，至少需要 {} MiB",
                    (pixels * 2).div_ceil(1 << 20)
                );
                ensure!(version == 2 || f.temporal.is_none(), "Temporal frame in a version 1 archive");
            } else {
                ensure!(
                    e.virtual_size == e.length as u64,
                    "Invalid stored entry length"
                );
            }
        }
        let mut cache_keys: Vec<usize> = (0..index.entries.len()).collect();
        let mut by_offset = HashMap::<u64, Vec<usize>>::new();
        let mut offset_counts = HashMap::<u64, usize>::new();
        for (i, e) in index.entries.iter().enumerate() {
            *offset_counts.entry(e.offset).or_default() += 1;
            if e.frame.as_ref().is_some_and(|f| f.temporal.is_some()) {
                by_offset.entry(e.offset).or_default().push(i);
            }
        }
        let mut groups = HashMap::new();
        for (offset, members) in by_offset {
            let first = &index.entries[members[0]];
            let f = first.frame.as_ref().unwrap();
            let t = f.temporal.as_ref().unwrap();
            ensure!((2..=8).contains(&t.count) && members.len() == t.count, "Invalid temporal group count");
            let need = f.width.checked_mul(f.height).and_then(|n| n.checked_mul(2))
                .and_then(|n| n.checked_mul(t.count)).context("Temporal group size overflow")?;
            ensure!(need <= TEMPORAL_GROUP_BYTES, "Temporal group exceeds 192 MiB");
            ensure!(need <= budget, "快取容量不足以容納一組 RAW，至少需要 {} MiB", need.div_ceil(1 << 20));
            let clip = first.path.rsplit_once('/').map_or("", |(p, _)| p);
            let mut ordered = vec![usize::MAX; t.count];
            for &i in &members {
                let e = &index.entries[i];
                let m = e.frame.as_ref().unwrap();
                let mt = m.temporal.as_ref().unwrap();
                ensure!(e.length == first.length && e.sha256 == first.sha256
                    && m.width == f.width && m.height == f.height && m.original_bits == f.original_bits
                    && mt.count == t.count && mt.index < t.count
                    && e.path.rsplit_once('/').map_or("", |(p, _)| p) == clip,
                    "Inconsistent temporal group");
                ensure!(ordered[mt.index] == usize::MAX, "Duplicate temporal frame index");
                ordered[mt.index] = i;
            }
            ensure!(ordered.iter().all(|&i| i != usize::MAX), "Incomplete temporal group");
            ensure!(offset_counts[&offset] == members.len(),
                "Temporal payload shared by an unrelated entry");
            let key = ordered[0];
            for &i in &ordered { cache_keys[i] = key; }
            groups.insert(key, ordered);
        }
        if version == 2 {
            // Only complete temporal groups may share a payload. All other
            // payloads and each frame's metadata occupy disjoint archive spans.
            let mut spans = Vec::new();
            let mut payloads = HashSet::new();
            for (i, e) in index.entries.iter().enumerate() {
                if e.length > 0 && payloads.insert(cache_keys[i]) {
                    spans.push((e.offset as usize, e.offset as usize + e.length));
                }
                if let Some(f) = &e.frame {
                    if f.header_len > 0 { spans.push((f.header_offset as usize, f.header_offset as usize + f.header_len)); }
                }
            }
            spans.sort_unstable();
            ensure!(spans.windows(2).all(|p| p[0].1 <= p[1].0), "Overlapping archive payload/header ranges");
        }
        // No entry may also be the parent of another entry (file/directory collision).
        let files: HashSet<_> = index.entries.iter().map(|e| e.path.as_str()).collect();
        for name in &names {
            let mut parent = name.as_str();
            while let Some((p, _)) = parent.rsplit_once('/') {
                ensure!(!files.contains(p), "File used as directory");
                parent = p;
            }
        }
        let n = index.entries.len();
        Ok(Self {
            index,
            data,
            codec: Mutex::new(None),
            gates: (0..n).map(|_| Mutex::new(())).collect(),
            verified: (0..n).map(|_| AtomicBool::new(false)).collect(),
            cache: Mutex::new(Cache::default()),
            changed: Condvar::new(),
            budget,
            hits: AtomicUsize::new(0),
            misses: AtomicUsize::new(0),
            cache_keys,
            groups,
        })
    }
    fn payload(&self, e: &Entry) -> &[u8] {
        &self.data[e.offset as usize..e.offset as usize + e.length]
    }
    fn header<'a>(&'a self, f: &Frame) -> &'a [u8] {
        &self.data[f.header_offset as usize..f.header_offset as usize + f.header_len]
    }
    pub fn verify_entry(&self, i: usize) -> Result<()> {
        let e = self.index.entries.get(i).context("Missing archive entry")?;
        ensure!(
            hash(self.payload(e)) == e.sha256,
            "Payload checksum mismatch: {}",
            e.path
        );
        if let Some(f) = &e.frame {
            ensure!(
                hash(self.header(f)) == f.header_sha256,
                "DNG header checksum mismatch: {}",
                e.path
            );
        }
        self.verified[i].store(true, Ordering::Release);
        Ok(())
    }
    /// Verify all stored bytes and independently decoded RAW samples. One task
    /// owns an entire shared temporal payload so concurrent cache eviction cannot
    /// repeatedly decode it between member-frame reads. Cache reservations and
    /// leases bound resident decoded samples even when all worker slots are busy.
    pub fn verify_all(&self, workers: usize, cancel: &AtomicBool, progress: impl Fn(Value) + Sync) -> Result<()> {
        cancelled(cancel)?;
        let jobs: Vec<usize> = self.cache_keys.iter().enumerate()
            .filter_map(|(i, &key)| (i == key).then_some(i)).collect();
        let pool = rayon::ThreadPoolBuilder::new().num_threads(workers.clamp(1, 8)).build()?;
        let done = AtomicUsize::new(0);
        let reporting = Mutex::new(());
        pool.install(|| jobs.par_iter().try_for_each(|&i| -> Result<()> {
            cancelled(cancel)?;
            let members = self.groups.get(&i).map(Vec::as_slice).unwrap_or(std::slice::from_ref(&i));
            for &member in members {
                cancelled(cancel)?;
                self.verify_entry(member)?;
            }
            // frame() checks every group's decoded mosaic against the original
            // per-frame hashes before its shared allocation can enter the cache.
            let lease = if self.index.entries[i].frame.is_some() { Some(self.frame(i)?) } else { None };
            cancelled(cancel)?;
            {
                let _report = reporting.lock().map_err(|_| anyhow::anyhow!("Verification progress failed"))?;
                for &member in members {
                    let completed = done.fetch_add(1, Ordering::Relaxed) + 1;
                    progress(json!({"stage":"verify","done":completed,"total":self.index.entries.len(),
                        "name":self.index.entries[member].path}));
                }
            }
            drop(lease);
            Ok(())
        }))?;
        cancelled(cancel)?;
        ensure!(done.load(Ordering::Relaxed) == self.index.entries.len(), "Archive verification is incomplete");
        Ok(())
    }
    fn frame(&self, i: usize) -> Result<Lease<'_>> {
        let key = self.cache_keys[i];
        let _gate = self.gates[key]
            .lock()
            .map_err(|_| anyhow::anyhow!("Frame gate failed"))?;
        let e = &self.index.entries[i];
        let f = e.frame.as_ref().context("Not a RAW frame")?;
        let len = f.width * f.height;
        let start = f.temporal.as_ref().map_or(0, |t| t.index * len);
        let need = len * 2 * f.temporal.as_ref().map_or(1, |t| t.count);
        let mut c = self
            .cache
            .lock()
            .map_err(|_| anyhow::anyhow!("Cache failed"))?;
        c.tick += 1;
        let tick = c.tick;
        if let Some(hit) = c.frames.get_mut(&key) {
            hit.tick = tick;
            self.hits.fetch_add(1, Ordering::Relaxed);
            return Ok(Lease {
                pixels: Some(hit.pixels.clone()),
                start,
                len,
                owner: self,
            });
        }
        loop {
            if c.used + c.reserved + need <= self.budget {
                break;
            }
            if let Some((&key, _)) = c
                .frames
                .iter()
                .filter(|(_, v)| Arc::strong_count(&v.pixels) == 1)
                .min_by_key(|(_, v)| v.tick)
            {
                let old = c.frames.remove(&key).unwrap();
                c.used -= old.pixels.len() * 2;
            } else {
                c = self
                    .changed
                    .wait(c)
                    .map_err(|_| anyhow::anyhow!("Cache wait failed"))?;
            }
        }
        c.reserved += need;
        c.peak = c.peak.max(c.used + c.reserved);
        drop(c);
        self.misses.fetch_add(1, Ordering::Relaxed);
        let decoded = (|| -> Result<Vec<u16>> {
            if let Some(members) = self.groups.get(&key) {
                for &member in members {
                    if !self.verified[member].load(Ordering::Acquire) { self.verify_entry(member)?; }
                }
            } else if !self.verified[i].load(Ordering::Acquire) {
                self.verify_entry(i)?;
            }
            let codec = {
                let mut slot = self
                    .codec
                    .lock()
                    .map_err(|_| anyhow::anyhow!("Codec failed"))?;
                if slot.is_none() {
                    *slot = Some(jxl::Codec::load()?);
                }
                slot.as_ref().unwrap().clone()
            };
            let pixels = if let Some(t) = &f.temporal {
                let pixels = crate::temporal::decode_cube(&codec, self.payload(e), f.width, f.height, t.count, f.original_bits as u32)?;
                ensure!(pixels.len() == len * t.count, "Temporal RAW length changed");
                for (&member, raw) in self.groups[&key].iter().zip(pixels.chunks_exact(len)) {
                    let entry = &self.index.entries[member];
                    ensure!(dng::pixel_hash(raw) == entry.frame.as_ref().unwrap().raw_sha256,
                        "RAW checksum mismatch: {}", entry.path);
                }
                pixels
            } else {
                let mut pixels = if self.index.version == 1 {
                    codec.decode(self.payload(e), f.width, f.height)?
                } else {
                    codec.decode_bits(self.payload(e), f.width, f.height, f.original_bits as u32)?
                };
                jxl::cfa_permute(&mut pixels, f.width, f.height, true)?;
                ensure!(dng::pixel_hash(&pixels) == f.raw_sha256, "RAW checksum mismatch: {}", e.path);
                pixels
            };
            Ok(pixels)
        })();
        let mut c = self
            .cache
            .lock()
            .map_err(|_| anyhow::anyhow!("Cache failed"))?;
        c.reserved -= need;
        self.changed.notify_all();
        let pixels = Arc::new(decoded?);
        c.used += need;
        c.tick += 1;
        let tick = c.tick;
        c.frames.insert(
            key,
            Cached {
                pixels: pixels.clone(),
                tick,
            },
        );
        Ok(Lease {
            pixels: Some(pixels),
            start,
            len,
            owner: self,
        })
    }
    /// Caller-owned destination, arbitrary file ranges, no whole-DNG staging allocation.
    pub fn read_into(&self, i: usize, offset: u64, out: &mut [u8]) -> Result<usize> {
        let e = self.index.entries.get(i).context("Missing archive entry")?;
        if out.is_empty() || offset >= e.virtual_size {
            return Ok(0);
        }
        let n = (e.virtual_size - offset).min(out.len() as u64) as usize;
        let mut at = offset as usize;
        let mut copied = 0;
        if let Some(f) = &e.frame {
            ensure!(
                cfg!(target_endian = "little"),
                "Big-endian host is unsupported"
            );
            if at < f.header_len {
                ensure!(
                    hash(self.header(f)) == f.header_sha256,
                    "DNG header checksum mismatch"
                );
                let k = (f.header_len - at).min(n);
                out[..k].copy_from_slice(&self.header(f)[at..at + k]);
                at += k;
                copied = k;
            }
            if copied < n {
                let lease = self.frame(i)?;
                let pixels = lease.pixels.as_ref().unwrap();
                // Read-only byte view retains the original u16 allocation and alignment.
                let bytes = unsafe {
                    std::slice::from_raw_parts(pixels.as_ptr().add(lease.start).cast::<u8>(), lease.len * 2)
                };
                let raw_at = at - f.header_len;
                out[copied..n].copy_from_slice(&bytes[raw_at..raw_at + n - copied]);
            }
        } else {
            if !self.verified[i].load(Ordering::Acquire) {
                self.verify_entry(i)?;
            }
            out[..n].copy_from_slice(&self.payload(e)[at..at + n]);
        }
        Ok(n)
    }
    pub fn stats(&self) -> Value {
        let c = self.cache.lock().unwrap();
        json!({"cache_bytes":c.used,"reserved_bytes":c.reserved,"peak_bytes":c.peak,"budget_bytes":self.budget,"hits":self.hits.load(Ordering::Relaxed),"decoded_frames":self.misses.load(Ordering::Relaxed),"mount_installed":false,"jxl_backend":"cpu"})
    }
    pub fn export(&self, output: &Path, cancel: &AtomicBool) -> Result<()> {
        cancelled(cancel)?;
        ensure!(fs::symlink_metadata(output).is_err(), "還原資料夾已存在");
        let parent = output
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."))
            .canonicalize()?;
        let target = parent.join(output.file_name().context("Missing destination")?);
        let mut output = crate::output::OutputDirectory::create(&target)?;
        for dir in &self.index.directories {
            cancelled(cancel)?;
            output.create_directories(Path::new(dir))?;
        }
        let mut buffer = vec![0; 1 << 20];
        // Creating a peer on macOS/exFAT can generate its ._ metadata file.
        // Restore opaque AppleDouble entries last so those exact archived bytes
        // survive the ordinary files' creation and closing.
        let mut order: Vec<usize> = (0..self.index.entries.len()).collect();
        order.sort_by_key(|&i| Path::new(&self.index.entries[i].path).file_name()
            .is_some_and(|name| name.as_encoded_bytes().starts_with(b"._")));
        for i in order {
            cancelled(cancel)?;
            let e = &self.index.entries[i];
            output.write_file(Path::new(&e.path), |file| {
                let mut at = 0;
                loop {
                    cancelled(cancel)?;
                    let n = self.read_into(i, at, &mut buffer)?;
                    if n == 0 { break; }
                    file.write_all(&buffer[..n])?;
                    at += n as u64;
                }
                Ok(())
            })?;
        }
        cancelled(cancel)?;
        output.finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn appledouble_dng_names_are_opaque_sidecars() {
        for path in ["frame.dng", "clip/FRAME.DNG", "clip/a._b.dng"] {
            assert!(pack::is_dng_source(Path::new(path)), "{path}");
        }
        for path in ["._frame.dng", "clip/._FRAME.DNG", "clip/audio.wav", "clip/._metadata", "clip/frame.dng.txt"] {
            assert!(!pack::is_dng_source(Path::new(path)), "{path}");
        }
    }
    fn write_test_index(path: &Path, body: &[u8], index: &Index, version: u32) {
        let json = serde_json::to_vec(index).unwrap();
        let mut data = vec![0; HEADER];
        data[..8].copy_from_slice(MAGIC);
        data[8..12].copy_from_slice(&version.to_le_bytes());
        data[12..16].copy_from_slice(&(HEADER as u32).to_le_bytes());
        data[16..24].copy_from_slice(&((HEADER + body.len()) as u64).to_le_bytes());
        data[24..32].copy_from_slice(&(json.len() as u64).to_le_bytes());
        data[32..96].copy_from_slice(hash(&json).as_bytes());
        data.extend(body); data.extend(json);
        fs::write(path, data).unwrap();
    }
    fn temporal_index() -> (Vec<u8>, Index) {
        let body = vec![0; 48];
        let entries = (0..3).map(|i| Entry {
            path: format!("clip/f{i}.dng"), offset: HEADER as u64 + 24, length: 24,
            sha256: hash(&body[24..]), virtual_size: 16,
            frame: Some(Frame { width: 2, height: 2, original_bits: 12,
                raw_sha256: hash(&[i as u8; 8]), header_offset: HEADER as u64 + (i * 8) as u64,
                header_len: 8, header_sha256: hash(&body[..8]),
                temporal: Some(TemporalFrame { count: 3, index: i }) }),
        }).collect();
        (body, Index { format: "CDNG JXL Archive".into(), version: 2, profile: "test".into(),
            libjxl: 0, directories: vec!["clip".into()], entries })
    }
    #[test]
    fn temporal_index_rejects_incomplete_inconsistent_and_oversized_groups() {
        let root = temp(); let path = root.join("group.cdngt");
        let (body, index) = temporal_index();
        write_test_index(&path, &body, &index, 2);
        assert!(Archive::open(&path, 24).is_ok());
        assert!(Archive::open(&path, 23).is_err(), "cache must fit the entire group");
        for case in 0..15 {
            let (_, mut index) = temporal_index();
            match case {
                0 => { index.entries.pop(); }
                1 => index.entries[1].frame.as_mut().unwrap().temporal.as_mut().unwrap().index = 0,
                2 => index.entries[1].frame.as_mut().unwrap().temporal.as_mut().unwrap().index = 3,
                3 => index.entries[1].frame.as_mut().unwrap().temporal.as_mut().unwrap().count = 4,
                4 => index.entries[1].length -= 1,
                5 => index.entries[1].sha256 = "f".repeat(64),
                6 => index.entries[1].frame.as_mut().unwrap().original_bits = 10,
                7 => index.entries[1].path = "other/f1.dng".into(),
                8 => index.entries[1].frame.as_mut().unwrap().temporal = None,
                9 => { index.entries[1].frame.as_mut().unwrap().width = 4; index.entries[1].virtual_size += 8; }
                10 => { for e in &mut index.entries { let f=e.frame.as_mut().unwrap(); f.width=8192;f.height=8192;e.virtual_size=8+8192*8192*2; } }
                11 => { for e in &mut index.entries { e.offset -= 1; } }
                12 => index.entries[1].frame.as_mut().unwrap().header_offset = HEADER as u64,
                13 => index.entries[1].frame.as_mut().unwrap().header_offset = HEADER as u64 + 24,
                14 => index.entries.push(Entry { path:"clip/overlap.wav".into(), offset:HEADER as u64+25,
                    length:2, sha256:hash(&[0;2]), virtual_size:2, frame:None }),
                _ => unreachable!(),
            }
            write_test_index(&path, &body, &index, 2);
            assert!(Archive::open(&path, 1 << 30).is_err(), "case {case}");
        }
        let (_, mut index) = temporal_index(); index.version = 1;
        write_test_index(&path, &body, &index, 1);
        assert!(Archive::open(&path, 24).is_err(), "v1 cannot claim temporal decoding");
        write_test_index(&path, &body, &index, 2);
        assert!(Archive::open(&path, 24).is_err(), "header and index versions must agree");
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn temporal_cache_shares_one_allocation_and_returns_only_the_requested_frame() {
        let root = temp(); let path = root.join("group.cdngt");
        let (body, index) = temporal_index(); write_test_index(&path, &body, &index, 2);
        let archive = Arc::new(Archive::open(&path, 24).unwrap());
        assert_eq!(archive.read_into(0, 0, &mut []).unwrap(), 0);
        assert_eq!(archive.read_into(1, 9, &mut []).unwrap(), 0);
        assert_eq!(archive.stats()["decoded_frames"], 0);
        let pixels: Vec<u16> = (0..12).map(|i| (i * 137 + 9) as u16).collect();
        {
            let mut cache = archive.cache.lock().unwrap();
            cache.used=24; cache.peak=24;
            cache.frames.insert(0, Cached { pixels: Arc::new(pixels.clone()), tick: 0 });
        }
        std::thread::scope(|scope| {
            for i in 0..3 {
                let archive = &archive; let pixels = &pixels;
                scope.spawn(move || {
                    let mut out=[0; 7];
                    assert_eq!(archive.read_into(i, 9, &mut out).unwrap(), 7);
                    let raw: Vec<u8> = pixels[i*4..i*4+4].iter().flat_map(|v| v.to_le_bytes()).collect();
                    assert_eq!(&out, &raw[1..]);
                });
            }
        });
        let cache=archive.cache.lock().unwrap();
        assert_eq!(cache.frames.len(), 1); assert_eq!(cache.used, 24);
        assert_eq!(cache.reserved, 0); drop(cache); drop(archive);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    #[ignore = "Native libjxl integration: requires a compatible libjxl library"]
    fn temporal_archive_native_roundtrip_group_cache_and_corruption() {
        let root=temp(); let source=root.join("source"); fs::create_dir(&source).unwrap();
        let (w,h)=(128usize,128usize);
        let pixels: Vec<u16> = (0..w*h).map(|i| {
            let mut x=i as u32+17; x^=x<<13; x^=x>>17; x^=x<<5; (x&65535) as u16
        }).collect();
        let tags=[(256,4,1,w as u32),(257,4,1,h as u32),(258,3,1,16),
            (259,3,1,1),(262,3,1,32803),(273,4,1,146),(277,3,1,1),
            (278,4,1,h as u32),(279,4,1,(w*h*2) as u32),
            (33421,3,2,2|(2<<16)),(33422,1,4,0x02010100)];
        let mut dng=b"II*\0\x08\0\0\0".to_vec();
        dng.extend((tags.len() as u16).to_le_bytes());
        for (tag,typ,count,value) in tags {
            dng.extend((tag as u16).to_le_bytes()); dng.extend((typ as u16).to_le_bytes());
            dng.extend((count as u32).to_le_bytes()); dng.extend(value.to_le_bytes());
        }
        dng.extend([0;4]); assert_eq!(dng.len(),146);
        dng.extend(pixels.iter().flat_map(|v| v.to_le_bytes()));
        for i in 0..9 { fs::write(source.join(format!("f{i}.dng")), &dng).unwrap(); }
        fs::write(source.join("z.wav"),b"audio").unwrap();
        fs::write(source.join("._f0.dng"),b"AppleDouble opaque metadata").unwrap();
        let output=root.join("frames.cdngt");
        let options=Options { source, output:output.clone(), effort:Effort::Fast, backend:Backend::Cpu,
            workers:1, store:false, verify:true, ram_buffer_bytes:Some(1<<20), excluded_clips:vec![], jxl:false };
        assert!(pack_temporal(&options,&AtomicBool::new(true),|_|{}).is_err());
        assert!(!output.exists());
        pack_temporal(&options,&AtomicBool::new(false),|_|{}).unwrap();
        let archive=Arc::new(Archive::open(&output,w*h*2*8).unwrap());
        assert_eq!(archive.index.version,2);
        let grouped: Vec<usize>=archive.index.entries.iter().enumerate().filter(|(_,e)|
            e.frame.as_ref().is_some_and(|f| f.temporal.is_some())).map(|(i,_)|i).collect();
        assert_eq!(grouped.len(),8,"static frames should use a shared temporal payload");
        std::thread::scope(|scope| {
            for &i in &grouped {
                let archive=&archive; let pixels=&pixels;
                scope.spawn(move||{
                    let mut all=vec![0;archive.index.entries[i].virtual_size as usize];
                    archive.read_into(i,0,&mut all).unwrap();
                    assert_eq!(dng::decode(&all).unwrap(),*pixels);
                });
            }
        });
        assert_eq!(archive.stats()["decoded_frames"],1,"group must decode once under concurrent reads");
        assert_eq!(archive.stats()["peak_bytes"],w*h*2*8);
        let restore=root.join("restored"); archive.export(&restore,&AtomicBool::new(false)).unwrap();
        for i in 0..9 { assert_eq!(dng::decode(&fs::read(restore.join(format!("f{i}.dng"))).unwrap()).unwrap(),pixels); }
        assert_eq!(fs::read(restore.join("z.wav")).unwrap(),b"audio");
        assert_eq!(fs::read(restore.join("._f0.dng")).unwrap(),b"AppleDouble opaque metadata");
        assert!(archive.index.entries.iter().find(|e|e.path=="._f0.dng").unwrap().frame.is_none());
        let at=archive.index.entries[grouped[0]].offset as usize;
        drop(archive);
        for workers in [1,8] {
            let check=Archive::open(&output,w*h*2*8).unwrap();
            let seen=Mutex::new(Vec::new());
            check.verify_all(workers,&AtomicBool::new(false),|event| {
                seen.lock().unwrap().push(event["done"].as_u64().unwrap());
            }).unwrap();
            assert_eq!(check.stats()["decoded_frames"],2,"each unique payload must decode once");
            assert_eq!(check.stats()["reserved_bytes"],0);
            assert!(check.stats()["peak_bytes"].as_u64().unwrap()<= (w*h*2*8) as u64);
            let seen=seen.into_inner().unwrap();
            assert_eq!(seen,(1..=11).collect::<Vec<u64>>());
        }
        // Keep payload hashes valid but corrupt one expected RAW hash: full
        // verification must decode and reject it, releasing its reservation.
        let original=fs::read(&output).unwrap();
        let index_at=u64::from_le_bytes(original[16..24].try_into().unwrap()) as usize;
        let mut index:Index=serde_json::from_slice(&original[index_at..]).unwrap();
        index.entries[grouped[0]].frame.as_mut().unwrap().raw_sha256="f".repeat(64);
        let bad_raw=root.join("bad-raw.cdngt");
        write_test_index(&bad_raw,&original[HEADER..index_at],&index,2);
        let check=Archive::open(&bad_raw,w*h*2*8).unwrap();
        assert!(check.verify_all(8,&AtomicBool::new(false),|_|{}).is_err());
        assert_eq!(check.stats()["reserved_bytes"],0); drop(check);
        let mut bytes=fs::read(&output).unwrap(); bytes[at]^=1;
        let bad=root.join("bad.cdngt"); fs::write(&bad,bytes).unwrap();
        let archive=Archive::open(&bad,w*h*2*8).unwrap();
        let i=grouped[0]; let header_len=archive.index.entries[i].frame.as_ref().unwrap().header_len;
        assert!(archive.read_into(i,header_len as u64,&mut [0;16]).is_err());
        assert!(archive.verify_all(8,&AtomicBool::new(false),|_|{}).is_err());
        assert_eq!(archive.stats()["reserved_bytes"],0);
        drop(archive); fs::remove_dir_all(root).unwrap();
    }
    fn temp() -> PathBuf {
        // tests run in parallel: a counter keeps names unique within the same nanosecond
        static NEXT: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
        let p = std::env::temp_dir().join(format!(
            "cdng-archive-test-{}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&p).unwrap();
        p
    }
    fn stored(path: &Path, mut change: impl FnMut(&mut Index)) {
        let bytes = b"0123456789abcdefghijklmnopqrstuvwxyz";
        let entry = Entry {
            path: "片段/a.txt".into(),
            offset: HEADER as u64,
            length: bytes.len(),
            sha256: hash(bytes),
            virtual_size: bytes.len() as u64,
            frame: None,
        };
        let mut index = Index {
            format: "CDNG JXL Archive".into(),
            version: 1,
            profile: "test".into(),
            libjxl: 0,
            directories: vec!["片段".into()],
            entries: vec![entry],
        };
        change(&mut index);
        let json = serde_json::to_vec(&index).unwrap();
        let mut data = vec![0; HEADER];
        data[..8].copy_from_slice(MAGIC);
        data[8..12].copy_from_slice(&1u32.to_le_bytes());
        data[12..16].copy_from_slice(&(HEADER as u32).to_le_bytes());
        data[16..24].copy_from_slice(&((HEADER + bytes.len()) as u64).to_le_bytes());
        data[24..32].copy_from_slice(&(json.len() as u64).to_le_bytes());
        data[32..96].copy_from_slice(hash(&json).as_bytes());
        data.extend(bytes);
        data.extend(json);
        fs::write(path, data).unwrap();
    }
    #[test]
    fn corrupted_ranges_paths_indexes_and_payloads_are_rejected() {
        let root = temp();
        let path = root.join("a.cdngj");
        for value in [
            "/absolute",
            "../outside",
            "a/../../outside",
            "a\\outside",
            "a:stream",
        ] {
            stored(&path, |i| i.entries[0].path = value.into());
            assert!(Archive::open(&path, 1024).is_err());
        }
        stored(&path, |i| i.entries[0].offset = u64::MAX);
        assert!(Archive::open(&path, 1024).is_err());
        stored(&path, |i| i.entries.push(i.entries[0].clone()));
        assert!(Archive::open(&path, 1024).is_err());
        stored(&path, |i| i.entries[0].path = "片段".into());
        assert!(Archive::open(&path, 1024).is_err());
        stored(&path, |_| {});
        let mut data = fs::read(&path).unwrap();
        *data.last_mut().unwrap() ^= 1;
        fs::write(&path, data).unwrap();
        assert!(Archive::open(&path, 1024).is_err());
        stored(&path, |_| {});
        let mut data = fs::read(&path).unwrap();
        data[HEADER] ^= 1;
        fs::write(&path, data).unwrap();
        let a = Archive::open(&path, 1024).unwrap();
        assert!(a.read_into(0, 0, &mut [0; 8]).is_err());
        drop(a);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn export_preserves_existing_paths_and_removes_failed_extractions() {
        let root=temp(); let path=root.join("input.cdngj"); stored(&path,|_|{});
        let archive=Archive::open(&path,1024).unwrap();
        let destination=root.join("restored");
        assert!(archive.export(&destination,&AtomicBool::new(true)).is_err());
        assert!(!destination.exists());
        archive.export(&destination,&AtomicBool::new(false)).unwrap();
        assert_eq!(fs::read(destination.join("片段/a.txt")).unwrap(),b"0123456789abcdefghijklmnopqrstuvwxyz");
        assert!(archive.export(&destination,&AtomicBool::new(false)).is_err());
        assert_eq!(fs::read(destination.join("片段/a.txt")).unwrap(),b"0123456789abcdefghijklmnopqrstuvwxyz");
        drop(archive);
        fs::remove_dir_all(&destination).unwrap();
        let mut damaged=fs::read(&path).unwrap(); damaged[HEADER]^=1; fs::write(&path,damaged).unwrap();
        let archive=Archive::open(&path,1024).unwrap();
        assert!(archive.export(&destination,&AtomicBool::new(false)).is_err());
        assert!(!destination.exists());
        assert_eq!(fs::read_dir(&root).unwrap().count(),1,"failed extraction left a staging directory");
        drop(archive); fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn export_preserves_opaque_appledouble_for_files_and_directories() {
        let root=temp(); let path=root.join("input.cdngj");
        stored(&path, |index| {
            index.directories=vec!["clip".into()];
            let template=index.entries[0].clone();
            index.entries=["._clip", "clip/._frame.dng", "clip/frame.dng"]
                .into_iter().map(|path| { let mut e=template.clone(); e.path=path.into(); e }).collect();
        });
        let archive=Archive::open(&path,1024).unwrap();
        let destination=root.join("restored");
        archive.export(&destination,&AtomicBool::new(false)).unwrap();
        for name in ["._clip", "clip/._frame.dng", "clip/frame.dng"] {
            assert_eq!(fs::read(destination.join(name)).unwrap(),b"0123456789abcdefghijklmnopqrstuvwxyz");
        }
        drop(archive);fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn parallel_archive_verification_reports_monotonic_counts_and_rejects_corruption() {
        let root=temp(); let path=root.join("input.cdngj");
        stored(&path,|index| {
            let entry=index.entries[0].clone();
            index.entries=(0..32).map(|i| { let mut e=entry.clone();e.path=format!("片段/{i}.txt");e }).collect();
        });
        for workers in [1,8] {
            let archive=Archive::open(&path,1024).unwrap();
            let seen=Mutex::new(Vec::new());
            archive.verify_all(workers,&AtomicBool::new(false),|event| {
                seen.lock().unwrap().push(event["done"].as_u64().unwrap());
            }).unwrap();
            assert_eq!(seen.into_inner().unwrap(),(1..=32).collect::<Vec<u64>>());
            assert!(archive.verified.iter().all(|v|v.load(Ordering::Acquire)));
            assert_eq!(archive.stats()["reserved_bytes"],0);
            assert!(archive.verify_all(workers,&AtomicBool::new(true),|_|panic!("cancelled work reported progress")).is_err());
        }
        let mut bytes=fs::read(&path).unwrap();bytes[HEADER]^=1;fs::write(&path,bytes).unwrap();
        let archive=Archive::open(&path,1024).unwrap();
        assert!(archive.verify_all(8,&AtomicBool::new(false),|_|{}).is_err());
        assert_eq!(archive.stats()["reserved_bytes"],0);
        drop(archive);fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn random_file_and_cross_extent_sector_reads_match_materialized_image() {
        let root = temp();
        let path = root.join("a.cdngj");
        stored(&path, |_| {});
        let a = Arc::new(Archive::open(&path, 1024).unwrap());
        let mut b = [0; 7];
        assert_eq!(a.read_into(0, 9, &mut b).unwrap(), 7);
        assert_eq!(&b, b"9abcdef");
        assert_eq!(a.read_into(0, u64::MAX, &mut b).unwrap(), 0);
        let disk = crate::virtual_disk::VirtualDisk::new(a.clone()).unwrap();
        let output = root.join("disk.iso");
        disk.materialize(&output, &AtomicBool::new(false)).unwrap();
        let reference = fs::read(output).unwrap();
        for at in (0..reference.len()).step_by(137) {
            let mut got = vec![0; 4097];
            let n = disk.read_into(at as u64, &mut got).unwrap();
            assert_eq!(&got[..n], &reference[at..at + n]);
        }
        assert!(disk.read_sectors(u64::MAX, &mut [0; 512]).is_err());
        assert!(disk.read_sectors(0, &mut [0; 513]).is_err());
        assert!(disk.read_sectors(disk.bytes / 512, &mut [0; 512]).is_err());
        assert_eq!(a.stats()["decoded_frames"], 0);
        drop(disk);
        drop(a);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    #[ignore = "Native libjxl integration: set CDNG_JXL_LIBRARY and CDNG_TEST_DNG, then run --ignored"]
    fn native_jxl_roundtrip_single_flight_and_eviction() {
        let input = PathBuf::from(std::env::var_os("CDNG_TEST_DNG").expect("Set CDNG_TEST_DNG"));
        let data = fs::read(input).unwrap();
        let expected = dng::decode(&data).unwrap();
        let (_, _, info) = dng::archive_input(&data).unwrap();
        let root = temp();
        let source = root.join("source");
        fs::create_dir(&source).unwrap();
        for i in 0..3 {
            fs::write(source.join(format!("f{i}.dng")), &data).unwrap();
        }
        fs::write(source.join("audio.wav"), b"audio passthrough").unwrap();
        let output = root.join("test.cdngj");
        let options = Options {
            source,
            output: output.clone(),
            effort: Effort::Fast,
            backend: Backend::Cpu,
            workers: 3,
            store: false,
            verify: true,
            ram_buffer_bytes: Some(1 << 20),
            excluded_clips: vec![],
            jxl: false,
        };
        let cancelled_flag = AtomicBool::new(true);
        assert!(pack(&options, &cancelled_flag, |_| {}).is_err());
        assert!(!output.exists());
        assert!(!fs::read_dir(&root).unwrap().any(|x| {
            x.unwrap()
                .file_name()
                .to_string_lossy()
                .ends_with(".partial")
        }));
        pack(&options, &AtomicBool::new(false), |_| {}).unwrap();
        for workers in [1, 8] {
            let check = Archive::open(&output, expected.len() * 2).unwrap();
            check.verify_all(workers, &AtomicBool::new(false), |_| {}).unwrap();
            assert_eq!(check.stats()["decoded_frames"], 3);
            assert_eq!(check.stats()["reserved_bytes"], 0);
            assert!(check.stats()["peak_bytes"].as_u64().unwrap() <= expected.len() as u64 * 2);
        }
        let a = Arc::new(Archive::open(&output, expected.len() * 2).unwrap());
        let i = a
            .index
            .entries
            .iter()
            .position(|e| e.frame.is_some())
            .unwrap();
        let frame = a.index.entries[i].frame.as_ref().unwrap();
        let mut head = vec![0; frame.header_len];
        a.read_into(i, 0, &mut head).unwrap();
        assert_eq!(a.stats()["decoded_frames"], 0);
        let raw_at = frame.header_len as u64;
        std::thread::scope(|scope| {
            for _ in 0..16 {
                let a = &a;
                let expected = &expected;
                scope.spawn(move || {
                    let mut bytes = [0; 32];
                    assert_eq!(a.read_into(i, raw_at + 1, &mut bytes).unwrap(), 32);
                    let raw: Vec<_> = expected.iter().flat_map(|v| v.to_le_bytes()).collect();
                    assert_eq!(&bytes, &raw[1..33]);
                });
            }
        });
        assert_eq!(a.stats()["decoded_frames"], 1);
        let mut file = vec![0; a.index.entries[i].virtual_size as usize];
        a.read_into(i, 0, &mut file).unwrap();
        assert_eq!(dng::decode(&file).unwrap(), expected);
        for (idx, e) in a.index.entries.iter().enumerate() {
            if let Some(f) = &e.frame {
                a.read_into(idx, f.header_len as u64, &mut [0; 32]).unwrap();
            }
        }
        assert!(a.stats()["peak_bytes"].as_u64().unwrap() <= expected.len() as u64 * 2);
        assert!(Archive::open(&output, expected.len() * 2 - 1).is_err());
        drop(a);
        let mut damaged = fs::read(&output).unwrap();
        let a = Archive::open(&output, expected.len() * 2).unwrap();
        let i = a
            .index
            .entries
            .iter()
            .position(|e| e.frame.is_some())
            .unwrap();
        let e = &a.index.entries[i];
        let at = e.frame.as_ref().unwrap().header_len as u64;
        damaged[e.offset as usize + e.length / 2] ^= 1;
        drop(a);
        let bad = root.join("bad.cdngj");
        fs::write(&bad, damaged).unwrap();
        let a = Archive::open(&bad, expected.len() * 2).unwrap();
        assert!(a.read_into(i, at, &mut [0; 32]).is_err());
        assert_eq!(a.stats()["reserved_bytes"], 0);
        drop(a);
        let _ = info;
        fs::remove_dir_all(root).unwrap();
    }
}
