use crate::Backend;
use anyhow::{Result, bail, ensure};
#[cfg(any(target_os = "macos", feature = "cuda"))]
use std::ffi::{CStr, CString};

#[cfg(any(target_os = "macos", feature = "cuda"))]
unsafe extern "C" {
    fn cdng_gpu_hist(
        pixels: *const u16,
        count: u32,
        tiles: u32,
        stride: u32,
        bits: u32,
        mask: u32,
        hist: *mut u32,
        source: *const std::ffi::c_char,
        error: *mut std::ffi::c_char,
        error_size: u32,
    ) -> i32;
    fn cdng_gpu_name() -> *const std::ffi::c_char;
}

#[cfg(target_os = "macos")]
unsafe extern "C" {
    fn cdng_metal_entropy_view(
        pixels: *const u16,
        input_capacity_bytes: usize,
        count: u32,
        source_tiles: u32,
        tiles: u32,
        source_indices: *const u32,
        stride: u32,
        bits: u32,
        codes: *const u32,
        predictors: *const u32,
        decode_lookup: *const u32,
        decode_codes: *const u32,
        damage_for_test: u32,
        max_words: u32,
        body_stride: u32,
        output: *mut *const u8,
        lengths: *mut u32,
        error: *mut std::ffi::c_char,
        error_size: u32,
    ) -> i32;
}

