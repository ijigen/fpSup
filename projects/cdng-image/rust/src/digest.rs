//! Identical SHA-256 digests using the platform implementation on macOS.
//! Other platforms and the diagnostic CDNG_PLATFORM_SHA256=0 switch retain
//! the existing RustCrypto implementation. No digest or verification is omitted.
use sha2::Digest as _;

type Output = sha2::digest::Output<sha2::Sha256>;

#[cfg(target_os = "macos")]
#[repr(C)]
#[derive(Clone)]
struct PlatformContext {
    count: [u32; 2],
    hash: [u32; 8],
    wbuf: [u32; 16],
}
// CommonDigest.h defines CC_LONG=u32 and this exact field layout. Initialize
// every field before calling Init: its scratch words need not be written by C.
#[cfg(target_os = "macos")]
const _: [(); 104] = [(); std::mem::size_of::<PlatformContext>()];
#[cfg(target_os = "macos")]
const _: [(); 4] = [(); std::mem::align_of::<PlatformContext>()];

#[cfg(target_os = "macos")]
#[link(name = "System")]
unsafe extern "C" {
    fn CC_SHA256_Init(context: *mut PlatformContext) -> std::ffi::c_int;
    fn CC_SHA256_Update(context: *mut PlatformContext, data: *const std::ffi::c_void, len: u32) -> std::ffi::c_int;
    fn CC_SHA256_Final(digest: *mut u8, context: *mut PlatformContext) -> std::ffi::c_int;
    fn CC_SHA256(data: *const std::ffi::c_void, len: u32, digest: *mut u8) -> *mut u8;
}

#[cfg(target_os = "macos")]
fn platform_enabled() -> bool {
    static ENABLED: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *ENABLED.get_or_init(|| std::env::var_os("CDNG_PLATFORM_SHA256").is_none_or(|v| v != "0"))
}

#[derive(Clone)]
enum State {
    Rust(sha2::Sha256),
    #[cfg(target_os = "macos")]
    Platform(PlatformContext),
}

#[derive(Clone)]
pub(crate) struct Sha256 {
    state: State,
}

impl Sha256 {
    pub(crate) fn new() -> Self {
        #[cfg(target_os = "macos")]
        if platform_enabled() { return Self::platform(); }
        Self { state: State::Rust(sha2::Sha256::new()) }
    }

    #[cfg(target_os = "macos")]
    fn platform() -> Self {
        let mut context = PlatformContext { count: [0; 2], hash: [0; 8], wbuf: [0; 16] };
        // SAFETY: SDK-compatible, fully initialized writable context; the C
        // implementation retains no pointer after this synchronous call.
        assert_eq!(unsafe { CC_SHA256_Init(&mut context) }, 1, "SHA-256 initialization failed");
        Self { state: State::Platform(context) }
    }

    pub(crate) fn update(&mut self, bytes: impl AsRef<[u8]>) {
        let bytes = bytes.as_ref();
        match &mut self.state {
            State::Rust(state) => state.update(bytes),
            #[cfg(target_os = "macos")]
            State::Platform(context) => {
                // CC_LONG is u32 even on 64-bit macOS. Never truncate a large
                // slice's length; no allocation or copy is needed for chunks.
                for chunk in bytes.chunks(u32::MAX as usize) {
                    // SAFETY: the immutable slice and unique context remain
                    // valid for the synchronous update; len always fits u32.
                    assert_eq!(unsafe {
                        CC_SHA256_Update(context, chunk.as_ptr().cast(), chunk.len() as u32)
                    }, 1, "SHA-256 update failed");
                }
            }
        }
    }

    pub(crate) fn finalize(self) -> Output {
        match self.state {
            State::Rust(state) => state.finalize(),
            #[cfg(target_os = "macos")]
            State::Platform(mut context) => {
                let mut digest = [0u8; 32];
                // SAFETY: the context is complete and digest has exactly the
                // SDK's CC_SHA256_DIGEST_LENGTH writable bytes.
                assert_eq!(unsafe { CC_SHA256_Final(digest.as_mut_ptr(), &mut context) }, 1, "SHA-256 finalization failed");
                digest.into()
            }
        }
    }

