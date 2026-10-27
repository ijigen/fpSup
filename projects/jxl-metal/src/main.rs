//! jxl-metal a.jxl ... : decode on the GPU, timing and checks against a.pgm
//! jxl-metal encode in.pgm out.jxl | encode OUTDIR a.pgm ... : encode on the GPU
fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("encode") {
        return jxl_metal::encode::run(&args[1..]);
    }
    anyhow::ensure!(!args.is_empty(), "usage: jxl-metal <a.jxl> [b.jxl ...] | encode ...");
    jxl_metal::decode::cli(&args)
}