pub struct Gpu {
    pub backend: Backend,
    pub name: String,
}
impl Gpu {
    pub fn entropy_enabled(&self) -> bool {
        Self::entropy_requested(self.backend)
    }
    pub fn entropy_requested(backend: Backend) -> bool {
        backend == Backend::Metal
            && cfg!(target_os = "macos")
            && !std::env::var_os("CDNG_METAL_ENTROPY").is_some_and(|v| v == "0")
    }
    pub fn new(backend: Backend) -> Result<Self> {
        ensure!(backend != Backend::Cpu, "CPU is not a GPU backend");
        ensure!(
            (backend == Backend::Metal && cfg!(target_os = "macos"))
                || (backend == Backend::Cuda
                    && cfg!(feature = "cuda")
                    && !cfg!(target_os = "macos")),
            "此版本未包含所選 GPU 後端；CUDA 需在 NVIDIA 電腦使用 --features cuda 編譯"
        );
        #[cfg(any(target_os = "macos", feature = "cuda"))]
        let name = unsafe { CStr::from_ptr(cdng_gpu_name()) }
            .to_string_lossy()
            .into_owned();
        #[cfg(not(any(target_os = "macos", feature = "cuda")))]
        let name = String::new();
        let gpu = Self { backend, name };
        // Hardware conformance runs before writing any image; no CPU fallback
        // is presented as successful GPU execution.
        for bits in [8, 10, 12, 14, 16] {
            let mask = (1u32 << bits) - 1;
            let pixels: Vec<u16> = (0..1728u32)
                .map(|i| {
                    ((i.wrapping_mul(23417)
                        .wrapping_add(i * i * 11 + i / 576 * 71))
                        & mask) as u16
                })
                .collect();
            let predictors = [1, 2, 3, 4, 5, 6, 7];
            let expected: Vec<u32> = pixels
                .chunks_exact(576)
                .flat_map(|tile| reference(tile, 64, bits, &predictors))
                .collect();
            let actual = gpu.histograms(&pixels, 576, 64, bits, &predictors)?;
            ensure!(actual == expected, "GPU 整數預測驗證失敗");
            if bits == 16 && gpu.entropy_enabled() {
                let encoded = gpu.encode_tiles(&pixels, 576, 64, bits, &[1, 5, 7], &actual)?;
                for (blob, tile) in encoded.iter().zip(pixels.chunks_exact(576)) {
                    let decoded = ljpeg::Decoder::new(blob)
                        .map_err(|e| anyhow::anyhow!("{e:?}"))?
                        .decode()
                        .map_err(|e| anyhow::anyhow!("{e:?}"))?;
                    ensure!(decoded == tile, "Metal 壓縮核心啟動驗證失敗");
                }
            }
        }
        Ok(gpu)
    }
    pub fn histogram(
        &self,
        pixels: &[u16],
        stride: u32,
        bits: u32,
        predictors: &[u8],
    ) -> Result<[u32; 238]> {
        Ok(self.histograms(pixels, pixels.len(), stride, bits, predictors)?[..].try_into()?)
    }
    fn histograms(
        &self,
        pixels: &[u16],
        tile_len: usize,
        stride: u32,
        bits: u32,
        predictors: &[u8],
    ) -> Result<Vec<u32>> {
        ensure!(
            tile_len > 0
                && !pixels.is_empty()
                && pixels.len().is_multiple_of(tile_len)
                && pixels.len() <= u32::MAX as usize,
            "Invalid GPU tile batch"
        );
        let tiles = pixels.len() / tile_len;
        let mut hist = vec![0u32; tiles * 238];
        #[cfg(any(target_os = "macos", feature = "cuda"))]
        {
            let mut error = [0i8; 2048];
            static SOURCE: std::sync::OnceLock<CString> = std::sync::OnceLock::new();
            let source = SOURCE.get_or_init(|| CString::new(concat!(
                "source:",
                include_str!("../../cdng_image/native/predict.metal"),
                "\n",
                include_str!("../../cdng_image/native/entropy.metal"),
                "\n",
                include_str!("../../cdng_image/native/verify.metal")
            )).expect("Embedded Metal source contains no NUL"));
            // SAFETY: all slices are contiguous and remain alive for the
            // synchronous native call; sizes are checked by both layers.
            let code = unsafe {
                cdng_gpu_hist(
                    pixels.as_ptr(),
                    tile_len as u32,
                    tiles as u32,
                    stride,
                    bits,
                    predictors.iter().fold(0, |m, p| m | (1 << (*p - 1))),
                    hist.as_mut_ptr(),
                    source.as_ptr(),
                    error.as_mut_ptr(),
                    2048,
                )
            };
            if code != 0 {
                bail!(
                    "GPU: {}",
                    unsafe { CStr::from_ptr(error.as_ptr()) }.to_string_lossy()
                );
            }
            Ok(hist)
        }
        #[cfg(not(any(target_os = "macos", feature = "cuda")))]
        {
            let _ = (pixels, stride, bits, predictors, &mut hist);
            bail!("GPU backend not compiled")
        }
    }
    pub fn rank(
        &self,
        pixels: &[u16],
        stride: u32,
        bits: u32,
        predictors: &[u8],
    ) -> Result<Vec<u8>> {
        Ok(self
            .rank_tiles(pixels, pixels.len(), stride, bits, predictors)?
            .remove(0))
    }
    pub fn rank_tiles(
        &self,
        pixels: &[u16],
        tile_len: usize,
        stride: u32,
        bits: u32,
        predictors: &[u8],
    ) -> Result<Vec<Vec<u8>>> {
        Ok(self
            .analyze_tiles(pixels, tile_len, stride, bits, predictors)?
            .0)
    }
    pub fn analyze_tiles(
        &self,
        pixels: &[u16],
        tile_len: usize,
        stride: u32,
        bits: u32,
        predictors: &[u8],
    ) -> Result<(Vec<Vec<u8>>, u64, Vec<u32>)> {
        let hist = self.histograms(pixels, tile_len, stride, bits, predictors)?;
        let (ranked, estimate) = Self::analyze_histograms(&hist, predictors)?;
        Ok((ranked, estimate, hist))
    }

