//! Compare LJ92 effort levels with the same current packing and verification code.
//! Diagnostic only: this does not change the desktop app's compression setting.
use anyhow::{Context, Result, ensure};
use cdng_image::{Backend, Effort, pack::{Options, auto_workers, pack}};
use std::{fs, path::PathBuf, sync::atomic::AtomicBool};

fn main() -> Result<()> {
    let mut args = std::env::args_os().skip(1);
    let source = PathBuf::from(args.next().context("SOURCE OUTPUT_DIRECTORY")?);
    let directory = PathBuf::from(args.next().context("SOURCE OUTPUT_DIRECTORY")?);
    ensure!(!directory.exists(), "Diagnostic output directory must be new");
    fs::create_dir(&directory)?;
    let mut results = Vec::new();
    for repeat in 0..3 {
        let modes = if repeat % 2 == 0 { [Effort::Balanced, Effort::Max] } else { [Effort::Max, Effort::Balanced] };
        for effort in modes {
            let output = directory.join(format!("{effort:?}-{repeat}.dmg"));
            let summary = pack(&Options {
                source: source.clone(), output: output.clone(), effort,
                backend: Backend::Metal, workers: auto_workers(Backend::Metal, false),
                store: false, verify: true, ram_buffer_bytes: None,
                excluded_clips: vec![], jxl: false,
            }, &AtomicBool::new(false), |_| {})?;
            let row = serde_json::json!({"effort":effort,"repeat":repeat,"summary":summary});
            println!("{row}");
            results.push(row);
            fs::remove_file(output)?;
        }
    }
    fs::write(directory.join("results.json"), serde_json::to_vec_pretty(&results)?)?;
    Ok(())
}
