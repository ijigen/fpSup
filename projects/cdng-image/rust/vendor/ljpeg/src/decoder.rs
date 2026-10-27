use crate::huffman::HuffTable;
use crate::pumps::{BitPumpJPEG, BitPumpMSB32, ByteStream};
use crate::Marker;

use alloc::{vec, vec::Vec};
use core::error::Error;
use core::fmt::{self, Display, Formatter};

/// Decoder of the lossless JPEG.
#[derive(Debug)]
pub struct Decoder<'a> {
    buffer: &'a [u8],
    sof: SOFInfo,
    predictor: usize,
    point_transform: usize,
    dhts: [HuffTable; 4],
    sony: bool,
    // Joint Huffman residuals for the ordinary two-component Bayer path.
    paircache: Vec<u64>,
}

#[derive(Debug, Clone)]
struct SOFInfo {
    width: usize,
    height: usize,
    cps: usize,
    bitdepth: usize,
    components: [JpegComponentInfo; 4],
    csfix: bool,
}

#[derive(Debug, Copy, Clone, Default)]
struct JpegComponentInfo {
    // These values are fixed over the whole image, read from the SOF marker.
    id: usize, // identifier for this component (0..255)

    // Huffman table selector (0..3). The value may vary between scans.
    // It is read from the SOS marker.
    dc_tbl_num: usize,
    super_h: usize, // Horizontal Supersampling
    super_v: usize, // Vertical Supersampling
}

/// The ways how the decoder may fail.
#[derive(Debug)]
pub enum DecoderError {
    /// Image did not start with the SOI marker.
    NoSoiStart,
    /// The image bitdepth outside of the allowed range `2..=16`.
    InvalidPrecision(usize),
    /// The number of componets outside of the allowed range `1..=4`.
    InvalidComponents(usize),
    /// The component selector outside allowed range.
    InvalidComponentSelector(usize),
    /// The table selector outside allowed range.
    InvalidTableSelector(usize),
    /// EOI marker was found before SOS marker.
    EoiBeforeSos,
    /// DQT found, which has no effect in lossless file.
    DqtFound,
    /// A marker was expected, but not found.
    ExpectedMarkerNotFound,
    /// The table class is not supported. Only `0` is supported.
    UnsupportedTableClass(usize),
    /// The table class is not supported. Only `0-3` are supported.
    UnsupportedTableId(usize),
    /// The predictor is not supported. Only `1-8` are supported.
    UnsupportedPredictor(usize),
    /// The interleave setting is not supported.
    UnsupportedInterleave(usize, usize),
    /// The Huffman table is not valid.
    InvalidTable,
    /// SOS block before SOF block
    SosBeforeSof,
    /// The SOF header had different size than stated.
    HeaderSizeMismatch,
    /// The number of components in the SOS header is different than in the SOF header.
    SosComponentMismatch,
    /// The buffer provided for decoding is too small.
    SmallBuffer,
}

type Result<T> = core::result::Result<T, DecoderError>;

