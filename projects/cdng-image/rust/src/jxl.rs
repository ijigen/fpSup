//! libjxl calls borrow input and write directly to Rust-owned output allocations.
use anyhow::{Result, bail, ensure};
use std::{
    ffi::{CString, c_void},
    path::PathBuf,
    sync::Arc,
};
unsafe extern "C" {
    fn cdng_jxl_open(path: *const std::ffi::c_char) -> *mut c_void;
    fn cdng_jxl_close(ptr: *mut c_void);
    fn cdng_jxl_version(ptr: *mut c_void) -> u32;
    fn cdng_jxl_encode(
        ptr: *mut c_void,
        pixels: *const u16,
        w: u32,
        h: u32,
        bits: u32,
        effort: i32,
        tier: i32,
        buffering: i32,
        group: i32,
        out: *mut u8,
        cap: usize,
        used: *mut usize,
    ) -> i32;
    fn cdng_jxl_decode(
        ptr: *mut c_void,
        data: *const u8,
        len: usize,
        w: u32,
        h: u32,
        bits: u32,
        out: *mut u16,
        count: usize,
    ) -> i32;
}
/// Encoder settings; `buffering` / `group` < 0 keep libjxl's defaults.
pub struct Settings {
    pub bits: u32,
    pub effort: i32,
    pub tier: i32,
    pub buffering: i32,
    pub group: i32,
}
pub struct Codec(*mut c_void);
// The handle contains immutable function pointers. Each operation owns its codec context.
unsafe impl Send for Codec {}
unsafe impl Sync for Codec {}
impl Drop for Codec {
    fn drop(&mut self) {
        unsafe { cdng_jxl_close(self.0) }
    }
}
impl Codec {
    pub fn load() -> Result<Arc<Self>> {
        let mut paths = Vec::<PathBuf>::new();
        if let Some(path) = std::env::var_os("CDNG_JXL_LIBRARY") {
            paths.push(path.into());
        }
        if let Ok(exe) = std::env::current_exe() {
            if let Some(parent) = exe.parent() {
                for base in [parent.to_path_buf(), parent.join("../Frameworks")] {
                    for name in [
                        "libjxl.0.12.0.dylib",
                        "libjxl.dylib",
                        "jxl.dll",
                        "libjxl.so.0.12",
                        "libjxl.so",
                    ] {
                        paths.push(base.join(name));
                    }
                }
            }
        }
        paths.extend(
            [
                "/opt/homebrew/lib/libjxl.dylib",
                "/usr/local/lib/libjxl.dylib",
            ]
            .map(PathBuf::from),
        );
        for path in paths {
            if path.is_file() {
                let text = CString::new(path.to_string_lossy().as_bytes())?;
                let ptr = unsafe { cdng_jxl_open(text.as_ptr()) };
                if !ptr.is_null() {
                    return Ok(Arc::new(Self(ptr)));
                }
            }
        }
        bail!(
            "找不到相容的 libjxl（需要 0.11.2 以上）。請使用包含 JPEG XL 元件的版本，或設定 CDNG_JXL_LIBRARY。"
        )
    }
    pub fn version(&self) -> u32 {
        unsafe { cdng_jxl_version(self.0) }
    }
    pub fn encode(&self, pixels: &[u16], w: usize, h: usize, effort: i32, tier: i32) -> Result<Vec<u8>> {
        self.encode_with(pixels, w, h, &Settings { bits: 16, effort, tier, buffering: -1, group: -1 })
    }
    /// Lossless encode; samples are stored at `settings.bits` exactly as given.
    pub fn encode_with(&self, pixels: &[u16], w: usize, h: usize, settings: &Settings) -> Result<Vec<u8>> {
        ensure!((8..=16).contains(&settings.bits), "Invalid JXL bit depth");
        ensure!(
            w.checked_mul(h) == Some(pixels.len()) && w > 0 && h > 0 && pixels.len() <= 100_000_000,
            "Invalid JXL dimensions"
        );
        // Raw size is a conservative first allocation; uncommon expansion retries only.
        let mut capacity = pixels.len() * 2 + 65536;
        loop {
            let mut out = Vec::<u8>::with_capacity(capacity);
            let mut used = 0;
            let status = unsafe {
                cdng_jxl_encode(
                    self.0,
                    pixels.as_ptr(),
                    w as u32,
                    h as u32,
                    settings.bits,
                    settings.effort,
                    settings.tier,
                    settings.buffering,
                    settings.group,
                    out.as_mut_ptr(),
                    capacity,
                    &mut used,
                )
            };
            if status == 0 {
                ensure!(used <= capacity, "JXL output overflow");
                unsafe { out.set_len(used) };
                return Ok(out);
            }
            ensure!(
                status == 2 && capacity < pixels.len() * 4 + 1_048_576,
                "JPEG XL encoding failed"
            );
            capacity *= 2;
        }
    }
    pub fn decode(&self, data: &[u8], w: usize, h: usize) -> Result<Vec<u16>> {
        self.decode_bits(data, w, h, 16)
    }
    /// Decodes a stream whose samples are stored at `bits`; values come back unscaled.
    pub fn decode_bits(&self, data: &[u8], w: usize, h: usize, bits: u32) -> Result<Vec<u16>> {
        let n = w
            .checked_mul(h)
            .filter(|&n| n > 0 && n <= 100_000_000)
            .ok_or_else(|| anyhow::anyhow!("Invalid JXL dimensions"))?;
        let mut out = Vec::<u16>::with_capacity(n);
        // libjxl initializes every sample before success. Failed output stays length zero.
        ensure!(
            unsafe {
                cdng_jxl_decode(
                    self.0,
                    data.as_ptr(),
                    data.len(),
                    w as u32,
                    h as u32,
                    bits,
                    out.as_mut_ptr(),
                    n,
                )
            } == 0,
            "JPEG XL decoding failed or dimensions changed"
        );
        unsafe { out.set_len(n) };
        Ok(out)
    }
}
/// Even/odd row and column permutations use one row of scratch, never a frame copy.
pub fn cfa_permute(pixels: &mut [u16], w: usize, h: usize, inverse: bool) -> Result<()> {
    ensure!(
        w > 0 && h > 0 && w % 2 == 0 && h % 2 == 0 && w.checked_mul(h) == Some(pixels.len()),
        "Bayer phase permutation requires even dimensions"
    );
    let mut scratch = vec![0; w];
    for row in pixels.chunks_exact_mut(w) {
        for x in 0..w {
            let to = if inverse {
                if x < w / 2 {
                    x * 2
                } else {
                    (x - w / 2) * 2 + 1
                }
            } else {
                x / 2 + (x % 2) * (w / 2)
            };
            scratch[to] = row[x];
        }
        row.copy_from_slice(&scratch);
    }
    let mut visited = vec![false; h];
    for start in 0..h {
        if visited[start] {
            continue;
        }
        scratch.copy_from_slice(&pixels[start * w..(start + 1) * w]);
        let mut at = start;
        loop {
            visited[at] = true;
            let to = if inverse {
                if at < h / 2 {
                    at * 2
                } else {
                    (at - h / 2) * 2 + 1
                }
            } else {
                at / 2 + (at % 2) * (h / 2)
            };
            for x in 0..w {
                std::mem::swap(&mut scratch[x], &mut pixels[to * w + x]);
            }
            at = to;
            if at == start {
                break;
            }
        }
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn permutations_are_reversible_for_non_power_of_two_rows() {
        for (h, w) in [(2, 2), (6, 14), (1090, 16), (2170, 8)] {
            let original: Vec<_> = (0..w * h).map(|x| x as u16).collect();
            let mut p = original.clone();
            cfa_permute(&mut p, w, h, false).unwrap();
            for y in 0..h {
                for x in 0..w {
                    assert_eq!(
                        p[(y / 2 + y % 2 * (h / 2)) * w + x / 2 + x % 2 * (w / 2)],
                        original[y * w + x]
                    );
                }
            }
            cfa_permute(&mut p, w, h, true).unwrap();
            assert_eq!(p, original);
        }
    }
}
