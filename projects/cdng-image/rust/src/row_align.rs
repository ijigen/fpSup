//! OG3K vertical CFA row-phase correction, applied only to the mounted view.
//!
//! The two CFA row families sample at unequal vertical positions. A symmetric
//! one-eighth same-colour-plane shift per family corrects the measured half
//! output-pixel relative offset while applying the same filter to both families.
use anyhow::{Result, ensure};

const LOBES: isize = 6;
const SCALE: i64 = 1 << 16;

fn sinc(x: f64) -> f64 {
    if x.abs() < 1e-12 { 1.0 } else { (std::f64::consts::PI * x).sin() / (std::f64::consts::PI * x) }
}

fn coefficients(shift: f64) -> (isize, [i32; 12]) {
    let base = shift.floor() as isize;
    let fraction = shift - base as f64;
    let mut weights = [0.0; 12];
    for (j, w) in weights.iter_mut().enumerate() {
        let k = j as isize - LOBES + 1;
        let x = fraction - k as f64;
        *w = sinc(x) * sinc(x / LOBES as f64);
    }
    let total: f64 = weights.iter().sum();
    let mut integer = weights.map(|w| (w / total * SCALE as f64).round() as i32);
    // Preserve a constant image exactly, despite fixed-point rounding.
    integer[5] += SCALE as i32 - integer.iter().sum::<i32>();
    (base - LOBES + 1, integer)
}

/// Interpolate each CFA row family without mixing Bayer colours. Only six
/// preceding source rows and one destination row are retained per worker.
pub(crate) fn correct(pixels: &mut [u16], width: usize, height: usize, bits: usize) -> Result<()> {
    ensure!(width > 0 && height >= 2 && height % 2 == 0 && pixels.len() == width * height
        && (8..=16).contains(&bits), "Invalid OG3K correction geometry");
    let ceiling = if bits == 16 { u16::MAX as i64 } else { (1i64 << bits) - 1 };
    let rows = height / 2;
    let mut history = vec![0u16; width * 6];
    let mut output = vec![0u16; width];
    for (parity, shift) in [(0, -0.125), (1, 0.125)] {
        let (first, weights) = coefficients(shift);
        for row in 0..rows {
            let mut sources = [std::ptr::null::<u16>(); 12];
            for (j, src) in sources.iter_mut().enumerate() {
                let sample = (row as isize + first + j as isize).clamp(0, rows as isize - 1) as usize;
                *src = if sample < row {
                    history[sample % 6 * width..].as_ptr()
                } else {
                    pixels[(2 * sample + parity) * width..].as_ptr()
                };
            }
            for (x, value) in output.iter_mut().enumerate() {
                let mut sum = 0i64;
                for j in 0..12 {
                    // Each source points to an allocated whole row. `x < width`,
                    // no allocation moves, and the source rows are not changed
                    // until the output row has been completely calculated.
                    sum += unsafe { *sources[j].add(x) } as i64 * weights[j] as i64;
                }
                *value = ((sum + SCALE / 2) / SCALE).clamp(0, ceiling) as u16;
            }
            let at = (2 * row + parity) * width;
            history[row % 6 * width..(row % 6 + 1) * width].copy_from_slice(&pixels[at..at + width]);
            pixels[at..at + width].copy_from_slice(&output);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn symmetric_filters_have_matching_weights_and_constant_gain() {
        let (left_start,left)=coefficients(-0.125);
        let (right_start,right)=coefficients(0.125);
        assert_eq!((left_start,right_start),(-6,-5));
        assert_eq!(left.iter().map(|&x|x as i64).sum::<i64>(),SCALE);
        assert_eq!(right.iter().map(|&x|x as i64).sum::<i64>(),SCALE);
        for i in 0..12 { assert!((left[i]-right[11-i]).abs()<=1); }
    }

    #[test]
    fn constant_cfa_planes_and_extremes_remain_constant() {
        let (w,h)=(20,18);
        let expected: Vec<u16> = (0..w*h).map(|i| match (i/w%2,i%2) {
            (0,0)=>0,(0,_)=>127,(1,0)=>2047,_=>4095
        }).collect();
        let mut p=expected.clone();
        correct(&mut p,w,h,12).unwrap();
        assert_eq!(p,expected);
    }

    #[test]
    fn split_phase_moves_row_families_in_opposite_directions() {
        let (w,h)=(4,48);
        let mut p: Vec<u16>=(0..w*h).map(|i| 1000+(i/w/2) as u16*64).collect();
        correct(&mut p,w,h,12).unwrap();
        for row in 7..17 {
            assert_eq!(p[(2*row)*w],1000+row as u16*64-8);
            assert_eq!(p[(2*row+1)*w],1000+row as u16*64+8);
        }
    }
}
