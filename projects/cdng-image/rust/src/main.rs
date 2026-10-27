#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]
use anyhow::{Context, Result, bail};
use cdng_image::{
    Backend, Effort,
    pack::{Options, pack},
};
use std::{path::PathBuf, sync::atomic::AtomicBool};
#[cfg(feature = "gui")]
mod gui;

/// Set by Ctrl+C / SIGTERM or a "cancel" line on stdin; packing stops cleanly and
/// removes its unfinished output.
static CANCEL: AtomicBool = AtomicBool::new(false);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Codec {
    Lj92,
    Jxl,
    Temporal,
}

impl Codec {
    fn parse(name: &str) -> Result<Self> {
        match name {
            "lj92" => Ok(Self::Lj92),
            "jxl" => Ok(Self::Jxl),
            "temporal" => Ok(Self::Temporal),
            _ => bail!("Invalid codec (lj92, jxl or temporal)"),
        }
    }
}

fn output_codec(output: &std::path::Path, requested: Option<Codec>) -> Result<Codec> {
    let temporal = output.extension().is_some_and(|e| e.eq_ignore_ascii_case("cdngt"));
    if temporal {
        anyhow::ensure!(requested.is_none_or(|c| c == Codec::Temporal),
            ".cdngt requires --codec temporal; use .dmg or .iso for LJ92 and single-frame JPEG XL");
        return Ok(Codec::Temporal);
    }
    anyhow::ensure!(requested != Some(Codec::Temporal),
        "Temporal compression requires an output filename ending in .cdngt");
    Ok(requested.unwrap_or_else(|| {
        if output.extension().is_some_and(|e| e.eq_ignore_ascii_case("cdngj")) { Codec::Jxl } else { Codec::Lj92 }
    }))
}

