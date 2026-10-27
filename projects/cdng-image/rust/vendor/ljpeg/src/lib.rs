#![doc = include_str!("../README.md")]
#![no_std]
#![warn(missing_docs)]

extern crate alloc;

mod decoder;
mod encoder;
mod huffman;
mod pumps;

pub use decoder::{Decoder, DecoderError};
pub use encoder::Encoder;

use core::error::Error;
use core::fmt::{self, Display, Formatter};

#[allow(clippy::upper_case_acronyms)]
#[repr(u8)]
pub(crate) enum Marker {
    SOF3 = 0xc3, // lossless
    DHT = 0xc4,  // huffman tables
    SOI = 0xd8,  // start of image
    EOI = 0xd9,  // end of image
    SOS = 0xda,  // start of scan
    DQT = 0xdb,  // quantization tables
    Fill = 0xff,
    Stuff = 0x00,
}

/// Lossless JPEG predictor.
///
/// Predicts the value of the pixel based on its neighbours.
/// Here, `x` is the pixel whose value is being predicted.
/// ```text
/// | c | b |
/// | a | x |
/// ```
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum Predictor {
    /// `a`
    P1 = 1,
    /// `b`
    P2 = 2,
    /// `c`
    P3 = 3,
    /// `a + b - c`
    P4 = 4,
    /// `a + ((b - c) / 2)`
    P5 = 5,
    /// `b + (a - c) / 2)`
    P6 = 6,
    /// `(a + b) / 2`
    P7 = 7,
}

/// Number of components in a lossless JPEG file.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum Components {
    /// 1 component
    C1 = 1,
    /// 2 components
    C2 = 2,
    /// 3 components
    C3 = 3,
    /// 4 components
    C4 = 4,
}

/// The number of bits per pixel.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum Bitdepth {
    /// 2 bits
    B2 = 2,
    /// 3 bits
    B3 = 3,
    /// 4 bits
    B4 = 4,
    /// 5 bits
    B5 = 5,
    /// 6 bits
    B6 = 6,
    /// 7 bits
    B7 = 7,
    /// 8 bits
    B8 = 8,
    /// 9 bits
    B9 = 9,
    /// 10 bits
    B10 = 10,
    /// 11 bits
    B11 = 11,
    /// 12 bits
    B12 = 12,
    /// 13 bits
    B13 = 13,
    /// 14 bits
    B14 = 14,
    /// 15 bits
    B15 = 15,
    /// 16 bits
    B16 = 16,
}

/// An error signaling that the value is out of bounds.
#[derive(Debug)]
pub struct OutOfBounds(pub u8);

impl TryFrom<u8> for Predictor {
    type Error = OutOfBounds;

    fn try_from(v: u8) -> Result<Self, Self::Error> {
        match v {
            1 => Ok(Self::P1),
            2 => Ok(Self::P2),
            3 => Ok(Self::P3),
            4 => Ok(Self::P4),
            5 => Ok(Self::P5),
            6 => Ok(Self::P6),
            7 => Ok(Self::P7),
            v => Err(OutOfBounds(v)),
        }
    }
}

impl TryFrom<u8> for Components {
    type Error = OutOfBounds;

    fn try_from(v: u8) -> Result<Self, Self::Error> {
        match v {
            1 => Ok(Self::C1),
            2 => Ok(Self::C2),
            3 => Ok(Self::C3),
            4 => Ok(Self::C4),
            v => Err(OutOfBounds(v)),
        }
    }
}

impl TryFrom<u8> for Bitdepth {
    type Error = OutOfBounds;

    fn try_from(v: u8) -> Result<Self, Self::Error> {
        match v {
            2 => Ok(Self::B2),
            3 => Ok(Self::B3),
            4 => Ok(Self::B4),
            5 => Ok(Self::B5),
            6 => Ok(Self::B6),
            7 => Ok(Self::B7),
            8 => Ok(Self::B8),
            9 => Ok(Self::B9),
            10 => Ok(Self::B10),
            11 => Ok(Self::B11),
            12 => Ok(Self::B12),
            13 => Ok(Self::B13),
            14 => Ok(Self::B14),
            15 => Ok(Self::B15),
            16 => Ok(Self::B16),
            v => Err(OutOfBounds(v)),
        }
    }
}

impl Display for OutOfBounds {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        write!(f, "the value {} is out of allowed bounds", self.0)
    }
}

impl Error for OutOfBounds {}
