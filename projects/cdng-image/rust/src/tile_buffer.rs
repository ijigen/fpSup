//! Owned, page-aligned pixels that Metal can read without an upload copy.
use anyhow::{Context, Result};
use std::ops::{Deref, DerefMut};

enum Storage {
    Heap(Vec<u16>),
    #[cfg(target_os = "macos")]
    Shared {
        pointer: std::ptr::NonNull<u16>,
        len: usize,
        layout: std::alloc::Layout,
    },
}
pub(crate) struct TileBuffer { storage: Storage }

impl TileBuffer {
    pub(crate) fn new(len: usize, shared: bool) -> Result<Self> {
        #[cfg(target_os = "macos")]
        if shared && len > 0 {
            unsafe extern "C" { fn getpagesize() -> std::ffi::c_int; }
            let page = unsafe { getpagesize() } as usize;
            anyhow::ensure!(page.is_power_of_two(), "Invalid system page size");
            let bytes = len.checked_mul(std::mem::size_of::<u16>()).context("Tile buffer size overflow")?;
            let capacity = bytes.checked_add(page - 1).context("Tile buffer size overflow")? & !(page - 1);
            let layout = std::alloc::Layout::from_size_align(capacity, page)?;
            // All samples are initialized before exposing a Rust slice. The
            // allocation retains page alignment and complete backing pages for
            // Metal's no-copy view, including any rounded-up trailing bytes.
            let pointer = std::ptr::NonNull::new(unsafe { std::alloc::alloc_zeroed(layout) }.cast::<u16>())
                .context("Cannot allocate shared tile pixels")?;
            return Ok(Self { storage: Storage::Shared { pointer, len, layout } });
        }
        let _ = shared;
        Ok(Self { storage: Storage::Heap(vec![0; len]) })
    }

    pub(crate) fn shared_bytes(&self) -> usize {
        match &self.storage {
            Storage::Heap(_) => 0,
            #[cfg(target_os = "macos")]
            Storage::Shared { layout, .. } => layout.size(),
        }
    }
}

impl Deref for TileBuffer {
    type Target = [u16];
    fn deref(&self) -> &[u16] {
        match &self.storage {
            Storage::Heap(data) => data,
            #[cfg(target_os = "macos")]
            Storage::Shared { pointer, len, .. } => unsafe { std::slice::from_raw_parts(pointer.as_ptr(), *len) },
        }
    }
}
impl DerefMut for TileBuffer {
    fn deref_mut(&mut self) -> &mut [u16] {
        match &mut self.storage {
            Storage::Heap(data) => data,
            #[cfg(target_os = "macos")]
            Storage::Shared { pointer, len, .. } => unsafe { std::slice::from_raw_parts_mut(pointer.as_ptr(), *len) },
        }
    }
}
impl Drop for TileBuffer {
    fn drop(&mut self) {
        #[cfg(target_os = "macos")]
        if let Storage::Shared { pointer, layout, .. } = &self.storage {
            // Every native user is synchronous and has released its no-copy
            // Metal view before this unique owner can be dropped.
            unsafe { std::alloc::dealloc(pointer.as_ptr().cast::<u8>(), *layout) };
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn shared_pixels_are_initialized_aligned_and_page_backed() {
        #[cfg(target_os = "macos")]
        let alignment = {
            unsafe extern "C" { fn getpagesize() -> std::ffi::c_int; }
            unsafe { getpagesize() as usize }
        };
        #[cfg(not(target_os = "macos"))]
        let alignment = 4096;
        for len in [0, 1, 1728, 65536, 100001] {
            let mut pixels = TileBuffer::new(len, true).unwrap();
            assert!(pixels.iter().all(|&p| p == 0));
            if pixels.shared_bytes() != 0 {
                assert_eq!(pixels.as_ptr() as usize % alignment, 0);
                assert_eq!(pixels.shared_bytes() % alignment, 0);
                assert!(pixels.shared_bytes() >= len * 2);
            }
            for (i, p) in pixels.iter_mut().enumerate() { *p = i as u16; }
            assert!(pixels.iter().enumerate().all(|(i, &p)| p == i as u16));
        }
    }
}
