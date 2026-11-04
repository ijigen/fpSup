//! Read this app's ISO/Joliet images without attaching or extracting them.
//! UDIF support deliberately covers only our uncompressed, single-run envelope.
use crate::{archive::{Entry, Frame, Index}, dng, hash};
use anyhow::{Context, Result, ensure};
use serde::Deserialize;
use std::collections::{BTreeMap, HashMap, HashSet};

const BLOCK: usize = 2048;
const MANIFEST: &str = "_CDNG_IMAGE_MANIFEST.json";

#[derive(Clone, Copy)]
pub(crate) struct Span { pub offset: usize, pub length: usize }
impl Span {
    pub(crate) fn bytes(self, data: &[u8]) -> &[u8] { &data[self.offset..self.offset + self.length] }
}

pub(crate) struct ImageBacking {
    pub sources: Vec<Span>,
    pub headers: HashMap<u64, (Span, ImageHeader)>,
}

pub(crate) enum ImageHeader { Jxl(dng::MountedJxl), Raw(dng::MountedRaw) }
impl ImageHeader {
    pub(crate) fn header(&self, source: &[u8]) -> Result<Vec<u8>> {
        match self { Self::Jxl(v)=>v.header(source), Self::Raw(v)=>v.header(source) }
    }
    pub(crate) fn is_raw(&self) -> bool { matches!(self, Self::Raw(_)) }
}

fn be32(d: &[u8], at: usize) -> Result<u32> {
    Ok(u32::from_be_bytes(d.get(at..at + 4).context("Truncated image metadata")?.try_into()?))
}
fn be64(d: &[u8], at: usize) -> Result<u64> {
    Ok(u64::from_be_bytes(d.get(at..at + 8).context("Truncated image metadata")?.try_into()?))
}
fn both32(d: &[u8], at: usize) -> Result<usize> {
    let little = u32::from_le_bytes(d.get(at..at + 4).context("Truncated ISO metadata")?.try_into()?);
    ensure!(little == be32(d, at + 4)?, "Inconsistent ISO metadata");
    Ok(little as usize)
}
fn span(offset: usize, length: usize, end: usize) -> Result<Span> {
    ensure!(offset >= 19 * BLOCK && offset.checked_add(length).is_some_and(|n| n <= end),
        "Image file extent is outside the data fork");
    Ok(Span { offset, length })
}
fn base64(text: &str) -> Result<Vec<u8>> {
    let chars: Vec<_> = text.bytes().filter(|b| !b.is_ascii_whitespace()).collect();
    ensure!(chars.len() % 4 == 0 && chars.len() <= 4096, "Invalid UDIF block map");
    let mut out = Vec::new();
    for (i, c) in chars.chunks_exact(4).enumerate() {
        let mut word = 0u32;
        let mut pad = 0;
        for &b in c {
            let value = match b {
                b'A'..=b'Z' => b - b'A', b'a'..=b'z' => b - b'a' + 26,
                b'0'..=b'9' => b - b'0' + 52, b'+' => 62, b'/' => 63,
                b'=' => { pad += 1; 0 }, _ => anyhow::bail!("Invalid UDIF block map"),
            };
            ensure!(b == b'=' || pad == 0, "Invalid UDIF base64 padding");
            word = (word << 6) | u32::from(value);
        }
        ensure!(pad <= 2 && (pad == 0 || i + 1 == chars.len() / 4), "Invalid UDIF base64 padding");
        out.push((word >> 16) as u8);
        if pad < 2 { out.push((word >> 8) as u8); }
        if pad < 1 { out.push(word as u8); }
    }
    Ok(out)
}

