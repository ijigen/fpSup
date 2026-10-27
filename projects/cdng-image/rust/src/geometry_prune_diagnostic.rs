//! Opt-in, read-only opportunity screen. This does not alter the encoder path.
use super::*;
use std::path::{Path, PathBuf};
use std::time::Instant;

fn collect_dngs(path: &Path, groups: &mut BTreeMap<PathBuf, Vec<PathBuf>>) -> Result<()> {
    for entry in std::fs::read_dir(path)? {
        let entry = entry?;
        let file_type = entry.file_type()?;
        let path = entry.path();
        if file_type.is_dir() {
            collect_dngs(&path, groups)?;
        } else if file_type.is_file()
            && path.extension().is_some_and(|s| s.eq_ignore_ascii_case("dng"))
        {
            groups.entry(path.parent().unwrap().to_owned()).or_default().push(path);
        }
    }
    Ok(())
}

fn container_size(image: &Image, tile_count: usize, payload: usize) -> usize {
    let prefix_and_payload = image.prefix + payload;
    let alignment = prefix_and_payload % 2;
    let tags = image.tags.keys().filter(|tag| !LAYOUT.contains(tag)).count() + 5;
    prefix_and_payload + alignment + if tile_count > 1 { tile_count * 8 } else { 0 }
        + 6 + tags * 12
}

