//! Preview discovery only: packing keeps its separate, strict file inventory.
//! macOS supplies file types and lengths in batches instead of a stat per frame.
use super::{Clip, MANIFEST, is_dng_source};
use crate::cancelled;
use anyhow::{Context, Result, ensure};
use std::{
    fs,
    path::{Path, PathBuf},
    sync::atomic::AtomicBool,
};

struct Entry {
    path: PathBuf,
    directory: bool,
    bytes: Option<u64>,
}

pub(super) fn scan(source: &Path, cancel: &AtomicBool, mut emit: impl FnMut(Clip)) -> Result<()> {
    cancelled(cancel)?;
    let source = source.canonicalize()?;
    ensure!(source.is_dir(), "請選擇素材資料夾");
    // An explicit stack avoids deep recursive calls. Children are visited in
    // sorted order, and the parent clip (if present) precedes its descendants.
    let mut pending = vec![source.clone()];
    while let Some(directory) = pending.pop() {
        cancelled(cancel)?;
        let entries = directory_entries(&directory, cancel)
            .with_context(|| format!("無法讀取資料夾：{}", directory.display()))?;
        let mut children = Vec::new();
        let mut frames = Vec::new();
        let mut bytes = 0u64;
        for entry in entries {
            cancelled(cancel)?;
            let relative = entry
                .path
                .strip_prefix(&source)?
                .to_str()
                .context("Non-Unicode filename")?;
            ensure!(
                !relative.eq_ignore_ascii_case(MANIFEST),
                "Source contains reserved manifest name"
            );
            if entry.directory {
                children.push(entry.path);
            } else if is_dng_source(&entry.path) {
                bytes = bytes
                    .checked_add(entry.bytes.context("Missing frame size")?)
                    .context("素材大小超出範圍")?;
                frames.push(entry.path);
            }
        }
        if !frames.is_empty() {
            frames.sort();
            cancelled(cancel)?;
            emit(Clip {
                relative: directory
                    .strip_prefix(&source)?
                    .to_str()
                    .context("Non-Unicode filename")?
                    .replace('\\', "/"),
                frames,
                bytes,
            });
        }
        children.sort();
        pending.extend(children.into_iter().rev());
    }
    cancelled(cancel)
}

fn portable_entries(directory: &Path, cancel: &AtomicBool) -> Result<Vec<Entry>> {
    let mut entries = Vec::new();
    for entry in fs::read_dir(directory)? {
        cancelled(cancel)?;
        let entry = entry?;
        let path = entry.path();
        let kind = entry.file_type()?;
        ensure!(
            kind.is_file() || kind.is_dir(),
            "不支援連結或特殊檔案：{}",
            path.display()
        );
        let bytes = if kind.is_file() && is_dng_source(&path) {
            Some(entry.metadata()?.len())
        } else {
            None
        };
        entries.push(Entry {
            path,
            directory: kind.is_dir(),
            bytes,
        });
    }
    Ok(entries)
}

fn directory_entries(directory: &Path, cancel: &AtomicBool) -> Result<Vec<Entry>> {
    #[cfg(target_os = "macos")]
    match macos::entries(directory, cancel) {
        Ok(entries) => return Ok(entries),
        // Some mounted/network filesystems do not implement bulk attributes.
        Err(error)
            if error
                .downcast_ref::<std::io::Error>()
                .is_some_and(|e| matches!(e.raw_os_error(), Some(22 | 45 | 78 | 102))) => {}
        Err(error) => return Err(error),
    }
    portable_entries(directory, cancel)
}

#[cfg(target_os = "macos")]
mod macos {
    use super::*;
    use std::{ffi::c_void, fs::File, io, os::fd::AsRawFd};

    const NAME: u32 = 0x0000_0001;
    const TYPE: u32 = 0x0000_0008;
    const ERROR: u32 = 0x2000_0000;
    const RETURNED: u32 = 0x8000_0000;
    const DATA_LENGTH: u32 = 0x0000_0200;
    #[repr(C)]
    struct Attributes {
        count: u16,
        reserved: u16,
        common: u32,
        volume: u32,
        directory: u32,
        file: u32,
        fork: u32,
    }
    unsafe extern "C" {
        fn getattrlistbulk(
            fd: i32,
            attributes: *mut Attributes,
            buffer: *mut c_void,
            length: usize,
            options: u64,
        ) -> i32;
    }

    // Returned records are packed, including 64-bit values that may only be
    // 4-byte aligned. Read integers from slices rather than casting pointers.
    fn number<const N: usize>(data: &[u8], offset: usize) -> Result<[u8; N]> {
        data.get(offset..offset.checked_add(N).context("Invalid attribute offset")?)
            .context("Truncated directory attributes")?
            .try_into()
            .map_err(Into::into)
    }
    fn u32_at(data: &[u8], offset: usize) -> Result<u32> {
        Ok(u32::from_ne_bytes(number(data, offset)?))
    }

