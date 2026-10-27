//! CPU-only entropy planning diagnostic; excludes JPEG/GPU entropy writing.
use anyhow::{Context, Result, ensure};
use std::{hint::black_box, time::Instant};
fn main() -> Result<()> {
    let source = std::env::args().nth(1).context("SOURCE_DNG WIDTH HEIGHT BITS")?;
    let width: usize = std::env::args().nth(2).context("WIDTH")?.parse()?;
    let height: usize = std::env::args().nth(3).context("HEIGHT")?.parse()?;
    let bits: u8 = std::env::args().nth(4).context("BITS")?.parse()?;
    let pixels = cdng_image::dng::decode(&std::fs::read(&source)?)?;
    ensure!(pixels.len() == width*height);
    let grid = ((width as f64 * height as f64 / 131072.).sqrt().round() as usize).max(1);
    let dimension = |n: usize| n.div_ceil(grid).next_multiple_of(16).clamp(16,65520);
    let (tw,th)=(dimension(width),dimension(height));
    let mut cases=Vec::new();
    for y in (0..height).step_by(th) { for x in (0..width).step_by(tw) {
        let (vw,vh)=(tw.min(width-x),th.min(height-y));
        let mut tile=vec![0;tw*th];
        for yy in 0..vh {
            tile[yy*tw..yy*tw+vw].copy_from_slice(&pixels[(y+yy)*width+x..(y+yy)*width+x+vw]);
            for xx in vw..tw {tile[yy*tw+xx]=tile[yy*tw+xx-2];}
        }
        for yy in vh..th {for xx in 0..tw {tile[yy*tw+xx]=tile[yy.saturating_sub(2)*tw+xx];}}
        let hist=cdng_image::gpu::reference(&tile,(tw*2) as u32,bits as u32,&[1,2,3,4,5,6,7]);
        let (ranked,_) = cdng_image::gpu::Gpu::analyze_histograms(&hist,&[1,2,3,4,5,6,7])?;
        for &p in &ranked[0][..2] {
            let at=(p as usize-1)*34;
            let histogram:[[u32;17];2]=[hist[at..at+17].try_into()?,hist[at+17..at+34].try_into()?];
            let encoder=ljpeg::Encoder::new(tw as u16,(th/2) as u16,ljpeg::Components::C2,ljpeg::Bitdepth::try_from(bits).unwrap(),ljpeg::Predictor::try_from(p).unwrap(),0,0);
            cases.push((encoder,histogram));
        }
    }}
    let mut checksum=0;
    let mut rows=Vec::new();
    for _ in 0..7 {
        let begin=Instant::now();
        for _ in 0..300 {for (encoder,hist) in &cases {
            let (prefix,table,bits)=black_box(encoder.plan_entropy(black_box(hist))).context("Plan")?;
            checksum^=bits ^ prefix.len() as u64 ^ table.len() as u64;
            black_box((prefix,table));
        }}
        rows.push(begin.elapsed().as_secs_f64());
    }
    println!("{}",serde_json::json!({"source":source,"tile_width":tw,"tile_height":th,"plans_per_round":300*cases.len(),"rounds":rows,"checksum":checksum}));
    Ok(())
}
