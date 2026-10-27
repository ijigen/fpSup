pub(crate) trait BitPump {
    fn peek_bits(&mut self, num: u32) -> u32;
    fn consume_bits(&mut self, num: u32);

    #[inline]
    fn get_bits(&mut self, num: u32) -> u32 {
        if num == 0 {
            return 0;
        }

        let val = self.peek_bits(num);
        self.consume_bits(num);

        val
    }
}

#[derive(Debug, Copy, Clone)]
pub(crate) struct BitPumpMSB32<'a> {
    buffer: &'a [u8],
    pos: usize,
    bits: u64,
    nbits: u32,
}

impl BitPumpMSB32<'_> {
    pub(crate) fn new(src: &[u8]) -> BitPumpMSB32 {
        BitPumpMSB32 {
            buffer: src,
            pos: 0,
            bits: 0,
            nbits: 0,
        }
    }
}

impl BitPump for BitPumpMSB32<'_> {
    #[inline]
    fn peek_bits(&mut self, num: u32) -> u32 {
        if num > self.nbits {
            let inbits =
                u32::from_le_bytes(self.buffer[self.pos..self.pos + 4].try_into().unwrap()) as u64;
            self.bits = (self.bits << 32) | inbits;
            self.pos += 4;
            self.nbits += 32;
        }
        (self.bits >> (self.nbits - num)) as u32
    }

    #[inline]
    fn consume_bits(&mut self, num: u32) {
        self.nbits -= num;
        self.bits &= (1 << self.nbits) - 1;
    }
}

#[derive(Debug, Copy, Clone)]
pub(crate) struct BitPumpJPEG<'a> {
    buffer: &'a [u8],
    pos: usize,
    bits: u64,
    nbits: u32,
    finished: bool,
}

impl BitPumpJPEG<'_> {
    pub(crate) fn new(src: &[u8]) -> BitPumpJPEG {
        BitPumpJPEG {
            buffer: src,
            pos: 0,
            bits: 0,
            nbits: 0,
            finished: false,
        }
    }
}

impl BitPump for BitPumpJPEG<'_> {
    #[inline]
    fn peek_bits(&mut self, num: u32) -> u32 {
        if num == 0 { return 0; }
        if num > self.nbits && !self.finished {
            if self.nbits <= 16 && self.pos + 8 <= self.buffer.len() {
                let word = u64::from_be_bytes(self.buffer[self.pos..self.pos + 8].try_into().unwrap());
                let inverse = !word;
                let contains_ff = inverse.wrapping_sub(0x0101_0101_0101_0101) & !inverse & 0x8080_8080_8080_8080;
                if contains_ff == 0 {
                    self.bits |= (word & 0xffff_ffff_ffff_0000) >> self.nbits;
                    self.pos += 6;
                    self.nbits += 48;
                    return (self.bits >> (64 - num)) as u32;
                }
            }
            // Refill at most four bytes, preserving JPEG byte stuffing and marker stop.
            let mut read_bytes = 0;
            while read_bytes < 4 && !self.finished {
                let byte = if self.pos >= self.buffer.len() {
                    self.finished = true;
                    0
                } else {
                    let next = self.buffer[self.pos];
                    if next != 0xff { next }
                    else if self.buffer.get(self.pos + 1) == Some(&0) { self.pos += 1; next }
                    else { self.finished = true; 0 }
                };
                self.bits |= (byte as u64) << (56 - self.nbits);
                self.pos += 1;
                self.nbits += 8;
                read_bytes += 1;
            }
        }
        if num > self.nbits && self.finished { self.nbits += 32; }
        (self.bits >> (64 - num)) as u32
    }

    #[inline]
    fn consume_bits(&mut self, num: u32) {
        debug_assert!(num <= self.nbits);
        self.nbits -= num;
        self.bits <<= num;
    }
}

#[derive(Debug, Copy, Clone)]
pub(crate) struct ByteStream<'a> {
    buffer: &'a [u8],
    pos: usize,
}

impl ByteStream<'_> {
    #[inline]
    pub(crate) fn new(buffer: &[u8]) -> ByteStream {
        ByteStream { buffer, pos: 0 }
    }

    #[inline]
    pub(crate) fn get_pos(&self) -> usize {
        self.pos
    }

    #[inline]
    pub(crate) fn peek_u8(&self) -> u8 {
        self.buffer[self.pos]
    }
    #[inline]
    pub(crate) fn get_u8(&mut self) -> u8 {
        let val = self.peek_u8();
        self.pos += 1;
        val
    }

    #[inline]
    pub(crate) fn peek_u16(&self) -> u16 {
        u16::from_be_bytes(self.buffer[self.pos..self.pos + 2].try_into().unwrap())
    }
    #[inline]
    pub(crate) fn get_u16(&mut self) -> u16 {
        let val = self.peek_u16();
        self.pos += 2;
        val
    }

    #[inline]
    pub(crate) fn skip_to_marker(&mut self) -> Option<usize> {
        let mut skip_count = 0;
        while !(self.buffer[self.pos] == 0xFF
            && self.buffer[self.pos + 1] != 0
            && self.buffer[self.pos + 1] != 0xFF)
        {
            self.pos += 1;
            skip_count += 1;
            if self.pos >= self.buffer.len() {
                return None;
            }
        }
        self.pos += 1; // Make the next byte the marker
        Some(skip_count + 1)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use alloc::{vec, vec::Vec};

    #[test]
    fn jpeg_refill_matches_independent_stuffing_and_bit_reader() {
        let mut stuffed = Vec::new();
        for i in 0..4096u32 {
            let byte = i.wrapping_mul(73).wrapping_add(i >> 3) as u8;
            stuffed.push(byte);
            if byte == 255 {
                stuffed.push(0);
            }
        }
        let mut marker = stuffed.clone();
        marker.extend_from_slice(&[255, 217, 12, 34, 56]);
        let mut truncated = stuffed.clone();
        truncated.push(255);
        for encoded in [
            vec![],
            vec![255],
            vec![255, 0],
            vec![255, 217],
            vec![1, 2, 3, 4, 5, 6, 7],
            stuffed,
            marker,
            truncated,
        ] {
            // Decode byte stuffing independently, stopping at any JPEG marker.
            let mut entropy = Vec::new();
            let mut offset = 0;
            while offset < encoded.len() {
                let byte = encoded[offset];
                offset += 1;
                if byte == 255 {
                    if encoded.get(offset) != Some(&0) {
                        break;
                    }
                    offset += 1;
                }
                entropy.push(byte);
            }
            let mut pump = BitPumpJPEG::new(&encoded);
            let mut position = 0;
            for width in [1, 2, 7, 8, 12, 13, 15, 16, 24, 32]
                .into_iter()
                .cycle()
                .take(4000)
            {
                let mut expected = 0u32;
                for _ in 0..width {
                    let bit = entropy
                        .get(position / 8)
                        .map_or(0, |byte| (byte >> (7 - position % 8)) & 1);
                    expected = (expected << 1) | bit as u32;
                    position += 1;
                }
                assert_eq!(
                    pump.get_bits(width),
                    expected,
                    "{} encoded bytes, position {position}, width {width}",
                    encoded.len()
                );
            }
        }
    }
}
