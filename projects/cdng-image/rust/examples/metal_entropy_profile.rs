//! Repeated exact Metal entropy encoding and full RAW verification, with source
//! decoding and histogram search outside timing. No source/output files change.
use anyhow::{Context, Result, ensure};
use cdng_image::{Backend, gpu::Gpu};
use std::{hint::black_box, time::Instant};

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let source = args.next().context("SOURCE WIDTH HEIGHT [REPEATS]")?;
    let width: usize = args.next().context("WIDTH")?.parse()?;
    let height: usize = args.next().context("HEIGHT")?.parse()?;
    let repeats: usize = args.next().map(|s| s.parse()).transpose()?.unwrap_or(80);
    let pixels = cdng_image::dng::decode(&std::fs::read(&source)?)?;
    ensure!(pixels.len() == width * height, "Wrong source dimensions");
    let grid = ((pixels.len() as f64 / 131072.).sqrt().round() as usize).max(1);
    let tw = width.div_ceil(grid).next_multiple_of(16).clamp(16, 65520);
    let th = height.div_ceil(grid).next_multiple_of(16).clamp(16, 65520);
    let nx = width.div_ceil(tw);
    let mut tiled = vec![0u16; nx * height.div_ceil(th) * tw * th];
    for (i, tile) in tiled.chunks_exact_mut(tw * th).enumerate() {
        let (x, y) = ((i % nx) * tw, (i / nx) * th);
        let (vw, vh) = (tw.min(width - x), th.min(height - y));
        for yy in 0..vh {
            tile[yy * tw..yy * tw + vw].copy_from_slice(&pixels[(y + yy) * width + x..(y + yy) * width + x + vw]);
            for xx in vw..tw { tile[yy * tw + xx] = tile[yy * tw + xx - 2]; }
        }
        for yy in vh..th {
            for xx in 0..tw { tile[yy * tw + xx] = tile[yy.saturating_sub(2) * tw + xx]; }
        }
    }
    let gpu = Gpu::new(Backend::Metal)?;
    let (ranked, _, hist) = gpu.analyze_tiles(&tiled, tw * th, (tw * 2) as u32, 12, &[1, 2, 3, 4, 5, 6, 7])?;
    let predictors: Vec<_> = ranked.iter().map(|rank| rank[0]).collect();
    let expected = gpu.encode_tiles(&tiled, tw * th, (tw * 2) as u32, 12, &predictors, &hist)?;
    for (blob, tile) in expected.iter().zip(tiled.chunks_exact(tw * th)) {
        ensure!(ljpeg_reference::Decoder::new(blob).unwrap().decode().unwrap() == tile, "Independent RAW mismatch");
    }
    let mut elapsed = Vec::new();
    for _ in 0..repeats {
        let started = Instant::now();
        let actual = gpu.encode_tiles(&tiled, tw * th, (tw * 2) as u32, 12, &predictors, &hist)?;
        elapsed.push(started.elapsed().as_secs_f64());
        ensure!(actual == expected, "Entropy bytes changed");
        black_box(actual);
    }
    println!("{}", serde_json::json!({"source": source, "width": width, "height":height, "tile":[tw,th], "seconds":elapsed, "bytes":expected.iter().map(Vec::len).sum::<usize>(), "independent_raw_verified":true, "all_repeated_bytes_identical":true}));
    Ok(())
}
