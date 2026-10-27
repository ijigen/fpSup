//! Decoder regressions against the separately compiled, unmodified upstream crate.
#[test]
fn ljpeg_source_decoder_matches_upstream_across_entropy_and_predictors() {
    for bits in 2u8..=16 {
        for predictor in 1u8..=7 {
            for components in 1u8..=4 {
                for (width, height) in [(1u16, 1u16), (2, 2), (15, 3), (129, 17)] {
                    for pattern in 0..3 {
                        let mask = (1u32 << bits) - 1;
                        let samples: Vec<u16> =
                            (0..width as usize * height as usize * components as usize)
                                .map(|i| match pattern {
                                    0 => 0,
                                    1 => {
                                        if i & 1 == 0 {
                                            0
                                        } else {
                                            mask as u16
                                        }
                                    }
                                    _ => {
                                        ((i as u32).wrapping_mul(23417).wrapping_add(
                                            (i as u32).wrapping_mul(i as u32).wrapping_mul(11),
                                        ) & mask) as u16
                                    }
                                })
                                .collect();
                        // Upstream encodes legal camera-style entropy streams independently
                        // of our encoder and its Huffman table optimization.
                        let stream = ljpeg_reference::Encoder::new(
                            width,
                            height,
                            ljpeg_reference::Components::try_from(components).unwrap(),
                            ljpeg_reference::Bitdepth::try_from(bits).unwrap(),
                            ljpeg_reference::Predictor::try_from(predictor).unwrap(),
                            0,
                            0,
                        )
                        .encode(&samples)
                        .unwrap();
                        let reference = ljpeg_reference::Decoder::new(&stream)
                            .unwrap()
                            .decode()
                            .unwrap();
                        let decoder = ljpeg::Decoder::new(&stream).unwrap();
                        let decoded = decoder.decode().unwrap();
                        // Existing nonzero backing must be completely overwritten.
                        let mut reused = vec![0xffff; decoded.len() + 13];
                        decoder.decode_to_buffer(&mut reused, width as usize, height as usize).unwrap();
                        assert_eq!(&reused[..decoded.len()], &decoded);
                        assert!(reused[decoded.len()..].iter().all(|&v|v==0xffff));
                        assert_eq!(
                            decoded, reference,
                            "{bits}-bit P{predictor} C{components} {width}x{height} pattern {pattern}"
                        );
                        assert_eq!(decoded, samples);
                    }
                }
            }
        }
    }
}


#[test]
fn source_decoder_matches_upstream_with_point_transforms() {
    let mut cases = 0;
    for bits in 2u8..=16 {
        for point_transform in 1..bits {
            for predictor in 1u8..=7 {
                for components in 1u8..=4 {
                    let (width,height)=(17u16,5u16);
                    let mask=(1u32<<bits)-1;
                    let samples:Vec<u16>=(0..width as usize*height as usize*components as usize)
                        .map(|i|((i as u32).wrapping_mul(23417).wrapping_add((i*i) as u32*11)&mask) as u16)
                        .collect();
                    let stream=ljpeg_reference::Encoder::new(width,height,
                        ljpeg_reference::Components::try_from(components).unwrap(),
                        ljpeg_reference::Bitdepth::try_from(bits).unwrap(),
                        ljpeg_reference::Predictor::try_from(predictor).unwrap(),point_transform,0)
                        .encode(&samples).unwrap();
                    let reference=ljpeg_reference::Decoder::new(&stream).unwrap().decode().unwrap();
                    let decoder=ljpeg::Decoder::new(&stream).unwrap();
                    let actual=decoder.decode().unwrap();
                    assert_eq!(actual,reference,"{bits}-bit PT{point_transform} P{predictor} C{components}");
                    cases+=1;
                }
            }
        }
    }
    assert_eq!(cases,3360);
}

#[test]
fn source_decoder_matches_upstream_at_entropy_marker_boundaries() {
    for bits in [8u8,12,16] {
        for predictor in 1u8..=7 {
            for components in 1u8..=4 {
                let (width,height)=(17u16,9u16);
                let mask=(1u32<<bits)-1;
                let samples:Vec<u16>=(0..width as usize*height as usize*components as usize)
                    .map(|i|((i as u32).wrapping_mul(23417).wrapping_add((i*i) as u32*11)&mask) as u16)
                    .collect();
                let stream=ljpeg_reference::Encoder::new(width,height,
                    ljpeg_reference::Components::try_from(components).unwrap(),
                    ljpeg_reference::Bitdepth::try_from(bits).unwrap(),
                    ljpeg_reference::Predictor::try_from(predictor).unwrap(),0,0)
                    .encode(&samples).unwrap();
                let mut at=2;
                loop {
                    let marker=stream[at+1];
                    let length=u16::from_be_bytes([stream[at+2],stream[at+3]]) as usize;
                    at+=2+length;
                    if marker==218 {break;}
                }
                // Place an early EOI at each byte refill boundary. Upstream
                // panics on a final unpaired FF byte, so preserve byte stuffing
                // when inserting the marker rather than copying that defect.
                for entropy_bytes in [0,1,2,3,4,5,6,7,8,9,15,16,17,31,32,33] {
                    let mut truncated=stream[..(at+entropy_bytes).min(stream.len())].to_vec();
                    if truncated.last()==Some(&255) {truncated.push(0);}
                    truncated.extend_from_slice(&[255,217]);
                    let reference=ljpeg_reference::Decoder::new(&truncated).unwrap().decode().unwrap();
                    let actual=ljpeg::Decoder::new(&truncated).unwrap().decode().unwrap();
                    assert_eq!(actual,reference,"{bits}-bit P{predictor} C{components} prefix+{entropy_bytes}");
                }
            }
        }
    }
}
