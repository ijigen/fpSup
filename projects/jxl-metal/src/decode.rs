//! Lossless JPEG XL decoding on the GPU (shaders/jxl.metal).
//!
//! `Decoder::decode` decodes a batch of codestreams to 16-bit planes; `cli` is the
//! `jxl-metal a.jxl ...` benchmark and diagnostics, checking `x.jxl` against `x.pgm`.
use anyhow::{Context, Result, bail, ensure};
use metal::{CompileOptions, Device, MTLResourceOptions, MTLSize};
use objc::rc::autoreleasepool;
use std::{ffi::c_void, mem::size_of, path::PathBuf, time::Instant};


const ARENA_INTS: u32 = 4 << 20; // 16 MiB per frame
const H: [&str; 20] = [
    "err", "width", "height", "bpp", "gshift", "gcols", "grows", "ngroups", "nlfgroups", "tree",
    "spec", "groups", "features", "errpos", "wp_tree", "top", "dbg0", "dbg1", "dbg2", "dbg3",
];
const ERRORS: [&str; 19] = [
    "", "short", "signature", "unsupported", "enum", "padding", "huffman", "ans", "cluster",
    "lz77", "tree", "toc", "arena", "range", "excess", "ans_final", "token", "window", "predictor",
];

#[repr(C)]
#[derive(Clone, Copy)]
struct FrameRef {
    offset: u32,
    size: u32,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct GroupJob {
    frame: u32,
    group: u32,
}

fn err_name(e: i32) -> String {
    if e == 0 {
        return "ok".into();
    }
    let (code, detail) = (e / 1000, e % 1000);
    format!("{}/{}", ERRORS.get(code as usize).unwrap_or(&"?"), detail)
}

/// Never consume GPU output after a failed or incomplete command. A completed wait
/// alone does not mean that Metal successfully executed the commands.
pub(crate) fn wait_completed(command: &metal::CommandBufferRef, operation: &str) -> Result<()> {
    command.wait_until_completed();
    let result = check_status(command.status(), operation);
    if result.is_err() && let Some(detail) = command_error(command) {
        return result.context(detail);
    }
    result
}

#[allow(unexpected_cfgs)] // objc 0.2's message macro uses its legacy cargo-clippy cfg.
fn command_error(command: &metal::CommandBufferRef) -> Option<String> {
    use objc::{msg_send, sel, sel_impl};
    use objc::runtime::Object;
    unsafe {
        let error: *mut Object = msg_send![command, error];
        if error.is_null() { return None; }
        let code: isize = msg_send![error, code];
        let description: *mut Object = msg_send![error, localizedDescription];
        if description.is_null() { return Some(format!("Metal error {code}")); }
        let text: *const std::ffi::c_char = msg_send![description, UTF8String];
        if text.is_null() { return Some(format!("Metal error {code}")); }
        Some(format!("Metal error {code}: {}", std::ffi::CStr::from_ptr(text).to_string_lossy()))
    }
}

fn check_status(status: metal::MTLCommandBufferStatus, operation: &str) -> Result<()> {
    ensure!(status == metal::MTLCommandBufferStatus::Completed,
        "Metal JPEG XL {operation} failed: command status {status:?}");
    Ok(())
}

fn select_chunk(njobs: u32, cores: u32, configured: Option<u32>, cached: Option<u32>) -> Result<u32> {
    ensure!(njobs > 0, "JPEG XL batch contains no image groups");
    ensure!(configured != Some(0), "JXL_CHUNK must be greater than zero");
    // Old or manually edited tuning caches must not make the dispatch loop stall.
    Ok(configured.or(cached.filter(|&n| n > 0))
        .unwrap_or_else(|| cores.max(1).saturating_mul(32 * 4)).min(njobs))
}

pub fn read_pgm(path: &PathBuf) -> Result<(usize, usize, Vec<u16>)> {
    let b = std::fs::read(path)?;
    let mut fields = Vec::new();
    let mut i = 0;
    while fields.len() < 4 {
        while b[i].is_ascii_whitespace() {
            i += 1;
        }
        let s = i;
        while !b[i].is_ascii_whitespace() {
            i += 1;
        }
        fields.push(std::str::from_utf8(&b[s..i])?.to_string());
    }
    i += 1;
    ensure!(fields[0] == "P5", "not a P5 pgm");
    let (w, h, maxv): (usize, usize, u32) = (fields[1].parse()?, fields[2].parse()?, fields[3].parse()?);
    ensure!(maxv > 255, "8-bit pgm not handled");
    let px = b[i..i + w * h * 2].chunks_exact(2).map(|c| u16::from_be_bytes([c[0], c[1]])).collect();
    Ok((w, h, px))
}

/// Bare codestream from a .jxl file: unwraps the ISOBMFF container (jxlc, or jxlp parts)
/// that cjxl writes e.g. for Level 10 (> 12-bit) images.
pub fn codestream(file: Vec<u8>) -> Result<Vec<u8>> {
    if file.starts_with(&[0xff, 0x0a]) {
        return Ok(file);
    }
    ensure!(file.len() >= 12 && file[4..12] == *b"JXL \r\n\x87\n", "not a JPEG XL file");
    let (mut i, mut out) = (0usize, Vec::new());
    while i + 8 <= file.len() {
        let mut size = u32::from_be_bytes(file[i..i + 4].try_into()?) as usize;
        let kind = &file[i + 4..i + 8];
        let mut head = 8;
        if size == 1 {
            size = u64::from_be_bytes(file[i + 8..i + 16].try_into()?) as usize;
            head = 16;
        } else if size == 0 {
            size = file.len() - i;
        }
        ensure!(size >= head && i + size <= file.len(), "bad box");
        match kind {
            b"jxlc" => out.extend_from_slice(&file[i + head..i + size]),
            b"jxlp" => out.extend_from_slice(&file[i + head + 4..i + size]),
            _ => {}
        }
        i += size;
    }
    ensure!(out.starts_with(&[0xff, 0x0a]), "no codestream box");
    Ok(out)
}

/// GPU core count from the IORegistry (AGXAccelerator "gpu-core-count").
fn gpu_core_count() -> Option<u32> {
    let out = std::process::Command::new("ioreg").args(["-rc", "AGXAccelerator", "-d", "1"]).output().ok()?;
    let text = String::from_utf8_lossy(&out.stdout);
    let line = text.lines().find(|l| l.contains("\"gpu-core-count\""))?;
    line.rsplit('=').next()?.trim().parse().ok()
}

/// Per-machine group chunk size, keyed by GPU name and core count.
fn tuning_file() -> Option<PathBuf> {
    Some(PathBuf::from(std::env::var_os("HOME")?).join("Library/Caches/jxl-metal/chunk.txt"))
}

fn cached_chunk(key: &str) -> Option<u32> {
    let text = std::fs::read_to_string(tuning_file()?).ok()?;
    text.lines().find_map(|l| l.strip_prefix(&format!("{key}=")).and_then(|v| v.parse().ok()))
}

fn save_chunk(key: &str, chunk: u32) -> Result<()> {
    let path = tuning_file().context("no HOME")?;
    std::fs::create_dir_all(path.parent().unwrap())?;
    let mut lines: Vec<String> = std::fs::read_to_string(&path).unwrap_or_default().lines()
        .filter(|l| !l.starts_with(&format!("{key}="))).map(String::from).collect();
    lines.push(format!("{key}={chunk}"));
    std::fs::write(path, lines.join("\n") + "\n")?;
    Ok(())
}

fn buffer<T: Copy>(dev: &Device, data: &[T]) -> metal::Buffer {
    dev.new_buffer_with_data(
        data.as_ptr() as *const c_void,
        (data.len() * size_of::<T>()).max(4) as u64,
        MTLResourceOptions::StorageModeShared,
    )
}

/// Shader source with optional `JXL_DEFS="A B=1"` preprocessor defines (timing experiments).
fn shader_source() -> String {
    let mut src = String::new();
    for d in std::env::var("JXL_DEFS").unwrap_or_default().split_whitespace() {
        let (k, v) = d.split_once('=').unwrap_or((d, "1"));
        src += &format!("#define {k} {v}\n");
    }
    src + include_str!("../shaders/jxl.metal")
}


struct Pipes {
    parse: metal::ComputePipelineState,
    setup: metal::ComputePipelineState,
    group: metal::ComputePipelineState,
    lean_multi: metal::ComputePipelineState,
    generic: metal::ComputePipelineState,
    inv_palette: metal::ComputePipelineState,
}

/// Device, kernels and per-GPU group chunk, created once.
pub struct Decoder {
    dev: Device,
    queue: metal::CommandQueue,
    p: Pipes,
    cores: u32,
    tune_key: String,
    /// buffers kept between batches (`decode` is called once per batch)
    pool: std::cell::RefCell<std::collections::HashMap<&'static str, metal::Buffer>>,
}

/// A batch after pass 1 (headers, TOC, global trees and tables of every frame).
struct Parsed {
    src_buf: metal::Buffer,
    arenas: metal::Buffer,
    nframes: u32,
    parse_ms: f64,
    jobs: Vec<GroupJob>,
    plane_offsets: Vec<u64>,
    dims: Vec<(usize, usize)>,
    total_px: u64,
    max_gw: u32,
    palette_frames: Vec<(u32, u64)>,
}

impl Parsed {
    fn hdr(&self, f: u32, i: usize) -> i32 {
        unsafe { *(self.arenas.contents() as *const i32).add(f as usize * ARENA_INTS as usize + i) }
    }
}

/// Buffers of pass 2 for a chunk size.
struct Groups {
    planes: metal::Buffer,
    status: metal::Buffer,
    scratch: metal::Buffer,
    scratch_ints: u32,
    rowpx: metal::Buffer,
    rowerr: metal::Buffer,
    jobs_buf: metal::Buffer,
    offs_buf: metal::Buffer,
    maxw: u32,
    tg: u64,
}

impl Decoder {
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
        let p = Pipes {
            parse: pipeline("jxl_parse_frame")?,
            setup: pipeline("jxl_group_setup")?,
            group: pipeline("jxl_group_decode_lean")?,
            lean_multi: pipeline("jxl_group_decode_lean_multi")?,
            generic: pipeline("jxl_group_decode_generic")?,
            inv_palette: pipeline("jxl_inverse_palette")?,
        };
        let cores = gpu_core_count().unwrap_or(8);
        let tune_key = format!("{} {cores}c", dev.name());
        let queue = dev.new_command_queue();
        Ok(Self { dev, queue, p, cores, tune_key, pool: Default::default() })
    }

