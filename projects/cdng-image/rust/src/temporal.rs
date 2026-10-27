//! Reversible Bayer time cubes, based on validation/jpegls-20261024/cube_eval.py.
//! Every group also encodes independent frames and retains the smaller representation.
use crate::{Backend, Effort, cancelled, jxl};
use anyhow::{Context, Result, ensure};
use std::sync::atomic::AtomicBool;

pub const MAX_FRAMES: usize = 8;
pub const MAX_GROUP_BYTES: usize = 192 << 20;
const MAGIC: &[u8; 8] = b"CDNGTC01";
const HEADER_BYTES: usize = 40;
// More than the extra serialized temporal reference and changed offset/size digits
// per entry. Require this margin before choosing a shared cube payload.
const REFERENCE_ALLOWANCE: usize = 128;

pub struct EncodedGroup {
    pub payloads: Vec<Vec<u8>>,
    pub temporal: bool,
}

fn shape(w: usize, h: usize, count: usize) -> Result<usize> {
    ensure!(w > 0 && h > 0 && w % 2 == 0 && h % 2 == 0, "Temporal Bayer frames need positive even dimensions");
    ensure!((1..=MAX_FRAMES).contains(&count), "Invalid temporal group length");
    let n = w.checked_mul(h).context("Temporal dimensions overflow")?;
    let bytes = n.checked_mul(count).and_then(|n| n.checked_mul(2)).context("Temporal group overflow")?;
    ensure!(n <= 100_000_000 && bytes <= MAX_GROUP_BYTES.max(n * 2), "Temporal group exceeds memory limit");
    // One oversized frame can still use independent coding; multi-frame groups are bounded.
    ensure!(count == 1 || bytes <= MAX_GROUP_BYTES, "Temporal group exceeds memory limit");
    Ok(n)
}

/// Metal scratch uses complete 128×128 groups, including edge padding. Keep
/// unusual narrow/tall inputs on the CPU so a small RAW buffer cannot require
/// enormous padded scratch or overflow the encoder's u32 group stride.
#[cfg(any(target_os = "macos", test))]
fn metal_geometry(w: usize, h: usize, count: usize) -> bool {
    let Some(actual) = w.checked_mul(h).and_then(|n| n.checked_mul(count)) else { return false };
    if actual == 0 { return false; }
    let Some(groups) = w.div_ceil(128).checked_mul(h.div_ceil(128)) else { return false };
    if groups <= 1 { return false; }
    let Some(stride) = groups.checked_mul(128 * 128) else { return false };
    if stride > u32::MAX as usize { return false; }
    let Some(padded) = stride.checked_mul(count) else { return false };
    // Bound both amplification and total batch scratch. Normal camera frames
    // have little padding; CPU fallback changes neither bit depth nor quality.
    padded <= 128 << 20 && actual.checked_mul(4).is_some_and(|limit| padded <= limit)
}

/// One colour plane: cube row y*T+s contains frame s (T-1-s on odd y).
/// Thus north is normally the same sensor position at the neighbouring time.
fn plane(frames: &[&[u16]], w: usize, h: usize, colour: usize) -> Result<Vec<u16>> {
    let n = shape(w, h, frames.len())?;
    ensure!(colour < 4 && frames.iter().all(|f| f.len() == n), "Invalid temporal input");
    let (pw, ph, count) = (w / 2, h / 2, frames.len());
    let (cy, cx) = (colour / 2, colour % 2);
    let mut pixels = vec![0; n / 4 * count];
    for y in 0..ph {
        for s in 0..count {
            let t = if y % 2 == 0 { s } else { count - 1 - s };
            let src = &frames[t][(y * 2 + cy) * w..];
            let row = &mut pixels[(y * count + s) * pw..][..pw];
            for (x, out) in row.iter_mut().enumerate() { *out = src[x * 2 + cx]; }
        }
    }
    Ok(pixels)
}

fn restore_plane(out: &mut [u16], pixels: &[u16], w: usize, h: usize, count: usize, colour: usize) -> Result<()> {
    let n = shape(w, h, count)?;
    ensure!(out.len() == n * count && pixels.len() == n / 4 * count && colour < 4, "Invalid temporal plane size");
    let (pw, ph) = (w / 2, h / 2);
    let (cy, cx) = (colour / 2, colour % 2);
    for y in 0..ph {
        for s in 0..count {
            let t = if y % 2 == 0 { s } else { count - 1 - s };
            let row = &pixels[(y * count + s) * pw..][..pw];
            let dst = &mut out[t * n + (y * 2 + cy) * w..];
            for (x, value) in row.iter().enumerate() { dst[x * 2 + cx] = *value; }
        }
    }
    Ok(())
}