fn listen_for_cancel() {
    #[cfg(unix)]
    {
        unsafe extern "C" {
            fn signal(sig: i32, handler: extern "C" fn(i32)) -> usize;
        }
        extern "C" fn on_signal(_: i32) {
            CANCEL.store(true, std::sync::atomic::Ordering::Relaxed);
        }
        unsafe {
            signal(2, on_signal); // SIGINT
            signal(15, on_signal); // SIGTERM
        }
    }
    std::thread::spawn(|| {
        for line in std::io::stdin().lines() {
            match line {
                Ok(l) if l.trim() == "cancel" => CANCEL.store(true, std::sync::atomic::Ordering::Relaxed),
                Ok(_) => {}
                Err(_) => break,
            }
        }
    });
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error:#}");
        std::process::exit(1);
    }
}
fn run() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        #[cfg(feature = "gui")]
        return gui::run(None).map_err(|e| anyhow::anyhow!("{e}"));
        #[cfg(not(feature = "gui"))]
        bail!(
            "Use: cdng-image pack SOURCE OUTPUT.iso --backend cpu|metal|cuda --effort fast|balanced|max --workers 4"
        );
    }
    if args[0] == "--help" {
        println!(
            "CDNG Image\ncdng-image pack SOURCE OUTPUT.dmg [--codec lj92|jxl] [--effort fast|balanced|max]\ncdng-image pack SOURCE OUTPUT.cdngt [--codec temporal] [--effort fast|balanced|max]\n  Default effort: max (Smallest), prioritizing compression ratio. All modes are lossless; faster modes may produce larger files.\n  jxl: Metal on macOS (every frame decoded again on the GPU); --backend cpu uses libjxl.\n  temporal: compares up to 8 consecutive frames and keeps the smaller lossless representation;\n    writes an app-mounted .cdngt archive. Metal on macOS, CPU on other platforms.\n  --exclude-clip FOLDER may be repeated. Progress is printed as one JSON object per line.\n  A line \"cancel\" on stdin (or Ctrl+C) stops and removes the unfinished output. Every file is always verified.\n  expert: --backend cpu|metal|cuda (default: metal on macOS), --workers N (default: automatic), --ram-buffer-mib MiB\ncdng-image mount ARCHIVE.cdngj|ARCHIVE.cdngt [--no-open]   macOS: mount in Finder until ejected\ncdng-image inspect ARCHIVE.cdngj|ARCHIVE.cdngt\ncdng-image extract ARCHIVE.cdngj|ARCHIVE.cdngt NEW_DIRECTORY\ncdng-image read ARCHIVE.cdngj|ARCHIVE.cdngt PATH OFFSET LENGTH NEW_OUTPUT\nNo arguments opens the desktop app."
        );
        return Ok(());
    }
    #[cfg(target_os = "macos")]
    if args[0] == "mount" {
        listen_for_cancel();
        let path = PathBuf::from(args.get(1).context("Missing archive")?);
        return cdng_image::mount::mount(&path, !args.iter().any(|a| a == "--no-open"), &CANCEL);
    }
    if matches!(
        args[0].as_str(),
        "inspect" | "extract" | "read" | "materialize" | "sector-read"
    ) {
        let archive = cdng_image::archive::Archive::open(
            std::path::Path::new(args.get(1).context("Missing archive")?),
            256 << 20,
        )?;
        match args[0].as_str() {
            "inspect" => println!(
                "{}",
                serde_json::json!({"index":archive.index,"read_engine":archive.stats()})
            ),
            "extract" => {
                archive.export(
                    std::path::Path::new(args.get(2).context("Missing output directory")?),
                    &AtomicBool::new(false),
                )?;
                println!("{}", archive.stats());
            }
            "read" => {
                use std::io::Write;
                let name = args.get(2).context("Missing entry path")?;
                let i = archive
                    .index
                    .entries
                    .iter()
                    .position(|e| &e.path == name)
                    .context("Missing entry")?;
                let at: u64 = args.get(3).context("Missing offset")?.parse()?;
                let len: usize = args.get(4).context("Missing length")?.parse()?;
                anyhow::ensure!(len <= 64 << 20, "Read limit is 64 MiB");
                let mut bytes = vec![0; len];
                let n = archive.read_into(i, at, &mut bytes)?;
                let mut file = std::fs::OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(args.get(5).context("Missing output")?)?;
                file.write_all(&bytes[..n])?;
                println!("{}", archive.stats());
            }
            "materialize" => {
                let disk =
                    cdng_image::virtual_disk::VirtualDisk::new(std::sync::Arc::new(archive))?;
                disk.materialize(
                    std::path::Path::new(args.get(2).context("Missing output image")?),
                    &AtomicBool::new(false),
                )?;
                println!(
                    "{}",
                    serde_json::json!({"virtual_bytes":disk.bytes,"mount_installed":false})
                );
            }
            "sector-read" => {
                use std::io::Write;
                let disk =
                    cdng_image::virtual_disk::VirtualDisk::new(std::sync::Arc::new(archive))?;
                let lba: u64 = args.get(2).context("Missing sector")?.parse()?;
                let len: usize = args.get(3).context("Missing byte length")?.parse()?;
                anyhow::ensure!(len <= 64 << 20, "Read limit is 64 MiB");
                let mut bytes = vec![0; len];
                disk.read_sectors(lba, &mut bytes)?;
                let mut file = std::fs::OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(args.get(4).context("Missing output")?)?;
                file.write_all(&bytes)?;
            }
            _ => unreachable!(),
        }
        return Ok(());
    }
    #[cfg(feature = "gui")]
    if args[0] == "gui" {
        return gui::run(args.get(1).map(PathBuf::from)).map_err(|e| anyhow::anyhow!("{e}"));
    }
    if args[0] == "preview" {
        use std::io::Write;
        let data = std::fs::read(args.get(1).context("Missing DNG")?)?;
        let p = cdng_image::dng::preview(&data)?;
        let mut file = std::fs::File::create(args.get(2).context("Missing PPM output")?)?;
        write!(file, "P6\n{} {}\n255\n", p.width, p.height)?;
        file.write_all(&p.rgb)?;
        return Ok(());
    }
    if args[0] == "decode" {
        let input = std::fs::read(args.get(1).context("Missing DNG")?)?;
        let pixels = cdng_image::dng::decode(&input)?;
        let bytes: Vec<u8> = pixels.into_iter().flat_map(u16::to_le_bytes).collect();
        std::fs::write(args.get(2).context("Missing RAW output")?, bytes)?;
        return Ok(());
    }
    if args[0] != "pack" || args.len() < 3 {
        bail!("Use --help for usage");
    }
    let mut options = Options {
        source: PathBuf::from(&args[1]),
        output: PathBuf::from(&args[2]),
        effort: Effort::Max,
        backend: cdng_image::default_backend(),
        workers: 4,
        store: false,
        verify: true,
        ram_buffer_bytes: None,
        excluded_clips: vec![],
        jxl: false,
    };
    let mut workers_specified = false;
    let mut backend_specified = false;
    let mut effort = None;
    let mut requested_codec = None;
    let mut i = 3;
    while i < args.len() {
        match args[i].as_str() {
            "--exclude-clip" => {
                i += 1;
                options
                    .excluded_clips
                    .push(args.get(i).context("Missing excluded clip folder")?.clone());
            }
            "--ram-buffer-mib" => {
                i += 1;
                options.ram_buffer_bytes = Some(
                    args.get(i)
                        .context("Missing RAM buffer size")?
                        .parse::<usize>()?
                        .checked_mul(1 << 20)
                        .context("RAM buffer size too large")?,
                );
            }
            "--backend" => {
                i += 1;
                options.backend = match args.get(i).map(String::as_str) {
                    Some("cpu") => Backend::Cpu,
                    Some("metal") => Backend::Metal,
                    Some("cuda") => Backend::Cuda,
                    _ => bail!("Invalid backend"),
                };
                backend_specified = true;
            }
            "--effort" => {
                i += 1;
                effort = Some(match args.get(i).map(String::as_str) {
                    Some("fast") => Effort::Fast,
                    Some("balanced") => Effort::Balanced,
                    Some("max") => Effort::Max,
                    _ => bail!("Invalid effort"),
                });
            }
            "--codec" => {
                i += 1;
                requested_codec = Some(Codec::parse(args.get(i).context("Missing codec")?)?);
            }
            "--workers" => {
                i += 1;
                options.workers = args.get(i).context("Missing workers")?.parse()?;
                workers_specified = true;
            }
            flag => bail!("Unknown option {flag}"),
        }
        i += 1;
    }
    let codec = output_codec(&options.output, requested_codec)?;
    options.jxl = codec != Codec::Lj92;
    if codec == Codec::Temporal && !cfg!(target_os = "macos") && !backend_specified {
        options.backend = Backend::Cpu;
    }
    let jxl = options.jxl || options.output.extension().is_some_and(|e| e.eq_ignore_ascii_case("cdngj"));
    // Honour explicit effort for LJ92 as well as CPU JPEG XL. Every setting is
    // lossless; more effort searches more predictors and tile geometries.
    options.effort = effort.unwrap_or(Effort::Max);
    // the old .cdngj archive codes with libjxl on the CPU; JPEG XL DMGs use Metal on macOS
    if options.output.extension().is_some_and(|e| e.eq_ignore_ascii_case("cdngj")) {
        options.backend = Backend::Cpu;
    }
    if !workers_specified {
        options.workers = cdng_image::pack::auto_workers(options.backend, jxl);
    }
    listen_for_cancel();
    pack(&options, &CANCEL, |event| println!("{event}"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    #[test]
    fn temporal_extension_selects_codec_and_rejects_mislabeled_output() {
        for name in ["clip.cdngt", "clip.CDNGT"] {
            assert_eq!(output_codec(Path::new(name), None).unwrap(), Codec::Temporal);
            assert_eq!(output_codec(Path::new(name), Some(Codec::Temporal)).unwrap(), Codec::Temporal);
            for codec in [Codec::Lj92, Codec::Jxl] {
                assert!(output_codec(Path::new(name), Some(codec)).is_err());
            }
        }
        for name in ["clip.dmg", "clip.iso", "clip.cdngj", "clip"] {
            assert!(output_codec(Path::new(name), Some(Codec::Temporal)).is_err());
        }
        assert_eq!(output_codec(Path::new("clip.dmg"), None).unwrap(), Codec::Lj92);
        assert_eq!(output_codec(Path::new("clip.cdngj"), None).unwrap(), Codec::Jxl);
        assert_eq!(output_codec(Path::new("clip.dmg"), Some(Codec::Jxl)).unwrap(), Codec::Jxl);
        assert_eq!(Codec::parse("temporal").unwrap(), Codec::Temporal);
        assert!(Codec::parse("unknown").is_err());
    }
}
