// Lossless JPEG encoder
// ITU T.81 Annex H from 1992
//
// Originally written by Andrew Baldwin as lj92.c
// Ported to Rust by Daniel Vogelbacher
//
// (c) 2014 Andrew Baldwin
// (c) 2021 Daniel Vogelbacher
//
// Permission is hereby granted, free of charge, to any person obtaining a copy of
// this software and associated documentation files (the "Software"), to deal in
// the Software without restriction, including without limitation the rights to
// use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
// of the Software, and to permit persons to whom the Software is furnished to do
// so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.
use crate::{Bitdepth, Components, Marker, Predictor};

use alloc::{vec, vec::Vec};

/// Find the number of bits needed for the magnitude of the coefficient
/// Maps directly to integer count-leading-zero instructions.
#[inline]
const fn lookup_ssss(diff: i16) -> u16 {
    (32 - (diff as i32).unsigned_abs().leading_zeros()) as u16
}

/// Encoder for Lossless JPEG
///
/// With this type you can get a instance of `Encoder`.
/// The encode() method consumes the instance and
/// returns the encoded JPEG data.
#[derive(Clone, Copy, Debug)]
pub struct Encoder {
    /// Width of input image
    width: usize,
    /// height of input image
    height: usize,
    /// Number of components (1-4)
    components: usize,
    /// Bitdepth of input image
    bitdepth: u8,
    /// Point transformation parameter
    /// **Warning:** This is untested, use with caution
    point_transform: u8,
    /// Predictor
    predictor: Predictor,
    /// Extra width after each line before next line starts
    padding: usize,
}

/// HUFFENC and HUFFBITS
#[derive(Debug, Default, Clone)]
struct HuffCode {
    enc: u16,
    bits: u16,
}

/// Huffman table builder
///
/// Builds an optimal Huffman table for encoding for a given
/// list of frequencies and total resolution.
#[derive(Default, Debug)]
struct HuffTableBuilder {
    /// Frequency of occurrence of symbol V
    /// Used while building the table. Initialized with the
    /// frequencies for each ssss (0-16).
    /// Reserving one code point guarantees that no code word can ever be all “1” bits.
    freq: [u64; Self::CLASSES + 1],

    /// Code size of symbol V
    /// Size (in bits) for each ssss.
    codesize: [usize; Self::CLASSES + 1],

    /// Index to next symbol in chain of all symbols in current branch of code tree
    /// Other frequencies, used during table buildup.
    others: [Option<usize>; Self::CLASSES + 1],

    /// Numbers of codes of each size
    bits: Vec<u8>,

    /// List of values (ssss) sorted in ascending
    /// code length.
    /// Unused values (at the end of array) are set
    /// to `None`.
    huffval: [Option<u8>; Self::CLASSES],

    /// Code for each symbol
    /// Is is a combination of Huffbits and Huffenc
    huffcode: [HuffCode; Self::CLASSES + 1],

    /// Maps a value (ssss) to a symbol.
    /// This symbol can be used as index into
    /// `huffcode` to get the actual code for encoding.
    huffsym: [Option<usize>; Self::CLASSES],
}

impl HuffTableBuilder {
    /// Count of classes for Lossless JPEG
    /// For regular JPEG, V goes from 0 to 256. For lossless,
    /// we only have 17 classes for ssss (0-16).
    const CLASSES: usize = 17; // Sample classes for Lossless JPEG

    /// Construct new Huffman table for given histogram
    /// and image resolution
    fn new(histogram: [usize; Self::CLASSES]) -> Self {
        let mut ins = Self::default();
        ins.bits.resize(33, 0);
        for (i, &freq) in histogram.iter().enumerate() {
            ins.freq[i] = freq as u64;
        }
        // T.81 Annex K reserves a pseudo-symbol with frequency ONE COUNT.
        // It must not have weight equal to an entire normalized component.
        ins.freq[Self::CLASSES] = 1;
        ins
    }

    /// Figure K.1 - Procedure to find Huffman code sizes
    fn gen_codesizes(&mut self) {
        loop {
            // smallest frequencies found in loop
            let mut v1freq = u64::MAX;
            let mut v2freq = u64::MAX;
            // Indices into frequency table
            let mut v1: Option<usize> = None;
            let mut v2: Option<usize> = None;
            // Search v1
            for (i, f) in self.freq.iter().enumerate().filter(|(_i, f)| **f > 0) {
                if *f <= v1freq {
                    v1freq = *f;
                    v1 = Some(i);
                }
            }
            // Search v2
            for (i, f) in self
                .freq
                .iter()
                .enumerate()
                .filter(|(i, f)| **f > 0 && Some(*i) != v1)
            {
                if *f <= v2freq {
                    v2freq = *f;
                    v2 = Some(i);
                }
            }

            match (&mut v1, &mut v2) {
                (Some(v1), Some(v2)) => {
                    // Combine frequency values
                    self.freq[*v1] += self.freq[*v2];
                    self.freq[*v2] = 0;

                    // Increment code sizes for all codewords in this tree branch
                    loop {
                        self.codesize[*v1] += 1;
                        if let Some(other) = self.others[*v1] {
                            *v1 = other
                        } else {
                            break;
                        }
                    }
                    self.others[*v1] = Some(*v2);
                    loop {
                        self.codesize[*v2] += 1;
                        if let Some(other) = self.others[*v2] {
                            *v2 = other;
                        } else {
                            break;
                        }
                    }
                }
                _ => {
                    break; // exit loop, all frequencies are processed
                }
            }
        }
    }

