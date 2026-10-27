#[path = "../src/gpu_prune.rs"]
mod gpu_prune;

use cdng_image::gpu::{Gpu, reference};

fn encode(pixels: &[u16], stride: usize, bits: u8, predictor: u8) -> Vec<u8> {
    ljpeg::Encoder::new(
        (stride / 2) as u16,
        (pixels.len() / stride) as u16,
        ljpeg::Components::C2,
        ljpeg::Bitdepth::try_from(bits).unwrap(),
        ljpeg::Predictor::try_from(predictor).unwrap(),
        0,
        0,
    )
    .encode(pixels)
    .unwrap()
}

#[test]
fn entropy_bounds_and_strict_pruning_preserve_exact_winning_bytes() {
    let predictors = [1, 2, 3, 4, 5, 6, 7];
    let (mut cases, mut skipped, mut stuffed, mut category_16, mut pruned_ties) = (0, 0, 0, 0, 0);
    for bits in [8u8, 10, 12, 14, 16] {
        let mask = (1u32 << bits) - 1;
        for (stride, height) in [(2, 1), (34, 9), (64, 16)] {
            for pattern in 0..4 {
                let pixels: Vec<u16> = (0..stride * height)
                    .map(|i| match pattern {
                        0 => 1 << (bits - 1),
                        1 => ((i * 7 + i / stride * 23) as u32 & mask) as u16,
                        2 => {
                            ((i as u32)
                                .wrapping_mul(23417)
                                .wrapping_add((i * i) as u32 * 11)
                                & mask) as u16
                        }
                        _ => {
                            if i % 4 < 2 {
                                0
                            } else {
                                mask as u16
                            }
                        }
                    })
                    .collect();
                let histogram = reference(&pixels, stride as u32, bits as u32, &predictors);
                category_16 += histogram.chunks_exact(17).map(|h| h[16]).sum::<u32>();
                let (ranked, _) = Gpu::analyze_histograms(&histogram, &predictors).unwrap();
                let repeated_histograms: Vec<u32> = (0..7).flat_map(|_| histogram).collect();
                let bounds = gpu_prune::lower_bounds(
                    pixels.len(),
                    stride as u32,
                    bits as u32,
                    &predictors,
                    &repeated_histograms,
                )
                .unwrap();
                let encoded: Vec<_> = predictors
                    .iter()
                    .map(|&p| encode(&pixels, stride, bits, p))
                    .collect();
                for (bound, bytes) in bounds.iter().zip(&encoded) {
                    assert!(*bound <= bytes.len(), "Bound exceeded actual byte count");
                    stuffed += usize::from(*bound < bytes.len());
                }
                let first = &encoded[ranked[0][0] as usize - 1];
                let second = &encoded[ranked[0][1] as usize - 1];
                let complete_winner = if second.len() < first.len() {
                    second
                } else {
                    first
                };
                let pruned_winner = if bounds[ranked[0][1] as usize - 1] >= first.len() {
                    skipped += 1;
                    pruned_ties += usize::from(second.len() == first.len());
                    first
                } else if second.len() < first.len() {
                    second
                } else {
                    first
                };
                assert_eq!(
                    pruned_winner, complete_winner,
                    "Pruning changed chosen JPEG"
                );
                cases += 1;
            }
        }
    }
    assert_eq!(cases, 60);
    assert!(
        skipped > 0,
        "Test must exercise dominated candidates and ties"
    );
    assert!(
        stuffed > 0,
        "Test must exercise stuffing beyond the lower bound"
    );
    assert!(
        category_16 > 0,
        "Test must exercise category 16's zero magnitude bits"
    );
    assert!(
        pruned_ties > 0,
        "Test must retain the first candidate on equal lengths"
    );
}

#[test]
fn invalid_bounds_fail_before_indexing_or_encoding() {
    let histogram = [0; 238];
    for (count, stride, bits, predictors, histograms) in [
        (0, 2, 12, &[1][..], &histogram[..]),
        (8, 3, 12, &[1][..], &histogram[..]),
        (8, 2, 17, &[1][..], &histogram[..]),
        (8, 2, 12, &[0][..], &histogram[..]),
        (8, 2, 12, &[8][..], &histogram[..]),
        (8, 2, 12, &[1, 2][..], &histogram[..]),
        (8, 2, 12, &[1][..], &histogram[..]),
    ] {
        assert!(gpu_prune::lower_bounds(count, stride, bits, predictors, histograms).is_err());
    }
}