impl Decoder<'_> {
    /// Create a new decoder from the source.
    #[inline]
    pub fn new(src: &[u8]) -> Result<Decoder> {
        Decoder::new_full(src, false, false)
    }

    /// Create a new decoder with the following options:
    /// - `csfix` fixes a frong placement of component selector byte in some cameras
    /// - `sony` make the decoder handle a special YUV 4:2:0 encoding used in Sony cameras
    #[inline]
    pub fn new_full(src: &[u8], csfix: bool, sony: bool) -> Result<Decoder> {
        let mut input = ByteStream::new(src);
        if get_next_marker(&mut input, false)? != Marker::SOI as u8 {
            return Err(DecoderError::NoSoiStart);
        }

        let mut sof = SOFInfo::empty(csfix);
        let mut dht_init = [false; 4];
        let mut dht_bits = [[0_u32; 17]; 4];
        let mut dht_huffval = [[0_u32; 256]; 4];
        let pred;
        let pt;
        loop {
            let marker = get_next_marker(&mut input, true)?;
            if marker == Marker::SOF3 as u8 {
                // Start of the frame, giving us the basic info
                sof.parse_sof(&mut input)?;
            } else if marker == Marker::DHT as u8 {
                // Huffman table settings
                parse_dht(&mut input, &mut dht_init, &mut dht_bits, &mut dht_huffval)?;
            } else if marker == Marker::SOS as u8 {
                // Start of the actual stream, we can decode after this
                let (a, b) = sof.parse_sos(&mut input)?;
                pred = a;
                pt = b;
                break;
            } else if marker == Marker::EOI as u8 {
                // Should never be reached as we stop at SOS
                return Err(DecoderError::EoiBeforeSos);
            } else if marker == Marker::DQT as u8 {
                return Err(DecoderError::DqtFound);
            }
        }

        let mut dhts = [
            HuffTable::empty(),
            HuffTable::empty(),
            HuffTable::empty(),
            HuffTable::empty(),
        ];
        for i in 0..4 {
            if dht_init[i] {
                if let Some(previous) = (0..i).find(|&j| dht_init[j]
                    && dht_bits[j] == dht_bits[i] && dht_huffval[j] == dht_huffval[i]) {
                    for component in &mut sof.components {
                        if component.dc_tbl_num == i { component.dc_tbl_num = previous; }
                    }
                } else {
                    dhts[i] = HuffTable::new(dht_bits[i], dht_huffval[i]);
                }
            }
        }

        let paircache = if sof.cps == 2 && pred != 8
            && sof.components[0].super_h == 1 && sof.components[0].super_v == 1 {
            dhts[sof.components[0].dc_tbl_num].pair_cache(&dhts[sof.components[1].dc_tbl_num])
        } else { Vec::new() };
        let offset = input.get_pos();
        Ok(Decoder {
            buffer: &src[offset..],
            sof,
            predictor: pred,
            point_transform: pt,
            dhts,
            sony,
            paircache,
        })
    }

    /// Decode the image into a newly allocated buffer.
    #[inline]
    pub fn decode(&self) -> Result<Vec<u16>> {
        let mut buffer = vec![0; self.width() * self.height() * self.components()];
        self.decode_to_buffer(&mut buffer, self.width(), self.height())?;
        Ok(buffer)
    }

    /// Decodes the image into the provided buffer.
    /// `width` and `height` must be smaller than the image width and height.
    /// The buffer must have enough capacity to store the image, i.e. `ncomp * width * height`,
    /// where `ncomp` is the number of components of the image.
    #[inline]
    pub fn decode_to_buffer(&self, out: &mut [u16], width: usize, height: usize) -> Result<()> {
        if self.sof.components[0].super_h == 2 && self.sof.components[0].super_v == 2 {
            if self.sony {
                self.decode_sony_ljpeg_420(out, width, height)
            } else {
                self.decode_ljpeg_420(out, width, height)
            }
        } else if self.sof.components[0].super_h == 2 && self.sof.components[0].super_v == 1 {
            self.decode_ljpeg_422(out, width, height)
        } else if self.sof.components[0].super_h == 1 && self.sof.components[0].super_v == 1 {
            match self.predictor {
                1 => self.decode_ljpeg::<1>(out, width, height),
                2 => self.decode_ljpeg::<2>(out, width, height),
                3 => self.decode_ljpeg::<3>(out, width, height),
                4 => self.decode_ljpeg::<4>(out, width, height),
                5 => self.decode_ljpeg::<5>(out, width, height),
                6 => self.decode_ljpeg::<6>(out, width, height),
                7 => self.decode_ljpeg::<7>(out, width, height),
                8 => self.decode_hasselblad(out, width),
                p => Err(DecoderError::UnsupportedPredictor(p)),
            }
        } else {
            Err(DecoderError::UnsupportedInterleave(
                self.sof.components[0].super_h,
                self.sof.components[0].super_v,
            ))
        }
    }

    #[allow(clippy::let_and_return)]
    #[allow(clippy::needless_range_loop)]
    fn decode_ljpeg<const PREDICTOR: u8>(
        &self,
        out: &mut [u16],
        width: usize,
        height: usize,
    ) -> Result<()> {
        // Bayer DNGs use two components. Specialize that hot loop so the
        // compiler can unroll it and keep both table references in registers.
        if self.components() == 2 {
            self.decode_ljpeg_components::<PREDICTOR, 2>(out, width, height)
        } else {
            self.decode_ljpeg_components::<PREDICTOR, 0>(out, width, height)
        }
    }

    fn decode_ljpeg_components<const PREDICTOR: u8, const COMPONENTS: usize>(
        &self,
        out: &mut [u16],
        width: usize,
        height: usize,
    ) -> Result<()> {
        let ncomp: usize = if COMPONENTS == 0 {
            self.components()
        } else {
            COMPONENTS
        };
        if self.sof.width * ncomp < width
            || self.sof.height < height
            || out.len() < width * height
            || ncomp > 4
        {
            return Err(DecoderError::SmallBuffer);
        }

        let htables = self.sof.components.map(|comp| &self.dhts[comp.dc_tbl_num]);
        let mut pump = BitPumpJPEG::new(self.buffer);
        let base_prediction = 1 << (self.sof.bitdepth - self.point_transform - 1);

        let skip_x = self.sof.width - width;
        let width = width * ncomp;

        // initialize first pixel components
        for c in 0..ncomp {
            out[c] = (base_prediction + htables[c].huff_decode(&mut pump)) as u16;
        }

        for col in (ncomp..width).step_by(ncomp) {
            for c in 0..ncomp {
                let a = out[(col - ncomp) + c] as i32;
                let diff = htables[c].huff_decode(&mut pump);
                out[col + c] = (a + diff) as u16;
            }
        }
        for _ in 0..skip_x {
            for c in 0..ncomp {
                // Skip extra encoded differences if the ljpeg frame is wider than the output
                htables[c].huff_decode(&mut pump);
            }
        }

        for row in 1..height {
            for c in 0..ncomp {
                let a = out[(row - 1) * width + c] as i32;
                let diff = htables[c].huff_decode(&mut pump);
                out[row * width + c] = (a + diff) as u16;
            }

            for col in (ncomp..width).step_by(ncomp) {
                let pair = if COMPONENTS == 2 {
                    let (a, b) = htables[0].huff_decode_pair(htables[1], &self.paircache, &mut pump);
                    [a, b]
                } else { [0, 0] };
                for c in 0..ncomp {
                    let p: i32 = match PREDICTOR {
                        1 => {
                            let a = out[row * width + (col - ncomp) + c] as i32;
                            a
                        }
                        2 => {
                            let b = out[(row - 1) * width + col + c] as i32;
                            b
                        }
                        3 => {
                            let c = out[(row - 1) * width + (col - ncomp) + c] as i32;
                            c
                        }
                        4 => {
                            let a = out[row * width + (col - ncomp) + c] as i32;
                            let b = out[(row - 1) * width + col + c] as i32;
                            let c = out[(row - 1) * width + (col - ncomp) + c] as i32;
                            a + b - c
                        }
                        5 => {
                            let a = out[row * width + (col - ncomp) + c] as i32;
                            let b = out[(row - 1) * width + col + c] as i32;
                            let c = out[(row - 1) * width + (col - ncomp) + c] as i32;
                            a + ((b - c) >> 1)
                        }
                        6 => {
                            let a = out[row * width + (col - ncomp) + c] as i32;
                            let b = out[(row - 1) * width + col + c] as i32;
                            let c = out[(row - 1) * width + (col - ncomp) + c] as i32;
                            b + ((a - c) >> 1)
                        }
                        7 => {
                            let a = out[row * width + (col - ncomp) + c] as i32;
                            let b = out[(row - 1) * width + col + c] as i32;
                            (a + b) >> 1 // Adobe DNG SDK uses int32 and shifts, so we will do, too.
                        }
                        p => {
                            return Err(DecoderError::UnsupportedPredictor(p as usize));
                        }
                    };

                    let diff = if COMPONENTS == 2 { pair[c] } else { htables[c].huff_decode(&mut pump) };
                    out[row * width + col + c] = (p + diff) as u16;
                }
            }
            for _ in 0..skip_x {
                for c in 0..ncomp {
                    // Skip extra encoded differences if the ljpeg frame is wider than the output
                    htables[c].huff_decode(&mut pump);
                }
            }
        }

        Ok(())
    }

    fn decode_sony_ljpeg_420(&self, out: &mut [u16], width: usize, height: usize) -> Result<()> {
        if self.sof.width * 3 != width || self.sof.height != height {
            return Err(DecoderError::SmallBuffer);
        }

        debug_assert_eq!(width % 2, 0);
        debug_assert_eq!(width % 6, 0); // Ensure we have enough samples for .step_by(6)
        debug_assert_eq!(height % 2, 0);

        let htable1 = &self.dhts[self.sof.components[0].dc_tbl_num];
        let htable2 = &self.dhts[self.sof.components[1].dc_tbl_num];
        let htable3 = &self.dhts[self.sof.components[2].dc_tbl_num];
        let mut pump = BitPumpJPEG::new(self.buffer);

        let base_prediction = 1 << (self.sof.bitdepth - self.point_transform - 1);

        let y1 = base_prediction + htable1.huff_decode(&mut pump);
        let y2 = y1 + htable1.huff_decode(&mut pump);
        let y3 = y1 + htable1.huff_decode(&mut pump); // y1 is sample above current row, column 0
        let y4 = y3 + htable1.huff_decode(&mut pump);

        let cb = base_prediction + htable2.huff_decode(&mut pump);
        let cr = base_prediction + htable3.huff_decode(&mut pump);

        set_yuv_420(out, 0, 0, width, y1, y2, y3, y4, cb, cr);

        // first column|second column
        // | Y, Cb, Cr | py1, pcb, pcr | y1, cb, cr | y2, cb, cr |  <- first row
        // | Y, Cb, Cr | py3, pcb, pcr | y3, cb, cr | y4, cb, cr |  <- second row
        for row in (0..height).step_by(2) {
            let startcol = if row == 0 { 6 } else { 0 };
            for col in (startcol..width).step_by(6) {
                // Get previous values (for adding huff differnce)
                let (py1, py3, pcb, pcr) = if col == 0 {
                    // This is possible broken 4:2:0 encoding by Sony, as the new row
                    // has to use the sample from the second-previous row instead of the
                    // first-previous row.
                    let pos = (row - 2) * width; // reference is previous block, first row, first column
                    (out[pos], 0, out[pos + 1], out[pos + 2]) // py3 is not required, instead py3 references to y1 on col == 0
                } else {
                    let pos1 = row * width + col - 3; // reference is current block, first row, second column
                    let pos3 = (row + 1) * width + col - 3; // reference current block, second row, second column
                    (out[pos1], out[pos3], out[pos1 + 1], out[pos1 + 2])
                };
                // Calculate 4 Y samples, 1 Cb sample, 1 Cr sample
                let y1 = (py1 as i32) + htable1.huff_decode(&mut pump);
                let y2 = y1 + htable1.huff_decode(&mut pump);
                let y3 = if col == 0 {
                    // y1 is sample above current row, column 0
                    y1 + htable1.huff_decode(&mut pump)
                } else {
                    // py3 is previous sample in same line
                    (py3 as i32) + htable1.huff_decode(&mut pump)
                };
                let y4 = y3 + htable1.huff_decode(&mut pump);

                // Cb and Cr components
                let cb = (pcb as i32) + htable2.huff_decode(&mut pump);
                let cr = (pcr as i32) + htable3.huff_decode(&mut pump);
                set_yuv_420(out, row, col, width, y1, y2, y3, y4, cb, cr);
            }
        }

        Ok(())
    }

    fn decode_ljpeg_420(&self, out: &mut [u16], width: usize, height: usize) -> Result<()> {
        if self.sof.width * 3 != width || self.sof.height != height {
            return Err(DecoderError::SmallBuffer);
        }

        debug_assert_eq!(width % 2, 0);
        debug_assert_eq!(width % 6, 0); // Ensure we have enough samples for .step_by(6)
        debug_assert_eq!(height % 2, 0);

        let htable1 = &self.dhts[self.sof.components[0].dc_tbl_num];
        let htable2 = &self.dhts[self.sof.components[1].dc_tbl_num];
        let htable3 = &self.dhts[self.sof.components[2].dc_tbl_num];
        let mut pump = BitPumpJPEG::new(self.buffer);

        let base_prediction = 1 << (self.sof.bitdepth - self.point_transform - 1);
        let y1 = base_prediction + htable1.huff_decode(&mut pump);
        let y2 = y1 + htable1.huff_decode(&mut pump);
        let y3 = y2 + htable1.huff_decode(&mut pump);
        let y4 = y3 + htable1.huff_decode(&mut pump);
        let cb = base_prediction + htable2.huff_decode(&mut pump);
        let cr = base_prediction + htable3.huff_decode(&mut pump);
        set_yuv_420(out, 0, 0, width, y1, y2, y3, y4, cb, cr);

        for row in (0..height).step_by(2) {
            let startcol = if row == 0 { 6 } else { 0 };
            for col in (startcol..width).step_by(6) {
                let pos = if col == 0 {
                    // At start of line predictor starts with first pixel of start of previous line
                    (row - 2) * width
                } else {
                    // All other cases use the last pixel in the same two lines
                    (row + 1) * width + col - 3
                };
                let (py, pcb, pcr) = (out[pos], out[pos + 1], out[pos + 2]);

                let y1 = (py as i32) + htable1.huff_decode(&mut pump);
                let y2 = y1 + htable1.huff_decode(&mut pump);
                let y3 = y2 + htable1.huff_decode(&mut pump);
                let y4 = y3 + htable1.huff_decode(&mut pump);
                let cb = (pcb as i32) + htable2.huff_decode(&mut pump);
                let cr = (pcr as i32) + htable3.huff_decode(&mut pump);
                set_yuv_420(out, row, col, width, y1, y2, y3, y4, cb, cr);
            }
        }

        Ok(())
    }

    fn decode_ljpeg_422(&self, out: &mut [u16], width: usize, height: usize) -> Result<()> {
        if self.sof.width * 3 != width || self.sof.height != height {
            return Err(DecoderError::SmallBuffer);
        }
        let htable1 = &self.dhts[self.sof.components[0].dc_tbl_num];
        let htable2 = &self.dhts[self.sof.components[1].dc_tbl_num];
        let htable3 = &self.dhts[self.sof.components[2].dc_tbl_num];
        let mut pump = BitPumpJPEG::new(self.buffer);

        let base_prediction = 1 << (self.sof.bitdepth - self.point_transform - 1);
        let y1 = base_prediction + htable1.huff_decode(&mut pump);
        let y2 = y1 + htable1.huff_decode(&mut pump);
        let cb = base_prediction + htable2.huff_decode(&mut pump);
        let cr = base_prediction + htable3.huff_decode(&mut pump);
        set_yuv_422(out, 0, 0, width, y1, y2, cb, cr);

        for row in 0..height {
            let startcol = if row == 0 { 6 } else { 0 };
            for col in (startcol..width).step_by(6) {
                let pos = if col == 0 {
                    // At start of line predictor starts with first pixel of start of previous line
                    (row - 1) * width
                } else {
                    // All other cases use the last pixel in the same two lines
                    row * width + col - 3
                };
                let (py, pcb, pcr) = (out[pos], out[pos + 1], out[pos + 2]);

                let y1 = (py as i32) + htable1.huff_decode(&mut pump);
                let y2 = y1 + htable1.huff_decode(&mut pump);
                let cb = (pcb as i32) + htable2.huff_decode(&mut pump);
                let cr = (pcr as i32) + htable3.huff_decode(&mut pump);

                set_yuv_422(out, row, col, width, y1, y2, cb, cr);
            }
        }

        Ok(())
    }

    fn decode_hasselblad(&self, out: &mut [u16], width: usize) -> Result<()> {
        // Pixels are packed two at a time, not like LJPEG:
        // [p1_length_as_huffman][p2_length_as_huffman][p0_diff_with_length][p1_diff_with_length]|NEXT PIXELS
        let mut pump = BitPumpMSB32::new(self.buffer);
        let htable = &self.dhts[self.sof.components[0].dc_tbl_num];

        for line in out.chunks_exact_mut(width) {
            let mut p1: i32 = 0x8000;
            let mut p2: i32 = 0x8000;
            for o in line.chunks_exact_mut(2) {
                let len1 = htable.huff_len(&mut pump);
                let len2 = htable.huff_len(&mut pump);
                p1 += htable.huff_diff(&mut pump, len1);
                p2 += htable.huff_diff(&mut pump, len2);
                o[0] = p1 as u16;
                o[1] = p2 as u16;
            }
        }

        Ok(())
    }

    /// Return the image width.
    #[inline]
    pub fn width(&self) -> usize {
        self.sof.width
    }

    /// Return the image height.
    #[inline]
    pub fn height(&self) -> usize {
        self.sof.height
    }

    /// Return the image vertical supersampling.
    #[inline]
    pub fn super_v(&self) -> usize {
        self.sof.components[0].super_v
    }

    /// Return the image horizontal supersampling.
    #[inline]
    pub fn super_h(&self) -> usize {
        self.sof.components[0].super_h
    }

    /// Return the number of image components.
    #[inline]
    pub fn components(&self) -> usize {
        self.sof.cps
    }

    /// Return the bitdepth of the image.
    #[inline]
    pub fn bitdepth(&self) -> usize {
        self.sof.bitdepth
    }

    /// Return the predictor used for encoding this image.
    #[inline]
    pub fn predictor(&self) -> usize {
        self.predictor
    }
}

