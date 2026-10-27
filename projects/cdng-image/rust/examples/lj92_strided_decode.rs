use anyhow::{Result, ensure};
use serde::Deserialize;
use std::{hint::black_box, time::Instant};

#[derive(Deserialize)]
struct Input {
    path: String,
    offsets: Vec<usize>,
    counts: Vec<usize>,
    width: usize,
    height: usize,
    tw: usize,
    th: usize,
}

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    let input: Vec<Input> = serde_json::from_slice(&std::fs::read(&args[1])?)?;
    let frames: Vec<_> = input
        .iter()
        .map(|v| std::fs::read(&v.path))
        .collect::<std::io::Result<_>>()?;
    let repeats = args.get(2).map(|s| s.parse()).transpose()?.unwrap_or(3);
    let reuse = args.get(3).is_some_and(|s| s == "reuse");
    for repeat in 0..repeats {
        let started = Instant::now();
        let mut samples = 0;
        let mut digest = 0u64;
        for (v, bytes) in input.iter().zip(&frames) {
            let mut frame = vec![0u16; v.width * v.height];
            let mut tile_buffer = Vec::new();
            for (i, (&offset, &count)) in v.offsets.iter().zip(&v.counts).enumerate() {
                let decoder = ljpeg::Decoder::new(&bytes[offset..offset + count])?;
                ensure!(decoder.width() * decoder.height() * decoder.components() == v.tw * v.th);
                let x = (i % v.width.div_ceil(v.tw)) * v.tw;
                let y = (i / v.width.div_ceil(v.tw)) * v.th;
                let owned;
                let decoded = if reuse {
                    tile_buffer.resize(v.tw * v.th, 0);
                    decoder.decode_to_buffer(&mut tile_buffer, decoder.width(), decoder.height())?;
                    &tile_buffer
                } else {
                    owned = decoder.decode()?;
                    &owned
                };
                for yy in 0..v.th.min(v.height - y) {
                    let n = v.tw.min(v.width - x);
                    frame[(y + yy) * v.width + x..(y + yy) * v.width + x + n]
                        .copy_from_slice(&decoded[yy * v.tw..yy * v.tw + n]);
                }
                samples += v.tw * v.th;
            }
            for &pixel in black_box(&frame) {
                digest = digest.wrapping_mul(31).wrapping_add(u64::from(pixel));
            }
        }
        println!(
            "{}",
            serde_json::json!({"repeat":repeat,"seconds":started.elapsed().as_secs_f64(),"samples":samples,"digest":digest,"reuse":reuse})
        );
    }
    Ok(())
}