    /// Figure K.2 - Procedure to find the number of codes of each size
    fn count_bits(&mut self) {
        // K2
        for i in 0..18 {
            if self.codesize[i] > 0 {
                self.bits[self.codesize[i]] += 1;
            }
        } // end of K2

        self.adjust_bits();
    }

    /// Section K.2 Figure K.4 Sorting of input values according to code size
    /// The input values are sorted according to code size as shown in Figure
    /// K.4.  HUFFVAL is the list containing the input values associated with
    /// each code word, in order of increasing code length.
    ///
    /// At this point, the list of code lengths (BITS) and the list of values
    /// (HUFFVAL) can be used to generate the code tables.  These procedures
    /// are described in Annex C.
    fn sort_input(&mut self) {
        let mut k = 0;
        for i in 1..=32 {
            for j in 0..=16 {
                // ssss
                if self.codesize[j] == i {
                    self.huffval[k] = Some(j as u8);
                    k += 1;
                }
            }
        }
    }

    /// Section C.2 Figure C.1 Generation of table of Huffman code sizes
    fn gen_size_table(&mut self) -> usize {
        let mut k = 0;
        let mut i = 1;

        while i <= 16 {
            let mut j = 1;
            while j <= self.bits[i] {
                self.huffcode[k].bits = i as u16;
                j += 1;
                k += 1;
            }
            i += 1;
        }
        self.huffcode[k].bits = 0;
        k
    }

    /// Section C.2 Figure C.2 Generation of table of Huffman codes
    fn gen_code_table(&mut self) {
        let mut k = 0;
        let mut code = 0;
        let mut si = self.huffcode[0].bits;
        loop {
            loop {
                self.huffcode[k].enc = code;
                code += 1;
                k += 1;
                if self.huffcode[k].bits != si {
                    break;
                }
            }
            if self.huffcode[k].bits == 0 {
                break;
            }
            loop {
                code <<= 1;
                si += 1;
                if self.huffcode[k].bits == si {
                    break;
                }
            }
        }
    }

    /// Section C.2 Figure C.3 Ordering procedure for encoding code tables
    fn order_codes(&mut self, _lastk: usize) {
        for (i, ssss) in self.huffval.iter().enumerate() {
            if let Some(ssss) = ssss {
                self.huffsym[*ssss as usize] = Some(i);
            }
        }
    }

    /// Section K.2 Figure K.3 Procedure for limiting code lengths to 16 bits
    ///
    /// Figure K.3 gives the procedure for adjusting the BITS list so that no
    /// code is longer than 16 bits.  Since symbols are paired for the
    /// longest Huffman code, the symbols are removed from this length
    /// category two at a time.  The prefix for the pair (which is one bit
    /// shorter) is allocated to one of the pair; then (skipping the BITS
    /// entry for that prefix length) a code word from the next shortest
    /// non-zero BITS entry is converted into a prefix for two code words one
    /// bit longer.  After the BITS list is reduced to a maximum code length
    /// of 16 bits, the last step removes the reserved code point from the
    /// code length count.
    fn adjust_bits(&mut self) {
        let mut i = 32;

        while i > 16 {
            if self.bits[i] > 0 {
                let mut j = i - 2; // See K.3: J = I - 1; J  = J - 1;
                while self.bits[j] == 0 {
                    j -= 1;
                }
                self.bits[i] -= 2;
                self.bits[i - 1] += 1;
                self.bits[j + 1] += 2;
                self.bits[j] -= 1;
            } else {
                i -= 1;
            }
        }

        while self.bits[i] == 0 {
            i -= 1;
        }
        self.bits[i] -= 1;
    }

