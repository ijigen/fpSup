//! Queues and scratch owned by short-lived workers may disappear before their
//! returned JPEG allocations are consumed by the writer.
use cdng_image::{Backend, gpu::Gpu};
use std::sync::Barrier;

#[test]
fn retained_jpegs_survive_worker_queue_and_scratch_destruction() {
    if !cfg!(target_os = "macos") || std::env::var_os("CDNG_TEST_GPU").is_none() {
        return;
    }
    // Initialization matches pack: complete hardware conformance before workers.
    let gpu = Gpu::new(Backend::Metal).unwrap();
    let mut retained = Vec::new();
    for wave in 0..4 {
        let barrier = Barrier::new(8);
        let outputs = std::thread::scope(|scope| {
            let handles: Vec<_> = (0..8).map(|worker| {
                let gpu = &gpu;
                let barrier = &barrier;
                scope.spawn(move || {
                    let (width, height) = if worker == 0 { (241u16, 136u16) } else { (17, 9) };
                    let bits = [8u8, 12, 16][(wave + worker) % 3];
                    let predictor = [1u8, 5, 7][(wave + worker) % 3];
                    let count = usize::from(width) * usize::from(height) * 2;
                    let mask = (1u32 << bits) - 1;
                    let pixels: Vec<u16> = (0..count * 2).map(|i| {
                        (((i as u32).wrapping_mul(23417 + worker as u32 * 2)
                            ^ (wave as u32 * 171)) & mask) as u16
                    }).collect();
                    // Simultaneous first submissions exercise lazy TLS queues.
                    barrier.wait();
                    let (_, _, hist) = gpu.analyze_tiles(
                        &pixels, count, u32::from(width) * 2, u32::from(bits), &[predictor],
                    ).unwrap();
                    let jpegs = gpu.encode_tiles(
                        &pixels, count, u32::from(width) * 2, u32::from(bits), &[predictor; 2], &hist,
                    ).unwrap();
                    (jpegs, pixels, width, height, bits, predictor)
                })
            }).collect();
            handles.into_iter().map(|handle| handle.join().unwrap()).collect::<Vec<_>>()
        });
        // All worker queues and scratch are gone before these results are used.
        retained.extend(outputs);
    }
    for (jpegs, pixels, width, height, bits, predictor) in retained {
        let count = usize::from(width) * usize::from(height) * 2;
        assert_eq!(jpegs.len(), pixels.len() / count);
        for (jpeg, tile) in jpegs.into_iter().zip(pixels.chunks_exact(count)) {
            let expected = ljpeg::Encoder::new(
                width, height, ljpeg::Components::C2,
                ljpeg::Bitdepth::try_from(bits).unwrap(),
                ljpeg::Predictor::try_from(predictor).unwrap(), 0, 0,
            ).encode(tile).unwrap();
            assert_eq!(jpeg, expected);
            assert_eq!(ljpeg_reference::Decoder::new(&jpeg).unwrap().decode().unwrap(), tile);
        }
    }
}
