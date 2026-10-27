use ljpeg::Decoder;

#[test]
fn decode_image() {
    let decoder = Decoder::new(include_bytes!("../tests/2comp.jpg")).unwrap();
    let output = decoder.decode().unwrap();
    let out: Vec<u8> = output
        .into_iter()
        .flat_map(|u| u.to_be_bytes().into_iter())
        .collect();
    let reference = include_bytes!("../tests/2comp.pgm");
    // 19 is the length of the PGM header in the reference file
    assert_eq!(out.len(), reference.len() - 19);
    for i in 0..out.len() {
        assert_eq!(out[i], reference[19 + i]);
    }
}
