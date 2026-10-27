//! Exact lower bounds for lossless JPEG candidates.
//!
//! A planned JPEG has an exact header and an exact number of entropy bits.
//! Rounding the entropy bits up to bytes and adding EOI gives a lower bound:
//! byte stuffing can only add bytes. If this bound is at least the length of
//! an already encoded candidate, it cannot replace that candidate under the
//! encoder's strict `new.len() < old.len()` rule. This does not approximate the
//! predictor search or omit a candidate that could improve compression.

use anyhow::{Result, ensure};

pub(crate) fn minimum_length(header_bytes: usize, entropy_bits: u64) -> Result<usize> {
    header_bytes.checked_add(usize::try_from(entropy_bits.div_ceil(8))?)
        .and_then(|bytes| bytes.checked_add(2))
        .ok_or_else(|| anyhow::anyhow!("JPEG bound length overflow"))
}

#[allow(dead_code)] // Independent reference used by integration tests and CPU diagnostics.
pub(crate) fn lower_bounds(
    tile_len: usize,
    stride: u32,
    bits: u32,
    predictors: &[u8],
    histograms: &[u32],
) -> Result<Vec<usize>> {
    ensure!(
        !predictors.is_empty()
            && tile_len > 0
            && stride >= 2
            && stride % 2 == 0
            && tile_len.is_multiple_of(stride as usize)
            && stride / 2 <= u16::MAX as u32
            && tile_len / stride as usize <= u16::MAX as usize
            && (8..=16).contains(&bits),
        "Invalid lossless JPEG bound dimensions"
    );
    ensure!(
        predictors.len().checked_mul(238) == Some(histograms.len()),
        "Invalid lossless JPEG bound histograms"
    );
    let depth = ljpeg::Bitdepth::try_from(bits as u8)
        .map_err(|_| anyhow::anyhow!("Invalid JPEG bound precision"))?;
    predictors
        .iter()
        .enumerate()
        .map(|(tile, &predictor)| {
            ensure!((1..=7).contains(&predictor), "Invalid JPEG bound predictor");
            let start = tile * 238 + (predictor as usize - 1) * 34;
            let histogram = [
                histograms[start..start + 17].try_into()?,
                histograms[start + 17..start + 34].try_into()?,
            ];
            let encoder = ljpeg::Encoder::new(
                (stride / 2) as u16,
                (tile_len / stride as usize) as u16,
                ljpeg::Components::C2,
                depth,
                ljpeg::Predictor::try_from(predictor).unwrap(),
                0,
                0,
            );
            let (header, _, entropy_bits) = encoder
                .plan_entropy(&histogram)
                .ok_or_else(|| anyhow::anyhow!("Invalid JPEG bound histogram counts"))?;
            minimum_length(header.len(), entropy_bits)
        })
        .collect()
}
