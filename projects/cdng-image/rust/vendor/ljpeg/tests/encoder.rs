use ljpeg::*;

#[test]
fn encode_16x16_16bit_black_decode_single() {
    let h = 16;
    let w = 16;
    let c = 1;
    let input_image = vec![0x0000; w * h * c];
    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B16,
        Predictor::P1,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();
    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h * w];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    assert_eq!(outbuf[0], input_image[0]);
    assert_eq!(outbuf[1], input_image[1]);
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}

#[test]
fn encode_16x16_16bit_black_decode_2component() {
    let h = 2;
    let w = 2;
    let c = 2;
    let input_image = vec![0x0000; w * h * c];
    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C2,
        Bitdepth::B16,
        Predictor::P1,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();
    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; w * h * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    assert_eq!(outbuf[0], input_image[0]);
    assert_eq!(outbuf[1], input_image[1]);
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}

#[test]
fn encode_16x16_16bit_black() {
    let h = 16;
    let w = 16;
    let c = 1;
    let input_image = vec![0x0000; w * h * c];
    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B16,
        Predictor::P1,
        0,
        0,
    );
    enc.encode(&input_image).unwrap();
}

#[test]
fn encode_16x16_16bit_white() {
    let h = 16;
    let w = 16;
    let c = 1;
    let input_image = vec![0xffff; w * h * c];
    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B16,
        Predictor::P1,
        0,
        0,
    );
    enc.encode(&input_image).unwrap();
}

#[cfg(debug_assertions)]
#[test]
#[should_panic(expected = "Sample overflow, sample is 0xfffe but max value is 0x3fff")]
fn encode_16x16_bitdepth_error() {
    let h = 16;
    let w = 16;
    let c = 1;
    let input_image = vec![0xfffe; w * h * c];
    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B14,
        Predictor::P1,
        0,
        0,
    );
    let _ = enc.encode(&input_image).unwrap();
}

#[test]
fn encode_16x16_short_buffer_error() {
    let h = 16;
    let w = 16;
    let c = 1;
    let input_image = vec![0x9999_u16; (w * h * c) - 1];
    let result = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B16,
        Predictor::P1,
        0,
        0,
    )
    .encode(&input_image);
    assert!(result.is_none());
}

#[test]
fn encode_16x16_16bit_incr() {
    let h = 16;
    let w = 16;
    let c = 2;
    let mut input_image = vec![0; h * w * c];
    for i in 0..input_image.len() {
        input_image[i] = i as u16;
    }

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C2,
        Bitdepth::B16,
        Predictor::P1,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();
    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    //debug!("input: {:?}", input_image);
    //debug!("output: {:?}", outbuf);
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}

#[test]
fn encode_all_differences() {
    // This simulates an input where every 17 SSSS classes are used because each difference
    // value exists (see ITU-T81 H.1.2.2 Table H.2, p. 138).
    let input_image = vec![
        0, 0, 1, 0, 2, 0, 4, 0, 8, 0, 16, 0, 32, 0, 64, 0, 128, 0, 256, 0, 512, 0, 1024, 0, 2048,
        0, 4096, 0, 8192, 0, 16384, 0, 32768,
    ];
    let h = 1;
    let w = input_image.len();
    let c = 1;

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B16,
        Predictor::P1,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();
    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}

#[test]
fn encode_ssss_16() {
    // This simulates an input where every 17 SSSS classes are used because each difference
    // value exists (see ITU-T81 H.1.2.2 Table H.2, p. 138).
    //let input_image = vec![0, 0, 0, 32768, 0, 0];
    let input_image = vec![0, 0, 0, 32768];
    let h = 1;
    let w = input_image.len();
    let c = 1;

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B16,
        Predictor::P1,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();
    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w as usize, h as usize)
        .unwrap();
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}

#[test]
fn encode_difference_above_32768() {
    // Test values larger than i16::MAX
    let input_image = vec![
        0,
        0,
        0,
        32768 + 1,
        0,
        0,
        0,
        u16::MAX,
        u16::MAX,
        1,
        u16::MAX,
        1,
        0,
    ];
    let h = 1;
    let w = input_image.len();
    let c = 1;

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B16,
        Predictor::P1,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();
    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    //debug!("{:?}", outbuf);
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}

#[test]
fn encode_predictor2_1comp() {
    let input_image = vec![0, 0, u16::MAX, 0, 0, 0, u16::MAX - 5, 0];
    let h = 2;
    let w = 4;
    let c = 1;

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B16,
        Predictor::P2,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();

    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    //debug!("{:?}", outbuf);
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}

