//! Output files without an extra full-image copy.
//!
//! Use an atomic, exclusive rename where the volume supports it. macOS exFAT
//! volumes can reject RENAME_EXCL with ENOTSUP, so probe before doing any work.
//! On those volumes, create the final name exclusively and stream into that
//! file. It is visible while incomplete and removed on failure/cancellation.
use anyhow::{Context, Result, ensure};
use std::{
    fs::{self, File, OpenOptions},
    io,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

pub(crate) fn publish(from: &Path, to: &Path) -> io::Result<()> {
    #[cfg(target_os = "macos")]
    {
        use std::{ffi::CString, os::unix::ffi::OsStrExt};
        unsafe extern "C" {
            fn renamex_np(
                from: *const std::ffi::c_char,
                to: *const std::ffi::c_char,
                flags: u32,
            ) -> i32;
        }
        let a = CString::new(from.as_os_str().as_bytes())?;
        let b = CString::new(to.as_os_str().as_bytes())?;
        if unsafe { renamex_np(a.as_ptr(), b.as_ptr(), 4) } != 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn MoveFileExW(a: *const u16, b: *const u16, flags: u32) -> i32;
        }
        let a: Vec<u16> = from.as_os_str().encode_wide().chain(Some(0)).collect();
        let b: Vec<u16> = to.as_os_str().encode_wide().chain(Some(0)).collect();
        if unsafe { MoveFileExW(a.as_ptr(), b.as_ptr(), 0) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
    #[cfg(not(any(target_os = "macos", windows)))]
    {
        fs::hard_link(from, to)?;
        fs::remove_file(from)
    }
}

pub(crate) struct OutputFile {
    path: PathBuf,
    target: PathBuf,
    directory: Option<PathBuf>,
    identity: Option<File>,
    committed: bool,
}

fn rename_unsupported(error: &io::Error) -> bool {
    if error.kind() == io::ErrorKind::Unsupported {
        return true;
    }
    // Darwin distinguishes ENOTSUP (45) from EOPNOTSUPP (102). Rust does not
    // consistently classify both as ErrorKind::Unsupported.
    #[cfg(target_os = "macos")]
    return matches!(error.raw_os_error(), Some(45 | 102));
    #[cfg(not(target_os = "macos"))]
    false
}

impl OutputFile {
    pub(crate) fn create(target: &Path) -> Result<(Self, File)> {
        Self::create_with(target, publish)
    }

    fn create_with(
        target: &Path,
        rename: impl FnOnce(&Path, &Path) -> io::Result<()>,
    ) -> Result<(Self, File)> {
        let parent = target
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
        let directory = parent.join(format!(
            ".cdng-image-{}-{nonce}.partial",
            std::process::id()
        ));
        fs::create_dir(&directory).context("Could not create the output staging directory")?;
        let mut output = Self {
            path: directory.join("data"),
            target: target.to_owned(),
            directory: Some(directory.clone()),
            identity: None,
            committed: false,
        };
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(&output.path)?;
        output.identity = Some(file.try_clone()?);
        // Probe within our private directory. No final output is exposed by the
        // probe, and even an empty source file exercises the volume's rename API.
        let probe = directory.join("ready");
        match rename(&output.path, &probe) {
            Ok(()) => {
                output.path = probe;
                Ok((output, file))
            }
            Err(e) if rename_unsupported(&e) => {
                drop(file);
                fs::remove_file(&output.path)?;
                fs::remove_dir(&directory)?;
                output.directory = None;
                output.identity = None;
                // create_new also rejects existing symlinks and concurrent jobs.
                // Do not replace this with an existence check followed by rename:
                // a different file could appear between those two operations.
                let file = OpenOptions::new()
                    .read(true)
                    .write(true)
                    .create_new(true)
                    .open(target)
                    .with_context(|| {
                        format!(
                            "Could not create output {} (existing files are never replaced)",
                            target.display()
                        )
                    })?;
                output.path = target.to_owned();
                output.identity = Some(file.try_clone()?);
                Ok((output, file))
            }
            Err(e) => {
                Err(e).context("Could not check whether this volume supports exclusive renaming")
            }
        }
    }

    pub(crate) fn path(&self) -> &Path {
        &self.path
    }

    fn owns_path(&self) -> bool {
        let (Some(file), Ok(current)) = (&self.identity, fs::symlink_metadata(&self.path)) else {
            return false;
        };
        // exFAT may assign a different file ID when an empty file gets its first
        // allocation. Compare the path to the still-open file, not its old stat.
        let Ok(owned) = file.metadata() else {
            return false;
        };
        if !current.is_file() {
            return false;
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            owned.dev() == current.dev() && owned.ino() == current.ino()
        }
        #[cfg(not(unix))]
        {
            // Direct output is currently only needed for macOS filesystems.
            let _ = owned;
            true
        }
    }

    pub(crate) fn finish(mut self) -> Result<()> {
        ensure!(
            self.owns_path(),
            "Output was removed or replaced during compression"
        );
        if self.path != self.target {
            publish(&self.path, &self.target).context(
                "Could not publish the completed output; existing files are never replaced",
            )?;
        }
        self.committed = true;
        Ok(())
    }
}

impl Drop for OutputFile {
    fn drop(&mut self) {
        let remove = !self.committed && self.owns_path();
        drop(self.identity.take());
        if remove {
            let _ = fs::remove_file(&self.path);
        }
        if let Some(directory) = &self.directory {
            let _ = fs::remove_dir(directory);
        }
    }
}

fn publish_directory(from: &Path, to: &Path) -> io::Result<()> {
    #[cfg(any(target_os = "macos", windows))]
    { publish(from, to) }
    #[cfg(target_os = "linux")]
    {
        use std::{ffi::CString, os::unix::ffi::OsStrExt};
        unsafe extern "C" {
            fn renameat2(old_dir: i32, old: *const std::ffi::c_char,
                new_dir: i32, new: *const std::ffi::c_char, flags: u32) -> i32;
        }
        let from = CString::new(from.as_os_str().as_bytes())?;
        let to = CString::new(to.as_os_str().as_bytes())?;
        // AT_FDCWD, RENAME_NOREPLACE: unlike a directory hard link, this works
        // atomically on supporting Linux filesystems and never replaces a name.
        if unsafe { renameat2(-100, from.as_ptr(), -100, to.as_ptr(), 1) } == 0 { Ok(()) }
        else { Err(io::Error::last_os_error()) }
    }
    #[cfg(not(any(target_os = "macos", target_os = "linux", windows)))]
    { let _ = (from, to); Err(io::ErrorKind::Unsupported.into()) }
}

fn directory_rename_unsupported(error: &io::Error) -> bool {
    if rename_unsupported(error) { return true; }
    #[cfg(target_os = "linux")]
    return matches!(error.raw_os_error(), Some(22 | 38 | 95)); // EINVAL, ENOSYS, EOPNOTSUPP
    #[cfg(not(target_os = "linux"))]
    false
}

fn open_directory(path: &Path) -> io::Result<File> {
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        // A directory needs BACKUP_SEMANTICS; OPEN_REPARSE_POINT avoids following
        // a replacement junction. Share-delete permits our eventual rename.
        OpenOptions::new().read(true).share_mode(7).custom_flags(0x02000000 | 0x00200000).open(path)
    }
    #[cfg(not(windows))]
    { File::open(path) }
}

#[cfg(windows)]
fn directory_identity(file: &File) -> Option<(u32, u32, u32)> {
    use std::os::windows::io::AsRawHandle;
    #[repr(C)]
    struct Info {
        attributes: u32, creation: [u32; 2], access: [u32; 2], write: [u32; 2],
        volume: u32, size_high: u32, size_low: u32, links: u32, index_high: u32, index_low: u32,
    }
    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn GetFileInformationByHandle(file: *mut std::ffi::c_void, info: *mut Info) -> i32;
    }
    let mut info = std::mem::MaybeUninit::<Info>::uninit();
    if unsafe { GetFileInformationByHandle(file.as_raw_handle(), info.as_mut_ptr()) } == 0 { return None; }
    let info = unsafe { info.assume_init() };
    Some((info.volume, info.index_high, info.index_low))
}

