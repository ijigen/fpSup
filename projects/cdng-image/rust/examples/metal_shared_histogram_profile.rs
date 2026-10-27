//! Read-only exact histogram comparison and warmed complete-call timing.
//! Run each native mode in a separate process; no environment is mutated.
//! SOURCE WIDTH HEIGHT BITS [REPEATS]
//! --check-corpus ROOT WIDTH HEIGHT BITS

#[cfg(target_os = "macos")]
mod profile {
    use anyhow::{Context, Result, ensure};
    use cdng_image::{Backend, gpu::Gpu};
    use serde_json::{Value, json};
    use std::{collections::BTreeSet, hint::black_box, path::Path, time::Instant};

    fn geometries(width: usize, height: usize) -> Vec<(usize, usize)> {
        let grid = ((width as f64 * height as f64 / 131072.).sqrt().round() as usize).max(1);
        let dimension = |n: usize| n.div_ceil(grid).next_multiple_of(16).clamp(16, 65520);
        let mut output = vec![(dimension(width), dimension(height))];
        for geometry in [(256, 256), (512, 256), (1024, 512)] {
            if !output.contains(&geometry) { output.push(geometry); }
        }
        output
    }

    /// Independent scalar predictor reference over explicitly filled tiles.
    /// Deliberately shares neither the native macroblock decomposition nor its
    /// border correction logic. Padding follows the established Bayer fill.
    fn expected_histograms(pixels: &[u16], width: usize, height: usize, bits: u32,
        geometries: &[(usize, usize)], predictors: &[u8]) -> Vec<Vec<u32>> {
        geometries.iter().map(|&(tw, th)| {
            let mut histograms = Vec::new();
            let mut tile = vec![0; tw * th];
            for y in (0..height).step_by(th) {
                for x in (0..width).step_by(tw) {
                    let (vw, vh) = (tw.min(width - x), th.min(height - y));
                    for yy in 0..vh {
                        tile[yy * tw..yy * tw + vw].copy_from_slice(
                            &pixels[(y + yy) * width + x..(y + yy) * width + x + vw]);
                        for xx in vw..tw { tile[yy * tw + xx] = tile[yy * tw + xx - 2]; }
                    }
                    for yy in vh..th {
                        for xx in 0..tw { tile[yy * tw + xx] = tile[yy.saturating_sub(2) * tw + xx]; }
                    }
                    histograms.extend(cdng_image::gpu::reference(&tile, (tw * 2) as u32, bits, predictors));
                }
            }
            histograms
        }).collect()
    }