    pub(crate) fn digest(bytes: impl AsRef<[u8]>) -> Output {
        let bytes = bytes.as_ref();
        #[cfg(target_os = "macos")]
        if platform_enabled() {
            if let Ok(count) = u32::try_from(bytes.len()) {
                let mut digest = [0u8; 32];
                // SAFETY: both buffers outlive the synchronous function, the
                // supplied length is checked, and the 32-byte output is unique.
                let result = unsafe { CC_SHA256(bytes.as_ptr().cast(), count, digest.as_mut_ptr()) };
                assert_eq!(result, digest.as_mut_ptr(), "SHA-256 digest failed");
                return digest.into();
            }
            let mut state = Self::platform();
            state.update(bytes);
            return state.finalize();
        }
        sha2::Sha256::digest(bytes)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn implementations() -> Vec<Sha256> {
        let mut states = vec![Sha256 { state: State::Rust(sha2::Sha256::new()) }];
        #[cfg(target_os = "macos")]
        states.push(Sha256::platform());
        states
    }

    #[test]
    fn platform_sha256_matches_known_vectors_and_output_format() {
        for (input, expected) in [
            (&b""[..], "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
            (&b"abc"[..], "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
            (&b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"[..], "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"),
        ] {
            assert_eq!(format!("{:x}", Sha256::digest(input)), expected);
            for mut state in implementations() {
                state.update(input);
                assert_eq!(format!("{:x}", state.finalize()), expected);
            }
        }
        let million = vec![b'a'; 1_000_000];
        assert_eq!(format!("{:x}", Sha256::digest(&million)), "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
    }

    #[test]
    fn platform_sha256_matches_independent_rust_at_boundaries_and_unaligned_inputs() {
        let input: Vec<u8> = (0..(12 << 20) + 32).map(|i| (i * 73 + i / 7) as u8).collect();
        for length in [0, 1, 2, 3, 31, 32, 55, 56, 63, 64, 65, 127, 128, 129,
            1023, 1024, 1025, 65535, 65536, 65537, (1 << 20)-1, 1 << 20, (1 << 20)+1,
            (3 << 20)+17, (12 << 20)+31] {
            let bytes = &input[1..length+1];
            let expected = sha2::Sha256::digest(bytes);
            assert_eq!(Sha256::digest(bytes), expected, "one-shot length {length}");
            for mut state in implementations() {
                let mut at = 0;
                state.update([]);
                for chunk in [1usize, 7, 63, 64, 65, 4093, 1 << 20].into_iter().cycle() {
                    let end = bytes.len().min(at + chunk);
                    state.update(&bytes[at..end]);
                    at = end;
                    if at == bytes.len() { break; }
                }
                assert_eq!(state.finalize(), expected, "stream length {length}");
            }
        }
    }

    #[test]
    fn platform_sha256_cloned_partial_states_are_independent() {
        let prefix: Vec<u8> = (0..8193).map(|i| (i * 31) as u8).collect();
        for split in [0, 1, 55, 56, 63, 64, 65, 1023, 8193] {
            for mut state in implementations() {
                state.update(&prefix[..split]);
                let mut a = state.clone();
                let mut b = state.clone();
                a.update(b"first suffix");
                b.update(b"different suffix");
                let mut reference = sha2::Sha256::new();
                reference.update(&prefix[..split]);
                let mut other = reference.clone();
                reference.update(b"first suffix");
                other.update(b"different suffix");
                assert_eq!(a.finalize(), reference.finalize());
                assert_eq!(b.finalize(), other.finalize());
                assert_eq!(state.finalize(), sha2::Sha256::digest(&prefix[..split]));
            }
        }
    }

    #[test]
    fn platform_sha256_concurrent_owned_states_match_rust_reference() {
        std::thread::scope(|scope| {
            for worker in 0..8 {
                scope.spawn(move || {
                    let bytes: Vec<u8> = (0..(1 << 20)+worker*17).map(|i| (i * 73 + worker) as u8).collect();
                    let expected = sha2::Sha256::digest(&bytes);
                    for _ in 0..8 {
                        assert_eq!(Sha256::digest(&bytes), expected);
                        for mut state in implementations() {
                            for chunk in bytes.chunks(4093 + worker) { state.update(chunk); }
                            assert_eq!(state.finalize(), expected);
                        }
                    }
                });
            }
        });
    }
}