impl SOFInfo {
    fn empty(csfix: bool) -> SOFInfo {
        SOFInfo {
            width: 0,
            height: 0,
            cps: 0,
            bitdepth: 0,
            components: Default::default(),
            csfix,
        }
    }

    fn parse_sof(&mut self, input: &mut ByteStream) -> Result<()> {
        let header_length = input.get_u16() as usize;
        self.bitdepth = input.get_u8() as usize;
        self.height = input.get_u16() as usize;
        self.width = input.get_u16() as usize;
        self.cps = input.get_u8() as usize;

        if self.bitdepth < 2 || self.bitdepth > 16 {
            return Err(DecoderError::InvalidPrecision(self.bitdepth));
        }
        if self.cps > 4 || self.cps < 1 {
            return Err(DecoderError::InvalidComponents(self.cps));
        }
        if header_length != 8 + self.cps * 3 {
            return Err(DecoderError::HeaderSizeMismatch);
        }

        for i in 0..self.cps {
            let id = input.get_u8() as usize;
            let subs = input.get_u8() as usize;
            input.get_u8(); // Skip info about quantized

            self.components[i] = JpegComponentInfo {
                id,
                //index: i,
                dc_tbl_num: 0,
                super_v: subs & 0xf,
                super_h: subs >> 4,
            };
        }
        Ok(())
    }