fn data_fork(data: &[u8]) -> Result<usize> {
    let trailer = data.len().checked_sub(512).map(|at| &data[at..]);
    let Some(t) = trailer.filter(|t| t.starts_with(b"koly")) else { return Ok(data.len()); };
    ensure!(be32(t, 4)? == 4 && be32(t, 8)? == 512 && be64(t, 24)? == 0
        && be64(t, 40)? == 0 && be64(t, 48)? == 0 && be32(t, 56)? == 1 && be32(t, 60)? == 1,
        "僅支援本程式產生的單一未壓縮 DMG；此映像檔格式不受支援");
    let len = usize::try_from(be64(t, 32)?)?;
    let xml_len = usize::try_from(be64(t, 224)?)?;
    ensure!(len > 0 && len % 512 == 0 && be64(t, 216)? == len as u64
        && xml_len <= 1 << 20 && len.checked_add(xml_len) == Some(data.len() - 512)
        && be64(t, 492)? == (len / 512) as u64, "Invalid UDIF data fork");
    let xml = std::str::from_utf8(&data[len..len + xml_len])?;
    ensure!(xml.matches("<data>").count() == 1, "Unsupported UDIF block maps");
    let encoded = xml.split_once("<data>").and_then(|(_, s)| s.split_once("</data>"))
        .context("Missing UDIF block map")?.0;
    let m = base64(encoded)?;
    ensure!(m.len() == 284 && &m[..4] == b"mish" && be32(&m, 4)? == 1
        && be64(&m, 8)? == 0 && be64(&m, 16)? == (len / 512) as u64 && be64(&m, 24)? == 0
        && be32(&m, 200)? == 2 && be32(&m, 204)? == 1 && be64(&m, 212)? == 0
        && be64(&m, 220)? == (len / 512) as u64 && be64(&m, 228)? == 0 && be64(&m, 236)? == len as u64
        && be32(&m, 244)? == u32::MAX && be64(&m, 252)? == (len / 512) as u64
        && be64(&m, 260)? == 0 && be64(&m, 268)? == len as u64 && be64(&m, 276)? == 0,
        "不支援壓縮或多區段 DMG；請選擇 CDNG Image 產生的映像檔");
    Ok(len)
}

fn safe_component(name: &str) -> bool {
    !name.is_empty() && !matches!(name, "." | "..")
        && !name.chars().any(|c| c.is_control() || matches!(c, '/' | '\\' | ':'))
}

fn catalog(data: &[u8], end: usize) -> Result<(Vec<String>, BTreeMap<String, Span>)> {
    ensure!(end >= 19 * BLOCK && end % BLOCK == 0, "不是本程式支援的 ISO／未壓縮 DMG");
    let pvd = &data[16 * BLOCK..17 * BLOCK];
    let svd = &data[17 * BLOCK..18 * BLOCK];
    ensure!(&pvd[..7] == b"\x01CD001\x01" && &svd[..7] == b"\x02CD001\x01"
        && &svd[88..91] == b"%/E" && &data[18 * BLOCK..18 * BLOCK + 7] == b"\xffCD001\x01",
        "僅支援 CDNG Image 的 ISO9660/Joliet 映像檔");
    ensure!(both32(pvd, 80)?.checked_mul(BLOCK) == Some(end)
        && both32(svd, 80)?.checked_mul(BLOCK) == Some(end)
        && svd[128..132] == [0, 8, 8, 0] && svd[156] == 34,
        "Invalid ISO volume descriptor");
    let root = &svd[156..190];
    let root_span = span(both32(root, 2)? * BLOCK, both32(root, 10)?, end)?;
    let mut pending = vec![(String::new(), root_span, 0usize)];
    let mut seen_dirs = HashSet::new();
    let mut directory_spans = BTreeMap::<usize, usize>::new();
    let mut path_bytes = 0usize;
    let mut names = HashSet::new();
    let mut directories = Vec::new();
    let mut files = BTreeMap::new();
    let mut metadata_end = 19 * BLOCK;
    while let Some((parent, directory, depth)) = pending.pop() {
        ensure!(depth <= 128 && directory.length > 0 && directory.length <= 64 << 20
            && directory.length % BLOCK == 0 && seen_dirs.insert(directory.offset),
            "Invalid/cyclic ISO directory");
        let dir_end = directory.offset + directory.length;
        ensure!(directory_spans.range(..dir_end).next_back().is_none_or(|(_, &end)| end <= directory.offset),
            "Overlapping ISO directories");
        directory_spans.insert(directory.offset, dir_end);
        metadata_end = metadata_end.max(directory.offset + directory.length);
        let bytes = directory.bytes(data);
        let mut at = 0;
        while at < bytes.len() {
            let n = bytes[at] as usize;
            if n == 0 { at = (at / BLOCK + 1) * BLOCK; continue; }
            ensure!(n >= 34 && at + n <= bytes.len() && at % BLOCK + n <= BLOCK,
                "Invalid ISO directory record");
            let record = &bytes[at..at + n];
            at += n;
            let nname = record[32] as usize;
            ensure!(33 + nname <= record.len() && record[1] == 0 && record[26] == 0 && record[27] == 0
                && record[25] & !2 == 0, "Unsupported ISO file layout");
            let name_bytes = &record[33..33 + nname];
            if nname == 1 && matches!(name_bytes[0], 0 | 1) { continue; }
            ensure!(nname > 0 && nname % 2 == 0, "Invalid Joliet filename");
            let units: Vec<_> = name_bytes.chunks_exact(2).map(|b| u16::from_be_bytes([b[0], b[1]])).collect();
            let component = String::from_utf16(&units)?;
            ensure!(safe_component(&component), "Unsafe ISO filename");
            let name = if parent.is_empty() { component } else { format!("{parent}/{component}") };
            path_bytes = path_bytes.checked_add(name.len()).context("ISO catalog size overflow")?;
            ensure!(path_bytes <= 64 << 20, "ISO catalog paths exceed 64 MiB");
            ensure!(names.insert(name.clone()) && names.len() <= 1_000_000, "Duplicate/oversized ISO catalog");
            let range = span(both32(record, 2)? * BLOCK, both32(record, 10)?, end)?;
            if record[25] == 2 {
                directories.push(name.clone());
                pending.push((name, range, depth + 1));
            } else {
                files.insert(name, range);
            }
        }
    }
    let mut spans: Vec<_> = files.values().filter(|s| s.length > 0).copied().collect();
    spans.sort_by_key(|s| s.offset);
    ensure!(spans.iter().all(|s| s.offset >= metadata_end)
        && spans.windows(2).all(|s| s[0].offset + s[0].length <= s[1].offset),
        "Overlapping image files or metadata");
    directories.sort();
    Ok((directories, files))
}

