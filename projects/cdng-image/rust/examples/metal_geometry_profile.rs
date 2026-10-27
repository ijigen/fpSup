//! Diagnostic histogram preparation comparison. All geometries and seven
//! predictors are evaluated; RAW decoding is performed once outside timing.
#[cfg(target_os = "macos")]
fn main() -> anyhow::Result<()> {
    use anyhow::{Context, ensure};
    use cdng_image::{Backend, gpu::Gpu};
    use std::{hint::black_box, time::Instant};
    let mut args = std::env::args().skip(1);
    let source = args.next();
    let width: usize = args.next().map(|s| s.parse()).transpose()?.unwrap_or(3024);
    let height: usize = args.next().map(|s| s.parse()).transpose()?.unwrap_or(2010);
    let pixels = if let Some(ref source) = source {
        cdng_image::dng::decode(&std::fs::read(source).context("Read diagnostic source")?)?
    } else {
        (0..width * height).map(|i| {
            let x = i % width;
            let y = i / width;
            (((x * 2 + y / 2) + ((i as u32).wrapping_mul(23417) >> 24) as usize) & 4095) as u16
        }).collect()
    };
    ensure!(pixels.len() == width * height, "Source dimensions differ");
    let grid = ((width as f64 * height as f64 / 131072.).sqrt().round() as usize).max(1);
    let dimension = |n: usize| n.div_ceil(grid).next_multiple_of(16).clamp(16, 65520);
    let adaptive = (dimension(width), dimension(height));
    let mut geometries = vec![adaptive];
    for geometry in [(256, 256), (512, 256), (1024, 512)] {
        if geometry != adaptive { geometries.push(geometry); }
    }
    let tile = |tw: usize, th: usize| {
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
        tiled
    };
    let gpu = Gpu::new(Backend::Metal)?;
    let predictors = [1, 2, 3, 4, 5, 6, 7];
    let expected: Vec<_> = geometries.iter().map(|&(tw, th)| {
        gpu.analyze_tiles(&tile(tw, th), tw * th, (tw * 2) as u32, 12, &predictors).map(|(_, _, hist)| hist)
    }).collect::<anyhow::Result<_>>()?;
    ensure!(gpu.histogram_geometries(&pixels, width, height, 12, &predictors, &geometries)? == expected, "Histogram parity failed");
    let mut rows = Vec::new();
    for repeat in 0..40 {
        for batched in if repeat % 2 == 0 { [false, true] } else { [true, false] } {
            let started = Instant::now();
            if batched {
                let result = gpu.histogram_geometries(&pixels, width, height, 12, &predictors, &geometries)?;
                let analyzed = result.iter().map(|h| Gpu::analyze_histograms(h, &predictors)).collect::<anyhow::Result<Vec<_>>>()?;
                let alternative = analyzed.iter().enumerate().skip(1).filter(|(_, (_, estimate))| *estimate < analyzed[0].1)
                    .min_by_key(|(_, (_, estimate))| *estimate).map(|(i, _)| i);
                // Include every tiled allocation still required by encoding.
                black_box(tile(adaptive.0, adaptive.1));
                if let Some(i) = alternative {
                    black_box(tile(geometries[i].0, geometries[i].1));
                }
                black_box(analyzed);
                black_box(result);
            } else {
                for &(tw, th) in &geometries {
                    black_box(gpu.analyze_tiles(&tile(tw, th), tw * th, (tw * 2) as u32, 12, &predictors)?);
                }
            }
            rows.push(serde_json::json!({"repeat":repeat,"batched":batched,"seconds":started.elapsed().as_secs_f64()}));
        }
    }
    println!("{}", serde_json::json!({"source":source,"width":width,"height":height,"geometry_count":geometries.len(),"all_histograms_identical":true,"rows":rows,"limits":"Microbenchmark includes histogram ranking and tiled pixels for adaptive plus any selected alternative, excludes source decoding and final entropy encoding. Whole-product benchmark required."}));
    Ok(())
}

#[cfg(not(target_os = "macos"))]
fn main() { panic!("Metal histogram diagnostic requires macOS"); }