    fn parse_sos(&mut self, input: &mut ByteStream) -> Result<(usize, usize)> {
        if self.width == 0 {
            return Err(DecoderError::SosBeforeSof);
        }
        input.get_u16(); //skip header length
        let soscps = input.get_u8() as usize;
        if self.cps != soscps {
            return Err(DecoderError::SosComponentMismatch);
        }
        for cs in 0..self.cps {
            // At least some MOS cameras have this broken
            let readcs = input.get_u8() as usize;
            let cs = if self.csfix { cs } else { readcs };
            let component = match self.components.iter_mut().find(|&&mut c| c.id == cs) {
                Some(val) => val,
                None => return Err(DecoderError::InvalidComponentSelector(cs)),
            };
            let td = (input.get_u8() as usize) >> 4;
            if td > 3 {
                return Err(DecoderError::InvalidTableSelector(cs));
            }
            component.dc_tbl_num = td;
        }
        let pred = input.get_u8() as usize;
        input.get_u8(); // Se + Ah Not used in LJPEG
        let pt = (input.get_u8() as usize) & 0xf; // Point Transform
        Ok((pred, pt))
    }
}

fn get_next_marker(input: &mut ByteStream, allowskip: bool) -> Result<u8> {
    if !allowskip {
        if input.get_u8() != 0xff {
            return Err(DecoderError::ExpectedMarkerNotFound);
        }
        let mark = input.get_u8();
        if mark == Marker::Stuff as u8 || mark == Marker::Fill as u8 {
            return Err(DecoderError::ExpectedMarkerNotFound);
        }
        return Ok(mark);
    }
    input
        .skip_to_marker()
        .ok_or(DecoderError::ExpectedMarkerNotFound)?;

    Ok(input.get_u8())
}