/// A directory extracted once, with exclusive publication and owned-path rollback.
/// Unsupported volumes expose the newly created destination while it is incomplete.
pub(crate) struct OutputDirectory {
    path: PathBuf,
    target: PathBuf,
    identity: Option<File>,
    committed: bool,
    #[cfg(target_os = "macos")]
    generated_sidecars: std::collections::HashMap<PathBuf, GeneratedSidecar>,
}

#[cfg(target_os = "macos")]
#[derive(PartialEq)]
struct GeneratedSidecar {
    device: u64,
    inode: u64,
    birth: SystemTime,
    digest: String,
}

#[cfg(target_os = "macos")]
fn sidecar_path(peer: &Path) -> Option<PathBuf> {
    let name = peer.file_name()?;
    if name.as_encoded_bytes().starts_with(b"._") { return None; }
    let mut sidecar = std::ffi::OsString::from("._");
    sidecar.push(name);
    Some(peer.with_file_name(sidecar))
}

#[cfg(target_os = "macos")]
fn open_sidecar(path: &Path, write: bool) -> io::Result<File> {
    use std::os::unix::fs::OpenOptionsExt;
    // O_NOFOLLOW: never follow a substituted symlink, and do not truncate until
    // the opened handle matches the generated file's identity and bytes.
    OpenOptions::new().read(true).write(write).custom_flags(0x100).open(path)
}