#[test]
#[ignore = "Read-only real-media Metal diagnostic; run alone with CDNG_GEOMETRY_SCREEN_SOURCE"]
fn real_media_geometry_lower_bound_screen() -> Result<()> {
    let root = std::env::var_os("CDNG_GEOMETRY_SCREEN_SOURCE")
        .map(PathBuf::from).context("Set CDNG_GEOMETRY_SCREEN_SOURCE")?;
    let mut groups = BTreeMap::new();
    collect_dngs(&root, &mut groups)?;
    ensure!(!groups.is_empty(), "No DNG clips found");
    let gpu = Gpu::new(Backend::Metal)?;
    ensure!(gpu.entropy_enabled(), "Metal entropy must be enabled");
    let cancel = AtomicBool::new(false);
    for (clip, mut frames) in groups {
        frames.sort();
        let mut indices = vec![0, frames.len() / 2, frames.len() - 1];
        indices.dedup();
        for index in indices {
            let path = &frames[index];
            let data = std::fs::read(path)?;
            let source_sha = crate::hash(&data);
            let image = read(&data, true)?;
            let geometries = prepare_search(&image, Effort::Max, Some(&gpu), &cancel, None)?;
            let mut rows = Vec::new();
            let mut bounds = Vec::new();
            let mut actuals = Vec::new();
            let mut payload_hashes = Vec::new();
            for geometry in &geometries {
                let (tw, th) = (geometry.tw, geometry.th);
                let rankings = geometry.rankings.as_ref().context("Missing rankings")?;
                let histograms = geometry.histograms.as_ref().context("Missing histograms")?;
                let tiles = geometry.tiles.as_ref().context("Missing shared tiles")?;
                let predictors: [Vec<u8>; 2] = std::array::from_fn(|attempt| {
                    rankings.iter().map(|rank| rank[attempt]).collect()
                });
                let started = Instant::now();
                let first_bounds = crate::gpu_prune::lower_bounds(tw * th, (tw * 2) as u32,
                    image.bits as u32, &predictors[0], histograms)?;
                let second_bounds = crate::gpu_prune::lower_bounds(tw * th, (tw * 2) as u32,
                    image.bits as u32, &predictors[1], histograms)?;
                let payload_bound: usize = first_bounds.iter().zip(&second_bounds)
                    .map(|(&first, &second)| first.min(second)).sum();
                let lower = container_size(&image, rankings.len(), payload_bound);
                let bound_plan_seconds = started.elapsed().as_secs_f64();
                let started = Instant::now();
                let mut first = gpu.encode_shared_tiles_bounded(tiles, tw * th, (tw * 2) as u32,
                    image.bits as u32, &predictors[0], histograms, None)?;
                let maximum: Vec<usize> = first.iter().map(Vec::len).collect();
                let second = gpu.encode_shared_tiles_bounded(tiles, tw * th, (tw * 2) as u32,
                    image.bits as u32, &predictors[1], histograms, Some(&maximum))?;
                for (old, new) in first.iter_mut().zip(second) {
                    if !new.is_empty() && new.len() < old.len() { *old = new; }
                }
                let encode_verify_seconds = started.elapsed().as_secs_f64();
                for (i, payload) in first.iter().enumerate() {
                    ensure!(first_bounds[i].min(second_bounds[i]) <= payload.len(), "Invalid tile bound");
                }
                let payload_actual: usize = first.iter().map(Vec::len).sum();
                let actual = container_size(&image, rankings.len(), payload_actual);
                ensure!(lower <= actual, "Invalid full-container bound");
                let mut payload_hasher = crate::digest::Sha256::new();
                for payload in &first { payload_hasher.update(payload); }
                let payload_sha256 = format!("{:x}", payload_hasher.finalize());
                rows.push(serde_json::json!({"width":tw,"height":th,"tiles":rankings.len(),
                    "estimated_bits_not_a_bound":geometry.estimated_bits,
                    "exact_jpeg_lower_bound_sum":payload_bound,"full_dng_lower_bound":lower,
                    "full_dng_actual_bytes":actual,"stuffing_slack_bytes":actual-lower,
                    "bound_planning_seconds":bound_plan_seconds,"encode_verify_seconds":encode_verify_seconds,
                    "payload_sha256":payload_sha256}));
                payload_hashes.push(payload_sha256);
                bounds.push(lower);
                actuals.push(actual);
            }
            // Priority zero is source passthrough, one is adaptive, two is the
            // alternative. This models the existing strict-size tie behavior.
            let expected = std::iter::once((data.len(), 0)).chain(actuals.iter()
                .enumerate().map(|(i, &size)| (size, i + 1))).min().unwrap();
            let simulate = |order: Vec<usize>| -> Result<serde_json::Value> {
                let mut selected = (data.len(), 0);
                let mut skipped = Vec::new();
                for i in order {
                    if (bounds[i], i + 1) >= selected {
                        skipped.push(i);
                    } else if (actuals[i], i + 1) < selected {
                        selected = (actuals[i], i + 1);
                    }
                }
                ensure!(selected == expected, "Pruning changed selected geometry or tie identity");
                Ok(serde_json::json!({"skipped_geometries":skipped,"selected_priority":selected.1,
                    "output_bytes":selected.0}))
            };
            let original_order = simulate((0..geometries.len()).collect())?;
            let reverse_order = simulate((0..geometries.len()).rev().collect())?;
            let (output, info) = compress(&data, Effort::Max, Backend::Metal, Some(&gpu), &cancel)?;
            ensure!(output.len() == expected.0 && info.pixel_verified, "Diagnostic and product disagree");
            if expected.1 == 0 {
                ensure!(output == data, "Source passthrough bytes differ");
            } else {
                let selected = &geometries[expected.1 - 1];
                let output_tags = entries(&output, u32at(&output, 4)? as usize)?;
                ensure!(scalar(&output_tags, &output, 322, None)? == selected.tw
                    && scalar(&output_tags, &output, 323, None)? == selected.th,
                    "Diagnostic and product geometry differ");
                let offsets = output_tags[&324].values(&output)?;
                let sizes = output_tags[&325].values(&output)?;
                let mut hasher = crate::digest::Sha256::new();
                for (&offset, &size) in offsets.iter().zip(&sizes) {
                    hasher.update(&output[offset..offset + size]);
                }
                ensure!(format!("{:x}", hasher.finalize()) == payload_hashes[expected.1 - 1],
                    "Diagnostic and product selected JPEG bytes differ");
            }
            ensure!(decode(&output)? == image.pixels, "Diagnostic product output changed RAW");
            ensure!(crate::hash(&data) == source_sha, "Source buffer changed");
            println!("CDNG_GEOMETRY_SCREEN {}", serde_json::json!({"source":path,"clip":clip,
                "frame_index":index,"clip_frames":frames.len(),"source_bytes":data.len(),
                "source_sha256":source_sha,"pixel_sha256":info.pixel_sha256,
                "output_sha256":crate::hash(&output),"geometries":rows,
                "original_order":original_order,"reverse_order":reverse_order,
                "scope":"Read-only applicability screen, not whole-product timing"}));
        }
    }
    Ok(())
}

// Pure CPU model of a possible future histogram organization. The production
// GPU path still uses its current independent per-geometry histogram pass.
struct MacroHistograms {
    width: usize,
    height: usize,
    cells: Vec<[u32; 238]>,
}

fn padded_sample(image: &Image, mut x: usize, mut y: usize) -> u16 {
    if x >= image.width { x = image.width - 2 + (x - image.width) % 2; }
    if y >= image.height { y = image.height - 2 + (y - image.height) % 2; }
    image.pixels[y * image.width + x]
}

