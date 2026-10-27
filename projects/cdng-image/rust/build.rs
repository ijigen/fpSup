fn main() {
    let os = std::env::var("CARGO_CFG_TARGET_OS").unwrap();
    let native = "../cdng_image/native";
    println!("cargo:rerun-if-changed={native}");
    cc::Build::new()
        .cpp(true)
        .file(format!("{native}/jxl_bridge.cpp"))
        .include("vendor/libjxl-headers")
        .flag_if_supported("-std=c++17")
        .compile("cdng_jxl");
    println!("cargo:rerun-if-changed=vendor/libjxl-headers");
    if os == "macos" {
        cc::Build::new()
            .cpp(true)
            .file(format!("{native}/metal_backend.mm"))
            .flag("-std=c++17")
            .flag("-fobjc-arc")
            .compile("cdng_metal");
        println!("cargo:rustc-link-lib=framework=Metal");
        println!("cargo:rustc-link-lib=framework=Foundation");
    } else if std::env::var_os("CARGO_FEATURE_CUDA").is_some() {
        cc::Build::new()
            .cuda(true)
            .cudart("static")
            .file(format!("{native}/cuda_backend.cu"))
            .flag("-std=c++17")
            .flag("-gencode")
            .flag("arch=compute_75,code=[sm_75,compute_75]")
            .compile("cdng_cuda");
    }
}
