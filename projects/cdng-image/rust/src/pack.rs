use crate::{
    Backend, Effort, cancelled, dng,
    gpu::Gpu,
    hash,
    iso::{Iso, Stored},
};
use anyhow::{Context, Result, ensure};
use rayon::prelude::*;
use serde::Serialize;
use serde_json::{Value, json};
use crate::digest::Sha256;
use std::{
    collections::{BTreeMap, HashSet},
    fs::{self, File, Metadata},
    io::{Cursor, Read, Seek, SeekFrom},
    path::{Path, PathBuf},
    sync::atomic::AtomicBool,
    time::{Instant, SystemTime, UNIX_EPOCH},
};

const MANIFEST: &str = "_CDNG_IMAGE_MANIFEST.json";

pub(crate) enum Work {
    Compressed(Vec<u8>, dng::Info, String, String),
    Copy,
}

/// A file on its way to the Metal JPEG XL coder: a DNG read as planes (with the source
/// digest), or anything already finished.
pub(crate) enum Staged {
    Frame(dng::JxlFrame, String),
    Ready(Work),
}

/// Metal JPEG XL packing. This thread groups frames by clip and size into batches and
/// codes them (each clip's model is learnt from its first batch); a second thread decodes
/// every coded batch again on the GPU, compares it with the planes, builds the DNGs and
/// hands them to the writer. The two overlap on the GPU (the decoder's per-frame parsing
/// leaves it mostly idle).
#[cfg(target_os = "macos")]
fn metal_jxl_coder<'a>(
    input: &crate::ram::Queue<(&'a Item, Result<Staged>)>,
    output: &crate::ram::Queue<(&'a Item, Result<Work>)>,
    cancel: &AtomicBool,
    stop: &AtomicBool,
    progress: &(impl Fn(Value) + Sync),
) {
    use jxl_metal::{decode::Decoder, encode::{Encoder, Model}};
    use std::collections::HashMap;
    const BATCH: usize = 16;
    type Key = (String, usize, usize, usize); // clip folder, width, height, bits
    type Frames<'a> = Vec<(&'a Item, dng::JxlFrame, String)>;
    enum Msg<'a> {
        Coded(Frames<'a>, Result<Vec<Vec<u8>>>),
        Done(&'a Item, Result<Work>),
    }
    let profile = std::env::var("CDNG_PROFILE_STAGES").is_ok();
    let initializing = std::sync::atomic::AtomicUsize::new(2);
    let activity_lock = std::sync::Mutex::new(());
    // Activity messages have no done/total: preparation and GPU work must not
    // advance the count of files actually written and checked by the writer.
    let activity = |phase: &str, component: &str, name: &str, frames: usize| {
        // Initialization can overlap encoding. Keep its message until both
        // codecs are ready, and serialize the final ready event with subsequent
        // activity so it cannot overwrite a newer encode/verify message.
        let _lock = activity_lock.lock().unwrap();
        if phase == "ready" {
            if initializing.fetch_sub(1, std::sync::atomic::Ordering::Relaxed) != 1 {
                return;
            }
        } else if phase != "initialize" && initializing.load(std::sync::atomic::Ordering::Relaxed) != 0 {
            return;
        }
        progress(json!({"stage":"codec","codec":"jpeg-xl","phase":phase,
            "component":component,"name":name,"frames":frames}));
    };
    let send = |item: &'a Item, r: Result<Work>| {
        let bytes = match &r {
            Ok(Work::Compressed(d, ..)) => d.capacity() + 512,
            _ => 512,
        };
        if !output.push((item, r), bytes) {
            stop.store(true, std::sync::atomic::Ordering::Relaxed);
        }
    };
    std::thread::scope(|scope| {
        let (tx, rx) = std::sync::mpsc::sync_channel::<Msg<'a>>(2);
        let send = &send;
        let activity = &activity;
        let verifier = scope.spawn(move || {
            activity("initialize", "decoder", "Preparing JPEG XL… First run may take longer.", 0);
            let init = Instant::now();
            let dec = cancelled(cancel).and_then(|_| Decoder::new()).and_then(|decoder| {
                cancelled(cancel)?;
                Ok(decoder)
            });
            let decoder_init_s = init.elapsed().as_secs_f64();
            activity("ready", "decoder", "Preparing JPEG XL frames…", 0);
            let mut decode_s = 0.;
            for msg in rx {
                match msg {
                    Msg::Done(item, r) => send(item, r),
                    Msg::Coded(batch, streams) => {
                        let t = Instant::now();
                        let checked = streams.and_then(|streams| {
                            cancelled(cancel)?;
                            let dec = dec.as_ref().map_err(|e| anyhow::anyhow!("Metal JPEG XL: {e:#}"))?;
                            activity("verify", "decoder", "Checking JPEG XL RAW samples…", batch.len());
                            let refs: Vec<&[u8]> = streams.iter().map(|s| s.as_slice()).collect();
                            let mut bad = None;
                            dec.decode_with(&refs, |i, w, h, px| {
                                let f = &batch[i].1;
                                if bad.is_none() && (w != f.width || h != f.height || px != f.planes.as_slice()) {
                                    bad = Some(i);
                                }
                            })?;
                            cancelled(cancel)?;
                            if let Some(i) = bad {
                                anyhow::bail!("JPEG XL changed RAW samples: {}", batch[i].0.relative);
                            }
                            Ok(streams)
                        });
                        decode_s += t.elapsed().as_secs_f64();
                        match checked {
                            Ok(streams) => {
                                for ((item, f, digest), s) in batch.into_iter().zip(streams) {
                                    let (out, info) = dng::jxl_dng(&f, &s, None, "metal-jxl-decode", Backend::Metal);
                                    let r = check(item).map(|_| {
                                        let out_digest = hash(&out);
                                        Work::Compressed(out, info, digest, out_digest)
                                    });
                                    send(item, r);
                                }
                            }
                            Err(e) => {
                                for (item, ..) in batch {
                                    send(item, Err(anyhow::anyhow!("無法壓縮 {}: {e:#}", item.relative)));
                                }
                            }
                        }
                    }
                }
            }
            (decode_s, decoder_init_s)
        });

        activity("initialize", "encoder", "Preparing JPEG XL… First run may take longer.", 0);
        let init = Instant::now();
        let enc = cancelled(cancel).and_then(|_| Encoder::new()).and_then(|encoder| {
            cancelled(cancel)?;
            Ok(encoder)
        });
        let encoder_init_s = init.elapsed().as_secs_f64();
        activity("ready", "encoder", "Preparing JPEG XL frames…", 0);
        let mut models: HashMap<Key, Model> = HashMap::new();
        let mut pending: HashMap<Key, Frames<'a>> = HashMap::new();
        let (mut wait_s, mut code_s) = (0., 0.);
        let mut code = |key: &Key, batch: Frames<'a>| -> Msg<'a> {
            let t = Instant::now();
            let streams = (|| -> Result<Vec<Vec<u8>>> {
                cancelled(cancel)?;
                let enc = enc.as_ref().map_err(|e| anyhow::anyhow!("Metal JPEG XL: {e:#}"))?;
                let (w, h, bits) = (key.1, key.2, key.3);
                if !models.contains_key(key) {
                    activity("learn", "encoder", "Analyzing clip for JPEG XL compression…", batch.len());
                    models.insert(key.clone(), enc.learn(&batch[0].1.planes, w, h)?);
                    cancelled(cancel)?;
                }
                let planes: Vec<&[u16]> = batch.iter().map(|b| b.1.planes.as_slice()).collect();
                activity("encode", "encoder", "Compressing JPEG XL frames…", batch.len());
                let streams = enc.encode(&models[key], &planes, w, h, bits as u32)?.0;
                cancelled(cancel)?;
                Ok(streams)
            })();
            code_s += t.elapsed().as_secs_f64();
            Msg::Coded(batch, streams)
        };
        let mut waited = Instant::now();
        while let Some((item, staged)) = input.pop() {
            wait_s += waited.elapsed().as_secs_f64();
            if stop.load(std::sync::atomic::Ordering::Relaxed) {
                break;
            }
            let msg = match staged {
                Ok(Staged::Frame(f, digest)) => {
                    let clip = item.relative.rsplit_once('/').map_or("", |(d, _)| d).to_string();
                    let key = (clip, f.width, f.height, f.bits);
                    let list = pending.entry(key.clone()).or_default();
                    list.push((item, f, digest));
                    if list.len() < BATCH {
                        waited = Instant::now();
                        continue;
                    }
                    let batch = pending.remove(&key).unwrap();
                    code(&key, batch)
                }
                Ok(Staged::Ready(work)) => Msg::Done(item, Ok(work)),
                Err(e) => Msg::Done(item, Err(e)),
            };
            if tx.send(msg).is_err() {
                break;
            }
            waited = Instant::now();
        }
        for (key, batch) in pending.drain().collect::<Vec<_>>() {
            if tx.send(code(&key, batch)).is_err() {
                break;
            }
        }
        drop(tx);
        let (decode_s, decoder_init_s) = verifier.join().unwrap_or((0., 0.));
        if profile {
            eprintln!("CDNG_METAL_JXL wait_s={wait_s:.2} code_s={code_s:.2} verify_s={decode_s:.2} encoder_init_s={encoder_init_s:.2} decoder_init_s={decoder_init_s:.2}");
        }
    });
}
#[cfg(target_os = "macos")]
fn sysctl_u64(name: &str) -> Option<u64> {
    unsafe extern "C" {
        fn sysctlbyname(
            name: *const std::ffi::c_char,
            oldp: *mut std::ffi::c_void,
            oldlenp: *mut usize,
            newp: *mut std::ffi::c_void,
            newlen: usize,
        ) -> i32;
    }
    let name = std::ffi::CString::new(name).ok()?;
    let mut buf = [0u8; 8];
    let mut len = buf.len();
    let ok = unsafe {
        sysctlbyname(name.as_ptr(), buf.as_mut_ptr().cast(), &mut len, std::ptr::null_mut(), 0)
    } == 0;
    match (ok, len) {
        (true, 4) => Some(u32::from_ne_bytes(buf[..4].try_into().unwrap()) as u64),
        (true, 8) => Some(u64::from_ne_bytes(buf)),
        _ => None,
    }
}

