//! Read-only sector synthesis. No OS device registration is performed here.
//! Tiny sparse ISO metadata + archive extents; payload holes are served on demand.
use crate::{archive::Archive, iso::Iso};
use anyhow::{Context, Result, ensure};
use std::{
    fs::{File, OpenOptions},
    io::{Read, Seek, SeekFrom, Write},
    path::PathBuf,
    sync::{Arc, Mutex, atomic::AtomicBool},
    time::{SystemTime, UNIX_EPOCH},
};
struct Extent {
    at: u64,
    end: u64,
    entry: usize,
}
pub struct VirtualDisk {
    archive: Arc<Archive>,
    metadata: Mutex<Option<File>>,
    temporary: PathBuf,
    extents: Vec<Extent>,
    pub bytes: u64,
}
impl Drop for VirtualDisk {
    fn drop(&mut self) {
        if let Ok(file) = self.metadata.get_mut() {
            drop(file.take());
        }
        let _ = std::fs::remove_file(&self.temporary);
    }
}
impl VirtualDisk {
    pub fn stats(&self) -> serde_json::Value {
        let physical = {
            #[cfg(unix)]
            {
                use std::os::unix::fs::MetadataExt;
                std::fs::metadata(&self.temporary)
                    .map(|m| m.blocks() * 512)
                    .unwrap_or(0)
            }
            #[cfg(not(unix))]
            {
                0u64
            }
        };
        serde_json::json!({"virtual_bytes":self.bytes,"metadata_physical_bytes":physical,"filesystem":"iso9660-joliet-read-only","sector_bytes":512,"registered_os_device":false,"archive":self.archive.stats()})
    }
    pub fn new(archive: Arc<Archive>) -> Result<Self> {
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
        let temporary =
            std::env::temp_dir().join(format!("cdng-virtual-{}-{nonce}.iso", std::process::id()));
        let file = OpenOptions::new()
            .write(true)
            .read(true)
            .create_new(true)
            .open(&temporary)?;
        let mut cleanup = crate::pack::Partial(temporary.clone());
        let paths: Vec<_> = archive
            .index
            .directories
            .iter()
            .map(|p| (p.clone(), true, 0))
            .chain(
                archive
                    .index
                    .entries
                    .iter()
                    .map(|e| (e.path.clone(), false, 0)),
            )
            .collect();
        let mut iso = Iso::new(file, &paths, "CDNG_JXL")?;
        let mut extents = Vec::new();
        for (i, e) in archive.index.entries.iter().enumerate() {
            let stored = iso.reserve(&e.path, e.virtual_size)?;
            let at = u64::from(stored.extent) * 2048;
            if e.virtual_size > 0 {
                extents.push(Extent {
                    at,
                    end: at + e.virtual_size,
                    entry: i,
                });
            }
        }
        let bytes = iso.finish()?;
        let metadata = Mutex::new(Some(File::open(&temporary)?));
        cleanup.0.clear();
        Ok(Self {
            archive,
            metadata,
            temporary,
            extents,
            bytes,
        })
    }
    pub fn read_into(&self, offset: u64, out: &mut [u8]) -> Result<usize> {
        if offset >= self.bytes {
            return Ok(0);
        }
        let n = (self.bytes - offset).min(out.len() as u64) as usize;
        let mut copied = 0;
        while copied < n {
            let at = offset + copied as u64;
            let index = self.extents.partition_point(|e| e.end <= at);
            if let Some(e) = self.extents.get(index).filter(|e| e.at <= at) {
                let k = (e.end - at).min((n - copied) as u64) as usize;
                ensure!(
                    self.archive
                        .read_into(e.entry, at - e.at, &mut out[copied..copied + k])?
                        == k,
                    "Short virtual file read"
                );
                copied += k;
            } else {
                let end = self.extents.get(index).map_or(self.bytes, |e| e.at);
                let k = (end - at).min((n - copied) as u64) as usize;
                let mut guard = self
                    .metadata
                    .lock()
                    .map_err(|_| anyhow::anyhow!("Metadata read failed"))?;
                let f = guard.as_mut().context("Metadata closed")?;
                f.seek(SeekFrom::Start(at))?;
                f.read_exact(&mut out[copied..copied + k])?;
                copied += k;
            }
        }
        Ok(n)
    }
    pub fn read_sectors(&self, lba: u64, out: &mut [u8]) -> Result<()> {
        ensure!(
            out.len() % 512 == 0,
            "Sector reads must be multiples of 512 bytes"
        );
        let at = lba.checked_mul(512).context("Sector address overflow")?;
        ensure!(
            at.checked_add(out.len() as u64)
                .is_some_and(|e| e <= self.bytes),
            "Sector read out of bounds"
        );
        ensure!(self.read_into(at, out)? == out.len(), "Short sector read");
        Ok(())
    }
    /// Explicit materialization utility for conformance/compatibility, never called "mount".
    pub fn materialize(&self, path: &std::path::Path, cancel: &AtomicBool) -> Result<()> {
        ensure!(!path.exists(), "Output already exists");
        let parent = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(std::path::Path::new("."))
            .canonicalize()?;
        let target = parent.join(path.file_name().context("Missing output filename")?);
        let (partial, mut file) = crate::output::OutputFile::create(&target)?;
        let mut buffer = vec![0; 1 << 20];
        let mut at = 0;
        loop {
            crate::cancelled(cancel)?;
            let n = self.read_into(at, &mut buffer)?;
            if n == 0 {
                break;
            }
            file.write_all(&buffer[..n])?;
            at += n as u64;
        }
        file.sync_all()?;
        drop(file);
        if target
            .extension()
            .is_some_and(|e| e.eq_ignore_ascii_case("dmg"))
        {
            crate::dmg::finish(partial.path(), cancel)?;
        }
        crate::cancelled(cancel)?;
        partial.finish()?;
        Ok(())
    }
}
