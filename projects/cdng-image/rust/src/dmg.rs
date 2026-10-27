//! Append an uncompressed UDIF envelope to an already streamed disk image.
//! The data fork stays in place: no second image and no payload rewrite.
use anyhow::{Result, ensure};
use std::{
    fs::OpenOptions,
    io::{Seek, SeekFrom, Write},
    path::Path,
    sync::atomic::AtomicBool,
};
fn put32(b: &mut [u8], at: usize, n: u32) {
    b[at..at + 4].copy_from_slice(&n.to_be_bytes());
}
fn put64(b: &mut [u8], at: usize, n: u64) {
    b[at..at + 8].copy_from_slice(&n.to_be_bytes());
}
fn b64(b: &[u8]) -> String {
    const T: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::new();
    for c in b.chunks(3) {
        let n = ((c[0] as u32) << 16)
            | ((c.get(1).copied().unwrap_or(0) as u32) << 8)
            | c.get(2).copied().unwrap_or(0) as u32;
        out.push(T[(n >> 18) as usize] as char);
        out.push(T[((n >> 12) & 63) as usize] as char);
        out.push(if c.len() > 1 {
            T[((n >> 6) & 63) as usize] as char
        } else {
            '='
        });
        out.push(if c.len() > 2 {
            T[(n & 63) as usize] as char
        } else {
            '='
        });
    }
    out
}
pub fn finish(path: &Path, cancel: &AtomicBool) -> Result<u64> {
    finish_with_checksum(path, cancel, None)
}
pub(crate) fn finish_with_checksum(
    path: &Path,
    cancel: &AtomicBool,
    checksum: Option<(u64, u32)>,
) -> Result<u64> {
    crate::cancelled(cancel)?;
    let mut f = OpenOptions::new().read(true).write(true).open(path)?;
    let size = f.metadata()?.len();
    ensure!(size > 0 && size % 512 == 0, "Invalid disk image size");
    let crc = if let Some((bytes, crc)) = checksum {
        ensure!(bytes == size, "DMG checksum length differs from data fork");
        crc
    } else {
        let mut digest = crc32fast::Hasher::new();
        // The finalized, privately owned data fork stays unchanged during this scan.
        let mapped = unsafe {
            memmap2::MmapOptions::new()
                .len(usize::try_from(size)?)
                .map(&f)?
        };
        for bytes in mapped.chunks(1 << 20) {
            crate::cancelled(cancel)?;
            digest.update(bytes);
        }
        drop(mapped);
        digest.finalize()
    };
    let sectors = size / 512;
    let mut map = vec![0; 284];
    map[..4].copy_from_slice(b"mish");
    put32(&mut map, 4, 1);
    put64(&mut map, 16, sectors);
    put32(&mut map, 36, 0xfffffffe);
    put32(&mut map, 64, 2);
    put32(&mut map, 68, 32);
    put32(&mut map, 72, crc);
    put32(&mut map, 200, 2);
    put32(&mut map, 204, 1);
    put64(&mut map, 220, sectors);
    put64(&mut map, 236, size);
    put32(&mut map, 244, u32::MAX);
    put64(&mut map, 252, sectors);
    put64(&mut map, 268, size);
    let xml = format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?><!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\"><plist version=\"1.0\"><dict><key>resource-fork</key><dict><key>blkx</key><array><dict><key>Attributes</key><string>0x0050</string><key>CFName</key><string>CDNG Image (Apple_ISO : 0)</string><key>Name</key><string>CDNG Image (Apple_ISO : 0)</string><key>ID</key><string>0</string><key>Data</key><data>{}</data></dict></array></dict></dict></plist>",
        b64(&map)
    );
    let mut trailer = [0; 512];
    trailer[..4].copy_from_slice(b"koly");
    put32(&mut trailer, 4, 4);
    put32(&mut trailer, 8, 512);
    put32(&mut trailer, 12, 1);
    put64(&mut trailer, 32, size);
    put32(&mut trailer, 56, 1);
    put32(&mut trailer, 60, 1);
    // Stable content-derived segment identity; single-segment image.
    let id = crate::hash(&map);
    trailer[64..80].copy_from_slice(&id.as_bytes()[..16]);
    put32(&mut trailer, 80, 2);
    put32(&mut trailer, 84, 32);
    put32(&mut trailer, 88, crc);
    put64(&mut trailer, 216, size);
    put64(&mut trailer, 224, xml.len() as u64);
    put32(&mut trailer, 352, 2);
    put32(&mut trailer, 356, 32);
    put32(&mut trailer, 360, crc32fast::hash(&crc.to_be_bytes()));
    put32(&mut trailer, 488, 2);
    put64(&mut trailer, 492, sectors);
    f.seek(SeekFrom::End(0))?;
    crate::cancelled(cancel)?;
    f.write_all(xml.as_bytes())?;
    f.write_all(&trailer)?;
    f.sync_all()?;
    Ok(size + xml.len() as u64 + 512)
}