    /// Build Huffman table
    #[allow(clippy::needless_range_loop)]
    fn build(mut self) -> [BitArray16; HuffTableBuilder::CLASSES] {
        self.gen_codesizes();
        self.count_bits();
        self.sort_input();
        let lastk = self.gen_size_table();
        self.gen_code_table();
        self.order_codes(lastk);
        let mut table = [BitArray16::default(); HuffTableBuilder::CLASSES];

        for ssss in 0..=16 {
            if let Some(code) = self.huffsym[ssss] {
                let enc = &self.huffcode[code];
                table[ssss] = BitArray16::from_lsb(enc.bits as usize, enc.enc);
            }
        }

        table
    }
}

/// State for one component of the image
#[derive(Default, Clone, Copy, Debug)]
struct ComponentState {
    /// Histogram of component
    histogram: [usize; 17],
    /// Huffman table for component
    hufftable: [BitArray16; HuffTableBuilder::CLASSES],
}

/// Bitstream for JPEG encoded data
struct BitstreamJPEG<'a> {
    inner: &'a mut Vec<u8>,
    pending: u64,
    used: usize,
}

impl<'a> BitstreamJPEG<'a> {
    #[inline]
    fn new(inner: &'a mut Vec<u8>) -> Self {
        Self {
            inner,
            pending: 0,
            used: 0,
        }
    }

    #[inline]
    fn write(&mut self, bits: usize, value: u64) {
        // CDNG Image: accumulate whole codes instead of splitting each code at
        // every byte boundary. The byte order, stuffing and zero padding stay identical.
        debug_assert!(bits <= 56);
        if bits == 0 {
            return;
        }
        let value = value & ((1u64 << bits) - 1);
        if self.used + bits < 64 {
            self.pending = (self.pending << bits) | value;
            self.used += bits;
        } else {
            let free = 64 - self.used;
            let word = (self.pending << free) | (value >> (bits - free));
            self.write_word(word);
            self.used = bits - free;
            self.pending = value & ((1u64 << self.used) - 1);
        }
    }

    #[inline]
    fn write_word(&mut self, word: u64) {
        let inverted = !word;
        let contains_ff =
            inverted.wrapping_sub(0x0101010101010101) & !inverted & 0x8080808080808080 != 0;
        let bytes = word.to_be_bytes();
        if contains_ff {
            for byte in bytes {
                self.write_byte(byte);
            }
        } else {
            self.inner.extend_from_slice(&bytes);
        }
    }

    #[inline]
    fn write_byte(&mut self, byte: u8) {
        self.inner.push(byte);
        if byte == 0xFF {
            // Byte stuffing
            self.inner.push(0x00);
        }
    }

    fn flush(&mut self) {
        if self.used > 0 {
            let count = self.used.div_ceil(8);
            let padded = self.pending << ((8 - self.used % 8) % 8);
            for i in (0..count).rev() {
                self.write_byte((padded >> (i * 8)) as u8);
            }
            self.used = 0;
            self.pending = 0;
        }
    }
}

impl Encoder {
    /// Create a new LJPEG encoder
    ///
    /// `padding` specifies the expeced padding after each row in the input image.
    pub fn new(
        width: u16,
        height: u16,
        components: Components,
        bitdepth: Bitdepth,
        predictor: Predictor,
        point_transform: u8,
        padding: usize,
    ) -> Self {
        let width = width as usize;
        let height = height as usize;
        Self {
            width,
            height,
            components: components as usize,
            bitdepth: bitdepth as u8,
            point_transform,
            predictor,
            padding,
        }
    }

    /// Encode the input image.
    ///
    /// Returns `None` if the length of the image buffer is too small for the image dimensions.
    pub fn encode(&self, image: &[u16]) -> Option<Vec<u8>> {
        if image.len() < self.height * ((self.width + self.padding) * self.components) {
            return None;
        }

        let mut encoded = Vec::with_capacity(2 * self.width * self.height * self.components);
        let (mut comp_state, cache) = self.scan_frequency(image);
        for comp in comp_state.iter_mut().take(self.components) {
            self.build_hufftable(comp);
        }

        self.write_header(&comp_state, &mut encoded);
        self.write_body(&comp_state, &cache, &mut encoded);
        self.write_post(&mut encoded);
        Some(encoded)
    }

    /// Build the JPEG prefix and canonical codes from externally counted DC
    /// categories. Each packed code is `(length << 16) | value`, indexed by
    /// component then category. The returned bit count excludes byte stuffing.
    /// This permits a parallel entropy writer to use the same tables as encode.
    pub fn plan_entropy(&self, histogram: &[[u32; 17]]) -> Option<(Vec<u8>, Vec<u32>, u64)> {
        self.plan_entropy_bounded(histogram, None)?
    }

