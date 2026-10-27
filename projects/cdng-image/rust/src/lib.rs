mod digest;
pub mod archive;
pub mod dmg;
pub mod dng;
pub mod gpu;
mod gpu_prune;
#[cfg(target_os = "macos")]
pub mod gpu_batch;
pub mod hfs;
pub mod iso;
pub mod jxl;
pub mod temporal;
#[cfg(target_os = "macos")]
pub mod mount;
pub mod pack;
mod output;
mod ram;
mod tile_buffer;
pub mod virtual_disk;

use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicBool, Ordering};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Effort {
    Fast,
    Balanced,
    Max,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Backend {
    Cpu,
    Metal,
    Cuda,
}
/// GPU backend when this build has one (Metal on macOS, CUDA when built with it).
pub fn default_backend() -> Backend {
    if cfg!(target_os = "macos") {
        Backend::Metal
    } else if cfg!(feature = "cuda") {
        Backend::Cuda
    } else {
        Backend::Cpu
    }
}
pub fn cancelled(cancel: &AtomicBool) -> anyhow::Result<()> {
    anyhow::ensure!(!cancel.load(Ordering::Relaxed), "已取消");
    Ok(())
}
pub fn hash(bytes: &[u8]) -> String {
    use crate::digest::Sha256;
    format!("{:x}", Sha256::digest(bytes))
}