/// Worker count for this machine. LJ92 on a GPU backend is limited by the GPU queue:
/// one worker per performance core keeps it fed (on a 10-core M1 Max, 8 workers reach
/// 135 frames/s while 4 reach 55 and 16 add nothing). CPU encoders (LJ92 on CPU,
/// JPEG XL) use every core. Each worker holds a few frames, so RAM caps the count.
pub fn auto_workers(backend: Backend, jxl: bool) -> usize {
    let logical = std::thread::available_parallelism().map_or(4, usize::from);
    #[cfg(target_os = "macos")]
    let (performance, ram) = (
        sysctl_u64("hw.perflevel0.physicalcpu").map_or(logical, |n| n as usize),
        sysctl_u64("hw.memsize"),
    );
    #[cfg(not(target_os = "macos"))]
    let (performance, ram) = (logical, None::<u64>);
    let wanted = if !jxl && backend != Backend::Cpu { performance } else { logical };
    let ram_cap = ram.map_or(32, |bytes| (bytes / (512 << 20)) as usize);
    wanted.min(ram_cap).clamp(1, 32)
}
#[derive(Clone, PartialEq, Eq)]
pub(crate) struct Fingerprint {
    pub(crate) length: u64,
    modified: SystemTime,
    identity: (u64, u64),
}
pub(crate) fn fingerprint(m: &Metadata) -> Result<Fingerprint> {
    #[cfg(unix)]
    let identity = {
        use std::os::unix::fs::MetadataExt;
        (m.dev(), m.ino())
    };
    #[cfg(not(unix))]
    let identity = (0, 0);
    Ok(Fingerprint {
        length: m.len(),
        modified: m.modified()?,
        identity,
    })
}
#[derive(Clone, PartialEq, Eq)]
pub(crate) struct Item {
    pub(crate) relative: String,
    pub(crate) path: PathBuf,
    pub(crate) dir: bool,
    pub(crate) stamp: Fingerprint,
}
pub(crate) fn inventory(source: &Path) -> Result<Vec<Item>> {
    fn visit(source: &Path, directory: &Path, result: &mut Vec<Item>) -> Result<()> {
        let mut children: Vec<_> = fs::read_dir(directory)?
            .map(|p| p.map(|d| d.path()))
            .collect::<std::io::Result<_>>()?;
        children.sort();
        for path in children {
            let meta = fs::symlink_metadata(&path)?;
            ensure!(
                meta.is_file() || meta.is_dir(),
                "不支援連結或特殊檔案：{}",
                path.display()
            );
            let relative = path
                .strip_prefix(source)?
                .to_str()
                .context("Non-Unicode filename")?
                .replace('\\', "/");
            ensure!(
                relative.to_lowercase() != MANIFEST.to_lowercase(),
                "Source contains reserved manifest name"
            );
            result.push(Item {
                relative,
                path: path.clone(),
                dir: meta.is_dir(),
                stamp: fingerprint(&meta)?,
            });
            if meta.is_dir() {
                visit(source, &path, result)?;
            }
        }
        Ok(())
    }
    let mut result = Vec::new();
    visit(source, source, &mut result)?;
    Ok(result)
}
pub(crate) fn check(item: &Item) -> Result<()> {
    let m = fs::symlink_metadata(&item.path)?;
    ensure!(
        !m.file_type().is_symlink() && fingerprint(&m)? == item.stamp,
        "Source changed: {}",
        item.relative
    );
    Ok(())
}