fn parse_dht(
    input: &mut ByteStream,
    init: &mut [bool; 4],
    bits: &mut [[u32; 17]; 4],
    huffval: &mut [[u32; 256]; 4],
) -> Result<()> {
    let mut length = (input.get_u16() as usize) - 2;

    while length > 0 {
        let b = input.get_u8() as usize;
        let tc = b >> 4;
        let th = b & 0xf;

        if tc != 0 {
            return Err(DecoderError::UnsupportedTableClass(tc));
        }
        if th > 3 {
            return Err(DecoderError::UnsupportedTableId(th));
        }

        let mut acc: usize = 0;
        for i in 0..16 {
            bits[th][i + 1] = input.get_u8() as u32;
            acc += bits[th][i + 1] as usize;
        }
        bits[th][0] = 0;

        if acc > 256 {
            return Err(DecoderError::InvalidTable);
        }

        if length < 1 + 16 + acc {
            return Err(DecoderError::InvalidTable);
        }

        for i in 0..acc {
            huffval[th][i] = input.get_u8() as u32;
        }

        init[th] = true;
        length -= 1 + 16 + acc;
    }

    Ok(())
}
#[allow(clippy::too_many_arguments)]
fn set_yuv_420(
    out: &mut [u16],
    row: usize,
    col: usize,
    width: usize,
    y1: i32,
    y2: i32,
    y3: i32,
    y4: i32,
    cb: i32,
    cr: i32,
) {
    let pix1 = row * width + col;
    let pix2 = pix1 + 3;
    let pix3 = (row + 1) * width + col;
    let pix4 = pix3 + 3;

    debug_assert!(!y1.is_negative());
    debug_assert!(!y2.is_negative());
    debug_assert!(!y3.is_negative());
    debug_assert!(!y4.is_negative());
    debug_assert!(!cb.is_negative());
    debug_assert!(!cr.is_negative());

    out[pix1] = y1 as u16;
    out[pix1 + 1] = cb as u16;
    out[pix1 + 2] = cr as u16;
    out[pix2] = y2 as u16;
    out[pix2 + 1] = cb as u16;
    out[pix2 + 2] = cr as u16;
    out[pix3] = y3 as u16;
    out[pix3 + 1] = cb as u16;
    out[pix3 + 2] = cr as u16;
    out[pix4] = y4 as u16;
    out[pix4 + 1] = cb as u16;
    out[pix4 + 2] = cr as u16;
}