#[derive(Deserialize)]
struct Manifest {
    format: String,
    version: u32,
    codec: String,
    files: Vec<ManifestFile>,
}
#[derive(Deserialize)]
struct ManifestFile {
    path: String,
    size: usize,
    extent: usize,
    sha256: String,
    codec: Option<String>,
    width: Option<usize>,
    height: Option<usize>,
    bits: Option<usize>,
    pixel_sha256: Option<String>,
}
fn checksum(s: &str) -> bool { s.len() == 64 && s.bytes().all(|c| c.is_ascii_hexdigit()) }

pub(crate) fn open(data: &[u8], budget: usize, correct_og3k: bool) -> Result<(Index, ImageBacking)> {
    let end = data_fork(data)?;
    let (directories, mut files) = catalog(data, end)?;
    let manifest_span = files.remove(MANIFEST).context("映像檔沒有 CDNG Image 保存清單，無法動態解壓")?;
    ensure!(manifest_span.length <= 64 << 20, "Image manifest exceeds 64 MiB");
    let manifest: Manifest = serde_json::from_slice(manifest_span.bytes(data))?;
    ensure!(manifest.format == "CDNG Image" && manifest.version == 1
        && matches!(manifest.codec.as_str(), "jpeg-xl-dng" | "lossless-jpeg")
        && manifest.files.len() == files.len(), "Unsupported/incomplete CDNG Image manifest");
    let mut entries = Vec::new();
    let mut sources = Vec::new();
    let mut headers = HashMap::new();
    for record in manifest.files {
        let source = files.remove(&record.path).context("Manifest file is missing/duplicated")?;
        ensure!(record.size == source.length && record.extent.checked_mul(BLOCK) == Some(source.offset)
            && checksum(&record.sha256), "Manifest file extent/checksum differs from ISO catalog");
        let mut entry = Entry { path: record.path, offset: source.offset as u64, length: source.length,
            sha256: record.sha256.to_ascii_lowercase(), virtual_size: source.length as u64, frame: None };
        if record.codec.as_deref() == Some("jpeg-xl-dng") {
            let layout = dng::mounted_jxl(source.bytes(data)).with_context(|| format!("JPEG XL DNG: {}", entry.path))?;
            ensure!(record.width == Some(layout.width) && record.height == Some(layout.height)
                && record.bits == Some(layout.bits), "JXL DNG dimensions differ from manifest");
            let raw_hash = record.pixel_sha256.context("Missing RAW checksum")?;
            ensure!(checksum(&raw_hash), "Invalid RAW checksum");
            let need = layout.width * layout.height * 2;
            ensure!(need <= budget, "快取容量不足以容納單張 RAW，至少需要 {} MiB", need.div_ceil(1 << 20));
            entry.offset += layout.payload_offset as u64;
            entry.length = layout.payload_len;
            entry.virtual_size = (layout.header_len + need) as u64;
            entry.frame = Some(Frame { width: layout.width, height: layout.height,
                original_bits: layout.bits, raw_sha256: raw_hash.to_ascii_lowercase(),
                header_offset: source.offset as u64, header_len: layout.header_len,
                // The original complete DNG is verified lazily before any bytes
                // are served. The generated header is not physically in the image.
                header_sha256: String::new(), temporal: None });
            headers.insert(source.offset as u64, (source, ImageHeader::Jxl(layout)));
        } else if crate::pack::is_dng_source(std::path::Path::new(&entry.path)) {
            ensure!(manifest.codec != "jpeg-xl-dng"
                && matches!(dng::stored_compression(source.bytes(data))?, 1 | 7),
                "DNG is missing supported codec metadata: {}", entry.path);
            if correct_og3k && dng::is_og3k(source.bytes(data)) {
                let layout=dng::MountedRaw::plan(source.bytes(data))
                    .with_context(|| format!("OG3K DNG: {}",entry.path))?;
                let need=layout.width*layout.height*2;
                ensure!(need<=budget,"快取容量不足以容納單張 RAW");
                let raw_hash=record.pixel_sha256.unwrap_or_default();
                ensure!(raw_hash.is_empty() || checksum(&raw_hash), "Invalid RAW checksum");
                entry.virtual_size=(layout.header_len+need) as u64;
                entry.frame=Some(Frame { width:layout.width,height:layout.height,original_bits:layout.bits,
                    raw_sha256:raw_hash.to_ascii_lowercase(),header_offset:source.offset as u64,
                    header_len:layout.header_len,header_sha256:String::new(),temporal:None });
                headers.insert(source.offset as u64,(source,ImageHeader::Raw(layout)));
            }
        }
        sources.push(source);
        entries.push(entry);
    }
    sources.push(manifest_span);
    entries.push(Entry { path: MANIFEST.into(), offset: manifest_span.offset as u64,
        length: manifest_span.length, sha256: hash(manifest_span.bytes(data)),
        virtual_size: manifest_span.length as u64, frame: None });
    Ok((Index { format: "CDNG Image virtual archive".into(), version: 2,
        profile: manifest.codec, libjxl: 0, directories, entries }, ImageBacking { sources, headers }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{archive::Archive, iso::Iso, Backend};
    use std::{fs, io::Cursor, path::PathBuf, sync::atomic::AtomicBool, time::{SystemTime, UNIX_EPOCH}};

    struct Temp(PathBuf);
    impl Temp {
        fn new() -> Self {
            let p = std::env::temp_dir().join(format!("cdng-image-reader-{}-{}", std::process::id(),
                SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
            fs::create_dir(&p).unwrap();
            Self(p)
        }
    }
    impl Drop for Temp { fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); } }

    fn raw_dng() -> Vec<u8> {
        let artist = b"Test metadata\0";
        let mut tags = vec![
            (256u16, 4u16, 1u32, 8u32), (257, 4, 1, 6), (258, 3, 1, 16),
            (259, 3, 1, 1), (262, 3, 1, 32803), (273, 4, 1, 0),
            (277, 3, 1, 1), (278, 4, 1, 6), (279, 4, 1, 96),
            (315, 2, artist.len() as u32, 0), (33421, 3, 2, 0x00020002),
            (33422, 1, 4, 0x02010100), (50706, 1, 4, 0x00000401), (50707, 1, 4, 0x00000101),
        ];
        let metadata = 8 + 6 + tags.len() * 12;
        let raw = metadata + artist.len();
        tags.iter_mut().find(|t| t.0 == 273).unwrap().3 = raw as u32;
        tags.iter_mut().find(|t| t.0 == 315).unwrap().3 = metadata as u32;
        let mut out = b"II*\0\x08\0\0\0".to_vec();
        out.extend_from_slice(&(tags.len() as u16).to_le_bytes());
        for (tag, typ, count, value) in tags {
            out.extend_from_slice(&tag.to_le_bytes()); out.extend_from_slice(&typ.to_le_bytes());
            out.extend_from_slice(&count.to_le_bytes()); out.extend_from_slice(&value.to_le_bytes());
        }
        out.extend_from_slice(&[0; 4]); out.extend_from_slice(artist);
        for i in 0u16..48 { out.extend_from_slice(&(i * 79).to_le_bytes()); }
        out
    }

    fn image(temp: &Temp, payload: &[u8], dmg: bool, mutate_manifest: bool) -> PathBuf {
        let source = raw_dng();
        let frame = dng::jxl_frame(&source).unwrap();
        let (compressed, info) = dng::jxl_dng(&frame, payload, None, "fixture", Backend::Cpu);
        let path = temp.0.join(if dmg { "Saved 拍攝.dmg" } else { "Saved 拍攝.iso" });
        let mut iso = Iso::new(fs::File::create(&path).unwrap(), &[
            ("Take".into(), true, 0), ("Take/frame.DNG".into(), false, 0),
            ("Take/sound.wav".into(), false, 0), ("Empty".into(), true, 0), (MANIFEST.into(), false, 0),
        ], "Saved 拍攝").unwrap();
        let cancel = AtomicBool::new(false);
        let stored = iso.add("Take/frame.DNG", &mut Cursor::new(compressed), &cancel).unwrap();
        let mut raw = serde_json::to_value(&info).unwrap();
        let object = raw.as_object_mut().unwrap();
        object.insert("path".into(), "Take/frame.DNG".into());
        object.insert("size".into(), stored.size.into());
        object.insert("extent".into(), (stored.extent + u32::from(mutate_manifest)).into());
        object.insert("sha256".into(), stored.sha256.into());
        let sound = iso.add("Take/sound.wav", &mut Cursor::new(b"sound"), &cancel).unwrap();
        let manifest = serde_json::json!({"format":"CDNG Image","version":1,"codec":"jpeg-xl-dng", "files":[raw,
            {"path":"Take/sound.wav", "size":sound.size,"extent":sound.extent,"sha256":sound.sha256}]});
        iso.add(MANIFEST, &mut Cursor::new(serde_json::to_vec(&manifest).unwrap()), &cancel).unwrap();
        iso.finish().unwrap();
        if dmg { crate::dmg::finish(&path, &cancel).unwrap(); }
        path
    }

    #[test]
    fn image_metadata_opens_lazily_and_preserves_sidecars_and_directories() {
        for dmg in [false, true] {
            let temp = Temp::new();
            // An intentionally invalid JXL stream proves opening/listing does
            // not decode any frame. Codec validation happens only on RAW reads.
            let path = image(&temp, b"not a JXL stream", dmg, false);
            let archive = Archive::open(&path, 1 << 20).unwrap();
            assert_eq!(archive.stats()["decoded_frames"], 0);
            assert_eq!(archive.index.directories, ["Empty", "Take"]);
            assert_eq!(archive.index.entries.len(), 3);
            let frame = archive.index.entries.iter().position(|e| e.frame.is_some()).unwrap();
            archive.verify_entry(frame).unwrap();
            let mut header = vec![0; archive.index.entries[frame].frame.as_ref().unwrap().header_len];
            assert_eq!(archive.read_into(frame, 0, &mut header).unwrap(), header.len());
            assert!(header.windows(b"Test metadata\0".len()).any(|b| b == b"Test metadata\0"));
            assert_eq!(archive.stats()["decoded_frames"], 0);
            let sidecar = archive.index.entries.iter().position(|e| e.path.ends_with("sound.wav")).unwrap();
            let mut out = [0; 20];
            assert_eq!(archive.read_into(sidecar, 0, &mut out).unwrap(), 5);
            assert_eq!(&out[..5], b"sound");
        }
    }

    #[test]
    fn image_rejects_corrupt_bounds_paths_manifest_and_payloads() {
        let temp = Temp::new();
        let path = image(&temp, b"a test payload", false, true);
        assert!(Archive::open(&path, 1 << 20).is_err());
        let path = image(&temp, b"a test payload", false, false);
        let bytes = fs::read(&path).unwrap();
        assert!(open(&bytes[..bytes.len() - 1], 1 << 20, false).is_err());
        let (_, files) = catalog(&bytes, bytes.len()).unwrap();
        let mut corrupt = bytes.clone();
        let dng = files["Take/frame.DNG"];
        corrupt[dng.offset + dng.length - 1] ^= 1;
        fs::write(&path, &corrupt).unwrap();
        let archive = Archive::open(&path, 1 << 20).unwrap();
        assert_eq!(archive.stats()["decoded_frames"], 0);
        let i = archive.index.entries.iter().position(|e| e.frame.is_some()).unwrap();
        assert!(archive.verify_entry(i).is_err());
        assert!(archive.read_into(i, 0, &mut [0; 8]).is_err());
        drop(archive);
        let svd = &bytes[17 * BLOCK..18 * BLOCK];
        let root = both32(&svd[156..190], 2).unwrap() * BLOCK;
        let mut overlap = bytes.clone();
        overlap[root + 68 + 10..root + 68 + 14].copy_from_slice(&(2 * BLOCK as u32).to_le_bytes());
        overlap[root + 68 + 14..root + 68 + 18].copy_from_slice(&(2 * BLOCK as u32).to_be_bytes());
        let error = catalog(&overlap, overlap.len()).err().expect("overlapping directories must fail");
        assert!(error.to_string().contains("Overlapping ISO directories"));
        let mut unsafe_name = bytes;
        unsafe_name[root + 68 + 33..root + 68 + 35].copy_from_slice(&u16::from(b'/').to_be_bytes());
        assert!(open(&unsafe_name, 1 << 20, false).is_err());
    }

    #[test]
    fn image_rejects_unsupported_udif_layout() {
        let temp = Temp::new();
        let path = image(&temp, b"a test payload", true, false);
        let mut bytes = fs::read(path).unwrap();
        let n = bytes.len();
        bytes[n - 512 + 24..n - 512 + 32].copy_from_slice(&512u64.to_be_bytes());
        assert!(open(&bytes, 1 << 20, false).is_err());
    }

    #[test]
    fn ordinary_dng_image_reads_original_file_without_loading_jxl() {
        let temp = Temp::new();
        let path = temp.0.join("Original.dmg");
        let source = raw_dng();
        let cancel = AtomicBool::new(false);
        let mut iso = Iso::new(fs::File::create(&path).unwrap(),
            &[("frame.DNG".into(), false, 0), (MANIFEST.into(), false, 0)], "Original").unwrap();
        let stored = iso.add("frame.DNG", &mut Cursor::new(&source), &cancel).unwrap();
        let manifest = serde_json::json!({"format":"CDNG Image","version":1,"codec":"lossless-jpeg",
            "files":[{"path":"frame.DNG","extent":stored.extent,"size":stored.size,"sha256":stored.sha256}]});
        iso.add(MANIFEST, &mut Cursor::new(serde_json::to_vec(&manifest).unwrap()), &cancel).unwrap();
        iso.finish().unwrap();
        crate::dmg::finish(&path, &cancel).unwrap();
        let archive = Archive::open(&path, 0).unwrap();
        assert!(archive.index.entries[0].frame.is_none());
        let mut out = vec![0; source.len()];
        assert_eq!(archive.read_into(0, 0, &mut out).unwrap(), source.len());
        assert_eq!(out, source);
        assert_eq!(archive.stats()["decoded_frames"], 0);
    }

    #[test]
    #[ignore = "requires the native libjxl decoder/encoder"]
    fn native_jxl_dmg_restores_raw_samples_and_uses_decode_cache() {
        let temp = Temp::new();
        let source = raw_dng();
        let frame = dng::jxl_frame(&source).unwrap();
        let codec = crate::jxl::Codec::load().unwrap();
        let payload = codec.encode(&frame.planes, frame.width, frame.height, 3, 0).unwrap();
        let path = image(&temp, &payload, true, false);
        let archive = Archive::open(&path, 1 << 20).unwrap();
        let i = archive.index.entries.iter().position(|e| e.frame.is_some()).unwrap();
        let mut restored = vec![0; archive.index.entries[i].virtual_size as usize];
        archive.read_into(i, 0, &mut restored).unwrap();
        assert_eq!(dng::decode(&restored).unwrap(), dng::decode(&source).unwrap());
        assert_eq!(archive.stats()["decoded_frames"], 1);
        archive.read_into(i, restored.len() as u64 - 17, &mut [0; 17]).unwrap();
        assert_eq!(archive.stats()["decoded_frames"], 1);
        assert_eq!(archive.stats()["hits"], 1);
    }
}
