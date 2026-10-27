//! Reused entropy scratch must not leak a longer previous stream into padding
//! or the joiner's one-word lookahead. Check actual JPEG bytes independently.
use cdng_image::{Backend, gpu::Gpu};

#[test]
fn dirty_entropy_scratch_remains_exact_for_flat_and_partial_blocks() {
    if !cfg!(target_os = "macos") || std::env::var_os("CDNG_TEST_GPU").is_none() {
        return;
    }
    let gpu = Gpu::new(Backend::Metal).unwrap();
    for predictor in 1u8..=7 {
        // First fill the reused scratch with a long high-entropy 16-bit stream.
        // Flat zero then creates a short stream with misaligned block starts;
        // midpoint creates exact 32-bit boundaries. The final cases shrink to
        // both sides of a 256-pixel block, keeping the larger scratch allocated.
        for (width, height, bits, pattern) in [
            (241u16, 136u16, 16u8, 0u8),
            (241, 136, 8, 1),
            (241, 136, 8, 2),
            (1, 127, 8, 1),
            (1, 128, 8, 2),
            (1, 129, 8, 1),
            (17, 9, 8, 1),
        ] {
            let count = usize::from(width) * usize::from(height) * 2;
            let pixels: Vec<u16> = (0..count * 3).map(|i| match pattern {
                0 => ((i as u32).wrapping_mul(23417)
                    ^ (i as u32).wrapping_mul(i as u32).rotate_left(7)
                    ^ (i / count) as u32 * 71) as u16,
                1 => 0,
                _ => 1 << (bits - 1),
            }).collect();
            let (_, _, hist) = gpu.analyze_tiles(
                &pixels, count, u32::from(width) * 2, u32::from(bits), &[predictor],
            ).unwrap();
            let actual = gpu.encode_tiles(
                &pixels, count, u32::from(width) * 2, u32::from(bits), &[predictor; 3], &hist,
            ).unwrap();
            for (tile, jpeg) in pixels.chunks_exact(count).zip(actual) {
                let expected = ljpeg::Encoder::new(
                    width, height, ljpeg::Components::C2,
                    ljpeg::Bitdepth::try_from(bits).unwrap(),
                    ljpeg::Predictor::try_from(predictor).unwrap(), 0, 0,
                ).encode(tile).unwrap();
                assert_eq!(jpeg, expected,
                    "P{predictor}, {bits}-bit {width}x{height}, pattern {pattern}");
                assert_eq!(ljpeg_reference::Decoder::new(&jpeg).unwrap().decode().unwrap(), tile);
            }
        }
    }
}