    /// Plan the same JPEG as `plan_entropy`, skipping serialization if its
    /// exact entropy bit count plus prefix and EOI cannot beat `maximum_size`.
    /// Outer `None` means invalid input; inner `None` is a proven size rejection.
    /// Byte stuffing can only make the final JPEG larger than this bound.
    pub fn plan_entropy_bounded(
        &self,
        histogram: &[[u32; 17]],
        maximum_size: Option<usize>,
    ) -> Option<Option<(Vec<u8>, Vec<u32>, u64)>> {
        if histogram.len() != self.components || self.point_transform != 0 {
            return None;
        }
        let mut states = [ComponentState::default(); 4];
        let mut total_bits = 0u64;
        // SOI + SOF3 + SOS and each component's DHT marker/header. Each used
        // category contributes one additional DHT symbol byte.
        let mut prefix_size = 20 + self.components * 26;
        for (state, hist) in states.iter_mut().zip(histogram) {
            if hist.iter().map(|&n| u64::from(n)).sum::<u64>() != (self.width * self.height) as u64
            {
                return None;
            }
            state.histogram = hist.map(|n| n as usize);
            self.build_hufftable(state);
            for (category, code) in state.hufftable.iter().enumerate() {
                prefix_size += usize::from(!code.is_empty());
                total_bits += u64::from(hist[category]) * (code.len() + (category & 15)) as u64;
            }
        }
        if maximum_size.is_some_and(|maximum| {
            (prefix_size as u64 + total_bits.div_ceil(8) + 2) >= maximum as u64
        }) {
            return Some(None);
        }
        let mut codes = Vec::with_capacity(self.components * 17);
        for state in states.iter().take(self.components) {
            for code in &state.hufftable {
                codes.push(((code.len() as u32) << 16) | u32::from(code.get_lsb()));
            }
        }
        let mut prefix = Vec::with_capacity(prefix_size);
        self.write_header(&states, &mut prefix);
        debug_assert_eq!(prefix.len(), prefix_size);
        Some(Some((prefix, codes, total_bits)))
    }

    /// Scan frequency for Huff table
    fn scan_frequency(&self, image: &[u16]) -> ([ComponentState; 4], Vec<i16>) {
        let mut comp_state = [ComponentState::default(); 4];
        let mut cache = vec![0; self.width * self.height * self.components];

        let rowsize = self.width * self.components;
        let linesize = (self.width + self.padding) * self.components;
        let mut row_prev = &image[0..];
        let mut row_curr = &image[0..];
        let mut diffs = vec![0_i16; linesize];

        macro_rules! match_predictor {
            ($comp:expr, $pred:expr) => {
                match $pred {
                    Predictor::P1 => ljpeg92_diff::<$comp, 1>(
                        row_prev,
                        row_curr,
                        &mut diffs,
                        linesize,
                        self.point_transform,
                        self.bitdepth,
                    ),
                    Predictor::P2 => ljpeg92_diff::<$comp, 2>(
                        row_prev,
                        row_curr,
                        &mut diffs,
                        linesize,
                        self.point_transform,
                        self.bitdepth,
                    ),
                    Predictor::P3 => ljpeg92_diff::<$comp, 3>(
                        row_prev,
                        row_curr,
                        &mut diffs,
                        linesize,
                        self.point_transform,
                        self.bitdepth,
                    ),
                    Predictor::P4 => ljpeg92_diff::<$comp, 4>(
                        row_prev,
                        row_curr,
                        &mut diffs,
                        linesize,
                        self.point_transform,
                        self.bitdepth,
                    ),
                    Predictor::P5 => ljpeg92_diff::<$comp, 5>(
                        row_prev,
                        row_curr,
                        &mut diffs,
                        linesize,
                        self.point_transform,
                        self.bitdepth,
                    ),
                    Predictor::P6 => ljpeg92_diff::<$comp, 6>(
                        row_prev,
                        row_curr,
                        &mut diffs,
                        linesize,
                        self.point_transform,
                        self.bitdepth,
                    ),
                    Predictor::P7 => ljpeg92_diff::<$comp, 7>(
                        row_prev,
                        row_curr,
                        &mut diffs,
                        linesize,
                        self.point_transform,
                        self.bitdepth,
                    ),
                }
            };
        }

        for row in 0..self.height {
            match self.components {
                1 => match_predictor!(1, self.predictor),
                2 => match_predictor!(2, self.predictor),
                3 => match_predictor!(3, self.predictor),
                4 => match_predictor!(4, self.predictor),
                _ => unreachable!(),
            }
            // Only copy rowsize values and ignore padding.
            cache[row * rowsize..row * rowsize + rowsize].copy_from_slice(&diffs[..rowsize]);

            if self.components == 2 {
                for pair in diffs[..rowsize].chunks_exact(2) {
                    comp_state[0].histogram[lookup_ssss(pair[0]) as usize] += 1;
                    comp_state[1].histogram[lookup_ssss(pair[1]) as usize] += 1;
                }
            } else {
                for (i, diff) in diffs.iter().take(rowsize).enumerate() {
                    let comp = i % self.components;
                    comp_state[comp].histogram[lookup_ssss(*diff) as usize] += 1;
                }
            }

            row_prev = row_curr;
            row_curr = &row_curr[linesize..];
        }

        (comp_state, cache)
    }

