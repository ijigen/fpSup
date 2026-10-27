use crate::pumps::BitPump;

use alloc::{vec, vec::Vec};

const DECODE_CACHE_BITS: u32 = 13;

#[derive(Debug)]
pub(crate) struct HuffTable {
    // These two fields directly represent the contents of a JPEG DHT marker
    bits: [u32; 17],
    huffval: [u32; 256],

    // The max number of bits in a huffman code and the table that converts those
    // bits into how many bits to consume and the decoded length and shift
    nbits: u32,
    hufftable: Vec<(u8, u8)>,

    // A pregenerated table that goes straight to decoding a diff without first
    // finding a length, fetching bits, and sign extending them. The table is
    // sized by DECODE_CACHE_BITS and can have 99%+ hit rate with 13 bits.
    // Zero means a miss; otherwise low 8 bits are consumed bits and the next
    // 16 bits hold the signed difference. Four-byte entries keep the hot table
    // one third smaller than Option<(u8, i16)> without reducing lookup precision.
    decodecache: Vec<u32>,
}

#[cfg(test)]
struct MockPump {
    bits: u64,
    nbits: u32,
}

#[cfg(test)]
impl MockPump {
    pub fn empty() -> Self {
        MockPump { bits: 0, nbits: 0 }
    }

    pub fn set(&mut self, bits: u32, nbits: u32) {
        self.bits = (bits as u64) << 32;
        self.nbits = nbits + 32;
    }

    pub fn validbits(&self) -> i32 {
        self.nbits as i32 - 32
    }
}

#[cfg(test)]
impl BitPump for MockPump {
    fn peek_bits(&mut self, num: u32) -> u32 {
        (self.bits >> (self.nbits - num)) as u32
    }

    fn consume_bits(&mut self, num: u32) {
        self.nbits -= num;
        self.bits &= (1 << self.nbits) - 1;
    }
}

impl HuffTable {
    pub(crate) const fn empty() -> HuffTable {
        HuffTable {
            bits: [0; 17],
            huffval: [0; 256],

            nbits: 0,
            hufftable: Vec::new(),
            decodecache: Vec::new(),
        }
    }

    pub(crate) fn new(bits: [u32; 17], huffval: [u32; 256]) -> HuffTable {
        let mut tbl = HuffTable {
            bits,
            huffval,

            nbits: 0,
            hufftable: Vec::new(),
            decodecache: Vec::new(),
        };
        tbl.initialize();
        tbl
    }

    pub(crate) fn initialize(&mut self) {
        // Find out the max code length and allocate a table with that size
        self.nbits = 16;
        for i in 0..16 {
            if self.bits[16 - i] != 0 {
                break;
            }
            self.nbits -= 1;
        }
        self.hufftable = vec![(0, 0); 1 << self.nbits];

        // Fill in the table itself
        let mut h = 0;
        let mut pos = 0;
        for len in 0..self.nbits {
            for _ in 0..self.bits[len as usize + 1] {
                for _ in 0..(1 << (self.nbits - len - 1)) {
                    self.hufftable[h] = (len as u8 + 1, self.huffval[pos] as u8);
                    h += 1;
                }
                pos += 1;
            }
        }

        self.decodecache.resize(1 << DECODE_CACHE_BITS, 0);

        // Populate complete Huffman + residual prefixes directly. This is the
        // same table as decoding all 8192 possible inputs, without constructing
        // and advancing a temporary bit pump for every entry of every tile.
        let mut code = 0usize;
        let mut symbol = 0usize;
        for bits in 1..=self.nbits {
            for _ in 0..self.bits[bits as usize] {
                let length = self.huffval[symbol];
                let residual_bits = if length == 16 { 0 } else { length };
                let consumed = bits + residual_bits;
                if consumed <= DECODE_CACHE_BITS {
                    let repetitions = 1usize << (DECODE_CACHE_BITS - consumed);
                    for residual in 0..(1u32 << residual_bits) {
                        let diff = if length == 0 {
                            0
                        } else if length == 16 {
                            -32768
                        } else if residual & (1 << (length - 1)) == 0 {
                            residual as i32 - ((1 << length) - 1)
                        } else {
                            residual as i32
                        };
                        let prefix = (code << (DECODE_CACHE_BITS - bits))
                            | ((residual as usize) << (DECODE_CACHE_BITS - consumed));
                        let packed = ((diff as u16 as u32) << 8) | consumed;
                        self.decodecache[prefix..prefix + repetitions].fill(packed);
                    }
                }
                code += 1;
                symbol += 1;
            }
            code <<= 1;
        }
    }

