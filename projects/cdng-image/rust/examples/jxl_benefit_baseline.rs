//! Cached production LJ92 codec benchmark for comparison with the JXL study.
use anyhow::{Context, Result, ensure};
use cdng_image::{Backend, Effort, dng, gpu::Gpu};
use rayon::prelude::*;
use serde_json::json;
use std::{fs, path::PathBuf, sync::atomic::AtomicBool, time::Instant};

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args_os().collect();
    ensure!(
        args.len() == 3 || args.len() == 4,
        "SOURCE OUTPUT_DIRECTORY [read]"
    );
    let source = PathBuf::from(&args[1]);
    let output = PathBuf::from(&args[2]);
    fs::create_dir_all(&output)?;
    let frames: Vec<_> = (0..16)
        .map(|i| fs::read(source.join(format!("frame_{i:06}.dng"))))
        .collect::<std::io::Result<_>>()?;
    let pixels: Vec<_> = frames
        .iter()
        .map(|f| dng::decode(f))
        .collect::<Result<_>>()?;
    let pool = rayon::ThreadPoolBuilder::new().num_threads(8).build()?;
    if args.len() == 4 && args[3] == "read" {
        let mut trials = Vec::new();
        for _ in 0..3 {
            let start = Instant::now();
            pool.install(|| {
                frames
                    .par_iter()
                    .enumerate()
                    .try_for_each(|(i, blob)| -> Result<()> {
                        ensure!(dng::decode(blob)? == pixels[i], "RAW mismatch");
                        Ok(())
                    })
            })?;
            trials.push(start.elapsed().as_secs_f64());
        }
        let mut latencies = Vec::new();
        for (blob, expected) in frames.iter().zip(&pixels) {
            let start = Instant::now();
            let decoded = dng::decode(blob)?;
            latencies.push(start.elapsed().as_secs_f64());
            ensure!(&decoded == expected, "RAW mismatch");
        }
        let row = json!({"frames":16,"workers":8,"trials":trials,
            "single_frame_latency_seconds":latencies,"raw_exact":true,
            "scope":"Cached production LJ92 DNG decoder, no disk I/O, whole-frame CPU decode; no tile threading within a frame."});
        println!("{row}");
        fs::write(
            output.join("read-timings.json"),
            serde_json::to_vec_pretty(&row)?,
        )?;
        return Ok(());
    }
    let gpu = Gpu::new(Backend::Metal)?;
    let cancel = AtomicBool::new(false);
    let mut rows = Vec::new();
    // Compile kernels and populate codec caches before reporting timed trials.
    let _ = dng::compress(
        &frames[0],
        Effort::Balanced,
        Backend::Metal,
        Some(&gpu),
        &cancel,
    )?;
    for repeat in 0..3 {
        let start = Instant::now();
        let encoded = pool.install(|| {
            (0..128)
                .into_par_iter()
                .map(|i| {
                    dng::compress(
                        &frames[i % 16],
                        Effort::Balanced,
                        Backend::Metal,
                        Some(&gpu),
                        &cancel,
                    )
                })
                .collect::<Result<Vec<_>>>()
        })?;
        let encode_verify_seconds = start.elapsed().as_secs_f64();
        let start = Instant::now();
        pool.install(|| {
            encoded
                .par_iter()
                .enumerate()
                .try_for_each(|(i, (blob, _))| -> Result<()> {
                    ensure!(dng::decode(blob)? == pixels[i % 16], "RAW mismatch");
                    Ok(())
                })
        })?;
        let decode_verify_seconds = start.elapsed().as_secs_f64();
        let row = json!({"repeat": repeat, "frames":128, "workers":8,
            "encode_verify_seconds":encode_verify_seconds,
            "encode_verify_fps":128.0/encode_verify_seconds,
            "decode_verify_seconds":decode_verify_seconds,
            "decode_verify_fps":128.0/decode_verify_seconds,
            "dng_bytes":encoded.iter().map(|v| v.0.len()).sum::<usize>(),
            "raw_exact":true});
        println!("{row}");
        rows.push(row);
        if repeat == 0 {
            for (i, (blob, _)) in encoded.iter().take(16).enumerate() {
                fs::write(output.join(format!("frame_{i:06}.dng")), blob)?;
            }
        }
        fs::write(
            output.join("timings.json"),
            serde_json::to_vec_pretty(&rows)?,
        )
        .context("write timings")?;
    }
    Ok(())
}