#[test]
fn encode_predictor1_2comp_padding() {
    let input_image = vec![1, 2, 5, 6, 3, 7, 0, 0, 7, 8, 3, 4, 6, 2, 0, 0];
    let expected_image = [1, 2, 5, 6, 3, 7, 7, 8, 3, 4, 6, 2];
    let h = 2;
    let w = 3;
    let c = 2;
    let padding = 1;

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C2,
        Bitdepth::B16,
        Predictor::P3,
        0,
        padding,
    );
    let jpeg = enc.encode(&input_image).unwrap();

    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    //debug!("{:?}", outbuf);
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], expected_image[i]);
    }
}

#[test]
fn encode_predictor3_1comp() {
    let input_image = vec![0, u16::MAX, 0, 0, 0, 0, u16::MAX - 5, 0];
    let h = 2;
    let w = 4;
    let c = 1;

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B16,
        Predictor::P3,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();

    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    //debug!("{:?}", outbuf);
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}

#[test]
fn encode_predictor4_1comp() {
    let input_image = vec![0, 0, u16::MAX, 0, 0, u16::MAX, 0, 0];
    let h = 2;
    let w = 4;
    let c = 1;

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B16,
        Predictor::P4,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();

    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    //debug!("{:?}", outbuf);
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}

#[test]
fn encode_predictor5_1comp() {
    let input_image = vec![0, u16::MAX, u16::MAX, 0, 0, u16::MAX, 0, 0];
    let h = 2;
    let w = 4;
    let c = 1;

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B16,
        Predictor::P5,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();

    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    //debug!("{:?}", outbuf);
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}

#[test]
fn encode_predictor6_1comp() {
    let input_image = vec![0, u16::MAX, u16::MAX, 0, 0, u16::MAX, 0, 0];
    let h = 2;
    let w = 4;
    let c = 1;

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B16,
        Predictor::P6,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();

    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    //debug!("{:?}", outbuf);
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}

#[test]
fn encode_predictor6_3comp() {
    let input_image = vec![56543, 45, 65000, 0, 0, 35632];
    let h = 2;
    let w = 1;
    let c = 3;

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C3,
        Bitdepth::B16,
        Predictor::P6,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();

    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    //debug!("{:?}", outbuf);
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}

#[test]
fn encode_predictor6_3comp_ssss16() {
    let input_image = vec![
        0, 0, 0, 0, 0, 0, 0, 0, 0, 32768, 32768, 32768, 0, 0, 0, 0, 0, 0,
    ];
    let h = 3;
    let w = 2;
    let c = 3;

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C3,
        Bitdepth::B16,
        Predictor::P6,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();

    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    //debug!("{:?}", outbuf);
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}

#[test]
fn encode_predictor7_1comp() {
    let input_image = vec![0, 0, u16::MAX, 0, 0, u16::MAX, 0, 0];
    let h = 2;
    let w = 4;
    let c = 1;

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B16,
        Predictor::P7,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();

    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    //debug!("{:?}", outbuf);
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}

#[test]
fn encode_predictor1_ljpeg_width_larger_than_output() {
    let input_image = vec![
        100, 105, 200, 207, 50, 48, 34, 45, 50, 45, 23, 100, 34, 76, 23, 99,
    ];
    let expected_output = vec![100, 105, 200, 207, 50, 45, 23, 100];
    let h = 2;
    let w = 4;
    let c = 2;

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C2,
        Bitdepth::B16,
        Predictor::P1,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();

    let w = w / 2; // we only want the first part of the image
    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    //debug!("{:?}", outbuf);
    assert_eq!(outbuf, expected_output);
}

#[test]
fn encode_predictor4_trigger_minus1_prediction() {
    let input_image = vec![0, 0, 5, 2, 0, 0, 0, 0, 2, 9, 0, 0];
    let h = 2;
    let w = 6;
    let c = 1;

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B16,
        Predictor::P4,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();

    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    //debug!("{:?}", outbuf);
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}

#[test]
fn encode_predictor5_trigger_minus1_prediction() {
    let input_image = vec![0, 0, 2, 1, 0, 0, 1, 9];
    let h = 2;
    let w = 4;
    let c = 1;

    let enc = Encoder::new(
        w as u16,
        h as u16,
        Components::C1,
        Bitdepth::B16,
        Predictor::P5,
        0,
        0,
    );
    let jpeg = enc.encode(&input_image).unwrap();

    let dec = Decoder::new(&jpeg).unwrap();
    let mut outbuf = vec![0; h as usize * w as usize * c];
    dec.decode_to_buffer(&mut outbuf, w, h).unwrap();
    //debug!("{:?}", outbuf);
    for i in 0..outbuf.len() {
        assert_eq!(outbuf[i], input_image[i]);
    }
}