    /// Rank precomputed histograms with the same stable costs and tie order as
    /// the individual-geometry search.
    pub fn analyze_histograms(hist: &[u32], predictors: &[u8]) -> Result<(Vec<Vec<u8>>, u64)> {
        ensure!(!hist.is_empty() && hist.len().is_multiple_of(238)
            && !predictors.is_empty() && predictors.iter().all(|p| (1..=7).contains(p)),
            "Invalid predictor histograms");
        let mut estimate = 0;
        let ranked = hist
            .chunks_exact(238)
            .map(|hist| {
                let mut ranked = predictors.to_vec();
                let mut costs = [0; 7];
                for &p in predictors {
                    costs[p as usize - 1] = cost(&hist[(p as usize - 1) * 34..p as usize * 34]);
                }
                ranked.sort_by_key(|p| costs[*p as usize - 1]);
                let best = &hist[(ranked[0] as usize - 1) * 34..ranked[0] as usize * 34];
                // SOI, SOF3, two DHTs, SOS, EOI and the nonzero DC symbols.
                estimate += costs[ranked[0] as usize - 1] + 8 * (74 + best.iter().filter(|&&n| n > 0).count() as u64);
                ranked
            })
            .collect();
        Ok((ranked, estimate))
    }

    pub fn encode_tiles(
        &self,
        pixels: &[u16],
        tile_len: usize,
        stride: u32,
        bits: u32,
        predictors: &[u8],
        histograms: &[u32],
    ) -> Result<Vec<Vec<u8>>> {
        self.encode_tiles_checked(pixels, tile_len, stride, bits, predictors, histograms, 0)
    }
    pub(crate) fn encode_shared_tiles(
        &self, pixels: &crate::tile_buffer::TileBuffer, tile_len: usize,
        stride: u32, bits: u32, predictors: &[u8], histograms: &[u32],
    ) -> Result<Vec<Vec<u8>>> {
        self.encode_tiles_with_input(pixels, pixels.shared_bytes(), tile_len, stride, bits, predictors, histograms, 0, None)
    }
    pub(crate) fn encode_shared_tiles_bounded(
        &self, pixels: &crate::tile_buffer::TileBuffer, tile_len: usize,
        stride: u32, bits: u32, predictors: &[u8], histograms: &[u32], maximum_sizes: Option<&[usize]>,
    ) -> Result<Vec<Vec<u8>>> {
        self.encode_tiles_with_input(pixels, pixels.shared_bytes(), tile_len, stride, bits, predictors, histograms, 0, maximum_sizes)
    }
    fn encode_tiles_checked(
        &self,
        pixels: &[u16],
        tile_len: usize,
        stride: u32,
        bits: u32,
        predictors: &[u8],
        histograms: &[u32],
        damage_for_test: u32,
    ) -> Result<Vec<Vec<u8>>> {
        self.encode_tiles_with_input(pixels, 0, tile_len, stride, bits, predictors, histograms, damage_for_test, None)
    }
    fn encode_tiles_with_input(
        &self, pixels: &[u16], input_capacity_bytes: usize, tile_len: usize,
        stride: u32, bits: u32, predictors: &[u8], histograms: &[u32], damage_for_test: u32,
        maximum_sizes: Option<&[usize]>,
    ) -> Result<Vec<Vec<u8>>> {
        ensure!(
            self.backend == Backend::Metal,
            "GPU entropy is currently implemented for Metal"
        );
        ensure!(
            tile_len > 0
                && !pixels.is_empty()
                && pixels.len().is_multiple_of(tile_len)
                && pixels.len() <= u32::MAX as usize
                && stride >= 2
                && stride % 2 == 0
                && tile_len.is_multiple_of(stride as usize)
                && stride / 2 <= u16::MAX as u32
                && tile_len / (stride as usize) <= u16::MAX as usize,
            "Invalid Metal entropy batch"
        );
        let source_tiles = pixels.len() / tile_len;
        ensure!(
            predictors.len() == source_tiles && histograms.len() == source_tiles * 238
                && maximum_sizes.is_none_or(|sizes| sizes.len() == source_tiles),
            "Invalid entropy tables"
        );
        let mut headers = Vec::with_capacity(source_tiles);
        let mut source_indices = Vec::with_capacity(source_tiles);
        let mut codes = Vec::with_capacity(source_tiles * 34);
        let mut decode_lookup = Vec::with_capacity(source_tiles * 1024);
        let mut decode_codes = Vec::with_capacity(source_tiles * 34);
        let mut max_bits = 0;
        for (t, &p) in predictors.iter().enumerate() {
            ensure!((1..=7).contains(&p), "Invalid JPEG predictor");
            let start = t * 238 + (p as usize - 1) * 34;
            let hist = [
                histograms[start..start + 17].try_into()?,
                histograms[start + 17..start + 34].try_into()?,
            ];
            let encoder = ljpeg::Encoder::new(
                (stride / 2) as u16,
                (tile_len / stride as usize) as u16,
                ljpeg::Components::C2,
                ljpeg::Bitdepth::try_from(bits as u8)
                    .map_err(|_| anyhow::anyhow!("Invalid JPEG depth"))?,
                ljpeg::Predictor::try_from(p).unwrap(),
                0,
                0,
            );
            // Reject exact size-dominated candidates before allocating codes,
            // serializing the prefix, or constructing independent decode tables.
            let Some((header, table, total)) = encoder
                .plan_entropy_bounded(&hist, maximum_sizes.map(|sizes| sizes[t]))
                .ok_or_else(|| anyhow::anyhow!("Invalid entropy histogram"))?
            else { continue; };
            debug_assert!(maximum_sizes.is_none_or(|sizes| {
                crate::gpu_prune::minimum_length(header.len(), total).is_ok_and(|n| n < sizes[t])
            }));
            let (lookup, canonical) = decoding_tables(
                &header,
                (stride / 2) as u16,
                (tile_len / stride as usize) as u16,
                bits as u8,
                p,
            )?;
            ensure!(
                canonical == table,
                "JPEG header and encoder tables disagree"
            );
            decode_lookup.extend(lookup);
            decode_codes.extend(canonical);
            headers.push(header);
            source_indices.push(t as u32);
            codes.extend(table);
            max_bits = max_bits.max(total);
        }
        if headers.is_empty() { return Ok(vec![Vec::new(); source_tiles]); }
        let tiles = headers.len();
        let max_words = u32::try_from(max_bits.div_ceil(32))?;
        let body_stride = max_words
            .checked_mul(8)
            .ok_or_else(|| anyhow::anyhow!("Entropy batch too large"))?;
        let mut lengths = vec![0u32; tiles];
        #[cfg(target_os = "macos")]
        {
            let mut error = [0i8; 2048];
            let mut bodies = std::ptr::null();
            let predictors: Vec<u32> = source_indices.iter().map(|&i| predictors[i as usize] as u32).collect();
            // SAFETY: validated contiguous input/output slices live across this
            // synchronous call. Native code checks dimensions and output limits.
            let result = unsafe {
                cdng_metal_entropy_view(
                    pixels.as_ptr(),
                    input_capacity_bytes,
                    tile_len as u32,
                    source_tiles as u32,
                    tiles as u32,
                    source_indices.as_ptr(),
                    stride,
                    bits,
                    codes.as_ptr(),
                    predictors.as_ptr(),
                    decode_lookup.as_ptr(),
                    decode_codes.as_ptr(),
                    damage_for_test,
                    max_words,
                    body_stride,
                    &mut bodies,
                    lengths.as_mut_ptr(),
                    error.as_mut_ptr(),
                    2048,
                )
            };
            if result != 0 {
                bail!(
                    "Metal entropy: {}",
                    unsafe { CStr::from_ptr(error.as_ptr()) }.to_string_lossy()
                );
            }
            ensure!(!bodies.is_null(), "Missing Metal entropy output");
            // The native per-thread pool owns this shared Metal buffer. Its
            // command has completed, and the view stays valid until the next
            // native entropy call on this thread. Consume it here without any
            // intervening native call; no borrowed bytes escape this function.
            for (t, header) in headers.iter_mut().enumerate() {
                ensure!(lengths[t] <= body_stride, "Invalid entropy output size");
                let offset = t.checked_mul(body_stride as usize)
                    .ok_or_else(|| anyhow::anyhow!("Entropy output offset overflow"))?;
                let body = unsafe { std::slice::from_raw_parts(bodies.add(offset), lengths[t] as usize) };
                // Reserve the trailer together with the body. Otherwise adding
                // EOI after a large exact-sized extension can reallocate and
                // copy the entire JPEG a second time for just two bytes.
                header.reserve(body.len().checked_add(2)
                    .ok_or_else(|| anyhow::anyhow!("JPEG allocation overflow"))?);
                header.extend_from_slice(body);
                header.extend_from_slice(&[255, 217]);
            }
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = (&codes, &mut lengths);
            bail!("Metal entropy backend not compiled");
        }
        // Empty entries mean a candidate proved unable to win, never an empty
        // JPEG. Preserve source order so the caller can merge only actual blobs.
        let mut output = vec![Vec::new(); source_tiles];
        for (source, header) in source_indices.into_iter().zip(headers) {
            output[source as usize] = header;
        }
        Ok(output)
    }
}