    fn run_source(gpu: &Gpu, source: &Path, width: usize, height: usize, bits: u32,
        repeats: usize) -> Result<Value> {
        let source = source.canonicalize()?;
        let bytes = std::fs::read(&source).with_context(|| format!("Read {}", source.display()))?;
        let source_sha256 = cdng_image::hash(&bytes);
        let pixels = cdng_image::dng::decode(&bytes)?;
        drop(bytes);
        ensure!(width.checked_mul(height) == Some(pixels.len()), "Source dimensions differ: {}", source.display());
        ensure!(pixels.iter().all(|&v| u32::from(v) < (1u32 << bits)), "Sample exceeds supplied bit depth");
        let geometries = geometries(width, height);
        let predictors = [1, 2, 3, 4, 5, 6, 7];
        let expected = expected_histograms(&pixels, width, height, bits, &geometries, &predictors);
        let warmup_calls = if repeats == 0 { 1 } else { 3 };
        for _ in 0..warmup_calls {
            let actual = gpu.histogram_geometries(&pixels, width, height, bits, &predictors, &geometries)?;
            ensure!(actual == expected, "Independent full histogram mismatch: {}", source.display());
            black_box(actual);
        }
        let mut seconds = Vec::with_capacity(repeats);
        for _ in 0..repeats {
            let started = Instant::now();
            let actual = gpu.histogram_geometries(&pixels, width, height, bits, &predictors, &geometries)?;
            seconds.push(started.elapsed().as_secs_f64());
            ensure!(actual == expected, "Repeated full histogram mismatch: {}", source.display());
            black_box(actual);
        }
        // Hash every scalar-verified bin after timing, in geometry/tile/bin order.
        let serialized: Vec<_> = expected.iter().flatten().flat_map(|v| v.to_le_bytes()).collect();
        let histogram_sha256 = cdng_image::hash(&serialized);
        Ok(json!({
            "source":source, "source_sha256":source_sha256,
            "width":width, "height":height, "bits":bits, "geometries":geometries,
            "predictors":predictors, "seconds":seconds, "warmup_calls":warmup_calls,
            "histogram_sha256":histogram_sha256,
            "histogram_bins":expected.iter().map(Vec::len).sum::<usize>(),
            "independent_reference_exact":true, "all_repeated_histograms_identical":true,
            "shared_histogram_mode":std::env::var("CDNG_METAL_SHARED_HISTOGRAM").unwrap_or_else(|_| "default".into()),
            "scope":"Complete warmed histogram_geometries call wall time, including native buffers, GPU completion and owned result allocation. Excludes file read, RAW decode, scalar verification, digest, final encoding and image writing. Dimensions/bit depth supplied by caller; decoded length/sample range validated. Not a whole-product speed measurement."
        }))
    }

    pub fn run() -> Result<()> {
        let args: Vec<_> = std::env::args().skip(1).collect();
        let corpus = args.first().is_some_and(|arg| arg == "--check-corpus");
        let args = if corpus { &args[1..] } else { &args[..] };
        ensure!(if corpus { args.len() == 4 } else { (4..=5).contains(&args.len()) },
            "SOURCE WIDTH HEIGHT BITS [REPEATS], or --check-corpus ROOT WIDTH HEIGHT BITS");
        let source = Path::new(&args[0]);
        let width: usize = args[1].parse()?;
        let height: usize = args[2].parse()?;
        let bits: u32 = args[3].parse()?;
        ensure!(width >= 2 && height >= 2 && width.is_multiple_of(2) && height.is_multiple_of(2)
            && width.checked_mul(height).is_some_and(|n| n <= u32::MAX as usize)
            && (8..=16).contains(&bits), "Invalid diagnostic dimensions or bit depth");
        let gpu = Gpu::new(Backend::Metal)?;
        let output = if corpus {
            let clips = cdng_image::pack::list_clips(source)?;
            let mut rows = Vec::new();
            for clip in &clips {
                if clip.frames.is_empty() { continue; }
                let samples = BTreeSet::from([0, clip.frames.len() / 2, clip.frames.len() - 1]);
                for index in samples {
                    let mut row = run_source(&gpu, &clip.frames[index], width, height, bits, 0)?;
                    row["clip"] = json!(clip.relative);
                    row["frame_index"] = json!(index);
                    row["clip_frames"] = json!(clip.frames.len());
                    rows.push(row);
                }
            }
            ensure!(!rows.is_empty(), "No DNG frames found");
            json!({"source":source.canonicalize()?, "clips":clips.len(), "frames":rows.len(),
                "rows":rows, "independent_reference_exact":true,
                "scope":"Read-only first/middle/last frame checks per clip against every scalar histogram bin. No speed measurement."})
        } else {
            let repeats: usize = args.get(4).map(|s| s.parse()).transpose()?.unwrap_or(80);
            ensure!((1..=10000).contains(&repeats), "REPEATS must be 1..10000");
            run_source(&gpu, source, width, height, bits, repeats)?
        };
        println!("{output}");
        Ok(())
    }
}

fn main() -> anyhow::Result<()> {
    #[cfg(target_os = "macos")]
    { profile::run() }
    #[cfg(not(target_os = "macos"))]
    { anyhow::bail!("Metal histogram diagnostic requires macOS") }
}