fn histogram_indices(image: &Image, x: usize, y: usize,
    tile_x: usize, tile_y: usize, tile_width: usize) -> [usize; 7]
{
    let (local_x, local_y) = (x - tile_x, y - tile_y);
    let col = (local_y % 2) * tile_width + local_x;
    let row = local_y / 2;
    let a = if col >= 2 {
        if local_x >= 2 { padded_sample(image, x - 2, y) }
        else { padded_sample(image, tile_x + tile_width - 2 + local_x, y - 1) }
    } else { 0 } as i32;
    let b = if row > 0 { padded_sample(image, x, y - 2) } else { 0 } as i32;
    let c = if row > 0 && col >= 2 {
        if local_x >= 2 { padded_sample(image, x - 2, y - 2) }
        else { padded_sample(image, tile_x + tile_width - 2 + local_x, y - 3) }
    } else { 0 } as i32;
    let sample = padded_sample(image, x, y) as i32;
    let interior = [a, b, c, a + b - c, a + ((b - c) >> 1), b + ((a - c) >> 1), (a + b) >> 1];
    std::array::from_fn(|p| {
        let prediction = if row == 0 && col < 2 { 1 << (image.bits - 1) }
            else if row == 0 { a } else if col < 2 { b } else { interior[p] };
        let difference = (sample - prediction) as i16 as i32;
        let magnitude = difference.unsigned_abs();
        let category = if magnitude == 0 { 0 } else { 32 - magnitude.leading_zeros() };
        p * 34 + local_x % 2 * 17 + category as usize
    })
}

fn macro_histograms(image: &Image, geometries: &[(usize, usize)]) -> MacroHistograms {
    let width = geometries.iter().map(|&(tw, _)| image.width.div_ceil(tw) * tw)
        .max().unwrap().next_multiple_of(64);
    let height = geometries.iter().map(|&(_, th)| image.height.div_ceil(th) * th)
        .max().unwrap().next_multiple_of(64);
    let mut cells = Vec::with_capacity(width / 64 * (height / 64));
    for y0 in (0..height).step_by(64) {
        for x0 in (0..width).step_by(64) {
            let mut hist = [0u32; 238];
            for y in y0..y0 + 64 {
                for x in x0..x0 + 64 {
                    for at in histogram_indices(image, x, y, 0, 0, width) { hist[at] += 1; }
                }
            }
            cells.push(hist);
        }
    }
    MacroHistograms { width, height, cells }
}

fn reused_geometry_histograms(image: &Image, base: &MacroHistograms,
    tw: usize, th: usize) -> (Vec<u32>, usize, usize, usize)
{
    let mut output = Vec::new();
    let (mut fringe, mut corrected, mut aggregated_bins) = (0, 0, 0);
    for tile_y in (0..image.height).step_by(th) {
        for tile_x in (0..image.width).step_by(tw) {
            let (x0, y0) = (tile_x.next_multiple_of(64), tile_y.next_multiple_of(64));
            let (x1, y1) = ((tile_x + tw) / 64 * 64, (tile_y + th) / 64 * 64);
            let has_full = x0 < x1 && y0 < y1;
            let mut hist = [0u32; 238];
            if has_full {
                for y in (y0..y1).step_by(64) {
                    for x in (x0..x1).step_by(64) {
                        let cell = &base.cells[y / 64 * (base.width / 64) + x / 64];
                        for (n, &part) in hist.iter_mut().zip(cell) { *n += part; }
                        aggregated_bins += 238;
                    }
                }
            }
            for y in tile_y..tile_y + th {
                for x in tile_x..tile_x + tw {
                    let inside_full = has_full && x >= x0 && x < x1 && y >= y0 && y < y1;
                    if inside_full {
                        // Only the first two sensor rows/columns differ from
                        // the shared interior predictor. Odd sensor rows wrap
                        // left to the preceding sensor row's tile end.
                        if x - tile_x >= 2 && y - tile_y >= 2 { continue; }
                        for at in histogram_indices(image, x, y, 0, 0, base.width) {
                            hist[at] = hist[at].checked_sub(1).expect("Base correction underflow");
                        }
                        corrected += 1;
                    } else { fringe += 1; }
                    for at in histogram_indices(image, x, y, tile_x, tile_y, tw) { hist[at] += 1; }
                }
            }
            output.extend(hist);
        }
    }
    (output, fringe, corrected, aggregated_bins)
}