#[derive(Clone, Debug)]
pub struct Clip {
    pub relative: String,
    pub frames: Vec<PathBuf>,
    pub bytes: u64,
}
pub(crate) fn is_dng_source(path: &Path) -> bool {
    // Preserve macOS AppleDouble metadata as opaque sidecars on all backends;
    // its copied extension does not make it a RAW frame or preview candidate.
    path.extension().is_some_and(|e| e.eq_ignore_ascii_case("dng"))
        && path.file_name().is_some_and(|name| !name.as_encoded_bytes().starts_with(b"._"))
}
fn groups(items: &[Item]) -> BTreeMap<String, Clip> {
    let mut clips = BTreeMap::<String, Clip>::new();
    for item in items.iter().filter(|i| {
        !i.dir && is_dng_source(&i.path)
    }) {
        let parent = item
            .relative
            .rsplit_once('/')
            .map_or("", |(p, _)| p)
            .to_owned();
        let clip = clips.entry(parent.clone()).or_insert_with(|| Clip {
            relative: parent,
            frames: Vec::new(),
            bytes: 0,
        });
        clip.frames.push(item.path.clone());
        clip.bytes += item.stamp.length;
    }
    clips
}
pub fn list_clips(source: &Path) -> Result<Vec<Clip>> {
    Ok(groups(&inventory(&source.canonicalize()?)?)
        .into_values()
        .collect())
}
pub(crate) fn select_items(items: Vec<Item>, excluded: &[String]) -> Result<Vec<Item>> {
    if excluded.is_empty() {
        return Ok(items);
    }
    let clips = groups(&items);
    let excluded: HashSet<&str> = excluded.iter().map(String::as_str).collect();
    for folder in &excluded {
        ensure!(
            clips.contains_key(*folder),
            "排除清單中的片段已變更，請重新讀取：{folder}"
        );
    }
    fn owner<'a>(
        relative: &'a str,
        is_dir: bool,
        clips: &BTreeMap<String, Clip>,
    ) -> Option<&'a str> {
        let mut path = if is_dir {
            relative
        } else {
            relative.rsplit_once('/').map_or("", |(p, _)| p)
        };
        loop {
            if clips.contains_key(path) {
                return Some(path);
            }
            if path.is_empty() {
                return None;
            }
            path = path.rsplit_once('/').map_or("", |(p, _)| p);
        }
    }
    let keep_file =
        |i: &Item| !owner(&i.relative, false, &clips).is_some_and(|group| excluded.contains(group));
    let mut parents = HashSet::new();
    for item in items.iter().filter(|i| !i.dir && keep_file(i)) {
        let mut path = item.relative.as_str();
        while let Some((parent, _)) = path.rsplit_once('/') {
            parents.insert(parent.to_owned());
            path = parent;
        }
    }
    Ok(items
        .into_iter()
        .filter(|i| {
            if i.dir {
                parents.contains(&i.relative)
                    || !owner(&i.relative, true, &clips).is_some_and(|g| excluded.contains(g))
            } else {
                keep_file(i)
            }
        })
        .collect())
}
#[derive(Clone)]
pub struct Options {
    pub source: PathBuf,
    pub output: PathBuf,
    pub effort: Effort,
    pub backend: Backend,
    pub workers: usize,
    pub store: bool,
    pub verify: bool,
    pub ram_buffer_bytes: Option<usize>,
    pub excluded_clips: Vec<String>,
    /// JPEG XL DNGs (DNG 1.7.1) instead of lossless JPEG
    pub jxl: bool,
}
#[derive(Serialize, Clone)]
pub struct Summary {
    pub output_format: &'static str,
    pub output: PathBuf,
    pub source_bytes: u64,
    pub image_bytes: u64,
    pub files: usize,
    pub compressed_files: usize,
    pub seconds: f64,
    pub backend: Backend,
    pub effort: Effort,
    pub workers: usize,
    pub checksums_verified: bool,
    pub raw_verification: &'static str,
    pub ram_buffer_bytes: usize,
    pub ram_peak_bytes: usize,
    pub iso_write_seconds: f64,
    pub writer_wait_seconds: f64,
    /// Serial readback duration, or only the final wait when readback overlaps
    /// compression (the macOS default; CDNG_PIPELINED_VERIFY=0 disables it). Total `seconds`
    /// always includes all readback work and its successful completion.
    pub image_check_seconds: f64,
    pub image_check_pipelined: bool,
    pub dmg_finalize_seconds: f64,
    pub dmg_checksum_streamed: bool,
    pub engine: &'static str,
}
#[derive(Serialize)]
struct Record {
    path: String,
    source_size: u64,
    source_sha256: String,
    #[serde(flatten)]
    stored: Stored,
    #[serde(flatten)]
    raw: Option<dng::Info>,
}
pub(crate) struct Partial(pub(crate) PathBuf);
impl Drop for Partial {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn verify_image<F: Fn(Value) + Sync>(
    path: &Path,
    files: &[(&str, &Stored)],
    pool: &rayon::ThreadPool,
    workers: usize,
    ram_budget: usize,
    cancel: &AtomicBool,
    progress: &F,
) -> Result<()> {
    let queue: crate::ram::Queue<(&str, &Stored, Vec<u8>)> =
        crate::ram::Queue::new(ram_budget.min(128 << 20));
    let done = std::sync::Mutex::new(0usize);
    let checked = |name: &str, stored: &Stored, digest: String| -> Result<()> {
        ensure!(digest == stored.sha256, "映像檔校驗失敗：{name}");
        let mut n = done.lock().unwrap();
        *n += 1;
        progress(json!({"stage":"verify","done":*n,"total":files.len(),"name":name}));
        Ok(())
    };
    std::thread::scope(|scope| -> Result<()> {
        let q = &queue;
        let checked = &checked;
        let worker = scope.spawn(move || {
            let _completion = q.producer();
            pool.install(|| {
                (0..workers.min(8))
                    .into_par_iter()
                    .try_for_each(|_| -> Result<()> {
                        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                            while let Some((name, stored, bytes)) = q.pop() {
                                cancelled(cancel)?;
                                checked(name, stored, hash(&bytes))?;
                            }
                            Ok(())
                        }))
                        .unwrap_or_else(|_| Err(anyhow::anyhow!("映像檔核對工作發生錯誤")));
                        if result.is_err() {
                            q.abort();
                        }
                        result
                    })
            })
        });
        let reader = (|| -> Result<()> {
            let _completion = queue.producer();
            let mut input = File::open(path)?;
            let mut buffer = vec![0; 1024 * 1024];
            // Keep disk reads sequential. Independent file hashes run in the
            // CPU pool while bounded RAM supplies the next files.
            for &(name, stored) in files {
                cancelled(cancel)?;
                input.seek(SeekFrom::Start(u64::from(stored.extent) * 2048))?;
                if stored.size <= 32 << 20 {
                    let mut bytes = vec![0; stored.size as usize];
                    input.read_exact(&mut bytes)?;
                    let cost = bytes.capacity() + 128;
                    ensure!(queue.push((name, stored, bytes), cost), "映像檔核對已中止");
                } else {
                    // Large sidecars use a fixed buffer rather than allocating
                    // a whole multi-gigabyte file in memory.
                    let mut remaining = stored.size;
                    let mut digest = Sha256::new();
                    while remaining > 0 {
                        cancelled(cancel)?;
                        let n = (remaining as usize).min(buffer.len());
                        input.read_exact(&mut buffer[..n])?;
                        digest.update(&buffer[..n]);
                        remaining -= n as u64;
                    }
                    checked(name, stored, format!("{:x}", digest.finalize()))?;
                }
            }
            Ok(())
        })();
        if reader.is_err() {
            queue.abort();
        } else {
            queue.finish();
        }
        worker
            .join()
            .map_err(|_| anyhow::anyhow!("映像檔核對工作發生錯誤"))??;
        reader
    })?;
    ensure!(*done.lock().unwrap() == files.len(), "映像檔核對尚未完成");
    Ok(())
}