// Parse the serialized JPEG prefix independently of the encoder's table builder.
// The checker decodes with these DHT-derived canonical codes, not encoder state.
fn decoding_tables(
    header: &[u8],
    width: u16,
    height: u16,
    bits: u8,
    predictor: u8,
) -> Result<(Vec<u32>, Vec<u32>)> {
    ensure!(header.starts_with(&[255, 216]), "Invalid JPEG prefix");
    let mut lookup = vec![0u32; 1024];
    let mut canonical = vec![0u32; 34];
    let mut tables = [false; 2];
    let mut sof = false;
    let mut sos = false;
    let mut at = 2;
    while at < header.len() {
        ensure!(
            at + 4 <= header.len() && header[at] == 255,
            "Invalid JPEG marker"
        );
        let marker = header[at + 1];
        let length = u16::from_be_bytes([header[at + 2], header[at + 3]]) as usize;
        ensure!(
            length >= 2 && at + 2 + length <= header.len(),
            "Invalid JPEG marker size"
        );
        let data = &header[at + 4..at + 2 + length];
        match marker {
            195 => {
                ensure!(
                    data.len() == 12
                        && data[0] == bits
                        && u16::from_be_bytes([data[1], data[2]]) == height
                        && u16::from_be_bytes([data[3], data[4]]) == width
                        && data[5..] == [2, 0, 17, 0, 1, 17, 0],
                    "Invalid JPEG frame"
                );
                sof = true;
            }
            196 => {
                ensure!(data.len() >= 17 && data[0] < 2, "Invalid JPEG DC table");
                let component = data[0] as usize;
                ensure!(!tables[component], "Duplicate DC table");
                tables[component] = true;
                let mut code = 0u32;
                let mut symbol = 17;
                for n in 1usize..=16 {
                    for _ in 0..data[n] {
                        ensure!(symbol < data.len(), "Truncated DC table");
                        let category = data[symbol] as usize;
                        symbol += 1;
                        ensure!(
                            category <= 16
                                && code < (1u32 << n) - 1
                                && canonical[component * 17 + category] == 0,
                            "Invalid canonical DC code"
                        );
                        canonical[component * 17 + category] = ((n as u32) << 16) | code;
                        if n <= 9 {
                            let start = component * 512 + ((code as usize) << (9 - n));
                            let end = start + (1 << (9 - n));
                            ensure!(
                                lookup[start..end].iter().all(|&v| v == 0),
                                "Overlapping DC codes"
                            );
                            lookup[start..end].fill(((n as u32) << 8) | category as u32);
                        }
                        code += 1;
                    }
                    code <<= 1;
                }
                ensure!(symbol == data.len(), "Extra DC table values");
            }
            218 => {
                ensure!(
                    data == [2, 0, 0, 1, 16, predictor, 0, 0],
                    "Invalid JPEG scan"
                );
                sos = true;
            }
            _ => bail!("Unexpected JPEG prefix marker"),
        }
        at += 2 + length;
    }
    ensure!(
        sof && sos && tables == [true, true],
        "Incomplete JPEG prefix"
    );
    Ok((lookup, canonical))
}