fn envelope(streams: &[Vec<u8>]) -> Result<Vec<u8>> {
    ensure!(streams.len() == 4 && streams.iter().all(|s| !s.is_empty()), "Temporal cube needs four colour streams");
    let mut bytes = Vec::with_capacity(HEADER_BYTES + streams.iter().map(Vec::len).sum::<usize>());
    bytes.extend_from_slice(MAGIC);
    for stream in streams { bytes.extend_from_slice(&(stream.len() as u64).to_le_bytes()); }
    for stream in streams { bytes.extend_from_slice(stream); }
    Ok(bytes)
}

fn streams(bytes: &[u8]) -> Result<[&[u8]; 4]> {
    ensure!(bytes.len() >= HEADER_BYTES && &bytes[..8] == MAGIC, "Invalid temporal payload header");
    let mut at = HEADER_BYTES;
    let mut streams = [&[][..]; 4];
    for (i, stream) in streams.iter_mut().enumerate() {
        let len = usize::try_from(u64::from_le_bytes(bytes[8 + i * 8..16 + i * 8].try_into()?))?;
        let end = at.checked_add(len).context("Temporal payload range overflow")?;
        ensure!(len > 0 && end <= bytes.len(), "Truncated temporal payload");
        *stream = &bytes[at..end]; at = end;
    }
    ensure!(at == bytes.len(), "Unexpected trailing temporal data");
    Ok(streams)
}

/// Independent, portable reconstruction used by archive reads and extraction.
/// Samples retain their source bit depth, without rescaling or demosaicing.
pub fn decode_cube(codec: &jxl::Codec, payload: &[u8], w: usize, h: usize, count: usize, bits: u32) -> Result<Vec<u16>> {
    let n = shape(w, h, count)?;
    ensure!(count >= 2 && (8..=16).contains(&bits), "Invalid temporal coding parameters");
    let streams = streams(payload)?;
    let mut out = vec![0; n * count];
    for (colour, stream) in streams.iter().enumerate() {
        let pixels = codec.decode_bits(stream, w / 2, h / 2 * count, bits)?;
        restore_plane(&mut out, &pixels, w, h, count, colour)?;
    }
    Ok(out)
}

#[cfg(target_os = "macos")]
struct Metal {
    encoder: jxl_metal::encode::Encoder,
    decoder: jxl_metal::decode::Decoder,
    key: String,
    frame: Option<jxl_metal::encode::Model>,
    cubes: Vec<jxl_metal::encode::Model>,
    cube_count: usize,
}

pub struct GroupCoder {
    cpu: std::sync::Arc<jxl::Codec>,
    effort: Effort,
    #[cfg(target_os = "macos")]
    metal: Option<Metal>,
}

