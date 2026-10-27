#![feature(test)]
extern crate test;

use ljpeg::Decoder;
use test::{black_box, Bencher};

#[inline]
fn read_image(image: &[u8]) -> Vec<u16> {
    let decoder = Decoder::new(black_box(image)).unwrap();
    decoder.decode().unwrap()
}

#[bench]
fn raw_ljpeg(b: &mut Bencher) {
    b.iter(|| read_image(include_bytes!("../tests/2comp.jpg")));
}
