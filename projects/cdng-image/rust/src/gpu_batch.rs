//! Metal histogram search from one untiled source image. Candidate geometries
//! retain exactly the existing tile padding, predictor statistics and ordering.
use crate::{Backend, gpu::Gpu};
use anyhow::{Result, bail, ensure};
use std::ffi::{CStr, CString};

struct HostWork<'a> {
    work: Option<&'a mut dyn FnMut() -> Result<()>>,
    result: Option<Result<()>>,
    panic: Option<Box<dyn std::any::Any + Send>>,
}

unsafe extern "C" fn run_host_work(context: *mut std::ffi::c_void) {
    // SAFETY: the synchronous bridge calls only on this thread and never retains
    // this pointer. The stack context outlives GPU completion and native return.
    let context = unsafe { &mut *context.cast::<HostWork<'_>>() };
    if let Some(work) = context.work.take() {
        match std::panic::catch_unwind(std::panic::AssertUnwindSafe(work)) {
            Ok(result) => context.result = Some(result),
            Err(panic) => context.panic = Some(panic),
        }
    }
}

unsafe extern "C" {
    fn cdng_metal_hist_geometries(
        pixels: *const u16,
        width: u32,
        height: u32,
        bits: u32,
        mask: u32,
        geometries: *const u32,
        geometry_count: u32,
        hist: *mut u32,
        hist_count: u32,
        source: *const std::ffi::c_char,
        host_work: Option<unsafe extern "C" fn(*mut std::ffi::c_void)>,
        host_context: *mut std::ffi::c_void,
        error: *mut std::ffi::c_char,
        error_size: u32,
    ) -> i32;
}

impl Gpu {
    /// Compute one histogram vector per geometry, in source raster tile order.
    /// All candidate geometries and all requested predictors are evaluated.
    pub fn histogram_geometries(
        &self,
        pixels: &[u16],
        width: usize,
        height: usize,
        bits: u32,
        predictors: &[u8],
        geometries: &[(usize, usize)],
    ) -> Result<Vec<Vec<u32>>> {
        self.histogram_geometries_with_work(pixels, width, height, bits, predictors, geometries, None)
    }

    /// Synchronous CPU work runs once after GPU submission. Its error or panic
    /// propagates only after the native bridge has completed the GPU command.
    pub(crate) fn histogram_geometries_with_work(
        &self, pixels: &[u16], width: usize, height: usize, bits: u32,
        predictors: &[u8], geometries: &[(usize, usize)],
        work: Option<&mut dyn FnMut() -> Result<()>>,
    ) -> Result<Vec<Vec<u32>>> {
        ensure!(self.backend == Backend::Metal, "Geometry batching requires Metal");
        ensure!(
            width >= 2 && height >= 2 && width.is_multiple_of(2) && height.is_multiple_of(2)
                && width.checked_mul(height) == Some(pixels.len())
                && pixels.len() <= u32::MAX as usize
                && (8..=16).contains(&bits)
                && !predictors.is_empty() && predictors.iter().all(|p| (1..=7).contains(p))
                && !geometries.is_empty() && geometries.len() <= 16,
            "Invalid Metal geometry batch"
        );
        let mut native_geometries = Vec::with_capacity(geometries.len() * 2);
        let mut counts = Vec::with_capacity(geometries.len());
        let mut total = 0usize;
        for &(tw, th) in geometries {
            ensure!(
                tw >= 2 && th >= 2 && tw.is_multiple_of(2) && th.is_multiple_of(2)
                    && tw <= 65520 && th <= 65520
                    && tw.checked_mul(th).is_some_and(|n| n <= u32::MAX as usize),
                "Invalid Metal tile geometry"
            );
            let count = width.div_ceil(tw).checked_mul(height.div_ceil(th))
                .and_then(|n| n.checked_mul(238)).ok_or_else(|| anyhow::anyhow!("Metal histogram size overflow"))?;
            total = total.checked_add(count).ok_or_else(|| anyhow::anyhow!("Metal histogram size overflow"))?;
            counts.push(count);
            native_geometries.extend([tw as u32, th as u32]);
        }
        ensure!(total <= u32::MAX as usize, "Metal histogram size overflow");
        let mut hist = vec![0u32; total];
        let mut error = [0i8; 2048];
        static SOURCE: std::sync::OnceLock<CString> = std::sync::OnceLock::new();
        let source = SOURCE.get_or_init(|| CString::new(include_str!(
            "../../cdng_image/native/histogram_batch.metal"
        )).expect("Embedded Metal source contains no NUL"));
        let has_work = work.is_some();
        let mut host = HostWork { work, result: None, panic: None };
        // SAFETY: sizes and dimension arithmetic are validated here and in the
        // bridge; all borrowed slices outlive the synchronous GPU completion.
        let code = unsafe {
            cdng_metal_hist_geometries(
                pixels.as_ptr(), width as u32, height as u32, bits,
                predictors.iter().fold(0, |mask, p| mask | (1 << (*p - 1))),
                native_geometries.as_ptr(), geometries.len() as u32,
                hist.as_mut_ptr(), hist.len() as u32, source.as_ptr(),
                has_work.then_some(run_host_work), (&mut host as *mut HostWork<'_>).cast(),
                error.as_mut_ptr(), error.len() as u32,
            )
        };
        // The callback never unwinds across Objective-C/C++. At this point its
        // GPU resources have completed and can safely be released during unwind.
        if let Some(panic) = host.panic.take() { std::panic::resume_unwind(panic); }
        if code != 0 {
            bail!("GPU: {}", unsafe { CStr::from_ptr(error.as_ptr()) }.to_string_lossy());
        }
        if has_work {
            host.result.take().ok_or_else(|| anyhow::anyhow!("Metal histogram host work did not run"))??;
        }
        let mut output = Vec::with_capacity(counts.len());
        let mut at = 0;
        for count in counts {
            output.push(hist[at..at + count].to_vec());
            at += count;
        }
        Ok(output)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn histogram_host_work_runs_once_and_recovers_after_error_cancel_and_panic() {
        if std::env::var_os("CDNG_TEST_GPU").is_none() { return; }
        let gpu = Gpu::new(Backend::Metal).unwrap();
        let pixels: Vec<u16> = (0..194 * 130).map(|i| (i * 31 % 4096) as u16).collect();
        let geometries = [(48, 80), (66, 126), (432, 288)];
        let expected: Vec<_> = geometries.iter().map(|&(tw, th)|
            expected(&pixels, 194, 130, 12, &[1, 5, 7], tw, th)).collect();
        let owner = std::thread::current().id();
        let mut calls = 0;
        let mut work = || {
            calls += 1;
            assert_eq!(std::thread::current().id(), owner);
            // Neither batched nor legacy histogram search may overwrite this
            // thread's buffers while the outer GPU command reads them.
            assert!(gpu.histogram_geometries(&pixels, 194, 130, 12, &[7], &geometries).unwrap_err().to_string().contains("reenter"));
            assert!(gpu.histogram(&pixels, 194, 12, &[7]).unwrap_err().to_string().contains("reenter"));
            Ok(())
        };
        assert_eq!(gpu.histogram_geometries_with_work(&pixels, 194, 130, 12, &[1, 5, 7], &geometries, Some(&mut work)).unwrap(), expected);
        assert_eq!(calls, 1);
        for failure in ["error", "cancel", "panic"] {
            let mut calls = 0;
            let mut work = || -> Result<()> {
                calls += 1;
                match failure {
                    "error" => bail!("test host error"),
                    "cancel" => crate::cancelled(&std::sync::atomic::AtomicBool::new(true)),
                    _ => panic!("test host panic"),
                }
            };
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                gpu.histogram_geometries_with_work(&pixels, 194, 130, 12, &[1, 5, 7], &geometries, Some(&mut work))
            }));
            if failure == "panic" { assert!(result.is_err()); }
            else { assert!(result.unwrap().is_err()); }
            assert_eq!(calls, 1);
            // This call reuses the same pooled buffers after the failed work;
            // native completion and the reentrancy guard must both be restored.
            assert_eq!(gpu.histogram_geometries(&pixels, 194, 130, 12, &[1, 5, 7], &geometries).unwrap(), expected);
        }
        let mut called = false;
        let mut work = || { called = true; Ok(()) };
        assert!(gpu.histogram_geometries_with_work(&pixels, 1, 34, 12, &[7], &geometries, Some(&mut work)).is_err());
        assert!(!called, "validation failure must not run unsubmitted work");
    }

    #[test]
    fn histogram_host_work_contexts_remain_local_to_each_worker() {
        if std::env::var_os("CDNG_TEST_GPU").is_none() { return; }
        let gpu = Gpu::new(Backend::Metal).unwrap();
        std::thread::scope(|scope| {
            for worker in 0..4 {
                let gpu = &gpu;
                scope.spawn(move || {
                    let pixels: Vec<u16> = (0..258 * 194).map(|i| ((i * 31 + worker) % 4096) as u16).collect();
                    let geometries = [(48, 80), (66, 126), (432, 288), (512, 256)];
                    let expected: Vec<_> = geometries.iter().map(|&(tw, th)|
                        expected(&pixels, 258, 194, 12, &[1, 5, 7], tw, th)).collect();
                    let owner = std::thread::current().id();
                    let mut calls = 0;
                    for _ in 0..3 {
                        let mut work = || {
                            assert_eq!(std::thread::current().id(), owner);
                            calls += 1;
                            assert_eq!(crate::hash(b"worker host hash"), crate::hash(b"worker host hash"));
                            Ok(())
                        };
                        assert_eq!(gpu.histogram_geometries_with_work(&pixels, 258, 194, 12, &[1, 5, 7], &geometries, Some(&mut work)).unwrap(), expected);
                    }
                    assert_eq!(calls, 3);
                });
            }
        });
    }

    fn expected(pixels: &[u16], width: usize, height: usize, bits: u32, predictors: &[u8], tw: usize, th: usize) -> Vec<u32> {
        let mut histograms = Vec::new();
        for y in (0..height).step_by(th) {
            for x in (0..width).step_by(tw) {
                let mut tile = vec![0; tw * th];
                let vw = tw.min(width - x);
                let vh = th.min(height - y);
                for yy in 0..vh {
                    tile[yy * tw..yy * tw + vw].copy_from_slice(&pixels[(y + yy) * width + x..(y + yy) * width + x + vw]);
                    for xx in vw..tw { tile[yy * tw + xx] = tile[yy * tw + xx - 2]; }
                }
                for yy in vh..th {
                    for xx in 0..tw { tile[yy * tw + xx] = tile[yy.saturating_sub(2) * tw + xx]; }
                }
                histograms.extend(crate::gpu::reference(&tile, (tw * 2) as u32, bits, predictors));
            }
        }
        histograms
    }

    #[test]
    fn geometry_histograms_match_scalar_with_cfa_edges() {
        if std::env::var_os("CDNG_TEST_GPU").is_none() { return; }
        let gpu = Gpu::new(Backend::Metal).unwrap();
        for bits in [8, 10, 12, 14, 16] {
            for (width, height) in [(2, 2), (18, 34), (258, 194)] {
                let mask = (1u32 << bits) - 1;
                let pixels: Vec<u16> = (0..width * height).map(|i| {
                    (match i % 17 {
                        0 => 0, 1 => mask, _ => (i as u32).wrapping_mul(23417) ^ (i as u32).wrapping_mul(i as u32),
                    } & mask) as u16
                }).collect();
                let geometries = [(16, 16), (32, 64), (256, 256), (512, 256), (1024, 512)];
                for predictors in [&[1, 2, 3, 4, 5, 6, 7][..], &[1, 5, 7][..], &[7][..]] {
                    let actual = gpu.histogram_geometries(&pixels, width, height, bits, predictors, &geometries).unwrap();
                    for (&(tw, th), actual) in geometries.iter().zip(actual) {
                        assert_eq!(actual, expected(&pixels, width, height, bits, predictors, tw, th), "{bits}-bit {width}x{height}, tile {tw}x{th}");
                    }
                }
            }
        }
    }

    #[test]
    fn shared_geometry_histograms_match_every_bin_at_macroblock_and_bayer_seams() {
        if std::env::var_os("CDNG_TEST_GPU").is_none() { return; }
        let gpu = Gpu::new(Backend::Metal).unwrap();
        let geometries = [(48, 80), (66, 126), (432, 288), (64, 64), (128, 64)];
        let masks: &[&[u8]] = &[&[1, 2, 3, 4, 5, 6, 7], &[1], &[2], &[3], &[4], &[5], &[6], &[7], &[1, 5, 7]];
        for bits in [8, 10, 12, 14, 16] {
            let maximum = (1u32 << bits) - 1;
            for (width, height) in [(2, 2), (18, 34), (62, 66), (64, 64), (130, 130), (434, 290)] {
                let pixels: Vec<_> = (0..width * height).map(|i| {
                    let (x, y) = (i % width, i / width);
                    // Different values on both Bayer parities expose an odd
                    // sensor row's dependency on the preceding row's tail.
                    // Extreme values straddle both 64-pixel and tile seams.
                    let value = if x < 2 || x % 64 >= 62 || y % 64 < 2 {
                        match (x + 3 * y) % 4 { 0 => 0, 1 => maximum, 2 => maximum / 2, _ => 1 }
                    } else {
                        (i as u32).wrapping_mul(23417) ^ (x as u32).wrapping_mul(y as u32 + 331)
                    };
                    (value & maximum) as u16
                }).collect();
                for &predictors in masks {
                    let actual = gpu.histogram_geometries(&pixels, width, height, bits, predictors, &geometries).unwrap();
                    for (&(tw, th), actual) in geometries.iter().zip(actual) {
                        assert_eq!(actual, expected(&pixels, width, height, bits, predictors, tw, th),
                            "{bits}-bit {width}x{height}, tile {tw}x{th}, predictors {predictors:?}");
                    }
                }
            }
        }
    }

    #[test]
    fn shared_geometry_histograms_preserve_single_geometry_and_extreme_aspect_fallbacks() {
        if std::env::var_os("CDNG_TEST_GPU").is_none() { return; }
        let gpu = Gpu::new(Backend::Metal).unwrap();
        let pixels = [0, 65535, 32768, 1];
        // Each legal thin tile is small, but their common bounding rectangle
        // would be 65536 squared after rounding. Never allocate that rectangle.
        for geometries in [vec![(2, 65520), (65520, 2)], vec![(48, 80)], vec![(432, 288)]] {
            for predictors in [&[1, 2, 3, 4, 5, 6, 7][..], &[4][..]] {
                let actual = gpu.histogram_geometries(&pixels, 2, 2, 16, predictors, &geometries).unwrap();
                for (&(tw, th), actual) in geometries.iter().zip(actual) {
                    assert_eq!(actual, expected(&pixels, 2, 2, 16, predictors, tw, th),
                        "fallback tile {tw}x{th}, predictors {predictors:?}");
                }
            }
        }
    }

    #[test]
    fn geometry_histograms_reject_invalid_dimensions() {
        // Validation is deliberately independent of Metal initialization.
        let gpu = Gpu { backend: Backend::Metal, name: String::new() };
        for (width, height, geometries) in [(1, 4, vec![(16, 16)]), (2, 2, vec![(3, 16)]), (2, 2, vec![])] {
            assert!(gpu.histogram_geometries(&[0; 4], width, height, 12, &[7], &geometries).is_err());
        }
        assert!(gpu.histogram_geometries(&[0; 4], 2, 2, 12, &[0], &[(16, 16)]).is_err());
    }

    #[test]
    fn geometry_histograms_remain_owned_across_workers_and_resizes() {
        if std::env::var_os("CDNG_TEST_GPU").is_none() { return; }
        let gpu = Gpu::new(Backend::Metal).unwrap();
        std::thread::scope(|scope| {
            for worker in 0..4 {
                let gpu = &gpu;
                scope.spawn(move || {
                    let mut retained = Vec::new();
                    for (round, (width, height)) in [(514, 258), (18, 34), (2, 2), (434, 290), (130, 66)].into_iter().enumerate() {
                        let bits = [16, 8, 10, 12, 14][(worker + round) % 5];
                        let mask = (1u32 << bits) - 1;
                        let pixels: Vec<u16> = (0..width * height).map(|i| {
                            if round == 1 { 0 } else if round == 2 { mask as u16 } else {
                                ((i as u32).wrapping_mul(23417 + worker as u32 * 2)
                                    .wrapping_add(round as u32 * 71) & mask) as u16
                            }
                        }).collect();
                        let geometries = [(48, 80), (66, 126), (432, 288), (256, 256), (1024, 512)];
                        let predictors: &[u8] = if round == 1 { &[7] } else if round == 2 { &[1, 3] } else { &[1, 2, 3, 4, 5, 6, 7] };
                        let actual = gpu.histogram_geometries(&pixels, width, height, bits, predictors, &geometries).unwrap();
                        let expected = geometries.iter().map(|&(tw, th)| expected(&pixels, width, height, bits, predictors, tw, th)).collect::<Vec<_>>();
                        retained.push((actual, expected));
                    }
                    for (actual, expected) in retained { assert_eq!(actual, expected); }
                });
            }
        });
    }
}
