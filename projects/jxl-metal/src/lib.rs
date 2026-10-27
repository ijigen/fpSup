//! Lossless JPEG XL on Metal: a GPU decoder for standard codestreams and a GPU encoder
//! that writes them (grey, modular, 128 x 128 groups, one frame-wide MA tree).
pub mod decode;
pub mod encode;