    fn parse(record: &[u8], directory: &Path) -> Result<Entry> {
        let common = u32_at(record, 4)?;
        let file = u32_at(record, 16)?;
        let mut offset = 24; // length + attribute_set_t (five u32 values)
        if common & ERROR != 0 {
            let error = u32_at(record, offset)?;
            offset += 4;
            if error != 0 {
                return Err(io::Error::from_raw_os_error(error as i32).into());
            }
        }
        ensure!(common & NAME != 0, "Missing directory entry name");
        let name_offset = i32::from_ne_bytes(number(record, offset)?) as i64 + offset as i64;
        let name_len = u32_at(record, offset + 4)? as usize;
        ensure!(
            name_offset >= 0 && name_len > 1,
            "Invalid directory entry name"
        );
        let name_offset = usize::try_from(name_offset)?;
        let name = record
            .get(
                name_offset
                    ..name_offset
                        .checked_add(name_len)
                        .context("Invalid filename size")?,
            )
            .context("Truncated directory entry name")?;
        ensure!(name.last() == Some(&0), "Unterminated directory entry name");
        let name = std::str::from_utf8(&name[..name.len() - 1]).context("Non-Unicode filename")?;
        ensure!(
            !name.contains(['/', '\0']) && name != "." && name != "..",
            "Invalid directory entry name"
        );
        let path = directory.join(name);
        offset += 8;
        let kind = if common & TYPE != 0 {
            let kind = u32_at(record, offset)?;
            offset += 4;
            Some(kind)
        } else {
            None
        };
        let size = if file & DATA_LENGTH != 0 {
            let value = i64::from_ne_bytes(number(record, offset)?);
            ensure!(value >= 0, "Invalid directory entry size");
            Some(value as u64)
        } else {
            None
        };
        // Missing optional attributes may occur on unusual filesystems.
        let metadata =
            if kind.is_none() || (kind == Some(1) && size.is_none() && is_dng_source(&path)) {
                Some(fs::symlink_metadata(&path)?)
            } else {
                None
            };
        let regular = kind.map_or_else(|| metadata.as_ref().unwrap().is_file(), |k| k == 1); // VREG
        let is_dir = kind.map_or_else(|| metadata.as_ref().unwrap().is_dir(), |k| k == 2); // VDIR
        ensure!(
            regular || is_dir,
            "不支援連結或特殊檔案：{}",
            path.display()
        );
        let bytes = if regular && is_dng_source(&path) {
            size.or_else(|| metadata.as_ref().map(|m| m.len()))
        } else {
            None
        };
        Ok(Entry {
            path,
            directory: is_dir,
            bytes,
        })
    }

