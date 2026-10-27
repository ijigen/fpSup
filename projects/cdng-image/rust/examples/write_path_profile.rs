//! Isolated write-path diagnostic. Never opens source media for writing.
//! Run only when the owner of the benchmark has serialized disk activity.
use anyhow::{Context, Result, ensure};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    hint::black_box,
    io::{IoSlice, Read, Seek, Write},
    path::PathBuf,
    time::{Instant, SystemTime, UNIX_EPOCH},
};

const SECTOR: usize = 2048;
#[derive(Clone, Copy, Debug)]
enum Mode {
    Current,
    Tracked,
    Batched,
}
impl Mode {
    fn name(self) -> &'static str {
        match self {
            Self::Current => "per-frame-writev-position",
            Self::Tracked => "per-frame-writev-tracked",
            Self::Batched => "multi-frame-writev-tracked",
        }
    }
}
#[derive(Clone, Copy)]
struct Frame {
    bytes: usize,
    padding: usize,
}
struct Directory(PathBuf);
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir(&self.0);
    }
}
struct Output {
    path: PathBuf,
    file: File,
    keep: bool,
}
impl Drop for Output {
    fn drop(&mut self) {
        if self.keep {
            return;
        }
        // Held-handle identity, obtained after writing, also works when exFAT
        // changes an empty file's inode on its first allocation.
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if let (Ok(at), Ok(held)) = (fs::symlink_metadata(&self.path), self.file.metadata()) {
                if at.is_file() && at.dev() == held.dev() && at.ino() == held.ino() {
                    let _ = fs::remove_file(&self.path);
                }
            }
        }
    }
}
fn writev(file: &mut File, slices: &mut [IoSlice<'_>]) -> Result<usize> {
    let mut rest = slices;
    let mut calls = 0;
    while !rest.is_empty() {
        calls += 1;
        match file.write_vectored(rest) {
            Ok(0) if rest.iter().all(|p| p.is_empty()) => break,
            Ok(0) => anyhow::bail!("write_vectored returned zero"),
            Ok(n) => IoSlice::advance_slices(&mut rest, n),
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e.into()),
        }
    }
    Ok(calls)
}
fn plan(total: usize, count: usize) -> Result<Vec<Frame>> {
    ensure!(
        total / SECTOR > count * 4 && count >= 11,
        "Output is too small for the frame count"
    );
    let mut result = Vec::with_capacity(count + 1);
    // Ten small sidecars, then varying frame spans. No extra staging copy is
    // introduced: every payload borrows one initialized, bounded backing buffer.
    for i in 0..10 {
        let bytes = 128 + 29 * i;
        result.push(Frame {
            bytes,
            padding: SECTOR - bytes,
        });
    }
    let weights: Vec<_> = (0..count - 10).map(|i| 2 + (i * 73 + i / 17) % 7).collect();
    let weight_sum: usize = weights.iter().sum();
    let mut sectors_left = total / SECTOR - 10;
    let distributable = sectors_left;
    let weight_count = weights.len();
    for (i, weight) in weights.into_iter().enumerate() {
        let sectors = if i + 1 == weight_count {
            sectors_left
        } else {
            distributable
                .checked_mul(weight)
                .context("Plan size overflow")?
                / weight_sum
        };
        ensure!(
            sectors > 0 && sectors <= sectors_left,
            "Invalid payload plan"
        );
        sectors_left -= sectors;
        let span = sectors.checked_mul(SECTOR).context("Plan size overflow")?;
        let padding = (i * 73) % SECTOR;
        result.push(Frame {
            bytes: span - padding,
            padding,
        });
    }
    ensure!(sectors_left == 0, "Incomplete payload plan");
    let trailer = total % SECTOR;
    if trailer > 0 {
        result.push(Frame {
            bytes: trailer,
            padding: 0,
        });
    }
    ensure!(
        result.iter().map(|f| f.bytes + f.padding).sum::<usize>() == total,
        "Plan length mismatch"
    );
    Ok(result)
}
fn scalar_crc(bytes: &[u8], state: &mut u32, table: &[u32; 256]) {
    for &byte in bytes {
        *state = table[((*state as u8) ^ byte) as usize] ^ (*state >> 8);
    }
}
fn main() -> Result<()> {
    let mut args = std::env::args_os().skip(1);
    let parent = PathBuf::from(args.next().context(
        "PARENT [--bytes N] [--frames N] [--rounds N] [--batch N] [--fixture FILE] [--keep]",
    )?)
    .canonicalize()?;
    let (mut bytes, mut frames, mut rounds, mut batch) =
        (4_720_229_727usize, 1553usize, 3usize, 8usize);
    let (mut fixture_path, mut keep) = (None, false);
    while let Some(flag) = args.next() {
        if flag == "--keep" {
            keep = true;
            continue;
        }
        let value = args.next().context("Missing option value")?;
        match flag.to_str().context("Non-Unicode option")? {
            "--bytes" => bytes = value.to_str().context("Invalid bytes")?.parse()?,
            "--frames" => frames = value.to_str().context("Invalid frames")?.parse()?,
            "--rounds" => rounds = value.to_str().context("Invalid rounds")?.parse()?,
            "--batch" => batch = value.to_str().context("Invalid batch")?.parse()?,
            "--fixture" => fixture_path = Some(PathBuf::from(value)),
            _ => anyhow::bail!("Unknown option: {}", flag.to_string_lossy()),
        }
    }
    ensure!(
        parent.is_dir() && (1..=16).contains(&rounds) && (1..=128).contains(&batch),
        "Invalid benchmark options"
    );
    ensure!(
        bytes <= 64usize << 30 && frames <= 100_000,
        "Diagnostic size limit exceeded"
    );
    let plan = plan(bytes, frames)?;
    let maximum = plan.iter().map(|f| f.bytes).max().unwrap();
    ensure!(maximum <= 32 << 20, "Largest fixture would exceed 32 MiB");
    let mut fixture = vec![0u8; maximum];
    if let Some(path) = &fixture_path {
        ensure!(
            fs::metadata(path)?.len() <= 32 << 20,
            "Fixture exceeds 32 MiB"
        );
        let sample = fs::read(path)?;
        ensure!(!sample.is_empty(), "Empty fixture");
        for (i, byte) in fixture.iter_mut().enumerate() {
            *byte = sample[i % sample.len()];
        }
    } else {
        for (i, byte) in fixture.iter_mut().enumerate() {
            *byte = (i.wrapping_mul(73).wrapping_add(i >> 3)) as u8;
        }
    }
    let zeros = [0u8; SECTOR];
    let mut expected_crc = crc32fast::Hasher::new();
    let mut expected_sha = Sha256::new();
    for f in &plan {
        expected_crc.update(&fixture[..f.bytes]);
        expected_crc.update(&zeros[..f.padding]);
        expected_sha.update(&fixture[..f.bytes]);
        expected_sha.update(&zeros[..f.padding]);
    }
    let expected_crc = expected_crc.finalize();
    let expected_sha = format!("{:x}", expected_sha.finalize());
    // Current CRC is serial in the image writer, but crc32fast may use hardware
    // instructions. Report that separately from a true byte-at-a-time baseline.
    let t = Instant::now();
    let mut crc = crc32fast::Hasher::new();
    for f in &plan {
        crc.update(black_box(&fixture[..f.bytes]));
        crc.update(&zeros[..f.padding]);
    }
    let crc_only_seconds = t.elapsed().as_secs_f64();
    ensure!(crc.finalize() == expected_crc, "CRC-only mismatch");
    let mut table = [0u32; 256];
    for (i, entry) in table.iter_mut().enumerate() {
        let mut v = i as u32;
        for _ in 0..8 {
            v = (v >> 1) ^ ((0u32.wrapping_sub(v & 1)) & 0xedb8_8320);
        }
        *entry = v;
    }
    let scalar_bytes = (64usize << 20).min(bytes);
    let t = Instant::now();
    let mut scalar = !0u32;
    let mut scalar_reference = crc32fast::Hasher::new();
    let mut left = scalar_bytes;
    while left > 0 {
        let n = left.min(fixture.len());
        scalar_crc(black_box(&fixture[..n]), &mut scalar, &table);
        scalar_reference.update(&fixture[..n]);
        left -= n;
    }
    let scalar_seconds = t.elapsed().as_secs_f64();
    ensure!(
        !scalar == scalar_reference.finalize(),
        "Scalar CRC polynomial mismatch"
    );
    let token = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let directory = parent.join(format!(
        ".cdng-write-profile-{}-{token}",
        std::process::id()
    ));
    fs::create_dir(&directory)?;
    let dir = Directory(directory);
    let mut rows = Vec::new();
    for round in 0..rounds {
        let modes = match round % 3 {
            0 => [Mode::Current, Mode::Tracked, Mode::Batched],
            1 => [Mode::Batched, Mode::Tracked, Mode::Current],
            _ => [Mode::Tracked, Mode::Current, Mode::Batched],
        };
        for mode in modes {
            let path = dir.0.join(format!("round-{round}-{}.bin", mode.name()));
            let file = OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(&path)?;
            let mut output = Output { path, file, keep };
            let (mut write_seconds, mut position_seconds, mut crc_seconds, mut calls, mut offset) =
                (0., 0., 0., 0usize, 0usize);
            let group = if matches!(mode, Mode::Batched) {
                batch
            } else {
                1
            };
            let mut crc = crc32fast::Hasher::new();
            let mut slices = Vec::with_capacity(group * 2);
            let start = Instant::now();
            for chunk in plan.chunks(group) {
                if matches!(mode, Mode::Current) {
                    let t = Instant::now();
                    let observed = output.file.stream_position()?;
                    position_seconds += t.elapsed().as_secs_f64();
                    ensure!(observed == offset as u64, "File position changed");
                }
                slices.clear();
                for f in chunk {
                    slices.push(IoSlice::new(&fixture[..f.bytes]));
                    slices.push(IoSlice::new(&zeros[..f.padding]));
                }
                let t = Instant::now();
                calls += writev(&mut output.file, &mut slices)?;
                write_seconds += t.elapsed().as_secs_f64();
                let t = Instant::now();
                for f in chunk {
                    crc.update(&fixture[..f.bytes]);
                    crc.update(&zeros[..f.padding]);
                    offset = offset
                        .checked_add(f.bytes + f.padding)
                        .context("Offset overflow")?;
                }
                crc_seconds += t.elapsed().as_secs_f64();
            }
            let stream_seconds = start.elapsed().as_secs_f64();
            let t = Instant::now();
            output.file.sync_all()?;
            let sync_seconds = t.elapsed().as_secs_f64();
            let total_seconds = start.elapsed().as_secs_f64();
            ensure!(
                offset == bytes
                    && output.file.metadata()?.len() == bytes as u64
                    && crc.finalize() == expected_crc,
                "Writer length or CRC mismatch"
            );
            let checking = Instant::now();
            let mut readback = File::open(&output.path)?;
            let mut buffer = vec![0u8; 1 << 20];
            let mut crc = crc32fast::Hasher::new();
            let mut sha = Sha256::new();
            let mut checked = 0u64;
            loop {
                let n = readback.read(&mut buffer)?;
                if n == 0 {
                    break;
                }
                crc.update(&buffer[..n]);
                sha.update(&buffer[..n]);
                checked += n as u64;
            }
            ensure!(
                checked == bytes as u64
                    && crc.finalize() == expected_crc
                    && format!("{:x}", sha.finalize()) == expected_sha,
                "Full output readback mismatch"
            );
            let row = json!({"round":round,"mode":mode.name(),"path":output.path,"bytes":bytes,"writev_calls":calls,"stream_position_calls":if matches!(mode,Mode::Current){plan.len()}else{0},"group_frames":group,"stream_seconds":stream_seconds,"write_seconds":write_seconds,"position_seconds":position_seconds,"crc_seconds":crc_seconds,"sync_seconds":sync_seconds,"total_seconds":total_seconds,"readback_seconds":checking.elapsed().as_secs_f64(),"full_crc_and_sha_verified":true});
            println!("{row}");
            rows.push(row);
        }
    }
    println!(
        "{}",
        json!({"complete":true,"temporary_directory":dir.0,"kept":keep,"logical_payloads":plan.len(),"fixture_bytes":fixture.len(),"expected_sha256":expected_sha,"expected_crc32":expected_crc,"crc_only_bytes":bytes,"crc_only_seconds":crc_only_seconds,"scalar_crc_bytes":scalar_bytes,"scalar_crc_seconds":scalar_seconds,"runs":rows,"limits":"Synthetic bounded fixture; isolates writev, position query, serial CRC and sync, excluding source reads, encoder, source metadata checks, GUI and disk-image metadata. Readback uses normal OS cache and occurs after sync; it is not a physical media scrub. Every mode writes identical bytes. Default cleanup removes only identity-matched files exclusively created by this run."})
    );
    Ok(())
}
