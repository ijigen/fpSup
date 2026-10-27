//! Exact geometry histograms; source decoding, encoder and file I/O are outside
//! the repeated timing. Diagnostic only; it writes no source or output media.
use anyhow::{Context, Result, ensure};
use cdng_image::{Backend, gpu::Gpu};
use std::{hint::black_box, time::Instant};
fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let source = args.next().context("SOURCE WIDTH HEIGHT [REPEATS]")?;
    let width: usize = args.next().context("WIDTH")?.parse()?;
    let height: usize = args.next().context("HEIGHT")?.parse()?;
    let repeats: usize = args.next().map(|s| s.parse()).transpose()?.unwrap_or(160);
    let pixels = cdng_image::dng::decode(&std::fs::read(&source)?)?;
    ensure!(pixels.len() == width * height, "Wrong source dimensions");
    let grid = ((pixels.len() as f64 / 131072.).sqrt().round() as usize).max(1);
    let dimension = |n: usize| n.div_ceil(grid).next_multiple_of(16).clamp(16, 65520);
    let mut geometries = vec![(dimension(width), dimension(height))];
    for geometry in [(256, 256), (512, 256), (1024, 512)] {
        if !geometries.contains(&geometry) { geometries.push(geometry); }
    }
    let gpu = Gpu::new(Backend::Metal)?;
    let predictors = [1, 2, 3, 4, 5, 6, 7];
    let expected = gpu.histogram_geometries(&pixels, width, height, 12, &predictors, &geometries)?;
    let mut elapsed = Vec::new();
    for _ in 0..repeats {
        let started = Instant::now();
        let actual = gpu.histogram_geometries(&pixels, width, height, 12, &predictors, &geometries)?;
        elapsed.push(started.elapsed().as_secs_f64());
        ensure!(actual == expected, "Histogram changed");
        black_box(actual);
    }
    println!("{}", serde_json::json!({"source": source, "width": width, "height":height, "geometries":geometries, "seconds":elapsed, "histograms":expected, "all_repeated_histograms_identical":true}));
    Ok(())
}