    #[inline]
    fn build_hufftable(&self, comp: &mut ComponentState) {
        let huffgen = HuffTableBuilder::new(comp.histogram);
        let table = huffgen.build();
        comp.hufftable = table;
    }

    /// Write JPEG header
    #[inline]
    fn write_header(&self, comp_state: &[ComponentState; 4], encoded: &mut Vec<u8>) {
        write_marker(encoded, Marker::SOI);
        write_marker(encoded, Marker::SOF3);

        // Write SOF
        write_u16(encoded, 2 + 6 + self.components as u16 * 3); // Lf, frame header length
        encoded.push(self.bitdepth); // Sample precision P
        write_u16(encoded, self.height as u16);
        write_u16(encoded, self.width as u16);

        encoded.push(self.components as u8); // Components Nf
        for c in 0..self.components {
            encoded.push(c as u8); // Component ID
            encoded.push(0x11); // H_i / V_i, Sampling factor 0001 0001
            encoded.push(0); // Quantisation table Tq (not used for lossless)
        }

        for (i, comp) in comp_state.iter().enumerate().take(self.components) {
            // Write HUFF
            write_marker(encoded, Marker::DHT);

            let bit_sum: u16 = comp.hufftable.iter().filter(|e| !e.is_empty()).count() as u16;

            write_u16(encoded, 2 + (1 + 16) + bit_sum); // Lf, frame header length
            encoded.push(i as u8); // Table ID

            // Write for each of the 16 possible code lengths how many codes
            // exists with the correspoding length.
            for bit_len in 1..=16 {
                let count = comp
                    .hufftable
                    .iter()
                    .filter(|entry| entry.len() == bit_len)
                    .count();
                encoded.push(count as u8);
            }

            // At most 17 symbols: order them on the stack once instead of
            // allocating and sorting a separate vector for each code length.
            let mut symbols = [(0u8, BitArray16::default()); 17];
            let mut used = 0;
            for (ssss, &code) in comp.hufftable.iter().enumerate() {
                if !code.is_empty() {
                    symbols[used] = (ssss as u8, code);
                    used += 1;
                }
            }
            symbols[..used].sort_unstable_by_key(|&(_, code)| (code.len(), code.storage));
            encoded.extend(symbols[..used].iter().map(|&(ssss, _)| ssss));
        }

        // Write SCAN
        write_marker(encoded, Marker::SOS);
        write_u16(encoded, 0x0006 + (self.components as u16 * 2)); // Ls, scan header length
        encoded.push(self.components as u8); // Ns, Component count
        for c in 0..self.components {
            encoded.push(c as u8); // Cs_i, Component selector
            encoded.push((c as u8) << 4); // Td, Ta, DC/AC entropy table selector
        }
        encoded.push(self.predictor as u8); // Ss, Predictor for lossless
        encoded.push(0); // Se, ignored for lossless
        debug_assert!(self.point_transform <= 15);
        encoded.push(self.point_transform & 0xF); // Ah=0, Al=Point transform
    }

    /// Write JPEG post
    #[inline]
    fn write_post(&self, encoded: &mut Vec<u8>) {
        write_marker(encoded, Marker::EOI);
    }

    /// Write JPEG body
    #[inline]
    fn write_body(&self, comp_state: &[ComponentState; 4], cache: &[i16], encoded: &mut Vec<u8>) {
        let mut bitstream = BitstreamJPEG::new(encoded);
        #[inline]
        fn write_sample(bitstream: &mut BitstreamJPEG<'_>, state: &ComponentState, diff: i16) {
            let ssss = lookup_ssss(diff);
            let enc = state.hufftable[ssss as usize];
            let (bits, value) = (enc.len(), enc.get_lsb() as u64);
            debug_assert!(bits > 0);

            // If the number of bits is 16, there is only one possible difference
            // value (-32786), so the lossless JPEG spec says not to output anything
            // in that case.  So we only need to output the diference value if
            // the number of bits is between 1 and 15. This also writes nothing
            // for ssss==0.
            debug_assert!(ssss <= 16);
            if (ssss & 15) != 0 {
                // sign encoding
                let diff = if diff < 0 {
                    diff as i32 - 1
                } else {
                    diff as i32
                };
                let extra = ssss as usize;
                let amplitude = (diff & (0x0FFFF >> (16 - ssss))) as u64;
                bitstream.write(bits + extra, (value << extra) | amplitude);
            } else {
                bitstream.write(bits, value);
            }
        }
        if self.components == 2 {
            for pair in cache.chunks_exact(2) {
                write_sample(&mut bitstream, &comp_state[0], pair[0]);
                write_sample(&mut bitstream, &comp_state[1], pair[1]);
            }
        } else {
            for (i, &diff) in cache.iter().enumerate() {
                write_sample(&mut bitstream, &comp_state[i % self.components], diff);
            }
        }
        // Flush the final bits
        bitstream.flush();
    }
}

