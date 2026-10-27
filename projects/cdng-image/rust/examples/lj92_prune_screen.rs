//! Bounded CPU-only screen of exact second-predictor dominance on a real frame.
//! Usage: lj92_prune_screen SOURCE_DNG [WIDTH HEIGHT BITS].
#[path = "../src/gpu_prune.rs"]
mod gpu_prune;

use anyhow::{Context, Result, ensure};
use cdng_image::gpu::{Gpu, reference};

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let source = args.next().context("SOURCE_DNG [WIDTH HEIGHT BITS]")?;
    let width: usize = args.next().map(|s| s.parse()).transpose()?.unwrap_or(3024);
    let height: usize = args.next().map(|s| s.parse()).transpose()?.unwrap_or(2010);
    let bits: u32 = args.next().map(|s| s.parse()).transpose()?.unwrap_or(12);
    let pixels = cdng_image::dng::decode(&std::fs::read(&source)?)?;
    ensure!(pixels.len() == width * height, "Source dimensions differ");
    let grid = ((width as f64 * height as f64 / 131072.).sqrt().round() as usize).max(1);
    let dimension = |n: usize| n.div_ceil(grid).next_multiple_of(16).clamp(16, 65520);
    let adaptive = (dimension(width), dimension(height));
    let mut geometries = vec![adaptive];
    for geometry in [(256, 256), (512, 256), (1024, 512)] {
        if geometry != adaptive {
            geometries.push(geometry);
        }
    }
    let predictors = [1, 2, 3, 4, 5, 6, 7];
    let mut prepared = Vec::new();
    for &(tw, th) in &geometries {
        let nx = width.div_ceil(tw);
        let mut tiles = vec![0u16; nx * height.div_ceil(th) * tw * th];
        for (i, tile) in tiles.chunks_exact_mut(tw * th).enumerate() {
            let (x, y) = ((i % nx) * tw, (i / nx) * th);
            let (vw, vh) = (tw.min(width - x), th.min(height - y));
            for yy in 0..vh {
                tile[yy * tw..yy * tw + vw]
                    .copy_from_slice(&pixels[(y + yy) * width + x..(y + yy) * width + x + vw]);
                for xx in vw..tw {
                    tile[yy * tw + xx] = tile[yy * tw + xx - 2];
                }
            }
            for yy in vh..th {
                for xx in 0..tw {
                    tile[yy * tw + xx] = tile[yy.saturating_sub(2) * tw + xx];
                }
            }
        }
        let histograms: Vec<u32> = tiles
            .chunks_exact(tw * th)
            .flat_map(|tile| reference(tile, (tw * 2) as u32, bits, &predictors))
            .collect();
        let (rankings, estimate) = Gpu::analyze_histograms(&histograms, &predictors)?;
        prepared.push((tiles, histograms, rankings, estimate));
    }
    let alternative = prepared
        .iter()
        .enumerate()
        .skip(1)
        .filter(|(_, p)| p.3 < prepared[0].3)
        .min_by_key(|(_, p)| p.3)
        .map(|(i, _)| i);
    let (mut tile_count, mut dominated, mut actual_second_wins) = (0, 0, 0);
    let mut rows = Vec::new();
    for (geometry_index, (&(tw, th), (tiles, histograms, rankings, _))) in
        geometries.iter().zip(&prepared).enumerate()
    {
        if geometry_index != 0 && Some(geometry_index) != alternative {
            continue;
        }
        let second_predictors: Vec<u8> = rankings.iter().map(|r| r[1]).collect();
        let bounds = gpu_prune::lower_bounds(
            tw * th,
            (tw * 2) as u32,
            bits,
            &second_predictors,
            histograms,
        )?;
        let (mut local_dominated, mut local_wins, mut total_bound_gap) = (0, 0, 0usize);
        for (i, tile) in tiles.chunks_exact(tw * th).enumerate() {
            let encode = |predictor| {
                ljpeg::Encoder::new(
                    tw as u16,
                    (th / 2) as u16,
                    ljpeg::Components::C2,
                    ljpeg::Bitdepth::try_from(bits as u8).unwrap(),
                    ljpeg::Predictor::try_from(predictor).unwrap(),
                    0,
                    0,
                )
                .encode(tile)
                .context("CPU JPEG encode failed")
            };
            let first = encode(rankings[i][0])?;
            let second = encode(rankings[i][1])?;
            ensure!(bounds[i] <= second.len(), "Invalid lower bound");
            let prune = bounds[i] >= first.len();
            let full = if second.len() < first.len() {
                &second
            } else {
                &first
            };
            let pruned = if prune || second.len() >= first.len() {
                &first
            } else {
                &second
            };
            ensure!(pruned == full, "Pruning changed selected JPEG bytes");
            local_dominated += usize::from(prune);
            local_wins += usize::from(second.len() < first.len());
            total_bound_gap += second.len() - bounds[i];
        }
        tile_count += rankings.len();
        dominated += local_dominated;
        actual_second_wins += local_wins;
        rows.push(serde_json::json!({"tw":tw,"th":th,"tiles":rankings.len(),"dominated":local_dominated,"actual_second_wins":local_wins,"sum_stuffing_bytes":total_bound_gap}));
    }
    println!(
        "{}",
        serde_json::json!({"source":source,"width":width,"height":height,"bits":bits,"selected_geometries":rows,"tiles":tile_count,"dominated":dominated,"dominated_percent":dominated as f64 / tile_count as f64 * 100.,"actual_second_wins":actual_second_wins,"selected_jpeg_bytes_identical":true,"gpu_used":false,"scope":"One-frame CPU screen; exact bound opportunity, not product speed benchmark"})
    );
    Ok(())
}
