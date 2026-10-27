//! CPU-only SHA-256 backend screen; all candidates retain identical digests.
use sha2::{Digest, Sha256};
use std::{hint::black_box,time::Instant};
#[cfg(target_os="macos")]
#[repr(C)]
struct ShaContext {count:[u32;2],hash:[u32;8],wbuf:[u32;16]}
#[cfg(target_os="macos")]
#[link(name="System")]
unsafe extern "C" {
 fn CC_SHA256(data:*const std::ffi::c_void,len:u32,md:*mut u8)->*mut u8;
 fn CC_SHA256_Init(context:*mut ShaContext)->i32;
 fn CC_SHA256_Update(context:*mut ShaContext,data:*const std::ffi::c_void,len:u32)->i32;
 fn CC_SHA256_Final(md:*mut u8,context:*mut ShaContext)->i32;
}
#[cfg(target_os="macos")]
fn apple_one(bytes:&[u8])->[u8;32] {
 let mut out=[0;32];let count=u32::try_from(bytes.len()).unwrap();
 let result=unsafe{CC_SHA256(bytes.as_ptr().cast(),count,out.as_mut_ptr())};assert_eq!(result,out.as_mut_ptr());out
}
#[cfg(target_os="macos")]
fn apple_stream(bytes:&[u8],chunk:usize)->[u8;32] {
 let mut context=ShaContext{count:[0;2],hash:[0;8],wbuf:[0;16]};
 assert_eq!(unsafe{CC_SHA256_Init(&mut context)},1);
 for part in bytes.chunks(chunk){assert_eq!(unsafe{CC_SHA256_Update(&mut context,part.as_ptr().cast(),u32::try_from(part.len()).unwrap())},1);}
 let mut out=[0;32];assert_eq!(unsafe{CC_SHA256_Final(out.as_mut_ptr(),&mut context)},1);out
}
fn rust_stream(bytes:&[u8],chunk:usize)->[u8;32]{let mut hash=Sha256::new();for part in bytes.chunks(chunk){hash.update(part);}hash.finalize().into()}
#[cfg(target_os="macos")]
fn main(){
 assert_eq!(std::mem::size_of::<ShaContext>(),104);assert_eq!(std::mem::align_of::<ShaContext>(),4);
 for size in [0,1,2,3,31,32,55,56,63,64,65,127,128,129,1023,1024,1025,65535,65536,65537,(3<<20)+17,(12<<20)+31]{
 let data:Vec<u8>=(0..size+1).map(|i|(i*73+i/7)as u8).collect();let data=&data[1..];let expected:[u8;32]=Sha256::digest(data).into();
 assert_eq!(apple_one(data),expected,"one-shot length{size}");for chunk in [1,7,64,4096,1<<20]{assert_eq!(apple_stream(data,chunk),expected,"stream length{size} chunk{chunk}");}}
 for size in [(3<<20)+17,(12<<20)+31]{let repeats=if size>4<<20{12}else{48};let data:Vec<u8>=(0..size).map(|i|(i*73+i/7)as u8).collect();let expected:[u8;32]=Sha256::digest(&data).into();
 for round in 0..7{for mode in if round%2==0{[0,1,2,3]}else{[3,2,1,0]}{let begin=Instant::now();let mut checksum=0u8;
 for _ in 0..repeats{let result:[u8;32]=match mode{0=>Sha256::digest(black_box(&data)).into(),1=>rust_stream(black_box(&data),1<<20),2=>apple_one(black_box(&data)),_=>apple_stream(black_box(&data),1<<20)};assert_eq!(result,expected);checksum^=black_box(result[0]);}
 println!("{{\"size\":{size},\"mode\":{mode},\"round\":{round},\"repeats\":{repeats},\"seconds\":{},\"checksum\":{checksum},\"digest_identical\":true}}",begin.elapsed().as_secs_f64());}}
 }
}
#[cfg(not(target_os="macos"))]
fn main(){panic!("CommonCrypto diagnostic requires macOS")}