    pub(super) fn entries(directory: &Path, cancel: &AtomicBool) -> Result<Vec<Entry>> {
        let file = File::open(directory)?;
        let mut attrs = Attributes {
            count: 5,
            reserved: 0,
            common: NAME | TYPE | ERROR | RETURNED,
            volume: 0,
            directory: 0,
            file: DATA_LENGTH,
            fork: 0,
        };
        // u64 allocation guarantees the alignment required by getattrlistbulk.
        let mut buffer = vec![0u64; (64 << 10) / 8];
        let mut entries = Vec::new();
        loop {
            cancelled(cancel)?;
            let count = unsafe {
                getattrlistbulk(
                    file.as_raw_fd(),
                    &mut attrs,
                    buffer.as_mut_ptr().cast(),
                    buffer.len() * 8,
                    0,
                )
            };
            if count < 0 {
                return Err(io::Error::last_os_error().into());
            }
            if count == 0 {
                return Ok(entries);
            }
            // All buffer bytes are initialized by the allocation; record bounds
            // are checked before reading fields or following name references.
            let bytes = unsafe {
                std::slice::from_raw_parts(buffer.as_ptr().cast::<u8>(), buffer.len() * 8)
            };
            let mut offset = 0usize;
            for _ in 0..count {
                cancelled(cancel)?;
                let length = u32_at(bytes, offset)? as usize;
                ensure!(length >= 24, "Invalid directory attribute record");
                let end = offset
                    .checked_add(length)
                    .context("Invalid directory attribute length")?;
                let record = bytes
                    .get(offset..end)
                    .context("Truncated directory attribute record")?;
                entries.push(parse(record, directory)?);
                offset = end;
            }
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        #[test]
        fn malformed_attribute_records_are_rejected_without_panicking() {
            for length in 0..48 {
                assert!(parse(&vec![0u8; length], Path::new("/test")).is_err());
            }
            let mut record = vec![0u8; 64];
            record[4..8].copy_from_slice(&NAME.to_ne_bytes());
            record[24..28].copy_from_slice(&i32::MAX.to_ne_bytes());
            record[28..32].copy_from_slice(&8u32.to_ne_bytes());
            assert!(parse(&record, Path::new("/test")).is_err());
            record[24..28].copy_from_slice(&(-25i32).to_ne_bytes());
            assert!(parse(&record, Path::new("/test")).is_err());
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::Ordering;

    fn fixture() -> PathBuf {
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!("cdng-clip-scan-{nonce}"));
        fs::create_dir(&path).unwrap();
        path
    }

    #[test]
    fn streaming_clips_match_packing_inventory_and_portable_scan() {
        let root = fixture();
        for directory in ["鏡頭 A/子片段", "Z", "sidecars"] {
            fs::create_dir_all(root.join(directory)).unwrap();
        }
        for (path, content) in [
            ("root.DNG", "root"),
            ("鏡頭 A/z.DNG", "frame-z"),
            ("鏡頭 A/a.dng", "a"),
            ("鏡頭 A/._a.dng", "appledouble"),
            ("鏡頭 A/音訊.wav", "audio"),
            ("鏡頭 A/子片段/1.DNG", "nested"),
            ("Z/1.dng", "z"),
            ("sidecars/file.txt", "text"),
        ] {
            fs::write(root.join(path), content).unwrap();
        }
        let mut actual = Vec::new();
        scan(&root, &AtomicBool::new(false), |clip| actual.push(clip)).unwrap();
        let canonical = root.canonicalize().unwrap();
        let expected: Vec<_> = super::super::groups(&super::super::inventory(&canonical).unwrap())
            .into_values()
            .collect();
        assert_eq!(
            actual
                .iter()
                .map(|c| (&c.relative, &c.frames, c.bytes))
                .collect::<Vec<_>>(),
            expected
                .iter()
                .map(|c| (&c.relative, &c.frames, c.bytes))
                .collect::<Vec<_>>()
        );
        let native = directory_entries(&canonical.join("鏡頭 A"), &AtomicBool::new(false)).unwrap();
        let portable =
            portable_entries(&canonical.join("鏡頭 A"), &AtomicBool::new(false)).unwrap();
        let summarize = |entries: Vec<Entry>| {
            let mut entries = entries
                .into_iter()
                .map(|e| (e.path, e.directory, e.bytes))
                .collect::<Vec<_>>();
            entries.sort();
            entries
        };
        assert_eq!(summarize(native), summarize(portable));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn cancelled_scan_stops_before_later_clips_and_before_opening_source() {
        let root = fixture();
        for directory in ["A", "B", "C"] {
            fs::create_dir(root.join(directory)).unwrap();
            fs::write(root.join(directory).join("1.dng"), b"raw").unwrap();
        }
        let cancel = AtomicBool::new(false);
        let mut received = Vec::new();
        assert!(
            scan(&root, &cancel, |clip| {
                received.push(clip.relative);
                cancel.store(true, Ordering::Relaxed);
            })
            .is_err()
        );
        assert_eq!(received, ["A"]);
        assert!(
            scan(&root.join("does-not-exist"), &cancel, |_| panic!(
                "cancelled scan emitted a clip"
            ))
            .unwrap_err()
            .to_string()
            .contains("取消")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn scan_rejects_symlinks_without_following_them() {
        let root = fixture();
        fs::write(root.join("frame.dng"), b"raw").unwrap();
        std::os::unix::fs::symlink(root.join("frame.dng"), root.join("linked.dng")).unwrap();
        assert!(scan(&root, &AtomicBool::new(false), |_| {}).is_err());
        fs::remove_dir_all(root).unwrap();
    }

    /// Read-only comparison against the former list_clips implementation.
    /// Run in release mode with CDNG_SCAN_BENCH_SOURCE pointing at real footage.
    #[test]
    #[ignore = "read-only scan benchmark; set CDNG_SCAN_BENCH_SOURCE"]
    fn scan_benchmark_inventory_vs_bulk() {
        let root = PathBuf::from(
            std::env::var_os("CDNG_SCAN_BENCH_SOURCE").expect("set CDNG_SCAN_BENCH_SOURCE"),
        )
        .canonicalize()
        .unwrap();
        let baseline = || {
            super::super::groups(&super::super::inventory(&root).unwrap())
                .into_values()
                .collect::<Vec<_>>()
        };
        let expected = baseline();
        for round in 0..5 {
            for candidate in [round % 2 == 0, round % 2 != 0] {
                let started = std::time::Instant::now();
                let mut first = None;
                let mut actual = if candidate {
                    let mut actual = Vec::new();
                    scan(&root, &AtomicBool::new(false), |clip| {
                        if first.is_none() {
                            first = Some(started.elapsed().as_secs_f64());
                        }
                        actual.push(clip);
                    })
                    .unwrap();
                    actual
                } else {
                    baseline()
                };
                let elapsed = started.elapsed().as_secs_f64();
                actual.sort_by(|a, b| a.relative.cmp(&b.relative));
                assert_eq!(
                    actual
                        .iter()
                        .map(|c| (&c.relative, &c.frames, c.bytes))
                        .collect::<Vec<_>>(),
                    expected
                        .iter()
                        .map(|c| (&c.relative, &c.frames, c.bytes))
                        .collect::<Vec<_>>()
                );
                println!(
                    "candidate={candidate} seconds={elapsed:.6} first_clip_seconds={first:?} clips={} frames={} exact=true",
                    actual.len(),
                    actual.iter().map(|c| c.frames.len()).sum::<usize>()
                );
            }
        }
    }
}