#[cfg(target_os = "macos")]
fn generated_sidecar(file: &mut File) -> Result<GeneratedSidecar> {
    use std::{io::{Read, Seek, SeekFrom}, os::unix::fs::MetadataExt};
    let metadata = file.metadata()?;
    ensure!(metadata.is_file() && metadata.nlink() == 1 && metadata.len() <= 1 << 20,
        "Unexpected generated AppleDouble file");
    file.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::with_capacity(metadata.len() as usize);
    file.take((1 << 20) + 1).read_to_end(&mut bytes)?;
    ensure!(bytes.len() as u64 == metadata.len() && bytes.len() >= 26
        && bytes[..8] == [0, 5, 22, 7, 0, 2, 0, 0], "Invalid generated AppleDouble file");
    let count = u16::from_be_bytes(bytes[24..26].try_into().unwrap()) as usize;
    let table_end = 26 + count * 12;
    ensure!(count > 0 && table_end <= bytes.len(), "Invalid AppleDouble entry table");
    for entry in bytes[26..table_end].chunks_exact(12) {
        let offset = u32::from_be_bytes(entry[4..8].try_into().unwrap()) as usize;
        let length = u32::from_be_bytes(entry[8..12].try_into().unwrap()) as usize;
        ensure!(offset >= table_end && offset.checked_add(length).is_some_and(|end| end <= bytes.len()),
            "Invalid AppleDouble entry range");
    }
    Ok(GeneratedSidecar { device: metadata.dev(), inode: metadata.ino(),
        birth: metadata.created()?, digest: crate::hash(&bytes) })
}

impl OutputDirectory {
    pub(crate) fn create(target: &Path) -> Result<Self> {
        Self::create_with(target, publish_directory)
    }

    fn create_with(target: &Path, rename: impl FnOnce(&Path, &Path) -> io::Result<()>) -> Result<Self> {
        let parent = target.parent().filter(|p| !p.as_os_str().is_empty()).unwrap_or(Path::new("."));
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
        let path = parent.join(format!(".cdng-restore-{}-{nonce}.partial", std::process::id()));
        fs::create_dir(&path).context("Could not create extraction staging directory")?;
        let mut output = Self { identity: Some(open_directory(&path)?), path, target: target.to_owned(), committed: false,
            #[cfg(target_os = "macos")]
            generated_sidecars: std::collections::HashMap::new() };
        // Directory renaming must be probed with a directory, not a file: the
        // file publisher's hard-link fallback cannot publish directories.
        let probe = output.path.join("probe");
        let ready = output.path.join("ready");
        fs::create_dir(&probe)?;
        match rename(&probe, &ready) {
            Ok(()) => fs::remove_dir(&ready)?,
            Err(e) if directory_rename_unsupported(&e) => {
                fs::remove_dir(&probe)?;
                ensure!(output.owns_path(), "Extraction directory was replaced");
                drop(output.identity.take());
                fs::remove_dir(&output.path)?;
                // create_dir is exclusive even for existing empty directories,
                // symlinks and concurrent extraction jobs.
                fs::create_dir(target).with_context(|| format!(
                    "Could not create extraction directory {} (existing paths are never replaced)", target.display()))?;
                output.path = target.to_owned();
                output.identity = Some(open_directory(target)?);
            }
            Err(e) => return Err(e).context("Could not check exclusive directory renaming"),
        }
        Ok(output)
    }

    pub(crate) fn path(&self) -> &Path { &self.path }