    /// A buffer of at least `bytes`, reused while big enough.
    fn scratch(&self, name: &'static str, bytes: u64, mode: MTLResourceOptions) -> metal::Buffer {
        let mut pool = self.pool.borrow_mut();
        if let Some(b) = pool.get(name)
            && b.length() >= bytes
        {
            return b.clone();
        }
        let b = self.dev.new_buffer(bytes.max(4), mode);
        pool.insert(name, b.clone());
        b
    }

    /// Pass 1: one thread per frame. Fails if any frame does not parse.
    fn parse(&self, streams: &[&[u8]], verbose: bool) -> Result<Parsed> {
        autoreleasepool(|| self.parse_inner(streams, verbose))
    }

    fn parse_inner(&self, streams: &[&[u8]], verbose: bool) -> Result<Parsed> {
        ensure!(!streams.is_empty(), "JPEG XL batch contains no frames");
        let mut src = Vec::new();
        let mut frames = Vec::new();
        for b in streams {
            frames.push(FrameRef { offset: src.len() as u32, size: b.len() as u32 });
            src.extend_from_slice(b);
            while src.len() % 4 != 0 {
                src.push(0);
            }
        }
        src.extend_from_slice(&[0; 16]); // the bit reader may read a few bytes past a section
        let nframes = frames.len() as u32;
        let src_buf = buffer(&self.dev, &src);
        let frames_buf = buffer(&self.dev, &frames);
        let arenas = self.scratch("arenas", nframes as u64 * ARENA_INTS as u64 * 4, MTLResourceOptions::StorageModeShared);
        let cb = self.queue.new_command_buffer();
        let enc = cb.new_compute_command_encoder();
        enc.set_compute_pipeline_state(&self.p.parse);
        enc.set_buffer(0, Some(&src_buf), 0);
        enc.set_buffer(1, Some(&frames_buf), 0);
        enc.set_buffer(2, Some(&arenas), 0);
        enc.set_bytes(3, 4, &ARENA_INTS as *const u32 as *const c_void);
        enc.set_bytes(4, 4, &nframes as *const u32 as *const c_void);
        enc.dispatch_threads(MTLSize::new(nframes as u64, 1, 1), MTLSize::new(1, 1, 1));
        enc.end_encoding();
        let t = Instant::now();
        cb.commit();
        wait_completed(cb, "header decoding")?;
        let parse_ms = t.elapsed().as_secs_f64() * 1e3;
        let mut p = Parsed {
            src_buf,
            arenas,
            nframes,
            parse_ms,
            jobs: Vec::new(),
            plane_offsets: Vec::new(),
            dims: Vec::new(),
            total_px: 0,
            max_gw: 0,
            palette_frames: Vec::new(),
        };
        for f in 0..nframes {
            let e = p.hdr(f, 0);
            if verbose {
                print!("frame {f}: {} ", err_name(e));
                for (i, name) in H.iter().enumerate().skip(1).take(15) {
                    print!("{name}={} ", p.hdr(f, i));
                }
                println!();
            }
            if e != 0 {
                bail!("frame {f} failed to parse: {}", err_name(e));
            }
            let (w, h, ng, gs) = (p.hdr(f, 1) as u64, p.hdr(f, 2) as u64, p.hdr(f, 7) as u32, p.hdr(f, 4));
            p.max_gw = p.max_gw.max(1 << gs);
            if p.hdr(f, 20) != 0 {
                p.palette_frames.push((f, w * h));
            }
            p.plane_offsets.push(p.total_px);
            p.dims.push((w as usize, h as usize));
            p.total_px += w * h;
            p.jobs.extend((0..ng).map(|g| GroupJob { frame: f, group: g }));
        }
        Ok(p)
    }

