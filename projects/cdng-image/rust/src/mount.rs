//! Mounts a .cdngj or .cdngt archive as a read-only disk in Finder.
//!
//! The archive's files are laid out as a synthesised HFS+ volume (`hfs`) that a local
//! HTTP server hands to `diskutil image attach`; the kernel reads only the byte ranges
//! it needs and each range is decoded from the archive on demand. The process lives
//! until the volume is ejected (in Finder or with `diskutil eject`) or is cancelled,
//! in which case it ejects the volume itself.
use crate::{archive::Archive, hfs};
use anyhow::{Context, Result, bail, ensure};
use serde_json::json;
use std::{
    cell::RefCell,
    collections::HashMap,
    io::{BufRead, BufReader, Write},
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::Command,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, SystemTime, UNIX_EPOCH},
};

/// Decoded-frame cache shared by all reads.
const CACHE_BYTES: usize = 1 << 30;

// The GUI may close while its independent mount process keeps serving. A closed
// progress pipe must not panic after attaching the volume or interrupt its reads.
fn progress(value: serde_json::Value) {
    let _ = writeln!(std::io::stdout(), "{value}");
}

fn diagnostic(value: serde_json::Value) {
    let _ = writeln!(std::io::stderr(), "{value}");
}

/// Folders and files of the archive as an HFS+ layout, in archive entry order.
fn layout(archive: &Archive) -> (Vec<hfs::Dir>, Vec<hfs::File>) {
    let mut dirs: Vec<hfs::Dir> = Vec::new();
    let mut ids: HashMap<String, usize> = HashMap::new();
    let mut folder = |path: &str, dirs: &mut Vec<hfs::Dir>| -> Option<usize> {
        let mut parent = None;
        let mut at = String::new();
        for part in path.split('/').filter(|p| !p.is_empty()) {
            if !at.is_empty() {
                at.push('/');
            }
            at.push_str(part);
            parent = Some(*ids.entry(at.clone()).or_insert_with(|| {
                dirs.push(hfs::Dir { name: part.to_string(), parent });
                dirs.len() - 1
            }));
        }
        parent
    };
    for d in &archive.index.directories {
        folder(d, &mut dirs);
    }
    let mut files = Vec::new();
    for e in &archive.index.entries {
        let (dir, name) = e.path.rsplit_once('/').unwrap_or(("", &e.path));
        files.push(hfs::File { dir: folder(dir, &mut dirs), name: name.to_string(), size: e.virtual_size });
    }
    (dirs, files)
}

fn volume_name(archive: &Path) -> String {
    let stem = archive.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
    let name: String = stem
        .chars()
        .map(|c| if (c.is_ascii_graphic() || c == ' ') && c != ':' && c != '/' { c } else { '_' })
        .take(27)
        .collect();
    if name.trim().is_empty() { "CDNG".into() } else { name }
}

struct Served {
    archive: Archive,
    volume: hfs::Volume,
}

impl Served {
    /// Volume bytes at `offset`. Any archive error fails the whole request, so the
    /// kernel sees an I/O error rather than wrong pixels.
    fn read(&self, offset: u64, out: &mut [u8]) -> Result<()> {
        let error = RefCell::new(None);
        let first = self.volume.files.first().map_or(0, |f| f.cnid);
        self.volume.read(offset, out, &|f, at, buf| {
            // files are numbered consecutively in archive entry order
            let entry = (f.cnid - first) as usize;
            let mut done = 0;
            while done < buf.len() && error.borrow().is_none() {
                match self.archive.read_into(entry, at + done as u64, &mut buf[done..]) {
                    Ok(0) => *error.borrow_mut() = Some(anyhow::anyhow!("archive entry {entry} is shorter than listed")),
                    Ok(n) => done += n,
                    Err(e) => *error.borrow_mut() = Some(e),
                }
            }
        });
        match error.into_inner() {
            Some(e) => Err(e),
            None => Ok(()),
        }
    }
}

fn serve(stream: TcpStream, served: &Served) -> Result<()> {
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut writer = stream;
    let size = served.volume.bytes;
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line)? == 0 {
            return Ok(());
        }
        let method = line.split_whitespace().next().unwrap_or("").to_string();
        let mut range = None;
        loop {
            let mut h = String::new();
            reader.read_line(&mut h)?;
            let h = h.trim_end();
            if h.is_empty() {
                break;
            }
            if let Some((name, v)) = h.split_once(':')
                && name.eq_ignore_ascii_case("range")
            {
                let (a, b) = v.trim().strip_prefix("bytes=").and_then(|r| r.split_once('-')).context("bad range")?;
                let a: u64 = a.parse()?;
                let b: u64 = if b.is_empty() { size - 1 } else { b.parse::<u64>()?.min(size - 1) };
                ensure!(a <= b, "empty range");
                range = Some((a, b));
            }
        }
        match (method.as_str(), range) {
            ("HEAD", _) => write!(
                writer,
                "HTTP/1.1 200 OK\r\nContent-Length: {size}\r\nAccept-Ranges: bytes\r\nContent-Type: application/octet-stream\r\n\r\n"
            )?,
            ("GET", Some((a, b))) => {
                let mut buf = vec![0u8; usize::try_from(b - a + 1)?];
                if let Err(e) = served.read(a, &mut buf) {
                    diagnostic(json!({"read_error": format!("{e:#}"), "offset": a}));
                    write!(writer, "HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\n\r\n")?;
                } else {
                    write!(
                        writer,
                        "HTTP/1.1 206 Partial Content\r\nContent-Length: {}\r\nContent-Range: bytes {a}-{b}/{size}\r\nAccept-Ranges: bytes\r\nContent-Type: application/octet-stream\r\n\r\n",
                        buf.len()
                    )?;
                    writer.write_all(&buf)?;
                }
            }
            _ => bail!("unsupported request {line:?}"),
        }
        writer.flush()?;
    }
}