impl GroupCoder {
    pub fn new(backend: Backend, effort: Effort) -> Result<Self> {
        ensure!(backend != Backend::Cuda, "Temporal JPEG XL CUDA is not implemented; use CPU");
        #[cfg(not(target_os = "macos"))]
        ensure!(backend == Backend::Cpu, "Metal requires macOS");
        let cpu = jxl::Codec::load()?;
        #[cfg(target_os = "macos")]
        let metal = if backend == Backend::Metal {
            Some(Metal { encoder: jxl_metal::encode::Encoder::new()?, decoder: jxl_metal::decode::Decoder::new()?,
                key: String::new(), frame: None, cubes: Vec::new(), cube_count: 0 })
        } else { None };
        Ok(Self { cpu, effort, #[cfg(target_os = "macos")] metal })
    }

    pub fn version(&self) -> u32 { self.cpu.version() }

    pub fn encode(&mut self, clip_key: &str, frames: &[&[u16]], w: usize, h: usize, bits: usize, cancel: &AtomicBool) -> Result<EncodedGroup> {
        let n = shape(w, h, frames.len())?;
        ensure!((8..=16).contains(&bits) && frames.iter().all(|f| f.len() == n), "Invalid temporal frames");
        ensure!(frames.iter().all(|f| f.iter().all(|&v| u32::from(v) < (1u32 << bits))), "RAW sample exceeds declared bit depth");
        cancelled(cancel)?;
        // The Metal decoder currently uses signed 16-bit samples and cannot decode
        // single-group images. Preserve these inputs through the full-range CPU codec.
        #[cfg(target_os = "macos")]
        let use_metal = self.metal.is_some() && bits <= 15
            && metal_geometry(w, h, frames.len())
            && (frames.len() == 1 || metal_geometry(w / 2, h / 2 * frames.len(), 1));
        #[cfg(not(target_os = "macos"))]
        let use_metal = false;
        let settings = jxl::Settings { bits: bits as u32,
            effort: match self.effort { Effort::Fast => 3, Effort::Balanced => 5, Effort::Max => 7 },
            tier: if self.effort == Effort::Max { 1 } else { 0 }, buffering: 0, group: 0 };
        let mut ordinary: Vec<Vec<u16>> = frames.iter().map(|f| f.to_vec()).collect();
        for f in &mut ordinary { jxl::cfa_permute(f, w, h, false)?; }
        let refs: Vec<&[u16]> = ordinary.iter().map(Vec::as_slice).collect();
        let independent;
        #[cfg(target_os = "macos")]
        if use_metal {
            let gpu = self.metal.as_mut().unwrap();
            let key = format!("{clip_key}:{w}:{h}:{bits}");
            if gpu.key != key {
                gpu.key = key; gpu.frame = None; gpu.cubes.clear(); gpu.cube_count = 0;
            }
            if gpu.frame.is_none() { gpu.frame = Some(gpu.encoder.learn(refs[0], w, h)?); }
            cancelled(cancel)?;
            independent = gpu.encoder.encode(gpu.frame.as_ref().unwrap(), &refs, w, h, bits as u32)?.0;
            verify_metal(&gpu.decoder, &independent, &refs, w, h)?;
        } else {
            independent = cpu_encode(&self.cpu, &refs, w, h, &settings, cancel)?;
        }
        #[cfg(not(target_os = "macos"))]
        { independent = cpu_encode(&self.cpu, &refs, w, h, &settings, cancel)?; }
        drop(refs); drop(ordinary);
        cancelled(cancel)?;
        if frames.len() == 1 { return Ok(EncodedGroup { payloads: independent, temporal: false }); }
        let (pw, ph) = (w / 2, h / 2 * frames.len());
        let mut coded = Vec::with_capacity(4);
        #[cfg(target_os = "macos")]
        if use_metal && self.metal.as_ref().unwrap().cube_count != frames.len() {
            let gpu = self.metal.as_mut().unwrap(); gpu.cubes.clear(); gpu.cube_count = frames.len();
        }
        for colour in 0..4 {
            cancelled(cancel)?;
            let pixels = plane(frames, w, h, colour)?;
            #[cfg(target_os = "macos")]
            if use_metal {
                let gpu = self.metal.as_mut().unwrap();
                if gpu.cubes.len() <= colour { gpu.cubes.push(gpu.encoder.learn(&pixels, pw, ph)?); }
                cancelled(cancel)?;
                let stream = gpu.encoder.encode(&gpu.cubes[colour], &[&pixels], pw, ph, bits as u32)?.0;
                verify_metal(&gpu.decoder, &stream, &[&pixels], pw, ph)?;
                coded.push(stream.into_iter().next().context("Missing temporal stream")?);
            } else {
                coded.push(cpu_encode(&self.cpu, &[&pixels], pw, ph, &settings, cancel)?.remove(0));
            }
            #[cfg(not(target_os = "macos"))]
            { coded.push(cpu_encode(&self.cpu, &[&pixels], pw, ph, &settings, cancel)?.remove(0)); }
        }
        cancelled(cancel)?;
        let cube = envelope(&coded)?;
        if choose_cube(cube.len(), independent.iter().map(Vec::len).sum(), frames.len()) {
            Ok(EncodedGroup { payloads: vec![cube], temporal: true })
        } else { Ok(EncodedGroup { payloads: independent, temporal: false }) }
    }
}

fn choose_cube(cube: usize, independent: usize, count: usize) -> bool {
    cube.checked_add(REFERENCE_ALLOWANCE * count + HEADER_BYTES).is_some_and(|cost| cost < independent)
}

fn cpu_encode(codec: &jxl::Codec, frames: &[&[u16]], w: usize, h: usize, settings: &jxl::Settings, cancel: &AtomicBool) -> Result<Vec<Vec<u8>>> {
    frames.iter().map(|pixels| {
        cancelled(cancel)?;
        let stream = codec.encode_with(pixels, w, h, settings)?;
        cancelled(cancel)?;
        ensure!(codec.decode_bits(&stream, w, h, settings.bits)?.as_slice() == *pixels, "Temporal JPEG XL changed RAW samples");
        Ok(stream)
    }).collect()
}

#[cfg(target_os = "macos")]
fn verify_metal(decoder: &jxl_metal::decode::Decoder, streams: &[Vec<u8>], expected: &[&[u16]], w: usize, h: usize) -> Result<()> {
    ensure!(streams.len() == expected.len(), "Missing JPEG XL frames");
    let refs: Vec<&[u8]> = streams.iter().map(Vec::as_slice).collect();
    let mut seen = 0; let mut bad = false;
    decoder.decode_with(&refs, |i, dw, dh, pixels| {
        seen += 1; bad |= i >= expected.len() || dw != w || dh != h || pixels != expected[i];
    })?;
    ensure!(!bad && seen == expected.len(), "Temporal JPEG XL changed RAW samples");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn metal_geometry_bounds_padding_batch_scratch_and_overflow() {
        assert!(metal_geometry(3024, 2010, 8));
        assert!(metal_geometry(1512, 8040, 1));
        assert!(metal_geometry(7680, 4320, 3));
        assert!(metal_geometry(130, 130, 8));
        assert!(!metal_geometry(128, 128, 8), "single-group images require CPU");
        assert!(!metal_geometry(2, 50_000_000, 1), "padded stride must not overflow u32");
        assert!(!metal_geometry(2, 1000, 8), "narrow frames must not amplify scratch 64 times");
        assert!(!metal_geometry(32, 3_000_000, 1), "total padded scratch is bounded even within the amplification limit");
        assert!(!metal_geometry(64, 150_000, 8), "the bound applies to the full batch");
        assert!(!metal_geometry(usize::MAX, usize::MAX, 8));
        assert!(!metal_geometry(usize::MAX, 1, 1));
        assert!(!metal_geometry(0, 2010, 8));
        assert!(!metal_geometry(3024, 2010, 0));
    }
    #[test]
    fn snake_planes_match_reference_axes_and_roundtrip_every_sample() {
        for (w,h) in [(2,2),(6,10),(258,130)] {
            for count in 1..=8 {
                let frames: Vec<Vec<u16>> = (0..count).map(|t| (0..w*h).map(|p| ((t*7919+p*47)&65535) as u16).collect()).collect();
                let refs: Vec<&[u16]> = frames.iter().map(Vec::as_slice).collect();
                let mut restored = vec![0;w*h*count];
                for colour in 0..4 {
                    let cube = plane(&refs,w,h,colour).unwrap();
                    for y in 0..h/2 { for t in 0..count { for x in 0..w/2 {
                        let s=if y%2==0 { t } else {count-1-t};
                        assert_eq!(cube[(y*count+s)*(w/2)+x],frames[t][(y*2+colour/2)*w+x*2+colour%2]);
                    } } }
                    restore_plane(&mut restored,&cube,w,h,count,colour).unwrap();
                }
                assert_eq!(restored, frames.concat());
            }
        }
    }
    #[test]
    fn framing_rejects_truncation_overflow_and_trailing_data() {
        let blobs=vec![vec![1,2],vec![3],vec![4,5,6],vec![7]];
        let good=envelope(&blobs).unwrap();
        assert_eq!(streams(&good).unwrap().to_vec(),blobs.iter().map(Vec::as_slice).collect::<Vec<_>>());
        for n in 0..good.len() { assert!(streams(&good[..n]).is_err()); }
        let mut bad=good.clone(); bad.extend([0]); assert!(streams(&bad).is_err());
        let mut bad=good.clone(); bad[8..16].copy_from_slice(&u64::MAX.to_le_bytes()); assert!(streams(&bad).is_err());
        let mut bad=good; bad[8..16].fill(0); assert!(streams(&bad).is_err());
    }
    #[test]
    fn adaptive_choice_includes_reference_overhead_and_preserves_ties() {
        assert!(!choose_cube(1000,1000,8));
        assert!(!choose_cube(1000,2000,8));
        assert!(choose_cube(1000,3000,8));
        assert!(!choose_cube(usize::MAX,usize::MAX,8));
        assert!(shape(2,3,8).is_err()); assert!(shape(2,2,9).is_err());
        assert!(shape(8192,8192,8).is_err());
    }
}