    /// Create each parent ourselves so macOS-generated metadata can be attributed
    /// to that creation, rather than accepting arbitrary preexisting ._ files.
    pub(crate) fn create_directories(&mut self, relative: &Path) -> Result<()> {
        ensure!(self.owns_path(), "Extraction directory was removed or replaced");
        let mut path = self.path.clone();
        for component in relative.components() {
            let std::path::Component::Normal(name) = component else {
                anyhow::bail!("Invalid extraction directory");
            };
            path.push(name);
            match fs::symlink_metadata(&path) {
                Ok(metadata) => ensure!(metadata.is_dir(), "Extraction parent is not a directory"),
                Err(e) if e.kind() == io::ErrorKind::NotFound => {
                    #[cfg(target_os = "macos")]
                    let absent = Self::absent_sidecar(&path)?;
                    fs::create_dir(&path)?;
                    #[cfg(target_os = "macos")]
                    self.record_sidecar(absent)?;
                }
                Err(e) => return Err(e.into()),
            }
        }
        Ok(())
    }

    #[cfg(target_os = "macos")]
    fn absent_sidecar(peer: &Path) -> Result<Option<PathBuf>> {
        let Some(path) = sidecar_path(peer) else { return Ok(None); };
        match fs::symlink_metadata(&path) {
            Ok(_) => Ok(None),
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(Some(path)),
            Err(e) => Err(e.into()),
        }
    }

    #[cfg(target_os = "macos")]
    fn record_sidecar(&mut self, absent: Option<PathBuf>) -> Result<()> {
        let Some(path) = absent else { return Ok(()); };
        let mut file = match open_sidecar(&path, false) {
            Ok(file) => file,
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(()),
            Err(e) => return Err(e.into()),
        };
        // Invalid or unrelated files are never adopted. Their later create_new
        // collision remains an error, preserving the no-overwrite contract.
        if let Ok(record) = generated_sidecar(&mut file) {
            self.generated_sidecars.insert(path, record);
        }
        Ok(())
    }

    pub(crate) fn write_file(&mut self, relative: &Path,
        write: impl FnOnce(&mut File) -> Result<()>) -> Result<()> {
        ensure!(relative.file_name().is_some(), "Missing extraction filename");
        if let Some(parent) = relative.parent() { self.create_directories(parent)?; }
        ensure!(self.owns_path(), "Extraction directory was removed or replaced");
        let path = self.path.join(relative);
        #[cfg(target_os = "macos")]
        let absent = Self::absent_sidecar(&path)?;
        let mut file = match OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(file) => file,
            #[cfg(target_os = "macos")]
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists && self.generated_sidecars.contains_key(&path) => {
                let mut file = open_sidecar(&path, true)?;
                ensure!(generated_sidecar(&mut file)? == self.generated_sidecars[&path],
                    "Generated AppleDouble file was changed or replaced");
                use std::io::{Seek, SeekFrom};
                file.set_len(0)?;
                file.seek(SeekFrom::Start(0))?;
                self.generated_sidecars.remove(&path);
                file
            }
            Err(e) => return Err(e).with_context(|| format!("Could not create extracted file {}", relative.display())),
        };
        write(&mut file)?;
        file.sync_all()?;
        drop(file);
        #[cfg(target_os = "macos")]
        self.record_sidecar(absent)?;
        Ok(())
    }

    fn owns_path(&self) -> bool {
        let (Some(identity), Ok(current)) = (&self.identity, fs::symlink_metadata(&self.path)) else { return false; };
        if !current.is_dir() { return false; }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            identity.metadata().is_ok_and(|owned| owned.dev() == current.dev() && owned.ino() == current.ino())
        }
        #[cfg(windows)]
        {
            let Some(owned) = directory_identity(identity) else { return false; };
            open_directory(&self.path).ok().and_then(|file| directory_identity(&file)) == Some(owned)
        }
        #[cfg(not(any(unix, windows)))]
        { false }
    }

    pub(crate) fn finish(mut self) -> Result<()> {
        ensure!(self.owns_path(), "Extraction directory was removed or replaced");
        if self.path != self.target {
            publish_directory(&self.path, &self.target).context(
                "Could not publish extracted files; existing directories are never replaced")?;
        }
        self.committed = true;
        Ok(())
    }
}