/// Where a running mount of the same archive records its mount point.
fn record_path(archive: &Path) -> Result<PathBuf> {
    let home = std::env::var_os("HOME").context("HOME is not set")?;
    let key = crate::hash(archive.as_os_str().as_encoded_bytes());
    Ok(PathBuf::from(home).join("Library/Caches/cdng-image/mounts").join(&key[..16]))
}

fn alive(pid: u32) -> bool {
    unsafe extern "C" {
        fn kill(pid: i32, sig: i32) -> i32;
    }
    unsafe { kill(pid as i32, 0) == 0 }
}

fn mounted(path: &Path) -> bool {
    use std::os::unix::fs::MetadataExt;
    match (std::fs::metadata(path), path.parent().map(std::fs::metadata)) {
        (Ok(m), Some(Ok(p))) => m.dev() != p.dev(),
        _ => false,
    }
}

fn eject(device: &str) -> bool {
    Command::new("diskutil").args(["eject", device]).output().is_ok_and(|o| o.status.success())
}

/// Mounts `archive` and serves it until the volume is ejected or `cancel` is set.
/// `open_window` opens the volume in Finder, as double-clicking a DMG does.
pub fn mount(archive_path: &Path, open_window: bool, cancel: &AtomicBool) -> Result<()> {
    let archive_path = archive_path.canonicalize().context("找不到封存檔")?;
    let record = record_path(&archive_path)?;
    if let Ok(text) = std::fs::read_to_string(&record)
        && let Some((pid, mount_point)) = text.split_once('\t')
        && pid.parse().is_ok_and(alive)
        && mounted(Path::new(mount_point))
    {
        progress(json!({"already_mounted": mount_point}));
        if open_window {
            let _ = Command::new("open").arg(mount_point).status();
        }
        return Ok(());
    }

    let started = std::time::Instant::now();
    let archive = Archive::open(&archive_path, CACHE_BYTES)?;
    let (dirs, files) = layout(&archive);
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() + 2_082_844_800; // HFS epoch 1904
    let volume = hfs::Volume::build(&volume_name(&archive_path), &dirs, &files, now as u32)?;
    let served = Arc::new(Served { archive, volume });

    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let url = format!("http://127.0.0.1:{}/volume.img", listener.local_addr()?.port());
    {
        let served = served.clone();
        std::thread::spawn(move || {
            for stream in listener.incoming().flatten() {
                let served = served.clone();
                std::thread::spawn(move || {
                    if let Err(e) = serve(stream, &served) {
                        diagnostic(json!({"connection_error": format!("{e:#}")}));
                    }
                });
            }
        });
    }

    let out = Command::new("diskutil").args(["image", "attach", "--readOnly", &url]).output()?;
    ensure!(out.status.success(), "掛載失敗: {}", String::from_utf8_lossy(&out.stderr).trim());
    // last line: "/dev/diskN<TAB>...<TAB>/Volumes/NAME"
    let text = String::from_utf8_lossy(&out.stdout);
    let line = text.lines().rev().find(|l| l.starts_with("/dev/")).context("diskutil did not report a device")?;
    let device = line.split_whitespace().next().unwrap().to_string();
    let mount_point = line.split('\t').map(str::trim).rfind(|f| f.starts_with('/') && !f.starts_with("/dev/"));
    let Some(mount_point) = mount_point.map(PathBuf::from) else {
        eject(&device);
        bail!("磁碟已連接但沒有掛載");
    };
    let save_record = (|| -> std::io::Result<()> {
        if let Some(dir) = record.parent() {
            std::fs::create_dir_all(dir)?;
        }
        std::fs::write(&record, format!("{}\t{}", std::process::id(), mount_point.display()))
    })();
    if let Err(error) = save_record {
        eject(&device);
        return Err(error).context("Could not save the archive mount record");
    }
    progress(
        json!({"mounted": mount_point, "device": device, "files": files.len(), "virtual_bytes": served.volume.bytes,
               "seconds": started.elapsed().as_secs_f64()})
    );
    if open_window {
        let _ = Command::new("open").arg(&mount_point).status();
    }

    let mut warned = false;
    loop {
        std::thread::sleep(Duration::from_millis(500));
        if !mounted(&mount_point) {
            eject(&device); // unmounted but maybe still attached
            break;
        }
        if cancel.load(Ordering::Relaxed) {
            if eject(&device) {
                break;
            }
            // still in use (e.g. by Resolve): keep serving rather than fail its reads
            if !warned {
                progress(json!({"busy": mount_point}));
                warned = true;
            }
        }
    }
    let _ = std::fs::remove_file(&record);
    progress(json!({"ejected": mount_point}));
    Ok(())
}