// Unix positional reads do not move the shared cursor of a cloned descriptor.
// Windows seek_read *does* move its cursor, so use an independently opened handle
// to the same private partial path there, exactly as the serial verifier does.
fn readback_handle(file: &File, path: &Path) -> Result<File> {
    #[cfg(unix)]
    { let _ = path; Ok(file.try_clone()?) }
    #[cfg(not(unix))]
    { let _ = file; Ok(File::open(path)?) }
}

// Payloads are immutable after Iso::add returns: final ISO metadata patches
// touch only the reserved prefix. The platform-specific handle above prevents
// these reads from changing the active writer's cursor.
fn readback_exact_at(file: &File, mut bytes: &mut [u8], mut offset: u64) -> Result<()> {
    while !bytes.is_empty() {
        #[cfg(unix)]
        let read = {
            use std::os::unix::fs::FileExt;
            file.read_at(bytes, offset)
        };
        #[cfg(windows)]
        let read = {
            use std::os::windows::fs::FileExt;
            file.seek_read(bytes, offset)
        };
        #[cfg(not(any(unix, windows)))]
        let read: std::io::Result<usize> = Err(std::io::ErrorKind::Unsupported.into());
        match read {
            Ok(0) => return Err(std::io::Error::from(std::io::ErrorKind::UnexpectedEof).into()),
            Ok(n) => {
                offset = offset.checked_add(n as u64).context("Readback offset overflow")?;
                bytes = &mut bytes[n..];
            }
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e.into()),
        }
    }
    Ok(())
}

fn pipelined_image_check(
    file: File,
    queue: &crate::ram::Queue<(String, Stored)>,
    cancel: &AtomicBool,
    checked: &std::sync::atomic::AtomicUsize,
    mut completed: impl FnMut(usize, &str),
) -> Result<()> {
    // Queue entries contain only offsets, sizes, hashes and names. Large
    // sidecars use the same fixed buffer as ordinary frames.
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> Result<()> {
        let mut buffer = vec![0; 1 << 20];
        while let Some((name, stored)) = queue.pop() {
            cancelled(cancel)?;
            let mut at = u64::from(stored.extent) * 2048;
            let mut remaining = stored.size;
            let mut digest = Sha256::new();
            while remaining > 0 {
                cancelled(cancel)?;
                let n = remaining.min(buffer.len() as u64) as usize;
                readback_exact_at(&file, &mut buffer[..n], at)
                    .with_context(|| format!("無法讀回映像檔：{name}"))?;
                digest.update(&buffer[..n]);
                remaining -= n as u64;
                at += n as u64;
            }
            ensure!(format!("{:x}", digest.finalize()) == stored.sha256, "映像檔校驗失敗：{name}");
            let done = checked.fetch_add(1, std::sync::atomic::Ordering::Relaxed) + 1;
            completed(done, &name);
        }
        cancelled(cancel)?;
        Ok(())
    })).unwrap_or_else(|_| Err(anyhow::anyhow!("映像檔核對工作發生錯誤")));
    if result.is_err() {
        // Release a writer waiting for metadata queue space on every worker
        // failure, including a panic in the reporting callback.
        queue.abort();
    }
    result
}

fn queue_image_check(queue: &crate::ram::Queue<(String, Stored)>, name: &str, stored: &Stored) -> Result<()> {
    let name = name.to_owned();
    let stored = stored.clone();
    let cost = name.capacity().saturating_add(stored.sha256.capacity()).saturating_add(128);
    ensure!(queue.push((name, stored), cost), "映像檔核對已中止");
    Ok(())
}

fn worker_priority() {
    #[cfg(target_os = "macos")]
    if std::env::var_os("CDNG_USER_INITIATED").is_some_and(|v| v == "1") {
        unsafe extern "C" {
            fn pthread_set_qos_class_self_np(class: u32, relative_priority: i32) -> i32;
        }
        // QOS_CLASS_USER_INITIATED from the macOS SDK. This applies only to
        // this job's worker, which terminates when its Rayon pool is dropped.
        let result = unsafe { pthread_set_qos_class_self_np(0x19, 0) };
        if result != 0 { eprintln!("Unable to set compression worker priority: {result}"); }
    }
}

pub(crate) fn publish(from: &Path, to: &Path) -> Result<()> {
    crate::output::publish(from, to)?;
    Ok(())
}

pub fn pack(
    options: &Options,
    cancel: &AtomicBool,
    progress: impl Fn(Value) + Sync,
) -> Result<Summary> {
    let pipeline = std::env::var_os("CDNG_PIPELINED_VERIFY")
        .map_or(cfg!(target_os = "macos"), |v| v == "1");
    pack_with_verification_mode(options, cancel, progress, pipeline)
}