    fn chunk(&self, njobs: u32) -> Result<u32> {
        select_chunk(njobs, self.cores,
            std::env::var("JXL_CHUNK").ok().and_then(|v| v.parse().ok()),
            cached_chunk(&self.tune_key))
    }

    fn group_buffers(&self, p: &Parsed, max_chunk: u32) -> Groups {
        // per group: local tree/tables, LZ77 window; odd stride keeps groups off the same cache sets
        let scratch_ints: u32 = std::env::var("JXL_SCRATCH").ok().and_then(|v| v.parse().ok()).unwrap_or((1 << 16) + 1040);
        let scratch_mode = if std::env::var("JXL_DUMP").is_ok() { MTLResourceOptions::StorageModeShared } else { MTLResourceOptions::StorageModePrivate };
        let maxw = p.max_gw;
        let private = MTLResourceOptions::StorageModePrivate;
        Groups {
            planes: self.scratch("planes", p.total_px * 2, MTLResourceOptions::StorageModeShared), // 16-bit samples
            status: self.scratch("status", p.jobs.len() as u64 * 16, MTLResourceOptions::StorageModeShared),
            scratch: self.scratch("scratch", max_chunk as u64 * scratch_ints as u64 * 4, scratch_mode),
            scratch_ints,
            rowpx: self.scratch("rowpx", 3 * maxw as u64 * max_chunk as u64 * 4, private),
            rowerr: self.scratch("rowerr", 2 * 5 * maxw as u64 * max_chunk as u64 * 4, private),
            jobs_buf: buffer(&self.dev, &p.jobs),
            offs_buf: buffer(&self.dev, &p.plane_offsets),
            maxw,
            tg: std::env::var("JXL_TG").ok().and_then(|v| v.parse().ok()).unwrap_or(32u64)
                .min(self.p.group.max_total_threads_per_threadgroup())
                .min(32), // the kernel's threadgroup tree storage is sized for 32 threads
        }
    }