/// Calculate the difference value between a sample and the predictor
/// value. This function is optimized for one and two component input
/// as this the case for most image data.
/// `linesize` is the count of values including padding data at the end
#[allow(clippy::needless_range_loop)]
fn ljpeg92_diff<const NCOMP: usize, const PX: u8>(
    row_prev: &[u16],  // Previous row (for index 0 it's the same reference as row_curr)
    row_curr: &[u16],  // Current row
    diffs: &mut [i16], // Output buffer for difference values
    linesize: usize,   // Count of values including padding data at the end
    point_transform: u8, // Point transform
    bitdepth: u8,      // Bit depth
) {
    debug_assert_eq!(linesize % NCOMP, 0);
    let pixels = linesize / NCOMP; // How many pixels are in the line
    let samplecnt = pixels * NCOMP;
    let row_prev = &row_prev[..samplecnt]; // Hint for compiler: each slice has identical bounds (SIMD).
    let row_curr = &row_curr[..samplecnt]; // Slice range must be identical for SIMD optimizations.
    let diffs = &mut diffs[..samplecnt];

    // In debug, check that no sample overflows max_value
    #[cfg(debug_assertions)]
    row_curr.iter().for_each(|sample| {
        let max_value = ((1u32 << (bitdepth - point_transform)) - 1) as u16;
        if (*sample >> point_transform) > max_value {
            panic!(
                "Sample overflow, sample is {:#x} but max value is {:#x}",
                sample, max_value
            );
        }
    });

    // First row always use predictor 1
    // Set first column to initial values
    if row_curr.as_ptr() == row_prev.as_ptr() {
        for comp in 0..NCOMP {
            let px = (1u16 << (bitdepth - point_transform - 1)) as i32;
            let sample = pred_x::<NCOMP>(row_prev, row_curr, comp, point_transform);
            diffs[comp] = (sample - px) as i16;
        }
        // Process remaining pixels
        for idx in NCOMP..samplecnt {
            let px = pred_a::<NCOMP>(row_prev, row_curr, idx, point_transform);
            let sample = pred_x::<NCOMP>(row_prev, row_curr, idx, point_transform);
            diffs[idx] = (sample - px) as i16;
        }
    } else {
        // Not on first row, the first column uses predictor 2
        for comp in 0..NCOMP {
            let px = pred_b::<NCOMP>(row_prev, row_curr, comp, point_transform);
            let sample = pred_x::<NCOMP>(row_prev, row_curr, comp, point_transform);
            diffs[comp] = (sample - px) as i16;
        }
        let predictor = match PX {
            1 => pred_a::<NCOMP>,
            2 => pred_b::<NCOMP>,
            3 => pred_c::<NCOMP>,
            4 => |prev: &[u16], curr: &[u16], idx: usize, pt: u8| -> i32 {
                let ra = pred_a::<NCOMP>(prev, curr, idx, pt);
                let rb = pred_b::<NCOMP>(prev, curr, idx, pt);
                let rc = pred_c::<NCOMP>(prev, curr, idx, pt);
                ra + rb - rc
            },
            5 => |prev: &[u16], curr: &[u16], idx: usize, pt: u8| -> i32 {
                let ra = pred_a::<NCOMP>(prev, curr, idx, pt);
                let rb = pred_b::<NCOMP>(prev, curr, idx, pt);
                let rc = pred_c::<NCOMP>(prev, curr, idx, pt);
                ra + ((rb - rc) >> 1) // Adobe DNG SDK uses int32 and shifts, so we will do, too.
            },
            6 => |prev: &[u16], curr: &[u16], idx: usize, pt: u8| -> i32 {
                let ra = pred_a::<NCOMP>(prev, curr, idx, pt);
                let rb = pred_b::<NCOMP>(prev, curr, idx, pt);
                let rc = pred_c::<NCOMP>(prev, curr, idx, pt);
                rb + ((ra - rc) >> 1) // Adobe DNG SDK uses int32 and shifts, so we will do, too.
            },
            7 => |prev: &[u16], curr: &[u16], idx: usize, pt: u8| -> i32 {
                let ra = pred_a::<NCOMP>(prev, curr, idx, pt);
                let rb = pred_b::<NCOMP>(prev, curr, idx, pt);
                (ra + rb) >> 1 // Adobe DNG SDK uses int32 and shifts, so we will do, too.
            },
            // Other predictors are not supported and catched in previous code path.
            _ => unreachable!(),
        };
        // First pixel is processed, now process the remaining pixels.
        for idx in NCOMP..samplecnt {
            let px = predictor(row_prev, row_curr, idx, point_transform);
            let sample = pred_x::<NCOMP>(row_prev, row_curr, idx, point_transform);
            // The difference between the prediction value and
            // the input is calculated modulo 2^16. So we can cast i32
            // down to i16 to truncate the upper 16 bits (H.1.2.1, last paragraph).
            diffs[idx] = (sample - px) as i16;
        }
    }
}