    // Fuse two consecutive component differences when both complete codes fit
    // in the existing 13-bit lookahead. Zero entries retain the scalar fallback.
    pub(crate) fn pair_cache(&self, next: &Self) -> Vec<u64> {
        if self.decodecache.is_empty() || next.decodecache.is_empty() { return Vec::new(); }
        let mut result = vec![0; 1 << DECODE_CACHE_BITS];
        for (prefix, result) in result.iter_mut().enumerate() {
            let a = self.decodecache[prefix];
            if a == 0 { continue; }
            let used = a & 255;
            let nextcode = (prefix << used) & ((1 << DECODE_CACHE_BITS) - 1);
            let b = next.decodecache[nextcode];
            if b == 0 || used + (b & 255) > DECODE_CACHE_BITS { continue; }
            *result = u64::from(used + (b & 255)) | (u64::from((a >> 8) & 65535) << 8) | (u64::from((b >> 8) & 65535) << 24);
        }
        result
    }
    #[inline]
    pub(crate) fn huff_decode_pair(&self, next: &Self, cache: &[u64], pump: &mut impl BitPump) -> (i32, i32) {
        let prefix = pump.peek_bits(DECODE_CACHE_BITS) as usize;
        let pair = cache.get(prefix).copied().unwrap_or(0);
        if pair != 0 {
            pump.consume_bits((pair & 255) as u32);
            (((pair >> 8) as u16 as i16) as i32, ((pair >> 24) as u16 as i16) as i32)
        } else { (self.huff_decode(pump), next.huff_decode(pump)) }
    }

    #[inline]
    pub(crate) fn huff_decode(&self, pump: &mut impl BitPump) -> i32 {
        let code = pump.peek_bits(DECODE_CACHE_BITS) as usize;
        let cached = self.decodecache[code];
        if cached != 0 {
            pump.consume_bits(cached & 255);
            ((cached << 8) as i32) >> 16
        } else {
            let decode = self.huff_decode_slow(pump);
            decode.1
        }
    }

    #[inline]
    pub(crate) fn huff_decode_slow(&self, pump: &mut impl BitPump) -> (u8, i32) {
        let len = self.huff_len(pump);
        (len.0 + len.1, self.huff_diff(pump, len))
    }

    #[inline]
    pub(crate) fn huff_len(&self, pump: &mut impl BitPump) -> (u8, u8) {
        let code = pump.peek_bits(self.nbits) as usize;
        let (bits, len) = self.hufftable[code];
        pump.consume_bits(bits as u32);
        (bits, len)
    }

