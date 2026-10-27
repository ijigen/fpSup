//! Reserve metadata, stream payloads once, then patch ISO9660/Joliet directories.
use crate::cancelled;
use anyhow::{Context, Result, ensure};
use crate::digest::Sha256;
use std::{
    collections::{BTreeMap, HashSet},
    fs::File,
    io::{IoSlice, Read, Seek, SeekFrom, Write},
    sync::atomic::AtomicBool,
};
const B: u64 = 2048;
fn blocks(n: u64) -> u64 {
    n.div_ceil(B)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        fs,
        io::Cursor,
        time::{SystemTime, UNIX_EPOCH},
    };

    #[test]
    fn streamed_crc_matches_complete_image_and_scanned_dmg() {
        let root = std::env::temp_dir().join(format!(
            "cdng-crc-{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&root).unwrap();
        let image = root.join("streamed.dmg");
        let mut iso = Iso::new(
            File::create(&image).unwrap(),
            &[
                ("empty.bin".into(), false, 0),
                ("中文".into(), true, 0),
                ("中文/edge.bin".into(), false, 0),
                ("aligned.bin".into(), false, 0),
                ("chunk.bin".into(), false, 0),
            ],
            "TEST",
        )
        .unwrap();
        iso.enable_checksum().unwrap();
        let cancel = AtomicBool::new(false);
        for (name, size) in [
            ("empty.bin", 0),
            ("中文/edge.bin", 2047),
            ("aligned.bin", 2048),
            ("chunk.bin", (1 << 20) + 3),
        ] {
            let data: Vec<u8> = (0..size).map(|i| (i * 13) as u8).collect();
            if size >= 2048 {
                iso.add_prehashed(name, &data, &cancel, crate::hash(&data))
                    .unwrap();
            } else {
                iso.add(name, &mut Cursor::new(data), &cancel).unwrap();
            }
        }
        let (size, crc) = iso.finish_with_checksum(false).unwrap();
        let crc = crc.unwrap();
        assert_eq!(crc, crc32fast::hash(&fs::read(&image).unwrap()));
        let scanned = root.join("scanned.dmg");
        fs::copy(&image, &scanned).unwrap();
        crate::dmg::finish_with_checksum(&image, &cancel, Some((size, crc))).unwrap();
        crate::dmg::finish(&scanned, &cancel).unwrap();
        assert_eq!(fs::read(&image).unwrap(), fs::read(&scanned).unwrap());
        fs::remove_dir_all(root).unwrap();
    }
}
fn both16(v: u16) -> Vec<u8> {
    [v.to_le_bytes(), v.to_be_bytes()].concat()
}
fn both32(v: u32) -> Vec<u8> {
    [v.to_le_bytes(), v.to_be_bytes()].concat()
}
fn unicode(s: &str) -> Vec<u8> {
    s.encode_utf16().flat_map(u16::to_be_bytes).collect()
}
#[derive(Clone)]
struct Node {
    path: String,
    dir: bool,
    parent: usize,
    children: Vec<usize>,
    extent: u32,
    size: u32,
    mtime: u64,
    locations: [u32; 2],
    lengths: [u32; 2],
}
impl Node {
    fn name(&self, j: usize, index: usize) -> Vec<u8> {
        if self.path.is_empty() {
            vec![0]
        } else if j == 1 {
            unicode(self.path.rsplit('/').next().unwrap())
        } else {
            format!(
                "{}{:07}{}",
                if self.dir { "D" } else { "F" },
                index,
                if self.dir { "" } else { ".DAT;1" }
            )
            .into_bytes()
        }
    }
}
fn date(seconds: u64) -> [u8; 7] {
    let days = (seconds / 86400) as i64;
    let z = days + 719468;
    let era = z / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = mp + if mp < 10 { 3 } else { -9 };
    let year = y + i64::from(month <= 2);
    [
        ((year - 1900).clamp(0, 255)) as u8,
        month as u8,
        day as u8,
        ((seconds / 3600) % 24) as u8,
        ((seconds / 60) % 60) as u8,
        (seconds % 60) as u8,
        0,
    ]
}
fn record(n: &Node, name: &[u8], j: usize) -> Vec<u8> {
    let len = 33 + name.len() + usize::from(name.len() % 2 == 0);
    let mut b = vec![len as u8, 0];
    b.extend(both32(if n.dir { n.locations[j] } else { n.extent }));
    b.extend(both32(if n.dir { n.lengths[j] } else { n.size }));
    b.extend(date(n.mtime));
    b.extend([if n.dir { 2 } else { 0 }, 0, 0]);
    b.extend(both16(1));
    b.push(name.len() as u8);
    b.extend(name);
    if name.len() % 2 == 0 {
        b.push(0);
    }
    b
}
pub struct Iso {
    file: File,
    nodes: Vec<Node>,
    map: BTreeMap<String, usize>,
    dirs: Vec<usize>,
    tables: [(u32, u32, u32); 2],
    volume: String,
    written: HashSet<String>,
    data_start: u64,
    payload_crc: Option<crc32fast::Hasher>,
}
#[derive(serde::Serialize, Clone)]
pub struct Stored {
    pub size: u64,
    pub sha256: String,
    pub extent: u32,
}
impl Iso {
    pub fn new(mut file: File, paths: &[(String, bool, u64)], volume: &str) -> Result<Self> {
        let mut nodes = vec![Node {
            path: String::new(),
            dir: true,
            parent: 0,
            children: vec![],
            extent: 0,
            size: 0,
            mtime: 0,
            locations: [0; 2],
            lengths: [0; 2],
        }];
        let mut map = BTreeMap::from([(String::new(), 0)]);
        for (path, isdir, mtime) in paths {
            let parts: Vec<_> = path.split('/').collect();
            ensure!(!parts.is_empty(), "Empty archive path");
            let mut parent = 0;
            for (i, part) in parts.iter().enumerate() {
                let stem = part.split('.').next().unwrap().to_uppercase();
                ensure!(
                    !part.is_empty()
                        && ![".", ".."].contains(part)
                        && part.encode_utf16().count() <= 64
                        && !part
                            .chars()
                            .any(|c| c > '\u{ffff}' || c < ' ' || "\\/:*?\"<>|".contains(c))
                        && !part.ends_with(['.', ' '])
                        && ![
                            "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5",
                            "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5",
                            "LPT6", "LPT7", "LPT8", "LPT9"
                        ]
                        .contains(&stem.as_str()),
                    "檔名不適合跨平台 ISO：{part}"
                );
                let key = parts[..=i].join("/");
                let dir = i + 1 < parts.len() || *isdir;
                if let Some(&idx) = map.get(&key) {
                    ensure!(nodes[idx].dir == dir, "File/directory conflict");
                    parent = idx;
                } else {
                    ensure!(nodes[parent].dir, "File/directory conflict");
                    ensure!(
                        !nodes[parent].children.iter().any(|&child| nodes[child]
                            .path
                            .rsplit('/')
                            .next()
                            .unwrap()
                            .to_lowercase()
                            == part.to_lowercase()),
                        "大小寫檔名衝突：{key}"
                    );
                    let idx = nodes.len();
                    nodes.push(Node {
                        path: key.clone(),
                        dir,
                        parent,
                        children: vec![],
                        extent: 0,
                        size: 0,
                        mtime: *mtime,
                        locations: [0; 2],
                        lengths: [0; 2],
                    });
                    nodes[parent].children.push(idx);
                    map.insert(key, idx);
                    parent = idx;
                }
            }
        }
        let mut dirs: Vec<usize> = (0..nodes.len()).filter(|&i| nodes[i].dir).collect();
        dirs.sort_by_key(|&i| {
            (
                if nodes[i].path.is_empty() {
                    0
                } else {
                    nodes[i].path.matches('/').count() + 1
                },
                nodes[i].path.clone(),
            )
        });
        ensure!(
            dirs.len() <= 65535 && nodes.len() <= 9_999_999,
            "Too many files/directories"
        );
        let mut cursor = 19u64;
        let mut tables = [(0, 0, 0); 2];
        for (j, table) in tables.iter_mut().enumerate() {
            let size: usize = dirs
                .iter()
                .map(|&i| {
                    let n = nodes[i].name(j, i).len();
                    8 + n + n % 2
                })
                .sum();
            *table = (
                cursor as u32,
                (cursor + blocks(size as u64)) as u32,
                size as u32,
            );
            cursor += 2 * blocks(size as u64);
            for &idx in &dirs {
                let mut used = 68u64;
                let mut children = nodes[idx].children.clone();
                children.sort_by_key(|&c| nodes[c].name(j, c));
                for c in children {
                    let len = nodes[c].name(j, c).len();
                    let length = 33 + len + usize::from(len % 2 == 0);
                    if used % B + length as u64 > B {
                        used += B - used % B;
                    }
                    used += length as u64;
                }
                nodes[idx].locations[j] = cursor as u32;
                nodes[idx].lengths[j] = (blocks(used) * B) as u32;
                cursor += blocks(used);
            }
        }
        file.seek(SeekFrom::Start(cursor * B))?;
        Ok(Self {
            file,
            nodes,
            map,
            dirs,
            tables,
            volume: volume.into(),
            written: HashSet::new(),
            data_start: cursor * B,
            payload_crc: None,
        })
    }
    pub(crate) fn enable_checksum(&mut self) -> Result<()> {
        ensure!(
            self.written.is_empty(),
            "Checksum must start before image payloads"
        );
        self.payload_crc = Some(crc32fast::Hasher::new());
        Ok(())
    }
    pub fn add(
        &mut self,
        path: &str,
        reader: &mut impl Read,
        cancel: &AtomicBool,
    ) -> Result<Stored> {
        self.add_impl(path, reader, cancel, None)
    }
    pub(crate) fn add_prehashed(
        &mut self,
        path: &str,
        data: &[u8],
        cancel: &AtomicBool,
        sha256: String,
    ) -> Result<Stored> {
        let &idx = self.map.get(path).context("Unknown image path")?;
        ensure!(
            !self.nodes[idx].dir && !self.written.contains(path),
            "Duplicate image payload"
        );
        let at = self.file.stream_position()?;
        let extent = u32::try_from(at / B)?;
        let size = data.len() as u64;
        ensure!(size <= u32::MAX as u64, "單一檔案超過 ISO 的 4 GiB 限制");
        ensure!(
            at.checked_add(size.div_ceil(B) * B)
                .is_some_and(|end| end < (u32::MAX as u64) * B),
            "Image exceeds 8 TiB"
        );
        let zeros = [0; B as usize];
        let padding = &zeros[..((B - size % B) % B) as usize];
        // The compressed DNG is already in memory and already hashed. Borrow it
        // directly and gather its alignment padding in the same write operation.
        // Avoid copying every frame through a new 1 MiB buffer and issuing a
        // separate tiny write for padding on external filesystems.
        let mut buffers = [IoSlice::new(data), IoSlice::new(padding)];
        let mut buffers = &mut buffers[..];
        while !buffers.is_empty() {
            cancelled(cancel)?;
            match self.file.write_vectored(buffers) {
                Ok(0) if buffers.iter().all(|b| b.is_empty()) => break,
                Ok(0) => return Err(std::io::Error::from(std::io::ErrorKind::WriteZero).into()),
                Ok(n) => IoSlice::advance_slices(&mut buffers, n),
                Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(e) => return Err(e.into()),
            }
        }
        if let Some(crc) = &mut self.payload_crc {
            crc.update(data);
            crc.update(padding);
        }
        self.nodes[idx].extent = extent;
        self.nodes[idx].size = size as u32;
        self.written.insert(path.into());
        Ok(Stored {
            size,
            sha256,
            extent,
        })
    }
    /// Reserve a payload range in a sparse metadata image; dynamic reads supply its bytes.
    pub(crate) fn reserve(&mut self, path: &str, size: u64) -> Result<Stored> {
        let &idx = self.map.get(path).context("Unknown image path")?;
        ensure!(
            !self.nodes[idx].dir && !self.written.contains(path),
            "Duplicate image payload"
        );
        ensure!(size <= u32::MAX as u64, "單一虛擬 DNG 超過 ISO 4 GiB 限制");
        let at = self.file.stream_position()?;
        let extent = u32::try_from(at / B)?;
        let end = at
            .checked_add(size.div_ceil(B) * B)
            .context("Virtual image overflow")?;
        ensure!(end < (u32::MAX as u64) * B, "Virtual image exceeds 8 TiB");
        self.file.seek(SeekFrom::Start(end))?;
        // Reserved bytes are supplied by the virtual disk rather than this writer.
        self.payload_crc = None;
        self.nodes[idx].extent = extent;
        self.nodes[idx].size = size as u32;
        self.written.insert(path.into());
        Ok(Stored {
            size,
            sha256: String::new(),
            extent,
        })
    }
    fn add_impl(
        &mut self,
        path: &str,
        reader: &mut impl Read,
        cancel: &AtomicBool,
        known_hash: Option<String>,
    ) -> Result<Stored> {
        let &idx = self.map.get(path).context("Unknown image path")?;
        ensure!(
            !self.nodes[idx].dir && !self.written.contains(path),
            "Duplicate image payload"
        );
        let extent = u32::try_from(self.file.stream_position()? / B)?;
        let mut hash = Sha256::new();
        let mut size = 0u64;
        let mut buf = vec![0; 1024 * 1024];
        loop {
            cancelled(cancel)?;
            let n = reader.read(&mut buf)?;
            if n == 0 {
                break;
            }
            size += n as u64;
            ensure!(size <= u32::MAX as u64, "單一檔案超過 ISO 的 4 GiB 限制");
            ensure!(
                self.file.stream_position()? + (n as u64) < (u32::MAX as u64) * B,
                "Image exceeds 8 TiB"
            );
            self.file.write_all(&buf[..n])?;
            if let Some(crc) = &mut self.payload_crc {
                crc.update(&buf[..n]);
            }
            if known_hash.is_none() {
                hash.update(&buf[..n]);
            }
        }
        let padding = [0; B as usize];
        let padding = &padding[..((B - size % B) % B) as usize];
        self.file.write_all(padding)?;
        if let Some(crc) = &mut self.payload_crc {
            crc.update(padding);
        }
        self.nodes[idx].extent = extent;
        self.nodes[idx].size = size as u32;
        self.written.insert(path.into());
        Ok(Stored {
            size,
            sha256: known_hash.unwrap_or_else(|| format!("{:x}", hash.finalize())),
            extent,
        })
    }
    fn descriptor(&self, j: usize, total: u32) -> Vec<u8> {
        let mut b = vec![0; B as usize];
        b[..7].copy_from_slice(&[vec![if j == 0 { 1 } else { 2 }], b"CD001\x01".to_vec()].concat());
        fn text(b: &mut [u8], at: usize, len: usize, s: &str, j: usize) {
            let mut raw = if j == 1 {
                unicode(s)
            } else {
                s.as_bytes().to_vec()
            };
            let pad = if j == 1 { vec![0, 32] } else { vec![32] };
            while raw.len() < len {
                raw.extend(&pad);
            }
            b[at..at + len].copy_from_slice(&raw[..len]);
        }
        text(&mut b, 8, 32, "CDNG IMAGE", j);
        text(&mut b, 40, 32, &self.volume, j);
        b[80..88].copy_from_slice(&both32(total));
        if j == 1 {
            b[88..91].copy_from_slice(b"%/E");
        }
        b[120..124].copy_from_slice(&both16(1));
        b[124..128].copy_from_slice(&both16(1));
        b[128..132].copy_from_slice(&both16(B as u16));
        let (le, be, size) = self.tables[j];
        b[132..140].copy_from_slice(&both32(size));
        b[140..144].copy_from_slice(&le.to_le_bytes());
        b[148..152].copy_from_slice(&be.to_be_bytes());
        b[156..190].copy_from_slice(&record(&self.nodes[0], &[0], j));
        for at in [190, 318, 446] {
            text(&mut b, at, 128, "CDNG IMAGE RUST 0.1.0", j);
        }
        for at in [813, 830, 847, 864] {
            b[at..at + 16].fill(b'0');
        }
        b[881] = 1;
        b
    }
    pub fn finish(self) -> Result<u64> {
        Ok(self.finish_with_checksum(true)?.0)
    }
    /// DMG callers defer syncing until the envelope is appended, then sync the
    /// entire finished image once. The optional CRC covers the complete data fork.
    pub(crate) fn finish_with_checksum(mut self, sync: bool) -> Result<(u64, Option<u32>)> {
        ensure!(
            self.nodes
                .iter()
                .filter(|n| !n.dir)
                .all(|n| self.written.contains(&n.path)),
            "Missing image payloads"
        );
        let end = self.file.stream_position()?;
        // Directory records and path tables are small but cause many filesystem
        // round trips on external volumes. Patch one bounded prefix in memory and
        // write it once. Very large directories retain the streaming fallback.
        let mut prefix = (self.data_start <= 64 << 20).then(|| vec![0; self.data_start as usize]);
        fn metadata(
            file: &mut File,
            prefix: &mut Option<Vec<u8>>,
            limit: u64,
            at: u64,
            bytes: &[u8],
        ) -> Result<()> {
            // Readback may already have verified completed payloads. Metadata
            // must stay inside the reservation even in the streaming fallback.
            ensure!(at.checked_add(bytes.len() as u64).is_some_and(|end| end <= limit),
                "Image metadata exceeds reserved prefix");
            if let Some(prefix) = prefix {
                let at = usize::try_from(at)?;
                let end = at
                    .checked_add(bytes.len())
                    .context("Image metadata overflow")?;
                prefix
                    .get_mut(at..end)
                    .context("Image metadata exceeds reserved prefix")?
                    .copy_from_slice(bytes);
            } else {
                file.seek(SeekFrom::Start(at))?;
                file.write_all(bytes)?;
            }
            Ok(())
        }
        let dir_indices: BTreeMap<usize, usize> = self
            .dirs
            .iter()
            .enumerate()
            .map(|(i, &n)| (n, i + 1))
            .collect();
        for j in 0..2 {
            for &idx in &self.dirs {
                let node = &self.nodes[idx];
                let parent = &self.nodes[node.parent];
                let mut data = record(node, &[0], j);
                data.extend(record(parent, &[1], j));
                let mut children = node.children.clone();
                children.sort_by_key(|&c| self.nodes[c].name(j, c));
                for c in children {
                    let rec = record(&self.nodes[c], &self.nodes[c].name(j, c), j);
                    if data.len() % B as usize + rec.len() > B as usize {
                        data.resize(data.len().div_ceil(B as usize) * B as usize, 0);
                    }
                    data.extend(rec);
                }
                data.resize(node.lengths[j] as usize, 0);
                metadata(
                    &mut self.file,
                    &mut prefix,
                    self.data_start,
                    node.locations[j] as u64 * B,
                    &data,
                )?;
            }
            let (le, be, _) = self.tables[j];
            for (big, location) in [(false, le), (true, be)] {
                let mut table = Vec::new();
                for &idx in &self.dirs {
                    let n = &self.nodes[idx];
                    let name = n.name(j, idx);
                    table.extend([name.len() as u8, 0]);
                    table.extend(if big {
                        n.locations[j].to_be_bytes()
                    } else {
                        n.locations[j].to_le_bytes()
                    });
                    let parent = dir_indices[&n.parent] as u16;
                    table.extend(if big {
                        parent.to_be_bytes()
                    } else {
                        parent.to_le_bytes()
                    });
                    table.extend(&name);
                    if name.len() % 2 != 0 {
                        table.push(0);
                    }
                }
                metadata(&mut self.file, &mut prefix, self.data_start, location as u64 * B, &table)?;
            }
        }
        for j in 0..2 {
            let descriptor = self.descriptor(j, (end / B) as u32);
            metadata(
                &mut self.file,
                &mut prefix,
                self.data_start,
                (16 + j as u64) * B,
                &descriptor,
            )?;
        }
        let mut term = vec![0; B as usize];
        term[..7].copy_from_slice(b"\xffCD001\x01");
        metadata(&mut self.file, &mut prefix, self.data_start, 18 * B, &term)?;
        let checksum = if let Some(prefix) = prefix {
            self.file.seek(SeekFrom::Start(0))?;
            self.file.write_all(&prefix)?;
            self.payload_crc.map(|payload| {
                let mut crc = crc32fast::Hasher::new();
                crc.update(&prefix);
                crc.combine(&payload);
                crc.finalize()
            })
        } else {
            None
        };
        self.file.set_len(end)?;
        if sync {
            self.file.sync_all()?;
        }
        Ok((end, checksum))
    }
}