/// Get Rx by current line
/// Figure H.1
/// | c | b |
/// | a | x |
#[inline(always)]
fn pred_x<const NCOMP: usize>(_prev: &[u16], curr: &[u16], idx: usize, point_transform: u8) -> i32 {
    unsafe { (curr.get_unchecked(idx) >> point_transform) as i32 }
}

/// Get Ra predictor by current line
/// Figure H.1
/// | c | b |
/// | a | x |
#[inline(always)]
fn pred_a<const NCOMP: usize>(_prev: &[u16], curr: &[u16], idx: usize, point_transform: u8) -> i32 {
    unsafe { (curr.get_unchecked(idx - NCOMP) >> point_transform) as i32 }
}

/// Get Rb predictor by previous line
/// Figure H.1
/// | c | b |
/// | a | x |
#[inline(always)]
fn pred_b<const NCOMP: usize>(prev: &[u16], _curr: &[u16], idx: usize, point_transform: u8) -> i32 {
    unsafe { (prev.get_unchecked(idx) >> point_transform) as i32 }
}

/// Get Rc predictor by previous line
/// Figure H.1
/// | c | b |
/// | a | x |
#[inline(always)]
fn pred_c<const NCOMP: usize>(prev: &[u16], _curr: &[u16], idx: usize, point_transform: u8) -> i32 {
    unsafe { (prev.get_unchecked(idx - NCOMP) >> point_transform) as i32 }
}

#[inline(always)]
fn write_u16(buf: &mut Vec<u8>, n: u16) {
    buf.extend_from_slice(&n.to_be_bytes());
}

#[inline(always)]
fn write_marker(buf: &mut Vec<u8>, m: Marker) {
    buf.extend_from_slice(&[0xff, m as u8]);
}

#[derive(Debug, Clone, Copy, Default, Eq, Ord, PartialEq, PartialOrd)]
struct BitArray16 {
    storage: u16,
    nbits: usize,
}

impl BitArray16 {
    fn len(&self) -> usize {
        self.nbits
    }

    fn is_empty(&self) -> bool {
        self.nbits == 0
    }

    fn get_lsb(&self) -> u16 {
        self.storage >> (16 - self.nbits)
    }