fn pack_with_verification_mode(
    options: &Options,
    cancel: &AtomicBool,
    progress: impl Fn(Value) + Sync,
    pipeline_requested: bool,
) -> Result<Summary> {
    if options.output.extension().is_some_and(|e| e.eq_ignore_ascii_case("cdngt")) {
        return crate::archive::pack_temporal(options, cancel, progress);
    }
    if options
        .output
        .extension()
        .is_some_and(|e| e.eq_ignore_ascii_case("cdngj"))
    {
        return crate::archive::pack(options, cancel, progress);
    }
    let started = Instant::now();
    let source = options.source.canonicalize()?;
    ensure!(source.is_dir(), "請選擇素材資料夾");
    ensure!(
        options
            .output
            .extension()
            .is_some_and(|e| e.eq_ignore_ascii_case("iso") || e.eq_ignore_ascii_case("dmg")),
        "Output must end in .dmg, .cdngj, .cdngt or .iso"
    );
    ensure!(
        fs::symlink_metadata(&options.output).is_err(),
        "映像檔已存在；請選擇新的檔名"
    );
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
            .context("Invalid output filename")?,
    );
    ensure!(!output.starts_with(&source), "映像檔需存放在素材資料夾之外");
    ensure!(
        (1..=32).contains(&options.workers),
        "Worker count must be 1–32"
    );
    // JPEG XL on macOS: workers only read DNGs, one thread codes batches on the GPU
    // (`--backend cpu` keeps libjxl on the CPU)
    let metal_jxl = cfg!(target_os = "macos") && options.jxl && options.backend != Backend::Cpu;
    let codec = if options.jxl && !metal_jxl { Some(crate::jxl::Codec::load()?) } else { None };
    let gpu = if options.backend == Backend::Cpu
        || options.jxl
        || options.store
        || (options.effort == crate::Effort::Fast && !Gpu::entropy_requested(options.backend))
    {
        None
    } else {
        Some(Gpu::new(options.backend)?)
    };
    let items = select_items(inventory(&source)?, &options.excluded_clips)?;
    let files: Vec<_> = items.iter().filter(|i| !i.dir).collect();
    for file in &files {
        ensure!(
            file.stamp.length <= u32::MAX as u64,
            "單一檔案超過 4 GiB：{}",
            file.relative
        );
    }
    ensure!(!files.is_empty(), "素材資料夾是空的");
    cancelled(cancel)?;
    let source_bytes = files.iter().map(|i| i.stamp.length).sum();
    let (partial, file) = crate::output::OutputFile::create(&output)?;
    let mut paths: Vec<_> = items
        .iter()
        .map(|i| {
            (
                i.relative.clone(),
                i.dir,
                i.stamp
                    .modified
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs(),
            )
        })
        .collect();
    paths.push((
        MANIFEST.into(),
        false,
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs(),
    ));
    let volume: String = source
        .file_name()
        .unwrap_or_default()
        .to_string_lossy()
        .chars()
        .take(16)
        .map(|c| {
            if c.is_ascii_alphanumeric() {
                c.to_ascii_uppercase()
            } else {
                '_'
            }
        })
        .collect();
    let is_dmg = output.extension().is_some_and(|e| e.eq_ignore_ascii_case("dmg"));
    let pipelined_verify = options.verify && cfg!(any(unix, windows)) && pipeline_requested;
    let readback_file = if pipelined_verify { Some(readback_handle(&file, partial.path())?) } else { None };
    let mut iso = Iso::new(file, &paths, &volume)?;
    if is_dmg { iso.enable_checksum()?; }
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(options.workers)
        .start_handler(|_| worker_priority())
        .build()?;
    let mut records = Vec::new();
    let mut compressed_files = 0;
    let mut iso_write_seconds = 0.;
    let mut writer_wait_seconds = 0.;
    let prepare = |item: &&Item| -> Result<Work> {
        cancelled(cancel)?;
        check(item)?;
        if !options.store && is_dng_source(&item.path) {
            let input = File::open(&item.path)?;
            ensure!(
                fingerprint(&input.metadata()?)? == item.stamp,
                "Source changed"
            );
            // Borrow immutable source pages; avoid a complete file-sized read buffer.
            let bytes = unsafe { memmap2::MmapOptions::new().map(&input)? };
            ensure!(
                fingerprint(&input.metadata()?)? == item.stamp,
                "Source changed"
            );
            let (out, info, digest) = match &codec {
                Some(codec) => {
                    let digest = hash(&bytes);
                    dng::compress_jxl(&bytes, options.effort, codec, cancel)
                        .map(|(out, info)| (out, info, digest))
                },
                None => dng::compress_with_source_hash(&bytes, options.effort, options.backend, gpu.as_ref(), cancel),
            }
            .with_context(|| format!("無法壓縮 {}", item.relative))?;
            check(item)?;
            let output_digest = hash(&out);
            Ok(Work::Compressed(out, info, digest, output_digest))
        } else {
            Ok(Work::Copy)
        }
    };
    // Metal JPEG XL: the DNG read as subimage planes, coded later on the GPU thread
    let stage = |item: &&Item| -> Result<Staged> {
        if !metal_jxl || !is_dng_source(&item.path) {
            return Ok(Staged::Ready(prepare(item)?));
        }
        cancelled(cancel)?;
        check(item)?;
        let input = File::open(&item.path)?;
        ensure!(fingerprint(&input.metadata()?)? == item.stamp, "Source changed");
        let bytes = unsafe { memmap2::MmapOptions::new().map(&input)? };
        ensure!(fingerprint(&input.metadata()?)? == item.stamp, "Source changed");
        let frame = dng::jxl_frame(&bytes).with_context(|| format!("無法讀取 {}", item.relative))?;
        Ok(Staged::Frame(frame, hash(&bytes)))
    };
    // A bounded handoff keeps workers processing the next frame while the main
    // thread writes completed frames. A slow frame cannot stall an entire batch.
    // Active workers plus the byte-bounded RAM queue limit in-flight memory.
    let ram_budget = options
        .ram_buffer_bytes
        .unwrap_or_else(crate::ram::default_budget);
    ensure!(ram_budget <= 32usize << 30, "RAM buffer exceeds 32 GiB");
    let queue = crate::ram::Queue::new(ram_budget);
    // Metal JPEG XL: workers -> staged (planes) -> GPU thread -> queue -> writer
    let staged = crate::ram::Queue::new(ram_budget.min(1 << 30));
    let stopped = AtomicBool::new(false);
    let image_check_queue = crate::ram::Queue::new(256 << 10);
    let image_check_final_phase = AtomicBool::new(false);
    let image_checked = std::sync::atomic::AtomicUsize::new(0);
    std::thread::scope(|verification_scope| -> Result<Summary> {
    // Drop closes the queue on any early return before the scoped reader joins.
    let _readback_completion = image_check_queue.producer();
    let image_verifier = readback_file.map(|file| verification_scope.spawn(|| {
        pipelined_image_check(file, &image_check_queue, cancel, &image_checked, |done, name| {
            if image_check_final_phase.load(std::sync::atomic::Ordering::Relaxed) {
                progress(json!({"stage":"verify","done":done,"total":files.len()+1,"name":name,"pipelined":true}));
            }
        })
    }));
    std::thread::scope(|scope| -> Result<()> {
        let stop = &stopped;
        let files = &files;
        let pool = &pool;
        let queue = &queue;
        let staged = &staged;
        let stage = &stage;
        let prepare = &prepare;
        let progress = &progress;
        let worker = scope.spawn(move || {
            if metal_jxl {
                let _completion = staged.producer();
                // roughly in file order, so a clip's frames arrive together and batch well
                pool.install(|| {
                    files.iter().par_bridge().for_each(|item| {
                        if stop.load(std::sync::atomic::Ordering::Relaxed) {
                            return;
                        }
                        let result = stage(item);
                        let bytes = match &result {
                            Ok(Staged::Frame(f, digest)) => f.retained_bytes().saturating_add(digest.capacity()).saturating_add(512),
                            _ => 512,
                        };
                        if !staged.push((*item, result), bytes) {
                            stop.store(true, std::sync::atomic::Ordering::Relaxed);
                        }
                    })
                });
                return;
            }
            let _completion = queue.producer();
            pool.install(|| {
                files.par_iter().for_each(|item| {
                    if stop.load(std::sync::atomic::Ordering::Relaxed) {
                        return;
                    }
                    let result = prepare(item);
                    let bytes = match &result {
                        Ok(Work::Compressed(data, _, _, _)) => data.capacity() + 512,
                        _ => 512,
                    };
                    if !queue.push((*item, result), bytes) {
                        stop.store(true, std::sync::atomic::Ordering::Relaxed);
                    }
                })
            });
        });
        #[cfg(target_os = "macos")]
        let coder = metal_jxl.then(|| {
            scope.spawn(move || {
                let _completion = queue.producer();
                metal_jxl_coder(staged, queue, cancel, stop, progress);
            })
        });
        let result = (|| -> Result<()> {
            loop {
                let waiting = Instant::now();
                let next = queue.pop();
                writer_wait_seconds += waiting.elapsed().as_secs_f64();
                let Some((item, work)) = next else {
                    break;
                };
                let work = work?;
                cancelled(cancel)?;
                let writing = Instant::now();
                let (stored, raw, source_sha256) = match work {
                    Work::Compressed(bytes, info, digest, output_digest) => {
                        let stored = iso.add_prehashed(
                            &item.relative,
                            &bytes,
                            cancel,
                            output_digest,
                        )?;
                        (stored, Some(info), digest)
                    }
                    Work::Copy => {
                        check(item)?;
                        let mut input = File::open(&item.path)?;
                        ensure!(
                            fingerprint(&input.metadata()?)? == item.stamp,
                            "Source changed"
                        );
                        let stored = iso.add(&item.relative, &mut input, cancel)?;
                        ensure!(
                            fingerprint(&input.metadata()?)? == item.stamp,
                            "Source changed"
                        );
                        let hash = stored.sha256.clone();
                        (stored, None, hash)
                    }
                };
                check(item)?;
                if pipelined_verify {
                    queue_image_check(&image_check_queue, &item.relative, &stored)?;
                }
                iso_write_seconds += writing.elapsed().as_secs_f64();
                if stored.size < item.stamp.length {
                    compressed_files += 1;
                }
                records.push(Record {
                    path: item.relative.clone(),
                    source_size: item.stamp.length,
                    source_sha256,
                    stored,
                    raw,
                });
                progress(
                    json!({"stage":"compress","done":records.len(),"total":files.len(),"name":item.relative,"ram_buffered_bytes":queue.stats().0,"ram_buffer_bytes":ram_budget}),
                );
            }
            Ok(())
        })();
        stopped.store(true, std::sync::atomic::Ordering::Relaxed);
        // Wake any producer blocked on a full queue before joining it, including
        // cancellation and I/O errors on the writer thread.
        queue.abort();
        staged.abort();
        #[cfg(target_os = "macos")]
        if let Some(c) = coder {
            c.join().map_err(|_| anyhow::anyhow!("GPU 壓縮工作發生錯誤"))?;
        }
        worker
            .join()
            .map_err(|_| anyhow::anyhow!("壓縮工作發生錯誤"))?;
        result
    })?;
    cancelled(cancel)?;
    ensure!(records.len() == files.len(), "有 {} 個檔案沒有寫入映像檔", files.len() - records.len());
    records.sort_by(|a, b| a.path.cmp(&b.path));
    ensure!(
        select_items(inventory(&source)?, &options.excluded_clips)? == items,
        "素材在處理期間改變，請停止寫入素材後重試"
    );
    ensure!(
        records
            .iter()
            .all(|r| r.raw.as_ref().is_none_or(|i| i.pixel_verified)),
        "RAW 核對尚未完成"
    );
    let manifest = json!({"format":"CDNG Image","version":1,"engine":"rust","codec":if options.jxl {"jpeg-xl-dng"} else {"lossless-jpeg"},"effort":options.effort,"backend":options.backend,"excluded_clips":options.excluded_clips,
        "gpu_device":gpu.as_ref().map(|g|g.name.as_str()),"gpu_entropy":gpu.as_ref().is_some_and(|g|g.entropy_enabled()),"raw_verification":if options.store {"original-bytes"} else if metal_jxl {"metal-jxl-decode"} else if options.jxl {"cpu-full-jxl-decode"} else if gpu.as_ref().is_some_and(|g|g.entropy_enabled()) {"metal-entropy-roundtrip"} else {"cpu-full-decode"},"source_bytes":source_bytes,"files":records,
        "lossless_definition":"Original stored RAW sample values; DNG storage bytes change",
        "metadata":"Original prefix bytes and metadata offsets retained; image layout entries replaced"});
    let bytes = serde_json::to_vec_pretty(&manifest)?;
    let writing = Instant::now();
    let manifest_stored = iso.add(MANIFEST, &mut Cursor::new(bytes), cancel)?;
    if pipelined_verify { queue_image_check(&image_check_queue, MANIFEST, &manifest_stored)?; }
    let (mut image_bytes, data_crc) = iso.finish_with_checksum(!is_dmg)?;
    iso_write_seconds += writing.elapsed().as_secs_f64();
    let checking = Instant::now();
    if let Some(verifier) = image_verifier {
        // This timer measures only the tail wait. The complete readback starts
        // during compression and must finish successfully before publication.
        image_check_final_phase.store(true, std::sync::atomic::Ordering::Relaxed);
        progress(json!({"stage":"verify","done":image_checked.load(std::sync::atomic::Ordering::Relaxed),"total":files.len()+1,"name":"完成映像檔核對","pipelined":true}));
        image_check_queue.finish();
        verifier.join().map_err(|_| anyhow::anyhow!("映像檔核對工作發生錯誤"))??;
        ensure!(image_checked.load(std::sync::atomic::Ordering::Relaxed) == files.len()+1, "映像檔核對尚未完成");
        progress(json!({"stage":"verify","done":files.len()+1,"total":files.len()+1,"name":"完成映像檔核對","pipelined":true}));
    } else if options.verify {
        let mut verification: Vec<_> = records
            .iter()
            .map(|r| (r.path.as_str(), &r.stored))
            .chain(Some((MANIFEST, &manifest_stored)))
            .collect();
        verification.sort_by_key(|(_, stored)| stored.extent);
        verify_image(
            partial.path(),
            &verification,
            &pool,
            options.workers,
            ram_budget,
            cancel,
            &progress,
        )?;
    }
    cancelled(cancel)?;
    let image_check_seconds = checking.elapsed().as_secs_f64();
    let finishing = Instant::now();
    if is_dmg {
        progress(json!({"stage":"finalize","name":"完成 macOS DMG 描述與校驗資訊"}));
        image_bytes = crate::dmg::finish_with_checksum(partial.path(), cancel, data_crc.map(|crc| (image_bytes, crc)))?;
    }
    let dmg_finalize_seconds = finishing.elapsed().as_secs_f64();
    cancelled(cancel)?;
    partial.finish()?;
    let summary = Summary {
        output_format: if is_dmg { "dmg-udif" } else { "iso" },
        output,
        source_bytes,
        image_bytes,
        files: files.len(),
        compressed_files,
        seconds: started.elapsed().as_secs_f64(),
        backend: options.backend,
        effort: options.effort,
        workers: options.workers,
        checksums_verified: options.verify,
        raw_verification: if options.store {
            "original-bytes"
        } else if metal_jxl {
            "metal-jxl-decode"
        } else if options.jxl {
            "cpu-full-jxl-decode"
        } else if gpu.as_ref().is_some_and(|g| g.entropy_enabled()) {
            "metal-entropy-roundtrip"
        } else {
            "cpu-full-decode"
        },
        ram_buffer_bytes: ram_budget,
        ram_peak_bytes: queue.stats().1,
        iso_write_seconds,
        writer_wait_seconds,
        image_check_seconds,
        image_check_pipelined: pipelined_verify,
        dmg_finalize_seconds,
        dmg_checksum_streamed: is_dmg && data_crc.is_some(),
        engine: "rust",
    };
    progress(json!({"stage":"done","result":summary}));
    Ok(summary)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{fs::OpenOptions, sync::atomic::Ordering};

    #[test]
    fn clip_preview_ignores_appledouble_frames_without_dropping_sidecars() {
        let nonce=SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root=std::env::temp_dir().join(format!("cdng-appledouble-clips-{nonce}"));
        fs::create_dir_all(root.join("clip")).unwrap();
        fs::create_dir(root.join("metadata-only")).unwrap();
        fs::write(root.join("clip/f0.DNG"),b"raw").unwrap();
        fs::write(root.join("clip/._f0.DNG"),b"metadata").unwrap();
        fs::write(root.join("clip/audio.wav"),b"audio").unwrap();
        fs::write(root.join("metadata-only/._old.dng"),b"preserve").unwrap();
        let items=inventory(&root).unwrap();
        let clips=groups(&items);
        assert_eq!(clips.len(),1);
        assert_eq!(clips["clip"].frames,vec![root.join("clip/f0.DNG")]);
        assert_eq!(clips["clip"].bytes,3);
        let selected=select_items(items,&[]).unwrap();
        assert!(selected.iter().any(|i|i.relative=="clip/._f0.DNG"));
        assert!(selected.iter().any(|i|i.relative=="metadata-only/._old.dng"));
        assert_eq!(selected.iter().filter(|i|!i.dir).count(),4);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn pipelined_readback_overlaps_writes_without_changing_shared_file_cursor() {
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root = std::env::temp_dir().join(format!("cdng-pipeline-readback-{nonce}"));
        fs::create_dir(&root).unwrap();
        let output = root.join("test.iso");
        let (partial, file) = crate::output::OutputFile::create(&output).unwrap();
        let readback = readback_handle(&file, partial.path()).unwrap();
        let names = ["empty", "large", MANIFEST];
        let paths = names.iter().map(|&s| (s.to_owned(), false, 0)).collect::<Vec<_>>();
        let mut iso = Iso::new(file, &paths, "TEST").unwrap();
        let queue = crate::ram::Queue::new(0);
        let cancel = AtomicBool::new(false);
        let checked = std::sync::atomic::AtomicUsize::new(0);
        let mut records = Vec::new();
        std::thread::scope(|scope| {
            let _completion = queue.producer();
            let reader = scope.spawn(|| pipelined_image_check(readback, &queue, &cancel, &checked, |_, _| {}));
            for (name, size) in names.into_iter().zip([0, (2 << 20) + 17, 313]) {
                let bytes: Vec<u8> = (0..size).map(|i| (i * 31) as u8).collect();
                let stored = iso.add_prehashed(name, &bytes, &cancel, hash(&bytes)).unwrap();
                queue_image_check(&queue, name, &stored).unwrap();
                records.push((name, stored));
            }
            iso.finish().unwrap();
            queue.finish();
            reader.join().unwrap().unwrap();
        });
        assert_eq!(checked.load(Ordering::Relaxed), 3);
        let files = records.iter().map(|(name, stored)| (*name, stored)).collect::<Vec<_>>();
        let pool = rayon::ThreadPoolBuilder::new().num_threads(2).build().unwrap();
        verify_image(partial.path(), &files, &pool, 2, 0, &cancel, &|_| {}).unwrap();
        partial.finish().unwrap();
        assert!(output.exists());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn pipelined_readback_rejects_corruption_eof_cancellation_and_worker_panic() {
        use std::io::Write;
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root = std::env::temp_dir().join(format!("cdng-pipeline-failure-{nonce}"));
        fs::create_dir(&root).unwrap();
        for failure in ["corrupt", "eof", "cancel", "panic"] {
            let target = root.join(format!("{failure}.iso"));
            let (partial, mut file) = crate::output::OutputFile::create(&target).unwrap();
            let original = vec![37; 4096];
            file.write_all(&original).unwrap();
            let stored = Stored { extent: 0, size: if failure == "eof" {8192} else {4096},
                sha256: if failure == "corrupt" {hash(b"different payload")} else {hash(&original)} };
            let queue = crate::ram::Queue::new(0);
            let cancel = AtomicBool::new(failure == "cancel");
            let checked = std::sync::atomic::AtomicUsize::new(0);
            queue_image_check(&queue, "fixture", &stored).unwrap();
            std::thread::scope(|scope| {
                let writer = scope.spawn(|| {
                    (0..10000).all(|_| queue_image_check(&queue, "next", &stored).is_ok())
                });
                let result = pipelined_image_check(file, &queue, &cancel, &checked, |_, _| {
                    if failure == "panic" {panic!("simulated readback callback failure");}
                });
                assert!(result.is_err(), "{failure}");
                assert!(!writer.join().unwrap(), "blocked producer ignored verifier failure");
            });
            drop(partial);
            assert!(!target.exists(), "failed image was published: {failure}");
        }
        assert_eq!(fs::read_dir(&root).unwrap().count(), 0);
        fs::remove_dir(root).unwrap();
    }

    #[test]
    fn pipelined_pack_keeps_manifest_verification_and_failure_cleanup() {
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root = std::env::temp_dir().join(format!("cdng-pipeline-pack-{nonce}"));
        let source = root.join("source");
        fs::create_dir_all(&source).unwrap();
        for i in 0..4 {
            fs::write(source.join(format!("{i}.bin")), vec![i as u8; (1 << 20) + i]).unwrap();
        }
        let options = Options { source: source.clone(), output: root.join("complete.iso"),
            effort: Effort::Max, backend: Backend::Cpu, workers: 1, store: true, verify: true,
            ram_buffer_bytes: Some(0), excluded_clips: vec![], jxl: false };
        let cancel = AtomicBool::new(false);
        let final_check = std::sync::atomic::AtomicUsize::new(0);
        let summary = pack_with_verification_mode(&options, &cancel, |event| {
            if event["stage"] == "verify" && event["pipelined"] == true {
                final_check.fetch_max(event["done"].as_u64().unwrap_or(0) as usize, Ordering::Relaxed);
            }
        }, true).unwrap();
        assert!(summary.checksums_verified);
        assert_eq!(final_check.load(Ordering::Relaxed), 5, "manifest must also be read back");
        let original = fs::read(&options.output).unwrap();
        assert!(pack_with_verification_mode(&options, &cancel, |_| {}, true).is_err());
        assert_eq!(fs::read(&options.output).unwrap(), original);
        let mut cancelled_options = options.clone();
        cancelled_options.output = root.join("cancelled.iso");
        assert!(pack_with_verification_mode(&cancelled_options, &cancel, |event| {
            if event["stage"] == "compress" {cancel.store(true, Ordering::Relaxed);}
        }, true).is_err());
        assert!(!cancelled_options.output.exists());
        assert!(fs::read_dir(&root).unwrap().all(|entry| !entry.unwrap().file_name().to_string_lossy().contains("partial")));
        assert_eq!(fs::read(source.join("3.bin")).unwrap(), vec![3; (1 << 20) + 3]);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn parallel_image_check_rejects_damage_cancel_and_worker_failure() {
        use std::io::Write;
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("cdng-image-check-{nonce}"));
        fs::create_dir(&root).unwrap();
        let path = root.join("test.iso");
        let mut file = File::create(&path).unwrap();
        let a = vec![31; 2048];
        let b = vec![67; 4096];
        file.write_all(&a).unwrap();
        file.write_all(&b).unwrap();
        drop(file);
        let a = Stored {
            size: a.len() as u64,
            sha256: hash(&a),
            extent: 0,
        };
        let b = Stored {
            size: b.len() as u64,
            sha256: hash(&b),
            extent: 1,
        };
        let files = [("A", &a), ("B", &b)];
        let pool = rayon::ThreadPoolBuilder::new()
            .num_threads(4)
            .build()
            .unwrap();
        let cancel = AtomicBool::new(false);
        // Zero budget still permits one queued file and cannot deadlock.
        verify_image(&path, &files, &pool, 4, 0, &cancel, &|_| {}).unwrap();
        assert!(
            verify_image(&path, &files, &pool, 4, 0, &cancel, &|_| panic!(
                "worker failure"
            ))
            .is_err()
        );
        cancel.store(true, Ordering::Relaxed);
        assert!(verify_image(&path, &files, &pool, 4, 0, &cancel, &|_| {}).is_err());
        cancel.store(false, Ordering::Relaxed);
        let mut changed = OpenOptions::new().write(true).open(&path).unwrap();
        changed.write_all(&[0]).unwrap();
        drop(changed);
        assert!(verify_image(&path, &files, &pool, 4, 0, &cancel, &|_| {}).is_err());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn excluded_clip_removes_frames_audio_and_sidecars_but_keeps_other_clips() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("cdng-select-test-{nonce}"));
        fs::create_dir_all(root.join("A/sidecars")).unwrap();
        fs::create_dir_all(root.join("nested/B")).unwrap();
        for path in [
            "A/frame_000001.dng",
            "A/frame_000002.DNG",
            "A/audio.wav",
            "A/sidecars/info.txt",
            "nested/B/frame_000001.dng",
            "nested/B/audio.wav",
            "common.txt",
        ] {
            fs::write(root.join(path), b"fixture").unwrap();
        }
        let clips = list_clips(&root).unwrap();
        assert_eq!(clips.len(), 2);
        assert_eq!(clips[0].frames.len(), 2);
        let selected = select_items(inventory(&root).unwrap(), &["A".into()]).unwrap();
        assert!(
            !selected
                .iter()
                .any(|i| i.relative == "A" || i.relative.starts_with("A/"))
        );
        for path in [
            "nested/B/frame_000001.dng",
            "nested/B/audio.wav",
            "common.txt",
        ] {
            assert!(selected.iter().any(|i| i.relative == path));
        }
        assert!(select_items(inventory(&root).unwrap(), &["../outside".into()]).is_err());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn cancellation_and_existing_output_preserve_originals() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("cdng-rust-test-{nonce}"));
        let source = root.join("source");
        fs::create_dir_all(&source).unwrap();
        for i in 0..4 {
            fs::write(source.join(format!("{i}.bin")), vec![i as u8; 4096]).unwrap();
        }
        let output = root.join("cancel.iso");
        let options = Options {
            source: source.clone(),
            output: output.clone(),
            effort: Effort::Fast,
            backend: Backend::Cpu,
            workers: 2,
            store: true,
            verify: true,
            ram_buffer_bytes: None,
            excluded_clips: vec![],
            jxl: false,
        };
        let cancel = AtomicBool::new(false);
        assert!(pack(&options, &cancel, |_| cancel.store(true, Ordering::Relaxed)).is_err());
        assert!(!output.exists());
        assert!(fs::read_dir(&root).unwrap().all(|e| {
            !e.unwrap()
                .file_name()
                .to_string_lossy()
                .ends_with("partial")
        }));
        fs::write(&output, b"existing image").unwrap();
        assert!(pack(&options, &AtomicBool::new(false), |_| {}).is_err());
        assert_eq!(fs::read(&output).unwrap(), b"existing image");
        assert_eq!(fs::read(source.join("3.bin")).unwrap(), vec![3; 4096]);
        fs::remove_dir_all(root).unwrap();
    }
}