    /// Pass 2: one thread per group across all frames, in chunks of `chunk` groups.
    /// Too many resident groups overflow the GPU caches (per-group entropy tables); a chunk
    /// that is not a whole number of threadgroups per core leaves cores idle.
    fn run_groups(&self, p: &Parsed, g: &Groups, chunk: u32) -> Result<f64> {
        autoreleasepool(|| self.run_groups_inner(p, g, chunk))
    }

    fn run_groups_inner(&self, p: &Parsed, g: &Groups, chunk: u32) -> Result<f64> {
        ensure!(chunk > 0, "JPEG XL group chunk must be greater than zero");
        let njobs = p.jobs.len() as u32;
        // One encoder for everything: serial dispatches keep their order and see each
        // other's writes, without an encoder switch per kernel.
        let cb = self.queue.new_command_buffer();
        let enc = cb.new_compute_command_encoder();
        enc.set_buffer(0, Some(&p.src_buf), 0);
        enc.set_buffer(1, Some(&p.arenas), 0);
        enc.set_bytes(2, 4, &ARENA_INTS as *const u32 as *const c_void);
        enc.set_buffer(3, Some(&g.jobs_buf), 0);
        enc.set_buffer(5, Some(&g.planes), 0);
        enc.set_buffer(6, Some(&g.offs_buf), 0);
        enc.set_buffer(7, Some(&g.scratch), 0);
        enc.set_bytes(8, 4, &g.scratch_ints as *const u32 as *const c_void);
        enc.set_buffer(9, Some(&g.status), 0);
        enc.set_buffer(10, Some(&g.rowpx), 0);
        enc.set_buffer(11, Some(&g.rowerr), 0);
        enc.set_bytes(12, 4, &g.maxw as *const u32 as *const c_void);
        let mut base = 0u32;
        while base < njobs {
            let n = chunk.min(njobs - base);
            enc.set_bytes(4, 4, &n as *const u32 as *const c_void);
            enc.set_bytes(13, 4, &base as *const u32 as *const c_void);
            // generic last: lean kernels hand overflowing groups over to it
            for pipe in [&self.p.setup, &self.p.group, &self.p.lean_multi, &self.p.generic] {
                enc.set_compute_pipeline_state(pipe);
                enc.dispatch_threads(MTLSize::new(n as u64, 1, 1), MTLSize::new(g.tg, 1, 1));
            }
            base += n;
        }
        // global palettes: indices -> values once every group of the frame is in place
        if !p.palette_frames.is_empty() {
            enc.set_compute_pipeline_state(&self.p.inv_palette);
            for &(f, n) in &p.palette_frames {
                enc.set_bytes(14, 4, &f as *const u32 as *const c_void);
                enc.dispatch_threads(MTLSize::new(n, 1, 1), MTLSize::new(256, 1, 1));
            }
        }
        enc.end_encoding();
        let t = Instant::now();
        cb.commit();
        wait_completed(cb, "pixel decoding")?;
        Ok(t.elapsed().as_secs_f64() * 1e3)
    }