    #[inline]
    pub(crate) fn huff_diff(&self, pump: &mut impl BitPump, input: (u8, u8)) -> i32 {
        let (_, len) = input;

        match len {
            0 => 0,
            16 => -32768,
            len => {
                // decode the difference and extend sign bit
                let mut diff = pump.get_bits(len as u32) as i32;
                if (diff & (1 << (len - 1))) == 0 {
                    diff -= (1 << len) - 1;
                }
                diff
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn packed_cache_matches_bitwise_decode_for_every_prefix() {
        // A balanced table, a short category-16 escape, and the longest legal
        // codes exercise sign extension, zero residuals and cache misses.
        for distribution in 0..3 {
            let mut bits = [0; 17];
            let mut symbols = [0; 256];
            match distribution {
                0 => {
                    bits[5] = 17;
                    for (i, symbol) in symbols[..17].iter_mut().enumerate() {
                        *symbol = i as u32;
                    }
                }
                1 => {
                    bits[1] = 1;
                    bits[5] = 16;
                    symbols[0] = 16;
                    for i in 0..16 {
                        symbols[i + 1] = i as u32;
                    }
                }
                _ => {
                    bits[1..16].fill(1);
                    bits[16] = 2;
                    for (i, symbol) in symbols[..17].iter_mut().enumerate() {
                        *symbol = i as u32;
                    }
                }
            }
            let table = HuffTable::new(bits, symbols);
            for prefix in 0..(1 << DECODE_CACHE_BITS) {
                let mut pump = MockPump::empty();
                pump.set(prefix, DECODE_CACHE_BITS);
                let (_, diff) = table.huff_decode_slow(&mut pump);
                let available = pump.validbits();
                let expected = if available >= 0 {
                    ((diff as u16 as u32) << 8) | (DECODE_CACHE_BITS - available as u32)
                } else {
                    0
                };
                assert_eq!(
                    table.decodecache[prefix as usize], expected,
                    "distribution {distribution}, prefix {prefix:013b}"
                );
            }
        }
    }
    #[test]
    fn joint_cache_and_fallback_match_independent_slow_decode() {
        let make = |distribution: usize| {
            let mut bits = [0; 17];
            let mut symbols = [0; 256];
            match distribution {
                0 => { bits[5] = 17; for (i,s) in symbols[..17].iter_mut().enumerate() { *s = i as u32; } }
                1 => { bits[1] = 1; bits[5] = 16; symbols[0] = 16; for i in 0..16 { symbols[i+1] = i as u32; } }
                _ => { bits[1..16].fill(1); bits[16] = 2; for (i,s) in symbols[..17].iter_mut().enumerate() { *s = i as u32; } }
            }
            HuffTable::new(bits, symbols)
        };
        assert!(HuffTable::empty().pair_cache(&make(0)).is_empty());
        assert!(make(0).pair_cache(&HuffTable::empty()).is_empty());
        let mut hits = 0;
        let mut misses = 0;
        for a in 0..3 { for b in 0..3 {
            let first = make(a); let second = make(b);
            let cache = first.pair_cache(&second);
            for prefix in 0..(1 << DECODE_CACHE_BITS) {
                let mut slow = MockPump::empty(); slow.set(prefix << (32-DECODE_CACHE_BITS), 32);
                let begin = slow.nbits;
                let x = first.huff_decode_slow(&mut slow).1;
                let first_consumed = begin - slow.nbits;
                let y = second.huff_decode_slow(&mut slow).1;
                let consumed = begin - slow.nbits;
                let second_consumed = consumed - first_consumed;
                // Unused invalid code prefixes have zero consumed bits in the
                // existing slow table; they remain on the original fallback.
                let expected = if first_consumed > 0 && second_consumed > 0 && consumed <= DECODE_CACHE_BITS {
                    consumed as u64 | ((x as u16 as u64) << 8) | ((y as u16 as u64) << 24)
                } else { 0 };
                assert_eq!(cache[prefix as usize], expected, "tables {a}/{b}, prefix {prefix}");
                let mut fast = MockPump::empty(); fast.set(prefix << (32-DECODE_CACHE_BITS), 32);
                assert_eq!(first.huff_decode_pair(&second, &cache, &mut fast), (x,y));
                assert_eq!(fast.nbits, slow.nbits);
                // Empty joint tables preserve the pre-existing scalar path.
                let mut fallback = MockPump::empty(); fallback.set(prefix << (32-DECODE_CACHE_BITS), 32);
                assert_eq!(first.huff_decode_pair(&second, &[], &mut fallback), (x,y));
                assert_eq!(fallback.nbits, slow.nbits);
                if expected != 0 { hits += 1; } else { misses += 1; }
            }
        } }
        assert!(hits > 0 && misses > 0);
    }

}
