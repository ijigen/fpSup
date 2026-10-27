#![cfg(target_os = "macos")]
use cdng_image::{Backend, gpu::{Gpu, reference}};

#[test]
fn exact_histograms_across_workgroup_and_partial_lane_boundaries() {
    if std::env::var_os("CDNG_TEST_GPU").is_none() { return; }
    let gpu = Gpu::new(Backend::Metal).unwrap();
    let (width, height) = (258usize, 194usize);
    // Below/exactly/above4,096 and8,192 samples, plus final partial SIMD lanes.
    let geometries = [(62, 66), (64, 64), (66, 64), (64, 128), (66, 126)];
    for bits in [8, 12, 16] {
        let mask = (1u32 << bits) - 1;
        for pattern in 0..3 {
            let pixels: Vec<u16> = (0..width * height).map(|i| {
                (match pattern {
                    0 => ((i as u32).wrapping_mul(23417) ^ (i as u32).wrapping_mul(i as u32)) & mask,
                    1 => 1 << (bits - 1),
                    _ => if i % 4 < 2 { 0 } else { mask },
                }) as u16
            }).collect();
            for predictors in [&[1, 2, 3, 4, 5, 6, 7][..], &[1, 5, 7][..], &[7][..]] {
                let actual = gpu.histogram_geometries(&pixels, width, height, bits, predictors, &geometries).unwrap();
                for (&(tw, th), histogram) in geometries.iter().zip(actual) {
                    let mut expected = Vec::new();
                    for y in (0..height).step_by(th) {
                        for x in (0..width).step_by(tw) {
                            let tile: Vec<u16> = (0..tw * th).map(|i| {
                                let sx = x + i % tw;
                                let sy = y + i / tw;
                                let sx = if sx < width { sx } else { width - 2 + ((sx - width) & 1) };
                                let sy = if sy < height { sy } else { height - 2 + ((sy - height) & 1) };
                                pixels[sy * width + sx]
                            }).collect();
                            expected.extend(reference(&tile, (tw * 2) as u32, bits, predictors));
                        }
                    }
                    assert_eq!(histogram, expected, "{bits}-bit, pattern{pattern}, tile{tw}x{th}");
                }
            }
        }
    }
}