    fn status(g: &Groups, njobs: usize) -> &[i32] {
        unsafe { std::slice::from_raw_parts(g.status.contents() as *const i32, 4 * njobs) }
    }

    /// Decodes bare codestreams to 16-bit planes (width, height, samples). Fails if any
    /// frame or group reports an error.
    pub fn decode(&self, streams: &[&[u8]]) -> Result<Vec<(usize, usize, Vec<u16>)>> {
        let mut out = Vec::new();
        self.decode_with(streams, |_, w, h, px| out.push((w, h, px.to_vec())))?;
        Ok(out)
    }

    /// Like `decode`, but hands each frame's samples (frame index, width, height) to `f`
    /// straight from the GPU buffer, without copying.
    pub fn decode_with(&self, streams: &[&[u8]], mut f: impl FnMut(usize, usize, usize, &[u16])) -> Result<()> {
        let p = self.parse(streams, false)?;
        let chunk = self.chunk(p.jobs.len() as u32)?;
        let g = self.group_buffers(&p, chunk);
        self.run_groups(&p, &g, chunk)?;
        let st = Self::status(&g, p.jobs.len());
        if let Some(j) = (0..p.jobs.len()).find(|&j| st[4 * j] != 0) {
            bail!("frame {} group {} failed: {}", p.jobs[j].frame, p.jobs[j].group, err_name(st[4 * j]));
        }
        let px = unsafe { std::slice::from_raw_parts(g.planes.contents() as *const u16, p.total_px as usize) };
        for i in 0..p.nframes as usize {
            let (w, h) = p.dims[i];
            let o = p.plane_offsets[i] as usize;
            f(i, w, h, &px[o..o + w * h]);
        }
        Ok(())
    }
}

