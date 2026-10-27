//! Benchmark the implemented Rust read engine, not a projected mounted-device rate.
use anyhow::{Result, ensure};
use cdng_image::{archive::Archive, virtual_disk::VirtualDisk};
use rayon::prelude::*;
use std::{path::PathBuf, sync::Arc, time::Instant};
fn main() -> Result<()> {
    let path = PathBuf::from(std::env::args_os().nth(1).expect("ARCHIVE"));
    let pool = rayon::ThreadPoolBuilder::new().num_threads(8).build()?;
    let mut results = Vec::new();
    for repeat in 0..3 {
        let archive = Arc::new(Archive::open(&path, 256 << 20)?);
        let mut outputs: Vec<_> = archive
            .index
            .entries
            .iter()
            .map(|e| vec![0; e.virtual_size as usize])
            .collect();
        let started = Instant::now();
        pool.install(|| {
            outputs
                .par_iter_mut()
                .enumerate()
                .try_for_each(|(i, b)| -> Result<()> {
                    ensure!(archive.read_into(i, 0, b)? == b.len(), "Short read");
                    Ok(())
                })
        })?;
        let cold = started.elapsed().as_secs_f64();
        let after_cold = archive.stats();
        let started = Instant::now();
        pool.install(|| {
            outputs
                .par_iter_mut()
                .enumerate()
                .try_for_each(|(i, b)| -> Result<()> {
                    ensure!(archive.read_into(i, 0, b)? == b.len(), "Short read");
                    Ok(())
                })
        })?;
        let warm = started.elapsed().as_secs_f64();
        let bytes: usize = outputs.iter().map(Vec::len).sum();
        for (i, b) in outputs.iter().enumerate() {
            if let Some(f) = &archive.index.entries[i].frame {
                let pixels = cdng_image::dng::decode(b)?;
                let original = f.raw_sha256.clone();
                let mut raw = Vec::with_capacity(pixels.len() * 2);
                for p in pixels {
                    raw.extend(p.to_le_bytes());
                }
                ensure!(cdng_image::hash(&raw) == original, "Decoded DNG mismatch");
            }
        }
        let row = serde_json::json!({"repeat":repeat,"frames":outputs.len(),"cold_decode_fps":outputs.len() as f64/cold,"cold_seconds":cold,"cache_copy_seconds":warm,"cache_copy_gb_per_second":bytes as f64/warm/1e9,"stats_after_cold":after_cold,"stats_after_cached":archive.stats()});
        println!("{row}");
        results.push(row);
    }
    let archive = Arc::new(Archive::open(&path, 256 << 20)?);
    let mut seek = Vec::new();
    for (i, e) in archive.index.entries.iter().enumerate() {
        if let Some(f) = &e.frame {
            let mut bytes = [0; 4096];
            let start = Instant::now();
            archive.read_into(i, f.header_len as u64, &mut bytes)?;
            seek.push(start.elapsed().as_secs_f64());
        }
    }
    let disk = VirtualDisk::new(archive)?;
    let mut header = [0; 2048];
    disk.read_sectors(64, &mut header)?;
    ensure!(&header[1..6] == b"CD001", "Invalid ISO descriptor");
    println!(
        "{}",
        serde_json::json!({"cold_seek_seconds":seek,"virtual_disk":disk.stats(),"trials":results,"scope":"Cached source bytes; cold frame cache then hot frame cache. Caller output buffers allocated before timing; CPU libjxl with 8 frames in parallel; no actual OS mount, physical disk or Resolve rendering."})
    );
    Ok(())
}