impl Drop for OutputDirectory {
    fn drop(&mut self) {
        let remove = !self.committed && self.owns_path();
        drop(self.identity.take());
        if remove { let _ = fs::remove_dir_all(&self.path); }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[cfg(target_os = "macos")]
    #[test]
    fn generated_appledouble_is_replaced_only_while_its_identity_and_bytes_match() {
        fn native_metadata() -> Vec<u8> {
            let mut bytes = vec![0; 42];
            bytes[..8].copy_from_slice(&[0, 5, 22, 7, 0, 2, 0, 0]);
            bytes[24..26].copy_from_slice(&1u16.to_be_bytes());
            bytes[26..30].copy_from_slice(&9u32.to_be_bytes());
            bytes[30..34].copy_from_slice(&38u32.to_be_bytes());
            bytes[34..38].copy_from_slice(&4u32.to_be_bytes());
            bytes[38..].copy_from_slice(b"meta");
            bytes
        }
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root = std::env::temp_dir().join(format!("cdng-appledouble-ownership-{nonce}"));
        fs::create_dir(&root).unwrap();
        let mut output = OutputDirectory::create(&root.join("restored")).unwrap();
        let native = native_metadata();
        let create_peer = |output: &mut OutputDirectory, name: &str| {
            let sidecar = output.path().join(format!("._{name}"));
            output.write_file(Path::new(name), |file| {
                file.write_all(b"peer")?;
                // Simulate the native filesystem creating metadata as a direct
                // result of this creation. The final exFAT integration also
                // exercises real kernel-generated 4096-byte AppleDouble files.
                fs::write(&sidecar, &native)?;
                Ok(())
            }).unwrap();
            sidecar
        };
        let sidecar = create_peer(&mut output, "frame.dng");
        output.write_file(Path::new("._frame.dng"), |file| {
            file.write_all(b"exact opaque archived bytes")?; Ok(())
        }).unwrap();
        assert_eq!(fs::read(&sidecar).unwrap(), b"exact opaque archived bytes");
        assert!(output.write_file(Path::new("._frame.dng"), |_| Ok(())).is_err());

        // A ._ file already present before its peer was created is not ours.
        let unexpected = output.path().join("._existing.dng");
        fs::write(&unexpected, &native).unwrap();
        output.write_file(Path::new("existing.dng"), |file| {
            file.write_all(b"peer")?; Ok(())
        }).unwrap();
        assert!(output.write_file(Path::new("._existing.dng"), |_| Ok(())).is_err());
        assert_eq!(fs::read(&unexpected).unwrap(), native);

        let changed = create_peer(&mut output, "changed.dng");
        let mut modified = native.clone(); *modified.last_mut().unwrap() ^= 1;
        fs::write(&changed, &modified).unwrap();
        assert!(output.write_file(Path::new("._changed.dng"), |_| Ok(())).is_err());
        assert_eq!(fs::read(&changed).unwrap(), modified);

        let replaced = create_peer(&mut output, "replaced.dng");
        fs::rename(&replaced, output.path().join("old-metadata")).unwrap();
        fs::write(&replaced, &native).unwrap();
        assert!(output.write_file(Path::new("._replaced.dng"), |_| Ok(())).is_err());
        assert_eq!(fs::read(&replaced).unwrap(), native);

        let link = create_peer(&mut output, "linked.dng");
        let external = root.join("must-remain"); fs::write(&external, &native).unwrap();
        fs::remove_file(&link).unwrap();
        std::os::unix::fs::symlink(&external, &link).unwrap();
        assert!(output.write_file(Path::new("._linked.dng"), |_| Ok(())).is_err());
        assert_eq!(fs::read(&external).unwrap(), native);
        let outside = root.join("outside"); fs::create_dir(&outside).unwrap();
        std::os::unix::fs::symlink(&outside, output.path().join("parent-link")).unwrap();
        assert!(output.write_file(Path::new("parent-link/child"), |_| Ok(())).is_err());
        assert!(!outside.join("child").exists());
        drop(output); fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn directory_unsupported_rename_streams_once_and_rolls_back_only_owned_paths() {
        let nonce=SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root=std::env::temp_dir().join(format!("cdng-directory-fallback-{nonce}"));
        fs::create_dir(&root).unwrap();
        let target=root.join("restored");
        let unsupported=|_: &Path, _: &Path| Err(io::Error::from(io::ErrorKind::Unsupported));
        let output=OutputDirectory::create_with(&target,unsupported).unwrap();
        assert_eq!(output.path(),target);
        fs::create_dir(output.path().join("clip")).unwrap();
        fs::write(output.path().join("clip/frame.dng"),b"decoded once").unwrap();
        output.finish().unwrap();
        assert_eq!(fs::read(target.join("clip/frame.dng")).unwrap(),b"decoded once");
        assert!(OutputDirectory::create_with(&target,unsupported).is_err());
        assert_eq!(fs::read_dir(&root).unwrap().count(),1);
        let cancelled=root.join("cancelled");
        let output=OutputDirectory::create_with(&cancelled,unsupported).unwrap();
        fs::write(output.path().join("partial.dng"),b"partial").unwrap();
        drop(output); assert!(!cancelled.exists());
        #[cfg(unix)]
        {
            let output=OutputDirectory::create_with(&cancelled,unsupported).unwrap();
            fs::write(output.path().join("partial.dng"),b"our data").unwrap();
            fs::rename(&cancelled,root.join("moved-by-user")).unwrap();
            fs::create_dir(&cancelled).unwrap();
            fs::write(cancelled.join("keep.txt"),b"different directory").unwrap();
            assert!(output.finish().is_err());
            assert_eq!(fs::read(cancelled.join("keep.txt")).unwrap(),b"different directory");
            let link=root.join("symlink");
            std::os::unix::fs::symlink(&cancelled,&link).unwrap();
            assert!(OutputDirectory::create_with(&link,unsupported).is_err());
        }
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn staged_directory_publication_refuses_concurrent_destination_creation() {
        let nonce=SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root=std::env::temp_dir().join(format!("cdng-directory-race-{nonce}"));
        fs::create_dir(&root).unwrap();
        let target=root.join("restored");
        let output=OutputDirectory::create(&target).unwrap();
        fs::write(output.path().join("frame.dng"),b"decoded").unwrap();
        if output.path()!=target {
            fs::create_dir(&target).unwrap();
            fs::write(target.join("keep.txt"),b"existing").unwrap();
            assert!(output.finish().is_err());
            assert_eq!(fs::read(target.join("keep.txt")).unwrap(),b"existing");
            assert_eq!(fs::read_dir(&root).unwrap().count(),1);
            fs::remove_dir_all(&target).unwrap();
            let output=OutputDirectory::create(&target).unwrap();
            fs::write(output.path().join("frame.dng"),b"decoded").unwrap();
            output.finish().unwrap();
        } else { output.finish().unwrap(); }
        assert_eq!(fs::read(target.join("frame.dng")).unwrap(),b"decoded");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn unsupported_rename_streams_once_and_cleans_up_without_clobbering() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("cdng-output-test-{nonce}"));
        fs::create_dir(&root).unwrap();
        let target = root.join("image.dmg");
        let unsupported = |_: &Path, _: &Path| {
            Err(if cfg!(target_os = "macos") {
                io::Error::from_raw_os_error(45)
            } else {
                io::Error::from(io::ErrorKind::Unsupported)
            })
        };
        let (output, mut file) = OutputFile::create_with(&target, unsupported).unwrap();
        assert_eq!(output.path(), target);
        file.write_all(b"verified image").unwrap();
        drop(file);
        output.finish().unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"verified image");
        assert!(OutputFile::create_with(&target, unsupported).is_err());
        assert_eq!(fs::read(&target).unwrap(), b"verified image");
        assert_eq!(fs::read_dir(&root).unwrap().count(), 1);

        let cancelled = root.join("cancelled.dmg");
        let (output, file) = OutputFile::create_with(&cancelled, unsupported).unwrap();
        drop(file);
        drop(output);
        assert!(!cancelled.exists());

        #[cfg(unix)]
        {
            // A replacement is not ours to delete, even after a failed job.
            let (output, file) = OutputFile::create_with(&cancelled, unsupported).unwrap();
            fs::rename(&cancelled, root.join("moved-by-user")).unwrap();
            fs::write(&cancelled, b"different file").unwrap();
            drop(file);
            assert!(output.finish().is_err());
            assert_eq!(fs::read(&cancelled).unwrap(), b"different file");
            fs::remove_file(&cancelled).unwrap();
            fs::remove_file(root.join("moved-by-user")).unwrap();
        }
        fs::remove_file(target).unwrap();
        fs::remove_dir(root).unwrap();
    }

    #[test]
    fn staged_output_refuses_a_destination_created_while_packing() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("cdng-output-race-{nonce}"));
        fs::create_dir(&root).unwrap();
        let target = root.join("image.dmg");
        let (output, mut file) = OutputFile::create(&target).unwrap();
        if output.path() != target {
            file.write_all(b"our image").unwrap();
            drop(file);
            fs::write(&target, b"existing image").unwrap();
            assert!(output.finish().is_err());
            assert_eq!(fs::read(&target).unwrap(), b"existing image");
            assert_eq!(fs::read_dir(&root).unwrap().count(), 1);
        } else {
            drop(file);
            drop(output);
        }
        let _ = fs::remove_file(target);
        fs::remove_dir(root).unwrap();
    }
}
