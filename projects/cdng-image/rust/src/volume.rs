//! Display names derive from the saved container, never from its source folder.
use std::path::Path;

pub(crate) fn name(path: &Path) -> String {
    let stem = path.file_stem().unwrap_or_default().to_string_lossy();
    let name: String = stem.chars().map(|c| {
        if c.is_control() || matches!(c, '/' | ':' | '\\') { '_' } else { c }
    }).collect();
    if name.trim().is_empty() { "CDNG".into() } else { name }
}

/// Joliet's volume identifier is 32 bytes of UCS-2. The primary ISO descriptor
/// has its own ASCII fallback; Finder uses the supplementary Joliet descriptor.
pub(crate) fn iso_label(name: &str, joliet: bool) -> String {
    name.chars().take(if joliet { 16 } else { 32 }).map(|c| {
        if joliet {
            if c <= '\u{ffff}' && !c.is_control() { c } else { '_' }
        } else if c.is_ascii_alphanumeric() || c == '_' {
            c.to_ascii_uppercase()
        } else { '_' }
    }).collect()
}

#[cfg(target_os = "macos")]
pub(crate) fn hfs_name(path: &Path) -> anyhow::Result<String> {
    use anyhow::ensure;
    use std::ffi::c_void;
    // Apple's converter applies Unicode 3.2 decomposition with the HFS+
    // exclusions, unlike generic modern Unicode NFD normalization.
    #[link(name = "CoreServices", kind = "framework")]
    unsafe extern "C" {
        fn CreateTextEncoding(base: u32, variant: u32, format: u32) -> u32;
        fn TECCreateConverter(converter: *mut *mut c_void, input: u32, output: u32) -> i32;
        fn TECConvertText(converter: *mut c_void, input: *const u8, input_len: usize,
            used_input: *mut usize, output: *mut u8, output_len: usize, used_output: *mut usize) -> i32;
        fn TECFlushText(converter: *mut c_void, output: *mut u8, output_len: usize, used: *mut usize) -> i32;
        fn TECDisposeConverter(converter: *mut c_void) -> i32;
    }
    struct Converter(*mut c_void);
    impl Drop for Converter {
        fn drop(&mut self) { unsafe { TECDisposeConverter(self.0); } }
    }
    let input = name(path);
    let mut converter = std::ptr::null_mut();
    let status = unsafe {
        TECCreateConverter(&mut converter,
            CreateTextEncoding(0x0100, 0, 2), // UTF-8
            CreateTextEncoding(0x0100, 8, 2)) // HFS+ decomposition, UTF-8
    };
    ensure!(status == 0 && !converter.is_null(), "Cannot prepare volume name: {status}");
    let converter = Converter(converter);
    let mut bytes = vec![0; input.len() * 8 + 64];
    let (mut consumed, mut written, mut flushed) = (0, 0, 0);
    let status = unsafe { TECConvertText(converter.0, input.as_ptr(), input.len(), &mut consumed,
        bytes.as_mut_ptr(), bytes.len(), &mut written) };
    ensure!(status == 0 && consumed == input.len() && written <= bytes.len(), "Cannot normalize volume name: {status}");
    let status = unsafe { TECFlushText(converter.0, bytes[written..].as_mut_ptr(), bytes.len() - written, &mut flushed) };
    ensure!(status == 0 && flushed <= bytes.len() - written, "Cannot finish volume name: {status}");
    bytes.truncate(written + flushed);
    let decoded = String::from_utf8(bytes)?;
    let mut count = 0;
    Ok(decoded.chars().take_while(|c| {
        count += c.len_utf16();
        count <= 255
    }).collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn output_filename_keeps_case_unicode_and_inner_dots() {
        assert_eq!(name(Path::new("/folder/Cinema 拍攝.v2.dmg")), "Cinema 拍攝.v2");
        assert_eq!(name(Path::new("/folder/    .cdngt")), "CDNG");
        assert_eq!(name(Path::new("/folder/Bad:Name.cdngj")), "Bad_Name");
    }

    #[test]
    fn iso_labels_have_separate_unicode_and_ascii_limits() {
        let title = "My 拍攝 Name 2026 Long";
        assert_eq!(iso_label(title, true), "My 拍攝 Name 2026 ");
        assert_eq!(iso_label(title, false), "MY____NAME_2026_LONG");
        assert_eq!(iso_label("Movie🎥", true), "Movie_");
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn hfs_volume_name_uses_native_decomposition_and_long_unicode_names() {
        assert_eq!(hfs_name(Path::new("/tmp/Café 拍攝.cdngj")).unwrap(), "Cafe\u{301} 拍攝");
        let title = format!("{}🎥", "拍".repeat(254));
        let result = hfs_name(Path::new(&format!("{title}.cdngt"))).unwrap();
        assert_eq!(result, "拍".repeat(254));
        assert_eq!(hfs_name(Path::new("Å 拍攝.cdngj")).unwrap(), "Å 拍攝");
    }
}