fn cost(hist: &[u32]) -> u64 {
    let mut cost = 0u64;
    for component in 0..2 {
        // At most 17 populated categories and one dummy symbol. A sorted leaf
        // queue plus a sorted merge queue produces the same Huffman cost without
        // allocating a heap for each predictor of every tile and geometry.
        let mut leaves = [0u64; 18];
        leaves[0] = 1;
        let mut count = 1;
        for c in 0..17 {
            let n = u64::from(hist[component * 17 + c]);
            if n > 0 {
                leaves[count] = n;
                count += 1;
            }
            if c < 16 {
                cost += n * c as u64;
            }
        }
        leaves[..count].sort_unstable();
        let mut merged = [0u64; 17];
        let (mut leaf, mut head) = (0, 0);
        for tail in 0..count - 1 {
            let mut sum = 0;
            for _ in 0..2 {
                if leaf < count && (head == tail || leaves[leaf] <= merged[head]) {
                    sum += leaves[leaf];
                    leaf += 1;
                } else {
                    sum += merged[head];
                    head += 1;
                }
            }
            merged[tail] = sum;
            cost += sum;
        }
    }
    cost
}
pub fn reference(pixels: &[u16], stride: u32, bits: u32, predictors: &[u8]) -> [u32; 238] {
    let stride = stride as usize;
    let mut hist = [0; 238];
    for (i, &sample) in pixels.iter().enumerate() {
        let row = i / stride;
        let col = i % stride;
        let a = if col >= 2 { pixels[i - 2] as i32 } else { 0 };
        let b = if row > 0 {
            pixels[i - stride] as i32
        } else {
            0
        };
        let c = if row > 0 && col >= 2 {
            pixels[i - stride - 2] as i32
        } else {
            0
        };
        for &p in predictors {
            let prediction = if row == 0 && col < 2 {
                1 << (bits - 1)
            } else if row == 0 {
                a
            } else if col < 2 {
                b
            } else {
                match p {
                    1 => a,
                    2 => b,
                    3 => c,
                    4 => a + b - c,
                    5 => a + ((b - c) >> 1),
                    6 => b + ((a - c) >> 1),
                    7 => (a + b) >> 1,
                    _ => unreachable!(),
                }
            };
            let mag = ((sample as i32 - prediction) as i16 as i32).unsigned_abs();
            let cat = if mag == 0 {
                0
            } else {
                32 - mag.leading_zeros()
            };
            hist[(p as usize - 1) * 34 + (i % 2) * 17 + cat as usize] += 1;
        }
    }
    hist
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stack_huffman_cost_matches_heap_reference() {
        use std::{cmp::Reverse, collections::BinaryHeap};
        fn original(hist: &[u32]) -> u64 {
            let mut total = 0;
            for component in hist.chunks_exact(17) {
                let mut heap = BinaryHeap::from([Reverse(1u64)]);
                for (category, &n) in component.iter().enumerate() {
                    if n > 0 { heap.push(Reverse(n as u64)); }
                    if category < 16 { total += n as u64 * category as u64; }
                }
                while heap.len() > 1 {
                    let Reverse(a) = heap.pop().unwrap();
                    let Reverse(b) = heap.pop().unwrap();
                    total += a + b;
                    heap.push(Reverse(a + b));
                }
            }
            total
        }
        let mut state = 713u64;
        for case in 0..2048 {
            let mut hist = [0u32; 34];
            for n in &mut hist {
                state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
                *n = if case % 5 == 0 { 0 } else { ((state >> 32) as u32) % (1 + case % 1000) };
            }
            assert_eq!(cost(&hist), original(&hist));
        }
    }
    #[test]
    fn category_16_and_borders() {
        let h = reference(
            &[0, 0, 65535, 32768, 1, 65534, 32768, 0],
            4,
            16,
            &[1, 2, 3, 4, 5, 6, 7],
        );
        for p in 0..7 {
            assert_eq!(h[p * 34..(p + 1) * 34].iter().sum::<u32>(), 8);
        }
    }
    #[test]
    fn bulk_histogram_matches_scalar_reference() {
        if !cfg!(target_os = "macos") || std::env::var_os("CDNG_TEST_GPU").is_none() { return; }
        let gpu = Gpu::new(Backend::Metal).unwrap();
        let count = 65536;
        for bits in [8, 12, 16] {
            let mask = (1u32 << bits) - 1;
            let pixels: Vec<u16> = (0..count*3).map(|i| {
                if i < count { 0 } else { ((i as u32).wrapping_mul(23417) ^ ((i as u32) >> 3)) as u16 & mask as u16 }
            }).collect();
            for predictors in [&[1, 2, 3, 4, 5, 6, 7][..], &[1, 5, 7][..], &[7][..]] {
                let actual = gpu.histograms(&pixels, count, 512, bits, predictors).unwrap();
                let expected: Vec<u32> = pixels.chunks_exact(count).flat_map(|p| reference(p, 512, bits, predictors)).collect();
                assert_eq!(actual, expected);
            }
        }
    }
    #[test]
    fn hardware_conformance_if_requested() {
        if std::env::var_os("CDNG_TEST_GPU").is_some() {
            Gpu::new(if cfg!(target_os = "macos") {
                Backend::Metal
            } else {
                Backend::Cuda
            })
            .unwrap();
        }
    }

    #[test]
    fn metal_entropy_matches_cpu_and_independent_decoder() {
        if !cfg!(target_os = "macos") || std::env::var_os("CDNG_TEST_GPU").is_none() {
            return;
        }
        let gpu = Gpu::new(Backend::Metal).unwrap();
        for bits in [8u32, 10, 12, 14, 16] {
            let mask = (1u32 << bits) - 1;
            for (width, height) in [(1u16, 1u16), (17, 9), (241, 136)] {
                let count = width as usize * height as usize * 2;
                let pixels: Vec<u16> = (0..count * 3)
                    .map(|i| {
                        let local = (i % count) as u32;
                        (match i / count {
                            0 => {
                                local
                                    .wrapping_mul(23417)
                                    .wrapping_add(local.wrapping_mul(local) * 11)
                                    & mask
                            }
                            1 => 1 << (bits - 1),
                            _ => {
                                if local % 4 < 2 {
                                    0
                                } else {
                                    mask
                                }
                            }
                        }) as u16
                    })
                    .collect();
                for p in 1u8..=7 {
                    let hist = gpu
                        .histograms(&pixels, count, width as u32 * 2, bits, &[p])
                        .unwrap();
                    let actual = gpu
                        .encode_tiles(&pixels, count, width as u32 * 2, bits, &[p; 3], &hist)
                        .unwrap();
                    for (tile, blob) in pixels.chunks_exact(count).zip(actual) {
                        let expected = ljpeg::Encoder::new(
                            width,
                            height,
                            ljpeg::Components::C2,
                            ljpeg::Bitdepth::try_from(bits as u8).unwrap(),
                            ljpeg::Predictor::try_from(p).unwrap(),
                            0,
                            0,
                        )
                        .encode(tile)
                        .unwrap();
                        assert_eq!(blob, expected, "{bits}-bit P{p} {width}x{height}");
                        assert_eq!(
                            ljpeg_reference::Decoder::new(&blob)
                                .unwrap()
                                .decode()
                                .unwrap(),
                            tile
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn metal_output_is_owned_across_threads_and_buffer_resizes() {
        if !cfg!(target_os = "macos") || std::env::var_os("CDNG_TEST_GPU").is_none() {
            return;
        }
        let gpu = Gpu::new(Backend::Metal).unwrap();
        std::thread::scope(|scope| {
            for worker in 0..4 {
                let gpu = &gpu;
                scope.spawn(move || {
                    let mut retained = Vec::new();
                    for (round, (width, height)) in [(17, 9), (241, 136), (33, 17), (512, 64), (1, 1), (241, 136)].into_iter().enumerate() {
                        let count = width * height * 2;
                        let bits = [8, 12, 16][(round + worker) % 3];
                        let mask = (1u32 << bits) - 1;
                        let pixels: Vec<u16> = (0..count * 2).map(|i| {
                            ((i as u32).wrapping_mul(23417 + worker as u32 * 2)
                                .wrapping_add(round as u32 * 71) & mask) as u16
                        }).collect();
                        let hist = gpu.histograms(&pixels, count, width as u32 * 2, bits, &[1, 7]).unwrap();
                        let blobs = gpu.encode_tiles(&pixels, count, width as u32 * 2, bits, &[1, 7], &hist).unwrap();
                        let mut shared = crate::tile_buffer::TileBuffer::new(pixels.len(), true).unwrap();
                        shared.copy_from_slice(&pixels);
                        let direct = gpu.encode_shared_tiles(&shared, count, width as u32 * 2, bits, &[1, 7], &hist).unwrap();
                        assert_eq!(direct, blobs, "Shared input changed the JPEG stream");
                        drop(shared);
                        for (blob, tile) in blobs.into_iter().zip(pixels.chunks_exact(count)) {
                            // Keep results alive through later native calls that
                            // overwrite and grow this thread's shared buffers.
                            retained.push((blob, tile.to_vec()));
                        }
                    }
                    for (blob, expected) in retained {
                        let actual = ljpeg_reference::Decoder::new(&blob).unwrap().decode().unwrap();
                        assert_eq!(actual, expected);
                    }
                });
            }
        });
    }

    #[test]
    fn metal_sparse_candidates_match_dense_and_verify_source_indices() {
        if !cfg!(target_os = "macos") || std::env::var_os("CDNG_TEST_GPU").is_none() { return; }
        let gpu = Gpu::new(Backend::Metal).unwrap();
        for bits in [8, 12, 16] {
            let count = 32 * 18 * 2;
            let mask = (1u32 << bits) - 1;
            let pixels: Vec<u16> = (0..count * 6).map(|i| {
                (((i as u32).wrapping_mul(23417) ^ (i / count) as u32 * 71) & mask) as u16
            }).collect();
            let predictors = [1, 2, 3, 4, 5, 7];
            let hist = gpu.histograms(&pixels, count, 64, bits, &[1, 2, 3, 4, 5, 6, 7]).unwrap();
            let dense = gpu.encode_tiles(&pixels, count, 64, bits, &predictors, &hist).unwrap();
            for shared in [false, true] {
                let mut input = crate::tile_buffer::TileBuffer::new(pixels.len(), shared).unwrap();
                input.copy_from_slice(&pixels);
                for retained in [&[0, 1, 2, 3, 4, 5][..], &[1, 3][..], &[0, 2, 5][..], &[5][..], &[][..]] {
                    let mut maximum = vec![1; 6];
                    for &i in retained { maximum[i] = usize::MAX; }
                    let sparse = gpu.encode_shared_tiles_bounded(&input, count, 64, bits, &predictors, &hist, Some(&maximum)).unwrap();
                    for (i, blob) in sparse.iter().enumerate() {
                        if retained.contains(&i) {
                            assert_eq!(*blob, dense[i], "Source tile {i}, shared {shared}");
                            let decoded = ljpeg_reference::Decoder::new(blob).unwrap().decode().unwrap();
                            assert_eq!(decoded, pixels[i * count..(i + 1) * count]);
                        } else { assert!(blob.is_empty()); }
                    }
                }
                let mut maximum = vec![1; 6]; maximum[5] = usize::MAX;
                let error = gpu.encode_tiles_with_input(&input, input.shared_bytes(), count, 64, bits,
                    &predictors, &hist, 1, Some(&maximum)).unwrap_err();
                assert!(error.to_string().contains("Metal RAW verification failed"), "{error}");
            }
        }
    }

    #[test]
    fn metal_raw_checker_rejects_corrupted_stream_and_boundaries() {
        if !cfg!(target_os = "macos") || std::env::var_os("CDNG_TEST_GPU").is_none() {
            return;
        }
        let gpu = Gpu::new(Backend::Metal).unwrap();
        let pixels = vec![32768u16; 1728];
        let hist = gpu.histograms(&pixels, 576, 64, 16, &[7]).unwrap();
        for damage in [1, 2, 3] {
            let error = gpu
                .encode_tiles_checked(&pixels, 576, 64, 16, &[7; 3], &hist, damage)
                .unwrap_err();
            assert!(
                error.to_string().contains("Metal RAW verification failed"),
                "{error}"
            );
        }
    }
}