#[allow(clippy::too_many_arguments)]
fn set_yuv_422(
    out: &mut [u16],
    row: usize,
    col: usize,
    width: usize,
    y1: i32,
    y2: i32,
    cb: i32,
    cr: i32,
) {
    let pix1 = row * width + col;
    let pix2 = pix1 + 3;

    debug_assert!(!y1.is_negative());
    debug_assert!(!y2.is_negative());
    debug_assert!(!cb.is_negative());
    debug_assert!(!cr.is_negative());

    out[pix1] = y1 as u16;
    out[pix1 + 1] = cb as u16;
    out[pix1 + 2] = cr as u16;
    out[pix2] = y2 as u16;
    out[pix2 + 1] = cb as u16;
    out[pix2 + 2] = cr as u16;
}

impl Display for DecoderError {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        match self {
            DecoderError::NoSoiStart => {
                write!(f, "image did not start with SOI. Probably not LJPEG")
            }
            DecoderError::InvalidPrecision(p) => {
                write!(f, "invalid bit bitdepth: {p}")
            }
            DecoderError::InvalidComponents(c) => {
                write!(f, "invalid number of components: {c}")
            }
            DecoderError::InvalidComponentSelector(c) => {
                write!(f, "invalid component selector: {c}")
            }
            DecoderError::InvalidTableSelector(c) => {
                write!(f, "invalid table selector: {c}")
            }
            DecoderError::EoiBeforeSos => {
                write!(f, "EOI marker found before SOS marker")
            }
            DecoderError::DqtFound => {
                write!(f, "DQT found")
            }
            DecoderError::ExpectedMarkerNotFound => {
                write!(f, "a marker was expected, but not found")
            }
            DecoderError::UnsupportedTableClass(c) => {
                write!(f, "table class not supported: {c}")
            }
            DecoderError::UnsupportedTableId(i) => {
                write!(f, "table id not supported: {i}")
            }
            DecoderError::UnsupportedPredictor(p) => {
                write!(f, "predictor not supported: {p}")
            }
            DecoderError::UnsupportedInterleave(h, v) => {
                write!(f, "interleave not supported, super_h: {h}, super_v: {v}")
            }
            DecoderError::InvalidTable => {
                write!(f, "invalid Huffman table")
            }
            DecoderError::SosBeforeSof => {
                write!(f, "SOS block found before SOF")
            }
            DecoderError::HeaderSizeMismatch => {
                write!(f, "SOF header size mismatch")
            }
            DecoderError::SosComponentMismatch => {
                write!(f, "number of components in SOS different than in SOF")
            }
            DecoderError::SmallBuffer => {
                write!(f, "the buffer provided for decoding is too small")
            }
        }
    }
}

impl Error for DecoderError {}