pub fn cli(args: &[String]) -> Result<()> {
    let files: Vec<PathBuf> = args.iter().map(PathBuf::from).collect();
    ensure!(!files.is_empty(), "usage: jxl-metal <a.jxl> [b.jxl ...]");
    let mut streams = Vec::new();
    for f in &files {
        streams.push(codestream(std::fs::read(f).with_context(|| format!("{}", f.display()))?)?);
    }
    let dec = Decoder::new()?;
    println!("device: {}", dec.dev.name());
    println!(
        "max threads/threadgroup: setup {}, lean {}, generic {}; simd width {}, static tg mem {} B",
        dec.p.setup.max_total_threads_per_threadgroup(),
        dec.p.group.max_total_threads_per_threadgroup(),
        dec.p.generic.max_total_threads_per_threadgroup(),
        dec.p.group.thread_execution_width(),
        dec.p.group.static_threadgroup_memory_length()
    );
    let refs: Vec<&[u8]> = streams.iter().map(|s| s.as_slice()).collect();
    let p = dec.parse(&refs, true)?;
    let (nframes, parse_ms, total_px) = (p.nframes, p.parse_ms, p.total_px);
    let a = p.arenas.contents() as *const i32;
    let hdr = |f: u32, i: usize| p.hdr(f, i);
    let jobs = &p.jobs;
    let plane_offsets = &p.plane_offsets;
    println!("parse: {parse_ms:.2} ms for {nframes} frame(s)");
    if std::env::var("JXL_GTREE").is_ok() && hdr(0, 9) >= 0 {
        // global tree statistics of frame 0
        let base = hdr(0, 9) as usize;
        let node = |k: usize| unsafe { std::slice::from_raw_parts(a.add(base + 4 * k), 4) };
        let (mut k, mut last, mut nb, mut nl) = (0usize, 0usize, 0, 0);
        let mut props = std::collections::BTreeMap::new();
        let mut preds = std::collections::BTreeMap::new();
        let mut depth = vec![0usize; 1];
        let mut maxd = 0;
        while k <= last {
            let n = node(k);
            if depth.len() <= k { depth.resize(k + 1, 0); }
            if n[0] < 0 {
                nb += 1;
                *props.entry(!n[0]).or_insert(0) += 1;
                let (l, r) = (k + n[2] as usize, k + n[3] as usize);
                last = last.max(r);
                if depth.len() <= r { depth.resize(r + 1, 0); }
                depth[l] = depth[k] + 1; depth[r] = depth[k] + 1;
            } else {
                nl += 1;
                *preds.entry((n[1], n[2], n[3])).or_insert(0) += 1;
                maxd = maxd.max(depth[k]);
            }
            k += 1;
        }
        let spec = hdr(0, 10) as usize;
        let sp = unsafe { std::slice::from_raw_parts(a.add(spec), 16) };
        println!("global tree: {nb} branches, {nl} leaves, max depth {maxd}, props {props:?}");
        println!("  leaves (pred, off, mul): {preds:?}");
        println!("  spec: num_dist {} lz77 {} prefix {} log_alpha {} clusters {}", sp[0], sp[1], sp[8], sp[9], sp[10]);
    }

    // ---- pass 2: groups (one thread per group across all frames)
    let njobs = jobs.len() as u32;
    let cores = dec.cores;
    let tune_key = dec.tune_key.clone();
    let tune = std::env::var("JXL_TUNE").is_ok();
    let candidates: Vec<u32> = (2..=5).map(|k| (cores * 32 * k).min(njobs)).collect();
    let mut chunk = dec.chunk(njobs)?;
    let max_chunk = if tune { *candidates.iter().max().unwrap() } else { chunk };
    println!("gpu: {tune_key}, chunk {chunk}{}", if tune { " (tuning)" } else { "" });
    let gb = dec.group_buffers(&p, max_chunk);
    let (scratch, scratch_ints, tg) = (&gb.scratch, gb.scratch_ints, gb.tg);
    let reps: usize = std::env::var("JXL_REPS").ok().and_then(|v| v.parse().ok()).unwrap_or(5);
    let run = |chunk: u32| -> Result<f64> { dec.run_groups(&p, &gb, chunk) };

    if tune {
        let mut best = (f64::MAX, chunk);
        for &c in &candidates {
            let mut t: Vec<f64> = (0..3).map(|_| run(c)).collect::<Result<_>>()?;
            t.sort_by(|a, b| a.partial_cmp(b).unwrap());
            println!("  tune chunk {c}: {:.2} ms", t[1]);
            if t[1] < best.0 { best = (t[1], c); }
        }
        chunk = best.1;
        save_chunk(&tune_key, chunk)?;
        println!("  -> chunk {chunk} saved for {tune_key}");
    }
    let mut times = Vec::new();
    for _ in 0..reps {
        times.push(run(chunk)?);
    }
    let st4 = Decoder::status(&gb, njobs as usize);
    let st: Vec<i32> = st4.iter().step_by(4).copied().collect();
    let used: Vec<i32> = st4.iter().skip(1).step_by(4).map(|v| v & 0xffffff).collect();
    let gfeat = st4.iter().skip(1).step_by(4).fold(0, |a, v| a | (v >> 24));
    if std::env::var("JXL_GTREE").is_ok() {
        // per-group sizes of global trees after folding
        let mut hist = std::collections::BTreeMap::new();
        let (mut sp, mut intg, mut n) = (0, 0, 0);
        for j in 0..njobs as usize {
            let v = st4[4 * j + 2];
            if v >= 0 { continue; }
            let v = -(v + 1);
            let nb = v & 0xffff;
            *hist.entry((nb / 16) * 16).or_insert(0) += 1;
            sp += (v >> 16) & 1; intg += (v >> 17) & 1; n += 1;
        }
        println!("folded trees: {n} groups, single-property {sp}, in threadgroup memory {intg}; branches (x16): {hist:?}");
    }
    if let Ok(v) = std::env::var("JXL_DUMP") {
        // dump the local tree of one job of the last chunk (scratch holds the last chunk)
        let last_base = (njobs - 1) / chunk * chunk;
        let lane: u32 = v.parse().unwrap_or(0);
        let j = (last_base + lane) as usize;
        let tree = st4[4 * j + 2];
        let sc = unsafe { (scratch.contents() as *const i32).add(lane as usize * scratch_ints as usize) };
        println!("job {j}: tree at {tree}, spec at {}", st4[4 * j + 3]);
        if tree >= 0 {
            let (mut k, mut last) = (0usize, 0usize);
            while k <= last {
                let n = unsafe { std::slice::from_raw_parts(sc.add(tree as usize + 4 * k), 4) };
                if n[0] < 0 {
                    println!("  {k}: prop {} > {} ? {} : {}", !n[0], n[1], k as i32 + n[2], k as i32 + n[3]);
                    last = last.max(k + n[2].max(n[3]) as usize);
                } else {
                    println!("  {k}: leaf cr@{} pred {} off {} mul {}", n[0], n[1], n[2], n[3]);
                }
                k += 1;
            }
            let spec = st4[4 * j + 3] as usize;
            let s = unsafe { std::slice::from_raw_parts(sc.add(spec), 16) };
            println!("  spec: num_dist {} lz77 {} prefix {} log_alpha {} clusters {}", s[0], s[1], s[8], s[9], s[10]);
        }
    }
    println!("group scratch use: max {} ints; group features {gfeat:#x}", used.iter().max().unwrap());
    let bad: Vec<_> = st.iter().enumerate().filter(|(_, e)| **e != 0).collect();
    if std::env::var("JXL_TRINFO").is_ok() {
        let mut seen = std::collections::BTreeMap::new();
        for (i, _) in &bad {
            let t = st4[4 * i + 3];
            let k = if t < 0 { format!("transform id {}", -t - 1) } else {
                format!("palette deltas {} d_pred {}", (t >> 16) & 0xfff, (t >> 28) & 15)
            };
            *seen.entry(k).or_insert(0) += 1;
        }
        for (k, n) in seen { println!("  {n} groups: {k}"); }
    }
    if let Some((i, e)) = bad.first() {
        println!("{} of {njobs} groups failed; first: job {i} ({}) {}", bad.len(), jobs[*i].group, err_name(**e));
    }
    times.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let med = times[reps / 2];
    println!(
        "groups: {njobs} jobs, chunk {chunk}, threadgroup {tg}, median {med:.2} ms over {reps} runs ({:.1} Mpx/s, {:.1} frames/s)",
        total_px as f64 / med / 1e3,
        nframes as f64 / med * 1e3
    );

    // ---- check against the cjxl input
    let px16 = unsafe { std::slice::from_raw_parts(gb.planes.contents() as *const i16, total_px as usize) };
    let px: Vec<i32> = px16.iter().map(|v| *v as i32).collect();
    for (f, file) in files.iter().enumerate() {
        let pgm = file.with_extension("pgm");
        if !pgm.exists() {
            continue;
        }
        let (w, h, refpx) = read_pgm(&pgm)?;
        ensure!(w as i32 == hdr(f as u32, 1) && h as i32 == hdr(f as u32, 2), "size mismatch");
        let o = plane_offsets[f] as usize;
        let got = &px[o..o + w * h];
        let diff = got.iter().zip(&refpx).filter(|(a, b)| **a != **b as i32).count();
        let first = got.iter().zip(&refpx).position(|(a, b)| *a != *b as i32);
        match first {
            None => println!("frame {f}: {} px exact", w * h),
            Some(i) => println!(
                "frame {f}: {diff} of {} px differ; first at x={} y={} got {} want {}",
                w * h,
                i % w,
                i / w,
                got[i],
                refpx[i]
            ),
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn explicit_zero_chunk_is_rejected_before_dispatch() {
        let error = select_chunk(32, 8, Some(0), Some(16)).unwrap_err();
        assert!(error.to_string().contains("JXL_CHUNK must be greater than zero"));
    }

    #[test]
    fn stale_zero_cache_uses_a_bounded_nonzero_default() {
        assert_eq!(select_chunk(6000, 32, None, Some(0)).unwrap(), 4096);
        assert_eq!(select_chunk(7, 32, None, Some(0)).unwrap(), 7);
        assert_eq!(select_chunk(6000, 0, None, None).unwrap(), 128);
        assert_eq!(select_chunk(6000, u32::MAX, None, None).unwrap(), 6000);
    }

    #[test]
    fn valid_chunk_preferences_and_empty_batch_are_handled() {
        assert_eq!(select_chunk(40, 8, Some(16), Some(8)).unwrap(), 16);
        assert_eq!(select_chunk(40, 8, None, Some(8)).unwrap(), 8);
        assert_eq!(select_chunk(40, 8, Some(100), None).unwrap(), 40);
        assert!(select_chunk(0, 8, None, None).is_err());
    }

    #[test]
    fn unsuccessful_gpu_commands_cannot_supply_output() {
        use metal::MTLCommandBufferStatus::*;
        for status in [NotEnqueued, Enqueued, Committed, Scheduled, Error] {
            let error = check_status(status, "pixel decoding").unwrap_err();
            assert!(error.to_string().contains("pixel decoding"));
            assert!(error.to_string().contains(&format!("{status:?}")));
        }
        check_status(Completed, "pixel decoding").unwrap();
    }

    #[test]
    #[ignore = "requires a Metal device; run with --ignored and no concurrent GPU benchmarks"]
    fn repeated_batches_survive_operation_pool_drain() {
        let encoder = crate::encode::Encoder::new().unwrap();
        let decoder = Decoder::new().unwrap();
        let (w, h) = (258, 130);
        let frames: Vec<Vec<u16>> = (0..2).map(|frame| {
            (0..w * h).map(|i| ((i * 47 + (i / w) * 113 + frame * 911) & 4095) as u16).collect()
        }).collect();
        let model = encoder.learn(&frames[0], w, h).unwrap();
        let refs: Vec<&[u16]> = frames.iter().map(Vec::as_slice).collect();
        let mut previous = None;
        // Each call drains its own Objective-C pool. The reusable buffers and model
        // must remain valid after that drain and after an intervening smaller batch.
        for count in [2, 1, 2] {
            let (streams, _) = encoder.encode(&model, &refs[..count], w, h, 12).unwrap();
            if count == 2 {
                if let Some(ref expected) = previous {
                    assert_eq!(&streams, expected);
                }
                previous = Some(streams.clone());
            }
            let encoded: Vec<&[u8]> = streams.iter().map(Vec::as_slice).collect();
            let mut seen = 0;
            decoder.decode_with(&encoded, |i, dw, dh, pixels| {
                assert_eq!((dw, dh), (w, h));
                assert_eq!(pixels, frames[i]);
                seen += 1;
            }).unwrap();
            assert_eq!(seen, count);
        }
    }
}
