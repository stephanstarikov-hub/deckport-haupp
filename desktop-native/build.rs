use std::{env, fs, path::PathBuf};

fn main() {
    let manifest =
        PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR is required"));
    let package = manifest.join("../package.json");
    let text = fs::read_to_string(&package).expect("package.json must be readable");
    let version = text
        .lines()
        .find_map(|line| {
            let line = line.trim();
            if line.starts_with("\"version\"") {
                line.split('"').nth(3)
            } else {
                None
            }
        })
        .filter(|value| {
            !value.is_empty()
                && value
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-' | b'+'))
        })
        .expect("package.json contains an invalid version");

    let cargo_version = env::var("CARGO_PKG_VERSION").expect("CARGO_PKG_VERSION is required");
    assert_eq!(
        version, cargo_version,
        "desktop-native/Cargo.toml and package.json versions must match"
    );

    println!("cargo:rerun-if-changed={}", package.display());
    println!("cargo:rustc-env=DECKPORT_VERSION={version}");
}