#[test]
#[ignore = "Pure CPU structural histogram equivalence screen; run separately from timing"]
fn macroblock_histogram_reuse_matches_independent_scalar() {
    let cases: &[(usize, usize, &[(usize, usize)])] = &[
        (2, 2, &[(16, 16), (32, 64), (64, 32)]),
        (18, 34, &[(16, 32), (32, 16), (64, 64)]),
        (126, 130, &[(16, 16), (32, 64), (64, 32), (128, 64)]),
        (130, 194, &[(48, 80), (64, 64), (128, 64)]),
        (434, 290, &[(432, 288), (256, 256), (512, 256), (1024, 512)]),
    ];
    let mut comparisons = 0;
    let mut bins = 0;
    let mut pixels_checked = 0;
    for bits in [8, 10, 12, 14, 16] {
        for &(width, height, geometries) in cases {
            let mask = (1u32 << bits) - 1;
            let pixels = (0..width * height).map(|i| {
                let x = i % width;
                let y = i / width;
                let value = (i as u32).wrapping_mul(0x9e3779b9).rotate_left((y % 31) as u32)
                    ^ ((x as u32) << 11) ^ ((y as u32) << 3);
                match i % 13 { 0 => 0, 1 => mask as u16, _ => (value & mask) as u16 }
            }).collect();
            let image = Image { width, height, bits, pixels, prefix: 0, tags: BTreeMap::new() };
            let base = macro_histograms(&image, geometries);
            assert_eq!(base.cells.len() * 4096, base.width * base.height);
            for &(tw, th) in geometries {
                let (actual, _, _, _) = reused_geometry_histograms(&image, &base, tw, th);
                let mut expected = Vec::new();
                let mut tile = vec![0; tw * th];
                for y in (0..height).step_by(th) {
                    for x in (0..width).step_by(tw) {
                        fill_tile(&image, x, y, tw, th, &mut tile);
                        expected.extend(crate::gpu::reference(&tile, (tw * 2) as u32, bits as u32,
                            &[1, 2, 3, 4, 5, 6, 7]));
                        pixels_checked += tile.len();
                    }
                }
                assert_eq!(actual, expected, "{bits} bits {width}x{height} geometry {tw}x{th}");
                comparisons += 1;
                bins += actual.len();
            }
        }
    }
    println!("CDNG_MACRO_HISTOGRAM_SCREEN {}", serde_json::json!({
        "geometry_comparisons":comparisons,"all_bins_compared":bins,
        "independent_reference_pixels":pixels_checked,"depths":[8,10,12,14,16],
        "predictors":[1,2,3,4,5,6,7],"all_exact":true,
        "scope":"Pure CPU equivalence proof only; no Metal implementation or speed claim"}));
}

#[test]
#[ignore = "Pure CPU real-media histogram equivalence; set CDNG_GEOMETRY_SCREEN_SOURCE"]
fn macroblock_histogram_real_media_matches_independent_scalar() -> Result<()> {
    let root = std::env::var_os("CDNG_GEOMETRY_SCREEN_SOURCE")
        .map(PathBuf::from).context("Set CDNG_GEOMETRY_SCREEN_SOURCE")?;
    let mut groups = BTreeMap::new();
    collect_dngs(&root, &mut groups)?;
    ensure!(!groups.is_empty(), "No DNG clips found");
    for (clip, mut frames) in groups {
        frames.sort();
        let image = read(&std::fs::read(&frames[0])?, true)?;
        let adaptive = adaptive_geometry(image.width, image.height);
        let mut geometries = vec![adaptive];
        geometries.extend([(256, 256), (512, 256), (1024, 512)].into_iter().filter(|&g| g != adaptive));
        let base = macro_histograms(&image, &geometries);
        let mut rows = Vec::new();
        for &(tw, th) in &geometries {
            let (actual, fringe, corrected, bins_read) = reused_geometry_histograms(&image, &base, tw, th);
            let mut expected = Vec::new();
            let mut tile = vec![0; tw * th];
            let mut reference_pixels = 0;
            for y in (0..image.height).step_by(th) {
                for x in (0..image.width).step_by(tw) {
                    fill_tile(&image, x, y, tw, th, &mut tile);
                    expected.extend(crate::gpu::reference(&tile, (tw * 2) as u32, image.bits as u32,
                        &[1, 2, 3, 4, 5, 6, 7]));
                    reference_pixels += tile.len();
                }
            }
            ensure!(actual == expected, "Real-media histogram mismatch: {:?} {tw}x{th}", frames[0]);
            rows.push(serde_json::json!({"width":tw,"height":th,"compared_bins":actual.len(),
                "reference_pixels":reference_pixels,"direct_fringe_pixels":fringe,
                "corrected_boundary_pixels":corrected,"aggregate_bin_reads":bins_read}));
        }
        println!("CDNG_MACRO_REAL_SCREEN {}", serde_json::json!({"source":frames[0],"clip":clip,
            "width":image.width,"height":image.height,"bits":image.bits,"geometries":rows,
            "base_width":base.width,"base_height":base.height,"base_histogram_bytes":base.cells.len()*238*4,
            "all_bins_exact":true,"scope":"Pure CPU equivalence only; not a speed measurement"}));
    }
    Ok(())
}