    fn from_lsb(nbits: usize, value: u16) -> Self {
        Self {
            storage: value << (16 - nbits),
            nbits,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{BitstreamJPEG, HuffTableBuilder};
    use alloc::vec::Vec;

    #[test]
    fn bounded_plan_and_stack_header_match_exhaustive_serialization() {
        use super::{ComponentState, Encoder, BitArray16};
        use crate::{Bitdepth, Components, Predictor};
        let mut seed = 0x123456789abcdefu64;
        for components in [Components::C1, Components::C2, Components::C3, Components::C4] {
            for case in 0..256 {
                let mut histogram = alloc::vec![[0u32; 17]; components as usize];
                for hist in &mut histogram {
                    for _ in 0..256 {
                        seed ^= seed << 13;
                        seed ^= seed >> 7;
                        seed ^= seed << 17;
                        let category = match case % 4 {
                            0 => 0,
                            1 => seed as usize % 2,
                            _ => seed as usize % 17,
                        };
                        hist[category] += 1;
                    }
                }
                let encoder = Encoder::new(16,16,components,Bitdepth::B16,Predictor::P7,0,0);
                let planned = encoder.plan_entropy(&histogram).unwrap();
                let mut states = [ComponentState::default(); 4];
                for (state, hist) in states.iter_mut().zip(&histogram) {
                    state.histogram = hist.map(|n| n as usize);
                    encoder.build_hufftable(state);
                }
                let mut old_prefix = Vec::new();
                encoder.write_header(&states,&mut old_prefix);
                // Locate and independently regenerate each DHT using the old
                // per-length collect/sort ordering. The rest of the JPEG prefix
                // is unchanged by this optimization.
                let mut at = 2;
                while at < old_prefix.len() {
                    let marker = old_prefix[at+1];
                    let length = u16::from_be_bytes([old_prefix[at+2],old_prefix[at+3]]) as usize;
                    if marker == 196 {
                        let component = old_prefix[at+4] as usize;
                        let mut symbols = Vec::new();
                        for bits in 1..=16 {
                            let mut codes: Vec<(usize,BitArray16)> = states[component].hufftable.iter()
                                .copied().enumerate().filter(|(_,code)|code.len()==bits).collect();
                            codes.sort_by(|a,b| a.1.cmp(&b.1));
                            symbols.extend(codes.iter().map(|&(category,_)|category as u8));
                        }
                        assert_eq!(&old_prefix[at+21..at+2+length],&symbols);
                    }
                    at += 2+length;
                }
                assert_eq!(planned.0,old_prefix);
                let bound = planned.0.len() + planned.2.div_ceil(8) as usize + 2;
                for maximum in [0,bound.saturating_sub(1),bound,bound+1,usize::MAX] {
                    let actual = encoder.plan_entropy_bounded(&histogram,Some(maximum)).unwrap();
                    if maximum <= bound {assert!(actual.is_none());}
                    else {assert_eq!(actual.as_ref(),Some(&planned));}
                }
            }
        }
        let encoder = Encoder::new(16,16,Components::C2,Bitdepth::B16,Predictor::P7,0,0);
        assert!(encoder.plan_entropy_bounded(&[[0;17];2],Some(0)).is_none());
        assert!(encoder.plan_entropy_bounded(&[[256;17]],Some(0)).is_none());
    }

    #[test]
    fn huffman_uses_one_count_pseudo_symbol_and_reserves_all_ones() {
        let mut hist = [0; 17];
        hist[..5].copy_from_slice(&[4000, 3000, 2000, 900, 100]);
        let table = HuffTableBuilder::new(hist).build();
        let cost: usize = hist
            .iter()
            .zip(table)
            .map(|(&n, code)| n * code.len())
            .sum();
        assert_eq!(cost, 20100);
        // Exercise the JPEG 16-bit code-length limit with a skewed distribution.
        let mut hist = [1usize; 17];
        for i in 2..17 {
            hist[i] = hist[i - 1] + hist[i - 2];
        }
        let table = HuffTableBuilder::new(hist).build();
        for (i, a) in table.iter().enumerate() {
            assert!(a.len() > 0 && a.len() <= 16);
            assert_ne!(a.get_lsb() as u32, (1u32 << a.len()) - 1);
            for (j, b) in table.iter().enumerate() {
                if i != j && a.len() <= b.len() {
                    assert_ne!(a.get_lsb(), b.get_lsb() >> (b.len() - a.len()));
                }
            }
        }
    }

    #[test]
    fn accumulator_matches_scalar_bit_writer() {
        let mut actual = Vec::new();
        let mut expected = Vec::new();
        let mut next = 0u8;
        let mut used = 0;
        let mut seed = 0x123456789abcdefu64;
        let mut writer = BitstreamJPEG::new(&mut actual);
        for i in 0..20000 {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            let bits = i % 32;
            let value = if i % 5 == 0 { u64::MAX } else { seed };
            writer.write(bits, value);
            for b in (0..bits).rev() {
                next = (next << 1) | ((value >> b) & 1) as u8;
                used += 1;
                if used == 8 {
                    expected.push(next);
                    if next == 255 {
                        expected.push(0);
                    }
                    used = 0;
                    next = 0;
                }
            }
            if i % 97 == 0 {
                writer.flush();
                if used > 0 {
                    next <<= 8 - used;
                    expected.push(next);
                    if next == 255 {
                        expected.push(0);
                    }
                    used = 0;
                    next = 0;
                }
            }
        }
        writer.flush();
        if used > 0 {
            next <<= 8 - used;
            expected.push(next);
            if next == 255 {
                expected.push(0);
            }
        }
        assert_eq!(actual, expected);
    }

    #[test]
    fn bitstream_test() {
        let mut buf = Vec::new();
        let mut bs = BitstreamJPEG::new(&mut buf);
        bs.write(1, 0b1);
        bs.flush();
        bs.write(1, 0b0);
        bs.write(3, 0b101);
        bs.write(4, 0b11111101);
        bs.write(2, 0b101);
        bs.flush();
        bs.write(16, 0b1111111111111111);
        bs.flush();
        bs.write(16, 0b0);
        bs.flush();
        assert_eq!(buf[0], 0b10000000);
        assert_eq!(buf[1], 0b01011101);
        assert_eq!(buf[2], 0b01000000);
        assert_eq!(buf[3], 0xFF);
        assert_eq!(buf[4], 0x00); // stuffing
        assert_eq!(buf[5], 0xFF);
        assert_eq!(buf[6], 0x00); // stuffing
        assert_eq!(buf[7], 0x00);
    }
}
