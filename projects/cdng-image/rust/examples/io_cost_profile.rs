//! Read-only CPU/IO diagnostic. Does not encode or write media.
use anyhow::{Context, Result, ensure};
use std::{
    collections::BTreeMap,
    fs,
    hint::black_box,
    io::{Read, Seek, SeekFrom},
    path::{Path, PathBuf},
    time::Instant,
};

fn compression(path: &Path) -> Result<u16> {
    let mut f = fs::File::open(path)?;
    let mut b = [0u8; 8];
    f.read_exact(&mut b)?;
    ensure!(&b[..2] == b"II", "Diagnostic expects little endian TIFF");
    f.seek(SeekFrom::Start(
        u32::from_le_bytes(b[4..8].try_into()?) as u64
    ))?;
    let mut n = [0u8; 2];
    f.read_exact(&mut n)?;
    for _ in 0..u16::from_le_bytes(n) {
        let mut e = [0u8; 12];
        f.read_exact(&mut e)?;
        if u16::from_le_bytes(e[..2].try_into()?) == 259 {
            return Ok(u16::from_le_bytes(e[8..10].try_into()?));
        }
    }
    Ok(1)
}

fn measure(mut f: impl FnMut(), repeats: usize) -> f64 {
    let t = Instant::now();
    for _ in 0..repeats {
        f();
    }
    t.elapsed().as_secs_f64() / repeats as f64
}
fn main() -> Result<()> {
    let root = PathBuf::from(std::env::args_os().nth(1).context("SOURCE")?);
    let mut clips = fs::read_dir(&root)?
        .map(|e| e.map(|e| e.path()))
        .collect::<std::io::Result<Vec<_>>>()?;
    clips.sort();
    let mut rows = Vec::new();
    for clip in clips.into_iter().filter(|p| p.is_dir()) {
        let mut frames = fs::read_dir(&clip)?
            .map(|e| e.map(|e| e.path()))
            .collect::<std::io::Result<Vec<_>>>()?;
        frames.retain(|p| p.extension().is_some_and(|e| e.eq_ignore_ascii_case("dng")));
        frames.sort();
        ensure!(!frames.is_empty(), "Empty clip");
        let n = frames.len();
        let mut strata: BTreeMap<u16, Vec<PathBuf>> = BTreeMap::new();
        for path in frames {
            strata.entry(compression(&path)?).or_default().push(path);
        }
        for (compression, members) in strata {
            let sample_indices = [0, members.len() / 2, members.len() - 1];
            let mut sample_indices = sample_indices.to_vec();
            sample_indices.dedup();
            for i in sample_indices {
                let path = &members[i];
                let f = fs::File::open(path)?;
                let t = Instant::now();
                let bytes = unsafe { memmap2::MmapOptions::new().map(&f)? };
                let source_hash = cdng_image::hash(&bytes);
                let source_first_s = t.elapsed().as_secs_f64();
                let source_hash_s = measure(
                    || {
                        black_box(cdng_image::hash(&bytes));
                    },
                    30,
                );
                let crc_s = measure(
                    || {
                        black_box(crc32fast::hash(&bytes));
                    },
                    30,
                );
                let memcpy_s = measure(
                    || {
                        black_box(bytes.to_vec());
                    },
                    30,
                );
                let t = Instant::now();
                let pixels = cdng_image::dng::decode(&bytes)?;
                let decode_first_s = t.elapsed().as_secs_f64();
                let decode_s = measure(
                    || {
                        black_box(cdng_image::dng::decode(&bytes).unwrap());
                    },
                    10,
                );
                let pixel_bytes = unsafe {
                    std::slice::from_raw_parts(pixels.as_ptr().cast::<u8>(), pixels.len() * 2)
                };
                let pixel_hash_s = measure(
                    || {
                        black_box(cdng_image::hash(pixel_bytes));
                    },
                    30,
                );
                let metadata_s = measure(
                    || {
                        black_box(fs::symlink_metadata(path).unwrap());
                    },
                    100,
                );
                rows.push(serde_json::json!({
                "path": path.strip_prefix(&root)?, "source_bytes":bytes.len(), "raw_bytes":pixel_bytes.len(),
                "source_sha256":source_hash,"source_first_mmap_hash_s":source_first_s,
                "source_hash_s":source_hash_s,"source_crc_s":crc_s,"source_memcpy_s":memcpy_s,
                "decode_first_s":decode_first_s,"decode_s":decode_s,"pixel_hash_s":pixel_hash_s,"metadata_s":metadata_s,
                "clip_frame_count":n,"compression":compression,"stratum_frame_count":members.len(),
            }));
            }
        }
    }
    println!(
        "{}",
        serde_json::json!({"source":root,"read_only":true,"rows":rows,
        "limits":"Warm-cache single-thread microbenchmark stratified by clip and source compression; CPU totals are estimated by per-stratum averages, not a whole-product throughput measurement."})
    );
    Ok(())
}
